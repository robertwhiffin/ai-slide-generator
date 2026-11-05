import json

from tests.fixtures.mock_chat_completions import MockChatCompletionsWorkspace, install_mock_gateway_transport

from src.services.gateway_openai import gateway_openai_client


def test_gateway_openai_client_posts_to_the_gateway_chat_route(monkeypatch):
    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace({}, usage=None)
    workspace._handle = _text_handler(workspace)

    client = gateway_openai_client(workspace)
    client.chat.completions.create(model="system.ai.claude-sonnet-4-5",
                                   messages=[{"role": "user", "content": "hi"}], max_tokens=5)

    request = workspace.requests[0]
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
    assert json.loads(request.content)["model"] == "system.ai.claude-sonnet-4-5"


def test_gateway_openai_client_sends_the_tellr_tag_and_user_agent(monkeypatch):
    """Export LLM calls are attributable to Tellr in ``system.ai_gateway.usage``."""
    import openai

    from src.core.databricks_client import _get_package_version

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace({}, usage=None)
    workspace._handle = _text_handler(workspace)

    client = gateway_openai_client(workspace)
    client.chat.completions.create(model="system.ai.claude-sonnet-4-5",
                                   messages=[{"role": "user", "content": "hi"}], max_tokens=5)

    request = workspace.requests[0]
    expected_ua = f"tellr/{_get_package_version()} OpenAI/Python {openai.__version__}"
    assert request.headers.get_list("databricks-ai-gateway-request-tags") == ['{"source": "tellr"}']
    assert request.headers.get_list("user-agent") == [expected_ua]
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"


def _text_handler(workspace):
    import httpx

    def handle(request):
        workspace.requests.append(request)
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        })

    return handle
