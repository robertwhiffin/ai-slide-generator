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

/**
 * Set up API mocks for all tests.
 * These mocks intercept backend API calls and return predefined responses.
 */
async function setupMocks(page: Page) {
  // Mock profiles endpoint
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles)
    });
  });

  // Mock deck prompts endpoint
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts)
    });
  });

  // Mock slide styles endpoint
  await page.route('http://localhost:8000/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles)
    });
  });

  // Mock sessions endpoints
  await page.route('http://localhost:8000/api/sessions**', (route, request) => {
    const url = request.url();
    
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
  await page.route('http://localhost:8000/api/verification/**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVerificationResponse)
    });
  });

  // Mock chat stream endpoint
  await page.route('http://localhost:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides)
    });
  });
}

/**
 * Helper to navigate to the Generator view since the app opens on Help by default.
 */
async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  // Wait for the Generator view to load
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

test.describe('Slide Generator App - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('should load the app and display header', async ({ page }) => {
    await page.goto('/');
    
    // Check that the app header is visible
    await expect(page.getByRole('heading', { name: 'databricks tellr', exact: true })).toBeVisible();
    
    // Check that navigation buttons are visible (scope to navigation element)
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('button', { name: 'Generator' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'History' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Profiles' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Deck Prompts' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Slide Styles' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Help' })).toBeVisible();
  });

  test('should display profile selector', async ({ page }) => {
    await page.goto('/');
    
    // Check that the current profile is displayed
    await expect(page.getByRole('button', { name: /Profile:/ })).toBeVisible();
  });

  test('should navigate to Generator view', async ({ page }) => {
    await goToGenerator(page);
    
    // Check that Generator view elements are visible
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
    await expect(page.getByRole('textbox', { name: /Ask to generate or modify/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
  });

  test('should navigate to Deck Prompts section', async ({ page }) => {
    await page.goto('/');
    
    // Click on Deck Prompts in the navigation bar
    await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
    
    // Wait for the page to load
    await expect(page.getByRole('button', { name: '+ Create Prompt' })).toBeVisible({ timeout: 10000 });
    
    // Check that Deck Prompts page is displayed
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
    
    // Check that deck prompts are listed
    await expect(page.getByRole('heading', { name: 'Monthly Review' })).toBeVisible();
  });

  test('should navigate to Slide Styles section', async ({ page }) => {
    await page.goto('/');
    
    // Click on Slide Styles in the navigation bar
    await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
    
    // Check that Slide Styles page is displayed
    await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
    
    // Check that styles are listed
    await expect(page.getByRole('heading', { name: 'Corporate Theme' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'System Default' })).toBeVisible();
    
    // Check that Create Style button is visible
    await expect(page.getByRole('button', { name: '+ Create Style' })).toBeVisible();
  });

  test('should navigate to History section', async ({ page }) => {
    await page.goto('/');
    
    // Click on History in the navigation bar
    await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
    
    // Check that History page is displayed
    await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
  });

  test('should navigate to Profiles section', async ({ page }) => {
    await page.goto('/');
    
    // Click on Profiles in the navigation bar
    await page.getByRole('navigation').getByRole('button', { name: 'Profiles' }).click();
    
    // Check that Profiles page is displayed
    await expect(page.getByRole('heading', { name: 'Configuration Profiles' })).toBeVisible();
    
    // Check that Create Profile button is visible
    await expect(page.getByRole('button', { name: '+ Create Profile' })).toBeVisible();
  });
});

test.describe('Slide Generator App - Generator View', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await goToGenerator(page);
  });

  test('should show chat input and send button', async ({ page }) => {
    // Check that the chat input is visible
    const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
    await expect(chatInput).toBeVisible();
    
    // Check that Send button exists (disabled when no text)
    await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('should enable send button when text is entered', async ({ page }) => {
    const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
    
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
    await page.goto('/');
    
    await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
    
    await page.getByRole('button', { name: '+ Create Prompt' }).click();
    
    // Check that the modal is open
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();
    
    // Check form fields are present
    await expect(page.getByRole('textbox', { name: 'Name *' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Description' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Category' })).toBeVisible();
    
    // Check action buttons
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create Prompt', exact: true })).toBeVisible();
  });

  test('should open slide style creation modal', async ({ page }) => {
    await page.goto('/');
    
    await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
    await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
    
    await page.getByRole('button', { name: '+ Create Style' }).click();
    
    // Check that the modal is open
    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
    
    // Check form fields are present
    await expect(page.getByRole('textbox', { name: 'Name *' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Description' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Category' })).toBeVisible();
    
    // Check action buttons
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create Style', exact: true })).toBeVisible();
  });

  test('should cancel deck prompt creation', async ({ page }) => {
    await page.goto('/');
    
    await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
    
    await page.getByRole('button', { name: '+ Create Prompt' }).click();
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();
    
    // Click cancel
    await page.getByRole('button', { name: 'Cancel' }).click();
    
    // Modal should be closed
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible();
    // Library should still be visible
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
  });
});
