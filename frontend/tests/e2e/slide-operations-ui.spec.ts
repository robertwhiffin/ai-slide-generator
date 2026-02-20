import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
} from '../fixtures/mocks';
import { goToGenerator } from '../helpers/new-ui';

/**
 * Slide Operations UI Tests
 *
 * Tests slide display, selection, deletion, editing, and verification.
 * Run: cd frontend && npx playwright test tests/e2e/slide-operations-ui.spec.ts
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

async function setupWithSlides(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockProfiles),
      });
    } else {
      route.continue();
    }
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

  // Mock sessions endpoints
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
      body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }),
    });
  });

  // Mock chat stream to generate slides
  await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponseWithDeck(mockSlideDeck),
    });
  });

  // Mock slide operations (DELETE, PUT)
  await page.route(/http:\/\/127.0.0.1:8000\/api\/slides\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted' }),
      });
    } else if (request.method() === 'PUT') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlides[0]),
      });
    } else {
      route.continue();
    }
  });

  // Mock verification endpoint
  await page.route(/http:\/\/127.0.0.1:8000\/api\/verification/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        score: 0.95,
        rating: 'green',
        explanation: 'Slide content verified successfully',
        issues: [],
        duration_ms: 150,
        error: false,
      }),
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

  // Mock Genie link
  await page.route(/http:\/\/127.0.0.1:8000\/api\/genie\/.*\/link/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ url: 'https://example.com/genie', message: null }),
    });
  });

  // Mock reorder endpoint
  await page.route('http://127.0.0.1:8000/api/slides/reorder**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });
}

// goToGenerator imported from helpers/new-ui

async function generateSlides(page: Page) {
  const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
  await chatInput.fill('Create a presentation about cloud computing');
  await page.getByRole('button', { name: 'Send' }).click();
  // Wait for first slide title to appear
  await expect(page.getByText(mockSlides[0].title)).toBeVisible({ timeout: 15000 });
}

// ============================================
// Slide Display Tests
// ============================================

test.describe('SlideDisplay', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('displays slide tiles after generation', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Should show all 3 slide headers - use the slide header text specifically
    // The slide header has class text-sm font-medium text-gray-700
    const slideHeaders = page.locator('[data-testid="slide-tile-header"]');
    await expect(slideHeaders.getByText('Slide 1')).toBeVisible();
    await expect(slideHeaders.getByText('Slide 2')).toBeVisible();
    await expect(slideHeaders.getByText('Slide 3')).toBeVisible();

    // Slides should have iframes for preview (there may be more than 3 due to thumbnails)
    const iframes = page.locator('iframe[title^="Slide"]');
    await expect(iframes.first()).toBeVisible();
  });

  test('shows slide index/number', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Verify slide numbers are displayed (Slide 1, Slide 2, Slide 3)
    // Use more specific selector to avoid matching thumbnail previews
    const slideHeaders = page.locator('[data-testid="slide-tile-header"]');
    await expect(slideHeaders.getByText('Slide 1')).toBeVisible();
    await expect(slideHeaders.getByText('Slide 2')).toBeVisible();
    await expect(slideHeaders.getByText('Slide 3')).toBeVisible();
  });

  test('shows slide count in header', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Should show "3 slides" in the panel header - use the specific gray text element
    await expect(page.getByText('3 slides').first()).toBeVisible();
  });

  test('displays slide deck title in header', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await expect(page.locator('header').getByText(/Benefits of Cloud Computing/i)).toBeVisible();
  });
});

// ============================================
// Slide Selection Tests
// ============================================

test.describe('SlideSelection', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('clicking chat context button selects slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Find the first slide's "Add to chat context" button (FiMessageSquare icon button)
    // The button is in the slide header actions area
    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    const chatContextButton = firstSlideHeader.locator('button[aria-pressed]');

    await chatContextButton.click();

    // Button should now show as selected (aria-pressed="true")
    await expect(chatContextButton).toHaveAttribute('aria-pressed', 'true');
  });

  test('selected slide shows visual indicator', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Click the chat context button to select the slide
    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    const chatContextButton = firstSlideHeader.locator('button[aria-pressed]');
    await chatContextButton.click();

    // The slide container should have a ring-2 ring-blue-500 class when selected
    const slideContainer = page.locator('.ring-2.ring-blue-500');
    await expect(slideContainer).toBeVisible();
  });

  test('selecting different slide changes selection', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Select first slide
    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    const firstChatContextButton = firstSlideHeader.locator('button[aria-pressed]');
    await firstChatContextButton.click();

    // Verify first slide is selected
    await expect(firstChatContextButton).toHaveAttribute('aria-pressed', 'true');

    // Select second slide
    const secondSlideHeader = page.locator('[data-testid="slide-tile-header"]').nth(1);
    const secondChatContextButton = secondSlideHeader.locator('button[aria-pressed]');
    await secondChatContextButton.click();

    // Second slide should be selected
    await expect(secondChatContextButton).toHaveAttribute('aria-pressed', 'true');
    // First slide should be deselected (only one selected at a time)
    await expect(firstChatContextButton).toHaveAttribute('aria-pressed', 'false');
  });
});

// ============================================
// Delete Slide Tests
// ============================================

test.describe('DeleteSlide', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('delete button is visible on each slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const deleteButtons = page.locator('[data-testid="slide-tile-header"]').getByRole('button', { name: 'Delete' });
    await expect(deleteButtons).toHaveCount(3);
  });

  test('clicking delete opens confirmation dialog', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    page.on('dialog', async dialog => {
      expect(dialog.message()).toContain('Delete slide 1?');
      await dialog.dismiss();
    });

    const deleteButton = page.locator('[data-testid="slide-tile-header"]').first().getByRole('button', { name: 'Delete' });
    await deleteButton.click();
  });

  test('confirming delete removes the slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const slidesAfterDelete = mockSlides.slice(1);
    const twoSlideDeck = {
      title: 'Benefits of Cloud Computing',
      slide_count: 2,
      css: '',
      scripts: '',
      external_scripts: [],
      slides: slidesAfterDelete.map((s, i) => ({
        index: i,
        slide_id: `slide-${i}`,
        title: s.title,
        html: s.html_content,
        content_hash: s.hash,
        scripts: '',
        verification: null,
      })),
    };

    // App calls DELETE then GET sessions/:id/slides; we must return 2-slide deck from GET
    let deleteDone = false;
    await page.route('**/api/slides/*', (route) => {
      if (route.request().method() === 'DELETE') {
        deleteDone = true;
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'deleted' }),
        });
      } else {
        route.continue();
      }
    });
    await page.route('**/api/sessions/*/slides', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            session_id: 'test-session-id',
            slide_deck: deleteDone ? twoSlideDeck : mockSlideDeck,
          }),
        });
      } else {
        route.continue();
      }
    });

    page.on('dialog', async dialog => {
      await dialog.accept();
    });

    const deleteButton = page.locator('[data-testid="slide-tile-header"]').first().getByRole('button', { name: 'Delete' });
    await deleteButton.click();

    await expect(page.getByText('2 slides').first()).toBeVisible({ timeout: 5000 });
  });

  test('canceling delete keeps the slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Handle the confirmation dialog - dismiss it
    page.on('dialog', async dialog => {
      await dialog.dismiss();
    });

    const deleteButton = page.locator('[data-testid="slide-tile-header"]').first().getByRole('button', { name: 'Delete' });
    await deleteButton.click();

    // Slide count should remain 3 - use specific selector
    await expect(page.getByText('3 slides').first()).toBeVisible();

    await expect(page.locator('header').getByText(/Benefits of Cloud Computing/i)).toBeVisible();
  });
});

// ============================================
// Edit Slide Tests
// ============================================

test.describe('EditSlide', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('edit button is visible on each slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Each slide should have an edit button (blue color, FiEdit icon)
    const editButtons = page.locator('button.text-blue-600').filter({ has: page.locator('svg') });
    // Filter to only include edit buttons (not other blue buttons)
    const slideEditButtons = page.locator('[data-testid="slide-tile-header"] button');
    await expect(slideEditButtons.first()).toBeVisible();
  });

  test('clicking edit opens HTML editor modal', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    await firstSlideHeader.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide' })).toBeVisible();
  });

  test('editor modal has save and cancel buttons', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    await firstSlideHeader.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('button', { name: 'Save Changes' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
  });

  test('cancel closes modal without saving', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    await firstSlideHeader.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: 'Edit Slide' })).not.toBeVisible();
  });

  test('X button closes modal', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    const firstSlideHeader = page.locator('[data-testid="slide-tile-header"]').first();
    await firstSlideHeader.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide' })).toBeVisible();
    await page.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('heading', { name: 'Edit Slide' })).not.toBeVisible();
  });
});

// ============================================
// Verification Tests
// ============================================

test.describe('SlideVerification', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('verify button is visible when no verification exists', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Look for the verify button (amber-colored button with gavel icon)
    // The button appears when there's no verification result
    const verifyButton = page.locator('button.text-amber-600').first();
    await expect(verifyButton).toBeVisible();
  });

  test('clicking verify shows verifying state', async ({ page }) => {
    // Delay the verification response to see the verifying state
    await page.route(/http:\/\/127.0.0.1:8000\/api\/verification/, async (route) => {
      await new Promise(resolve => setTimeout(resolve, 500));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          score: 0.95,
          rating: 'green',
          explanation: 'Slide content verified successfully',
          issues: [],
          duration_ms: 150,
          error: false,
        }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Click verify button
    const verifyButton = page.locator('button.text-amber-600').first();
    await verifyButton.click();

    // Should show "Verifying..." text
    await expect(page.getByText('Verifying...')).toBeVisible();
  });

  test('verification badge appears after verification', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Click verify button on first slide
    const verifyButton = page.locator('button.text-amber-600').first();
    await verifyButton.click();

    // Wait for verification badge to appear
    // The badge shows the rating label - for 'green' rating it shows "No issues"
    await expect(page.getByText('No issues').first()).toBeVisible({ timeout: 5000 });
  });
});

// ============================================
// Drag and Drop / Reorder Tests
// ============================================

test.describe('SlideReorder', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('drag handle is visible on each slide', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Each slide should have a drag handle button
    // The drag handle has cursor-grab class
    const dragHandles = page.locator('button.cursor-grab');
    await expect(dragHandles).toHaveCount(3);
  });
});

// ============================================
// Presentation Mode Tests
// ============================================

test.describe('PresentationMode', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('present button is visible when slides exist', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Present button should be visible
    await expect(page.getByRole('button', { name: 'Present' })).toBeVisible();
  });

  test('clicking present opens presentation mode', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Click Present button
    await page.getByRole('button', { name: 'Present' }).click();

    // Presentation mode should open - it uses createPortal with inline styles
    // Look for the slide counter which appears at the bottom
    // It shows "1 / 3" format
    await expect(page.getByText('1 / 3')).toBeVisible({ timeout: 5000 });
  });
});

// ============================================
// Export Tests
// ============================================

test.describe('SlideExport', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithSlides(page);
  });

  test('export button is visible when slides exist', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    // Export button should be visible
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
  });

  test('clicking export opens export menu', async ({ page }) => {
    await goToGenerator(page);
    await generateSlides(page);

    await page.getByRole('button', { name: 'Export' }).click();

    await expect(page.getByText('Download PDF')).toBeVisible();
    await expect(page.getByText('Download PPTX')).toBeVisible();
  });
});
