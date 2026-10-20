"""#317 A2 — a deleted turn and a reset reach no agent and no checkpoint.

The acceptance this file holds: "The architect's conversation context
(``_conversation``) and the graph checkpoint reflect the deletion/reset, so a
reset chat really starts fresh for the agent."

**The model is NOT real.**  ``AgentRuntime`` is stubbed by the ``SkillRecorder``
(edit targets are scripted with ``edit_target_positions``), so these tests prove
what each agent is GIVEN and what the checkpoint HOLDS after a delete or a
reset.  They do not prove what a model would do with that input.  Everything
else is the shipped code: ``build_graph()``'s compiled graph over a real
file-backed SQLite database with the real ``SqlAlchemyCheckpointSaver`` (the
``graph_turn_env`` harness), and, for the two transport tests, the real async
job (``process_chat_request`` and ``poll_chat``) and the real SSE entry point
(``send_message_streaming``).

Why the checkpoint is scanned in full
-------------------------------------
The saver keeps EVERY checkpoint of every turn, and nothing prunes them.  A
turn's ``__start__`` input and its ``architect_message`` channel carry the
user's text, and ``architect_message`` later carries the architect's reply.
After a later turn the latest checkpoint no longer has an earlier turn's text,
but the historical ones still do.  So ``_thread_holds`` reads every checkpoint
and every pending write of the thread, not just the latest; a test that read
only ``get_tuple`` would pass on a delete that left the thread.

What a delete costs the thread (plan D5)
----------------------------------------
Any delete deletes the WHOLE thread, so a delete of the middle turn also drops
the later turn's checkpoints.  Test 1 records that: after the delete and one
more turn, the thread holds the new turn and nothing of turns 1-3.  The kept
turns reach the architect from their persisted rows only.

How the delete and the clear are reached
----------------------------------------
``delete_message``, ``clear_context`` and ``resolve_engine_mode`` import
``get_db_session`` and ``get_checkpointer`` lazily, so the reachable targets are
``src.core.database.get_db_session`` and ``src.core.checkpointer.get_checkpointer``
(as in ``test_clear_context_graph_turn.py``).  The two transport fixtures already
patch the first, so their tests patch only the checkpointer.  None of the
fixtures exposes a saver; each test builds its own on the harness's factory,
which is the database the graph's own saver writes to.

Every database here is the harness's file-backed SQLite file: the CI job's
``DATABASE_URL`` (PostgreSQL) is never reached, because every read and write
goes through a patched ``get_db_session`` or the harness factory.
"""

from __future__ import annotations

import contextlib
import json
from typing import List
from unittest.mock import patch

from src.api.services.chat_service import ChatService, resolve_engine_mode
from src.api.services.session_manager import SessionManager, get_session_manager
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.database.models.session import SessionMessage, UserSession
from src.domain.skill_io import BuilderOutput
from src.services.conversation_pins import load_conversation_pin
from src.services.graph.nodes import _advisory_text
from src.services.spec_sync import mark_dirty, sweep_once
from tests.integration.conftest import _make_fake_db
from tests.integration.conftest_stub_skills import edited_brief
from tests.integration.test_architect_reply_is_persisted import (  # noqa: F401
    AUTHOR,
    REPLY,
    async_turn_env,
)
from tests.integration.test_graph_mode_turn import AUTHOR as SSE_AUTHOR
from tests.integration.test_graph_mode_turn import graph_chat_env  # noqa: F401
from tests.integration.test_sweeper_describe_only import (  # noqa: F401
    _age_the_marker,
    sweeper_env,
)

# Sentinels no stub produces.  The KEEP turns survive the delete in the rows;
# the DELETE turn must be gone from every payload and every checkpoint.
ALPHA = "ALPHA-KEEP build me a deck about puffins"
BETA = "BETA-DELETE make slide 3 shorter"
GAMMA = "GAMMA-KEEP make slide 2 punchier"
DELTA = "DELTA-ASK make slide 1 punchier"

# The recorder's own architect replies (conftest_stub_skills._skill_architect).
BUILT_FOUR = "Building 4 slide(s)."
BETA_REPLY = "Editing slide(s) [2]."
GAMMA_REPLY = "Editing slide(s) [1]."

