"""Task 7: while an Agent-deck generation is live, it holds the deck for its sender.

The contract (plan Task 7, spec "Locks and other people" rules 2 and 3):

* **The editing lock.**  ``SessionManager.require_editing_lock``,
  ``acquire_editing_lock`` and ``get_editing_lock_status`` consult the deck's live
  generation (``_live_generation_holder``): the newest ``GenerationSnapshot`` on the
  deck owner whose ``chat_requests`` row is live (``pending`` / ``running``), or whose
  own ``state`` is ``restore_failed``.  Its holder is the ``created_by`` of the
  snapshot's actor session.  A holder who is not the caller means "locked by the
  holder", whatever ``locked_by`` / ``locked_at`` (the browser heartbeat) say.  Once
  the generation has ended (completed, stopped, failed and rolled back) the lock
  follows today's rules again.  A monolith turn takes no snapshot, so it never holds.
* **The owner's chat route.**  ``_check_chat_permission``'s root-owner branch
  answers 423 ``Session is locked by <display name>`` only when a live generation of
  SOMEONE ELSE holds the deck.  It does not call ``require_editing_lock``: an idle
  contributor's heartbeat lock never blocks the owner (Agent and Legacy decks), and
  the owner's own generation is not "someone else".
* **The arc-review sweeper.**  ``claim_due_marker`` never claims a deck with a live
  generation or a ``restore_failed`` snapshot, and such a deck does not starve the
  queue: the next due deck is claimed instead.  The marker is kept and is claimed
  once the generation has ended.  (The submit/claim serialisation under real row
  locks is ``tests/integration/test_generation_lock_postgres.py``.)

How the tests are built
-----------------------
* A file-backed SQLite database behind every ``get_db_session``, the checkpointer and
  the routes' ``get_db`` (``build_env`` from the Task 4 suite).
* Live generations are seeded exactly as production makes them: ``press_enter`` (the
  Task 4 helper) runs ``submit_chat_async``'s order -- session lock, ``chat_requests``
  row, the lock bound to it, the generation snapshot (actor and owner pks), the user
  message -- then the job's ``pending`` -> ``running``.  Ends run the real ends: the
  seal + ``complete_chat_request`` + release (success), ``roll_back_generation``
  (stop, failure, failed restore), ``fail_chat_request`` (the C13 path that leaves an
  ``active`` snapshot on an ended request).  A monolith turn is the same order with
  no snapshot and the monolith job's ``update_chat_request_status(..., "running")``.
* The editing lock is taken through the real ``acquire_editing_lock`` /
  ``release_editing_lock``; "the heartbeat lapsed 10 minutes ago" back-dates
  ``locked_at`` (time passing is the one thing a test has to fake).
* Display names: SCIM is replaced at ``identity_provider._resolve_cached`` with a
  fixed map, so every refusal must name the HOLDER'S DISPLAY NAME, not an email and
  not whoever ``locked_by`` names.
* Chat and manual edits go through ``TestClient(app)`` (real auth middleware with
  ``DEV_USER_ID``, real permission gates); only ``enqueue_job``, the title model,
  ``get_settings``, the middleware's background log/usage writers and the chat
  service's Databricks username lookup are stubbed.
* "Nothing was taken over / nothing changed" compares every table, every column.

Guards (green today, by design): ``test_owner_chat_allowed_on_unshared_deck``,
``test_owner_chat_allowed_while_contributor_holds_idle_heartbeat_lock`` and
``test_monolith_turn_does_not_hold_lock`` pin what must NOT change.
``test_lock_follows_normal_rules_after_generation_ends`` first asserts, as a
precondition, that the live generation did hold the lock (red today), then that its
end gives the deck back to today's rules.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.main import app
from src.api.services import job_queue
from src.api.services.session_manager import get_session_manager
from src.core.database import Base, _run_migrations, get_db_session
from src.core.user_context import get_current_user, set_current_user
from src.database.models.session import SessionSlideDeck, UserSession
from src.services.generation_fence import start_chat_request
from src.services.generation_rollback import (
    RollbackResult,
    recover_orphaned_generations,
    seal_generation,
)
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from src.services.spec_sync import DEBOUNCE_SECONDS, claim_due_marker, mark_dirty
from tests.unit.test_generation_rollback import (
    CONTRIBUTOR,
    OWNER,
    RESTORE_PENDING,
    STRANGER,
    RollbackEnv,
    _assert_lock,
    _assert_tables_equal,
    _ctx,
    _slide_inserts_fail,
    build_env,
    edit_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)

#: SCIM display names.  Every refusal must carry the holder's, never an email.
NAMES: Dict[str, str] = {
    OWNER: "Dana Owner",
    CONTRIBUTOR: "Casey Contributor",
    STRANGER: "Sam Stranger",
}

#: Existing copy the new paths must keep.
SESSION_BUSY = "Session is already processing a request"

HEARTBEAT_LAPSED_SECONDS = 600  # "locked_at is 10 minutes old" (the timeout is 45 s)

LEGACY_SLIDE = "<div class='slide'><h1>MK-LEGACY</h1></div>"
MANUAL_EDIT = "<div class='slide'><h1>MK-EDITED-BY-HAND</h1></div>"
OWNER_MESSAGE = "MK-OWNER add a slide"


def locked_by(user: str) -> str:
    """``require_editing_lock``'s wording, with *user*'s display name."""
    return f"Session is locked by {NAMES[user]}"


def _display_name(email: str) -> str:
    return NAMES.get(email, email)


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch, tmp_path) -> Iterator[RollbackEnv]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/generation-lock.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    rb = build_env(engine, monkeypatch)
    # resolve_display_name -> _resolve_cached (looked up at call time, whatever the
    # caller imported): a fixed map instead of SCIM, which would retry and hang.
    monkeypatch.setattr("src.services.identity_provider._resolve_cached", _display_name)
    yield rb
    engine.dispose()


class Api:
    def __init__(self, client: TestClient, rb: RollbackEnv, enqueued: AsyncMock, monkeypatch):
        self.client = client
        self.rb = rb
        self.enqueued = enqueued
        self._monkeypatch = monkeypatch

    def sign_in(self, user: str) -> None:
        self._monkeypatch.setenv("DEV_USER_ID", user)

    def submit(self, session_id: str, message: str = OWNER_MESSAGE):
        return self.client.post(
            "/api/chat/async", json={"session_id": session_id, "message": message}
        )

    def submit_ok(self, session_id: str) -> str:
        resp = self.submit(session_id)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        body = resp.json()
        assert body == {"request_id": body["request_id"], "status": "pending"}
        return body["request_id"]

    def payload(self, request_id: str) -> Dict[str, Any]:
        for call in self.enqueued.await_args_list:
            if call.args[0] == request_id:
                return dict(call.args[1])
        raise AssertionError(f"no job was enqueued for {request_id}")

    def edit_slide(self, session_id: str, index: int, html: str):
        return self.client.patch(
            f"/api/slides/{index}", json={"session_id": session_id, "html": html}
        )


@pytest.fixture
def api(env, monkeypatch) -> Iterator[Api]:
    monkeypatch.setattr("src.api.middleware.request_logging._enqueue_log", lambda entry: None)
    monkeypatch.setattr("src.api.services.usage_events._submit", lambda *a, **k: None)
    enqueued = AsyncMock()
    monkeypatch.setattr("src.api.routes.chat.enqueue_job", enqueued)
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title", lambda message, model: None
    )
    monkeypatch.setattr("src.api.services.session_naming.build_session_title_model", MagicMock())
    # A manual edit stamps modified_by through the Databricks SDK, which retries
    # (and hangs) against an unreachable host.
    monkeypatch.setattr("src.api.services.chat_service.get_current_username", lambda: OWNER)
    monkeypatch.setenv("DEV_USER_ID", OWNER)
    job_queue.jobs.clear()
    job_queue.shutdown_chat_executor()
    try:
        with TestClient(app) as client:
            yield Api(client, env, enqueued, monkeypatch)
    finally:
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()


@pytest.fixture(autouse=True)
def _no_request_id_or_user_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    previous_user = get_current_user()
    set_current_user(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)
        set_current_user(previous_user)


@contextlib.contextmanager
def as_user(user: str) -> Iterator[None]:
    """Run the block as *user* (what the auth middleware binds for a request)."""
    previous = get_current_user()
    set_current_user(user)
    try:
        yield
    finally:
        set_current_user(previous)


# ---------------------------------------------------------------------------
# Decks, generations and their ends -- through the real code paths
# ---------------------------------------------------------------------------


class SharedDeck:
    """An owner's deck and one contributor session on it."""

    def __init__(self, owner: str, contributor: str):
        self.owner = owner
        self.contributor = contributor

    def of(self, role: str) -> Tuple[str, str]:
        """``(session_id, user)`` of *role* (``"owner"`` / ``"contributor"``)."""
        return (self.owner, OWNER) if role == "owner" else (self.contributor, CONTRIBUTOR)

    def other(self, role: str) -> Tuple[str, str]:
        return self.of("contributor" if role == "owner" else "owner")


