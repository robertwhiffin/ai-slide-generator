# Tools Expansion Design Spec

**Date:** 2026-03-30
**Branch:** `ty/feature/tools-expansion`
**Status:** Draft

## Overview

Expand the tools system to support 5 tool types in the agent config. Currently the app supports Genie spaces (working) and MCP servers (schema only, no execution). This spec adds full execution for MCP and introduces 3 new tool types: Vector Index, Model Endpoint, and Agent Bricks.

All tools are inline on the session's `AgentConfig.tools[]` — no centralized tool library, no mandatory profiles. Users can start generating with zero tools and add tools via the agent config bar at any time.

## Goals

- Add Vector Index, Model Endpoint, and Agent Bricks as new tool types
- Wire up MCP execution (currently schema-only with no backend execution)
- Provide discovery APIs for each tool type (all OBO-authenticated)
- Update the frontend tool picker from single `+ Add Genie` to category-first selection
- Move the Genie deep-link button from per-slide to a top-level header button with multi-genie dropdown
- Ensure profile save/load works automatically for all tool types
- Production-ready: OBO auth, proper error handling, verified SDK calls

## Non-Goals

- No centralized tool library or `ToolLibrary` database table
- No profile-tool assignment workflow
- No database migrations (tools stay as JSON in `agent_config`)
- No changes to profile save/load mechanism (it already works)
- No changes to Slide Style / Deck Prompt dropdowns

---

## Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Agent Bricks discovery | Single flat list of all agent endpoints | No reliable API to distinguish KA vs Supervisor; endpoint names are descriptive enough |
| 2 | Tool picker organization | Category-first (`+ Genie Space`, `+ Agent Bricks`, etc.) | 5 types would be noisy in flat list; category buttons give clear mental model |
| 3 | Vector Index config | 2-step (endpoint -> index) with all columns selected by default, optional deselect | Simpler for non-technical users; agent works with any columns |
| 4 | Genie top-level button | Header bar next to session title/savepoint | Always visible, supports multi-genie dropdown, matches UX intent |
| 5 | MCP discovery | UC HTTP Connection discovery via Databricks API | Databricks-native, OBO auth, no static config files |
| 6 | Model Endpoint display | All non-agent endpoints in one list with Foundation/Custom badges | Simple; agent bricks already separated out |
| 7 | Tool chips pattern | Same chip + detail panel for all types | Consistent UX; click to edit, X to remove |

---

## Schema & Data Model

### New Pydantic Schemas

Added to `src/api/schemas/agent_config.py`:

```python
class VectorIndexTool(BaseModel):
    type: Literal["vector_index"]
    endpoint_name: str
    index_name: str
    description: Optional[str] = None
    columns: Optional[list[str]] = None  # None = all columns
    num_results: int = 5

class ModelEndpointTool(BaseModel):
    type: Literal["model_endpoint"]
    endpoint_name: str
    endpoint_type: Optional[str] = None  # "foundation" | "custom" — auto-detected
    description: Optional[str] = None

class AgentBricksTool(BaseModel):
    type: Literal["agent_bricks"]
    endpoint_name: str
    description: Optional[str] = None
```

### MCP Schema Update

Change `server_uri` to `connection_name` for UC HTTP connection approach:

```python
class MCPTool(BaseModel):
    type: Literal["mcp"]
    connection_name: str       # UC HTTP connection name (was server_uri)
    server_name: str           # Display name (unchanged)
    description: Optional[str] = None  # New field
    config: dict = Field(default_factory=dict)
```

This is safe because MCP was never functional — no saved MCP tools exist in practice.

### Updated ToolEntry Union

```python
ToolEntry = Annotated[
    Union[GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool],
    Field(discriminator="type")
]
```

### Duplicate Detection Update

The `no_duplicate_tools` validator in `AgentConfig` must handle new types:

```python
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
```

### Frontend TypeScript Types

Updated in `frontend/src/types/agentConfig.ts`:

```typescript
interface VectorIndexTool {
  type: 'vector_index';
  endpoint_name: string;
  index_name: string;
  description?: string;
  columns?: string[];
  num_results?: number;
}

interface ModelEndpointTool {
  type: 'model_endpoint';
  endpoint_name: string;
  endpoint_type?: string;
  description?: string;
}

interface AgentBricksTool {
  type: 'agent_bricks';
  endpoint_name: string;
  description?: string;
}

// Updated MCPTool
interface MCPTool {
  type: 'mcp';
  connection_name: string;  // was server_uri
  server_name: string;
  description?: string;
  config?: Record<string, unknown>;
}

type ToolEntry = GenieTool | MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool;
```

### No Database Migration

Tools remain as JSON within `UserSession.agent_config` and `ConfigProfile.agent_config`. No new tables. Profile save/load works automatically via `resolve_agent_config()` which calls `AgentConfig.model_validate(raw)` — Pydantic's discriminated union handles deserialization of all tool types.

---

## Backend — Discovery Endpoints

All endpoints use `get_user_client()` for OBO authentication. Users only see resources they have permission to access.

Added to `src/api/routes/tools.py` (or split into sub-module):

| Endpoint | Returns | SDK Call |
|----------|---------|----------|
| `GET /api/tools/discover/genie` | Genie spaces | `client.genie.list_spaces()` |
| `GET /api/tools/discover/vector` | Vector search endpoints | `client.vector_search_endpoints.list_endpoints()` |
| `GET /api/tools/discover/vector/{endpoint}/indexes` | Indexes for endpoint | `client.vector_search_indexes.list_indexes(endpoint)` |
| `GET /api/tools/discover/vector/{endpoint}/{index}/columns` | Columns for index | `VectorSearchClient.get_index()` -> schema |
| `GET /api/tools/discover/mcp` | UC HTTP connections | `client.connections.list()` filtered to HTTP type |
| `GET /api/tools/discover/model-endpoints` | Non-agent serving endpoints | `client.serving_endpoints.list()` where task NOT `agent/*` |
| `GET /api/tools/discover/agent-bricks` | Agent serving endpoints | `client.serving_endpoints.list()` where task starts with `agent/` |

### Response Format

Each discovery endpoint returns a consistent shape:

```python
{
    "items": [
        {
            "name": "...",           # Display name
            "id": "...",             # Unique identifier (space_id, endpoint_name, connection_name)
            "description": "...",    # Auto-populated description
            "metadata": {}           # Type-specific extra info
        }
    ]
}
```

### Existing `GET /api/tools/available` Endpoint

The current `GET /api/tools/available` endpoint lists Genie spaces + MCP servers from config in a flat list. This is replaced by the per-type `/api/tools/discover/*` endpoints. The old endpoint will be **deprecated and removed** — the frontend will call per-type discovery endpoints instead.

### Existing `src/services/tools.py`

The current `tools.py` contains `initialize_genie_conversation()` and `query_genie_space()`. These functions will be **moved to `src/services/tools/genie_tool.py`** as part of the refactor. The original `tools.py` file will be removed. Imports in `agent_factory.py` and `chat_service.py` will be updated.

### SDK Verification

Every SDK call will be verified against the current `databricks-sdk` version at implementation time. Method names, parameters, and response shapes will be confirmed — nothing assumed from old repo.

---

## Backend — Tool Execution

Each tool type gets its own execution module under `src/services/tools/`:

```
src/services/tools/
├── __init__.py                # Re-exports builder functions
├── genie_tool.py              # Extracted from agent_factory.py
├── vector_tool.py             # New — VectorSearchClient integration
├── mcp_tool.py                # New — DatabricksMCPClient, thread-isolated
├── model_endpoint_tool.py     # New — auto-detect foundation/custom
├── agent_bricks_tool.py       # New — agent format execution
```

### Builder Functions

Each module exports a builder that returns a LangChain `StructuredTool`:

| Module | Function | Returns | OBO Pattern |
|--------|----------|---------|-------------|
| `genie_tool.py` | `build_genie_tool(config, session_data, index)` | Single tool | `get_user_client()` directly |
| `vector_tool.py` | `build_vector_tool(config, index)` | Single tool | `get_user_client()` -> extract token at query time -> `VectorSearchClient(token=...)` |
| `mcp_tool.py` | `build_mcp_tools(config)` | List of tools | `get_user_client()` -> extract token -> pass to isolated thread -> `DatabricksMCPClient` |
| `model_endpoint_tool.py` | `build_model_endpoint_tool(config, index)` | Single tool | `get_user_client()` -> `client.api_client.do()` |
| `agent_bricks_tool.py` | `build_agent_bricks_tool(config, index)` | Single tool | `get_user_client()` -> `client.api_client.do()` (agent format) |

### OBO Token Handling

- Token is extracted **inside the tool's closure at query time**, not at build time
- Ensures freshest token from request context
- Consistent with how Genie already works in the current repo

### Tool Naming

Tools need unique names for the LLM. Pattern with index suffix for duplicates:

| Type | Name Pattern | Example |
|------|-------------|---------|
| Genie | `query_genie_space`, `query_genie_space_2` | Existing pattern |
| Vector Index | `search_vector_index`, `search_vector_index_2` | New |
| MCP | `mcp_{connection}_{tool_name}` | Namespaced per connection |
| Model Endpoint | `query_model_endpoint`, `query_model_endpoint_2` | New |
| Agent Bricks | `query_agent`, `query_agent_2` | New |

### Agent Factory Changes

`agent_factory.py` — `_build_tools()` extended:

```python
def _build_tools(config: AgentConfig, session_data: dict) -> list[StructuredTool]:
    tools = [image_search_tool]
    genie_idx = vector_idx = model_idx = agent_idx = 0

    for tool_entry in config.tools:
        if isinstance(tool_entry, GenieTool):
            genie_idx += 1
            tools.append(build_genie_tool(tool_entry, session_data, genie_idx))
        elif isinstance(tool_entry, VectorIndexTool):
            vector_idx += 1
            tools.append(build_vector_tool(tool_entry, vector_idx))
        elif isinstance(tool_entry, MCPTool):
            tools.extend(build_mcp_tools(tool_entry))
        elif isinstance(tool_entry, ModelEndpointTool):
            model_idx += 1
            tools.append(build_model_endpoint_tool(tool_entry, model_idx))
        elif isinstance(tool_entry, AgentBricksTool):
            agent_idx += 1
            tools.append(build_agent_bricks_tool(tool_entry, agent_idx))

    return tools
```

### MCP Execution Details

Ported from old repo with adaptation to current architecture:

- Uses `connection_name` to build proxy URL: `{host}/api/2.0/mcp/external/{connection_name}`
- Runs in `ThreadPoolExecutor(max_workers=1)` for asyncio isolation
- Auto-discovers tools from MCP server via `list_tools()`
- Builds dynamic Pydantic `args_schema` from MCP tool input schemas
- Falls back to generic `search` tool if discovery fails
- 120s timeout on execution, 60s on discovery
- OBO: fresh `WorkspaceClient(host, token)` created in the thread

### Model Endpoint Execution Details

Ported from old repo:

- Auto-detects endpoint type via `task` metadata field (1hr in-memory cache)
- Foundation Model (`llm/v1/chat`): `{"messages": [{"role": "user", "content": "..."}]}`
- Custom ML (other): `{"dataframe_records": [{...}]}`
- Trial-and-error fallback if detection fails
- OBO via `get_user_client().api_client.do()`

### Agent Bricks Execution Details

Same SDK call as Model Endpoint but with agent format:

- Agent endpoints (`agent/*`): `{"input": [{"role": "user", "content": "..."}]}`
- Response: `{"output": [{"type": "message", "content": [{"text": "..."}]}]}`
- OBO via `get_user_client().api_client.do()`

### Vector Search Execution Details

Ported from old repo:

- Token extracted at query time: `get_user_client().config.token`
- `VectorSearchClient(workspace_url=host, personal_access_token=token)`
- `index.similarity_search(query_text=query, columns=columns, num_results=num_results)`
- Returns results as formatted JSON string for LLM consumption

### Implementation Verification Checklist

Each tool implementation must verify:

- [ ] SDK method exists in current `databricks-sdk` version
- [ ] OBO token flows correctly end-to-end
- [ ] Import paths are correct (package names may have changed)
- [ ] Response shapes match expectations
- [ ] Error handling covers auth failures, timeouts, not-found
- [ ] Thread isolation still required for MCP (check if `databricks-mcp` changed)
- [ ] Endpoint `task` field still reliable for type detection

---

## Frontend — Tool Picker

### Category Buttons

Replace the single `+ Add Genie` button with category buttons:

```
Tools
  + Genie Space    + Agent Bricks    + Vector Index
  + MCP Server     + Model Endpoint
```

Each button opens a type-specific discovery panel **in the same inline space** within the Agent Config section.

### Refactored Components

```
components/AgentConfigBar/
├── ToolPicker.tsx                  # Refactored — renders category buttons
├── GenieDetailPanel.tsx            # Existing — edit mode for Genie tools
├── tools/
│   ├── GenieDiscovery.tsx          # Extracted from current ToolPicker search
│   ├── VectorIndexDiscovery.tsx    # New — endpoint -> index -> columns
│   ├── MCPDiscovery.tsx            # New — UC connection search
│   ├── ModelEndpointDiscovery.tsx  # New — serving endpoints with badges
│   └── AgentBricksDiscovery.tsx    # New — agent endpoints search
```

### Discovery Panel UX (Same Pattern for All)

1. Fetch available items from discovery API
2. Search/filter within the scrollable list (max-height, no overflow)
3. User selects one -> detail panel shows name, ID, editable Description
4. Save & Add -> calls `addTool()` from AgentConfigContext
5. Panel closes, chip appears in Tools row

### Vector Index Discovery — Special Flow

1. Fetch vector endpoints -> show dropdown
2. User picks endpoint -> fetch indexes for that endpoint -> show dropdown
3. User picks index -> fetch columns -> show checkboxes (all selected by default)
4. User can optionally deselect columns
5. Save & Add

### Tool Chips

Each tool type gets a colored badge:

| Type | Badge | Color |
|------|-------|-------|
| Genie | `GENIE` | Blue (`bg-blue-100 text-blue-800`) |
| Agent Bricks | `AGENT` | Teal (`bg-teal-100 text-teal-800`) |
| Vector Index | `VECTOR` | Indigo (`bg-indigo-100 text-indigo-800`) |
| MCP | `MCP` | Green (`bg-green-100 text-green-800`) |
| Model Endpoint | `MODEL` | Amber (`bg-amber-100 text-amber-800`) |

Click chip -> opens edit panel (same detail panel, edit mode). X -> removes tool.

### No Context Changes

`AgentConfigContext.tsx` already has generic `addTool()`, `removeTool()`, `updateTool()` that work with any `ToolEntry`. No changes needed.

---

## Frontend — Genie Header Button

### New Component: `GenieDataButton.tsx`

Located in `components/Layout/`. Renders in the header bar next to session title and savepoint dropdown.

**Behavior:**
- **No genie tools in session**: Button hidden
- **Single genie tool with conversation_id**: Click opens conversation in new tab directly
- **Multiple genie tools**: Click shows dropdown listing all active Genie conversations by name, each clickable
- **Genie tool without conversation_id** (not yet queried): Shows toast "No Genie queries in this session yet"

**Styling:** Purple theme (`bg-purple-500 hover:bg-purple-700 text-white`) to distinguish from other header actions.

**Data source:** Reads `GenieTool` entries from current `AgentConfig.tools[]` via `AgentConfigContext`. Uses `api.getGenieLink(sessionId, spaceId)` for URL generation.

### Per-Slide Genie Icon Removal

Remove from `SlideTile.tsx`:
- State: `isLoadingGenieLink`
- Handler: `handleOpenGenieLink`
- UI: `<Tooltip text="View source data">` button with `Database` icon
- Update `HelpPage.tsx` to remove "Database icon on each slide tile" documentation

---

## Frontend API Client Updates

Add discovery methods to `frontend/src/services/api.ts`:

```typescript
// Discovery endpoints
discoverGenieSpaces(): Promise<DiscoveryResponse>
discoverVectorEndpoints(): Promise<DiscoveryResponse>
discoverVectorIndexes(endpointName: string): Promise<DiscoveryResponse>
discoverVectorColumns(endpointName: string, indexName: string): Promise<ColumnDiscoveryResponse>
discoverMCPConnections(): Promise<DiscoveryResponse>
discoverModelEndpoints(): Promise<DiscoveryResponse>
discoverAgentBricks(): Promise<DiscoveryResponse>
```

---

## Testing Strategy

### Backend Unit Tests

- Schema tests: Validate serialization/deserialization for all 5 tool types
- Duplicate detection: Verify `no_duplicate_tools` validator for new types
- Discovery endpoint tests: Mock SDK calls, verify OBO client usage
- Tool builder tests: Mock SDK clients, verify LangChain tool creation
- Agent factory tests: Verify `_build_tools()` handles all types with correct indexing

### Frontend Tests

- ToolPicker renders all 5 category buttons
- Each discovery panel fetches from correct API endpoint
- Chip rendering for each tool type with correct badge
- Add/remove/edit flow for each tool type
- GenieDataButton visibility logic (hidden/single/multi)
- Profile save/load preserves all tool types

### Integration Tests

- End-to-end: Add tool via UI -> saved to session -> agent uses tool during generation
- Profile round-trip: Add tools -> save as profile -> load profile -> tools restored
- Multi-tool session: Multiple tools of different types coexist

---

## Implementation Order

1. **Schema** — Add new Pydantic types + TypeScript types + update validators
2. **Discovery endpoints** — Backend APIs for each tool type (verify SDK calls)
3. **Tool execution modules** — `vector_tool.py`, `mcp_tool.py`, `model_endpoint_tool.py`, `agent_bricks_tool.py`
4. **Agent factory** — Extend `_build_tools()` to handle all types
5. **Frontend tool picker** — Category buttons + discovery panels
6. **Frontend tool chips** — Badges + edit panels for new types
7. **Genie header button** — New `GenieDataButton.tsx` + remove per-slide icon
8. **Testing** — Unit + integration tests
9. **Cleanup** — Remove deprecated code, update help docs

---

## Files Modified

### Backend (Modified)
- `src/api/schemas/agent_config.py` — New tool types, updated union, updated validator
- `src/api/routes/tools.py` — Discovery endpoints
- `src/services/agent_factory.py` — Extended `_build_tools()`

### Backend (New)
- `src/services/tools/genie_tool.py` — Extracted from agent_factory
- `src/services/tools/vector_tool.py` — Vector search execution
- `src/services/tools/mcp_tool.py` — MCP execution with thread isolation
- `src/services/tools/model_endpoint_tool.py` — Model serving execution
- `src/services/tools/agent_bricks_tool.py` — Agent endpoint execution
- `src/services/tools/__init__.py` — Re-exports

### Frontend (Modified)
- `src/types/agentConfig.ts` — New TypeScript types
- `src/components/AgentConfigBar/ToolPicker.tsx` — Category buttons
- `src/components/SlidePanel/SlideTile.tsx` — Remove genie per-slide icon
- `src/components/Help/HelpPage.tsx` — Update documentation
- `src/services/api.ts` — Discovery API methods

### Frontend (New)
- `src/components/AgentConfigBar/tools/GenieDiscovery.tsx`
- `src/components/AgentConfigBar/tools/VectorIndexDiscovery.tsx`
- `src/components/AgentConfigBar/tools/MCPDiscovery.tsx`
- `src/components/AgentConfigBar/tools/ModelEndpointDiscovery.tsx`
- `src/components/AgentConfigBar/tools/AgentBricksDiscovery.tsx`
- `src/components/Layout/GenieDataButton.tsx`

### Files NOT Modified
- `src/contexts/AgentConfigContext.tsx` — Already generic
- `src/api/routes/profiles.py` — Profile save/load already works
- `src/database/models/*` — No schema changes
- Slide Style / Deck Prompt dropdowns — Untouched
