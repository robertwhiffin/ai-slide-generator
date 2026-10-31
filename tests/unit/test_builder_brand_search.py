# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Builders and fixers can search the deck's brand assets (addendum A, Task B3).

``builder_node`` and ``fixer_node`` hand the runtime a toolset holding the
``search_brand_assets`` tool on ``AgentAssemblyContext.toolset`` (the runtime's
one tool loop, RA19) only when all three hold (Correction A13):

* the payload's ``design_system_active`` is true,
* the payload carries a ``deck_style`` (an old deck's never does), and
* the branch payload's ``design_contract`` names a design system.

The tool searches THAT design system only, keeps the name and arguments of
``build_ds_asset_tool``'s tool, and caps its rows so an unfiltered call stays
valid JSON instead of being truncated mid-row by spotlight's byte cap.  What the
model finally sees is that JSON spotlighted once, by the tool.  Each run gets a
fresh toolset (a toolset counts its calls), the safety retry included.

Workbench test runs and slide-style previews bind no tool.  The eval harness
and ``builder_node`` reach the same loop function with the same tool class.

How this file asserts: on the context and payload each node actually handed the
runtime, on what the handed tool returns from a real database holding two
design systems, and by replaying a node's exact call through a real
``AgentRuntime`` whose chat model is a double — never on whether a helper ran.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentRuntime,
    DatabricksModelAdapter,
)
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.graph import nodes
from src.services.graph.nodes import build_branch_payload, builder_node, fixer_node
from src.services.graph.state import scoped
from src.services.graph_definition_manifest import (
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import ResolvedDefinition
from tests.fixtures.deterministic_model_adapter import fake_output
from tests.fixtures.model_payload_keys import BUILDER_MODEL_KEYS
from tests.fixtures.tool_call_doubles import replying, tool_call_reply
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    DEFAULT_STYLE,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
)

TURN = "turn-1"

#: The row cap the scoped tool applies (A13: "cap rows at about 20").
ROW_CAP = 20

#: A clean style the sanitiser keeps byte-identical (as test_deck_style_payloads).
CALLOUT_STYLE = DeckStyle(
    css=".dk-callout{border-left:4px solid #0b2a4a;padding:12px}",
    components=[
        DeckStyleComponent(
            name="callout",
            class_names=["dk-callout"],
            use="a single takeaway the slide should land",
            example_html="<div class='dk-callout'>Revenue doubled.</div>",
        )
    ],
)

_SPOTLIGHT_OPEN = '<untrusted-data source="brand_assets">\n'
_SPOTLIGHT_CLOSE = "\n</untrusted-data>"


# ---------------------------------------------------------------------------
# A real database with two design systems
# ---------------------------------------------------------------------------


def _asset(kind: str, filename: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "filename": filename,
        "mime": "image/svg+xml",
        "data": b"<svg/>",
        "size_bytes": 6,
    }


def _add_design_system(factory, name: str, assets: list[dict[str, Any]]):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    db = factory()
    try:
        design_system = DesignSystem(name=name)
        for values in assets:
            design_system.assets.append(DesignSystemAsset(**values))
        db.add(design_system)
        db.commit()
        db.refresh(design_system)
        return design_system.id, {
            asset.id: (asset.kind, asset.filename) for asset in design_system.assets
        }
    finally:
        db.close()


