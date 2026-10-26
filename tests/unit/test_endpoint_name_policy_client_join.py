"""Join the client's local endpoint-name policy to the server's (#266 correction 18).

The client mirrors ``validate_endpoint_name_policy`` so a URL- or path-shaped name is
refused locally with zero PUT. Nothing typechecks the two against each other, so this
module reads the client sources as text:

* ``frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts``: the
  ``ENDPOINT_URL_PREFIX`` and ``ENDPOINT_PATH_METACHARACTERS`` regex-literal lines, the
  control-character line in ``hasAsciiControlCharacter``, the ``endpointNamePolicyError``
  condition, the ``validateDraftForm`` call, and ``ENDPOINT_URL_NOT_ALLOWED_MESSAGE``.
* ``frontend/tests/fixtures/mocks.ts``: the strict-JSON ``ENDPOINT_NAME_POLICY_CASES``
  block, which the client's Vitest policy table also drives.

The regex literals are pinned to the server patterns, and then every shared case is
decided three ways: by the server function, by the pinned client rules evaluated here,
and by the table's expected verdict. All three must agree.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from src.services import model_endpoint_catalog
from src.services.model_endpoint_catalog import (
    EndpointValidationFailure,
    validate_endpoint_name_policy,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_POLICY = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "Admin"
    / "AgentDefinitionWorkbench"
    / "draftEditorState.ts"
)
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"

_TS_REGEX_LINE = r"^const {name} = /(?P<source>.*)/(?P<flags>[a-z]*);$"
_TS_CONTROL_RULE = "if (code <= 0x1f || code === 0x7f) return true;"
_TS_POLICY_CONDITION = (
    "  if (ENDPOINT_URL_PREFIX.test(name)\n"
    "    || ENDPOINT_PATH_METACHARACTERS.test(name)\n"
    "    || hasAsciiControlCharacter(name)\n"
    "    || name === '.'\n"
    "    || name === '..') {\n"
    "    return ENDPOINT_URL_NOT_ALLOWED_MESSAGE;\n"
)
_TS_VALIDATE_CALL = "endpointNamePolicyError(form.endpoint_name)"


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"client source missing: {path}"
    return path.read_text(encoding="utf-8")


def _ts_regex(source: str, name: str) -> tuple[str, str]:
    matches = re.findall(
        _TS_REGEX_LINE.format(name=re.escape(name)), source, flags=re.MULTILINE
    )
    assert len(matches) == 1, f"expected exactly one `const {name} = /.../;` line"
    return matches[0]


def _cases() -> dict[str, list[str]]:
    source = _read(_CLIENT_MOCKS)
    start = source.index("export const ENDPOINT_NAME_POLICY_CASES:")
    opening = source.index("= {", start) + 2
    closing = source.index("\n};", opening)
    cases = json.loads(source[opening : closing + 2])
    assert set(cases) == {"rejected", "accepted"}
    assert cases["rejected"] and cases["accepted"]
    assert not set(cases["rejected"]) & set(cases["accepted"])
    return cases


def _server_rejects(name: str) -> bool:
    try:
        validate_endpoint_name_policy(name)
    except EndpointValidationFailure as failure:
        assert failure.code == "endpoint_url_not_allowed"
        return True
    return False


def _client_rejects(name: str) -> bool:
    """Evaluate the client's pinned rules exactly as ``endpointNamePolicyError`` does."""
    source = _read(_CLIENT_POLICY)
    url_source, url_flags = _ts_regex(source, "ENDPOINT_URL_PREFIX")
    meta_source, meta_flags = _ts_regex(source, "ENDPOINT_PATH_METACHARACTERS")
    url = re.compile(url_source, re.IGNORECASE if "i" in url_flags else 0)
    meta = re.compile(meta_source, re.IGNORECASE if "i" in meta_flags else 0)
    return bool(
        url.search(name)
        or meta.search(name)
        or any(ord(char) <= 0x1F or ord(char) == 0x7F for char in name)
        or name in {".", ".."}
    )


def test_client_url_prefix_literal_is_the_server_pattern():
    url_source, url_flags = _ts_regex(_read(_CLIENT_POLICY), "ENDPOINT_URL_PREFIX")
    # A JS regex literal escapes `/` as `\/`; the server pattern writes it bare.
    assert url_source.replace("\\/", "/") == model_endpoint_catalog._URL_PREFIX.pattern
    assert url_flags == "i"
    assert model_endpoint_catalog._URL_PREFIX.flags & re.IGNORECASE


def test_client_metacharacter_literal_plus_control_rule_is_the_server_class():
    source = _read(_CLIENT_POLICY)
    meta_source, meta_flags = _ts_regex(source, "ENDPOINT_PATH_METACHARACTERS")
    assert meta_flags == ""
    # The client keeps control characters out of the regex (ESLint no-control-regex)
    # and checks them in `hasAsciiControlCharacter`; together they are the server class.
    assert meta_source.endswith("]")
    assert (
        meta_source[:-1] + r"\x00-\x1f\x7f]"
        == model_endpoint_catalog._PATH_METACHARACTERS.pattern
    )
    assert source.count(_TS_CONTROL_RULE) == 1


def test_client_dot_segments_condition_and_message_are_the_server_policy():
    source = _read(_CLIENT_POLICY)
    assert source.count(_TS_POLICY_CONDITION) == 1
    assert model_endpoint_catalog._DOT_SEGMENTS == frozenset({".", ".."})
    assert source.count(_TS_VALIDATE_CALL) == 1

    messages = re.findall(
        r"^export const ENDPOINT_URL_NOT_ALLOWED_MESSAGE = '([^'\\]*)';$",
        source,
        flags=re.MULTILINE,
    )
    with pytest.raises(EndpointValidationFailure) as failure:
        validate_endpoint_name_policy("a/b")
    assert messages == [failure.value.message]
    assert failure.value.retryable is False


@pytest.mark.parametrize("name", _cases()["rejected"])
def test_every_shared_rejected_case_is_rejected_by_both_policies(name):
    assert _server_rejects(name), f"server accepted {name!r}"
    assert _client_rejects(name), f"client rules accepted {name!r}"


@pytest.mark.parametrize("name", _cases()["accepted"])
def test_every_shared_accepted_case_is_accepted_verbatim_by_both_policies(name):
    assert not _server_rejects(name), f"server rejected {name!r}"
    assert not _client_rejects(name), f"client rules rejected {name!r}"
