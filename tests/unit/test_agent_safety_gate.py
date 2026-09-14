"""Tests for the post-output HTML safety gate + corrective retry (AISEC-248 PR1)."""

import pytest
from src.services.agent import _run_output_safety_gate, AgentError, SAFETY_RETRY_NOTICE


def test_clean_output_passes_through():
    calls = []

    def regenerate():
        calls.append("retry")
        return "<div class='slide'>clean</div>"

    out, retried = _run_output_safety_gate(
        "<div class='slide'>clean</div>", regenerate, session_id="s1"
    )
    assert out == "<div class='slide'>clean</div>"
    assert retried is False
    assert calls == []  # no retry needed


def test_unsafe_then_clean_retry_succeeds_and_flags_retried():
    def regenerate():
        return "<div class='slide'>now clean</div>"

    out, retried = _run_output_safety_gate(
        '<script>fetch("https://x")</script>', regenerate, session_id="s1"
    )
    assert out == "<div class='slide'>now clean</div>"
    assert retried is True  # caller surfaces SAFETY_RETRY_NOTICE on this


def test_unsafe_twice_raises():
    def regenerate():
        return '<img src="https://attacker.com/b.png">'

    with pytest.raises(AgentError):
        _run_output_safety_gate('<img src="https://attacker.com/b.png">', regenerate, session_id="s1")


def test_safety_retry_notice_is_generic():
    # Generic copy — names the category, not the specific pattern.
    assert "external network/resource access" in SAFETY_RETRY_NOTICE
    assert "Attempting to build again" in SAFETY_RETRY_NOTICE


def test_on_retry_fires_before_regenerate_when_unsafe():
    order = []

    def regenerate():
        order.append("regenerate")
        return "<div class='slide'>now clean</div>"

    def on_retry():
        order.append("on_retry")

    out, retried = _run_output_safety_gate(
        '<script>fetch("https://x")</script>', regenerate, session_id="s1", on_retry=on_retry
    )
    assert retried is True
    # Notice must be emitted BEFORE the rebuild so it lands between attempts.
    assert order == ["on_retry", "regenerate"]


def test_on_retry_not_called_when_clean():
    calls = []
    _run_output_safety_gate(
        "<div class='slide'>clean</div>",
        lambda: "x",
        session_id="s1",
        on_retry=lambda: calls.append("x"),
    )
    assert calls == []


# ---------------------------------------------------------------------------
# Graph-path equivalents — gate_emitted_html (AISEC-248)
# ---------------------------------------------------------------------------

class TestGraphPathGate:
    """Graph-path gate_emitted_html exercises the same scanner as the monolith.

    Both paths carry AISEC-248; these cases confirm the graph entry point
    behaves identically to _run_output_safety_gate for the core contract.
    """

    def test_graph_gate_clean_passes_through(self):
        from src.utils.graph_safety import gate_emitted_html

        out, retried = gate_emitted_html(
            "<div class='slide'>clean</div>",
            lambda: "x",
            session_id="s1",
        )
        assert out == "<div class='slide'>clean</div>"
        assert retried is False

    def test_graph_gate_unsafe_then_clean_flags_retried(self):
        from src.utils.graph_safety import gate_emitted_html

        out, retried = gate_emitted_html(
            '<script>fetch("https://x")</script>',
            lambda: "<div class='slide'>clean</div>",
            session_id="s1",
        )
        assert out == "<div class='slide'>clean</div>"
        assert retried is True

    def test_graph_gate_unsafe_twice_raises(self):
        from src.services.agent import AgentError
        from src.utils.graph_safety import gate_emitted_html

        unsafe = '<img src="https://attacker.com/b.png">'
        with pytest.raises(AgentError):
            gate_emitted_html(unsafe, lambda: unsafe, session_id="s1")
