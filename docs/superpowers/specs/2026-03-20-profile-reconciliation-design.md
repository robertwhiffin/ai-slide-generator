# Profile Reconciliation Design

**Date:** 2026-03-20
**Branch:** feature/profile-rebuild
**Status:** Draft

## Problem

Two independent profile systems exist on this branch:

1. **AgentConfigBar** (generator page) — uses `AgentConfigContext` and `services/api.ts`, calls `/api/profiles` endpoints. Works correctly.
2. **Sidebar "Agent Profiles" page** — uses `ProfileContext` and `api/config.ts`, calls `/api/settings/profiles` endpoints. Every call returns **404** because those routes were removed in commit `d1ea3bb`.

Both systems target the same database table (`config_profiles`) but through different API clients hitting different URLs.

## Design

### One table, two views

The `config_profiles` table is the single source of truth. Both the generator page and the sidebar page read/write from it via the `/api/profiles` backend routes.

| Operation | Generator (AgentConfigBar) | Sidebar (Agent Profiles) |
|---|---|---|
| List | yes (Load Profile dialog) | yes |
| Save (from session) | yes | no |
| Load into session | yes | no |
| Rename | no | yes |
| Delete | no | yes |

### Deduplication on save

When a user clicks "Save as Profile", the backend checks whether any existing (non-deleted) profile already has an identical `agent_config` JSON blob. If a match is found, the save is rejected with a 409 Conflict (e.g., "A profile with this configuration already exists: '{name}'").

**Normalization:** The `agent_config` dict is normalized via `AgentConfig.model_dump()` before comparison so field ordering doesn't matter.

**`conversation_id` handling:** The `GenieTool.conversation_id` field is session-specific and must be stripped before both persisting and comparing. During `save-from-session`, all `conversation_id` values are set to `None` in the config before saving. This ensures that two configs with the same tools but different conversation IDs are correctly detected as duplicates, and that session-specific state doesn't leak into saved profiles.

### What gets removed

Features that no longer apply:

- **Set as default** — removed from sidebar UI. The `is_default` column and backend `update_profile` logic are preserved (see note below).
- **Duplicate profile** — removed; users save new profiles from sessions
- **Create profile (standalone)** — removed; profiles are only created via "Save as Profile" from a session
- **Load (hot-reload) from sidebar** — removed; loading happens only from the generator's AgentConfigBar

**Note on `is_default`:** `AgentConfigContext` reads `is_default` during pre-session mount to seed the initial config (lines 88-108). This behavior is preserved. Existing `is_default` values in the DB remain valid. The only change is removing the "Set as Default" button from the sidebar UI. The backend's `update_profile` route still supports setting `is_default` via PUT for future use.

### Backend changes

**No new routes needed.** The existing `profiles.py` already has:

| Route | Method | Purpose |
|---|---|---|
| `/api/profiles` | GET | List all profiles |
| `/api/profiles/save-from-session/{session_id}` | POST | Save session config as profile |
| `/api/sessions/{session_id}/load-profile/{profile_id}` | POST | Load profile into session |
| `/api/profiles/{profile_id}` | PUT | Update name/description |
| `/api/profiles/{profile_id}` | DELETE | Soft-delete |

**Changes to `save-from-session`:**
1. Strip `conversation_id` from all Genie tools before persisting
2. Query for existing non-deleted profiles where `agent_config` matches the normalized config
3. Return 409 Conflict if a duplicate is found

**Change to `_profile_to_dict`:** Add `updated_at` to the serialized response for consistency with the model.

### Frontend changes

#### 1. `api/config.ts` — trim profile methods only

The `configApi` object serves both profile and non-profile endpoints (slide styles, deck prompts, etc.). **Non-profile methods are kept as-is** — `AgentConfigBar` imports `configApi` for slide styles and deck prompts, and these must continue to work.

Profile method changes:
- `listProfiles` — repoint from `/api/settings/profiles` to `/api/profiles`
- `updateProfile` — repoint from `/api/settings/profiles/{id}` to `/api/profiles/{id}` (for rename)
- `deleteProfile` — repoint from `/api/settings/profiles/{id}` to `/api/profiles/{id}`
- **Remove** methods with no backend route: `createProfile`, `createProfileWithConfig`, `getProfile`, `getDefaultProfile`, `duplicateProfile`, `setDefaultProfile`, `loadProfile` (old-style via `/profiles/{id}/load`), `reloadConfiguration`

#### 2. Type alignment

The `Profile` type in `api/config.ts` includes `updated_at` and `updated_by` fields that the backend's `_profile_to_dict` currently omits. After adding `updated_at` to the backend response (see Backend changes), update the `Profile` type to match the actual response shape. Remove `updated_by` if not returned.

The `ProfileSummary` type in `types/agentConfig.ts` (used by `services/api.ts`) is already correct.

#### 3. `ProfileContext` — trim to list + rename + delete

Remove:
- `createProfile`, `duplicateProfile`, `setDefaultProfile`, `loadProfile`
- `currentProfile` state and `loadedProfileId` tracking (including localStorage persistence)

Keep:
- `profiles`, `loading`, `error`, `reload`
- `updateProfile` (for rename)
- `deleteProfile`

#### 4. `hooks/useProfiles.ts`

This file re-exports from `ProfileContext`. It's a pass-through — no changes needed beyond what `ProfileContext` exports (TypeScript will pick up the trimmed interface automatically).

#### 5. `ProfileList` component — simplify UI

Remove:
- Load button and `handleLoadProfile`
- Set Default button
- Duplicate button
- "Currently Loaded" badge
- Per-card "Loaded" badge (checks `currentProfile?.id === profile.id`)

Keep:
- Profile list display
- Rename action (inline edit)
- Delete action (with confirmation dialog)

#### 6. `AgentConfigBar` — no changes

Already works correctly. It imports `configApi` from `api/config.ts` for slide styles/deck prompts (not profiles) and `api` from `services/api.ts` for profile operations. Both continue to work.

### Test updates

E2E tests mock both `/api/profiles` and `/api/settings/profiles`. After this change:
- Remove all `/api/settings/profiles` mocks from test setup helpers
- Update `ProfileContext`-based test assertions to match the trimmed interface
- `profile-ui.spec.ts` — remove tests for load, set-default, duplicate actions
- `profile-integration.spec.ts` — update or remove tests referencing old profile creation flow

Files to update: `setup-mocks.ts`, `shared.ts`, `chat-ui.spec.ts`, `profile-ui.spec.ts`, `profile-integration.spec.ts`, `export-ui.spec.ts`, `history-ui.spec.ts`, `deck-integrity.spec.ts`, `slide-styles-ui.spec.ts`, `slide-operations-ui.spec.ts`, `deck-prompts-ui.spec.ts`, `help-ui.spec.ts`, `save-points-versioning.spec.ts`, `slide-generator.spec.ts`.

## Out of scope

- Renaming from the generator page (future enhancement)
- Profile versioning or diffing
- Removing `is_default` column from DB (preserved for pre-session default loading)
- Removing old relationship fields on `ConfigProfile` model (`ai_infra`, `genie_spaces`, `prompts`) — these reference legacy tables and can be cleaned up separately
- Migrating all `api/config.ts` methods to `services/api.ts` (future consolidation)
