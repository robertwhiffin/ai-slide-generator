"""Building one agent run's AI Gateway MCP tools (gateway-mcp Task 5).

``build_gateway_tools`` joins a deck's ``gateway_mcp`` entries to the admin
registry, lists each service's tools AS THE USER (in parallel, one worker per
connection), applies the allowlist, names the tools for the model and reports
every connection it could not bind as a ``GatewayFailure``:

- a row-less entry is ``removed``, reported by the architect pass only; a
  disabled row is ``removed`` for its own agent only; a row for the other agent
  is silently skipped;
- a token whose scopes are known and lack ``ai-gateway`` builds nothing: one
  ``missing_scope`` per connection (PLAN-CORRECTIONS T5.1);
- a list-time ``GatewayMcpError`` keeps its kind (a timeout is ``unavailable``)
  and the other connections still bind.

``model_tool_names`` keeps unique names, prefixes clashes (and the reserved
``genie`` / output-schema names, T5.2) with the service slug, truncates to 64
and suffixes post-truncation clashes.  ``turn_budget`` is the per-turn budget;
``failure_notice`` is the exact Global Constraints copy.

Doubles: the Gateway client (``client_factory=``) and, for the image test, the
DB session and ``image_service.upload_image``.  Task 4's ``GatewayMcpAgentTool``
is production's, so routing is checked by RUNNING each built tool, through the
loop's own ``_answer_tool_call`` where the loop matters.
"""

from __future__ import annotations

import ast
import base64
import dataclasses
import inspect
import io
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from src.api.schemas.agent_config import GatewayMcpTool
from src.core.scope_errors import consent_message, oauth_scopes_from_token
from src.services import image_service
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools import gateway_tool
from src.services.agent_tools.gateway_mcp import GatewayMcpError, GatewayToolSpec
from src.services.agent_tools.gateway_toolset import (
    ANALYST_GATEWAY_BUDGET_SECONDS,
    ANALYST_GATEWAY_MAX_CALLS,
    ARCHITECT_GATEWAY_BUDGET_SECONDS,
    ARCHITECT_GATEWAY_MAX_CALLS,
    GATEWAY_TURN_DEADLINE_SECONDS,
    GatewayFailure,
    GatewayToolsetBuild,
    build_gateway_tools,
    failure_notice,
    model_tool_names,
    turn_budget,
)
from src.services.agent_tools.toolset import AgentToolset, ToolAccessError
from src.services.gateway_mcp_registry import GatewayConnection
from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN
from src.utils.spotlight import spotlight

REPO = Path(__file__).resolve().parents[2]

HOST = "https://fevm-db-tellr-dev-workspace.cloud.databricks.com"
#: Not a JWT, so its scopes are unknown (``oauth_scopes_from_token`` -> None).
TOKEN = "dapi-user-token"
USER = "alice@example.com"

WEB = "system.ai.web_search"
DOCS = "main.tools.docs"
LAKEDRAW = "db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw"
SIGN_IN_URL = HOST + "/mcp-service-login?name=" + LAKEDRAW + "&o=7474645249186749"

#: Every model-facing tool name (Review Focus 5).
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: U+00B7 and U+2014, as the Global Constraints copy has them.
DOT = "·"
DASH = "—"


# ---------------------------------------------------------------------------
# Doubles and builders
# ---------------------------------------------------------------------------


def _conn(
    service_name: str,
    display_name: str,
    *,
    agent: str = "architect",
    instructions: str | None = None,
    allowlist: tuple[str, ...] | None = None,
    enabled: bool = True,
    id: int = 1,
) -> GatewayConnection:
    return GatewayConnection(
        id=id,
        service_name=service_name,
        display_name=display_name,
        description=None,
        agent=agent,  # type: ignore[arg-type]
        instructions=instructions,
        tool_allowlist=allowlist,
        enabled=enabled,
        created_by="admin@example.com",
        created_at=None,
        updated_by="admin@example.com",
        updated_at=None,
    )


def _entry(service_name: str, display_name: str) -> GatewayMcpTool:
    return GatewayMcpTool(type="gateway_mcp", service_name=service_name, display_name=display_name)


def _spec(
    name: str, description: str = "", schema: dict[str, Any] | None = None
) -> GatewayToolSpec:
    return GatewayToolSpec(
        name=name,
        description=description,
        input_schema=schema if schema is not None else {"type": "object", "properties": {}},
    )


def _text_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)


class FakeClient:
    """A ``GatewayMcpClient`` double for one service.

    ``list_tools`` runs ``before_list`` (a barrier, a sleep), then raises
    ``list_error`` or returns ``tools``.  ``call_tool`` records ``(name, args)``
    and raises ``call_error`` or returns ``call_result`` (default: a text block
    naming the service, so a test can tell which service answered).
    """

    def __init__(
        self,
        service_name: str,
        tools: list[GatewayToolSpec] | tuple[GatewayToolSpec, ...] = (),
        *,
        list_error: BaseException | None = None,
        before_list: Any = None,
        call_error: BaseException | None = None,
        call_result: CallToolResult | None = None,
    ) -> None:
        self.service_name = service_name
        self.tools = list(tools)
        self.list_error = list_error
        self.before_list = before_list
        self.call_error = call_error
        self.call_result = call_result
        self.list_calls = 0
        self.calls: list[tuple[str, Any]] = []

    def list_tools(self, **kwargs: Any) -> list[GatewayToolSpec]:
        self.list_calls += 1
        if self.before_list is not None:
            self.before_list()
        if self.list_error is not None:
            raise self.list_error
        return list(self.tools)

    def call_tool(self, name: str, arguments: Any, *, timeout_seconds: float = 90) -> Any:
        self.calls.append((name, arguments))
        if self.call_error is not None:
            raise self.call_error
        if self.call_result is not None:
            return self.call_result
        return _text_result("answer from " + self.service_name)


