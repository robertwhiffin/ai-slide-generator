# Deck-Centric Permissions Model

**Status:** Approved design
**Date:** 2026-03-24

## Overview

Redesign the permissions model to make decks (sessions with slide decks) the primary shareable entity, completely decoupled from profiles. Profiles become independently shareable config templates with their own simpler permission model.

**Key principles:**
- Decks are the fact table; everything else is a dimension.
- Sharing a profile never grants access to any deck. Sharing a deck never grants access to any profile.
- Conversations (chat messages) are always private to the session creator.
- Identity matching uses Databricks user/group IDs as the primary key, with email (case-insensitive) as fallback. The `identity_id` column stores the Databricks ID; `identity_name` stores the email/group name for display.
- Any session can be shared via deck contributors, regardless of whether it was created from a profile.

## Current State (What's Changing)

The existing permissions model routes deck access through profiles: sharing a profile implicitly shares all decks created under it. This no longer makes sense after the profile rebuild, where profiles are lightweight agent config snapshots (templates). The old sharing model is fully implemented in the backend but never surfaced in the frontend — it's dead code.

**Removed:**
- `profile_id` and `profile_name` columns on `UserSession`
- All code that derives deck access from profile access
- The "Shared with Me" path that queries accessible profiles to find shared decks
- `list_sessions_by_profile_ids()` in SessionManager

**Added:**
- Direct deck sharing via a new `deck_contributors` table
- Simplified profile sharing (CAN_USE / CAN_EDIT / CAN_MANAGE)

## Data Model

### DeckContributor (new table)

```python
class DeckContributor(Base):
    __tablename__ = "deck_contributors"

    id: int                          # PK
    user_session_id: int             # FK to user_sessions.id (integer PK, not the string session_id)
    identity_type: str               # "USER" or "GROUP"
    identity_id: str                 # Databricks user/group ID
    identity_name: str               # Email for users, name for groups
    permission_level: str            # CAN_VIEW, CAN_EDIT, CAN_MANAGE
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    # Unique constraint: (user_session_id, identity_id)
```

Created automatically by `Base.metadata.create_all()` on app startup.

### Permission Level Enum

A single combined enum with four values, ordered by priority:

```python
class PermissionLevel(str, Enum):
    CAN_USE = "CAN_USE"        # Profile-only: can see and load the profile
    CAN_VIEW = "CAN_VIEW"      # Deck-only: read-only access to presentations
    CAN_EDIT = "CAN_EDIT"      # Modify content (profile config or deck slides)
    CAN_MANAGE = "CAN_MANAGE"  # Full control (delete, manage sharing)
```

**Priority order** (for `PERMISSION_PRIORITY` in `permission_service.py`):

```python
PERMISSION_PRIORITY = {
    PermissionLevel.CAN_USE: 1,    # Profile-only
    PermissionLevel.CAN_VIEW: 1,   # Deck-only (same tier as CAN_USE)
    PermissionLevel.CAN_EDIT: 2,
    PermissionLevel.CAN_MANAGE: 3,
}
```

CAN_USE and CAN_VIEW are at the same priority tier — they are context-specific equivalents (lowest access for their respective domains).

- **Deck contributors** use: CAN_VIEW, CAN_EDIT, CAN_MANAGE
- **Profile contributors** use: CAN_USE, CAN_EDIT, CAN_MANAGE
- Validation ensures the correct subset is used for each context
- The `default` on `ConfigProfileContributor.permission_level` changes from `CAN_VIEW` to `CAN_USE`

### ConfigProfileContributor (repurposed)

Same table structure, updated permission levels:

| Level | Meaning |
|-------|---------|
| **CAN_USE** | See profile in list, load into own sessions, set as personal default |
| **CAN_EDIT** | Modify agent config, rename, update description |
| **CAN_MANAGE** | Full control: edit, delete, manage sharing |

### UserSession (columns removed)

Drop `profile_id` and `profile_name`. Sessions have no relationship to profiles. The `parent_session_id` column stays — it links contributor sessions to the owner's session for shared deck access and private chat isolation.

