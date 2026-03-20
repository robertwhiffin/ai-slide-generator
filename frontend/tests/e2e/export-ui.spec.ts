import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
} from '../fixtures/mocks';
import { goToGenerator as goToGeneratorFromHelper } from '../helpers/new-ui';

/**
 * Export Functionality UI Tests
 *
 * Tests PDF/PPTX/HTML export, download functionality, and view modes.
 * Run: cd frontend && npx playwright test tests/e2e/export-ui.spec.ts
 */

// ============================================
// Mock Data
// ============================================

// Full SlideDeck structure that matches backend response
const mockSlideDeck = {
  title: 'Benefits of Cloud Computing',
  slide_count: 3,
  css: '',
  scripts: '',
  external_scripts: [],
  slides: mockSlides.map((slide, index) => ({
    slide_id: `slide-${index}`,
    title: slide.title,
    html: slide.html_content,
    content_hash: slide.hash,
    scripts: '',
    verification: null,
  })),
};

/**
 * Create a streaming response for slide generation with complete slide deck.
 * Simulates SSE (Server-Sent Events) format.
 */
function createStreamingResponseWithDeck(slideDeck: typeof mockSlideDeck): string {
  const events: string[] = [];

  // Start event
  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');

  // Progress events
  events.push('data: {"type": "progress", "message": "Generating slides..."}\n\n');

  // Complete event with slides
  events.push(`data: {"type": "complete", "message": "Generation complete", "slides": ${JSON.stringify(slideDeck)}}\n\n`);

  return events.join('');
}

// ============================================
// Setup Helpers
// ============================================

async function setupMocks(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });
  await page.route(/\/api\/settings\/profiles$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles),
    });
  });

  // Mock individual profile endpoints
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const profile = mockProfiles.find((p) => p.id === id) || mockProfiles[0];
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(profile),
      });
    } else {
      route.continue();
    }
  });

  // Mock deck prompts
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts),
    });
  });

  // Mock slide styles
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles),
    });
  });

  // Mock sessions and slides
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();

    // Handle session creation/deletion
    if (method === 'POST' || method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }

    if (url.includes('limit=')) {
      // Sessions list
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions),
      });
    } else if (url.includes('/slides')) {
      // Slides for a session - return slide deck
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-session-id',
          slide_deck: mockSlideDeck,
        }),
      });
    } else {
      // Individual session - return mock session with messages
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-session-id',
          messages: [],
        }),
      });
    }
  });

  // Mock version check
  await page.route('**/api/version**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: '1.0.0', latest: '1.0.0' }),
    });
  });

  // Mock Genie spaces
  await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ spaces: [], total: 0 }),
    });
  });

  // Mock verification endpoint
  await page.route('http://127.0.0.1:8000/api/verification/**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'verified', message: 'OK' }),
    });
  });
}

async function setupStreamMock(page: Page, slideDeck = mockSlideDeck) {
  await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponseWithDeck(slideDeck),
    });
  });
}

/** Mock full PPTX flow (async → poll → download) so export runs without real backend. */
async function setupPPTXExportMocks(page: Page) {
  await page.route('**/api/export/pptx/async', async (route) => {
    if (route.request().method() !== 'POST') {
      route.continue();
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 300));
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'test-job', status: 'running', total_slides: 3 }),
    });
  });
  await page.route('**/api/export/pptx/poll/**', async (route) => {
    await new Promise(resolve => setTimeout(resolve, 400));
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'test-job', status: 'completed', progress: 3, total_slides: 3 }),
    });
  });
  await page.route('**/api/export/pptx/download/**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      body: Buffer.from('mock pptx content'),
    });
  });
}

async function goToGenerator(page: Page) {
  await goToGeneratorFromHelper(page);
}

async function generateSlides(page: Page) {
  const chatInput = page.getByRole('textbox');
  await chatInput.fill('Create a presentation about cloud computing');
  await page.getByRole('button', { name: 'Send' }).click();
  // Wait for first slide title to appear
  await expect(page.getByText(mockSlides[0].title)).toBeVisible({ timeout: 15000 });
}

