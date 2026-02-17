import { test, expect } from '@playwright/test';

/**
 * Admin Page E2E Tests
 *
 * Tests the consolidated admin page with Feedback and Google Slides tabs.
 * Frontend at baseURL (localhost:3000), backend at http://127.0.0.1:8000
 *
 * Run with: npx playwright test e2e/admin-page.spec.ts
 */

test.describe('Admin Page', () => {
  test('renders page with Feedback and Google Slides tabs', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByRole('tab', { name: 'Feedback' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Google Slides' })).toBeVisible();
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
