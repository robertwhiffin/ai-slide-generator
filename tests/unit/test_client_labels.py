"""Every client Tellr builds says it is Tellr: no bare WorkspaceClient, no bare MCP client.

Two kinds of test:

- **Guards** scan ``src/`` for an SDK ``WorkspaceClient`` or ``Config`` built without a
  label, and ``mcp_transport.py`` for an ``httpx`` client opened without Tellr's headers
  (``httpx.AsyncClient`` or ``from httpx import AsyncClient``, aliases included).  Each
  guard has its own test showing that it flags the bare form.
- **Wire tests** build the real client at each site and read what it sends, on a mock
  transport, so nothing leaves the machine: ``requests``' adapter under the SDK, and
  ``httpx``'s transport under the MCP client.  The user signs in through the real
  ``_create_user_client`` (its ``/Me`` answered by the mock), which is how a site learns
  the user's label in production.  A site that runs in a worker thread is driven in one,
  with another user's request bound to the calling thread, so only the token can name
  the user.

The golden hashes are pinned in ``test_attribution.py``: ``john.doe`` is ``30f69670bba2``
and ``test.user`` is ``07460583da32``.
"""

from __future__ import annotations

import ast
import asyncio
import json
import threading
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import databricks.sdk
import databricks_mcp
import httpx
import pytest
import requests
from databricks.sdk.config import Config
from requests.adapters import HTTPAdapter

from src.core import attribution
from src.services.agent_tools import mcp_transport
from tests.unit.test_attribution import _request_user

SRC = Path(__file__).resolve().parents[2] / "src"

HOST = "https://unit.invalid"
VERSION = "9.9.9"
ME_PATH = "/api/2.0/preview/scim/v2/Me"

#: The user who owns the token, and the label ``_create_user_client`` computes for them.
TOKEN_USER = "john.doe@example.com"
TOKEN_USER_PRODUCT = "tellr-app-30f69670bba2"
#: Another user, bound to the calling thread's request: no site may take this label.
OTHER_REQUEST_USER = "test.user@company.com"
OTHER_REQUEST_USER_PRODUCT = "tellr-app-07460583da32"


# ---------------------------------------------------------------------------
# Guards: source scans of src/
# ---------------------------------------------------------------------------


#: The functions whose ``**`` spread labels a client: ``**user_product_kwargs(token)``.
_LABEL_HELPERS = frozenset({"user_product_kwargs", "system_product_kwargs"})


def _import_bindings(tree: ast.AST) -> dict[str, set[str]]:
    """Each name the file's imports bind, in any scope -> the dotted paths it stands for.

    ``import databricks.sdk.config as sdk_config`` binds ``sdk_config`` to
    ``databricks.sdk.config``, ``from databricks.sdk import core`` binds ``core`` to
    ``databricks.sdk.core``, and ``import databricks.sdk`` binds ``databricks`` to itself.
    """
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                bindings.setdefault(name, set()).add(alias.name if alias.asname else name)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bound = alias.asname or alias.name
                bindings.setdefault(bound, set()).add(f"{node.module}.{alias.name}")
    return bindings


def _called_paths(func: ast.expr, bindings: dict[str, set[str]]) -> set[str]:
    """The dotted paths a callee may stand for, through the file's imports:
    ``sdk_config.Config`` -> ``{"databricks.sdk.config.Config"}``.  Empty unless the callee
    is a name, or a chain of attributes on one."""
    attributes = []
    while isinstance(func, ast.Attribute):
        attributes.append(func.attr)
        func = func.value
    if not isinstance(func, ast.Name):
        return set()
    tail = "".join(f".{attribute}" for attribute in reversed(attributes))
    return {root + tail for root in bindings.get(func.id, set()) | {func.id}}


