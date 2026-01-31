# Test Suite Expansion Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**One-Line Summary:** Expand the profile test pattern to slide styles, deck prompts, and history views.

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** `frontend/` directory

```bash
cd frontend
npx playwright test tests/e2e/{feature}-ui.spec.ts
```

**Backend URL:** `http://localhost:8000`

**Frontend URL:** `http://localhost:5173` (Vite dev server)

---

## Critical: Read These Files First

Before implementing ANY task, the agent MUST read these files to understand the established pattern:

1. **Working UI test example:** `frontend/tests/e2e/profile-ui.spec.ts`
2. **Working integration test example:** `frontend/tests/e2e/profile-integration.spec.ts`
3. **Mock data patterns:** `frontend/tests/fixtures/mocks.ts`
4. **Existing mock setup:** `frontend/tests/e2e/deck-integrity.spec.ts` (for setupMocks pattern)

---

## App Navigation Structure

The app has a left sidebar navigation. Use these exact button names:

| Nav Button Name | Page Heading | Route |
|-----------------|--------------|-------|
| `Generator` | `Chat` | `/` |
| `History` | `Session History` | `/history` |
| `Profiles` | `Configuration Profiles` | `/profiles` |
| `Deck Prompts` | `Deck Prompt Library` | `/deck-prompts` |
| `Slide Styles` | `Slide Style Library` | `/slide-styles` |
| `Help` | `Help & Documentation` | `/help` |

**Navigation pattern:**
```typescript
await page.goto('/');
await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
```

---

## File Structure Convention

For each feature, create TWO files:

```
frontend/tests/e2e/
├── {feature}-ui.spec.ts          # Mocked - no backend needed
└── {feature}-integration.spec.ts  # Hits real backend
```

---

## Test Data Strategy

**UI Tests:** Use mocked API responses. No cleanup needed.

**Integration Tests:** Each test MUST:
1. Generate unique name: `E2E Test {operation} ${Date.now()}`
2. Create test data via UI or API
3. Perform the operation being tested
4. Verify result via UI AND via API re-fetch
5. Delete test data in `finally` block

---

## Common Selector Issues and Solutions

These issues were encountered in profile tests. Avoid them:

| Issue | Bad Selector | Good Selector |
|-------|-------------|---------------|
| Text matches multiple elements | `page.getByText('Sales')` | `page.getByRole('table').getByRole('cell', { name: 'Sales' })` |
| Button name not unique | `page.getByRole('button', { name: /Create/i })` | `page.getByRole('button', { name: '+ Create Style' })` or `.first()` |
| "Default" badge matches many | `page.getByText('Default')` | `row.getByText('Default')` (scoped to row) |
| Modal title | `page.getByText(/Delete/i)` | `page.getByRole('heading', { name: /Delete Style/i })` |
| Radio/checkbox labels | `page.getByText('Option')` | `page.locator('label').filter({ hasText: 'Option' }).first()` |

**Debug strict mode errors:** When Playwright says "resolved to N elements", use `.first()` or add more specificity.

---

## Task 1: Slide Styles Test Suite

### Discovery: Read These Component Files

```
frontend/src/components/config/SlideStyleList.tsx   # Main list view
frontend/src/components/config/SlideStyleForm.tsx   # Create/Edit modal
frontend/src/api/config.ts                          # API functions
```

### API Endpoints and Response Shapes

**GET `/api/settings/slide-styles`**
```json
{
  "styles": [
    {
      "id": 1,
      "name": "System Default",
      "description": "Protected system style...",
      "category": "System",
      "style_content": "/* CSS content */",
      "is_active": true,
      "is_system": true,
      "created_by": "system",
      "created_at": "2026-01-08T20:10:28.692105",
      "updated_by": "system",
      "updated_at": "2026-01-08T20:10:28.692107"
    }
  ],
  "total": 1
}
```

**POST `/api/settings/slide-styles`** - Create style
```json
// Request
{ "name": "My Style", "description": "...", "category": "Custom", "style_content": "/* css */" }
// Response: Same shape as single style object with new id
```

