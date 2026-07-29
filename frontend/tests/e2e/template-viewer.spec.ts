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
  mockDesignSystemTemplatesWithLive,
  mockDesignSystemTemplateSource,
  mockDesignSystemTemplateSourceMultiSlide,
  mockDesignSystemFiles,
  mockDesignSystemFileContents,
  TINY_PNG_BASE64,
} from '../fixtures/mocks';

/**
 * Expanded template viewer popup.
 *
 * Each template card carries an expand affordance that opens a read-only
 * popup showing the template's slides larger — scaled and clipped, paginated
 * when the layout ships several slide sections.
 *
 * SECURITY is the load-bearing property: the viewer must REUSE the same
 * sandboxed renderer the thumbnails use (sandbox="" + a srcDoc CSP with
 * network egress BLOCKED + assets resolved as inline data: URIs) and must not
 * gain any capability for being bigger. These tests assert that directly, so a
 * future refactor cannot quietly weaken the sandbox.
 *
 * Scope: viewer only — expand, look, close. No editing, no Present mode.
 *
 * All API responses are mocked; fixtures are SYNTHETIC ("Acme") only.
 *
 * Run: npx playwright test tests/e2e/template-viewer.spec.ts
 */

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
  await page.route('**/api/user/current', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'test@test.com', display_name: 'Test User' }),
    });
  });
  await page.route('**/api/slides/versions**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ versions: [], current_version: null }),
    });
  });
}

async function setupDesignSystemMocks(page: Page, source: unknown = mockDesignSystemTemplateSource) {
  await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystems) });
    } else {
      route.continue();
    }
  });
  await page.route(/\/api\/settings\/design-systems\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemDetail) });
      return;
    }
    route.continue();
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/files$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemFiles) });
  });
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
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/\d+\/thumbnail$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'image/png',
      headers: { 'X-Content-Type-Options': 'nosniff' },
      body: Buffer.from(TINY_PNG_BASE64, 'base64'),
    });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/\d+\/source$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(source) });
  });
}

async function openAcmeDetail(page: Page) {
  await page.goto('/design-systems');
  await expect(page.getByRole('heading', { name: 'Design System Library' })).toBeVisible({ timeout: 10000 });
  await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();
  await expect(page.getByTestId('design-system-detail')).toBeVisible();
}

/** Open the viewer from the first template card. */
async function openViewer(page: Page) {
  await openAcmeDetail(page);
  const card = page.locator('[data-testid="template-card"]').first();
  await card.locator('[data-testid="expand-template-button"]').click();
  const modal = page.getByTestId('template-viewer-modal');
  await expect(modal).toBeVisible();
  return modal;
}