def _callee_name(func: ast.expr) -> str | None:
    """``f`` for a callee ``f`` or ``module.f``; ``None`` for any other callee."""
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _sdk_calls(source: str, cls: str) -> list[ast.Call]:
    """Calls that build the SDK's ``cls``: by its name, by an ``import ... as`` alias of it,
    or as an attribute reached from the SDK (``databricks.sdk.config.Config``, or through a
    module alias: ``sdk_config.Config``, ``core.Config``).  ``WorkspaceClient`` is the SDK's
    name alone, so every call by that name counts (a lazy import inside a function binds it
    too); ``Config`` is a common name, so only one reached from ``databricks.sdk`` counts."""
    tree = ast.parse(source)
    bindings = _import_bindings(tree)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        from_sdk = any(
            path.startswith("databricks.sdk.") and path.endswith(f".{cls}")
            for path in _called_paths(node.func, bindings)
        )
        by_name = cls == "WorkspaceClient" and _callee_name(node.func) == cls
        if from_sdk or by_name:
            calls.append(node)
    return sorted(calls, key=lambda call: call.lineno)


def _blank_literal(node: ast.expr) -> bool:
    """``None``, ``""`` or any other literal that is not a product name."""
    return isinstance(node, ast.Constant) and not (isinstance(node.value, str) and node.value)


def _labelled(call: ast.Call, *, config_counts: bool) -> bool:
    """A ``**`` spread of a call to ``user_product_kwargs`` or ``system_product_kwargs``, a
    ``product=`` that is not a blank literal, or, when ``config_counts``, ``config=`` (that
    ``Config`` is held to the label itself).  Any other spread (``**kwargs``) labels nothing."""
    for keyword in call.keywords:
        if keyword.arg is None:
            spread = keyword.value
            if isinstance(spread, ast.Call) and _callee_name(spread.func) in _LABEL_HELPERS:
                return True
        elif keyword.arg == "product" and not _blank_literal(keyword.value):
            return True
        elif keyword.arg == "config" and config_counts:
            return True
    return False


def _bare_workspace_clients(source: str) -> list[int]:
    """Lines that build a ``WorkspaceClient`` with no label (see ``_labelled``)."""
    return [
        call.lineno
        for call in _sdk_calls(source, "WorkspaceClient")
        if not _labelled(call, config_counts=True)
    ]


def _bare_sdk_configs(source: str) -> list[int]:
    """Lines that build the SDK's ``Config`` with no label: ``config=`` does not count."""
    return [
        call.lineno
        for call in _sdk_calls(source, "Config")
        if not _labelled(call, config_counts=False)
    ]


def _scan_src(scan: Callable[[str], list[int]]) -> dict[str, list[int]]:
    return {
        path.relative_to(SRC).as_posix(): lines
        for path in sorted(SRC.rglob("*.py"))
        if (lines := scan(path.read_text()))
    }


def test_guard_flags_a_bare_client_and_accepts_the_labelled_forms():
    source = (
        "from databricks.sdk import WorkspaceClient as SdkClient\n"
        "import databricks.sdk\n"
        "a = WorkspaceClient(host=h, token=t)\n"
        "b = WorkspaceClient(host=h, token=t, product='tellr-app-system')\n"
        "c = WorkspaceClient(config=cfg)\n"
        "d = WorkspaceClient(host=h, **user_product_kwargs(t))\n"
        "# e = WorkspaceClient()\n"
        "f = databricks.sdk.WorkspaceClient(host=h)\n"
        "g = SdkClient(host=h, token=t)\n"
        "h = SdkClient(host=h, token=t, **system_product_kwargs())\n"
        "i = WorkspaceClient()\n"
        "j = WorkspaceClient(host=h, product_version=v)\n"
        "k = WorkspaceClient(host=h, **kwargs)\n"
        "l = WorkspaceClient(host=h, **other_kwargs(t))\n"
        "m = WorkspaceClient(host=h, **system_product_kwargs)\n"
        "n = WorkspaceClient(host=h, product=None)\n"
        "o = WorkspaceClient(host=h, product='')\n"
        "p = WorkspaceClient(host=h, **attribution.user_product_kwargs(t))\n"
        "q = WorkspaceClient(host=h, product=PRODUCT_NAME_SYSTEM)\n"
    )
    assert _bare_workspace_clients(source) == [3, 8, 9, 11, 12, 13, 14, 15, 16, 17]


