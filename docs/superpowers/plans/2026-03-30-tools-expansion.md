# Tools Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand AgentConfig tools from 2 types (Genie, MCP stub) to 5 fully functional types (Genie, MCP, Vector Index, Model Endpoint, Agent Bricks) with discovery APIs, OBO execution, frontend category picker, and Genie header button.

**Architecture:** Extend the existing inline `AgentConfig.tools[]` discriminated union pattern. Each tool type gets a Pydantic schema, discovery endpoint, execution module, and frontend discovery panel. No database migrations — tools stay as JSON on sessions/profiles.

**Tech Stack:** Python/FastAPI backend, Pydantic v2 schemas, Databricks SDK (OBO), LangChain StructuredTool, React/TypeScript frontend, Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-03-30-tools-expansion-design.md`

**Branch:** `ty/feature/tools-expansion`

**Old repo reference:** `/Users/tariq.yaaqba/Desktop/Slide Gen Dev Repos/tools/ai-slide-generator/` — reference only, verify all SDK calls against current versions.

---

## Phase 1: Backend Schema

### Task 1: Add new tool type Pydantic schemas

**Files:**
- Modify: `src/api/schemas/agent_config.py`
- Modify: `tests/unit/test_agent_config_schema.py`

- [ ] **Step 1: Write failing tests for new tool types**

Add to `tests/unit/test_agent_config_schema.py`:

```python
# --- VectorIndexTool tests ---

def test_vector_index_tool_valid():
    from src.api.schemas.agent_config import VectorIndexTool
    tool = VectorIndexTool(
        type="vector_index",
        endpoint_name="my-endpoint",
        index_name="my-index",
        description="Product docs",
        columns=["title", "content"],
        num_results=5,
    )
    assert tool.endpoint_name == "my-endpoint"
    assert tool.index_name == "my-index"
    assert tool.columns == ["title", "content"]
    assert tool.num_results == 5


def test_vector_index_tool_requires_endpoint_and_index():
    from src.api.schemas.agent_config import VectorIndexTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VectorIndexTool(type="vector_index")


def test_vector_index_tool_defaults():
    from src.api.schemas.agent_config import VectorIndexTool
    tool = VectorIndexTool(
        type="vector_index",
        endpoint_name="ep",
        index_name="idx",
    )
    assert tool.columns is None
    assert tool.num_results == 5
    assert tool.description is None


# --- ModelEndpointTool tests ---

def test_model_endpoint_tool_valid():
    from src.api.schemas.agent_config import ModelEndpointTool
    tool = ModelEndpointTool(
        type="model_endpoint",
        endpoint_name="my-llm",
        endpoint_type="foundation",
        description="Claude model",
    )
    assert tool.endpoint_name == "my-llm"
    assert tool.endpoint_type == "foundation"


def test_model_endpoint_tool_requires_endpoint_name():
    from src.api.schemas.agent_config import ModelEndpointTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ModelEndpointTool(type="model_endpoint")


def test_model_endpoint_tool_defaults():
    from src.api.schemas.agent_config import ModelEndpointTool
    tool = ModelEndpointTool(type="model_endpoint", endpoint_name="ep")
    assert tool.endpoint_type is None
    assert tool.description is None


# --- AgentBricksTool tests ---

def test_agent_bricks_tool_valid():
    from src.api.schemas.agent_config import AgentBricksTool
    tool = AgentBricksTool(
        type="agent_bricks",
        endpoint_name="hr-knowledge-bot",
        description="HR assistant",
    )
    assert tool.endpoint_name == "hr-knowledge-bot"


def test_agent_bricks_tool_requires_endpoint_name():
    from src.api.schemas.agent_config import AgentBricksTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentBricksTool(type="agent_bricks")


# --- Updated MCPTool tests ---

def test_mcp_tool_connection_name_valid():
    from src.api.schemas.agent_config import MCPTool
    tool = MCPTool(type="mcp", connection_name="jira-conn", server_name="Jira")
    assert tool.connection_name == "jira-conn"
    assert tool.server_name == "Jira"


def test_mcp_tool_connection_name_required():
    from src.api.schemas.agent_config import MCPTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MCPTool(type="mcp", server_name="Jira")


# --- Mixed tool config tests ---

def test_config_with_all_tool_types():
    from src.api.schemas.agent_config import (
        AgentConfig, GenieTool, MCPTool,
        VectorIndexTool, ModelEndpointTool, AgentBricksTool,
    )
    config = AgentConfig(tools=[
        GenieTool(type="genie", space_id="s1", space_name="Sales"),
        MCPTool(type="mcp", connection_name="jira", server_name="Jira"),
        VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx"),
        ModelEndpointTool(type="model_endpoint", endpoint_name="llm"),
        AgentBricksTool(type="agent_bricks", endpoint_name="hr-bot"),
    ])
    assert len(config.tools) == 5


