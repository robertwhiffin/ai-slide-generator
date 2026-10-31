"""Missing-scope detection, the OAuth client id read from a token, and the consent copy.

The positive texts are real: the recorded SDK error in
``tests/fixtures/genie_one/error_missing_scope_sdk.json`` and the staging log line.
"""

from __future__ import annotations

import base64
import importlib
import json
import threading
from pathlib import Path

import pytest
from databricks.sdk.errors.platform import NotFound, PermissionDenied

from src.core.scope_errors import (
    consent_message,
    is_missing_scope_error,
    mentions_missing_scope,
    oauth_client_id_from_token,
    oauth_scopes_from_token,
    scopes_grant,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "genie_one" / "error_missing_scope_sdk.json"

STAGING_TEXT = "Provided OAuth token does not have required scopes: unity-catalog"


def _fixture_error() -> BaseException:
    """Rebuild the recorded SDK exception from the fixture's own class path and message."""
    recorded = json.loads(FIXTURE.read_text())
    module_name, _, class_name = recorded["exception_class"].rpartition(".")
    exc_class = getattr(importlib.import_module(module_name), class_name)
    assert exc_class is PermissionDenied
    return exc_class(recorded["message"])


def _staging_error() -> BaseException:
    return PermissionDenied(STAGING_TEXT)


POSITIVE_FACTORIES = {
    "fixture_sdk_error": _fixture_error,
    "staging_log_text": _staging_error,
}


# ---------------------------------------------------------------------------
# is_missing_scope_error: positives
# ---------------------------------------------------------------------------


class TestMissingScopePositives:
    @pytest.mark.parametrize("make", POSITIVE_FACTORIES.values(), ids=POSITIVE_FACTORIES.keys())
    def test_direct(self, make):
        assert is_missing_scope_error(make()) is True

    @pytest.mark.parametrize("make", POSITIVE_FACTORIES.values(), ids=POSITIVE_FACTORIES.keys())
    def test_wrapped_as_cause(self, make):
        inner = make()
        try:
            try:
                raise inner
            except PermissionDenied as e:
                raise RuntimeError("MCP call failed") from e
        except RuntimeError as outer:
            assert outer.__cause__ is inner
            assert is_missing_scope_error(outer) is True

    @pytest.mark.parametrize("make", POSITIVE_FACTORIES.values(), ids=POSITIVE_FACTORIES.keys())
    def test_wrapped_as_context(self, make):
        inner = make()
        try:
            try:
                raise inner
            except PermissionDenied:
                raise RuntimeError("tool call failed while handling")
        except RuntimeError as outer:
            assert outer.__cause__ is None
            assert outer.__context__ is inner
            assert is_missing_scope_error(outer) is True

    @pytest.mark.parametrize("make", POSITIVE_FACTORIES.values(), ids=POSITIVE_FACTORIES.keys())
    def test_inside_exception_group(self, make):
        group = ExceptionGroup("unhandled errors in a TaskGroup", [ValueError("other"), make()])
        assert is_missing_scope_error(group) is True

    def test_deeply_nested_group_cause_and_context(self):
        """Group -> nested group -> wrapper whose __cause__ -> wrapper whose __context__ -> scope error."""
        scope = _fixture_error()
        try:
            try:
                raise scope
            except PermissionDenied:
                raise OSError("transport closed")
        except OSError as with_context:
            middle = with_context
        try:
            raise RuntimeError("session failed") from middle
        except RuntimeError as with_cause:
            leaf = with_cause
        group = ExceptionGroup(
            "outer",
            [KeyError("k"), ExceptionGroup("inner", [TypeError("t"), leaf])],
        )
        assert is_missing_scope_error(group) is True

    def test_matching_is_case_insensitive(self):
        assert is_missing_scope_error(RuntimeError("INVALID SCOPE for this token")) is True
        assert is_missing_scope_error(RuntimeError("Token lacks Required Scopes: sql")) is True


# ---------------------------------------------------------------------------
# is_missing_scope_error: negatives
# ---------------------------------------------------------------------------


class TestMissingScopeNegatives:
    def test_plain_permission_denied_is_not_a_scope_error(self):
        exc = PermissionDenied("User does not have USE CONNECTION on connection x")
        assert is_missing_scope_error(exc) is False

    def test_plain_runtime_error(self):
        assert is_missing_scope_error(RuntimeError("boom")) is False

    def test_not_found(self):
        exc = NotFound("Connection 'x' does not exist.")
        assert is_missing_scope_error(exc) is False

    def test_chain_and_group_without_a_scope_message(self):
        try:
            try:
                raise PermissionDenied("User does not have USE CONNECTION on connection x")
            except PermissionDenied as e:
                raise RuntimeError("wrapped") from e
        except RuntimeError as outer:
            group = ExceptionGroup("g", [outer, NotFound("missing")])
        assert is_missing_scope_error(group) is False

    def test_cyclic_chain_terminates(self):
        """A __context__ cycle must not hang or recurse forever."""
        a = RuntimeError("a")
        b = ValueError("b")
        a.__context__ = b
        b.__context__ = a

        outcome: dict = {}

        def run():
            try:
                outcome["value"] = is_missing_scope_error(a)
            except BaseException as exc:  # noqa: BLE001 - record and fail below
                outcome["raised"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "is_missing_scope_error did not terminate on a cyclic chain"
        assert "raised" not in outcome, f"raised {outcome.get('raised')!r}"
        assert outcome["value"] is False


# ---------------------------------------------------------------------------
# oauth_client_id_from_token
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload) -> str:
    """Hand-built unsigned JWT: header.payload.signature, base64url without padding."""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{header}.{body}.c2lnbmF0dXJl"


# The value makes the encoded payload contain base64url-only characters ('-' / '_')
# and need padding, so a standard-alphabet or padding-strict decoder fails.
_URLSAFE_FILLER = "ûÿþ?>>?"


class TestOAuthClientIdFromToken:
    def test_client_id_claim(self):
        token = _jwt({"client_id": "tellr-app-1234", "sub": "user@example.com", "x": _URLSAFE_FILLER})
        payload_segment = token.split(".")[1]
        assert "=" not in payload_segment
        assert len(payload_segment) % 4 != 0
        assert "-" in payload_segment or "_" in payload_segment
        assert oauth_client_id_from_token(token) == "tellr-app-1234"

    def test_azp_claim_when_no_client_id(self):
        token = _jwt({"azp": "azp-client-5678", "sub": "user@example.com"})
        assert oauth_client_id_from_token(token) == "azp-client-5678"

    def test_client_id_preferred_over_azp(self):
        token = _jwt({"client_id": "from-client-id", "azp": "from-azp"})
        assert oauth_client_id_from_token(token) == "from-client-id"

    def test_jwt_without_either_claim(self):
        assert oauth_client_id_from_token(_jwt({"sub": "user@example.com"})) is None

    @pytest.mark.parametrize(
        "token",
        [
            "dapi123",
            None,
            "",
            "garbage",
            "not.a.jwt",
            "a.b",
            "header.!!!not-base64!!!.sig",
            f"{_b64url(b'{}')}.{_b64url(b'this is not json')}.sig",
            _jwt(["a", "list", "payload"]),
            _jwt("a string payload"),
        ],
        ids=[
            "pat",
            "none",
            "empty",
            "garbage",
            "three_junk_segments",
            "two_segments",
            "bad_base64",
            "payload_not_json",
            "payload_is_list",
            "payload_is_string",
        ],
    )
    def test_non_jwt_inputs_give_none_without_raising(self, token):
        assert oauth_client_id_from_token(token) is None


# ---------------------------------------------------------------------------
# oauth_scopes_from_token, scopes_grant, mentions_missing_scope (final fix I1)
# ---------------------------------------------------------------------------


class TestOAuthScopesFromToken:
    def test_space_separated_scope_claim(self):
        # The shape a Databricks OAuth token carries (decoded from real CLI tokens).
        token = _jwt({"scope": "ai-gateway catalog.connections offline_access", "x": _URLSAFE_FILLER})
        assert oauth_scopes_from_token(token) == frozenset(
            {"ai-gateway", "catalog.connections", "offline_access"}
        )

    def test_list_scope_claim(self):
        token = _jwt({"scope": ["sql", "ai-gateway"]})
        assert oauth_scopes_from_token(token) == frozenset({"sql", "ai-gateway"})

    def test_scp_claim_when_no_scope(self):
        assert oauth_scopes_from_token(_jwt({"scp": "sql dashboards.genie"})) == frozenset(
            {"sql", "dashboards.genie"}
        )
        assert oauth_scopes_from_token(_jwt({"scp": ["all-apis"]})) == frozenset({"all-apis"})

    def test_scope_preferred_over_scp(self):
        assert oauth_scopes_from_token(_jwt({"scope": "sql", "scp": "ai-gateway"})) == frozenset(
            {"sql"}
        )

    def test_extra_whitespace_and_non_string_list_items_are_ignored(self):
        assert oauth_scopes_from_token(_jwt({"scope": "  sql   ai-gateway "})) == frozenset(
            {"sql", "ai-gateway"}
        )
        assert oauth_scopes_from_token(_jwt({"scope": ["sql", 7, None]})) == frozenset({"sql"})

    @pytest.mark.parametrize(
        "payload",
        [
            {"sub": "user@example.com"},
            {"scope": ""},
            {"scope": "   "},
            {"scope": []},
            {"scope": 42},
            {"scope": None, "scp": {"a": 1}},
        ],
        ids=["absent", "empty", "blank", "empty_list", "number", "neither_usable"],
    )
    def test_a_claim_naming_no_scope_is_unknown(self, payload):
        # Unknown, not "no scopes": callers act only on a known set.
        assert oauth_scopes_from_token(_jwt(payload)) is None

    @pytest.mark.parametrize(
        "token",
        [
            "dapi123",
            None,
            "",
            "not.a.jwt",
            "a.b",
            "header.!!!not-base64!!!.sig",
            f"{_b64url(b'{}')}.{_b64url(b'this is not json')}.sig",
            _jwt(["scope", "sql"]),
            _jwt("scope sql"),
        ],
        ids=[
            "pat",
            "none",
            "empty",
            "three_junk_segments",
            "two_segments",
            "bad_base64",
            "payload_not_json",
            "payload_is_list",
            "payload_is_string",
        ],
    )
    def test_non_jwt_inputs_give_none_without_raising(self, token):
        assert oauth_scopes_from_token(token) is None


class TestScopesGrant:
    def test_the_scope_itself(self):
        assert scopes_grant(frozenset({"sql", "ai-gateway"}), "ai-gateway")

    def test_all_apis_holds_every_scope(self):
        # A full CLI token carries "all-apis offline_access" and no ai-gateway.
        assert scopes_grant(frozenset({"all-apis", "offline_access"}), "ai-gateway")

    def test_a_set_without_it(self):
        assert not scopes_grant(frozenset({"sql", "offline_access"}), "ai-gateway")
        assert not scopes_grant(frozenset(), "ai-gateway")


class TestMentionsMissingScope:
    @pytest.mark.parametrize(
        "text",
        [
            "Invalid scope, required scopes: ai-gateway",
            "403 Forbidden: INVALID SCOPE",
            STAGING_TEXT,
        ],
    )
    def test_scope_texts(self, text):
        assert mentions_missing_scope(text)

    @pytest.mark.parametrize("text", ["", "403 Forbidden", "PERMISSION_DENIED: no EXECUTE"])
    def test_other_texts(self, text):
        assert not mentions_missing_scope(text)


# ---------------------------------------------------------------------------
# consent_message
# ---------------------------------------------------------------------------

_CONSENT_TEMPLATE = (
    "Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.\n"
    "\n"
    "There are two possible causes:\n"
    "1. The app itself hasn't been given the permission. A workspace admin fixes this by running tellr.update() for this app.\n"
    "2. You approved this app before it needed this permission. To approve it again:\n"
    "   a. Run: databricks api delete /api/2.0/oauth-app-integrations/{client_id}/user-consent/me\n"
    "   b. Clear this site's data in your browser, or open the app in a private window.\n"
    "   c. Reload the app and approve the new permissions when asked."
)


class TestConsentMessage:
    def test_exact_text_with_client_id(self):
        expected = _CONSENT_TEMPLATE.replace("{client_id}", "tellr-app-1234")
        assert consent_message(oauth_client_id="tellr-app-1234") == expected

    def test_exact_text_without_client_id(self):
        expected = _CONSENT_TEMPLATE.replace("{client_id}", "<this app's OAuth client ID>")
        assert consent_message(oauth_client_id=None) == expected

    def test_client_id_is_keyword_only(self):
        with pytest.raises(TypeError):
            consent_message("tellr-app-1234")  # type: ignore[misc]
