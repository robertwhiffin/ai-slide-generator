# Test Suite Expansion Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**One-Line Summary:** Expand the profile test pattern to slide styles, deck prompts, and history views.

---

## Overview

This plan documents the test pattern established in `profile-ui.spec.ts` and `profile-integration.spec.ts` so agents can implement identical test suites for:

1. **Slide Styles** - CRUD operations for slide style library
2. **Deck Prompts** - CRUD operations for deck prompt library
3. **History** - Session history view and restore operations

---

## Established Pattern

### File Structure

For each feature area, create two test files:

```
frontend/tests/e2e/
├── {feature}-ui.spec.ts          # Mocked UI behavior tests
└── {feature}-integration.spec.ts  # Real backend persistence tests
```

### Test Types

| Type | Purpose | Backend Required | Speed |
|------|---------|------------------|-------|
| UI Tests | Validate buttons, forms, modals, navigation | No (mocked) | Fast (~10s) |
| Integration Tests | Validate database persistence | Yes | Slower (~60s) |

### Test Data Strategy (Integration Tests)

Each integration test MUST:
1. Create test data with unique name: `E2E Test {operation} {timestamp}`
2. Perform operation via UI
3. Verify via UI AND API re-fetch
4. Delete test data in finally block (cleanup)

---

## Implementation Tasks

### Task 1: Slide Styles Test Suite

**Files to create:**
- `frontend/tests/e2e/slide-styles-ui.spec.ts`
- `frontend/tests/e2e/slide-styles-integration.spec.ts`

**Reference documentation:** `docs/technical/frontend-overview.md`

**UI Components to test:**
- Slide Styles page (`/slide-styles` nav)
- Style list/grid view
- Create Style modal
- Edit Style modal
- Style preview
- Delete confirmation dialog

**UI Tests (~15 tests):**

```
test.describe('SlideStylesList')
├── renders all styles in grid/list
├── shows system styles with protected badge
├── shows action buttons per style (View, Edit, Delete)
├── hides Delete for system styles
├── opens create modal on "+ Create Style" click
├── opens edit modal on Edit click
├── opens confirm dialog on Delete click

test.describe('SlideStyleModal')
├── opens when Create Style clicked
├── shows name, description, category fields
├── shows CSS editor
├── shows preview pane
├── validates required fields (name, CSS)
├── closes on Cancel
├── closes on X button

test.describe('SlideStyleValidation')
├── shows error for duplicate name
├── enforces character limits
```

**Integration Tests (~12 tests):**

```
test.describe('Slide Style CRUD')
├── create style saves to database
├── created style appears in list
├── edit style name persists
├── edit style CSS persists
├── delete style removes from database
├── duplicate style creates copy

test.describe('Slide Style Validation')
├── cannot create with duplicate name
├── cannot delete system style
├── requires name to save
├── requires CSS content to save

test.describe('Slide Style Usage')
├── style can be selected in profile wizard
├── style preview renders correctly
```

**Mock data to add to `mocks.ts`:**
```typescript
export const mockStyleCreateResponse = {
  id: 3,
  name: "New Test Style",
  description: "Test style",
  category: "Custom",
  style_content: "/* test */",
  is_active: true,
  is_system: false,
  // timestamps...
};

export const mockStyleDuplicateError = {
  detail: "Style with this name already exists"
};
```

**API endpoints:**
- `GET /api/settings/slide-styles` - List styles
- `POST /api/settings/slide-styles` - Create style
- `PUT /api/settings/slide-styles/{id}` - Update style
- `DELETE /api/settings/slide-styles/{id}` - Delete style

---

### Task 2: Deck Prompts Test Suite

**Files to create:**
- `frontend/tests/e2e/deck-prompts-ui.spec.ts`
- `frontend/tests/e2e/deck-prompts-integration.spec.ts`

**UI Components to test:**
- Deck Prompts page (`/deck-prompts` nav)
- Prompt list view
- Create Prompt modal
- Edit Prompt modal
- Delete confirmation dialog

**UI Tests (~12 tests):**

```
test.describe('DeckPromptsList')
├── renders all prompts in list
├── shows category badges
├── shows action buttons (View, Edit, Delete)
├── opens create modal on "+ Create Prompt" click
├── opens edit modal on Edit click
├── opens confirm dialog on Delete click

test.describe('DeckPromptModal')
├── opens when Create clicked
├── shows name, description, category fields
├── shows prompt content textarea
├── validates required fields
├── closes on Cancel
├── closes on X button
```

**Integration Tests (~10 tests):**

```
test.describe('Deck Prompt CRUD')
├── create prompt saves to database
├── created prompt appears in list
├── edit prompt name persists
├── edit prompt content persists
├── delete prompt removes from database

test.describe('Deck Prompt Validation')
├── cannot create with duplicate name
├── requires name to save
├── requires prompt content to save

test.describe('Deck Prompt Usage')
├── prompt can be selected in profile wizard
├── prompt appears in Generator view selector
```

**Mock data to add:**
```typescript
export const mockPromptCreateResponse = {
  id: 5,
  name: "New Test Prompt",
  description: "Test prompt",
  category: "Custom",
  prompt_content: "Create a presentation about...",
  is_active: true,
  // timestamps...
};

export const mockPromptDuplicateError = {
  detail: "Prompt with this name already exists"
};
```

**API endpoints:**
- `GET /api/settings/deck-prompts` - List prompts
- `POST /api/settings/deck-prompts` - Create prompt
- `PUT /api/settings/deck-prompts/{id}` - Update prompt
- `DELETE /api/settings/deck-prompts/{id}` - Delete prompt

---

### Task 3: History Test Suite

**Files to create:**
- `frontend/tests/e2e/history-ui.spec.ts`
- `frontend/tests/e2e/history-integration.spec.ts`

