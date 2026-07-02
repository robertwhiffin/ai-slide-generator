import { test, expect, Page } from '@playwright/test';
import {
  mockProfileSummaries,
  mockDefaultAgentConfig,
  mockAvailableTools,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockDesignSystems,
  mockDesignSystemDetail,
  mockDesignSystemImportResponse,
  mockDesignSystemImportError,
  mockDesignSystemSetDefaultResponse,
} from '../fixtures/mocks';

/**
 * Design System Library UI Tests (Mocked) — Phase 4.
 *
 * Exercises the Claude-Design-style Design System front door under "slide style":
 *  - LIBRARY list renders from GET /api/settings/design-systems
 *  - DETAIL panel (templates, color tokens, brand-asset summary) from GET /{id}
 *  - UPLOAD flow POSTs a .zip to /import (mocked); 400 errors surfaced clearly
 *  - SET-DEFAULT (org) + DELETE (soft) controls, mirroring slide styles
 *
 * All API responses are mocked — these run fast and need no backend.
 * Fixtures are SYNTHETIC only (fake "Acme" brand) per public-repo hygiene.
 *
 * Run: npx playwright test tests/e2e/design-systems-ui.spec.ts
 */

// ============================================
// Setup Helpers
// ============================================

/** Ancillary app-shell mocks so the layout can mount without a backend. */
async function setupShellMocks(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });
  await page.route(/\/api\/profiles$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfileSummaries) });
  });
  await page.route('**/api/tools/available', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAvailableTools) });
  });
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();
    if (method === 'POST' || method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }
    if (url.includes('/agent-config')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
      return;
    }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }) });
  });
}

/** Design-system endpoints. Registered after the shell mocks so they win (LIFO). */
async function setupDesignSystemMocks(page: Page) {
  // Collection: list (GET) — bare /design-systems, optional query string only.
  await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystems) });
    } else {
      route.continue();
    }
  });

  // Detail (GET) + soft delete (DELETE): /design-systems/{id}
  await page.route(/\/api\/settings\/design-systems\/\d+$/, (route, request) => {
    const method = request.method();
    if (method === 'DELETE') {
      route.fulfill({ status: 204 });
      return;
    }
    if (method === 'GET') {
      const id = Number(request.url().split('/').pop());
      const summary = mockDesignSystems.design_systems.find((d) => d.id === id);
      const detail = id === mockDesignSystemDetail.id || !summary
        ? mockDesignSystemDetail
        : { ...summary, manifest_json: null, compiled_style_content: null, tokens: [], assets: [] };
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) });
      return;
    }
    route.continue();
  });

  // Import (POST): /design-systems/import
  await page.route(/\/api\/settings\/design-systems\/import$/, (route) => {
    route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(mockDesignSystemImportResponse) });
  });

  // Set-default (POST): /design-systems/{id}/set-default
  await page.route(/\/api\/settings\/design-systems\/\d+\/set-default$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemSetDefaultResponse) });
  });
}

async function goToLibrary(page: Page) {
  await page.goto('/design-systems');
  await expect(page.getByRole('heading', { name: 'Design System Library' })).toBeVisible({ timeout: 10000 });
}

// ============================================
// Library List
// ============================================

test.describe('Design System Library — list', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('renders design systems from the API', async ({ page }) => {
    await goToLibrary(page);
    await expect(page.getByRole('heading', { name: 'Acme Design System', level: 3 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Nimbus Theme', level: 3 })).toBeVisible();
  });

  test('shows the org Default badge on the default system', async ({ page }) => {
    await goToLibrary(page);
    const acmeCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' });
    await expect(acmeCard.getByText('Default', { exact: true })).toBeVisible();
  });

  test('shows token / asset / template counts', async ({ page }) => {
    await goToLibrary(page);
    const acmeCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' });
    await expect(acmeCard.getByText(/3 tokens/i)).toBeVisible();
    await expect(acmeCard.getByText(/3 assets/i)).toBeVisible();
    await expect(acmeCard.getByText(/2 templates/i)).toBeVisible();
  });

  test('shows the headline Upload design system control', async ({ page }) => {
    await goToLibrary(page);
    await expect(page.getByRole('button', { name: /Upload design system/i })).toBeVisible();
  });

  test('shows an empty state when there are no design systems', async ({ page }) => {
    // Override the list to be empty (registered last → wins).
    await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ design_systems: [], total: 0 }) });
      } else {
        route.continue();
      }
    });
    await goToLibrary(page);
    await expect(page.getByText(/No design systems yet/i)).toBeVisible();
  });
});

// ============================================
// Detail Panel
// ============================================

