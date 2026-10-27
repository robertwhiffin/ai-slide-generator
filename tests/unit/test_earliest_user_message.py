"""`earliest_user_message` (#317 Task 1, plan D16): ONE copy of the earliest-user-row rule.

The session's earliest ``role='user'`` row is the row ``clear_context`` (and
#317's message delete) keeps.  Before #317 three callers each wrote the query
out; this file pins the single helper that replaces them and proves that every
converted caller goes through it.  (``resolve_engine_mode`` and
``duplicate_session`` were the other two; since Deck Mode the first reads the
owner's ``deck_mode`` column and the second copies it, carrying no row, so
their entries are gone from tests 5 and 6.)

Real sqlite throughout, with EXPLICIT ``created_at`` on every row (a fixed
past instant, never the clock), so a tie is a real tie.  Tied rows are given
explicit ids and the HIGHER id is inserted first, so "the lower id wins" is not
insertion order in disguise.

SQLite and ties: for rows that tie on ``created_at``, a plain SQLite ORDER BY
returns them in rowid (= ``id``) order whether or not ``id`` is in the ORDER
BY, so tests 1 and 6 catch ``id DESC`` but cannot see a DROPPED ``id``
tie-break.  ``test_a_tie_is_broken_by_id_not_by_the_order_sqlite_scans_in``
adds a test-only ``(session_id, created_at, id DESC)`` index so SQLite walks
a tie highest id first, and an order on ``created_at`` alone goes red there.

Red before Task 1 for a stated reason, one test at a time:
  * tests 1-4 import the helper INSIDE the test (``ImportError: cannot import
    name 'earliest_user_message'``) so the file still collects and test 6
    runs;
  * test 5 reads ``session_manager.earliest_user_message`` to wrap it, then
    patches both module names with ``monkeypatch.setattr`` (``raising=True``):
    ``AttributeError`` while the module has no such attribute;
  * test 6 is a characterization test of the callers' observable
    results: green before and after.

Patch targets: ``clear_context`` imports
``get_db_session`` / ``get_checkpointer`` lazily, so the reachable targets are
the source attributes; ``_patched`` from ``test_clear_context`` patches those
and ``session_manager.get_db_session``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import pytest
from sqlalchemy import text

import src.api.services.session_manager as session_manager_module
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.database.models.session import SessionMessage, UserSession
from src.domain.conversation_engine import ENGINE_MODE_MARKER_MESSAGE_TYPE
from tests.unit.conftest import _make_factory, _make_fake_db
from tests.unit.test_clear_context import (
    _messages_of,
    _patched,
    _RecordingSaver,
    _session_pk,
)

# Two distinguishable first asks: which row a caller kept is read off its content.
_OTHER_MESSAGE = "Build me a deck about gannets"
_PLAIN_MESSAGE = "Build me a deck about puffins"

# A fixed instant long before any fixture's ``datetime.utcnow()`` row, so the
# rows a test seeds are the earliest in their session by construction.
_T0 = datetime(2020, 1, 1, 9, 0, 0)


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _the_helper() -> Callable[..., Optional[SessionMessage]]:
    """The function under test, looked up when a test runs.

    Absent before Task 1; importing it at module scope would stop the whole
    file collecting, test 6 included.
    """
    from src.api.services.session_manager import earliest_user_message

    return earliest_user_message


def _new_session(factory, *, created_by: str = "owner@example.com") -> tuple[str, int]:
    """A bare UserSession; returns (session_id, integer pk)."""
    sid = f"earliest-{uuid.uuid4().hex[:12]}"
    with _make_fake_db(factory)() as db:
        us = UserSession(session_id=sid, created_by=created_by)
        db.add(us)
        db.flush()
        pk = us.id
    return sid, pk


def _add_rows(factory, session_pk: int, *rows: dict[str, Any]) -> list[int]:
    """Insert *rows* into *session_pk*'s transcript in the order given.

    Each row is ``dict(role=..., content=..., created_at=..., message_type=...,
    id=...)``; ``id`` and ``message_type`` are optional.  Flushed one at a time
    so the order given is the insert order.  Returns the ids, in that order.
    """
    ids: list[int] = []
    with _make_fake_db(factory)() as db:
        for row in rows:
            msg = SessionMessage(session_id=session_pk, **row)
            db.add(msg)
            db.flush()
            ids.append(msg.id)
    return ids


def _row(role: str, content: str, at: datetime, *, message_type: Optional[str] = None,
         id: Optional[int] = None) -> dict[str, Any]:
    row: dict[str, Any] = dict(role=role, content=content, created_at=at,
                               message_type=message_type)
    if id is not None:
        row["id"] = id
    return row


def _earliest(factory, session_pk: int) -> Optional[tuple]:
    """Ask the helper, on a session of its own; (id, role, content, message_type) or None."""
    helper = _the_helper()
    with _make_fake_db(factory)() as db:
        row = helper(db, session_pk)
        if row is None:
            return None
        assert isinstance(row, SessionMessage), f"expected a SessionMessage row, got {row!r}"
        return (row.id, row.role, row.content, row.message_type)


def _next_free_id(factory) -> int:
    """An id clear of every row already in this engine (for explicit-id seeding)."""
    from sqlalchemy import func

    with _make_fake_db(factory)() as db:
        return (db.query(func.max(SessionMessage.id)).scalar() or 0) + 100


# ---------------------------------------------------------------------------
# 1-4: the helper itself
# ---------------------------------------------------------------------------


def test_the_earliest_user_row_is_ordered_by_created_at_then_id(_session_unit_engine):
    """``created_at`` first, then ``id``: a tie goes to the lower id, and an
    earlier ``created_at`` beats any id."""
    factory = _make_factory(_session_unit_engine)
    _, pk = _new_session(factory)
    base = _next_free_id(factory)
    low_id_but_late, tied_lower, tied_higher, earliest_but_highest = (
        base, base + 10, base + 11, base + 20,
    )

    # Higher id inserted first: the winner is not simply the first row written.
    _add_rows(
        factory, pk,
        _row("user", "tied, higher id", _at(10), message_type="user_input", id=tied_higher),
        _row("user", "tied, lower id", _at(10), message_type="user_input", id=tied_lower),
        # The lowest id of all, but a second later: created_at outranks id.
        _row("user", "lowest id, a second later", _at(11), message_type="user_input",
             id=low_id_but_late),
    )

    assert _earliest(factory, pk) == (tied_lower, "user", "tied, lower id", "user_input")

    # One second earlier than the tie, with the highest id in the session.
    _add_rows(
        factory, pk,
        _row("user", "a second earlier", _at(9), message_type="user_query",
             id=earliest_but_highest),
    )

    assert _earliest(factory, pk) == (
        earliest_but_highest, "user", "a second earlier", "user_query"
    )


def test_a_tie_is_broken_by_id_not_by_the_order_sqlite_scans_in(_session_unit_engine):
    """The ``id`` tie-break is in the query, not borrowed from the scan order.

    Plain SQLite hands ``created_at`` ties back in rowid (= ``id``) order, so
    test 1 cannot tell ``ORDER BY created_at, id`` from ``ORDER BY created_at``.
    A test-only index on ``(session_id, created_at, id DESC)`` lets SQLite
    satisfy ``ORDER BY created_at`` from the index, walking a tie highest id
    first -- so an order on ``created_at`` alone returns the HIGHER id here.
    """
    with _session_unit_engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX ix_test_ties_walk_ids_backwards "
            "ON session_messages (session_id, created_at, id DESC)"
        ))
    factory = _make_factory(_session_unit_engine)
    _, pk = _new_session(factory)
    lower = _next_free_id(factory)
    _add_rows(
        factory, pk,
        _row("user", "tied, lower id", _at(0), message_type="user_input", id=lower),
        _row("user", "tied, higher id", _at(0), message_type="user_input", id=lower + 1),
    )
    with _make_fake_db(factory)() as db:
        scan_first = (
            db.query(SessionMessage)
            .filter(SessionMessage.session_id == pk, SessionMessage.role == "user")
            .order_by(SessionMessage.created_at.asc())
            .first()
        )
        assert scan_first.id == lower + 1, (
            "precondition: with the index, ORDER BY created_at alone walks the tie "
            "highest id first (else this test cannot see a dropped tie-break)"
        )

    assert _earliest(factory, pk) == (lower, "user", "tied, lower id", "user_input")


@pytest.mark.parametrize("first_user_type", ["user_input", "user_query", "chat", None])
def test_assistant_and_tool_rows_are_never_the_earliest_user_row(
    _session_unit_engine, first_user_type
):
    """``role`` only, never ``message_type``: replies that predate every user
    row are skipped, and the earliest user row is found whatever type its path
    wrote (SSE ``user_input``, async/MCP ``user_query``, tour ``chat``, and
    ``POST /messages``' ``None``)."""
    factory = _make_factory(_session_unit_engine)
    _, pk = _new_session(factory)
    ids = _add_rows(
        factory, pk,
        _row("assistant", "an assistant row before any user row", _at(0),
             message_type="llm_response"),
        _row("tool", "a tool row before any user row", _at(1), message_type="tool_result"),
        _row("assistant", "a notice before any user row", _at(2), message_type="info"),
        _row("user", "the first user row", _at(3), message_type=first_user_type),
        _row("assistant", "its reply", _at(4), message_type="llm_response"),
        _row("user", "a later user row", _at(5), message_type="user_input"),
    )

    assert _earliest(factory, pk) == (ids[3], "user", "the first user row", first_user_type)


def test_a_hidden_marker_is_still_the_earliest_user_row(_session_unit_engine):
    """The row a clear (or a delete) keeps is re-typed ``engine_mode_marker``
    and hidden from every transcript read -- and is still THE earliest user row,
    so the next clear (or delete) keeps seeing it."""
    factory = _make_factory(_session_unit_engine)
    sid, pk = _new_session(factory)
    marker_id, _, later_id = _add_rows(
        factory, pk,
        _row("user", _OTHER_MESSAGE, _at(0), message_type=ENGINE_MODE_MARKER_MESSAGE_TYPE),
        _row("assistant", "a reply", _at(5), message_type="llm_response"),
        _row("user", "make slide 2 blue", _at(10), message_type="user_input"),
    )
    with _patched(factory, _RecordingSaver()):
        visible = [m["id"] for m in SessionManager().get_messages(sid)]
    assert marker_id not in visible and later_id in visible, (
        "precondition: the marker is hidden from the transcript"
    )

    assert _earliest(factory, pk) == (
        marker_id, "user", _OTHER_MESSAGE, ENGINE_MODE_MARKER_MESSAGE_TYPE
    )


def test_no_user_row_is_none(_session_unit_engine):
    """No user row is ``None`` -- never another session's row, even one that
    is earlier than anything in this session."""
    factory = _make_factory(_session_unit_engine)
    _, empty_pk = _new_session(factory)
    _, replies_only_pk = _new_session(factory)
    _, other_pk = _new_session(factory, created_by="someone-else@example.com")
    _, mine_pk = _new_session(factory)

    # The other session's user row is the earliest user row in the database.
    [other_id] = _add_rows(
        factory, other_pk,
        _row("user", "another session's first ask", _at(0), message_type="user_input"),
    )
    _add_rows(
        factory, replies_only_pk,
        _row("assistant", "a reply with no ask", _at(1), message_type="llm_response"),
        _row("tool", "a tool result with no ask", _at(2), message_type="tool_result"),
    )
    [mine_id] = _add_rows(
        factory, mine_pk,
        _row("user", "my first ask", _at(30), message_type="user_input"),
    )

    assert _earliest(factory, empty_pk) is None
    assert _earliest(factory, replies_only_pk) is None
    assert _earliest(factory, 10_000_000) is None, "a pk with no session"
    assert _earliest(factory, mine_pk) == (mine_id, "user", "my first ask", "user_input")
    assert _earliest(factory, other_pk) == (
        other_id, "user", "another session's first ask", "user_input"
    )


# ---------------------------------------------------------------------------
# 5: every converted caller reads the row through the helper
# ---------------------------------------------------------------------------


class _HelperSpy:
    """Stands in for ``earliest_user_message`` at both module names.

    Records the ``session_pk`` of every call.  Answers with the real helper,
    unless ``steer`` is set, in which case it answers ``steer(db, session_pk)``
    -- a row the database's own query would NOT return.  A caller whose result
    follows the steered row demonstrably acts on the helper's answer, not on a
    query of its own that it runs as well.
    """

    def __init__(self, real: Callable[..., Optional[SessionMessage]]):
        self._real = real
        self.pks: list[int] = []
        self.steer: Optional[Callable[[Any, int], Optional[SessionMessage]]] = None

    def __call__(self, db, session_pk):
        self.pks.append(session_pk)
        if self.steer is not None:
            return self.steer(db, session_pk)
        return self._real(db, session_pk)


def _install_spy(monkeypatch) -> _HelperSpy:
    """Patch the spy over BOTH names, failing loudly where a name is missing.

    ``chat_service`` imports the helper by name (``clear_context``);
    ``session_manager`` defines it, so a caller there would read that module
    global.  ``monkeypatch.setattr`` defaults to ``raising=True``.
    """
    spy = _HelperSpy(session_manager_module.earliest_user_message)
    monkeypatch.setattr("src.api.services.session_manager.earliest_user_message", spy)
    monkeypatch.setattr("src.api.services.chat_service.earliest_user_message", spy)
    return spy


def _clear_context_reads_the_sessions_own_row(
    spy, *, contributor_session, session_with_spec_and_messages, _session_unit_engine, **_
):
    """``clear_context`` asks for the cleared session's own pk -- a
    contributor's, never its deck owner's -- and keeps the row the helper
    answers with."""
    # (a) A contributor session: its own pk, not the deck owner's (a
    # contributor's clear never touches the owner's transcript).
    c_factory = contributor_session._factory
    owner_pk = _session_pk(c_factory, contributor_session._owner_session_id)
    contrib_sid = contributor_session.contributor_session_id
    contrib_pk = _session_pk(c_factory, contrib_sid)
    _add_rows(c_factory, owner_pk,
              _row("user", _OTHER_MESSAGE, _at(0), message_type="user_input"))
    _add_rows(c_factory, contrib_pk,
              _row("user", _PLAIN_MESSAGE, _at(10), message_type="user_query"))

    with _patched(c_factory, _RecordingSaver()):
        ChatService().clear_context(contrib_sid, cleared_by="contributor@example.com")
    assert spy.pks == [contrib_pk], (
        f"clear_context on a contributor session must ask the helper once, for "
        f"its own pk {contrib_pk} (the owner's is {owner_pk}); it asked for {spy.pks}"
    )

    # (b) A root session, steered: the clear keeps the helper's answer.
    spy.pks.clear()
    factory = _make_factory(_session_unit_engine)
    sid = session_with_spec_and_messages
    pk = _session_pk(factory, sid)
    [first_user_id] = [r.id for r in _messages_of(factory, sid)]
    _, second_user_id, _ = _add_rows(
        factory, pk,
        _row("assistant", "deck built", datetime.utcnow() + timedelta(seconds=5),
             message_type="llm_response"),
        _row("user", "make slide 3 shorter", datetime.utcnow() + timedelta(seconds=10),
             message_type="user_input"),
        _row("assistant", "done", datetime.utcnow() + timedelta(seconds=15),
             message_type="llm_response"),
    )
    # Steer to the SECOND user row: the database's own earliest-row query
    # would keep the first.
    spy.steer = lambda db, session_pk: db.get(SessionMessage, second_user_id)

    with _patched(factory, _RecordingSaver()):
        result = ChatService().clear_context(sid, cleared_by="owner@example.com")

    assert spy.pks == [pk], (
        f"clear_context must ask the helper once, for the session's pk {pk}; "
        f"it asked for {spy.pks}"
    )
    assert result["preserved_message_id"] == second_user_id, (
        "clear_context must keep the row the helper answered with"
    )
    # The database's own first user row went with the rest.
    [kept] = _messages_of(factory, sid)
    assert kept.id != first_user_id
    assert (kept.id, kept.message_type) == (second_user_id, ENGINE_MODE_MARKER_MESSAGE_TYPE)


_CALLERS = {
    "clear_context": _clear_context_reads_the_sessions_own_row,
}


@pytest.mark.parametrize("caller", list(_CALLERS))
def test_every_caller_reads_the_row_through_the_helper(
    caller,
    monkeypatch,
    contributor_session,
    session_with_spec_and_messages,
    _session_unit_engine,
):
    """Each converted caller calls ``earliest_user_message`` with the right
    pk -- the session's own for a clear -- and acts on its answer (the spy
    steers it to a row the caller's old inline query would not pick)."""
    spy = _install_spy(monkeypatch)
    _CALLERS[caller](
        spy,
        contributor_session=contributor_session,
        session_with_spec_and_messages=session_with_spec_and_messages,
        _session_unit_engine=_session_unit_engine,
    )


# ---------------------------------------------------------------------------
# 6: a created_at tie, through each caller's observable result
# ---------------------------------------------------------------------------


def _seed_tie(factory, pk: int, *, other_on: str) -> tuple[int, int]:
    """Two user rows sharing one ``created_at``; ``_OTHER_MESSAGE`` on the
    "lower" or "higher" id.  The higher id is inserted first.  Returns (lower, higher)."""
    lower = _next_free_id(factory)
    higher = lower + 1
    lower_content = _OTHER_MESSAGE if other_on == "lower" else _PLAIN_MESSAGE
    higher_content = _OTHER_MESSAGE if other_on == "higher" else _PLAIN_MESSAGE
    _add_rows(
        factory, pk,
        _row("user", higher_content, _at(0), message_type="user_input", id=higher),
        _row("user", lower_content, _at(0), message_type="user_input", id=lower),
    )
    return lower, higher


def _clear_context_keeps_the_lower_id(*, factory, **_):
    sid, pk = _new_session(factory)
    lower, higher = _seed_tie(factory, pk, other_on="lower")
    _add_rows(factory, pk, _row("assistant", "deck built", _at(5), message_type="llm_response"))

    with _patched(factory, _RecordingSaver()):
        result = ChatService().clear_context(sid, cleared_by="owner@example.com")

    assert result["preserved_message_id"] == lower
    assert result["deleted_messages"] == 2
    [kept] = _messages_of(factory, sid)
    assert (kept.id, kept.content, kept.message_type) == (
        lower, _OTHER_MESSAGE, ENGINE_MODE_MARKER_MESSAGE_TYPE
    )


_TIE_CALLERS = {
    "clear_context": _clear_context_keeps_the_lower_id,
}


@pytest.mark.parametrize("caller", list(_TIE_CALLERS))
def test_a_created_at_tie_is_broken_by_id_for_every_caller(
    caller, session_with_spec_and_messages, _session_unit_engine
):
    """CHARACTERIZATION TEST: green before Task 1 and after it.

    Two user rows share one ``created_at``; the lower id wins.  Pinned through
    each caller's OBSERVABLE result (the row a clear keeps), not through the
    helper, so it holds the
    behaviour steady across the refactor; sabotaging the helper's order
    (``id DESC``) after Task 1 turns every case red.
    """
    _TIE_CALLERS[caller](
        factory=_make_factory(_session_unit_engine),
        session_with_spec_and_messages=session_with_spec_and_messages,
    )