def test_duplicate_vector_index_rejected():
    from src.api.schemas.agent_config import AgentConfig, VectorIndexTool
    tool = VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_model_endpoint_rejected():
    from src.api.schemas.agent_config import AgentConfig, ModelEndpointTool
    tool = ModelEndpointTool(type="model_endpoint", endpoint_name="llm")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_agent_bricks_rejected():
    from src.api.schemas.agent_config import AgentConfig, AgentBricksTool
    tool = AgentBricksTool(type="agent_bricks", endpoint_name="bot")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_resolve_agent_config_with_new_types():
    from src.api.schemas.agent_config import resolve_agent_config
    raw = {
        "tools": [
            {"type": "vector_index", "endpoint_name": "ep", "index_name": "idx"},
            {"type": "model_endpoint", "endpoint_name": "llm"},
            {"type": "agent_bricks", "endpoint_name": "bot"},
        ]
    }
    config = resolve_agent_config(raw)
    assert len(config.tools) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tariq.yaaqba/Desktop/Slide\ Gen\ Dev\ Repos/Session\ Tools/ai-slide-generator && python -m pytest tests/unit/test_agent_config_schema.py -v --tb=short 2>&1 | tail -30`

Expected: Multiple FAIL — classes not defined yet.

- [ ] **Step 3: Implement new schemas**

Update `src/api/schemas/agent_config.py` to:

```python
"""Pydantic models for agent_config JSON stored on sessions and profiles."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class GenieTool(BaseModel):
    """Native Genie space tool — registered directly as a LangChain tool."""
    type: Literal["genie"]
    space_id: str = Field(..., min_length=1)
    space_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    conversation_id: Optional[str] = None


class MCPTool(BaseModel):
    """MCP server tool — tools discovered via UC HTTP connections."""
    type: Literal["mcp"]
    connection_name: str = Field(..., min_length=1)
    server_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    config: dict = Field(default_factory=dict)


class VectorIndexTool(BaseModel):
    """Vector search index tool — similarity search over embeddings."""
    type: Literal["vector_index"]
    endpoint_name: str = Field(..., min_length=1)
    index_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    columns: Optional[list[str]] = None
    num_results: int = Field(default=5, ge=1, le=50)


class ModelEndpointTool(BaseModel):
    """Model serving endpoint tool — foundation models and custom ML."""
    type: Literal["model_endpoint"]
    endpoint_name: str = Field(..., min_length=1)
    endpoint_type: Optional[str] = None
    description: Optional[str] = None


class AgentBricksTool(BaseModel):
    """Agent Bricks tool — knowledge assistants and supervisor agents."""
    type: Literal["agent_bricks"]
    endpoint_name: str = Field(..., min_length=1)
    description: Optional[str] = None


ToolEntry = Annotated[
    Union[GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool],
    Field(discriminator="type"),
]


class AgentConfig(BaseModel):
    """Agent configuration stored as JSON on sessions and profiles."""
    tools: list[ToolEntry] = Field(default_factory=list)
    slide_style_id: Optional[int] = None
    deck_prompt_id: Optional[int] = None
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None

    @field_validator("system_prompt", "slide_editing_instructions")
    @classmethod
    def must_be_nonempty_if_set(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() == "":
            raise ValueError("Must be non-empty if provided")
        return v

    @model_validator(mode="after")
    def no_duplicate_tools(self) -> "AgentConfig":
        seen: set[str] = set()
        for tool in self.tools:
            if isinstance(tool, GenieTool):
                key = f"genie:{tool.space_id}"
            elif isinstance(tool, MCPTool):
                key = f"mcp:{tool.connection_name}"
            elif isinstance(tool, VectorIndexTool):
                key = f"vector_index:{tool.endpoint_name}:{tool.index_name}"
            elif isinstance(tool, ModelEndpointTool):
                key = f"model_endpoint:{tool.endpoint_name}"
            elif isinstance(tool, AgentBricksTool):
                key = f"agent_bricks:{tool.endpoint_name}"
            else:
                continue
            if key in seen:
                raise ValueError(f"Duplicate tool: {key}")
            seen.add(key)
        return self


def resolve_agent_config(raw: Optional[dict]) -> AgentConfig:
    """Parse agent_config JSON from DB, returning defaults if None."""
    if raw is None:
        return AgentConfig()
    return AgentConfig.model_validate(raw)
```

- [ ] **Step 4: Fix existing MCP tests that reference `server_uri`**

Update the existing tests in `tests/unit/test_agent_config_schema.py` that use `server_uri` to use `connection_name` instead. Specifically update `test_mcp_tool_requires_server_uri_and_name`, `test_mcp_tool_valid`, and `test_duplicate_mcp_tools_rejected`.

Also update `test_tools_routes.py` if it references `server_uri`.

Also update `src/services/agent_factory.py:298` which logs `tool_entry.server_uri` — change to `tool_entry.connection_name`.

- [ ] **Step 5: Run all tests to verify they pass**

Run: `cd /Users/tariq.yaaqba/Desktop/Slide\ Gen\ Dev\ Repos/Session\ Tools/ai-slide-generator && python -m pytest tests/unit/test_agent_config_schema.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/api/schemas/agent_config.py tests/unit/test_agent_config_schema.py src/services/agent_factory.py
git commit -m "feat: add VectorIndexTool, ModelEndpointTool, AgentBricksTool schemas

Extend ToolEntry union with 3 new tool types. Update MCPTool
to use connection_name (UC HTTP connections) instead of server_uri.
Update duplicate detection validator for all 5 types."
```

---

### Task 2: Update frontend TypeScript types

**Files:**
- Modify: `frontend/src/types/agentConfig.ts`

- [ ] **Step 1: Update types file**

Replace the full contents of `frontend/src/types/agentConfig.ts`:

```typescript
export interface GenieTool {
  type: 'genie';
  space_id: string;
  space_name: string;
  description?: string;
  conversation_id?: string;
}

export interface MCPTool {
  type: 'mcp';
  connection_name: string;
  server_name: string;
  description?: string;
  config?: Record<string, unknown>;
}

export interface VectorIndexTool {
  type: 'vector_index';
  endpoint_name: string;
  index_name: string;
  description?: string;
  columns?: string[];
  num_results?: number;
}

export interface ModelEndpointTool {
  type: 'model_endpoint';
  endpoint_name: string;
  endpoint_type?: string;
  description?: string;
}

export interface AgentBricksTool {
  type: 'agent_bricks';
  endpoint_name: string;
  description?: string;
}

export type ToolType = 'genie' | 'mcp' | 'vector_index' | 'model_endpoint' | 'agent_bricks';

export type ToolEntry = GenieTool | MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool;

export interface AgentConfig {
  tools: ToolEntry[];
  slide_style_id: number | null;
  deck_prompt_id: number | null;
  system_prompt: string | null;
  slide_editing_instructions: string | null;
}

export interface DiscoveryItem {
  name: string;
  id: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface DiscoveryResponse {
  items: DiscoveryItem[];
}

export interface ColumnInfo {
  name: string;
  type?: string;
}

export interface ColumnDiscoveryResponse {
  columns: ColumnInfo[];
  source_table?: string;
  primary_key?: string;
}

export interface AvailableTool {
  type: ToolType;
  space_id?: string;
  space_name?: string;
  connection_name?: string;
  server_name?: string;
  endpoint_name?: string;
  index_name?: string;
  description?: string;
}

export interface ProfileSummary {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  agent_config: AgentConfig | null;
  created_at: string | null;
  created_by: string | null;
}

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  tools: [],
  slide_style_id: null,
  deck_prompt_id: null,
  system_prompt: null,
  slide_editing_instructions: null,
};

export const TOOL_TYPE_LABELS: Record<ToolType, string> = {
  genie: 'Genie Space',
  mcp: 'MCP Server',
  vector_index: 'Vector Index',
  model_endpoint: 'Model Endpoint',
  agent_bricks: 'Agent Bricks',
};

export const TOOL_TYPE_BADGE_LABELS: Record<ToolType, string> = {
  genie: 'GENIE',
  mcp: 'MCP',
  vector_index: 'VECTOR',
  model_endpoint: 'MODEL',
  agent_bricks: 'AGENT',
};

export const TOOL_TYPE_COLORS: Record<ToolType, string> = {
  genie: 'bg-blue-100 text-blue-800',
  mcp: 'bg-green-100 text-green-800',
  vector_index: 'bg-indigo-100 text-indigo-800',
  model_endpoint: 'bg-amber-100 text-amber-800',
  agent_bricks: 'bg-teal-100 text-teal-800',
};
```

- [ ] **Step 2: Fix any TypeScript compilation errors from `server_uri` -> `connection_name` change**

Search for `server_uri` in frontend code and update all references to `connection_name`. Key files to check:
- `frontend/src/components/AgentConfigBar/ToolPicker.tsx`
- `frontend/src/components/AgentConfigBar/toolUtils.ts`
- `frontend/src/services/api.ts`
- `frontend/src/contexts/AgentConfigContext.tsx`

- [ ] **Step 3: Verify frontend compiles**

Run: `cd /Users/tariq.yaaqba/Desktop/Slide\ Gen\ Dev\ Repos/Session\ Tools/ai-slide-generator/frontend && npx tsc --noEmit 2>&1 | head -20`

Expected: No errors (or only pre-existing ones unrelated to our changes).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/agentConfig.ts frontend/src/
git commit -m "feat: add frontend TypeScript types for new tool types

Add VectorIndexTool, ModelEndpointTool, AgentBricksTool interfaces.
Update MCPTool to use connection_name. Add tool type labels, badges,
colors, and discovery response types."
```

---

## Phase 2: Backend Discovery Endpoints

### Task 3: Add discovery endpoints for all tool types

**Files:**
- Modify: `src/api/routes/tools.py`
- Create: `tests/unit/test_tools_discovery.py`

- [ ] **Step 1: Write failing tests for discovery endpoints**

Create `tests/unit/test_tools_discovery.py`:

```python
"""Tests for tool discovery endpoints."""
import pytest
from unittest.mock import MagicMock, patch


def _make_client():
    return MagicMock()


class TestGenieDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_genie_returns_spaces(self, mock_client_fn):
        from src.api.routes.tools import _discover_genie_spaces

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_space = MagicMock()
        mock_space.space_id = "space-1"
        mock_space.title = "Sales Data"
        mock_space.description = "Revenue analytics"

        mock_response = MagicMock()
        mock_response.spaces = [mock_space]
        mock_response.next_page_token = None
        mock_client.genie.list_spaces.return_value = mock_response

        result = _discover_genie_spaces()
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "space-1"
        assert result["items"][0]["name"] == "Sales Data"


class TestVectorDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_endpoints(self, mock_client_fn):
        from src.api.routes.tools import _discover_vector_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_ep = MagicMock()
        mock_ep.name = "vs-endpoint-1"
        mock_ep.endpoint_status = MagicMock()
        mock_ep.endpoint_status.state = "ONLINE"

        mock_client.vector_search_endpoints.list_endpoints.return_value = [mock_ep]

        result = _discover_vector_endpoints()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "vs-endpoint-1"


class TestMCPDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_mcp_connections(self, mock_client_fn):
        from src.api.routes.tools import _discover_mcp_connections

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.name = "jira-conn"
        mock_conn.connection_type = "HTTP"
        mock_conn.comment = "Jira integration"

        mock_client.connections.list.return_value = [mock_conn]

        result = _discover_mcp_connections()
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "jira-conn"


class TestModelEndpointDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_model_endpoints_excludes_agents(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_foundation = MagicMock()
        mock_foundation.name = "claude-sonnet"
        mock_foundation.task = "llm/v1/chat"

        mock_agent = MagicMock()
        mock_agent.name = "hr-bot"
        mock_agent.task = "agent/langchain"

        mock_custom = MagicMock()
        mock_custom.name = "fraud-model"
        mock_custom.task = "custom/inference"

        mock_client.serving_endpoints.list.return_value = [
            mock_foundation, mock_agent, mock_custom,
        ]

        result = _discover_model_endpoints()
        names = [item["name"] for item in result["items"]]
        assert "claude-sonnet" in names
        assert "fraud-model" in names
        assert "hr-bot" not in names


class TestAgentBricksDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_agent_bricks_only_agents(self, mock_client_fn):
        from src.api.routes.tools import _discover_agent_bricks

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_foundation = MagicMock()
        mock_foundation.name = "claude-sonnet"
        mock_foundation.task = "llm/v1/chat"

        mock_agent = MagicMock()
        mock_agent.name = "hr-bot"
        mock_agent.task = "agent/langchain"

        mock_client.serving_endpoints.list.return_value = [
            mock_foundation, mock_agent,
        ]

        result = _discover_agent_bricks()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "hr-bot"


class TestDiscoveryErrorHandling:
    """Verify all discovery endpoints return empty items on SDK failure."""

    @patch("src.api.routes.tools.get_user_client")
    def test_genie_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_genie_spaces
        mock_client_fn.return_value.genie.list_spaces.side_effect = Exception("Auth failed")
        result = _discover_genie_spaces()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_vector_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_vector_endpoints
        mock_client_fn.return_value.vector_search_endpoints.list_endpoints.side_effect = Exception("No access")
        result = _discover_vector_endpoints()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_mcp_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_mcp_connections
        mock_client_fn.return_value.connections.list.side_effect = Exception("Not configured")
        result = _discover_mcp_connections()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_model_endpoint_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints
        mock_client_fn.return_value.serving_endpoints.list.side_effect = Exception("Timeout")
        result = _discover_model_endpoints()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_agent_bricks_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_agent_bricks
        mock_client_fn.return_value.serving_endpoints.list.side_effect = Exception("Timeout")
        result = _discover_agent_bricks()
        assert result["items"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_tools_discovery.py -v --tb=short 2>&1 | tail -20`

Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement discovery functions and routes**

Replace `src/api/routes/tools.py` with the full implementation. Each discovery function uses `get_user_client()` for OBO auth. Verify each SDK method name exists by checking imports at implementation time.

Key implementation details:
- `_discover_genie_spaces()`: Refactor existing `_list_genie_spaces()` to return `{"items": [...]}`
- `_discover_vector_endpoints()`: Call `client.vector_search_endpoints.list_endpoints()`
- `_discover_vector_indexes(endpoint_name)`: Call `client.vector_search_indexes.list_indexes(endpoint_name=...)`
- `_discover_vector_columns(endpoint_name, index_name)`: Use `VectorSearchClient` to get index schema
- `_discover_mcp_connections()`: Call `client.connections.list()`, filter for HTTP connections
- `_discover_model_endpoints()`: Call `client.serving_endpoints.list()`, exclude `task.startswith("agent/")`
- `_discover_agent_bricks()`: Call `client.serving_endpoints.list()`, include only `task.startswith("agent/")`

Register routes:
```python
@router.get("/discover/genie")
@router.get("/discover/vector")
@router.get("/discover/vector/{endpoint_name}/indexes")
@router.get("/discover/vector/{endpoint_name}/{index_name}/columns")
@router.get("/discover/mcp")
@router.get("/discover/model-endpoints")
@router.get("/discover/agent-bricks")
```

Keep deprecated `GET /available` for now with a deprecation log warning.

- [ ] **Step 4: Verify SDK method names exist**

Before finalizing, run a quick check:
```bash
python -c "from databricks.sdk import WorkspaceClient; w = WorkspaceClient.__init__.__doc__; print('SDK imported')"
python -c "from databricks.sdk.service.serving import ServingEndpointsAPI; print('serving OK')"
python -c "from databricks.sdk.service.vectorsearch import VectorSearchEndpointsAPI; print('vector OK')"
python -c "from databricks.sdk.service.catalog import ConnectionsAPI; print('connections OK')"
```

If any import fails, investigate the correct SDK module path and update accordingly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_tools_discovery.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 6: Run existing tool route tests to check no regressions**

Run: `python -m pytest tests/unit/test_tools_routes.py -v --tb=short`

Expected: ALL PASS (may need updates if they reference old `_list_mcp_servers`).

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/tools.py tests/unit/test_tools_discovery.py
git commit -m "feat: add discovery endpoints for all tool types

Add /api/tools/discover/* endpoints for genie, vector, mcp,
model-endpoints, and agent-bricks. All use OBO auth via
get_user_client(). Deprecate /api/tools/available."
```

---

## Phase 3: Backend Tool Execution

### Task 4: Create tool execution modules

**Files:**
- Create: `src/services/tools/__init__.py`
- Create: `src/services/tools/genie_tool.py`
- Create: `src/services/tools/vector_tool.py`
- Create: `src/services/tools/mcp_tool.py`
- Create: `src/services/tools/model_endpoint_tool.py`
- Create: `src/services/tools/agent_bricks_tool.py`
- Modify: `src/services/tools.py` (rename to avoid conflict)
- Create: `tests/unit/test_tool_builders.py`

**IMPORTANT:** The existing `src/services/tools.py` (flat file) must be renamed or the `src/services/tools/` directory will conflict. Rename `tools.py` to `tools_legacy.py` temporarily, then move its functions into `src/services/tools/genie_tool.py`.

- [ ] **Step 1: Restructure — move existing genie functions to package**

1. Create `src/services/tools/` directory
2. Move `initialize_genie_conversation` and `query_genie_space` from `src/services/tools.py` into `src/services/tools/genie_tool.py`
3. Add `build_genie_tool` function (extracted from `agent_factory.py:158-244`)
4. Create `src/services/tools/__init__.py` that re-exports:
   ```python
   from src.services.tools.genie_tool import (
       initialize_genie_conversation,
       query_genie_space,
       build_genie_tool,
       GenieToolError,
   )
   ```
5. Delete `src/services/tools.py`
6. Update imports in `src/services/agent_factory.py` (line 22) from `from src.services.tools import ...` to `from src.services.tools import ...` (same path, now resolves to package)

- [ ] **Step 2: Run existing tests to verify genie still works**

Run: `python -m pytest tests/unit/test_tools.py tests/unit/test_agent_factory.py tests/unit/test_genie_conversation_persistence.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 3: Commit restructure**

```bash
git add src/services/tools/ src/services/agent_factory.py
git rm src/services/tools.py
git commit -m "refactor: move genie tool functions to src/services/tools/ package

Extract initialize_genie_conversation, query_genie_space, and
build_genie_tool into genie_tool.py. Re-export from __init__.py
for backward-compatible imports."
```

- [ ] **Step 4: Write failing tests for new tool builders**

Create `tests/unit/test_tool_builders.py`:

```python
"""Tests for tool builder functions."""
import pytest
from unittest.mock import MagicMock, patch


class TestBuildVectorTool:
    @patch("src.services.tools.vector_tool.get_user_client")
    def test_build_returns_structured_tool(self, mock_client_fn):
        from src.api.schemas.agent_config import VectorIndexTool
        from src.services.tools.vector_tool import build_vector_tool

        config = VectorIndexTool(
            type="vector_index",
            endpoint_name="ep",
            index_name="idx",
            description="Product docs",
            columns=["title", "content"],
        )
        tool = build_vector_tool(config, index=1)

        assert tool.name == "search_vector_index"
        assert "Product docs" in tool.description

    def test_build_second_tool_has_index_suffix(self):
        from src.api.schemas.agent_config import VectorIndexTool
        from src.services.tools.vector_tool import build_vector_tool

        config = VectorIndexTool(
            type="vector_index",
            endpoint_name="ep",
            index_name="idx",
        )
        tool = build_vector_tool(config, index=2)
        assert tool.name == "search_vector_index_2"


class TestBuildModelEndpointTool:
    def test_build_returns_structured_tool(self):
        from src.api.schemas.agent_config import ModelEndpointTool
        from src.services.tools.model_endpoint_tool import build_model_endpoint_tool

        config = ModelEndpointTool(
            type="model_endpoint",
            endpoint_name="my-llm",
            description="Foundation model",
        )
        tool = build_model_endpoint_tool(config, index=1)

        assert tool.name == "query_model_endpoint"
        assert "Foundation model" in tool.description


class TestBuildAgentBricksTool:
    def test_build_returns_structured_tool(self):
        from src.api.schemas.agent_config import AgentBricksTool
        from src.services.tools.agent_bricks_tool import build_agent_bricks_tool

        config = AgentBricksTool(
            type="agent_bricks",
            endpoint_name="hr-bot",
            description="HR knowledge assistant",
        )
        tool = build_agent_bricks_tool(config, index=1)

        assert tool.name == "query_agent"
        assert "HR knowledge assistant" in tool.description


class TestBuildMCPTools:
    @patch("src.services.tools.mcp_tool.list_mcp_tools")
    def test_build_returns_list_of_tools(self, mock_list):
        from src.api.schemas.agent_config import MCPTool
        from src.services.tools.mcp_tool import build_mcp_tools

        mock_list.return_value = [
            {"name": "search", "description": "Search", "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            }},
        ]

        config = MCPTool(
            type="mcp",
            connection_name="jira",
            server_name="Jira",
        )
        tools = build_mcp_tools(config)

        assert isinstance(tools, list)
        assert len(tools) >= 1
        assert "jira" in tools[0].name
```

- [ ] **Step 5: Implement vector_tool.py**

Create `src/services/tools/vector_tool.py`. Reference old repo's implementation at `/Users/tariq.yaaqba/Desktop/Slide Gen Dev Repos/tools/ai-slide-generator/src/services/tools/vector_tool.py` but verify all SDK calls. Key: extract token at query time inside closure, not at build time.

- [ ] **Step 6: Implement model_endpoint_tool.py**

Create `src/services/tools/model_endpoint_tool.py`. Reference old repo's implementation. Key: auto-detect endpoint type via `task` field, 1hr in-memory cache, handle foundation/custom formats.

- [ ] **Step 7: Implement agent_bricks_tool.py**

Create `src/services/tools/agent_bricks_tool.py`. Similar to model_endpoint but always uses agent format: `{"input": [{"role": "user", "content": "..."}]}`.

- [ ] **Step 8: Implement mcp_tool.py**

Create `src/services/tools/mcp_tool.py`. Port from old repo. Key: thread isolation via `ThreadPoolExecutor`, `DatabricksMCPClient`, dynamic Pydantic schema from MCP tool definitions. Verify `databricks-mcp` package is in requirements.

- [ ] **Step 9: Update __init__.py re-exports**

Add to `src/services/tools/__init__.py`:

```python
from src.services.tools.genie_tool import (
    initialize_genie_conversation,
    query_genie_space,
    build_genie_tool,
    GenieToolError,
)
from src.services.tools.vector_tool import build_vector_tool
from src.services.tools.mcp_tool import build_mcp_tools
from src.services.tools.model_endpoint_tool import build_model_endpoint_tool
from src.services.tools.agent_bricks_tool import build_agent_bricks_tool
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_tool_builders.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 11: Commit**

```bash
git add src/services/tools/
git commit -m "feat: add tool execution modules for vector, mcp, model endpoint, agent bricks

Each module provides a build_*_tool() function returning LangChain
StructuredTool instances. All use OBO auth via get_user_client().
MCP uses thread isolation for DatabricksMCPClient compatibility."
```

---

### Task 5: Extend agent factory to handle all tool types

**Files:**
- Modify: `src/services/agent_factory.py`
- Modify: `tests/unit/test_agent_factory.py`

- [ ] **Step 1: Write failing test for new tool types in factory**

Add to `tests/unit/test_agent_factory.py`:

```python
@patch("src.services.agent_factory.build_vector_tool")
def test_build_tools_includes_vector(self, mock_build):
    from src.api.schemas.agent_config import AgentConfig, VectorIndexTool
    from src.services.agent_factory import _build_tools

    mock_tool = MagicMock()
    mock_tool.name = "search_vector_index"
    mock_build.return_value = mock_tool

    config = AgentConfig(tools=[
        VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx"),
    ])
    tools = _build_tools(config, {})
    assert any(t.name == "search_vector_index" for t in tools)
    mock_build.assert_called_once()
```

Add similar tests for `ModelEndpointTool`, `AgentBricksTool`, and `MCPTool`.

- [ ] **Step 2: Update agent_factory.py `_build_tools()`**

Update imports and the tool building loop in `src/services/agent_factory.py` to handle all 5 types, calling the respective `build_*` functions from `src/services/tools/`.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_agent_factory.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 4: Run full backend test suite for regressions**

Run: `python -m pytest tests/unit/ -v --tb=short -x 2>&1 | tail -30`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_factory.py tests/unit/test_agent_factory.py
git commit -m "feat: extend agent factory to build all 5 tool types

_build_tools() now handles GenieTool, MCPTool, VectorIndexTool,
ModelEndpointTool, and AgentBricksTool via their respective builders."
```

---

## Phase 4: Frontend Tool Picker

### Task 6: Refactor ToolPicker to category buttons

**Files:**
- Modify: `frontend/src/components/AgentConfigBar/ToolPicker.tsx`
- Modify: `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`
- Create: `frontend/src/components/AgentConfigBar/tools/GenieDiscovery.tsx`

- [ ] **Step 1: Extract existing Genie search logic into GenieDiscovery.tsx**

Move the Genie space search/select logic from `ToolPicker.tsx` into a new `tools/GenieDiscovery.tsx` component. This component renders the search input, filtered list, and calls `onSelect` when user picks a space.

- [ ] **Step 2: Refactor ToolPicker.tsx to render category buttons**

Replace the current single "Add Genie" dropdown with 5 category buttons. When a button is clicked, it sets state to show the corresponding discovery panel. Only one panel open at a time.

```tsx
// Simplified structure
const TOOL_CATEGORIES = [
  { type: 'genie', label: '+ Genie Space' },
  { type: 'agent_bricks', label: '+ Agent Bricks' },
  { type: 'vector_index', label: '+ Vector Index' },
  { type: 'mcp', label: '+ MCP Server' },
  { type: 'model_endpoint', label: '+ Model Endpoint' },
] as const;

// Render buttons, show discovery panel for selected type
```

- [ ] **Step 3: Verify Genie flow still works end-to-end**

Open the app, navigate to Agent Config, click `+ Genie Space`, search for a space, add it. Verify chip appears and is clickable/removable.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentConfigBar/
git commit -m "refactor: replace single Add Genie with category tool picker

Extract GenieDiscovery.tsx from ToolPicker. ToolPicker now renders
category buttons for all 5 tool types."
```

---

### Task 7: Add discovery panels for new tool types

**Files:**
- Create: `frontend/src/components/AgentConfigBar/tools/VectorIndexDiscovery.tsx`
- Create: `frontend/src/components/AgentConfigBar/tools/MCPDiscovery.tsx`
- Create: `frontend/src/components/AgentConfigBar/tools/ModelEndpointDiscovery.tsx`
- Create: `frontend/src/components/AgentConfigBar/tools/AgentBricksDiscovery.tsx`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add discovery API methods to api.ts**

Add methods to the API client:

```typescript
async discoverVectorEndpoints(): Promise<DiscoveryResponse>
async discoverVectorIndexes(endpointName: string): Promise<DiscoveryResponse>
async discoverVectorColumns(endpointName: string, indexName: string): Promise<ColumnDiscoveryResponse>
async discoverMCPConnections(): Promise<DiscoveryResponse>
async discoverModelEndpoints(): Promise<DiscoveryResponse>
async discoverAgentBricks(): Promise<DiscoveryResponse>
```

Each calls the corresponding `GET /api/tools/discover/*` endpoint.

- [ ] **Step 2: Create VectorIndexDiscovery.tsx**

Three-step progressive selection:
1. Dropdown of vector endpoints
2. Dropdown of indexes for selected endpoint
3. Column checkboxes (all checked by default)
Plus name display, description textarea, Save & Add button.

All rendered inline in the same Agent Config space.

- [ ] **Step 3: Create MCPDiscovery.tsx**

Search/filter UC HTTP connections. Select one → show detail panel with connection name, description textarea, Save & Add.

- [ ] **Step 4: Create ModelEndpointDiscovery.tsx**

Search/filter serving endpoints (non-agent). Show Foundation/Custom badge per endpoint. Select → detail panel with endpoint name, type badge, description, Save & Add.

- [ ] **Step 5: Create AgentBricksDiscovery.tsx**

Search/filter agent serving endpoints. Select → detail panel with endpoint name, description, Save & Add.

- [ ] **Step 6: Wire discovery panels into ToolPicker**

Update `ToolPicker.tsx` to render the correct discovery panel based on selected category.

- [ ] **Step 7: Verify all 5 tool types can be added via UI**

Test each tool type: click category button → discovery panel opens → search/select → Save & Add → chip appears.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/AgentConfigBar/tools/ frontend/src/services/api.ts
git commit -m "feat: add discovery panels for vector, mcp, model endpoint, agent bricks

Each tool type has its own discovery component with search/filter,
detail panel, and Save & Add flow. VectorIndex has progressive
endpoint -> index -> columns selection."
```

---

### Task 8: Update tool chips for new types

**Files:**
- Modify: `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`
- Modify: `frontend/src/components/AgentConfigBar/toolUtils.ts`

- [ ] **Step 1: Update chip rendering to handle all tool types**

Update the tool chip rendering in `AgentConfigBar.tsx` to use `TOOL_TYPE_BADGE_LABELS` and `TOOL_TYPE_COLORS` from the types file. Each chip shows the colored badge and tool name.

- [ ] **Step 2: Add edit panels for new tool types**

When clicking a chip for a non-Genie tool, open the appropriate edit panel showing the tool's config with an editable description field and Save/Cancel buttons. Reuse the same discovery panel components in "edit" mode.

- [ ] **Step 3: Verify chips render correctly for all types**

Add tools of each type, verify badges and colors. Click each chip to edit. X to remove.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentConfigBar/
git commit -m "feat: add colored badge chips for all tool types

Tool chips show GENIE/VECTOR/MCP/MODEL/AGENT badges with type-specific
colors. Click to edit, X to remove."
```

---

## Phase 5: Genie Header Button

### Task 9: Add GenieDataButton to header

**Files:**
- Create: `frontend/src/components/Layout/GenieDataButton.tsx`
- Modify: `frontend/src/components/Layout/AppLayout.tsx` (or equivalent header component)

- [ ] **Step 1: Create GenieDataButton component**

```tsx
// GenieDataButton.tsx
// - Reads GenieTool entries from AgentConfigContext
// - Hidden if no Genie tools in config
// - Single genie: click opens conversation link in new tab
// - Multi genie: click shows dropdown with all conversations
// - Purple styling (bg-purple-500 hover:bg-purple-700 text-white)
// - Uses api.getGenieLink(sessionId, spaceId) for URL generation
```

- [ ] **Step 2: Add GenieDataButton to header layout**

Insert the component in the header bar, positioned near the session title/savepoint area.

- [ ] **Step 3: Remove per-slide genie icon from SlideTile.tsx**

Remove from `frontend/src/components/SlidePanel/SlideTile.tsx`:
- Line 87: `const [isLoadingGenieLink, setIsLoadingGenieLink] = useState(false);`
- Lines 91-108: `handleOpenGenieLink` function
- Lines 312-322: The `<Tooltip text="View source data">` button block
- Clean up unused `Database` import from lucide-react if no longer used elsewhere in the file.

- [ ] **Step 4: Update HelpPage.tsx**

Remove or update the line about "Database icon on each slide tile" in `frontend/src/components/Help/HelpPage.tsx`.

- [ ] **Step 5: Verify Genie header button works**

1. Add a Genie space, send a message to trigger a query
2. Verify header button appears
3. Click → opens Genie conversation
4. Add second Genie space, send another message
5. Click → dropdown shows both conversations

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Layout/GenieDataButton.tsx frontend/src/components/Layout/AppLayout.tsx frontend/src/components/SlidePanel/SlideTile.tsx frontend/src/components/Help/HelpPage.tsx
git commit -m "feat: move Genie deep-link from per-slide to header button

Add GenieDataButton with multi-genie dropdown in header bar.
Remove per-slide Database icon from SlideTile."
```

---

## Phase 6: Integration & Cleanup

### Task 10: Integration testing and cleanup

**Files:**
- Modify: `tests/unit/test_tools_routes.py` (update for new route structure)
- Modify: `requirements.txt` (add `databricks-vectorsearch`, `databricks-mcp` if missing)

- [ ] **Step 1: Check and update requirements.txt**

Verify these packages are in `requirements.txt`:
- `databricks-vectorsearch`
- `databricks-mcp`

If missing, add them.

- [ ] **Step 2: Run full backend test suite**

Run: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40`

Expected: ALL PASS. Fix any failures.

- [ ] **Step 3: Run frontend compilation check**

Run: `cd frontend && npx tsc --noEmit`

Expected: No new errors.

- [ ] **Step 4: Verify profile save/load round-trip**

1. Add tools of multiple types
2. Click "Save as Profile"
3. Start new session
4. Click "Load Profile"
5. Verify all tools restored with correct types and config

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: integration fixes and dependency updates

Update requirements, fix remaining test failures, verify profile
save/load works for all tool types."
```

- [ ] **Step 6: Verify branch state**

```bash
git log --oneline ty/feature/tools-expansion --not main
git diff main --stat
```

Confirm all changes are on the feature branch and main is untouched.
