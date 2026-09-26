"""Join the client's Agent Test Case and test run contract to the server's (#267).

The case and run DTOs, the refusal codes and the 503 body are owned by the server:
``src/api/schemas/agent_definitions.py`` and ``src/api/routes/agent_definitions.py``.
The client holds hand copies in ``frontend/src/api/agentDefinitions.ts`` that nothing
typechecks against the server, and the fixtures Vitest and Playwright serve live in
``frontend/tests/fixtures/mocks.ts``, so this module reads them as text (C38).

Text-read rules for those lines (keep them, or this join cannot read them):

* ``const TEST_CASE_KEYS = [``, ``const TEST_RUN_KEYS = [``, ``const TEST_RUN_KINDS``,
  ``const TEST_RUN_STATUSES``, ``const TEST_RUN_VERDICTS`` and
  ``const DETERMINISTIC_CHECK_NAMES`` each appear
  exactly once and list single-quoted names up to the closing ``];``.
* ``export const TEST_RUN_UNAVAILABLE = {`` is closed by ``} as const;`` with the
  exact lines ``  code: '<code>',``, ``  message: '<text>',`` and ``  retryable: true,``.
* ``export const TEST_CASE_NOT_FOUND_DETAIL = '<text>';`` is one line.
* In ``mocks.ts``, ``syntheticTestRunUnavailable`` and ``syntheticStaleTestCase`` keep
  their single-quoted ``message: '<text>',`` lines.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import get_args

from src.api.routes import agent_definitions as routes
from src.api.schemas import agent_definitions as schemas
from src.services.agent_test_workbench import TestCaseStale

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_API = _REPO_ROOT / "frontend" / "src" / "api" / "agentDefinitions.ts"
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"
_QUOTED = re.compile(r"'([^'\\\n]*)'")


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"client source missing: {path}"
    return path.read_text(encoding="utf-8")


def _block(source: str, opening: str, closing: str) -> str:
    assert source.count(opening) == 1, f"expected exactly one {opening.strip()!r}"
    start = source.index(opening) + len(opening)
    return source[start : source.index(closing, start)]


def _names(source: str, opening: str) -> list[str]:
    return _QUOTED.findall(_block(source, opening, "]"))


def _literal_values(annotation: object) -> set[str]:
    return set(get_args(annotation))


def test_the_client_case_keys_are_exactly_the_server_case_response_fields() -> None:
    client = _names(_read(_CLIENT_API), "\nconst TEST_CASE_KEYS = [")
    assert len(client) == len(set(client))
    assert set(client) == set(schemas.TestCaseResponse.model_fields)


def test_the_client_run_keys_are_exactly_the_server_evidence_fields() -> None:
    client = _names(_read(_CLIENT_API), "\nconst TEST_RUN_KEYS = [")
    assert len(client) == len(set(client))
    assert set(client) == set(schemas.TestRunEvidenceResponse.model_fields)
    # #268 C16: the four verdict keys are required on both sides of the wire.
    assert {key for key in client if key.startswith("verdict")} == {
        "verdict",
        "verdict_reviewer",
        "verdict_at",
        "verdict_notes",
    }


def test_the_client_verdict_choices_are_the_servers() -> None:
    source = _read(_CLIENT_API)
    annotation = schemas.TestRunEvidenceResponse.model_fields["verdict"].annotation
    server = {value for arg in get_args(annotation) for value in get_args(arg)}
    assert server == {"approved", "rejected"}
    assert set(_names(source, "\nconst TEST_RUN_VERDICTS: readonly TestRunVerdict[] = [")) == server


def test_the_client_run_kinds_statuses_and_check_names_are_the_servers() -> None:
    source = _read(_CLIENT_API)
    fields = schemas.TestRunEvidenceResponse.model_fields
    assert set(
        _names(source, "\nconst TEST_RUN_KINDS: readonly TestRunKind[] = [")
    ) == _literal_values(fields["run_kind"].annotation)
    assert set(
        _names(source, "\nconst TEST_RUN_STATUSES: readonly TestRunExecutionStatus[] = [")
    ) == _literal_values(fields["execution_status"].annotation)
    check_names = _names(
        source,
        "\nconst DETERMINISTIC_CHECK_NAMES: readonly DeterministicCheckResult['name'][] = [",
    )
    assert set(check_names) == _literal_values(
        schemas.DeterministicCheckResultResponse.model_fields["name"].annotation
    )


def test_the_client_503_body_is_the_route_body() -> None:
    block = _block(_read(_CLIENT_API), "\nexport const TEST_RUN_UNAVAILABLE = {\n", "\n} as const;")
    lines = block.splitlines()
    assert lines == [
        "  code: 'test_run_unavailable',",
        f"  message: '{routes._TEST_RUN_UNAVAILABLE_MESSAGE}',",
        "  retryable: true,",
    ]
    body = json.loads(routes._test_run_unavailable_response().body)
    assert body == {
        "code": "test_run_unavailable",
        "message": routes._TEST_RUN_UNAVAILABLE_MESSAGE,
        "retryable": True,
    }


def test_the_client_404_detail_is_the_route_detail() -> None:
    line = re.search(
        r"^export const TEST_CASE_NOT_FOUND_DETAIL = '([^'\\\n]*)';$",
        _read(_CLIENT_API),
        re.MULTILINE,
    )
    assert line is not None
    assert line.group(1) == routes._test_case_not_found().detail


def test_the_client_refusal_codes_are_the_servers() -> None:
    source = _read(_CLIENT_API)
    server_codes = {
        *_literal_values(schemas.DraftSaveConflictResponse.model_fields["code"].annotation),
        *_literal_values(schemas.TestCaseConflictResponse.model_fields["code"].annotation),
        *_literal_values(schemas.DraftValidationErrorResponse.model_fields["code"].annotation),
        *_literal_values(schemas.TestCaseValidationErrorResponse.model_fields["code"].annotation),
    }
    assert server_codes == {"stale_draft", "stale_test_case", "invalid_draft", "invalid_test_case"}
    for code in server_codes:
        assert f"'{code}'" in source, code


def test_the_served_fixtures_carry_the_route_messages() -> None:
    mocks = _read(_CLIENT_MOCKS)
    unavailable = _block(mocks, "\nexport function syntheticTestRunUnavailable() {\n", "\n}\n")
    assert f"message: '{routes._TEST_RUN_UNAVAILABLE_MESSAGE}'," in unavailable
    stale = _block(mocks, "\nexport function syntheticStaleTestCase(testCaseId = 101) {\n", "\n}\n")
    body = json.loads(routes._test_case_stale_response(TestCaseStale(101)).body)
    assert f"message: '{body['message']}'," in stale
