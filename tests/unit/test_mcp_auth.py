"""Tests for the dual-token MCP auth helper."""

from unittest.mock import MagicMock, patch

import pytest

from src.api.mcp_auth import (
    MCPAuthError,
    extract_mcp_identity,
    mcp_auth_scope,
)


class _FakeRequest:
    """Minimal Request stand-in with a headers dict."""

    def __init__(self, headers: dict):
        self.headers = headers


@pytest.fixture
def fake_user_client():
    client = MagicMock()
    me = MagicMock()
    me.id = "user-abc"
    me.user_name = "alice@example.com"
    client.current_user.me.return_value = me
    return client


# ---- extract_mcp_identity -------------------------------------------------


def test_extracts_from_x_forwarded_access_token_when_present(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok-xfa"})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.user_id == "user-abc"
    assert identity.user_name == "alice@example.com"
    assert identity.token == "tok-xfa"
    assert identity.source == "x-forwarded-access-token"


def test_falls_back_to_authorization_bearer(fake_user_client):
    req = _FakeRequest(headers={"authorization": "Bearer tok-bearer"})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-bearer"
    assert identity.source == "authorization-bearer"


def test_x_forwarded_wins_over_authorization_when_both_present(fake_user_client):
    req = _FakeRequest(
        headers={
            "x-forwarded-access-token": "tok-xfa",
            "authorization": "Bearer tok-bearer",
        }
    )
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-xfa"
    assert identity.source == "x-forwarded-access-token"


def test_raises_on_missing_credentials():
    req = _FakeRequest(headers={})
    with pytest.raises(MCPAuthError) as exc:
        extract_mcp_identity(req)
    msg = str(exc.value).lower()
    assert "authentication" in msg or "credentials" in msg


def test_raises_on_malformed_authorization_header():
    req = _FakeRequest(headers={"authorization": "Basic abcd"})
    with pytest.raises(MCPAuthError):
        extract_mcp_identity(req)


def test_raises_when_identity_resolution_fails():
    req = _FakeRequest(headers={"authorization": "Bearer tok-bad"})
    bad_client = MagicMock()
    bad_client.current_user.me.side_effect = Exception("token invalid")
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=bad_client,
    ):
        with pytest.raises(MCPAuthError):
            extract_mcp_identity(req)


def test_bearer_extraction_trims_whitespace(fake_user_client):
    req = _FakeRequest(headers={"authorization": "Bearer    tok-spaced   "})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-spaced"


# ---- mcp_auth_scope context manager --------------------------------------


def test_scope_sets_and_clears_context_vars(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch("src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client), \
         patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with mcp_auth_scope(req) as identity:
            assert identity.user_name == "alice@example.com"

        # After exit: all three setters were called with None for teardown
        assert set_user.call_args_list[-1].args[0] is None
        assert set_client.call_args_list[-1].args[0] is None
        assert set_perm.call_args_list[-1].args[0] is None


def test_scope_clears_context_even_on_exception(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch("src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client), \
         patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with pytest.raises(RuntimeError):
            with mcp_auth_scope(req):
                raise RuntimeError("boom")

        # Context was still cleared
        assert set_user.call_args_list[-1].args[0] is None
        assert set_client.call_args_list[-1].args[0] is None
        assert set_perm.call_args_list[-1].args[0] is None


def test_mcp_identity_repr_does_not_leak_token():
    """The dataclass repr must not include the raw bearer token, so the
    identity object is safe to log even if someone writes
    ``logger.info("id=%s", identity)`` in the future."""
    from src.api.mcp_auth import MCPIdentity
    identity = MCPIdentity(
        user_id="u-1",
        user_name="alice@example.com",
        token="super-secret-bearer-token",
        source="authorization-bearer",
    )
    rendered = repr(identity)
    assert "super-secret-bearer-token" not in rendered
    # user_name and source still in repr (useful for debugging)
    assert "alice@example.com" in rendered
    assert "authorization-bearer" in rendered