test.describe('Design System Library — detail panel', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('selecting a design system shows its templates', async ({ page }) => {
    await goToLibrary(page);
    const acmeCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' });
    await acmeCard.click();

    const detail = page.getByTestId('design-system-detail');
    await expect(detail.getByText('Title Slide')).toBeVisible();
    await expect(detail.getByText('Two Column')).toBeVisible();
  });

  test('detail panel shows color tokens with swatch and hex', async ({ page }) => {
    await goToLibrary(page);
    await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();

    const detail = page.getByTestId('design-system-detail');
    // Color token name + hex value are rendered.
    await expect(detail.getByText('primary')).toBeVisible();
    await expect(detail.getByText('#123456')).toBeVisible();
    // A swatch element carries the token color inline.
    const swatch = detail.locator('[data-testid="color-swatch"]').first();
    await expect(swatch).toBeVisible();
  });

  test('detail panel summarizes brand assets by kind', async ({ page }) => {
    await goToLibrary(page);
    await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();

    const detail = page.getByTestId('design-system-detail');
    await expect(detail.getByText('logo.svg')).toBeVisible();
    await expect(detail.getByText('hero-bg.png')).toBeVisible();
  });
});

// ============================================
// Upload Flow
// ============================================

test.describe('Design System Library — upload', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('Upload button opens the upload dialog', async ({ page }) => {
    await goToLibrary(page);
    await page.getByRole('button', { name: /Upload design system/i }).click();
    await expect(page.getByRole('heading', { name: 'Upload design system' })).toBeVisible();
  });

  test('uploading a .zip imports it and the new system appears', async ({ page }) => {
    await goToLibrary(page);
    await page.getByRole('button', { name: /Upload design system/i }).click();

    // After a successful import, the list is refreshed. Make the refreshed list
    // include the newly-imported system so it appears.
    await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            design_systems: [
              ...mockDesignSystems.design_systems,
              {
                id: 99,
                name: 'Imported Design System',
                description: 'Freshly imported synthetic bundle.',
                created_by: 'system',
                published: false,
                is_default: false,
                is_active: true,
                version: 1,
                token_count: 3,
                asset_count: 3,
                template_count: 2,
                created_at: '2026-02-03T10:00:00.000000',
                updated_at: '2026-02-03T10:00:00.000000',
              },
            ],
            total: 3,
          }),
        });
      } else {
        route.continue();
      }
    });

    // Attach a synthetic zip and submit.
    await page.getByTestId('design-system-file-input').setInputFiles({
      name: 'acme-bundle.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('PK synthetic zip bytes'),
    });
    await page.getByTestId('design-system-upload-submit').click();

    await expect(page.getByRole('heading', { name: 'Imported Design System', level: 3 })).toBeVisible({ timeout: 10000 });
  });

  test('a 400 validation error is surfaced clearly', async ({ page }) => {
    await goToLibrary(page);
    await page.getByRole('button', { name: /Upload design system/i }).click();

    // Override import to fail with a 400 (registered last → wins).
    await page.route(/\/api\/settings\/design-systems\/import$/, (route) => {
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify(mockDesignSystemImportError) });
    });

    await page.getByTestId('design-system-file-input').setInputFiles({
      name: 'broken.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('not really a zip'),
    });
    await page.getByTestId('design-system-upload-submit').click();

    await expect(page.getByText(/missing its manifest/i)).toBeVisible();
  });
});

// ============================================
// Set Default + Delete
// ============================================

test.describe('Design System Library — set default & delete', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('Set as org default calls the API and reflects the change', async ({ page }) => {
    let setDefaultCalled = false;
    await page.route(/\/api\/settings\/design-systems\/\d+\/set-default$/, (route) => {
      setDefaultCalled = true;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemSetDefaultResponse) });
    });

    await goToLibrary(page);
    // Nimbus is not the default → it exposes a "Set as org default" control.
    const nimbusCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Nimbus Theme' });
    await nimbusCard.getByRole('button', { name: /Set as org default/i }).click();

    await expect.poll(() => setDefaultCalled).toBe(true);
  });

  test('Delete asks for confirmation then removes the system', async ({ page }) => {
    await goToLibrary(page);
    const nimbusCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Nimbus Theme' });
    await nimbusCard.getByRole('button', { name: 'Delete' }).click();

    await expect(page.getByRole('heading', { name: 'Delete Design System' })).toBeVisible();

    // After deletion the list refreshes without Nimbus.
    await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ design_systems: [mockDesignSystems.design_systems[0]], total: 1 }),
        });
      } else {
        route.continue();
      }
    });

    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByRole('heading', { name: 'Nimbus Theme', level: 3 })).not.toBeVisible({ timeout: 10000 });
  });
});
