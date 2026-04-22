"""Unit tests for MCP tool handlers.

Each handler is tested in isolation with mocked services. Integration
behavior (full JSON-RPC round trip, FastMCP routing) lives in
tests/integration/test_mcp_endpoint.py (added in Task 11).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.api.mcp_auth import MCPIdentity


@pytest.fixture
def identity():
    return MCPIdentity(
        user_id="user-abc",
        user_name="alice@example.com",
        token="tok",
        source="x-forwarded-access-token",
    )


@pytest.fixture
def fake_request():
    req = MagicMock()
    req.headers = {"x-forwarded-access-token": "tok"}
    return req


# ---- create_deck --------------------------------------------------------


@pytest.mark.asyncio
async def test_create_deck_creates_session_and_submits_job(fake_request, identity):
    from src.api import mcp_server

    mock_session = {"session_id": "sess-123"}

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job") as enqueue:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        sm = MagicMock()
        sm.create_session.return_value = mock_session
        get_sm.return_value = sm

        async def _fake_enqueue(**kwargs):
            return "req-777"

        enqueue.side_effect = _fake_enqueue

        result = await mcp_server._create_deck_impl(
            request=fake_request,
            prompt="make a deck about Q3",
            num_slides=7,
            slide_style_id=4,
            deck_prompt_id=2,
            correlation_id="vibe-xyz",
        )

        sm.create_session.assert_called_once()
        create_kwargs = sm.create_session.call_args.kwargs
        assert create_kwargs["created_by"] == "alice@example.com"
        agent_config = create_kwargs["agent_config"]
        assert agent_config["tools"] == []
        assert agent_config["slide_style_id"] == 4
        assert agent_config["deck_prompt_id"] == 2
        assert agent_config["num_slides"] == 7

        enqueue.assert_called_once()
        assert enqueue.call_args.kwargs["session_id"] == "sess-123"
        assert enqueue.call_args.kwargs["prompt"] == "make a deck about Q3"
        assert enqueue.call_args.kwargs["mode"] == "generate"
        assert enqueue.call_args.kwargs["correlation_id"] == "vibe-xyz"

        assert result == {
            "session_id": "sess-123",
            "request_id": "req-777",
            "status": "pending",
        }


@pytest.mark.asyncio
async def test_create_deck_rejects_empty_prompt(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="",
            )
        assert "prompt" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_create_deck_rejects_num_slides_out_of_range(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        with pytest.raises(MCPToolError):
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
                num_slides=0,
            )
        with pytest.raises(MCPToolError):
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
                num_slides=51,
            )


@pytest.mark.asyncio
async def test_create_deck_surfaces_auth_error_as_tool_error(fake_request):
    from src.api import mcp_server
    from src.api.mcp_auth import MCPAuthError
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.side_effect = MCPAuthError("no creds")

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
            )
        assert "auth" in str(exc.value).lower() or "credentials" in str(exc.value).lower()
