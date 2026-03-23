# Agent Config E2E Tests — Design Spec

**Date:** 2026-03-21
**Branch:** feature/profile-rebuild
**Status:** Approved design, pending implementation

## Purpose

End-to-end integration tests for the agent config workflow introduced by the profile rebuild. These tests validate the full user journey — from configuring tools/prompts/styles before and during sessions, to saving and loading profiles, to managing profiles on the dedicated page — against a real backend and Postgres database.

## Approach

Two new Playwright integration test files, following the existing pattern (`deck-prompts-integration.spec.ts`, `history-integration.spec.ts`). All database operations are real. Only the LLM chat stream and Databricks tool discovery are mocked at the Playwright route level.

## Mocking Strategy

### Mocked (Playwright route interception)

| Endpoint | Pattern | Reason |
|---|---|---|
| `/api/chat/stream` | `**/api/chat/stream` | SSE response — avoids real LLM calls. Returns a simple slide deck. The `createStreamingResponseWithDeck()` helper is extracted into `integration-helpers.ts` (currently duplicated across 4+ test files). |
| `/api/tools/available` | `**/api/tools/available` | Calls `client.genie.list_spaces()` which requires a real Databricks connection. Returns a fixed list of Genie spaces and MCP servers. |
| `/api/setup/status` | `**/api/setup/status` | Returns `{ configured: true }` to bypass the welcome/setup screen. Required by all E2E tests. |

Since `/api/chat/stream` is intercepted before hitting the backend, no Genie spaces are invoked during generation either.

### Real (backend + Postgres)

Everything else:
- Session CRUD (`/api/sessions/*`)
- Agent config reads/writes (`/api/sessions/{id}/agent-config`, PUT/PATCH)
- Profile operations (`/api/profiles/*`)
- Slide styles (`/api/settings/slide-styles`)
- Deck prompts (`/api/settings/deck-prompts`)

## Test Data Lifecycle

- **`beforeAll`** — create shared library data via API (a slide style + a deck prompt)
- **`beforeEach`** — create per-test sessions/profiles as needed; clear `localStorage` (specifically the `pendingAgentConfig` key) to prevent state leaking between pre-session tests
- **`afterEach`** — clean up sessions and profiles created during the test
- **`afterAll`** — clean up the shared library data

### Profile deduplication constraint

The backend's `save-from-session` endpoint rejects duplicate agent configs with a 409. Each test profile must have a unique config — e.g., by using a distinct `deck_prompt_id`, `slide_style_id`, or unique tool entry. The `createTestProfile` helper should accept parameters that ensure uniqueness.

## Shared Helpers

New file: `frontend/tests/helpers/integration-helpers.ts`

Functions:

**API helpers (use Playwright `request` fixture):**
- `createTestSession(request)` → POST `/api/sessions`, returns session_id
- `createTestProfile(request, { name, description?, tools?, styleId?, promptId? })` → multi-step: (1) create a throwaway session, (2) PUT the desired agent_config onto it, (3) POST `/api/profiles/save-from-session/{sessionId}` with name/description, (4) return the profile. The caller passes config ingredients; the helper assembles a unique `AgentConfig`.
- `createTestStyle(request, data)` → POST `/api/settings/slide-styles`, returns style
- `createTestDeckPrompt(request, data)` → POST `/api/settings/deck-prompts`, returns prompt
- `cleanupSession(request, id)` → DELETE session
- `cleanupProfile(request, id)` → DELETE profile (soft-delete)
- `getSessionConfig(request, sessionId)` → GET `/api/sessions/{id}/agent-config`

**Page-level mocks:**
- `mockChatStream(page)` → route-intercept `**/api/chat/stream` with SSE response (contains `createStreamingResponseWithDeck()` extracted from existing duplicated implementations)
- `mockAvailableTools(page)` → route-intercept `**/api/tools/available`
- `mockSetupStatus(page)` → route-intercept `**/api/setup/status` with `{ configured: true }`

## File 1: `agent-config-integration.spec.ts`

