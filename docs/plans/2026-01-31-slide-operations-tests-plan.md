# Slide Operations Test Suite Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**Estimated Tests:** ~25 UI tests

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** `frontend/` directory

```bash
cd frontend
npx playwright test tests/e2e/slide-operations-ui.spec.ts
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **Working test example:** `frontend/tests/e2e/profile-ui.spec.ts`
2. **Mock patterns:** `frontend/tests/fixtures/mocks.ts`
3. **Deck integrity tests:** `frontend/tests/e2e/deck-integrity.spec.ts`

---

## Discovery: Read These Component Files

```
frontend/src/components/slides/SlideTile.tsx         # Individual slide card
frontend/src/components/slides/SlidePanel.tsx        # Slide container/grid
frontend/src/components/slides/SlideSelection.tsx    # Selection state management
frontend/src/components/slides/SelectionRibbon.tsx   # Multi-select actions bar
frontend/src/components/slides/VerificationBadge.tsx # Verification status
frontend/src/components/modals/HTMLEditorModal.tsx   # Edit slide HTML
frontend/src/components/modals/ConfirmDialog.tsx     # Delete confirmation
```

---

## Context: How Slides Work

1. User sends a chat message → slides are generated
2. Slides appear in SlidePanel as SlideTile components
3. Each slide can be: selected, deleted, edited, verified
4. Multi-select enables batch operations via SelectionRibbon

**Important:** Tests need slides to exist first. Either:
- Mock the chat stream to generate slides, OR
- Mock the session/slides endpoint to return existing slides

---

## API Endpoints

**DELETE `/api/slides/{slide_id}`** - Delete a slide
**PUT `/api/slides/{slide_id}`** - Update slide content
**POST `/api/verification/{slide_id}`** - Verify slide data
**GET `/api/sessions/{id}/slides`** - Get slides for a session

---

## Mock Data

Add to `frontend/tests/fixtures/mocks.ts` if not present:

```typescript
// Mock slide deletion response
export const mockSlideDeleteResponse = {
  status: 'deleted',
  slide_id: 1
};

// Mock slide update response
export const mockSlideUpdateResponse = {
  index: 0,
  title: "Updated Slide Title",
  html_content: "<div class='slide'>Updated content</div>",
  verification_status: "pending",
  hash: "abc123"
};

// Mock verification response
export const mockVerificationResponse = {
  status: "verified",
  message: "Slide verified successfully",
  score: 0.95
};
```

---

## File to Create

**`frontend/tests/e2e/slide-operations-ui.spec.ts`**

---

## Test Setup Pattern

Since slide operations require existing slides, use this setup:

```typescript
async function setupWithSlides(page: Page) {
  // Mock all settings endpoints
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
  });
  // ... other settings mocks ...

  // Mock chat stream to generate slides
  await page.route('http://localhost:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides),
    });
  });

  // Mock slide operations
  await page.route(/http:\/\/localhost:8000\/api\/slides\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'deleted' }) });
    } else if (request.method() === 'PUT') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideUpdateResponse) });
    }
  });

  // Mock verification
  await page.route(/http:\/\/localhost:8000\/api\/verification\/\d+/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockVerificationResponse) });
  });
}

