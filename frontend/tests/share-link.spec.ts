import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from './helpers/session-helpers';

test.describe('Share Link', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
  });

  test('share button is visible on edit page', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Wait for session to load
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();

    // Share button should be visible
    await expect(page.locator('button:has-text("Share")')).toBeVisible();
  });

  test('share button copies view URL to clipboard', async ({ page, context }) => {
    // Grant clipboard permissions
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);

    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();

    // Click the share button
    await page.click('button:has-text("Share")');

    // Verify clipboard contains the view URL
    const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboardText).toContain(`/sessions/${TEST_SESSION_ID}/view`);
  });

  test('share button shows confirmation toast', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);

    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();

    await page.click('button:has-text("Share")');

    // Should show a success toast
    await expect(page.locator('[data-testid="toast"]').first()).toContainText('copied');
  });

  test('share button not visible on view page', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Wait for session to load
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();

    // Share button should not be visible in view mode
    await expect(page.locator('button:has-text("Share")')).toBeHidden();
  });
});