def test_config_guard_flags_a_bare_sdk_config_and_only_the_sdks():
    source = (
        "from databricks.sdk.config import Config\n"
        "from databricks.sdk.core import Config as CoreConfig\n"
        "import databricks.sdk.config\n"
        "import databricks.sdk.config as sdk_config\n"
        "from databricks.sdk import core\n"
        "from databricks.sdk import config as sdk_conf\n"
        "import databricks.sdk as sdk\n"
        "a = Config(host=h, token=t)\n"
        "b = Config(host=h, token=t, **user_product_kwargs(t))\n"
        "c = Config(host=h, product='tellr-app-system', product_version=v)\n"
        "d = CoreConfig(host=h)\n"
        "e = databricks.sdk.config.Config(host=h)\n"
        "f = pydantic_settings.Config(x=1)\n"
        "g = sdk_config.Config(host=h)\n"
        "h = core.Config(host=h)\n"
        "i = sdk_conf.Config(host=h)\n"
        "j = sdk.config.Config(host=h)\n"
        "k = sdk_config.Config(host=h, **user_product_kwargs(t))\n"
        "l = Config(host=h, **kwargs)\n"
        "m = Config(host=h, product=None)\n"
    )
    assert _bare_sdk_configs(source) == [8, 11, 12, 14, 15, 16, 17, 19, 20]
    assert _bare_sdk_configs("from app.settings import Config\nc = Config(x=1)\n") == []
    assert _bare_sdk_configs("from app import settings\nc = settings.Config(x=1)\n") == []


def test_no_workspace_client_in_src_is_bare():
    assert _scan_src(_bare_workspace_clients) == {}


def test_a_config_built_for_a_client_carries_the_label():
    """``WorkspaceClient(config=...)`` passes the guard above, so the SDK ``Config`` it is
    built from must carry the label itself.  Agent-mode Genie builds one."""
    built = _scan_src(lambda source: [call.lineno for call in _sdk_calls(source, "Config")])
    assert "services/agent_tools/genie_agent.py" in built, "no Config found: the scan is vacuous"
    assert _scan_src(_bare_sdk_configs) == {}


#: The ``httpx`` clients an MCP transport may open.
_HTTPX_CLIENTS = frozenset({"httpx.AsyncClient", "httpx.Client"})


def _httpx_clients(source: str) -> list[ast.Call]:
    """Calls that open an ``httpx`` client, through the file's imports: ``httpx.AsyncClient``,
    the same through an ``import httpx as ...`` alias, or ``from httpx import AsyncClient``
    (aliased or not).  A class of that name imported from anywhere else is not one."""
    tree = ast.parse(source)
    bindings = _import_bindings(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _called_paths(node.func, bindings) & _HTTPX_CLIENTS
    ]
    return sorted(calls, key=lambda call: call.lineno)


def _mcp_clients_without_headers(source: str) -> list[int]:
    """Lines that open an ``httpx`` client without ``headers=mcp_http_headers()``."""
    return [
        call.lineno
        for call in _httpx_clients(source)
        if not any(
            keyword.arg == "headers" and ast.unparse(keyword.value) == "mcp_http_headers()"
            for keyword in call.keywords
        )
    ]