# What deck_reviewer_node persists after every completed turn here.
ADVISORY = _advisory_text([])

OWNER = "owner@example.com"


def _thread_config(sid: str) -> dict:
    return {"configurable": {"thread_id": sid, "checkpoint_ns": ""}}


def _thread_holds(saver, sid: str, needle: str) -> bool:
    """True when ANY checkpoint or pending write of the thread contains *needle*."""
    return any(
        needle in repr(t.checkpoint) or needle in repr(t.pending_writes)
        for t in saver.list(_thread_config(sid))
    )


def _columns(row) -> dict:
    """Every column of an ORM row: "unchanged" means unchanged, not a chosen few."""
    return {c.name: getattr(row, c.name) for c in type(row).__table__.columns}


def _edited_html(position: int, brief: str) -> str:
    """The builder output this file installs: it carries the brief it was given."""
    return f"<div class='slide'><h1>Slide {position}</h1><p>{brief}</p></div>"


def _builder(payload: dict) -> BuilderOutput:
    """A builder whose HTML carries its brief, so a kept edit is visible in a row.

    The recorder's default builder emits ``builder_html(position)``, which is the
    same for every brief, so with it no row could show that turn 2's edit
    survived the delete.
    """
    position = payload["position"]
    return BuilderOutput(
        position=position,
        html=_edited_html(position, payload["slide_spec"]["content_brief"]),
        scripts="",
    )


@contextlib.contextmanager
def _delete_reaches(env):
    """Point the service's lazily imported DB and checkpointer at the harness."""
    with patch("src.core.database.get_db_session", _make_fake_db(env.factory)), \
            patch(
                "src.core.checkpointer.get_checkpointer",
                lambda: SqlAlchemyCheckpointSaver(session_factory=env.factory),
            ):
        yield


def _raw_rows(factory, sid: str) -> List[SessionMessage]:
    """Every row of the session, hidden or not, in transcript order, with request_id.

    ``get_messages`` returns no ``request_id``; the transport tests need it to
    show which transport wrote the turn.
    """
    with factory() as db:
        owner = db.query(UserSession).filter(UserSession.session_id == sid).one()
        return (
            db.query(SessionMessage)
            .filter(SessionMessage.session_id == owner.id)
            .order_by(SessionMessage.created_at.asc(), SessionMessage.id.asc())
            .all()
        )


def _contents(env) -> List[str]:
    return [m["content"] for m in env.messages()]


def _payload_mentions(recorder, *needles: str) -> List[str]:
    """The agent calls whose payload contains any of *needles* (empty is good)."""
    return [
        call["name"]
        for call in recorder.calls
        if any(needle in repr(call["payload"]) for needle in needles)
    ]


# ===========================================================================
# 1. Deleting the middle of three turns
# ===========================================================================


