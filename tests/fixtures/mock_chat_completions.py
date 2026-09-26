"""A workspace-client stand-in that serves the REAL ``ChatDatabricks`` a canned
chat completion over ``httpx.MockTransport`` (#267 whole-branch fix I-1).

It follows #266's probe harness (``tests/unit/test_model_endpoint_probe.py``):
the chat model gets an ``openai.OpenAI`` whose only transport is the mock, with
a literal dummy key and an ``.invalid`` host, so no request can reach a network
and no ambient credential is read.  The completion answers the bound schema's
own tool with ``arguments``; ``usage`` is included only when given, so a test
can drive an endpoint that reports token usage and one that does not.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai

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
    """Expose only ``serving_endpoints.get_open_ai_client``, as the chat model uses."""

    def __init__(self, arguments: dict[str, Any], *, usage: dict[str, int] | None) -> None:
        self.arguments = arguments
        self.usage = usage
        self.requests: list[httpx.Request] = []
        self.serving_endpoints = self

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

    def get_open_ai_client(self, **kwargs: Any) -> openai.OpenAI:
        return openai.OpenAI(
            base_url=f"https://{MOCK_CHAT_HOST}/serving-endpoints",
            api_key="unit-test-dummy-key",
            http_client=httpx.Client(transport=httpx.MockTransport(self._handle)),
            **kwargs,
        )


__all__ = [
    "MOCK_CHAT_HOST",
    "MOCK_COMPLETION_TOKENS",
    "MOCK_PROMPT_TOKENS",
    "MOCK_USAGE",
    "MockChatCompletionsWorkspace",
]
