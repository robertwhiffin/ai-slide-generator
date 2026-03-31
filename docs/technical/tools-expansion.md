# Tools Expansion – Technical Overview

Agent configuration tools system supporting 5 tool types: Genie Space, Agent Bricks, Vector Index, MCP Server, and Model Endpoint.

---

## Stack / Entry Points

| Layer | Key Files |
|-------|-----------|
| **Schema** | `src/api/schemas/agent_config.py` — Pydantic models for all 5 tool types |
| **Discovery** | `src/api/routes/tools.py` — 8 REST endpoints for tool discovery |
| **Execution** | `src/services/tools/*.py` — per-type LangChain tool builders |
| **Agent Factory** | `src/services/agent_factory.py` — builds tools from AgentConfig per request |
| **Frontend Types** | `frontend/src/types/agentConfig.ts` — TypeScript interfaces, labels, colors |
| **Frontend UI** | `frontend/src/components/AgentConfigBar/` — tool picker, discovery panels, chips |
| **Genie Button** | `frontend/src/components/Layout/GenieDataButton.tsx` — header-level Genie deep-link |

---

## Architecture

```
User opens Agent Config
  → clicks "+ Genie Space" / "+ Agent Bricks" / "+ Vector Index" / etc.
  → discovery panel fetches from /api/tools/discover/*
  → user selects item → detail panel with description
  → Save & Add → tool added to AgentConfig.tools[] on session
  → on chat message: agent_factory builds LangChain tools from config
  → LLM agent decides which tools to call during slide generation
```

All discovery and execution uses OBO authentication via `get_user_client()`. Users only see and can query resources they have permission to access.

---

## Tool Types

| Type | Schema | Discovery Endpoint | Execution Module | Input Format |
|------|--------|--------------------|------------------|-------------|
| **Genie Space** | `GenieTool` | `GET /api/tools/discover/genie` | `genie_tool.py` | SDK `client.genie.create_message_and_wait()` |
| **Agent Bricks** | `AgentBricksTool` | `GET /api/tools/discover/agent-bricks` | `agent_bricks_tool.py` | SDK `client.api_client.do("POST", ..., body={"input": [messages]})` |
| **Vector Index** | `VectorIndexTool` | `GET /api/tools/discover/vector` | `vector_tool.py` | SDK `client.vector_search_indexes.query_index()` |
| **MCP Server** | `MCPTool` | `GET /api/tools/discover/mcp` | `mcp_tool.py` | `DatabricksMCPClient` via UC HTTP connection |
| **Model Endpoint** | `ModelEndpointTool` | `GET /api/tools/discover/model-endpoints` | `model_endpoint_tool.py` | SDK `client.api_client.do("POST", ...)` — auto-detects format |

---

## Data Contracts

### AgentConfig Schema (stored as JSON on sessions and profiles)

```python
class AgentConfig(BaseModel):
    tools: list[ToolEntry] = []          # Union of 5 tool types
    slide_style_id: Optional[int] = None
    deck_prompt_id: Optional[int] = None
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None
```

### ToolEntry Discriminated Union

```python
ToolEntry = Union[GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool]
# Discriminated by the "type" field
```

### Tool Schemas

| Tool | Required Fields | Optional Fields |
|------|----------------|-----------------|
| `GenieTool` | `type="genie"`, `space_id`, `space_name` | `description`, `conversation_id` |
| `MCPTool` | `type="mcp"`, `connection_name`, `server_name` | `description`, `config` |
| `VectorIndexTool` | `type="vector_index"`, `endpoint_name`, `index_name` | `description`, `columns`, `num_results` (default 5) |
| `ModelEndpointTool` | `type="model_endpoint"`, `endpoint_name` | `description`, `endpoint_type` |
| `AgentBricksTool` | `type="agent_bricks"`, `endpoint_name` | `description` |

---

## Discovery Endpoints

All endpoints use `get_user_client()` for OBO authentication.

