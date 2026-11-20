"""The one module that builds Tellr's Unity AI Gateway clients, and the tag they carry."""

import ast
import asyncio
import contextlib
import contextvars
import json
import threading
from collections import UserString
from datetime import datetime
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

import httpx
import openai
import pytest
from langchain_core.messages import HumanMessage

from src.core import attribution
from src.core.databricks_client import _get_package_version
from src.services.gateway_clients import (
    REQUEST_TAGS_HEADER,
    gateway_chat_model,
    gateway_openai_client,
    gateway_request_headers,
)
from tests.fixtures.mock_chat_completions import (
    MockChatCompletionsWorkspace,
    install_mock_gateway_transport,
)
from tests.unit.test_attribution import ALL_ENTRYPOINTS, OFF_LIST_ENTRYPOINTS, _Impostor

#: The SDK's own User-Agent for ``DatabricksOpenAI`` (``openai._base_client``:
#: ``f"{self.__class__.__name__}/Python {version}"``), kept as the suffix.
SDK_UA = f"DatabricksOpenAI/Python {openai.__version__}"
#: A source checkout has no installed ``databricks-tellr-app`` wheel, so the
#: version falls back to the source tree's (``_get_package_version``).
EXPECTED_UA = f"tellr/{_get_package_version()} {SDK_UA}"


def _source_tree_version() -> str:
    """What the source tree says: its generated ``_version.py`` if built, else ``__init__``'s."""
    try:
        from src._version import version
    except ImportError:
        from src import __version__ as version
    return version


@pytest.fixture(autouse=True)
def _fresh_version_cache():
    """``attribution.package_version`` is cached per process; each test starts and ends clean."""
    attribution.package_version.cache_clear()
    yield
    attribution.package_version.cache_clear()


def test_request_tags_header_is_the_source_tellr_json_object():
    assert REQUEST_TAGS_HEADER == "Databricks-Ai-Gateway-Request-Tags"
    assert json.loads(gateway_request_headers()[REQUEST_TAGS_HEADER]) == {"source": "tellr"}


def test_user_agent_leads_with_tellr_and_keeps_the_sdk_user_agent():
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


def test_user_agent_reports_the_installed_wheel_version(monkeypatch):
    """A deployed app runs from the ``databricks-tellr-app`` wheel, whose source
    tree carries no generated ``_version.py``: the wheel's metadata is the truth."""

    def _version(name):
        if name == "databricks-tellr-app":
            return "9.9.9"
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(attribution.metadata, "version", _version)

    assert gateway_request_headers()["User-Agent"] == f"tellr/9.9.9 {SDK_UA}"


def test_user_agent_falls_back_to_the_source_version_outside_a_wheel(monkeypatch):
    def _not_installed(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(attribution.metadata, "version", _not_installed)

    assert gateway_request_headers()["User-Agent"] == f"tellr/{_source_tree_version()} {SDK_UA}"


def test_user_agent_reads_the_one_shared_version_lookup(monkeypatch):
    """``attribution.metadata`` is ``importlib.metadata`` itself, so a copy of the lookup in
    ``gateway_clients`` would pass the two tests above. Only attribution's own cache still
    answers 7.0.0 once the installed metadata says 8.0.0."""
    monkeypatch.setattr(attribution.metadata, "version", lambda name: "7.0.0")
    assert attribution.package_version() == "7.0.0"
    monkeypatch.setattr(attribution.metadata, "version", lambda name: "8.0.0")

    assert gateway_request_headers()["User-Agent"] == f"tellr/7.0.0 {SDK_UA}"


def test_only_the_tag_and_user_agent_are_set():
    assert set(gateway_request_headers()) == {REQUEST_TAGS_HEADER, "User-Agent"}


def test_each_call_returns_a_fresh_dict():
    first = gateway_request_headers()
    first["User-Agent"] = "mutated"
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


def _text_workspace(monkeypatch) -> MockChatCompletionsWorkspace:
    """A mock-transport workspace that answers every chat completion with plain text."""
    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace({}, usage=None)

    def handle(request):
        workspace.requests.append(request)
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        })

    workspace._handle = handle
    return workspace


def _assert_tagged_gateway_chat_request(request: httpx.Request, model: str) -> None:
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
    assert request.headers.get_list("databricks-ai-gateway-request-tags") == ['{"source": "tellr"}']
    assert request.headers.get_list("user-agent") == [EXPECTED_UA]
    sent = json.loads(request.content)
    assert sent["model"] == model
    assert "extra_headers" not in sent and "extra_params" not in sent


def test_gateway_openai_client_sends_tagged_requests_to_the_gateway_chat_route(monkeypatch):
    """Exports: the raw client, bound to {host}/ai-gateway/mlflow/v1, tagged."""
    workspace = _text_workspace(monkeypatch)

    gateway_openai_client(workspace).chat.completions.create(
        model="system.ai.claude-sonnet-4-5",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5,
    )

    assert len(workspace.requests) == 1
    _assert_tagged_gateway_chat_request(workspace.requests[0], "system.ai.claude-sonnet-4-5")


def test_gateway_openai_client_forwards_client_kwargs_and_stays_tagged(monkeypatch):
    """Image generation builds its client with ``max_retries=0`` (no silent paid
    retries) and a timeout; ``with_options()`` is broken on ``DatabricksOpenAI``
    0.17.1, so the builder forwards them to the constructor (corrections doc, C5)."""
    workspace = _text_workspace(monkeypatch)

    client = gateway_openai_client(workspace, max_retries=0, timeout=12.5)
    client.chat.completions.create(
        model="system.ai.claude-sonnet-4-5",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5,
    )

    assert client.max_retries == 0
    assert client.timeout == 12.5
    assert len(workspace.requests) == 1
    _assert_tagged_gateway_chat_request(workspace.requests[0], "system.ai.claude-sonnet-4-5")
    assert workspace.requests[0].extensions["timeout"]["read"] == 12.5


def test_gateway_chat_model_sends_tagged_requests_to_the_gateway_chat_route(monkeypatch):
    """Graph agents and titles: the LangChain model, as the given identity, tagged."""
    workspace = _text_workspace(monkeypatch)

    model = gateway_chat_model(model="system.ai.claude-opus-5-5", max_tokens=5, workspace_client=workspace)
    model.invoke([HumanMessage(content="hi")])

    assert model.workspace_client is workspace
    assert len(workspace.requests) == 1
    _assert_tagged_gateway_chat_request(workspace.requests[0], "system.ai.claude-opus-5-5")
    assert json.loads(workspace.requests[0].content)["max_tokens"] == 5


_GATEWAY_FLAGS = ("use_ai_gateway", "use_ai_gateway_native_api")


def _is_headers_call(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "gateway_request_headers"
    )


def _carries_extra_headers(node: ast.AST | None) -> bool:
    """``extra_params={"extra_headers": gateway_request_headers()}``."""
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "extra_headers" and _is_headers_call(value)
        for key, value in zip(node.keys, node.values)
    )


