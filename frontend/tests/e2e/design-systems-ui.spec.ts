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
  mockDesignSystemTemplates,
  mockDesignSystemFiles,
  mockDesignSystemFileContents,
  TINY_PNG_BASE64,
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

/** Source-file browser endpoints (Phase 6) + template entities/thumbnails. */
async function setupFileBrowserMocks(page: Page) {
  // Addressable templates (Phase 4) — the browser joins these for name/desc/thumb.
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplates) });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/\d+\/thumbnail$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'image/png',
      headers: { 'X-Content-Type-Options': 'nosniff' },
      body: Buffer.from(TINY_PNG_BASE64, 'base64'),
    });
  });

  // File tree listing (metadata only).
  await page.route(/\/api\/settings\/design-systems\/\d+\/files$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemFiles) });
  });

  // Single-file serving: text sources ship as text/plain + attachment + nosniff,
  // exactly like the real endpoint's security posture.
  await page.route(/\/api\/settings\/design-systems\/\d+\/files\/.+$/, (route, request) => {
    const rawPath = new URL(request.url()).pathname.split('/files/')[1] ?? '';
    const filePath = rawPath.split('/').map(decodeURIComponent).join('/');
    const body = mockDesignSystemFileContents[filePath];
    if (body === undefined) {
      route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'File not found' }) });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'text/plain; charset=utf-8',
      headers: { 'Content-Disposition': 'attachment', 'X-Content-Type-Options': 'nosniff' },
      body,
    });
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
// Source-File Browser (Phase 6)
// ============================================

