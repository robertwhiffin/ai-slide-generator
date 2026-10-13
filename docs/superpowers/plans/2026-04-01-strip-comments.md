# Strip Comments Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the entire comments, mentions, and notifications feature to fix performance degradation.

**Architecture:** Surgical deletion of 5 dedicated files and editing ~14 mixed files. No database migration — the `slide_comments` table stays orphaned. The permissions model (sharing, contributors) is untouched.

**Spec:** `docs/superpowers/specs/2026-04-01-strip-comments-design.md`

---

### Task 1: Remove comment methods from session_manager.py

**Files:**
- Modify: `src/api/services/session_manager.py:1831-2145`

- [ ] **Step 1: Delete the Slide Comments section**

Remove the entire block from line 1831 (the `# === Slide Comments ===` header) through line 2145 (end of `_get_session_id_str`). This removes these methods:
- `add_comment`
- `list_comments`
- `update_comment`
- `delete_comment`
- `resolve_comment`
- `unresolve_comment`
- `_comment_to_dict`
- `list_mentions`
- `get_mentionable_users`
- `_get_session_id_str`

The line after the deletion (`# Global session manager instance`) should follow directly after the `_get_session_or_raise` method that ends at line 1829.

- [ ] **Step 2: Remove SlideComment import if present**

Check for and remove any `from src.database.models.slide_comment import SlideComment` import at the top of the file.

- [ ] **Step 3: Verify no remaining comment references**

Run: `grep -n "comment\|SlideComment\|mention" src/api/services/session_manager.py`
Expected: No matches (or only unrelated uses of the word)

- [ ] **Step 4: Commit**

```bash
git add src/api/services/session_manager.py
git commit -m "refactor: remove comment methods from session_manager"
```

---

### Task 2: Remove backend comment tests and comments route

> **Important:** This task removes tests that import from `comments.py` AND the route file + registration in a single commit, avoiding broken intermediate states where test imports would fail.

**Files:**
- Modify: `tests/unit/test_deck_permission_routes.py:383-424`
- Modify: `tests/unit/test_security_permission_checks.py:374-479`
- Delete: `src/api/routes/comments.py`
- Modify: `src/api/main.py:19,345`

- [ ] **Step 1: Remove TestMentionableUsers from test_deck_permission_routes.py**

Delete the entire `TestMentionableUsers` class (lines 383-424, both methods: `test_returns_deck_contributors` and `test_no_profile_dependency`).

- [ ] **Step 2: Remove comment test classes from test_security_permission_checks.py**

Delete these 4 classes:
- `TestListCommentsPermission` (lines 374-405)
- `TestAddCommentPermission` (lines 407-429)
- `TestMentionableUsersPermission` (lines 432-448)
- `TestListMentionsPermission` (lines 451-479)

- [ ] **Step 3: Edit main.py line 19 — remove comments from import**

Change:
```python
from src.api.routes import admin, agent_config, chat, comments, export, feedback, images, profiles, sessions, slides, tools, verification, version, google_slides, setup, local_version
```
To:
```python
from src.api.routes import admin, agent_config, chat, export, feedback, images, profiles, sessions, slides, tools, verification, version, google_slides, setup, local_version
```

- [ ] **Step 4: Edit main.py line 345 — remove router registration**

Delete:
```python
app.include_router(comments.router)
```

- [ ] **Step 5: Delete the route file**

Delete: `src/api/routes/comments.py`

- [ ] **Step 6: Run backend tests**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass, no import errors.

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/comments.py src/api/main.py tests/unit/test_deck_permission_routes.py tests/unit/test_security_permission_checks.py
git commit -m "refactor: remove comments route, registration, and related tests"
```

---

### Task 3: Remove SlideComment model and migration block

**Files:**
- Delete: `src/database/models/slide_comment.py`
- Modify: `src/database/models/__init__.py:27,51`
- Modify: `src/core/database.py:465-476`

- [ ] **Step 1: Edit models/__init__.py**

Remove line 27:
```python
from src.database.models.slide_comment import SlideComment
```

Remove `"SlideComment",` from the `__all__` list (line 51).

- [ ] **Step 2: Delete the model file**

Delete: `src/database/models/slide_comment.py`

- [ ] **Step 3: Remove dead migration block from database.py**

Remove lines 465-476 in `src/core/database.py`:
```python
        # --- slide_comments: add mentions column ---
        comments_table = "slide_comments"
        try:
            comment_cols = {c["name"] for c in inspector.get_columns(comments_table, schema=schema)}
        except Exception:
            comment_cols = set()
        if comment_cols and "mentions" not in comment_cols:
            logger.info(f"Migration: adding mentions column to {comments_table}")
            col_type = "TEXT" if is_sqlite else "JSON"
            conn.execute(text(
                f"ALTER TABLE {_qual(comments_table)} ADD COLUMN mentions {col_type} NULL"
            ))