def _gateway_calls(source: str) -> list[tuple[int, bool]]:
    """``(line, tagged)`` for each call in ``source`` that builds a Unity AI Gateway client.

    A call builds one when it passes a Gateway flag that is not literally ``False``,
    or a ``base_url`` under ``/ai-gateway/``.  It is tagged when it passes
    ``default_headers=gateway_request_headers()`` or the ``extra_params`` form.
    Comments and prose are not calls, so they neither count nor tag.
    """
    calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        flagged = any(
            name in kwargs
            and not (isinstance(kwargs[name], ast.Constant) and kwargs[name].value is False)
            for name in _GATEWAY_FLAGS
        )
        gateway_url = "base_url" in kwargs and "/ai-gateway/" in ast.unparse(kwargs["base_url"])
        if flagged or gateway_url:
            tagged = _is_headers_call(kwargs.get("default_headers")) or _carries_extra_headers(
                kwargs.get("extra_params")
            )
            calls.append((node.lineno, tagged))
    return sorted(calls)


TAGGED = 'extra_params={"extra_headers": gateway_request_headers()}'


def test_guard_flags_an_untagged_construction_beside_a_tagged_one():
    source = f"a = ChatDatabricks(use_ai_gateway=True, {TAGGED})\nb = ChatDatabricks(use_ai_gateway=True)\n"
    assert _gateway_calls(source) == [(1, True), (2, False)]


def test_guard_flags_a_commented_out_header_argument():
    source = "DatabricksOpenAI(\n    use_ai_gateway=True,\n    # default_headers=gateway_request_headers(),\n)\n"
    assert _gateway_calls(source) == [(1, False)]


def test_guard_flags_a_client_built_from_an_ai_gateway_base_url():
    source = 'DatabricksOpenAI(base_url=f"{host}/ai-gateway/mlflow/v1")\n'
    assert _gateway_calls(source) == [(1, False)]


def test_guard_accepts_both_tagging_forms():
    source = (
        "DatabricksOpenAI(use_ai_gateway=True, default_headers=gateway_request_headers())\n"
        f"ChatDatabricks(use_ai_gateway_native_api=True, {TAGGED}, **kwargs)\n"
    )
    assert _gateway_calls(source) == [(1, True), (2, True)]


def test_guard_ignores_prose_and_disabled_flags():
    source = '"""Mentions use_ai_gateway=True and /ai-gateway/ in prose."""\nx = f(use_ai_gateway=False)\n'
    assert _gateway_calls(source) == []


def test_only_gateway_clients_builds_gateway_clients_and_every_one_is_tagged():
    """Isaac's tag was once silently dropped; a new Gateway client must not ship untagged.

    Every Gateway client in ``src`` is built in ``services/gateway_clients.py``;
    a construction anywhere else should call its builders instead.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    found = {p.relative_to(src).as_posix(): _gateway_calls(p.read_text()) for p in src.rglob("*.py")}
    sites = {path: calls for path, calls in found.items() if calls}
    assert set(sites) == {"services/gateway_clients.py"}
    untagged = [(path, line) for path, calls in sites.items() for line, tagged in calls if not tagged]
    assert untagged == []


# ---------------------------------------------------------------------------
# component: which feature made the call
# ---------------------------------------------------------------------------

#: The feature names a tag may carry, spelled out: a test that read them from
#: ``COMPONENTS`` would follow a changed list instead of pinning it.
ALL_COMPONENTS = ("generation", "title", "export", "image")

#: Values a component must never be sent as: each is dropped, and none raises.
OFF_LIST_COMPONENTS = [
    pytest.param("judge", id="unknown-name"),
    pytest.param("Generation", id="wrong-case"),
    pytest.param("TITLE", id="upper-case"),
    pytest.param(" export", id="leading-space"),
    pytest.param("image\n", id="trailing-newline"),
    pytest.param("", id="empty"),
    pytest.param("a prompt someone typed", id="free-text"),
    pytest.param("generation,title", id="two-names"),
    pytest.param(None, id="none"),
    pytest.param(0, id="int"),
    pytest.param(True, id="bool"),
    pytest.param(b"title", id="bytes"),
    pytest.param(UserString("title"), id="str-like"),
    pytest.param(["title"], id="unhashable-list"),
    pytest.param({"component": "title"}, id="unhashable-dict"),
]


def _sent_tags(request: httpx.Request) -> dict:
    """The tag header ``request`` carries, parsed: exactly one, or the test fails."""
    values = request.headers.get_list("databricks-ai-gateway-request-tags")
    assert len(values) == 1, f"expected one tag header, got {values}"
    return json.loads(values[0])


#: Body fields that would mean the tag, or the builder's own options, reached the JSON body.
_TAG_BODY_FIELDS = frozenset(
    {"source", "component", "entrypoint", "extra_headers", "extra_params", "default_headers"}
)


def _assert_sent_with_tags(request: httpx.Request, tags: dict) -> None:
    """A Gateway chat request with exactly ``tags``, Tellr's one User-Agent, no tag in its body."""
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert _sent_tags(request) == tags
    assert request.headers.get_list("user-agent") == [EXPECTED_UA]
    leaked = _TAG_BODY_FIELDS & set(json.loads(request.content))
    assert not leaked, f"tag fields in the request body: {sorted(leaked)}"
    assert b"ai-gateway-request-tags" not in request.content.lower()


def test_the_components_are_exactly_these_four():
    from src.services import gateway_clients

    assert gateway_clients.COMPONENTS == frozenset(ALL_COMPONENTS)
    assert type(gateway_clients.COMPONENTS) is frozenset


@pytest.mark.parametrize("component", ALL_COMPONENTS)
def test_component_is_added_beside_source(component):
    by_position = gateway_request_headers(component)
    by_keyword = gateway_request_headers(component=component)
    for headers in (by_position, by_keyword):
        tags = json.loads(headers[REQUEST_TAGS_HEADER])
        assert tags == {"source": "tellr", "component": component}
        assert set(headers) == {REQUEST_TAGS_HEADER, "User-Agent"}
        assert headers["User-Agent"] == EXPECTED_UA


@pytest.mark.parametrize("value", OFF_LIST_COMPONENTS)
def test_a_component_off_the_list_is_dropped_and_never_raises(value):
    """Nothing may raise into a request: an unhashable value, or a ``str`` stand-in equal to
    an allowed name, is dropped like any other value off the list (only a ``str`` counts)."""
    headers = gateway_request_headers(value)

    assert json.loads(headers[REQUEST_TAGS_HEADER]) == {"source": "tellr"}
    assert set(headers) == {REQUEST_TAGS_HEADER, "User-Agent"}


@pytest.mark.parametrize("posing_as", ALL_COMPONENTS)
def test_free_text_posing_as_a_component_never_reaches_the_tag(posing_as):
    impostor = _Impostor("a prompt someone typed", posing_as)
    assert impostor in frozenset(ALL_COMPONENTS)  # precondition: it fools a membership test

    raw = gateway_request_headers(impostor)[REQUEST_TAGS_HEADER]

    assert "a prompt someone typed" not in raw
    assert json.loads(raw) in ({"source": "tellr"}, {"source": "tellr", "component": posing_as})


