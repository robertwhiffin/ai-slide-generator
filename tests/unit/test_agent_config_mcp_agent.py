"""Stored ``agent`` on MCP server tool entries (agent mode MCP, Task 1)."""

import copy
import logging

import pytest
from pydantic import ValidationError

from src.api.schemas.agent_config import MCPTool, resolve_agent_config

_BASE = {"type": "mcp", "connection_name": "c", "server_name": "s"}


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_mcp_entry_without_agent_reads_as_data_analyst():
    cfg = resolve_agent_config({"tools": [dict(_BASE)]})
    assert cfg.tools[0].agent == "data_analyst"


def test_mcp_entry_keeps_architect():
    cfg = resolve_agent_config({"tools": [{**_BASE, "agent": "architect"}]})
    assert cfg.tools[0].agent == "architect"
    assert cfg.model_dump()["tools"][0]["agent"] == "architect"


def test_unknown_stored_agent_reads_as_data_analyst_with_a_warning(caplog):
    raw = {"tools": [{**_BASE, "agent": "builder"}]}
    snapshot = copy.deepcopy(raw)
    with caplog.at_level(logging.WARNING):
        cfg = resolve_agent_config(raw)
    assert cfg.tools[0].agent == "data_analyst"
    assert any("builder" in r.getMessage() for r in _warnings(caplog))
    # The caller's dict (and its nested tool entry) must not be mutated.
    assert raw == snapshot
    assert raw["tools"][0]["agent"] == "builder"


def test_an_absent_agent_logs_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = resolve_agent_config({"tools": [dict(_BASE)]})
    assert cfg.tools[0].agent == "data_analyst"
    assert _warnings(caplog) == []


def test_unhashable_stored_agent_reads_as_data_analyst():
    cfg = resolve_agent_config({"tools": [{**_BASE, "agent": ["x"]}]})
    assert cfg.tools[0].agent == "data_analyst"


def test_direct_construction_rejects_unknown_agent():
    with pytest.raises(ValidationError):
        MCPTool(type="mcp", connection_name="c", server_name="s", agent="builder")
