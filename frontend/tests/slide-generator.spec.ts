import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
  mockVerificationResponse,
  createStreamingResponse
} from './fixtures/mocks';
import {
  goToGenerator as goToGeneratorNewUi,
  NEW_DECK_BUTTON_LABEL,
  VIEW_ALL_DECKS_LABEL,
  AGENT_PROFILES_LABEL,
  DECK_PROMPTS_LABEL,
  SLIDE_STYLES_LABEL,
  HELP_LABEL,
} from './helpers/new-ui';

/**
 * Set up API mocks for all tests.
 * These mocks intercept backend API calls and return predefined responses.
 */
async function setupMocks(page: Page) {
  // Mock setup status so app skips welcome screen
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ configured: true }),
    });
  });

  // Mock profiles endpoint
  await page.route(/\/api\/settings\/profiles$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles)
    });
  });

  // Mock deck prompts endpoint
  await page.route(/\/api\/settings\/deck-prompts$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts)
    });
  });

  // Mock slide styles endpoint
  await page.route(/\/api\/settings\/slide-styles$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles)
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
        body: JSON.stringify(mockSessions)
      });
    } else if (url.includes('/slides')) {
      // Slides for a session
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlides)
      });
    } else {
      // Session details - return 404 for new sessions
      route.fulfill({ status: 404 });
    }
  });

  // Mock verification endpoint
  await page.route('http://127.0.0.1:8000/api/verification/**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVerificationResponse)
    });
  });

  // Mock chat stream endpoint
  await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides)
    });
  });
}

async function goToGenerator(page: Page) {
  await goToGeneratorNewUi(page);
}

test.describe('Slide Generator App - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('should load the app and display header', async ({ page }) => {
    await page.goto('/');

    await expect(
      page.getByText(/Tellr|AI slide generator|How to Use/i).first()
    ).toBeVisible({ timeout: 15000 });

    const sidebarTrigger = page.getByRole('button', { name: 'Toggle Sidebar' });
    if (await sidebarTrigger.isVisible().catch(() => false)) {
      await sidebarTrigger.click();
      await page.waitForTimeout(300);
    }

    await expect(page.getByRole('button', { name: NEW_DECK_BUTTON_LABEL }).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: VIEW_ALL_DECKS_LABEL }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: AGENT_PROFILES_LABEL }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: DECK_PROMPTS_LABEL }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: SLIDE_STYLES_LABEL }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: HELP_LABEL }).first()).toBeVisible();
  });

  test('should display profile selector', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('button', { name: /Profile|Sales Analytics/i }).first()).toBeVisible();
  });

  test('should navigate to Generator view', async ({ page }) => {
    await goToGenerator(page);

    await expect(page.getByRole('heading', { name: 'AI Assistant', level: 2 })).toBeVisible();
    await expect(page.getByRole('textbox')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
  });

  test('should navigate to Deck Prompts section', async ({ page }) => {
    await page.goto('/deck-prompts');

    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: /New Prompt|Create Prompt/i })).toBeVisible();
    await expect(page.getByText('Monthly Review').first()).toBeVisible();
  });

  test('should navigate to Slide Styles section', async ({ page }) => {
    await page.goto('/slide-styles');

    await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Corporate Theme').first()).toBeVisible();
    await expect(page.getByText('System Default').first()).toBeVisible();
    await expect(page.getByRole('button', { name: /New Style|Create Style/i })).toBeVisible();
  });

  test('should navigate to My Sessions section', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: VIEW_ALL_DECKS_LABEL }).click();

    await expect(page.getByRole('heading', { name: 'All Decks' })).toBeVisible();
  });

  test('should navigate to Profiles section', async ({ page }) => {
    await page.goto('/profiles');

    await expect(page.getByRole('heading', { name: /Agent Profiles|Configuration Profiles/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: /New Agent|Create Profile/i })).toBeVisible();
  });
});

test.describe('Slide Generator App - Generator View', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await goToGenerator(page);
  });

  test('should show chat input and send button', async ({ page }) => {
    const chatInput = page.getByRole('textbox');
    await expect(chatInput).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('should enable send button when text is entered', async ({ page }) => {
    const chatInput = page.getByRole('textbox');
    
    // Type a prompt
    await chatInput.fill('Create a presentation');
    
    // Send button should now be enabled
    await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  });

  test('should display empty state message', async ({ page }) => {
    // Check for empty state message
    await expect(page.getByText('No slides yet')).toBeVisible();
    await expect(page.getByText('Send a message to generate slides')).toBeVisible();
  });
});

test.describe('Slide Generator App - Modal Dialogs', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('should open deck prompt creation modal', async ({ page }) => {
    await page.goto('/deck-prompts');
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: /New Prompt|Create Prompt/i }).click();

    await expect(page.getByRole('heading', { name: /Create Deck Prompt|New Deck Prompt/i })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
  });

  test('should open slide style creation modal', async ({ page }) => {
    await page.goto('/slide-styles');
    await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: /New Style|Create Style/i }).click();

    await expect(page.getByRole('heading', { name: /Create Slide Style|New Slide Style/i })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
  });

  test('should cancel deck prompt creation', async ({ page }) => {
    await page.goto('/deck-prompts');
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: /New Prompt|Create Prompt/i }).click();
    await expect(page.getByRole('heading', { name: /Create Deck Prompt|New Deck Prompt/i })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: /Create Deck Prompt|New Deck Prompt/i })).not.toBeVisible();
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
  });
});
