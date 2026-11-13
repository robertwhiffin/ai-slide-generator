"""``process_chat_request``'s ``finally`` frees only the lock its own request holds.

The hazard (spec, "Unconditional lock release"): the job's ``finally`` calls
``release_session_lock(session_id)``, which frees the lock WHOEVER holds it.  After
a stop, the abandoned job's ``finally`` runs late, by which time the person may have
sent their next message.  It would then free the NEXT turn's lock.

The fix splits by engine:
* a **graph** job releases with its ``request_id``, so a lock now owned by a newer
  request is left alone;
* a **monolith** job (every MCP job: ``mcp_server.py`` acquires the lock and never
  binds a request id, and its payload carries no ``engine_mode`` key) keeps today's
  unconditional release.  A matched release there would never fire, and the lock
  would leak.

These drive the real ``process_chat_request`` with a REAL ``SessionManager`` over
a file-backed SQLite schema (``create_all`` + ``_run_migrations``).  The schema is
file-backed because the job runs its generator on the chat-job executor thread,
and an in-memory ``SingletonThreadPool`` engine would hand that thread a different,
empty database.  Only the chat service is stubbed.  Its ``send_message_streaming``
is a generator that yields one COMPLETE event, and for the r2 test it first hands
the lock to a newer request.

Lock state is set and changed with direct SQL, never with ``bind_session_lock``.
That keeps these tests about the job's ``finally`` (``test_session_lock_ownership``
covers bind and release), and lets the two "released as today" tests run against
today's code as regression guards.  No ``generation_snapshots`` row exists in any
test.
"""
from __future__ import annotations

import contextvars
import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 -- registers every model before create_all
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import job_queue
from src.api.services.session_manager import SessionManager
from src.core.database import Base, _run_migrations
from src.database.models.session import ChatRequest, UserSession

#: ``onupdate=datetime.utcnow`` -- any UPDATE of the row moves it; not the lock's contract.
_VOLATILE = ("last_activity",)


class _Env:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        self.sm = SessionManager()

    def new_session(self) -> str:
        sid = f"jq-{uuid.uuid4().hex[:12]}"
        with self.factory() as db:
            db.add(UserSession(session_id=sid, created_by="jq-owner@example.com"))
            db.commit()
        return sid

    def new_request(self, sid: str, request_id: str) -> None:
        """The request row ``create_chat_request`` would have made: ``pending``."""
        with self.factory() as db:
            owner = db.execute(
                select(UserSession.__table__.c.id).where(UserSession.__table__.c.session_id == sid)
            ).scalar_one()
            db.add(ChatRequest(request_id=request_id, session_id=owner, status="pending"))
            db.commit()

    def set_lock_owner(self, sid: str, request_id: Optional[str]) -> None:
        """Make the held lock *request_id*'s.

        This is the end state of bind, or of stop, release, acquire and bind.
        """
        table = UserSession.__table__
        with self.factory() as db:
            db.execute(
                update(table)
                .where(table.c.session_id == sid)
                .values(
                    is_processing=True,
                    processing_started_at=datetime.utcnow(),
                    processing_request_id=request_id,
                )
            )
            db.commit()

    def lock_row(self, sid: str) -> Dict[str, Any]:
        table = UserSession.__table__
        with self.engine.connect() as conn:
            row = conn.execute(select(table).where(table.c.session_id == sid)).mappings().one()
        return {k: v for k, v in row.items() if k not in _VOLATILE}

    def request_status(self, request_id: str) -> str:
        table = ChatRequest.__table__
        with self.engine.connect() as conn:
            return conn.execute(
                select(table.c.status).where(table.c.request_id == request_id)
            ).scalar_one()


class _StubChatService:
    """Stands in for ChatService: the turn's generator, with an optional mid-turn hook."""

    def __init__(self) -> None:
        self.during_turn = None  # callable run inside the generator, on the executor thread
        self.calls: List[Dict[str, Any]] = []

    def send_message_streaming(self, **kwargs) -> Iterator[StreamEvent]:
        self.calls.append(kwargs)
        if self.during_turn is not None:
            self.during_turn()
        yield StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})


