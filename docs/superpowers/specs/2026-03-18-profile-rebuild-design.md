# Profile Rebuild: Session-Bound Agent Configuration

**Date:** 2026-03-18
**Status:** Approved
**Branch:** feature/profile-rebuild

## Problem

The current profile system creates friction in the user flow. New users must navigate to a separate profile page, create a profile (configuring AI infra, Genie space, style, prompts), and then return to the generator before they can create a single slide. This interrupts the natural flow and increases time-to-value.

Additionally, profiles as a concept conflate "agent configuration" with "reusable templates." Users shouldn't need to understand profiles to start generating slides.

## Solution

Invert the configuration model: instead of pre-defining profiles that drive the agent, users land directly on the generator with a working default agent and configure it on the fly. Configuration is stored per-session. Users can optionally save their configuration as a named profile for reuse.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Default landing | Pre-session generator at `/` | Fastest time-to-value; no setup required |
| Default agent state | LLM + default style, no tools | Works immediately for prompt-only slide generation |
| LLM selection | Fixed backend default, not user-configurable | Reduces complexity; one less decision for users |
| Config storage | JSON column on session table | Simple, flexible, naturally versioned with session |
| Config changes mid-session | Agent recreated per-request from config | Eliminates hot-reload locking; config always current |
| Profiles | Named snapshots saved from / loaded into sessions | Decoupled from agent lifecycle; opt-in reuse |
| Profile save/load semantics | One-way copy (not linked) | Avoids sync complexity; sessions are independent |
| Tool registration | `type` field routes to native LangChain or MCP | Genie stays native (preserves functionality); MCP for new tools |
| Existing profile pages | Demoted to "Saved Configurations" management | Still needed for rename/delete/load, but not the primary path |
| WelcomeSetup (Databricks auth) | Unchanged | Deployment-level concern, orthogonal to this work |

## Data Model

### Session Agent Config

New `agent_config` JSON column on `user_sessions`:

```python
agent_config = Column(JSON, nullable=True, default=None)
```

When `null`, the system uses defaults (no tools, default style, no deck prompt).

Schema:

```json
{
  "tools": [
    {
      "type": "genie",
      "space_id": "abc123",
      "space_name": "Sales Data",
      "description": "Q4 revenue and pipeline data"
    },
    {
      "type": "mcp",
      "server_uri": "https://...",
      "server_name": "Web Search",
      "config": {}
    }
  ],
  "slide_style_id": 3,
  "deck_prompt_id": 7,
  "system_prompt": null,
  "slide_editing_instructions": null
}
```

### Validation

A Pydantic model validates `agent_config` on write (`PUT /api/sessions/:id/agent-config`, `POST /api/chat/stream`, `POST /api/chat/async`, `POST /api/profiles/save-from-session`). Validation rules:

- **Tools**: each entry must have a valid `type` (`"genie"` or `"mcp"`). Genie tools require `space_id` and `space_name`. MCP tools require `server_uri` and `server_name`. Duplicate tools (same `type` + `space_id` or `server_uri`) are rejected.
- **References**: `slide_style_id` and `deck_prompt_id`, if set, must reference existing non-deleted library entries. Validated via DB lookup.
- **Prompts**: `system_prompt` and `slide_editing_instructions`, if set, must be non-empty strings.
- Invalid payloads return 422 with field-level error details (standard Pydantic/FastAPI behavior).

The `system_prompt` and `slide_editing_instructions` fields are optional overrides. When `null`, the backend defaults from `defaults.py` are used. When set, they replace the defaults for that session/profile. This preserves any customizations made under the old profile system.

The `type` field determines how each tool is registered with the agent:
- `"genie"` → instantiate the existing `GenieTool` directly as a LangChain tool (unchanged from today)
- `"mcp"` → connect to an MCP server and register its tools via the MCP protocol

This is extensible — future native tool types (e.g., `"sql_warehouse"`) are just another case in the agent factory.

### Genie Conversation Persistence