def seed_legacy_deck(env: RollbackEnv, owner_sid: str) -> None:
    """An earlier, completed Legacy (monolith) turn: the first message locks the deck
    to Legacy, the monolith saves a one-slide deck, the request completes."""
    sm = get_session_manager()
    rid0 = sm.create_chat_request(owner_sid)
    sm.add_user_message(
        owner_sid,
        "MK-EARLIER legacy first message",
        message_type="user_query",
        request_id=rid0,
        requested_deck_mode="legacy",
    )
    sm.update_chat_request_status(rid0, "running")
    sm.save_slide_deck(
        owner_sid,
        "MK-LEGACY-DECK",
        f"<html>{LEGACY_SLIDE}</html>",
        slide_count=1,
        deck_dict={"slides": [{"slide_id": "slide_mk_legacy_0", "html": LEGACY_SLIDE}]},
        modified_by=OWNER,
        mutation=_ctx(owner_sid, "save_deck", "deck"),
    )
    sm.add_message(
        owner_sid, "assistant", "MK-EARLIER legacy reply", message_type="chat", request_id=rid0
    )
    sm.update_chat_request_status(rid0, "completed")
    assert env.session_row(owner_sid)["deck_mode"] == "legacy"
    assert env.deck_row(owner_sid) is not None, "the Legacy turn saved no deck row"


