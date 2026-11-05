"""Tellr's Unity AI Gateway attribution headers (``source=tellr`` + a tellr User-Agent)."""

import json

import openai

from src.core.databricks_client import _get_package_version
from src.services.gateway_headers import REQUEST_TAGS_HEADER, gateway_request_headers

EXPECTED_UA = f"tellr/{_get_package_version()} OpenAI/Python {openai.__version__}"


def test_request_tags_header_is_the_source_tellr_json_object():
    assert REQUEST_TAGS_HEADER == "Databricks-Ai-Gateway-Request-Tags"
    assert json.loads(gateway_request_headers()[REQUEST_TAGS_HEADER]) == {"source": "tellr"}


def test_user_agent_leads_with_tellr_and_keeps_the_openai_sdk():
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA


def test_only_the_tag_and_user_agent_are_set():
    assert set(gateway_request_headers()) == {REQUEST_TAGS_HEADER, "User-Agent"}


def test_each_call_returns_a_fresh_dict():
    first = gateway_request_headers()
    first["User-Agent"] = "mutated"
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA
