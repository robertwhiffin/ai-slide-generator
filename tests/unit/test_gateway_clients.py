"""The one module that builds Tellr's Unity AI Gateway clients, and the tag they carry."""

import ast
import json
from importlib import metadata
from pathlib import Path

import httpx
import openai
import pytest
from langchain_core.messages import HumanMessage

from src.core.databricks_client import _get_package_version
from src.services import gateway_clients
from src.services.gateway_clients import (
    REQUEST_TAGS_HEADER,
    gateway_chat_model,
    gateway_openai_client,
    gateway_request_headers,
)
from tests.fixtures.mock_chat_completions import (
    MockChatCompletionsWorkspace,
    install_mock_gateway_transport,
)

#: The SDK's own User-Agent for ``DatabricksOpenAI`` (``openai._base_client``:
#: ``f"{self.__class__.__name__}/Python {version}"``), kept as the suffix.
SDK_UA = f"DatabricksOpenAI/Python {openai.__version__}"
#: A source checkout has no installed ``databricks-tellr-app`` wheel, so the
#: version falls back to the source tree's (``_get_package_version``).
EXPECTED_UA = f"tellr/{_get_package_version()} {SDK_UA}"


@pytest.fixture(autouse=True)
def _fresh_version_cache():
    gateway_clients._tellr_version.cache_clear()
    yield
    gateway_clients._tellr_version.cache_clear()


def test_request_tags_header_is_the_source_tellr_json_object():
    assert REQUEST_TAGS_HEADER == "Databricks-Ai-Gateway-Request-Tags"
    assert json.loads(gateway_request_headers()[REQUEST_TAGS_HEADER]) == {"source": "tellr"}


def test_user_agent_leads_with_tellr_and_keeps_the_sdk_user_agent():
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


def test_user_agent_reports_the_installed_wheel_version(monkeypatch):
    """A deployed app runs from the ``databricks-tellr-app`` wheel, whose source
    tree carries no generated ``_version.py``: the wheel's metadata is the truth."""

    def _version(name):
        if name == "databricks-tellr-app":
            return "9.9.9"
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(gateway_clients.metadata, "version", _version)

    assert gateway_request_headers()["User-Agent"] == f"tellr/9.9.9 {SDK_UA}"


def test_user_agent_falls_back_to_the_source_version_outside_a_wheel(monkeypatch):
    def _not_installed(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(gateway_clients.metadata, "version", _not_installed)

    assert gateway_request_headers()["User-Agent"] == f"tellr/{_get_package_version()} {SDK_UA}"


def test_only_the_tag_and_user_agent_are_set():
    assert set(gateway_request_headers()) == {REQUEST_TAGS_HEADER, "User-Agent"}


def test_each_call_returns_a_fresh_dict():
    first = gateway_request_headers()
    first["User-Agent"] = "mutated"
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


def _text_workspace(monkeypatch) -> MockChatCompletionsWorkspace:
    """A mock-transport workspace that answers every chat completion with plain text."""
    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace({}, usage=None)

    def handle(request):
        workspace.requests.append(request)
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        })

    workspace._handle = handle
    return workspace


def _assert_tagged_gateway_chat_request(request: httpx.Request, model: str) -> None:
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
    assert request.headers.get_list("databricks-ai-gateway-request-tags") == ['{"source": "tellr"}']
    assert request.headers.get_list("user-agent") == [EXPECTED_UA]
    sent = json.loads(request.content)
    assert sent["model"] == model
    assert "extra_headers" not in sent and "extra_params" not in sent


def test_gateway_openai_client_sends_tagged_requests_to_the_gateway_chat_route(monkeypatch):
    """Exports: the raw client, bound to {host}/ai-gateway/mlflow/v1, tagged."""
    workspace = _text_workspace(monkeypatch)

    gateway_openai_client(workspace).chat.completions.create(
        model="system.ai.claude-sonnet-4-5",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5,
    )

    assert len(workspace.requests) == 1
    _assert_tagged_gateway_chat_request(workspace.requests[0], "system.ai.claude-sonnet-4-5")


