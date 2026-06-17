"""Tests for the post-output HTML safety gate + corrective retry (AISEC-248 PR1)."""

import pytest
from src.services.agent import _run_output_safety_gate, AgentError


def test_clean_output_passes_through():
    calls = []

    def regenerate():
        calls.append("retry")
        return "<div class='slide'>clean</div>"

    out = _run_output_safety_gate("<div class='slide'>clean</div>", regenerate, session_id="s1")
    assert out == "<div class='slide'>clean</div>"
    assert calls == []  # no retry needed


def test_unsafe_then_clean_retry_succeeds():
    def regenerate():
        return "<div class='slide'>now clean</div>"

    out = _run_output_safety_gate('<script>fetch("https://x")</script>', regenerate, session_id="s1")
    assert out == "<div class='slide'>now clean</div>"


def test_unsafe_twice_raises():
    def regenerate():
        return '<img src="https://attacker.com/b.png">'

    with pytest.raises(AgentError):
        _run_output_safety_gate('<img src="https://attacker.com/b.png">', regenerate, session_id="s1")
