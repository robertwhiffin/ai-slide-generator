# Session Access Control Guide

This document explains how to use the new access control system for presentations in tellr.

## Overview

tellr now provides comprehensive access control for sessions (presentations):

- **Ownership**: Every session has an owner (the creator)
- **Permissions**: Fine-grained access control (read/edit) for users and groups
- **Visibility Levels**: Control whether sessions are private, shared, or workspace-wide
- **Databricks Integration**: Uses your Databricks workspace users and groups

## Key Concepts

### Session Ownership

- Every session is created by a user (the **owner**)
- Owners automatically have full **edit** permission
- Owners can grant/revoke permissions to others
- Owners can change visibility and delete sessions

### Permission Levels

| Permission | Can View | Can Edit | Can Delete | Can Share |
|-----------|----------|----------|------------|-----------|
| **READ**  | ✓        | ✗        | ✗          | ✗         |
| **EDIT**  | ✓        | ✓        | ✗          | ✗         |
| **OWNER** | ✓        | ✓        | ✓          | ✓         |

### Visibility Levels

| Visibility | Description | Who Can Access |
|-----------|-------------|----------------|
| **private** | Owner only | Just the session owner |
| **shared** | Explicitly granted | Owner + users/groups with permissions |
| **workspace** | All can view | All workspace users (read-only unless explicitly granted edit) |

### Principal Types

Permissions can be granted to:
- **Users**: Individual Databricks workspace users (by email)
- **Groups**: Databricks workspace groups (all members inherit permission)

## API Reference

### 1. Create Session (with ownership)

Sessions are automatically owned by the authenticated user.

```bash
POST /api/sessions
Content-Type: application/json

{
  "title": "Q3 Revenue Analysis",
  "visibility": "private"  # optional: private (default), shared, workspace
}
```

**Response:**
```json
{
  "session_id": "abc123...",
  "created_by": "user@company.com",
  "visibility": "private",
  "title": "Q3 Revenue Analysis",
  "created_at": "2026-01-29T10:00:00Z"
}
```

### 2. List Accessible Sessions

Returns only sessions you have permission to access.

```bash
GET /api/sessions?limit=50
```

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "abc123...",
      "created_by": "user@company.com",
      "visibility": "private",
      "title": "My Presentation",
      "last_activity": "2026-01-29T10:00:00Z"
    },
    {
      "session_id": "def456...",
      "created_by": "other@company.com",
      "visibility": "shared",
      "title": "Shared Presentation",
      "last_activity": "2026-01-29T09:00:00Z"
    }
  ],
  "count": 2
}
```

### 3. Grant Permission

Only session owners can grant permissions.

```bash
POST /api/sessions/{session_id}/permissions
Content-Type: application/json

{
  "principal_type": "user",      # "user" or "group"
  "principal_id": "colleague@company.com",  # email or group name
  "permission": "read"           # "read" or "edit"
}
```

**Grant to a Group:**
```json
{
  "principal_type": "group",
  "principal_id": "data-analysts",
  "permission": "read"
}
```

**Response:**
```json
{
  "session_id": "abc123...",
  "principal_type": "user",
  "principal_id": "colleague@company.com",
  "permission": "read",
  "granted_by": "owner@company.com",
  "granted_at": "2026-01-29T10:05:00Z"
}
```

### 4. Revoke Permission

```bash
DELETE /api/sessions/{session_id}/permissions
Content-Type: application/json

{
  "principal_type": "user",
  "principal_id": "colleague@company.com"
}
```

**Response:**
```json
{
  "status": "revoked",
  "session_id": "abc123..."
}
```

### 5. List Session Permissions

Requires read permission on the session.

```bash
GET /api/sessions/{session_id}/permissions
```

**Response:**
```json
{
  "session_id": "abc123...",
  "permissions": [
    {
      "principal_type": "user",
      "principal_id": "colleague@company.com",
      "permission": "read",
      "granted_by": "owner@company.com",
      "granted_at": "2026-01-29T10:05:00Z"
    },
    {
      "principal_type": "group",
      "principal_id": "data-analysts",
      "permission": "read",
      "granted_by": "owner@company.com",
      "granted_at": "2026-01-29T10:10:00Z"
    }
  ],
  "count": 2
}
```

### 6. Change Session Visibility

Only owners can change visibility.

```bash
PATCH /api/sessions/{session_id}/permissions/visibility
Content-Type: application/json

{
  "visibility": "workspace"  # "private", "shared", or "workspace"
}
```

**Response:**
```json
{
  "session_id": "abc123...",
  "visibility": "workspace",
  "updated_at": "2026-01-29T10:15:00Z"
}
```

## Usage Examples

### Example 1: Share with a Colleague

```python
import requests

# Grant read permission to a colleague
response = requests.post(
    "http://localhost:8000/api/sessions/abc123/permissions",
    json={
        "principal_type": "user",
        "principal_id": "colleague@company.com",
        "permission": "read"
    }
)

