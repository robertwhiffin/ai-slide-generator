"""Unit tests for the log-record rendering helper.

The helper must exclude every source-location attribute so that a test run from
a path containing "private" (e.g. macOS's /private/tmp) cannot cause a false
positive when a test checks that "private" does not appear in rendered output.
"""

from __future__ import annotations

import logging

from tests.fixtures.log_records import rendered_record


def _record(**extra):
    record = logging.LogRecord(
        "n", logging.INFO, "/private/tmp/agent_model_payload.py", 1,
        "persisted_agent_invocation", (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_path_attributes_never_reach_the_rendering():
    text = rendered_record(_record())
    assert "private" not in text and "payload" not in text


def test_extras_message_args_and_exception_text_do_reach_it():
    record = _record(agent_key="architect")
    record.exc_text = "Traceback: secret-prompt"
    text = rendered_record(record)
    assert "architect" in text and "persisted_agent_invocation" in text and "secret-prompt" in text
