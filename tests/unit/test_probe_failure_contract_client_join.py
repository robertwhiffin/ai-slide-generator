"""Join the client's structured-output probe failure contract to the server's (#266).

The probe's failure table is owned by the server: the code, message and retryable
flag by ``src/services/model_endpoint_probe.py`` and the HTTP status by the route's
``_PROBE_FAILURE_STATUS``.  The client holds two hand copies that nothing
typechecks against the server, so this module reads them as text:

* ``frontend/src/api/agentDefinitions.ts``: the ``StructuredOutputProbeFailureCode``
  union, the ``PROBE_FAILURE_CONTRACT`` status table (status, code, retryable) that
  the strict parser checks every failure body against, and the parser's status guard.
* ``frontend/tests/fixtures/mocks.ts``: the ``STRUCTURED_OUTPUT_PROBE_FAILURES``
  fixture (status, message, retryable per code) that Vitest and Playwright serve.

Text-read rules for those lines (keep them, or this join cannot read them):

* ``PROBE_FAILURE_CONTRACT`` stays ``const PROBE_FAILURE_CONTRACT = {`` closed by
  ``} as const;``, one entry per line in the exact form
  ``  NNN: { code: '<code>', retryable: <true|false> },`` with no comments.
* ``StructuredOutputProbeFailureCode`` stays one ``  | '<code>'`` member per line,
  the last ending in ``;``.
* ``STRUCTURED_OUTPUT_PROBE_FAILURES`` stays ``export const ... = {`` closed by
  ``} as const;``; each entry is exactly the five lines ``  <code>: {``,
  ``    status: NNN,``, ``    message: '<text>',``, ``    retryable: <bool>,``,
  ``  },``.  Messages stay single-quoted with no apostrophe or backslash.
"""

from __future__ import annotations

import pathlib
import re
from typing import get_args

from src.api.routes import agent_definitions as routes
from src.services import model_endpoint_probe as probe

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_API = _REPO_ROOT / "frontend" / "src" / "api" / "agentDefinitions.ts"
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"

_CONTRACT_OPEN = "\nconst PROBE_FAILURE_CONTRACT = {\n"
_CONTRACT_LINE = re.compile(
    r"^  (?P<status>\d{3}): \{ code: '(?P<code>[a-z_]+)', "
    r"retryable: (?P<retryable>true|false) \},$"
)
_UNION_OPEN = "\nexport type StructuredOutputProbeFailureCode =\n"
_UNION_LINE = re.compile(r"^  \| '(?P<code>[a-z_]+)';?$")
_STATUS_GUARD = "  if (status !== 403 && status !== 422 && status !== 503) return null;\n"
_FIXTURE_OPEN = "\nexport const STRUCTURED_OUTPUT_PROBE_FAILURES = {\n"
_FIXTURE_ENTRY = re.compile(
    r"  (?P<code>[a-z_]+): \{\n"
    r"    status: (?P<status>\d{3}),\n"
    r"    message: '(?P<message>[^'\\\n]*)',\n"
    r"    retryable: (?P<retryable>true|false),\n"
    r"  \},\n"
)
_CLOSE = "\n} as const;"


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"client source missing: {path}"
    return path.read_text(encoding="utf-8")


def _block(source: str, opening: str, closing: str) -> str:
    assert source.count(opening) == 1, f"expected exactly one {opening.strip()!r}"
    start = source.index(opening) + len(opening)
    return source[start : source.index(closing, start) + 1]


def _server_table() -> dict[str, tuple[int, str, bool]]:
    """Each code's (status, message, retryable), exactly as the server emits it."""
    outcomes = (probe._UNSUPPORTED, probe._FORBIDDEN, probe._FAILED)
    codes = {code for code, _message, _retryable in outcomes}
    assert codes == set(get_args(probe.StructuredOutputProbeCode))
    assert codes == set(routes._PROBE_FAILURE_STATUS)
    return {
        code: (routes._PROBE_FAILURE_STATUS[code], message, retryable)
        for code, message, retryable in outcomes
    }


def _client_contract() -> dict[str, tuple[int, bool]]:
    lines = _block(_read(_CLIENT_API), _CONTRACT_OPEN, _CLOSE).splitlines()
    parsed = [_CONTRACT_LINE.match(line) for line in lines]
    assert all(parsed), f"unreadable PROBE_FAILURE_CONTRACT line in {lines!r}"
    contract = {
        match["code"]: (int(match["status"]), match["retryable"] == "true")
        for match in parsed
    }
    assert len(contract) == len(lines), "a probe failure code appears twice"
    return contract


def _client_fixture() -> dict[str, tuple[int, str, bool]]:
    body = _block(_read(_CLIENT_MOCKS), _FIXTURE_OPEN, _CLOSE)
    entries = list(_FIXTURE_ENTRY.finditer(body))
    assert "".join(entry.group(0) for entry in entries) == body, (
        "STRUCTURED_OUTPUT_PROBE_FAILURES has a line outside the five-line entry shape"
    )
    fixture = {
        entry["code"]: (
            int(entry["status"]),
            entry["message"],
            entry["retryable"] == "true",
        )
        for entry in entries
    }
    assert len(fixture) == len(entries), "a probe failure code appears twice"
    return fixture


def test_client_status_contract_is_the_server_status_and_retryable_table():
    server = _server_table()
    assert _client_contract() == {
        code: (status, retryable) for code, (status, _message, retryable) in server.items()
    }


def test_client_failure_code_union_and_status_guard_are_the_server_table():
    source = _read(_CLIENT_API)
    lines = _block(source, _UNION_OPEN, ";\n").splitlines()
    members = [_UNION_LINE.match(line) for line in lines]
    assert all(members), f"unreadable StructuredOutputProbeFailureCode line in {lines!r}"
    assert sorted(member["code"] for member in members) == sorted(_server_table())

    assert source.count(_STATUS_GUARD) == 1
    statuses = sorted(int(status) for status in re.findall(r"\d{3}", _STATUS_GUARD))
    assert statuses == sorted(status for status, _m, _r in _server_table().values())


def test_client_fixture_is_the_server_status_message_and_retryable_table():
    assert _client_fixture() == _server_table()
