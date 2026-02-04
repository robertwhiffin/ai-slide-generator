# 🔐 Access Control Setup - Quick Start

This guide will help you enable the new access control system for tellr.

## What's New

You now have **complete ownership and permission control** for presentations:

✅ **Session Ownership** - Every presentation has an owner  
✅ **Fine-grained Permissions** - Grant read/edit access to specific users or groups  
✅ **Visibility Levels** - Make presentations private, shared, or workspace-wide  
✅ **Databricks Integration** - Uses your workspace users and groups  
✅ **Security Inheritance** - Respects Unity Catalog permissions via user tokens  

## Quick Start (5 Minutes)

### Step 1: Run the Database Migration

```bash
# Preview what will change (safe, no modifications)
python scripts/run_migration.py --dry-run

# Apply the migration
python scripts/run_migration.py
```

**What this does:**
- Adds `created_by` (owner) and `visibility` columns to sessions
- Creates `session_permissions` table for ACLs
- Backfills owner from existing `user_id` values

### Step 2: Restart Your Application

```bash
# Local development
./stop_start_app.sh

# Or manually
uvicorn src.api.main:app --reload --port 8000
```

### Step 3: Test It Out

```bash
# 1. Create a session (automatically owned by you)
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "My First Presentation"}'

# Response includes your ownership:
# {
#   "session_id": "abc123...",
#   "created_by": "you@company.com",   <-- You're the owner!
#   "visibility": "private"
# }

# 2. List sessions (see only what you can access)
curl http://localhost:8000/api/sessions

# 3. Grant permission to a colleague
curl -X POST http://localhost:8000/api/sessions/abc123/permissions \
  -H "Content-Type: application/json" \
  -d '{
    "principal_type": "user",
    "principal_id": "colleague@company.com",
    "permission": "read"
  }'
```

Done! You now have access control enabled.

## Key Concepts (1 Minute Read)

### Ownership
- You own sessions you create
- Owners can do anything: view, edit, delete, share

### Permissions
- **Read**: View sessions and slides
- **Edit**: Modify sessions, rename, update slides

### Visibility
- **Private** (default): Only you can access
- **Shared**: You + people you explicitly grant access
- **Workspace**: All workspace users can view (read-only unless granted edit)

### Sharing
Grant access to:
- **Individual users**: `user@company.com`
- **Databricks groups**: `data-analysts`, `engineering-team`

## Common Tasks

### Share with a Colleague

```bash
POST /api/sessions/{session_id}/permissions
{
  "principal_type": "user",
  "principal_id": "colleague@company.com",
  "permission": "read"
}
```

### Share with a Team

```bash
POST /api/sessions/{session_id}/permissions
{
  "principal_type": "group",
  "principal_id": "data-team",
  "permission": "edit"
}
```

### Make Workspace-Wide

```bash
PATCH /api/sessions/{session_id}/permissions/visibility
{
  "visibility": "workspace"
}
```

### Revoke Access

```bash
DELETE /api/sessions/{session_id}/permissions
{
  "principal_type": "user",
  "principal_id": "colleague@company.com"
}
```

### List Who Has Access

```bash
GET /api/sessions/{session_id}/permissions
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  USER (you@company.com)                                     │
│  - Databricks Apps forwards your token                     │
│  - Your Unity Catalog permissions apply                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  MIDDLEWARE                                                  │
│  - Extracts your identity from token                        │
│  - Sets current user context                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  PERMISSION CHECKS                                           │
│  1. Are you the owner? → Full access                        │
│  2. Do you have explicit grant? → Check level               │
│  3. Are you in a granted group? → Check level               │
│  4. Is visibility workspace? → Read access                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  DATABASE                                                    │
│  - user_sessions: created_by, visibility                    │
│  - session_permissions: ACL entries                         │
└─────────────────────────────────────────────────────────────┘
```

## Files Added

```
src/
├── core/user_context.py              # User context management
├── database/models/permissions.py    # Permission models
├── services/permission_service.py    # Permission logic
└── api/routes/permissions.py         # Permission API

scripts/
├── migrations/
│   └── 001_add_session_permissions.sql
└── run_migration.py

docs/
├── access-control.md                 # Detailed user guide
└── access-control-implementation.md  # Technical implementation details
```

## Files Modified

```
src/
├── database/models/session.py        # Added created_by, visibility
├── api/main.py                       # Enhanced middleware
└── api/services/session_manager.py  # Permission enforcement
```

## Backward Compatibility

✅ **Existing sessions work**: Migration backfills owner from `user_id`  
✅ **Old API calls work**: No breaking changes to request/response formats  
⚠️ **One change**: `GET /api/sessions` now filters by permission (was: all sessions)

## Security Model

**How it works:**

1. Databricks Apps forwards **your token** to tellr
2. tellr uses **your token** to query Genie
3. Genie uses **your token** to access Unity Catalog
4. You see only data **you** have permission to access

**This means:**
- Your presentations respect **your** data permissions
- When you share a presentation, the viewer uses **their own** token
- Viewers see only data **they** have access to
- Unity Catalog permissions are always enforced

**Example:**
```
You: Can access sales_data, NOT hr_data
Colleague: Can access hr_data, NOT sales_data

1. You create presentation with sales_data → Works ✓
2. You share with colleague
3. Colleague views presentation
   - Sees sales_data slides (they query UC with THEIR token)
   - Gets access denied if they lack permissions
```

## Troubleshooting

### "Permission denied" on my own session

**Cause**: Session doesn't have `created_by` set

**Fix**:
```sql
UPDATE user_sessions 
SET created_by = 'you@company.com'
WHERE session_id = 'abc123' AND created_by IS NULL;
```

### Group permissions not working

**Verify**:
1. User is in the Databricks group
2. Group name matches exactly (case-sensitive)
3. Check logs for group resolution errors

### Can't see any sessions

**Cause**: Permission filtering is working correctly - you don't own any sessions

**Fix**: Create a new session or have someone share one with you

## Next Steps

1. ✅ Run migration
2. ✅ Restart application
3. ✅ Test basic functionality
4. 📖 Read [docs/access-control.md](docs/access-control.md) for detailed API reference
5. 🔧 Update frontend to show owner/sharing controls (if applicable)
6. 📊 Monitor logs for permission errors

## Documentation

- **[docs/access-control.md](docs/access-control.md)** - Complete API reference and examples
- **[docs/access-control-implementation.md](docs/access-control-implementation.md)** - Technical details
- **[scripts/migrations/README.md](scripts/migrations/README.md)** - Migration guide

## Questions?

1. Check the error message and logs
2. Review [docs/access-control.md](docs/access-control.md) troubleshooting section
3. Verify database migration completed successfully
4. Check that user identity is being detected (logs: "Set current user context")

## Summary

You now have:
- ✅ **Ownership tracking** for all presentations
- ✅ **Permission-based access control** (read/edit)
- ✅ **User and group sharing** via Databricks workspace
- ✅ **Visibility levels** (private/shared/workspace)
- ✅ **Unity Catalog integration** (inherit data permissions)
- ✅ **Complete API** for managing permissions

**Ready to use!** 🎉
