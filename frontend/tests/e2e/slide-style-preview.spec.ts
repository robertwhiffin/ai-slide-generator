import { test, expect, Page } from '@playwright/test';
import {
  mockProfileSummaries,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Slide Style Visual Preview UI tests (mocked).
 *
 * Covers the properties the design depends on:
 * - no per-card preview fan-out at initial render (lazy + settled),
 * - every status state renders non-blockingly (ready/generating/failed),
 * - the raw style-text toggle is independent of preview success,
 * - the mini-deck modal opens from an accessible control and closes on Escape.
 */

type PreviewBody = Record<string, unknown>;

const READY_PREVIEW: PreviewBody = {
  status: 'ready',
  fingerprint: 'fp-1',
  slides: ["<div class='slide'>Cover</div>", "<div class='slide'>Content</div>"],
  css: '.slide{color:navy}',
  assets: [],
  generated_at: '2026-01-01T00:00:00Z',
  stale: false,
};

/** Base app mocks + a configurable /preview handler that records call count. */
async function setupMocks(page: Page, previewBody: () => PreviewBody) {
  const state = { previewCalls: 0 };

  await page.route('**/api/setup/status', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) }),
  );
  await page.route(/\/api\/settings\/slide-styles$/, (r, req) => {
    if (req.method() === 'GET') {
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
    } else {
      r.continue();
    }
  });
  // The preview endpoint — counts calls so we can assert no fan-out.
  await page.route(/\/api\/settings\/slide-styles\/(\d+)\/preview$/, (r, req) => {
    const id = parseInt(req.url().match(/slide-styles\/(\d+)\/preview/)?.[1] || '1');
    state.previewCalls += 1;
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ style_id: id, ...previewBody() }),
    });
  });
  await page.route(/\/api\/settings\/slide-styles\/\d+$/, (r, req) => {
    if (req.method() === 'GET') {
      const id = parseInt(req.url().split('/').pop() || '1');
      const style = mockSlideStyles.styles.find((s) => s.id === id) || mockSlideStyles.styles[0];
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(style) });
    } else {
      r.continue();
    }
  });
  await page.route(/\/api\/profiles$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfileSummaries) }),
  );
  await page.route('**/api/tools/available', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tools: [] }) }),
  );
  await page.route('**/api/settings/deck-prompts', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) }),
  );
  await page.route('**/api/sessions**', (r, req) => {
    if (req.method() === 'POST' || req.method() === 'DELETE') {
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/genie/spaces', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) }),
  );
  await page.route('**/api/version**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }) }),
  );

  return state;
}

async function goToSlideStyles(page: Page) {
  await page.goto('/slide-styles');
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible({ timeout: 10000 });
}

test.describe('Slide style preview', () => {
  test('does not fetch previews for every card at initial render', async ({ page }) => {
    const state = await setupMocks(page, () => READY_PREVIEW);
    await goToSlideStyles(page);
    // Give any errant fan-out a chance to fire.
    await page.waitForTimeout(500);
    expect(state.previewCalls).toBe(0);

    // Expanding one card fetches only THAT card's preview — never one per card.
    // (There are 3 styles; a fan-out bug would fire >=3. React StrictMode may
    // double-invoke the effect in dev, so allow up to 2 for the single card.)
    await page.getByRole('button', { name: 'Preview' }).first().click();
    await expect(page.getByTestId('slide-style-preview').first()).toBeVisible();
    expect(state.previewCalls).toBeGreaterThan(0);
    expect(state.previewCalls).toBeLessThan(mockSlideStyles.styles.length);
  });

  test('ready preview renders a sandboxed frame and opens a modal', async ({ page }) => {
    await setupMocks(page, () => READY_PREVIEW);
    await goToSlideStyles(page);
    await page.getByRole('button', { name: 'Preview' }).first().click();

    const preview = page.getByTestId('slide-style-preview').first();
    await expect(preview).toBeVisible();
    await expect(preview).toHaveAttribute('data-preview-status', 'ready');

    // Accessible opener → modal → Escape closes, focus-managed.
    await preview.getByTestId('slide-style-preview-open').click();
    await expect(page.getByTestId('slide-style-preview-modal')).toBeVisible();
    await expect(page.getByTestId('slide-style-preview-counter')).toHaveText(/Slide 1 of 2/);
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('slide-style-preview-modal')).not.toBeVisible();
  });

  test('generating state shows a non-blocking spinner', async ({ page }) => {
    await setupMocks(page, () => ({ status: 'generating' }));
    await goToSlideStyles(page);
    await page.getByRole('button', { name: 'Preview' }).first().click();

    const preview = page.getByTestId('slide-style-preview').first();
    await expect(preview).toHaveAttribute('data-preview-status', 'generating');
    await expect(page.getByText('Generating preview…')).toBeVisible();
    // Raw text is still reachable even without a rendered preview.
    await page.getByTestId('slide-style-raw-toggle').first().click();
    await expect(page.locator('pre').first()).toBeVisible();
  });

  test('failed state shows an error without breaking the page', async ({ page }) => {
    await setupMocks(page, () => ({ status: 'failed', error_code: 'too_large' }));
    await goToSlideStyles(page);
    await page.getByRole('button', { name: 'Preview' }).first().click();

    const preview = page.getByTestId('slide-style-preview').first();
    await expect(preview).toHaveAttribute('data-preview-status', 'failed');
    await expect(page.getByText(/Preview failed/)).toBeVisible();
    // The list still works: other actions remain usable.
    await expect(page.getByRole('button', { name: 'New Style' })).toBeVisible();
  });
});