async function generateSlides(page: Page) {
  await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create a presentation');
  await page.getByRole('button', { name: 'Send' }).click();
  // Wait for slides to appear
  await expect(page.getByText(mockSlides[0].title)).toBeVisible({ timeout: 10000 });
}
```

---

## Test Categories

### 1. Slide Display Tests

```typescript
test.describe('SlideDisplay', () => {
  test('displays slide tiles after generation', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Should show all 3 mock slides
    await expect(page.getByText('Benefits of Cloud Computing')).toBeVisible();
    await expect(page.getByText('Cost Savings Drive Cloud Adoption')).toBeVisible();
    await expect(page.getByText('Key Benefits Beyond Cost')).toBeVisible();
  });

  test('shows slide index/number', async ({ page }) => {
    // Verify slide numbers are displayed (1, 2, 3...)
  });

  test('shows verification badge on each slide', async ({ page }) => {
    // Look for verification status indicator
  });

  test('displays slide thumbnail/preview', async ({ page }) => {
    // Verify slide content preview is shown
  });
});
```

### 2. Slide Selection Tests

```typescript
test.describe('SlideSelection', () => {
  test('clicking slide selects it', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Click on first slide
    await page.locator('[data-testid="slide-tile"]').first().click();
    // OR find by slide title and click

    // Should show selection indicator (border, checkmark, etc)
    // Explore component to find exact selection indicator
  });

  test('selected slide shows visual indicator', async ({ page }) => {
    // Look for selected state styling
  });

  test('clicking selected slide deselects it', async ({ page }) => {
    // Toggle selection off
  });

  test('can select multiple slides with shift/ctrl', async ({ page }) => {
    // Multi-select behavior
  });

  test('selection ribbon appears with multiple selections', async ({ page }) => {
    // SelectionRibbon should appear
  });
});
```

### 3. Delete Slide Tests

```typescript
test.describe('DeleteSlide', () => {
  test('delete button appears on slide hover or selection', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Hover over slide or select it
    const firstSlide = page.locator('[data-testid="slide-tile"]').first();
    await firstSlide.hover();

    // Delete button should be visible
    await expect(page.getByRole('button', { name: /delete/i }).first()).toBeVisible();
  });

  test('clicking delete opens confirmation dialog', async ({ page }) => {
    // Click delete button
    // Confirmation dialog should appear
    await expect(page.getByRole('heading', { name: /delete|confirm/i })).toBeVisible();
  });

  test('confirmation dialog shows slide info', async ({ page }) => {
    // Dialog should mention which slide is being deleted
  });

  test('cancel closes dialog without deleting', async ({ page }) => {
    // Click Cancel - dialog closes, slide remains
  });

  test('confirm deletes the slide', async ({ page }) => {
    // Click Confirm - slide should be removed from list
  });

  test('slide count decreases after deletion', async ({ page }) => {
    // Verify count goes from 3 to 2
  });
});
```

### 4. Edit Slide Tests

```typescript
test.describe('EditSlide', () => {
  test('edit button appears on slide', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Look for edit button on slide
    const firstSlide = page.locator('[data-testid="slide-tile"]').first();
    await firstSlide.hover();

    await expect(page.getByRole('button', { name: /edit/i }).first()).toBeVisible();
  });

  test('clicking edit opens HTML editor modal', async ({ page }) => {
    // Click edit
    // Modal with HTML editor should open
    await expect(page.getByRole('heading', { name: /edit.*html|html.*editor/i })).toBeVisible();
  });

  test('editor shows current slide HTML', async ({ page }) => {
    // Editor should be pre-filled with slide content
  });

  test('can modify HTML in editor', async ({ page }) => {
    // Type/modify content in editor
  });

  test('save button updates slide', async ({ page }) => {
    // Save changes - modal closes, slide updates
  });

  test('cancel discards changes', async ({ page }) => {
    // Cancel - modal closes, slide unchanged
  });
});
```

### 5. Verification Tests

```typescript
test.describe('SlideVerification', () => {
  test('verification badge shows status', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Look for verification badge/icon on slides
    // mockSlides have verification_status field
  });

  test('verify button triggers verification', async ({ page }) => {
    // Click verify button if present
  });

  test('verification updates badge after completion', async ({ page }) => {
    // Badge should change after verification
  });

  test('shows verification score or details', async ({ page }) => {
    // If verification details are displayed
  });
});
```

### 6. Batch Operations Tests (if SelectionRibbon exists)

```typescript
test.describe('BatchOperations', () => {
  test('selection ribbon shows selected count', async ({ page }) => {
    // Select multiple slides
    // Ribbon should show "2 selected" or similar
  });

  test('batch delete button in ribbon', async ({ page }) => {
    // Delete all selected
  });

  test('deselect all button clears selection', async ({ page }) => {
    // Clear selection
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
  mockSlides,
  createStreamingResponse,
} from '../fixtures/mocks';

/**
 * Slide Operations UI Tests
 *
 * Tests slide display, selection, deletion, editing, and verification.
 * Run: cd frontend && npx playwright test tests/e2e/slide-operations-ui.spec.ts
 */

async function setupWithSlides(page: Page) {
  // Mock settings
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

  // Mock chat stream
  await page.route('http://localhost:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides),
    });
  });

  // Mock slide operations
  await page.route(/http:\/\/localhost:8000\/api\/slides\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'deleted' }) });
    } else if (request.method() === 'PUT') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlides[0]) });
    } else {
      route.continue();
    }
  });

  // Mock verification
  await page.route(/http:\/\/localhost:8000\/api\/verification/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'verified', message: 'OK', score: 0.95 }),
    });
  });
}

async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

async function generateSlides(page: Page) {
  await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create a presentation');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText(mockSlides[0].title)).toBeVisible({ timeout: 10000 });
}

test.describe('SlideDisplay', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('SlideSelection', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('DeleteSlide', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('EditSlide', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('SlideVerification', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});
```

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `npx playwright test tests/e2e/slide-operations-ui.spec.ts`
- [ ] No strict mode violations
- [ ] Tests cover: display, selection, delete, edit, verify
- [ ] File committed to git

---

## Selector Tips

| Element | Likely Selector |
|---------|-----------------|
| Slide tile | `[data-testid="slide-tile"]` or explore component |
| Delete button | `getByRole('button', { name: /delete/i })` scoped to slide |
| Edit button | `getByRole('button', { name: /edit/i })` scoped to slide |
| Verify button | `getByRole('button', { name: /verify/i })` |
| Confirmation dialog | `getByRole('heading', { name: /confirm|delete/i })` |
| HTML editor | `getByRole('textbox')` inside modal, or Monaco editor |
| Selection ribbon | Look for fixed/sticky bar at bottom |

---

## Debug Commands

```bash
# Run with visible browser
npx playwright test tests/e2e/slide-operations-ui.spec.ts --headed

# Run single test
npx playwright test tests/e2e/slide-operations-ui.spec.ts -g "delete button"

# Debug mode
npx playwright test tests/e2e/slide-operations-ui.spec.ts --debug
```
