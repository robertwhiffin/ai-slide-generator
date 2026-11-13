# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""The Stage Slide reaches the Agent-mode architect, fresh and identity-safe
(architect stage context, plan Task 3; PLAN-CORRECTIONS C2, C3, C5).

The viewer sends the slide on stage at send time as a raw snapshot
``{"slide_number": N, "slide_id"?: str}``; Task 2 forwards it to
``invoke_graph(initial={"stage_slide": ...})``.  This file pins what happens
after that:

* **Turn scoping (C2).**  ``GraphState.stage_slide`` is a turn-scoped key
  registered in ``_EMPTY_FOR`` with empty value ``None``.  ``invoke_graph`` writes
  ``scoped(turn_id, value)`` on EVERY invocation, omission included, and
  ``architect_node`` reads it only through ``scoped_vals``: a raw or stale value
  is no stage.
* **Identity (C3).**  The snapshot is resolved against THIS session's committed
  rows.  A supplied id that is absent, duplicated or from another deck never
  falls back to the number; with no id the number is looked up in
  ``slide_numbering``.
* **Sanitised model payload.**  The architect payload carries ``stage_slide``:
  ``None`` or exactly ``{"slide_number", "position"}``.  No slide id, row id,
  session, user, turn or release identifier reaches the model.  The architect
  retry and the analyst loop keep the same turn's stage; the next turn without a
  stage clears it, through a REAL compiled graph with a REAL checkpointer.
* **Selection never forces targets.**  ``slide_references`` and the turn's
  ``target_positions`` are unchanged by the stage.
* **Shipped instructions.**  The authored prompt, the packaged manifest prompt
  and the prompt actually ASSEMBLED for the model all carry the stage policy.
  These are literal-text checks: they prove the instructions ship, NOT that a
  live model follows them (that needs the eval harness, out of scope here).

How this file asserts: every architect payload is the object the stubbed
``AgentRuntime`` was handed (``SkillStub.calls``), deep-copied at call time where
the turn makes more than one call.  Oracles are literals.

Sabotage map (each run against the implementation, one at a time):

1. ``invoke_graph`` does not write ``stage_slide`` when the caller omits it AND
   the node reads the wrapper without the turn check -> the checkpointed
   turn-2 test (and the fake-graph omission test alone for the write).
2. ``invoke_graph`` forwards the raw value unwrapped -> every boundary test.
3. ``architect_node`` reads ``state["stage_slide"]`` raw -> the raw/stale tests.
4. ``stage_slide`` not declared on ``GraphState`` -> the compiled-graph tests
   (the runtime drops undeclared keys).
5. the node passes the snapshot (or the row) through -> the sanitisation tests.
6. the node resolves by number when the id is missing/duplicated/foreign -> the
   identity tests.
7. the retry payload rebuilt without the stage -> the retry test.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple, get_type_hints

import pytest

from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.skill_io import AnalystOutput, ArchitectOutput
from src.services import agent_model_payload
from src.services.graph import builder as builder_module
from src.services.graph.builder import build_graph, invoke_graph
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.nodes import architect_node
from src.services.graph.state import _EMPTY_FOR, GraphState, scoped, scoped_vals
from tests.fixtures.model_payload_keys import ARCHITECT_MODEL_KEYS, ARCHITECT_RETRY_MODEL_KEYS
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    graph_env,
    graph_env_threadsafe,
    make_spec,
)
from tests.unit.test_architect_edit_operations import _content, _ops_out, _replace
from tests.unit.test_graph_builder import fake_graph  # noqa: F401 — fixture

#: The deck every identity test runs on: three slides at GAPPED positions, so a
#: position computed as ``slide_number - 1`` is visibly wrong.
POSITIONS = (3, 8, 15)
STAGE_KEYS = {"slide_number", "position"}

DISCUSS_MSG = "STAGE-DISCUSS: here is my answer."
USER_MESSAGE = "Make the title bigger"


@pytest.fixture(autouse=True)
def _no_turn_state_leaks():
    set_event_emitter(None)
    set_chat_request_id(None)
    yield
    set_event_emitter(None)
    set_chat_request_id(None)