@pytest.mark.parametrize("component", ALL_COMPONENTS)
def test_chat_model_sends_its_component(monkeypatch, component):
    workspace = _text_workspace(monkeypatch)

    model = gateway_chat_model(
        component=component,
        model="system.ai.claude-opus-5-5",
        max_tokens=5,
        workspace_client=workspace,
    )
    model.invoke([HumanMessage(content="hi")])

    assert len(workspace.requests) == 1
    _assert_sent_with_tags(workspace.requests[0], {"source": "tellr", "component": component})
    assert json.loads(workspace.requests[0].content)["max_tokens"] == 5


@pytest.mark.parametrize("component", ALL_COMPONENTS)
def test_openai_client_sends_its_component_and_keeps_its_client_kwargs(monkeypatch, component):
    """``component`` is the builder's own: not forwarded to ``DatabricksOpenAI``, while
    the client kwargs beside it still are."""
    workspace = _text_workspace(monkeypatch)

    client = gateway_openai_client(workspace, component=component, max_retries=0)
    client.chat.completions.create(
        model="system.ai.claude-sonnet-4-5",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5,
    )

    assert client.max_retries == 0
    assert len(workspace.requests) == 1
    _assert_sent_with_tags(workspace.requests[0], {"source": "tellr", "component": component})


_BUILDERS = frozenset({"gateway_chat_model", "gateway_openai_client"})
#: What ``_builder_uses`` reports in place of a literal component.
_NO_COMPONENT = "<no component=>"
_NOT_LITERAL = "<component= not a literal>"
_NOT_CALLED = "<referenced, not called>"


def _builder_uses(source: str) -> list[tuple[str, object]]:
    """``(builder, component)`` for each use of a Gateway builder in ``source``, in order.

    A use is a call (by the builder's own name however it was imported, absolute,
    relative or ``*``; by an import alias; or as ``module.<builder>``) or any other
    reference to one, such as ``functools.partial(gateway_openai_client, ws)``, which hides
    its component from this reader (``_NOT_CALLED``).  The component is the literal passed
    as ``component=``; a ``**`` splat is not one.  Comments and prose are not uses.
    """
    tree = ast.parse(source)
    local_names = {name: name for name in _BUILDERS}
    local_names.update(
        (alias.asname or alias.name, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.services.gateway_clients"
        for alias in node.names
        if alias.name in _BUILDERS
    )

    def builder_named(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return local_names.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr in _BUILDERS:
            return node.attr
        return None

    uses: list[tuple[int, int, str, object]] = []
    called: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (builder := builder_named(node.func)):
            called.add(id(node.func))
            named = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
            value = named.get("component")
            if value is None:
                component: object = _NO_COMPONENT
            elif isinstance(value, ast.Constant):
                component = value.value
            else:
                component = _NOT_LITERAL
            uses.append((node.lineno, node.col_offset, builder, component))
    for node in ast.walk(tree):
        if id(node) not in called and (builder := builder_named(node)):
            uses.append((node.lineno, node.col_offset, builder, _NOT_CALLED))
    in_order = sorted(uses, key=lambda use: use[:2])
    return [(builder, component) for _, _, builder, component in in_order]


def test_builder_reader_names_each_calls_component():
    source = (
        "from src.services.gateway_clients import gateway_chat_model, gateway_openai_client\n"
        'gateway_chat_model(component="title", model=m)\n'
        "gateway_openai_client(ws)\n"
        "gateway_openai_client(ws, component=name)\n"
        'gateway_chat_model(**{"component": "title"})\n'
    )
    assert _builder_uses(source) == [
        ("gateway_chat_model", "title"),
        ("gateway_openai_client", _NO_COMPONENT),
        ("gateway_openai_client", _NOT_LITERAL),
        ("gateway_chat_model", _NO_COMPONENT),
    ]


def test_builder_reader_follows_aliases_attributes_and_bare_references():
    source = (
        "from src.services.gateway_clients import gateway_openai_client as make_client\n"
        "from src.services import gateway_clients\n"
        "make_client(ws)\n"
        'gateway_clients.gateway_chat_model(component="generation")\n'
        "factory = functools.partial(make_client, ws)\n"
    )
    assert _builder_uses(source) == [
        ("gateway_openai_client", _NO_COMPONENT),
        ("gateway_chat_model", "generation"),
        ("gateway_openai_client", _NOT_CALLED),
    ]


def test_builder_reader_sees_a_builder_however_its_name_was_imported():
    """A relative or ``*`` import names no module this reader can match, so the builder's
    own name is recognised wherever it appears."""
    source = (
        "from .gateway_clients import gateway_chat_model\n"
        "from src.services.gateway_clients import *\n"
        "gateway_chat_model(model=m)\n"
        'gateway_openai_client(ws, component="export")\n'
        "factory = gateway_openai_client\n"
    )
    assert _builder_uses(source) == [
        ("gateway_chat_model", _NO_COMPONENT),
        ("gateway_openai_client", "export"),
        ("gateway_openai_client", _NOT_CALLED),
    ]


def test_builder_reader_ignores_prose_comments_and_definitions():
    source = (
        '"""Call gateway_chat_model(component="title") like this."""\n'
        "# gateway_openai_client(ws)\n"
        "def gateway_chat_model(**kwargs):\n"
        "    return kwargs\n"
    )
    assert _builder_uses(source) == []


def test_every_builder_call_site_names_its_component():
    """Each Gateway client is built for one feature, named by a literal where it is built."""
    src = Path(__file__).resolve().parents[2] / "src"
    found = {}
    for path in sorted(src.rglob("*.py")):
        uses = _builder_uses(path.read_text())
        if uses:
            found[path.relative_to(src).as_posix()] = uses

    assert found == {
        "api/services/session_naming.py": [("gateway_chat_model", "title")],
        "services/agent_runtime.py": [("gateway_chat_model", "generation")],
        "services/html_to_google_slides.py": [("gateway_openai_client", "export")],
        "services/html_to_pptx.py": [("gateway_openai_client", "export")],
        "services/image_generation.py": [("gateway_openai_client", "image")],
    }


# ---------------------------------------------------------------------------
# entrypoint: how the turn reached Tellr (its UI, or its MCP server)
# ---------------------------------------------------------------------------


def _in_a_turn(entrypoint, fn):
    """``fn()`` in a fresh copy of this context, after the turn marked ``entrypoint``."""

    def turn():
        attribution.set_entrypoint(entrypoint)
        return fn()

    return contextvars.copy_context().run(turn)


def _tags_for(component) -> dict:
    return json.loads(gateway_request_headers(component)[REQUEST_TAGS_HEADER])


@pytest.mark.parametrize("entrypoint", ALL_ENTRYPOINTS)
@pytest.mark.parametrize("component", [*ALL_COMPONENTS, None])
def test_entrypoint_is_added_when_the_turn_set_it(entrypoint, component):
    expected = {"source": "tellr", "entrypoint": entrypoint}
    if component is not None:
        expected["component"] = component

    assert _in_a_turn(entrypoint, lambda: _tags_for(component)) == expected


@pytest.mark.parametrize("component", [*ALL_COMPONENTS, None])
def test_no_entrypoint_key_outside_a_turn(component):
    assert "entrypoint" not in _tags_for(component)


@pytest.mark.parametrize("value", OFF_LIST_ENTRYPOINTS)
def test_an_entrypoint_off_the_list_adds_no_key(value):
    assert _in_a_turn(value, lambda: _tags_for("generation")) == {
        "source": "tellr",
        "component": "generation",
    }


@pytest.mark.parametrize("posing_as", ALL_ENTRYPOINTS)
def test_free_text_posing_as_an_entrypoint_never_reaches_the_tag(posing_as):
    raw = _in_a_turn(
        _Impostor("a prompt someone typed", posing_as),
        lambda: gateway_request_headers("generation")[REQUEST_TAGS_HEADER],
    )

    assert "a prompt someone typed" not in raw
    assert json.loads(raw) in (
        {"source": "tellr", "component": "generation"},
        {"source": "tellr", "component": "generation", "entrypoint": posing_as},
    )


#: Free text posing as each entrypoint, as a value held in the turn's context.
_IMPOSTOR_ENTRYPOINTS = [
    pytest.param(_Impostor("a prompt someone typed", name), id=f"impostor-{name}")
    for name in ALL_ENTRYPOINTS
]


@pytest.mark.parametrize("value", [*OFF_LIST_ENTRYPOINTS, *_IMPOSTOR_ENTRYPOINTS])
def test_the_tag_checks_the_entrypoint_it_reads_itself(value):
    """``_request_tags`` checks the value it reads, not only ``set_entrypoint`` the value it
    writes: one put straight into the ContextVar, past that filter, adds no key and never
    raises."""

    def turn():
        attribution._entrypoint_var.set(value)
        return gateway_request_headers("generation")[REQUEST_TAGS_HEADER]

    raw = contextvars.copy_context().run(turn)

    assert json.loads(raw) == {"source": "tellr", "component": "generation"}


def test_the_tag_is_sent_as_exactly_this_text():
    """The header's text, not only its parsed value: ``source``, ``component`` and
    ``entrypoint`` in that order, with ``json.dumps``' default separators."""
    raw = _in_a_turn("mcp", lambda: gateway_request_headers("generation")[REQUEST_TAGS_HEADER])

    assert raw == '{"source": "tellr", "component": "generation", "entrypoint": "mcp"}'


@pytest.mark.parametrize("entrypoint", ALL_ENTRYPOINTS)
def test_clients_built_in_a_turn_send_its_entrypoint_beside_their_component(
    monkeypatch, entrypoint
):
    workspace = _text_workspace(monkeypatch)

    def turn():
        gateway_chat_model(
            component="title", model="system.ai.claude-opus-5-5", workspace_client=workspace
        ).invoke([HumanMessage(content="hi")])
        gateway_openai_client(workspace, component="export").chat.completions.create(
            model="system.ai.claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}]
        )

    _in_a_turn(entrypoint, turn)

    assert len(workspace.requests) == 2
    for request, component in zip(workspace.requests, ("title", "export")):
        _assert_sent_with_tags(
            request, {"source": "tellr", "component": component, "entrypoint": entrypoint}
        )


# --- through the real job queue: entry site -> enter_chat_turn -> enqueue_job -> worker ---

_TURN_MESSAGE = "build me a deck about eider ducks"


def _title_tags(entrypoint) -> dict:
    tags = {"source": "tellr", "component": "title"}
    if entrypoint is not None:
        tags["entrypoint"] = entrypoint
    return tags


class _TitleCallingChatService:
    """Stands in for the chat service: every turn makes one real title call.

    The model is built by the REAL ``build_session_title_model`` and called over the mock
    transport on the chat-job thread, in the job's context: where the real service builds
    its models (each of its limbs copies that context for its title thread).
    """

    def __init__(self, workspace: MockChatCompletionsWorkspace) -> None:
        self.workspace = workspace
        self.requests_by_turn: dict[str, list[httpx.Request]] = {}

    def send_message_streaming(self, **kwargs):
        from src.api.schemas.streaming import StreamEvent, StreamEventType
        from src.api.services.session_naming import build_session_title_model

        before = len(self.workspace.requests)
        build_session_title_model().invoke(kwargs["message"])
        self.requests_by_turn[kwargs["request_id"]] = self.workspace.requests[before:]
        yield StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})


