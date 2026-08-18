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
  mockDesignSystemTemplates,
  mockDesignSystemFiles,
} from '../fixtures/mocks';

/**
 * A design-system name must reach the request UNCHANGED, however long it is.
 *
 * Hard rule A — no brand data is ever turned away or silently altered — was closed
 * at the ORM (uncapped TEXT), at the Pydantic validators, and in the importer's
 * name resolution. Six rounds of that work, and the BROWSER was still clipping the
 * input: `DesignSystemUploadDialog` carried `maxLength={255}`, so typing a
 * 300-character brand name produced 255 characters and dropped 45 — destroyed in
 * the DOM, before any request existed. Every backend fix was invisible to the user
 * who typed a long name.
 *
 * These assertions therefore read the OUTBOUND REQUEST, not the input's value. A
 * test that checks `inputValue()` is testing the same attribute that does the
 * clipping: `maxLength` truncates the value itself, so the DOM and the payload
 * agree on the truncated string and the test passes while the data is already gone.
 * The payload is the last place the user's bytes can be observed leaving the app.
 *
 * CSS ellipsis is explicitly fine and is NOT what this covers: `truncate` shortens
 * what is DRAWN and keeps the value intact. Only JS/attribute truncation destroys
 * data.
 *
 * All API responses are mocked. Fixtures are SYNTHETIC (fake "Acme" brand).
 *
 * Run: npx playwright test tests/e2e/design-system-brand-text-uncapped.spec.ts
 */

/** Longer than every historical cap (50/100/255) — the finding's own 300. */
const LONG_NAME_LENGTH = 300;

/**
 * A brand name that is long AND exotic: hard rule A is about not altering brand
 * text at all, so the probe carries unicode, emoji and punctuation that a
 * sanitizer or a slug helper might be tempted to rewrite.
 *
 * It deliberately does NOT begin or end in whitespace. Both save paths call
 * `.trim()`, which is an intentional, non-destructive convenience — mixing it into
 * the probe would make this suite fail for a reason that is not truncation.
 */
const LONG_BRAND_NAME = `${'Acme Brand Systém 🎨 セマンティック — '
  .repeat(20)
  .slice(0, LONG_NAME_LENGTH - 1)
  .trimEnd()}X`.padEnd(LONG_NAME_LENGTH, 'X');

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
  await page.route('**/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('**/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
  await page.route('**/api/sessions**', (route, request) => {
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
  await page.route('**/api/genie/spaces', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }) });
  });
  await page.route('**/api/user/current', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user_name: 'tester', is_admin: true }) });
  });
}

async function setupDesignSystemMocks(page: Page) {
  await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystems) });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+$/, (route, request) => {
    if (request.method() === 'PUT') {
      // Echo the submitted name back so the UI's success path can settle.
      const body = JSON.parse(request.postData() || '{}');
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDesignSystemDetail, name: body.name ?? mockDesignSystemDetail.name }),
      });
      return;
    }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemDetail) });
  });
  await page.route(/\/api\/settings\/design-systems\/import$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemImportResponse) });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplates) });
  });
  await page.route(/\/api\/settings\/design-systems\/\d+\/files$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemFiles) });
  });
}

async function goToLibrary(page: Page) {
  await page.goto('/design-systems');
  await expect(page.getByRole('heading', { name: 'Design System Library' })).toBeVisible({ timeout: 15000 });
}

test.describe('design-system brand text is never truncated by the browser', () => {
  test.beforeEach(async ({ page }) => {
    await setupShellMocks(page);
    await setupDesignSystemMocks(page);
  });

  test('a >255-char name reaches the IMPORT request unchanged', async ({ page }) => {
    await goToLibrary(page);
    await page.getByRole('button', { name: /Upload design system/i }).click();

    const nameInput = page.locator('#ds-name');
    await nameInput.fill(LONG_BRAND_NAME);

    // The DOM must hold every character the user typed. Asserted as well as the
    // payload, because a cap here is what silently produced the clipped payload.
    expect(await nameInput.inputValue()).toHaveLength(LONG_BRAND_NAME.length);

    await page.getByTestId('design-system-file-input').setInputFiles({
      name: 'acme-bundle.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('PK synthetic zip bytes'),
    });

    const importRequest = page.waitForRequest(
      (request) => request.url().includes('/design-systems/import') && request.method() === 'POST',
    );
    await page.getByTestId('design-system-upload-submit').click();
    const request = await importRequest;

    // The name travels as multipart form data; read it out of the raw body, which
    // is what actually left the browser.
    const sentBody = request.postData() ?? '';
    expect(sentBody).toContain(LONG_BRAND_NAME);
    expect(
      sentBody.includes(LONG_BRAND_NAME.slice(0, 255) + '"'),
      'the name was clipped to 255 characters before the request was sent',
    ).toBe(false);
  });

  test('a >255-char name reaches the RENAME request unchanged', async ({ page }) => {
    await goToLibrary(page);
    const acmeCard = page
      .locator('[data-testid="design-system-card"]')
      .filter({ hasText: 'Acme Design System' });
    await acmeCard.first().click();

    await page.getByTestId('ds-rename-button').click();
    const renameInput = page.getByTestId('ds-rename-input');
    await renameInput.fill(LONG_BRAND_NAME);
    expect(await renameInput.inputValue()).toHaveLength(LONG_BRAND_NAME.length);

    const renameRequest = page.waitForRequest(
      (request) => /\/design-systems\/\d+$/.test(request.url()) && request.method() === 'PUT',
    );
    await page.getByTestId('ds-rename-save').click();
    const request = await renameRequest;

    expect(JSON.parse(request.postData() || '{}').name).toBe(LONG_BRAND_NAME);
  });

  test('no brand-text input carries a length cap', async ({ page }) => {
    await goToLibrary(page);
    await page.getByRole('button', { name: /Upload design system/i }).click();

    // Read the ATTRIBUTE, not the value: an input with no cap reports null. This
    // is the structural half of the assertion — it fails the moment a cap is
    // reintroduced, without needing a 300-character round trip to notice.
    expect(await page.locator('#ds-name').getAttribute('maxlength')).toBeNull();
  });
});
