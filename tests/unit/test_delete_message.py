"""Deleting one chat message (#317): the service, then the route.

The SERVICE half: ``ChatService.delete_message`` (#317 Task 2, plan D2-D10).
What a delete must do, read back from real rows:

* The unit is a TURN: the user message and every later row of the SAME
  session up to the next ``role='user'`` row -- replies, clarifications,
  ``info`` notices, ``reasoning``, ``tool_call`` and ``tool_result`` rows --
  whatever their type and whether or not they carry a ``request_id``.
* The session's earliest user row is never deleted: ``message_count`` counts it,
  which keeps the title from regenerating.  (Since Deck Mode the engine is read
  off the deck owner's ``deck_mode`` column, so a delete cannot change it.)  A
  delete of the first turn re-types it ``engine_mode_marker``, which hides it
  from every transcript read, and deletes the rest of its turn.
* The graph thread is deleted, and one ``usage_events`` ``message_deleted`` row
  names who deleted.  The row delete, the re-type, the event and the thread
  delete are ONE transaction.
* Nothing else changes: save points keep what they captured, and every reader
  (the panel's ``get_messages``, the architect's ``conversation``, the
  monolith's history, a new save point) sees the turn gone.

Real sqlite throughout.  Helpers come from #323's ``test_clear_context`` by
NAME only: importing one of its ``Test*`` classes would make pytest collect it
here a second time.  The one-transaction tests use a FILE-BACKED engine and the
REAL ``SqlAlchemyCheckpointSaver``, where a thread delete on a second
connection blocks on SQLite's write lock.  ``usage_events`` rows are read back
by the stored string, the way admin analytics reads them.

Patch targets: like ``clear_context``, ``delete_message`` imports
``get_db_session`` and ``get_checkpointer`` lazily, so ``_patched`` patches the
source attributes (and ``session_manager.get_db_session``, which every
``SessionManager`` read goes through).

Red before Task 2, test by test: ``AttributeError`` (``ChatService`` has no
``delete_message``).  A test that needs ``MessageNotFoundError`` or
``EVENT_MESSAGE_DELETED`` imports it inside its body before anything else
(``ImportError``), so the file still collects.

The ROUTE half (Task 3) follows the service half, below the marked boundary at
the end of this file.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from src.api.services.chat_service import (
    ChatService,
    resolve_engine_mode,
)
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.database.models.session import SessionMessage, UserSession
from src.database.models.usage_event import UsageEvent
from tests.unit.conftest import _make_factory
from tests.unit.test_clear_context import (  # noqa: F401 (file_backed_db: a fixture)
    _PLAIN_MESSAGE,
    _add_message,
    _assert_thread_rows,
    _marker_type,
    _messages_of,
    _patched,
    _patched_with_failing_commit,
    _RecordingSaver,
    _seed_clearable_session,
    _seed_transcript,
    _session_pk,
    _set_deck_mode,
    _version_rows,
    file_backed_db,
)

# The values stored in ``usage_events.event_type``.  Read back by these
# strings, so a constant with another value fails too.
_MESSAGE_DELETED = "message_deleted"
_CONTEXT_CLEARED = "context_cleared"

# A fixed instant: every row a test seeds is placed at ``_T0 + offset``, so the
# transcript order is the seed order by construction.
_T0 = datetime(2026, 1, 1, 9, 0, 0)

# The three-turn transcript most tests start from, as
# (label, offset s, role, content, message_type, request_id).  The types are
# the ones the live paths write, so the architect's and the monolith's own type
# filters admit the rows they replay.  U2's turn is a polling turn (request id
# set) with a tool call, its tool result and an UNTAGGED notice (N2: the SSE
# path and the sweeper write no request id); U3's is a tour-style ``chat``.
_TURNS = (
    ("U1", 0, "user", _PLAIN_MESSAGE, "user_input", None),
    ("A1", 5, "assistant", "Building 4 slide(s).", "llm_response", None),
    ("N1", 6, "assistant", "Deck review complete.", "info", None),
    ("U2", 10, "user", "Add a slide on their diet", "user_query", "req-2"),
    ("T2", 11, "assistant", "Querying diet data", "tool_call", "req-2"),
    ("R2", 12, "tool", "diet table", "tool_result", "req-2"),
    ("A2", 13, "assistant", "Slide 4 covers diet.", "llm_response", "req-2"),
    ("N2", 14, "assistant", "Slide 4: the model was briefly unavailable.", "info", None),
    ("U3", 20, "user", "Make slide 3 shorter", "chat", None),
    ("A3", 21, "assistant", "Which slide is slide 3?", "clarification", None),
)
_LABELS = [label for label, *_ in _TURNS]
_CONTENT = {label: content for label, _, _, content, _, _ in _TURNS}
_ROLE = {label: role for label, _, role, _, _, _ in _TURNS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_session(factory, *, created_by: str = "owner@example.com") -> str:
    sid = f"del-{uuid.uuid4().hex[:12]}"
    db = factory()
    try:
        db.add(UserSession(session_id=sid, created_by=created_by))
        db.commit()
    finally:
        db.close()
    return sid


def _add_row(factory, sid: str, *, role: str, content: str, message_type,
             offset_seconds: float, request_id: str | None = None) -> int:
    """One chat row at ``_T0 + offset_seconds``; returns its id.

    ``_add_message`` (test_clear_context) cannot set ``request_id``.
    """
    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == sid).one()
        row = SessionMessage(
            session_id=us.id,
            role=role,
            content=content,
            message_type=message_type,
            request_id=request_id,
            created_at=_T0 + timedelta(seconds=offset_seconds),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _seed_turns(factory, *, contents: dict[str, str] | None = None,
                created_by: str = "owner@example.com") -> SimpleNamespace:
    """A fresh session holding ``_TURNS`` (with *contents* overriding by label).

    Returns ``sid``, ``pk``, ``ids`` (label -> row id) and ``label_of``.
    """
    contents = contents or {}
    sid = _new_session(factory, created_by=created_by)
    ids = {
        label: _add_row(
            factory, sid, role=role, content=contents.get(label, content),
            message_type=message_type, offset_seconds=offset, request_id=request_id,
        )
        for label, offset, role, content, message_type, request_id in _TURNS
    }
    seeded = SimpleNamespace(
        sid=sid,
        pk=_session_pk(factory, sid),
        ids=ids,
        label_of={row_id: label for label, row_id in ids.items()},
    )
    assert _labels(factory, seeded) == _LABELS, "seed precondition"
    return seeded


def _rows(factory, sid: str) -> list[tuple]:
    """Every raw row of *sid* in transcript order, every column a delete could touch."""
    return [
        (r.id, r.session_id, r.role, r.content, r.message_type, r.request_id,
         r.created_at, r.metadata_json)
        for r in _messages_of(factory, sid)
    ]


def _retyped(row: tuple, message_type: str) -> tuple:
    """*row* (a ``_rows`` tuple) with only its ``message_type`` changed."""
    return row[:4] + (message_type,) + row[5:]


def _labels(factory, seeded: SimpleNamespace) -> list[str]:
    """The labels of *seeded*'s raw rows, in order (a row it did not seed: ``new``)."""
    return [seeded.label_of.get(r.id, "new") for r in _messages_of(factory, seeded.sid)]


def _only(before: list[tuple], seeded: SimpleNamespace, labels: list[str]) -> list[tuple]:
    """The rows of *before* that carry *labels*, unchanged."""
    keep = {seeded.ids[label] for label in labels}
    return [row for row in before if row[0] in keep]


