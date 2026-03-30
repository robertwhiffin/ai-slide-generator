"""Tool discovery endpoint — returns available tools for agent configuration."""

import logging

from fastapi import APIRouter

from src.core.config_loader import load_config
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _list_genie_spaces() -> list[dict]:
    """Discover available Genie spaces via Databricks SDK."""
    try:
        client = get_user_client()
        results: list[dict] = []

        response = client.genie.list_spaces(page_size=100)
        if response.spaces:
            for s in response.spaces:
                results.append(
                    {
                        "type": "genie",
                        "space_id": s.space_id,
                        "space_name": s.title,
                        "description": getattr(s, "description", None),
                    }
                )

        while response.next_page_token:
            response = client.genie.list_spaces(
                page_token=response.next_page_token, page_size=100
            )
            if response.spaces:
                for s in response.spaces:
                    results.append(
                        {
                            "type": "genie",
                            "space_id": s.space_id,
                            "space_name": s.title,
                            "description": getattr(s, "description", None),
                        }
                    )

        return results
    except Exception as e:
        logger.warning(f"Failed to list Genie spaces: {e}")
        return []


def _list_mcp_servers() -> list[dict]:
    """List MCP servers from application config."""
    try:
        config = load_config()
        servers = config.get("mcp_servers", [])
        return [
            {
                "type": "mcp",
                "connection_name": s["uri"],
                "server_name": s["name"],
                "config": s.get("config", {}),
            }
            for s in servers
        ]
    except Exception as e:
        logger.warning(f"Failed to list MCP servers: {e}")
        return []


@router.get("/available")
def get_available_tools():
    """Return all available tools (Genie spaces + MCP servers)."""
    return _list_genie_spaces() + _list_mcp_servers()
