"""Task 5: the stop route, the snapshot at submit, and ``rollback`` on the poll.

Driven through ``TestClient(app)``: the real auth middleware (``DEV_USER_ID``), the
real owner gates, the real ``submit_chat_async`` / ``poll_chat`` and the new
``POST /api/chat/cancel/{request_id}``, a real ``SessionManager`` and the real
snapshot / rollback (``src.services.generation_rollback``), over a file-backed
SQLite database.

The contract under test (plan Task 5, with PLAN-CORRECTIONS C9):

* **Submit** decides the engine read-only before writing anything.  An Agent
  deck's Enter, in one transaction under the owner deck row's lock, refuses
  while a failed restore is pending or an arc review holds a live claim, and
  otherwise takes the generation snapshot -- BEFORE the user message, which
  locks the deck mode on a first message.  A Legacy deck never touches the
  snapshot machinery.  Any failure after the snapshot rolls the turn back
  before the existing error mapping, except ``DeckModeLockedError`` (C9: the
  snapshot is discarded, because another message locked the mode).  The engine
  is re-checked after the user message: graph-then-monolith discards the
  snapshot; monolith-then-graph fails closed with the engine-race 409.
* **Stop:** owner-only (404 unknown, 403 another user); a live request with no
  snapshot is 409 ``not_stoppable``; otherwise ``roll_back_generation`` maps to
  ``cancelled`` / ``already_finished`` (with the request's current status) /
  409 ``refused_foreign_change`` / 500.  ``already_finished`` carries the
  request's current status; on ``cancelled`` the status may be ``"cancelled"``
  or null (the brief leaves it open).
* **Poll** reports ``rollback`` (the request's ``rollback_outcome``) and the
  ``cancelled`` status.

Stubbed, and why
----------------
* ``get_session_local`` (every ``get_db_session`` and ``get_db``) and the
  checkpointer point at this test's database (``build_env`` from the Task 4 suite).
* ``enqueue_job`` records the job instead of queueing it: no runner runs here.
  Where a test needs the job, it calls the real ``process_chat_request`` itself,
  with only ``invoke_graph`` replaced (its body runs the real turn writers).
* The request log and usage-event writers (background writes from middleware)
  are no-ops, so "nothing changed" can compare every table.
* Turn writes between Enter and the stop are the Task 4 suite's real-writer
  helpers, run under the turn's request id once the request is ``running``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterator, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.main import app
from src.api.routes.chat import ENGINE_MODE_UNAVAILABLE_DETAIL
from src.api.services import job_queue
from src.api.services.session_manager import SessionManager, get_session_manager
from src.core.database import Base, _run_migrations, get_db_session
from src.database.models.session import UserSession
from src.services import generation_rollback
from src.services.generation_fence import start_chat_request
from src.services.generation_rollback import RollbackResult
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from src.services.persisted_graph_release import PersistedConfigurationUnavailableError
from src.services.spec_sync import DEBOUNCE_SECONDS, claim_due_marker, mark_dirty
from tests.unit.test_generation_rollback import (
    OWNER,
    RESTORE_PENDING,
    SLIDES_BUILT,
    STRANGER,
    RollbackEnv,
    _assert_lock,
    _assert_rolled_back_to_enter,
    _assert_sessions_equal,
    _assert_tables_equal,
    _messages_tagged,
    _one,
    _slide_inserts_fail,
    _without,
    build_env,
    edit_turn,
    first_generation_turn,
    foreign_edit,
    in_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)

#: Global Constraints copy, exact.
REFUSED_STOP = "Someone else has edited this deck since you sent this, so it can't be rolled back."
ARC_REVIEW_BUSY = "This deck is being updated in the background. Try again in a few seconds."
NOT_STOPPABLE = "This generation can't be stopped."
ENGINE_RACE = "This deck changed while you sent your message. Try again."
#: Existing copy the new paths must keep.
NOT_THE_SENDER = "Conversations are private. Only the session creator can view chat events."
REQUEST_NOT_FOUND = "Request not found"
INTERNAL_ERROR = "Internal server error"
LEGACY_LOCKED_DETAIL = {
    "code": "deck_mode_locked",
    "message": "This deck's mode is already set to Legacy mode, and it can't be changed.",
    "deck_mode": "legacy",
}

USER_MESSAGE = "MK-USER make me a deck"


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class _GraphStub:
    """``invoke_graph``: runs :attr:`body` under the turn's request id."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.body: Optional[Callable[[str, Optional[str]], None]] = None

    def __call__(self, session_id, initial=None, *, emitter=None, request_id=None, **kwargs):
        self.calls.append(request_id)
        if self.body is not None:
            with in_turn(request_id):
                self.body(session_id, request_id)
        return {}