The existing `genie_conversation_id` column on `user_sessions` is unchanged. When the agent is built per-request, the session's `genie_conversation_id` is passed to the `GenieTool` constructor so it can continue an existing Genie conversation. After a request completes, any new or updated `genie_conversation_id` is persisted back to the session — exactly as it works today, just read/written per-request instead of held in a singleton.

### Profiles (Simplified)

The existing `config_profiles` table is simplified. Instead of FK relationships to `config_ai_infra`, `config_genie_spaces`, `config_prompts`, it stores the same JSON blob:

```python
# Simplified config_profiles
id              # PK
name            # string, unique, required
description     # optional text
is_default      # boolean — if true, new sessions start with this profile's agent_config instead of bare defaults. Only one profile can be default; setting a new default clears the flag on others (same constraint as today).
agent_config    # JSON (same schema as session agent_config)
created_at
created_by
updated_at
is_deleted      # soft-delete
```

### Tables Deprecated

These tables are no longer read by application code after migration:

- `config_ai_infra` — LLM is not user-configurable
- `config_genie_spaces` — Genie spaces move into `agent_config.tools`
- `config_prompts` — system prompt and slide editing instructions migrated into `agent_config` JSON (as optional overrides, `null` = use backend defaults); deck prompt is a reference ID in agent_config

### Tables Unchanged

- `slide_style_library` — global library, referenced by ID in `agent_config`
- `slide_deck_prompt_library` — global library, referenced by ID in `agent_config`
- `config_history` — dropped (unused in the application, not worth maintaining for lightweight config changes)

## API Changes

### New Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/sessions/:id/agent-config` | GET | Return current agent config for a session |
| `/api/sessions/:id/agent-config` | PUT | Update full agent config (persists to session) |
| `/api/sessions/:id/agent-config/tools` | PATCH | Add/remove a single tool |
| `/api/profiles/save-from-session/:session_id` | POST | Snapshot session config into a named profile |
| `/api/sessions/:id/load-profile/:profile_id` | POST | Copy profile config into session |
| `/api/profiles` | GET | List saved profiles |
| `/api/profiles/:id` | PUT | Rename/update description |
| `/api/profiles/:id` | DELETE | Soft-delete |
| `/api/tools/available` | GET | List available tools the user can add (see Tool Discovery below) |

### Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/sessions` | No longer requires profile ID. Creates with `agent_config: null` (defaults). |
| `POST /api/chat/stream` | **Primary chat endpoint (local dev, SSE).** Handles missing `session_id`: creates session with `agent_config` from request payload, processes message, returns new `session_id` in the SSE stream. If `agent_config` is also missing, uses defaults. Invalid tool references return 400. |
| `POST /api/chat/async` | **Primary chat endpoint (Databricks Apps, polling).** Same session-creation-on-first-message behavior as `/chat/stream`. Returns new `session_id` in the initial response so the frontend can begin polling. |
| `POST /api/chat` | **Sync endpoint (unused in practice).** Same changes for consistency, but not actively called by the frontend. |

### Tool Discovery

`GET /api/tools/available` returns tools the user can add to their agent config:

- **Genie spaces**: discovered via the Databricks SDK (`w.genie.list_spaces()` or equivalent). The user's Unity Catalog permissions determine which spaces are visible. Each result includes `space_id`, `space_name`, and optional `description`.
- **MCP servers**: defined in application config (`config/config.yaml` under an `mcp_servers` key). Admin registers available MCP server URIs and metadata at deployment time. This list is static per deployment.

The endpoint merges both sources into a unified response with `type` discriminator matching the `agent_config.tools` schema.

### Deprecated Endpoints

