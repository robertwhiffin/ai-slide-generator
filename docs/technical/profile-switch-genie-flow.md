# Agent Config Flow - Session-Bound Configuration

This document traces how session-bound agent configuration controls Genie space connections and agent behaviour.

## Overview

Configuration is now session-bound rather than profile-based. Each session carries an `agent_config` JSON column that determines which tools (Genie spaces, MCP servers) and settings the agent uses. Key behaviours:

1. **Agent built per-request** from the session's `agent_config` via `build_agent_for_request()` in `src/services/agent_factory.py`
2. **Multiple Genie spaces** supported per session, each with a unique tool name and its own `conversation_id`
3. **No singleton agent** -- `ChatService` no longer holds `self.agent`
4. **Profiles are optional snapshots** -- save a session's config as a profile, or load a profile into a session

### Agent Config Schema

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
  "slide_editing_instructions": null
}
```

---

## Step-by-Step Flow

### 1. Frontend: User Configures Tools via AgentConfigBar

**Component:** `AgentConfigBar`

The AgentConfigBar displays the session's current tool list as chips. Users can:
- Add Genie spaces or MCP servers from the tool discovery endpoint
- Remove tools from the session
- View Genie conversation links directly from tool chips

Changes call the agent config API endpoints to update the session.

---

### 2. Frontend Context: AgentConfigContext

**File:** `frontend/src/contexts/AgentConfigContext.tsx`

Replaces the old `ProfileContext`. Provides:
- `agentConfig` -- current session's agent configuration
- `updateTools()` -- add/remove tools via `PATCH /api/sessions/:id/agent-config/tools`
- `updateConfig()` -- full config update via `PUT /api/sessions/:id/agent-config`
- `loadProfile()` -- load a saved profile via `POST /api/sessions/:id/load-profile/:profile_id`
- `saveAsProfile()` -- snapshot config via `POST /api/profiles/save-from-session/:session_id`

---

### 3. Backend: Agent Config Endpoints

**Routes:** `src/api/routes/sessions.py` (agent-config sub-routes)

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
