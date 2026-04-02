# Permissions Model Architecture

**Status:** Complete
**Last Updated:** April 2026

## Overview

The AI Slide Generator uses a deck-centric permissions model where decks (sessions with slide decks) are the primary shareable entity, completely decoupled from profiles. Profiles are independently shareable configuration templates with their own simpler permission model.

**Key principles:**
- Decks are the primary entity; everything else is a dimension.
- Sharing a profile never grants access to any deck. Sharing a deck never grants access to any profile.
- Conversations (chat messages) are always private to the session creator.
- Identity matching uses Databricks user/group IDs as the primary key, with email (case-insensitive) as fallback. The `identity_id` column stores the Databricks ID; `identity_name` stores the email/group name for display.
- Any session can be shared via deck contributors, regardless of whether it was created from a profile.

## Permission Levels

A single combined enum with four values, ordered by priority:

| Level | Domain | Description |
|-------|--------|-------------|
| **CAN_USE** | Profile only | See profile in list, load into sessions, set as personal default |
| **CAN_VIEW** | Deck only | Read-only access to presentations |
| **CAN_EDIT** | Both | Modify content (profile config or deck slides) |
| **CAN_MANAGE** | Both | Full control (delete, manage sharing) |

CAN_USE and CAN_VIEW are at the same priority tier — they are context-specific equivalents (lowest access for their respective domains).

- **Deck contributors** use: CAN_VIEW, CAN_EDIT, CAN_MANAGE
- **Profile contributors** use: CAN_USE, CAN_EDIT, CAN_MANAGE
- Validation ensures the correct subset is used for each context

---

## Permission Tables

### Deck Permissions

| Action | Creator | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:-------:|:--------:|:--------:|:----------:|
| View slides | ✅ | ✅ | ✅ | ✅ |
| View slide metadata | ✅ | ✅ | ✅ | ✅ |
| Export (PPTX / Google Slides) | ✅ | ✅ | ✅ | ✅ |
| Edit slides (direct + chat) | ✅ | ❌ | ✅ | ✅ |
| Reorder / duplicate slides | ✅ | ❌ | ✅ | ✅ |
| Delete slides | ✅ | ❌ | ❌ | ✅ |
| Manage deck contributors | ✅ | ❌ | ❌ | ✅ |
| Delete deck | ✅ | ❌ | ❌ | ✅ |

### Profile Permissions

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

### Conversation Privacy

Conversations (chat messages) are **always private** to the session creator.

| Action | Session Creator | Any Contributor |
|--------|:--------------:|:---------------:|
| View chat messages | ✅ | ❌ |
| Send chat messages | ✅ | ❌ (uses own contributor session) |
| View other users' conversations | ❌ | ❌ |

> When a CAN_EDIT contributor uses chat to modify slides, they do so through their own **contributor session** — a private session that shares the parent's slide deck but has its own chat history.

---

## Deck Sharing

Decks are shared directly via the `DeckContributor` table. There is no global/workspace-wide sharing on decks — decks are always explicitly shared with specific users or groups.

### Sharing Flow

1. Open a deck and click the **Share** button to open the permissions manager
2. Search for a user or group by name/email
3. Select the permission level (CAN_VIEW, CAN_EDIT, or CAN_MANAGE)
4. Click Add — the contributor now sees the deck in their "Shared with Me" tab
5. Use the **Copy Link** button to share a direct URL to the deck

### Permission Resolution

`PermissionService.get_deck_permission(db, session_id, user_id, user_name, group_ids)`:

1. Is user the session creator (`user_sessions.created_by`)? → CAN_MANAGE
2. Direct user entry in `deck_contributors` (match by `identity_id`, fallback by `identity_name`)? → Use that level
3. Any group the user belongs to in `deck_contributors`? → Use highest level
4. No match → No access

---

## Profile Sharing

Profiles are shared independently from decks. Sharing a profile grants access to the profile configuration template only, not to any decks.

### Permission Levels

| Level | Meaning |
|-------|---------|
| **CAN_USE** | See profile in list, load into own sessions, set as personal default |
| **CAN_EDIT** | Modify agent config, rename, update description |
| **CAN_MANAGE** | Full control: edit, delete, manage sharing |

### Global Profile Sharing