def test_gateway_chat_model_sends_tagged_requests_to_the_gateway_chat_route(monkeypatch):
    """Graph agents and titles: the LangChain model, as the given identity, tagged."""
    workspace = _text_workspace(monkeypatch)

    model = gateway_chat_model(model="system.ai.claude-opus-5-5", max_tokens=5, workspace_client=workspace)
    model.invoke([HumanMessage(content="hi")])

    assert model.workspace_client is workspace
    assert len(workspace.requests) == 1
    _assert_tagged_gateway_chat_request(workspace.requests[0], "system.ai.claude-opus-5-5")
    assert json.loads(workspace.requests[0].content)["max_tokens"] == 5


_GATEWAY_FLAGS = ("use_ai_gateway", "use_ai_gateway_native_api")


def _is_headers_call(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "gateway_request_headers"
    )


def _carries_extra_headers(node: ast.AST | None) -> bool:
    """``extra_params={"extra_headers": gateway_request_headers()}``."""
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "extra_headers" and _is_headers_call(value)
        for key, value in zip(node.keys, node.values)
    )


def _gateway_calls(source: str) -> list[tuple[int, bool]]:
    """``(line, tagged)`` for each call in ``source`` that builds a Unity AI Gateway client.

    A call builds one when it passes a Gateway flag that is not literally ``False``,
    or a ``base_url`` under ``/ai-gateway/``.  It is tagged when it passes
    ``default_headers=gateway_request_headers()`` or the ``extra_params`` form.
    Comments and prose are not calls, so they neither count nor tag.
    """
    calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        flagged = any(
            name in kwargs
            and not (isinstance(kwargs[name], ast.Constant) and kwargs[name].value is False)
            for name in _GATEWAY_FLAGS
        )
        gateway_url = "base_url" in kwargs and "/ai-gateway/" in ast.unparse(kwargs["base_url"])
        if flagged or gateway_url:
            tagged = _is_headers_call(kwargs.get("default_headers")) or _carries_extra_headers(
                kwargs.get("extra_params")
            )
            calls.append((node.lineno, tagged))
    return sorted(calls)


TAGGED = 'extra_params={"extra_headers": gateway_request_headers()}'


def test_guard_flags_an_untagged_construction_beside_a_tagged_one():
    source = f"a = ChatDatabricks(use_ai_gateway=True, {TAGGED})\nb = ChatDatabricks(use_ai_gateway=True)\n"
    assert _gateway_calls(source) == [(1, True), (2, False)]


def test_guard_flags_a_commented_out_header_argument():
    source = "DatabricksOpenAI(\n    use_ai_gateway=True,\n    # default_headers=gateway_request_headers(),\n)\n"
    assert _gateway_calls(source) == [(1, False)]


def test_guard_flags_a_client_built_from_an_ai_gateway_base_url():
    source = 'DatabricksOpenAI(base_url=f"{host}/ai-gateway/mlflow/v1")\n'
    assert _gateway_calls(source) == [(1, False)]


def test_guard_accepts_both_tagging_forms():
    source = (
        "DatabricksOpenAI(use_ai_gateway=True, default_headers=gateway_request_headers())\n"
        f"ChatDatabricks(use_ai_gateway_native_api=True, {TAGGED}, **kwargs)\n"
    )
    assert _gateway_calls(source) == [(1, True), (2, True)]


def test_guard_ignores_prose_and_disabled_flags():
    source = '"""Mentions use_ai_gateway=True and /ai-gateway/ in prose."""\nx = f(use_ai_gateway=False)\n'
    assert _gateway_calls(source) == []


def test_only_gateway_clients_builds_gateway_clients_and_every_one_is_tagged():
    """Isaac's tag was once silently dropped; a new Gateway client must not ship untagged.

    Every Gateway client in ``src`` is built in ``services/gateway_clients.py``;
    a construction anywhere else should call its builders instead.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    found = {p.relative_to(src).as_posix(): _gateway_calls(p.read_text()) for p in src.rglob("*.py")}
    sites = {path: calls for path, calls in found.items() if calls}
    assert set(sites) == {"services/gateway_clients.py"}
    untagged = [(path, line) for path, calls in sites.items() for line, tagged in calls if not tagged]
    assert untagged == []
