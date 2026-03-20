"""Tests for job_queue cancellation paths in process_chat_request."""

import pytest
from unittest.mock import MagicMock, patch

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.services.cancellation import CancellationRegistry


def _make_cancelled_event():
    return StreamEvent(type=StreamEventType.CANCELLED, content="Generation was cancelled.")


def _make_complete_event():
    return StreamEvent(
        type=StreamEventType.COMPLETE,
        slides={"title": "Test", "slides": []},
        raw_html=None,
        replacement_info=None,
        experiment_url=None,
    )


def _base_payload(session_id: str = "sess-1", pre_gen_version: int = 2) -> dict:
    """Payload with no _context so the else-branch of process_chat_request runs."""
    return {
        "session_id": session_id,
        "message": "make slides",
        "slide_context": None,
        "is_first_message": False,
        "image_ids": None,
        "pre_gen_version": pre_gen_version,
    }


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure the cancellation registry is clean before and after each test."""
    CancellationRegistry._cancelled.clear()
    yield
    CancellationRegistry._cancelled.clear()


# get_chat_service and get_session_manager are imported locally inside
# process_chat_request, so we patch them at their source module.
_PATCH_CS = "src.api.services.chat_service.get_chat_service"
_PATCH_SM = "src.api.services.session_manager.get_session_manager"
_PATCH_GEN = "src.api.services.job_queue._run_streaming_generator"


@pytest.mark.asyncio
async def test_cancelled_event_calls_revert_and_skips_lock_release():
    """When a CANCELLED event is received, revert is called and lock is NOT released."""
    payload = _base_payload()

    mock_sm = MagicMock()
    with (
        patch(_PATCH_CS, return_value=MagicMock()),
        patch(_PATCH_SM, return_value=mock_sm),
        patch(_PATCH_GEN, return_value=[_make_cancelled_event()]),
    ):
        from src.api.services.job_queue import process_chat_request
        await process_chat_request("req-1", payload)

    mock_sm.revert_slides_on_cancel.assert_called_once_with("sess-1", 2, "req-1")
    mock_sm.release_session_lock.assert_not_called()


@pytest.mark.asyncio
async def test_complete_event_releases_lock_and_skips_revert():
    """When a COMPLETE event is received (no cancel), lock is released and revert is NOT called."""
    payload = _base_payload()

    mock_sm = MagicMock()
    with (
        patch(_PATCH_CS, return_value=MagicMock()),
        patch(_PATCH_SM, return_value=mock_sm),
        patch(_PATCH_GEN, return_value=[_make_complete_event()]),
    ):
        from src.api.services.job_queue import process_chat_request
        await process_chat_request("req-2", payload)

    mock_sm.release_session_lock.assert_called_once_with("sess-1")
    mock_sm.revert_slides_on_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_exception_before_cancelled_event_releases_lock():
    """If generator raises before yielding CANCELLED, lock is released normally."""
    payload = _base_payload()

    mock_sm = MagicMock()
    with (
        patch(_PATCH_CS, return_value=MagicMock()),
        patch(_PATCH_SM, return_value=mock_sm),
        patch(_PATCH_GEN, side_effect=RuntimeError("Genie exploded")),
    ):
        from src.api.services.job_queue import process_chat_request
        with pytest.raises(RuntimeError):
            await process_chat_request("req-3", payload)

    mock_sm.release_session_lock.assert_called_once_with("sess-1")
    mock_sm.revert_slides_on_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_exception_with_cancel_flag_reverts_without_lock_release():
    """If cancel flag is set AND generator raises, revert is attempted and lock is NOT released."""
    payload = _base_payload(session_id="sess-exc")
    CancellationRegistry.cancel("sess-exc")

    mock_sm = MagicMock()
    with (
        patch(_PATCH_CS, return_value=MagicMock()),
        patch(_PATCH_SM, return_value=mock_sm),
        patch(_PATCH_GEN, side_effect=RuntimeError("crash")),
    ):
        from src.api.services.job_queue import process_chat_request
        with pytest.raises(RuntimeError):
            await process_chat_request("req-4", payload)

    mock_sm.revert_slides_on_cancel.assert_called_once_with("sess-exc", 2, "req-4")
    mock_sm.release_session_lock.assert_not_called()
    assert not CancellationRegistry.is_cancelled("sess-exc")  # flag reset
