"""Shared graph-engine selection semantics."""

from __future__ import annotations

AGENT_MODE_PHRASE = "USE AGENT MODE"


def selects_graph_engine(content: str | None) -> bool:
    """Return whether ``content`` contains the case-sensitive graph marker."""
    return bool(content) and AGENT_MODE_PHRASE in content
