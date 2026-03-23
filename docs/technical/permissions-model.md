# Permissions Model Architecture

**Status:** Complete  
**Last Updated:** March 2026

## Overview

The AI Slide Generator implements a permissions model for sharing configuration profiles and their associated presentations with Databricks users and groups.

**Key principles:**
- Conversations are always private. Profile sharing controls access to **presentations (slide decks)**, never to chat history.
- All identity matching uses **email addresses** (case-insensitive, exact match). No regex or display-name heuristics.
- Mentions and notifications are scoped to a **specific deck and slide** — never bleed across decks.

## Permission Levels

Three permission levels control what users can do:

### CAN_VIEW
Read-only access. Users can see presentations, add comments, and use @mentions, but cannot modify slides.

### CAN_EDIT  
Modification access. Users can change slide content, use chat to regenerate slides, and manage contributors.

### CAN_MANAGE
Full administrative control over the profile. Users can do everything including delete presentations and manage assets.

---

## Permission Tables

### Profile Permissions

| Action | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:--------:|:--------:|:----------:|
| See profile in list | ✅ | ✅ | ✅ |
| View profile configuration | ✅ | ✅ | ✅ |
| Set as personal default | ✅ | ✅ | ✅ |
| **Edit profile configuration** | ❌ | ✅ | ✅ |
| **Manage contributors** | ❌ | ✅ | ✅ |
| **Delete profile** | ❌ | ❌ | ✅ |

### Presentation Permissions (Shared Slide Decks)

Contributors see presentations only — never conversations.

| Action | Session Creator | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:--------------:|:--------:|:--------:|:----------:|
| View slide deck | ✅ | ✅ | ✅ | ✅ |
| View slide metadata (created_by, modified_by) | ✅ | ✅ | ✅ | ✅ |
| Export (PPTX/Google Slides) | ✅ | ✅ | ✅ | ✅ |
| **Edit slides directly** | ✅ | ❌ | ✅ | ✅ |
| **Edit slides via chat** | ✅ | ❌ | ✅ | ✅ |
| **Reorder / duplicate slides** | ✅ | ❌ | ✅ | ✅ |
| **Delete slides** | ✅ | ❌ | ❌ | ✅ |

### Slide Comments

Comments are shared across all contributors — stored on the deck-owner session.

| Action | Session Creator | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:--------------:|:--------:|:--------:|:----------:|
| View comments | ✅ | ✅ | ✅ | ✅ |
| Add comment / reply | ✅ | ✅ | ✅ | ✅ |
| @mention other users | ✅ | ✅ | ✅ | ✅ |
| Edit own comment | ✅ | ✅ | ✅ | ✅ |
| Delete own comment | ✅ | ✅ | ✅ | ✅ |
| Delete any comment | ❌ | ❌ | ❌ | ✅ |
| Resolve / unresolve comments | ✅ | ❌ | ✅ | ✅ |

> **Note:** CAN_VIEW users and locked-out users can still add comments and @mentions. The editing lock only restricts slide mutations.

### Conversation Privacy

Conversations (chat messages) are **always private** to the session creator.

| Action | Session Creator | Any Contributor |
|--------|:--------------:|:---------------:|
| View chat messages | ✅ | ❌ |
| Send chat messages | ✅ | ❌ (uses own contributor session) |
| View other users' conversations | ❌ | ❌ |

> **Note:** When a CAN_EDIT contributor uses chat to modify slides, they do so through their own **contributor session** — a private session that shares the parent's slide deck but has its own chat history. The original session creator never sees the contributor's chat, and the contributor never sees the creator's chat.

---

## Global Profile Sharing

Profiles can be shared with **all workspace users** at a specific permission level via the `global_permission` column on `ConfigProfile`.

| `global_permission` value | Effect |
|---------------------------|--------|
| `NULL` | Private — only explicit contributors can access |
| `CAN_VIEW` | All workspace users can view presentations |
| `CAN_EDIT` | All workspace users can view and edit presentations |
| `CAN_MANAGE` | All workspace users have full control |

### How it works

1. During profile creation or editing, select "All workspace users" from the sharing dropdown and choose a permission level.
2. The `global_permission` value is stored directly on the `ConfigProfile` row.
3. `PermissionService.get_user_permission()` checks `global_permission` as a fallback when no direct user or group contributor entry is found.
4. Individual contributor entries override the global permission if they grant a higher level.

### Session visibility

All decks created under a globally-shared profile appear in the **Shared with Me** tab of "View All Decks" for every workspace user, filtered by the global permission level.

---

## @Mentions & Notifications

### Adding a mention

Type `@` followed by the user's email in any comment input. A search-as-you-type dropdown appears after 2+ characters, querying the backend for matching users.