def _events(factory, event_type: str) -> list[tuple[str, int | None]]:
    """Every committed usage event of *event_type*, as (username, session_id)."""
    db = factory()
    try:
        return [
            (e.username, e.session_id)
            for e in db.query(UsageEvent)
            .filter(UsageEvent.event_type == event_type)
            .order_by(UsageEvent.id)
            .all()
        ]
    finally:
        db.close()


def _all_events(factory) -> list[tuple[str, str, int | None]]:
    """Every committed usage event, as (event_type, username, session_id)."""
    db = factory()
    try:
        return [
            (e.event_type, e.username, e.session_id)
            for e in db.query(UsageEvent).order_by(UsageEvent.id).all()
        ]
    finally:
        db.close()


def _message_not_found_error() -> type[Exception]:
    """``MessageNotFoundError``, imported only when a test needs it.

    It is new in Task 2; a module-scope import would stop this whole file
    collecting before it lands.
    """
    from src.api.services.session_manager import MessageNotFoundError

    return MessageNotFoundError


def _delete(sid: str, message_id: int, *, deleted_by: str = "owner@example.com"):
    return ChatService().delete_message(sid, message_id, deleted_by=deleted_by)


class _SessionSnoopingSaver(_RecordingSaver):
    """A ``_RecordingSaver`` that also notes, AT CALL TIME, which ``UserSession``
    rows the ``session=`` it was handed has loaded.

    A session opened afresh for the saver is bound to the same engine as the
    delete's own, so the bind alone cannot tell them apart; only the delete's
    own session has already loaded the session it is deleting from.
    """

    def __init__(self) -> None:
        super().__init__()
        self.loaded: list[set[str]] = []

    def delete_thread(self, thread_id: str, *, session: Any = None) -> None:
        self.loaded.append(
            set()
            if session is None
            else {
                obj.session_id
                for obj in session.identity_map.values()
                if isinstance(obj, UserSession)
            }
        )
        super().delete_thread(thread_id, session=session)


# ---------------------------------------------------------------------------
# The service: the turn is the unit.
# ---------------------------------------------------------------------------