@pytest.fixture
def brand(graph_env, monkeypatch):
    """The deck's design system (30 icons, 2 logos) and a foreign one.

    The foreign system holds an ``icon-cloud.svg`` too, so a search that is not
    scoped to the deck's system returns a row it must not.
    """
    deck_assets = [_asset("icon", f"icon-{n:02d}.svg") for n in range(29)]
    deck_assets.append(_asset("icon", "icon-cloud.svg"))
    deck_assets += [_asset("logo", "logo-primary.svg"), _asset("logo", "logo-white.svg")]
    deck_id, deck_rows = _add_design_system(graph_env.factory, "Deck Brand", deck_assets)
    foreign_id, foreign_rows = _add_design_system(
        graph_env.factory,
        "Foreign Brand",
        [_asset("icon", "icon-cloud.svg"), _asset("logo", "foreign-logo.svg")],
    )

    @contextlib.contextmanager
    def _session():
        db = graph_env.factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ``build_ds_asset_tool`` imports this at call time.
    monkeypatch.setattr("src.core.database.get_db_session", _session)
    return SimpleNamespace(
        design_system_id=deck_id,
        foreign_design_system_id=foreign_id,
        asset_ids=set(deck_rows),
        logo_ids={i for i, (kind, _) in deck_rows.items() if kind == "logo"},
        icon_ids={i for i, (kind, _) in deck_rows.items() if kind == "icon"},
        foreign_asset_ids=set(foreign_rows),
    )


def _rows(tool_output: str) -> list[dict[str, Any]]:
    """The rows of a search's JSON, unwrapped from the tool's spotlight when present."""
    if tool_output.startswith(_SPOTLIGHT_OPEN):
        assert tool_output.endswith(_SPOTLIGHT_CLOSE)
        tool_output = tool_output[len(_SPOTLIGHT_OPEN) : -len(_SPOTLIGHT_CLOSE)]
    return json.loads(tool_output)["assets"]


def _run_search(tool, **args) -> str:
    """Run the handed ``AgentTool`` the way the runtime's loop does."""
    return tool.run(tool.args_schema.model_validate(args), remaining_seconds=300.0)


def _tools(context: AgentAssemblyContext) -> tuple:
    """The tools a context's toolset holds; ``()`` when it carries none."""
    return () if context.toolset is None else tuple(context.toolset.tools)


# ---------------------------------------------------------------------------
# A runtime stub that records the whole fourth argument
# ---------------------------------------------------------------------------


class _ContextRecordingRuntime:
    """Stands in for ``AgentRuntime``: records every argument, the context whole."""

    def __init__(self, handlers: dict[str, Callable[[dict], Any]]) -> None:
        self.handlers = handlers
        self.calls: list[SimpleNamespace] = []

    def run(self, agent_key, graph_release_id, payload, assembly_context):
        self.calls.append(
            SimpleNamespace(
                agent_key=agent_key,
                graph_release_id=graph_release_id,
                payload=payload,
                context=assembly_context,
            )
        )
        return SimpleNamespace(output=self.handlers[agent_key](payload))


def _recording_runtime(monkeypatch, **handlers) -> _ContextRecordingRuntime:
    runtime = _ContextRecordingRuntime(handlers)
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: runtime)
    return runtime


# ---------------------------------------------------------------------------
# Payloads, through the production payload builder
# ---------------------------------------------------------------------------


def _spec(design_system_id, deck_style) -> DeckSpec:
    spec = make_spec((0,), design_system_id=design_system_id)
    if deck_style is None:
        return spec
    return DeckSpec.model_validate({**spec.model_dump(), "deck_style": deck_style.model_dump()})


def _branch_payload(
    graph_env, *, design_system_id, design_system_active=True, deck_style=CALLOUT_STYLE
) -> dict[str, Any]:
    state = graph_env.state(
        deck_spec=_spec(design_system_id, deck_style),
        design_system_active=design_system_active,
        root_session_id=graph_env.session_id,
        actor_session_id=graph_env.session_id,
        resolved_style=DEFAULT_STYLE,
    )
    return build_branch_payload(state, 0)


def _fix_state(graph_env, branch_payload, *, html="<div class='slide'>original</div>"):
    """A fixer's state: one fix entry carrying the builder record as its payload."""
    entry = {
        "original_html": html,
        "original_scripts": "",
        "finding": finding("overflow", slide_index=0).model_dump(),
        "findings": [finding("overflow", slide_index=0).model_dump()],
        "payload": {**branch_payload, "html": html, "scripts": ""},
    }
    return graph_env.state(
        turn_id=TURN,
        deck_spec=make_spec((0,)),
        fix_map=scoped(TURN, {0: entry}),
        design_system_active=branch_payload["design_system_active"],
        root_session_id=graph_env.session_id,
        actor_session_id=graph_env.session_id,
    )


