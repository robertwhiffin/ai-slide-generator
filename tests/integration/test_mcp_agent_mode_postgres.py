"""MCP turns go through the real Enter, on real PostgreSQL, and refused or failed
ones leave nothing behind.

What this proves
----------------
* ``create_deck`` makes an Agent deck (``deck_mode="agent"``, pinned to the active
  Graph Release) and enters its first turn through ``enter_chat_turn``, the Enter
  the async chat route uses: a ``pending`` request with a generation snapshot, the
  session lock bound to that request, the prompt saved verbatim as the one user
  message, and a graph job queued.
* A ``create_deck`` whose Enter fails after the session was made (the enqueue
  raises) answers a tool error and is rolled back: the request is ``error``, no
  snapshot and no user message survive, no live request holds the deck, and the
  session lock is free.  The empty Agent deck itself stays (PLAN-CORRECTIONS,
  Addendum Task 3).
* ``edit_deck`` on a Legacy deck is refused with the Legacy copy BEFORE Enter, so
  the whole database is unchanged: no request row, no message, no lock.
* ``edit_deck`` by the creator of a deck the app made (``graph_capable=True``,
  ``deck_mode`` not chosen yet) enters an Agent turn and locks the deck to Agent.

How
---
The real ``_create_deck_impl`` / ``_edit_deck_impl``, the real ``mcp_auth_scope``
(it binds ``current_user`` and the permission context), the real session manager,
snapshot, rollback, engine-mode resolver and permission service, all on a
throwaway PostgreSQL database (``postgres_engine``, routed by ``build_env``, which
also seeds an active Graph Release).  Only three seams are patched:

* ``src.api.mcp_auth.extract_mcp_identity`` returns a token-less identity for
  ``OWNER`` (C17): no workspace client, no group fetch;
* ``src.api.routes.chat.enqueue_job`` records ``(request_id, payload)``, or
  records and then raises;
* ``src.api.mcp_server._public_app_url`` returns ``""`` where error copy with a
  ``deck_url``, or the relative links a create/edit returns, is asserted (C12).

Every assertion reads the database (every row of every table, before and after)
or the real readers (``has_generation_snapshot``, ``live_generation_holder``,
``acquire_session_lock``).  Self-skips when no PostgreSQL is reachable.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from src.api.mcp_auth import MCPIdentity
from src.api.mcp_server import (
    MCP_LEGACY_DECK_ERROR,
    MCPToolError,
    _create_deck_impl,
    _edit_deck_impl,
)
from src.api.routes.chat import _maybe_create_session
from src.api.schemas.requests import ChatRequest as ChatRequestBody
from src.api.services.session_manager import get_session_manager
from src.core.user_context import set_current_user
from src.services.generation_fence import LIVE_STATUSES
from src.services.generation_rollback import has_generation_snapshot
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.unit.test_generation_rollback import (
    OWNER,
    RollbackEnv,
    _assert_lock,
    _assert_tables_equal,
    build_env,
)

pytestmark = pytest.mark.postgres

#: Leading/trailing whitespace and an inner newline, so "verbatim" means verbatim.
PROMPT = "  MK-PROMPT A five-slide deck on Lakebase.\nAudience: data engineers.  \n"
INSTRUCTION = "  MK-EDIT On slide 2, shorten the title.\nKeep the rest.  "
CORRELATION_ID = "mk-corr-7f3a"

#: The tables an Agent Enter writes: the lock and the deck-mode lock
#: (user_sessions), the request, the user message and the snapshot.  Every other
#: table must be byte-identical across a create or an edit.
_ENTER_TABLES = ("user_sessions", "chat_requests", "session_messages", "generation_snapshots")

#: create_deck / edit_deck's reply, in order: the deck's links first.
_SUBMIT_KEYS = ["deck_url", "deck_view_url", "session_id", "request_id", "status"]


# ---------------------------------------------------------------------------
# Fixtures and seams
# ---------------------------------------------------------------------------


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


@pytest.fixture(autouse=True)
def _mcp_caller_is_owner(monkeypatch) -> None:
    """The real ``mcp_auth_scope``, fed a token-less identity for OWNER (C17)."""
    monkeypatch.setattr(
        "src.api.mcp_auth.extract_mcp_identity",
        lambda request: MCPIdentity(
            user_id=None, user_name=OWNER, token=None, source="x-forwarded-identity"
        ),
    )


class _Enqueue:
    """Stands in for ``src.api.routes.chat.enqueue_job``: records, then maybe raises."""

    def __init__(self, fail: Optional[BaseException] = None) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.fail = fail

    async def __call__(self, request_id: str, payload: Dict[str, Any]) -> None:
        self.calls.append((request_id, payload))
        if self.fail is not None:
            raise self.fail


def _patch_enqueue(monkeypatch, fail: Optional[BaseException] = None) -> _Enqueue:
    recorder = _Enqueue(fail)
    monkeypatch.setattr("src.api.routes.chat.enqueue_job", recorder)
    return recorder


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _messages(tables, pk: int) -> List[Tuple[Any, ...]]:
    return [
        (m["role"], m["content"], m["message_type"], m["request_id"])
        for m in tables["session_messages"]
        if m["session_id"] == pk
    ]


def _requests(tables, pk: int) -> List[Dict[str, Any]]:
    return [r for r in tables["chat_requests"] if r["session_id"] == pk]


def _snapshot_at_enter(env: RollbackEnv, rid: str, pk: int) -> Dict[str, Any]:
    """The one active snapshot of *rid*, taken on *pk*'s own deck; its owner fields."""
    snaps = env.snapshot_rows(rid)
    assert [(s["state"], s["actor_session_pk"], s["owner_session_pk"]) for s in snaps] == [
        ("active", pk, pk)
    ], f"expected one active snapshot of the turn on its own deck, got {snaps}"
    return json.loads(snaps[0]["session_fields_json"])["owner"]