| Endpoint | Replacement |
|----------|-------------|
| `POST /api/settings/profiles/with-config` | `POST /api/profiles/save-from-session/:session_id` |
| `POST /api/settings/profiles/:id/load` | `POST /api/sessions/:id/load-profile/:profile_id` |
| `GET/PUT /api/settings/ai-infra/*` | Removed (LLM not configurable) |
| `GET/PUT /api/settings/genie/*` | Managed through agent-config tools |
| `GET/PUT /api/settings/prompts/*` | System prompt is backend-only; deck prompt is a reference in agent-config |
| `POST /api/settings/profiles/:id/set-default` | Replaced by `PUT /api/profiles/:id` with `is_default` field |
| `POST /api/settings/profiles/:id/duplicate` | Replaced by `POST /api/profiles/save-from-session` (or copy via load + save) |
| `POST /api/settings/profiles/reload` | Removed (agent built per-request, no reload needed) |

### Unchanged Endpoints

- `/api/settings/slide-styles/*` — global library
- `/api/settings/deck-prompts/*` — global library
- `/api/slides/*`, `/api/export/*`, `/api/verification/*`, `/api/images/*`

## Agent Lifecycle

### Current Model
Agent created once at startup, recreated on profile switch via `reload_agent()` with locking.

### New Model
Agent built **per-request** from the session's `agent_config`. There are two active chat endpoints; both follow the same lifecycle:

- **`POST /api/chat/stream`** (local dev) — SSE streaming. Agent is created, runs for the duration of the stream, and is discarded when the stream closes.
- **`POST /api/chat/async`** (Databricks Apps) — polling. Agent is created, runs to completion writing results to DB, and is discarded. The frontend polls for results separately.

In both cases the agent lives for exactly one chat turn (which may involve multiple LLM calls and tool invocations within that turn), then is garbage collected.

```
Chat request arrives (stream or async) with session_id
  → load session from DB (includes agent_config)
  → build agent from config:
      - LLM: fixed default
      - Tools: iterate agent_config.tools, construct by type
      - System prompt: backend default + deck_prompt content (if referenced)
      - Slide style: injected into prompt from library (if referenced)
  → agent runs to completion (streaming or async)
  → response persisted to session
  → agent discarded
```

This eliminates the singleton agent pattern and the hot-reload locking mechanism. The sync `POST /api/chat` endpoint exists but is unused by the frontend; it receives the same changes for consistency.

### ChatService Remains a Singleton (Minus the Agent)

`ChatService` is currently a process-level singleton (`get_chat_service()`) that holds two things: the agent and an in-memory `_deck_cache`. In the new model:

- **`self.agent`** — removed. The agent is built per-request inside the chat method, not held as instance state.
- **`self._reload_lock`** — removed. No agent to reload.
- **`self._deck_cache`** — retained. This is an in-memory LRU of parsed `SlideDeck` objects keyed by `session_id`, avoiding re-parsing HTML from the DB on every request. It is independent of the agent and still valuable. The `_cache_lock` stays to protect concurrent access.
- **Orchestration logic** — retained. `ChatService` still owns the chat flow (build agent, invoke, parse response, persist deck, stream events). It just no longer holds a long-lived agent reference.

`ChatService` becomes a stateless orchestrator with a deck cache — no agent state, no session state, no reload machinery.

### Session State Hydration

The current `_ensure_agent_session()` maintains in-memory state per session: `chat_history`, `genie_conversation_id`, `experiment_id`, `experiment_url`, `username`, `profile_name`, `message_count`. In the per-request model, this state must be hydrated on every request. Here's how each piece is handled:

| State | Current (singleton) | New (per-request) | Cost |
|-------|--------------------|--------------------|------|
| `chat_history` | Hydrated once from DB, kept in memory | Hydrated from DB every request | See below |
| `genie_conversation_id` | Held in memory, synced to DB | Read from session row (already loaded) | Negligible — part of the session row fetch |
| `experiment_id` / `experiment_url` | Created once, held in memory | Read from session row (already persisted) | Negligible — part of the session row fetch |
| `username` | Resolved once | Resolved from request context | Negligible |
| `profile_name` | Tracked for profile switching | Removed (no profiles to track) | N/A |

**Chat history is the only expensive hydration.** Today `_hydrate_chat_history()` reads all messages from DB and builds `ChatMessageHistory`. In the per-request model this happens every chat request.