def shared_deck(env: RollbackEnv, *, legacy: bool = False) -> SharedDeck:
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    if legacy:
        seed_legacy_deck(env, owner)
    else:
        seed_earlier_turn(env, owner)
    return SharedDeck(owner, env.contributor(owner))


def start_generation(env: RollbackEnv, actor_sid: str, live: str) -> str:
    """An Agent-deck Enter on *actor_sid*, left ``pending``, ``running`` or
    ``sealed`` (graph finished, request still ``running``: the save point and the
    title join are still to come)."""
    rid = press_enter(env, actor_sid, start=live != "pending")
    if live == "sealed":
        assert seal_generation(rid) is True
    assert env.request_row(rid)["status"] == ("pending" if live == "pending" else "running")
    return rid


def end_generation(env: RollbackEnv, rid: str, actor_sid: str, how: str) -> None:
    sm = get_session_manager()
    if how == "completed":
        # The job's success path: seal, complete (drops the snapshot), release.
        assert seal_generation(rid) is True
        assert sm.complete_chat_request(rid, None) is True
        assert sm.release_session_lock(actor_sid, rid) is True
        assert env.snapshot_rows(rid) == []
    elif how == "stopped":
        assert roll_back(rid, "cancelled", None, True) == RollbackResult.ROLLED_BACK
    elif how == "failed":
        assert roll_back(rid, "error", "MK failed", False) == RollbackResult.ROLLED_BACK
    elif how == "ended_with_leftover_snapshot":
        # C13: a discard that raised at submit ends the request with
        # fail_chat_request; the ``active`` snapshot row stays behind, harmless.
        assert sm.fail_chat_request(rid, "MK failed") is True
        assert sm.release_session_lock(actor_sid, rid) is True
        assert [s["state"] for s in env.snapshot_rows(rid)] == ["active"]
    else:  # pragma: no cover
        raise AssertionError(how)
    assert env.request_row(rid)["status"] in ("completed", "cancelled", "error")


def monolith_enter(env: RollbackEnv, session_id: str, *, start: bool) -> str:
    """``POST /chat/async`` on a Legacy deck, then the monolith job's start: session
    lock, request row, bound lock, user message -- and no snapshot."""
    sm = get_session_manager()
    assert sm.acquire_session_lock(session_id)
    rid = sm.create_chat_request(session_id)
    sm.bind_session_lock(session_id, rid)
    sm.add_user_message(
        session_id, "MK-MONOLITH make me a slide", message_type="user_query", request_id=rid
    )
    if start:
        sm.update_chat_request_status(rid, "running")
    return rid


def fail_restore(env: RollbackEnv, actor_sid: str, owner_sid: str) -> str:
    """An edit turn on *actor_sid* whose failure's restore failed part-way."""
    rid = press_enter(env, actor_sid)
    edit_turn(env, actor_sid, owner_sid, rid)
    with _slide_inserts_fail(env.engine) as attempted:
        assert roll_back(rid, "error", "MK failed", False) == RollbackResult.RESTORE_FAILED
    assert attempted, "the restore never re-inserted a slide; nothing failed"
    row = env.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("error", "restore_failed"), (
        "the request is no longer live: only the snapshot's state can keep the deck"
    )
    assert [s["state"] for s in env.snapshot_rows(rid)] == ["restore_failed"]
    return rid


def _lock_columns(env: RollbackEnv, owner_sid: str) -> Tuple[Optional[str], Optional[datetime]]:
    row = env.deck_row(owner_sid)
    return row["locked_by"], row["locked_at"]


def lapse_heartbeat(env: RollbackEnv, owner_sid: str, user: str) -> None:
    """*user* still names the lock, but their browser stopped heartbeating
    :data:`HEARTBEAT_LAPSED_SECONDS` ago."""
    db = env.factory()
    try:
        db.execute(
            update(SessionSlideDeck)
            .where(SessionSlideDeck.session_id == env.pk(owner_sid))
            .values(
                locked_by=user,
                locked_at=datetime.utcnow() - timedelta(seconds=HEARTBEAT_LAPSED_SECONDS),
            )
        )
        db.commit()
    finally:
        db.close()


def backdate_session_lock(env: RollbackEnv, session_id: str) -> None:
    """Time passed: a session lock nothing refreshes went stale."""
    db = env.factory()
    try:
        db.execute(
            update(UserSession)
            .where(UserSession.session_id == session_id)
            .values(processing_started_at=datetime.utcnow() - timedelta(hours=1))
        )
        db.commit()
    finally:
        db.close()


def _due() -> datetime:
    """A sweeper tick after the debounce window of every marker set so far."""
    return datetime.utcnow() + timedelta(seconds=DEBOUNCE_SECONDS + 1)