**PUT `/api/settings/slide-styles/{id}`** - Update style

**DELETE `/api/settings/slide-styles/{id}`** - Returns 204 No Content

### UI Elements to Test

| Element | Selector Pattern |
|---------|------------------|
| Page heading | `getByRole('heading', { name: 'Slide Style Library' })` |
| Create button | `getByRole('button', { name: '+ Create Style' })` |
| Style cards/rows | Explore component to find structure |
| Edit button | `getByRole('button', { name: /Edit/i })` scoped to row |
| Delete button | `getByRole('button', { name: /Delete/i })` scoped to row |
| Modal heading (create) | `getByRole('heading', { name: 'Create Slide Style' })` |
| Modal heading (edit) | `getByRole('heading', { name: 'Edit Slide Style' })` |
| Name input | `getByPlaceholder(...)` or `getByLabel('Name')` |
| Cancel button | `getByRole('button', { name: 'Cancel' })` |
| Save button | `getByRole('button', { name: /Save|Create/i })` |

### Files to Create

**`frontend/tests/e2e/slide-styles-ui.spec.ts`**

```typescript
import { test, expect, Page } from '@playwright/test';
import { mockSlideStyles, mockProfiles, mockDeckPrompts, mockSessions } from '../fixtures/mocks';

/**
 * Slide Styles UI Tests (Mocked)
 *
 * Tests UI behavior without backend. Uses mocked API responses.
 * Run: npx playwright test tests/e2e/slide-styles-ui.spec.ts
 */

async function setupMocks(page: Page) {
  // Mock slide styles endpoint
  await page.route('http://localhost:8000/api/settings/slide-styles', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlideStyles),
      });
    } else if (request.method() === 'POST') {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 99,
          name: 'New Style',
          description: 'Test',
          category: 'Custom',
          style_content: '/* test */',
          is_active: true,
          is_system: false,
          created_by: 'test',
          created_at: new Date().toISOString(),
          updated_by: null,
          updated_at: new Date().toISOString(),
        }),
      });
    } else {
      route.continue();
    }
  });

  // Mock individual style endpoints
  await page.route(/http:\/\/localhost:8000\/api\/settings\/slide-styles\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    } else if (request.method() === 'PUT') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlideStyles.styles[0]),
      });
    } else {
      route.continue();
    }
  });

  // Mock other required endpoints (profiles, prompts, sessions, version)
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
  });
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://localhost:8000/api/sessions**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) });
  });
}

async function goToSlideStyles(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
}

test.describe('SlideStylesList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('renders all styles', async ({ page }) => {
    await goToSlideStyles(page);
    // Verify mock styles are displayed - adjust selector based on actual UI
    await expect(page.getByText('System Default')).toBeVisible();
    await expect(page.getByText('Corporate Theme')).toBeVisible();
  });

  test('shows system badge for system styles', async ({ page }) => {
    await goToSlideStyles(page);
    // System styles should have a protected/system indicator
    // Explore the component to find exact selector
    await expect(page.getByText('System').first()).toBeVisible();
  });

  test('Create Style button opens modal', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
  });

  test('modal closes on Cancel', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible();
  });

  // TODO: Add remaining tests from task list
  // - shows action buttons per style
  // - hides Delete for system styles
  // - opens confirm dialog on Delete click
  // - validates required fields
});
```

**`frontend/tests/e2e/slide-styles-integration.spec.ts`**