**Why this is acceptable:**
1. The chat message read is a single indexed query (`SELECT * FROM messages WHERE session_id = ? ORDER BY created_at`). Lakebase/PostgreSQL handles this efficiently even for long conversations.
2. The LLM call itself dominates request latency by orders of magnitude (seconds vs milliseconds for the DB read).
3. The current model already does this hydration — just once per session rather than per request. For users who reload the page or switch sessions frequently, the cost is already paid today.
4. The conversation length is naturally bounded — LLM context windows limit how many messages are useful. Long conversations are already summarized/truncated before being sent to the LLM.

**If this becomes a bottleneck** (unlikely, but measurable), the obvious optimization is a per-process LRU cache of chat histories keyed by `(session_id, message_count)`. The message count acts as a cache invalidation key — if it matches, the cached history is current. This is a simple, local optimization that doesn't affect the architecture. We do not implement this upfront.

### Pre-Session Flow

When the user is on `/` (no session yet):

1. Frontend shows generator UI with default config in local React state
2. No backend calls until first interaction
3. User sends first message → `POST /api/chat` with no `session_id` but with `agent_config` in payload
4. Backend creates session, persists agent_config, processes message
5. Response includes new `session_id` → frontend updates URL to `/sessions/:id/edit`

If the user changes config before chatting, the config is held in React state and mirrored to `localStorage` (`pendingAgentConfig`). Session is created on first message with that config, and `localStorage` is cleared.

### Config Change Mid-Session

1. User adds/removes a tool or changes style/prompt
2. Frontend calls `PUT /api/sessions/:id/agent-config`
3. Backend persists new config to session
4. Next `POST /api/chat` builds the agent with the updated config

No explicit "reload" step. The agent is built fresh from config on every request.

## Frontend Changes

### New: AgentConfigContext

Replaces `ProfileContext` as the primary config driver.

- **Pre-session** (`/`): config held in React state and mirrored to `localStorage` (`pendingAgentConfig` key). On mount, if no active session, restore from `localStorage`. Cleared when a session is created (config moves to DB). This survives page refresh, tab close, and navigation away and back.
- **Active session** (`/sessions/:id/edit`): synced with backend via `PUT /api/sessions/:id/agent-config`.
- Exposes: `agentConfig`, `updateTool`, `removeTool`, `setStyle`, `setDeckPrompt`, `saveAsProfile`, `loadProfile`

### New: AgentConfigBar Component

Self-contained, loosely coupled UI component that renders the current agent config. Consumes `AgentConfigContext` and can be mounted anywhere (chat panel toolbar is the intended placement, but the designer owns the final location).

Renders:
- Active tools as removable chips
- "Add Tool" action (picker lists Genie spaces + MCP servers from `GET /api/tools/available`)
- Style selector (from slide style library)
- Deck prompt selector (from deck prompt library)
- "Save as Profile" action
- "Load Profile" action

**Error handling:**
- `GET /api/tools/available` fails → show "Unable to load tools" with retry option; existing tools in config unaffected
- `PUT /api/sessions/:id/agent-config` fails → show toast error, revert local state to last known good config
- Pre-session mode → all config changes are local React state, no error states possible until first chat message

### Routing Changes

| Route | Before | After |
|-------|--------|-------|
| `/` | Help page | Pre-session generator |
| `/help` | Help page | Help page (unchanged) |
| `/profiles` | Profile management (create/edit/delete) | Simplified "Saved Configurations" list (rename/delete/load) |

### Removed

- `ProfileContext` — replaced by `AgentConfigContext`
- `ProfileCreationWizard` — removed
- `ProfileSelector` (header component) — removed
- Config sub-pages: AI infra, Genie, Prompts — removed

### Modified

- `AppLayout`: `/` renders generator in pre-session mode
- `SessionContext`: `createNewSession()` no longer needs profile ID; session restoration populates `AgentConfigContext`

### Unchanged

- `ChatPanel`, `SlidePanel` — don't know about config
- `SelectionContext`, `GenerationContext`, `ToastContext` — unchanged
- `SlideStyleList`, `DeckPromptList` — global library pages stay

