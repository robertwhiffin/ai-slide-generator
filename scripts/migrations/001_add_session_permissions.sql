-- Migration: Add session ownership and permissions
-- Purpose: Implement ACL-based access control for sessions

-- 1. Add owner tracking to existing sessions table
ALTER TABLE user_sessions 
ADD COLUMN IF NOT EXISTS created_by VARCHAR(255);

-- Add index for querying by owner
CREATE INDEX IF NOT EXISTS ix_user_sessions_created_by 
ON user_sessions(created_by);

-- 2. Create session permissions table for fine-grained ACLs
CREATE TABLE IF NOT EXISTS session_permissions (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL,
    
    -- Subject (who has access)
    principal_type VARCHAR(20) NOT NULL, -- 'user' or 'group'
    principal_id VARCHAR(255) NOT NULL,  -- email for users, group name for groups
    
    -- Permission level
    permission VARCHAR(20) NOT NULL,     -- 'read' or 'edit'
    
    -- Metadata
    granted_by VARCHAR(255) NOT NULL,    -- who granted this permission
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key
    CONSTRAINT fk_session_permissions_session 
        FOREIGN KEY (session_id) 
        REFERENCES user_sessions(id) 
        ON DELETE CASCADE,
    
    -- Ensure unique permission per principal per session
    CONSTRAINT uq_session_principal 
        UNIQUE (session_id, principal_type, principal_id)
);

-- Indexes for fast permission lookups
CREATE INDEX IF NOT EXISTS ix_session_permissions_session 
ON session_permissions(session_id);

CREATE INDEX IF NOT EXISTS ix_session_permissions_principal 
ON session_permissions(principal_type, principal_id);

-- 3. Add visibility column for list filtering
ALTER TABLE user_sessions 
ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private';
-- Possible values: 'private' (owner only), 'shared' (explicit grants), 'workspace' (all users)

-- 4. Backfill created_by from user_id for existing sessions
UPDATE user_sessions 
SET created_by = user_id 
WHERE created_by IS NULL AND user_id IS NOT NULL;

COMMENT ON TABLE session_permissions IS 'Access control list for session sharing and collaboration';
COMMENT ON COLUMN session_permissions.principal_type IS 'Type of principal: user (email) or group (Databricks group)';
COMMENT ON COLUMN session_permissions.permission IS 'Permission level: read (view only) or edit (modify/delete)';
COMMENT ON COLUMN user_sessions.visibility IS 'Session visibility: private, shared, or workspace';