```typescript
import { test, expect, Page, APIRequestContext } from '@playwright/test';

/**
 * Slide Styles Integration Tests
 *
 * Tests real backend persistence. Requires backend running.
 * Run: npx playwright test tests/e2e/slide-styles-integration.spec.ts
 */

const API_BASE = 'http://localhost:8000/api/settings';

interface SlideStyle {
  id: number;
  name: string;
  description: string | null;
  category: string;
  style_content: string;
  is_active: boolean;
  is_system: boolean;
}

function testStyleName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

async function createStyleViaAPI(request: APIRequestContext, name: string): Promise<SlideStyle> {
  const response = await request.post(`${API_BASE}/slide-styles`, {
    data: {
      name,
      description: 'E2E test style',
      category: 'Test',
      style_content: '/* E2E test CSS */',
    },
  });
  if (!response.ok()) {
    throw new Error(`Failed to create style: ${await response.text()}`);
  }
  return response.json();
}

async function deleteStyleViaAPI(request: APIRequestContext, id: number): Promise<void> {
  const response = await request.delete(`${API_BASE}/slide-styles/${id}`);
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete style ${id}`);
  }
}

async function getStyleByName(request: APIRequestContext, name: string): Promise<SlideStyle | null> {
  const response = await request.get(`${API_BASE}/slide-styles`);
  const data = await response.json();
  return data.styles?.find((s: SlideStyle) => s.name === name) || null;
}

async function goToSlideStyles(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
}

test.describe('Slide Style CRUD', () => {
  test('create style saves to database', async ({ page, request }) => {
    const styleName = testStyleName('Create');

    await goToSlideStyles(page);

    // Open create modal
    await page.getByRole('button', { name: '+ Create Style' }).click();
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();

    // Fill form - adjust selectors based on actual form
    await page.getByLabel('Name').fill(styleName);
    await page.getByLabel('Description').fill('E2E test description');
    // Fill CSS content - may be a textarea or code editor

    // Submit
    await page.getByRole('button', { name: /Create|Save/i }).click();

    // Wait for modal to close
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible({ timeout: 10000 });

    // Verify in database
    const style = await getStyleByName(request, styleName);
    expect(style).not.toBeNull();

    // Cleanup
    if (style) {
      await deleteStyleViaAPI(request, style.id);
    }
  });

  test('delete style removes from database', async ({ page, request }) => {
    const styleName = testStyleName('Delete');

    // Create via API
    const style = await createStyleViaAPI(request, styleName);

    await goToSlideStyles(page);

    // Find and delete the style - adjust selector based on UI structure
    // May need to scope to a specific row/card
    const styleElement = page.locator(`text=${styleName}`).first();
    await expect(styleElement).toBeVisible();

    // Click delete - may need to find button relative to the style element
    // Example: await page.locator('tr', { hasText: styleName }).getByRole('button', { name: /Delete/i }).click();

    // Confirm deletion
    // await page.getByRole('button', { name: /Confirm/i }).click();

    // Verify removed from database
    const deleted = await getStyleByName(request, styleName);
    expect(deleted).toBeNull();
  });

  // TODO: Add remaining tests
  // - edit style persists
  // - cannot delete system style
  // - cannot create duplicate name
});
```

### Mocks to Add to `frontend/tests/fixtures/mocks.ts`

```typescript
// Add these exports to mocks.ts

export const mockStyleCreateResponse = {
  id: 99,
  name: "New Test Style",
  description: "Test style created via E2E",
  category: "Custom",
  style_content: "/* test CSS */",
  is_active: true,
  is_system: false,
  created_by: "test",
  created_at: "2026-01-31T10:00:00.000000",
  updated_by: null,
  updated_at: "2026-01-31T10:00:00.000000"
};

