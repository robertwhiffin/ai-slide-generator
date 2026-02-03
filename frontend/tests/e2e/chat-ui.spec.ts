import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
} from '../fixtures/mocks';

/**
 * Chat UI Tests
 *
 * Tests chat input, message display, loading states, and slide generation.
 * Run: cd frontend && npx playwright test tests/e2e/chat-ui.spec.ts
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

// ============================================
// ChatInput Tests
// ============================================

test.describe('ChatInput', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('displays chat input field', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('textbox')).toBeVisible();
  });

  test('shows placeholder text in input', async ({ page }) => {
    await goToGenerator(page);
    const input = page.getByRole('textbox');
    await expect(input).toHaveAttribute('placeholder', /Ask.*to.*generate|create slides/i);
  });

  test('Send button is disabled when input is empty', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('Send button is enabled when input has text', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create a presentation');
    await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  });

  test('input clears after sending message', async ({ page }) => {
    await goToGenerator(page);
    const input = page.getByRole('textbox');
    await input.fill('Create a presentation');
    await page.getByRole('button', { name: 'Send' }).click();

    // Input should clear after send
    await expect(input).toHaveValue('');
  });

  test('can submit with Enter key', async ({ page }) => {
    await goToGenerator(page);
    const input = page.getByRole('textbox');
    await input.fill('Create a presentation');
    await input.press('Enter');

    // Input should clear after submit
    await expect(input).toHaveValue('');
  });

  test('Shift+Enter adds new line instead of submitting', async ({ page }) => {
    await goToGenerator(page);
    const input = page.getByRole('textbox');
    await input.fill('Line 1');
    await input.press('Shift+Enter');
    await input.type('Line 2');

    // Should have both lines in the input
    const value = await input.inputValue();
    expect(value).toContain('Line 1');
    expect(value).toContain('Line 2');
    expect(value.split('\n').length).toBeGreaterThan(1);
  });

  test('shows expand button for editor modal', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('button', { name: /expand/i })).toBeVisible();
  });
});

// ============================================
// MessageList Tests
// ============================================

test.describe('MessageList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('displays user message after sending', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides about cloud computing');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for user message to appear
    await expect(page.getByText('Create slides about cloud computing')).toBeVisible({ timeout: 5000 });
  });

  test('displays "You" label for user messages', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should see "You" label for user message (exact match to avoid tooltip matches)
    await expect(page.getByText('You', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('messages appear in chronological order', async ({ page }) => {
    await goToGenerator(page);

    // Send first message
    await page.getByRole('textbox').fill('First message');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for first message to appear
    await expect(page.getByText('First message')).toBeVisible({ timeout: 5000 });

    // Wait for slides to appear (indicates first generation complete)
    await expect(page.locator('.text-gray-500').filter({ hasText: /3 slides?/ })).toBeVisible({ timeout: 15000 });

    // Send second message
    await page.getByRole('textbox').fill('Second message');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for second message to appear
    await expect(page.getByText('Second message')).toBeVisible({ timeout: 5000 });

    // Both user messages should be visible
    await expect(page.getByText('First message')).toBeVisible();
    await expect(page.getByText('Second message')).toBeVisible();
  });
});

// ============================================
// LoadingStates Tests
// ============================================

test.describe('LoadingStates', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('shows loading indicator while generating', async ({ page }) => {
    // Mock a slow response to observe loading state
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponseWithDeck(mockSlideDeck),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should show loading indicator (from MessageList)
    await expect(page.getByText(/Generating slides/i)).toBeVisible({ timeout: 2000 });
  });

  test('Send button is disabled while generating', async ({ page }) => {
    // Mock a slow response
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 3000));
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponseWithDeck(mockSlideDeck),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Button should be disabled during generation
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('loading indicator disappears when complete', async ({ page }) => {
    await setupStreamMock(page);

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for completion (slides appear)
    await expect(page.locator('.text-gray-500').filter({ hasText: /3 slides?/ })).toBeVisible({ timeout: 15000 });

    // Loading indicator should be gone (MessageList loading spinner)
    await expect(page.getByText(/Generating slides/i)).not.toBeVisible();
  });

  test('shows rotating loading messages', async ({ page }) => {
    // Mock a slow response to observe loading messages
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 5000));
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponseWithDeck(mockSlideDeck),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should show some loading message in the LoadingIndicator component
    await expect(page.locator('.bg-blue-50').getByText(/./)).toBeVisible({ timeout: 2000 });
  });
});

// ============================================
// SlideGeneration Tests
// ============================================

test.describe('SlideGeneration', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('slides appear after generation completes', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides about cloud computing');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for slides to appear
    await expect(page.getByText('Benefits of Cloud Computing')).toBeVisible({ timeout: 10000 });
  });

  test('shows correct number of slides', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for slides panel to show slide count in the panel header (gray text)
    await expect(page.locator('.text-gray-500').filter({ hasText: /3 slides?/ })).toBeVisible({ timeout: 10000 });
  });

  test('slide deck title appears in panel header', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // The deck title should appear in the slide panel header as an h2
    await expect(page.getByRole('heading', { name: 'Benefits of Cloud Computing', level: 2 })).toBeVisible({ timeout: 10000 });
  });
});

// ============================================
// EmptyState Tests
// ============================================

test.describe('EmptyState', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('shows empty state message before any slides', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByText('No slides yet')).toBeVisible();
  });

  test('shows prompt to send message', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByText(/Send a message to generate/i)).toBeVisible();
  });

  test('empty state disappears after slides generated', async ({ page }) => {
    await goToGenerator(page);

    // Verify empty state is shown
    await expect(page.getByText('No slides yet')).toBeVisible();

    // Generate slides
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for slides panel to show slide count (indicates slides loaded)
    await expect(page.locator('.text-gray-500').filter({ hasText: /3 slides?/ })).toBeVisible({ timeout: 10000 });

    // Empty state should be gone
    await expect(page.getByText('No slides yet')).not.toBeVisible();
  });
});

// ============================================
// ErrorHandling Tests
// ============================================

test.describe('ErrorHandling', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('shows error message on stream failure', async ({ page }) => {
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should show error (ErrorDisplay component has bg-red-50)
    await expect(page.locator('.bg-red-50')).toBeVisible({ timeout: 5000 });
  });

  test('error can be dismissed', async ({ page }) => {
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for error to appear
    await expect(page.locator('.bg-red-50')).toBeVisible({ timeout: 5000 });

    // Click dismiss button
    await page.getByRole('button', { name: /dismiss/i }).click();

    // Error should be gone
    await expect(page.locator('.bg-red-50')).not.toBeVisible();
  });

  test('can send new message after error', async ({ page }) => {
    let requestCount = 0;

    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      requestCount++;
      if (requestCount === 1) {
        // First request fails
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal server error' }),
        });
      } else {
        // Subsequent requests succeed
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: createStreamingResponseWithDeck(mockSlideDeck),
        });
      }
    });

    await goToGenerator(page);

    // First attempt - will fail
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for error
    await expect(page.locator('.bg-red-50')).toBeVisible({ timeout: 5000 });

    // Dismiss error
    await page.getByRole('button', { name: /dismiss/i }).click();

    // Try again - should succeed
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should see slides panel show slide count
    await expect(page.locator('.text-gray-500').filter({ hasText: /3 slides?/ })).toBeVisible({ timeout: 10000 });
  });

  test('input is re-enabled after error', async ({ page }) => {
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for error
    await expect(page.locator('.bg-red-50')).toBeVisible({ timeout: 5000 });

    // Input should be enabled again
    await expect(page.getByRole('textbox')).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled(); // Disabled because input is empty after clear
  });
});

// ============================================
// ChatPanel Header Tests
// ============================================

test.describe('ChatPanel Header', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);
  });

  test('shows Chat heading', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
  });

  test('shows input hint text', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByText(/Press Enter to send/i)).toBeVisible();
  });
});