def test_mcp_headers_guard_flags_a_bare_client_and_accepts_tellrs_headers():
    source = (
        "import httpx\n"
        "import httpx as hx\n"
        "from httpx import AsyncClient\n"
        "from httpx import AsyncClient as OpenedClient\n"
        "a = httpx.AsyncClient(auth=a)\n"
        "b = httpx.AsyncClient(auth=a, headers=mcp_http_headers())\n"
        "c = AsyncClient(auth=a)\n"
        "d = AsyncClient(auth=a, headers=mcp_http_headers())\n"
        "e = hx.AsyncClient(auth=a)\n"
        "f = OpenedClient(auth=a)\n"
        "g = httpx.Client(auth=a)\n"
        "h = httpx.AsyncClient(auth=a, headers={'User-Agent': 'x'})\n"
        "i = httpx.AsyncClient(auth=a, **kwargs)\n"
        "# j = httpx.AsyncClient(auth=a)\n"
        "k = httpx.Timeout(30)\n"
    )
    assert _mcp_clients_without_headers(source) == [5, 7, 9, 10, 11, 12, 13]
    other_library = "from aiohttp import AsyncClient\nc = AsyncClient()\n"
    assert _mcp_clients_without_headers(other_library) == []


def test_mcp_transport_opens_its_http_client_with_those_headers():
    source = (SRC / "services/agent_tools/mcp_transport.py").read_text()
    assert _httpx_clients(source), "no httpx client found: the scan is vacuous"
    assert _mcp_clients_without_headers(source) == []


# ---------------------------------------------------------------------------
# The mock transports
# ---------------------------------------------------------------------------


@pytest.fixture
def installed_version(monkeypatch: pytest.MonkeyPatch) -> str:
    """The installed app wheel reports ``9.9.9``; every other distribution answers as installed."""
    real_version = metadata.version

    def _version(name: str) -> str:
        return VERSION if name == attribution.APP_PACKAGE else real_version(name)

    monkeypatch.setattr(attribution.metadata, "version", _version)
    return VERSION


class _SdkWire:
    """The network under the SDK: keeps every request and answers it from ``bodies``
    (URL path -> JSON body), or with a 404 for a path it has no body for."""

    def __init__(self) -> None:
        self.sent: list[requests.PreparedRequest] = []
        self.bodies: dict[str, Any] = {}

    def send(self, request: requests.PreparedRequest) -> requests.Response:
        self.sent.append(request)
        path = urlparse(request.url).path
        found = path in self.bodies
        body = self.bodies[path] if found else {"error_code": "NOT_FOUND", "message": path}
        response = requests.Response()
        response.status_code = 200 if found else 404
        response.reason = "OK" if found else "Not Found"
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    def sent_to(self, path: str) -> list[requests.PreparedRequest]:
        return [request for request in self.sent if urlparse(request.url).path == path]


@pytest.fixture
def sdk_wire(monkeypatch: pytest.MonkeyPatch) -> _SdkWire:
    """Real SDK clients with nothing leaving the machine (see ``_SdkWire``).

    Host discovery is the one network step in building a PAT client; it is turned off as
    ``test_model_endpoint_catalog.py`` does.  The operator's Databricks settings are
    cleared from the environment, so each client is built from what the code passes it.
    """
    wire = _SdkWire()
    for name in (
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_AUTH_TYPE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Config, "_resolve_host_metadata", lambda self: None)
    monkeypatch.setattr(HTTPAdapter, "send", lambda adapter, request, **kwargs: wire.send(request))
    return wire


def _sign_in(
    sdk_wire: _SdkWire, monkeypatch: pytest.MonkeyPatch, token: str
) -> databricks.sdk.WorkspaceClient:
    """The user's first request: their client is built from the token, and ``/Me`` names
    them as ``TOKEN_USER``.  The requests it took are then forgotten, and ``/Me`` 404s."""
    from src.core import databricks_client

    monkeypatch.setenv("DATABRICKS_HOST", HOST)
    sdk_wire.bodies[ME_PATH] = {"userName": TOKEN_USER, "id": "1"}
    client, user = databricks_client._create_user_client(token)
    assert user is not None and user.user_name == TOKEN_USER
    del sdk_wire.bodies[ME_PATH]
    sdk_wire.sent.clear()
    return client


