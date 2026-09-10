# Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce idle API request volume by ~90% and eliminate redundant Databricks API calls from route handlers to make the app responsive on Databricks Apps (4 vCPU).

**Architecture:** Frontend polling intervals are the primary bottleneck (~300 requests/minute idle with 15 slides). We reduce polling frequency, add a batch comment-counts endpoint to collapse N per-slide requests into 1, and replace 8 redundant `current_user.me()` API calls in route handlers with the existing request-scoped `get_current_user()` context variable that the middleware already populates.

**Tech Stack:** FastAPI (Python), React/TypeScript, SQLAlchemy, pytest

---

## File Structure

### Backend (new/modified)
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/api/routes/comments.py` | Add `GET /api/comments/counts` batch endpoint |
| Modify | `src/api/routes/images.py` | Replace `_get_current_user()` with context var |
| Modify | `src/api/routes/google_slides.py` | Replace `_get_user_identity()` with context var |
| Modify | `src/api/routes/settings/deck_prompts.py` | Replace 3× `current_user.me()` with context var |
| Modify | `src/api/routes/settings/slide_styles.py` | Replace 3× `current_user.me()` with context var |
| Create | `tests/unit/test_comment_counts.py` | Tests for batch comment-counts endpoint |
| Create | `tests/unit/test_redundant_user_calls.py` | Tests verifying no extra `.me()` calls |

### Frontend (modified)
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `frontend/src/services/api.ts` | Add `getCommentCounts()` method |
| Modify | `frontend/src/components/SlidePanel/SlideTile.tsx` | Remove per-slide polling, accept count as prop |
| Modify | `frontend/src/components/SlidePanel/SlidePanel.tsx` | Batch-fetch comment counts, pass to SlideTiles; reduce mentions polling to 30s |
| Modify | `frontend/src/components/Notifications/NotificationBell.tsx` | Reduce polling to 30s |
| Modify | `frontend/src/components/Layout/AppLayout.tsx` | Reduce lock polling to 30s |
| Modify | `frontend/src/components/History/SessionHistory.tsx` | Reduce polling to 60s |

---

## Task 1: Batch Comment-Counts Backend Endpoint

**Files:**
- Create: `tests/unit/test_comment_counts.py`
- Modify: `src/api/routes/comments.py` (add new route before the `GET ""` at line 183)

This collapses N per-slide comment requests into 1 per deck.

- [ ] **Step 1: Write failing test for batch comment counts**

```python
# tests/unit/test_comment_counts.py
"""Tests for GET /api/comments/counts batch endpoint."""

import os
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_permissions():
    """Skip permission checks for unit tests."""
    with patch("src.api.routes.comments._require_deck_view_for_session"):
        yield


@pytest.fixture
def mock_session_manager():
    """Mock session manager with comment count data."""
    manager = MagicMock()
    manager.list_comments.return_value = [
        {"id": 1, "slide_id": "slide-1", "content": "hello", "resolved_at": None},
        {"id": 2, "slide_id": "slide-1", "content": "world", "resolved_at": None},
        {"id": 3, "slide_id": "slide-2", "content": "test", "resolved_at": None},
    ]
    with patch("src.api.routes.comments.get_session_manager", return_value=manager):
        yield manager


def test_comment_counts_returns_per_slide_counts(client, mock_permissions, mock_session_manager):
    """GET /api/comments/counts returns count per slide_id."""
    response = client.get("/api/comments/counts?session_id=test-session")
    assert response.status_code == 200
    data = response.json()
    assert data["counts"]["slide-1"] == 2
    assert data["counts"]["slide-2"] == 1


def test_comment_counts_requires_session_id(client, mock_permissions):
    """GET /api/comments/counts requires session_id parameter."""
    response = client.get("/api/comments/counts")
    assert response.status_code == 422