def _marker(row: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    return row["spec_dirty_at"], row["spec_dirty_by"], row["spec_dirty_claimed_at"]


def _status(user: Optional[str]) -> Dict[str, Any]:
    if user is None:
        return {"locked": False, "locked_by": None, "locked_by_email": None}
    return {"locked": True, "locked_by": NAMES[user], "locked_by_email": user}


# ---------------------------------------------------------------------------
# The editing lock
# ---------------------------------------------------------------------------

_LIVE_CASES = [
    pytest.param("owner", "running", "lapsed", id="owner-running-heartbeat_lapsed"),
    pytest.param("owner", "pending", "lapsed", id="owner-pending-heartbeat_lapsed"),
    pytest.param("owner", "sealed", "lapsed", id="owner-sealed_still_running-heartbeat_lapsed"),
    pytest.param("owner", "running", "released", id="owner-running-lock_released"),
    pytest.param(
        "owner", "running", "other_holds_fresh", id="owner-running-contributor_heartbeat_fresh"
    ),
    pytest.param("contributor", "running", "lapsed", id="contributor-running-heartbeat_lapsed"),
    pytest.param("contributor", "pending", "lapsed", id="contributor-pending-heartbeat_lapsed"),
    pytest.param(
        "contributor", "sealed", "lapsed", id="contributor-sealed_still_running-heartbeat_lapsed"
    ),
    pytest.param("contributor", "running", "released", id="contributor-running-lock_released"),
]


@pytest.mark.parametrize("actor, live, heartbeat", _LIVE_CASES)
def test_live_generation_keeps_lock_after_heartbeat_lapses(env, actor, live, heartbeat):
    """A's generation is live; A's browser heartbeat lapsed 10 minutes ago (or A's
    browser released the lock, or B's idle heartbeat names the lock).  B cannot
    take the lock, B's edits are refused naming A, and the status says A -- the
    generation holds the deck whatever ``locked_by`` / ``locked_at`` say."""
    deck = shared_deck(env)
    sm = get_session_manager()
    a_sid, a_user = deck.of(actor)
    b_sid, b_user = deck.other(actor)
    if heartbeat == "other_holds_fresh":
        # B opened the deck and is heartbeating; the owner's chat never needed the
        # editing lock, so the owner pressed Enter anyway.
        assert sm.acquire_editing_lock(b_sid, b_user) == {
            "acquired": True,
            "locked_by": NAMES[b_user],
        }
    else:
        # A opened the deck (took the lock), then pressed Enter.
        assert sm.acquire_editing_lock(a_sid, a_user) == {
            "acquired": True,
            "locked_by": NAMES[a_user],
        }
    start_generation(env, a_sid, live)
    if heartbeat == "lapsed":
        lapse_heartbeat(env, deck.owner, a_user)
    elif heartbeat == "released":
        sm.release_editing_lock(a_sid, a_user)
        assert _lock_columns(env, deck.owner) == (None, None)
    before = env.tables()

    assert sm.acquire_editing_lock(b_sid, b_user) == {
        "acquired": False,
        "locked_by": NAMES[a_user],
    }
    with as_user(b_user), pytest.raises(PermissionError) as refused:
        sm.require_editing_lock(b_sid)
    assert str(refused.value) == locked_by(a_user)
    # B took nothing over: no lock row write, nothing else either.
    _assert_tables_equal(before, env.tables())

    # Status has no caller: every viewer (B, and A's own browser) is told A.
    assert sm.get_editing_lock_status(b_sid) == _status(a_user)
    assert sm.get_editing_lock_status(a_sid) == _status(a_user)

    if heartbeat != "other_holds_fresh":
        # The sender is never locked out of their own deck.
        with as_user(a_user):
            sm.require_editing_lock(a_sid)
        assert sm.acquire_editing_lock(a_sid, a_user) == {
            "acquired": True,
            "locked_by": NAMES[a_user],
        }


_END_CASES = [
    pytest.param("contributor", "completed", id="contributor-completed"),
    pytest.param("contributor", "stopped", id="contributor-stopped"),
    pytest.param("contributor", "failed", id="contributor-failed_rolled_back"),
    pytest.param(
        "contributor",
        "ended_with_leftover_snapshot",
        id="contributor-error_leftover_active_snapshot",
    ),
    pytest.param("owner", "completed", id="owner-completed"),
]


@pytest.mark.parametrize("actor, how", _END_CASES)
def test_lock_follows_normal_rules_after_generation_ends(env, actor, how):
    """Once A's generation has ended -- completed, stopped, failed and rolled back,
    or ended with its ``active`` snapshot row left behind (C13; only a LIVE request
    or a ``restore_failed`` snapshot holds) -- the deck follows today's rules: A's
    lapsed heartbeat lock has expired, B takes it, and then B's fresh lock refuses A."""
    deck = shared_deck(env)
    sm = get_session_manager()
    a_sid, a_user = deck.of(actor)
    b_sid, b_user = deck.other(actor)
    assert sm.acquire_editing_lock(a_sid, a_user)["acquired"] is True
    rid = press_enter(env, a_sid)
    lapse_heartbeat(env, deck.owner, a_user)
    # Precondition: while live, the generation did hold the deck against B.
    assert sm.acquire_editing_lock(b_sid, b_user) == {
        "acquired": False,
        "locked_by": NAMES[a_user],
    }, "precondition: the live generation did not hold the lock, so its end proves nothing"

    end_generation(env, rid, a_sid, how)

    with as_user(b_user):
        sm.require_editing_lock(b_sid)
    assert sm.get_editing_lock_status(b_sid) == _status(None)
    assert sm.acquire_editing_lock(b_sid, b_user) == {
        "acquired": True,
        "locked_by": NAMES[b_user],
    }
    assert _lock_columns(env, deck.owner)[0] == b_user
    assert sm.get_editing_lock_status(a_sid) == _status(b_user)
    with as_user(a_user), pytest.raises(PermissionError) as refused:
        sm.require_editing_lock(a_sid)
    assert str(refused.value) == locked_by(b_user)
    assert sm.acquire_editing_lock(a_sid, a_user) == {
        "acquired": False,
        "locked_by": NAMES[b_user],
    }


@pytest.mark.parametrize("live", ["pending", "running"])
def test_monolith_turn_does_not_hold_lock(api, live):
    """A Legacy deck's monolith turn takes no snapshot, so it holds nothing: the
    lock, the owner's chat and the sweeper all behave exactly as today while it runs
    (Global Constraints: no behaviour change on Legacy decks)."""
    env = api.rb
    deck = shared_deck(env, legacy=True)
    sm = get_session_manager()
    assert mark_dirty(deck.owner, OWNER) is True
    assert sm.acquire_editing_lock(deck.contributor, CONTRIBUTOR)["acquired"] is True
    rid = monolith_enter(env, deck.contributor, start=live == "running")
    lapse_heartbeat(env, deck.owner, CONTRIBUTOR)
    assert env.tables()["generation_snapshots"] == [], "a monolith turn took a snapshot"
    assert env.request_row(rid)["status"] == live

    # The editing lock: the contributor's lapsed heartbeat lock has expired.
    with as_user(OWNER):
        sm.require_editing_lock(deck.owner)
    assert sm.get_editing_lock_status(deck.owner) == _status(None)
    assert sm.acquire_editing_lock(deck.owner, OWNER) == {
        "acquired": True,
        "locked_by": NAMES[OWNER],
    }
    assert sm.get_editing_lock_status(deck.contributor) == _status(OWNER)

    # The owner's chat is not refused.
    owner_rid = api.submit_ok(deck.owner)
    assert api.payload(owner_rid)["engine_mode"] == "monolith"
    assert env.tables()["generation_snapshots"] == []

    # The sweeper claims the deck as today.
    assert claim_due_marker(_due()) == (deck.owner, OWNER)


@pytest.mark.parametrize("actor", ["contributor", "owner"])
def test_restore_failed_snapshot_keeps_lock_and_refuses_manual_edit(api, actor):
    """A's generation failed and its restore failed (the request is ``error``; the
    snapshot ``restore_failed``).  Until the retry restores the deck, it stays locked
    to A: B cannot take the lock and B's manual edit is refused with 423 naming A.
    Once the retry has restored it, the normal rules apply again."""
    env = api.rb
    deck = shared_deck(env)
    sm = get_session_manager()
    a_sid, a_user = deck.of(actor)
    b_sid, b_user = deck.other(actor)
    assert sm.acquire_editing_lock(a_sid, a_user)["acquired"] is True
    rid = fail_restore(env, a_sid, deck.owner)
    lapse_heartbeat(env, deck.owner, a_user)
    before = env.tables()

    assert sm.acquire_editing_lock(b_sid, b_user) == {
        "acquired": False,
        "locked_by": NAMES[a_user],
    }
    with as_user(b_user), pytest.raises(PermissionError) as refused:
        sm.require_editing_lock(b_sid)
    assert str(refused.value) == locked_by(a_user)
    _assert_tables_equal(before, env.tables())
    assert sm.get_editing_lock_status(b_sid) == _status(a_user)

    if b_user == OWNER:
        # The owner's WYSIWYG edit, through the real route (the owner's session
        # lock is free: the failed turn kept the CONTRIBUTOR's session locked).
        _assert_lock(env, deck.owner, held_by=None)
        before_edit = env.tables()
        api.sign_in(OWNER)
        resp = api.edit_slide(deck.owner, 0, MANUAL_EDIT)
        assert resp.status_code == 423, (resp.status_code, resp.text)
        assert resp.json() == {"detail": locked_by(a_user)}
        _assert_tables_equal(before_edit, env.tables())

    # The recovery sweep's retry restores the deck; the lock is free again.
    assert recover_orphaned_generations() == 1
    assert env.snapshot_rows(rid) == []
    assert sm.acquire_editing_lock(b_sid, b_user) == {
        "acquired": True,
        "locked_by": NAMES[b_user],
    }


# ---------------------------------------------------------------------------
# The deck owner's chat route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("live", ["pending", "running"])
@pytest.mark.parametrize("heartbeat", ["fresh", "lapsed"])
def test_owner_chat_refused_423_while_contributor_generation_live(api, live, heartbeat):
    """A contributor's generation is live on the shared Agent deck.  The owner's
    own chat route used to return early for the root owner; now it answers 423
    naming the contributor, and writes nothing."""
    env = api.rb
    deck = shared_deck(env)
    sm = get_session_manager()
    assert sm.acquire_editing_lock(deck.contributor, CONTRIBUTOR)["acquired"] is True
    start_generation(env, deck.contributor, live)
    if heartbeat == "lapsed":
        lapse_heartbeat(env, deck.owner, CONTRIBUTOR)
    before = env.tables()

    resp = api.submit(deck.owner)

    assert resp.status_code == 423, (resp.status_code, resp.text)
    assert resp.json() == {"detail": locked_by(CONTRIBUTOR)}
    api.enqueued.assert_not_awaited()
    _assert_tables_equal(before, env.tables())
    _assert_lock(env, deck.owner, held_by=None)


@pytest.mark.parametrize(
    "case", ["no_generation", "own_generation_live", "own_restore_pending"]
)
def test_owner_chat_allowed_on_unshared_deck(api, case):
    """Guard.  On an unshared deck nobody else can hold it: the owner's chat is
    never 423.  The owner's own live generation is not "someone else" (the session
    lock answers, as today), nor is the owner's own failed restore (the
    restore-pending 409, as today)."""
    env = api.rb
    sm = get_session_manager()
    sid = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, sid)
    assert sm.acquire_editing_lock(sid, OWNER)["acquired"] is True

    if case == "no_generation":
        rid = api.submit_ok(sid)
        assert api.payload(rid)["engine_mode"] == "graph"
        assert [s["state"] for s in env.snapshot_rows(rid)] == ["active"]
        _assert_lock(env, sid, held_by=rid)
        return

    if case == "own_generation_live":
        rid0 = press_enter(env, sid)
        lapse_heartbeat(env, sid, OWNER)
        expected = {"detail": SESSION_BUSY}
    else:
        rid0 = fail_restore(env, sid, sid)
        lapse_heartbeat(env, sid, OWNER)
        # Time passed: the failed turn's session lock went stale (nothing refreshes it).
        backdate_session_lock(env, sid)
        expected = {"detail": RESTORE_PENDING}

    resp = api.submit(sid)

    assert resp.status_code == 409, (resp.status_code, resp.text)
    assert resp.json() == expected
    api.enqueued.assert_not_awaited()
    assert env.snapshot_rows(rid0) != [], "the owner's own generation lost its snapshot"