class TestTheTurnIsTheUnit:
    def test_deleting_a_message_deletes_its_whole_turn_and_nothing_else(
        self, _session_unit_engine
    ):
        """The tool row R2 (role ``tool``) and the untagged notice N2 (no
        request id) go with U2: grouping is by role and order, not by
        ``request_id`` or type.  Every row that stays is unchanged, column for
        column."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        with _patched(factory, _RecordingSaver()):
            result = _delete(seeded.sid, seeded.ids["U2"])

        assert result == {
            "status": "deleted",
            "session_id": seeded.sid,
            "message_id": seeded.ids["U2"],
            "deleted_messages": 5,
            "hidden_message_id": None,
        }
        kept = ["U1", "A1", "N1", "U3", "A3"]
        assert _labels(factory, seeded) == kept
        assert _rows(factory, seeded.sid) == _only(before, seeded, kept)

    def test_the_last_turn_runs_to_the_end_of_the_transcript(self, _session_unit_engine):
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        with _patched(factory, _RecordingSaver()):
            result = _delete(seeded.sid, seeded.ids["U3"])

        assert (result["deleted_messages"], result["hidden_message_id"]) == (2, None)
        kept = _LABELS[:-2]
        assert _labels(factory, seeded) == kept
        assert _rows(factory, seeded.sid) == _only(before, seeded, kept)

    @pytest.mark.parametrize("user_type", ["user_input", "user_query", "chat", None])
    def test_every_user_message_type_starts_a_turn(self, user_type, _session_unit_engine):
        """SSE writes ``user_input``, polling and MCP ``user_query``, the tour
        ``chat``, and ``POST /sessions/{id}/messages`` ``None``.  The type is on
        the deleted turn's head AND on the next turn's head, so it both starts a
        turn and ends the one before."""
        factory = _make_factory(_session_unit_engine)
        sid = _new_session(factory)
        ids = {}
        for label, offset, role, content, message_type in (
            ("U1", 0, "user", _PLAIN_MESSAGE, "user_input"),
            ("A1", 5, "assistant", "deck built", "llm_response"),
            ("U2", 10, "user", "make slide 3 shorter", user_type),
            ("A2", 15, "assistant", "done", "llm_response"),
            ("N2", 16, "assistant", "Deck review complete.", "info"),
            ("U3", 20, "user", "now add a chart", user_type),
            ("A3", 25, "assistant", "chart added", "llm_response"),
        ):
            ids[label] = _add_row(factory, sid, role=role, content=content,
                                  message_type=message_type, offset_seconds=offset)
        before = _rows(factory, sid)

        with _patched(factory, _RecordingSaver()):
            result = _delete(sid, ids["U2"])

        assert (result["deleted_messages"], result["hidden_message_id"]) == (3, None)
        keep = {ids["U1"], ids["A1"], ids["U3"], ids["A3"]}
        assert _rows(factory, sid) == [row for row in before if row[0] in keep]

    @pytest.mark.parametrize(
        ("head", "kept", "hidden"),
        [("U2", ["U1", "A1"], False), ("U1", ["U1", "U2", "A2"], True)],
        ids=["a_later_turn", "the_first_turn"],
    )
    def test_the_turn_is_read_in_transcript_order_not_id_order(
        self, head, kept, hidden, _session_unit_engine
    ):
        """A1 is WRITTEN last (the highest id) but placed at 5 s, inside U1's
        turn: a late row, or SQLite reusing a deleted id (D13).  The panel
        shows rows by ``(created_at, id)``, so the delete must group them in
        that order too; grouped by id, A1 would follow A2 and go with U2's
        turn (and stay behind when U1's turn is deleted)."""
        factory = _make_factory(_session_unit_engine)
        sid = _new_session(factory)
        ids = {}
        for label, offset, role, content, message_type in (
            ("U1", 0, "user", _PLAIN_MESSAGE, "user_input"),
            ("U2", 10, "user", "make slide 3 shorter", "user_input"),
            ("A2", 15, "assistant", "done", "llm_response"),
            ("A1", 5, "assistant", "deck built", "llm_response"),
        ):
            ids[label] = _add_row(factory, sid, role=role, content=content,
                                  message_type=message_type, offset_seconds=offset)
        assert ids["A1"] > ids["A2"], "precondition: A1 has the highest id"
        before = _rows(factory, sid)
        assert [row[0] for row in before] == [ids[x] for x in ("U1", "A1", "U2", "A2")], (
            "precondition: transcript order is not id order"
        )

        with _patched(factory, _RecordingSaver()):
            result = _delete(sid, ids[head])

        assert (result["deleted_messages"], result["hidden_message_id"]) == (
            2 if not hidden else 1,
            ids[head] if hidden else None,
        )
        expected = [row for row in before if row[0] in {ids[x] for x in kept}]
        if hidden:
            expected[0] = _retyped(expected[0], _marker_type())
        assert _rows(factory, sid) == expected

    @pytest.mark.parametrize(
        "case",
        [
            "an_assistant_reply",
            "a_tool_row",
            "an_absent_id",
            "the_hidden_marker",
            "another_sessions_user_message",
        ],
    )
    def test_an_id_that_is_not_a_visible_user_message_of_this_session_is_not_found(
        self, case, _session_unit_engine
    ):
        """One error for every case, so the route's 404 says nothing about ids
        in other sessions (D3).  And a refused delete changes nothing: no row
        in either session, no thread delete, no attribution."""
        error = _message_not_found_error()
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        other = _seed_turns(factory)

        if case == "the_hidden_marker":
            # The clear gets a saver of its own, so the delete's starts empty.
            with _patched(factory, _RecordingSaver()):
                ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")
            [marker] = _rows(factory, seeded.sid)
            assert (marker[0], marker[4]) == (seeded.ids["U1"], _marker_type()), (
                "precondition: the clear kept U1 as the hidden marker"
            )

        every_id = [*seeded.ids.values(), *other.ids.values()]
        message_id = {
            "an_assistant_reply": seeded.ids["A1"],
            "a_tool_row": seeded.ids["R2"],
            "an_absent_id": max(every_id) + 1000,
            "the_hidden_marker": seeded.ids["U1"],
            "another_sessions_user_message": other.ids["U2"],
        }[case]
        before = (_rows(factory, seeded.sid), _rows(factory, other.sid))

        saver = _RecordingSaver()
        with _patched(factory, saver), pytest.raises(error):
            _delete(seeded.sid, message_id)

        assert (_rows(factory, seeded.sid), _rows(factory, other.sid)) == before
        assert saver.deleted == []
        assert _events(factory, _MESSAGE_DELETED) == []

    def test_an_unknown_session_raises_session_not_found(self, _session_unit_engine):
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        saver = _RecordingSaver()
        with _patched(factory, saver), pytest.raises(SessionNotFoundError):
            _delete("no-such-session", seeded.ids["U2"])

        assert _rows(factory, seeded.sid) == before
        assert saver.deleted == []
        assert _events(factory, _MESSAGE_DELETED) == []


# ---------------------------------------------------------------------------
# The session's earliest user row is hidden, never deleted (D4).
# ---------------------------------------------------------------------------


class TestTheFirstUserMessageIsHiddenNotDeleted:
    def test_deleting_the_first_turn_hides_its_user_row_and_deletes_its_replies(
        self, _session_unit_engine
    ):
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        with _patched(factory, _RecordingSaver()):
            result = _delete(seeded.sid, seeded.ids["U1"])
            visible = SessionManager().get_messages(seeded.sid)

        assert result == {
            "status": "deleted",
            "session_id": seeded.sid,
            "message_id": seeded.ids["U1"],
            "deleted_messages": 2,
            "hidden_message_id": seeded.ids["U1"],
        }
        # U1 is still there, and only its type changed; A1 and N1 are gone.
        rest = ["U2", "T2", "R2", "A2", "N2", "U3", "A3"]
        assert _labels(factory, seeded) == ["U1", *rest]
        assert _rows(factory, seeded.sid) == [
            _retyped(before[0], _marker_type()),
            *_only(before, seeded, rest),
        ]
        # The panel's read starts at U2.
        assert [(m["id"], m["content"]) for m in visible] == [
            (seeded.ids[label], _CONTENT[label]) for label in rest
        ]

    def test_a_legacy_deck_stays_legacy_after_its_first_turn_is_deleted(
        self, _session_unit_engine
    ):
        """The deck's mode is stored on its (owner) row: deleting its first turn,
        or adding a later one, does not move this legacy deck onto the graph."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        _set_deck_mode(factory, seeded.sid, "legacy")

        with _patched(factory, _RecordingSaver()):
            assert resolve_engine_mode(seeded.sid) == "monolith", "precondition"

            _delete(seeded.sid, seeded.ids["U1"])
            assert resolve_engine_mode(seeded.sid) == "monolith"

            _add_row(factory, seeded.sid, role="user", content="Now add a summary slide",
                     message_type="user_input", offset_seconds=30)
            assert resolve_engine_mode(seeded.sid) == "monolith"

    def test_a_transcript_that_opens_with_an_assistant_row_hides_its_first_user_row(
        self, _session_unit_engine
    ):
        """Legacy decks, and decks whose first build failed, can open with an
        assistant row.  The row a delete keeps is the earliest USER row (role
        only), not the earliest row: deleting the first user turn hides U1 and
        leaves A0, which belongs to no turn."""
        factory = _make_factory(_session_unit_engine)
        sid = _new_session(factory)
        _set_deck_mode(factory, sid, "legacy")
        ids = {}
        for label, offset, role, content, message_type in (
            ("A0", 0, "assistant", "Welcome back.", "llm_response"),
            ("U1", 5, "user", _PLAIN_MESSAGE, "user_input"),
            ("A1", 10, "assistant", "deck built", "llm_response"),
            ("U2", 20, "user", "make slide 3 shorter", "user_input"),
            ("A2", 25, "assistant", "done", "llm_response"),
        ):
            ids[label] = _add_row(factory, sid, role=role, content=content,
                                  message_type=message_type, offset_seconds=offset)
        before = _rows(factory, sid)

        with _patched(factory, _RecordingSaver()):
            assert resolve_engine_mode(sid) == "monolith", "precondition: a legacy deck"

            result = _delete(sid, ids["U1"])

            assert resolve_engine_mode(sid) == "monolith"

        assert (result["hidden_message_id"], result["deleted_messages"]) == (ids["U1"], 1)
        assert _rows(factory, sid) == [
            before[0],
            _retyped(before[1], _marker_type()),
            *before[3:],
        ]

    def test_message_count_keeps_the_hidden_row_so_the_title_is_not_regenerated(
        self, _session_unit_engine
    ):
        """``is_first_message = message_count == 0`` gates title generation: a
        deck whose only turn was deleted is not on its first message."""
        from src.services.graph_configuration import bootstrap_graph_configuration

        factory = _make_factory(_session_unit_engine)
        bootstrap_graph_configuration(factory)  # get_session projects the pin (C4)
        sid = _new_session(factory)
        head = _add_row(factory, sid, role="user", content=_PLAIN_MESSAGE,
                        message_type="user_input", offset_seconds=0)
        _add_row(factory, sid, role="assistant", content="Building 4 slide(s).",
                 message_type="llm_response", offset_seconds=5)
        _add_row(factory, sid, role="assistant", content="Deck review complete.",
                 message_type="info", offset_seconds=6)

        with _patched(factory, _RecordingSaver()):
            assert SessionManager().get_session(sid)["message_count"] == 3, "precondition"

            result = _delete(sid, head)

            assert SessionManager().get_session(sid)["message_count"] == 1
        assert (result["hidden_message_id"], result["deleted_messages"]) == (head, 2)

    def test_deleting_the_first_message_keeps_the_deck_locked(self, _session_unit_engine):
        """Deleting the message that locked the deck does not unlock its Deck Mode.

        The deck is locked to legacy by its first message through the real lock
        (``add_user_message``), and that message's turn is the deck's only one.
        After deleting it:

        - a message asking for agent mode is refused with ``DeckModeLockedError``.
          An unlocked deck would take it and lock to agent instead.  An active
          Graph Release is seeded, so that agent lock could not fail for another
          reason and hide a lost lock;
        - the stored mode is still legacy;
        - ``message_count`` is above zero, so the next turn is not a "first
          message" and the title is not regenerated.  The deleted turn was the
          only one, so a delete that took the hidden row too would leave zero.
        """
        from src.api.services.session_manager import DeckModeLockedError
        from src.services.graph_configuration import bootstrap_graph_configuration

        factory = _make_factory(_session_unit_engine)
        bootstrap_graph_configuration(factory)  # the active release; get_session projects it
        sid = _new_session(factory)

        with _patched(factory, _RecordingSaver()):
            manager = SessionManager()
            first = manager.add_user_message(
                sid, _PLAIN_MESSAGE, message_type="user_input", requested_deck_mode="legacy"
            )
            assert (first["deck_mode"], first["locked_now"]) == ("legacy", True), (
                "precondition: the first message locked the deck to legacy"
            )
            # Clock-relative, so the reply follows the locking message (``_add_row``
            # places rows at the fixed past ``_T0``).
            _add_message(factory, sid, role="assistant", content="Building 4 slide(s).",
                         message_type="llm_response", offset_seconds=5)

            result = _delete(sid, first["id"])
            assert (result["hidden_message_id"], result["deleted_messages"]) == (
                first["id"], 1
            ), "precondition: the delete took the first-turn path"

            with pytest.raises(DeckModeLockedError) as refused:
                manager.add_user_message(
                    sid, "now switch to agent", message_type="user_input",
                    requested_deck_mode="agent",
                )
            assert refused.value.deck_mode == "legacy"

            after = manager.get_session(sid)
            assert after["deck_mode"] == "legacy"
            assert after["message_count"] > 0

    def test_the_hidden_first_message_cannot_be_deleted_again(self, _session_unit_engine):
        error = _message_not_found_error()
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        saver = _RecordingSaver()
        with _patched(factory, saver):
            first = _delete(seeded.sid, seeded.ids["U1"])
            after_first = _rows(factory, seeded.sid)

            with pytest.raises(error):
                _delete(seeded.sid, seeded.ids["U1"])

        assert first["hidden_message_id"] == seeded.ids["U1"], "precondition"
        assert _rows(factory, seeded.sid) == after_first
        assert saver.deleted == [seeded.sid]
        assert _events(factory, _MESSAGE_DELETED) == [("owner@example.com", seeded.pk)]

    def test_a_duplicate_of_a_legacy_deck_whose_first_turn_was_deleted_stays_legacy_and_shows_no_chat(  # noqa: E501
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """The copy takes the owner's stored ``deck_mode``, so it keeps the
        source's engine without carrying the hidden first row: it has no message
        rows at all, and its chat panel is empty, as a duplicate's always is."""
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory, session_with_spec_and_messages)
        _set_deck_mode(factory, sid, "legacy")
        head, *_ = _messages_of(factory, sid)

        with _patched(factory, _RecordingSaver()):
            assert resolve_engine_mode(sid) == "monolith", "precondition: a legacy deck"

            # Its first turn is [user _PLAIN_MESSAGE, assistant "deck built"] (C5).
            result = _delete(sid, head.id)
            assert (result["hidden_message_id"], result["deleted_messages"]) == (head.id, 1)
            assert resolve_engine_mode(sid) == "monolith"

            assert _messages_of(factory, sid)[0].message_type == _marker_type(), (
                "precondition: the delete hid the first row"
            )

            new = SessionManager().duplicate_session(sid, "copier@example.com")["session_id"]
            assert new != sid

            assert SessionManager().get_messages(new) == []
            assert resolve_engine_mode(new) == "monolith"

        assert _messages_of(factory, new) == []
        db = factory()
        try:
            copy = db.query(UserSession).filter(UserSession.session_id == new).one()
            assert (copy.deck_mode, copy.graph_release_id) == ("legacy", None)
        finally:
            db.close()

    def test_a_contributor_deletes_in_their_own_session_only(self, contributor_session):
        """A contributor's rows are its own: its first turn is hidden on ITS
        earliest row (not the owner's), and the owner's transcript is never
        touched.  The deck's engine is read off the owner's row (legacy here)."""
        factory = contributor_session._factory
        owner_sid = contributor_session._owner_session_id
        contrib_sid = contributor_session.contributor_session_id

        _set_deck_mode(factory, owner_sid, "legacy")
        _add_row(factory, owner_sid, role="user", content=_PLAIN_MESSAGE,
                 message_type="user_input", offset_seconds=0)
        _add_row(factory, owner_sid, role="assistant", content="deck built",
                 message_type="llm_response", offset_seconds=5)
        first_ask = _add_row(factory, contrib_sid, role="user", content="my own first ask",
                             message_type="user_query", offset_seconds=10, request_id="req-c1")
        _add_row(factory, contrib_sid, role="assistant", content="on it",
                 message_type="llm_response", offset_seconds=11, request_id="req-c1")
        second_ask = _add_row(factory, contrib_sid, role="user", content="and a second",
                              message_type="user_query", offset_seconds=20, request_id="req-c2")
        _add_row(factory, contrib_sid, role="assistant", content="done too",
                 message_type="llm_response", offset_seconds=21, request_id="req-c2")
        owner_before = _rows(factory, owner_sid)
        contrib_before = _rows(factory, contrib_sid)
        hidden_first_ask = _retyped(contrib_before[0], _marker_type())

        saver = _RecordingSaver()
        with _patched(factory, saver):
            assert resolve_engine_mode(contrib_sid) == "monolith", (
                "precondition: the deck is legacy, read off the owner's row"
            )

            first = _delete(contrib_sid, first_ask, deleted_by="contributor@example.com")
            assert (first["hidden_message_id"], first["deleted_messages"]) == (first_ask, 1)
            assert _rows(factory, contrib_sid) == [hidden_first_ask, *contrib_before[2:]]

            second = _delete(contrib_sid, second_ask, deleted_by="contributor@example.com")
            assert (second["hidden_message_id"], second["deleted_messages"]) == (None, 2)
            assert _rows(factory, contrib_sid) == [hidden_first_ask]

            assert resolve_engine_mode(contrib_sid) == "monolith"

        assert _rows(factory, owner_sid) == owner_before
        assert saver.deleted == [contrib_sid, contrib_sid]
        contrib_pk = _session_pk(factory, contrib_sid)
        assert _events(factory, _MESSAGE_DELETED) == [
            ("contributor@example.com", contrib_pk),
            ("contributor@example.com", contrib_pk),
        ]