def _unsafe_then_clean(make_output):
    """First answer fails the safety gate (an external image), the retry is clean."""
    attempts: list[dict] = []

    def handler(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            return make_output(
                payload, html="<div class='slide'><img src='https://evil.example/x.png'></div>"
            )
        return make_output(payload, html="<div class='slide'>clean</div>")

    return handler


# ---------------------------------------------------------------------------
# Replaying a node's exact call through the real runtime
# ---------------------------------------------------------------------------


class _ScriptedChatModel:
    """A chat-model double at the production adapter's model-factory seam."""

    def __init__(self, script: list[Callable[[type[BaseModel]], AIMessage]]) -> None:
        self.script = list(script)
        self.bindings: list[tuple[list[Any], dict[str, Any]]] = []
        self.raw_inputs: list[Any] = []
        self.inputs: list[list[Any]] = []

    def bind_tools(self, tools, **kwargs):
        tools = list(tools)
        self.bindings.append((tools, kwargs))
        schema = next(
            tool for tool in tools if isinstance(tool, type) and issubclass(tool, BaseModel)
        )

        def reply(model_input):
            self.raw_inputs.append(model_input)
            self.inputs.append(
                [HumanMessage(content=model_input)]
                if isinstance(model_input, str)
                else list(model_input)
            )
            if not self.script:
                raise AssertionError("the model was called more often than scripted")
            return self.script.pop(0)(schema)

        return replying(reply)

    def with_structured_output(self, schema):  # pragma: no cover - failure path
        raise AssertionError("forced tool choice must not be bound")


def _answer(agent_key: str):
    return lambda schema: tool_call_reply(schema, fake_output(agent_key))


def _search(args: dict[str, Any], call_id: str = "call_s1"):
    return lambda _schema: AIMessage(
        content="",
        tool_calls=[
            {"name": "search_brand_assets", "args": args, "id": call_id, "type": "tool_call"}
        ],
    )


def _manifest_content(agent_key: str):
    return next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == agent_key
    )


def _chat_adapter(chat: _ScriptedChatModel) -> DatabricksModelAdapter:
    return DatabricksModelAdapter(
        model_factory=lambda **_kwargs: chat, client_factory=lambda: object()
    )


def _v1_runtime(chat: _ScriptedChatModel) -> AgentRuntime:
    """A real runtime over the v1 definitions whose chat model is ``chat``."""

    def resolve(graph_release_id, key):
        content = _manifest_content(key)
        return ResolvedDefinition(
            graph_version=1,
            graph_release_id=graph_release_id,
            agent_key=key,
            agent_definition_revision_id=1,
            content_hash=definition_content_hash(content),
            content=content,
        )

    return AgentRuntime(
        persisted_release_loader=SimpleNamespace(resolve=resolve),
        model_adapter=_chat_adapter(chat),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )


def _replay(call: SimpleNamespace, chat: _ScriptedChatModel):
    """Run a recorded node call through a real runtime over the v1 definition."""
    return _v1_runtime(chat).run(
        call.agent_key, call.graph_release_id, call.payload, call.context
    )


def _assert_todays_binding(chat: _ScriptedChatModel, agent_key: str, prompt: str) -> None:
    """One ``bind_tools([schema], tool_choice="auto")``, invoked with the prompt string."""
    assert len(chat.bindings) == 1
    bound, kwargs = chat.bindings[0]
    assert kwargs == {"tool_choice": "auto"}
    (schema,) = bound
    assert issubclass(schema, OUTPUT_SCHEMAS[agent_key])
    assert chat.raw_inputs == [prompt]


# ===========================================================================
# builder_node
# ===========================================================================


