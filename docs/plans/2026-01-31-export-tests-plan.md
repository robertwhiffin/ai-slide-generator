# Export Functionality Test Suite Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**Estimated Tests:** ~15 UI tests

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** `frontend/` directory

```bash
cd frontend
npx playwright test tests/e2e/export-ui.spec.ts
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
frontend/src/components/slides/SlidePanel.tsx       # Contains export buttons
frontend/src/components/slides/ExportMenu.tsx       # Export dropdown (if exists)
frontend/src/components/export/                     # Export-related components
frontend/src/api/export.ts                          # Export API calls (if exists)
```

Look for:
- Export buttons (PDF, PPTX, HTML)
- Download functionality
- Export progress indicators
- View mode switchers (tiles, raw HTML, raw text)

---

## Context: Export Flow

1. User generates slides via chat
2. Export buttons appear in SlidePanel toolbar/header
3. Clicking export triggers download
4. May show progress indicator for large decks
5. File downloads to user's browser

---

## API Endpoints

**GET `/api/export/pdf`** - Export deck as PDF
**GET `/api/export/pptx`** - Export deck as PowerPoint
**GET `/api/export/html`** - Export deck as HTML
**GET `/api/deck/render`** - Get rendered deck HTML

Response is typically a file download (blob) or URL to download.

---

## Mock Data

Add to `frontend/tests/fixtures/mocks.ts`:

```typescript
// Mock PDF export response (blob simulation)
export const mockPdfExportResponse = new Blob(['mock pdf content'], { type: 'application/pdf' });

// Mock PPTX export response
export const mockPptxExportResponse = new Blob(['mock pptx content'], {
  type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
});

// Mock export error
export const mockExportError = {
  detail: "Export failed: No slides to export"
};
```

---

## File to Create

**`frontend/tests/e2e/export-ui.spec.ts`**

---

## Test Categories

### 1. Export Button Visibility Tests

```typescript
test.describe('ExportButtons', () => {
  test('export buttons hidden when no slides', async ({ page }) => {
    await setupMocks(page);
    await goToGenerator(page);

    // Empty state - no slides
    // Export buttons should not be visible or be disabled
    const pdfButton = page.getByRole('button', { name: /pdf|export.*pdf/i });
    await expect(pdfButton).not.toBeVisible();
    // OR await expect(pdfButton).toBeDisabled();
  });

  test('export buttons visible when slides exist', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Export buttons should now be visible
    await expect(page.getByRole('button', { name: /pdf|export.*pdf/i })).toBeVisible();
  });

  test('shows PDF export option', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Look for PDF button or menu item
    await expect(page.getByRole('button', { name: /pdf/i })).toBeVisible();
    // OR if in dropdown:
    // await page.getByRole('button', { name: /export/i }).click();
    // await expect(page.getByRole('menuitem', { name: /pdf/i })).toBeVisible();
  });

  test('shows PPTX export option', async ({ page }) => {
    // Similar to PDF
  });

  test('shows HTML export option if available', async ({ page }) => {
    // If HTML export exists
  });
});
```

### 2. Export Menu Tests (if dropdown menu exists)

```typescript
test.describe('ExportMenu', () => {
  test('export button opens dropdown menu', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Click export dropdown
    await page.getByRole('button', { name: /export/i }).click();

    // Menu should appear
    await expect(page.getByRole('menu')).toBeVisible();
  });

  test('menu shows all export formats', async ({ page }) => {
    // PDF, PPTX, possibly HTML
  });

  test('clicking outside closes menu', async ({ page }) => {
    // Close menu by clicking elsewhere
  });
});
```

### 3. PDF Export Tests

