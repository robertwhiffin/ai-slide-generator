# Access Control Implementation Summary

Complete implementation of session-level access control for tellr.

## What Was Implemented

### ✅ Database Layer
- **New Table**: `session_permissions` for ACL entries
- **Updated Table**: `user_sessions` with `created_by` (owner) and `visibility` columns
- **Migration Script**: `scripts/migrations/001_add_session_permissions.sql`
- **Models**: SQLAlchemy models for permissions with enums for type safety

### ✅ Permission Service
- **Core Logic**: `src/services/permission_service.py`
  - Check user/group permissions
  - Grant/revoke access
  - List accessible sessions
  - Databricks group membership resolution
  - Permission hierarchy (owner > edit > read)

### ✅ User Context Management
- **New Module**: `src/core/user_context.py`
  - Stores current authenticated user in ContextVar
  - Request-scoped user identity
  - Integration with Databricks API for user lookup

### ✅ Updated Middleware
- **Enhanced**: `src/api/main.py` user_auth_middleware
  - Extracts user identity from `x-forwarded-user` header
  - Falls back to Databricks API query
  - Sets user context for request lifecycle

### ✅ Updated Session Manager
- **Enhanced**: `src/api/services/session_manager.py`
  - Auto-sets `created_by` and `visibility = 'private'` on session creation
  - Permission checks on get/delete/rename
  - Lists only accessible sessions with optional `profile_id` filter for profile-scoped history
  - New methods for permission management

### ✅ Auto-Migration on Startup
- **Enhanced**: `src/core/database.py`
  - `_run_migrations()` inspects live schema and adds missing columns (`created_by`, `visibility`, `experiment_id`)
  - Runs automatically during `init_db()` before `Base.metadata.create_all()`
  - Ensures deployed apps self-heal schema differences without manual SQL

### ✅ Permission API Routes
- **New**: `src/api/routes/permissions.py`
  - `POST /api/sessions/{id}/permissions` - Grant permission
  - `DELETE /api/sessions/{id}/permissions` - Revoke permission
  - `GET /api/sessions/{id}/permissions` - List permissions
  - `PATCH /api/sessions/{id}/permissions/visibility` - Change visibility