def _graph_payload(session_id: str, message: str) -> Dict[str, Any]:
    """The whole job payload of a first Agent turn entered over MCP: the turn's own
    keys over MCP's ``correlation_id``, ``engine_mode`` (never ``mode``)."""
    return {
        "correlation_id": CORRELATION_ID,
        "session_id": session_id,
        "message": message,
        "slide_context": None,
        "is_first_message": True,
        "image_ids": None,
        "engine_mode": "graph",
        "stage_slide": None,
    }


# ---------------------------------------------------------------------------
# create_deck
# ---------------------------------------------------------------------------


def test_create_deck_leaves_an_agent_deck_with_a_live_snapshotted_request(pg_env, monkeypatch):
    env = pg_env
    enqueue = _patch_enqueue(monkeypatch)
    monkeypatch.setattr("src.api.mcp_server._public_app_url", lambda: "")
    before = env.tables()

    result = asyncio.run(
        _create_deck_impl(request=None, prompt=PROMPT, correlation_id=CORRELATION_ID)
    )

    # The new deck's links come first (relative: no public app URL).
    assert list(result) == _SUBMIT_KEYS, result
    sid, rid = result["session_id"], result["request_id"]
    assert result["status"] == "pending"
    assert result["deck_url"] == f"/sessions/{sid}/edit"
    assert result["deck_view_url"] == f"/sessions/{sid}/view"
    after = env.tables()
    pk = env.pk(sid)

    # One new deck: the caller's, an Agent deck pinned to the active release.
    assert [r for r in after["user_sessions"] if r["session_id"] != sid] == before["user_sessions"]
    session = env.session_row(sid)
    assert session["created_by"] == OWNER
    assert session["deck_mode"] == "agent"
    assert session["graph_release_id"] == env.release_id

    # One live request, the tool's, holding a snapshot of the deck as it was at
    # Enter: already an Agent deck, already pinned (create_session, not Enter, did it).
    assert [r["request_id"] for r in _requests(after, pk)] == [rid]
    request = env.request_row(rid)
    assert (request["status"], request["rollback_outcome"], request["completed_at"]) == (
        "pending",
        None,
        None,
    )
    assert has_generation_snapshot(rid)
    assert _snapshot_at_enter(env, rid, pk) == {
        "deck_mode": "agent",
        "graph_release_id": env.release_id,
        "title": session["title"],
    }
    assert get_session_manager().live_generation_holder(sid, live_only=True) == OWNER

    # The session lock is bound to that request, so no second turn can start.
    _assert_lock(env, sid, held_by=rid)

    # The prompt, verbatim, is the session's one message, tagged with the request.
    assert _messages(after, pk) == [("user", PROMPT, "user_query", rid)]

    # One graph job, carrying the prompt verbatim.
    assert enqueue.calls == [(rid, _graph_payload(sid, PROMPT))]

    # Nothing else in the database moved.
    _assert_tables_equal(before, after, exclude=_ENTER_TABLES)
    assert get_session_manager().acquire_session_lock(sid) is False


