# Duplicate Deck Feature Design

**Status:** Implemented (backend + session history UI)  
**Branch:** `feature/duplicate-slide`  
**Last Updated:** June 2026

## Summary

Allow any user with **CAN_VIEW** or higher on a deck to create an independent copy in their own **My Sessions** list. The copy is a snapshot of the source deck at duplicate time, with a fresh private chat session.

## Scope

### Copied

| Data | Notes |
|------|-------|
| `session_slide_decks` content | `html_content`, `scripts_content`, `deck_json`, `verification_map`, `slide_count` |
| `user_sessions.agent_config` | Genie `conversation_id` stripped |
| `user_sessions.title` | Default: `Copy of {source title}` |

### Not copied

| Data | Reason |
|------|--------|
| `session_messages` | Conversations are private per session |
| `slide_deck_versions` | Save-point history starts fresh on the copy |
| `deck_contributors` | Copy is private to the duplicator |
| `global_permission` | Workspace sharing not inherited |
| Contributor child sessions | Copy is a new root session |
| `genie_conversation_id`, `experiment_id`, Google Slides export IDs | Session-specific runtime state |

## Permission

- **Minimum:** `CAN_VIEW` on the source deck (via ownership, contributor grant, or workspace share).
- **Result:** New root session with `created_by` = current user and `CAN_MANAGE` implicit as creator.

## Contributor sessions

If duplicate is requested using a **contributor session** ID, resolve to the parent (deck owner) session before copying slide content. The new session is always a root session owned by the caller.

## API

```
POST /api/sessions/{session_id}/duplicate
Body: { "title": "optional" }
Response 201: {
  "session_id": "...",
  "title": "Copy of ...",
  "created_by": "...",
  "created_at": "...",
  "slide_count": N,
  "source_session_id": "..."
}
```

| Status | Condition |
|--------|-----------|
| 201 | Success |
| 400 | Source has no slide deck |
| 403 | No CAN_VIEW on source |
| 404 | Session not found |
| 500 | Unexpected error |

## Implementation

- `SessionManager.duplicate_session()` — core copy logic
- `sanitize_agent_config_for_persist()` — shared agent config sanitization
- `POST /api/sessions/{session_id}/duplicate` — HTTP entry point

## Out of scope (v1)

- In-deck duplicate action in `AppLayout`
- MCP `duplicate_deck` tool
- Copying save-point history

## References

- [Permissions Model](../../technical/permissions-model.md)
- [Duplicate Deck Test Suite](../../technical/duplicate-deck-tests.md)