print(response.json())
```

### Example 2: Share with a Team

```python
# Grant edit permission to the entire data team
response = requests.post(
    "http://localhost:8000/api/sessions/abc123/permissions",
    json={
        "principal_type": "group",
        "principal_id": "data-team",
        "permission": "edit"
    }
)
```

### Example 3: Make Workspace-Wide

```python
# Make presentation visible to all workspace users (read-only)
response = requests.patch(
    "http://localhost:8000/api/sessions/abc123/permissions/visibility",
    json={"visibility": "workspace"}
)
```

### Example 4: List My Sessions

```python
# List all sessions I can access
response = requests.get("http://localhost:8000/api/sessions")
sessions = response.json()["sessions"]

# Filter by ownership
my_sessions = [s for s in sessions if s["created_by"] == "me@company.com"]
shared_with_me = [s for s in sessions if s["created_by"] != "me@company.com"]
```

## Security Model

### Authentication

tellr uses Databricks Apps **on-behalf-of-user (OBO)** authentication:

1. User opens tellr in their browser
2. Databricks Apps proxy forwards user's token in `x-forwarded-access-token` header
3. tellr extracts user identity and creates request-scoped client
4. All operations use **your credentials** → respects Unity Catalog permissions

### Permission Inheritance

```
Owner
├─ Explicit User Grants
│  └─ user@company.com → read
├─ Group Grants
│  ├─ data-analysts → read
│  └─ All group members inherit
└─ Workspace Visibility
   └─ All workspace users → read (if visibility = "workspace")
```

### Unity Catalog Integration

tellr **inherits** Unity Catalog permissions via your token:

- When you query Genie, Databricks checks **your** UC permissions
- When you access tables, only tables **you** can access are returned
- When you create experiments, they're created under **your** identity

**Example:**
```
You: user@company.com
UC Permissions: Can access sales_data, CANNOT access hr_data

1. You create presentation → Owner: user@company.com
2. AI queries Genie → Uses YOUR token
3. Genie queries UC → Checks YOUR permissions
4. Result: Presentation includes sales_data only ✓
```

## Migration Guide

### 1. Run the Migration

```bash
# Dry run (see what will be executed)
python scripts/run_migration.py --dry-run

# Apply migration
python scripts/run_migration.py
```

### 2. Restart Application

```bash
# Local development
./stop_start_app.sh

# Databricks Apps
# Redeploy using the deployment CLI
```

### 3. Verify

```bash
# Create a test session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Session"}'

# Check ownership
curl http://localhost:8000/api/sessions/{session_id}
```

### 4. Backfill Existing Sessions (Optional)

Existing sessions may not have `created_by` set. The migration automatically backfills from `user_id` where possible.

To manually set ownership:

```sql
-- Set owner for sessions without one
UPDATE user_sessions 
SET created_by = 'default-owner@company.com'
WHERE created_by IS NULL;
```

## Troubleshooting

### Issue: "Permission denied" errors

**Cause**: User lacks required permission on session.

**Solution**:
1. Check session ownership: `GET /api/sessions/{session_id}`
2. Check permissions: `GET /api/sessions/{session_id}/permissions`
3. Have owner grant you permission

### Issue: "Could not determine user identity"

**Cause**: 
- Running locally without token forwarding
- x-forwarded-access-token header not present

**Solution**:
- In production: Databricks Apps automatically forwards tokens
- In development: Set DATABRICKS_HOST and DATABRICKS_TOKEN env vars

### Issue: Group permissions not working

**Cause**: User not found in Databricks workspace or not in group.

**Solution**:
1. Verify user exists in workspace
2. Check group membership in Databricks admin console
3. Verify group name matches exactly (case-sensitive)

### Issue: Workspace visibility not working

**Cause**: Session visibility still set to "private" or "shared".

**Solution**:
```bash
# Change visibility to workspace
curl -X PATCH http://localhost:8000/api/sessions/{session_id}/permissions/visibility \
  -H "Content-Type: application/json" \
  -d '{"visibility": "workspace"}'
```

## Best Practices

1. **Default to Private**: Keep sessions private by default, share only when needed
2. **Use Groups**: Grant permissions to groups instead of individual users when possible
3. **Review Permissions**: Periodically review who has access to sensitive presentations
4. **Workspace Visibility**: Use sparingly for truly public presentations
5. **Remove Access**: Revoke permissions when team members change roles
6. **Audit Logs**: Check `config_history` table for permission change history

## Database Schema

### New Tables

**session_permissions**
- `id`: Primary key
- `session_id`: FK to user_sessions
- `principal_type`: 'user' or 'group'
- `principal_id`: Email or group name
- `permission`: 'read' or 'edit'
- `granted_by`: Who granted this permission
- `granted_at`: When permission was granted

### Modified Tables

**user_sessions**
- `created_by`: Owner's email (NEW)
- `visibility`: 'private', 'shared', 'workspace' (NEW)
- `user_id`: Deprecated (kept for backward compatibility)

## Future Enhancements

Potential improvements for access control:

- **Expiring Permissions**: Time-limited access grants
- **Transfer Ownership**: Allow owners to transfer ownership
- **Role-Based Access**: Pre-defined roles (viewer, editor, admin)
- **Audit Trail**: Detailed history of permission changes
- **Notification System**: Notify users when shared with them
- **External Sharing**: Share presentations outside Databricks workspace

## Support

For issues or questions:
1. Check this documentation
2. Review the API responses for error details
3. Check application logs for detailed error messages
4. Contact your Databricks account team
