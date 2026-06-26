# Strip Comments Architecture

**Date:** 2026-04-01
**Approach:** Surgical deletion (Approach A)
**Goal:** Remove the entire comments, mentions, and notifications feature to address performance degradation introduced with PR #131 (permissions model).

## Context

Since PR #131 merged on 2026-03-23, app performance has seriously degraded. The comments architecture introduces per-session DB queries, polling, and API calls that contribute to connection exhaustion and slow loads. Rather than continuing to patch (PRs #160, #161, #162), we are removing the feature entirely.

## Constraints

- Leave `slide_comments` DB table orphaned — no migration, no data loss
- Clean removal with no stubs or placeholders
- Permissions model (sharing, contributors) stays intact — only comments/mentions/notifications go

## Scope

### Backend — Delete

| File | Reason |
|------|--------|
| `src/api/routes/comments.py` | All 8 comment/mention endpoints |
| `src/database/models/slide_comment.py` | SlideComment ORM model |

### Backend — Edit

| File | Change |
|------|--------|
| `src/api/main.py` | Remove `comments` import and router registration |
| `src/database/models/__init__.py` | Remove `SlideComment` import and `__all__` entry |
| `src/api/services/session_manager.py` | Remove ~300 lines of comment methods (lines ~1835-2146): `add_comment`, `list_comments`, `update_comment`, `delete_comment`, `resolve_comment`, `unresolve_comment`, `_comment_to_dict`, `list_mentions`, `get_mentionable_users` |
| `src/core/database.py` | Remove dead `slide_comments` migration block (lines ~465-476) that adds `mentions` column |

### Frontend — Delete

| File | Reason |
|------|--------|
| `frontend/src/components/SlidePanel/CommentThread.tsx` | Comment thread UI + mention input |
| `frontend/src/components/Notifications/NotificationsPanel.tsx` | Mentions notification panel (also delete empty `Notifications/` directory) |
| `frontend/src/types/comment.ts` | SlideComment TypeScript interface |

### Frontend — Edit

| File | Change |
|------|--------|
| `frontend/src/services/api.ts` | Remove 8 comment API methods (~lines 1355-1444) |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Remove comment count state, mention tracking state, fetch callbacks, comment-related props passed to SlideTile, and update locked-session banner text (line ~649) to remove "add comments, and mention users" |
| `frontend/src/components/SlidePanel/SlideTile.tsx` | Remove comment/mention props, badge rendering, CommentThread import/usage |
| `frontend/src/components/Layout/AppLayout.tsx` | Remove NotificationsPanel import, `'notifications'` view mode, notifications rendering |
| `frontend/src/components/Layout/app-sidebar.tsx` | Remove `'notifications'` from ViewMode type |
| `frontend/src/App.tsx` | Remove `/notifications` route |

### Tests — Edit

| File | Change |
|------|--------|
| `frontend/tests/e2e/slide-operations-ui.spec.ts` | Remove comment/mention API mocks |
| `frontend/tests/e2e/deck-integrity.spec.ts` | Remove comment/mention API mocks |
| `frontend/tests/e2e/history-ui.spec.ts` | Remove comment/mention API mocks |
| `frontend/tests/e2e/presentation-mode.spec.ts` | Remove comment/mention API mocks |
| `frontend/tests/e2e/export-ui.spec.ts` | Remove comment/mention API mocks |
| `frontend/tests/e2e/chat-ui.spec.ts` | Remove comment/mention API mocks (lines ~194-200) |
| `tests/unit/test_deck_permission_routes.py` | Remove comment endpoint permission tests |
| `tests/unit/test_security_permission_checks.py` | Remove comment route security tests |

## Implementation Order

Changes should land in this order to keep the build green at each step:

**Backend:**
1. Edit `session_manager.py` (remove comment methods)
2. Edit `models/__init__.py` (remove SlideComment import/export)
3. Delete `slide_comment.py`
4. Edit `main.py` (remove comments router)
5. Delete `comments.py`
6. Edit `database.py` (remove migration block)
7. Edit backend test files

**Frontend:**
1. Edit `SlidePanel.tsx` (remove comment/mention state, callbacks, props)
2. Edit `SlideTile.tsx` (remove comment/mention props, CommentThread import)
3. Edit `AppLayout.tsx` (remove NotificationsPanel import, rendering)
4. Edit `app-sidebar.tsx` (remove `'notifications'` from ViewMode)
5. Edit `App.tsx` (remove `/notifications` route)
6. Edit `api.ts` (remove 8 comment methods)
7. Delete `CommentThread.tsx`, `NotificationsPanel.tsx`, `comment.ts`, empty `Notifications/` dir
8. Edit E2E test files

### Documentation — Edit

| File | Change |
|------|--------|
| `docs/technical/permissions-model.md` | Strip all references to comments, mentions, SlideComment model, comment permission matrix, and comment API endpoints |

## What Stays

- `slide_comments` table in the database (orphaned, no migration)
- Permissions model (sharing, contributors, CAN_VIEW/CAN_EDIT/CAN_MANAGE)
- All non-comment functionality from PR #131 and subsequent PRs

## Verification

After removal:
1. Backend tests pass (`pytest`)
2. Frontend builds without errors (`npm run build`)
3. E2E tests pass (`npx playwright test`)
4. No remaining imports or references to deleted files
5. App loads without comment-related API calls in network tab