@pytest.fixture
def real_job_queue(monkeypatch):
    """The real ``enqueue_job``, ``worker`` and ``process_chat_request`` over a fresh queue.

    No database: the runner's session manager is a ``MagicMock``.  Every module is
    imported before anything is patched, so none binds a patched name at its own import.
    """
    import src.api.main  # noqa: F401 - binds every route and service module first
    import src.services.graph.builder  # noqa: F401 - the app does not import it itself
    from src.api.services import job_queue

    runner_manager = MagicMock()
    monkeypatch.setattr(
        "src.api.services.session_manager.get_session_manager", lambda: runner_manager
    )
    monkeypatch.setattr(job_queue, "job_queue", asyncio.Queue())
    monkeypatch.setattr(job_queue, "jobs", {})
    job_queue.shutdown_chat_executor()
    yield SimpleNamespace(module=job_queue, manager=runner_manager)
    job_queue.shutdown_chat_executor()


@pytest.fixture
def title_calling_turns(real_job_queue, monkeypatch):
    """Every turn the worker runs makes one real title call as the service principal."""
    workspace = _text_workspace(monkeypatch)
    service = _TitleCallingChatService(workspace)
    monkeypatch.setattr("src.core.databricks_client.get_system_client", lambda: workspace)
    monkeypatch.setattr("src.api.services.chat_service.get_chat_service", lambda: service)
    return service


def _enter_through(monkeypatch, manager, engine_mode: str) -> None:
    """Point the shared Enter (``chat.enter_chat_turn``) at ``manager`` and ``engine_mode``.

    The browser route and the MCP tools both enter their turns through it, so each sender
    calls this as it sends: turns from both, sent one after another, each get their own.
    """
    from src.api.routes import chat

    monkeypatch.setattr(chat, "get_session_manager", lambda: manager)
    monkeypatch.setattr(chat, "resolve_engine_mode_or_unavailable", lambda session_id: engine_mode)


def _app_route(monkeypatch, *, deck_mode):
    """``POST /api/chat/async``'s own coroutine, with no database and no permission check.

    ``deck_mode="legacy"`` sends a Legacy deck's turn (the monolith); ``None`` a new Agent
    deck's (the graph; its Enter snapshot is the ``MagicMock`` manager's).  The route and
    the shared Enter it calls are real.  Returns ``submit(request_id)``, the coroutine
    function that sends one turn.
    """
    from src.api.routes import chat
    from src.api.schemas.requests import ChatRequest

    engine_mode = "monolith" if deck_mode == "legacy" else "graph"
    manager = MagicMock()
    manager.acquire_session_lock.return_value = True
    manager.get_deck_mode.return_value = deck_mode
    manager.get_session.return_value = {"message_count": 0}
    monkeypatch.setattr(chat, "_check_chat_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_maybe_create_session", lambda request, session_manager: False)

    def submit(request_id):
        async def send():
            manager.create_chat_request.return_value = request_id
            _enter_through(monkeypatch, manager, engine_mode)
            result = await chat.submit_chat_async(
                ChatRequest(session_id="s-app", message=_TURN_MESSAGE), db=MagicMock()
            )
            assert result == {"request_id": request_id, "status": "pending"}

        return send

    return submit