test.describe('Design System Library — source files', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
    await setupFileBrowserMocks(page);
  });

  async function openAcme(page: Page) {
    await goToLibrary(page);
    await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();
    await expect(page.getByTestId('ds-file-browser')).toBeVisible();
  }

  test('renders the grouped source-file tree', async ({ page }) => {
    await openAcme(page);
    const browser = page.getByTestId('ds-file-browser');
    // Role-scoped: a bare text match would also hit the transient
    // "Loading source files…" paragraph (strict-mode violation).
    await expect(browser.getByRole('heading', { name: 'Source files' })).toBeVisible();
    for (const section of ['readme', 'templates', 'brand', 'colors', 'fonts', 'other']) {
      await expect(browser.getByTestId(`ds-file-section-${section}`)).toBeVisible();
    }
    // This bundle retains no component files — the section is omitted entirely.
    await expect(browser.getByTestId('ds-file-section-components')).toHaveCount(0);

    await browser.getByTestId('ds-file-section-brand').click();
    await expect(browser.getByText('assets/logo.svg')).toBeVisible();
    await browser.getByTestId('ds-file-section-colors').click();
    await expect(browser.getByText('colors_and_type.css')).toBeVisible();
  });

  test('shows the README as safe plain text', async ({ page }) => {
    await openAcme(page);
    const readme = page.getByTestId('ds-readme-content');
    // The literal markdown source is shown (leading '#') — NOT a rendered heading.
    // Rendered as markdown: the H1 marker becomes a real heading element.
    await expect(readme.locator('h1')).toHaveText('Acme Design System');
    await expect(readme).toContainText('Synthetic readme for tests');
    await expect(readme).not.toContainText('# Acme Design System');
  });

  test('clicking a file opens its source in the read-only text viewer', async ({ page }) => {
    await openAcme(page);
    const browser = page.getByTestId('ds-file-browser');
    await browser.getByTestId('ds-file-section-colors').click();
    await browser.getByText('colors_and_type.css').click();

    const viewer = page.getByTestId('ds-file-viewer');
    await expect(viewer).toContainText('colors_and_type.css');
    // Source is rendered inside a read-only <pre> as text nodes.
    await expect(viewer.locator('pre')).toContainText('--brand-core-primary: #123456');
  });

  test('template entries show the Phase-4 thumbnail with name and description', async ({ page }) => {
    await openAcme(page);
    const browser = page.getByTestId('ds-file-browser');
    await browser.getByTestId('ds-file-section-templates').click();

    const card = browser.getByTestId('ds-file-template-card');
    await expect(card).toContainText('Acme Cover');
    await expect(card).toContainText('Centered hero with logo lockup.');
    await expect(card.locator('img')).toHaveAttribute('src', /\/templates\/1\/thumbnail$/);

    // Opening a template shows its HTML *source* as text in the viewer.
    await card.click();
    await expect(page.getByTestId('ds-file-viewer').locator('pre')).toContainText('<!doctype html>');
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
// Personal Default + Delete
// ============================================

/**
 * The in-app library control is a PERSONAL, browser-local default. The org-wide
 * default is an admin action and lives on /admin — so nothing here may call
 * `set-default` / `clear-default`, and the control is available to every user.
 */
test.describe('Design System Library — personal default & delete', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  /** Route guard: records any call to the ORG-wide default endpoints. */
  async function watchOrgDefaultEndpoints(page: Page): Promise<string[]> {
    const calls: string[] = [];
    await page.route(/\/api\/settings\/design-systems\/\d+\/(set|clear)-default$/, (route, request) => {
      calls.push(request.url());
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemSetDefaultResponse) });
    });
    return calls;
  }

  /**
   * Which source holds the STYLE SLOT in the pre-session working config, read
   * from its localStorage mirror. An absent key and an explicit null both mean
   * "nothing selected" — profile fixtures omit `design_system_id` altogether —
   * so both normalize to null here.
   */
  async function mirroredStyleSlot(
    page: Page,
  ): Promise<{ design_system_id: number | null; slide_style_id: number | null }> {
    const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
    const config = raw ? (JSON.parse(raw) as Record<string, number | null>) : {};
    return {
      design_system_id: config.design_system_id ?? null,
      slide_style_id: config.slide_style_id ?? null,
    };
  }

  test('Set as default stores a personal preference and calls no API', async ({ page }) => {
    const orgDefaultCalls = await watchOrgDefaultEndpoints(page);

    await goToLibrary(page);
    // Nimbus is not the org default → its control is the personal one.
    const nimbusCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Nimbus Theme' });
    await nimbusCard.getByRole('button', { name: 'Set as default' }).click();

    // The preference is browser-local…
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('userDefaultDesignSystemId')))
      .toBe('2');
    // …the control flips to its Clear counterpart…
    await expect(nimbusCard.getByRole('button', { name: 'Clear default' })).toBeVisible();
    // …the page discloses the precedence the preference carries…
    await expect(page.getByTestId('ds-personal-default-hint')).toContainText(/overrides/i);
    // …and no org-wide endpoint was called: this is not an admin action.
    expect(orgDefaultCalls).toEqual([]);
  });

  test('Clear default hands the style slot back to the personal slide-style default', async ({ page }) => {
    // THE requirement this control exists to satisfy. The resolver
    // short-circuits on a design_system_id that is already set, and the working
    // config is mirrored to localStorage where it is authoritative once
    // present — so a Clear that only dropped the preference key would leave the
    // resolved design system winning until a genuinely fresh surface, which
    // reads as "Clear does nothing". Clear must release the slot HERE.
    await page.addInitScript(() => {
      localStorage.removeItem('pendingAgentConfig');
      localStorage.removeItem('userDefaultDesignSystemId');
      // The personal slide-style default that must come back.
      localStorage.setItem('userDefaultSlideStyleId', '2');
    });
    const orgDefaultCalls = await watchOrgDefaultEndpoints(page);

    await goToLibrary(page);

    // Baseline: the personal style default holds the style slot.
    await expect.poll(async () => (await mirroredStyleSlot(page)).slide_style_id).toBe(2);
    expect((await mirroredStyleSlot(page)).design_system_id).toBeNull();

    // Set a personal design-system default → it takes the slot, style drops.
    const nimbusCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Nimbus Theme' });
    await nimbusCard.getByRole('button', { name: 'Set as default' }).click();
    await expect.poll(async () => (await mirroredStyleSlot(page)).design_system_id).toBe(2);
    expect((await mirroredStyleSlot(page)).slide_style_id).toBeNull();

    // Clear it — SAME surface, no reload: the style default applies again.
    await nimbusCard.getByRole('button', { name: 'Clear default' }).click();
    await expect.poll(async () => (await mirroredStyleSlot(page)).design_system_id).toBeNull();
    expect((await mirroredStyleSlot(page)).slide_style_id).toBe(2);

    // The preference key is gone; nothing else in storage was wiped; no
    // org-wide endpoint was ever called.
    expect(await page.evaluate(() => localStorage.getItem('userDefaultDesignSystemId'))).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem('userDefaultSlideStyleId'))).toBe('2');
    expect(orgDefaultCalls).toEqual([]);
  });

  /**
   * Seed an ALREADY-RESOLVED pre-session mirror alongside the two preferences —
   * the state a user is actually in when they come BACK to this page: their
   * personal default claimed the style slot on an earlier visit.
   *
   * This seeding is load-bearing, not convenience. On a genuinely fresh surface
   * the design-system list load (and so the prune) RACES config resolution, and
   * the prune usually wins — it deletes the key before the resolver ever reads
   * it, so the slot is never filled and a prune bug cannot show up at all. A
   * stale-prune test written without this seeding passes on broken code.
   */
  async function seedResolvedMirror(page: Page, designSystemId: number, userStyleId: number) {
    await page.addInitScript(
      ([dsId, styleId]) => {
        localStorage.setItem('userDefaultDesignSystemId', String(dsId));
        localStorage.setItem('userDefaultSlideStyleId', String(styleId));
        localStorage.setItem(
          'pendingAgentConfig',
          JSON.stringify({
            tools: [],
            slide_style_id: null,
            design_system_id: dsId,
            template_id: null,
            deck_prompt_id: null,
            system_prompt: null,
            slide_editing_instructions: null,
            style_source: 'user',
          }),
        );
      },
      [designSystemId, userStyleId] as [number, number],
    );
  }

  test('a stale personal default is pruned AND releases the style slot', async ({ page }) => {
    // The omission that bit the slide-style page: a stored id whose row no
    // longer exists must not survive the list load. Deleting the KEY alone is
    // not enough and is the worse half of the bug — the resolved id stays in the
    // working config while the Clear button, the only control that releases it,
    // disappears with the key. That is a sticky dead-end with no UI escape, so
    // the prune must release the slot with the same semantics as explicit Clear.
    // Design system 999 is not in the list at all — deleted. Style default 2 is
    // what must come back.
    await seedResolvedMirror(page, 999, 2);
    // A prune that re-triggered itself would show up here as React's own
    // update-depth error, so an infinite loop cannot pass this test quietly.
    const loopErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error' && /Maximum update depth/i.test(msg.text())) loopErrors.push(msg.text());
    });
    page.on('pageerror', (err) => {
      if (/Maximum update depth/i.test(String(err))) loopErrors.push(String(err));
    });

    await goToLibrary(page);

    // The stale preference is dropped…
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('userDefaultDesignSystemId')))
      .toBeNull();
    // …and the slot it was holding is released, not left wedged. Split in two
    // so each half can fail on its own.
    await expect.poll(async () => (await mirroredStyleSlot(page)).design_system_id).toBeNull();
    expect((await mirroredStyleSlot(page)).slide_style_id).toBe(2);

    // IDEMPOTENT: the effect ran once and settled. Re-reading after a beat finds
    // the same state, and React logged no update-depth error.
    const settled = await mirroredStyleSlot(page);
    await page.waitForTimeout(500);
    expect(await mirroredStyleSlot(page)).toEqual(settled);
    expect(await page.evaluate(() => localStorage.getItem('userDefaultDesignSystemId'))).toBeNull();
    expect(loopErrors).toEqual([]);
  });

  test('a VALID personal default is left alone by the prune', async ({ page }) => {
    // The other side of the guardrail: the prune must do nothing at all while
    // the design system is present and active — no key removal, and above all
    // no release of a slot the user legitimately filled.
    // Acme (id 1) is present and active in the fixture list.
    await seedResolvedMirror(page, 1, 2);

    await goToLibrary(page);

    // The design system keeps the slot; the style default stays displaced.
    await expect.poll(async () => (await mirroredStyleSlot(page)).design_system_id).toBe(1);
    expect((await mirroredStyleSlot(page)).slide_style_id).toBeNull();
    // The preference survives, so the escape hatch is still on screen.
    expect(await page.evaluate(() => localStorage.getItem('userDefaultDesignSystemId'))).toBe('1');
    const acmeCard = page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' });
    await expect(acmeCard.getByRole('button', { name: 'Clear default' })).toBeVisible();
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