class Api:
    def __init__(
        self, client: TestClient, rb: RollbackEnv, enqueued: AsyncMock, graph, monkeypatch
    ):
        self.client = client
        self.rb = rb
        self.enqueued = enqueued
        self.graph = graph
        self._monkeypatch = monkeypatch

    # -- identity ------------------------------------------------------------

    def sign_in(self, user: str) -> None:
        self._monkeypatch.setenv("DEV_USER_ID", user)

    # -- routes --------------------------------------------------------------

    def submit(self, session_id: str, message: str = USER_MESSAGE, *, deck_mode=None):
        body: Dict[str, Any] = {"session_id": session_id, "message": message}
        if deck_mode is not None:
            body["deck_mode"] = deck_mode
        return self.client.post("/api/chat/async", json=body)

    def submit_ok(self, session_id: str, **kwargs) -> str:
        resp = self.submit(session_id, **kwargs)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        body = resp.json()
        assert body == {"request_id": body["request_id"], "status": "pending"}
        return body["request_id"]

    def cancel(self, request_id: str):
        return self.client.post(f"/api/chat/cancel/{request_id}")

    def poll(self, request_id: str, after_message_id: int = 0) -> Dict[str, Any]:
        resp = self.client.get(
            f"/api/chat/poll/{request_id}", params={"after_message_id": after_message_id}
        )
        assert resp.status_code == 200, (resp.status_code, resp.text)
        return resp.json()

    # -- the job -------------------------------------------------------------

    def payload(self, request_id: str) -> Dict[str, Any]:
        for call in self.enqueued.await_args_list:
            if call.args[0] == request_id:
                return dict(call.args[1])
        raise AssertionError(f"no job was enqueued for {request_id}")

    def run_job(self, request_id: str) -> Optional[BaseException]:
        try:
            asyncio.run(job_queue.process_chat_request(request_id, self.payload(request_id)))
        except Exception as exc:  # noqa: BLE001 -- asserted by the caller
            return exc
        return None

    # -- reads ---------------------------------------------------------------

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.rb.tables()

    def requests_of(self, session_id: str) -> List[Dict[str, Any]]:
        pk = self.rb.pk(session_id)
        return [r for r in self.tables()["chat_requests"] if r["session_id"] == pk]


@pytest.fixture
def api(monkeypatch, tmp_path) -> Iterator[Api]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/stop-routes.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    rb = build_env(engine, monkeypatch)

    monkeypatch.setattr("src.api.middleware.request_logging._enqueue_log", lambda entry: None)
    monkeypatch.setattr("src.api.services.usage_events._submit", lambda *a, **k: None)
    enqueued = AsyncMock()
    monkeypatch.setattr("src.api.routes.chat.enqueue_job", enqueued)

    graph = _GraphStub()
    monkeypatch.setattr("src.services.graph.builder.invoke_graph", graph)
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title", lambda message, model: None
    )
    monkeypatch.setattr("src.api.services.session_naming.build_session_title_model", MagicMock())

    monkeypatch.setenv("DEV_USER_ID", OWNER)
    job_queue.jobs.clear()
    job_queue.shutdown_chat_executor()
    try:
        with TestClient(app) as client:
            yield Api(client, rb, enqueued, graph, monkeypatch)
    finally:
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


def start(request_id: str) -> None:
    """The job picked the request up (``pending`` -> ``running``)."""
    with get_db_session() as db:
        assert start_chat_request(db, request_id), "the job could not start the request"


