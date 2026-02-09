import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
} from '../fixtures/mocks';

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
  // Mock profiles endpoint
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
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

async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
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

    // Mock slow PPTX export
    await page.route('**/api/export/pptx**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 5000));
      route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        body: Buffer.from('mock pptx content'),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Click Export to open menu
    await page.getByRole('button', { name: 'Export' }).click();

    // Click PPTX export
    await page.getByText('Export as PowerPoint').click();

    // Export button should show loading state
    await expect(page.getByText('Exporting...')).toBeVisible();
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

    // Menu should appear with export options
    await expect(page.getByText('Export as PDF')).toBeVisible();
    await expect(page.getByText('Export as PowerPoint')).toBeVisible();
    await expect(page.getByText('Save as HTML')).toBeVisible();
  });

  test('menu shows all export formats', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();

    // Should show PDF, PPTX, and HTML options
    await expect(page.getByText('Export as PDF')).toBeVisible();
    await expect(page.getByText('Export as PowerPoint')).toBeVisible();
    await expect(page.getByText('Save as HTML')).toBeVisible();
  });

  test('clicking outside closes menu', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Open menu
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.getByText('Export as PDF')).toBeVisible();

    // Click outside (on the header area)
    await page.locator('header').click({ position: { x: 10, y: 10 } });

    // Menu should close
    await expect(page.getByText('Export as PDF')).not.toBeVisible();
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
    await page.getByText('Export as PDF').click();

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
    await page.getByText('Export as PDF').click();

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
    await goToGenerator(page);
    await generateSlides(page);

    // Click export menu and PPTX option
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Export as PowerPoint').click();

    // Should show exporting state (the button changes to "Exporting...")
    await expect(page.getByText('Exporting...')).toBeVisible();
  });

  test('shows progress during PPTX generation', async ({ page }) => {
    // Override with slower mock
    await page.route('**/api/export/pptx**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        body: Buffer.from('mock pptx content'),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Click export
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Export as PowerPoint').click();

    // Should show exporting state
    await expect(page.getByText('Exporting...')).toBeVisible();
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
    await page.getByText('Export as PowerPoint').click();

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

  test('clicking HTML export triggers download', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Set up download listener
    const downloadPromise = page.waitForEvent('download', { timeout: 10000 });

    // Click export menu and HTML option
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Save as HTML').click();

    // Verify download started
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.html$/);
  });

  test('HTML export closes menu after click', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Open menu
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.getByText('Save as HTML')).toBeVisible();

    // Click HTML export
    await page.getByText('Save as HTML').click();

    // Menu should close
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

    // Generated Slides tab should be active
    const tilesTab = page.getByRole('button', { name: 'Generated Slides' });
    await expect(tilesTab).toBeVisible();
    // Check if it has the active state (blue color)
    await expect(tilesTab).toHaveClass(/text-blue-600/);
  });

  test('debug view tabs hidden by default', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Raw HTML tabs should not be visible without debug mode
    await expect(page.getByRole('button', { name: 'Raw HTML (Rendered)' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Raw HTML (Text)' })).not.toBeVisible();
  });

  test('debug view tabs visible in debug mode', async ({ page }) => {
    // Enable debug mode via URL - need to set up mocks before goto
    await setupMocks(page);
    await setupStreamMock(page);
    await page.goto('/?debug=true');
    await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
    await generateSlides(page);

    // Raw HTML tabs should now be visible (but disabled until we have raw HTML)
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
