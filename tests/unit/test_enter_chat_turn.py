"""``enter_chat_turn``: the async chat route's Enter, as one function (MCP on Agent mode, Task 1).

``submit_chat_async`` keeps its permission check, injection check and session
auto-create, then hands the rest of the turn's Enter to
``src.api.routes.chat.enter_chat_turn``, which runs today's steps in today's order:

    acquire_session_lock -> create_chat_request(current user) -> bind_session_lock
    -> get_deck_mode -> (graph) begin_generation -> get_session (message_count)
    -> add_user_message -> resolve_engine_mode_or_unavailable -> engine-race checks
    -> enqueue_job

and every cleanup today's ``except`` clauses do (lock release respecting
``keep_lock``, the chat request's error mark, rollback or discard) before it
re-raises.  It returns ``EnteredTurn(request_id, engine_mode)``.

Pinned here:

* a busy session raises ``SessionBusyError`` and writes nothing;
* an Agent turn snapshots BEFORE the user message and enqueues a graph job;
* the job payload is ``{**extra_payload, <core keys>}``: core keys always win;
* ``stage_slide`` reaches only a graph turn's payload (plan corrections C2);
* the chat request is created for ``get_current_user()`` (C3);
* an enqueue failure on a graph turn rolls the turn back, then releases the
  lock, and re-raises the SAME error; a rollback that did not restore (or could
  not run) keeps the lock (C1);
* ``DeckModeLockedError`` drops the snapshot (no rollback), marks the request
  ``deck_mode_locked``, releases the lock and propagates.

The names under test are resolved from the ``src.api.routes.chat`` namespace at
call time, so every collaborator is patched THERE: ``get_session_manager``,
``enqueue_job``, ``resolve_engine_mode_or_unavailable``, ``get_current_user`` and
``roll_back_generation``.  The session manager is an autospec of the real
``SessionManager`` (a ``MagicMock`` that enforces the real method signatures, so
argument assertions hold whether a value was passed by position or keyword).
One parent ``Mock`` records the call order across all of them.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, create_autospec, patch

import pytest

from src.api.routes.chat import EnteredTurn, SessionBusyError, enter_chat_turn
from src.api.services.chat_service import resolve_engine_mode_or_unavailable
from src.api.services.job_queue import enqueue_job
from src.api.services.session_manager import DeckModeLockedError, SessionManager
from src.services.generation_rollback import RollbackResult, roll_back_generation

pytestmark = pytest.mark.asyncio

_CHAT = "src.api.routes.chat"

SESSION_ID = "sess-enter-1"
REQUEST_ID = "req-enter-1"
USER = "author@example.com"
MESSAGE = "make the title bigger"
SLIDE_CONTEXT = {"indices": [0, 1], "slide_htmls": ["<div>a</div>", "<div>b</div>"]}
IMAGE_IDS = ["img-1", "img-2"]
STAGE_SLIDE = {"slide_number": 3, "slide_id": "slide-7f3a"}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def env():
    """Every collaborator of the Enter, patched in the ``chat`` module namespace.

    Defaults drive an Agent deck's graph turn to a successful enqueue; each test
    overrides what it needs.  ``get_session`` reports ``message_count`` 0 until
    ``add_user_message`` has been called and 1 afterwards, like the real one, so
    ``is_first_message`` is only right if it was read before the message was saved.
    """
    sm = create_autospec(SessionManager, instance=True)
    sm.acquire_session_lock.return_value = True
    sm.create_chat_request.return_value = REQUEST_ID
    sm.get_deck_mode.return_value = "agent"
    sm.get_session.side_effect = lambda *a, **k: {
        "session_id": SESSION_ID,
        "message_count": 1 if sm.add_user_message.called else 0,
    }

    enqueue = AsyncMock(spec=enqueue_job, return_value=None)
    resolver = MagicMock(spec=resolve_engine_mode_or_unavailable, return_value="graph")
    rollback = MagicMock(spec=roll_back_generation, return_value=RollbackResult.ROLLED_BACK)

    parent = Mock()
    parent.attach_mock(sm, "sm")
    parent.attach_mock(enqueue, "enqueue_job")
    parent.attach_mock(resolver, "resolve_engine_mode")
    parent.attach_mock(rollback, "roll_back_generation")

    with patch(f"{_CHAT}.get_session_manager", return_value=sm), patch(
        f"{_CHAT}.enqueue_job", enqueue
    ), patch(f"{_CHAT}.resolve_engine_mode_or_unavailable", resolver), patch(
        f"{_CHAT}.get_current_user", return_value=USER
    ), patch(f"{_CHAT}.roll_back_generation", rollback):
        yield SimpleNamespace(
            sm=sm, enqueue=enqueue, resolver=resolver, rollback=rollback, parent=parent
        )


async def _enter(**overrides: Any) -> EnteredTurn:
    kwargs: Dict[str, Any] = {
        "session_id": SESSION_ID,
        "message": MESSAGE,
        "requested_deck_mode": "agent",
    }
    kwargs.update(overrides)
    return await enter_chat_turn(**kwargs)


def _bound(func, call) -> Dict[str, Any]:
    """*call*'s arguments by parameter name, bound to *func*'s real signature."""
    return dict(inspect.signature(func).bind(*call.args, **call.kwargs).arguments)


def _the_one_enqueue(env) -> tuple[str, dict]:
    assert env.enqueue.await_count == 1, env.enqueue.mock_calls
    args = _bound(enqueue_job, env.enqueue.call_args)
    return args["request_id"], args["payload"]


def _call_names(env) -> List[str]:
    return [name for name, _args, _kwargs in env.parent.mock_calls]


def _assert_in_order(env, expected: List[str]) -> None:
    """Each of *expected* happened, and their first calls came in this order."""
    names = _call_names(env)
    missing = [name for name in expected if name not in names]
    assert not missing, f"never called: {missing}; calls were {names}"
    positions = [names.index(name) for name in expected]
    assert positions == sorted(positions), f"wrong order; calls were {names}"


def _core_payload(*, engine_mode: str, stage_slide=None, slide_context=None,
                  image_ids=None, is_first_message: bool = True) -> dict:
    """Today's job payload core keys (chat.py ``submit_chat_async`` enqueue)."""
    return {
        "session_id": SESSION_ID,
        "message": MESSAGE,
        "slide_context": slide_context,
        "is_first_message": is_first_message,
        "image_ids": image_ids,
        "engine_mode": engine_mode,
        "stage_slide": stage_slide,
    }