Profiles can be shared with all workspace users via the `global_permission` column on `ConfigProfile`. This controls profile visibility only (CAN_USE / CAN_EDIT / CAN_MANAGE on the profile template). It has no bearing on deck access.

### Permission Resolution

`PermissionService.get_profile_permission(db, profile_id, user_id, user_name, group_ids)`:

1. Is user the profile creator? → CAN_MANAGE
2. Direct user entry in `config_profile_contributors`? → Use that level
3. Any group in `config_profile_contributors`? → Use highest level
4. Profile has `global_permission` set? → Use that level
5. No match → No access

---

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

### Flow

1. Owner creates a session, chats, generates slides
2. Contributor opens shared deck → `POST /api/sessions/{id}/contribute`
3. System creates contributor session with `parent_session_id` pointing to owner's session
4. Contributor chats in their session → messages stored privately, slide changes applied to parent's deck
5. Neither user sees the other's chat messages

The contribute endpoint resolves permissions via `get_deck_permission(parent_session.id, ...)` and requires CAN_VIEW or higher. Any session can be shared via deck contributors.

---

## Exclusive Editing Lock

Only one user can edit a shared session at a time. First-come, heartbeat-based, auto-expires after 45 seconds without heartbeat. Client releases after 5 minutes idle.

| Aspect | Detail |
|--------|--------|
| **Acquire** | Automatically when a user opens the session |
| **Heartbeat** | Client sends a heartbeat to keep the lock alive |
| **Idle release** | Client releases the lock after 5 minutes of no activity |
| **Server expiry** | Lock auto-expires after 45 seconds without a heartbeat |
| **Release** | Automatically when the editing user leaves / closes the session |
| **Locked-out UX** | Other users see a banner: "[User] is editing the slides" and are restricted to view-only mode |
| **Polling** | Locked-out users poll every 10 seconds; they acquire the lock once it is released |

All slide mutation endpoints enforce `require_editing_lock()`.

**What locked-out users CAN still do:**
- View slides
- Export presentations

---

## Database Schema

### DeckContributor

Stores access grants for decks:

```python
class DeckContributor(Base):
    __tablename__ = "deck_contributors"

    id: int                          # PK
    user_session_id: int             # FK to user_sessions.id (integer PK)
    identity_type: str               # "USER" or "GROUP"
    identity_id: str                 # Databricks user/group ID
    identity_name: str               # Email for users, name for groups
    permission_level: str            # CAN_VIEW, CAN_EDIT, CAN_MANAGE
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    # Unique constraint: (user_session_id, identity_id)
```

### ConfigProfileContributor

Stores access grants for profiles:

```python
class ConfigProfileContributor(Base):
    __tablename__ = "config_profile_contributors"

    id: int                          # PK
    profile_id: int                  # FK to config_profiles
    identity_type: str               # "USER" or "GROUP"
    identity_id: str                 # Databricks user/group ID
    identity_name: str               # Email for users, name for groups
    permission_level: str            # CAN_USE, CAN_EDIT, CAN_MANAGE
    created_by: str | None           # Who added this contributor
    created_at: datetime
    updated_at: datetime

    # Unique constraint: (profile_id, identity_id)
```

### UserSession

Sessions support a parent-child relationship for shared decks. The `profile_id` and `profile_name` columns have been removed — sessions have no relationship to profiles.

```python
class UserSession(Base):
    __tablename__ = "user_sessions"

    # ... existing fields ...
    parent_session_id: int | None    # FK to self — NULL = owner, set = contributor
```

### ConfigProfile

`global_permission` controls profile visibility only (CAN_USE / CAN_EDIT / CAN_MANAGE). It has no bearing on deck access.

```python
class ConfigProfile(Base):
    __tablename__ = "config_profiles"

    # ... existing fields ...
    global_permission: str | None    # NULL, "CAN_USE", "CAN_EDIT", or "CAN_MANAGE"
```

### SessionSlideDeck

Slide decks include concurrency control fields:

```python
class SessionSlideDeck(Base):
    __tablename__ = "session_slide_decks"

    # ... existing fields ...
    locked_by: str | None            # Email of user holding the exclusive editing lock
    locked_at: datetime | None       # When lock was acquired/renewed
    version: int                     # Optimistic lock counter for direct edits
```

### UserProfilePreference

Per-user default profile selection:

```python
class UserProfilePreference(Base):
    __tablename__ = "user_profile_preferences"

    id: int                          # PK (auto-increment)
    user_name: str                   # Email (unique, indexed)
    default_profile_id: int | None   # FK to config_profiles (SET NULL on delete)
    updated_at: datetime
```

### AppIdentity (Local Mode Only)

```python
class AppIdentity(Base):
    __tablename__ = "app_identities"

    id: int                          # PK (auto-increment)
    identity_id: str                 # Databricks user ID (unique, indexed)
    identity_type: str               # "USER" or "GROUP"
    identity_name: str               # Email/username
    display_name: str | None
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

Centralized permission checking split into deck and profile paths:

**Deck methods:**

```python
class PermissionService:
    def get_deck_permission(self, db, session_id, user_id, user_name, group_ids) -> PermissionLevel | None
    def can_view_deck(self, db, session_id, user_id, user_name, group_ids) -> bool
    def can_edit_deck(self, db, session_id, user_id, user_name, group_ids) -> bool
    def can_manage_deck(self, db, session_id, user_id, user_name, group_ids) -> bool
    def require_view_deck(self, db, session_id, user_id, user_name, group_ids) -> None    # Raises 403
    def require_edit_deck(self, db, session_id, user_id, user_name, group_ids) -> None
    def require_manage_deck(self, db, session_id, user_id, user_name, group_ids) -> None
    def get_shared_session_ids(self, db, user_id, user_name, group_ids) -> Set[int]
```

**Profile methods:**

```python
class PermissionService:
    def get_profile_permission(self, db, profile_id, user_id, user_name, group_ids) -> PermissionLevel | None
    def get_current_user_profile_permission(self, db, profile_id) -> PermissionLevel | None
    def can_use_profile(self, db, profile_id) -> bool        # Uses current request context
    def can_edit_profile(self, db, profile_id) -> bool
    def can_manage_profile(self, db, profile_id) -> bool
    def require_use_profile(self, db, profile_id) -> None    # Raises 403
    def require_edit_profile(self, db, profile_id) -> None
    def require_manage_profile(self, db, profile_id) -> None
    def get_accessible_profile_ids(self, db, user_id, user_name, group_ids) -> List[int]
    def get_current_user_accessible_profile_ids(self, db) -> List[int]
    def get_profiles_with_permissions(self, db, user_id, user_name, group_ids) -> List[Tuple[ConfigProfile, PermissionLevel]]
```

Note: Deck methods take explicit identity params (`user_id`, `user_name`, `group_ids`). Profile convenience methods (`can_use_profile`, `can_edit_profile`, etc.) resolve identity from the current request's `PermissionContext` automatically. `get_current_user_profile_permission()` and `get_current_user_accessible_profile_ids()` are convenience wrappers that also use the request context.

### IdentityProvider

Unified interface backed by the app's service principal:

```python
class IdentityProvider:
    mode: IdentityProviderMode       # WORKSPACE or LOCAL

    def list_users(self, filter_query, max_results) -> List[dict]
    def list_groups(self, filter_query, max_results) -> List[dict]
    def search_identities(self, query, include_users, include_groups, max_results) -> List[dict]
    def get_user_groups(self, user_id) -> List[str]
    def get_user_by_id(self, user_id) -> dict | None
    def get_group_by_id(self, group_id) -> dict | None
    def record_user_login(self, user_id, user_name, display_name=None) -> None  # Local cache
```

**Utility functions** (module-level in `identity_provider.py`):

```python
def resolve_display_name(email: str) -> str
    # Returns SCIM displayName for an email, falling back to the email itself.
    # Uses an LRU cache (256 entries) for repeated lookups.

def resolve_display_names(emails: List[str]) -> Dict[str, str]
    # Batch-resolve a list of emails to display names.