@pytest.mark.parametrize("deck_mode", ["agent", "legacy"])
def test_owner_chat_allowed_while_contributor_holds_idle_heartbeat_lock(api, deck_mode):
    """Guard.  An ordinary heartbeat lock held by an idle contributor (no
    generation) never blocks the owner's chat, on an Agent deck or a Legacy one:
    the owner's route must not call ``require_editing_lock``.  The contributor's
    lock row is left exactly as it was."""
    env = api.rb
    deck = shared_deck(env, legacy=deck_mode == "legacy")
    sm = get_session_manager()
    assert sm.acquire_editing_lock(deck.contributor, CONTRIBUTOR) == {
        "acquired": True,
        "locked_by": NAMES[CONTRIBUTOR],
    }
    lock_before = _lock_columns(env, deck.owner)
    assert lock_before[0] == CONTRIBUTOR

    rid = api.submit_ok(deck.owner)

    if deck_mode == "agent":
        assert api.payload(rid)["engine_mode"] == "graph"
        assert [s["state"] for s in env.snapshot_rows(rid)] == ["active"]
    else:
        assert api.payload(rid)["engine_mode"] == "monolith"
        assert env.tables()["generation_snapshots"] == []
    assert _lock_columns(env, deck.owner) == lock_before
    _assert_lock(env, deck.owner, held_by=rid)