| Endpoint | SDK Call | Returns |
|----------|---------|---------|
| `GET /api/tools/discover/genie` | `client.genie.list_spaces()` | Genie spaces with descriptions |
| `GET /api/tools/discover/vector` | `client.vector_search_endpoints.list_endpoints()` | ONLINE endpoints with `num_indexes > 0` |
| `GET /api/tools/discover/vector/{ep}/indexes` | `client.vector_search_indexes.list_indexes()` | Indexes with embedding support only |
| `GET /api/tools/discover/vector/{ep}/{idx}/columns` | `client.vector_search_indexes.get_index()` | Column names and types |
| `GET /api/tools/discover/mcp` | `client.connections.list()` | UC HTTP connections |
| `GET /api/tools/discover/model-endpoints` | `client.serving_endpoints.list()` | Non-agent endpoints (excludes `agent/*` and `llm/v1/embeddings`) |
| `GET /api/tools/discover/agent-bricks` | `client.serving_endpoints.list()` | Agent endpoints only (`task` starts with `agent/`) |

### Response Format

```json
{
  "items": [
    { "id": "...", "name": "...", "description": "...", "metadata": {} }
  ]
}
```

### Vector Index Discovery Notes

- **Endpoint listing** uses a 40-second timeout wrapper (ThreadPoolExecutor) because the SDK retries indefinitely on rate limits
- **Endpoints with 0 indexes** are filtered out — users only see endpoints with data
- **Index listing** filters to embedding-compatible indexes only (must have `embedding_source_columns`). Indexes without embedding support can't be queried with text
- **Index count** shown next to each endpoint name for quick reference

### Model Endpoint Discovery Notes

- **Embedding endpoints** (`llm/v1/embeddings`) are excluded — they return vectors, not text
- **Agent endpoints** (`agent/*`) are excluded — shown in Agent Bricks instead
- **Foundation badge**: `llm/v1/chat`, `llm/v1/completions`
- **Custom badge**: everything else

---

## Execution Modules

All modules are in `src/services/tools/`:

### genie_tool.py
- Functions: `initialize_genie_conversation()`, `query_genie_space()`, `build_genie_tool()`
- Conversation IDs tracked per space in `session_data` via closure
- Auth: `get_user_client()` directly

### vector_tool.py
- Function: `build_vector_tool(config, index)`
- Uses SDK `client.vector_search_indexes.query_index()`
- Token extracted at query time inside closure (not at build time)
- Auth: `get_user_client()` → extract `config.token` at query time

### agent_bricks_tool.py
- Function: `build_agent_bricks_tool(config, index)`
- Uses `client.api_client.do("POST", path, body={"input": [messages]})`
- Handles both `output` (v1/responses) and `choices` (v2/chat) response formats
- Empty responses handled gracefully with informative message
- Auth: `get_user_client()` directly

### model_endpoint_tool.py
- Function: `build_model_endpoint_tool(config, index)`
- Auto-detects endpoint type via `task` metadata (1-hour in-memory cache)
- Foundation models: `{"messages": [...]}`
- Custom ML: `{"dataframe_records": [...]}`
- Trial-and-error fallback if detection fails
- Auth: `get_user_client()` directly

### mcp_tool.py
- Function: `build_mcp_tools(config)` — returns list (MCP servers expose multiple tools)
- Uses `DatabricksMCPClient` via UC HTTP connection proxy: `{host}/api/2.0/mcp/external/{connection_name}`
- Thread-isolated execution (DatabricksMCPClient uses asyncio.run internally)
- Dynamic Pydantic schema built from MCP tool definitions
- Falls back to generic `search` tool if discovery fails
- Auth: extracts token from `get_user_client()`, passes to thread

---

## Frontend Components

### Tool Picker (`AgentConfigBar/ToolPicker.tsx`)
- Renders 5 category buttons: `+ Genie Space`, `+ Agent Bricks`, `+ Vector Index`, `+ MCP Server`, `+ Model Endpoint`
- Each opens a type-specific discovery panel inline

### Discovery Panels (`AgentConfigBar/tools/`)
| Component | Tool Type | Flow |
|-----------|-----------|------|
| `GenieDiscovery.tsx` | Genie Space | Search → select → GenieDetailPanel |
| `AgentBricksDiscovery.tsx` | Agent Bricks | Search → select → ToolDetailPanel |
| `VectorIndexDiscovery.tsx` | Vector Index | Select endpoint → select index → ToolDetailPanel with columns |
| `MCPDiscovery.tsx` | MCP Server | Search → select → ToolDetailPanel |
| `ModelEndpointDiscovery.tsx` | Model Endpoint | Search → select → ToolDetailPanel with Foundation/Custom badge |

