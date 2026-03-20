import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from './helpers/session-helpers';

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('clicking nav buttons changes URL', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Agent profiles' }).click();
    await expect(page).toHaveURL('/profiles');

    await page.getByRole('button', { name: 'Slide styles' }).click();
    await expect(page).toHaveURL('/slide-styles');

    await page.getByRole('button', { name: 'Deck prompts' }).click();
    await expect(page).toHaveURL('/deck-prompts');

    await page.getByRole('button', { name: 'Images' }).click();
    await expect(page).toHaveURL('/images');

    await page.getByRole('button', { name: 'View All Decks' }).click();
    await expect(page).toHaveURL('/history');

    await page.getByRole('button', { name: 'Help' }).click();
    await expect(page).toHaveURL('/help');
  });

  test('browser back button returns to previous page', async ({ page }) => {
    await page.goto('/help');
    await page.getByRole('button', { name: 'View All Decks' }).click();
    await expect(page).toHaveURL('/history');

    await page.goBack();
    await expect(page).toHaveURL('/help');
  });

  test('New Deck always creates a fresh session', async ({ page }) => {
    await page.goto('/help');
    await page.getByRole('button', { name: 'New Deck' }).click();

    // Should create a new UUID session and navigate there
    await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });

  test('History page session click navigates to edit mode', async ({ page }) => {
    const sessionId = 'b1b4d8e3-6cf6-47cb-ad58-9fdc6ad205cc';
    await mockSessionWithSlides(page, sessionId);
    await page.goto('/history');

    // Click Restore on a session from the mock data
    await page.getByRole('button', { name: 'Restore' }).first().click();
    await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}/edit`));
  });
});