@pytest.mark.parametrize(
    "path,gated",
    [("/api/chat", False), ("/api/chat/stream", False), ("/api/chat/async", True)],
)
def test_owner_gate_applies_only_to_the_async_route(api, monkeypatch, path, gated):
    """The 423 owner gate is the deployed transport's alone: with a contributor's
    Agent generation live, the OWNER's ``/api/chat/async`` is refused 423 while the
    sync ``/api/chat`` and the SSE ``/api/chat/stream`` are not (their behaviour is
    unchanged).  The chat service is stubbed, so the ungated routes just run."""
    env = api.rb
    deck = shared_deck(env)
    start_generation(env, deck.contributor, "running")
    service = MagicMock()
    service.send_message.return_value = {}
    service.send_message_streaming.return_value = iter(())
    monkeypatch.setattr("src.api.routes.chat.get_chat_service", lambda: service)

    resp = api.client.post(path, json={"session_id": deck.owner, "message": OWNER_MESSAGE})

    if gated:
        assert resp.status_code == 423, (resp.status_code, resp.text)
        assert resp.json() == {"detail": locked_by(CONTRIBUTOR)}
    else:
        assert resp.status_code != 423, (resp.status_code, resp.text)
        assert resp.status_code in (200, 500), (resp.status_code, resp.text)
        assert (service.send_message.called or service.send_message_streaming.called)