# ---------------------------------------------------------------------------
# Every transcript reader sees the turn gone.
# ---------------------------------------------------------------------------


class TestEveryReaderSeesTheDeletion:
    def test_the_architect_conversation_omits_the_deleted_turn(self, _session_unit_engine):
        """``nodes._conversation`` is the architect payload's ``conversation``.

        It swallows a read failure as ``[]``, so the BEFORE assertion is what
        proves this test reads the seeded rows at all.  Its type filter drops
        ``info`` and the tool rows, so U2's turn shows there as U2 and A2.
        """
        from src.services.graph.nodes import _conversation

        def turns(*labels: str) -> list[dict[str, str]]:
            return [{"role": _ROLE[label], "content": _CONTENT[label]} for label in labels]

        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        with _patched(factory, _RecordingSaver()):
            assert _conversation(seeded.sid) == turns("U1", "A1", "U2", "A2", "U3", "A3"), (
                "precondition: U2's turn is in the conversation before the delete"
            )

            _delete(seeded.sid, seeded.ids["U2"])

            assert _conversation(seeded.sid) == turns("U1", "A1", "U3", "A3")

    def test_the_monolith_history_omits_the_deleted_turn(self, _session_unit_engine):
        """``_hydrate_chat_history`` is the legacy agent's history."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        def hydrated() -> tuple[int, list[tuple[type, str]]]:
            history = ChatMessageHistory()
            count = ChatService()._hydrate_chat_history(seeded.sid, history)
            return count, [(type(m), m.content) for m in history.messages]

        def expected(*labels: str) -> tuple[int, list[tuple[type, str]]]:
            return len(labels), [
                (HumanMessage if _ROLE[label] == "user" else AIMessage, _CONTENT[label])
                for label in labels
            ]

        with _patched(factory, _RecordingSaver()):
            assert hydrated() == expected("U1", "A1", "U2", "A2", "U3", "A3"), (
                "precondition: U2's turn hydrates before the delete"
            )

            _delete(seeded.sid, seeded.ids["U2"])

            assert hydrated() == expected("U1", "A1", "U3", "A3")


# ---------------------------------------------------------------------------
# Save points stay exactly as they are (D10).
# ---------------------------------------------------------------------------


class TestSavePoints:
    def test_a_delete_leaves_every_save_point_untouched(self, _session_unit_engine):
        """A save point keeps the chat it captured, so its preview still shows a
        later-deleted turn.  Every column of every version row is compared."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        with _patched(factory, _RecordingSaver()):
            manager = SessionManager()
            manager.create_version(seeded.sid, "v1", deck_dict={"title": "t", "slides": []})
            manager.create_version(seeded.sid, "v2", deck_dict={"title": "t", "slides": []})
            before = _version_rows(factory, seeded.sid)
            assert [v["version_number"] for v in before] == [1, 2], "precondition"
            for v in before:
                assert [m["id"] for m in json.loads(v["chat_history_json"])] == [
                    seeded.ids[label] for label in _LABELS
                ], "precondition: each save point captured the whole chat"

            _delete(seeded.sid, seeded.ids["U2"])

        after = _version_rows(factory, seeded.sid)
        assert after == before
        for v in after:
            captured = {m["id"]: m["content"] for m in json.loads(v["chat_history_json"])}
            assert captured[seeded.ids["U2"]] == _CONTENT["U2"]

    @pytest.mark.parametrize(
        ("head", "visible"),
        [
            ("U2", ["U1", "A1", "N1", "U3", "A3"]),
            ("U1", ["U2", "T2", "R2", "A2", "N2", "U3", "A3"]),
        ],
        ids=["a_later_turn", "the_first_turn"],
    )
    def test_a_save_point_taken_after_a_delete_captures_only_what_is_left(
        self, head, visible, _session_unit_engine
    ):
        """Exactly the visible rows; after a first-turn delete, no hidden row."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        by_id = {r.id: r for r in _messages_of(factory, seeded.sid)}

        with _patched(factory, _RecordingSaver()):
            _delete(seeded.sid, seeded.ids[head])
            created = SessionManager().create_version(
                seeded.sid, "after the delete", deck_dict={"title": "t", "slides": []}
            )

        [version] = _version_rows(factory, seeded.sid)
        assert json.loads(version["chat_history_json"]) == [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "message_type": row.message_type,
                "created_at": row.created_at.isoformat(),
            }
            for row in (by_id[seeded.ids[label]] for label in visible)
        ]
        assert created["message_count"] == len(visible)


class TestTheDeleteWaitsForAnArcReview:
    """As for a clear (#323): the arc-review sweeper runs a graph turn on the
    owner's thread without the session lock, so a delete waits for its claim.
    The race itself: ``tests/integration/test_delete_message_graph_turn.py``."""

    def test_a_live_review_claim_refuses_the_delete_and_changes_nothing(
        self, _session_unit_engine
    ):
        from tests.unit.test_clear_context import _give_the_session_a_deck_claimed_at

        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        _give_the_session_a_deck_claimed_at(
            factory, seeded.sid, datetime.utcnow() - timedelta(seconds=30)
        )
        before = _rows(factory, seeded.sid)

        saver = _RecordingSaver()
        with _patched(factory, saver):
            with pytest.raises(Exception) as raised:
                _delete(seeded.sid, seeded.ids["U2"])

        assert _rows(factory, seeded.sid) == before, "a refused delete changed rows"
        assert saver.deleted == [], "a refused delete deleted the thread"
        assert _events(factory, _MESSAGE_DELETED) == [], "a refused delete was attributed"

        from src.api.services.chat_service import ArcReviewInFlightError

        assert isinstance(raised.value, ArcReviewInFlightError), raised.value


# ---------------------------------------------------------------------------
# One transaction, attributed (D6, D8).
# ---------------------------------------------------------------------------


class TestTheDeleteIsOneAttributedTransaction:
    def test_a_delete_records_who_deleted_in_the_same_transaction(self, _session_unit_engine):
        """One ``message_deleted`` row naming the actor and the session, and no
        other usage event (no ``context_cleared``).

        Two sessions, and the SECOND is deleted from, so the row's
        ``session_id`` must be that session's own integer id.  The actor is not
        the session's ``created_by``, so the row records the caller it was
        given, not the session's creator.  The "same transaction" half -- no
        row when the delete does not commit -- is
        ``test_an_unimplemented_saver_rolls_the_whole_delete_back`` and the
        file-backed ``test_a_failed_commit_rolls_back_rows_marker_event_and_thread``.
        """
        from src.database.models.usage_event import EVENT_MESSAGE_DELETED

        factory = _make_factory(_session_unit_engine)
        bystander = _seed_turns(factory)
        seeded = _seed_turns(factory)
        assert seeded.pk != bystander.pk, "fixture precondition"

        with _patched(factory, _RecordingSaver()):
            _delete(seeded.sid, seeded.ids["U2"], deleted_by="editor@example.com")

        assert _all_events(factory) == [(_MESSAGE_DELETED, "editor@example.com", seeded.pk)]
        assert _events(factory, _CONTEXT_CLEARED) == []
        assert EVENT_MESSAGE_DELETED == _MESSAGE_DELETED

    def test_the_log_line_names_who_deleted_and_is_written_only_once_committed(
        self, _session_unit_engine, caplog
    ):
        """The log line is the other half of the record (D8, D18).  It carries
        the actor and the message, and a delete that did not commit -- a saver
        that raises, or a lost commit -- logs no "deleted" line."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        def deleted_lines() -> list[logging.LogRecord]:
            return [r for r in caplog.records if r.getMessage() == "Deleted a conversation turn"]

        with caplog.at_level(logging.INFO, logger="src.api.services.chat_service"):
            with _patched(factory, _RecordingSaver(raises=NotImplementedError())), \
                    pytest.raises(NotImplementedError):
                _delete(seeded.sid, seeded.ids["U2"], deleted_by="editor@example.com")
            with _patched_with_failing_commit(factory, _RecordingSaver()), pytest.raises(
                RuntimeError, match="commit failed"
            ):
                _delete(seeded.sid, seeded.ids["U2"], deleted_by="editor@example.com")
            assert deleted_lines() == [], "a delete that did not commit logged as deleted"

            with _patched(factory, _RecordingSaver()):
                _delete(seeded.sid, seeded.ids["U2"], deleted_by="editor@example.com")

        [line] = deleted_lines()
        assert (
            line.session_id, line.message_id, line.deleted_by,
            line.deleted_messages, line.hidden_message_id,
        ) == (seeded.sid, seeded.ids["U2"], "editor@example.com", 5, None)

    @pytest.mark.parametrize("actor", [None, ""])
    def test_a_delete_without_an_actor_is_refused_before_anything_changes(
        self, actor, _session_unit_engine
    ):
        """An unattributable delete must not happen at all: the first turn's
        head is not re-typed and nothing is deleted."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        saver = _RecordingSaver()
        with _patched(factory, saver), pytest.raises(ValueError):
            _delete(seeded.sid, seeded.ids["U1"], deleted_by=actor)

        assert _rows(factory, seeded.sid) == before
        assert saver.deleted == []
        assert _all_events(factory) == []

    def test_the_graph_thread_is_deleted_on_the_deletes_own_session(
        self, _session_unit_engine
    ):
        """Keyed by the session id ``invoke_graph`` runs the thread under, and
        on the delete's OWN session, so it commits or rolls back with it."""
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)

        saver = _SessionSnoopingSaver()
        with _patched(factory, saver):
            _delete(seeded.sid, seeded.ids["U2"])

        assert saver.deleted == [seeded.sid]
        [given] = saver.sessions
        assert given is not None, "delete_thread was not handed the delete's session"
        assert isinstance(given, Session)
        assert given.get_bind() is _session_unit_engine
        assert saver.loaded == [{seeded.sid}], (
            "delete_thread was handed a session other than the one the delete ran on"
        )

    def test_an_unimplemented_saver_rolls_the_whole_delete_back(self, _session_unit_engine):
        """``BaseCheckpointSaver.delete_thread`` is ``raise NotImplementedError``.

        It surfaces (the route turns it into a 500), and nothing of the
        first-turn delete is left: U1 keeps its type, A1 and N1 are there, and
        there is no attribution row.
        """
        factory = _make_factory(_session_unit_engine)
        seeded = _seed_turns(factory)
        before = _rows(factory, seeded.sid)

        saver = _RecordingSaver(raises=NotImplementedError())
        with _patched(factory, saver), pytest.raises(NotImplementedError):
            _delete(seeded.sid, seeded.ids["U1"])

        assert saver.deleted == [seeded.sid], "precondition: the delete reached the saver"
        assert _rows(factory, seeded.sid) == before
        assert _all_events(factory) == []

    def test_with_the_real_saver_on_a_file_backed_database_the_delete_is_one_transaction(
        self, file_backed_db  # noqa: F811 (the imported fixture)
    ):
        """A thread delete on a second connection would wait on the write lock
        the bulk DELETE holds, and fail with ``database is locked``."""
        factory = _make_factory(file_backed_db)
        saver = SqlAlchemyCheckpointSaver(session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)
        _assert_thread_rows(file_backed_db, seeded.sid, 1)
        [second_ask] = [
            r for r in _messages_of(factory, seeded.sid) if r.content == "make slide 3 shorter"
        ]

        with _patched(factory, saver):
            result = _delete(seeded.sid, second_ask.id)

        assert (result["deleted_messages"], result["hidden_message_id"]) == (2, None)
        assert [r.content for r in _messages_of(factory, seeded.sid)] == [
            _PLAIN_MESSAGE, "deck built"
        ]
        _assert_thread_rows(file_backed_db, seeded.sid, 0)
        _assert_thread_rows(file_backed_db, seeded.other_thread, 1)
        assert _events(factory, _MESSAGE_DELETED) == [("owner@example.com", seeded.pk)]

    def test_a_failed_commit_rolls_back_rows_marker_event_and_thread(
        self, file_backed_db  # noqa: F811 (the imported fixture)
    ):
        """A lost commit of a first-turn delete leaves everything as it was:
        the rows, U1's type, the thread and the attribution.  A retry is an
        ordinary delete."""
        factory = _make_factory(file_backed_db)
        saver = SqlAlchemyCheckpointSaver(session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)
        before = _rows(factory, seeded.sid)
        head = before[0][0]
        assert len(before) == 4, "precondition"

        with _patched_with_failing_commit(factory, saver), pytest.raises(
            RuntimeError, match="commit failed"
        ):
            _delete(seeded.sid, head)

        assert _rows(factory, seeded.sid) == before
        _assert_thread_rows(file_backed_db, seeded.sid, 1)
        _assert_thread_rows(file_backed_db, seeded.other_thread, 1)
        assert _events(factory, _MESSAGE_DELETED) == []

        with _patched(factory, saver):
            result = _delete(seeded.sid, head)

        assert (result["hidden_message_id"], result["deleted_messages"]) == (head, 1)
        assert _rows(factory, seeded.sid) == [_retyped(before[0], _marker_type()), *before[2:]]
        _assert_thread_rows(file_backed_db, seeded.sid, 0)
        _assert_thread_rows(file_backed_db, seeded.other_thread, 1)
        assert _events(factory, _MESSAGE_DELETED) == [("owner@example.com", seeded.pk)]


