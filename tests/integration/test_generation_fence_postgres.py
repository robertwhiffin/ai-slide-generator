"""The fence and the rollback serialise on the request row, on real PostgreSQL.

``claim_turn_row`` is an ``UPDATE chat_requests SET status = status WHERE
request_id = :rid AND status IN ('pending', 'running')``.  On PostgreSQL that
UPDATE takes the row's lock and holds it to the end of the transaction, so:

1. **A writer that has passed the fence finishes first.**  The writer claims the
   row and writes; the rollback's own claim (followed by ``status='cancelled'``)
   blocks on the writer's row lock until the writer commits.  The restore that
   follows therefore sees the writer's committed write -- it cannot be undone and
   then land afterwards.
2. **A writer that arrives after the cancel is refused.**  The rollback claims and
   cancels; the writer's claim blocks on that lock, and when the rollback commits
   PostgreSQL re-checks the UPDATE's WHERE against the committed row (READ
   COMMITTED), finds ``cancelled``, matches nothing, and the fence raises.  A
   claim written as read-then-write would read ``running`` here and let the write
   through -- this is the test that catches that.

Ordering is proven, not slept on: the waiting connection is OBSERVED blocked by
the holder's backend (``pg_blocking_pids``) before the holder commits, its
``threading.Event`` is asserted still unset at that moment, and its claim's return
time is asserted later than the holder's commit start.

SQLite has a single writer and renders no row locks, so none of this can be
shown there.  Self-skips when no PostgreSQL is reachable (``postgres_engine``).
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Tuple

import pytest
from sqlalchemy import select, text

from src.database.models.session import ChatRequest, UserSession
from src.services.generation_fence import (
    TurnFencedError,
    claim_turn_row,
    fence_turn_write,
)
from tests.integration.conftest import _make_factory
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS, _await_blocked_by

pytestmark = pytest.mark.postgres

_TURN_TITLE = "written by the in-flight turn"
_LATE_TITLE = "written by a turn that was already cancelled"


def _seed_running_request(factory) -> Tuple[str, int]:
    """One owner session with one ``running`` request; returns (request_id, owner pk)."""
    rid = f"req-{uuid.uuid4().hex[:16]}"
    with factory() as db:
        owner = UserSession(
            session_id=f"pg-fence-{uuid.uuid4().hex[:12]}",
            created_by="fence-owner@example.com",
            title="original title",
        )
        db.add(owner)
        db.flush()
        db.add(ChatRequest(request_id=rid, session_id=owner.id, status="running"))
        db.commit()
        return rid, owner.id


def _request_row(factory, rid: str) -> Dict[str, Any]:
    table = ChatRequest.__table__
    with factory() as db:
        return dict(
            db.execute(select(table).where(table.c.request_id == rid)).mappings().one()
        )


def _title(factory, owner_pk: int) -> str:
    table = UserSession.__table__
    with factory() as db:
        return db.execute(select(table.c.title).where(table.c.id == owner_pk)).scalar_one()


def _pid(db) -> int:
    return db.execute(text("SELECT pg_backend_pid()")).scalar_one()


def test_rollback_claim_waits_for_in_flight_writer(postgres_engine):
    factory = _make_factory(postgres_engine)
    rid, owner_pk = _seed_running_request(factory)
    before = _request_row(factory, rid)

    b_ready = threading.Event()
    b_claimed = threading.Event()
    b_done = threading.Event()
    b_pid: List[int] = []
    b_claim_result: List[bool] = []
    errors: List[BaseException] = []
    stamps: Dict[str, float] = {}

    def rollback() -> None:
        """Connection B: the stop's claim, then the cancel, in one transaction."""
        db = factory()
        try:
            b_pid.append(_pid(db))
            b_ready.set()
            claimed = claim_turn_row(db, rid)  # must block behind A's row lock
            stamps["b_claim_returned"] = time.monotonic()
            b_claim_result.append(claimed)
            b_claimed.set()
            db.execute(
                text("UPDATE chat_requests SET status = 'cancelled' WHERE request_id = :rid"),
                {"rid": rid},
            )
            db.commit()
        except BaseException as exc:  # noqa: BLE001 -- recorded, asserted on
            errors.append(exc)
            db.rollback()
        finally:
            db.close()
            b_done.set()

    # Connection A: the turn's write transaction -- claim, write, hold open.
    writer = factory()
    thread = threading.Thread(target=rollback, name="rollback-B", daemon=True)
    try:
        a_pid = _pid(writer)
        assert claim_turn_row(writer, rid) is True
        writer.execute(
            text("UPDATE user_sessions SET title = :t WHERE id = :id"),
            {"t": _TURN_TITLE, "id": owner_pk},
        )

        thread.start()
        assert b_ready.wait(_WAIT_SECONDS), "the rollback thread never connected"
        assert _await_blocked_by(
            postgres_engine, waiter_pid=b_pid[0], blocker_pid=a_pid
        ), "the rollback's claim never waited on the writer's row lock"
        assert not b_claimed.is_set(), "the rollback's claim returned while the writer held the row"

        stamps["a_commit_started"] = time.monotonic()
        writer.commit()
    finally:
        writer.close()  # on a failed assertion this rolls A back and unblocks B

    assert b_done.wait(_WAIT_SECONDS), "the rollback never finished after the writer committed"
    thread.join(_WAIT_SECONDS)
    assert not errors, f"the rollback thread failed: {errors!r}"

    # B's claim ran only after A's commit began, and still matched: A's claim is
    # SET status = status, so the row was still ``running`` when B re-checked it.
    assert b_claim_result == [True]
    assert stamps["b_claim_returned"] > stamps["a_commit_started"]

    # The writer's write landed, and the request is cancelled.
    assert _title(factory, owner_pk) == _TURN_TITLE
    assert _request_row(factory, rid) == {**before, "status": "cancelled"}

    # A fresh claim is refused, and so is a fenced write.
    with factory() as db:
        assert claim_turn_row(db, rid) is False
        db.rollback()
    with factory() as db:
        with pytest.raises(TurnFencedError) as excinfo:
            fence_turn_write(db, rid)
        db.rollback()
    assert excinfo.value.request_id == rid
    assert _request_row(factory, rid) == {**before, "status": "cancelled"}