@pytest.mark.parametrize(
    "case,busy,live_busy",
    [("none", False, False), ("live", True, True), ("restore_failed", True, False)],
)
def test_busy_deck_rule_is_one_rule_for_lock_and_sweeper(env, case, busy, live_busy):
    """Divergence guard.  The lock's holder lookup and the sweeper's claim agree on
    whether the deck is busy: a live generation and a ``restore_failed`` snapshot
    hold it in BOTH, an idle deck in neither.  ``live_only`` (the owner's chat gate)
    ignores ``restore_failed``."""
    sm = get_session_manager()
    deck = shared_deck(env)
    if case == "live":
        start_generation(env, deck.contributor, "running")
    elif case == "restore_failed":
        fail_restore(env, deck.contributor, deck.owner)
    assert mark_dirty(deck.owner, OWNER) is True

    claimed = claim_due_marker(_due())

    assert (sm.live_generation_holder(deck.owner) is not None) == busy
    assert (claimed is None) == busy
    assert (sm.live_generation_holder(deck.owner, live_only=True) is not None) == live_busy


# ---------------------------------------------------------------------------
# The arc-review sweeper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("live", ["pending", "running"])
@pytest.mark.parametrize("actor", ["owner", "contributor"])
def test_sweeper_skips_deck_with_live_generation(env, actor, live):
    """A human's edit marked the deck; then a generation started on it.  The
    sweeper does not claim it while the generation is live (the marker is kept
    exactly as it was), and claims it once the generation has ended."""
    deck = shared_deck(env)
    assert mark_dirty(deck.owner, OWNER) is True
    a_sid, _ = deck.of(actor)
    rid = start_generation(env, a_sid, live)
    due = _due()
    marker_before = _marker(env.deck_row(deck.owner))
    assert marker_before[2] is None, "precondition: the marker is unclaimed"
    before = env.tables()

    assert claim_due_marker(due) is None
    _assert_tables_equal(before, env.tables())

    if live == "pending":
        # The job picks the request up, then the turn completes.
        with get_db_session() as db:
            assert start_chat_request(db, rid)
    end_generation(env, rid, a_sid, "completed")
    assert claim_due_marker(due) == (deck.owner, OWNER)
    assert _marker(env.deck_row(deck.owner)) == (marker_before[0], marker_before[1], due), (
        "the marker was not kept for the claim"
    )


def test_live_generation_deck_does_not_block_other_due_decks(env):
    """The deck with the OLDEST due marker -- the one today's query picks -- is
    busy generating.  The sweeper claims the next due deck instead (the live-
    generation rule is inside the candidate selection, not a check after it), and
    the busy deck's marker waits for the generation to end."""
    busy = shared_deck(env)
    quiet = env.new_session(created_by=STRANGER, title="MK-QUIET-TITLE")
    seed_earlier_turn(env, quiet)
    assert mark_dirty(busy.owner, OWNER) is True
    assert mark_dirty(quiet, STRANGER) is True
    assert env.deck_row(busy.owner)["spec_dirty_at"] < env.deck_row(quiet)["spec_dirty_at"], (
        "precondition: the busy deck's marker is the oldest, the one claimed first today"
    )
    rid = press_enter(env, busy.contributor)
    due = _due()
    busy_before = env.deck_row(busy.owner)

    assert claim_due_marker(due) == (quiet, STRANGER)
    assert env.deck_row(busy.owner) == busy_before
    assert claim_due_marker(due) is None, "the busy deck was claimed on the next tick"
    assert env.deck_row(busy.owner) == busy_before

    end_generation(env, rid, busy.contributor, "completed")
    assert claim_due_marker(due) == (busy.owner, OWNER)


@pytest.mark.parametrize("actor", ["owner", "contributor"])
def test_sweeper_skips_deck_with_restore_failed_snapshot(env, actor):
    """A failed restore keeps the deck locked to its sender although its request has
    ended: the sweeper skips that deck (the oldest marker) and claims the next one,
    and keeps skipping it."""
    failed = shared_deck(env)
    quiet = env.new_session(created_by=STRANGER, title="MK-QUIET-TITLE")
    seed_earlier_turn(env, quiet)
    assert mark_dirty(failed.owner, OWNER) is True
    assert mark_dirty(quiet, STRANGER) is True
    assert env.deck_row(failed.owner)["spec_dirty_at"] < env.deck_row(quiet)["spec_dirty_at"], (
        "precondition: the failed deck's marker is the oldest, the one claimed first today"
    )
    a_sid, _ = failed.of(actor)
    fail_restore(env, a_sid, failed.owner)
    due = _due()
    failed_before = env.deck_row(failed.owner)

    assert claim_due_marker(due) == (quiet, STRANGER)
    assert claim_due_marker(due) is None, "the deck with a failed restore was claimed"
    assert env.deck_row(failed.owner) == failed_before


# ---------------------------------------------------------------------------
# One generation per deck, checked under the deck lock (final review B1)
# ---------------------------------------------------------------------------

#: ``begin_generation``'s refusal reason for "another generation is live on this deck".
GENERATION_IN_FLIGHT = "generation_in_flight"


