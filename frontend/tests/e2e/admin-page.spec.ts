import { test, expect, Page } from '@playwright/test';
import { mockSlideStyles } from '../fixtures/mocks';

/**
 * Admin Page E2E Tests
 *
 * Tests the consolidated admin page with Feedback, Google Slides, and
 * Slide Style tabs. Frontend at baseURL (localhost:3000), backend at
 * http://127.0.0.1:8000.
 *
 * Run with: npx playwright test e2e/admin-page.spec.ts
 */

// Mock the slide styles listing so the Slide Style tab renders a known
// fixture without needing a running backend.
async function setupSlideStyleMocks(page: Page) {
  await page.route('**/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles),
    });
  });
}

test.describe('Admin Page', () => {
  test('renders page with Feedback and Google Slides tabs', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByRole('tab', { name: 'Feedback' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Google Slides' })).toBeVisible();
  });

  test('renders Slide Style tab alongside Feedback and Google Slides', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.goto('/admin');
    await expect(page.getByRole('tab', { name: 'Slide Style' })).toBeVisible();
  });

  test('Slide Style tab renders each slide style name', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    await expect(
      page.getByRole('heading', { name: 'System Default Slide Style' }),
    ).toBeVisible();
    // getByText resolves inside the active tabpanel; the other panels remain
    // rendered but are hidden via the `hidden` attribute + `sr-only` class.
    await expect(page.getByText('System Default', { exact: true })).toBeVisible();
    await expect(page.getByText('Corporate Theme', { exact: true })).toBeVisible();
  });

  test('Feedback tab renders FeedbackDashboard content', async ({ page }) => {
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Feedback' }).click();
    await expect(page.getByRole('heading', { name: 'Feedback Dashboard' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Weekly Survey Stats' })).toBeVisible();
  });

  test('Google Slides tab renders credential upload form', async ({ page }) => {
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Google Slides' }).click();
    await expect(page.getByRole('heading', { name: 'OAuth Client Credentials' })).toBeVisible();
    await expect(page.getByText(/Drop credentials\.json here or click to browse/i)).toBeVisible();
  });

  test('/feedback redirects to /admin', async ({ page }) => {
    await page.goto('/feedback');
    await expect(page).toHaveURL(/\/admin/);
  });
});