def test_after_deleting_a_turn_neither_the_architect_nor_the_checkpoint_carries_it(
    graph_turn_env, monkeypatch
):
    env = graph_turn_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    manager = get_session_manager()
    monkeypatch.setattr(env.recorder, "_skill_builder", _builder)

    # -- Turn 1: build four slides -------------------------------------------
    env.recorder.configure(slide_count=4)
    manager.add_message(sid, "user", ALPHA, message_type="user_input")
    first = env.run(initial={"architect_message": ALPHA})
    assert first["architect_intent"] == "build" and first["error_state"] is None

    # -- Turn 2 (the one deleted): edit slide 3 -------------------------------
    env.recorder.configure(slide_count=4, edit_target_positions={2})
    beta_id = manager.add_message(sid, "user", BETA, message_type="user_input")["id"]
    second = env.run(initial={"architect_message": BETA})
    assert second["architect_intent"] == "edit" and second["error_state"] is None

    # -- Turn 3: edit slide 2 -------------------------------------------------
    env.recorder.configure(slide_count=4, edit_target_positions={1})
    manager.add_message(sid, "user", GAMMA, message_type="user_input")
    third = env.run(initial={"architect_message": GAMMA})
    assert third["architect_intent"] == "edit" and third["error_state"] is None

    # -- Non-vacuity: what the delete has to remove, and what it must keep ----
    assert _contents(env) == [
        ALPHA, BUILT_FOUR, ADVISORY,
        BETA, BETA_REPLY, ADVISORY,
        GAMMA, GAMMA_REPLY, ADVISORY,
    ], "precondition: three turns of three rows each"
    assert _thread_holds(saver, sid, "BETA-DELETE"), (
        "precondition: the scan cannot see turn 2's message in the checkpoint"
    )
    assert _thread_holds(saver, sid, BETA_REPLY), (
        "precondition: the scan cannot see turn 2's reply in the checkpoint"
    )
    assert _thread_holds(saver, sid, "GAMMA-KEEP"), "precondition: turn 3 is in it"

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1, 2, 3], "precondition: four committed rows"
    spec_before = json.loads(env.deck_row().deck_spec_json)
    briefs = {s["position"]: s["content_brief"] for s in spec_before["slides"]}
    # Turn 2's and turn 3's edits are in the deck, so "not rolled back" can fail.
    assert rows[2].html == _edited_html(2, edited_brief("brief-2"))
    assert rows[1].html == _edited_html(1, edited_brief("brief-1"))
    assert briefs[2] == edited_brief("brief-2")
    assert briefs[1] == edited_brief("brief-1")
    row_columns_before = {p: _columns(row) for p, row in rows.items()}
    deck_columns_before = _columns(env.deck_row())
    pin_before = load_conversation_pin(env.factory, sid)
    assert pin_before == env.graph_release_id, "precondition: the deck is pinned"

    # -- Delete turn 2 --------------------------------------------------------
    with _delete_reaches(env):
        result = ChatService().delete_message(sid, beta_id, deleted_by=OWNER)
        engine = resolve_engine_mode(sid)

    assert result["deleted_messages"] == 3, "BETA, its reply and its deck review advisory"
    assert result["hidden_message_id"] is None
    assert list(saver.list(_thread_config(sid))) == [], "the graph thread survived"
    assert _contents(env) == [
        ALPHA, BUILT_FOUR, ADVISORY,
        GAMMA, GAMMA_REPLY, ADVISORY,
    ]

    # Not rolled back: the deck, its Spec and its rows are exactly as they were,
    # so slide 3 keeps turn 2's edit.
    assert _columns(env.deck_row()) == deck_columns_before
    assert {p: _columns(row) for p, row in env.rows_by_position().items()} == (
        row_columns_before
    )
    assert json.loads(env.deck_row().deck_spec_json) == spec_before
    assert load_conversation_pin(env.factory, sid) == pin_before
    assert engine == "graph"

    # -- Turn 4: edit slide 1 -------------------------------------------------
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=4, edit_target_positions={0})
    manager.add_message(sid, "user", DELTA, message_type="user_input")
    final = env.run(initial={"architect_message": DELTA})

    # -- What every agent was given -------------------------------------------
    assert final["architect_intent"] == "edit" and final["error_state"] is None
    architect = env.recorder.calls_for("architect")
    assert len(architect) == 1
    payload = architect[0]["payload"]
    assert payload["conversation"] == [
        {"role": "user", "content": ALPHA},
        {"role": "assistant", "content": BUILT_FOUR},
        {"role": "user", "content": GAMMA},
        {"role": "assistant", "content": GAMMA_REPLY},
        {"role": "user", "content": DELTA},
    ]
    assert payload["message"] == DELTA
    assert payload["current_deck_spec"] == spec_before
    # Every agent of the turn, not only the architect.
    called = {call["name"] for call in env.recorder.calls}
    assert {"architect", "builder", "build_reviewer", "deck_reviewer"} <= called, called
    assert _payload_mentions(env.recorder, "BETA-DELETE", BETA_REPLY) == [], (
        "a deleted turn's text reached an agent"
    )

    # -- What the checkpoint holds --------------------------------------------
    assert not _thread_holds(saver, sid, "BETA-DELETE")
    assert not _thread_holds(saver, sid, BETA_REPLY)
    # D5's whole-thread cost: turn 3's checkpoints went with the thread.  The
    # kept turn reaches the architect from its rows only (above).
    assert not _thread_holds(saver, sid, "GAMMA-KEEP")
    assert not _thread_holds(saver, sid, GAMMA_REPLY)
    assert _thread_holds(saver, sid, "DELTA-ASK"), "positive control: turn 4 is in it"