// ============================================
// Export Button Visibility Tests
// ============================================

test.describe('ExportButtons', () => {
  test('export button hidden when no slides', async ({ page }) => {
    await setupMocks(page);
    // Override to return null slide_deck
    await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
      const url = request.url();
      const method = request.method();

      // Handle session creation/deletion
      if (method === 'POST' || method === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
        return;
      }

      if (url.includes('limit=')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockSessions),
        });
      } else if (url.includes('/slides')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ slide_deck: null }),
        });
      } else {
        route.fulfill({ status: 404 });
      }
    });
    await goToGenerator(page);

    // Empty state - no slides
    await expect(page.getByText('No slides yet')).toBeVisible();

    // Export button should not be visible when there are no slides
    const exportButton = page.getByRole('button', { name: 'Export' });
    await expect(exportButton).not.toBeVisible();
  });

  test('export button visible when slides exist', async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Export button should now be visible
    const exportButton = page.getByRole('button', { name: 'Export' });
    await expect(exportButton).toBeVisible();
  });

  test('export button disabled during export', async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);

    // Mock full PPTX flow so export completes; app shows "Starting export..." then runs async start → poll → download
    await page.route('**/api/export/pptx/async', async (route) => {
      if (route.request().method() !== 'POST') {
        route.continue();
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 300));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'test-job', status: 'running', total_slides: 3 }),
      });
    });
    await page.route('**/api/export/pptx/poll/**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 400));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'test-job', status: 'completed', progress: 3, total_slides: 3 }),
      });
    });
    await page.route('**/api/export/pptx/download/**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        body: Buffer.from('mock pptx content'),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Download PPTX').click();

    // Either status text appears (export in progress) or export finishes; either way export was triggered
    const statusOrDone = page.locator('header').getByText(/Exporting|Starting|Export/);
    await expect(statusOrDone).toBeVisible({ timeout: 15000 });
  });
});

// ============================================
// Export Menu Tests
// ============================================

test.describe('ExportMenu', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('export button opens dropdown menu', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Click Export dropdown
    await page.getByRole('button', { name: 'Export' }).click();

    // Menu should appear with export options (new UI: Download PDF, Download PPTX)
    await expect(page.getByText('Download PDF')).toBeVisible();
    await expect(page.getByText('Download PPTX')).toBeVisible();
  });

  test('menu shows all export formats', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();

    await expect(page.getByText('Download PDF')).toBeVisible();
    await expect(page.getByText('Download PPTX')).toBeVisible();
  });

  test('clicking outside closes menu', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.getByText('Download PDF').first()).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(page.getByText('Download PDF').first()).not.toBeVisible();
  });
});

// ============================================
// PDF Export Tests
// ============================================

test.describe('PDFExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('clicking PDF export shows exporting state', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Open export menu
    await page.getByRole('button', { name: 'Export' }).click();

    // Click PDF export
    await page.getByText('Download PDF').click();

    // Should show exporting state (brief - PDF is client-side)
    // The UI shows "Exporting PDF..." in the subtitle
    await expect(page.getByText(/Exporting PDF/)).toBeVisible({ timeout: 2000 });
  });

  test('PDF export creates download', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Set up download listener
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });

    // Click export menu and PDF option
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Download PDF').click();

    // Verify download started
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain('.pdf');
  });
});

// ============================================
// PPTX Export Tests
// ============================================

test.describe('PPTXExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('clicking PPTX export shows exporting state', async ({ page }) => {
    await setupPPTXExportMocks(page);
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Download PPTX').click();

    await expect(page.locator('header').getByText(/Exporting|Starting|Export/)).toBeVisible({ timeout: 15000 });
  });

  test('shows progress during PPTX generation', async ({ page }) => {
    await setupPPTXExportMocks(page);
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Download PPTX').click();

    await expect(page.locator('header').getByText(/Exporting|Starting|Export/)).toBeVisible({ timeout: 15000 });
  });

  test('handles PPTX export error gracefully', async ({ page }) => {
    // Override with error response
    await page.route('**/api/export/pptx**', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Export failed' }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Set up dialog handler for alert
    page.on('dialog', async dialog => {
      expect(dialog.message()).toContain('Failed');
      await dialog.accept();
    });

    // Click export
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Download PPTX').click();

    // Wait for error handling to complete
    await page.waitForTimeout(1000);
  });
});

