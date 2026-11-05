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


def test_every_gateway_client_construction_sends_the_tellr_headers():
    """Isaac's tag was once silently dropped; a new Gateway client must not ship untagged."""
    src = Path(__file__).resolve().parents[2] / "src"
    sites = {
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "use_ai_gateway" in p.read_text()  # also catches use_ai_gateway_native_api
    }
    assert sites == {
        "services/agent_runtime.py",
        "api/services/session_naming.py",
        "services/gateway_openai.py",
    }
    for site in sites:
        assert "gateway_request_headers()" in (src / site).read_text(), site