def test_create_deck_enqueue_failure_leaves_no_lock_and_no_live_request(pg_env, monkeypatch):
    env = pg_env
    enqueue = _patch_enqueue(monkeypatch, fail=RuntimeError("MK-QUEUE-DOWN"))
    before = env.tables()

    with pytest.raises(MCPToolError) as raised:
        asyncio.run(
            _create_deck_impl(request=None, prompt=PROMPT, correlation_id=CORRELATION_ID)
        )

    # The generic tool error (_create_deck_impl's ``except Exception``).
    assert str(raised.value) == f"Internal error (correlation_id={CORRELATION_ID}): MK-QUEUE-DOWN"

    # Enter got as far as the queue, as a graph turn: the snapshot was taken, so
    # what follows is the rollback's work.  The ids come from the recorder.
    assert len(enqueue.calls) == 1
    rid, payload = enqueue.calls[0]
    sid = payload["session_id"]
    assert payload == _graph_payload(sid, PROMPT)
    after = env.tables()
    pk = env.pk(sid)

    # The request ended in error, by the rollback.
    assert [r["request_id"] for r in _requests(after, pk)] == [rid]
    request = env.request_row(rid)
    assert (request["status"], request["rollback_outcome"]) == ("error", "rolled_back")
    assert request["completed_at"] is not None
    assert [r for r in _requests(after, pk) if r["status"] in LIVE_STATUSES] == []

    # No snapshot survives, and nothing holds the deck.
    assert not has_generation_snapshot(rid)
    assert after["generation_snapshots"] == before["generation_snapshots"] == []
    assert get_session_manager().live_generation_holder(sid) is None

    # The rolled-back user message is gone.
    assert _messages(after, pk) == []

    # The session lock is free.
    _assert_lock(env, sid, held_by=None)

    # What is left is the empty Agent deck create_session made, as it was at Enter.
    session = env.session_row(sid)
    assert (session["created_by"], session["deck_mode"], session["graph_release_id"]) == (
        OWNER,
        "agent",
        env.release_id,
    )
    assert [r for r in after["user_sessions"] if r["session_id"] != sid] == before["user_sessions"]
    _assert_tables_equal(before, after, exclude=("user_sessions", "chat_requests"))

    # A new turn can take the lock again.
    assert get_session_manager().acquire_session_lock(sid) is True


# ---------------------------------------------------------------------------
# edit_deck
# ---------------------------------------------------------------------------


