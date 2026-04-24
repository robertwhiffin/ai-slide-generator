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

  test('Slide Style tab marks the is_default row with a System default badge', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    // Row 1 ("System Default") is is_default=true in the fixture.
    const defaultRow = page.getByTestId('slide-style-row-1');
    await expect(defaultRow.getByText('System default', { exact: true })).toBeVisible();
    // Row 2 ("Corporate Theme") must not carry the badge.
    const otherRow = page.getByTestId('slide-style-row-2');
    await expect(otherRow.getByText('System default', { exact: true })).toHaveCount(0);
  });

  test('Set as system default button shows only on non-default active rows', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    const defaultRow = page.getByTestId('slide-style-row-1');
    const otherRow = page.getByTestId('slide-style-row-2');
    // The current default row should not offer the action.
    await expect(
      defaultRow.getByRole('button', { name: 'Set as system default' }),
    ).toHaveCount(0);
    // Another active, non-default row should.
    await expect(
      otherRow.getByRole('button', { name: 'Set as system default' }),
    ).toBeVisible();
  });

  test('Inactive slide styles do not show the Set as system default button', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    // Row 3 ("Archived Legacy") is is_active=false in the fixture.
    const inactiveRow = page.getByTestId('slide-style-row-3');
    await expect(
      inactiveRow.getByRole('button', { name: 'Set as system default' }),
    ).toHaveCount(0);
  });

  test('A failed Set as system default surfaces an error toast', async ({ page }) => {
    await setupSlideStyleMocks(page);
    await page.route('**/api/settings/slide-styles/*/set-default', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'boom' }),
      });
    });

    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    await page
      .getByTestId('slide-style-row-2')
      .getByRole('button', { name: 'Set as system default' })
      .click();

    const toast = page.getByTestId('toast');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/failed|error|boom/i);
  });

  test('Clicking Set as system default calls the endpoint and moves the badge', async ({ page }) => {
    // Track whether the set-default POST has fired. The list mock keys off
    // this flag so strict-mode double-effect pre-click returns the initial
    // state, and any re-fetch after the POST returns the post-change state.
    let setDefaultUrl: string | null = null;
    let setDefaultFired = false;
    await page.route('**/api/settings/slide-styles/*/set-default', (route, req) => {
      setDefaultUrl = req.url();
      setDefaultFired = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSlideStyles.styles[1],
          is_default: true,
        }),
      });
    });
    await page.route('**/api/settings/slide-styles', (route) => {
      const styles = setDefaultFired
        ? mockSlideStyles.styles.map(s => ({ ...s, is_default: s.id === 2 }))
        : mockSlideStyles.styles;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ styles, total: styles.length }),
      });
    });

    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Slide Style' }).click();
    await page
      .getByTestId('slide-style-row-2')
      .getByRole('button', { name: 'Set as system default' })
      .click();

    // Exact id in the URL path.
    await expect.poll(() => setDefaultUrl).toContain('/api/settings/slide-styles/2/set-default');
    // Badge now on Corporate Theme.
    await expect(
      page.getByTestId('slide-style-row-2').getByText('System default', { exact: true }),
    ).toBeVisible();
    // Badge removed from System Default row.
    await expect(
      page.getByTestId('slide-style-row-1').getByText('System default', { exact: true }),
    ).toHaveCount(0);
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