def _newest_request(api: Api, session_id: str) -> Optional[str]:
    rows = api.requests_of(session_id)
    return rows[-1]["request_id"] if rows else None


def _has_user_message(api: Api, request_id: str) -> bool:
    return any(
        m["role"] == "user" for m in _messages_tagged(api.tables(), request_id)
    )


def _after_the_user_message(api: Api, monkeypatch, then: Callable[[str, str], str]) -> None:
    """Replace the route's post-message engine resolution: once the newest
    request's user message is saved, call ``then(session_id, request_id)``; any
    earlier call (a read-only pre-decision, if it uses this resolver) is real."""
    import src.api.routes.chat as chat_routes

    real = chat_routes.resolve_engine_mode_or_unavailable

    def resolver(session_id):
        rid = _newest_request(api, session_id)
        if rid is not None and _has_user_message(api, rid):
            return then(session_id, rid)
        return real(session_id)

    monkeypatch.setattr(chat_routes, "resolve_engine_mode_or_unavailable", resolver)


def _assert_refused_submit(api: Api, before, after, *, session_id: str) -> None:
    """A submit refused before the snapshot: one new request row, ``error``,
    never rolled back; the session's lock taken and given back; nothing else."""
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    _assert_sessions_equal(before, after, touched=(session_id,))
    old = before["chat_requests"]
    assert after["chat_requests"][: len(old)] == old
    new = after["chat_requests"][len(old):]
    assert len(new) == 1, f"expected one new request row, got {len(new)}"
    # Every column but the generated ones and error_message (the brief says only
    # "mark the request error", so its text is the implementer's choice).
    generated = ("id", "request_id", "created_at", "completed_at", "error_message")
    assert _without(new[0], generated) == {
        "session_id": api.rb.pk(session_id),
        "status": "error",
        "result_json": None,
        "progress_json": None,
        "progress_seq": None,
        "rollback_outcome": None,
    }


# ---------------------------------------------------------------------------
# The stop route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["first_generation", "edit"])
def test_cancel_rolls_back_and_frees_session(api, kind):
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if kind == "edit":
        seed_earlier_turn(api.rb, sid)
    before = api.tables()
    rid = api.submit_ok(sid)
    start(rid)
    if kind == "edit":
        edit_turn(api.rb, sid, sid, rid)
    else:
        first_generation_turn(api.rb, sid, rid)
    at_turn_end = api.tables()

    resp = api.cancel(rid)

    assert resp.status_code == 200, (resp.status_code, resp.text)
    # The brief gives `status` only for already_finished ("with the current
    # status"); on a cancel it may be the new status or null.
    assert resp.json() in (
        {"outcome": "cancelled", "status": "cancelled"},
        {"outcome": "cancelled", "status": None},
    )
    after = api.tables()
    _assert_rolled_back_to_enter(
        api.rb,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=kind == "edit",
    )
    _assert_lock(api.rb, sid, held_by=None)

    # A second stop (another tab, or Esc after the click) is a definite answer
    # and restores nothing a second time.
    again = api.cancel(rid)
    assert again.status_code == 200, (again.status_code, again.text)
    assert again.json() == {"outcome": "already_finished", "status": "cancelled"}
    _assert_tables_equal(after, api.tables())

    # The person can send again at once.
    next_resp = api.submit(sid, "MK-USER try again")
    assert next_resp.status_code == 200, (next_resp.status_code, next_resp.text)
    assert next_resp.json()["request_id"] != rid


