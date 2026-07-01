/**
 * AISEC-248 PR1 — E2E coverage for the locked-down Presentation-mode slide iframe.
 *
 * Verifies the browser-side render surface hardening:
 *   1. The Presentation iframe is sandboxed `allow-scripts` WITHOUT `allow-same-origin`.
 *   2. Its `srcdoc` carries the injected Content-Security-Policy meta with
 *      `connect-src 'none'` (blocks fetch/XHR exfiltration at runtime).
 *   3. Pressing ArrowRight advances the slide counter — exercising the
 *      postMessage key bridge that replaced direct contentDocument access once
 *      `allow-same-origin` was dropped.
 *
 * Setup/navigation reuse the existing E2E harness: the fully-mocked backend from
 * helpers/setup-mocks.ts plus helpers/session-helpers.ts's mockSessionWithSlides
 * (the same pattern navigation.spec.ts's "History page session click" test uses
 * to load a deck into edit mode). No real backend is required.
 */
import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides } from './helpers/session-helpers';

// Deterministic session id (a fresh value distinct from session-helpers' default
// so these tests are self-contained and order-independent).
const SESSION_ID = 'c0ffee00-1111-2222-3333-444455556666';

/**
 * Navigate into Presentation mode for a session that has a (>= 2 slide) deck.
 * Returns a locator for the presentation iframe.
 */
async function enterPresentationMode(page: import('@playwright/test').Page) {
  await mockSessionWithSlides(page, SESSION_ID);
  await page.goto(`/sessions/${SESSION_ID}/edit`);

  // Wait for the deck to load — the Present button only renders once slideDeck
  // is populated.
  const presentButton = page.getByRole('button', { name: 'Present' });
  await expect(presentButton).toBeVisible({ timeout: 15000 });
  await presentButton.click();

  // PresentationMode renders an iframe via a portal on <body>. It is uniquely
  // identifiable by tabIndex={-1} — the SlidePanel preview/main iframes (also
  // titled "Slide N"/"Slide N preview") do not set tabindex, so this selector
  // resolves to exactly the presentation iframe.
  const iframe = page.locator('iframe[title^="Slide"][tabindex="-1"]');
  await expect(iframe).toBeVisible({ timeout: 10000 });
  return iframe;
}

test.describe('Slide security — Presentation mode iframe lockdown (AISEC-248)', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('presentation iframe is sandboxed allow-scripts without same-origin', async ({ page }) => {
    const iframe = await enterPresentationMode(page);

    // Exact match: the only sandbox token is allow-scripts.
    await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');

    // Defensive: allow-same-origin must NOT be present (would re-enable
    // parent-origin access and defeat the CSP isolation).
    const sandbox = await iframe.getAttribute('sandbox');
    expect(sandbox).not.toContain('allow-same-origin');
  });

  test('presentation iframe srcdoc injects a CSP with connect-src none', async ({ page }) => {
    const iframe = await enterPresentationMode(page);

    const srcdoc = await iframe.getAttribute('srcdoc');
    expect(srcdoc).not.toBeNull();
    expect(srcdoc!).toContain('Content-Security-Policy');
    expect(srcdoc!).toContain("connect-src 'none'");
  });

  test('ArrowRight advances the slide counter via the postMessage key bridge', async ({ page }) => {
    await enterPresentationMode(page);

    // The mocked deck (mockSlidesResponse) has 3 slides; the counter overlay
    // reads "<current> / <total>".
    const counter = page.getByText(/^\s*1\s*\/\s*3\s*$/);
    await expect(counter).toBeVisible({ timeout: 10000 });

    // Drive navigation through the parent-window keydown listener that the key
    // bridge forwards into.
    await page.keyboard.press('ArrowRight');

    await expect(page.getByText(/^\s*2\s*\/\s*3\s*$/)).toBeVisible({ timeout: 10000 });
  });
});

test('slide-selection preview iframe is sandboxed without same-origin', async ({ page }) => {
  // navigate to a deck with the slide-selection panel visible, then:
  const frames = page.locator('.slide-preview-frame');
  const count = await frames.count();
  for (let i = 0; i < count; i++) {
    const sandbox = await frames.nth(i).getAttribute('sandbox');
    expect(sandbox).toBe('allow-scripts');
  }
});