# ===========================================================================
# 2. A reset (#323's Clear chat) starts fresh
# ===========================================================================

FIRST = "SENTINEL-FIRST build puffins"
SECOND = "SENTINEL-SECOND add a diet slide"
SECOND_REPLY = "SENTINEL-REPLY diet added"
NEW_ASK = "NEW-ASK shorten slide 2"


def test_after_a_reset_no_message_from_before_reaches_any_agent_or_the_checkpoint(
    graph_turn_env,
):
    env = graph_turn_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    manager = get_session_manager()

    # -- Before: a build, then one more exchange -------------------------------
    env.recorder.configure(slide_count=3)
    manager.add_message(sid, "user", FIRST, message_type="user_input")
    first = env.run(initial={"architect_message": FIRST})
    assert first["architect_intent"] == "build" and first["error_state"] is None
    manager.add_message(sid, "user", SECOND, message_type="user_input")
    manager.add_message(sid, "assistant", SECOND_REPLY, message_type="llm_response")

    assert _thread_holds(saver, sid, "SENTINEL-FIRST"), (
        "precondition: the scan cannot see the first turn in the checkpoint"
    )
    assert [m["content"] for m in env.messages() if m["role"] == "user"] == [
        FIRST, SECOND,
    ], "precondition: the transcript the reset removes"

    # -- Reset ----------------------------------------------------------------
    with _delete_reaches(env):
        ChatService().clear_context(sid, cleared_by=OWNER)
        engine = resolve_engine_mode(sid)

    assert env.messages() == []
    assert list(saver.list(_thread_config(sid))) == [], "the graph thread survived"
    assert engine == "graph"

    # -- The next turn: edit slide 2 ------------------------------------------
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    manager.add_message(sid, "user", NEW_ASK, message_type="user_input")
    final = env.run(initial={"architect_message": NEW_ASK})

    assert final["architect_intent"] == "edit" and final["error_state"] is None
    called = {call["name"] for call in env.recorder.calls}
    assert {"architect", "builder", "build_reviewer", "deck_reviewer"} <= called, called
    assert _payload_mentions(env.recorder, "SENTINEL") == [], (
        "a message from before the reset reached an agent"
    )
    payload = env.recorder.calls_for("architect")[0]["payload"]
    assert payload["conversation"] == [{"role": "user", "content": NEW_ASK}]
    assert not _thread_holds(saver, sid, "SENTINEL")
    assert _thread_holds(saver, sid, "NEW-ASK"), "positive control: the new turn is in it"


# ===========================================================================
# 3. The polling transport: one turn, every poll row of it, goes
# ===========================================================================

POLL_ONE = "POLL-ONE draft puffins"
POLL_TWO = "POLL-TWO tighten the intro"
POLL_TWO_REPLY = "POLL-TWO-REPLY Two slides, the intro cut to one line."
POLL_THREE = "POLL-THREE make it shorter"
POLL_THREE_REPLY = "POLL-THREE-REPLY Shorter it is."