@pytest.fixture
def env(monkeypatch) -> Iterator[tuple]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="tellr-jq-lock-")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    e = _Env(engine)
    chat = _StubChatService()

    monkeypatch.setattr("src.core.database.get_session_local", lambda: e.factory)
    job_queue.jobs.clear()
    job_queue.shutdown_chat_executor()
    try:
        with (
            patch("src.api.services.session_manager.get_session_manager", return_value=e.sm),
            patch("src.api.services.chat_service.get_chat_service", return_value=chat),
        ):
            yield e, chat
    finally:
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()
        engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _graph_payload(sid: str) -> dict:
    return {
        "session_id": sid,
        "message": "build",
        "slide_context": None,
        "is_first_message": True,
        "image_ids": None,
        "engine_mode": "graph",
        "_context": contextvars.copy_context(),
    }


def _monolith_payload(sid: str, shape: str) -> dict:
    payload = {
        "session_id": sid,
        "message": "build",
        "slide_context": None,
        "is_first_message": True,
        "image_ids": None,
        "_context": contextvars.copy_context(),
    }
    if shape == "explicit":
        payload["engine_mode"] = "monolith"
    else:  # mcp_server.py's enqueue payload: no engine_mode key, MCP's own `mode`
        payload["mode"] = "generate"
        payload["correlation_id"] = "corr-1"
    return payload


def _freed(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **row,
        "is_processing": False,
        "processing_started_at": None,
        "processing_request_id": None,
    }


@pytest.mark.asyncio
async def test_graph_job_release_only_frees_its_own_lock(env):
    e, chat = env
    sid = e.new_session()
    e.new_request(sid, "r1")
    e.new_request(sid, "r2")
    assert e.sm.acquire_session_lock(sid) is True
    e.set_lock_owner(sid, "r1")

    # Mid-turn, r1 is stopped and the person's next turn r2 takes and binds the
    # lock, all before r1's job reaches its finally.
    seen: Dict[str, Any] = {}

    def hand_lock_to_r2() -> None:
        e.set_lock_owner(sid, "r2")
        seen["r2_lock"] = e.lock_row(sid)

    chat.during_turn = hand_lock_to_r2

    await job_queue.process_chat_request("r1", _graph_payload(sid))

    assert len(chat.calls) == 1 and chat.calls[0]["engine_mode"] == "graph"
    assert seen["r2_lock"]["processing_request_id"] == "r2"
    after = e.lock_row(sid)
    assert after["is_processing"] is True, "r1's finally freed r2's lock"
    assert after["processing_request_id"] == "r2"
    assert after == seen["r2_lock"], "r1's finally changed r2's lock row"
    assert e.sm.acquire_session_lock(sid) is False, "r2's lock could be taken by a third turn"
    assert e.request_status("r1") == "completed"
    assert "r1" not in job_queue.jobs


@pytest.mark.asyncio
async def test_graph_job_releases_its_own_lock(env):
    e, chat = env
    sid = e.new_session()
    e.new_request(sid, "r1")
    assert e.sm.acquire_session_lock(sid) is True
    e.set_lock_owner(sid, "r1")
    held = e.lock_row(sid)

    await job_queue.process_chat_request("r1", _graph_payload(sid))

    assert len(chat.calls) == 1 and chat.calls[0]["engine_mode"] == "graph"
    assert e.lock_row(sid) == _freed(held), "a graph job did not release its own lock"
    assert e.request_status("r1") == "completed"
    assert "r1" not in job_queue.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["explicit", "mcp"], ids=["engine_mode=monolith", "mcp-payload"])
async def test_monolith_job_releases_unbound_lock(env, shape):
    """An MCP-style job: acquired, never bound.  Freed after the job, as today."""
    e, chat = env
    sid = e.new_session()
    e.new_request(sid, "r-mcp")
    assert e.sm.acquire_session_lock(sid) is True
    held = e.lock_row(sid)
    assert held["is_processing"] is True and held["processing_request_id"] is None

    await job_queue.process_chat_request("r-mcp", _monolith_payload(sid, shape))

    assert len(chat.calls) == 1 and chat.calls[0]["engine_mode"] == "monolith"
    assert e.lock_row(sid) == _freed(held), "a monolith job left its unbound lock held"
    assert e.request_status("r-mcp") == "completed"
    assert "r-mcp" not in job_queue.jobs
