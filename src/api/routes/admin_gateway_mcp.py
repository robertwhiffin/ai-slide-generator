"""Admin API for the AI Gateway MCP connection registry."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.schemas.gateway_mcp import (
    GatewayConnectionCreate,
    GatewayConnectionOut,
    GatewayConnectionUpdate,
    GatewayStatusOut,
    GatewayTestRequest,
    GatewayToolOut,
)
from src.core.database import get_db
from src.core.databricks_client import get_user_client
from src.core.scope_errors import oauth_scopes_from_token
from src.core.user_context import get_current_user
from src.services import gateway_mcp_registry as registry
from src.services.agent_tools.gateway_mcp import GatewayMcpClient, probe_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/gateway-mcp-connections",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _out(conn: registry.GatewayConnection) -> GatewayConnectionOut:
    return GatewayConnectionOut(
        id=conn.id,
        service_name=conn.service_name,
        display_name=conn.display_name,
        description=conn.description,
        agent=conn.agent,
        instructions=conn.instructions,
        tool_allowlist=None if conn.tool_allowlist is None else list(conn.tool_allowlist),
        enabled=conn.enabled,
        created_by=conn.created_by,
        updated_by=conn.updated_by,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


@router.get("", response_model=list[GatewayConnectionOut])
def list_gateway_connections(db: Session = Depends(get_db)):
    return [_out(c) for c in registry.list_connections(db)]


@router.post("", response_model=GatewayConnectionOut, status_code=status.HTTP_201_CREATED)
def create_gateway_connection(body: GatewayConnectionCreate, db: Session = Depends(get_db)):
    user = get_current_user() or "unknown"
    try:
        conn = registry.create_connection(
            db,
            service_name=body.service_name,
            display_name=body.display_name,
            description=body.description,
            agent=body.agent,
            instructions=body.instructions,
            tool_allowlist=body.tool_allowlist,
            enabled=body.enabled,
            user=user,
        )
    except registry.DuplicateServiceError:
        raise HTTPException(status_code=409, detail="This service is already registered")
    return _out(conn)


# Registered before "/{connection_id}" so "test" is never read as an id.
@router.post("/test", response_model=GatewayStatusOut)
def test_gateway_connection(body: GatewayTestRequest):
    """Probe the service AS THE CALLING ADMIN (their host and token)."""
    config = get_user_client().config
    token = config.token
    client = GatewayMcpClient(
        host=config.host,
        token=token,
        service_name=body.service_name,
        token_scopes=oauth_scopes_from_token(token),
    )
    probe = probe_service(client)
    message = registry.status_message(
        probe.state,
        display_name=body.service_name,
        service_name=body.service_name,
        detail=probe.detail,
        sign_in_url=probe.sign_in_url,
    )
    return GatewayStatusOut(
        state=probe.state,
        message=message,
        sign_in_url=probe.sign_in_url,
        tools=[GatewayToolOut(name=t.name, description=t.description) for t in probe.tools],
    )


@router.put("/{connection_id}", response_model=GatewayConnectionOut)
def update_gateway_connection(
    connection_id: int, body: GatewayConnectionUpdate, db: Session = Depends(get_db)
):
    user = get_current_user() or "unknown"
    try:
        conn = registry.update_connection(
            db,
            connection_id,
            display_name=body.display_name,
            description=body.description,
            agent=body.agent,
            instructions=body.instructions,
            tool_allowlist=body.tool_allowlist,
            enabled=body.enabled,
            user=user,
        )
    except registry.ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _out(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gateway_connection(connection_id: int, db: Session = Depends(get_db)):
    try:
        registry.delete_connection(db, connection_id)
    except registry.ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Connection not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