# ---------------------------------------------------------------------------
# Seeding: committed rows with KNOWN stable ids
# ---------------------------------------------------------------------------


def _owner(db, session_id: str) -> UserSession:
    return db.query(UserSession).filter(UserSession.session_id == session_id).one()


def _seed(
    env, layout: Sequence[Tuple[int, Optional[str]]], *, session_id: Optional[str] = None
) -> None:
    """Committed rows ``(position, slide_id)`` for *session_id* (default: the env's).

    Each row's HTML carries its id, so a test can tell which slide is which.
    Creates the deck row when there is none.
    """
    db = env.factory()
    try:
        owner = _owner(db, session_id or env.session_id)
        if (
            db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner.id).first()
            is None
        ):
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    html_content="",
                    scripts_content=None,
                    slide_count=len(layout),
                    version=1,
                )
            )
        for position, slide_id in layout:
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=f"row-{uuid.uuid4().hex}",
                    slide_id=slide_id,
                    html=f"<section class='slide'><h1>{slide_id or 'no-id'}</h1></section>",
                    scripts="",
                )
            )
        db.commit()
    finally:
        db.close()


def _foreign_session(env) -> str:
    """A second conversation (its own deck) in the same database; returns its id."""
    db = env.factory()
    try:
        release_id = _owner(db, env.session_id).graph_release_id
        foreign = f"foreign-{uuid.uuid4().hex[:10]}"
        db.add(
            UserSession(
                session_id=foreign,
                created_by="someone-else@example.com",
                graph_release_id=release_id,
            )
        )
        db.commit()
        return foreign
    finally:
        db.close()


def _persist(env, positions: Sequence[int] = POSITIONS) -> None:
    from src.api.services.deck_level_writer import write_deck_level_columns

    write_deck_level_columns(env.session_id, deck_spec=make_spec(tuple(positions)).to_json())


def _deck_abc(env) -> None:
    """sid-a, sid-b, sid-c at 3, 8, 15 (slides 1, 2, 3) with a persisted spec."""
    _seed(env, [(3, "sid-a"), (8, "sid-b"), (15, "sid-c")])
    _persist(env)


# ---------------------------------------------------------------------------
# Running the architect node and capturing what the model was handed
# ---------------------------------------------------------------------------