### ConfigProfile (unchanged)

`global_permission` stays but only controls profile visibility (CAN_USE / CAN_EDIT / CAN_MANAGE on the profile template). It has no bearing on deck access. Existing `CAN_VIEW` values are migrated to `CAN_USE`.

### UserProfilePreference (unchanged)

Per-user default profile selection is unaffected. CAN_USE is the minimum permission required to set a profile as your personal default (same as the old CAN_VIEW).

## Permission Resolution

### Deck Permissions

`PermissionService.get_deck_permission(session_id, user_id, user_name, group_ids)`:

1. Is user the session creator (`user_sessions.created_by`)? → CAN_MANAGE
2. Direct user entry in `deck_contributors` (match by `identity_id`, fallback by `identity_name`)? → Use that level
3. Any group the user belongs to in `deck_contributors`? → Use highest level
4. No match → No access

No global/workspace-wide sharing on decks. Decks are always explicitly shared. This is intentional — decks are shared with specific users/groups, never broadcast to the entire workspace.

### Profile Permissions

`PermissionService.get_profile_permission(profile_id, user_id, user_name, group_ids)`:

1. Is user the profile creator? → CAN_MANAGE
2. Direct user entry in `config_profile_contributors`? → Use that level
3. Any group in `config_profile_contributors`? → Use highest level
4. Profile has `global_permission` set? → Use that level
5. No match → No access

### Deck Permission Table

| Action | Creator | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:-------:|:--------:|:--------:|:----------:|
| View slides | ✅ | ✅ | ✅ | ✅ |
| View slide metadata | ✅ | ✅ | ✅ | ✅ |
| Export (PPTX / Google Slides) | ✅ | ✅ | ✅ | ✅ |
| Add comments / @mentions | ✅ | ✅ | ✅ | ✅ |
| Edit own comments | ✅ | ✅ | ✅ | ✅ |
| Delete own comments | ✅ | ✅ | ✅ | ✅ |
| Edit slides (direct + chat) | ✅ | ❌ | ✅ | ✅ |
| Reorder / duplicate slides | ✅ | ❌ | ✅ | ✅ |
| Delete slides | ✅ | ❌ | ❌ | ✅ |
| Delete any comment | ❌ | ❌ | ❌ | ✅ |
| Resolve / unresolve comments | ✅ | ❌ | ✅ | ✅ |
| Manage deck contributors | ✅ | ❌ | ❌ | ✅ |
| Delete deck | ✅ | ❌ | ❌ | ✅ |

> **Note:** "Delete any comment" is CAN_MANAGE only — the session creator does NOT automatically get this unless they have CAN_MANAGE (which they do, since creators resolve to CAN_MANAGE). This is consistent with the existing model.

### Profile Permission Table

| Action | Creator | CAN_USE | CAN_EDIT | CAN_MANAGE |
|--------|:-------:|:-------:|:--------:|:----------:|
| See profile in list | ✅ | ✅ | ✅ | ✅ |
| View profile configuration | ✅ | ✅ | ✅ | ✅ |
| Load into session | ✅ | ✅ | ✅ | ✅ |
| Set as personal default | ✅ | ✅ | ✅ | ✅ |
| Edit agent config | ✅ | ❌ | ✅ | ✅ |
| Rename / update description | ✅ | ❌ | ✅ | ✅ |
| Delete profile | ✅ | ❌ | ❌ | ✅ |
| Manage profile sharing | ✅ | ❌ | ❌ | ✅ |

### Conversation Privacy (unchanged)

Conversations are always private to the session creator. Contributors use their own contributor session (private chat, shared slides via `parent_session_id`).

## Contributor Sessions

When a contributor opens a shared deck, the system creates a contributor session linked to the owner's session via `parent_session_id`. This gives the contributor:

- Their own private chat history
- Shared read/write access to the owner's slide deck

```
Owner's Session (root)
  ├── SessionSlideDeck (shared)
  ├── SessionMessage (owner's private chat)
  └── SlideDeckVersion (shared version history)

Contributor Session (parent_session_id → owner)
  └── SessionMessage (contributor's private chat)
      (reads/writes slides from parent's deck)
```