For globally-shared profiles, the backend queries the **Workspace SCIM API** directly with the search term (fast path). For explicitly-shared profiles, only contributors are shown.

### How mentions are stored

When a comment is saved, the backend extracts email patterns from the content and stores them as a lowercase JSON array in the `SlideComment.mentions` column:

```json
["tariq.yaaqba@databricks.com", "jane.doe@example.com"]
```

### How notifications appear

1. The frontend polls `GET /api/comments/mentions?session_id={id}` every 3 seconds.
2. The `session_id` parameter scopes results to the **current deck** (resolved to the deck-owner session for contributor sessions).
3. Returned mentions are grouped by `slide_id` on the frontend.
4. Each `SlideTile` shows a bell icon with a badge count for unread mentions on **that specific slide**.
5. "Last seen" timestamps per slide are stored in `localStorage` to determine unread state.

### Scoping guarantees

- **Deck level**: The backend filters `SlideComment` rows by `session_id` (deck-owner internal ID). Mentions from Deck A never appear in Deck B.
- **Slide level**: The frontend groups by `slide_id` and only passes each slide its own mentions.
- **User level**: The backend only returns comments where the current user's email appears in the `mentions` JSON array.

---

## Per-User Default Profiles

Each user has their own "default" profile, stored in the `UserProfilePreference` table. This replaces the old global `is_default` flag on `ConfigProfile`.

| Column | Purpose |
|--------|---------|
| `user_name` | The user's email (PK component) |
| `profile_id` | FK to `config_profiles` |

The API returns `is_my_default: true/false` on each profile summary. The `ProfileList` and `ProfileSelector` components use this field for rendering the "Default" badge.

---

## Identity Provider

The system needs to look up Databricks users and groups when adding contributors to a profile.

### How It Works

Users and groups are retrieved via the **Workspace SCIM API** using the app's **service principal** (system client). The service principal token is automatically provided by the Databricks Apps platform via `system.databricks_token` — no separate admin PATs are required.

