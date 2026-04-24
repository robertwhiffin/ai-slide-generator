"""Regression tests for intent detectors: `extra={"message": ...}` must not
collide with LogRecord reserved attribute, which would raise
KeyError("Attempt to overwrite 'message' in LogRecord") and break the
first chat message in a new deck.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def enable_info_logging():
    """Force the intent-detector module loggers to INFO.

    In production (LOG_LEVEL=DEBUG/INFO), `logger.info(..., extra={"message": ...})`
    invokes stdlib makeRecord which rejects reserved keys. In a default test
    environment, the root logger is WARNING and logger.info is a no-op, which
    hides the bug. This fixture raises the level so the regression is visible.
    """
    loggers = [
        logging.getLogger("src.api.services.chat_service"),
        logging.getLogger("src.services.agent"),
    ]
    prev_levels = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.DEBUG)
    yield
    for lg, level in prev_levels:
        lg.setLevel(level)


class TestChatServiceIntentDetectors:
    """Intent detectors on ChatService must not pass reserved LogRecord keys."""

    @pytest.fixture
    def service(self):
        from src.api.services.chat_service import ChatService

        return ChatService()

    def test_detect_generation_intent_does_not_raise(self, service, enable_info_logging):
        # "Create slides about X" matches _detect_generation_intent, which
        # previously logged extra={"message": ...} and raised KeyError.
        assert service._detect_generation_intent("create slides about Q3 sales") is True

    def test_detect_add_intent_does_not_raise(self, service, enable_info_logging):
        assert service._detect_add_intent("add a slide at the end") is True

    def test_detect_add_position_does_not_raise(self, service, enable_info_logging):
        pos, _ = service._detect_add_position("add a slide at the beginning")
        assert pos == "beginning"

    def test_detect_explicit_replace_intent_does_not_raise(self, service, enable_info_logging):
        assert service._detect_explicit_replace_intent("replace the deck") is True

    def test_detect_edit_intent_does_not_raise(self, service, enable_info_logging):
        assert service._detect_edit_intent("change slide 3") is True


class TestAgentIntentDetector:
    """SlideGeneratorAgent._detect_add_slide_intent must not pass reserved keys."""

    def test_agent_detect_add_intent_does_not_raise(self, enable_info_logging):
        # Call the unbound method directly — it's a pure function of (self, message)
        # and doesn't touch any agent state.
        from src.services.agent import SlideGeneratorAgent

        assert (
            SlideGeneratorAgent._detect_add_intent(
                None, "add a new slide about revenue"
            )
            is True
        )
