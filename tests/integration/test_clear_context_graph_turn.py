"""#323 A2 — after a clear, an edit turn runs from the Spec and the committed rows.

**This is the only test that runs the real graph — the real architect NODE and
its payload — after a clear.**  The model is NOT real: ``AgentRuntime`` is
stubbed, and the edit's target (slide 3, position 2) is scripted on the
recorder (``edit_target_positions={2}``).  So this proves what the architect is
GIVEN after a clear and that only the targeted slide is rebuilt; it does not
prove a model would choose slide 3.  No test in CI runs a model after a clear.
The unit suite (``tests/unit/test_clear_context.py``) pins each reader of the
transcript on its own; this one runs build, clear, edit through
``build_graph()``'s compiled graph, over a real file-backed database, with the
real ``SqlAlchemyCheckpointSaver`` (the ``graph_turn_env`` harness — see
``tests/integration/test_graph_orchestration.py`` for how it is registered and
why its knobs live on the recorder).

What a clear must leave the next turn
-------------------------------------
The architect never sees slide HTML.  The committed slides reach it as
``committed_slide_count`` and as ``previous_deck_review`` keyed by the digest
of the committed rows; the deck itself reaches it as ``current_deck_spec``.
None of those come from the graph thread or the transcript, so a clear that
deletes both must change none of them.  What it MUST change is
``conversation``: before #323 the kept first row (the engine-mode marker) was
replayed to the architect, so the deck's original prompt came back as if the
user had just said it (plan Context 4's probe).

How the clear is reached
------------------------
``clear_context`` imports ``get_db_session`` and ``get_checkpointer`` lazily,
so the reachable targets are ``src.core.database.get_db_session`` and
``src.core.checkpointer.get_checkpointer``.  They are patched for the clear
(and the mode read) only, so both turns run exactly as every other
orchestration test runs them.  The saver is a real one on the harness's own
database: on file-backed SQLite the pre-#323 two-transaction clear could not
complete at all (``database is locked``).

What the fixture teardown does NOT prove
----------------------------------------
``graph_turn_env``'s teardown checks every runtime call used
``env.graph_release_id``, but ``_GraphTurnEnv._turn_state`` FORCES that id into
the state and ``env.run`` never goes through ``invoke_graph``'s pin loader — so
it holds even if the clear nulled the pin.  The pin evidence is the
``load_conversation_pin`` read-back after the clear, the read ``invoke_graph``
itself uses.  Likewise ``resolve_engine_mode(sid) == "graph"`` holds for a
graph deck with NO marker at all; the engine-preservation proof is the unit
suite's legacy-phrase and legacy-duplicate tests.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from src.api.services.chat_service import ChatService, resolve_engine_mode
from src.api.services.session_manager import get_session_manager
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.domain.skill_io import BuilderOutput
from src.services.conversation_pins import load_conversation_pin
from src.services.deck_review_store import compute_deck_digest
from src.services.spec_sync import mark_dirty, sweep_once
from tests.integration.conftest import _make_fake_db
from tests.integration.conftest_stub_skills import edited_brief
from tests.integration.test_sweeper_describe_only import (  # noqa: F401
    _age_the_marker,
    sweeper_env,
)

_FIRST_PROMPT = "Build me a deck about puffins"
_EDIT_ASK = "Make slide 3 shorter"
_EDIT_POSITION = 2  # "slide 3"


def _columns(row) -> dict:
    """Every column of an ORM row: "unchanged" means unchanged, not a chosen few."""
    return {c.name: getattr(row, c.name) for c in type(row).__table__.columns}


def _thread_config(sid: str) -> dict:
    return {"configurable": {"thread_id": sid, "checkpoint_ns": ""}}


def _slides_by_position(spec: dict) -> dict:
    return {slide["position"]: slide for slide in spec["slides"]}


def _edited_html(position: int, brief: str) -> str:
    """Turn 2's builder output: carries the brief, so the rebuilt row differs."""
    return f"<div class='slide'><h1>Slide {position}</h1><p>{brief}</p></div>"


@contextlib.contextmanager
def _clear_reaches(env):
    """Point the clear's lazily-imported DB and checkpointer at the harness."""
    with patch("src.core.database.get_db_session", _make_fake_db(env.factory)), \
            patch(
                "src.core.checkpointer.get_checkpointer",
                lambda: SqlAlchemyCheckpointSaver(session_factory=env.factory),
            ):
        yield