#: The MCP tools that start a turn.  Both enter it through ``_enter_turn_or_tool_error``.
_MCP_TOOLS = ("create_deck", "edit_deck")


def _mcp_tool(monkeypatch, *, tool):
    """An MCP tool's own implementation (``_create_deck_impl`` or ``_edit_deck_impl``).

    Real from there through ``_enter_turn_or_tool_error`` and the shared Enter to
    ``enqueue_job``: an Agent deck's turn.  Stubbed, as ``tests/unit/test_mcp_server.py``
    stubs them: the auth scope (it yields a fixed identity), the session manager (a
    ``MagicMock``; ``create_deck``'s new deck has no messages, ``edit_deck``'s is the
    caller's own Agent deck with three), both engine resolvers (``graph``), the
    edit-permission facade (allowed) and the admin defaults (no design system, slide style
    or Genie One default).  Returns ``submit(request_id)``.

    Each tool is sent by its own sender, looked up by its name: a tool with none raises
    ``KeyError`` here, so a tool added to ``_MCP_TOOLS`` never runs another tool's
    implementation in its place.
    """
    from src.api import mcp_server
    from src.api.mcp_auth import MCPIdentity
    from src.api.routes import chat

    session_id = f"s-mcp-{tool}"
    # Each tool's deck message count when its turn is sent, and its sender.
    senders = {
        "create_deck": (
            0,
            lambda: mcp_server._create_deck_impl(request=MagicMock(), prompt=_TURN_MESSAGE),
        ),
        "edit_deck": (
            3,
            lambda: mcp_server._edit_deck_impl(
                request=MagicMock(), session_id=session_id, instruction=_TURN_MESSAGE
            ),
        ),
    }
    message_count, send_turn = senders[tool]
    identity = MCPIdentity(
        user_id="user-mcp",
        user_name="caller@example.com",
        token="tok",
        source="x-forwarded-access-token",
    )
    manager = MagicMock()
    manager.acquire_session_lock.return_value = True
    manager.create_session.return_value = {"session_id": session_id}
    manager.get_deck_mode.return_value = "agent"
    manager.get_session.return_value = {
        "message_count": message_count,
        "created_by": identity.user_name,
        "is_contributor_session": False,
    }
    manager.live_generation_holder.return_value = None

    @contextlib.contextmanager
    def auth_scope(request):
        yield identity

    monkeypatch.setattr(mcp_server, "mcp_auth_scope", auth_scope)
    monkeypatch.setattr(mcp_server, "get_session_manager", lambda: manager)
    monkeypatch.setattr(
        mcp_server, "permission_service", MagicMock(**{"can_edit_deck.return_value": True})
    )
    monkeypatch.setattr(
        mcp_server, "resolve_engine_mode_or_unavailable", lambda session_id: "graph"
    )
    monkeypatch.setattr(mcp_server, "get_default_design_system_id", lambda: None)
    monkeypatch.setattr(mcp_server, "get_default_slide_style_id", lambda: None)
    monkeypatch.setattr(chat, "get_genie_one_default", lambda: False)

    def submit(request_id):
        async def send():
            manager.create_chat_request.return_value = request_id
            _enter_through(monkeypatch, manager, "graph")
            result = await send_turn()
            assert (result["session_id"], result["request_id"], result["status"]) == (
                session_id,
                request_id,
                "pending",
            )

        return send

    return submit


def test_an_mcp_tool_with_no_sender_raises_instead_of_running_another_tools(monkeypatch):
    """A tool added to ``_MCP_TOOLS`` without a sender in ``_mcp_tool`` fails every test
    that sends it, instead of passing on ``edit_deck``'s implementation."""
    with pytest.raises(KeyError, match="duplicate_deck"):
        _mcp_tool(monkeypatch, tool="duplicate_deck")


#: Every way a turn reaches Tellr: the browser route, and each MCP tool that starts one.
_ENTRY_SITES = ("app", *(f"mcp-{tool}" for tool in _MCP_TOOLS))


def _entry_site(monkeypatch, entry: str):
    """``(entrypoint, submit)`` for one of ``_ENTRY_SITES``.  The browser route sends a
    Legacy deck's turn here (only the browser sends turns to Legacy decks); MCP's are
    Agent decks' turns."""
    if entry == "app":
        return "app", _app_route(monkeypatch, deck_mode="legacy")
    return "mcp", _mcp_tool(monkeypatch, tool=entry.removeprefix("mcp-"))


def _assert_completed(manager, request_id: str, *, agent: bool) -> None:
    """The runner completed the turn: an Agent turn with ``complete_chat_request``, which
    writes its result and status at once, any other with the ``completed`` status."""
    if agent:
        manager.complete_chat_request.assert_any_call(request_id, ANY)
    else:
        manager.update_chat_request_status.assert_any_call(request_id, "completed")


def _job_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "message": _TURN_MESSAGE,
        "slide_context": None,
        "is_first_message": True,
        "image_ids": None,
    }


def _unlabelled(request_id):
    """A job ``enqueue_job`` captured from a context that marked no entrypoint."""

    async def send():
        from src.api.services import job_queue

        await job_queue.enqueue_job(request_id, _job_payload("s-plain"))

    return send


def _without_context(request_id):
    """A job with no captured context (a recovered job's shape): it runs in a copy of the
    runner's own context, so it shows anything a job left there."""

    async def send():
        from src.api.services import job_queue

        job_queue.jobs[request_id] = {
            "status": "pending",
            "session_id": "s-recovered",
            "engine_mode": None,
            "queued_at": datetime.utcnow(),
        }
        job_queue.job_queue.put_nowait((request_id, _job_payload("s-recovered")))

    return send


def _run_turns(*sends) -> list:
    """Send each turn from its own task, then let ONE real ``worker()`` drain the queue.

    Each send runs in its own ``asyncio`` task, so in its own copy of the context, as each
    HTTP request and each MCP tool call does.  The runner starts afterwards from the outer
    coroutine, which marked nothing, as the app's lifespan starts its runners.  Returns the
    outer context's entrypoint after the sends and after the jobs ran.
    """
    from src.api.services import job_queue

    async def main():
        for send in sends:
            await asyncio.create_task(send())
        seen = [attribution.get_entrypoint()]
        runner = asyncio.create_task(job_queue.worker())
        await asyncio.wait_for(job_queue.job_queue.join(), timeout=30)
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner
        seen.append(attribution.get_entrypoint())
        return seen

    return asyncio.run(main())


def _assert_turn_sent(service, manager, request_id: str, tags: dict) -> None:
    sent = service.requests_by_turn.get(request_id)
    assert sent is not None, (
        f"{request_id} never reached the chat service; status writes: "
        f"{manager.update_chat_request_status.call_args_list}"
    )
    assert len(sent) == 1, f"{request_id} made {len(sent)} model calls"
    _assert_sent_with_tags(sent[0], tags)


