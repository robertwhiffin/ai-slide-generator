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