def test_cancel_after_complete_is_already_finished(api):
    """Review Focus 2: the stop loses the race to completion.  A definite
    "already finished", the finished deck kept, and nothing written."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = api.submit_ok(sid)
    api.graph.body = lambda s, r: first_generation_turn(api.rb, s, r)
    raised = api.run_job(rid)
    assert raised is None, f"the turn failed: {raised!r}"
    assert api.rb.request_row(rid)["status"] == "completed"
    before = api.tables()

    resp = api.cancel(rid)

    assert resp.status_code == 200, (resp.status_code, resp.text)
    assert resp.json() == {"outcome": "already_finished", "status": "completed"}
    _assert_tables_equal(before, api.tables())
    assert api.rb.slide_htmls(sid) == SLIDES_BUILT


def test_cancel_other_users_request_is_403(api):
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = api.submit_ok(sid)
    start(rid)
    first_generation_turn(api.rb, sid, rid)
    before = api.tables()

    api.sign_in(STRANGER)
    resp = api.cancel(rid)

    assert resp.status_code == 403, (resp.status_code, resp.text)
    assert resp.json() == {"detail": NOT_THE_SENDER}
    _assert_tables_equal(before, api.tables())
    assert api.rb.request_row(rid)["status"] == "running"


def test_cancel_unknown_request_is_404(api):
    api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = api.tables()

    resp = api.cancel("no-such-request")

    assert resp.status_code == 404, (resp.status_code, resp.text)
    assert resp.json() == {"detail": REQUEST_NOT_FOUND}
    _assert_tables_equal(before, api.tables())


@pytest.mark.parametrize("job_state", ["pending", "running"])
def test_cancel_monolith_turn_is_409_not_stoppable(api, job_state):
    """A Legacy deck's turn has no snapshot, so it cannot be undone: the stop is
    refused and the turn carries on untouched."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = api.submit_ok(sid, deck_mode="legacy")
    assert api.payload(rid)["engine_mode"] == "monolith"
    if job_state == "running":
        get_session_manager().update_chat_request_status(rid, "running")
    before = api.tables()

    resp = api.cancel(rid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": NOT_STOPPABLE, "outcome": "not_stoppable"}
    _assert_tables_equal(before, api.tables())
    assert api.rb.request_row(rid)["status"] == job_state
    _assert_lock(api.rb, sid, held_by=rid)


def test_cancel_refused_on_foreign_change_409(api):
    """Someone else edited the shared deck since Enter: the stop is refused, the
    generation carries on (still ``running``, snapshot kept, lock held) and their
    edit survives."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    contributor = api.rb.contributor(sid)
    rid = api.submit_ok(sid)
    start(rid)
    edit_turn(api.rb, sid, sid, rid)
    foreign_edit(api.rb, contributor)
    before = api.tables()

    resp = api.cancel(rid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": REFUSED_STOP, "outcome": "refused_foreign_change"}
    _assert_tables_equal(before, api.tables())
    assert api.rb.request_row(rid)["status"] == "running"
    assert [s["state"] for s in api.rb.snapshot_rows(rid)] == ["active"]
    _assert_lock(api.rb, sid, held_by=rid)


def test_cancel_restore_failure_is_500(api):
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    rid = api.submit_ok(sid)
    start(rid)
    edit_turn(api.rb, sid, sid, rid)

    with _slide_inserts_fail(api.rb.engine) as seen:
        resp = api.cancel(rid)

    assert resp.status_code == 500, (resp.status_code, resp.text)
    assert resp.json() == {"detail": INTERNAL_ERROR}
    assert seen, "the restore never re-inserted a slide row; the test proves nothing"
    row = api.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "cancelled",
        RESTORE_PENDING,
        "restore_failed",
    )
    _assert_lock(api.rb, sid, held_by=rid)


# ---------------------------------------------------------------------------
# The poll
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ended_by", ["stop", "failure"])
def test_poll_reports_cancelled_and_rollback(api, ended_by):
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = api.submit_ok(sid)
    user_message = _one(_messages_tagged(api.tables(), rid), role="user")

    pending = api.poll(rid)
    assert isinstance(pending.pop("revision_mark"), float)
    assert pending == {
        "status": "pending",
        "events": [],
        "last_message_id": user_message["id"],
        "result": None,
        "error": None,
        "slides": [],
        "slide_cursor": 0,
        "slide_revisions": [],
        "turn_progress": None,
        "rollback": None,
    }

    start(rid)
    first_generation_turn(api.rb, sid, rid)
    if ended_by == "stop":
        resp = api.cancel(rid)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        status, error = "cancelled", None
    else:
        assert roll_back(rid, "error", "MK-failed: 403", False) == RollbackResult.ROLLED_BACK
        status, error = "error", "MK-failed: 403"

    ended = api.poll(rid)
    assert isinstance(ended.pop("revision_mark"), float)
    assert ended == {
        "status": status,
        "events": [],
        "last_message_id": 0,
        "result": None,
        "error": error,
        "slides": [],
        "slide_cursor": 0,
        "slide_revisions": [],
        "turn_progress": None,
        "rollback": "rolled_back",
    }


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["contributor_restore", "own_stale_lock"])
def test_submit_refused_while_restore_pending(api, where):
    """A failed restore is pending on the deck: no new Agent turn may start on it
    (the snapshot would capture a half-restored deck)."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    actor = api.rb.contributor(sid) if where == "contributor_restore" else sid
    rid_failed = press_enter(api.rb, actor)
    edit_turn(api.rb, actor, sid, rid_failed)
    with _slide_inserts_fail(api.rb.engine):
        assert roll_back(rid_failed, "error", "MK failed", False) == RollbackResult.RESTORE_FAILED
    assert generation_rollback.has_pending_restore(sid) is True
    if where == "own_stale_lock":
        # Time passed: the failed turn's lock went stale (nothing refreshes it).
        with get_db_session() as db:
            db.execute(
                update(UserSession)
                .where(UserSession.session_id == sid)
                .values(processing_started_at=datetime.utcnow() - timedelta(hours=1))
            )
    before = api.tables()

    resp = api.submit(sid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": RESTORE_PENDING}
    api.enqueued.assert_not_awaited()
    after = api.tables()
    if where == "own_stale_lock":
        # The stale lock was taken by the refused request and given back.
        owner_after = api.rb.session_row(sid)
        assert (
            owner_after["is_processing"],
            owner_after["processing_started_at"],
            owner_after["processing_request_id"],
        ) == (False, None, None)
        for table in (before, after):
            for row in table["user_sessions"]:
                if row["session_id"] == sid:
                    row.update(is_processing=None, processing_started_at=None,
                               processing_request_id=None)
    _assert_refused_submit(api, before, after, session_id=sid)


def test_submit_refused_during_arc_review(api):
    """The arc-review sweeper holds a live claim on the deck (it runs a graph turn
    on the owner's thread with no session lock): Enter is refused."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    assert mark_dirty(sid, OWNER) is True
    claimed = claim_due_marker(datetime.utcnow() + timedelta(seconds=DEBOUNCE_SECONDS + 1))
    assert claimed == (sid, OWNER), "the sweeper did not claim the deck"
    before = api.tables()

    resp = api.submit(sid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": ARC_REVIEW_BUSY}
    api.enqueued.assert_not_awaited()
    _assert_refused_submit(api, before, api.tables(), session_id=sid)
    _assert_lock(api.rb, sid, held_by=None)


@pytest.mark.parametrize("failure", ["engine_resolution", "enqueue"])
def test_submit_failure_after_snapshot_rolls_back(api, monkeypatch, failure):
    """Enter saved the user message and locked the deck mode, then the submit
    failed: the failure is rolled back before its usual error answer."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = api.tables()
    at: Dict[str, Any] = {}

    if failure == "engine_resolution":

        def fail(session_id, rid):
            at["enter"] = api.tables()
            raise PersistedConfigurationUnavailableError(code="lakebase_unavailable")

        _after_the_user_message(api, monkeypatch, fail)
        expected = (503, {"detail": dict(ENGINE_MODE_UNAVAILABLE_DETAIL)})
    else:

        async def fail_enqueue(request_id, payload):
            at["enter"] = api.tables()
            raise RuntimeError("MK-INJECTED the queue is gone")

        api.enqueued.side_effect = fail_enqueue
        expected = (500, {"detail": INTERNAL_ERROR})

    resp = api.submit(sid)

    assert (resp.status_code, resp.json()) == expected
    assert "enter" in at, "the injected failure never fired"
    entered = at["enter"]
    rid = _newest_request(api, sid)
    assert _one(entered["user_sessions"], session_id=sid)["deck_mode"] == "agent"
    assert len(_messages_tagged(entered, rid)) == 1
    assert [s["request_id"] for s in entered["generation_snapshots"]] == [rid], (
        "no snapshot had been taken when the submit failed"
    )
    after = api.tables()
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    _assert_sessions_equal(before, after, touched=(sid,))
    assert _messages_tagged(after, rid) == [], "the failed submit's user message remains"
    assert api.rb.session_row(sid)["deck_mode"] is None, "the deck-mode lock was not undone"
    assert api.rb.session_row(sid)["graph_release_id"] is None, "the pin was not undone"
    row = api.rb.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("error", "rolled_back")
    _assert_lock(api.rb, sid, held_by=None)


def test_deck_mode_locked_by_another_message_discards_not_rolls_back(api, monkeypatch):
    """C9.  Between this Enter's snapshot and its user message, a contributor's
    first message locked the shared deck to Legacy.  ``add_user_message`` then
    refuses ours and writes nothing.  The snapshot is discarded -- a rollback
    would put the deck mode (and pins) back to before the OTHER person's lock."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    contributor = api.rb.contributor(sid)
    at: Dict[str, Any] = {}
    real_add = SessionManager.add_user_message

    def racing_add(self, session_id, content, **kwargs):
        if session_id == sid and "foreign" not in at:
            at["snapshots"] = api.rb.snapshot_rows(kwargs["request_id"])
            real_add(
                self, contributor, "MK-FOREIGN first message",
                message_type="user_query", requested_deck_mode="legacy",
            )
            at["foreign"] = api.tables()
        return real_add(self, session_id, content, **kwargs)

    monkeypatch.setattr(SessionManager, "add_user_message", racing_add)

    resp = api.submit(sid, deck_mode="agent")

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": LEGACY_LOCKED_DETAIL}
    rid = _newest_request(api, sid)
    assert [s["request_id"] for s in at["snapshots"]] == [rid], (
        "no snapshot was taken before the user message"
    )
    foreign, after = at["foreign"], api.tables()
    assert api.rb.session_row(sid)["deck_mode"] == "legacy", (
        "the other person's deck-mode lock was reverted"
    )
    _assert_tables_equal(
        foreign, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    assert after["generation_snapshots"] == [], "the snapshot was not discarded"
    _assert_sessions_equal(foreign, _unlocked(after, sid, foreign), touched=(sid,))
    row = _one(after["chat_requests"], request_id=rid)
    assert row["completed_at"] is not None
    assert _without(row, ("completed_at",)) == _without(
        dict(
            _one(foreign["chat_requests"], request_id=rid),
            status="error",
            error_message="deck_mode_locked",
            rollback_outcome=None,
        ),
        ("completed_at",),
    )
    _assert_lock(api.rb, sid, held_by=None)


def _unlocked(after, session_id: str, reference) -> Dict[str, Any]:
    """*after* with *session_id*'s lock columns put back to *reference*'s (the
    lock's release is asserted separately)."""
    ref = _one(reference["user_sessions"], session_id=session_id)
    rows = []
    for row in after["user_sessions"]:
        if row["session_id"] == session_id:
            row = dict(
                row,
                is_processing=ref["is_processing"],
                processing_started_at=ref["processing_started_at"],
                processing_request_id=ref["processing_request_id"],
            )
        rows.append(row)
    return dict(after, user_sessions=rows)


def test_engine_mismatch_discards_snapshot(api, monkeypatch):
    """Enter decided ``graph`` (unlocked deck) and took a snapshot; a contributor's
    Legacy first message then locked the deck, so the turn resolves ``monolith``.
    The snapshot is discarded (never rolled back) and the job runs on the monolith."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    contributor = api.rb.contributor(sid)
    at: Dict[str, Any] = {}
    real_add = SessionManager.add_user_message

    def racing_add(self, session_id, content, **kwargs):
        if session_id == sid and "foreign" not in at:
            at["snapshots"] = api.rb.snapshot_rows(kwargs["request_id"])
            real_add(
                self, contributor, "MK-FOREIGN first message",
                message_type="user_query", requested_deck_mode="legacy",
            )
            at["foreign"] = api.tables()
        return real_add(self, session_id, content, **kwargs)

    monkeypatch.setattr(SessionManager, "add_user_message", racing_add)

    rid = api.submit_ok(sid)

    assert [s["request_id"] for s in at["snapshots"]] == [rid], (
        "no snapshot was taken before the user message"
    )
    assert api.payload(rid)["engine_mode"] == "monolith"
    foreign, after = at["foreign"], api.tables()
    assert after["generation_snapshots"] == [], "the snapshot was not discarded"
    assert api.rb.session_row(sid)["deck_mode"] == "legacy"
    _assert_tables_equal(
        foreign, after, exclude=("generation_snapshots", "session_messages", "user_sessions")
    )
    _assert_sessions_equal(foreign, after, touched=(sid,))
    assert after["session_messages"][: len(foreign["session_messages"])] == foreign[
        "session_messages"
    ]
    added = after["session_messages"][len(foreign["session_messages"]):]
    assert [(m["role"], m["content"], m["message_type"], m["request_id"]) for m in added] == [
        ("user", USER_MESSAGE, "user_query", rid)
    ]
    row = api.rb.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("pending", None)
    _assert_lock(api.rb, sid, held_by=rid)


def test_engine_mismatch_reverse_fails_closed(api, monkeypatch):
    """Enter decided ``monolith`` (a Legacy deck: no snapshot) but the turn resolves
    ``graph``.  A graph turn must never run without a snapshot: the request's
    messages are deleted, it ends ``error``, the lock is released, nothing is
    queued, and the engine-race 409 is answered."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    get_session_manager().add_user_message(
        sid, "MK-EARLIER legacy first message", message_type="user_query",
        requested_deck_mode="legacy",
    )
    _after_the_user_message(api, monkeypatch, lambda session_id, rid: "graph")
    before = api.tables()

    resp = api.submit(sid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == {"detail": ENGINE_RACE}
    api.enqueued.assert_not_awaited()
    _assert_refused_submit(api, before, api.tables(), session_id=sid)
    _assert_lock(api.rb, sid, held_by=None)


@pytest.mark.parametrize("deck", ["locked_legacy", "first_message_legacy"])
def test_monolith_submit_writes_no_snapshot(api, monkeypatch, deck):
    """Guard: a Legacy turn takes exactly today's submit path -- the snapshot
    machinery (refusal checks, snapshot, discard, rollback) is never touched."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if deck == "locked_legacy":
        get_session_manager().add_user_message(
            sid, "MK-EARLIER legacy first message", message_type="user_query",
            requested_deck_mode="legacy",
        )
    used: List[str] = []

    def forbidden(name):
        def call(*args, **kwargs):
            used.append(name)
            raise AssertionError(f"a Legacy submit called {name}")

        return call

    import src.api.routes.chat as chat_routes

    for name in (
        "take_generation_snapshot",
        "has_pending_restore",
        "discard_generation_snapshot",
        "roll_back_generation",
    ):
        monkeypatch.setattr(generation_rollback, name, forbidden(name))
        monkeypatch.setattr(chat_routes, name, forbidden(name), raising=False)
    before = api.tables()

    rid = api.submit_ok(sid, deck_mode="legacy" if deck == "first_message_legacy" else None)

    assert used == []
    assert api.payload(rid)["engine_mode"] == "monolith"
    after = api.tables()
    assert after["generation_snapshots"] == []
    assert api.rb.session_row(sid)["deck_mode"] == "legacy"
    added = after["session_messages"][len(before["session_messages"]):]
    assert [(m["role"], m["content"], m["request_id"]) for m in added] == [
        ("user", USER_MESSAGE, rid)
    ]
    assert api.rb.request_row(rid)["status"] == "pending"
    _assert_lock(api.rb, sid, held_by=rid)
