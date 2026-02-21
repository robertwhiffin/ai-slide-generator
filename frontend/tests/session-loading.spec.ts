import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides, mockSessionNotFound, TEST_SESSION_ID } from './helpers/session-helpers';

test.describe('Session Loading from URL', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('generator loads session slides from URL parameter', async ({ page }) => {
    await mockSessionWithSlides(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Verify slide deck title is rendered in the SlidePanel header
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();
  });

  test('generator shows slide count in header after loading session', async ({ page }) => {
    await mockSessionWithSlides(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Wait for slides to load - the header shows "N slides" text
    await expect(page.locator('header').getByText('3 slides')).toBeVisible();
  });

  test('invalid session ID redirects to help with error', async ({ page }) => {
    await mockSessionNotFound(page, 'nonexistent-id');
    await page.goto('/sessions/nonexistent-id/edit');

    // Should redirect to help page (may have query params)
    await expect(page).toHaveURL(/\/help/);
    // Should show error toast (use .first() since React StrictMode may trigger effect twice)
    await expect(page.locator('[data-testid="toast"]').first()).toContainText('Session not found');
  });

  test('session title is shown in header after loading', async ({ page }) => {
    await mockSessionWithSlides(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Header shows slide deck title when slides are loaded (otherwise session title)
    await expect(page.locator('header').getByText(/Benefits of Cloud Computing|Test Session With Slides/)).toBeVisible({ timeout: 10000 });
  });
});
