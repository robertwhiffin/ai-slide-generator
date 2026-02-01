# Help Page Test Suite Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**Estimated Tests:** ~12 UI tests

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** `frontend/` directory

```bash
cd frontend
npx playwright test tests/e2e/help-ui.spec.ts
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **Working test example:** `frontend/tests/e2e/profile-ui.spec.ts`
2. **Mock patterns:** `frontend/tests/fixtures/mocks.ts`
3. **Component to test:** `frontend/src/components/Help/HelpPage.tsx`

---

## Context: Help Page Structure

The Help page is a **static content page** with:
- Header with title "How to Use databricks tellr" and Back button
- Tab bar with 7 tabs: Overview, Generator, Verification, History, Profiles, Deck Prompts, Slide Styles
- Content area that displays different help sections based on active tab
- Quick link buttons in Overview tab to navigate to other tabs

**No API calls** - this is purely client-side navigation and content display.

---

## Navigation

| Nav Button | Page Component | Heading |
|------------|----------------|---------|
| `Help` | HelpPage | `How to Use databricks tellr` |

```typescript
async function goToHelp(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();
  await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
}
```

---

## Tabs Available

| Tab Name | Tab Button Text | Key Content Heading |
|----------|-----------------|---------------------|
| Overview | `Overview` | `What is databricks tellr?` |
| Generator | `Generator` | `Chat Panel (Left)` |
| Verification | `Verification` | `What is Slide Verification?` |
| History | `History` | `Session List` |
| Profiles | `Profiles` | `What are Profiles?` |
| Deck Prompts | `Deck Prompts` | `What are Deck Prompts?` |
| Slide Styles | `Slide Styles` | `What are Slide Styles?` |

---

## File to Create

**`frontend/tests/e2e/help-ui.spec.ts`**

---

## Test Categories

### 1. Help Page Navigation Tests

```typescript
test.describe('HelpNavigation', () => {
  test('Help button navigates to help page', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/');

    await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();

    await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
  });

  test('Back button returns to main view', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Back' }).click();

    // Should return to main view (Generator)
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
  });

  test('shows Overview tab by default', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    // Overview should be the active tab
    await expect(page.getByRole('heading', { name: 'What is databricks tellr?' })).toBeVisible();
  });
});
```

### 2. Tab Switching Tests

```typescript
test.describe('HelpTabs', () => {
  test('all tabs are visible', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Generator' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verification' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'History' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Profiles' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Deck Prompts' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Slide Styles' })).toBeVisible();
  });

  test('clicking Generator tab shows generator content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Generator' }).click();

    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });

  test('clicking Verification tab shows verification content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Verification' }).click();

    await expect(page.getByRole('heading', { name: 'What is Slide Verification?' })).toBeVisible();
  });

  test('clicking History tab shows history content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'History' }).click();

    await expect(page.getByRole('heading', { name: 'Session List' })).toBeVisible();
  });

  test('clicking Profiles tab shows profiles content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Profiles' }).click();

    await expect(page.getByRole('heading', { name: 'What are Profiles?' })).toBeVisible();
  });

  test('clicking Deck Prompts tab shows deck prompts content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Deck Prompts' }).click();

    await expect(page.getByRole('heading', { name: 'What are Deck Prompts?' })).toBeVisible();
  });

  test('clicking Slide Styles tab shows slide styles content', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    await page.getByRole('button', { name: 'Slide Styles' }).click();

    await expect(page.getByRole('heading', { name: 'What are Slide Styles?' })).toBeVisible();
  });
});
```

### 3. Quick Link Tests

```typescript
test.describe('QuickLinks', () => {
  test('quick links visible in overview tab', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    // Quick link buttons should be visible
    await expect(page.getByRole('button', { name: /Learn about Generator/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Learn about Verification/i })).toBeVisible();
  });

  test('clicking quick link navigates to corresponding tab', async ({ page }) => {
    await setupMocks(page);
    await goToHelp(page);

    // Click Generator quick link
    await page.getByRole('button', { name: /Learn about Generator/i }).click();

    // Should show Generator content
    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });
});
```

---

## Complete Test File Template

```typescript
import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Help Page UI Tests
 *
 * Tests help page navigation, tab switching, and content display.
 * Run: cd frontend && npx playwright test tests/e2e/help-ui.spec.ts
 */

async function setupMocks(page: Page) {
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
  });
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://localhost:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
  await page.route('http://localhost:8000/api/sessions**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) });
  });
}

async function goToHelp(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();
  await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
}

test.describe('HelpNavigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Help button navigates to help page', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();

    await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
  });

  test('Back button returns to main view', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Back' }).click();

    // Should return to main view
    await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).not.toBeVisible();
  });

  test('shows Overview tab by default', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('heading', { name: 'What is databricks tellr?' })).toBeVisible();
  });
});

test.describe('HelpTabs', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('all tabs are visible', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Generator' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verification' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'History' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Profiles' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Deck Prompts' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Slide Styles' })).toBeVisible();
  });

  test('clicking Generator tab shows generator content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Generator' }).click();

    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });

  test('clicking Verification tab shows verification content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Verification' }).click();

    await expect(page.getByRole('heading', { name: 'What is Slide Verification?' })).toBeVisible();
  });

  test('clicking History tab shows history content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'History' }).click();

    await expect(page.getByRole('heading', { name: 'Session List' })).toBeVisible();
  });

  test('clicking Profiles tab shows profiles content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Profiles' }).click();

    await expect(page.getByRole('heading', { name: 'What are Profiles?' })).toBeVisible();
  });

  test('clicking Deck Prompts tab shows deck prompts content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Deck Prompts' }).click();

    await expect(page.getByRole('heading', { name: 'What are Deck Prompts?' })).toBeVisible();
  });

  test('clicking Slide Styles tab shows slide styles content', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Slide Styles' }).click();

    await expect(page.getByRole('heading', { name: 'What are Slide Styles?' })).toBeVisible();
  });
});

test.describe('QuickLinks', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('quick links visible in overview tab', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('button', { name: /Learn about Generator/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Learn about Verification/i })).toBeVisible();
  });

  test('clicking quick link navigates to corresponding tab', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: /Learn about Generator/i }).click();

    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });
});
```

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `npx playwright test tests/e2e/help-ui.spec.ts`
- [ ] No strict mode violations
- [ ] Tests cover: navigation, tabs, quick links, back button
- [ ] File committed to git

---

## Selector Tips

| Element | Likely Selector |
|---------|-----------------|
| Help nav button | `getByRole('navigation').getByRole('button', { name: 'Help' })` |
| Page heading | `getByRole('heading', { name: 'How to Use databricks tellr' })` |
| Back button | `getByRole('button', { name: 'Back' })` |
| Tab buttons | `getByRole('button', { name: 'TabName' })` |
| Quick links | `getByRole('button', { name: /Learn about/i })` |
| Section headings | `getByRole('heading', { name: 'Section Title' })` |

---

## Debug Commands

```bash
# Run with visible browser
npx playwright test tests/e2e/help-ui.spec.ts --headed

# Run single test
npx playwright test tests/e2e/help-ui.spec.ts -g "Help button"

# Debug mode
npx playwright test tests/e2e/help-ui.spec.ts --debug
```
