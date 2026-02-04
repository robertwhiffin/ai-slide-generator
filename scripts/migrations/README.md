# Database Migrations

This directory contains SQL migration scripts for database schema changes.

## Available Migrations

### 001_add_session_permissions.sql

**Purpose**: Add ownership and access control to sessions

**Changes**:
- Adds `created_by` column to `user_sessions` (session owner)
- Adds `visibility` column to `user_sessions` (private/shared/workspace)
- Creates `session_permissions` table for ACLs
- Backfills `created_by` from existing `user_id` values

**Run with**:
```bash
python scripts/run_migration.py
```

## Running Migrations

### Dry Run (Preview)

```bash
python scripts/run_migration.py --dry-run
```

This prints the SQL that would be executed without making changes.

### Apply Migration

```bash
python scripts/run_migration.py
```

Applies the default migration (001_add_session_permissions.sql).

### Run Specific Migration

```bash
python scripts/run_migration.py --migration scripts/migrations/002_other_migration.sql
```

## Creating New Migrations

1. Create a new SQL file: `scripts/migrations/NNN_description.sql`
2. Write SQL statements (semicolon-separated)
3. Test with `--dry-run` first
4. Apply migration

### Template

```sql
-- Migration: [Description]
-- Purpose: [Why this change is needed]

-- Add columns
ALTER TABLE table_name 
ADD COLUMN new_column VARCHAR(255);

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_table_column 
ON table_name(new_column);

-- Add comments
COMMENT ON COLUMN table_name.new_column IS 'Description of column';
```

## Best Practices

1. **Always test with --dry-run first**
2. **Back up your database** before running migrations
3. **Use IF NOT EXISTS** for idempotent migrations
4. **Add indexes** for new foreign keys
5. **Document changes** with comments in the SQL
6. **Version migrations** with numbers (001, 002, etc.)

## Rollback

Migrations do not have automatic rollback. To rollback:

1. Write a reverse migration SQL file
2. Run manually or via migration script

Example rollback for 001:
```sql
-- Rollback migration 001
DROP TABLE IF EXISTS session_permissions;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS created_by;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS visibility;
```

## Troubleshooting

### Migration Failed

Check the error message and logs. Common issues:

- **Syntax error**: Fix SQL syntax
- **Column already exists**: Use `IF NOT EXISTS` clause
- **Foreign key violation**: Check data consistency

### Partial Migration

If migration fails partway:

1. Check which statements succeeded
2. Comment out completed statements
3. Fix the failing statement
4. Re-run migration

## Environment

Migrations run against the database configured in your environment:

- **Local**: Uses `DATABASE_URL` env var or default PostgreSQL
- **Production**: Uses Lakebase connection from `PGHOST`/`PGUSER`

Make sure to run migrations in the correct environment!
