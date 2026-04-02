# Agent Config Flow - Session-Bound Configuration

This document traces how session-bound agent configuration controls Genie space connections and agent behaviour.

## Overview

Configuration is now session-bound rather than profile-based. Each session carries an `agent_config` JSON column that determines which tools and settings the agent uses. Five tool types are supported: Genie Space, Agent Bricks, Vector Index, MCP Server, and Model Endpoint (see also [tools-expansion.md](tools-expansion.md)). Key behaviours:

1. **Agent built per-request** from the session's `agent_config` via `build_agent_for_request()` in `src/services/agent_factory.py`
2. **Multiple Genie spaces** supported per session, each with a unique tool name and its own `conversation_id`
3. **No singleton agent** -- `ChatService` no longer holds `self.agent`
4. **Profiles are optional snapshots** -- save a session's config as a profile, or load a profile into a session

### Agent Config Schema

Defined in `src/api/schemas/agent_config.py` as `AgentConfig`:

```json
{
  "tools": [
    {
      "type": "genie",
      "space_id": "01abc...",
      "space_name": "Sales Data",
      "description": "Revenue and pipeline metrics",
      "conversation_id": "conv_xyz..."
    }
  ],
  "slide_style_id": 3,
  "deck_prompt_id": 7,
  "system_prompt": null,
  "slide_editing_instructions": "Always use bullet points..."
}
```

`AgentConfig.tools` is a discriminated union (`ToolEntry`) keyed on the `type` field. The five tool type schemas:

| Type | Discriminator | Key Fields | Description |
|------|--------------|------------|-------------|
| `genie` | `GenieTool` | `space_id`, `space_name`, `description?`, `conversation_id?` | Native Genie space tool |
| `mcp` | `MCPTool` | `connection_name`, `server_name`, `description?`, `config?` | MCP server via UC HTTP connections |
| `vector_index` | `VectorIndexTool` | `endpoint_name`, `index_name`, `description?`, `columns?`, `num_results` | Vector search index for similarity search |
| `model_endpoint` | `ModelEndpointTool` | `endpoint_name`, `endpoint_type?`, `description?` | Foundation models and custom ML endpoints |
| `agent_bricks` | `AgentBricksTool` | `endpoint_name`, `description?` | Knowledge assistants and supervisor agents |

A model validator on `AgentConfig` prevents duplicate tools (keyed by type + primary identifier).

The `slide_editing_instructions` field provides custom instructions that guide the agent when editing slides (e.g. formatting preferences, style rules).

---

## Step-by-Step Flow

### 1. Frontend: User Configures Tools via AgentConfigBar

**Component:** `AgentConfigBar`

The AgentConfigBar displays the session's current tool list as chips. Users can:
- Add tools (Genie spaces, Agent Bricks, Vector Indexes, MCP servers, Model Endpoints) from the tool discovery endpoint
- Remove tools from the session
- View Genie conversation links directly from tool chips

Changes call the agent config API endpoints to update the session.

---

### 2. Frontend Context: AgentConfigContext

**File:** `frontend/src/contexts/AgentConfigContext.tsx`

Replaces the old `ProfileContext`. Provides:
- `agentConfig` -- current session's agent configuration
- `updateConfig(config)` -- full config update via `PUT /api/sessions/:id/agent-config` (optimistic update with revert on failure)
- `addTool(tool)` / `removeTool(tool)` -- convenience mutators that build an updated config and call `updateConfig()`
- `updateTool(spaceId, updates)` -- update fields on a Genie tool by space ID
- `updateToolEntry(tool)` -- replace a tool entry in-place, matched by type + primary key
- `setStyle(styleId)` / `setDeckPrompt(promptId)` -- update style and prompt selections
- `loadProfile(profileId)` -- load a saved profile via `POST /api/sessions/:id/load-profile/:profile_id`
- `saveAsProfile(name, description?)` -- snapshot config via `POST /api/profiles/save-from-session/:session_id`
- `refreshConfig()` -- re-fetch config from backend
- `isPreSession` -- whether the context is operating in pre-session (localStorage) mode

All tool mutations flow through `updateConfig()`. There is no separate `updateTools()` export.

---

### 3. Backend: Agent Config Endpoints

**Routes:** `src/api/routes/agent_config.py`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/sessions/{id}/agent-config` | Read session config |
| `PUT` | `/api/sessions/{id}/agent-config` | Replace full config |
| `PATCH` | `/api/sessions/{id}/agent-config/tools` | Add/remove tools |

Config is validated with Pydantic models and stored as JSON on the `user_sessions.agent_config` column.

---

### 4. Backend: Per-Request Agent Build

**File:** `src/services/agent_factory.py`

```
ChatService.send_message(session_id, message)
  └─> build_agent_for_request(session_id)
        ├─ Load agent_config from user_sessions
        ├─ Resolve slide_style_id → style content
        ├─ Resolve deck_prompt_id → prompt content
        ├─ Create Genie tools (one per space in agent_config.tools)
        └─ Return configured SlideGeneratorAgent
```

Each Genie space tool:
- Has a unique name derived from the space name
- Tracks its own `conversation_id` in the agent config
- Initializes a new conversation on first use, then persists the ID back to `agent_config`

---

### 5. Genie Conversation Management

Unlike the old system where a single `genie_conversation_id` lived on the session, conversation IDs are now stored **per-tool** inside `agent_config.tools[].conversation_id`.

When the agent invokes a Genie tool:
1. The tool checks its `conversation_id` in the agent config
2. If `null`, initializes a new Genie conversation and persists the ID
3. Subsequent queries reuse the existing conversation

This supports multiple Genie spaces per session, each maintaining independent conversation state.

---

### 6. Profile Save/Load

Profiles are simplified to named snapshots of `agent_config` JSON.

**Save:** `POST /api/profiles/save-from-session/{session_id}`
- Reads the session's current `agent_config`
- Stores it as a named profile with `agent_config` JSON

**Load:** `POST /api/sessions/{id}/load-profile/{profile_id}`
- Reads the profile's `agent_config`
- Writes it to the session's `agent_config` column
- conversation_id fields are cleared; fresh conversations initialize on first Genie query

---

## Flow Summary

1. User opens generator (landing page `/`)
2. First chat message creates a session on the fly (session-creation-on-first-message)
3. User optionally configures tools via AgentConfigBar
4. Each chat request: `build_agent_for_request()` reads session's `agent_config`, builds agent
5. Agent queries configured Genie spaces, generates slides
6. User can save config as a profile for reuse, or load an existing profile

---

## Debugging

### Verify Agent Config

```sql
SELECT session_id, title, agent_config
FROM user_sessions
ORDER BY last_activity DESC;
```

### Verify Genie Conversation IDs

```sql
-- Check conversation_id values inside agent_config JSON
SELECT session_id, agent_config->'tools' AS tools
FROM user_sessions
WHERE agent_config IS NOT NULL;
```
