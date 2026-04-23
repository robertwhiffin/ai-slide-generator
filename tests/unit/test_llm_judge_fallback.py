"""Tests for LLM judge MLflow failure detection and JSON parsing helpers."""

import json

import pytest

from src.services.evaluation.llm_judge import (
    _mlflow_evaluate_should_use_direct_fallback,
    _parse_judge_json_response,
)


def test_fallback_detects_storage_egress_chain():
    inner = ConnectionError(
        "HTTPSConnectionPool(host='us-east-1.storage.cloud.databricks.com', port=443): "
        "Failed to establish a new connection: [Errno 111] Connection refused"
    )
    outer = RuntimeError("evaluate failed")
    outer.__cause__ = inner
    assert _mlflow_evaluate_should_use_direct_fallback(outer) is True


def test_fallback_detects_resource_does_not_exist():
    exc = RuntimeError(
        "RESOURCE_DOES_NOT_EXIST: Node ID 1115809433618914 does not exist."
    )
    assert _mlflow_evaluate_should_use_direct_fallback(exc) is True


def test_fallback_false_for_unrelated_error():
    assert _mlflow_evaluate_should_use_direct_fallback(ValueError("bad input")) is False


def test_parse_judge_json_clean():
    text = json.dumps({"rating": "green", "explanation": "All figures match."})
    r, e = _parse_judge_json_response(text)
    assert r == "green"
    assert "match" in e.lower()


def test_parse_judge_json_fenced():
    text = '```json\n{"rating": "amber", "explanation": "Minor gap."}\n```'
    r, e = _parse_judge_json_response(text)
    assert r == "amber"


def test_parse_judge_regex_fallback():
    text = 'something {"rating": "red", "explanation": "Wrong total."} trailing'
    r, e = _parse_judge_json_response(text)
    assert r == "red"