def test_writer_waiting_on_rollback_is_refused_after_it_commits(postgres_engine):
    factory = _make_factory(postgres_engine)
    rid, owner_pk = _seed_running_request(factory)
    before = _request_row(factory, rid)
    title_before = _title(factory, owner_pk)

    a_ready = threading.Event()
    a_returned = threading.Event()
    a_done = threading.Event()
    a_pid: List[int] = []
    outcome: List[object] = []  # the TurnFencedError, or "wrote"
    errors: List[BaseException] = []
    stamps: Dict[str, float] = {}

    def late_writer() -> None:
        """Connection A: a turn's fenced write arriving while the cancel is in flight."""
        db = factory()
        try:
            a_pid.append(_pid(db))
            a_ready.set()
            try:
                fence_turn_write(db, rid)  # must block behind B's row lock
            except TurnFencedError as exc:
                stamps["a_returned"] = time.monotonic()
                a_returned.set()
                outcome.append(exc)
                db.rollback()
                return
            stamps["a_returned"] = time.monotonic()
            a_returned.set()
            db.execute(
                text("UPDATE user_sessions SET title = :t WHERE id = :id"),
                {"t": _LATE_TITLE, "id": owner_pk},
            )
            db.commit()
            outcome.append("wrote")
        except BaseException as exc:  # noqa: BLE001 -- recorded, asserted on
            errors.append(exc)
            db.rollback()
        finally:
            db.close()
            a_done.set()

    # Connection B: the stop -- claim, cancel, hold open.
    stopper = factory()
    thread = threading.Thread(target=late_writer, name="late-writer-A", daemon=True)
    try:
        b_pid = _pid(stopper)
        assert claim_turn_row(stopper, rid) is True
        stopper.execute(
            text("UPDATE chat_requests SET status = 'cancelled' WHERE request_id = :rid"),
            {"rid": rid},
        )

        thread.start()
        assert a_ready.wait(_WAIT_SECONDS), "the writer thread never connected"
        assert _await_blocked_by(
            postgres_engine, waiter_pid=a_pid[0], blocker_pid=b_pid
        ), "the writer's fence never waited on the rollback's row lock"
        assert not a_returned.is_set(), "the writer's fence returned while the cancel was uncommitted"

        stamps["b_commit_started"] = time.monotonic()
        stopper.commit()
    finally:
        stopper.close()

    assert a_done.wait(_WAIT_SECONDS), "the writer never finished after the cancel committed"
    thread.join(_WAIT_SECONDS)
    assert not errors, f"the writer thread failed: {errors!r}"

    assert len(outcome) == 1
    assert isinstance(outcome[0], TurnFencedError), (
        f"a write that waited on the cancel was let through ({outcome[0]!r}); "
        "the claim did not re-check the status after the lock wait"
    )
    assert outcome[0].request_id == rid
    assert stamps["a_returned"] > stamps["b_commit_started"]

    assert _title(factory, owner_pk) == title_before
    assert _request_row(factory, rid) == {**before, "status": "cancelled"}