# ===========================================================================
# The ROUTE half: DELETE /api/sessions/{session_id}/messages/{message_id}
# (#317 Task 3).  Route tests go below this line; the service tests above are
# Task 2's.
# ===========================================================================
#
# The checks run in exactly #323's order (plan D7): the deck gate (CAN_EDIT,
# not the helper's CAN_VIEW default), the creator gate (a contributor deletes
# only in their own session), the session lock (409 while a turn or slide
# operation holds it, and a 409 never releases a lock it did not take), the
# delete, then the release in ``finally``.  #323's stubs all append to ONE
# ``events`` list, so the order is asserted, not inferred from call counts.
#
# #323's route fixtures are re-bound below by NAME (pytest finds a fixture by
# the name it was defined with).  A plain binding, unlike an import, does not
# trip F811 on every test that requests one.  The real-row class at the
# end drives the REAL ``ChatService`` through the route on a file-backed engine:
# the route runs the service in a worker thread, and the house in-memory
# engine gives every thread its own empty database.
#
# Red before Task 3, test by test: the route table holds no such path, and
# FastAPI answers every ``DELETE /api/sessions/{id}/messages/{id}`` itself with
# ``404 {"detail": "Not Found"}``.  A test expecting another status fails on
# it; a test expecting a 404 fails on what the route would have done (the
# service call, the lock it takes and gives back, the session 404's detail).
# ``MESSAGE_NOT_FOUND_DETAIL`` is imported inside a test body, AFTER its
# behavioural assertions (``ImportError`` only once those pass), so the file
# still collects.

