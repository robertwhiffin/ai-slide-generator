"""Tellr's Unity AI Gateway attribution headers (``source=tellr`` + a tellr User-Agent)."""

import ast
import json
from importlib import metadata
from pathlib import Path

import openai
import pytest

from src.core.databricks_client import _get_package_version
from src.services import gateway_headers
from src.services.gateway_headers import REQUEST_TAGS_HEADER, gateway_request_headers

#: The SDK's own User-Agent for ``DatabricksOpenAI`` (``openai._base_client``:
#: ``f"{self.__class__.__name__}/Python {version}"``), kept as the suffix.
SDK_UA = f"DatabricksOpenAI/Python {openai.__version__}"
#: A source checkout has no installed ``databricks-tellr-app`` wheel, so the
#: version falls back to the source tree's (``_get_package_version``).
EXPECTED_UA = f"tellr/{_get_package_version()} {SDK_UA}"


@pytest.fixture(autouse=True)
def _fresh_version_cache():
    gateway_headers._tellr_version.cache_clear()
    yield
    gateway_headers._tellr_version.cache_clear()


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

    monkeypatch.setattr(gateway_headers.metadata, "version", _version)

    assert gateway_request_headers()["User-Agent"] == f"tellr/9.9.9 {SDK_UA}"


def test_user_agent_falls_back_to_the_source_version_outside_a_wheel(monkeypatch):
    def _not_installed(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(gateway_headers.metadata, "version", _not_installed)

    assert gateway_request_headers()["User-Agent"] == f"tellr/{_get_package_version()} {SDK_UA}"


def test_only_the_tag_and_user_agent_are_set():
    assert set(gateway_request_headers()) == {REQUEST_TAGS_HEADER, "User-Agent"}


def test_each_call_returns_a_fresh_dict():
    first = gateway_request_headers()
    first["User-Agent"] = "mutated"
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


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


def test_every_gateway_client_construction_sends_the_tellr_headers():
    """Isaac's tag was once silently dropped; a new Gateway client must not ship untagged."""
    src = Path(__file__).resolve().parents[2] / "src"
    found = {p.relative_to(src).as_posix(): _gateway_calls(p.read_text()) for p in src.rglob("*.py")}
    sites = {path: calls for path, calls in found.items() if calls}
    assert set(sites) == {
        "services/agent_runtime.py",
        "api/services/session_naming.py",
        "services/gateway_openai.py",
    }
    untagged = [(path, line) for path, calls in sites.items() for line, tagged in calls if not tagged]
    assert untagged == []
