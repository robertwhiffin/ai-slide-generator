"""C4 — graph assembly, ``invoke_graph`` and the emitter lifecycle.

The topology assertions read the assembled ``StateGraph`` (``compiled.builder``)
rather than a drawing, so they fail if a static edge is added alongside a
conditional set — the duplicate-conflicting-edge shape that ends in
``GraphRecursionError``.

The three run-the-graph tests compile with ``checkpointer=False`` and drive a
real three-slide turn through the real nodes against a real (file-backed)
database.  They are here, not in C5's layer-1 suite, because the emitter contract
this task owns is only meaningful if the graph actually builds: "with
``emitter=None`` nothing is emitted" is satisfied vacuously by a turn that
dispatches nothing.
"""

from __future__ import annotations

import ast
import inspect
import queue
from pathlib import Path
from typing import Any, Dict

import pytest
from langgraph.graph import END, START

from src.services.foreman_service import CAP
from src.services.graph import builder as builder_module
from src.services.graph.builder import build_graph, invoke_graph
from src.services.graph.event_emitter import (
    get_event_emitter,
    set_event_emitter,
)
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    graph_env_threadsafe,
    make_spec,
    review_out,
)

NODE_NAMES = {
    "architect",
    "data_analyst",
    "foreman",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "placeholder",
    "deck_reviewer",
}


@pytest.fixture
def assembled():
    """The assembled StateGraph behind a compiled graph."""
    return build_graph(checkpointer=False).builder


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


class TestTopology:
    def test_exactly_nine_nodes_and_no_tenth(self, assembled):
        assert set(assembled.nodes) == NODE_NAMES

    def test_the_static_edges_are_exactly_these_six(self, assembled):
        assert set(assembled.edges) == {
            (START, "architect"),
            ("data_analyst", "architect"),
            ("build_reviewer", "foreman"),
            ("fix_reviewer", "foreman"),
            ("placeholder", "foreman"),
            ("deck_reviewer", END),
        }

    def test_build_reviewer_to_foreman_is_static(self, assembled):
        """Measured: wiring a router here raises InvalidUpdateError on fix_target."""
        assert ("build_reviewer", "foreman") in assembled.edges
        assert "build_reviewer" not in assembled.branches

    def test_the_four_conditionally_routed_nodes(self, assembled):
        assert set(assembled.branches) == {"architect", "foreman", "builder", "fixer"}

    @pytest.mark.parametrize(
        "node", ["architect", "foreman", "builder", "fixer"]
    )
    def test_no_static_edge_leaves_a_conditionally_routed_node(self, assembled, node):
        """One conditional-edge set per node.

        A static ``add_edge`` alongside gives duplicate conflicting edges and a
        ``GraphRecursionError`` at run time — nothing at assembly time complains.
        """
        assert [edge for edge in assembled.edges if edge[0] == node] == []

    def test_the_sentinels_are_used_not_the_strings(self):
        source = inspect.getsource(builder_module)
        assert 'add_edge("START"' not in source
        assert '"__end__"' not in source
        assert "add_edge(START" in source

    def test_build_graph_uses_the_shared_checkpointer_by_default(self, monkeypatch):
        calls = []

        def fake_get_checkpointer():
            calls.append(True)
            return False  # a valid "no saver" value for compile()

        monkeypatch.setattr(builder_module, "get_checkpointer", fake_get_checkpointer)

        build_graph()

        assert calls == [True]

    def test_an_explicit_checkpointer_overrides_the_shared_one(self, monkeypatch):
        """C5's compiled-graph suite needs a file-backed saver of its own."""
        monkeypatch.setattr(
            builder_module,
            "get_checkpointer",
            lambda: pytest.fail("the override was ignored"),
        )
        assert build_graph(checkpointer=False) is not None

    def test_the_graph_is_compiled_once_per_process(self, monkeypatch):
        monkeypatch.setattr(builder_module, "get_checkpointer", lambda: False)
        monkeypatch.setattr(builder_module, "_compiled_graph", None)

        first = builder_module.get_graph()
        second = builder_module.get_graph()

        assert first is second

    def test_no_reviewer_router_is_defined_or_imported(self):
        names = [name for name in dir(builder_module) if name.endswith("_router")]
        assert "reviewer_router" not in names
        assert sorted(names) == [
            "architect_router",
            "build_reviewer_refan_router",
            "fixer_router",
            "foreman_router",
        ]


# ---------------------------------------------------------------------------
# invoke_graph
# ---------------------------------------------------------------------------


