import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';

/**
 * /admin route UX gate.
 *
 * The admin page is hidden from non-admins in the UI. This is UX ONLY — every
 * admin API route keeps its server-side require_admin gate, and those 403s are
 * the real protection. These tests pin the client behaviour: a non-admin never
 * sees admin content, an actual admin does, and neither outcome is decided
 * before the identity fetch resolves (no admin-content flash, no wrong
 * redirect of a real admin).
 *
 * Run: cd frontend && npx playwright test tests/e2e/admin-route-gate.spec.ts
 */

/** Mock the identity endpoint the gate reads. */
async function mockIdentity(page: Page, isAdmin: boolean) {
  await page.route('**/api/user/current', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        username: 'user@test.com',
        display_name: 'user@test.com',
        is_admin: isAdmin,
      }),
    });
  });
}

/**
 * Admin-page sub-resources: fail them FAST and explicitly.
 *
 * Deliberately 500s rather than returning stub bodies. The admin panels catch
 * load errors into an error state and still render the page chrome (the `Admin`
 * h1) — which is exactly what these tests assert on — whereas a stub body of
 * the wrong shape throws inside a panel and blanks the whole page. Aborting
 * also avoids waiting on a backend that isn't running.
 */
async function failAdminSubresources(page: Page) {
  for (const pattern of ['**/api/admin/**', '**/api/feedback/**']) {
    await page.route(pattern, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'stubbed out in this spec' }),
      });
    });
  }
}

const adminHeading = (page: Page) =>
  page.getByRole('heading', { level: 1, name: 'Admin' });

test.describe('/admin route gate', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await failAdminSubresources(page);
  });

  test('non-admin visiting /admin lands on / and sees no admin content', async ({
    page,
  }) => {
    await mockIdentity(page, false);

    await page.goto('/admin');

    await expect(page).toHaveURL(/\/(help)?$/);
    await expect(adminHeading(page)).toHaveCount(0);
    // The landing page really rendered (not a blank redirect target).
    await expect(
      page.getByRole('heading', { level: 2, name: 'AI Assistant' })
    ).toBeVisible();
  });

  test('admin visiting /admin sees the admin page', async ({ page }) => {
    await mockIdentity(page, true);

    await page.goto('/admin');

    await expect(adminHeading(page)).toBeVisible();
    await expect(page).toHaveURL(/\/admin$/);
  });

  test('non-admin is redirected away from /feedback too', async ({ page }) => {
    await mockIdentity(page, false);

    await page.goto('/feedback');

    await expect(page).toHaveURL(/\/(help)?$/);
    await expect(adminHeading(page)).toHaveCount(0);
  });

  test('/feedback still reaches the admin page for an admin', async ({
    page,
  }) => {
    await mockIdentity(page, true);

    await page.goto('/feedback');

    await expect(adminHeading(page)).toBeVisible();
    await expect(page).toHaveURL(/\/admin$/);
  });

  test('while identity is resolving, neither admin content nor a redirect appears', async ({
    page,
  }) => {
    // Hold the identity response open so the "unknown" window is observable.
    let release: () => void = () => {};
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });

    await page.route('**/api/user/current', async (route) => {
      await released;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          username: 'admin@test.com',
          display_name: 'admin@test.com',
          is_admin: true,
        }),
      });
    });

    await page.goto('/admin');

    // Identity is still unknown here: the gate must not guess either way.
    await expect(adminHeading(page)).toHaveCount(0);
    await expect(page).toHaveURL(/\/admin$/);

    // Resolving as admin then reveals the page — proving the wait, not a
    // permanent block, is what the assertions above observed.
    release();
    await expect(adminHeading(page)).toBeVisible();
    await expect(page).toHaveURL(/\/admin$/);
  });
});