```

- [ ] **Step 4: Verify backend starts**

Run: `python -c "from src.api.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Verify no remaining references**

Run: `grep -rn "SlideComment\|slide_comment" src/`
Expected: No matches.

- [ ] **Step 6: Commit**

```bash
git add src/database/models/slide_comment.py src/database/models/__init__.py src/core/database.py
git commit -m "refactor: remove SlideComment model and migration block"
```

---

### Task 4: Remove comment state and props from SlidePanel.tsx

**Files:**
- Modify: `frontend/src/components/SlidePanel/SlidePanel.tsx`

- [ ] **Step 1: Remove comment/mention constants (lines 54-55)**

Delete:
```typescript
const EMPTY_MENTIONS: Array<{ id: number; user_name: string; content: string; created_at: string }> = [];
const EPOCH_ISO = new Date(0).toISOString();
```

- [ ] **Step 2: Remove comment counts state and refresh (lines 73-89)**

Delete the entire block:
```typescript
  // Batch comment counts per slide (single request instead of N+1)
  const [commentCountsBySlide, setCommentCountsBySlide] = useState<Record<string, number>>({});

  const refreshCommentCounts = useCallback(() => {
    ...
  }, [sessionId]);

  useEffect(() => {
    refreshCommentCounts();
  }, [refreshCommentCounts]);
```

- [ ] **Step 3: Remove mentions state and fetching (lines 91-123)**

Delete the entire block covering:
- `mentionsBySlide` state
- `mentionsLastSeenMap` state with localStorage
- `fetchMentions` callback
- `fetchMentions` useEffect
- `handleMarkMentionsSeen` callback

- [ ] **Step 4: Remove comment/mention props passed to SlideTile (lines 687-692)**

Delete these props from the `<SlideTile>` JSX:
```tsx
              commentCount={commentCountsBySlide[slide.slide_id] ?? 0}
              onCommentCountRefresh={refreshCommentCounts}
              mentions={mentionsBySlide[slide.slide_id] ?? EMPTY_MENTIONS}
              mentionsLastSeen={mentionsLastSeenMap[slide.slide_id] ?? EPOCH_ISO}
              onMarkMentionsSeen={() => handleMarkMentionsSeen(slide.slide_id)}
              onMentionsRefresh={fetchMentions}
```

- [ ] **Step 5: Update locked-session banner text (line 649)**

Change:
```
You can view slides, add comments, and mention users but cannot edit slides.
```
To:
```
You can view slides but cannot edit them.
```

- [ ] **Step 6: Remove unused imports**

Remove `api` import if it's now unused (was only used for comment fetching). Check for unused `useState`, `useCallback`, `useEffect` imports — only remove if no other usage exists.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/SlidePanel/SlidePanel.tsx
git commit -m "refactor: remove comment state and props from SlidePanel"
```

---

### Task 5: Strip comments from SlideTile.tsx

**Files:**
- Modify: `frontend/src/components/SlidePanel/SlideTile.tsx`

- [ ] **Step 1: Remove CommentThread import (line 10)**

Delete:
```typescript
import { CommentThread } from './CommentThread';
```

- [ ] **Step 2: Remove unused icon imports (line 4)**

Remove `Bell` and `MessageCircle` from the lucide-react import. Keep all other icons.

- [ ] **Step 3: Remove comment/mention props (lines 41-47)**

Delete from the props interface:
```typescript
  mentions?: Array<{ id: number; user_name: string; content: string; created_at: string }>;
  mentionsLastSeen?: string;
  onMarkMentionsSeen?: () => void;
  onMentionsRefresh?: () => void;
  commentCount: number;
  onCommentCountRefresh?: () => void;
  canManage?: boolean;
