-- Migration: Add polling support for async chat requests
-- This migration adds the chat_requests table and request_id column to session_messages
-- Required for SSE-to-polling migration to work around Databricks Apps 60s timeout
--
-- Run this migration on existing Lakebase instances via Databricks SQL Editor
-- or during app startup if using automatic migrations

-- Add chat_requests table
CREATE TABLE IF NOT EXISTS chat_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(64) UNIQUE NOT NULL,
    session_id INTEGER NOT NULL REFERENCES user_sessions(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    result_json TEXT
);

-- Create indexes for efficient lookups
CREATE INDEX IF NOT EXISTS ix_chat_requests_request_id ON chat_requests(request_id);
CREATE INDEX IF NOT EXISTS ix_chat_requests_session_id ON chat_requests(session_id);

-- Add request_id column to session_messages for linking messages to requests
ALTER TABLE session_messages ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_session_messages_request_id ON session_messages(request_id);