@pytest.mark.parametrize("entry", _ENTRY_SITES)
def test_a_turn_tags_its_model_calls_with_its_entrypoint_through_the_real_job_queue(
    real_job_queue, title_calling_turns, monkeypatch, entry
):
    """From each real entry site (the chat route for ``app``; ``create_deck`` and
    ``edit_deck`` for ``mcp``) through the real shared Enter, ``enqueue_job``, ``worker``
    and ``process_chat_request``.  The site marks its own context before it calls the
    Enter, and the job runs in ``enqueue_job``'s copy of that context, so the turn's title
    call carries the site's entrypoint, and nothing else does."""
    entrypoint, submit = _entry_site(monkeypatch, entry)
    request_id = f"req-{entry}"

    outer = _run_turns(submit(request_id))

    _assert_turn_sent(
        title_calling_turns, real_job_queue.manager, request_id, _title_tags(entrypoint)
    )
    _assert_completed(real_job_queue.manager, request_id, agent=entrypoint == "mcp")
    assert real_job_queue.module.jobs == {}
    assert outer == [None, None], "the site's entrypoint reached the runner's context"


def test_one_turns_entrypoint_never_reaches_another_turn_on_the_same_runner(
    real_job_queue, title_calling_turns, monkeypatch
):
    """Five jobs, ONE runner, in this order: an MCP turn (``create_deck``, an Agent deck's),
    a recovered job (no captured context: a copy of the runner's own), a job enqueued from
    a context that marked nothing, an app turn (a Legacy deck's), and a second recovered
    job.  Each carries its own entrypoint, or none: no job's value reaches the next, nor
    the runner."""
    from_mcp = _mcp_tool(monkeypatch, tool="create_deck")
    from_app = _app_route(monkeypatch, deck_mode="legacy")
    turns = [
        ("req-1-mcp", from_mcp("req-1-mcp"), "mcp"),
        ("req-2-recovered", _without_context("req-2-recovered"), None),
        ("req-3-unlabelled", _unlabelled("req-3-unlabelled"), None),
        ("req-4-app", from_app("req-4-app"), "app"),
        ("req-5-recovered", _without_context("req-5-recovered"), None),
    ]

    outer = _run_turns(*(send for _, send, _ in turns))

    for request_id, _, entrypoint in turns:
        _assert_turn_sent(
            title_calling_turns, real_job_queue.manager, request_id, _title_tags(entrypoint)
        )
    assert outer == [None, None]


def _text_completion() -> dict:
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "A Title"}}],
    }


def _turn_workspace(monkeypatch) -> MockChatCompletionsWorkspace:
    """A mock-transport workspace for a whole graph turn: a request that binds tools (a
    graph agent's) gets a call to the first one, any other (the title's) plain text."""
    from tests.fixtures.deterministic_model_adapter import fake_output

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(fake_output("data_analyst"), usage=None)
    answer_with_the_tool = workspace._handle

    def handle(request):
        if json.loads(request.content).get("tools"):
            return answer_with_the_tool(request)
        workspace.requests.append(request)
        return httpx.Response(200, json=_text_completion())

    workspace._handle = handle
    return workspace


def _run_an_agent_turn(monkeypatch, submit, request_id: str) -> SimpleNamespace:
    """Send one Agent deck's turn with ``submit`` and run it on the REAL worker and the REAL
    chat service's graph limb.

    Its graph thread makes a production adapter call (``DatabricksModelAdapter()``: the
    default model factory, as the service principal) and, on a deck's first message, its
    title thread makes a production title call.  Stubbed: ``invoke_graph`` (it makes that
    one adapter call instead of running a pinned Graph Release), the service's deck store
    and its own collaborators (``_service_double``, ``_service_env``: settings, its session
    manager, the liveness poll and the seal), ``has_generation_snapshot``,
    ``get_system_client`` and the HTTP layer (a mock transport).  Returns the graph calls,
    the title calls, the graph threads' names and ``_run_turns``' outer entrypoints.
    """
    from src.domain.skill_io import OUTPUT_SCHEMAS
    from src.services.agent_runtime import AgentModelConfiguration, DatabricksModelAdapter
    from tests.unit.test_stage_slide_wiring import _service_double, _service_env

    workspace = _turn_workspace(monkeypatch)
    monkeypatch.setattr("src.core.databricks_client.get_system_client", lambda: workspace)
    graph_threads = []

    def invoke_graph(session_id, initial=None, **kwargs):
        graph_threads.append(threading.current_thread().name)
        DatabricksModelAdapter().invoke(
            agent_key="data_analyst",
            configuration=AgentModelConfiguration(
                endpoint_name="system.ai.claude-opus-5-5",
                temperature=0.7,
                max_tokens=64,
                top_p=0.95,
            ),
            schema=OUTPUT_SCHEMAS["data_analyst"],
            prompt="assembled analyst prompt",
        )
        return {}

    chat_service = _service_double()
    with (
        _service_env(),
        # Inside _service_env, so this stub replaces its recorder.
        patch("src.services.graph.builder.invoke_graph", invoke_graph),
        patch("src.services.generation_rollback.has_generation_snapshot", return_value=False),
    ):
        monkeypatch.setattr("src.api.services.chat_service.get_chat_service", lambda: chat_service)
        outer = _run_turns(submit(request_id))

    return SimpleNamespace(
        graph_calls=[r for r in workspace.requests if json.loads(r.content).get("tools")],
        title_calls=[r for r in workspace.requests if not json.loads(r.content).get("tools")],
        graph_threads=graph_threads,
        outer=outer,
    )


def test_an_agent_decks_turn_from_the_app_tags_its_graph_and_title_calls(
    real_job_queue, monkeypatch
):
    """The whole Agent-deck turn: the REAL route enters it through the shared Enter and the
    REAL worker runs the REAL chat service's graph limb.  The graph thread and the title
    thread each run in a copy of the job's context, so each call carries the app
    entrypoint beside its own component."""
    turn = _run_an_agent_turn(monkeypatch, _app_route(monkeypatch, deck_mode=None), "req-agent")

    real_job_queue.manager.complete_chat_request.assert_called_once()
    threads = turn.graph_threads
    assert len(threads) == 1 and not threads[0].startswith("chat-job"), threads
    sent = (turn.graph_calls, turn.title_calls)
    assert (len(turn.graph_calls), len(turn.title_calls)) == (1, 1), sent
    _assert_sent_with_tags(
        turn.graph_calls[0], {"source": "tellr", "component": "generation", "entrypoint": "app"}
    )
    _assert_sent_with_tags(
        turn.title_calls[0], {"source": "tellr", "component": "title", "entrypoint": "app"}
    )
    assert turn.outer == [None, None]


@pytest.mark.parametrize("tool", _MCP_TOOLS)
def test_an_agent_decks_turn_from_mcp_tags_its_graph_and_title_calls(
    real_job_queue, monkeypatch, tool
):
    """MCP decks are Agent decks: ``create_deck`` makes one and ``edit_deck`` enters only
    one.  The REAL tool implementation enters the turn through ``_enter_turn_or_tool_error``
    and the shared Enter (``_mcp_tool``), and the REAL worker runs the REAL chat service's
    graph limb (``_run_an_agent_turn``).  The graph call carries ``mcp`` beside the
    ``generation`` component.  A new deck's first turn (``create_deck``) also makes its
    title call, which carries ``mcp`` beside ``title``; an edit of a deck that already has
    messages makes no title call."""
    request_id = f"req-agent-{tool}"
    turn = _run_an_agent_turn(monkeypatch, _mcp_tool(monkeypatch, tool=tool), request_id)

    real_job_queue.manager.complete_chat_request.assert_called_once_with(request_id, ANY)
    threads = turn.graph_threads
    assert len(threads) == 1 and not threads[0].startswith("chat-job"), threads
    titles = 1 if tool == "create_deck" else 0
    sent = (turn.graph_calls, turn.title_calls)
    assert (len(turn.graph_calls), len(turn.title_calls)) == (1, titles), sent
    _assert_sent_with_tags(
        turn.graph_calls[0], {"source": "tellr", "component": "generation", "entrypoint": "mcp"}
    )
    for title_call in turn.title_calls:
        _assert_sent_with_tags(
            title_call, {"source": "tellr", "component": "title", "entrypoint": "mcp"}
        )
    assert turn.outer == [None, None]


