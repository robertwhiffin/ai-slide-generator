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

## Current State (What's Changing)

The existing permissions model routes deck access through profiles: sharing a profile implicitly shares all decks created under it. This no longer makes sense after the profile rebuild, where profiles are lightweight agent config snapshots (templates). The old sharing model is fully implemented in the backend but never surfaced in the frontend — it's dead code.

**Removed:**
- `profile_id` and `profile_name` columns on `UserSession`
- All code that derives deck access from profile access
- The "Shared with Me" path that queries accessible profiles to find shared decks

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

### Permission Level Enums

A single combined enum with four values is used across both contributor tables:

```python
class PermissionLevel(str, Enum):
    CAN_USE = "CAN_USE"        # Profile-only: can see and load the profile
    CAN_VIEW = "CAN_VIEW"      # Deck-only: read-only access to presentations
    CAN_EDIT = "CAN_EDIT"      # Modify content (profile config or deck slides)
    CAN_MANAGE = "CAN_MANAGE"  # Full control (delete, manage sharing)
```

- **Deck contributors** use: CAN_VIEW, CAN_EDIT, CAN_MANAGE
- **Profile contributors** use: CAN_USE, CAN_EDIT, CAN_MANAGE
- Validation ensures the correct subset is used for each context

### ConfigProfileContributor (repurposed)

Same table structure, updated permission levels:

| Level | Meaning |
|-------|---------|
| **CAN_USE** | See profile in list, load into own sessions |
| **CAN_EDIT** | Modify agent config, rename, update description |
| **CAN_MANAGE** | Full control: edit, delete, manage sharing |

### UserSession (columns removed)

Drop `profile_id` and `profile_name`. Sessions have no relationship to profiles. The `parent_session_id` column stays — it links contributor sessions to the owner's session for shared deck access and private chat isolation.

### ConfigProfile (unchanged)

`global_permission` stays but only controls profile visibility (CAN_USE / CAN_EDIT / CAN_MANAGE on the profile template). It has no bearing on deck access.

## Permission Resolution

### Deck Permissions

`PermissionService.get_deck_permission(session_id, user_id, user_name, group_ids)`:

1. Is user the session creator? → CAN_MANAGE
2. Direct user entry in `deck_contributors`? → Use that level
3. Any group the user belongs to in `deck_contributors`? → Use highest level
4. No match → No access

No global/workspace-wide sharing on decks. Decks are always explicitly shared.

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
| Delete any comment | ✅ | ❌ | ❌ | ✅ |
| Resolve / unresolve comments | ✅ | ❌ | ✅ | ✅ |
| Manage deck contributors | ✅ | ❌ | ❌ | ✅ |
| Delete deck | ✅ | ❌ | ❌ | ✅ |

### Profile Permission Table

| Action | Creator | CAN_USE | CAN_EDIT | CAN_MANAGE |
|--------|:-------:|:-------:|:--------:|:----------:|
| See profile in list | ✅ | ✅ | ✅ | ✅ |
| View profile configuration | ✅ | ✅ | ✅ | ✅ |
| Load into session | ✅ | ✅ | ✅ | ✅ |
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

**Permission check change:** Previously, contributor session permissions were resolved via the parent session's `profile_id` → `ConfigProfileContributor`. Now they resolve via `DeckContributor` on the parent session directly.

### Exclusive Editing Lock (unchanged)

First-come, heartbeat-based, auto-expires after 45 seconds without heartbeat. Client releases after 5 minutes idle. All slide mutations enforce `require_editing_lock()`.

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

`POST /api/sessions/{session_id}/contribute` requires CAN_VIEW or higher on the deck. This is the minimum permission needed to open a shared presentation and get a contributor session.

`GET /api/sessions/shared` now queries `deck_contributors` for the current user (by user ID and group IDs) instead of resolving through profile IDs. The response shape is unchanged: presentation-only data (slides, metadata), no chat messages.

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
4. **App identity:** User and group lookups use the app's service principal — no admin PATs
5. **Group cache:** 5-minute TTL balances API efficiency with permission propagation
6. **Exclusive lock:** One editor at a time; 45-second server expiry; 5-minute idle release
7. **Server-side enforcement:** All slide mutations check `require_editing_lock()`
8. **Identity matching:** Primary match by Databricks user/group ID (`identity_id`), fallback match by email (`identity_name`), case-insensitive
