"""ChatRequest.message length cap is disabled (CHAT_MESSAGE_MAX_LENGTH=None)."""

import pytest
from pydantic import ValidationError

from src.api.schemas.requests import CHAT_MESSAGE_MAX_LENGTH, ChatRequest


def test_length_cap_disabled_by_default():
    assert CHAT_MESSAGE_MAX_LENGTH is None


def test_accepts_message_beyond_old_8k_cap():
    request = ChatRequest(message="x" * 100_000)
    assert len(request.message) == 100_000


def test_still_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")