**Permission check change:** Previously, the `POST /api/sessions/{session_id}/contribute` endpoint required `profile_id` on the parent session and resolved permissions via `ConfigProfileContributor`. The new flow:

1. Look up the parent session by `session_id` (string) → get `id` (integer PK)
2. Call `get_deck_permission(parent_session.id, user_id, user_name, group_ids)`
3. Require CAN_VIEW or higher — if no access, return 403
4. Create/return contributor session with `parent_session_id = parent_session.id`

The old `profile_id` check (`if not profile_id: raise 403`) is removed entirely. Any session can be shared via deck contributors.

### Exclusive Editing Lock (unchanged)

First-come, heartbeat-based, auto-expires after 45 seconds without heartbeat. Client releases after 5 minutes idle. All slide mutations enforce `require_editing_lock()`.

## PermissionService Changes

The current `PermissionService` is entirely profile-centric. It needs to be split into deck and profile paths.

### Renamed Methods

| Old | New | Notes |
|-----|-----|-------|
| `get_user_permission(profile_id, ...)` | `get_profile_permission(profile_id, ...)` | Clarity |
| `can_view(profile_id, ...)` | `can_use_profile(profile_id, ...)` | Profile context |
| `can_edit(profile_id, ...)` | `can_edit_profile(profile_id, ...)` | Profile context |
| `can_manage(profile_id, ...)` | `can_manage_profile(profile_id, ...)` | Profile context |
| `require_view(profile_id, ...)` | `require_use_profile(profile_id, ...)` | Profile context |
| `require_edit(profile_id, ...)` | `require_edit_profile(profile_id, ...)` | Profile context |
| `require_manage(profile_id, ...)` | `require_manage_profile(profile_id, ...)` | Profile context |

### New Methods (deck-specific)

| Method | Purpose |
|--------|---------|
| `get_deck_permission(session_id, ...)` | Resolve user's permission on a deck |
| `can_view_deck(session_id, ...)` | Check CAN_VIEW+ on deck |
| `can_edit_deck(session_id, ...)` | Check CAN_EDIT+ on deck |
| `can_manage_deck(session_id, ...)` | Check CAN_MANAGE on deck |
| `require_view_deck(session_id, ...)` | Raise 403 if not CAN_VIEW+ |
| `require_edit_deck(session_id, ...)` | Raise 403 if not CAN_EDIT+ |
| `require_manage_deck(session_id, ...)` | Raise 403 if not CAN_MANAGE |
| `get_shared_session_ids(user_id, user_name, group_ids)` | Return session IDs shared with user via `deck_contributors` |

### Unchanged Methods

| Method | Notes |
|--------|-------|
| `get_accessible_profile_ids(...)` | Still needed for profile list filtering |
| `get_profiles_with_permissions(...)` | Still needed for profile list display |

### Removed Methods

| Method | Reason |
|--------|--------|
| `list_sessions_by_profile_ids(...)` | SessionManager method; replaced by `get_shared_session_ids` |

### `_get_session_permission` Helper (sessions.py)

This helper currently delegates to `PermissionService` via `profile_id`. Complete rewrite:

```python
def _get_session_permission(session, user_id, user_name, group_ids):
    # For root sessions: check deck_contributors
    if session.parent_session_id is None:
        return permission_service.get_deck_permission(
            session.id, user_id, user_name, group_ids
        )
    # For contributor sessions: check deck_contributors on parent
    return permission_service.get_deck_permission(
        session.parent_session_id, user_id, user_name, group_ids
    )
```

## Mention Resolution Changes

The `get_mentionable_users` method in `session_manager.py` currently resolves mentionable users via `deck_owner.profile_id` → `ConfigProfileContributor` + `ConfigProfile.global_permission`.

In the new model, mentionable users for a deck come from `deck_contributors` on the root session:

1. Query `deck_contributors` for the root session (`user_session_id = root_session.id`)
2. Return all contributor `identity_name` values (emails) plus the session creator
3. For globally-shared profiles, the SCIM search remains available for @mention autocomplete (unchanged)