**API Used:** [Workspace SCIM API](https://docs.databricks.com/api/workspace/users/list)

**Capabilities:**
- Lists all users and groups in the workspace
- Supports filtered search by username, display name, or group name
- Resolves group memberships for permission checks

### Fallback: Local Table

When the system client is unavailable (e.g. local development without Databricks), the identity provider falls back to the local `app_identities` table.

**Limitations of local mode:**
- Only lists users who have previously signed into the app
- Group-based permissions don't work (no group membership data)
- Populated automatically when users log in via middleware

### Mode Selection Logic

```
1. System client available → Workspace SCIM API (via service principal)
       ↓ (unavailable)
2. Local Table             → Default fallback (dev/offline)
```

---

## Contributor Sessions

When a contributor opens a shared presentation, the system creates a **contributor session** — a private session linked to the owner's session.

```
Owner's Session (parent)
  ├── SessionSlideDeck (shared)
  ├── SessionMessage (owner's private chat)
  └── SlideDeckVersion (shared version history)

Contributor Session (parent_session_id → owner)
  └── SessionMessage (contributor's private chat)
      (reads/writes slides from parent's deck)
```

### Flow

1. Owner creates a session, chats, generates slides
2. Contributor opens shared presentation → `POST /api/sessions/{id}/contribute`
3. System creates contributor session with `parent_session_id` pointing to owner's session
4. Contributor chats in their session → messages stored privately, slide changes applied to parent's deck
5. Neither user sees the other's chat messages

### Exclusive Editing Lock

Only one user can edit a shared session at a time. The first person to open the session acquires an exclusive editing lock. The profile owner has **no priority** — whoever arrives first gets the lock.

| Aspect | Detail |
|---|---|
| **Acquire** | Automatically when a user opens the session |
| **Heartbeat** | Client sends a heartbeat every 60 seconds to keep the lock alive |
| **Idle release** | Client releases the lock after 5 minutes of no mouse/keyboard activity |
| **Server expiry** | Lock auto-expires after 45 seconds without a heartbeat (safety net for browser crashes) |
| **Release** | Automatically when the editing user leaves / closes the session |
| **Locked-out UX** | Other users see a banner: "[User] is editing the slides" and are restricted to view-only mode |
| **Polling** | Locked-out users poll every 10 seconds; they acquire the lock once it is released |

**Server-side enforcement:** All slide mutation endpoints (`update_slide`, `delete_slide`, `reorder_slides`, `duplicate_slide`) and chat endpoints call `require_editing_lock()` which returns HTTP 423 if another user holds the lock.

**What locked-out users CAN still do:**
- View slides
- Add comments and replies
- @mention other users
- Export presentations

Per-request processing locks (`is_processing` on `session_slide_decks`) still prevent race conditions during individual slide operations (e.g. two concurrent chat edits).

---

## Database Schema

### ConfigProfile (Global Sharing)

```python
class ConfigProfile(Base):
    __tablename__ = "config_profiles"
    
    # ... existing fields ...
    global_permission: str | None    # NULL, "CAN_VIEW", "CAN_EDIT", or "CAN_MANAGE"
```

### ConfigProfileContributor

Stores access grants for profiles:

```python
class ConfigProfileContributor(Base):
    __tablename__ = "config_profile_contributors"
    
    id: int                          # Primary key
    profile_id: int                  # FK to config_profiles
    identity_type: str               # "USER" or "GROUP"
    identity_id: str                 # Databricks user/group ID
    identity_name: str               # Email for users, name for groups
    permission_level: str            # CAN_VIEW, CAN_EDIT, CAN_MANAGE
    added_by: str | None             # Who granted this permission
    added_at: datetime
    
    # Unique constraint: (profile_id, identity_id)
```

### UserSession (Contributor Support)

Sessions now support a parent-child relationship for shared presentations:

```python
class UserSession(Base):
    __tablename__ = "user_sessions"
    
    # ... existing fields ...
    parent_session_id: int | None    # FK to self — NULL = owner, set = contributor
```

### SessionSlideDeck (Locking Support)

Slide decks include concurrency control fields:

```python
class SessionSlideDeck(Base):
    __tablename__ = "session_slide_decks"
    
    # ... existing fields ...
    locked_by: str | None            # Email of user holding the exclusive editing lock
    locked_at: datetime | None       # When lock was acquired/renewed
    version: int                     # Optimistic lock counter for direct edits
```

### SlideComment

Per-slide threaded comments shared across all contributors:

```python
class SlideComment(Base):
    __tablename__ = "slide_comments"
    
    id: int                          # Primary key
    session_id: int                  # FK to user_sessions (deck owner)
    slide_id: str                    # e.g. "slide_0"
    user_name: str                   # Display name
    user_email: str                  # Email (used for identity matching)
    content: str                     # Comment body (may contain @email mentions)
    mentions: list[str] | None       # JSON array of mentioned emails, lowercase
    resolved: bool                   # Whether comment is resolved
    resolved_by: str | None          # Who resolved it
    resolved_at: datetime | None
    parent_comment_id: int | None    # FK to self — for threaded replies
    created_at: datetime
    updated_at: datetime
```

### UserProfilePreference

Per-user default profile selection:

```python
class UserProfilePreference(Base):
    __tablename__ = "user_profile_preferences"
    
    user_name: str                   # Email (PK component)
    profile_id: int                  # FK to config_profiles
```

### Slide Metadata (in deck_json)

Each slide in the JSON `slides` array now carries authorship metadata:

```json
{
  "slide_id": "slide_0",
  "html": "...",
  "created_by": "matt@example.com",
  "created_at": "2026-03-09T10:00:00Z",
  "modified_by": "tariq@example.com",
  "modified_at": "2026-03-09T11:30:00Z"
}
```

- `created_by`/`created_at` — stamped when a slide is first persisted
- `modified_by`/`modified_at` — updated on direct edits and AI chat modifications

### AppIdentity (Local Mode Only)

Stores users who have signed into the app:

```python
class AppIdentity(Base):
    __tablename__ = "app_identities"
    
    identity_id: str                 # Databricks user ID (PK)
    identity_type: str               # "USER" or "GROUP"
    identity_name: str               # Email/username
    display_name: str | None         # Friendly name
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
```

---

## Core Components

### PermissionContext

Request-scoped context containing the current user's identity:

```python
@dataclass
class PermissionContext:
    user_id: str | None              # Databricks user ID
    user_name: str | None            # Email/username
    group_ids: List[str]             # Groups the user belongs to (cached 5 min)
```

### PermissionService

Centralized permission checking:

```python
class PermissionService:
    def get_user_permission(db, profile_id, perm_ctx) -> PermissionLevel | None
    def can_view(db, profile_id, perm_ctx) -> bool
    def can_edit(db, profile_id, perm_ctx) -> bool
    def can_manage(db, profile_id, perm_ctx) -> bool
    def require_view(db, profile_id, perm_ctx) -> None   # Raises 403 if denied
    def require_edit(db, profile_id, perm_ctx) -> None
    def require_manage(db, profile_id, perm_ctx) -> None
```

**Permission Resolution Order:**
1. Is user the profile creator? → CAN_MANAGE
2. Direct user entry in contributors table? → Use that level
3. Any group the user belongs to in contributors? → Use highest level
4. Profile has `global_permission` set? → Use that level
5. No match → No access

### IdentityProvider

Unified interface backed by the app's service principal:

```python
class IdentityProvider:
    mode: IdentityProviderMode       # WORKSPACE or LOCAL
    
    def list_users(filter_query, max_results) -> List[dict]
    def list_groups(filter_query, max_results) -> List[dict]
    def search_identities(query, include_users, include_groups) -> List[dict]
    def get_user_groups(user_id) -> List[str]
    def record_user_login(user_id, user_name) -> None  # Local cache
```

---

## API Endpoints

### Contributors

```
GET    /api/settings/profiles/{id}/contributors
POST   /api/settings/profiles/{id}/contributors
PUT    /api/settings/profiles/{id}/contributors/{contrib_id}
DELETE /api/settings/profiles/{id}/contributors/{contrib_id}
```

### Global Sharing

```
PUT    /api/settings/profiles/{id}/global    # Set global_permission (body: { "global_permission": "CAN_VIEW" | "CAN_EDIT" | "CAN_MANAGE" | null })
```

### Identity Search

```
GET    /api/settings/identities/search?q=john
GET    /api/settings/identities/users
GET    /api/settings/identities/groups
GET    /api/settings/identities/provider    # Returns current mode
```

### Sessions & Presentations

```
GET    /api/sessions                           # My sessions (owner sessions only)
GET    /api/sessions/shared                    # Shared presentations (slides only, no chat)
POST   /api/sessions/{id}/contribute           # Get/create contributor session for a shared presentation
GET    /api/sessions/{id}                      # Session detail — messages only if you are the creator
GET    /api/sessions/{id}/messages             # 403 unless you are the session creator
```

### Editing Lock

```
POST   /api/sessions/{id}/lock                 # Acquire exclusive editing lock
DELETE /api/sessions/{id}/lock                 # Release editing lock
GET    /api/sessions/{id}/lock                 # Get current lock status
PUT    /api/sessions/{id}/lock/heartbeat       # Renew lock (keep alive)
```

### Comments & Mentions

```
GET    /api/comments/{session_id}/{slide_id}           # List comments for a slide
POST   /api/comments/{session_id}/{slide_id}           # Add a comment (extracts @mentions)
PUT    /api/comments/{session_id}/{slide_id}/{id}      # Edit a comment
DELETE /api/comments/{session_id}/{slide_id}/{id}      # Delete a comment
POST   /api/comments/{session_id}/{slide_id}/{id}/resolve    # Resolve a comment
POST   /api/comments/{session_id}/{slide_id}/{id}/unresolve  # Unresolve a comment
GET    /api/comments/mentions?session_id={id}          # List mentions for current user, scoped to deck
GET    /api/comments/mentionable-users?session_id={id}&query={q}  # Search mentionable users
```

---

## Group Resolution

When a user's permission is checked:

1. Fetch user's group memberships from Identity Provider
2. Cache results for 5 minutes
3. Check each group against profile contributors
4. Return highest permission found

**Example:**
- User belongs to groups: `[Engineering, Managers]`
- Profile contributors: Engineering=CAN_VIEW, Managers=CAN_EDIT
- Result: User gets CAN_EDIT (the higher permission)

---

## Polling & Real-Time Updates

| Resource | Interval | Notes |
|----------|----------|-------|
| Mentions (per-slide bell) | 3 seconds | Scoped to current deck via `session_id` param |
| Lock status (locked-out users) | 10 seconds | Stops when lock is acquired |
| Profile list | 15 seconds | Silent background poll (no loading spinner) |
| Shared decks list | 15 seconds | Silent background poll (no loading spinner) |

---

## Security Notes

1. **Creator Protection:** Profile creators get CAN_MANAGE automatically and cannot be removed
2. **Default Profile:** Per-user default stored in `UserProfilePreference`; profile itself can still be deleted
3. **App Identity:** User and group lookups use the app's service principal — no admin PATs stored or required
4. **Group Cache:** 5-minute TTL balances API efficiency with permission propagation
5. **Exclusive Lock:** Only one user can edit at a time; lock auto-expires after 45 seconds without heartbeat; client releases after 5 minutes idle
6. **Server-Side Enforcement:** All slide mutations check `require_editing_lock()` — UI bypasses cannot succeed
7. **Email-Based Identity:** All mention matching and permission checks use lowercase email, case-insensitive exact match

---

## References

- [User Guide: Profile Sharing](../user-guide/08-profile-sharing-permissions.md)
- [Database Configuration](./database-configuration.md)
- [Multi-User Concurrency](./multi-user-concurrency.md)
- [Databricks Workspace SCIM API](https://docs.databricks.com/api/workspace/users/list)