### Tool Chips (`AgentConfigBar.tsx`)
- Colored badges per type: GENIE (blue), AGENT (teal), VECTOR (indigo), MCP (green), MODEL (amber)
- Click to edit (opens detail panel), X to remove
- Constants in `types/agentConfig.ts`: `TOOL_TYPE_BADGE_LABELS`, `TOOL_TYPE_COLORS`

### Genie Header Button (`Layout/GenieDataButton.tsx`)
- Renders in page header next to session title and savepoint dropdown
- Hidden when no Genie tools in session
- Single Genie: click opens conversation in new tab
- Multiple Genies: dropdown listing all conversations
- Replaced the per-slide Database icon that was on each `SlideTile`

---

## Profile Save/Load

Profile save/load works automatically for all 5 tool types:

1. **Save as Profile**: `POST /api/profiles/save-from-session/{session_id}` takes the session's `agent_config` JSON (which includes all tools) and stores it as a profile
2. **Load Profile**: `POST /api/sessions/{id}/load-profile/{profile_id}` writes the profile's `agent_config` back to the session
3. **Deserialization**: `resolve_agent_config()` calls `AgentConfig.model_validate(raw)` — Pydantic's discriminated union handles all 5 tool types automatically

No additional code was needed for profile support.

---

## Known Limitations

### Vector Index
- **Endpoint listing includes non-embedding endpoints**: The `num_indexes` count from the API includes ALL indexes (embedding and non-embedding). Some endpoints may show "1 index" but have no compatible indexes for text search. The index step filters these correctly and shows a clear message.
- **User permissions required**: Users need UC access on the vector index. If they lack permission, they see: "Insufficient permissions for UC entity."
- **Rate limiting on shared workspaces**: The SDK retries indefinitely on 429 responses. We wrap the call in a 40-second timeout to prevent infinite loading. In production (Databricks Apps, internal network) this is not an issue.

### Agent Bricks
- **Empty responses from misconfigured agents**: Some agent endpoints return HTTP 200 with empty body. Our code handles this gracefully with an informative message.
- **Description not auto-populated**: The agent description from Agent Builder UI is not accessible via any public API. Users must type a description manually.
- **Input format**: Agent endpoints require `{"input": [...]}` not `{"messages": [...]}`. Our code uses the correct format.

### MCP Server
- **Requires `databricks-mcp` package**: Listed in `requirements.txt` and `pyproject.toml`. If missing, a clear error message is shown.
- **Requires UC HTTP connection**: Users must have a Unity Catalog HTTP connection configured pointing to their MCP server. They need `USE CONNECTION` permission.
- **Thread isolation**: MCP execution runs in a separate thread because `DatabricksMCPClient` uses `asyncio.run()` internally which conflicts with FastAPI's event loop.

### Model Endpoint
- **Embedding endpoints excluded**: `llm/v1/embeddings` endpoints are filtered out — they return vectors, not text usable by the slide generator agent.
- **Foundation vs Custom detection**: Uses the endpoint's `task` metadata field. If the field is missing, falls back to trial-and-error across all formats.

---

## Testing

- **944 unit tests** covering schemas, discovery, tool builders, agent factory, and existing functionality
- **Schema tests**: Serialization/deserialization round-trip for all 5 types
- **Discovery tests**: Mock SDK calls, verify filtering, error handling for all endpoints
- **Builder tests**: Verify LangChain tool creation, naming, description handling
- **Agent factory tests**: Verify `_build_tools()` dispatches to correct builders

---

## Cross-References

- `docs/technical/backend-overview.md` — Agent lifecycle and per-request construction
- `docs/technical/frontend-overview.md` — AgentConfigBar and UI architecture
- `docs/technical/profile-switch-genie-flow.md` — agent_config schema and Genie conversation persistence
- `docs/technical/configuration-validation.md` — agent_config validation
- `docs/technical/database-configuration.md` — Session table schema (agent_config JSON column)
- `docs/technical/permissions-model.md` — OBO authentication and access control