class _McpService:
    """A Gateway MCP service on ``httpx``'s mock transport.  It completes one MCP session
    (``initialize``, ``notifications/initialized``, ``tools/list``), answering in JSON
    with no session id, and keeps every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        message = json.loads(request.content) if request.content else {}
        if "id" not in message:  # a notification
            return httpx.Response(202)
        if message.get("method") == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {},
                "serverInfo": {"name": "unit", "version": "0"},
            }
        else:
            result = {"tools": []}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def rpc_methods(self) -> list[str | None]:
        return [
            json.loads(request.content).get("method") if request.content else None
            for request in self.requests
        ]


@pytest.fixture
def mcp_service(monkeypatch: pytest.MonkeyPatch) -> _McpService:
    """Every ``httpx.AsyncClient`` opened in the test talks to one ``_McpService``; the
    client keeps its own arguments (headers, auth, timeouts)."""
    service = _McpService()
    real_async_client = httpx.AsyncClient

    class _OnTheMockTransport(real_async_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(service)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _OnTheMockTransport)
    return service


def _record_mcp_site_clients(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict[str, Any], bool]]:
    """Fakes for the SDK client and ``DatabricksMCPClient`` that the MCP sites import when
    called.  Returns each SDK client's keywords, and whether a worker thread built it."""
    built: list[tuple[dict[str, Any], bool]] = []

    class _FakeWorkspaceClient:
        def __init__(self, **kwargs: Any) -> None:
            built.append((kwargs, threading.current_thread() is not threading.main_thread()))

    class _FakeMCPClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            return SimpleNamespace(content=[SimpleNamespace(text='{"ok": true}')])

        def list_tools(self) -> list[Any]:
            return []

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", _FakeWorkspaceClient)
    monkeypatch.setattr(databricks_mcp, "DatabricksMCPClient", _FakeMCPClient)
    return built


# ---------------------------------------------------------------------------
# The user client and the clients derived from the system client
# ---------------------------------------------------------------------------


def test_first_stage_user_client_is_labelled(installed_version, sdk_wire, monkeypatch):
    """The first client asks ``/Me`` who the user is, so it is labelled as the app; the
    client then built carries the user's label, and the label is remembered for the token."""
    from src.core import databricks_client

    monkeypatch.setenv("DATABRICKS_HOST", HOST)
    sdk_wire.bodies[ME_PATH] = {"userName": TOKEN_USER, "id": "1"}

    client, _ = databricks_client._create_user_client("tok-first")
    client.current_user.me()

    first_stage, final = sdk_wire.sent_to(ME_PATH)
    assert first_stage.headers["User-Agent"].startswith(f"tellr-app-system/{VERSION} ")
    assert final.headers["User-Agent"].startswith(f"{TOKEN_USER_PRODUCT}/{VERSION} ")
    assert {r.headers["Authorization"] for r in (first_stage, final)} == {"Bearer tok-first"}
    assert attribution.user_product_kwargs("tok-first") == {
        "product": TOKEN_USER_PRODUCT,
        "product_version": VERSION,
    }


def test_a_failed_me_lookup_never_hides_a_known_label(installed_version, sdk_wire, monkeypatch):
    """A workspace can rate-limit ``/Me``, and a failed lookup is not cached, so the next request
    builds the client again.  Its fallback label is never remembered: it must not replace
    the label already known for that token, nor hide the request's user for a token never
    seen (``mcp_auth`` binds the user from a second ``/Me`` after this one failed)."""
    from src.core import databricks_client

    _sign_in(sdk_wire, monkeypatch, "tok-known")
    databricks_client._create_user_client("tok-known")
    databricks_client._create_user_client("tok-never-seen")

    assert len(sdk_wire.sent_to(ME_PATH)) == 2, "both rebuilds must have met a failing /Me"
    assert attribution.user_product_kwargs("tok-known")["product"] == TOKEN_USER_PRODUCT
    with _request_user(OTHER_REQUEST_USER):
        assert attribution.user_product_kwargs("tok-never-seen")["product"] == (
            OTHER_REQUEST_USER_PRODUCT
        )


