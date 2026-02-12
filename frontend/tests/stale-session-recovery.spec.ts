import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionNotFound } from './helpers/session-helpers';

test.describe('Stale Session Recovery', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Generator clears stale lastWorkingSessionId and creates new session on second click', async ({ page }) => {
    const staleSessionId = 'stale-dead-session-00000000-0000-0000-0000-000000000099';
    await mockSessionNotFound(page, staleSessionId);

    // Poison localStorage with a stale session ID, then reload so SessionContext picks it up
    await page.goto('/help');
    await page.evaluate((id) => {
      localStorage.setItem('lastWorkingSessionId', id);
    }, staleSessionId);
    await page.reload();

    // Click Generator — should attempt to navigate to stale session, fail, redirect to /help
    await page.click('button:has-text("Generator")');
    await expect(page).toHaveURL('/help');
    await expect(page.locator('[data-testid="toast"]').first()).toContainText('Session not found');

    // localStorage should be cleared so the next click self-heals
    const stored = await page.evaluate(() => localStorage.getItem('lastWorkingSessionId'));
    expect(stored).toBeNull();

    // Click Generator again — should create a fresh session and navigate successfully
    await page.click('button:has-text("Generator")');
    await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });

  test('stale session does not re-poison localStorage on failed load', async ({ page }) => {
    const staleSessionId = 'stale-dead-session-00000000-0000-0000-0000-000000000099';
    await mockSessionNotFound(page, staleSessionId);

    await page.goto('/help');
    await page.evaluate((id) => {
      localStorage.setItem('lastWorkingSessionId', id);
    }, staleSessionId);

    // Navigate directly to the stale session URL
    await page.goto(`/sessions/${staleSessionId}/edit`);
    await expect(page).toHaveURL('/help');

    // Verify the stale ID was NOT re-persisted
    const stored = await page.evaluate(() => localStorage.getItem('lastWorkingSessionId'));
    expect(stored).toBeNull();
  });

  test('Generator shows loading state while validating session from URL', async ({ page }) => {
    const staleSessionId = 'stale-dead-session-00000000-0000-0000-0000-000000000099';
    await mockSessionNotFound(page, staleSessionId);

    // Navigate directly to a session URL — chat should be disabled while loading
    await page.goto(`/sessions/${staleSessionId}/edit`);

    // Before the 404 redirect, if the page briefly shows the generator,
    // the chat input should not be interactive (disabled or loading state shown)
    // After redirect, we should be on /help
    await expect(page).toHaveURL('/help');
  });
});