def test_after_a_clear_an_edit_turn_runs_from_the_spec_and_the_committed_rows(
    graph_turn_env, monkeypatch
):
    env = graph_turn_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    manager = get_session_manager()

    # -- Turn 1: build four slides, then one more exchange -------------------
    env.recorder.configure(slide_count=4)
    manager.add_message(sid, "user", _FIRST_PROMPT, message_type="user_input")
    first = env.run(initial={"architect_message": _FIRST_PROMPT})
    assert first["architect_intent"] == "build" and first["error_state"] is None
    manager.add_message(sid, "user", "Add a slide on their diet", message_type="user_input")
    manager.add_message(sid, "assistant", "Done: slide 4 covers diet.",
                        message_type="llm_response")

    rows_before = {p: row.html for p, row in env.rows_by_position().items()}
    assert sorted(rows_before) == [0, 1, 2, 3], "precondition: four committed rows"
    row_columns_before = {p: _columns(row) for p, row in env.rows_by_position().items()}
    deck_columns_before = _columns(env.deck_row())
    spec_before = json.loads(env.deck_row().deck_spec_json)
    assert sorted(_slides_by_position(spec_before)) == [0, 1, 2, 3], "precondition"
    assert saver.get_tuple(_thread_config(sid)) is not None, (
        "precondition: turn 1 left a graph thread for the clear to delete"
    )
    assert [m["content"] for m in env.messages() if m["role"] == "user"] == [
        _FIRST_PROMPT, "Add a slide on their diet",
    ], "precondition: the transcript the clear removes"

    # -- Clear ---------------------------------------------------------------
    with _clear_reaches(env):
        ChatService().clear_context(sid, cleared_by="owner@example.com")

        assert saver.get_tuple(_thread_config(sid)) is None
        assert env.messages() == []
        # Holds for a graph deck even with no marker: NOT engine evidence (see
        # the module docstring).
        assert resolve_engine_mode(sid) == "graph"

    # The Conversation Pin, read the way invoke_graph reads it.
    assert load_conversation_pin(env.factory, sid) == env.graph_release_id
    # The deck, its Spec and its rows are exactly as they were.
    assert _columns(env.deck_row()) == deck_columns_before
    assert {p: _columns(row) for p, row in env.rows_by_position().items()} == (
        row_columns_before
    )

    # -- Turn 2: "make slide 3 shorter", persisted the way chat_service does --
    manager.add_message(sid, "user", _EDIT_ASK, message_type="user_input")
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=4, edit_target_positions={_EDIT_POSITION})

    def _builder(payload: dict) -> BuilderOutput:
        position = payload["position"]
        return BuilderOutput(
            position=position,
            html=_edited_html(position, payload["slide_spec"]["content_brief"]),
            scripts="",
        )

    monkeypatch.setattr(env.recorder, "_skill_builder", _builder)

    final = env.run(initial={"architect_message": _EDIT_ASK})

    # -- What the architect was given ----------------------------------------
    payload = env.recorder.calls_for("architect")[0]["payload"]
    assert payload["conversation"] == [{"role": "user", "content": _EDIT_ASK}]
    assert payload["message"] == _EDIT_ASK
    assert payload["current_deck_spec"] == spec_before
    assert payload["committed_slide_count"] == 4
    assert payload["previous_deck_review"] is not None, (
        "turn 1's deck review, keyed by the committed rows' digest, was not found"
    )
    assert payload["previous_deck_review"]["digest"] == compute_deck_digest(
        [rows_before[p] for p in sorted(rows_before)]
    )

    # -- What the turn did ---------------------------------------------------
    assert final["architect_intent"] == "edit"
    assert final["error_state"] is None
    assert env.recorder.positions("builder") == [_EDIT_POSITION]
    assert [
        call["payload"]["slide_spec"]["content_brief"]
        for call in env.recorder.calls_for("builder")
    ] == [edited_brief(f"brief-{_EDIT_POSITION}")]

    rows_after = {p: row.html for p, row in env.rows_by_position().items()}
    assert sorted(rows_after) == [0, 1, 2, 3]
    for untouched in (0, 1, 3):
        assert rows_after[untouched] == rows_before[untouched], untouched
    assert rows_after[_EDIT_POSITION] == _edited_html(
        _EDIT_POSITION, edited_brief(f"brief-{_EDIT_POSITION}")
    )
    assert rows_after[_EDIT_POSITION] != rows_before[_EDIT_POSITION]

    # The persisted Spec was revised at slide 3's brief and nowhere else.
    spec_after = json.loads(env.deck_row().deck_spec_json)
    slides_before = _slides_by_position(spec_before)
    slides_after = _slides_by_position(spec_after)
    assert sorted(slides_after) == [0, 1, 2, 3]
    for untouched in (0, 1, 3):
        assert slides_after[untouched] == slides_before[untouched], untouched
    assert slides_after[_EDIT_POSITION] == {
        **slides_before[_EDIT_POSITION],
        "content_brief": edited_brief(f"brief-{_EDIT_POSITION}"),
    }
    assert {k: v for k, v in spec_after.items() if k != "slides"} == {
        k: v for k, v in spec_before.items() if k != "slides"
    }


# ===========================================================================
# A clear that lands while the arc-review sweeper is running a turn
# ===========================================================================
#
# The sweeper (``spec_sync.sweep_once`` -> ``run_arc_review`` -> ``invoke_graph``)
# runs a whole graph turn on the deck OWNER's thread, whose ``thread_id`` is the
# session id (``builder.invoke_graph``), and it never takes the session lock that
# the clear route checks.  The turn loads the thread's latest checkpoint before
# its architect runs and writes a checkpoint after every superstep, and each
# checkpoint carries EVERY channel it holds.  So a clear that commits during the
# review's model call deletes the thread, and the review's next superstep writes
# it back: the pre-clear turn's ``findings`` (an all-turns log), its turn-scoped
# wrappers, and a reply from an architect that was given the cleared
# conversation.  The next turn resumes that checkpoint.
#
# The stub architect quotes the conversation it was given in its reply.  A real
# model's reply is a function of its payload; the quote makes that dependency
# visible without a model.

