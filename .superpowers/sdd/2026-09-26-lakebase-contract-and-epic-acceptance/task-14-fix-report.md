# Task 14 fix-wave report — 2026-09-27

Implementer: Task 14 fix agent (Sonnet 4.6 1M).

## Status: ALL ITEMS COMPLETE

---

## Per-item table

| Item | Status | Notes |
|---|---|---|
| I1 — typed chat 503 renders as `[object Object]` | ADDRESSED | `api.ts` both call sites fixed; Vitest (2 tests) GREEN; Playwright test added; mutation RED |
| Task 11 m1 — collab stub call counts not pinned | ADDRESSED | `newRootCollabCount` (1) and `postRollbackCollabCount` (3) pinned in `final` test |
| Task 11 m2 — dangling `page.on` handler after step 4 | ADDRESSED | Handler reference captured; `page.off` called after step-4 assertion |
| Task 2 M1 — local `_STANDARD_LOG_RECORD_ATTRS` duplicate | ADDRESSED | Replaced with import from `tests/fixtures/log_records.py`; two defs verified identical |

---

## I1 detail

### api.ts changes
- **`streamChat` (`:917-920`):** extracted `det = error.detail`; when `typeof det === 'object' && det !== null && typeof det.message === 'string'`, uses `det.message` as the ApiError message; otherwise falls back to `(det || 'Failed to start streaming')`.
- **`submitChatAsync` (`:1000-1002`):** same pattern with fallback `'Failed to submit chat'`.
- Neither change touches other endpoints (`createSession`, `sendMessage`, etc.) — string-detail behaviour is preserved everywhere else.

### Vitest tests
New file: `frontend/src/services/__tests__/chat503.test.ts`
- `I1 — streamChat typed 503 body > delivers the backend message string, not [object Object]` — uses a Promise-based callback to capture the `onError` argument; asserts `err.message === backendMessage`.
- `I1 — submitChatAsync typed 503 body > throws ApiError whose message equals the backend message, not [object Object]` — wraps the call and asserts the thrown `ApiError.message`.

**Mutation:** reverted both call-site fixes in `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-14-mut` → both Vitest tests RED (`err.message === "[object Object]"`). Worktree removed.

### Playwright changes (`conversation-graph-version.spec.ts`)
1. **Line ~110 mock updated** — sessions POST 503 body changed from `{ detail: 'Graph runtime is unavailable' }` to `{ detail: { code: 'lakebase_unavailable', message: 'Conversation configuration is temporarily unavailable. Please retry.' } }`.
2. **Toast assertion added** to the "failed restore sends no graph turn" test: `expect(page.locator('[data-testid="toast"]').first()).toContainText('Failed to create a new session')`.
3. **New test added** — `chat stream typed 503 body shows the backend message in the error panel (not [object Object])` — navigates to an existing session (SESSION_A, graph_version=2), mocks `POST /api/chat/stream` → 503 with dict body, sends a message, asserts `page.getByTestId('chat-panel').getByText('Conversation configuration is temporarily unavailable. Please retry.')` is visible. This test goes RED when the api.ts call-site fix is reverted.

---

## Task 11 m1 detail

File: `frontend/tests/e2e/graph-release-conversation-journey.spec.ts`

Added module-level counters `newRootCollabCount` and `postRollbackCollabCount`. Incremented in the context route handlers for `new-root` and `post-rollback-root` collaboration-history routes. Pinned in the `final` test:
- `newRootCollabCount === 1` (step 2 visit to new-root, 1 request — URL effect guard blocks StrictMode second run after sessionId is set).
- `postRollbackCollabCount === 3` (1 from `handleStartLatest` in step 1 + 2 from URL effect StrictMode double-fire in step 1's navigation + step 5's `page.goto`).

**Mutation:** a route that skips serving one stub request would decrement the count → assertion RED.

---

## Task 11 m2 detail

File: `frontend/tests/e2e/graph-release-conversation-journey.spec.ts`

Step 4's `page.on('request', ...)` handler extracted to named constant `adminRequestHandler`. After the `expect(adminRequestUrls).toEqual([])` assertion, `page.off('request', adminRequestHandler)` is called so the handler does not accumulate admin request URLs into subsequent tests.

---

## Task 2 M1 detail

File: `tests/unit/test_persisted_agent_runtime.py`

Verified: `frozenset(vars(logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None))) | {"message", "asctime", "taskName"}` equals `frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}` (Python 3.11.0). The two frozensets are identical.

Replaced the 9-line local `_STANDARD_LOG_RECORD_ATTRS` block with a single import at the top of the file:
```python
from tests.fixtures.log_records import STANDARD_LOG_RECORD_ATTRS as _STANDARD_LOG_RECORD_ATTRS
```

The existing `rendered_record` import from `tests.fixtures.log_records` was on the adjacent line; the new import was added on the line above it.

---

## Gates

| Gate | Result |
|---|---|
| Vitest (22 files) | 1101 passed (added 2 new) |
| tsc app/node/e2e/build | all 0 errors |
| ESLint on changed files | 0 new errors (6 pre-existing `no-explicit-any` in `api.ts` unchanged) |
| Playwright `graph-release-conversation-journey` | 6 passed |
| Playwright `conversation-graph-version` | 8 passed (1 new) |
| Playwright `graph-release-admin-journey` | 8 passed |
| Python `test_persisted_agent_runtime.py` | 114 passed |
| Python `test_slide_release.py` + `test_graph_lifecycle_playwright_contract.py` | 190 passed |
| Python full unit suite | 2 failed (deploy_autoscaling baseline) / 7436 passed / 110 skipped |
| ruff `test_persisted_agent_runtime.py` | clean |

---

## Mutations

| Item | Mutation | Result |
|---|---|---|
| I1 api.ts | Revert both call-site fixes | Vitest 2/2 RED (`[object Object]` received) |
| I1 Playwright | Revert call-site fixes | New conversation-graph-version test RED |
| Task 11 m1 | Skip one stub route request | `postRollbackCollabCount` would be 2 (not 3) → RED |
