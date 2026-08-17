import { test, expect, Page } from '@playwright/test';
import { mockDesignSystems, mockSlideStyles } from '../fixtures/mocks';

/**
 * Admin Page E2E Tests
 *
 * Tests the consolidated admin page with Feedback, Google Slides, Design
 * System, and Slide Style tabs. Frontend at baseURL (localhost:3000), backend
 * at http://127.0.0.1:8000.
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

// Same for the design-systems listing behind the Design System tab. A
// soft-deleted row is appended to the shared fixture (which ships only active
// ones) so the "inactive rows offer no action" case is covered.
const inactiveDesignSystem = {
  ...mockDesignSystems.design_systems[1],
  id: 3,
  name: 'Acme Retired DS',
  description: 'Soft-deleted; cannot become the org default.',
  is_default: false,
  is_active: false,
};

const designSystemRows = [...mockDesignSystems.design_systems, inactiveDesignSystem];

async function setupDesignSystemMocks(page: Page) {
  await page.route('**/api/settings/design-systems', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ design_systems: designSystemRows, total: designSystemRows.length }),
    });
  });
}

/**
 * Mock the identity endpoint the /admin route gate reads.
 *
 * /admin is now gated on `is_admin` from GET /api/user/current
 * (`hooks/useCurrentUser.ts` -> the gate in `AdminPage`). This suite predates the
 * gate and mocked only its own sub-resources, so with no identity route every
 * spec below rendered NOTHING and failed with `element(s) not found` — the page
 * chrome was never reached, so none of the panel assertions ran at all.
 *
 * The gate itself is NOT relaxed here, and these specs do not re-test it: they
 * exercise the admin PANELS, which requires being an admin, so the suite states
 * that precondition explicitly instead of depending on an unmocked fetch. The
 * gate's own behaviour (non-admin redirected, admin admitted, no pre-resolution
 * flash) is owned by `admin-route-gate.spec.ts` and stays the only place that
 * varies `is_admin`.
 */
async function setupAdminIdentityMock(page: Page) {
  await page.route('**/api/user/current', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        username: 'admin@test.com',
        display_name: 'admin@test.com',
        is_admin: true,
      }),
    });
  });
}

test.describe('Admin Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupAdminIdentityMock(page);
  });

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

  test('Design System tab renders each design system name', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    await expect(
      page.getByRole('heading', { name: 'Org Default Design System' }),
    ).toBeVisible();
    await expect(page.getByText('Acme Design System', { exact: true })).toBeVisible();
    await expect(page.getByText('Nimbus Theme', { exact: true })).toBeVisible();
  });

  test('Design System tab marks the is_default row with an Org default badge', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    await expect(page.getByTestId('design-system-default-badge-1')).toBeVisible();
    await expect(page.getByTestId('design-system-default-badge-2')).toHaveCount(0);
  });

  test('the org-default control is a TOGGLE, per row state', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    // The current default offers the WITHDRAWAL. It used to offer nothing at all,
    // which is what made the org default one-way: an admin could promote a design
    // system and switch between systems, but never return the org to "no default",
    // so the legacy slide-style fallback was unreachable (WD-01).
    await expect(
      page.getByTestId('design-system-row-1').getByRole('button', { name: 'Clear org default' }),
    ).toBeVisible();
    await expect(
      page.getByTestId('design-system-row-1').getByRole('button', { name: 'Set as org default' }),
    ).toHaveCount(0);
    // ...an active non-default one offers the promotion...
    await expect(
      page.getByTestId('design-system-row-2').getByRole('button', { name: 'Set as org default' }),
    ).toBeVisible();
    // ...and an INACTIVE, non-default one offers neither: the backend rejects
    // PROMOTING a tombstone with a 400, and there is nothing to withdraw.
    await expect(
      page.getByTestId('design-system-row-3').getByRole('button'),
    ).toHaveCount(0);
  });

  test('Clicking Clear org default calls the endpoint and drops the badge', async ({ page }) => {
    let clearUrl: string | null = null;
    let clearFired = false;
    await page.route('**/api/settings/design-systems/*/clear-default', (route, req) => {
      clearUrl = req.url();
      clearFired = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDesignSystems.design_systems[0], is_default: false }),
      });
    });
    await page.route('**/api/settings/design-systems', (route) => {
      const design_systems = clearFired
        ? designSystemRows.map(ds => ({ ...ds, is_default: false }))
        : designSystemRows;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ design_systems, total: design_systems.length }),
      });
    });

    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    await page
      .getByTestId('design-system-row-1')
      .getByRole('button', { name: 'Clear org default' })
      .click();

    await expect.poll(() => clearUrl).toContain('/design-systems/1/clear-default');
    // No row is the org default any more — the state D4's legacy fallback needs.
    await expect(page.getByTestId('design-system-default-badge-1')).toHaveCount(0);
  });

  test('Clicking Set as org default calls the endpoint and moves the badge', async ({ page }) => {
    let setDefaultUrl: string | null = null;
    let setDefaultFired = false;
    await page.route('**/api/settings/design-systems/*/set-default', (route, req) => {
      setDefaultUrl = req.url();
      setDefaultFired = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDesignSystems.design_systems[1], is_default: true }),
      });
    });
    await page.route('**/api/settings/design-systems', (route) => {
      const design_systems = setDefaultFired
        ? designSystemRows.map(ds => ({ ...ds, is_default: ds.id === 2 }))
        : designSystemRows;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ design_systems, total: design_systems.length }),
      });
    });

    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    await page
      .getByTestId('design-system-row-2')
      .getByRole('button', { name: 'Set as org default' })
      .click();

    await expect
      .poll(() => setDefaultUrl)
      .toContain('/api/settings/design-systems/2/set-default');
    await expect(page.getByTestId('design-system-default-badge-2')).toBeVisible();
    await expect(page.getByTestId('design-system-default-badge-1')).toHaveCount(0);
  });

  test('A failed Set as org default surfaces an error toast', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await page.route('**/api/settings/design-systems/*/set-default', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'boom' }),
      });
    });

    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Design System' }).click();
    await page
      .getByTestId('design-system-row-2')
      .getByRole('button', { name: 'Set as org default' })
      .click();

    const toast = page.getByTestId('toast');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/failed|error|boom/i);
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