def test_a_client_built_while_me_fails_carries_the_label_known_for_its_token(
    installed_version, sdk_wire, monkeypatch
):
    """When ``/Me`` fails for a token whose user is already known, the client built then
    still carries that user's label; only a token never seen gets ``tellr-app-unknown``."""
    from src.core import databricks_client

    _sign_in(sdk_wire, monkeypatch, "tok-known")  # from here on, /Me fails
    known, known_user = databricks_client._create_user_client("tok-known")
    never_seen, never_seen_user = databricks_client._create_user_client("tok-never-seen")
    assert known_user is None and never_seen_user is None
    assert len(sdk_wire.sent_to(ME_PATH)) == 2, "both builds must have met a failing /Me"

    sdk_wire.bodies[ME_PATH] = {"userName": TOKEN_USER, "id": "1"}
    sdk_wire.sent.clear()
    known.current_user.me()
    never_seen.current_user.me()

    known_request, never_seen_request = sdk_wire.sent_to(ME_PATH)
    assert known_request.headers["Authorization"] == "Bearer tok-known"
    assert known_request.headers["User-Agent"].startswith(f"{TOKEN_USER_PRODUCT}/{VERSION} ")
    assert never_seen_request.headers["Authorization"] == "Bearer tok-never-seen"
    assert never_seen_request.headers["User-Agent"].startswith(
        f"{attribution.PRODUCT_NAME_UNKNOWN}/{VERSION} "
    )