def test_comment_counts_empty_session(client, mock_permissions, mock_session_manager):
    """Returns empty counts for session with no comments."""
    mock_session_manager.list_comments.return_value = []
    response = client.get("/api/comments/counts?session_id=test-session")
    assert response.status_code == 200
    assert response.json()["counts"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_comment_counts.py -v`
Expected: FAIL — 404 because `/api/comments/counts` doesn't exist yet

- [ ] **Step 3: Implement batch comment-counts endpoint**

Add this endpoint to `src/api/routes/comments.py` **before** the existing `GET ""` route (line 183) so FastAPI matches `/counts` before the parameterless `GET ""`:

```python
@router.get("/counts")
async def comment_counts(
    session_id: str = Query(..., description="Session ID"),
):
    """Return comment counts per slide for a session.

    Used by the frontend to batch-fetch counts instead of polling per-slide.
    Only counts unresolved top-level comments.
    """
    await asyncio.to_thread(_require_deck_view_for_session, session_id)

    session_manager = get_session_manager()
    try:
        comments = await asyncio.to_thread(
            session_manager.list_comments,
            session_id,
            slide_id=None,
            include_resolved=False,
        )
        counts: dict[str, int] = {}
        for c in comments:
            sid = c.get("slide_id", "")
            if sid:
                counts[sid] = counts.get(sid, 0) + 1
        return {"counts": counts}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to get comment counts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_comment_counts.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_comment_counts.py src/api/routes/comments.py
git commit -m "feat: add batch comment-counts endpoint to reduce per-slide polling"
```

---

## Task 2: Frontend — Batch Comment Counts + Remove Per-Slide Polling

**Files:**
- Modify: `frontend/src/services/api.ts` (add `getCommentCounts` method)
- Modify: `frontend/src/components/SlidePanel/SlideTile.tsx` (remove polling, accept count as prop)
- Modify: `frontend/src/components/SlidePanel/SlidePanel.tsx` (batch-fetch counts, pass to tiles, reduce mentions polling)

This is the highest-impact change — eliminates ~200 requests/minute for a 10-slide deck.

- [ ] **Step 1: Add `getCommentCounts` to api.ts**

In `frontend/src/services/api.ts`, add near the existing `listComments` method (around line 1372):

```typescript
async getCommentCounts(sessionId: string): Promise<{ counts: Record<string, number> }> {
  const response = await fetch(`${API_BASE_URL}/api/comments/counts?session_id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new ApiError(response.status, 'Failed to get comment counts');
  return response.json();
},
```

- [ ] **Step 2: Modify SlideTile to accept commentCount as prop and onCommentCountChange callback**

In `frontend/src/components/SlidePanel/SlideTile.tsx`:

a) Add two new props to the component props interface:
```typescript
commentCount?: number;
onCommentCountChange?: (slideId: string, count: number) => void;
```

b) Remove the entire `useEffect` block that polls for comment counts (lines ~102-114 — the one with `setInterval(fetchCount, 3_000)`).

c) Remove the `commentCount` local state (`useState<number | null>(null)` at line 75) since it now comes from props.

d) Update `handleCommentChange` (line ~116) to propagate count changes upward instead of setting local state:
```typescript
const handleCommentChange = useCallback((count: number, hasMentions: boolean) => {
  onCommentCountChange?.(slide.slide_id, count);
  if (hasMentions) onMentionsRefresh?.();
}, [onMentionsRefresh, onCommentCountChange, slide.slide_id]);
```

e) Use `(commentCount ?? 0)` wherever the old local `commentCount` state was referenced (e.g., badge display).

- [ ] **Step 3: Modify SlidePanel to batch-fetch comment counts and distribute to SlideTiles**

In `frontend/src/components/SlidePanel/SlidePanel.tsx`:

a) Add state for comment counts:
```typescript
const [commentCounts, setCommentCounts] = useState<Record<string, number>>({});
```

b) Add a batch-fetch effect with 30s polling (replaces N×3s per-slide polling):
```typescript
useEffect(() => {
  if (!sessionId) return;
  let cancelled = false;
  const fetchCounts = () => {
    api.getCommentCounts(sessionId).then(({ counts }) => {
      if (!cancelled) setCommentCounts(counts);
    }).catch(() => {});
  };
  fetchCounts();
  const timer = setInterval(fetchCounts, 30_000);
  return () => { cancelled = true; clearInterval(timer); };
}, [sessionId]);
```

c) Add a callback to handle immediate count updates from CommentThread interactions:
```typescript
const handleCommentCountChange = useCallback((slideId: string, count: number) => {
  setCommentCounts(prev => ({ ...prev, [slideId]: count }));
}, []);
```

d) Pass count and callback to each SlideTile:
```typescript
<SlideTile
  ...
  commentCount={commentCounts[slide.slide_id] ?? 0}
  onCommentCountChange={handleCommentCountChange}
/>
```

e) Change the existing mentions polling interval from `3_000` to `30_000` (line ~93).

- [ ] **Step 4: Verify the app builds**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend && npm run build`
Expected: Build succeeds with no type errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/SlidePanel/SlideTile.tsx frontend/src/components/SlidePanel/SlidePanel.tsx
git commit -m "feat: batch comment counts, remove per-slide 3s polling"
```

---

## Task 3: Reduce Remaining Frontend Polling Intervals

**Files:**
- Modify: `frontend/src/components/Notifications/NotificationBell.tsx` (3s → 30s)
- Modify: `frontend/src/components/Layout/AppLayout.tsx` (10s → 30s)
- Modify: `frontend/src/components/History/SessionHistory.tsx` (15s → 60s)

- [ ] **Step 1: Reduce NotificationBell polling from 3s to 30s**