class _FakeCompiled:
    """Records what ``invoke_graph`` hands the compiled graph."""

    def __init__(self):
        self.calls = []
        self.emitter_during_invoke = "not-invoked"

    def invoke(self, state, config):
        self.emitter_during_invoke = get_event_emitter()
        self.calls.append({"state": dict(state), "config": dict(config)})
        return {"ok": True}


@pytest.fixture
def fake_graph(monkeypatch):
    fake = _FakeCompiled()
    monkeypatch.setattr(builder_module, "_compiled_graph", fake)
    yield fake
    set_event_emitter(None)


class TestNothingNewMayReachTheForeman:
    """The structural tripwire behind ws4d's describe-only gate.

    `architect_router` is the only thing that stops a sweeper turn dispatching
    builders over a human's hand-edits.  It protects ONE edge, so a new edge or a
    new router fall-through into the foreman would bypass it silently — and ws4c's
    amended Ruling C-2 already forbids exactly that for its own reason: a
    fall-through to the foreman once woke it mid-batch and made the deck reviewer
    run twice.

    A MEASURED CORRECTION to how C-2 is usually stated.  C-2 is quoted as "the
    foreman's only inbound edges are static ones from build_reviewer, fix_reviewer
    and placeholder, plus the conditional set out of itself".  Read off the
    compiled graph, that is incomplete: `architect` and `fixer` BOTH have
    conditional edges into the foreman.  `architect -> foreman` is the very edge
    the describe-only gate guards, and `fixer -> foreman` is `fixer_router`'s
    fall-through.  So the invariant this asserts is the measured five, not the
    quoted three, and it is asserted as set EQUALITY.
    """

    #: (source, conditional) for every edge into the foreman, measured.
    _INBOUND = {
        ("architect", True),        # architect_router — the describe-only gate
        ("fixer", True),            # fixer_router's fall-through
        ("build_reviewer", False),  # static, after a barrier (C-2)
        ("fix_reviewer", False),    # static, after a barrier (C-2)
        ("placeholder", False),     # static, after a barrier (C-2)
    }

    @staticmethod
    def _inbound_to_foreman():
        compiled = build_graph(checkpointer=False)
        return {
            (e.source, e.conditional)
            for e in compiled.get_graph().edges
            if e.target == "foreman"
        }

    def test_the_edge_list_is_read_at_all(self):
        """Entry assertion: an empty edge list would make the equality vacuous."""
        compiled = build_graph(checkpointer=False)
        edges = compiled.get_graph().edges
        assert len(edges) >= 15, f"only {len(edges)} edges found; the read failed"

    def test_exactly_five_edges_reach_the_foreman_and_no_sixth(self):
        """Set EQUALITY, not containment.

        Containment is the same class of hole as asserting a field equals its own
        default: it stays green with an extra edge present, which is precisely the
        edge that would bypass the describe-only gate.
        """
        assert self._inbound_to_foreman() == self._INBOUND, (
            "the foreman's inbound edges changed. A new edge reaching it bypasses "
            "architect_router, so a sweeper's describe-only turn can dispatch "
            "builders over a human's hand-edits — and C-2's own reason applies "
            "too: a fall-through wakes the foreman mid-batch and the deck "
            "reviewer runs twice"
        )

    def test_the_only_conditional_inbound_edges_are_the_two_routers_we_know(self):
        conditional = {src for src, cond in self._inbound_to_foreman() if cond}
        assert conditional == {"architect", "fixer"}