def test_the_builder_gets_the_brand_search_tool_for_a_styled_design_system_deck(
    graph_env, monkeypatch, brand
):
    runtime = _recording_runtime(monkeypatch, builder=builder_out)
    payload = _branch_payload(graph_env, design_system_id=brand.design_system_id)

    updates = builder_node(payload)

    assert "slides" in updates
    (call,) = runtime.calls
    assert [tool.name for tool in _tools(call.context)] == ["search_brand_assets"]
    # Three searches at most (the toolset's budget, enforced by the loop).
    assert call.context.toolset.max_calls == 3
    # The rest of the context is what it always was.
    assert call.context == AgentAssemblyContext(True, graph_env.session_id, graph_env.session_id)
    assert call.context.design_system_active is True
    # The model-facing payload is untouched by the binding: content keys only,
    # still JSON (no tool object, no design-system id smuggled in).
    assert set(call.payload) == BUILDER_MODEL_KEYS | {"deck_style"}
    assert json.loads(json.dumps(call.payload)) == call.payload


def test_the_builders_tool_searches_only_the_decks_design_system(
    graph_env, monkeypatch, brand
):
    """A13: scoped to the branch payload's ``design_contract.design_system_id``."""
    runtime = _recording_runtime(monkeypatch, builder=builder_out)

    builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))

    (tool,) = _tools(runtime.calls[0].context)
    everything = {row["id"] for row in _rows(_run_search(tool))}
    assert everything and everything <= brand.asset_ids
    assert not everything & brand.foreign_asset_ids
    # The model's arguments reach the search: kind and query filter it.
    logos = _rows(_run_search(tool, kind="logo"))
    assert {row["id"] for row in logos} == brand.logo_ids
    assert {row["kind"] for row in logos} == {"logo"}
    cloud = _rows(_run_search(tool, query="cloud"))
    assert [row["filename"] for row in cloud] == ["icon-cloud.svg"]
    assert {row["id"] for row in cloud} <= brand.icon_ids
    # Each row still carries the deck's own handle.
    for row in cloud:
        assert "{{ds-asset:%d}}" % row["id"] in row["usage"]


def test_the_builders_tool_caps_its_rows_and_keeps_the_tools_name_and_arguments(
    graph_env, monkeypatch, brand
):
    """A13: wrap, don't edit — the unscoped tool has no row cap, the bound one has."""
    from src.services.tools.ds_asset_tool import build_ds_asset_tool

    runtime = _recording_runtime(monkeypatch, builder=builder_out)

    builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))

    (tool,) = _tools(runtime.calls[0].context)
    unscoped = build_ds_asset_tool(brand.design_system_id)
    assert tool.name == unscoped.name == "search_brand_assets"
    assert tool.description == unscoped.description
    assert tool.args_schema is unscoped.args_schema
    assert set(tool.args_schema.model_fields) == {"query", "kind"}
    uncapped = _rows(unscoped.invoke({"kind": "icon"}))
    assert len(uncapped) == 30
    capped = _rows(_run_search(tool, kind="icon"))
    # The first ROW_CAP rows of the search's own ranking, as valid JSON.
    assert capped == uncapped[:ROW_CAP]
    assert len(_rows(_run_search(tool))) == ROW_CAP


def test_no_tool_without_deck_style(graph_env, monkeypatch, brand):
    """An old deck (no deck style): the call, and the binding it makes, are today's."""
    runtime = _recording_runtime(monkeypatch, builder=builder_out)
    payload = _branch_payload(
        graph_env, design_system_id=brand.design_system_id, deck_style=None
    )
    assert "deck_style" not in payload

    builder_node(payload)

    (call,) = runtime.calls
    assert set(call.payload) == BUILDER_MODEL_KEYS
    assert call.context == AgentAssemblyContext(True, graph_env.session_id, graph_env.session_id)
    chat = _ScriptedChatModel([_answer("builder")])
    result = _replay(call, chat)
    _assert_todays_binding(chat, "builder", result.diagnostics.assembled_prompt)
    assert call.context.toolset is None


