import pytest
from src.services.agent import _run_output_safety_gate, UnsafeContentError


def test_hard_fail_raises_unsafe_content_error():
    unsafe = '<script>fetch("https://evil")</script>'
    with pytest.raises(UnsafeContentError):
        _run_output_safety_gate(unsafe, regenerate=lambda: unsafe, session_id="s1")


def test_unsafe_content_error_message_is_generic():
    unsafe = '<script>fetch("https://evil")</script>'
    try:
        _run_output_safety_gate(unsafe, regenerate=lambda: unsafe, session_id="s1")
    except UnsafeContentError as e:
        assert "disallowed content" in str(e)
        assert "evil" not in str(e)  # no payload echoed back