class _Recorder:
    """An architect stub: deep-copies every payload, answers from a list (last repeats)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers) or [ArchitectOutput(intent="discuss", message=DISCUSS_MSG)]
        self.seen: List[Dict[str, Any]] = []

    def __call__(self, payload: Dict[str, Any]) -> Any:
        self.seen.append(copy.deepcopy(payload))
        index = min(len(self.seen), len(self.answers)) - 1
        return self.answers[index]


def _node(
    env, recorder: Optional[_Recorder] = None, **overrides
) -> Tuple[Dict[str, Any], _Recorder]:
    """Run ``architect_node`` once on ``env.state(**overrides)``."""
    recorder = recorder or _Recorder()
    env.skills.set("architect", recorder)
    overrides.setdefault("architect_message", USER_MESSAGE)
    updates = architect_node(env.state(**overrides))
    assert recorder.seen, "the architect model was never called"
    return updates, recorder


def _staged(raw: Any, turn_id: str = "turn-1") -> Dict[str, Any]:
    """The state value ``invoke_graph`` writes for this turn."""
    return {"stage_slide": scoped(turn_id, raw)}


def _stage_of(payload: Dict[str, Any]) -> Any:
    assert "stage_slide" in payload, (
        "the architect's model payload has no stage_slide key (it must be present, "
        "null when there is no stage)"
    )
    return payload["stage_slide"]


def _assert_stage(payload: Dict[str, Any], expected: Optional[Dict[str, int]]) -> None:
    stage = _stage_of(payload)
    if expected is None:
        assert stage is None, f"expected no stage, the model was handed {stage!r}"
        return
    assert type(stage) is dict, f"stage_slide must be a plain dict, got {stage!r}"
    assert set(stage) == STAGE_KEYS, f"stage_slide must be exactly {STAGE_KEYS}: {stage!r}"
    assert stage == expected


def _assert_no_identifiers(payload: Dict[str, Any], *identifiers: str) -> None:
    """None of *identifiers* appears anywhere in the JSON the model is shown."""
    dumped = json.dumps(payload, default=str)
    for identifier in identifiers:
        assert identifier not in dumped, f"{identifier!r} reached the architect's model payload"


# ---------------------------------------------------------------------------
# 1. The state contract (C2)
# ---------------------------------------------------------------------------


class TestStateContract:
    def test_graph_state_declares_stage_slide(self):
        """The runtime silently drops undeclared keys, so the stage would vanish."""
        assert "stage_slide" in get_type_hints(GraphState, include_extras=True)

    def test_stage_slide_is_registered_turn_scoped_with_none_as_empty(self):
        assert "stage_slide" in _EMPTY_FOR, "stage_slide is not registered in _EMPTY_FOR"
        assert _EMPTY_FOR["stage_slide"] is None

    def test_scoped_vals_reads_this_turns_stage_and_discards_an_earlier_one(self):
        if "stage_slide" not in _EMPTY_FOR:
            pytest.fail("stage_slide is not registered in _EMPTY_FOR")
        raw = {"slide_number": 2, "slide_id": "sid-b"}
        assert (
            scoped_vals({"turn_id": "t2", "stage_slide": scoped("t2", raw)}, "stage_slide") == raw
        )
        assert (
            scoped_vals({"turn_id": "t2", "stage_slide": scoped("t1", raw)}, "stage_slide") is None
        )
        assert scoped_vals({"turn_id": "t2", "stage_slide": raw}, "stage_slide") is None, (
            "a raw (unwrapped) value must read as no stage"
        )
        assert scoped_vals({"turn_id": "t2"}, "stage_slide") is None


# ---------------------------------------------------------------------------
# 2. invoke_graph wraps the stage on EVERY invocation (C2)
# ---------------------------------------------------------------------------


class TestInvokeGraphWrapsTheStage:
    def test_a_supplied_stage_is_wrapped_with_this_turns_id(self, fake_graph):
        raw = {"slide_number": 2, "slide_id": "sid-b"}
        invoke_graph("sess-42", {"architect_message": "x", "stage_slide": dict(raw)})
        state = fake_graph.calls[0]["state"]
        assert state["stage_slide"] == {"turn": state["turn_id"], "vals": raw}

    @pytest.mark.parametrize(
        "initial",
        [
            pytest.param({"architect_message": "x"}, id="omitted"),
            pytest.param({"architect_message": "x", "stage_slide": None}, id="explicit-None"),
            pytest.param(None, id="no-initial-at-all"),
        ],
    )
    def test_no_stage_still_writes_this_turns_empty_wrapper(self, fake_graph, initial):
        invoke_graph("sess-42", initial)
        state = fake_graph.calls[0]["state"]
        assert "stage_slide" in state, (
            "invoke_graph must write stage_slide on every invocation, omission included"
        )
        assert state["stage_slide"] == {"turn": state["turn_id"], "vals": None}

    def test_the_next_turn_without_a_stage_overwrites_the_previous_one(self, fake_graph):
        invoke_graph("sess-42", {"stage_slide": {"slide_number": 2, "slide_id": "sid-b"}})
        invoke_graph("sess-42", {})
        first, second = (call["state"] for call in fake_graph.calls)
        assert first.get("stage_slide") == {
            "turn": first["turn_id"],
            "vals": {"slide_number": 2, "slide_id": "sid-b"},
        }
        assert second.get("stage_slide") == {"turn": second["turn_id"], "vals": None}
        assert first["turn_id"] != second["turn_id"]

    def test_a_caller_seeded_wrapper_is_rewrapped_not_trusted(self, fake_graph):
        """A pre-wrapped value from a caller is DATA, re-stamped with this turn."""
        hostile = scoped("some-other-turn", {"slide_number": 1})
        invoke_graph("sess-42", {"stage_slide": hostile})
        state = fake_graph.calls[0]["state"]
        assert state["stage_slide"]["turn"] == state["turn_id"]

    def test_the_wrapper_is_json_native(self, fake_graph):
        invoke_graph("sess-42", {"stage_slide": {"slide_number": 2, "slide_id": "sid-b"}})
        wrapper = fake_graph.calls[0]["state"]["stage_slide"]
        assert json.loads(json.dumps(wrapper)) == wrapper


# ---------------------------------------------------------------------------
# 3. The architect's model payload: identity-safe and sanitised (C3)
# ---------------------------------------------------------------------------


class TestArchitectPayloadStage:
    def test_the_payload_keys_are_the_allowlist_plus_stage_slide(self, graph_env):
        _deck_abc(graph_env)
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
        assert set(rec.seen[0]) == set(ARCHITECT_MODEL_KEYS) | {"stage_slide"}

    def test_both_allowlists_carry_stage_slide(self):
        """The test-fixture literal AND the production projection (C5)."""
        assert "stage_slide" in ARCHITECT_MODEL_KEYS
        assert "stage_slide" in ARCHITECT_RETRY_MODEL_KEYS
        assert "stage_slide" in agent_model_payload.MODEL_PAYLOAD_KEYS["architect"]

    def test_the_projection_keeps_a_stage_and_a_null_stage(self):
        for value in ({"slide_number": 2, "position": 8}, None):
            projected = agent_model_payload.model_payload_for(
                "architect", {"message": "m", "stage_slide": value}
            )
            assert "stage_slide" in projected and projected["stage_slide"] == value

    def test_a_stable_id_resolves_its_current_number_and_position(self, graph_env):
        _deck_abc(graph_env)
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
        _assert_stage(rec.seen[0], {"slide_number": 2, "position": 8})

    def test_no_identifier_reaches_the_model(self, graph_env):
        _deck_abc(graph_env)
        stage = {"slide_number": 2, "slide_id": "sid-b"}
        _, rec = _node(graph_env, **_staged(stage))
        payload = graph_env.skills.calls_for("architect")[0]["payload"]
        row_ids = [r.id for r in graph_env.rows()]
        _assert_stage(payload, {"slide_number": 2, "position": 8})
        _assert_no_identifiers(
            payload, "sid-a", "sid-b", "sid-c", graph_env.session_id, "turn-1", *row_ids
        )

    def test_after_a_reorder_the_stage_follows_the_slide_not_its_old_number(self, graph_env):
        """Staged as slide 2 (sid-b); sid-b now sits last.  Slide 2 is sid-c."""
        _seed(graph_env, [(3, "sid-a"), (8, "sid-c"), (15, "sid-b")])
        _persist(graph_env)
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
        _assert_stage(rec.seen[0], {"slide_number": 3, "position": 15})

    def test_a_deleted_stage_slide_is_no_stage_not_the_slide_now_at_its_number(self, graph_env):
        _seed(graph_env, [(3, "sid-a"), (15, "sid-c")])
        _persist(graph_env, (3, 15))
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
        payload = rec.seen[0]
        assert [e["position"] for e in payload["slide_numbering"]] == [3, 15], (
            "control: slide 2 still exists, so a number fallback would find it"
        )
        _assert_stage(payload, None)

    def test_a_duplicated_id_is_ambiguous_and_is_no_stage(self, graph_env):
        _seed(graph_env, [(3, "sid-a"), (8, "sid-b"), (15, "sid-b")])
        _persist(graph_env)
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
        _assert_stage(rec.seen[0], None)

    def test_an_id_from_another_deck_is_no_stage(self, graph_env):
        """The foreign deck has sid-foreign at position 8 = this deck's slide 2."""
        _deck_abc(graph_env)
        foreign = _foreign_session(graph_env)
        _seed(graph_env, [(8, "sid-foreign")], session_id=foreign)
        _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-foreign"}))
        _assert_stage(rec.seen[0], None)
        _assert_no_identifiers(rec.seen[0], "sid-foreign", foreign)

    @pytest.mark.parametrize(
        "stage",
        [
            pytest.param({"slide_number": 3}, id="no-slide_id-key"),
            pytest.param({"slide_number": 3, "slide_id": None}, id="model_dump-slide_id-None"),
        ],
    )
    def test_without_an_id_the_number_is_looked_up_in_numbering(self, graph_env, stage):
        """Older slides without a stable id: slide 3 of [3, 8, 15] is position 15."""
        _seed(graph_env, [(3, None), (8, None), (15, None)])
        _persist(graph_env)
        _, rec = _node(graph_env, **_staged(stage))
        _assert_stage(rec.seen[0], {"slide_number": 3, "position": 15})

    @pytest.mark.parametrize(
        "stage",
        [
            pytest.param({"slide_number": 4}, id="out-of-range"),
            pytest.param({"slide_number": 0}, id="zero"),
            pytest.param({"slide_number": "2"}, id="numeric-string"),
            pytest.param({"slide_id": "sid-b"}, id="no-number"),
            pytest.param("slide 2", id="not-an-object"),
        ],
    )
    def test_an_invalid_snapshot_is_no_stage(self, graph_env, stage):
        _deck_abc(graph_env)
        _, rec = _node(graph_env, **_staged(stage))
        _assert_stage(rec.seen[0], None)

    def test_no_stage_key_at_all_is_a_null_stage(self, graph_env):
        _deck_abc(graph_env)
        _, rec = _node(graph_env)
        _assert_stage(rec.seen[0], None)

    def test_a_raw_unscoped_stage_is_ignored(self, graph_env):
        """C2: production nodes accept only scoped state; no raw fallback."""
        _deck_abc(graph_env)
        _, rec = _node(graph_env, stage_slide={"slide_number": 2, "slide_id": "sid-b"})
        _assert_stage(rec.seen[0], None)

    def test_an_earlier_turns_stage_is_ignored(self, graph_env):
        _deck_abc(graph_env)
        _, rec = _node(
            graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}, turn_id="turn-0")
        )
        _assert_stage(rec.seen[0], None)

    def test_a_describe_only_turn_has_no_stage(self, graph_env):
        _deck_abc(graph_env)
        recorder = _Recorder(ArchitectOutput(intent="discuss", message=DISCUSS_MSG))
        _, rec = _node(
            graph_env,
            recorder,
            describe_only=scoped("turn-1", True),
            **_staged({"slide_number": 2, "slide_id": "sid-b"}),
        )
        _assert_stage(rec.seen[0], None)

    def test_the_stage_changes_neither_references_nor_numbering(self, graph_env):
        """Explicit "slide 3" stays slide 3 (position 15) with slide 1 on stage."""
        _deck_abc(graph_env)
        message = "Make slide 3 shorter"
        _, staged = _node(
            graph_env,
            architect_message=message,
            **_staged({"slide_number": 1, "slide_id": "sid-a"}),
        )
        _, plain = _node(graph_env, architect_message=message)
        with_stage, without = staged.seen[0], plain.seen[0]
        assert with_stage["slide_references"] == [
            {"text": "slide 3", "slide_numbers": [3], "positions": [15], "out_of_range": []}
        ]
        assert without["slide_references"] == with_stage["slide_references"]
        assert without["slide_numbering"] == with_stage["slide_numbering"]
        _assert_stage(with_stage, {"slide_number": 1, "position": 3})
        _assert_stage(without, None)

    def test_a_stage_never_forces_edit_targets(self, graph_env):
        """A question with a slide on stage stays a question: no targets, no rows touched."""
        _deck_abc(graph_env)
        before = [(r.position, r.slide_id, r.html) for r in graph_env.rows()]
        updates, rec = _node(
            graph_env,
            architect_message="What does this slide say?",
            **_staged({"slide_number": 2, "slide_id": "sid-b"}),
        )
        _assert_stage(rec.seen[0], {"slide_number": 2, "position": 8})
        assert updates["architect_intent"] == "discuss"
        assert updates["target_positions"] is None
        assert [(r.position, r.slide_id, r.html) for r in graph_env.rows()] == before