export const mockStyleDuplicateError = {
  detail: "Style with this name already exists"
};
```

---

## Task 2: Deck Prompts Test Suite

### Discovery: Read These Component Files

```
frontend/src/components/config/DeckPromptList.tsx   # Main list view
frontend/src/components/config/DeckPromptForm.tsx   # Create/Edit modal
frontend/src/api/config.ts                          # API functions
```

### API Endpoints and Response Shapes

**GET `/api/settings/deck-prompts`**
```json
{
  "prompts": [
    {
      "id": 1,
      "name": "Monthly Review",
      "description": "Template for review meetings...",
      "category": "Review",
      "prompt_content": "Create a presentation that...",
      "is_active": true,
      "created_by": "system",
      "created_at": "2026-01-08T20:10:28.689395",
      "updated_by": "system",
      "updated_at": "2026-01-08T20:10:28.689398"
    }
  ],
  "total": 1
}
```

### UI Elements

| Element | Expected Selector |
|---------|-------------------|
| Page heading | `getByRole('heading', { name: 'Deck Prompt Library' })` |
| Create button | `getByRole('button', { name: '+ Create Prompt' })` |
| Modal heading | `getByRole('heading', { name: 'Create Deck Prompt' })` |

### Files to Create

Follow the same pattern as Slide Styles:
- `frontend/tests/e2e/deck-prompts-ui.spec.ts`
- `frontend/tests/e2e/deck-prompts-integration.spec.ts`

**Implementation approach:** Copy the slide-styles test files and adapt:
1. Change navigation to `'Deck Prompts'`
2. Change heading to `'Deck Prompt Library'`
3. Change API endpoints to `/api/settings/deck-prompts`
4. Change mock data to `mockDeckPrompts`
5. Adjust form fields (prompt_content instead of style_content)

---

## Task 3: History Test Suite

### Discovery: Read These Component Files

```
frontend/src/components/history/SessionHistory.tsx  # Main history view
frontend/src/api/sessions.ts                        # Session API functions
```

### API Endpoints and Response Shapes

**GET `/api/sessions?limit=50`**
```json
{
  "sessions": [
    {
      "session_id": "uuid-here",
      "user_id": null,
      "title": "Session 2026-01-08 20:38",
      "created_at": "2026-01-08T20:38:56.749592",
      "last_activity": "2026-01-08T20:42:11.058737",
      "message_count": 4,
      "has_slide_deck": true,
      "profile_id": 1,
      "profile_name": "Sales Analytics"
    }
  ],
  "count": 1
}
```

**DELETE `/api/sessions/{session_id}`** - Returns 204

### UI Elements

| Element | Expected Selector |
|---------|-------------------|
| Page heading | `getByRole('heading', { name: 'Session History' })` |
| Table | `getByRole('table')` |
| Profile column | `getByRole('columnheader', { name: /Profile/i })` |
| Restore button | Per-row, `getByRole('button', { name: /Restore/i })` |
| Delete button | Per-row, `getByRole('button', { name: /Delete/i })` |

### Key Differences from CRUD Tests

History is **read-only** with **restore** and **delete** operations. No create/edit via this page.

Sessions are created by using the Generator to send messages. For integration tests:
1. Create a session by navigating to Generator and sending a message
2. OR use existing sessions and verify they display correctly

### Files to Create

- `frontend/tests/e2e/history-ui.spec.ts`
- `frontend/tests/e2e/history-integration.spec.ts`

---

## Verification Checklist

Before marking a task complete, run:

```bash
cd frontend
npx playwright test tests/e2e/{feature}-ui.spec.ts
```

All tests must pass. If you see "strict mode violation", fix the selector to be more specific.

**Checklist:**
- [ ] All UI tests pass with mocks
- [ ] No strict mode violations (selectors match exactly 1 element)
- [ ] Integration tests create unique test data
- [ ] Integration tests clean up in finally blocks
- [ ] New mocks added to `fixtures/mocks.ts`
- [ ] Tests committed to git

---

## How to Debug Failing Tests

```bash
# Run with headed browser to watch
npx playwright test tests/e2e/slide-styles-ui.spec.ts --headed

# Run single test
npx playwright test tests/e2e/slide-styles-ui.spec.ts -g "renders all styles"

# Generate trace on failure
npx playwright test tests/e2e/slide-styles-ui.spec.ts --trace on

# View report
npx playwright show-report
```

---

## Reference: Working Profile Tests

The profile tests are the canonical example. Read these files completely before starting:

- `frontend/tests/e2e/profile-ui.spec.ts` (26 tests, all passing)
- `frontend/tests/e2e/profile-integration.spec.ts` (21 tests)