def test_a_polling_turn_is_one_deletable_turn_and_its_poll_rows_go_with_it(
    async_turn_env, graph_turn_env  # noqa: F811 (the imported fixture)
):
    env = async_turn_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=graph_turn_env.factory)

    # Turn 1 discusses (one reply).  Turn 2 builds, so it writes TWO poll rows:
    # the architect's reply and the deck review advisory.
    rid1 = env.run(POLL_ONE)
    env.recorder.configure(slide_count=2)
    env.architect_builds(POLL_TWO_REPLY)
    rid2 = env.run(POLL_TWO)

    # -- Non-vacuity -----------------------------------------------------------
    raw = [(r.role, r.message_type, r.content, r.request_id)
           for r in _raw_rows(graph_turn_env.factory, sid)]
    assert raw == [
        ("user", "user_query", POLL_ONE, rid1),
        ("assistant", "llm_response", REPLY, rid1),
        ("user", "user_query", POLL_TWO, rid2),
        ("assistant", "llm_response", POLL_TWO_REPLY, rid2),
        ("assistant", "info", ADVISORY, rid2),
    ], "precondition: each turn's rows carry its request id"
    assert [e["content"] for e in env.poll(rid2)["events"]] == [
        POLL_TWO_REPLY, ADVISORY,
    ], "precondition: the poll for turn 2 delivers both rows"
    assert list(saver.list(_thread_config(sid))) != [], "precondition: a thread exists"
    turn_one = SessionManager().get_messages(sid)[:2]

    # The poll events never carry the user row; the id comes from the transcript
    # read GET /messages uses.
    poll_two = [
        m for m in SessionManager().get_messages(sid) if m["content"] == POLL_TWO
    ]
    assert len(poll_two) == 1 and poll_two[0]["message_type"] == "user_query"
    assert isinstance(poll_two[0]["id"], int)

    # -- Delete turn 2 --------------------------------------------------------
    with patch("src.core.checkpointer.get_checkpointer", lambda: saver):
        result = ChatService().delete_message(sid, poll_two[0]["id"], deleted_by=AUTHOR)

    assert result["deleted_messages"] == 3
    assert SessionManager().get_messages_for_request(rid2) == []
    assert env.poll(rid2)["events"] == []
    assert REPLY in [e["content"] for e in env.poll(rid1)["events"]]
    assert SessionManager().get_messages(sid) == turn_one
    assert list(saver.list(_thread_config(sid))) == [], "the graph thread survived"

    # -- The next polling turn ------------------------------------------------
    env.recorder.reset_observations()
    env.architect_builds(POLL_THREE_REPLY)
    env.run(POLL_THREE)

    payloads = env.architect_payloads()
    assert len(payloads) == 1
    assert payloads[0]["conversation"] == [
        {"role": "user", "content": POLL_ONE},
        {"role": "assistant", "content": REPLY},
        {"role": "user", "content": POLL_THREE},
    ]
    assert _payload_mentions(env.recorder, "POLL-TWO") == []
    assert not _thread_holds(saver, sid, "POLL-TWO")
    assert _thread_holds(saver, sid, "POLL-THREE"), "positive control"


# ===========================================================================
# 4. The SSE transport: rows with no request id are still one turn
# ===========================================================================

SSE_ONE = "SSE-ONE build me a deck about puffins"
SSE_TWO = "SSE-TWO add a summary slide"


def test_an_sse_turn_is_one_deletable_turn(
    graph_chat_env, graph_turn_env  # noqa: F811 (the imported fixture)
):
    env = graph_chat_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=graph_turn_env.factory)

    env.recorder.configure(slide_count=3)
    env.run(message=SSE_ONE, is_first_message=True)
    turn_one = [
        (m["id"], m["role"], m["content"], m["message_type"])
        for m in SessionManager().get_messages(sid)
    ]
    assert [row[2:] for row in turn_one] == [
        (SSE_ONE, "user_input"),
        ("Building 3 slide(s).", "llm_response"),
        (ADVISORY, "info"),
    ], "precondition: turn 1's rows"

    env.recorder.configure(slide_count=3, edit_target_positions={1})
    env.run(message=SSE_TWO, is_first_message=False)

    # -- Non-vacuity: the SSE path writes no request id, so only role and order
    # can group this turn.
    raw = _raw_rows(graph_turn_env.factory, sid)
    assert [(r.role, r.message_type, r.content, r.request_id) for r in raw[3:]] == [
        ("user", "user_input", SSE_TWO, None),
        ("assistant", "llm_response", "Editing slide(s) [1].", None),
        ("assistant", "info", ADVISORY, None),
    ], "precondition: turn 2's SSE rows"
    assert list(saver.list(_thread_config(sid))) != [], "precondition: a thread exists"

    sse_two = [m for m in SessionManager().get_messages(sid) if m["content"] == SSE_TWO]
    assert len(sse_two) == 1

    with patch("src.core.checkpointer.get_checkpointer", lambda: saver):
        result = ChatService().delete_message(
            sid, sse_two[0]["id"], deleted_by=SSE_AUTHOR
        )

    assert result["deleted_messages"] == 3
    assert [
        (m["id"], m["role"], m["content"], m["message_type"])
        for m in SessionManager().get_messages(sid)
    ] == turn_one
    assert list(saver.list(_thread_config(sid))) == [], "the graph thread survived"