def _deck_for(env: RollbackEnv, start: str) -> SharedDeck:
    """A shared Agent deck: with an earlier turn's deck row (``edit``), or none yet
    (``first_generation``: nothing to lock but the owner's session row)."""
    if start == "edit":
        return shared_deck(env)
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    return SharedDeck(owner, env.contributor(owner))


def grant_contributor_edit(monkeypatch) -> None:
    """The contributor holds CAN_EDIT on the deck (permission is not under test; the
    route's editing-lock check still runs for real)."""
    from src.core.permission_context import PermissionContext
    from src.database.models.profile_contributor import PermissionLevel

    monkeypatch.setattr(
        "src.api.routes.chat.get_permission_context",
        lambda: PermissionContext(user_id="contributor-id", user_name=CONTRIBUTOR),
    )
    service = MagicMock()
    service.get_deck_permission.return_value = PermissionLevel.CAN_EDIT
    monkeypatch.setattr("src.api.routes.chat.get_permission_service", lambda: service)


@pytest.mark.parametrize("start", ["edit", "first_generation"])
@pytest.mark.parametrize("first", ["owner", "contributor"])
def test_begin_generation_refuses_while_another_generation_is_live(env, first, start):
    """Two people pressed Enter on one deck inside the window before either
    snapshot existed, so both passed the route's holder checks.  Under the deck
    lock, ``begin_generation`` refuses the second Enter -- naming the first's
    sender -- and writes nothing.  Once the first generation has ended, the same
    Enter is accepted."""
    from src.api.services.session_manager import GenerationRefusedError

    deck = _deck_for(env, start)
    sm = get_session_manager()
    a_sid, a_user = deck.of(first)
    b_sid, _ = deck.other(first)
    rid_a = press_enter(env, a_sid)
    assert sm.acquire_session_lock(b_sid)
    rid_b = sm.create_chat_request(b_sid)
    sm.bind_session_lock(b_sid, rid_b)
    before = env.tables()

    with pytest.raises(GenerationRefusedError) as refused:
        sm.begin_generation(b_sid, rid_b)

    assert refused.value.reason == GENERATION_IN_FLIGHT
    assert refused.value.holder == a_user
    _assert_tables_equal(before, env.tables())
    assert env.snapshot_rows(rid_b) == []
    assert [s["state"] for s in env.snapshot_rows(rid_a)] == ["active"]

    end_generation(env, rid_a, a_sid, "completed")
    sm.begin_generation(b_sid, rid_b)
    assert [s["state"] for s in env.snapshot_rows(rid_b)] == ["active"]


@pytest.mark.parametrize("start", ["edit", "first_generation"])
@pytest.mark.parametrize("first", ["owner", "contributor"])
def test_enter_raced_past_the_route_check_is_refused_423(api, monkeypatch, first, start):
    """The race, through the real route: B's ``POST /api/chat/async`` passes its
    holder check (no snapshot yet), and A's Enter commits its snapshot before B's
    reaches ``begin_generation``.  B is answered 423 ``Session is locked by <A>``,
    B's request is ended ``error`` and B's session lock given back; nothing of B's
    is snapshotted, saved or queued, and A's generation is untouched."""
    env = api.rb
    deck = _deck_for(env, start)
    grant_contributor_edit(monkeypatch)
    sm = get_session_manager()
    a_sid, a_user = deck.of(first)
    b_sid, b_user = deck.other(first)
    raced: Dict[str, str] = {}
    real_get_deck_mode = sm.get_deck_mode
    earlier = {r["request_id"] for r in env.tables()["chat_requests"]}

    def get_deck_mode_after_a_entered(session_id: str):
        # The route reads the deck mode after its holder check and right before
        # begin_generation: A's Enter lands exactly in that window.
        if session_id == b_sid and not raced:
            with as_user(a_user):
                raced["rid"] = press_enter(env, a_sid)
        return real_get_deck_mode(session_id)

    monkeypatch.setattr(sm, "get_deck_mode", get_deck_mode_after_a_entered)
    api.sign_in(b_user)

    resp = api.submit(b_sid)

    assert raced, "the route never read the deck mode; the race was not staged"
    assert resp.status_code == 423, (resp.status_code, resp.text)
    assert resp.json() == {"detail": locked_by(a_user)}
    api.enqueued.assert_not_awaited()
    after = env.tables()
    b_requests = [
        r
        for r in after["chat_requests"]
        if r["session_id"] == env.pk(b_sid) and r["request_id"] not in earlier
    ]
    assert len(b_requests) == 1
    refused = b_requests[0]
    assert (refused["status"], refused["rollback_outcome"]) == ("error", None)
    assert env.snapshot_rows(refused["request_id"]) == []
    assert [
        m for m in after["session_messages"] if m["request_id"] == refused["request_id"]
    ] == [], "the refused Enter saved its user message"
    _assert_lock(env, b_sid, held_by=None)
    assert [s["state"] for s in env.snapshot_rows(raced["rid"])] == ["active"]
    _assert_lock(env, a_sid, held_by=raced["rid"])
