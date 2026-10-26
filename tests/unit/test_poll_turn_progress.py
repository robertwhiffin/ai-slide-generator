"""The polling transport serves a graph turn's stage summary (#319, Task 4).

``GET /api/chat/poll/{request_id}`` gains one key, ``turn_progress``: the
snapshot ``SessionManager.get_chat_request`` reads off the request's row.

Covers:
- A running or pending request serves whatever snapshot its row holds (or
  ``None`` when it holds none yet).
- A request that reached a terminal status (``completed`` / ``error``) serves
  ``None`` even though its row still holds the last snapshot, so a finished turn
  never shows a stale stage (D13).
- A monolith turn never writes a snapshot, so it serves ``None``.
- The snapshot travels in its own key, never as an element of ``events`` (the
  transcript-derived list).
- The value comes from the database row, not from anything held in the process
  or on a ``SessionManager`` instance: a poll served by a fresh manager over its
  own engine returns what another manager recorded.

The creator-only gate needs no new test here.  ``tests/unit/test_authz_chat_poll.py``
already proves the gate runs before ``get_chat_request``, which is the only
source of ``turn_progress`` (D15).
"""

import contextlib
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.services.session_manager import SessionManager
from tests.unit.conftest_graph import graph_env_threadsafe  # noqa: F401 — fixture

#: A valid snapshot, shaped as ``TurnProgress.snapshot()`` builds it.
SNAP = {
    "seq": 7,
    "phase": "building",
    "slides": {
        "total": 3,
        "building": [2],
        "reviewing": [1],
        "fixing": [],
        "done": [0],
    },
}


# ---------------------------------------------------------------------------
# Fixtures (pattern: tests/unit/test_slide_release.py, the polling route)
# ---------------------------------------------------------------------------


@pytest.fixture
def poll_client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def poll_manager(monkeypatch):
    manager = MagicMock()
    manager.get_session_id_for_request.return_value = "sess-poll"
    manager.get_chat_request.return_value = {
        "status": "processing",
        "result": None,
        "error_message": None,
    }
    manager.get_messages_for_request.return_value = []
    manager.slides_since_cursor.return_value = []
    manager.slide_revisions_since.return_value = []
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: manager)
    monkeypatch.setattr(
        "src.api.routes.chat._require_chat_request_owner", MagicMock()
    )
    return manager


def _request(status: str, turn_progress, error_message=None) -> dict:
    """The fields of ``get_chat_request``'s dict that ``poll_chat`` reads."""
    return {
        "status": status,
        "result": None,
        "error_message": error_message,
        "turn_progress": turn_progress,
    }


def _poll(client) -> dict:
    response = client.get("/api/chat/poll/req-1")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


def test_a_running_request_serves_its_latest_snapshot(poll_client, poll_manager):
    poll_manager.get_chat_request.return_value = _request("running", SNAP)

    body = _poll(poll_client)

    assert body["status"] == "running"
    assert body["turn_progress"] == SNAP


def test_a_pending_request_serves_whatever_it_holds(poll_client, poll_manager):
    """A queued request has written nothing yet; once its row holds a snapshot
    (a report can land before the status flips to running) it is served."""
    poll_manager.get_chat_request.return_value = _request("pending", None)
    assert _poll(poll_client)["turn_progress"] is None

    poll_manager.get_chat_request.return_value = _request("pending", SNAP)
    assert _poll(poll_client)["turn_progress"] == SNAP


@pytest.mark.parametrize(
    ("status", "error_message"),
    [("completed", None), ("error", "The turn failed.")],
)
def test_a_finished_request_never_serves_a_stale_snapshot(
    poll_client, poll_manager, status, error_message
):
    """The row keeps its last snapshot after the turn ends; the poll must not
    serve it, or the next poll shows "Reviewing slide 3..." on a finished turn."""
    poll_manager.get_chat_request.return_value = _request(
        status, SNAP, error_message=error_message
    )

    body = _poll(poll_client)

    assert body["status"] == status
    assert "turn_progress" in body
    assert body["turn_progress"] is None


def test_a_monolith_request_serves_no_stage(poll_client, poll_manager):
    """The monolith engine never calls ``record_chat_request_progress``."""
    poll_manager.get_chat_request.return_value = _request("running", None)

    body = _poll(poll_client)

    assert "turn_progress" in body
    assert body["turn_progress"] is None


def test_stage_progress_never_enters_the_events_list(poll_client, poll_manager):
    """``events`` is derived from the transcript only; the snapshot has its own key."""
    poll_manager.get_chat_request.return_value = _request("running", SNAP)
    poll_manager.get_messages_for_request.return_value = [
        {
            "id": 11,
            "role": "assistant",
            "content": "Building 3 slides.",
            "message_type": "llm_response",
            "created_at": "2026-10-19T09:00:00",
            "metadata": None,
        }
    ]
    # The real converter, so ``events`` is exactly what the transcript yields.
    poll_manager.msg_to_stream_event.side_effect = SessionManager().msg_to_stream_event

    body = _poll(poll_client)

    assert body["turn_progress"] == SNAP
    assert body["events"] == [
        {
            "type": "assistant",
            "content": "Building 3 slides.",
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "message_id": 11,
            # #321: every event carries `metadata`, null except on a failure notice.
            "metadata": None,
        }
    ]
    assert not [e for e in body["events"] if e.get("type") == "turn_progress"]


# ---------------------------------------------------------------------------
# Any worker serves the same value
# ---------------------------------------------------------------------------


def _db_session_on(engine):
    """A ``get_db_session`` stand-in over *engine* (commit on exit, rollback on raise)."""
    factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )

    @contextlib.contextmanager
    def _cm():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


def test_a_poll_on_another_manager_serves_the_snapshot_this_one_recorded(
    graph_env_threadsafe, poll_client, monkeypatch  # noqa: F811 — fixture
):
    """The worker running the turn records the snapshot; a poll that lands on a
    different worker must still serve it.

    The writer is one ``SessionManager`` on the fixture's engine.  The poll is
    then served with every ``get_chat_request`` call on a brand-new
    ``SessionManager`` over a second engine (its own connection pool) on the
    same database file, so the only thing the two share is the row.  A route
    that served the in-process tracker, or a manager that cached the snapshot on
    itself, returns ``None`` here.

    File-backed SQLite (``graph_env_threadsafe``) because ``poll_chat`` runs
    every read in ``asyncio.to_thread``: an in-memory database is empty on any
    thread but the one that created it.  A module-level cache in the same
    process is out of reach of any in-process test; Task 5's cross-process read
    covers that.
    """
    env = graph_env_threadsafe
    writer = SessionManager()
    request_id = writer.create_chat_request(env.session_id, "owner@example.com")
    writer.update_chat_request_status(request_id, "running")
    assert writer.record_chat_request_progress(request_id, SNAP["seq"], SNAP) is True

    reader_engine = create_engine(
        env.engine.url, connect_args={"check_same_thread": False}
    )
    try:
        monkeypatch.setattr(
            "src.api.services.session_manager.get_db_session",
            _db_session_on(reader_engine),
        )
        monkeypatch.setattr(
            "src.api.routes.chat.get_session_manager", lambda: SessionManager()
        )
        monkeypatch.setattr(
            "src.api.routes.chat._require_chat_request_owner", MagicMock()
        )

        response = poll_client.get(f"/api/chat/poll/{request_id}")
    finally:
        reader_engine.dispose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["turn_progress"] == SNAP