# ---------------------------------------------------------------------------
# 4. The architect retry keeps the same turn's stage
# ---------------------------------------------------------------------------


def test_the_retry_payload_carries_the_same_stage(graph_env):
    """A refused first answer (replace an unknown position) is retried with the
    same payload plus ``rejected_edit``: the stage is still there, unchanged."""
    _deck_abc(graph_env)
    first = _ops_out([_replace(29, _content("X"))], message="FIRST")
    second = ArchitectOutput(intent="discuss", message=DISCUSS_MSG)
    recorder = _Recorder(first, second)
    _node(graph_env, recorder, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
    assert len(recorder.seen) == 2, f"expected exactly one retry, got {len(recorder.seen)} calls"
    original, retry = recorder.seen
    assert "rejected_edit" in retry and "rejected_edit" not in original
    _assert_stage(original, {"slide_number": 2, "position": 8})
    _assert_stage(retry, {"slide_number": 2, "position": 8})
    assert set(retry) == set(ARCHITECT_RETRY_MODEL_KEYS) | {"stage_slide"}
    _assert_no_identifiers(retry, "sid-b", graph_env.session_id)


# ---------------------------------------------------------------------------
# 5. A REAL compiled graph with a REAL checkpointer, across invoke_graph calls
# ---------------------------------------------------------------------------


@pytest.fixture
def checkpointed(graph_env_threadsafe, monkeypatch):
    """``invoke_graph`` over the shipped compiled graph and a SQL checkpointer.

    The checkpointer persists to the env's file-backed database, so turn 2
    resumes turn 1's checkpointed state on the same thread (``session_id``).  The
    pin and root loaders are injected through ``invoke_graph``'s own parameters.
    """
    from src.core.checkpointer import SqlAlchemyCheckpointSaver

    env = graph_env_threadsafe
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    compiled = build_graph(checkpointer=saver)
    monkeypatch.setattr(builder_module, "_compiled_graph", compiled)
    monkeypatch.setattr(builder_module, "get_session_local", lambda: env.factory)
    env.compiled = compiled
    return env


def _turn(env, initial: Dict[str, Any]) -> Dict[str, Any]:
    return invoke_graph(
        env.session_id,
        initial,
        principal="graph-user@example.com",
        pin_loader=lambda factory, session_id: 1,
        root_loader=lambda factory, session_id: session_id,
    )


def _checkpointed_stage(env) -> Any:
    snapshot = env.compiled.get_state({"configurable": {"thread_id": env.session_id}})
    return snapshot.values.get("stage_slide")


class TestCheckpointedBoundary:
    def test_a_later_turn_without_a_stage_never_inherits_the_checkpointed_one(self, checkpointed):
        env = checkpointed
        _deck_abc(env)
        recorder = _Recorder()
        env.skills.set("architect", recorder)

        _turn(
            env,
            {
                "architect_message": USER_MESSAGE,
                "stage_slide": {"slide_number": 2, "slide_id": "sid-b"},
            },
        )
        assert len(recorder.seen) == 1
        _assert_stage(recorder.seen[0], {"slide_number": 2, "position": 8})
        turn_1 = _checkpointed_stage(env)
        assert isinstance(turn_1, dict) and turn_1.get("vals") == {
            "slide_number": 2,
            "slide_id": "sid-b",
        }, f"control: the checkpoint must carry turn 1's stage, got {turn_1!r}"

        _turn(env, {"architect_message": "And now?"})
        assert len(recorder.seen) == 2
        _assert_stage(recorder.seen[1], None)
        turn_2 = _checkpointed_stage(env)
        assert turn_2.get("vals") is None and turn_2.get("turn") != turn_1.get("turn"), (
            f"turn 2 did not overwrite the checkpointed stage: {turn_2!r}"
        )

        _turn(
            env,
            {
                "architect_message": "This one",
                "stage_slide": {"slide_number": 1, "slide_id": "sid-a"},
            },
        )
        _assert_stage(recorder.seen[2], {"slide_number": 1, "position": 3})

    def test_the_analyst_loop_keeps_the_same_turns_stage(self, checkpointed):
        """architect (ask_data) -> data_analyst -> architect, one turn: both
        architect passes see the stage; the analyst's payload never does."""
        env = checkpointed
        _deck_abc(env)
        recorder = _Recorder(
            ArchitectOutput(
                intent="ask_data",
                message="Fetching the numbers.",
                data_request={"metric": "weekly active users"},
            ),
            ArchitectOutput(intent="discuss", message=DISCUSS_MSG),
        )
        env.skills.set("architect", recorder)
        env.skills.set(
            "data_analyst",
            AnalystOutput(outcome="success", synthesis="WAU is 1.2m.", sources=["genie:wau"]),
        )

        _turn(
            env,
            {
                "architect_message": USER_MESSAGE,
                "stage_slide": {"slide_number": 3, "slide_id": "sid-c"},
            },
        )

        assert len(env.skills.calls_for("data_analyst")) == 1
        assert len(recorder.seen) == 2, f"expected two architect passes, got {len(recorder.seen)}"
        for payload in recorder.seen:
            _assert_stage(payload, {"slide_number": 3, "position": 15})
            _assert_no_identifiers(payload, "sid-c", env.session_id)
        analyst_payload = env.skills.calls_for("data_analyst")[0]["payload"]
        assert "stage_slide" not in analyst_payload
        _assert_no_identifiers(analyst_payload, "sid-c")


# ---------------------------------------------------------------------------
# 6. The shipped instructions carry the stage policy
#
# Literal-text checks over the authored prompt, the packaged manifest prompt and
# the prompt actually ASSEMBLED for the model.  They prove the policy SHIPS; they
# do not prove a live model follows it.
# ---------------------------------------------------------------------------


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).strip().lower()