# ===========================================================================
# 5. A delete that lands while the arc-review sweeper is running a turn
# ===========================================================================
#
# As in test_clear_context_graph_turn.py: the sweeper runs a graph turn on the
# owner's thread without the session lock, loads the thread before its architect
# runs and checkpoints every channel after each superstep.  A delete committed
# during the review's model call deletes the thread, and the review then wrote
# it back with the deleted turn's findings and scoped state, plus a reply from
# an architect given the deleted turn's text; the next turn resumed it.  The
# stub architect quotes the conversation it was given, which makes a real
# model's dependence on its payload visible.

RACE_KEEP = "RACE-KEEP build me a deck about puffins"
RACE_DELETE = "RACE-DELETE make slide 2 shorter"
RACE_NEXT = "RACE-NEXT make slide 1 punchier"
RACE_FINDING = "content overflows the frame"  # objective_finding()'s message


def test_a_delete_during_an_arc_review_leaves_nothing_of_the_deleted_turn(
    sweeper_env, monkeypatch  # noqa: F811 (the imported fixture)
):
    env = sweeper_env
    sid = env.session_id
    saver = SqlAlchemyCheckpointSaver(session_factory=env.factory)
    manager = get_session_manager()
    stub_architect = env.recorder._skill_architect

    # -- Turn 1 (kept): a build ----------------------------------------------
    env.recorder.configure(slide_count=3)
    manager.add_message(sid, "user", RACE_KEEP, message_type="user_input")
    env.run(initial={"architect_message": RACE_KEEP})

    # -- Turn 2 (deleted): an edit whose review leaves a finding --------------
    env.recorder.configure(
        slide_count=3, edit_target_positions={1}, objective_findings_at={1}
    )
    doomed_id = manager.add_message(
        sid, "user", RACE_DELETE, message_type="user_input"
    )["id"]
    second = env.run(initial={"architect_message": RACE_DELETE})
    assert second["architect_intent"] == "edit" and second["error_state"] is None
    doomed_turn = env.last_turn_id
    assert _thread_holds(saver, sid, doomed_turn), "precondition: turn 2's state"
    assert _thread_holds(saver, sid, RACE_FINDING), "precondition: turn 2's finding"

    # -- A hand edit schedules an arc review, and its debounce has passed -----
    assert mark_dirty(sid, "hand-editor@example.com") is True
    _age_the_marker(env)

    # -- The user deletes turn 2 while the review's model call is running -----
    attempts: list = []

    def architect_during_the_review(payload):
        try:
            with _delete_reaches(env):
                ChatService().delete_message(sid, doomed_id, deleted_by=OWNER)
            attempts.append("deleted")
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

    if attempts[0] != "deleted":
        # Refused while the review ran; the user retries once it has finished.
        assert RACE_DELETE in _contents(env), "a refused delete changed rows"
        with _delete_reaches(env):
            ChatService().delete_message(sid, doomed_id, deleted_by=OWNER)

    # -- A committed delete leaves nothing of the deleted turn in the thread --
    assert RACE_DELETE not in _contents(env)
    assert not _thread_holds(saver, sid, "RACE-DELETE"), (
        "the review wrote a reply built from the deleted turn into the thread"
    )
    assert not _thread_holds(saver, sid, doomed_turn), (
        "the review wrote the deleted turn's state back into the thread"
    )
    assert not _thread_holds(saver, sid, RACE_FINDING), (
        "the review wrote the deleted turn's findings back into the thread"
    )

    # -- The next turn carries nothing of it ----------------------------------
    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={0})
    manager.add_message(sid, "user", RACE_NEXT, message_type="user_input")
    final = env.run(initial={"architect_message": RACE_NEXT})

    assert final["architect_intent"] == "edit" and final["error_state"] is None
    assert final["findings"] == [], "the next turn inherited the deleted turn's findings"
    assert _payload_mentions(env.recorder, "RACE-DELETE", RACE_FINDING) == []
    assert not _thread_holds(saver, sid, doomed_turn)
    assert not _thread_holds(saver, sid, "RACE-DELETE")
    assert _thread_holds(saver, sid, "RACE-NEXT"), "positive control"

    # -- How: the delete is refused while the review holds its claim ----------
    from src.api.services.chat_service import ArcReviewInFlightError

    assert isinstance(attempts[0], ArcReviewInFlightError), attempts[0]
