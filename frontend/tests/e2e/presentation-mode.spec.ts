import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';

/**
 * Presentation Mode UI Tests
 *
 * Tests that presentation mode stays open despite parent component re-renders.
 * Regression test for: inline onExit callback + [onExit] useEffect dependency
 * caused fullscreen to exit whenever SlidePanel re-rendered.
 *
 * Run: cd frontend && npx playwright test tests/e2e/presentation-mode.spec.ts
 */

async function setupPresentationMocks(page: Page) {
  await setupMocks(page);
  await mockSessionWithSlides(page, TEST_SESSION_ID);

  // Mock lock/user endpoints
  await page.route('**/api/user/current', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'test@test.com', display_name: 'Test User' }),
    });
  });
  await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ locked_by: 'test@test.com', locked_at: new Date().toISOString() }),
    });
  });
}

/** Locator for the presentation overlay (portal rendered at document.body). */
function presentationOverlay(page: Page) {
  // The overlay is a fixed div with slide counter text like "1 / 3"
  return page.locator('div[style*="position: fixed"][style*="z-index: 9999"]');
}

test.describe('Presentation Mode', () => {
  test('stays open despite parent re-renders from polling', async ({ page }) => {
    await setupPresentationMocks(page);

    // Navigate to a session with slides
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Wait for slides to render and Present button to appear
    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });

    // Click Present to open presentation mode
    await presentButton.click();

    // Verify the presentation overlay appeared
    const overlay = presentationOverlay(page);
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Verify slide counter is showing (confirms presentation is functional)
    await expect(page.getByText(/1\s*\/\s*\d+/)).toBeVisible();

    // Wait well beyond the 3s mentions polling interval.
    // Before the fix, the first polling response would re-render SlidePanel,
    // create a new onExit reference, trigger the fullscreen useEffect cleanup,
    // and close presentation mode.
    await page.waitForTimeout(7000);

    // Presentation overlay must still be visible
    await expect(overlay).toBeVisible();
    await expect(page.getByText(/1\s*\/\s*\d+/)).toBeVisible();
  });
});
