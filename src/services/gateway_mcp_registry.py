"""Registry of admin-registered AI Gateway MCP connections."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.scope_errors import consent_message
from src.database.models.gateway_mcp_connection import GatewayMcpConnection

INSTRUCTIONS_MAX_CHARS: Final = 4000

AgentName = Literal["architect", "data_analyst"]


class DuplicateServiceError(Exception):
    """A connection for this service name already exists."""


class ConnectionNotFoundError(Exception):
    """No connection has this id."""


@dataclass(frozen=True)
class GatewayConnection:
    id: int
    service_name: str
    display_name: str
    description: str | None
    agent: AgentName
    instructions: str | None
    tool_allowlist: tuple[str, ...] | None
    enabled: bool
    created_by: str | None
    created_at: datetime | None
    updated_by: str | None
    updated_at: datetime | None


def _to_connection(row: GatewayMcpConnection) -> GatewayConnection:
    allowlist = row.tool_allowlist
    return GatewayConnection(
        id=row.id,
        service_name=row.service_name,
        display_name=row.display_name,
        description=row.description,
        agent=row.agent,  # type: ignore[arg-type]
        instructions=row.instructions,
        tool_allowlist=None if allowlist is None else tuple(allowlist),
        enabled=bool(row.enabled),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _allowlist(value: Iterable[str] | None) -> list[str] | None:
    return None if value is None else list(value)


def list_connections(db: Session) -> list[GatewayConnection]:
    rows = db.execute(select(GatewayMcpConnection).order_by(GatewayMcpConnection.id)).scalars()
    return [_to_connection(r) for r in rows]


def get_by_service(db: Session, service_name: str) -> GatewayConnection | None:
    row = db.execute(
        select(GatewayMcpConnection).where(GatewayMcpConnection.service_name == service_name)
    ).scalar_one_or_none()
    return None if row is None else _to_connection(row)


def enabled_by_service(db: Session, service_names: Iterable[str]) -> dict[str, GatewayConnection]:
    names = list(service_names)
    if not names:
        return {}
    rows = db.execute(
        select(GatewayMcpConnection).where(
            GatewayMcpConnection.service_name.in_(names),
            GatewayMcpConnection.enabled.is_(True),
        )
    ).scalars()
    return {r.service_name: _to_connection(r) for r in rows}


def create_connection(
    db: Session,
    *,
    service_name: str,
    display_name: str,
    description: str | None,
    agent: str,
    instructions: str | None,
    tool_allowlist: Iterable[str] | None,
    enabled: bool,
    user: str,
) -> GatewayConnection:
    row = GatewayMcpConnection(
        service_name=service_name,
        display_name=display_name,
        description=description,
        agent=agent,
        instructions=instructions,
        tool_allowlist=_allowlist(tool_allowlist),
        enabled=enabled,
        created_by=user,
        updated_by=user,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise DuplicateServiceError(service_name) from err
    return _to_connection(row)


def _get_row(db: Session, connection_id: int) -> GatewayMcpConnection:
    row = db.get(GatewayMcpConnection, connection_id)
    if row is None:
        raise ConnectionNotFoundError(connection_id)
    return row


def update_connection(
    db: Session,
    connection_id: int,
    *,
    display_name: str,
    description: str | None,
    agent: str,
    instructions: str | None,
    tool_allowlist: Iterable[str] | None,
    enabled: bool,
    user: str,
) -> GatewayConnection:
    row = _get_row(db, connection_id)
    row.display_name = display_name
    row.description = description
    row.agent = agent
    row.instructions = instructions
    row.tool_allowlist = _allowlist(tool_allowlist)
    row.enabled = enabled
    row.updated_by = user
    row.updated_at = datetime.utcnow()
    db.commit()
    return _to_connection(row)


def delete_connection(db: Session, connection_id: int) -> None:
    row = _get_row(db, connection_id)
    db.delete(row)
    db.commit()


def status_message(
    state: str,
    *,
    display_name: str,
    service_name: str,
    detail: str | None,
    sign_in_url: str | None,
    oauth_client_id: str | None = None,
) -> str | None:
    """The user-facing line for a probe state, or ``None`` when ready."""
    if state == "ready":
        return None
    if state == "sign_in_required":
        return f"To use {display_name}, sign in here: {sign_in_url} — then ask again."
    if state == "access_denied":
        return (
            f"You don't have access to {display_name} ({service_name}). "
            "Ask an admin to grant EXECUTE on it."
        )
    if state == "not_found":
        return (
            f"{display_name} ({service_name}) was not found on this workspace. "
            "Ask an admin to check the connection."
        )
    if state == "missing_scope":
        return consent_message(oauth_client_id=oauth_client_id)
    if state == "not_registered":
        return f"{display_name} is no longer available."
    reason = detail or "no reason given"
    return f"{display_name} is unavailable right now ({reason})."