# ---------------------------------------------------------------------------
# The brief's five tests
# ---------------------------------------------------------------------------


async def test_busy_session_raises_and_writes_nothing(env):
    env.sm.acquire_session_lock.return_value = False

    with pytest.raises(SessionBusyError):
        await _enter()

    env.sm.acquire_session_lock.assert_called_once_with(SESSION_ID)
    env.sm.create_chat_request.assert_not_called()
    env.sm.bind_session_lock.assert_not_called()
    env.sm.begin_generation.assert_not_called()
    env.sm.add_user_message.assert_not_called()
    env.sm.update_chat_request_status.assert_not_called()
    # The lock belongs to whoever holds it: releasing it would free their turn.
    env.sm.release_session_lock.assert_not_called()
    assert env.enqueue.call_count == 0


async def test_agent_turn_snapshots_before_the_user_message_and_enqueues_graph(env):
    env.sm.get_deck_mode.return_value = "agent"
    env.resolver.return_value = "graph"

    result = await _enter(
        requested_deck_mode="agent",
        slide_context=SLIDE_CONTEXT,
        image_ids=IMAGE_IDS,
        stage_slide=STAGE_SLIDE,
    )

    assert result == EnteredTurn(request_id=REQUEST_ID, engine_mode="graph")

    _assert_in_order(
        env,
        [
            "sm.acquire_session_lock",
            "sm.create_chat_request",
            "sm.bind_session_lock",
            "sm.get_deck_mode",
            "sm.begin_generation",
            "sm.add_user_message",
            "resolve_engine_mode",
            "enqueue_job",
        ],
    )
    env.sm.bind_session_lock.assert_called_once_with(SESSION_ID, REQUEST_ID)
    env.sm.begin_generation.assert_called_once_with(SESSION_ID, REQUEST_ID)
    env.sm.add_user_message.assert_called_once_with(
        SESSION_ID,
        MESSAGE,
        message_type="user_query",
        request_id=REQUEST_ID,
        requested_deck_mode="agent",
    )
    env.resolver.assert_called_once_with(SESSION_ID)

    request_id, payload = _the_one_enqueue(env)
    assert request_id == REQUEST_ID
    assert payload["engine_mode"] == "graph"
    assert payload == _core_payload(
        engine_mode="graph",
        stage_slide=STAGE_SLIDE,
        slide_context=SLIDE_CONTEXT,
        image_ids=IMAGE_IDS,
        is_first_message=True,
    )

    # A queued turn keeps its lock (the worker releases it) and is not errored.
    env.sm.release_session_lock.assert_not_called()
    env.sm.update_chat_request_status.assert_not_called()
    env.rollback.assert_not_called()


@pytest.mark.parametrize(
    "extra_payload",
    [
        pytest.param(
            {"correlation_id": "c-1", "message": "other", "engine_mode": "monolith"},
            id="brief",
        ),
        pytest.param(
            {
                "correlation_id": "c-1",
                "origin": {"tool": "create_deck"},
                "session_id": "someone-elses-deck",
                "message": "other",
                "slide_context": {"indices": [9]},
                "is_first_message": False,
                "image_ids": ["injected"],
                "engine_mode": "monolith",
                "stage_slide": {"slide_number": 9},
            },
            id="every-core-key",
        ),
    ],
)
async def test_extra_payload_reaches_the_job_but_never_overrides_core_keys(env, extra_payload):
    env.sm.get_deck_mode.return_value = "agent"
    env.resolver.return_value = "graph"
    sent = dict(extra_payload)

    await _enter(extra_payload=sent)

    _request_id, payload = _the_one_enqueue(env)
    assert payload["correlation_id"] == "c-1"
    assert payload["message"] == MESSAGE
    assert payload["engine_mode"] == "graph"

    core = _core_payload(engine_mode="graph")
    extras_only = {k: v for k, v in extra_payload.items() if k not in core}
    # Every non-core key arrives; every core key is the turn's own value, even
    # where that value is None (no stage, no images, no slide context).
    assert payload == {**extras_only, **core}