13 tests across 3 describe blocks.

### `describe('Pre-session configuration')`

| # | Test | What it verifies |
|---|---|---|
| 1 | Configure Genie tool before first message | Land on `/`, open tool picker, add Genie space, send message. Verify created session's `agent_config.tools` includes the Genie tool via API. |
| 2 | Configure deck prompt before first message | Land on `/`, select deck prompt from dropdown, send message. Verify session's `agent_config.deck_prompt_id` matches. |
| 3 | Configure slide style before first message | Land on `/`, select slide style from dropdown, send message. Verify session's `agent_config.slide_style_id` matches. |
| 4 | Configure Genie + deck prompt together | Add both before sending. Verify both present in session config. |
| 5 | Send message with no configuration | Land on `/`, send message immediately. Verify session created with default agent_config values. |
| 6 | New session gets default slide style *(test.fail)* | Land on `/`, send message. Verify `agent_config.slide_style_id` references a default style. **Fails** — no concept of default styles yet. |

### `describe('Mid-session configuration')`

| # | Test | What it verifies |
|---|---|---|
| 7 | Add Genie tool mid-session | Create session (send first message), open tool picker, add Genie. Verify config updated via API. |
| 8 | Remove tool mid-session | Start with a tool configured, remove via chip X button. Verify config updated via API. |
| 9 | Change deck prompt mid-session | Switch deck prompt dropdown in active session. Verify new `deck_prompt_id` persisted. |
| 10 | Change slide style mid-session | Switch style dropdown. Verify new `slide_style_id` persisted. |

### `describe('Load profile into session')`

| # | Test | What it verifies |
|---|---|---|
| 11 | Load profile into new session | Create session, load a saved profile. Verify session config matches profile's config via API. |
| 12 | Load profile mid-session shows confirmation *(test.fail)* | Create session, configure tools, load a different profile. Assert a confirmation step appears before overwriting. **Fails** — not implemented yet. |
| 13 | Load profile replaces config entirely | Create session with Genie tool A, load profile with Genie tool B. Verify session config has only tool B, not both. |

## File 2: `profiles-integration.spec.ts`

6 tests across 2 describe blocks.

### `describe('Profile list and display')`

| # | Test | What it verifies |
|---|---|---|
| 1 | List profiles from database | Create 2-3 profiles via API, navigate to `/profiles`. Verify all appear with correct names. |
| 2 | Expanded profile shows agent config details | Create profile with Genie tools, style, and deck prompt. Click to expand. Verify config details are rendered (whatever current UI shows). |
| 3 | Empty state | No profiles in DB. Navigate to `/profiles`. Verify appropriate empty state message. |

### `describe('Profile operations')`

| # | Test | What it verifies |
|---|---|---|
| 4 | Delete a profile | Create profile, navigate to `/profiles`, delete it. Verify removed from list. Verify soft-deleted via API. |
| 5 | Rename a profile | Create profile, rename via UI. Verify new name persists via API. |
| 6 | Save current session as profile | Create session with tools configured, click "Save as Profile", enter name/description. Navigate to `/profiles`, verify new profile appears with correct config. |

## CI Integration

Update the E2E matrix in `.github/workflows/test.yml`:

1. **Replace** the existing `profile-integration` entry with `profiles-integration` (plural — new file replaces old)
2. **Add** `agent-config-integration`

```yaml
matrix:
  test:
    # ... existing entries ...
    - agent-config-integration
    - profiles-integration    # replaces old profile-integration
```

Each runs with its own isolated Postgres service, seeded database, and real backend — identical to existing integration test entries.

## Failing Tests (TDD)

Two tests are intentionally written to fail using Playwright's `test.fail()`:

1. **New session gets default slide style** — asserts `slide_style_id` is set on session creation. Fails because there's no concept of default styles yet.
2. **Load profile mid-session shows confirmation** — asserts a confirmation step before config overwrite. Fails because not implemented yet.

These keep CI green while documenting the desired behavior. When the features are implemented, remove the `test.fail()` marker and the tests should pass.