## Migration Strategy

### Step 1: Add Columns

- Add `agent_config` JSON column to `user_sessions` (nullable, default null)
- Add `agent_config` JSON column to `config_profiles`
- Null means "use defaults" — all existing sessions work immediately

### Step 2: Migrate Profile Data

Migration script reads each profile's relational data and writes equivalent JSON:

```python
for profile in all_profiles:
    agent_config = {
        "tools": [],
        "slide_style_id": profile.prompts.selected_slide_style_id,
        "deck_prompt_id": profile.prompts.selected_deck_prompt_id,
        "system_prompt": profile.prompts.system_prompt if differs_from_default(profile.prompts.system_prompt) else None,
        "slide_editing_instructions": profile.prompts.slide_editing_instructions if differs_from_default(profile.prompts.slide_editing_instructions) else None
    }
    # Add Genie space as a tool if configured
    if profile.genie_spaces:
        gs = profile.genie_spaces[0]
        agent_config["tools"].append({
            "type": "genie",
            "space_id": gs.space_id,
            "space_name": gs.space_name,
            "description": gs.description
        })
    profile.agent_config = agent_config
```

### Step 3: Backfill Existing Sessions

After profiles have their `agent_config` populated (Step 2), backfill active sessions from their `profile_id`:

```python
for session in all_sessions_with_profile_id:
    if session.agent_config is not None:
        continue  # Already has config, skip
    profile = get_profile(session.profile_id)
    if profile and profile.agent_config:
        session.agent_config = profile.agent_config
```

This ensures that when a user resumes an existing session, it retains the Genie space, style, and deck prompt it was originally created with rather than falling back to bare defaults. Sessions with no `profile_id` (shouldn't exist in practice) or whose profile has been deleted remain at `null` (defaults).

### Step 4: Deprecate Old Tables

Old relational tables (`config_ai_infra`, `config_genie_spaces`, `config_prompts`) remain in DB but are no longer read by application code. Clean removal in a future release.

### Step 5: Drop Config History

Drop the `config_history` table and remove all config history write paths from the codebase. The table is unused in the application and not worth maintaining for lightweight config changes.

### Backward Compatibility

- Existing sessions are backfilled with `agent_config` from their profile (Step 3), preserving their original Genie space, style, and deck prompt settings
- Sessions whose profile was deleted or that had no `profile_id` get `agent_config: null` → treated as defaults
- Existing sessions retain chat history and slides intact
- `profile_id` and `profile_name` columns on sessions remain for audit but are no longer functionally used. New sessions will not populate these columns. Both are already `nullable=True` with no FK constraint (`src/database/models/session.py:103-104`), so no schema change needed.
- Existing shared view links (`/sessions/:id/view`) unaffected

## Testing Strategy

### Backend Unit Tests

- Agent config JSON serialization/deserialization
- Agent factory: correct tools from config (genie → GenieTool, mcp → MCP connection)
- Agent factory: null/empty config → defaults
- Session creation with and without agent_config
- Profile save-from-session: correctly snapshots config
- Profile load-into-session: correctly copies config
- Migration script: relational profile → JSON conversion

### Backend Integration Tests

- Full chat flow with agent_config on session
- Config change mid-session → next chat uses new config
- Pre-session chat: no session_id → session created, config persisted, response includes session_id
- `GET /api/tools/available` returns Genie spaces and MCP servers

### Frontend E2E Tests (Playwright)

- Land on `/` → generator in pre-session mode (no backend session created)
- Send first message → session created, URL updates to `/sessions/:id/edit`
- Add/remove tool via AgentConfigBar → reflected in config
- Change style/deck prompt → reflected in config
- Save as Profile → appears in management list
- Load Profile → session config updated
- Reload session → agent config restored
- Existing session URLs still work

### Tests Removed/Updated

- Profile wizard tests → removed
- Profile selector tests → removed
- Tests mocking profile loading → updated to use agent config
- Help page as landing → updated (landing is now generator)
