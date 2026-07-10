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
  mockDesignSystemFiles,
  mockDesignSystemFileContents,
  TINY_PNG_BASE64,
} from '../fixtures/mocks';

/**
 * Template card thumbnails — bundle preview vs live-rendered fallback.
 *
 * Synthetic bundles ship a preview screenshot; real Claude Design exports
 * ship none. The cards must PREFER the shipped screenshot (unchanged
 * behavior) and otherwise fetch the stored template sources (JSON) and
 * live-render them as a scaled, clipped mini-card inside a FULLY-sandboxed
 * iframe (sandbox="" — no scripts, no same-origin).
 *
 * All API responses are mocked; fixtures are SYNTHETIC ("Acme") only.
 *
 * Run: npx playwright test tests/e2e/template-cards.spec.ts
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
  // Shell endpoints the app polls on every mount — mocked so the console-clean
  // assertion sees only the preview surface, exactly like a served backend.
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

async function setupDesignSystemMocks(page: Page) {
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
  // Single-file serving (the detail page fetches README.md for its docs pane) —
  // the design-systems-ui suite's pattern, security posture included.
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

  // Two templates: id 1 ships a screenshot, id 2 does not (live-render path).
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
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplateSource) });
  });
}

async function openAcmeDetail(page: Page) {
  await page.goto('/design-systems');
  await expect(page.getByRole('heading', { name: 'Design System Library' })).toBeVisible({ timeout: 10000 });
  await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();
  await expect(page.getByTestId('design-system-detail')).toBeVisible();
}

test.describe('Template cards — preview preference and live-render fallback', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('card with a shipped screenshot keeps using the thumbnail image', async ({ page }) => {
    await openAcmeDetail(page);
    const coverCard = page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Cover' });
    await expect(coverCard.locator('img')).toHaveAttribute('src', /\/templates\/1\/thumbnail$/);
    // The screenshot path never fetches template sources.
    await expect(coverCard.locator('[data-testid="template-live-preview"]')).toHaveCount(0);
  });

  test('screenshot-less card live-renders the stored layout in a sandboxed iframe', async ({ page }) => {
    await openAcmeDetail(page);
    const contentCard = page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Content' });
    const frame = contentCard.locator('[data-testid="template-live-preview"]');
    await expect(frame).toBeVisible();

    // Fully sandboxed: no scripts, no same-origin — user markup can never
    // execute in the app origin.
    await expect(frame).toHaveAttribute('sandbox', '');

    // The srcdoc carries the stored layout with the token stylesheet
    // injected so var(--...) references resolve.
    const srcdoc = await frame.getAttribute('srcdoc');
    expect(srcdoc).toContain('Acme Content Layout');
    expect(srcdoc).toContain('--brand-core-primary: #123456;');

    // Scaled+clipped mini-card: fixed 1280x720 frame, top-left scale.
    await expect(frame).toHaveCSS('width', '1280px');
    await expect(frame).toHaveCSS('height', '720px');
    const transform = await frame.evaluate((el) => getComputedStyle(el).transform);
    expect(transform).not.toBe('none');

    // The rendered document actually painted the template content.
    const inner = page.frameLocator('[data-testid="template-live-preview"]');
    await expect(inner.locator('h1')).toHaveText('Acme Content Layout');
  });

  test('live preview blocks ALL external egress from uploaded template markup (CSP)', async ({ page }) => {
    // sandbox="" blocks scripts/same-origin; the srcDoc CSP closes the
    // passive channel: img/link tags and css url()/@import in uploaded
    // template HTML/CSS must not trigger any external network fetch.
    const externalRequests: string[] = [];
    await page.route('https://external.example/**', (route, request) => {
      externalRequests.push(request.url());
      route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(TINY_PNG_BASE64, 'base64') });
    });

    // Exfil-shaped template: external <img>, css url(), @import, <link>.
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 2,
          name: 'Acme Content',
          layout_html:
            '<!doctype html><html><head>' +
            '<link rel="stylesheet" href="https://external.example/style.css">' +
            '<style>@import url("https://external.example/import.css");' +
            '.slide{width:1280px;height:720px;background-image:url("https://external.example/bg.png");}</style>' +
            '</head><body><section class="slide"><h1>Acme Exfil Probe</h1>' +
            '<img src="https://external.example/pixel.png" alt="">' +
            `<img src="data:image/png;base64,${TINY_PNG_BASE64}" alt="" data-testid="legit-data-img">` +
            '</section></body></html>',
          token_css: ':root { --brand-core-primary: #123456; }',
        }),
      });
    });

    await openAcmeDetail(page);
    const contentCard = page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Content' });
    const frame = contentCard.locator('[data-testid="template-live-preview"]');
    await expect(frame).toBeVisible();

    // The document rendered (content painted)…
    const inner = page.frameLocator('[data-testid="template-live-preview"]');
    await expect(inner.locator('h1')).toHaveText('Acme Exfil Probe');
    // …the srcDoc carries the CSP…
    const srcdoc = await frame.getAttribute('srcdoc');
    expect(srcdoc).toContain('Content-Security-Policy');
    // …and give any (blocked) fetches a beat, then assert ZERO egress.
    await page.waitForTimeout(500);
    expect(externalRequests).toEqual([]);
  });

  test('malformed markup BEFORE <html> still renders behind the CSP (structurally-first guard)', async ({ page }) => {
    // A fetch-capable tag ahead of the template's own <html>/<head> must not
    // beat the policy: the preview wrapper is synthesized, so the CSP meta is
    // the first fetch-capable byte no matter how mangled the upload is.
    const externalRequests: string[] = [];
    await page.route('https://external.example/**', (route, request) => {
      externalRequests.push(request.url());
      route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(TINY_PNG_BASE64, 'base64') });
    });

    await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 2,
          name: 'Acme Content',
          layout_html:
            // Malformed on purpose: resources declared BEFORE the html/head.
            '<img src="https://external.example/pre.png">' +
            '<link rel="stylesheet" href="https://external.example/pre.css">' +
            '<html><head><style>.slide{width:1280px;height:720px;}</style></head>' +
            '<body class="acme-body"><section class="slide"><h1>Acme Malformed Probe</h1>' +
            `<img src="data:image/png;base64,${TINY_PNG_BASE64}" alt="">` +
            '</section></body></html>',
          token_css: ':root { --brand-core-primary: #123456; }',
        }),
      });
    });

    await openAcmeDetail(page);
    const contentCard = page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Content' });
    const frame = contentCard.locator('[data-testid="template-live-preview"]');
    await expect(frame).toBeVisible();

    // Structural guarantee: the CSP meta precedes every uploaded byte.
    const srcdoc = (await frame.getAttribute('srcdoc')) ?? '';
    expect(srcdoc.startsWith('<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy"')).toBe(true);
    expect(srcdoc.indexOf('Content-Security-Policy')).toBeLessThan(srcdoc.indexOf('external.example'));

    // The legit render still works (content painted, body attrs preserved)…
    const inner = page.frameLocator('[data-testid="template-live-preview"]');
    await expect(inner.locator('h1')).toHaveText('Acme Malformed Probe');
    await expect(inner.locator('body.acme-body')).toHaveCount(1);
    // …and nothing left the frame.
    await page.waitForTimeout(500);
    expect(externalRequests).toEqual([]);
  });

  test('srcdoc arrives fully inline: data: URIs render, stray handles are neutralized, console stays clean', async ({ page }) => {
    // The /source endpoint resolves {{ds-asset:ID}} handles to data: URIs at
    // the response boundary (dsv2 F8). The BUILDER must still guarantee the
    // srcdoc-level invariant against a version-skewed backend or a handle the
    // resolver could not satisfy: nothing placeholder-shaped may enter the
    // frame — inside the sandbox a raw handle resolves as a relative URL and
    // the CSP refuses it (a failed-resource console error per occurrence,
    // the ~174-error signature of the dsv2 battery). Stray handles degrade
    // to the inert data:, placeholder instead.
    const resourceErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      if (/Refused to load|Failed to load resource|net::ERR/i.test(text)) {
        resourceErrors.push(text);
      }
    });
    page.on('requestfailed', (req) => resourceErrors.push(`requestfailed: ${req.url()}`));
    page.on('response', (res) => {
      if (res.status() >= 400) resourceErrors.push(`HTTP ${res.status()}: ${res.url()}`);
    });

    await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 2,
          name: 'Acme Content',
          layout_html:
            '<!doctype html><html><head>' +
            '<style>.slide{width:1280px;height:720px;}' +
            '.hero{background-image:url("{{ds-asset:31}}");}</style>' +
            '</head><body><section class="slide hero"><h1>Acme Inline Probe</h1>' +
            `<img src="data:image/png;base64,${TINY_PNG_BASE64}" alt="resolved brand mark">` +
            '<img src="{{ds-asset:99}}" alt="ghost">' +
            '</section></body></html>',
          token_css:
            "@font-face { font-family: 'Acme Preview Sans'; " +
            "src: url(data:font/woff2;base64,d29mZjItYnl0ZXM=) format('woff2'); }\n" +
            ':root { --brand-core-primary: #123456; }',
        }),
      });
    });

    await openAcmeDetail(page);
    const contentCard = page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Content' });
    const frame = contentCard.locator('[data-testid="template-live-preview"]');
    await expect(frame).toBeVisible();

    // The legit inline content painted…
    const inner = page.frameLocator('[data-testid="template-live-preview"]');
    await expect(inner.locator('h1')).toHaveText('Acme Inline Probe');

    const srcdoc = (await frame.getAttribute('srcdoc')) ?? '';
    // …resolved data: URIs pass through untouched (img src AND @font-face)…
    expect(srcdoc).toContain(`data:image/png;base64,${TINY_PNG_BASE64}`);
    expect(srcdoc).toContain('data:font/woff2;base64,');
    // …NOTHING placeholder-shaped survives (img src and CSS url() forms)…
    expect(srcdoc).not.toContain('{{ds-asset');
    expect(srcdoc).toContain('src="data:,"');
    expect(srcdoc).toContain('url("data:,")');
    // …the hardening is byte-identical: same sandbox, same CSP…
    await expect(frame).toHaveAttribute('sandbox', '');
    expect(srcdoc).toContain(
      '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; ' +
        "style-src 'unsafe-inline'; img-src data: blob:; font-src data:;\">",
    );
    // …and the detail page produced ZERO failed-resource console errors.
    await page.waitForTimeout(500);
    expect(resourceErrors).toEqual([]);
  });

  test('source fetch fires only for screenshot-less templates', async ({ page }) => {
    const sourceRequests: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/source')) sourceRequests.push(req.url());
    });
    await openAcmeDetail(page);
    await expect(
      page.locator('[data-testid="template-card"]').filter({ hasText: 'Acme Content' })
        .locator('[data-testid="template-live-preview"]'),
    ).toBeVisible();
    expect(sourceRequests.some((u) => /\/templates\/2\/source$/.test(u))).toBe(true);
    expect(sourceRequests.some((u) => /\/templates\/1\/source$/.test(u))).toBe(false);
  });
});