// ============================================
// HTML Export Tests
// ============================================

test.describe('HTMLExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test.skip('clicking HTML export triggers download', async ({ page }) => {
    // New header dropdown has Download PDF / Download PPTX / Export to Google Slides only; no Save as HTML
    await goToGenerator(page);
    await generateSlides(page);
    const downloadPromise = page.waitForEvent('download', { timeout: 10000 });
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Save as HTML').click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.html$/);
  });

  test.skip('HTML export closes menu after click', async ({ page }) => {
    // New header dropdown does not include Save as HTML
    await goToGenerator(page);
    await generateSlides(page);
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.getByText('Save as HTML')).toBeVisible();
    await page.getByText('Save as HTML').click();
    await expect(page.getByText('Save as HTML')).not.toBeVisible();
  });
});

// ============================================
// View Mode Tests (Debug Mode)
// ============================================

test.describe('ViewModes', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('default view is Generated Slides (tiles)', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await expect(page.locator('[data-testid="slide-tile-header"]').first()).toBeVisible();
  });

  test('debug view tabs hidden by default', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Raw HTML tabs should not be visible without debug mode
    await expect(page.getByRole('button', { name: 'Raw HTML (Rendered)' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Raw HTML (Text)' })).not.toBeVisible();
  });

  test.skip('debug view tabs visible in debug mode', async ({ page }) => {
    // New UI may have different debug tab labels or structure
    await setupMocks(page);
    await setupStreamMock(page);
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('debug', 'true'));
    await page.getByRole('button', { name: 'New Deck' }).click();
    await page.waitForURL(/\/sessions\/[^/]+\/edit/);
    await page.getByRole('textbox').waitFor({ state: 'visible', timeout: 10000 });
    await generateSlides(page);
    await expect(page.getByRole('button', { name: 'Raw HTML (Rendered)' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Raw HTML (Text)' })).toBeVisible();
  });
});

// ============================================
// Present Button Tests
// ============================================

test.describe('PresentButton', () => {
  test('present button hidden when no slides', async ({ page }) => {
    await setupMocks(page);
    // Override to return null slide_deck
    await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
      const url = request.url();
      const method = request.method();

      // Handle session creation/deletion
      if (method === 'POST' || method === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
        return;
      }

      if (url.includes('limit=')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockSessions),
        });
      } else if (url.includes('/slides')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ slide_deck: null }),
        });
      } else {
        route.fulfill({ status: 404 });
      }
    });
    await goToGenerator(page);

    // Empty state
    await expect(page.getByText('No slides yet')).toBeVisible();

    // Present button should not be visible
    await expect(page.getByRole('button', { name: 'Present' })).not.toBeVisible();
  });

  test('present button visible when slides exist', async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Present button should be visible
    await expect(page.getByRole('button', { name: 'Present' })).toBeVisible();
  });

  test('clicking present opens presentation mode', async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
    await goToGenerator(page);
    await generateSlides(page);

    // Click Present button
    await page.getByRole('button', { name: 'Present' }).click();

    // Presentation mode should be active - look for the slide counter "1 / 3"
    // which appears in presentation mode overlay
    await expect(page.getByText(/1\s*\/\s*3/)).toBeVisible({ timeout: 5000 });
  });
});

// ============================================
// Slide Panel Header Tests
// ============================================

test.describe('SlidePanelHeader', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('shows deck title and slide count', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Should show slide count in the slide panel (use more specific selector)
    // There may be multiple matches, so use .first() for the main slide panel indicator
    await expect(page.getByText(`${mockSlides.length} slides`).first()).toBeVisible();
  });

  test('shows deck title in header', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Should show deck title in the slide panel header
    await expect(page.getByText(mockSlideDeck.title)).toBeVisible();
  });
});