from src.database.models.profile_contributor import PermissionLevel  # noqa: E402
from tests.unit import test_clear_context as _clear_route  # noqa: E402

client = _clear_route.client
events = _clear_route.events
deck_gate = _clear_route.deck_gate
allowing_gate = _clear_route.allowing_gate
allowing_creator = _clear_route.allowing_creator
refusing_creator = _clear_route.refusing_creator
session_lock = _clear_route.session_lock
as_editor = _clear_route.as_editor

_ROUTE_PATH = "/api/sessions/{session_id}/messages/{message_id}"
_ROUTES_LOGGER = "src.api.routes.sessions"

# What the stub service answers: the real service's shape (Task 2), fixed, so
# a route that rebuilt or altered the result shows up.
_STUB_RESULT = {
    "status": "deleted",
    "session_id": "s1",
    "message_id": 42,
    "deleted_messages": 5,
    "hidden_message_id": None,
}


def _message_not_found_detail() -> str:
    """``MESSAGE_NOT_FOUND_DETAIL``, imported only when a test needs it (new in Task 3)."""
    from src.api.routes.sessions import MESSAGE_NOT_FOUND_DETAIL

    return MESSAGE_NOT_FOUND_DETAIL


def _the_whole_delete(session_id: str) -> list[tuple[str, str]]:
    """The order a delete that gets as far as the service runs its steps in."""
    return [
        ("deck_gate", session_id),
        ("creator", session_id),
        ("acquire", session_id),
        ("service", session_id),
        ("release", session_id),
    ]