class TestNoSendMayTargetTheForeman:
    """The hole the edge list cannot see, measured rather than assumed.

    A `Send` to a node that is NOT in its router's path map **runs anyway, and
    does not appear in the compiled graph's edge list at all.**  Probed on a
    three-node graph: a router declaring `{"b": "b"}` and returning
    `[Send("c", {})]` executed `c`, while `get_graph().edges` listed only
    `a -> b`.  So `TestNothingNewMayReachTheForeman` would stay green over a
    `Send("foreman", …)` added anywhere.

    Hence this second, complementary scan: no `Send` under
    `src/services/graph/` may name the foreman.  Read off the AST rather than the
    text, because `routers.py`'s docstrings discuss `Send` and the foreman at
    length and a substring check would pass or fail on prose.
    """

    _GRAPH_DIR = Path(__file__).resolve().parents[2] / "src/services/graph"

    @classmethod
    def _send_targets(cls):
        """Every literal first argument to a `Send(...)` call under the package."""
        targets = []
        for path in sorted(cls._GRAPH_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "Send"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    targets.append((str(path.name), node.args[0].value))
        return targets

    def test_the_scan_finds_the_sends_that_do_exist(self):
        """Entry assertion. An absence over a scan that finds nothing is free."""
        found = {name for _, name in self._send_targets()}
        assert found == {"builder", "build_reviewer"}, (
            f"the Send targets under src/services/graph are {sorted(found)}; "
            "update this test deliberately rather than letting it drift"
        )

    def test_no_send_targets_the_foreman(self):
        offenders = [f"{f}:{n}" for f, n in self._send_targets() if n == "foreman"]
        assert not offenders, (
            f"{offenders} Sends to the foreman. A Send outside its router's path "
            "map runs and shows in NO edge list, so it bypasses both "
            "architect_router's describe-only gate and the inbound-edge tripwire"
        )


class TestInvokeGraphConfig:
    def test_passes_thread_id_and_max_concurrency_and_no_recursion_limit(
        self, fake_graph
    ):
        """Omitting thread_id raises ValueError out of the checkpointer.

        The recursion limit is deliberately unset: the installed default is
        10007, and a low value makes the graph fail EARLIER.
        """
        invoke_graph("sess-42", {})

        config = fake_graph.calls[0]["config"]
        assert config["configurable"]["thread_id"] == "sess-42"
        assert config["max_concurrency"] == CAP == 15
        assert "recursion_limit" not in config

    def test_mints_a_fresh_turn_id_per_turn(self, fake_graph):
        invoke_graph("sess-42", {})
        invoke_graph("sess-42", {})

        first, second = (call["state"]["turn_id"] for call in fake_graph.calls)
        assert first != second
        assert first and second

    def test_the_thread_id_is_stable_across_turns(self, fake_graph):
        """Turn 2 must resume the same thread; turn_id is what resets turn state."""
        invoke_graph("sess-42", {})
        invoke_graph("sess-42", {})
        assert {
            call["config"]["configurable"]["thread_id"] for call in fake_graph.calls
        } == {"sess-42"}

    def test_seeds_the_caller_s_initial_state(self, fake_graph):
        invoke_graph("sess-42", {"architect_message": "build me a deck"})
        assert fake_graph.calls[0]["state"]["architect_message"] == "build me a deck"

    def test_session_id_always_wins_over_the_initial_state(self, fake_graph):
        invoke_graph("sess-42", {"session_id": "someone-elses-session"})
        assert fake_graph.calls[0]["state"]["session_id"] == "sess-42"


class TestInvokeGraphDescribeOnly:
    """ws4d: the flag that lets a sweeper turn describe a deck without rebuilding.

    `invoke_graph` wraps it because `invoke_graph` is the only thing that knows
    `turn_id`, and it must be turn-scoped: turn state accumulates across a
    thread, so a plain bool set on a sweeper turn would still read True on the
    user's next turn and silently bar every later build for that deck.
    """

    def test_it_defaults_to_false_so_a_normal_turn_still_builds(self, fake_graph):
        invoke_graph("sess-42", {})
        assert fake_graph.calls[0]["state"]["describe_only"]["vals"] is False

    def test_an_explicit_flag_is_wrapped_with_THIS_turns_id(self, fake_graph):
        invoke_graph("sess-42", {}, describe_only=True)
        state = fake_graph.calls[0]["state"]
        wrapper = state["describe_only"]
        assert wrapper["vals"] is True
        assert wrapper["turn"] == state["turn_id"], (
            "the flag is not stamped with this turn, so scoped_vals cannot "
            "discard it on the next turn"
        )

    def test_each_turn_stamps_its_own_id_so_the_flag_cannot_outlive_its_turn(
        self, fake_graph
    ):
        invoke_graph("sess-42", {}, describe_only=True)
        invoke_graph("sess-42", {}, describe_only=False)

        first, second = fake_graph.calls
        assert first["state"]["describe_only"]["turn"] != (
            second["state"]["describe_only"]["turn"]
        )
        assert second["state"]["describe_only"]["vals"] is False, (
            "the second turn did not overwrite the flag; on a real thread the "
            "sweeper's True would still be in the channel"
        )

    def test_the_wrapper_is_json_native(self, fake_graph):
        """Ruling W-8(b): a new GraphState key carries JSON-native scalars only,
        because state crosses the checkpointer's serde on turn 2."""
        import json

        invoke_graph("sess-42", {}, describe_only=True)
        wrapper = fake_graph.calls[0]["state"]["describe_only"]
        assert json.loads(json.dumps(wrapper)) == wrapper


class TestInvokeGraphPrincipal:
    def test_an_explicit_principal_becomes_initiated_by(self, fake_graph):
        """For callers with no request context — ws4d's sweeper passes a marker."""
        from src.core.user_context import get_current_user

        assert get_current_user() is None
        invoke_graph("sess-42", {}, principal="sweeper@example.com")
        assert fake_graph.calls[0]["state"]["initiated_by"] == "sweeper@example.com"

    def test_the_request_user_is_resolved_once_when_no_principal_is_given(
        self, fake_graph, monkeypatch
    ):
        monkeypatch.setattr(
            builder_module, "get_current_user", lambda: "web@example.com"
        )
        invoke_graph("sess-42", {})
        assert fake_graph.calls[0]["state"]["initiated_by"] == "web@example.com"

    def test_no_node_calls_get_current_user_itself(self):
        """It works today and breaks the first time the graph runs on a bare thread.

        Checked on the AST, not the text: ``nodes.py``'s docstrings discuss
        ``get_current_user`` deliberately, and a substring check would pass or
        fail on prose.
        """
        import ast

        from src.services.graph import nodes

        tree = ast.parse(inspect.getsource(nodes))
        called = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "get_current_user" not in called
        assert "get_current_user" not in [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        ]


class TestEmitterLifecycle:
    def test_the_emitter_is_live_before_invoke_runs(self, fake_graph):
        emitter: queue.Queue = queue.Queue()
        invoke_graph("sess-42", {}, emitter=emitter)
        assert fake_graph.emitter_during_invoke is emitter

    def test_no_emitter_resets_a_var_left_by_an_earlier_turn(self, fake_graph):
        """Otherwise a resumed turn queues into the first process's queue forever."""
        first: queue.Queue = queue.Queue()
        invoke_graph("sess-42", {}, emitter=first)
        assert fake_graph.emitter_during_invoke is first

        invoke_graph("sess-42", {})
        assert fake_graph.emitter_during_invoke is None

    def test_a_second_turn_gets_its_own_emitter(self, fake_graph):
        first: queue.Queue = queue.Queue()
        second: queue.Queue = queue.Queue()
        invoke_graph("sess-42", {}, emitter=first)
        invoke_graph("sess-42", {}, emitter=second)
        assert fake_graph.emitter_during_invoke is second


# ---------------------------------------------------------------------------
# A real three-slide turn through the compiled graph
# ---------------------------------------------------------------------------


def _wire_three_slide_turn(env, *, findings_for=()):
    """Stub the five skills a clean three-slide build needs."""
    spec = make_spec((0, 1, 2))
    env.skills.set("architect", architect_build(spec))
    env.skills.set("builder", builder_out)
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=payload["position"])]
            if payload["position"] in findings_for
            else [],
        ),
    )
    env.skills.set("fixer", fixer_out)
    env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))
    from src.domain.finding import DeckReviewOutput

    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))
    return spec


