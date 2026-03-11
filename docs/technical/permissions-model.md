# Permissions Model Architecture

**Status:** Complete  
**Last Updated:** March 2026

## Overview

The AI Slide Generator implements a permissions model for sharing configuration profiles and their associated presentations with Databricks users and groups.

**Key principle:** Conversations are always private. Profile sharing controls access to **presentations (slide decks)**, never to chat history.

## Permission Levels

Three permission levels control what users can do:

### CAN_VIEW
Read-only access. Users can see presentations but not modify them.

### CAN_EDIT  
Modification access. Users can change slide content but not delete presentations or manage assets.

### CAN_MANAGE
Full administrative control over the profile. Users can do everything including delete and manage assets.

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
| Edit own comment | ✅ | ✅ | ✅ | ✅ |
| Delete own comment | ✅ | ✅ | ✅ | ✅ |
| Resolve / unresolve comments | ✅ | ❌ | ✅ | ✅ |

### Conversation Privacy

Conversations (chat messages) are **always private** to the session creator.

| Action | Session Creator | Any Contributor |
|--------|:--------------:|:---------------:|
| View chat messages | ✅ | ❌ |
| Send chat messages | ✅ | ❌ (uses own contributor session) |
| View other users' conversations | ❌ | ❌ |

> **Note:** When a CAN_EDIT contributor uses chat to modify slides, they do so through their own **contributor session** — a private session that shares the parent's slide deck but has its own chat history. The original session creator never sees the contributor's chat, and the contributor never sees the creator's chat.

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

### Concurrent Editing

When multiple users edit the same deck simultaneously:

| Conflict Type | Mechanism | User Experience |
|---|---|---|
| Two chat edits at once | Deck-level lock (`locked_by` on `session_slide_decks`) | "Slides are being updated by [user]. Please wait." |
| Chat + direct edit | Lock blocks direct edits while agent is running | Same message |
| Two direct edits at once | Version counter (optimistic lock) | Auto-refresh + re-apply |
| Stale lock (crash) | 2-minute auto-expiry | Self-healing |

---

## Database Schema

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
    locked_by: str | None            # Username holding the edit lock
    locked_at: datetime | None       # When lock was acquired (auto-expires after 2 min)
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
    user_name: str                   # Comment author
    content: str                     # Comment body
    resolved: bool                   # Whether comment is resolved
    resolved_by: str | None          # Who resolved it
    resolved_at: datetime | None
    parent_comment_id: int | None    # FK to self — for threaded replies
    created_at: datetime
    updated_at: datetime
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
4. No match → No access

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

## Security Notes

1. **Creator Protection:** Profile creators get CAN_MANAGE automatically and cannot be removed
2. **Default Profile:** Cannot be deleted (must set another as default first)
3. **Token Storage:** Admin tokens should be set via environment variables, not hardcoded
4. **Group Cache:** 5-minute TTL balances API efficiency with permission propagation

---

## References

- [User Guide: Profile Sharing](../user-guide/08-profile-sharing-permissions.md)
- [Database Configuration](./database-configuration.md)
- [Databricks Account SCIM API](https://docs.databricks.com/api/account/accountusers/list)
- [Databricks Workspace SCIM API](https://docs.databricks.com/api/workspace/users/list)