### ✅ Documentation
- **User Guide**: `docs/access-control.md`
- **Implementation Guide**: This file

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  REQUEST                                                        │
│  - Header: x-forwarded-access-token (user's OAuth token)      │
│  - Header: x-forwarded-user (user's email)                    │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  MIDDLEWARE (src/api/main.py)                                  │
│  1. Create user-scoped Databricks client                      │
│  2. Extract user identity → set_current_user()                │
│  3. Store in ContextVar for request scope                     │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  API ROUTES                                                     │
│  - sessions.py: CRUD with permission enforcement              │
│  - permissions.py: Permission management                       │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  SESSION MANAGER (src/api/services/session_manager.py)        │
│  - Calls PermissionService for access checks                  │
│  - Enforces owner-only operations                             │
│  - Filters sessions by accessibility                          │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  PERMISSION SERVICE (src/services/permission_service.py)      │
│  - check_permission(): Is user allowed?                       │
│  - grant_permission(): Add ACL entry                          │
│  - list_accessible_sessions(): Get all user can see          │
│  - _get_user_groups(): Query Databricks for group membership │
└───────────────────────┬────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  DATABASE                                                       │
│  - user_sessions: created_by, visibility                      │
│  - session_permissions: ACL entries                           │
└────────────────────────────────────────────────────────────────┘
```

## Permission Resolution Logic

```python
def can_user_access(session, user, required_permission):
    """
    0. Legacy session (created_by is NULL)? → Yes (any authenticated user)
    1. Owner? → Yes (always has edit)
    2. Workspace visibility + read required? → Yes
    3. User has explicit grant? → Check level
    4. User in group with grant? → Check level
    5. Otherwise → No
    """
```

**Legacy session handling:** Sessions created before ownership tracking have `created_by = NULL`. These are accessible to any authenticated user to prevent "permission denied" errors on pre-existing data.

## Files Created

```
src/
├── core/
│   └── user_context.py                    # NEW: User context management
├── database/
│   └── models/
│       └── permissions.py                  # NEW: Permission models
├── services/
│   └── permission_service.py              # NEW: Permission logic
└── api/
    └── routes/
        └── permissions.py                  # NEW: Permission API

scripts/
├── migrations/
│   └── 001_add_session_permissions.sql   # NEW: Database migration
└── run_migration.py                       # NEW: Migration runner

docs/
├── access-control.md                      # NEW: User guide
└── access-control-implementation.md       # NEW: This file
```

## Files Modified

```
src/
├── core/
│   └── databricks_client.py               # No changes needed (already has user client)
├── database/
│   └── models/
│       ├── __init__.py                    # Added permissions imports
│       └── session.py                     # Added created_by, visibility, permissions relationship
└── api/
    ├── main.py                            # Enhanced middleware, added permissions router
    └── services/
        └── session_manager.py             # Added permission checks, new methods
```

## Database Schema Changes

### user_sessions (modified)
```sql
ALTER TABLE user_sessions 
ADD COLUMN created_by VARCHAR(255);     -- Owner's email

ALTER TABLE user_sessions 
ADD COLUMN visibility VARCHAR(20) DEFAULT 'private';  -- Visibility level

CREATE INDEX ix_user_sessions_created_by ON user_sessions(created_by);
```

### session_permissions (new)
```sql
CREATE TABLE session_permissions (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL,
    principal_type VARCHAR(20) NOT NULL,    -- 'user' or 'group'
    principal_id VARCHAR(255) NOT NULL,     -- email or group name
    permission VARCHAR(20) NOT NULL,        -- 'read' or 'edit'
    granted_by VARCHAR(255) NOT NULL,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES user_sessions(id) ON DELETE CASCADE,
    UNIQUE (session_id, principal_type, principal_id)
);
```

## How to Deploy

### 1. Run Migration

```bash
# Test migration (dry-run)
python scripts/run_migration.py --dry-run

# Apply migration
python scripts/run_migration.py
```

### 2. Restart Application

```bash
# Local development
./stop_start_app.sh

# Or manually
uvicorn src.api.main:app --reload --port 8000
```

### 3. Verify

```bash
# Test session creation
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Session"}'

# Check current user
curl http://localhost:8000/api/user/current

# List accessible sessions
curl http://localhost:8000/api/sessions
```

## Testing Checklist

- [ ] Session creation sets `created_by` to current user
- [ ] Owner can view their session
- [ ] Non-owner cannot view private session (403 error)
- [ ] Owner can grant read permission
- [ ] Granted user can view session
- [ ] Granted user cannot edit session (403 on rename/delete)
- [ ] Owner can grant edit permission
- [ ] Granted editor can rename session
- [ ] Group permission grants work
- [ ] Workspace visibility grants read to all
- [ ] Owner can revoke permission
- [ ] Owner can change visibility
- [ ] list_sessions returns only accessible sessions

## Configuration

### Environment Variables

No new environment variables required! The system uses:

- `DATABRICKS_HOST`: Databricks workspace URL
- `DATABRICKS_TOKEN`: System client token (existing)
- User token forwarded by Databricks Apps proxy

### Databricks Apps Headers

Automatically forwarded by Databricks Apps:

- `x-forwarded-access-token`: User's OAuth token
- `x-forwarded-user`: User's email (optional, will query API if not present)

## Security Considerations

### ✅ Implemented
- User identity extracted from authenticated token
- All operations use user's credentials
- Permission checks on all session operations
- Owner-only operations (grant/revoke/visibility)
- Unity Catalog permissions inherited via user token
- Database CASCADE deletes for cleanup

### 🔒 Best Practices
- Always use HTTPS in production
- Log all permission changes
- Regularly audit session permissions
- Use groups instead of individual grants when possible
- Default visibility to "private"

## Backward Compatibility

### Existing Sessions
- Migration backfills `created_by` from `user_id` where possible
- Sessions without owner can be claimed via admin script
- `user_id` column kept for backward compatibility

### Existing API Calls
- `GET /api/sessions` now filters by permission (was: all sessions)
- `POST /api/sessions` now sets `created_by` automatically
- All other endpoints backward compatible

### Breaking Changes
- **list_sessions**: Now returns only accessible sessions (was: all sessions)
  - Impact: Frontend may show fewer sessions
  - Fix: Expected behavior for access control

## Troubleshooting

### Issue: All sessions show 403 errors

**Cause**: No `created_by` set on sessions

**Fix**:
```sql
-- Set owner for existing sessions
UPDATE user_sessions 
SET created_by = user_id 
WHERE created_by IS NULL AND user_id IS NOT NULL;

-- Or set a default owner
UPDATE user_sessions 
SET created_by = 'admin@company.com'
WHERE created_by IS NULL;
```

### Issue: User identity not detected

**Cause**: x-forwarded-user header not present, Databricks API call failing

**Fix**:
1. Check logs for "Could not determine user identity"
2. Verify `DATABRICKS_HOST` is set
3. Verify user token is valid
4. Check network connectivity to Databricks workspace

### Issue: Group permissions not working

**Cause**: User not in Databricks group or group name incorrect

**Fix**:
1. Check user's groups in Databricks admin console
2. Verify group name matches exactly (case-sensitive)
3. Check logs for group resolution errors

## Performance Considerations

- **Group Membership Caching**: Groups are cached per-request to avoid repeated API calls
- **Permission Query Optimization**: Indexes on `session_id`, `principal_type`, `principal_id`
- **Bulk Operations**: `list_accessible_sessions` uses a single query with joins

### Scaling
- For large workspaces (1000+ users), consider:
  - Caching group memberships in Redis
  - Async group resolution
  - Pagination for permission lists

## Future Improvements

### Phase 2 (Potential)
- [ ] Transfer ownership API
- [ ] Expiring permissions (time-limited access)
- [ ] Bulk permission operations
- [ ] Permission templates (e.g., "share with my team")
- [ ] Audit log viewer UI

### Phase 3 (Advanced)
- [ ] External sharing (outside workspace)
- [ ] Role-based access control (RBAC)
- [ ] Permission inheritance from profiles
- [ ] Notification system for shares
- [ ] Advanced analytics (who viewed what)

## Support

### Logs to Check
- Application logs: `logs/api.log`
- Permission checks: Look for "Permission check failed" or "Permission denied"
- User context: Look for "Set current user context"

### Database Queries

```sql
-- Check session ownership
SELECT session_id, created_by, visibility, title 
FROM user_sessions 
WHERE session_id = 'abc123';

-- Check permissions for a session
SELECT * FROM session_permissions 
WHERE session_id = (SELECT id FROM user_sessions WHERE session_id = 'abc123');

-- Find sessions shared with user
SELECT us.session_id, us.title, sp.permission
FROM user_sessions us
JOIN session_permissions sp ON us.id = sp.session_id
WHERE sp.principal_type = 'user' 
  AND sp.principal_id = 'user@company.com';
```

## Related Documentation

- [User Guide](./access-control.md)
- [Database Configuration](./technical/database-configuration.md)
- [Backend Overview](./technical/backend-overview.md)
- [Local Development](./local-development.md)