class Factory:
    """The ``client_factory`` double: records every call's kwargs and returns the
    fake for its ``service_name``.  Keyword-only, like ``GatewayMcpClient``."""

    def __init__(self, *clients: FakeClient) -> None:
        self.by_service = {client.service_name: client for client in clients}
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, **kwargs: Any) -> FakeClient:
        with self._lock:
            self.calls.append(kwargs)
        return self.by_service[kwargs["service_name"]]

    @property
    def services_built(self) -> list[str]:
        return sorted(call["service_name"] for call in self.calls)


def _build(
    entries: list[GatewayMcpTool],
    registry: dict[str, GatewayConnection],
    factory: Factory,
    *,
    agent: str = "architect",
    token: str = TOKEN,
    on_call: Any = None,
    **kwargs: Any,
) -> GatewayToolsetBuild:
    return build_gateway_tools(
        entries,
        agent=agent,  # type: ignore[arg-type]
        registry=registry,
        host=HOST,
        token=token,
        user=USER,
        on_call=on_call if on_call is not None else (lambda line: None),
        session_id="session-1",
        client_factory=factory,
        **kwargs,
    )


def _run(tool: Any, args: dict[str, Any] | None = None, remaining: float = 60.0) -> str:
    """Run a built tool as the loop does: args parsed with its ``args_schema``."""
    return tool.run(tool.args_schema.model_validate(args or {}), remaining_seconds=remaining)


def _answer(tool_by_name: dict[str, Any], toolset: AgentToolset, name: str, args: dict, cid: str):
    """One tool call answered by the runtime loop's own dispatcher."""
    return DatabricksModelAdapter._answer_tool_call(
        {"name": name, "args": dict(args), "id": cid, "type": "tool_call"},
        tool_by_name,
        toolset,
        budget_text="Tool budget exhausted.",
    )


def _brief(failure: GatewayFailure) -> tuple[Any, ...]:
    """The failure fields every kind pins (``message`` is pinned where it matters)."""
    return (failure.display_name, failure.service_name, failure.kind, failure.sign_in_url)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict[str, Any]) -> str:
    return (
        _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        + "."
        + _b64url(json.dumps(payload).encode())
        + ".sig"
    )