def test_no_tool_without_a_design_system(graph_env, monkeypatch, brand):
    """A deck style on a deck with no active design system binds nothing."""
    runtime = _recording_runtime(monkeypatch, builder=builder_out)

    builder_node(
        _branch_payload(
            graph_env, design_system_id=brand.design_system_id, design_system_active=False
        )
    )

    (call,) = runtime.calls
    chat = _ScriptedChatModel([_answer("builder")])
    result = _replay(call, chat)
    _assert_todays_binding(chat, "builder", result.diagnostics.assembled_prompt)
    assert call.context.toolset is None


def test_no_tool_when_the_contract_names_no_design_system(graph_env, monkeypatch, brand):
    """A13: ``design_system_active`` with a contract whose design_system_id is None."""
    runtime = _recording_runtime(monkeypatch, builder=builder_out)
    payload = _branch_payload(graph_env, design_system_id=None)
    assert payload["design_contract"]["design_system_id"] is None

    builder_node(payload)

    (call,) = runtime.calls
    chat = _ScriptedChatModel([_answer("builder")])
    result = _replay(call, chat)
    _assert_todays_binding(chat, "builder", result.diagnostics.assembled_prompt)
    assert call.context.toolset is None


def _spending_unsafe_then_clean(runtime_box: list, spent_before: list, make_output):
    """``_unsafe_then_clean``, and each attempt spends its toolset's whole budget.

    A retry handed the same toolset would start exhausted: every search answered
    with the budget text.  ``runtime_box`` holds the recording runtime, so the
    handler can reach the context of the call it is answering; ``spent_before``
    gets each toolset's call count as its run starts.
    """
    unsafe_then_clean = _unsafe_then_clean(make_output)

    def handler(payload):
        (runtime,) = runtime_box
        toolset = runtime.calls[-1].context.toolset
        spent_before.append(toolset.calls_made)
        toolset.start()
        toolset.calls_made = toolset.max_calls
        return unsafe_then_clean(payload)

    return handler


def test_the_builders_safety_retry_keeps_the_tool_with_a_fresh_budget(
    graph_env, monkeypatch, brand
):
    """Both builder calls (first attempt and gate retry) get the scoped tool, each in a
    toolset of its own (RA21): the first attempt's spent budget is not the retry's."""
    box: list = []
    spent_before: list = []
    runtime = _recording_runtime(
        monkeypatch, builder=_spending_unsafe_then_clean(box, spent_before, builder_out)
    )
    box.append(runtime)

    updates = builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))

    assert updates["slides"]["vals"][0]["html"] == "<div class='slide'>clean</div>"
    first, retry = runtime.calls
    assert "corrective_instruction" in retry.payload
    assert first.context.toolset is not retry.context.toolset
    # The first attempt spent its whole budget; the retry still started with none spent.
    assert spent_before == [0, 0]
    for call in (first, retry):
        (tool,) = _tools(call.context)
        assert {row["id"] for row in _rows(_run_search(tool, kind="logo"))} == brand.logo_ids


def test_a_brand_search_reaches_the_builders_model_spotlighted_once_and_capped(
    graph_env, monkeypatch, brand
):
    """End to end: the node's exact call, replayed through the real runtime.

    The model searches unfiltered once, then answers.  The result it is shown
    is the deck's assets, at most ROW_CAP of them, as JSON wrapped in exactly
    one spotlight — not raw, and not double-wrapped by the tool and the loop.
    The search ran on the node's own toolset, which counted it.
    """
    runtime = _recording_runtime(monkeypatch, builder=builder_out)
    builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))
    (call,) = runtime.calls
    chat = _ScriptedChatModel([_search({}), _answer("builder")])

    result = _replay(call, chat)

    assert result.output == OUTPUT_SCHEMAS["builder"].model_validate(fake_output("builder"))
    (answer,) = [m for m in chat.inputs[1] if isinstance(m, ToolMessage)]
    content = str(answer.content)
    assert content.startswith(_SPOTLIGHT_OPEN)
    assert content.endswith(_SPOTLIGHT_CLOSE)
    assert content.count("<untrusted-data") == 1
    rows = _rows(content[len(_SPOTLIGHT_OPEN) : -len(_SPOTLIGHT_CLOSE)])
    assert len(rows) == ROW_CAP
    assert {row["id"] for row in rows} <= brand.asset_ids
    assert call.context.toolset.calls_made == 1