async def test_enqueue_failure_on_a_graph_turn_rolls_back_releases_and_reraises(env):
    boom = RuntimeError("boom")
    env.enqueue.side_effect = boom
    env.rollback.return_value = RollbackResult.ROLLED_BACK

    with pytest.raises(RuntimeError) as excinfo:
        await _enter()

    assert excinfo.value is boom
    assert env.rollback.call_count == 1
    assert _bound(roll_back_generation, env.rollback.call_args)["request_id"] == REQUEST_ID
    env.sm.release_session_lock.assert_called_once_with(SESSION_ID, REQUEST_ID)
    # The turn is put back before its lock frees the deck for the next one.
    _assert_in_order(env, ["enqueue_job", "roll_back_generation", "sm.release_session_lock"])


async def test_deck_mode_locked_marks_the_request_and_releases_the_lock(env):
    # The deck was unlocked at the read-only decision (so this Agent turn took a
    # snapshot), then another first message locked it Legacy before this one saved.
    env.sm.get_deck_mode.return_value = None
    locked = DeckModeLockedError("legacy")
    env.sm.add_user_message.side_effect = locked

    with pytest.raises(DeckModeLockedError) as excinfo:
        await _enter(requested_deck_mode="agent")

    assert excinfo.value is locked
    env.sm.update_chat_request_status.assert_called_once_with(
        REQUEST_ID, "error", "deck_mode_locked"
    )
    env.sm.release_session_lock.assert_called_once_with(SESSION_ID, REQUEST_ID)
    # Nothing was saved: the snapshot is dropped, never restored (a restore would
    # undo the other message's lock and pins).
    env.sm.begin_generation.assert_called_once_with(SESSION_ID, REQUEST_ID)
    env.sm.discard_generation_snapshot.assert_called_once_with(REQUEST_ID)
    env.rollback.assert_not_called()
    assert env.enqueue.call_count == 0


# ---------------------------------------------------------------------------
# Plan corrections C1-C3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rollback_behaviour",
    [
        pytest.param({"return_value": RollbackResult.RESTORE_FAILED}, id="restore-failed"),
        pytest.param({"return_value": None}, id="none"),
        pytest.param({"side_effect": RuntimeError("rollback down")}, id="rollback-raised"),
    ],
)
async def test_enqueue_failure_whose_rollback_did_not_restore_keeps_the_lock(
    env, rollback_behaviour
):
    """C1: a failed restore, or a rollback that could not run, keeps the deck
    locked to this request until the orphan sweep restores it."""
    boom = RuntimeError("boom")
    env.enqueue.side_effect = boom
    env.rollback.return_value = rollback_behaviour.get("return_value")
    env.rollback.side_effect = rollback_behaviour.get("side_effect")

    with pytest.raises(RuntimeError) as excinfo:
        await _enter()

    assert excinfo.value is boom
    assert env.rollback.call_count == 1
    assert _bound(roll_back_generation, env.rollback.call_args)["request_id"] == REQUEST_ID
    env.sm.release_session_lock.assert_not_called()


@pytest.mark.parametrize(
    ("stored_deck_mode", "requested_deck_mode", "engine_mode", "expected_stage"),
    [
        pytest.param("agent", "agent", "graph", STAGE_SLIDE, id="graph-keeps-it"),
        pytest.param("legacy", "legacy", "monolith", None, id="monolith-nulls-it"),
    ],
)
async def test_stage_slide_reaches_only_a_graph_turn(
    env, stored_deck_mode, requested_deck_mode, engine_mode, expected_stage
):
    """C2: the engine is only known inside Enter, so the graph-only rule lives there."""
    env.sm.get_deck_mode.return_value = stored_deck_mode
    env.resolver.return_value = engine_mode

    result = await _enter(
        requested_deck_mode=requested_deck_mode, stage_slide=dict(STAGE_SLIDE)
    )

    assert result == EnteredTurn(request_id=REQUEST_ID, engine_mode=engine_mode)
    _request_id, payload = _the_one_enqueue(env)
    assert payload["engine_mode"] == engine_mode
    assert payload["stage_slide"] == expected_stage
    if engine_mode == "monolith":
        # A Legacy turn never touches the generation snapshot.
        env.sm.begin_generation.assert_not_called()
    else:
        env.sm.begin_generation.assert_called_once_with(SESSION_ID, REQUEST_ID)


async def test_the_chat_request_is_created_for_the_current_user(env):
    """C3: Enter reads the caller itself, at call time, from the chat module."""
    with patch(f"{_CHAT}.get_current_user", return_value="mcp-caller@example.com"):
        await _enter()

    env.sm.create_chat_request.assert_called_once_with(SESSION_ID, "mcp-caller@example.com")