def test_a_legacy_decks_turn_tags_its_title_call_through_the_real_chat_service(
    real_job_queue, monkeypatch
):
    """The Legacy (monolith) limb of the REAL chat service, reached from the real browser
    route through the real worker.  Only the browser sends turns to Legacy decks: MCP's
    ``create_deck`` makes Agent decks and its ``edit_deck`` refuses a Legacy deck.  The
    Legacy engine's deck calls build no Gateway client, so the turn's first-message title
    call is its one tagged request.  The limb makes that call on its own title thread,
    started in a copy of the job's context, so it carries the app entrypoint beside the
    ``title`` component.  Stubbed: the deck store (``_get_or_load_deck``), the agent
    (``_build_agent_for_session``; it returns no HTML, so no deck is saved), two helpers
    (``_persist_genie_conversation_ids``, ``_substitute_images_for_response``), the session
    managers, the settings, ``get_system_client`` and the HTTP layer (a mock transport);
    the route's own stubs are in ``_app_route``."""
    from src.api.services.chat_service import ChatService

    workspace = _text_workspace(monkeypatch)
    calling_threads = []
    answer = workspace._handle

    def handle(request):
        calling_threads.append(threading.current_thread().name)
        return answer(request)

    workspace._handle = handle
    monkeypatch.setattr("src.core.databricks_client.get_system_client", lambda: workspace)

    agent = MagicMock()
    agent.generate_slides_streaming.return_value = {"html": "", "metadata": {}}
    service = ChatService.__new__(ChatService)
    service._deck_cache = {}
    service._cache_lock = threading.Lock()
    service._get_or_load_deck = MagicMock(return_value=None)
    service._build_agent_for_session = MagicMock(
        return_value=(agent, {"genie_conversation_id": None}, None)
    )
    service._persist_genie_conversation_ids = MagicMock()
    service._substitute_images_for_response = MagicMock(
        side_effect=lambda deck, raw_html=None, *, session_id: (deck, raw_html)
    )
    service_manager = MagicMock()
    service_manager.get_session.return_value = {"message_count": 1, "genie_conversation_id": None}
    monkeypatch.setattr(
        "src.api.services.chat_service.get_session_manager", lambda: service_manager
    )
    monkeypatch.setattr("src.core.settings_db.get_settings", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("src.api.services.chat_service.get_chat_service", lambda: service)
    submit, session_id = _app_route(monkeypatch, deck_mode="legacy"), "s-app"
    request_id = "req-legacy-app"

    outer = _run_turns(submit(request_id))

    real_job_queue.manager.update_chat_request_status.assert_any_call(request_id, "completed")
    # The monolith limb ran the turn: it built its agent and ran it once.
    service._build_agent_for_session.assert_called_once()
    agent.generate_slides_streaming.assert_called_once()
    assert len(workspace.requests) == 1, workspace.requests
    _assert_sent_with_tags(
        workspace.requests[0], {"source": "tellr", "component": "title", "entrypoint": "app"}
    )
    # Sent from the limb's own title thread, not from the chat-job thread the job runs on.
    assert len(calling_threads) == 1, calling_threads
    assert not calling_threads[0].startswith("chat-job"), calling_threads
    # ``run_title_gen`` ran to its end: the session took the model's title.
    service_manager.rename_session.assert_called_once_with(session_id, "ok")
    assert outer == [None, None]


# --- the two entry sites mark their entrypoint before the shared Enter enqueues ---


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _set_entrypoint_literals(source: str) -> list[object]:
    """The value each ``set_entrypoint(...)`` call in ``source`` passes (or ``_NOT_LITERAL``)."""
    values = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _called_name(node) == "set_entrypoint":
            passed = [*node.args, *(kw.value for kw in node.keywords)]
            literal = len(passed) == 1 and isinstance(passed[0], ast.Constant)
            values.append(passed[0].value if literal else _NOT_LITERAL)
    return values


def _sets_entrypoint(statement: ast.stmt, value: str) -> bool:
    """``set_entrypoint(value)`` as a statement of its own, ``value`` passed as a literal."""
    if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)):
        return False
    call = statement.value
    passed = [*call.args, *(kw.value for kw in call.keywords if kw.arg in (None, "value"))]
    return (
        _called_name(call) == "set_entrypoint"
        and len(passed) == 1
        and len(call.args) + len(call.keywords) == 1
        and isinstance(passed[0], ast.Constant)
        and passed[0].value == value
    )


def _entrypoint_set_before_each_call(source: str, callee: str, value: str) -> list[bool]:
    """For each call to ``callee`` in ``source``: whether ``set_entrypoint(value)`` runs on
    every path to it, earlier in its own function.

    That holds when the set is a statement of the block holding the call's statement, or of
    a block holding a statement that encloses it, and comes before it there.  A set inside
    a branch, after the call, in another function or at module level does not count.
    """
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    results = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _called_name(call) == callee):
            continue
        node, dominated = call, False
        while not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
            parent = parents[node]
            if isinstance(node, ast.stmt):
                for field in ("body", "orelse", "finalbody"):
                    block = getattr(parent, field, None)
                    if not isinstance(block, list):
                        continue
                    for index, statement in enumerate(block):
                        if statement is node and any(
                            _sets_entrypoint(earlier, value) for earlier in block[:index]
                        ):
                            dominated = True
            node = parent
        results.append(dominated)
    return results


def _async_function(*body: str, before: str = "") -> str:
    """Source of ``async def f(x)`` whose lines are ``body`` (indented once), after ``before``."""
    return before + "async def f(x):\n" + "".join(f"    {line}\n" for line in body)


_SET_APP = 'set_entrypoint("app")'
_ENTER = "await enter_chat_turn(r, p)"

