import pytest
from src.services.agent import (
    SlideGeneratorAgent,
    _run_output_safety_gate,
    AgentError,
    UnsafeContentError,
)


def test_hard_fail_raises_unsafe_content_error():
    unsafe = '<script>fetch("https://evil")</script>'
    with pytest.raises(UnsafeContentError):
        _run_output_safety_gate(unsafe, regenerate=lambda: unsafe, session_id="s1")


def test_generate_slides_propagates_unsafe_content_error(monkeypatch):
    """Integration: a safety-gate hard-fail must survive generate_slides' own
    try/except and surface as UnsafeContentError (not the generic AgentError
    that the broad `except Exception` handler would otherwise re-wrap it as).

    This is the gap the per-task gate tests missed: they called
    _run_output_safety_gate directly, never exercising the method's handlers.
    """
    unsafe = '<script>fetch("https://evil")</script>'

    # Build the agent without running __init__ (which would hit Databricks/MLflow).
    # We only need the attributes generate_slides touches on the unsafe path; the
    # method's own try/except is what we're exercising, so it must be the real one.
    agent = SlideGeneratorAgent.__new__(SlideGeneratorAgent)
    # Non-empty (truthy) so generate_slides uses _pre_built_tools and skips the
    # legacy _create_tools_for_session path. _create_agent_executor is stubbed
    # below and ignores the tools, so their content is irrelevant.
    agent._pre_built_tools = ["_sentinel"]

    class _History:
        messages: list = []

        def add_message(self, _msg):  # pragma: no cover - not reached pre-fail
            pass

    agent.get_session = lambda session_id: {  # type: ignore[method-assign]
        "chat_history": _History(),
        "message_count": 0,
        "genie_conversation_id": "g1",
        "experiment_id": None,
    }

    # Stub executor: every invoke (initial + corrective retry) yields unsafe HTML,
    # forcing the gate to hard-fail with UnsafeContentError.
    class _StubExecutor:
        def invoke(self, *_args, **_kwargs):
            return {"output": unsafe, "intermediate_steps": []}

    agent._create_agent_executor = lambda tools: _StubExecutor()  # type: ignore[method-assign]

    with pytest.raises(UnsafeContentError):
        agent.generate_slides(question="make slides", session_id="s1")

    # Guard against regression: the hard-fail must NOT be downgraded to a bare
    # AgentError (which the route maps to a 500 leaking str(e)).
    with pytest.raises(UnsafeContentError):
        try:
            agent.generate_slides(question="make slides", session_id="s1")
        except AgentError as e:
            assert isinstance(e, UnsafeContentError), (
                f"safety hard-fail was re-wrapped as {type(e).__name__}"
            )
            raise


def test_unsafe_content_error_message_is_generic():
    unsafe = '<script>fetch("https://evil")</script>'
    try:
        _run_output_safety_gate(unsafe, regenerate=lambda: unsafe, session_id="s1")
    except UnsafeContentError as e:
        assert "disallowed content" in str(e)
        assert "evil" not in str(e)  # no payload echoed back