```

---

## API Endpoints

### Deck Contributors

```
GET    /api/sessions/{session_id}/contributors
POST   /api/sessions/{session_id}/contributors
PUT    /api/sessions/{session_id}/contributors/{contributor_id}
DELETE /api/sessions/{session_id}/contributors/{contributor_id}
```

All require CAN_MANAGE on the deck.

### Deck Contributor Sessions

```
POST   /api/sessions/{session_id}/contribute    # Create/get contributor session (requires CAN_VIEW+)
GET    /api/sessions/shared                      # List decks shared with current user
```

`GET /api/sessions/shared` resolves via `deck_contributors` joined to `user_sessions` and `session_slide_decks`.

### Profile Contributors

```
GET    /api/settings/profiles/{id}/contributors
POST   /api/settings/profiles/{id}/contributors
PUT    /api/settings/profiles/{id}/contributors/{contrib_id}
DELETE /api/settings/profiles/{id}/contributors/{contrib_id}
```

Permission levels: CAN_USE, CAN_EDIT, CAN_MANAGE. Managing contributors requires CAN_MANAGE on the profile.

### Profile Endpoints

```
GET    /api/profiles                                    # List profiles visible to current user
POST   /api/profiles/save-from-session/{session_id}     # Create profile (creator gets CAN_MANAGE)
PUT    /api/profiles/{profile_id}                        # Requires CAN_EDIT
DELETE /api/profiles/{profile_id}                        # Requires CAN_MANAGE
POST   /api/sessions/{session_id}/load-profile/{id}     # Requires CAN_USE
```

### Sessions

```
GET    /api/sessions                           # My sessions (owner sessions only)
GET    /api/sessions/shared                    # Shared decks (slides only, no chat)
POST   /api/sessions/{id}/contribute           # Get/create contributor session
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

### Identity Search

```
GET    /api/settings/identities/search?q=john
GET    /api/settings/identities/users
GET    /api/settings/identities/groups
GET    /api/settings/identities/provider    # Returns current mode
```

---

## Identity Provider

Users and groups are resolved via the Workspace SCIM API using the app's service principal. The service principal token is automatically provided by the Databricks Apps platform via `system.databricks_token` — no separate admin PATs are required.

### Fallback: Local Table

When the system client is unavailable (e.g. local development), the identity provider falls back to the local `app_identities` table.

**Limitations of local mode:**
- Only lists users who have previously signed into the app
- Group-based permissions don't work (no group membership data)
- Populated automatically when users log in via middleware

### Mode Selection

```
1. System client available → Workspace SCIM API (via service principal)
       ↓ (unavailable)
2. Local Table             → Default fallback (dev/offline)
```

---

## Group Resolution

When a user's permission is checked:

1. Fetch user's group memberships from Identity Provider
2. Cache results for 5 minutes
3. Check each group against the relevant contributors table (deck or profile)
4. Return highest permission found

**Example:**
- User belongs to groups: `[Engineering, Managers]`
- Deck contributors: Engineering=CAN_VIEW, Managers=CAN_EDIT
- Result: User gets CAN_EDIT (the higher permission)

---

## Polling & Real-Time Updates

| Resource | Interval | Notes |
|----------|----------|-------|
| Lock status (locked-out users) | 10 seconds | Stops when lock is acquired |
| Profile list | 15 seconds | Silent background poll |
| Shared decks list | 15 seconds | Silent background poll |

---

## Security Notes

1. **Creator protection:** Session creators get CAN_MANAGE automatically via the resolution algorithm (step 1 checks `created_by`). Creators are not stored in `deck_contributors` — protection is at the resolution layer.
2. **Profile creator protection:** Profile creators get CAN_MANAGE automatically and cannot be removed.
3. **No cross-pollination:** Deck and profile permissions are completely independent. Sharing a profile never grants deck access. Sharing a deck never grants profile access.
4. **No global deck sharing:** Decks have no `global_permission` equivalent — always explicitly shared with specific users/groups.
5. **App identity:** User and group lookups use the app's service principal — no admin PATs.
6. **Group cache:** 5-minute TTL balances API efficiency with permission propagation.
7. **Exclusive lock:** One editor at a time; 45-second server expiry; 5-minute idle release.
8. **Server-side enforcement:** All slide mutations check `require_editing_lock()`.
9. **Identity matching:** Primary match by Databricks user/group ID (`identity_id`), fallback match by email (`identity_name`), case-insensitive.

---

## References

- [User Guide: Sharing & Permissions](../user-guide/08-profile-sharing-permissions.md)
- [Database Configuration](./database-configuration.md)
- [Multi-User Concurrency](./multi-user-concurrency.md)
- [Databricks Workspace SCIM API](https://docs.databricks.com/api/workspace/users/list)