def test_catalog_clients_derived_from_the_system_client_keep_its_label(
    installed_version, sdk_wire, monkeypatch, tmp_path
):
    """``model_endpoint_catalog`` derives its bounded clients from the system client's
    ``Config`` (``WorkspaceClient(config=...)``, which the guard accepts): the copy must
    keep the system client's label."""
    from src.core import databricks_client
    from src.services.model_endpoint_catalog import (
        bounded_catalog_workspace_client,
        bounded_discovery_workspace_client,
    )

    monkeypatch.setattr(databricks_client, "TELLR_CONFIG_PATH", tmp_path / "no-config.yaml")
    monkeypatch.setenv("DATABRICKS_HOST", HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-system")
    sdk_wire.bodies[ME_PATH] = {"userName": "app-service-principal", "id": "1"}
    system_client = databricks_client.get_system_client()

    bounded_catalog_workspace_client(system_client).current_user.me()
    bounded_discovery_workspace_client(system_client).current_user.me()

    agents = [request.headers["User-Agent"] for request in sdk_wire.sent_to(ME_PATH)]
    assert len(agents) == 2
    assert all(agent.startswith(f"tellr-app-system/{VERSION} ") for agent in agents), agents


# ---------------------------------------------------------------------------
# Agent-mode Genie
# ---------------------------------------------------------------------------


def test_agent_mode_genie_client_is_labelled_for_its_user(installed_version, sdk_wire, monkeypatch):
    """Agent-mode Genie builds its client on the first call, from the user's host and
    token, inside ``run_with_timeout``'s worker thread.  It asks nobody who the user is:
    the call is the only request."""
    from src.services.agent_tools.genie_agent import GenieAgentClient

    _sign_in(sdk_wire, monkeypatch, "tok-genie")
    message_path = "/api/2.0/genie/spaces/space-1/conversations/conv-1/messages/msg-1"
    sdk_wire.bodies[message_path] = {"id": "msg-1", "status": "COMPLETED"}
    client = GenieAgentClient(host=HOST, token="tok-genie", space_id="space-1", source="Sales")

    with _request_user(OTHER_REQUEST_USER):
        client._call(
            lambda genie: genie.get_message(
                space_id="space-1", conversation_id="conv-1", message_id="msg-1"
            ),
            time.monotonic() + 30,
        )

    (request,) = sdk_wire.sent
    assert urlparse(request.url).path == message_path
    assert request.headers["User-Agent"].startswith(f"{TOKEN_USER_PRODUCT}/{VERSION} ")
    assert request.headers["Authorization"] == "Bearer tok-genie"


# ---------------------------------------------------------------------------
# MCP: the shared transport and the Legacy MCP tool
# ---------------------------------------------------------------------------


def test_mcp_http_headers_are_tellrs_user_agent_and_nothing_else(installed_version):
    """The User-Agent only: the AI Gateway records the request-tags header on model routes,
    not on MCP routes."""
    assert mcp_transport.mcp_http_headers() == {
        "User-Agent": f"tellr/{VERSION} python-httpx/{httpx.__version__}"
    }


def test_mcp_http_client_sends_one_tellr_user_agent_and_no_tag_header(
    installed_version, sdk_wire, mcp_service
):
    """The real client ``build_user_mcp_client`` returns, through one whole MCP session:
    every request carries one User-Agent, Tellr's, the user's bearer, and no tag header.
    Building it makes no SDK request."""
    path = "/ai-gateway/mcp-services/system.ai.web_search"
    client = mcp_transport.build_user_mcp_client(HOST, "tok-mcp", path)

    assert asyncio.run(client._get_tools_async()) == []

    assert mcp_service.rpc_methods() == ["initialize", "notifications/initialized", "tools/list"]
    for request in mcp_service.requests:
        assert str(request.url) == f"{HOST}{path}"
        assert request.headers.get_list("user-agent") == [
            f"tellr/{VERSION} python-httpx/{httpx.__version__}"
        ]
        assert "databricks-ai-gateway-request-tags" not in request.headers
        assert request.headers["authorization"] == "Bearer tok-mcp"
    assert sdk_wire.sent == []


def test_mcp_transport_workspace_client_is_labelled_for_its_user(
    installed_version, sdk_wire, monkeypatch
):
    """Genie One and the Gateway MCP client build it inside ``run_with_timeout``'s worker."""
    _sign_in(sdk_wire, monkeypatch, "tok-mcp")
    built = _record_mcp_site_clients(monkeypatch)

    with _request_user(OTHER_REQUEST_USER):
        mcp_transport.run_with_timeout(
            lambda: mcp_transport.build_user_mcp_client(
                HOST, "tok-mcp", "/ai-gateway/mcp-services/system.ai.web_search"
            ),
            timeout_seconds=10,
            on_timeout=lambda: AssertionError("the build did not finish"),
        )

    assert built == [
        (
            {
                "host": HOST,
                "token": "tok-mcp",
                "auth_type": "pat",
                "product": TOKEN_USER_PRODUCT,
                "product_version": VERSION,
            },
            True,
        )
    ]


@pytest.mark.parametrize("operation", ["call_mcp_tool", "list_mcp_tools"])
def test_legacy_mcp_tool_workspace_client_is_labelled_for_its_user(
    operation, installed_version, sdk_wire, monkeypatch
):
    """The Legacy MCP tool takes the host and token from the request's user client and
    builds a fresh SDK client in a bare ``ThreadPoolExecutor`` worker."""
    from src.core.databricks_client import set_user_client
    from src.services.tools import mcp_tool

    set_user_client(_sign_in(sdk_wire, monkeypatch, "tok-legacy"))
    built = _record_mcp_site_clients(monkeypatch)

    with _request_user(OTHER_REQUEST_USER):
        if operation == "call_mcp_tool":
            assert mcp_tool.call_mcp_tool("conn", "search", {"query": "q"}) == '{"ok": true}'
        else:
            assert mcp_tool.list_mcp_tools("conn") == []

    assert built == [
        (
            {
                "host": HOST,
                "token": "tok-legacy",
                "auth_type": "pat",
                "product": TOKEN_USER_PRODUCT,
                "product_version": VERSION,
            },
            True,
        )
    ]