@pytest.mark.parametrize(
    "failing",
    [
        pytest.param(
            ("src.services.tools.ds_asset_tool", "build_ds_asset_tool"), id="the_search"
        ),
        pytest.param(
            ("src.services.agent_tools.brand_search", "build_brand_search_toolset"),
            id="the_toolset",
        ),
    ],
)
def test_a_search_tool_that_cannot_be_built_binds_none_and_the_slide_still_builds(
    graph_env, monkeypatch, brand, failing
):
    """Building the search and its toolset runs inside ``_brand_search_toolset``'s guard.

    Either construction failing gives no toolset, today's binding and a slide,
    never a failed branch.
    """
    module, name = failing

    def _fail(*_args, **_kwargs):
        raise RuntimeError("tool construction failed")

    monkeypatch.setattr(f"{module}.{name}", _fail)
    runtime = _recording_runtime(monkeypatch, builder=builder_out)

    updates = builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))

    assert 0 in updates["slides"]["vals"]
    (call,) = runtime.calls
    assert call.context.toolset is None
    chat = _ScriptedChatModel([_answer("builder")])
    result = _replay(call, chat)
    _assert_todays_binding(chat, "builder", result.diagnostics.assembled_prompt)


# ===========================================================================
# fixer_node
# ===========================================================================


def test_the_fixer_gets_the_brand_search_tool(graph_env, monkeypatch, brand):
    runtime = _recording_runtime(monkeypatch, fixer=fixer_out)
    branch = _branch_payload(graph_env, design_system_id=brand.design_system_id)

    updates = fixer_node(_fix_state(graph_env, branch))

    assert updates["fix_target"] == 0
    (call,) = runtime.calls
    assert call.agent_key == "fixer"
    (tool,) = _tools(call.context)
    assert tool.name == "search_brand_assets"
    assert call.context.toolset.max_calls == 3
    # Scoped to the design system of the builder record's design contract.
    assert {row["id"] for row in _rows(_run_search(tool, kind="logo"))} == brand.logo_ids
    assert not {row["id"] for row in _rows(_run_search(tool))} & brand.foreign_asset_ids
    assert call.context == AgentAssemblyContext(True, graph_env.session_id, graph_env.session_id)
    assert "deck_style" in call.payload


def test_the_fixers_safety_retry_keeps_the_tool_with_a_fresh_budget(
    graph_env, monkeypatch, brand
):
    box: list = []
    spent_before: list = []
    runtime = _recording_runtime(
        monkeypatch, fixer=_spending_unsafe_then_clean(box, spent_before, fixer_out)
    )
    box.append(runtime)
    branch = _branch_payload(graph_env, design_system_id=brand.design_system_id)

    fixer_node(_fix_state(graph_env, branch))

    first, retry = runtime.calls
    assert "corrective_instruction" in retry.payload
    assert first.context.toolset is not retry.context.toolset
    assert spent_before == [0, 0]
    for call in (first, retry):
        (tool,) = _tools(call.context)
        assert {row["id"] for row in _rows(_run_search(tool, kind="logo"))} == brand.logo_ids


@pytest.mark.parametrize(
    "branch_kwargs",
    [
        pytest.param({"deck_style": None}, id="no_deck_style"),
        pytest.param({"design_system_active": False}, id="no_design_system"),
        pytest.param({"design_system_id": None}, id="contract_names_no_design_system"),
    ],
)
def test_the_fixer_gets_no_tool_unless_all_three_hold(
    graph_env, monkeypatch, brand, branch_kwargs
):
    runtime = _recording_runtime(monkeypatch, fixer=fixer_out)
    arguments = {"design_system_id": brand.design_system_id, **branch_kwargs}
    branch = _branch_payload(graph_env, **arguments)

    fixer_node(_fix_state(graph_env, branch))

    (call,) = runtime.calls
    chat = _ScriptedChatModel([_answer("fixer")])
    result = _replay(call, chat)
    _assert_todays_binding(chat, "fixer", result.diagnostics.assembled_prompt)
    assert call.context.toolset is None