def _run(env, state_overrides: Dict[str, Any] = None):
    graph = build_graph(checkpointer=False)
    state = env.state(turn_id="turn-run")
    state.update(state_overrides or {})
    return graph.invoke(state, {"max_concurrency": CAP})


class TestARealTurn:
    def test_the_graph_builds_a_deck_with_no_emitter_and_emits_nothing(
        self, graph_env_threadsafe, monkeypatch
    ):
        """Both halves matter: emission is optional, and the turn really builds.

        The spy makes "emits nothing" observable rather than assumed: nodes DO
        reach the emission path (so the test is not vacuous) and every attempt
        queues nothing and raises nothing.
        """
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)
        set_event_emitter(None)

        from src.services.graph import event_emitter as event_emitter_module

        real_emit = event_emitter_module.emit_event
        queued = []

        def spy(event):
            result = real_emit(event)
            queued.append(result)
            return result

        monkeypatch.setattr("src.services.graph.nodes.emit_event", spy)

        final = _run(env)

        assert queued, "no node reached the emission path — the test is vacuous"
        assert not any(queued)

        assert sorted(r.position for r in env.rows()) == [0, 1, 2]
        assert all(r.modified_by == "graph-user@example.com" for r in env.rows())
        assert env.deck_row().slide_count == 3
        assert final["knitted_html"]
        assert len(env.skills.calls_for("build_reviewer")) == 3
        assert len(env.skills.calls_for("deck_reviewer")) == 1
        assert get_event_emitter() is None

    def test_one_reviewer_per_slide_each_with_its_own_position(
        self, graph_env_threadsafe
    ):
        """A static edge here would collapse three branches into ONE invocation."""
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)

        _run(env)

        positions = sorted(
            call["payload"]["position"]
            for call in env.skills.calls_for("build_reviewer")
        )
        assert positions == [0, 1, 2]
        for call in env.skills.calls_for("build_reviewer"):
            assert call["payload"]["html"].endswith(
                f"slide {call['payload']['position']}</div>"
            )

    def test_every_fanned_node_queues_into_the_one_emitter(
        self, graph_env_threadsafe
    ):
        """ContextVars survive the thread boundary AND the fan-out (measured)."""
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            _run(env)
        finally:
            set_event_emitter(None)

        events = []
        while not emitter.empty():
            events.append(emitter.get_nowait())

        by_node: Dict[str, list] = {}
        for event in events:
            by_node.setdefault(event.metadata["node"], []).append(event)

        assert sorted(
            e.metadata["position"] for e in by_node["build_reviewer"]
        ) == [0, 1, 2]
        assert by_node["architect"]
        assert by_node["foreman"]
        assert by_node["deck_reviewer"]

    def test_one_fix_round_per_position_then_deck_review_once(
        self, graph_env_threadsafe
    ):
        """Without ``in_flight`` every position above the minimum is re-fixed."""
        env = graph_env_threadsafe
        _wire_three_slide_turn(env, findings_for=(0, 1))

        _run(env)

        fixer_positions = sorted(
            call["payload"]["position"] for call in env.skills.calls_for("fixer")
        )
        assert fixer_positions == [0, 1]
        assert len(env.skills.calls_for("fix_reviewer")) == 2
        assert len(env.skills.calls_for("deck_reviewer")) == 1
        assert sorted(r.position for r in env.rows()) == [0, 1, 2]
        rows = {r.position: r.html for r in env.rows()}
        assert rows[0] == "<div class='slide'>fixed 0</div>"
        assert rows[2] == "<div class='slide'>slide 2</div>"

    def test_a_failed_builder_is_placeheld_and_the_turn_still_completes(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)

        def builder_handler(payload):
            if payload["position"] == 1:
                raise RuntimeError("model exploded")
            return builder_out(payload)

        env.skills.set("builder", builder_handler)

        _run(env)

        import json

        from src.api.services.slide_repository import is_placeholder_record

        rows = {r.position: r for r in env.rows()}
        assert sorted(rows) == [0, 1, 2]
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert len(env.skills.calls_for("build_reviewer")) == 2
        assert len(env.skills.calls_for("deck_reviewer")) == 1

    def test_a_failed_build_reviewer_is_placeheld_and_the_turn_still_completes(
        self, graph_env_threadsafe
    ):
        """Before the handler existed this turn DIED: no placeholder, no
        deck-level write, nothing in chat."""
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)

        def reviewer(payload):
            if payload["position"] == 1:
                raise RuntimeError("reviewer exploded")
            return review_out(payload["position"])

        env.skills.set("build_reviewer", reviewer)

        final = _run(env)

        import json

        from src.api.services.slide_repository import is_placeholder_record

        rows = {r.position: r for r in env.rows()}
        assert sorted(rows) == [0, 1, 2]
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert rows[0].modified_by == "graph-user@example.com"
        # The deck-level write happened and the deck reached review exactly once.
        assert env.deck_row().slide_count == 3
        assert env.deck_row().scripts_content == final["scripts_content"]
        assert len(env.skills.calls_for("deck_reviewer")) == 1
        # …and the failure is visible in chat, not swallowed.
        info = [m for m in env.messages() if m["message_type"] == "info"]
        assert any("Slide 1" in m["content"] for m in info)

    def test_two_reviewers_failing_in_one_superstep_do_not_kill_the_turn(
        self, graph_env_threadsafe
    ):
        """The concurrency half: two branches writing ``error_state`` in one
        superstep raise ``InvalidUpdateError`` and the turn dies, which is why the
        handler surfaces an ``info`` notice instead."""
        env = graph_env_threadsafe
        _wire_three_slide_turn(env)

        def reviewer(payload):
            if payload["position"] in (0, 1):
                raise RuntimeError("reviewer exploded")
            return review_out(payload["position"])

        env.skills.set("build_reviewer", reviewer)

        _run(env)

        import json

        from src.api.services.slide_repository import is_placeholder_record

        rows = {r.position: r for r in env.rows()}
        assert sorted(rows) == [0, 1, 2]
        assert is_placeholder_record(json.loads(rows[0].verification_record))
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert len(env.skills.calls_for("deck_reviewer")) == 1

    def test_a_discuss_turn_ends_without_dispatching_anything(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        from src.domain.skill_io import ArchitectOutput

        env.skills.set(
            "architect", ArchitectOutput(intent="discuss", message="Let's talk.")
        )

        final = _run(env)

        assert final["architect_intent"] == "discuss"
        assert env.rows() == []
        assert env.skills.calls_for("builder") == []
