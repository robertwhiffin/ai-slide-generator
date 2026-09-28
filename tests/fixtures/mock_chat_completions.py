"""A workspace-client stand-in that serves the REAL ``ChatDatabricks`` a canned
chat completion over ``httpx.MockTransport`` (#267 whole-branch fix I-1, ws2a).

``install_mock_gateway_transport`` patches the one HTTP-client factory that
``DatabricksOpenAI`` calls, so every request from real ``ChatDatabricks`` is
routed through ``MockChatCompletionsWorkspace._handle`` instead of hitting a
network.  The real ``BearerAuth`` still reads
``workspace_client.config.authenticate``, and the real base-URL resolution
still decides the path (``{host}/ai-gateway/mlflow/v1``), so the full
production code path executes — only the transport is replaced.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

MOCK_CHAT_HOST = "chat.invalid"

#: The token counts a usage-reporting mock endpoint returns.
MOCK_PROMPT_TOKENS = 123
MOCK_COMPLETION_TOKENS = 45
MOCK_USAGE = {
    "prompt_tokens": MOCK_PROMPT_TOKENS,
    "completion_tokens": MOCK_COMPLETION_TOKENS,
    "total_tokens": MOCK_PROMPT_TOKENS + MOCK_COMPLETION_TOKENS,
}


class MockChatCompletionsWorkspace:
    """Expose only what ``DatabricksOpenAI`` reads: ``config.host`` and ``config.authenticate``.

    ``install_mock_gateway_transport`` routes the client's HTTP through ``_handle``,
    so no request can reach a network and no ambient credential is read.
    """

    def __init__(self, arguments: dict[str, Any], *, usage: dict[str, int] | None) -> None:
        self.arguments = arguments
        self.usage = usage
        self.requests: list[httpx.Request] = []
        self.config = SimpleNamespace(
            host=f"https://{MOCK_CHAT_HOST}",
            authenticate=lambda: {"Authorization": "Bearer unit-test-dummy-key"},
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        sent = json.loads(request.content)
        tool_name = sent["tools"][0]["function"]["name"]
        body: dict[str, Any] = {
            "id": "mock",
            "object": "chat.completion",
            "created": 0,
            "model": "mock",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(self.arguments),
                                },
                            }
                        ],
                    },
                }
            ],
        }
        if self.usage is not None:
            body["usage"] = dict(self.usage)
        return httpx.Response(200, json=body)


def install_mock_gateway_transport(monkeypatch) -> None:
    """Make ``DatabricksOpenAI`` send through the workspace stand-in's ``_handle``.

    Only the transport is replaced: the real ``BearerAuth`` still reads
    ``workspace_client.config.authenticate``, and the real base-URL resolution still
    decides the path.
    """
    from databricks_openai.utils import clients

    def _mock_http_client(workspace_client, follow_redirects: bool = True) -> httpx.Client:
        return httpx.Client(
            auth=clients.BearerAuth(workspace_client.config.authenticate),
            transport=httpx.MockTransport(workspace_client._handle),
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(clients, "_get_authorized_http_client", _mock_http_client)


__all__ = [
    "MOCK_CHAT_HOST",
    "MOCK_COMPLETION_TOKENS",
    "MOCK_PROMPT_TOKENS",
    "MOCK_USAGE",
    "MockChatCompletionsWorkspace",
    "install_mock_gateway_transport",
]
