"""Join the client's verdict and draft readiness contract to the server's (#268 C17, C22).

The readiness wire (``DraftReadinessResponse``, ``AgentReadinessResponse``,
``TestCaseReadinessResponse``), the verdict body (``VerdictRequest``) and its refusals
are owned by ``src/api/schemas/agent_definitions.py`` and
``src/api/routes/agent_definitions.py``. The client holds hand copies in
``frontend/src/api/agentDefinitions.ts`` that nothing typechecks against the server, and
the fixtures Vitest and Playwright serve live in ``frontend/tests/fixtures/mocks.ts``, so
this module reads them as text, as ``test_test_run_failure_contract_client_join.py`` does.

Text-read rules for those lines (keep them, or this join cannot read them):

* ``const DRAFT_READINESS_KEYS = [``, ``const AGENT_READINESS_KEYS = [``,
  ``const TEST_CASE_READINESS_KEYS = [``, ``const READINESS_STATUSES: readonly
  ReadinessStatus[] = [``, ``const VERDICT_REQUEST_KEYS = [`` and
  ``const INELIGIBILITY_REASONS: readonly TestRunIneligibilityReason[] = [`` each appear
  exactly once and list single-quoted names up to the closing ``]``.
* ``export const TEST_RUN_NOT_FOUND_DETAIL = '<text>';`` is one line.
* In ``mocks.ts``, ``syntheticVerdictIneligible`` keeps its single-quoted messages (one per reason).

The wire is snake_case codes, never display labels (C17): the client owns the labels.
"""

from __future__ import annotations

import pathlib
import re
from typing import get_args

from src.api.routes import agent_definitions as routes
from src.api.schemas import agent_definitions as schemas

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_API = _REPO_ROOT / "frontend" / "src" / "api" / "agentDefinitions.ts"
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"
_QUOTED = re.compile(r"'([^'\\\n]*)'")
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"client source missing: {path}"
    return path.read_text(encoding="utf-8")


def _block(source: str, opening: str, closing: str) -> str:
    assert source.count(opening) == 1, f"expected exactly one {opening.strip()!r}"
    start = source.index(opening) + len(opening)
    return source[start : source.index(closing, start)]


def _names(source: str, opening: str) -> list[str]:
    return _QUOTED.findall(_block(source, opening, "]"))


def _unique_names(opening: str) -> list[str]:
    names = _names(_read(_CLIENT_API), opening)
    assert names, f"no names under {opening.strip()!r}"
    assert len(names) == len(set(names)), names
    return names


def test_the_client_draft_readiness_keys_are_exactly_the_server_fields() -> None:
    client = _unique_names("\nconst DRAFT_READINESS_KEYS = [")
    assert set(client) == set(schemas.DraftReadinessResponse.model_fields)


def test_the_client_agent_readiness_keys_are_exactly_the_server_fields() -> None:
    client = _unique_names("\nconst AGENT_READINESS_KEYS = [")
    assert set(client) == set(schemas.AgentReadinessResponse.model_fields)
    assert "missing_required_case" in client


def test_the_client_case_readiness_keys_are_exactly_the_server_fields() -> None:
    client = _unique_names("\nconst TEST_CASE_READINESS_KEYS = [")
    assert set(client) == set(schemas.TestCaseReadinessResponse.model_fields)


def test_the_readiness_wire_is_strict_snake_case_on_both_sides() -> None:
    for model, opening in (
        (schemas.DraftReadinessResponse, "\nconst DRAFT_READINESS_KEYS = ["),
        (schemas.AgentReadinessResponse, "\nconst AGENT_READINESS_KEYS = ["),
        (schemas.TestCaseReadinessResponse, "\nconst TEST_CASE_READINESS_KEYS = ["),
    ):
        assert model.model_config.get("extra") == "forbid", model.__name__
        for name in _unique_names(opening):
            assert _SNAKE_CASE.match(name), name


def test_the_client_readiness_statuses_are_the_server_codes_not_labels() -> None:
    client = _unique_names("\nconst READINESS_STATUSES: readonly ReadinessStatus[] = [")
    annotation = schemas.TestCaseReadinessResponse.model_fields["status"].annotation
    assert set(client) == set(get_args(annotation))
    assert set(client) == {"needs_test", "test_failed", "awaiting_review", "approved"}


def test_the_client_verdict_body_is_exactly_the_server_request() -> None:
    client = _unique_names("\nconst VERDICT_REQUEST_KEYS = [")
    assert set(client) == set(schemas.VerdictRequest.model_fields) == {"verdict", "notes"}
    assert schemas.VerdictRequest.model_config.get("extra") == "forbid"
    # `notes` is required (it may be null): the client must always send it.
    assert schemas.VerdictRequest.model_fields["notes"].is_required()


def test_the_client_ineligibility_reasons_and_codes_are_the_servers() -> None:
    source = _read(_CLIENT_API)
    reasons = _unique_names(
        "\nconst INELIGIBILITY_REASONS: readonly TestRunIneligibilityReason[] = ["
    )
    fields = schemas.IneligibleForApprovalResponse.model_fields
    assert set(reasons) == set(get_args(fields["reason"].annotation))
    assert set(reasons) == set(routes._INELIGIBLE_MESSAGES)
    for field, model in (
        ("code", schemas.IneligibleForApprovalResponse),
        ("code", schemas.VerdictValidationErrorResponse),
    ):
        (code,) = get_args(model.model_fields[field].annotation)
        assert f"'{code}'" in source, code
    assert set(schemas.IneligibleForApprovalResponse.model_fields) == {"code", "reason", "message"}
    assert set(schemas.VerdictValidationErrorResponse.model_fields) == {"code", "errors"}


def test_the_client_404_detail_is_the_route_detail() -> None:
    line = re.search(
        r"^export const TEST_RUN_NOT_FOUND_DETAIL = '([^'\\\n]*)';$",
        _read(_CLIENT_API),
        re.MULTILINE,
    )
    assert line is not None
    assert line.group(1) == routes._test_run_not_found().detail


def test_the_served_ineligible_fixture_carries_the_route_messages() -> None:
    block = _block(
        _read(_CLIENT_MOCKS),
        "\nexport function syntheticVerdictIneligible(",
        "\n}\n",
    )
    for message in routes._INELIGIBLE_MESSAGES.values():
        assert f"'{message}'" in block, message
