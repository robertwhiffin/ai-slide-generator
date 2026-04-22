"""MCP (Model Context Protocol) server for tellr.

Exposes tellr's deck-generation capabilities as a set of MCP tools so
external Databricks Apps and MCP-compatible agent tools (e.g., Claude
Code) can programmatically create, edit, and retrieve slide decks.

The tools are thin wrappers over existing services (ChatService,
SessionManager, SlideDeck, permission_service) — no re-implementation
of the agent pipeline.

See docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md for
the design rationale and docs/technical/mcp-server.md (added later) for
the caller-facing integration guide.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# FastMCP instance — one per process. Tools are registered via decorators
# added in subsequent tasks (create_deck, get_deck_status, edit_deck, get_deck).
mcp = FastMCP("tellr")


def _public_app_url() -> str:
    """Return the base URL for constructing deck_url / deck_view_url.

    Reads TELLR_APP_URL from the environment; this is set at deploy time
    by the Databricks App platform or by local dev config. Returns an
    empty string if unset — tool handlers should treat empty as "build
    relative URLs" rather than fail hard.
    """
    return os.getenv("TELLR_APP_URL", "").rstrip("/")


# Tool implementations are added in subsequent tasks.