def _stage_text(prompt: str) -> str:
    """Every ``\\n\\n`` block of *prompt* that names ``stage_slide``, joined, plain."""
    blocks = [block for block in prompt.split("\n\n") if "stage_slide" in block]
    assert blocks, "the architect instructions never mention stage_slide"
    return _plain(" ".join(blocks))


_NEG = r"(\bnot\b|n't\b|\bnever\b|\bno\b)"

#: (description, regex over the plain stage-policy text).  Sentence-bounded.
STAGE_POLICY = (
    ("deictic 'this slide' means the stage slide", r"\bthis slide\b"),
    (
        "an unqualified local edit defaults to the stage slide",
        r"\b(unqualified|default\w*|does not name|doesn't name|names no|without naming)\b",
    ),
    (
        "explicit slide references take precedence over the stage",
        r"slide_references\b[^.]{0,160}\b(win|wins|precedence|over|instead|rather than|first)\b|"
        r"\b(explicit\w*|named)\b[^.]{0,120}\b(win|wins|precedence|over|instead|rather than)\b",
    ),
    (
        "deck-wide requests are not narrowed to the stage",
        r"\b(whole deck|deck-wide|entire deck|every slide|all slides|all the slides)\b",
    ),
    (
        "questions about the stage slide do not edit it",
        rf"\b(question|questions|asks?|discuss\w*)\b[^.]{{0,160}}{_NEG}[^.]{{0,60}}\b(edit|change|mutat)\w*|"
        rf"{_NEG}[^.]{{0,60}}\b(edit|change|mutat)\w*[^.]{{0,160}}\b(question|questions|discuss\w*)\b",
    ),
    (
        "no stage (null) or ambiguity means ask for clarification",
        r"\b(null|none|absent|missing|no stage)\b[^.]{0,200}\b(ask|clarif\w*|which slide)\b|"
        r"\b(ask|clarif\w*|which slide)\b[^.]{0,200}\b(null|none|absent|missing|no stage)\b",
    ),
    (
        "relative references (next/previous slide) have a stated boundary",
        r"\b(next|previous) slide\b",
    ),
)