The profile contributor table is no longer consulted for mention resolution.

## API Endpoints

### Deck Contributors (new)

```
GET    /api/sessions/{session_id}/contributors
POST   /api/sessions/{session_id}/contributors
PUT    /api/sessions/{session_id}/contributors/{contributor_id}
DELETE /api/sessions/{session_id}/contributors/{contributor_id}
```

All require CAN_MANAGE on the deck.

### Deck Contributor Sessions (updated)

```
POST   /api/sessions/{session_id}/contribute    # Create/get contributor session (requires CAN_VIEW+ on deck)
GET    /api/sessions/shared                      # Queries deck_contributors
```

`POST /api/sessions/{session_id}/contribute` requires CAN_VIEW or higher on the deck, resolved via `get_deck_permission(parent_session.id, ...)`. The old `profile_id` guard is removed — any session can be shared.

`GET /api/sessions/shared` implementation changes:

- **Old:** `get_accessible_profile_ids()` → `list_sessions_by_profile_ids(profile_ids)` → filter sessions
- **New:** `get_shared_session_ids(user_id, user_name, group_ids)` → join `deck_contributors` to `user_sessions` to `session_slide_decks` → return sessions with decks

The response shape is unchanged: presentation-only data (slides, metadata), no chat messages.

### Session Creation (updated)

`POST /api/sessions` — the `CreateSessionRequest` schema no longer includes `profile_id` or `profile_name`. The client stops sending them. The backend ignores them if present (backwards compatibility during rollout, then remove).

### Profile Contributors (existing routes, updated permission levels)

```
GET    /api/settings/profiles/{id}/contributors
POST   /api/settings/profiles/{id}/contributors
PUT    /api/settings/profiles/{id}/contributors/{contrib_id}
DELETE /api/settings/profiles/{id}/contributors/{contrib_id}
```

Permission levels in request/response: CAN_USE, CAN_EDIT, CAN_MANAGE.

Managing contributors (add/update/delete) requires CAN_MANAGE on the profile. This is a change from the current code which gates on CAN_EDIT — the permission table is authoritative.

### Profile Endpoints (updated with permission checks)

```
GET    /api/profiles                                    # List profiles visible to current user
POST   /api/profiles/save-from-session/{session_id}     # Create profile (creator gets CAN_MANAGE)
PUT    /api/profiles/{profile_id}                        # Requires CAN_EDIT
DELETE /api/profiles/{profile_id}                        # Requires CAN_MANAGE
POST   /api/sessions/{session_id}/load-profile/{id}     # Requires CAN_USE
```

### Editing Lock (unchanged)

```
POST   /api/sessions/{id}/lock
DELETE /api/sessions/{id}/lock
GET    /api/sessions/{id}/lock
PUT    /api/sessions/{id}/lock/heartbeat
```

### Comments & Mentions (unchanged)

Same endpoints, same behavior. Scoped to deck, not profile.

## Identity Provider (unchanged)

Users and groups resolved via Workspace SCIM API using the app's service principal. Falls back to local `app_identities` table in dev. Any workspace user can be shared with regardless of whether they've logged into the app.

## Frontend Changes

### Deck View

- **Share button** → opens `DeckContributorsManager` (permissions manager for the deck)
- **New "Copy Link" button** → copies shareable URL (current share button behavior)

### My Sessions / Shared with Me

- **"My Sessions"** → unchanged (sessions where `created_by` is current user)
- **"Shared with Me"** → queries `GET /api/sessions/shared` which resolves via `deck_contributors`
- Each shared deck card shows the user's permission level

### Profile List Page

- **Surface sharing UI** on profile cards (the `ContributorsManager` component, currently unrendered)
- Permission levels display as CAN_USE / CAN_EDIT / CAN_MANAGE
- Delete button gated on CAN_MANAGE
- Edit config gated on CAN_EDIT+

### AgentConfigBar

- "Save as Profile" / "Load Profile" unchanged
- Remove `profile_id` / `profile_name` from session creation and loading flows

