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


# ---- Priority 3: x-forwarded-identity (app-to-app) ------------------------


def test_forwarded_identity_resolved_when_env_var_enabled(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    req = _FakeRequest(
        headers={
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "12345@99999",
        }
    )
    identity = extract_mcp_identity(req)

    assert identity.user_name == "alice@example.com"
    assert identity.user_id == "12345"
    assert identity.token is None
    assert identity.source == "x-forwarded-identity"


def test_forwarded_identity_rejected_when_env_var_disabled(monkeypatch):
    monkeypatch.delenv("TELLR_TRUST_FORWARDED_IDENTITY", raising=False)
    req = _FakeRequest(
        headers={
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "12345@99999",
        }
    )
    with pytest.raises(MCPAuthError):
        extract_mcp_identity(req)


def test_token_takes_precedence_over_forwarded_identity(
    monkeypatch, fake_user_client
):
    """Even with TELLR_TRUST_FORWARDED_IDENTITY on, a presented token wins."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    req = _FakeRequest(
        headers={
            "authorization": "Bearer tok-bearer",
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "12345@99999",
        }
    )
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-bearer"
    assert identity.source == "authorization-bearer"


def test_forwarded_identity_handles_malformed_user_header(monkeypatch):
    """x-forwarded-user without '@' yields user_id=None, not a crash."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    req = _FakeRequest(
        headers={
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "bare-user-id",  # no @workspace suffix
        }
    )
    identity = extract_mcp_identity(req)

    assert identity.user_name == "alice@example.com"
    assert identity.user_id is None
    assert identity.source == "x-forwarded-identity"


def test_forwarded_identity_requires_email(monkeypatch):
    """x-forwarded-user without x-forwarded-email is insufficient."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    req = _FakeRequest(headers={"x-forwarded-user": "12345@99999"})
    with pytest.raises(MCPAuthError):
        extract_mcp_identity(req)


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


# ---- HIGH-7 (SDR-4437): priority-3 header-only identity ---------------------


def _forwarded_identity_request():
    return _FakeRequest(
        headers={
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "12345@99999",
        }
    )


def test_scope_binds_no_client_for_forwarded_identity(monkeypatch):
    """Header-only identity must NOT bind the SP client (HIGH-7)."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")

    with patch("src.api.mcp_auth.get_or_create_user_client") as user_client_factory, \
         patch("src.api.mcp_auth.set_current_user"), \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context"):

        with mcp_auth_scope(_forwarded_identity_request()) as identity:
            assert identity.source == "x-forwarded-identity"
            assert identity.token is None

        user_client_factory.assert_not_called()
        # Every set_user_client call (entry AND teardown) bound None.
        assert all(c.args[0] is None for c in set_client.call_args_list)
        assert set_client.call_count >= 1


def test_scope_require_user_token_refuses_forwarded_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")

    with patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with pytest.raises(MCPAuthError, match="user access token"):
            with mcp_auth_scope(
                _forwarded_identity_request(), require_user_token=True
            ):
                pass  # pragma: no cover — must not be reached

        # Refused before binding anything.
        set_user.assert_not_called()
        set_client.assert_not_called()
        set_perm.assert_not_called()


def test_scope_require_user_token_allows_token_callers(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch(
        "src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client
    ), patch("src.api.mcp_auth.set_current_user"), \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context"):

        with mcp_auth_scope(req, require_user_token=True) as identity:
            assert identity.token == "tok"

        bound = [c.args[0] for c in set_client.call_args_list if c.args[0] is not None]
        assert bound == [fake_user_client]


# ---- HIGH-7: tool-level enforcement (call sites in mcp_server.py) -----------


@pytest.mark.asyncio
async def test_create_deck_refuses_header_only_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api.mcp_server import MCPToolError, _create_deck_impl

    with pytest.raises(MCPToolError, match="user access token"):
        await _create_deck_impl(_forwarded_identity_request(), prompt="make a deck")


@pytest.mark.asyncio
async def test_edit_deck_refuses_header_only_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api.mcp_server import MCPToolError, _edit_deck_impl

    with pytest.raises(MCPToolError, match="user access token"):
        await _edit_deck_impl(
            _forwarded_identity_request(), session_id="s1", instruction="tweak it"
        )


@pytest.mark.asyncio
async def test_get_deck_status_allows_header_only_identity(monkeypatch):
    """Read/attribution tools keep working with header-only identity."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError, _get_deck_status_impl

    with patch.object(mcp_server, "permission_service") as perm:
        perm.can_view_deck.return_value = False
        with pytest.raises(MCPToolError, match="permission"):
            # request_id is a required positional (mcp_server.py:526-528);
            # it is never reached — the permission check fires first.
            await _get_deck_status_impl(
                _forwarded_identity_request(), session_id="s1", request_id="r1"
            )
    # Reaching the permission check proves auth did NOT refuse the caller.


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
