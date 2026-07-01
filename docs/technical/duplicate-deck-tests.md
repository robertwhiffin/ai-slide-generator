# Duplicate Deck Test Suite

**One-Line Summary:** Test coverage for duplicating a full slide deck into a new private session, including permission gates, contributor-session resolution, and data isolation.

---

## 1. Overview

The duplicate deck feature copies the current slide deck snapshot from a source session into a **new root session** owned by the caller. Tests validate:

- Slide content and agent config are copied
- Chat, save points, and sharing are **not** copied
- Contributor sessions resolve to the parent deck
- API returns correct status codes and enforces **CAN_VIEW** minimum permission

### Test Files

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/unit/test_session_duplicate.py` | 8 | `SessionManager.duplicate_session`, agent config sanitization |
| `tests/unit/test_deck_permission_routes.py` | 1 | CAN_VIEW gate for duplicate (`TestDuplicateDeckPermission`) |
| `tests/integration/test_api_routes.py` | 6 | HTTP layer for `POST /api/sessions/{id}/duplicate` |
| `frontend/tests/e2e/history-ui.spec.ts` | 3 | Duplicate button UI (mocked API) |

---

## 2. Unit Tests — Session Manager

```
tests/unit/test_session_duplicate.py
```

### 2.1 Agent config sanitization

| Test | Scenario | Validation |
|------|----------|------------|
| `TestSanitizeAgentConfigForPersist::test_strips_genie_conversation_id` | Genie tool with `conversation_id` | ID cleared, other fields kept |
| `TestSanitizeAgentConfigForPersist::test_none_config_returns_none` | `None` input | Returns `None` |

### 2.2 Valid duplicate scenarios

| Test | Scenario | Validation |
|------|----------|------------|
| `test_duplicate_root_session_creates_owned_copy` | Owner duplicates own deck with sharing, chat, versions | New root session; deck copied; session fields reset; no messages/contributors/versions on copy |
| `test_duplicate_from_contributor_session_uses_parent_deck` | Duplicate via contributor session ID | `source_session_id` is parent; copy has parent deck JSON |
| `test_default_title_when_not_provided` | No title in request | Title is `Copy of {source}` |

### 2.3 Error handling

| Test | Scenario | Expected |
|------|----------|----------|
| `test_missing_session_raises_not_found` | Unknown session ID | `SessionNotFoundError` |
| `test_session_without_deck_raises_value_error` | Session with no `session_slide_decks` row | `ValueError` |
| `test_deck_only_session_appears_in_list` | Duplicate without sending chat | Copy appears in `list_sessions` |

---

## 3. Unit Tests — Permissions

```
tests/unit/test_deck_permission_routes.py::TestDuplicateDeckPermission
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_can_view_contributor_passes_view_gate` | User with `CAN_VIEW` on shared deck | `_require_session_access(..., CAN_VIEW)` succeeds |

---

## 4. Integration Tests — API Routes

```
tests/integration/test_api_routes.py::TestSessionEndpoints
```

| Test | Scenario | Status |
|------|----------|--------|
| `test_duplicate_session_success` | Owner duplicates own session | 201 |
| `test_duplicate_session_with_custom_title` | Optional `title` in body | 201, title passed to service |
| `test_duplicate_session_not_found` | Missing session | 404 |
| `test_duplicate_session_no_deck` | Source has no deck | 400 |
| `test_duplicate_session_forbidden` | No deck access | 403 |

---

## 5. Frontend E2E Tests (Mocked)

```
frontend/tests/e2e/history-ui.spec.ts::SessionHistory Duplicate
```

| Test | Scenario | Validation |
|------|----------|------------|
| `shows Duplicate action on My Sessions rows` | History page loaded | Duplicate button visible |
| `clicking Duplicate on My Sessions calls duplicate API` | Click Duplicate | `POST .../duplicate` invoked |
| `shows Duplicate action on Shared with Me rows` | Shared tab with mock data | Duplicate button visible |

Run:

```bash
cd frontend && npx playwright test tests/e2e/history-ui.spec.ts -g "SessionHistory Duplicate"
```

---

## 6. CI/CD Integration

Add this block to your main-branch CI workflow to run the duplicate-deck suite in isolation (or include in the full unit/integration jobs):

```bash
# Duplicate deck feature test suite (backend + frontend UI)
pytest \
  tests/unit/test_session_duplicate.py \
  tests/unit/test_deck_permission_routes.py::TestDuplicateDeckPermission \
  tests/integration/test_api_routes.py -k "duplicate_session" \
  -v --tb=short

cd frontend && npx playwright test tests/e2e/history-ui.spec.ts -g "SessionHistory Duplicate"
```

**Recommended CI placement:** Run as part of existing `unit-tests` and `integration-tests` jobs (no separate job required). Use the command above for a focused pre-merge check on `feature/duplicate-slide`.

```yaml
# Example: focused job for duplicate-deck PRs
duplicate-deck-tests:
  name: Duplicate Deck Tests
  steps:
    - run: |
        pytest tests/unit/test_session_duplicate.py \
          tests/unit/test_deck_permission_routes.py::TestDuplicateDeckPermission \
          tests/integration/test_api_routes.py -k "duplicate_session" -v --tb=short
        cd frontend && npx playwright test tests/e2e/history-ui.spec.ts -g "SessionHistory Duplicate"
```

---

## 7. Key Invariants

1. **Independent copy:** Duplicate never modifies the source session or deck.
2. **Root session only:** Copy always has `parent_session_id = NULL`.
3. **Private by default:** `global_permission` and `deck_contributors` are not copied.
4. **Fresh conversation:** No `session_messages`; Genie `conversation_id` stripped from `agent_config`.
5. **Contributor resolution:** Duplicating from a contributor session copies the parent's current deck.
6. **Permission floor:** Caller needs at least **CAN_VIEW** on the source deck.

---

## 8. Cross-References

- [Duplicate Deck Design Spec](../superpowers/specs/2026-06-30-duplicate-deck-design.md)
- [Permissions Model](./permissions-model.md)
- [Backend Overview](./backend-overview.md)
- [Deck Operations Tests](./deck-operations-tests.md) — single-slide duplicate (different feature)
