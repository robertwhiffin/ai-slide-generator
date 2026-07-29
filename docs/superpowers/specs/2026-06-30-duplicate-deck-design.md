# Duplicate Deck Feature Design

**Status:** Implemented  
**Branch:** `feature/duplicate-slide`  
**Last Updated:** July 2026

## Summary

Allow any user with **CAN_VIEW** or higher on a deck to create an independent copy in their own **My Sessions** list. The copy is a snapshot of the source deck at duplicate time (live deck or a specific save point when previewing), with a fresh private chat session.

## Scope

### Copied

| Data | Notes |
|------|-------|
| `session_slide_decks` content | `html_content`, `scripts_content`, `deck_json`, `verification_map`, `slide_count` |
| `user_sessions.agent_config` | Genie `conversation_id` stripped via `sanitize_agent_config_for_persist()` |
| `user_sessions.title` | Default: `Copy of {source title}` (truncated to 255 chars) |

When `version_number` is supplied, slide content is taken from that **save point** snapshot instead of the live deck.

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

### Duplicate deck

```
POST /api/sessions/{session_id}/duplicate
Body: {
  "title": "optional",
  "version_number": optional save point to copy (default: live deck)
}
Response 201: {
  "session_id": "...",
  "title": "Copy of ...",
  "created_by": "...",
  "created_at": "...",
  "slide_count": N,
  "source_session_id": "...",
  "source_version_number": optional
}
```

| Status | Condition |
|--------|-----------|
| 201 | Success |
| 400 | Source has no slide deck, or save point not found |
| 403 | No CAN_VIEW on source |
| 404 | Session not found |
| 500 | Unexpected error |

### List sessions (sidebar support)

```
GET /api/sessions?limit=10&deck_only=true
```

When `deck_only=true`, returns only root sessions that have a slide deck (ordered by `last_activity`). Used by the **Recent Decks** sidebar so chat-only sessions do not crowd out decks.

## UI entry points

| Location | Behavior |
|----------|----------|
| **My Sessions** (`SessionHistory`) | Duplicate → opens new copy |
| **Shared with Me** (`SessionHistory`) | Duplicate → switches to My Sessions and opens new copy |
| **Deck editor** (`AppLayout` / `PageHeader`) | Duplicate → navigates to new copy |
| **Save-point preview** (editor) | Duplicates the **previewed** save point; confirm dialog if preview is older than latest save point |
| **Recent Decks sidebar** (`DeckHistory`) | Lists 10 most recent decks via `deck_only=true` (no duplicate action) |

## Implementation

- `SessionManager.duplicate_session()` — core copy logic (live deck or save point)
- `sanitize_agent_config_for_persist()` — shared agent config sanitization
- `SessionManager.list_sessions(deck_only=True)` — deck-only session listing
- `POST /api/sessions/{session_id}/duplicate` — HTTP entry point

## Out of scope (future)

- MCP `duplicate_deck` tool
- Copying save-point history onto the new session
- Version picker modal (v1 duplicates what you are viewing; confirm only when previewing an older save point)

## References

- [Permissions Model](../../technical/permissions-model.md)
- [Duplicate Deck Test Suite](../../technical/duplicate-deck-tests.md)