_ENTER_READER_CASES = {
    "set-first": (_async_function(_SET_APP, _ENTER), [True]),
    "through-the-module": (_async_function(f"attribution.{_SET_APP}", _ENTER), [True]),
    "by-keyword": (_async_function('set_entrypoint(value="app")', _ENTER), [True]),
    "before-the-enclosing-statements": (
        _async_function(
            _SET_APP, "try:", "    if x:", f"        {_ENTER}", "finally:", "    pass"
        ),
        [True],
    ),
    "before-a-try-whose-body-assigns-the-call": (
        _async_function(_SET_APP, "try:", f"    entered: T = {_ENTER}", "except E:", "    raise"),
        [True],
    ),
    "each-call": (_async_function(_SET_APP, _ENTER, _ENTER), [True, True]),
    "set-after": (_async_function(_ENTER, _SET_APP), [False]),
    "set-in-a-branch": (_async_function("if x:", f"    {_SET_APP}", _ENTER), [False]),
    "set-in-the-try-the-call-is-the-finally-of": (
        _async_function("try:", f"    {_SET_APP}", "finally:", f"    {_ENTER}"),
        [False],
    ),
    "set-at-module-level": (_async_function(_ENTER, before=f"{_SET_APP}\n"), [False]),
    "set-in-another-function": (
        _async_function(_ENTER, before=f"def g():\n    {_SET_APP}\n"),
        [False],
    ),
    "the-other-entrypoint": (_async_function('set_entrypoint("mcp")', _ENTER), [False]),
    "not-a-literal": (_async_function("set_entrypoint(x)", _ENTER), [False]),
    "commented-out": (_async_function(f"# {_SET_APP}", _ENTER), [False]),
}


@pytest.mark.parametrize(
    "source, expected", list(_ENTER_READER_CASES.values()), ids=list(_ENTER_READER_CASES)
)
def test_the_entry_reader_counts_only_a_set_on_every_path_before_the_call(source, expected):
    assert _entrypoint_set_before_each_call(source, "enter_chat_turn", "app") == expected


def _uses(source: str, name: str) -> list[tuple[str, str]]:
    """``(function, kind)`` for each place ``source`` names ``name``, in source order.

    ``function`` is the innermost enclosing ``def`` (``<module>`` outside one).  ``kind`` is
    ``defines`` (its ``def``), ``imports`` (an import of it, under any alias), ``calls`` (a
    call by its own name, or as ``module.<name>``) or ``refers`` (any other mention in code:
    a callback, an assignment, an attribute such as ``.set``).  Prose and comments are not
    uses.  A call through an import alias is not a ``calls`` of ``name``: the import is.
    """
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}

    def function_of(node: ast.AST) -> str:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    uses = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            kind = "defines"
        elif isinstance(node, ast.alias) and node.name == name:
            kind = "imports"
        elif (isinstance(node, ast.Name) and node.id == name) or (
            isinstance(node, ast.Attribute) and node.attr == name
        ):
            kind = "calls" if id(node) in called else "refers"
        else:
            continue
        uses.append((node.lineno, node.col_offset, function_of(node), kind))
    return [(function, kind) for _, _, function, kind in sorted(uses)]


def test_the_use_reader_names_each_use_by_its_function_and_kind():
    source = (
        "from src.api.routes.chat import enter_chat_turn as enter\n"
        "from src.api.routes import chat\n"
        "async def enter_chat_turn(**kwargs):\n"
        "    pass\n"
        "async def a():\n"
        "    await chat.enter_chat_turn(x)\n"
        "    await enter(x)\n"
        "def b():\n"
        "    callback = enter_chat_turn\n"
        "    def inner():\n"
        "        enter_chat_turn()\n"
        '    """enter_chat_turn() in prose"""\n'
        "    # enter_chat_turn() in a comment\n"
    )
    assert _uses(source, "enter_chat_turn") == [
        ("<module>", "imports"),
        ("<module>", "defines"),
        ("a", "calls"),
        ("b", "refers"),
        ("inner", "calls"),
    ]


def _uses_in_src(name: str) -> list[tuple[str, str, str]]:
    """``(file, function, kind)`` for every use of ``name`` under ``src`` (``_uses``)."""
    src = Path(__file__).resolve().parents[2] / "src"
    return [
        (path.relative_to(src).as_posix(), function, kind)
        for path in sorted(src.rglob("*.py"))
        for function, kind in _uses(path.read_text(), name)
    ]


def test_each_entry_site_marks_its_entrypoint_before_the_shared_enter():
    """``enqueue_job`` copies the context it is called in, and its one call is in the shared
    Enter, ``enter_chat_turn``, which each entry site awaits in its own task: the browser
    route (``submit_chat_async``) and the MCP server (``_enter_turn_or_tool_error``, which
    every MCP tool that starts a turn calls).  So a turn carries an entrypoint only if its
    entry site set it on every path to its call into the Enter, in the same function,
    before it.  The two entry sites are the only callers of the Enter and the only places in
    ``src`` that mark a turn, each once and with its own value; nothing else touches the
    ContextVar.  The Enter marks nothing: a mark there would give every turn that passes
    through it, from either site, the same value.  And each site is reached only from its
    own side: the browser route by its route alone, and each MCP tool's implementation by
    its own tool alone, which only its MCP registration reaches.  An MCP tool that reused
    the route would send ``app``, and a browser route that reused an MCP tool would send
    ``mcp``."""
    assert _uses_in_src("enqueue_job") == [
        ("api/routes/chat.py", "<module>", "imports"),
        ("api/routes/chat.py", "enter_chat_turn", "calls"),
        ("api/services/job_queue.py", "<module>", "defines"),
    ]
    assert _uses_in_src("enter_chat_turn") == [
        ("api/mcp_server.py", "<module>", "imports"),
        ("api/mcp_server.py", "_enter_turn_or_tool_error", "calls"),
        ("api/routes/chat.py", "<module>", "defines"),
        ("api/routes/chat.py", "submit_chat_async", "calls"),
    ]
    # The MCP tools that start a turn, each run end to end by the tests above (_MCP_TOOLS).
    assert _uses_in_src("_enter_turn_or_tool_error") == [
        ("api/mcp_server.py", "<module>", "defines"),
        *(("api/mcp_server.py", f"_{tool}_impl", "calls") for tool in _MCP_TOOLS),
    ]
    # The functions one level above the marks: who reaches each decides its value.
    assert _uses_in_src("submit_chat_async") == [("api/routes/chat.py", "<module>", "defines")]
    for tool in _MCP_TOOLS:
        assert _uses_in_src(f"_{tool}_impl") == [
            ("api/mcp_server.py", tool, "calls"),
            ("api/mcp_server.py", "<module>", "defines"),
        ], tool
        assert _uses_in_src(tool) == [("api/mcp_server.py", "<module>", "defines")], tool
    markers = _uses_in_src("set_entrypoint")
    assert ("api/routes/chat.py", "enter_chat_turn", "calls") not in markers, (
        "the shared Enter marks every turn that passes through it with one value"
    )
    assert markers == [
        ("api/mcp_server.py", "<module>", "imports"),
        ("api/mcp_server.py", "_enter_turn_or_tool_error", "calls"),
        ("api/routes/chat.py", "<module>", "imports"),
        ("api/routes/chat.py", "submit_chat_async", "calls"),
        ("core/attribution.py", "<module>", "defines"),
    ]
    assert {path for path, _, _ in _uses_in_src("_entrypoint_var")} == {"core/attribution.py"}

    src = Path(__file__).resolve().parents[2] / "src"
    for relative, value in (("api/routes/chat.py", "app"), ("api/mcp_server.py", "mcp")):
        source = (src / relative).read_text()
        assert _entrypoint_set_before_each_call(source, "enter_chat_turn", value) == [True], (
            relative
        )
        assert _set_entrypoint_literals(source) == [value], relative