# ===========================================================================
# Workbench test runs and slide-style previews stay unbound
# ===========================================================================


@pytest.fixture
def workbench_factory() -> Iterator[sessionmaker]:
    """The workbench's own SQLite with the v1 release bootstrapped."""
    import src.database.models  # noqa: F401 - register the complete ORM metadata
    from src.core.database import Base
    from src.services.graph_configuration import GraphConfiguration

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(session_factory)
    try:
        yield session_factory
    finally:
        engine.dispose()


class _ContextSpyRuntime(AgentRuntime):
    """The real runtime, recording the context its two test-run entry points get."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.contexts: list[AgentAssemblyContext] = []

    def run_candidate(
        self, agent_key, content, candidate_hash, payload, context, *, observation=None
    ):
        self.contexts.append(context)
        return super().run_candidate(
            agent_key, content, candidate_hash, payload, context, observation=observation
        )

    def run_published_baseline(self, agent_key, release_id, payload, context, *, observation=None):
        self.contexts.append(context)
        return super().run_published_baseline(
            agent_key, release_id, payload, context, observation=observation
        )


def test_workbench_test_runs_bind_no_tool(workbench_factory):
    """A builder case WITH a deck style and an active design system still binds only
    the output schema, on a candidate run and on a baseline rerun."""
    from src.database.models.graph_configuration import GraphDraft
    from src.services.agent_test_workbench import AgentTestWorkbench
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    chat = _ScriptedChatModel([_answer("builder"), _answer("builder")])
    runtime = _ContextSpyRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=workbench_factory),
        model_adapter=_chat_adapter(chat),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    workbench = AgentTestWorkbench(runtime=runtime)
    synthetic_payload = {
        "position": 1,
        "slide_spec": {"position": 1, "title": "Styled", "purpose": "Show the style"},
        "assumes": [],
        "hands_off": [],
        "design_contract": {"design_system_id": 5, "template_id": None},
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "section_html": "<section><h1>Styled</h1></section>",
        "section_css": "",
        "resolved_style": "Synthetic demo style",
        "design_system_active": True,
        "deck_style": CALLOUT_STYLE.model_dump(),
    }
    with workbench_factory() as session:
        case = AgentTestWorkbench().create_test_case(
            session,
            agent_key="builder",
            name="builder_deck_style_case",
            synthetic_payload=synthetic_payload,
            assembly_context={"design_system_active": True},
            is_required=False,
            actor="admin@example.com",
        )
    with workbench_factory() as session:
        lock_version = session.scalar(select(GraphDraft.lock_version))
    with workbench_factory() as session:
        workbench.execute_candidate_run(
            session,
            agent_key="builder",
            test_case_id=case.id,
            expected_lock_version=lock_version,
            actor="runner@example.com",
        )
    with workbench_factory() as session:
        workbench.execute_baseline_rerun(
            session, agent_key="builder", test_case_id=case.id, actor="runner@example.com"
        )

    assert len(chat.bindings) == 2
    for bound, kwargs in chat.bindings:
        assert kwargs == {"tool_choice": "auto"}
        (schema,) = bound
        assert issubclass(schema, OUTPUT_SCHEMAS["builder"])
    assert all(isinstance(model_input, str) for model_input in chat.raw_inputs)
    assert len(runtime.contexts) == 2
    assert all(context.design_system_active is True for context in runtime.contexts)
    assert [context.toolset for context in runtime.contexts] == [None, None]


@pytest.fixture
def preview_release(tmp_path):
    """A file-backed SQLite with the v1 release; its builder definition."""
    import src.database.models  # noqa: F401 - register the complete ORM metadata
    from src.core.database import Base
    from src.services import slide_style_preview_fixture as preview_fixture
    from src.services.graph_configuration import GraphConfiguration

    engine = create_engine(f"sqlite:///{tmp_path}/preview.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    with factory() as session:
        builder = preview_fixture.current_builder_definition(session)
    assert builder is not None
    try:
        yield factory, builder
    finally:
        engine.dispose()


def test_slide_style_previews_bind_no_tool(preview_release, monkeypatch):
    from src.api.services import slide_style_preview_queue as queue
    from src.services import slide_style_preview_fixture as preview_fixture
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    factory, builder = preview_release
    chat = _ScriptedChatModel([_answer("builder")])
    contexts: list[AgentAssemblyContext] = []

    class _Runtime(AgentRuntime):
        def run(self, agent_key, graph_release_id, payload, assembly_context):
            contexts.append(assembly_context)
            return super().run(agent_key, graph_release_id, payload, assembly_context)

    runtime = _Runtime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=_chat_adapter(chat),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    monkeypatch.setattr(queue, "get_agent_runtime", lambda: runtime)

    queue._build_slide(1, "Signature style.", builder, preview_fixture.PREVIEW_SLIDE_SPECS[0])

    assert len(chat.bindings) == 1
    bound, kwargs = chat.bindings[0]
    assert kwargs == {"tool_choice": "auto"}
    (schema,) = bound
    assert issubclass(schema, OUTPUT_SCHEMAS["builder"])
    assert all(isinstance(model_input, str) for model_input in chat.raw_inputs)
    assert [context.toolset for context in contexts] == [None]


# ===========================================================================
# One tool loop: builder_node and the eval harness (RA19, RA21)
# ===========================================================================


def test_builder_node_and_the_eval_harness_run_the_search_through_one_loop_function(
    graph_env, monkeypatch, brand
):
    """A production builder run and an eval-harness builder run both enter
    ``DatabricksModelAdapter.invoke_with_tools`` with a toolset holding production's
    ``BrandSearchAgentTool``; only the search backend under it differs."""
    from evals.harness.config import v1_baseline
    from evals.harness.runner import Runner
    from src.services.agent_tools.brand_search import BrandSearchAgentTool

    loop = DatabricksModelAdapter.invoke_with_tools
    entered: list[tuple[str, Any]] = []

    def _entering_the_loop(self, **kwargs):
        entered.append((kwargs["agent_key"], kwargs["toolset"]))
        return loop(self, **kwargs)

    monkeypatch.setattr(DatabricksModelAdapter, "invoke_with_tools", _entering_the_loop)

    node_chat = _ScriptedChatModel([_search({"kind": "icon"}), _answer("builder")])
    node_runtime = _v1_runtime(node_chat)
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: node_runtime)
    builder_node(_branch_payload(graph_env, design_system_id=brand.design_system_id))

    harness_chat = _ScriptedChatModel([_search({"kind": "icon"}), _answer("builder")])
    runner = Runner(model_adapter=_chat_adapter(harness_chat), max_infra_retries=0)
    harness_payload = {
        "position": 1,
        "design_system_active": True,
        "deck_style": CALLOUT_STYLE.model_dump(),
    }
    result = runner.run(v1_baseline("builder"), harness_payload, design_system_active=True)

    assert result.status == "completed", result.error_detail
    assert [agent_key for agent_key, _ in entered] == ["builder", "builder"]
    for _, toolset in entered:
        (tool,) = toolset.tools
        assert type(tool) is BrandSearchAgentTool
        assert toolset.max_calls == 3
        assert toolset.calls_made == 1
    # Each search reached its model as the tool's spotlighted rows.
    for chat in (node_chat, harness_chat):
        (answer,) = [m for m in chat.inputs[1] if isinstance(m, ToolMessage)]
        assert str(answer.content).startswith(_SPOTLIGHT_OPEN)
        assert _rows(str(answer.content))
    assert result.tool_calls == (
        {"name": "search_brand_assets", "args": {"query": None, "kind": "icon"}},
    )