_RACE_PROMPT = "SENTINEL-RACE build me a deck about puffins"
_RACE_NEXT_ASK = "AFTER-THE-CLEAR make slide 2 shorter"
_HAND_EDITOR = "hand-editor@example.com"
_FINDING_TEXT = "content overflows the frame"  # objective_finding()'s message


def _thread_holds(saver, sid: str, needle: str) -> bool:
    """True when ANY checkpoint or pending write of the thread contains *needle*."""
    return any(
        needle in repr(t.checkpoint) or needle in repr(t.pending_writes)
        for t in saver.list(_thread_config(sid))
    )


def _payload_mentions(recorder, needle: str) -> list:
    return [c["name"] for c in recorder.calls if needle in repr(c["payload"])]


def test_a_clear_during_an_arc_review_leaves_nothing_from_before_it(
    sweeper_env, monkeypatch  # noqa: F811 (the imported fixture)
):
    env = sweeper_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    manager = get_session_manager()
    stub_architect = env.recorder._skill_architect

    # -- Before: a build whose review leaves a finding in the thread ----------
    env.recorder.configure(slide_count=3, objective_findings_at={1})
    manager.add_message(sid, "user", _RACE_PROMPT, message_type="user_input")
    first = env.run(initial={"architect_message": _RACE_PROMPT})
    assert first["architect_intent"] == "build" and first["error_state"] is None
    pre_clear_turn = env.last_turn_id
    transcript_before = env.messages()
    assert _thread_holds(saver, sid, pre_clear_turn), "precondition: turn 1's state"
    assert _thread_holds(saver, sid, _FINDING_TEXT), "precondition: turn 1's finding"

    # -- A hand edit schedules an arc review, and its debounce has passed -----
    assert mark_dirty(sid, _HAND_EDITOR) is True
    _age_the_marker(env)

    # -- The user clears while the review's model call is running -------------
    attempts: list = []

    def architect_during_the_review(payload):
        try:
            with _clear_reaches(env):
                ChatService().clear_context(sid, cleared_by="owner@example.com")
            attempts.append("cleared")
        except Exception as exc:  # asserted on below, by type
            attempts.append(exc)
        out = stub_architect(payload)
        said = [m["content"] for m in payload["conversation"] if m["role"] == "user"]
        return out.model_copy(
            update={"message": f"Re-described the arc. You had asked: {said}"}
        )

    monkeypatch.setattr(env.recorder, "_skill_architect", architect_during_the_review)
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3)
    assert sweep_once() == 1, "precondition: the sweeper claimed the marker"
    monkeypatch.setattr(env.recorder, "_skill_architect", stub_architect)
    assert len(attempts) == 1, "precondition: the review's architect ran once"

    if attempts[0] != "cleared":
        # Refused while the review ran: nothing changed, and the user retries
        # once it has finished, as the 409 tells them to.
        assert env.messages() == transcript_before, "a refused clear changed rows"
        with _clear_reaches(env):
            ChatService().clear_context(sid, cleared_by="owner@example.com")

    # -- A committed clear leaves nothing from before it in the thread --------
    assert env.messages() == []
    assert not _thread_holds(saver, sid, "SENTINEL-RACE"), (
        "the review wrote a reply built from the cleared conversation into the thread"
    )
    assert not _thread_holds(saver, sid, pre_clear_turn), (
        "the review wrote the pre-clear turn's state back into the cleared thread"
    )
    assert not _thread_holds(saver, sid, _FINDING_TEXT), (
        "the review wrote the pre-clear turn's findings back into the cleared thread"
    )

    # -- The next turn starts fresh -------------------------------------------
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    manager.add_message(sid, "user", _RACE_NEXT_ASK, message_type="user_input")
    final = env.run(initial={"architect_message": _RACE_NEXT_ASK})

    assert final["architect_intent"] == "edit" and final["error_state"] is None
    assert final["findings"] == [], "the next turn inherited the pre-clear findings"
    payload = env.recorder.calls_for("architect")[0]["payload"]
    assert payload["conversation"] == [{"role": "user", "content": _RACE_NEXT_ASK}]
    assert _payload_mentions(env.recorder, "SENTINEL-RACE") == []
    assert _payload_mentions(env.recorder, _FINDING_TEXT) == []
    assert not _thread_holds(saver, sid, pre_clear_turn)
    assert not _thread_holds(saver, sid, "SENTINEL-RACE")
    assert _thread_holds(saver, sid, "AFTER-THE-CLEAR"), "positive control"

    # -- How: the clear is refused while the review holds its claim -----------
    from src.api.services.chat_service import ArcReviewInFlightError

    assert isinstance(attempts[0], ArcReviewInFlightError), attempts[0]
