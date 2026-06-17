"""Tests for the output self-reflection safety gate (AISEC-248 PR2)."""

from src.services.evaluation.self_reflection import parse_reflection_verdict, is_reflection_enabled


def test_parse_safe_verdict():
    safe, reasons = parse_reflection_verdict('{"safe": true, "reasons": []}')
    assert safe is True and reasons == []


def test_parse_unsafe_verdict():
    safe, reasons = parse_reflection_verdict('{"safe": false, "reasons": ["external url"]}')
    assert safe is False and "external url" in reasons


def test_parse_handles_fenced_json():
    safe, _ = parse_reflection_verdict('```json\n{"safe": true, "reasons": []}\n```')
    assert safe is True


def test_parse_failopen_on_garbage():
    # Unparseable verdict must not block generation (fail-open with a logged reason).
    safe, reasons = parse_reflection_verdict("the model rambled")
    assert safe is True


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("TELLR_SELF_REFLECTION_ENABLED", "false")
    assert is_reflection_enabled() is False