**UI Components to test:**
- History page (`/history` nav)
- Session list with columns (Title, Profile, Date, Actions)
- Session restore
- Session delete
- Session rename

**UI Tests (~10 tests):**

```
test.describe('HistoryList')
├── renders session history table
├── shows correct columns (Title, Profile, Date, Slides, Actions)
├── shows profile name for each session
├── shows "has slides" indicator
├── shows action buttons (Restore, Delete)
├── opens confirm dialog on Delete click

test.describe('HistoryNavigation')
├── navigating to History shows session list
├── empty state shown when no sessions
├── pagination works (if applicable)
```

**Integration Tests (~10 tests):**

```
test.describe('Session History')
├── sessions appear in history after creation
├── session shows correct profile association
├── session shows correct slide count

test.describe('Session Restore')
├── restore session loads slides in Generator
├── restore session from different profile triggers profile switch
├── restored session maintains conversation history

test.describe('Session Management')
├── delete session removes from history
├── delete session removes from database
├── rename session persists
```

**Mock data to add:**
```typescript
// Already have mockSessions - may need more varied data
export const mockSessionsMultiProfile = {
  sessions: [
    { session_id: "...", profile_id: 1, profile_name: "Sales", ... },
    { session_id: "...", profile_id: 2, profile_name: "Marketing", ... },
  ],
  count: 2
};

export const mockSessionDetail = {
  session_id: "...",
  messages: [...],
  slide_deck: {...},
  profile_id: 1,
  profile_name: "Sales"
};
```

**API endpoints:**
- `GET /api/sessions?limit=N` - List sessions
- `GET /api/sessions/{id}` - Get session detail
- `DELETE /api/sessions/{id}` - Delete session
- `PUT /api/sessions/{id}` - Update session (rename)
- `POST /api/sessions/{id}/restore` - Restore session

---

## Code Templates

### UI Test Template

```typescript
import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  // ... other mocks
} from '../fixtures/mocks';

async function setupMocks(page: Page) {
  // Mock all required endpoints
  await page.route('http://localhost:8000/api/...', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockData),
    });
  });
  // ... other mocks
}

async function goToFeaturePage(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Feature' }).click();
  await expect(page.getByRole('heading', { name: 'Feature Title' })).toBeVisible();
}

test.describe('FeatureList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('renders all items', async ({ page }) => {
    await goToFeaturePage(page);
    // Use specific selectors - prefer table/role selectors
    const table = page.getByRole('table');
    await expect(table.getByRole('cell', { name: 'Item Name' })).toBeVisible();
  });

  // ... more tests
});
```

### Integration Test Template

```typescript
import { test, expect, Page, APIRequestContext } from '@playwright/test';

const API_BASE = 'http://localhost:8000/api/settings';

interface Item {
  id: number;
  name: string;
  // ...
}

function testItemName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

async function createTestItemViaAPI(
  request: APIRequestContext,
  name: string
): Promise<Item> {
  const response = await request.post(`${API_BASE}/items`, {
    data: { name, /* required fields */ },
  });
  if (!response.ok()) throw new Error(`Failed to create: ${await response.text()}`);
  return response.json();
}

async function deleteTestItemViaAPI(
  request: APIRequestContext,
  id: number
): Promise<void> {
  await request.delete(`${API_BASE}/items/${id}`);
}

test.describe('Item CRUD', () => {
  test('create saves to database', async ({ page, request }) => {
    const itemName = testItemName('Create');

    // Navigate and create via UI
    await goToFeaturePage(page);
    await page.getByRole('button', { name: /Create/i }).click();
    // Fill form...
    await page.getByRole('button', { name: /Save|Create/i }).click();

    // Verify in database
    const response = await request.get(`${API_BASE}/items`);
    const items = await response.json();
    const created = items.find((i: Item) => i.name === itemName);
    expect(created).toBeDefined();

    // Cleanup
    if (created) await deleteTestItemViaAPI(request, created.id);
  });
});
```

---

## Selector Best Practices

Based on issues encountered in profile tests:

| Problem | Solution |
|---------|----------|
| Text matches multiple elements | Use `page.getByRole('table').getByRole('cell', { name: '...' })` |
| Button name matches multiple | Use `{ name: 'Exact Name', exact: true }` or `.first()` |
| Generic text like "Default" | Use parent context: `row.getByText('Default')` |
| Modal/dialog elements | Use `page.getByRole('heading', { name: /Dialog Title/i })` |
| Form labels vs buttons | Use `page.locator('label').filter({ hasText: '...' })` |

---

## Execution Order

1. **Task 1: Slide Styles** - Similar CRUD pattern to profiles
2. **Task 2: Deck Prompts** - Similar CRUD pattern to profiles
3. **Task 3: History** - Different pattern (read/restore vs CRUD)

Each task can be executed in parallel by separate agents.

---

## Verification Checklist

Before marking a task complete, verify:

- [ ] All UI tests pass: `npx playwright test tests/e2e/{feature}-ui.spec.ts`
- [ ] Tests use unique selectors (no strict mode violations)
- [ ] Integration tests clean up test data
- [ ] Mock data added to `fixtures/mocks.ts`
- [ ] Tests follow established naming patterns
- [ ] No hardcoded waits > 1000ms (use `expect().toBeVisible()` instead)

---

## Reference Files

- Pattern example: `frontend/tests/e2e/profile-ui.spec.ts`
- Pattern example: `frontend/tests/e2e/profile-integration.spec.ts`
- Mock data: `frontend/tests/fixtures/mocks.ts`
- Existing e2e tests: `frontend/tests/e2e/deck-integrity.spec.ts`
- Technical docs: `docs/technical/`
