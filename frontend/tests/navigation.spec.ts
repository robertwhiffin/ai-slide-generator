import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from './helpers/session-helpers';

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('clicking nav buttons changes URL', async ({ page }) => {
    await page.goto('/');
    await page.click('button:has-text("Profiles")');
    await expect(page).toHaveURL('/profiles');

    await page.click('button:has-text("Slide Styles")');
    await expect(page).toHaveURL('/slide-styles');

    await page.click('button:has-text("Deck Prompts")');
    await expect(page).toHaveURL('/deck-prompts');

    await page.click('button:has-text("Images")');
    await expect(page).toHaveURL('/images');

    await page.click('button:has-text("History")');
    await expect(page).toHaveURL('/history');

    await page.click('button:has-text("Help")');
    await expect(page).toHaveURL('/help');
  });

  test('browser back button returns to previous page', async ({ page }) => {
    await page.goto('/help');
    await page.click('button:has-text("History")');
    await expect(page).toHaveURL('/history');

    await page.goBack();
    await expect(page).toHaveURL('/help');
  });

  test('Generator nav creates new session if no last session', async ({ page }) => {
    await page.goto('/help');
    await page.click('button:has-text("Generator")');

    // Should create a new UUID session and navigate there
    await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });

  test('Generator nav returns to last session after navigating away', async ({ page }) => {
    await mockSessionWithSlides(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    // Wait for session to load
    await expect(page.locator('header').getByText('Test Session With Slides')).toBeVisible();

    // Navigate away
    await page.click('button:has-text("Profiles")');
    await expect(page).toHaveURL('/profiles');

    // Click Generator to return
    await page.click('button:has-text("Generator")');
    await expect(page).toHaveURL(`/sessions/${TEST_SESSION_ID}/edit`);
  });

  test('History page session click navigates to edit mode', async ({ page }) => {
    const sessionId = 'b1b4d8e3-6cf6-47cb-ad58-9fdc6ad205cc';
    await mockSessionWithSlides(page, sessionId);
    await page.goto('/history');

    // Click Restore on a session from the mock data
    await page.click('text=Restore');
    await expect(page).toHaveURL(`/sessions/${sessionId}/edit`);
  });
});