```typescript
test.describe('PDFExport', () => {
  test('clicking PDF export triggers download', async ({ page }) => {
    await setupWithSlides(page);

    // Mock the PDF endpoint to return a blob
    await page.route('**/api/export/pdf**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: Buffer.from('mock pdf content'),
        headers: {
          'Content-Disposition': 'attachment; filename="presentation.pdf"'
        }
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Set up download listener
    const downloadPromise = page.waitForEvent('download');

    // Click PDF export
    await page.getByRole('button', { name: /pdf/i }).click();

    // Verify download started
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain('.pdf');
  });

  test('shows loading indicator during PDF generation', async ({ page }) => {
    // Mock slow response
    await page.route('**/api/export/pdf**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: Buffer.from('mock pdf'),
      });
    });

    // Click export - should show loading
    await page.getByRole('button', { name: /pdf/i }).click();
    await expect(page.getByText(/exporting|generating|loading/i)).toBeVisible();
  });

  test('handles PDF export error gracefully', async ({ page }) => {
    await page.route('**/api/export/pdf**', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Export failed' }),
      });
    });

    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: /pdf/i }).click();

    // Should show error message
    await expect(page.getByText(/error|failed/i)).toBeVisible();
  });
});
```

### 4. PPTX Export Tests

```typescript
test.describe('PPTXExport', () => {
  test('clicking PPTX export triggers download', async ({ page }) => {
    await setupWithSlides(page);

    await page.route('**/api/export/pptx**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        body: Buffer.from('mock pptx content'),
        headers: {
          'Content-Disposition': 'attachment; filename="presentation.pptx"'
        }
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /pptx|powerpoint/i }).click();

    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.pptx$/);
  });

  test('handles PPTX export error gracefully', async ({ page }) => {
    // Similar to PDF error test
  });
});
```

### 5. View Mode Tests (if applicable)

```typescript
test.describe('ViewModes', () => {
  test('can switch to raw HTML view', async ({ page }) => {
    await setupWithSlides(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Look for view mode toggle/buttons
    await page.getByRole('button', { name: /html|raw/i }).click();

    // Should show HTML code view
    await expect(page.locator('pre, code, .monaco-editor')).toBeVisible();
  });

  test('can switch to raw text view', async ({ page }) => {
    // If text view exists
  });

  test('can switch back to tile view', async ({ page }) => {
    // Return to default view
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
 * Export Functionality UI Tests
 *
 * Tests PDF/PPTX export, download functionality, and view modes.
 * Run: cd frontend && npx playwright test tests/e2e/export-ui.spec.ts
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

async function setupWithSlides(page: Page) {
  await setupMocks(page);

  await page.route('http://localhost:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides),
    });
  });

  // Default export mocks
  await page.route('**/api/export/pdf**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: Buffer.from('mock pdf content'),
      headers: { 'Content-Disposition': 'attachment; filename="presentation.pdf"' }
    });
  });

  await page.route('**/api/export/pptx**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      body: Buffer.from('mock pptx content'),
      headers: { 'Content-Disposition': 'attachment; filename="presentation.pptx"' }
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

test.describe('ExportButtons', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('PDFExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('PPTXExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests
});

test.describe('ViewModes', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  // Implement tests - if view modes exist
});
```

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `npx playwright test tests/e2e/export-ui.spec.ts`
- [ ] No strict mode violations
- [ ] Tests cover: button visibility, PDF export, PPTX export, errors
- [ ] File committed to git

---

## Selector Tips

| Element | Likely Selector |
|---------|-----------------|
| Export button/dropdown | `getByRole('button', { name: /export/i })` |
| PDF option | `getByRole('button', { name: /pdf/i })` or `getByRole('menuitem', { name: /pdf/i })` |
| PPTX option | `getByRole('button', { name: /pptx|powerpoint/i })` |
| Export menu | `getByRole('menu')` |
| Loading indicator | `getByText(/exporting|generating/i)` |
| View mode toggle | Look for tabs or button group |

---

## Download Testing Pattern

```typescript
// Wait for download event
const downloadPromise = page.waitForEvent('download');
await page.getByRole('button', { name: /pdf/i }).click();
const download = await downloadPromise;

// Verify download
expect(download.suggestedFilename()).toContain('.pdf');

// Optionally save and verify content
const path = await download.path();
// Read file if needed
```

---

## Debug Commands

```bash
# Run with visible browser
npx playwright test tests/e2e/export-ui.spec.ts --headed

# Run single test
npx playwright test tests/e2e/export-ui.spec.ts -g "PDF export"

# Debug mode
npx playwright test tests/e2e/export-ui.spec.ts --debug
```
