import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionNotFound } from './helpers/session-helpers';

test.describe('Session Recovery', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('New Session always creates a fresh DB-persisted session', async ({ page }) => {
    await page.goto('/help');

    await page.getByRole('button', { name: 'New Deck' }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });

  test('navigating to non-existent session redirects to /help with toast', async ({ page }) => {
    const staleSessionId = 'stale-dead-session-00000000-0000-0000-0000-000000000099';
    await mockSessionNotFound(page, staleSessionId);

    // Navigate directly to the stale session URL
    await page.goto(`/sessions/${staleSessionId}/edit`);
    await expect(page).toHaveURL(/\/help/);
    await expect(page.locator('[data-testid="toast"]').first()).toContainText('Session not found');
  });

  test('clicking New Session multiple times creates distinct sessions', async ({ page }) => {
    await page.goto('/help');

    await page.getByRole('button', { name: 'New Deck' }).click();
    await page.waitForURL(/\/sessions\/[^/]+\/edit/);
    const firstUrl = page.url();
    const firstSessionId = firstUrl.match(/\/sessions\/([^/]+)\/edit/)?.[1];
    expect(firstSessionId).toBeTruthy();

    await page.getByRole('button', { name: 'Help' }).click();
    await expect(page).toHaveURL('/help');

    await page.getByRole('button', { name: 'New Deck' }).click();
    await page.waitForURL(/\/sessions\/[^/]+\/edit/);
    const secondUrl = page.url();
    const secondSessionId = secondUrl.match(/\/sessions\/([^/]+)\/edit/)?.[1];
    expect(secondSessionId).toBeTruthy();

    // Sessions should be different
    expect(secondSessionId).not.toBe(firstSessionId);
  });
});