def _png(size: tuple[int, int] = (4, 3)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _image_result(data: bytes) -> CallToolResult:
    return CallToolResult(
        content=[
            ImageContent(
                type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png"
            )
        ],
        isError=False,
    )


# ---------------------------------------------------------------------------
# Collisions and routing (Review Focus 5)
# ---------------------------------------------------------------------------


def test_two_connections_both_exposing_search_are_prefixed_and_route_correctly():
    """Two bound services both list ``search``: both are renamed with their service
    slug, the names are unique and model-safe, and each name runs ITS service's
    ``search`` (by the MCP name, with the model's args), with that connection's
    progress line and spotlight source."""
    web_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    docs_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    web = FakeClient(WEB, [_spec("search", "Search the web.", web_schema)])
    docs = FakeClient(DOCS, [_spec("search", "Search the docs.", docs_schema)])
    progress: list[str] = []

    build = _build(
        [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")],
        {WEB: _conn(WEB, "Web Search", id=1), DOCS: _conn(DOCS, "Docs", id=2)},
        Factory(web, docs),
        on_call=progress.append,
    )

    assert build.failures == ()
    names = [tool.name for tool in build.tools]
    assert len(names) == 2
    assert len(set(names)) == 2
    assert all(NAME_RE.fullmatch(name) for name in names), names
    assert sorted(names) == ["docs__search", "web_search__search"]
    by_name = {tool.name: tool for tool in build.tools}
    # Each model name carries its own service's spec.
    assert by_name["web_search__search"].parameters_json_schema == web_schema
    assert by_name["docs__search"].parameters_json_schema == docs_schema

    toolset = AgentToolset(tools=build.tools, max_calls=12, budget_seconds=360.0)
    web_answer = _answer(by_name, toolset, "web_search__search", {"query": "lakehouse"}, "c1")

    assert web.calls == [("search", {"query": "lakehouse"})]
    assert docs.calls == []
    assert web_answer == spotlight("Web Search", "answer from " + WEB)

    docs_answer = _answer(by_name, toolset, "docs__search", {"q": "unity catalog"}, "c2")

    assert docs.calls == [("search", {"q": "unity catalog"})]
    assert web.calls == [("search", {"query": "lakehouse"})]
    assert docs_answer == spotlight("Docs", "answer from " + DOCS)
    assert progress == ["Web Search " + DOT + " search", "Docs " + DOT + " search"]
    assert toolset.calls_made == 2
    assert toolset.access_errors == []


def test_unique_names_are_kept():
    names = model_tool_names({WEB: ["search", "fetch_page"], DOCS: ["lookup"]})

    assert names == {
        (WEB, "search"): "search",
        (WEB, "fetch_page"): "fetch_page",
        (DOCS, "lookup"): "lookup",
    }


def test_unique_names_are_kept_by_the_built_tools():
    web = FakeClient(WEB, [_spec("search"), _spec("fetch_page")])
    docs = FakeClient(DOCS, [_spec("lookup")])

    build = _build(
        [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")],
        {WEB: _conn(WEB, "Web Search"), DOCS: _conn(DOCS, "Docs", id=2)},
        Factory(web, docs),
    )

    assert sorted(tool.name for tool in build.tools) == ["fetch_page", "lookup", "search"]


def test_only_the_colliding_names_are_prefixed():
    names = model_tool_names({WEB: ["search", "fetch_page"], DOCS: ["search", "lookup"]})

    assert names == {
        (WEB, "search"): "web_search__search",
        (WEB, "fetch_page"): "fetch_page",
        (DOCS, "search"): "docs__search",
        (DOCS, "lookup"): "lookup",
    }


def test_services_with_the_same_last_part_get_the_schema_part_in_their_slug():
    """The slug is the service's last part, made unique by adding the schema part
    when two clashing services share that last part.  A service whose last part is
    unique keeps the bare slug."""
    a = "cat_a.alpha.search_svc"
    b = "cat_b.beta.search_svc"
    c = "cat_c.gamma.other"

    names = model_tool_names({a: ["query"], b: ["query"], c: ["query"]})

    a_name, b_name, c_name = names[(a, "query")], names[(b, "query")], names[(c, "query")]
    assert len({a_name, b_name, c_name}) == 3
    assert all(NAME_RE.fullmatch(name) for name in (a_name, b_name, c_name))
    assert c_name == "other__query"
    assert a_name.endswith("__query") and "alpha" in a_name and "search_svc" in a_name
    assert "beta" not in a_name
    assert b_name.endswith("__query") and "beta" in b_name and "search_svc" in b_name
    assert "alpha" not in b_name


def test_reserved_names_are_prefixed():
    """T5.2: ``genie`` (Genie One's tool) and the output-schema tool names the loop
    binds beside the Gateway tools are never taken by a Gateway tool."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from src.domain.skill_io import AnalystOutput, ArchitectOutput
    from src.services.agent_tools.registry import GENIE_TOOL_NAME

    # Guard: these are the names the model actually sees for those tools.
    assert GENIE_TOOL_NAME == "genie"
    assert convert_to_openai_tool(ArchitectOutput)["function"]["name"] == "ArchitectOutput"
    assert convert_to_openai_tool(AnalystOutput)["function"]["name"] == "AnalystOutput"

    names = model_tool_names({DOCS: ["genie", "ArchitectOutput", "AnalystOutput", "search"]})

    assert names == {
        (DOCS, "genie"): "docs__genie",
        (DOCS, "ArchitectOutput"): "docs__ArchitectOutput",
        (DOCS, "AnalystOutput"): "docs__AnalystOutput",
        (DOCS, "search"): "search",
    }


def test_long_names_truncated_and_deduplicated():
    # A unique name over 64 characters is truncated.
    long_unique = "t" * 80
    assert model_tool_names({WEB: [long_unique]}) == {(WEB, long_unique): "t" * 64}

    # A prefixed name is truncated after prefixing.
    tail = "s" * 60
    prefixed = model_tool_names({WEB: [tail], DOCS: [tail]})
    assert prefixed == {
        (WEB, tail): ("web_search__" + tail)[:64],
        (DOCS, tail): ("docs__" + tail)[:64],
    }

    # Names that clash only after truncation get _2, _3 ... and stay within 64.
    base = "x" * 70
    clashing = [base + "a", base + "b", base + "c"]
    names = model_tool_names({DOCS: clashing})
    assert set(names) == {(DOCS, name) for name in clashing}
    assert sorted(names.values()) == sorted(["x" * 64, "x" * 62 + "_2", "x" * 62 + "_3"])
    assert all(NAME_RE.fullmatch(name) for name in names.values())
    # Deterministic: the same input names the same tools the same way.
    assert model_tool_names({DOCS: clashing}) == names


def test_names_are_sanitised_to_the_model_alphabet_and_stay_unique():
    names = model_tool_names(
        {WEB: ["get.weather", "list files", "näme", "a/b"], DOCS: ["get_weather"]}
    )

    values = list(names.values())
    assert len(values) == 5
    assert len(set(values)) == 5
    assert all(NAME_RE.fullmatch(name) for name in values), values


def test_a_sanitised_tool_still_calls_the_service_by_its_own_name():
    web = FakeClient(WEB, [_spec("get.weather", "Weather.")])

    build = _build([_entry(WEB, "Web Search")], {WEB: _conn(WEB, "Web Search")}, Factory(web))

    (tool,) = build.tools
    assert NAME_RE.fullmatch(tool.name)
    out = _run(tool, {"city": "Paris"})
    assert web.calls == [("get.weather", {"city": "Paris"})]
    assert out == spotlight("Web Search", "answer from " + WEB)


# ---------------------------------------------------------------------------
# Joining entries to the registry
# ---------------------------------------------------------------------------


def test_allowlist_filters_tools():
    docs = FakeClient(DOCS, [_spec("search"), _spec("lookup"), _spec("delete_everything")])

    build = _build(
        [_entry(DOCS, "Docs")],
        {DOCS: _conn(DOCS, "Docs", allowlist=("search", "lookup", "not_listed"))},
        Factory(docs),
    )

    assert build.failures == ()
    assert sorted(tool.name for tool in build.tools) == ["lookup", "search"]


def test_no_allowlist_binds_every_tool():
    docs = FakeClient(DOCS, [_spec("search"), _spec("lookup"), _spec("delete_everything")])

    build = _build([_entry(DOCS, "Docs")], {DOCS: _conn(DOCS, "Docs")}, Factory(docs))

    assert sorted(tool.name for tool in build.tools) == ["delete_everything", "lookup", "search"]


def test_a_service_listing_one_name_twice_binds_it_once():
    """Two tools of one name in a request make the provider reject the whole call,
    so a service that lists a name twice binds only its first listing."""
    docs = FakeClient(
        DOCS, [_spec("search", "First."), _spec("lookup"), _spec("search", "Second.")]
    )

    build = _build([_entry(DOCS, "Docs")], {DOCS: _conn(DOCS, "Docs")}, Factory(docs))

    assert [tool.name for tool in build.tools] == ["search", "lookup"]
    assert build.tools[0].description == "Docs: First."


def test_a_tool_left_out_by_the_allowlist_does_not_force_a_prefix():
    """Collisions are resolved over the BOUND tools: Docs' ``search`` is not
    allowlisted, so Web Search's ``search`` keeps its own name."""
    web = FakeClient(WEB, [_spec("search")])
    docs = FakeClient(DOCS, [_spec("search"), _spec("lookup")])

    build = _build(
        [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")],
        {WEB: _conn(WEB, "Web Search"), DOCS: _conn(DOCS, "Docs", id=2, allowlist=("lookup",))},
        Factory(web, docs),
    )

    by_name = {tool.name: tool for tool in build.tools}
    assert sorted(by_name) == ["lookup", "search"]
    _run(by_name["search"], {"query": "x"})
    assert web.calls == [("search", {"query": "x"})]
    assert docs.calls == []


def test_description_carries_the_connection_instructions():
    """T4.5: ``description_prefix`` is the connection's ``instructions``."""
    lakedraw = FakeClient(LAKEDRAW, [_spec("lakedraw_create_from_spec", "Create a diagram.")])
    web = FakeClient(WEB, [_spec("search", "Search the web.")])

    build = _build(
        [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        {
            LAKEDRAW: _conn(LAKEDRAW, "LakeDraw", instructions="Validate, then persist."),
            WEB: _conn(WEB, "Web Search", id=2),
        },
        Factory(lakedraw, web),
    )

    by_name = {tool.name: tool for tool in build.tools}
    assert by_name["lakedraw_create_from_spec"].description == (
        "LakeDraw: Validate, then persist.\n\nCreate a diagram."
    )
    assert by_name["search"].description == "Web Search: Search the web."


def test_wrong_agent_entries_skipped():
    """A row for the OTHER agent is skipped silently: no tools, no failure, and its
    service is never contacted.  Each agent's pass binds only its own."""
    entries = [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")]
    registry = {
        WEB: _conn(WEB, "Web Search", agent="architect"),
        DOCS: _conn(DOCS, "Docs", agent="data_analyst", id=2),
    }

    architect_factory = Factory(
        FakeClient(WEB, [_spec("search")]), FakeClient(DOCS, [_spec("lookup")])
    )
    architect = _build(entries, registry, architect_factory, agent="architect")

    assert [tool.name for tool in architect.tools] == ["search"]
    assert architect.failures == ()
    assert architect_factory.services_built == [WEB]
    assert architect_factory.by_service[DOCS].list_calls == 0

    analyst_factory = Factory(
        FakeClient(WEB, [_spec("search")]), FakeClient(DOCS, [_spec("lookup")])
    )
    analyst = _build(entries, registry, analyst_factory, agent="data_analyst")

    assert [tool.name for tool in analyst.tools] == ["lookup"]
    assert analyst.failures == ()
    assert analyst_factory.services_built == [DOCS]
    assert analyst_factory.by_service[WEB].list_calls == 0


def test_removed_connection_reported_once_by_architect():
    """Review Focus 1: an entry whose row is gone is ``removed``.  The architect pass
    reports it; the analyst pass does not (the user is told once).  Nothing is
    contacted for it."""
    entries = [_entry(LAKEDRAW, "LakeDraw")]

    architect_factory = Factory(FakeClient(LAKEDRAW, [_spec("lakedraw_create_from_spec")]))
    architect = _build(entries, {}, architect_factory, agent="architect")

    assert architect.tools == ()
    assert [_brief(f) for f in architect.failures] == [("LakeDraw", LAKEDRAW, "removed", None)]
    assert architect_factory.calls == []
    assert failure_notice(architect.failures[0], oauth_client_id=None) == (
        "LakeDraw is no longer available."
    )

    analyst_factory = Factory(FakeClient(LAKEDRAW, [_spec("lakedraw_create_from_spec")]))
    analyst = _build(entries, {}, analyst_factory, agent="data_analyst")

    assert analyst.tools == ()
    assert analyst.failures == ()
    assert analyst_factory.calls == []


def test_disabled_connection_is_removed_for_its_own_agent_only():
    entries = [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")]
    registry = {
        LAKEDRAW: _conn(LAKEDRAW, "LakeDraw", agent="data_analyst", enabled=False),
        WEB: _conn(WEB, "Web Search", agent="architect", enabled=False, id=2),
    }

    architect_factory = Factory(FakeClient(LAKEDRAW), FakeClient(WEB, [_spec("search")]))
    architect = _build(entries, registry, architect_factory, agent="architect")

    assert architect.tools == ()
    assert [_brief(f) for f in architect.failures] == [("Web Search", WEB, "removed", None)]
    assert architect_factory.calls == []

    analyst_factory = Factory(FakeClient(LAKEDRAW), FakeClient(WEB, [_spec("search")]))
    analyst = _build(entries, registry, analyst_factory, agent="data_analyst")

    assert analyst.tools == ()
    assert [_brief(f) for f in analyst.failures] == [("LakeDraw", LAKEDRAW, "removed", None)]
    assert analyst_factory.calls == []


def test_no_entries_builds_nothing():
    factory = Factory()

    build = _build([], {}, factory)

    assert build.tools == ()
    assert build.failures == ()
    assert build.saved_tokens() == []
    assert factory.calls == []


# ---------------------------------------------------------------------------
# Listing: as the user, in parallel, failures isolated
# ---------------------------------------------------------------------------


def test_sign_in_at_list_time_becomes_failure_with_url_and_other_connection_still_binds():
    """Review Focus 2: LakeDraw needs a sign-in, so it is left out with its sign-in
    link; Web Search still binds."""
    error = GatewayMcpError(
        "sign_in_required", "Not signed in to " + LAKEDRAW, sign_in_url=SIGN_IN_URL
    )
    lakedraw = FakeClient(LAKEDRAW, list_error=error)
    web = FakeClient(WEB, [_spec("search")])

    build = _build(
        [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        {LAKEDRAW: _conn(LAKEDRAW, "LakeDraw"), WEB: _conn(WEB, "Web Search", id=2)},
        Factory(lakedraw, web),
    )

    assert [tool.name for tool in build.tools] == ["search"]
    assert build.failures == (
        GatewayFailure(
            display_name="LakeDraw",
            service_name=LAKEDRAW,
            kind="sign_in_required",
            message="Not signed in to " + LAKEDRAW,
            sign_in_url=SIGN_IN_URL,
        ),
    )
    assert failure_notice(build.failures[0], oauth_client_id=None) == (
        "To use LakeDraw, sign in here: " + SIGN_IN_URL + " " + DASH + " then ask again."
    )


@pytest.mark.parametrize(
    ("error_kind", "failure_kind"),
    [
        ("sign_in_required", "sign_in_required"),
        ("missing_scope", "missing_scope"),
        ("access_denied", "access_denied"),
        ("not_found", "not_found"),
        ("unavailable", "unavailable"),
        ("timeout", "unavailable"),
    ],
)
def test_list_time_errors_keep_their_kind_and_message(error_kind, failure_kind):
    """A list-time ``GatewayMcpError`` becomes a failure of the same kind (a timeout
    is ``unavailable``: ``GatewayFailure`` has no ``timeout``), carrying the
    error's message (the unavailable notice's reason) and sign-in link."""
    url = SIGN_IN_URL if error_kind == "sign_in_required" else None
    message = "LakeDraw said " + error_kind
    error = GatewayMcpError(error_kind, message, sign_in_url=url)
    lakedraw = FakeClient(LAKEDRAW, list_error=error)
    web = FakeClient(WEB, [_spec("search")])

    build = _build(
        [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        {LAKEDRAW: _conn(LAKEDRAW, "LakeDraw"), WEB: _conn(WEB, "Web Search", id=2)},
        Factory(lakedraw, web),
    )

    assert [tool.name for tool in build.tools] == ["search"]
    assert build.failures == (
        GatewayFailure(
            display_name="LakeDraw",
            service_name=LAKEDRAW,
            kind=failure_kind,
            message=message,
            sign_in_url=url,
        ),
    )


def test_an_unexpected_listing_error_is_unavailable_and_does_not_escape():
    """Spec: "any other failure (unavailable)".  The build never raises for one
    connection's failure."""
    lakedraw = FakeClient(LAKEDRAW, list_error=RuntimeError("socket closed"))
    web = FakeClient(WEB, [_spec("search")])

    build = _build(
        [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        {LAKEDRAW: _conn(LAKEDRAW, "LakeDraw"), WEB: _conn(WEB, "Web Search", id=2)},
        Factory(lakedraw, web),
    )

    assert [tool.name for tool in build.tools] == ["search"]
    assert [_brief(f) for f in build.failures] == [("LakeDraw", LAKEDRAW, "unavailable", None)]


def test_services_are_listed_in_parallel_one_worker_per_connection():
    """Each listing waits at a 3-party barrier: it is passed only if all three
    connections are listed at the same time (a serial loop, or a pool smaller
    than the connection count, breaks the barrier after 5 s)."""
    barrier = threading.Barrier(3, timeout=5)
    services = ["c.s.one", "c.s.two", "c.s.three"]
    clients = [
        FakeClient(service, [_spec("tool_" + service.rsplit(".", 1)[1])], before_list=barrier.wait)
        for service in services
    ]
    registry = {
        service: _conn(service, "Svc " + str(index), id=index)
        for index, service in enumerate(services, start=1)
    }

    build = _build(
        [_entry(service, "Svc " + str(index)) for index, service in enumerate(services, 1)],
        registry,
        Factory(*clients),
    )

    assert build.failures == ()
    assert sorted(tool.name for tool in build.tools) == ["tool_one", "tool_three", "tool_two"]
    assert [client.list_calls for client in clients] == [1, 1, 1]


def test_tools_and_failures_follow_entry_order():
    """Whichever listing finishes first, tools and failures come out in the deck's
    entry order (a stable toolset across attempts)."""
    a, b, c, d = "c.s.alpha", "c.s.beta", "c.s.gamma", "c.s.delta"
    slow = lambda: time.sleep(0.3)  # noqa: E731
    clients = [
        FakeClient(a, [_spec("alpha_tool")], before_list=slow),
        FakeClient(b, [_spec("beta_tool")]),
        FakeClient(c, list_error=GatewayMcpError("not_found", "gone"), before_list=slow),
        FakeClient(d, list_error=GatewayMcpError("access_denied", "403")),
    ]
    names = {a: "Alpha", b: "Beta", c: "Gamma", d: "Delta"}

    build = _build(
        [_entry(service, names[service]) for service in (a, b, c, d)],
        {service: _conn(service, names[service], id=i) for i, service in enumerate(names, 1)},
        Factory(*clients),
    )

    assert [tool.name for tool in build.tools] == ["alpha_tool", "beta_tool"]
    assert [(f.display_name, f.kind) for f in build.failures] == [
        ("Gamma", "not_found"),
        ("Delta", "access_denied"),
    ]


def test_clients_are_built_as_the_user_with_the_tokens_scopes():
    """Every client is the signed-in user's: host, token, its service, and the
    scopes the token says it carries (T5.1)."""
    token = _jwt({"sub": USER, "scope": "ai-gateway sql"})
    factory = Factory(FakeClient(WEB, [_spec("search")]))

    _build([_entry(WEB, "Web Search")], {WEB: _conn(WEB, "Web Search")}, factory, token=token)

    (call,) = factory.calls
    assert {key: call.get(key) for key in ("host", "token", "service_name", "token_scopes")} == {
        "host": HOST,
        "token": token,
        "service_name": WEB,
        "token_scopes": frozenset({"ai-gateway", "sql"}),
    }
    assert call["token_scopes"] == oauth_scopes_from_token(token)


def test_unknown_token_scopes_are_passed_as_none():
    factory = Factory(FakeClient(WEB, [_spec("search")]))

    build = _build([_entry(WEB, "Web Search")], {WEB: _conn(WEB, "Web Search")}, factory)

    assert [tool.name for tool in build.tools] == ["search"]
    (call,) = factory.calls
    assert "token_scopes" in call
    assert call["token_scopes"] is None


def test_token_lacking_the_ai_gateway_scope_builds_nothing():
    """T5.1 (Genie's pre-flight): scopes known and lacking ``ai-gateway`` -> no
    client is built, and each of this agent's connections is one ``missing_scope``
    failure.  The other agent's connection is still skipped silently."""
    token = _jwt({"sub": USER, "scope": "sql offline_access"})
    factory = Factory(
        FakeClient(WEB, [_spec("search")]),
        FakeClient(LAKEDRAW, [_spec("lakedraw_create_from_spec")]),
        FakeClient(DOCS, [_spec("lookup")]),
    )

    build = _build(
        [_entry(WEB, "Web Search"), _entry(LAKEDRAW, "LakeDraw"), _entry(DOCS, "Docs")],
        {
            WEB: _conn(WEB, "Web Search", id=1),
            LAKEDRAW: _conn(LAKEDRAW, "LakeDraw", id=2),
            DOCS: _conn(DOCS, "Docs", agent="data_analyst", id=3),
        },
        factory,
        token=token,
    )

    assert build.tools == ()
    assert factory.calls == []
    assert sorted(_brief(f) for f in build.failures) == sorted(
        [("Web Search", WEB, "missing_scope", None), ("LakeDraw", LAKEDRAW, "missing_scope", None)]
    )
    assert failure_notice(build.failures[0], oauth_client_id="abc-123") == consent_message(
        oauth_client_id="abc-123"
    )


def test_an_all_apis_token_passes_the_scope_pre_flight():
    token = _jwt({"sub": USER, "scope": "all-apis offline_access"})
    factory = Factory(FakeClient(WEB, [_spec("search")]))

    build = _build(
        [_entry(WEB, "Web Search")], {WEB: _conn(WEB, "Web Search")}, factory, token=token
    )

    assert [tool.name for tool in build.tools] == ["search"]
    assert build.failures == ()
    assert factory.services_built == [WEB]


# ---------------------------------------------------------------------------
# Running the built tools: images, refusals, deadline
# ---------------------------------------------------------------------------

_UPLOAD_SIGNATURE = inspect.signature(image_service.upload_image)


@pytest.fixture
def uploads(monkeypatch):
    """Patch ``gateway_tool.get_db_session`` and ``image_service.upload_image``;
    each upload returns the next 43-character token."""
    made: list[dict[str, Any]] = []
    tokens = ["T" + str(index) + "x" * 41 for index in range(1, 10)]

    @contextmanager
    def fake_session():
        yield SimpleNamespace(name="db-session")

    def fake_upload(*args: Any, **kwargs: Any) -> Any:
        bound = _UPLOAD_SIGNATURE.bind(*args, **kwargs)
        bound.apply_defaults()
        made.append(dict(bound.arguments))
        return SimpleNamespace(token=tokens[len(made) - 1], id=len(made))

    monkeypatch.setattr(gateway_tool, "get_db_session", fake_session)
    monkeypatch.setattr(image_service, "upload_image", fake_upload)
    return SimpleNamespace(made=made, tokens=tokens)


def test_images_are_saved_as_the_user_and_saved_tokens_is_the_union(uploads):
    web = FakeClient(WEB, [_spec("render")], call_result=_image_result(_png((4, 3))))
    docs = FakeClient(DOCS, [_spec("snapshot")], call_result=_image_result(_png((2, 2))))

    build = _build(
        [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")],
        {WEB: _conn(WEB, "Web Search"), DOCS: _conn(DOCS, "Docs", id=2)},
        Factory(web, docs),
    )
    by_name = {tool.name: tool for tool in build.tools}
    assert build.saved_tokens() == []

    web_out = _run(by_name["render"])
    docs_out = _run(by_name["snapshot"])

    first, second = uploads.tokens[0], uploads.tokens[1]
    assert IMAGE_PLACEHOLDER_PATTERN.findall(web_out) == [first]
    assert IMAGE_PLACEHOLDER_PATTERN.findall(docs_out) == [second]
    assert [(u["user"], u["tags"], u["category"]) for u in uploads.made] == [
        (USER, ["gateway_mcp", WEB], "content"),
        (USER, ["gateway_mcp", DOCS], "content"),
    ]
    tokens = build.saved_tokens()
    assert isinstance(tokens, list)
    assert sorted(tokens) == sorted([first, second])


def test_access_failures_convert_the_refusals_recorded_during_the_run():
    """Refusals the loop records on the toolset become one failure per connection
    (in the order first seen), mapped back from the model-facing tool name.  A
    Genie One refusal on the same toolset is not a Gateway failure (T6.5)."""
    lakedraw = FakeClient(
        LAKEDRAW,
        [_spec("lakedraw_create_from_spec"), _spec("lakedraw_export_diagram")],
        call_error=GatewayMcpError(
            "sign_in_required", "Not signed in to " + LAKEDRAW, sign_in_url=SIGN_IN_URL
        ),
    )
    web = FakeClient(
        WEB, [_spec("search")], call_error=GatewayMcpError("access_denied", "403 Forbidden")
    )
    build = _build(
        [_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        {LAKEDRAW: _conn(LAKEDRAW, "LakeDraw"), WEB: _conn(WEB, "Web Search", id=2)},
        Factory(lakedraw, web),
    )
    by_name = {tool.name: tool for tool in build.tools}
    toolset = AgentToolset(tools=build.tools, max_calls=12, budget_seconds=360.0)
    assert build.access_failures(toolset) == []

    _answer(by_name, toolset, "lakedraw_create_from_spec", {}, "c1")
    _answer(by_name, toolset, "search", {"query": "x"}, "c2")
    _answer(by_name, toolset, "lakedraw_export_diagram", {}, "c3")
    toolset.access_errors.append(ToolAccessError("missing_scope", "genie", "no genie scope"))
    assert len(toolset.access_errors) == 4

    failures = build.access_failures(toolset)

    assert [_brief(f) for f in failures] == [
        ("LakeDraw", LAKEDRAW, "sign_in_required", SIGN_IN_URL),
        ("Web Search", WEB, "access_denied", None),
    ]
    assert all(isinstance(f, GatewayFailure) for f in failures)
    assert failure_notice(failures[0], oauth_client_id=None) == (
        "To use LakeDraw, sign in here: " + SIGN_IN_URL + " " + DASH + " then ask again."
    )
    assert failure_notice(failures[1], oauth_client_id=None) == (
        "You don't have access to Web Search (" + WEB + "). Ask an admin to grant EXECUTE on it."
    )


def test_access_failures_map_a_prefixed_tool_name_back_to_its_connection():
    web = FakeClient(WEB, [_spec("search")])
    docs = FakeClient(
        DOCS, [_spec("search")], call_error=GatewayMcpError("missing_scope", "scope")
    )
    build = _build(
        [_entry(WEB, "Web Search"), _entry(DOCS, "Docs")],
        {WEB: _conn(WEB, "Web Search"), DOCS: _conn(DOCS, "Docs", id=2)},
        Factory(web, docs),
    )
    by_name = {tool.name: tool for tool in build.tools}
    toolset = AgentToolset(tools=build.tools, max_calls=12, budget_seconds=360.0)

    _answer(by_name, toolset, "docs__search", {"q": "x"}, "c1")

    assert [_brief(f) for f in build.access_failures(toolset)] == [
        ("Docs", DOCS, "missing_scope", None)
    ]


def test_deadline_at_reaches_every_built_tool():
    """T4.7 via the builder: ``build_gateway_tools(..., deadline_at=...)`` (epoch
    seconds, default None) is every tool's deadline, so the 700 s guard can stop
    Gateway calls without clipping Genie One in a mixed toolset."""
    past = FakeClient(WEB, [_spec("search")])
    build = _build(
        [_entry(WEB, "Web Search")],
        {WEB: _conn(WEB, "Web Search")},
        Factory(past),
        deadline_at=time.time() - 1,
    )
    (tool,) = build.tools
    _run(tool, {"query": "x"})
    assert past.calls == []

    future = FakeClient(WEB, [_spec("search")])
    build = _build(
        [_entry(WEB, "Web Search")],
        {WEB: _conn(WEB, "Web Search")},
        Factory(future),
        deadline_at=time.time() + 3600,
    )
    (tool,) = build.tools
    _run(tool, {"query": "x"})
    assert future.calls == [("search", {"query": "x"})]

    default = FakeClient(WEB, [_spec("search")])
    build = _build([_entry(WEB, "Web Search")], {WEB: _conn(WEB, "Web Search")}, Factory(default))
    (tool,) = build.tools
    _run(tool, {"query": "x"})
    assert default.calls == [("search", {"query": "x"})]


# ---------------------------------------------------------------------------
# The per-turn budget
# ---------------------------------------------------------------------------


def test_budget_constants():
    assert ARCHITECT_GATEWAY_MAX_CALLS == 12
    assert ARCHITECT_GATEWAY_BUDGET_SECONDS == 360.0
    assert ANALYST_GATEWAY_MAX_CALLS == 6
    assert ANALYST_GATEWAY_BUDGET_SECONDS == 300.0
    assert GATEWAY_TURN_DEADLINE_SECONDS == 700.0


def test_turn_budget_shares_calls_and_clips_to_deadline():
    common = dict(used_calls=10, used_seconds=100, max_calls=12, budget_seconds=360)

    assert turn_budget(**common, turn_started_at=0, now=650) == (2, 50.0)
    assert turn_budget(**common, turn_started_at=0, now=710) == (2, 0.0)
    assert turn_budget(**common, turn_started_at=None, now=650) == (2, 260.0)


def test_turn_budget_types():
    calls, seconds = turn_budget(
        used_calls=1, used_seconds=10, max_calls=12, budget_seconds=360, turn_started_at=0, now=5
    )
    assert (calls, seconds) == (11, 350.0)
    assert isinstance(calls, int)
    assert isinstance(seconds, float)


def test_turn_budget_never_negative():
    assert turn_budget(
        used_calls=14, used_seconds=400, max_calls=12, budget_seconds=360,
        turn_started_at=None, now=0,
    ) == (0, 0.0)
    assert turn_budget(
        used_calls=12, used_seconds=0, max_calls=12, budget_seconds=360,
        turn_started_at=0, now=10_000,
    ) == (0, 0.0)


def test_turn_budget_default_deadline_is_700_seconds_and_overridable():
    common = dict(used_calls=0, used_seconds=0, max_calls=6, budget_seconds=300)

    # 700 - 500 = 200 left of the turn: tighter than the 300 s budget.
    assert turn_budget(**common, turn_started_at=1000, now=1500) == (6, 200.0)
    # Early in the turn the budget is the tighter bound.
    assert turn_budget(**common, turn_started_at=1000, now=1100) == (6, 300.0)
    assert turn_budget(**common, turn_started_at=1000, now=1030, deadline_seconds=100) == (6, 70.0)


# ---------------------------------------------------------------------------
# Notices (exact Global Constraints copy)
# ---------------------------------------------------------------------------


def _failure(kind: str, *, message: str | None = None, url: str | None = None) -> GatewayFailure:
    return GatewayFailure(
        display_name="LakeDraw",
        service_name=LAKEDRAW,
        kind=kind,  # type: ignore[arg-type]
        message=message,
        sign_in_url=url,
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            _failure("sign_in_required", message="Not signed in", url=SIGN_IN_URL),
            "To use LakeDraw, sign in here: " + SIGN_IN_URL + " " + DASH + " then ask again.",
        ),
        (
            _failure("access_denied", message="403 Forbidden"),
            "You don't have access to LakeDraw (" + LAKEDRAW + "). "
            "Ask an admin to grant EXECUTE on it.",
        ),
        (_failure("removed"), "LakeDraw is no longer available."),
        (
            _failure("not_found", message="does not exist"),
            "LakeDraw (" + LAKEDRAW + ") was not found on this workspace. "
            "Ask an admin to check the connection.",
        ),
        (
            _failure("unavailable", message="did not respond within 30 seconds"),
            "LakeDraw is unavailable right now (did not respond within 30 seconds). "
            "The deck was built without it.",
        ),
    ],
    ids=["sign_in_required", "access_denied", "removed", "not_found", "unavailable"],
)
def test_failure_notice_copy_exact(failure, expected):
    assert failure_notice(failure, oauth_client_id="abc-123") == expected


@pytest.mark.parametrize("client_id", ["abc-123", None])
def test_failure_notice_missing_scope_is_the_consent_message(client_id):
    failure = _failure("missing_scope", message="missing ai-gateway")

    assert failure_notice(failure, oauth_client_id=client_id) == consent_message(
        oauth_client_id=client_id
    )


def test_unavailable_notice_without_a_reason_never_says_none():
    notice = failure_notice(_failure("unavailable"), oauth_client_id=None)

    assert notice.startswith("LakeDraw is unavailable right now")
    assert notice.endswith("The deck was built without it.")
    assert "None" not in notice


def test_gateway_failure_is_a_frozen_dataclass_with_the_declared_fields():
    assert [field.name for field in dataclasses.fields(GatewayFailure)] == [
        "display_name",
        "service_name",
        "kind",
        "message",
        "sign_in_url",
    ]
    failure = _failure("removed")
    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.kind = "unavailable"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Module contract
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Every module a source imports, relative imports resolved."""
    package = ".".join(path.relative_to(REPO).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                module = base + ("." + node.module if node.module else "")
            else:
                module = node.module or ""
            modules.add(module)
            modules.update(module + "." + alias.name for alias in node.names)
    return modules


def test_the_toolset_module_does_not_import_core_skills():
    """T5.5 (``test_lakebase_only_runtime_contract``): no code-owned agent definitions."""
    modules = _imported_modules(REPO / "src" / "services" / "agent_tools" / "gateway_toolset.py")

    assert not [m for m in modules if m == "src.core.skills" or m.startswith("src.core.skills.")]