def _instructions() -> str:
    from src.core.skills.architect import INSTRUCTIONS

    return INSTRUCTIONS


def _packaged_architect_prompt() -> str:
    from src.services.graph_definition_manifest import load_graph_v1_manifest

    manifest = load_graph_v1_manifest()
    return next(d for d in manifest.definitions if d.agent_key == "architect").prompt_text


@pytest.mark.parametrize(("description", "pattern"), STAGE_POLICY, ids=[d for d, _ in STAGE_POLICY])
@pytest.mark.parametrize("source", ["authored", "packaged"])
def test_the_shipped_instructions_state_the_stage_policy(source, description, pattern):
    prompt = _instructions() if source == "authored" else _packaged_architect_prompt()
    assert re.search(pattern, _stage_text(prompt)), (
        f"{source} architect prompt lacks: {description}"
    )


def test_the_packaged_prompt_is_the_authored_prompt():
    assert _packaged_architect_prompt() == _instructions()


def test_the_assembled_prompt_carries_the_policy_and_only_the_sanitised_stage(graph_env):
    """The prompt the runtime would send for a REAL captured payload: authored
    stage policy present, the payload stage exactly ``{slide_number, position}``,
    and no stable id anywhere in the assembled text."""
    from src.services.agent_runtime import AgentAssemblyContext
    from src.services.graph_definition_manifest import load_graph_v1_manifest
    from src.services.prompt_assembler import PromptAssembler

    _deck_abc(graph_env)
    _, rec = _node(graph_env, **_staged({"slide_number": 2, "slide_id": "sid-b"}))
    payload = rec.seen[0]
    definition = next(d for d in load_graph_v1_manifest().definitions if d.agent_key == "architect")
    assembled = PromptAssembler().assemble(
        definition=definition, payload=payload, context=AgentAssemblyContext(False)
    )
    authored = [s for s in assembled.stages if s.stage_id == "authored_prompt"]
    runtime = [s for s in assembled.stages if s.stage_id == "runtime_payload"]
    assert len(authored) == 1 and len(runtime) == 1
    assert "stage_slide" in _plain(authored[0].rendered_text)
    assert json.loads(runtime[0].rendered_text)["stage_slide"] == {"slide_number": 2, "position": 8}
    assert "sid-b" not in assembled.prompt
    assert graph_env.session_id not in assembled.prompt