test.describe('Template viewer popup', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
  });

  test('every template card exposes an expand affordance', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await openAcmeDetail(page);
    const cards = page.locator('[data-testid="template-card"]');
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      await expect(cards.nth(i).locator('[data-testid="expand-template-button"]')).toHaveCount(1);
    }
  });

  test('expanding shows the slide larger than the card thumbnail', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await openAcmeDetail(page);

    const card = page.locator('[data-testid="template-card"]').first();
    const cardBox = await card.boundingBox();

    await card.locator('[data-testid="expand-template-button"]').click();
    const frame = page.getByTestId('template-viewer-frame');
    await expect(frame).toBeVisible();

    // The viewer stage is wider than the whole card it came from.
    const stage = page.getByTestId('template-viewer-modal').locator('.aspect-video').first();
    const stageBox = await stage.boundingBox();
    expect(stageBox!.width).toBeGreaterThan(cardBox!.width);
  });

  test('viewer reuses the sandboxed renderer (sandbox="" + CSP, unchanged)', async ({ page }) => {
    await setupDesignSystemMocks(page);
    await openViewer(page);
    const frame = page.getByTestId('template-viewer-frame');

    // The SAME hard guarantees as the thumbnail: no scripts, no same-origin.
    await expect(frame).toHaveAttribute('sandbox', '');
    const srcdoc = await frame.getAttribute('srcdoc');
    expect(srcdoc).toContain('Content-Security-Policy');
    expect(srcdoc).toContain("default-src 'none'");
    // Token CSS still rides along so var(--...) refs resolve.
    expect(srcdoc).toContain('--brand-core-primary: #123456;');

    // Fixed 1280x720 frame, scaled — the slide is scaled and clipped, not reflowed.
    await expect(frame).toHaveCSS('width', '1280px');
    await expect(frame).toHaveCSS('height', '720px');
    expect(await frame.evaluate((el) => getComputedStyle(el).transform)).not.toBe('none');

    // The template content actually painted inside the frame.
    await expect(page.frameLocator('[data-testid="template-viewer-frame"]').locator('h1')).toHaveText(
      'Acme Content Layout',
    );
  });

  test('viewer blocks ALL external egress from uploaded template markup', async ({ page }) => {
    const externalRequests: string[] = [];
    await page.route('https://external.example/**', (route, request) => {
      externalRequests.push(request.url());
      route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(TINY_PNG_BASE64, 'base64') });
    });

    // Exfil-shaped template: external <img>, css url(), @import, <link>.
    await setupDesignSystemMocks(page, {
      id: 2,
      name: 'Acme Content',
      layout_html:
        '<!doctype html><html><head>' +
        '<link rel="stylesheet" href="https://external.example/style.css">' +
        '<style>@import url("https://external.example/import.css");' +
        '.slide{width:1280px;height:720px;background-image:url("https://external.example/bg.png");}</style>' +
        '</head><body><section class="slide"><h1>Acme Exfil Probe</h1>' +
        '<img src="https://external.example/pixel.png" alt="">' +
        '</section></body></html>',
      token_css: ':root { --brand-core-primary: #123456; }',
    });

    await openViewer(page);
    // The document rendered...
    await expect(page.frameLocator('[data-testid="template-viewer-frame"]').locator('h1')).toHaveText(
      'Acme Exfil Probe',
    );
    // ...and, after a beat for any (blocked) fetch, ZERO egress from the frame.
    await page.waitForTimeout(500);
    expect(externalRequests).toEqual([]);
  });

  test('multi-slide template paginates one slide at a time', async ({ page }) => {
    await setupDesignSystemMocks(page, mockDesignSystemTemplateSourceMultiSlide);
    await openViewer(page);

    const counter = page.getByTestId('template-viewer-counter');
    await expect(counter).toHaveText('Slide 1 of 3');

    const inner = page.frameLocator('[data-testid="template-viewer-frame"]');
    // Exactly ONE section is rendered per page — the others are removed, so the
    // scaled frame shows a single slide rather than a stacked column.
    await expect(inner.locator('.slide')).toHaveCount(1);
    await expect(inner.locator('h1')).toHaveText('Acme Slide One');

    await page.getByTestId('template-viewer-next').click();
    await expect(counter).toHaveText('Slide 2 of 3');
    await expect(inner.locator('h1')).toHaveText('Acme Slide Two');

    await page.getByTestId('template-viewer-prev').click();
    await expect(counter).toHaveText('Slide 1 of 3');
    await expect(inner.locator('h1')).toHaveText('Acme Slide One');
  });

  test('arrow keys page through the slides', async ({ page }) => {
    await setupDesignSystemMocks(page, mockDesignSystemTemplateSourceMultiSlide);
    await openViewer(page);
    const counter = page.getByTestId('template-viewer-counter');

    await page.keyboard.press('ArrowRight');
    await expect(counter).toHaveText('Slide 2 of 3');
    await page.keyboard.press('ArrowLeft');
    await expect(counter).toHaveText('Slide 1 of 3');
  });

  test('single-slide template shows no pager', async ({ page }) => {
    await setupDesignSystemMocks(page); // the single-`.slide` fixture
    await openViewer(page);
    await expect(page.getByTestId('template-viewer-counter')).toHaveCount(0);
    await expect(page.getByTestId('template-viewer-next')).toHaveCount(0);
  });

  test('close button, backdrop click and Escape all dismiss the viewer', async ({ page }) => {
    await setupDesignSystemMocks(page);

    const modal = await openViewer(page);
    await page.getByTestId('template-viewer-close').click();
    await expect(modal).toHaveCount(0);

    await openViewer(page);
    // Click the exposed backdrop near the top-left corner: the modal panel is
    // centered over the backdrop's middle, so a center click would land on the
    // panel (and must NOT dismiss).
    await page.getByTestId('template-viewer-backdrop').click({ position: { x: 4, y: 4 } });
    await expect(page.getByTestId('template-viewer-modal')).toHaveCount(0);

    await openViewer(page);
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('template-viewer-modal')).toHaveCount(0);
  });

  test('clicking inside the panel does not dismiss the viewer', async ({ page }) => {
    await setupDesignSystemMocks(page);
    const modal = await openViewer(page);
    // The stage sits over the backdrop's centre; a click there is "inside the
    // dialog" and must leave it open.
    await modal.locator('.aspect-video').first().click();
    await expect(page.getByTestId('template-viewer-modal')).toBeVisible();
  });

  test('viewer is read-only — no editing or present affordances', async ({ page }) => {
    await setupDesignSystemMocks(page);
    const modal = await openViewer(page);
    // Scope guard: this is a viewer, not an editor or a slideshow.
    await expect(modal.getByRole('button', { name: /edit|present|fullscreen|save/i })).toHaveCount(0);
    await expect(modal.locator('textarea')).toHaveCount(0);
    // The frame is inert to pointer input (it is a preview, not a live page).
    await expect(page.getByTestId('template-viewer-frame')).toHaveCSS('pointer-events', 'none');
  });
});
