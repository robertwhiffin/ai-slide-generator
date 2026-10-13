"""A workspace-client stand-in that serves the REAL ``ChatDatabricks`` a canned
chat completion over ``httpx.MockTransport`` (#267 whole-branch fix I-1, ws2a).

``MockChatCompletionsWorkspace`` is a ``WorkspaceClient`` subclass with a
no-op ``__init__`` that sets only what ``DatabricksOpenAI`` reads
(``_config.host``, ``_config.authenticate``) and ``_handle`` for the mock
transport.  Because it is a real ``WorkspaceClient`` subclass, ChatDatabricks
0.20.0 accepts it as ``workspace_client`` directly (pydantic ``isinstance``
check passes), and the entire production path from ``client_factory`` through
``_default_model_factory`` → ``ChatDatabricks`` → ``DatabricksOpenAI`` →
``_get_authorized_http_client`` runs unmodified — only the HTTP transport
layer is replaced.

``install_mock_gateway_transport`` patches ``_get_authorized_http_client`` so
every request is routed through the workspace's own ``_handle`` with no network
contact and no ambient credential.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
from databricks.sdk import WorkspaceClient

MOCK_CHAT_HOST = "chat.invalid"

#: The token counts a usage-reporting mock endpoint returns.
MOCK_PROMPT_TOKENS = 123
MOCK_COMPLETION_TOKENS = 45
MOCK_USAGE = {
    "prompt_tokens": MOCK_PROMPT_TOKENS,
    "completion_tokens": MOCK_COMPLETION_TOKENS,
    "total_tokens": MOCK_PROMPT_TOKENS + MOCK_COMPLETION_TOKENS,
}


class MockChatCompletionsWorkspace(WorkspaceClient):
    """A ``WorkspaceClient`` subclass that stands in for a real workspace.

    Subclassing satisfies ChatDatabricks 0.20.0's pydantic
    ``workspace_client: Optional[WorkspaceClient]`` field check, so tests
    can use ``client_factory=lambda: workspace`` with the real production
    factory without any mock substitution higher up the call stack.

    Only ``_config.host`` and ``_config.authenticate`` are set; every other
    WorkspaceClient attribute is absent, which is fine because DatabricksOpenAI
    only reads those two.
    """

    def __init__(
        self,
        arguments: dict[str, Any],
        *,
        usage: dict[str, int] | None,
        tool_call: bool = True,
    ) -> None:
        # Do NOT call super().__init__() — it would try to resolve Databricks
        # credentials.  We set only _config (the attribute the .config property
        # reads) and _handle (used by the patched _get_authorized_http_client).
        self.arguments = arguments
        self.usage = usage
        #: ``False``: the model answers in prose and calls no tool — what a
        #: ``tool_choice="auto"`` request permits (ws2a follow-up A).
        self.tool_call = tool_call
        self.requests: list[httpx.Request] = []
        self._config = SimpleNamespace(
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
        if not self.tool_call:
            body["choices"][0]["finish_reason"] = "stop"
            body["choices"][0]["message"] = {
                "role": "assistant",
                "content": "Here is my answer in prose, without calling the tool.",
            }
        if self.usage is not None:
            body["usage"] = dict(self.usage)
        return httpx.Response(200, json=body)


def install_mock_gateway_transport(monkeypatch) -> None:
    """Patch ``_get_authorized_http_client`` so requests go through ``_handle``.

    The real ``BearerAuth`` reads ``workspace_client.config.authenticate``,
    and the real ``_resolve_base_url`` decides the path
    (``{host}/ai-gateway/mlflow/v1``), so the entire production chain runs —
    only the HTTP transport layer is replaced.
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
