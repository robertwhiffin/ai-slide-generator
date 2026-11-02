"""AI Gateway MCP connection registry.

One row per Gateway MCP service an admin has registered, and the agent it is bound to.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text

from src.core.database import Base


class GatewayMcpConnection(Base):
    """An admin-registered AI Gateway MCP service (``catalog.schema.service``)."""

    __tablename__ = "gateway_mcp_connections"

    id = Column(Integer, primary_key=True)
    service_name = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    agent = Column(String(32), nullable=False)
    instructions = Column(Text, nullable=True)
    tool_allowlist = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(255))
    updated_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