@pytest.fixture
def delete_stub_service(monkeypatch, events):
    """Replaces ChatService for the route: records (session_id, message_id, deleted_by).

    Set ``.raises`` to an exception to make ``delete_message`` raise it (after
    recording the call: a ``TypeError`` from a signature mismatch would be a
    500 too, and would record nothing).
    """
    stub = SimpleNamespace(calls=[], raises=None)

    class _Stub:
        def delete_message(self, session_id, message_id, *, deleted_by):
            stub.calls.append((session_id, message_id, deleted_by))
            events.append(("service", session_id))
            if stub.raises is not None:
                raise stub.raises
            return dict(_STUB_RESULT)

    monkeypatch.setattr("src.api.routes.sessions.get_chat_service", lambda: _Stub())
    return stub


def _break_the_release(monkeypatch, events) -> None:
    """Make the ``session_lock`` stub's release raise, after recording the call."""
    from src.api.routes import sessions as sessions_route

    manager = sessions_route.get_session_manager()  # the session_lock stub

    def _broken_release(session_id):
        events.append(("release", session_id))
        raise RuntimeError("lock row unreachable")

    monkeypatch.setattr(manager, "release_session_lock", _broken_release)


class TestDeleteMessageRoute:
    def test_the_route_is_delete_on_the_message_path(self):
        from src.api.main import app

        matches = {
            (r.path, frozenset(r.methods))
            for r in app.routes
            if getattr(r, "path", "") == _ROUTE_PATH
        }
        assert matches == {(_ROUTE_PATH, frozenset({"DELETE"}))}

    def test_a_viewer_is_refused_and_nothing_is_deleted(
        self, client, deck_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        """The deck gate's DEFAULT is CAN_VIEW: taking it would let a viewer of
        a shared deck delete from a conversation.  The deck gate is FIRST, so a
        viewer reaches neither the creator gate nor the lock."""
        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 403, resp.text
        assert deck_gate == [("s1", PermissionLevel.CAN_EDIT)]
        assert delete_stub_service.calls == [], "the gate must run BEFORE any delete"
        assert allowing_creator == []
        assert session_lock.acquired == []
        assert session_lock.released == []
        assert events == [("deck_gate", "s1")]

    def test_the_happy_path_runs_gate_creator_lock_service_release_in_order(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 200, resp.text
        assert resp.json() == _STUB_RESULT
        assert allowing_gate == [("s1", PermissionLevel.CAN_EDIT)]
        # The caller is the actor (D8), and the id reaches the service as the
        # int the path parameter declares, not the URL's string.
        assert delete_stub_service.calls == [("s1", 42, "editor@example.com")]
        assert type(delete_stub_service.calls[0][1]) is int
        # Exactly this order: the lock is taken only once both gates have
        # passed, is held across the delete, and is given back once.
        assert events == _the_whole_delete("s1")

    def test_an_editor_who_is_not_the_sessions_creator_is_refused(
        self, client, allowing_gate, refusing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        """Deck permission resolves on the ROOT deck, so every editor of a
        shared deck passes the deck gate, for the owner's session id too.
        Conversations are private: the creator gate refuses before the lock is
        taken and before anything is deleted."""
        resp = client.delete("/api/sessions/owners-session/messages/42")

        assert resp.status_code == 403, resp.text
        assert refusing_creator == ["owners-session"]
        assert delete_stub_service.calls == [], "a refused delete must not reach the service"
        assert session_lock.acquired == [], "the creator gate runs BEFORE the lock"
        assert session_lock.released == []
        assert events == [("deck_gate", "owners-session"), ("creator", "owners-session")]

    def test_no_user_is_a_401_before_the_lock(
        self, client, allowing_gate, session_lock, delete_stub_service, monkeypatch, events,
    ):
        """The REAL creator gate (not stubbed here): with no signed-in user the
        route answers 401, before the lock and before anything is deleted.  An
        empty ``DEV_USER_ID`` is how the real middleware yields no user."""
        monkeypatch.setenv("DEV_USER_ID", "")

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 401, resp.text
        assert delete_stub_service.calls == []
        assert session_lock.acquired == []
        assert session_lock.released == []
        assert events == [("deck_gate", "s1")]

    def test_a_turn_in_flight_is_a_409_and_the_lock_is_not_released(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        """A chat turn or a slide operation holds the session lock.  The busy
        answer must NOT release it: the lock belongs to the request that took
        it, and freeing it would let a third request run alongside that turn."""
        session_lock.grant = False

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 409, resp.text
        assert delete_stub_service.calls == [], "a busy session must not be deleted from"
        assert session_lock.acquired == ["s1"]
        assert session_lock.released == [], (
            "a 409 must not release a lock this request did not acquire"
        )
        assert events == [("deck_gate", "s1"), ("creator", "s1"), ("acquire", "s1")]

        from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL

        assert resp.json()["detail"] == CONVERSATION_BUSY_DETAIL

    def test_a_message_not_in_this_conversation_is_a_404_and_the_lock_is_released(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        delete_stub_service.raises = _message_not_found_error()("message 42 not in s1")

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 404, resp.text
        assert delete_stub_service.calls == [("s1", 42, "editor@example.com")]
        # A failed delete still gives the lock back: once, after the service.
        assert session_lock.released == ["s1"]
        assert events == _the_whole_delete("s1")
        # The one text for every not-found case (D3), and not the service's
        # message, which names the id.
        assert resp.json()["detail"] == _message_not_found_detail()
        assert _message_not_found_detail() == "That message is not in this conversation."

    def test_a_missing_session_is_a_404_and_the_lock_is_released(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        delete_stub_service.raises = SessionNotFoundError("Session not found: ghost")

        resp = client.delete("/api/sessions/ghost/messages/42")

        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Session not found: ghost"
        assert delete_stub_service.calls == [("ghost", 42, "editor@example.com")]
        assert session_lock.released == ["ghost"]
        assert events == _the_whole_delete("ghost")

    def test_an_arc_review_in_flight_is_a_409_and_the_lock_is_released(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        """The service refuses while the deck's arc review runs: the same busy
        answer as a held lock, and this request took the lock, so it releases it."""
        from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL
        from src.api.services.chat_service import ArcReviewInFlightError

        delete_stub_service.raises = ArcReviewInFlightError("s1")

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == CONVERSATION_BUSY_DETAIL
        assert session_lock.released == ["s1"]
        assert events == _the_whole_delete("s1")

    def test_an_unexpected_failure_is_a_500_and_the_lock_is_released(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events,
    ):
        """The 500 carries a fixed text, never the exception's own message."""
        delete_stub_service.raises = RuntimeError("internal: saver dsn=secret")

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 500, resp.text
        assert "secret" not in resp.text
        assert delete_stub_service.calls == [("s1", 42, "editor@example.com")]
        assert session_lock.released == ["s1"]
        assert events == _the_whole_delete("s1")

    def test_a_lock_release_failure_after_a_committed_delete_is_still_a_200(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events, monkeypatch, caplog,
    ):
        """#323's whole-branch review W2, for the delete: the delete has
        committed by the time the ``finally`` releases the lock.  If the release
        raises, the caller must still be told the delete happened; the release
        failure is logged, not surfaced."""
        _break_the_release(monkeypatch, events)

        with caplog.at_level(logging.ERROR, logger=_ROUTES_LOGGER):
            resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 200, resp.text
        assert resp.json() == _STUB_RESULT
        assert delete_stub_service.calls == [("s1", 42, "editor@example.com")]
        assert events == _the_whole_delete("s1")
        # Logged, not swallowed: the lock now goes stale on its own, and the
        # log line is the only trace of why the session stays busy until then.
        logged = [
            (getattr(r, "session_id", None), str(r.exc_info[1]))
            for r in caplog.records
            if r.name == _ROUTES_LOGGER and r.levelno >= logging.ERROR and r.exc_info
        ]
        assert logged == [("s1", "lock row unreachable")]

    def test_a_lock_release_failure_does_not_mask_the_deletes_own_404(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, events, monkeypatch,
    ):
        """The other half of W2: a release failure must not replace the
        delete's own answer with a 500."""
        _break_the_release(monkeypatch, events)
        delete_stub_service.raises = _message_not_found_error()("message 42 not in s1")

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 404, resp.text
        assert events == _the_whole_delete("s1")
        assert resp.json()["detail"] == _message_not_found_detail()

    @pytest.mark.parametrize("message_id", ["abc", "4.5"])
    def test_a_non_integer_message_id_is_a_422_before_any_gate(
        self, message_id, client, allowing_gate, allowing_creator, session_lock,
        delete_stub_service, as_editor, events,
    ):
        """FastAPI validates the ``int`` path parameter before the handler
        runs: no gate, no lock, no delete."""
        resp = client.delete(f"/api/sessions/s1/messages/{message_id}")

        assert resp.status_code == 422, resp.text
        assert events == []
        assert delete_stub_service.calls == []

    @pytest.mark.parametrize("caller", ["editor@example.com", "contributor@example.com"])
    def test_the_route_passes_the_caller_as_deleted_by(
        self, caller, client, allowing_gate, allowing_creator, session_lock,
        delete_stub_service, monkeypatch,
    ):
        """The identity comes from the request (``DEV_USER_ID`` through the real
        middleware), not from anything the route invents: the creator gate
        judges the same caller the delete is attributed to (D8)."""
        monkeypatch.setenv("DEV_USER_ID", caller)

        resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 200, resp.text
        assert allowing_creator == [("s1", caller)]
        assert delete_stub_service.calls == [("s1", 42, caller)]

    def test_the_log_line_names_who_deleted_which_message(
        self, client, allowing_gate, allowing_creator, session_lock, delete_stub_service,
        as_editor, caplog,
    ):
        """The route's log line carries ``deleted_by`` and ``message_id`` (D8)."""
        with caplog.at_level(logging.INFO, logger=_ROUTES_LOGGER):
            resp = client.delete("/api/sessions/s1/messages/42")

        assert resp.status_code == 200, resp.text
        lines = [
            (r.session_id, r.message_id, r.deleted_by)
            for r in caplog.records
            if r.name == _ROUTES_LOGGER and hasattr(r, "deleted_by")
        ]
        assert lines == [("s1", 42, "editor@example.com")]


# ---------------------------------------------------------------------------
# The route on REAL rows: the real ChatService behind the route, on a
# file-backed engine.  The gates and the lock are #323's stubs; what is real is
# what a request does (and does not do) to the transcript, the attribution row
# and the graph thread.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_service(monkeypatch):
    """The route's ChatService is a real one (``_patched`` points it at the test DB)."""
    monkeypatch.setattr("src.api.routes.sessions.get_chat_service", lambda: ChatService())


class TestTheRouteOnRealRows:
    def test_a_delete_through_the_route_removes_the_turn_and_is_attributed_to_the_caller(
        self, client, allowing_gate, allowing_creator, session_lock, real_service,
        as_editor, events, file_backed_db,  # noqa: F811 (the imported fixture)
    ):
        factory = _make_factory(file_backed_db)
        seeded = _seed_turns(factory, created_by="editor@example.com")
        before = _rows(factory, seeded.sid)
        saver = _RecordingSaver()

        with _patched(factory, saver):
            resp = client.delete(f"/api/sessions/{seeded.sid}/messages/{seeded.ids['U2']}")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "status": "deleted",
            "session_id": seeded.sid,
            "message_id": seeded.ids["U2"],
            "deleted_messages": 5,
            "hidden_message_id": None,
        }
        kept = ["U1", "A1", "N1", "U3", "A3"]
        assert _rows(factory, seeded.sid) == _only(before, seeded, kept)
        assert saver.deleted == [seeded.sid]
        assert _events(factory, _MESSAGE_DELETED) == [("editor@example.com", seeded.pk)]
        assert session_lock.released == [seeded.sid]

    @pytest.mark.parametrize(
        "case",
        ["absent", "another_sessions_user_message", "an_assistant_message",
         "the_hidden_first_message"],
    )
    def test_every_not_found_case_is_the_same_404_and_changes_nothing(
        self, case, client, allowing_gate, allowing_creator, session_lock, real_service,
        as_editor, file_backed_db,  # noqa: F811 (the imported fixture)
    ):
        """One detail for every case (D3), so a 404 says nothing about ids in
        other sessions; and a 404 deletes, re-types, records and drops nothing,
        in this session or the other one."""
        factory = _make_factory(file_backed_db)
        mine = _seed_turns(factory, created_by="editor@example.com")
        theirs = _seed_turns(factory, created_by="other@example.com")
        if case == "the_hidden_first_message":
            with _patched(factory, _RecordingSaver()):
                _delete(mine.sid, mine.ids["U1"], deleted_by="editor@example.com")
            assert _rows(factory, mine.sid)[0][4] == _marker_type(), "precondition"
        message_id = {
            "absent": max(theirs.ids.values()) + 1000,
            "another_sessions_user_message": theirs.ids["U2"],
            "an_assistant_message": mine.ids["A2"],
            "the_hidden_first_message": mine.ids["U1"],
        }[case]
        mine_before = _rows(factory, mine.sid)
        theirs_before = _rows(factory, theirs.sid)
        events_before = _all_events(factory)
        saver = _RecordingSaver()

        with _patched(factory, saver):
            resp = client.delete(f"/api/sessions/{mine.sid}/messages/{message_id}")

        assert resp.status_code == 404, resp.text
        # The route's own 404 (it took and gave back the lock), not FastAPI's.
        assert session_lock.released == [mine.sid]
        assert _rows(factory, mine.sid) == mine_before
        assert _rows(factory, theirs.sid) == theirs_before
        assert _all_events(factory) == events_before
        assert saver.deleted == []
        assert resp.json()["detail"] == _message_not_found_detail()

    @pytest.mark.parametrize(
        "refusal, status",
        [("viewer", 403), ("not_the_creator", 403), ("turn_in_flight", 409)],
    )
    def test_a_refused_request_deletes_nothing(
        self, refusal, status, request, client, session_lock, real_service, as_editor,
        file_backed_db,  # noqa: F811 (the imported fixture)
    ):
        """A refusal is not a partial delete: the transcript, the attribution
        rows and the graph thread are as they were."""
        if refusal == "viewer":
            request.getfixturevalue("deck_gate")
            request.getfixturevalue("allowing_creator")
        elif refusal == "not_the_creator":
            request.getfixturevalue("allowing_gate")
            request.getfixturevalue("refusing_creator")
        else:
            request.getfixturevalue("allowing_gate")
            request.getfixturevalue("allowing_creator")
            session_lock.grant = False
        factory = _make_factory(file_backed_db)
        seeded = _seed_turns(factory, created_by="editor@example.com")
        before = _rows(factory, seeded.sid)
        saver = _RecordingSaver()

        with _patched(factory, saver):
            resp = client.delete(f"/api/sessions/{seeded.sid}/messages/{seeded.ids['U2']}")

        assert resp.status_code == status, resp.text
        assert _rows(factory, seeded.sid) == before
        assert _all_events(factory) == []
        assert saver.deleted == []
        assert session_lock.released == []