def test_edit_deck_on_a_legacy_deck_writes_nothing(pg_env, monkeypatch):
    env = pg_env
    enqueue = _patch_enqueue(monkeypatch)
    monkeypatch.setattr("src.api.mcp_server._public_app_url", lambda: "")
    sm = get_session_manager()
    sid = sm.create_session(created_by=OWNER, deck_mode="legacy")["session_id"]
    # An earlier Legacy turn's message, so "unchanged" is not just "still empty".
    sm.add_user_message(
        sid, "MK-LEGACY an earlier message", message_type="user_query", requested_deck_mode="legacy"
    )
    pk = env.pk(sid)
    assert (env.session_row(sid)["deck_mode"], env.session_row(sid)["graph_release_id"]) == (
        "legacy",
        None,
    )
    before = env.tables()

    with pytest.raises(MCPToolError) as raised:
        asyncio.run(
            _edit_deck_impl(
                request=None,
                session_id=sid,
                instruction=INSTRUCTION,
                correlation_id=CORRELATION_ID,
            )
        )

    assert str(raised.value) == MCP_LEGACY_DECK_ERROR.format(deck_url=f"/sessions/{sid}/edit")
    after = env.tables()
    # The whole database, every row and column: no request, message, lock,
    # snapshot or last_activity bump.  Nothing is excluded: nothing may move.
    _assert_tables_equal(before, after)
    assert len(_requests(after, pk)) == len(_requests(before, pk))
    assert len(_messages(after, pk)) == len(_messages(before, pk))
    _assert_lock(env, sid, held_by=None)
    assert enqueue.calls == []


def test_edit_deck_on_an_app_made_agent_deck_enters(pg_env, monkeypatch):
    env = pg_env
    enqueue = _patch_enqueue(monkeypatch)
    monkeypatch.setattr("src.api.mcp_server._public_app_url", lambda: "")
    # The deck the app's New Deck makes: the route's own session creation, as its
    # creator, before any message (graph_capable=True, deck_mode not chosen).
    set_current_user(OWNER)
    try:
        body = ChatRequestBody(message="MK-unused: only the session is made here")
        assert _maybe_create_session(body, get_session_manager()) is True
    finally:
        set_current_user(None)
    sid = body.session_id
    pk = env.pk(sid)
    made = env.session_row(sid)
    assert (made["created_by"], made["deck_mode"], made["graph_release_id"]) == (
        OWNER,
        None,
        env.release_id,
    )
    before = env.tables()
    assert _messages(before, pk) == [] and _requests(before, pk) == []

    result = asyncio.run(
        _edit_deck_impl(
            request=None,
            session_id=sid,
            instruction=INSTRUCTION,
            correlation_id=CORRELATION_ID,
        )
    )

    assert len(enqueue.calls) == 1
    rid = enqueue.calls[0][0]
    assert list(result) == _SUBMIT_KEYS, result
    assert result == {
        "deck_url": f"/sessions/{sid}/edit",
        "deck_view_url": f"/sessions/{sid}/view",
        "session_id": sid,
        "request_id": rid,
        "status": "pending",
    }
    after = env.tables()

    # The deck is now locked to Agent, its pin unchanged.
    session = env.session_row(sid)
    assert (session["deck_mode"], session["graph_release_id"]) == ("agent", env.release_id)

    # A live request with a snapshot of the deck as it was at Enter (not chosen yet).
    assert [r["request_id"] for r in _requests(after, pk)] == [rid]
    request = env.request_row(rid)
    assert (request["status"], request["rollback_outcome"]) == ("pending", None)
    assert has_generation_snapshot(rid)
    assert _snapshot_at_enter(env, rid, pk) == {
        "deck_mode": None,
        "graph_release_id": env.release_id,
        "title": made["title"],
    }
    _assert_lock(env, sid, held_by=rid)

    # The instruction, verbatim, and a graph job.
    assert _messages(after, pk) == [("user", INSTRUCTION, "user_query", rid)]
    assert enqueue.calls == [(rid, _graph_payload(sid, INSTRUCTION))]

    _assert_tables_equal(before, after, exclude=_ENTER_TABLES)
    assert [r for r in after["user_sessions"] if r["session_id"] != sid] == [
        r for r in before["user_sessions"] if r["session_id"] != sid
    ]
