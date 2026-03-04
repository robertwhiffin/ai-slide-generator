# Permissions Model Architecture

**Status:** Complete  
**Last Updated:** March 2026

## Overview

The AI Slide Generator implements role-based access control (RBAC) for sharing configuration profiles and their associated content with Databricks users and groups.

## Permission Levels

Three permission levels control what users can do:

### CAN_VIEW
Read-only access. Users can see content but not modify it.

### CAN_EDIT  
Modification access. Users can change content but not delete it or manage access.

### CAN_MANAGE
Full administrative control. Users can do everything including delete and manage contributors.

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

### Session Permissions

Sessions inherit permissions from their associated profile.

| Action | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:--------:|:--------:|:----------:|
| View session in "Shared with Me" | ✅ | ✅ | ✅ |
| View session content | ✅ | ✅ | ✅ |
| Create new sessions | ✅ | ✅ | ✅ |
| **Rename session** | ❌ | ✅ | ✅ |
| **Delete session** | ❌ | ❌ | ✅ |

> **Note:** Users always have full control over sessions they created, regardless of profile permissions.

### Slide Permissions

Slides inherit permissions from the session's profile.

| Action | CAN_VIEW | CAN_EDIT | CAN_MANAGE |
|--------|:--------:|:--------:|:----------:|
| View slides | ✅ | ✅ | ✅ |
| **Edit slide content** | ❌ | ✅ | ✅ |
| **Reorder slides** | ❌ | ✅ | ✅ |
| **Duplicate slides** | ❌ | ✅ | ✅ |
| **Use chat to regenerate** | ❌ | ✅ | ✅ |
| **Delete slides** | ❌ | ❌ | ✅ |

---

## Identity Provider Modes

The system needs to look up Databricks users and groups when adding contributors to a profile. Three modes are supported, selected automatically based on environment variables.

### Mode 1: Account API

**When to use:** Organizations that want to share profiles across multiple workspaces.

**Configuration:**
```yaml
DATABRICKS_ACCOUNT_HOST: "https://accounts.cloud.databricks.com"
DATABRICKS_ACCOUNT_ID: "your-account-id"
DATABRICKS_ACCOUNT_ADMIN_TOKEN: "dapi..."
```

**Capabilities:**
- Lists all users and groups in the Databricks account
- Works across all workspaces in the account
- Requires an account admin PAT

**API Used:** [Account SCIM API](https://docs.databricks.com/api/account/accountusers/list)

---

### Mode 2: Workspace API

**When to use:** Single-workspace deployments where account-level access isn't available.

**Configuration:**
```yaml
DATABRICKS_WORKSPACE_ADMIN_TOKEN: "dapi..."
# DATABRICKS_HOST is auto-injected by Databricks Apps
```

**Capabilities:**
- Lists all users and groups in the specific workspace
- Only sees users/groups assigned to that workspace
- Requires a workspace admin PAT

**API Used:** [Workspace SCIM API](https://docs.databricks.com/api/workspace/users/list)

---

### Mode 3: Local Table

**When to use:** When no admin tokens are available, or for simpler deployments.

**Configuration:**
```yaml
# No tokens needed - this is the default fallback
```

**Capabilities:**
- Only lists users who have previously signed into the app
- No groups available (group permissions won't work)
- Populated automatically when users log in

**How it works:**
1. User signs into the app
2. Middleware captures their identity from `x-forwarded-access-token`
3. Identity is stored in `app_identities` table
4. Future contributor searches can find this user

**Limitations:**
- Cannot search for users who haven't logged in yet
- Group-based permissions don't work (no group membership data)

---

### Mode Selection Logic

The system checks environment variables in order and uses the first available mode:

```
1. Account API    → If DATABRICKS_ACCOUNT_HOST + DATABRICKS_ACCOUNT_ID + DATABRICKS_ACCOUNT_ADMIN_TOKEN are all set
       ↓ (not set)
2. Workspace API  → If DATABRICKS_WORKSPACE_ADMIN_TOKEN is set
       ↓ (not set)
3. Local Table    → Default fallback (always available)
```

### Comparison Table

| Feature | Account API | Workspace API | Local Table |
|---------|:-----------:|:-------------:|:-----------:|
| Cross-workspace users | ✅ | ❌ | ❌ |
| Single workspace users | ✅ | ✅ | ✅* |
| Groups | ✅ | ✅ | ❌ |
| Requires admin token | ✅ | ✅ | ❌ |
| Setup complexity | High | Medium | None |

*Only users who have logged into the app

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

Unified interface for all three modes:

```python
class IdentityProvider:
    mode: IdentityProviderMode       # ACCOUNT, WORKSPACE, or LOCAL
    
    def list_users(filter_query, max_results) -> List[dict]
    def list_groups(filter_query, max_results) -> List[dict]
    def search_identities(query, include_users, include_groups) -> List[dict]
    def get_user_groups(user_id) -> List[str]
    def record_user_login(user_id, user_name) -> None  # For local mode
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

### Sessions

```
GET    /api/sessions                        # My sessions only
GET    /api/sessions/shared                 # Sessions from profiles I have access to
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