```

- [ ] **Step 4: Remove comment/mention state (lines 75-78)**

Delete:
```typescript
  const [showComments, setShowComments] = useState(false);
  const [showMentions, setShowMentions] = useState(false);
  const [scrollToCommentId, setScrollToCommentId] = useState<number | null>(null);
  const mentionsRef = useRef<HTMLDivElement>(null);
```

- [ ] **Step 5: Remove close-mentions-dropdown effect (lines 93-103)**

Delete the entire `useEffect` for closing mentions dropdown on outside click.

- [ ] **Step 6: Remove handleCommentChange callback (lines 105-108)**

Delete:
```typescript
  const handleCommentChange = useCallback((_count: number, hasMentions: boolean) => {
    onCommentCountRefresh?.();
    if (hasMentions) onMentionsRefresh?.();
  }, [onCommentCountRefresh, onMentionsRefresh]);
```

- [ ] **Step 7: Remove mentions calculation (lines 239-241)**

Delete:
```typescript
  const unreadCount = mentions.filter(m => m.created_at > mentionsLastSeen).length;
  const hasUnread = unreadCount > 0;
  const hasMentions = mentions.length > 0;
```

- [ ] **Step 8: Remove mentions notification bell UI (lines 281-342)**

Delete the entire `{/* Mentions notification bell */}` block including the dropdown.

- [ ] **Step 9: Remove comments toggle button (lines 345-364)**

Delete the entire `{/* Comments toggle */}` block.

- [ ] **Step 10: Remove CommentThread rendering (lines 478-487)**

Delete:
```tsx
      {/* Comments Panel */}
      {showComments && (
        <CommentThread
          sessionId={sessionId}
          slideId={slide.slide_id}
          onCommentChange={handleCommentChange}
          highlightCommentId={scrollToCommentId}
          canManage={canManage}
        />
      )}
```

- [ ] **Step 11: Clean up unused imports**

Remove `useRef` if no longer used. Check `useState`, `useCallback`, `useEffect` — only remove if no other usage.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/components/SlidePanel/SlideTile.tsx
git commit -m "refactor: strip comment UI from SlideTile"
```

---

### Task 6: Remove notifications from layout and routing

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx:13,37,603,769-780`
- Modify: `frontend/src/components/Layout/app-sidebar.tsx:25`
- Modify: `frontend/src/App.tsx:29`

- [ ] **Step 1: Edit AppLayout.tsx — remove NotificationsPanel import (line 13)**

Delete:
```typescript
import { NotificationsPanel } from '../Notifications/NotificationsPanel';
```

- [ ] **Step 2: Edit AppLayout.tsx — remove 'notifications' from ViewMode (line 37)**

Change:
```typescript
type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'notifications' | 'help';
```
To:
```typescript
type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'help';
```

- [ ] **Step 3: Edit AppLayout.tsx — remove notifications navigation (line 603)**

Delete:
```typescript
      else if (view === 'notifications') navigate('/notifications');
```

- [ ] **Step 4: Edit AppLayout.tsx — remove notifications view rendering (lines 769-780)**

Delete the entire block:
```tsx
        {viewMode === 'notifications' && (
          <div className="flex h-full flex-col">
            ...
                <NotificationsPanel />
            ...
          </div>
        )}
```

- [ ] **Step 5: Edit app-sidebar.tsx — remove 'notifications' from ViewMode (line 25)**

Change:
```typescript
type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'notifications' | 'help'
```
To:
```typescript
type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'help'
```

- [ ] **Step 6: Edit App.tsx — remove /notifications route (line 29)**

Delete:
```tsx
      <Route path="/notifications" element={<AppLayout key={layoutKey} initialView="notifications" />} />
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Layout/AppLayout.tsx frontend/src/components/Layout/app-sidebar.tsx frontend/src/App.tsx
git commit -m "refactor: remove notifications from layout and routing"
```

---

### Task 7: Remove comment API methods and delete dedicated frontend files

**Files:**
- Modify: `frontend/src/services/api.ts:5,1355-1446`
- Delete: `frontend/src/components/SlidePanel/CommentThread.tsx`
- Delete: `frontend/src/components/Notifications/NotificationsPanel.tsx`
- Delete: `frontend/src/components/Notifications/` (directory)
- Delete: `frontend/src/types/comment.ts`

- [ ] **Step 1: Edit api.ts — remove SlideComment import (line 5)**

Delete:
```typescript
import type { SlideComment } from '../types/comment';
```

- [ ] **Step 2: Edit api.ts — remove Comments API section (lines 1355-1446)**

Delete the entire block from `// ============ Comments API ============` through the `unresolveComment` method. The line before (`},` closing a previous method) and the line after (`// --- Feedback ---`) should remain.