In `frontend/src/components/Notifications/NotificationBell.tsx`, change line 7:
```typescript
// Before:
const POLL_INTERVAL = 3_000;
// After:
const POLL_INTERVAL = 30_000;
```

- [ ] **Step 2: Split AppLayout lock heartbeat from slide-fetching**

The existing 10s `setInterval` in `frontend/src/components/Layout/AppLayout.tsx` (line ~178-213) combines the lock heartbeat, lock status check, and full slide deck fetch into one timer. The lock heartbeat **must stay at 10s** because `EDITING_LOCK_TIMEOUT_SECONDS = 45` on the backend — a 30s interval would leave only 15s of margin, making the lock fragile to a single missed heartbeat.

Split the single interval into two:

a) **Keep** the lock heartbeat + lock status check at 10s (lines ~178-207), but **remove** the `api.getSlides()` call from inside it.

b) **Add a separate** 30s interval for slide-fetching only:
```typescript
// Separate slide sync poll (30s) — doesn't need to be as frequent as lock heartbeat
const slideTimer = setInterval(async () => {
  if (cancelled) return;
  try {
    const slideResult = await api.getSlides(sessionId);
    if (cancelled) return;
    const lockStatus = await api.getEditingLockStatus(sessionId);
    if (slideResult.slide_deck && !isSelf(lockStatus)) {
      setSlideDeckGated(slideResult.slide_deck as SlideDeck, (slideResult.slide_deck as SlideDeck).version);
    }
  } catch { /* ignore */ }
}, 30_000);
```

c) Clean up both timers in the effect's return.

- [ ] **Step 3: Reduce SessionHistory polling from 15s to 60s**

In `frontend/src/components/History/SessionHistory.tsx`, change line ~49:
```typescript
// Before:
const timer = setInterval(loadSessions, 15_000);
// After:
const timer = setInterval(loadSessions, 60_000);
```

- [ ] **Step 4: Verify the app builds**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Notifications/NotificationBell.tsx frontend/src/components/Layout/AppLayout.tsx frontend/src/components/History/SessionHistory.tsx
git commit -m "perf: reduce frontend polling intervals (3-15s → 30-60s)"
```

---

## Task 4: Eliminate Redundant `current_user.me()` Calls in Route Handlers

**Files:**
- Create: `tests/unit/test_redundant_user_calls.py`
- Modify: `src/api/routes/images.py` (~lines 64-72)
- Modify: `src/api/routes/google_slides.py` (~lines 35-48)
- Modify: `src/api/routes/settings/deck_prompts.py` (~lines 200-208, 300-309, 372-380)
- Modify: `src/api/routes/settings/slide_styles.py` (~lines 210-219, 324-333, 416-425)

The middleware already calls `current_user.me()` once and stores the result via `set_current_user()`. These 8 route-level calls each add ~50-100ms of latency for a redundant Databricks API roundtrip.

- [ ] **Step 1: Write test verifying routes use context instead of API calls**

```python
# tests/unit/test_redundant_user_calls.py
"""Verify route handlers use context var instead of calling current_user.me()."""

import os
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import patch, MagicMock
import pytest


def test_images_get_current_user_uses_context_not_api():
    """images._get_current_user should use context var, not Databricks API."""
    with patch("src.core.user_context.get_current_user", return_value="ctx-user@example.com"):
        from src.api.routes.images import _get_current_user
        result = _get_current_user()
        assert result == "ctx-user@example.com"


def test_images_get_current_user_fallback():
    """images._get_current_user falls back to 'system' when context is empty."""
    with patch("src.core.user_context.get_current_user", return_value=None):
        from src.api.routes.images import _get_current_user
        result = _get_current_user()
        assert result == "system"


def test_google_slides_get_user_identity_uses_context_not_api():
    """google_slides._get_user_identity should use context var, not Databricks API."""
    with patch("src.core.user_context.get_current_user", return_value="ctx-user@example.com"):
        from src.api.routes.google_slides import _get_user_identity
        result = _get_user_identity()
        assert result == "ctx-user@example.com"


def test_google_slides_get_user_identity_fallback():
    """google_slides._get_user_identity falls back to 'local_dev' when context is empty."""
    with patch("src.core.user_context.get_current_user", return_value=None):
        from src.api.routes.google_slides import _get_user_identity
        result = _get_user_identity()
        assert result == "local_dev"


