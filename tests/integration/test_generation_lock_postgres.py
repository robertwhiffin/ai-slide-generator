"""Task 7 on real PostgreSQL: an Agent-deck Enter and the arc-review sweeper's claim
serialise on the deck owner's ``session_slide_decks`` row.

The submit (``begin_generation``, Task 5) takes ``SELECT … FOR UPDATE`` on the
owner's deck row before its ``review_in_flight`` check and its snapshot.  The
sweeper's ``claim_due_marker`` (Task 7) selects its candidate, takes the same row
lock, re-checks "no live generation, no ``restore_failed`` snapshot" as its own
statement, then claims.  So exactly one of two things happens, never both:

* the sweeper claims first, and the submit -- queued on the row lock -- sees the
  live claim and is refused with the arc-review-busy 409, or
* the submit snapshots first, and the sweeper -- queued on the row lock -- sees the
  committed snapshot of a live request and skips the deck.

Under READ COMMITTED a subquery inside the claim's ``UPDATE`` alone is not enough:
the ``UPDATE`` waits on the submit's row lock, then re-evaluates only its own row
against the committed version (EvalPlanQual), never the subquery, so it claims a
deck whose snapshot committed while it waited.  That is today's behaviour, and the
``submit_first`` case is red on it.

Each case parks the first party's transaction at a chosen statement (an
``after_cursor_execute`` hook on a ``threading.Event``), starts the second,
OBSERVES the second waiting on the first's backend (``pg_blocking_pids``) -- or
already finished without waiting -- and only then lets the first commit.  Nothing
is ordered by sleeping.  Self-skips when no PostgreSQL is reachable
(``postgres_engine``).
"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from src.api.schemas.requests import ChatRequest as ChatRequestBody
from src.core.user_context import set_current_user
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from src.services.spec_sync import DEBOUNCE_SECONDS, claim_due_marker, mark_dirty
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS
from tests.integration.test_generation_rollback_postgres import (
    _anyone_waiting_on,
    _observer,
    _Runner,
    _until,
)
from tests.unit.test_generation_rollback import (
    OWNER,
    RollbackEnv,
    _assert_lock,
    build_env,
    seed_earlier_turn,
)

pytestmark = pytest.mark.postgres

#: Global Constraints copy, exact.
ARC_REVIEW_BUSY = "This deck is being updated in the background. Try again in a few seconds."

#: The sweeper's claim: whatever its shape, it is an UPDATE of the deck row that
#: sets ``spec_dirty_claimed_at``; the row lock is held from there to its commit.
_CLAIM_UPDATE = re.compile(
    r"^\s*UPDATE\s+session_slide_decks\s+SET\b.*\bspec_dirty_claimed_at\s*=",
    re.IGNORECASE | re.DOTALL,
)
#: The submit's snapshot, written under the deck-row lock ``begin_generation`` took.
_SNAPSHOT_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+[\"`]?generation_snapshots\b", re.IGNORECASE)

USER_MESSAGE = "MK-USER add a slide"


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


@pytest.fixture
def pg_env(postgres_engine, monkeypatch) -> RollbackEnv:
    return build_env(postgres_engine, monkeypatch)


def _submit_as_owner(env: RollbackEnv, session_id: str) -> Dict[str, Any]:
    """``POST /api/chat/async`` as the deck owner: the real route function, with
    the real ``_check_chat_permission`` and a real ``get_db`` session."""
    from src.api.routes import chat as chat_routes

    async def call():
        set_current_user(OWNER)
        db = env.factory()
        try:
            return await chat_routes.submit_chat_async(
                ChatRequestBody(session_id=session_id, message=USER_MESSAGE), db=db
            )
        finally:
            db.close()

    return asyncio.run(call())


@pytest.mark.parametrize("first", ["sweeper_first", "submit_first"])
def test_submit_and_sweeper_claim_serialise(pg_env, postgres_engine, monkeypatch, first):
    env = pg_env
    from src.api.routes import chat as chat_routes

    enqueued = AsyncMock()
    monkeypatch.setattr(chat_routes, "enqueue_job", enqueued)

    sid = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, sid)
    assert mark_dirty(sid, OWNER) is True
    due = datetime.utcnow() + timedelta(seconds=DEBOUNCE_SECONDS + 1)
    deck_before = env.deck_row(sid)
    assert deck_before["spec_dirty_claimed_at"] is None
    assert env.tables()["generation_snapshots"] == []

    observer = _observer(postgres_engine)
    parked = threading.Event()
    release = threading.Event()
    holder: Dict[str, int] = {}

    def hook(conn, cursor, statement, parameters, context, executemany):
        if parked.is_set():
            return
        if first == "sweeper_first":
            hit = threading.current_thread().name == "sweeper" and _CLAIM_UPDATE.match(statement)
        else:
            # The submit's DB work runs on asyncio.to_thread workers; only it
            # writes a snapshot here.
            hit = _SNAPSHOT_INSERT.match(statement)
        if hit:
            holder["pid"] = cursor.connection.get_backend_pid()
            parked.set()
            if not release.wait(_WAIT_SECONDS):
                raise AssertionError("the parked transaction was never released")

    sweeper = _Runner("sweeper", lambda: claim_due_marker(due))
    submit = _Runner("submit", lambda: _submit_as_owner(env, sid))
    leader, follower = (sweeper, submit) if first == "sweeper_first" else (submit, sweeper)

    event.listen(postgres_engine, "after_cursor_execute", hook)
    try:
        leader.start()
        _until(lambda: parked.is_set() or leader.done.is_set())
        assert parked.is_set(), (
            f"the {leader.name} never reached its write under the deck-row lock: "
            f"result={leader.result!r} error={leader.error!r}"
        )
        follower.start()
        overlapped = _until(
            lambda: follower.done.is_set() or _anyone_waiting_on(observer, holder["pid"])
        )
        assert overlapped, (
            f"the {follower.name} neither waited on the {leader.name}'s transaction nor finished"
        )
        assert not leader.done.is_set(), f"the {leader.name} was not still inside its transaction"
    finally:
        release.set()
        for runner in (leader, follower):
            if runner.ident is not None:
                runner.join(_WAIT_SECONDS)
        event.remove(postgres_engine, "after_cursor_execute", hook)
        observer.dispose()

    assert not sweeper.is_alive() and not submit.is_alive(), "a party never finished"
    assert sweeper.error is None, f"the sweeper raised: {sweeper.error!r}"
    assert submit.error is None or isinstance(submit.error, HTTPException), (
        f"the submit raised: {submit.error!r}"
    )

    after = env.tables()
    claimed = sweeper.result is not None
    snapshotted = after["generation_snapshots"] != []
    assert not (claimed and snapshotted), (
        "BOTH happened: the sweeper claimed the deck for an arc review AND the submit "
        f"snapshotted a generation on it (claim={sweeper.result!r}, "
        f"snapshots={[(s['request_id'], s['state']) for s in after['generation_snapshots']]})"
    )
    assert claimed or snapshotted, "neither the claim nor the generation happened"

    requests = [r for r in after["chat_requests"] if r["session_id"] == env.pk(sid)]
    rid = requests[-1]["request_id"]

    if first == "sweeper_first":
        assert sweeper.result == (sid, OWNER)
        assert env.deck_row(sid)["spec_dirty_claimed_at"] == due
        assert isinstance(submit.error, HTTPException), (
            f"the submit was accepted under a live arc-review claim: {submit.result!r}"
        )
        assert (submit.error.status_code, submit.error.detail) == (409, ARC_REVIEW_BUSY)
        enqueued.assert_not_awaited()
        assert after["generation_snapshots"] == []
        refused = env.request_row(rid)
        assert (refused["status"], refused["rollback_outcome"]) == ("error", None)
        _assert_lock(env, sid, held_by=None)
    else:
        assert submit.error is None, f"the submit was refused: {submit.error!r}"
        assert submit.result == {"request_id": rid, "status": "pending"}
        assert [(s["request_id"], s["state"]) for s in after["generation_snapshots"]] == [
            (rid, "active")
        ]
        assert enqueued.await_count == 1
        assert sweeper.result is None, (
            f"the sweeper claimed a deck whose generation snapshot committed while it "
            f"waited: {sweeper.result!r}"
        )
        # The marker is kept, unclaimed, for after the generation.
        assert env.deck_row(sid) == deck_before
        _assert_lock(env, sid, held_by=rid)