- [ ] **Step 3: Delete dedicated frontend files**

```bash
rm frontend/src/components/SlidePanel/CommentThread.tsx
rm frontend/src/components/Notifications/NotificationsPanel.tsx
rmdir frontend/src/components/Notifications
rm frontend/src/types/comment.ts
```

- [ ] **Step 4: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor: remove comment API methods and dedicated comment files"
```

---

### Task 8: Remove comment mocks from E2E tests

**Files:**
- Modify: `frontend/tests/e2e/slide-operations-ui.spec.ts` (lines ~96-110)
- Modify: `frontend/tests/e2e/deck-integrity.spec.ts` (lines ~175-188)
- Modify: `frontend/tests/e2e/history-ui.spec.ts` (lines ~34-50)
- Modify: `frontend/tests/e2e/presentation-mode.spec.ts` (lines ~19-51)
- Modify: `frontend/tests/e2e/export-ui.spec.ts` (lines ~69-82)
- Modify: `frontend/tests/e2e/chat-ui.spec.ts` (lines ~193-206)

- [ ] **Step 1: Remove comment API mocks from each E2E test file**

In each file, delete all `page.route` calls that mock these patterns:
- `**/api/comments/mentions**`
- `**/api/comments/mentionable-users**`
- `/\/api\/comments\?session_id=/`

Keep all non-comment mocks (e.g. `**/api/user/current`, lock endpoints) in place.

- [ ] **Step 2: Run E2E tests**

Run: `cd frontend && npx playwright test`
Expected: All tests pass — the app no longer makes comment API calls so the mocks are unnecessary.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/
git commit -m "test: remove comment API mocks from E2E tests"
```

---

### Task 9: Update permissions documentation

**Files:**
- Modify: `docs/technical/permissions-model.md`

- [ ] **Step 1: Remove comment rows from Deck Permissions table**

Delete these rows (lines ~45-47, 51-52):
- "Add comments / @mentions"
- "Edit own comments"
- "Delete own comments"
- "Delete any comment"
- "Resolve / unresolve comments"

- [ ] **Step 2: Remove comment note under permissions table (line ~56)**

Delete: `> **Note:** "Delete any comment" is CAN_MANAGE only...`

- [ ] **Step 3: Remove comment capabilities from Exclusive Editing Lock section (lines ~184-185)**

Delete:
- "- Add comments and replies"
- "- @mention other users"

- [ ] **Step 4: Remove SlideComment from Database Schema section (lines ~283-304)**

Delete the entire `SlideComment` subsection.

- [ ] **Step 5: Remove Comments & Mentions from API Endpoints section (lines ~449-462)**

Delete the entire "Comments & Mentions" subsection.

- [ ] **Step 6: Remove mentions polling row (line ~518)**

Delete the row: `Mentions (per-slide bell) | 3 seconds | ...`

- [ ] **Step 7: Commit**

```bash
git add docs/technical/permissions-model.md
git commit -m "docs: remove comment references from permissions model"
```

---

### Task 10: Final verification

- [ ] **Step 1: Search for any remaining comment references**

```bash
grep -rn "SlideComment\|CommentThread\|NotificationsPanel\|comment_to_dict\|listComments\|addComment\|deleteComment\|resolveComment\|unresolveComment\|listMentions\|getMentionableUsers\|mentionable.users\|/api/comments" src/ frontend/src/ tests/
```
Expected: No matches (or only comments in natural language, not code references).

- [ ] **Step 2: Run full backend test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Run E2E tests**

Run: `cd frontend && npx playwright test`
Expected: All tests pass.

- [ ] **Step 5: Verify no comment API calls at runtime**

Start the app and open browser dev tools Network tab. Load a session with slides. Confirm no requests to `/api/comments/*` endpoints.