# ---------------------------------------------------------------------------
# 7. Reviewer addition: a message that is BOTH deictic and numbered
#
# "Move this slide after slide 5" carries a resolved Slide Reference (slide 5)
# AND means the stage slide.  "Explicit references win" alone reads as "slide 5
# is the slide they mean"; the policy must say the deictic phrase still means
# the stage slide and the named slide keeps its own role (the move's anchor).
# Literal-text check: it proves the rule ships, not that a live model follows it.
# ---------------------------------------------------------------------------

#: (description, regex over the plain stage-policy text).
COMBINED_POLICY = (
    (
        "a combined deictic + numbered request keeps 'this slide' as the stage slide",
        r"\balso names?\b[^.]{0,200}\bthis slide\W{0,3}\s?is still the stage slide\b",
    ),
    (
        "the named slide in a combined request keeps its own role (an anchor)",
        r"\beach named slide keeps its own role\b[^.]{0,80}\banchor\b",
    ),
    (
        "the stage slide can itself be the anchor of a new or moved slide",
        r"\bstage slide is an anchor\b[^.]{0,80}\bnew or moved slide\b",
    ),
)


@pytest.mark.parametrize(
    ("description", "pattern"), COMBINED_POLICY, ids=[d for d, _ in COMBINED_POLICY]
)
@pytest.mark.parametrize("source", ["authored", "packaged"])
def test_a_combined_deictic_and_numbered_request_is_covered(source, description, pattern):
    prompt = _instructions() if source == "authored" else _packaged_architect_prompt()
    assert re.search(pattern, _stage_text(prompt)), (
        f"{source} architect prompt lacks: {description}"
    )


def test_a_combined_request_carries_both_the_reference_and_the_stage(graph_env):
    """'Move this slide after slide 3' with slide 1 on stage: slide 3 is resolved as
    a reference (position 15) and the stage is still slide 1 (position 3): the
    reference does not displace the stage, nor the stage the reference."""
    _deck_abc(graph_env)
    _, rec = _node(
        graph_env,
        architect_message="Move this slide after slide 3",
        **_staged({"slide_number": 1, "slide_id": "sid-a"}),
    )
    payload = rec.seen[0]
    assert payload["slide_references"] == [
        {"text": "slide 3", "slide_numbers": [3], "positions": [15], "out_of_range": []}
    ]
    _assert_stage(payload, {"slide_number": 1, "position": 3})