def test_no_databricks_api_calls_in_user_helpers():
    """Verify that _get_current_user and _get_user_identity never import get_user_client."""
    import inspect
    from src.api.routes.images import _get_current_user
    from src.api.routes.google_slides import _get_user_identity

    images_source = inspect.getsource(_get_current_user)
    assert "get_user_client" not in images_source, "images._get_current_user should not call get_user_client"

    google_source = inspect.getsource(_get_user_identity)
    assert "get_user_client" not in google_source, "google_slides._get_user_identity should not call get_user_client"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_redundant_user_calls.py -v`
Expected: FAIL — current implementations make API calls, not context lookups

- [ ] **Step 3: Replace `_get_current_user()` in images.py**

Replace the function at `src/api/routes/images.py` (~lines 64-72):

Add `from src.core.user_context import get_current_user` to the top-level imports of the file, then replace the function:

```python
# Before:
def _get_current_user() -> str:
    """Get current username (dev fallback to 'system')."""
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "system"
    try:
        from src.core.databricks_client import get_user_client
        return get_user_client().current_user.me().user_name
    except Exception:
        return "system"

# After:
def _get_current_user() -> str:
    """Get current username from request context (set by middleware)."""
    return get_current_user() or "system"
```

- [ ] **Step 4: Replace `_get_user_identity()` in google_slides.py**

Replace the function at `src/api/routes/google_slides.py` (~lines 35-48):

Add `from src.core.user_context import get_current_user` to the top-level imports of the file, then replace the function:

```python
# Before:
def _get_user_identity() -> str:
    """Return the current user's identity string. ..."""
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "local_dev"
    try:
        from src.core.databricks_client import get_user_client
        client = get_user_client()
        return client.current_user.me().user_name or "local_dev"
    except Exception:
        return "local_dev"

# After:
def _get_user_identity() -> str:
    """Return the current user's identity string from request context."""
    return get_current_user() or "local_dev"
```

- [ ] **Step 5: Replace 3× `current_user.me()` in deck_prompts.py**

In `src/api/routes/settings/deck_prompts.py`, replace the repeated pattern at ~lines 200-208, 300-309, 372-380. Each block looks like:

Add `from src.core.user_context import get_current_user` to the **top-level imports** of `deck_prompts.py`, then replace each of the 3 blocks:

```python
# Before (appears 3 times at ~lines 200-208, 300-309, 372-380):
if os.getenv("ENVIRONMENT") in ("development", "test"):
    user = "system"
else:
    try:
        from src.core.databricks_client import get_user_client
        client = get_user_client()
        user = client.current_user.me().user_name
    except Exception:
        user = "system"

# After (replace each block with this single line):
user = get_current_user() or "system"
```

Note: the second and third occurrences assign to `prompt.updated_by` instead of `user` — preserve that target variable name.

- [ ] **Step 6: Replace 3× `current_user.me()` in slide_styles.py**

Same pattern in `src/api/routes/settings/slide_styles.py` at ~lines 210-219, 324-333, 416-425. Apply identical replacement as Step 5.

- [ ] **Step 7: Run tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_redundant_user_calls.py -v`
Expected: PASS

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_redundant_user_calls.py src/api/routes/images.py src/api/routes/google_slides.py src/api/routes/settings/deck_prompts.py src/api/routes/settings/slide_styles.py
git commit -m "perf: eliminate 8 redundant current_user.me() API calls from route handlers"
```

---

## Task 5: Skip Middleware for Static Files

**Files:**
- Modify: `src/api/main.py` (~line 227)

In production, static files (JS bundles, CSS, favicon) go through the full auth middleware unnecessarily.

- [ ] **Step 1: Add early return for static asset paths in middleware**

In `src/api/main.py`, at the top of `user_auth_middleware` (line ~228), add:

```python
@app.middleware("http")
async def user_auth_middleware(request: Request, call_next):
    # Skip auth for static assets and health check
    path = request.url.path
    if path.startswith("/assets/") or path == "/favicon.svg" or path == "/api/health":
        return await call_next(request)

    # ... rest of existing middleware unchanged
```

- [ ] **Step 2: Verify the app starts and health check works**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -c "from src.api.main import app; print('App loaded OK')"`
Expected: "App loaded OK"

- [ ] **Step 3: Run existing tests to ensure no regressions**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/ -v --timeout=30 -x`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "perf: skip auth middleware for static assets and health check"
```

---

## Impact Summary

| Change | Before | After | Reduction |
|--------|--------|-------|-----------|
| Comment count polling (10 slides) | 200 req/min | 2 req/min | **99%** |
| Notification polling | 20 req/min | 2 req/min | **90%** |
| Mentions polling | 20 req/min | 2 req/min | **90%** |
| Lock heartbeat + status | 12 req/min | 12 req/min (kept at 10s for safety) | **0%** |
| Slide deck sync | (bundled above) | 2 req/min (split to 30s) | **new saving** |
| Session history polling | 8 req/min | 2 req/min | **75%** |
| **Total idle requests** | **~260/min** | **~12/min** | **~95%** |
| Redundant `.me()` API calls | 8 per affected request | 0 | **100%** |
| Static file middleware cost | Full auth | Bypassed | **100%** |