### Removed

- All frontend code that resolves deck access through profile permissions
- `profile_id` and `profile_name` references in session API calls and state

## Database Migration

### New table

`deck_contributors` — created automatically by `Base.metadata.create_all()`.

### Column changes on existing tables

Handled by a new `_migrate_deck_permissions_model()` function in `_run_migrations()`, following the existing idempotent pattern (check column existence before altering):

**Drop from `user_sessions`:**
- `profile_id`
- `profile_name`

**Update `config_profile_contributors`:**
- Update any existing `CAN_VIEW` permission levels to `CAN_USE`

**Update `config_profiles`:**
- Update any existing `global_permission = 'CAN_VIEW'` to `'CAN_USE'`

All migration steps are idempotent and run on every app startup via `init_db()` → `_run_migrations()`.

### Code cleanup for dropped columns

All backend code that reads `profile_id` or `profile_name` from `UserSession` must be removed or updated. Key locations:

- `sessions.py`: `_get_session_permission()`, contribute endpoint, session creation
- `session_manager.py`: `list_sessions_by_profile_ids()`, `get_mentionable_users()`
- `profiles.py`: `save-from-session` (no longer writes profile_id to session), `load-profile` (no longer reads profile_id)
- Frontend: session API calls, session state/context, any TypeScript interfaces

## Testing

### Backend

- **DeckContributor CRUD**: Unit tests for create, read, update, delete deck contributors
- **Deck permission resolution**: Test all 4 steps (creator, direct user, group, no match)
- **Profile permission resolution**: Test all 5 steps with CAN_USE replacing CAN_VIEW
- **Contributor session creation**: Test that sessions without profile_id can be shared
- **Permission enforcement**: Test that deck mutations check deck permissions (not profile)
- **Mention resolution**: Test that mentionable users come from deck_contributors
- **Migration**: Test column drops and permission level updates are idempotent

### Frontend

- **DeckContributorsManager**: Test add/remove/update contributors on a deck
- **Share button**: Test that it opens permissions manager (not URL copy)
- **Copy Link button**: Test URL copy functionality
- **Shared with Me**: Test that shared decks display with correct permission levels
- **Profile sharing UI**: Test ContributorsManager renders on profile cards

## Documentation Updates

The following documents need updating or replacement after implementation:

- `docs/technical/permissions-model.md` — replace entirely with content reflecting the new deck-centric model
- `docs/user-guide/08-profile-sharing-permissions.md` — update to reflect decoupled deck/profile sharing

## Group Resolution (unchanged)

1. Fetch user's group memberships from Identity Provider
2. Cache results for 5 minutes
3. Check each group against contributors table (deck or profile)
4. Return highest permission found

## Polling & Real-Time Updates (unchanged)

| Resource | Interval | Notes |
|----------|----------|-------|
| Mentions (per-slide bell) | 3 seconds | Scoped to current deck via session_id |
| Lock status (locked-out users) | 10 seconds | Stops when lock is acquired |
| Profile list | 15 seconds | Silent background poll |
| Shared decks list | 15 seconds | Silent background poll |

## Security Notes

1. **Creator protection:** Session creators get CAN_MANAGE automatically via the resolution algorithm (step 1 checks `created_by`). Creators are not stored in `deck_contributors` — protection is at the resolution layer, not a table constraint. The DELETE endpoint should reject attempts to remove the creator.
2. **Profile creator protection:** Profile creators get CAN_MANAGE automatically
3. **No cross-pollination:** Deck and profile permissions are completely independent
4. **No global deck sharing:** Decks have no `global_permission` equivalent — always explicitly shared with specific users/groups
5. **App identity:** User and group lookups use the app's service principal — no admin PATs
6. **Group cache:** 5-minute TTL balances API efficiency with permission propagation
7. **Exclusive lock:** One editor at a time; 45-second server expiry; 5-minute idle release
8. **Server-side enforcement:** All slide mutations check `require_editing_lock()`
9. **Identity matching:** Primary match by Databricks user/group ID (`identity_id`), fallback match by email (`identity_name`), case-insensitive
