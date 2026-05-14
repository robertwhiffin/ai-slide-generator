import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';

/**
 * Presentation Mode UI Tests
 *
 * Tests that presentation mode stays open despite parent component re-renders.
 * Regression test for: inline onExit callback + [onExit] useEffect dependency
 * caused fullscreen to exit whenever SlidePanel re-rendered.
 *
 * Run: cd frontend && npx playwright test tests/e2e/presentation-mode.spec.ts
 */

async function setupPresentationMocks(page: Page) {
  await setupMocks(page);
  await mockSessionWithSlides(page, TEST_SESSION_ID);

  // Mock lock/user endpoints
  await page.route('**/api/user/current', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'test@test.com', display_name: 'Test User' }),
    });
  });
  await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ locked_by: 'test@test.com', locked_at: new Date().toISOString() }),
    });
  });
}

/** Locator for the presentation overlay (portal rendered at document.body). */
function presentationOverlay(page: Page) {
  // The overlay is a fixed div with slide counter text like "1 / 3"
  return page.locator('div[style*="position: fixed"][style*="z-index: 9999"]');
}

test.describe('Presentation Mode', () => {
  test('stays open despite parent re-renders from polling', async ({ page }) => {
    await setupPresentationMocks(page);

    // Navigate to a session with slides
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    // Wait for slides to render and Present button to appear
    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });

    // Click Present to open presentation mode
    await presentButton.click();

    // Verify the presentation overlay appeared
    const overlay = presentationOverlay(page);
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Verify slide counter is showing (confirms presentation is functional)
    await expect(page.getByText(/1\s*\/\s*\d+/)).toBeVisible();

    // Wait well beyond the 3s mentions polling interval.
    // Before the fix, the first polling response would re-render SlidePanel,
    // create a new onExit reference, trigger the fullscreen useEffect cleanup,
    // and close presentation mode.
    await page.waitForTimeout(7000);

    // Presentation overlay must still be visible
    await expect(overlay).toBeVisible();
    await expect(page.getByText(/1\s*\/\s*\d+/)).toBeVisible();
  });

  test('keyboard navigation still works after polling-driven re-renders', async ({ page }) => {
    // Regression for the "freezes after a few seconds" wishlist item: the
    // 3s ChatPanel polling was re-creating the slideDeck reference, the
    // useMemo recomputed the iframe srcdoc, and the iframe reloaded mid-press.
    // We snapshot the deck on mount now, so ArrowRight should still advance
    // the slide after the polling interval has elapsed.
    await setupPresentationMocks(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();

    await expect(presentationOverlay(page)).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/1\s*\/\s*\d+/)).toBeVisible();

    // Wait past the polling interval, then advance.
    await page.waitForTimeout(5000);
    await page.keyboard.press('ArrowRight');
    await expect(page.getByText(/2\s*\/\s*\d+/)).toBeVisible({ timeout: 2000 });
  });

  test('opens in full-window mode by default, does not request browser fullscreen', async ({ page }) => {
    // Wishlist item #2: presenter view should default to full-window (like
    // Google Slides Slideshow view), not browser fullscreen.
    await setupPresentationMocks(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();

    await expect(presentationOverlay(page)).toBeVisible({ timeout: 5000 });

    // The toolbar must expose both controls so users have a discoverable exit
    // and a way to opt into browser fullscreen.
    await expect(page.getByTestId('presentation-fullscreen-toggle')).toBeVisible();
    await expect(page.getByTestId('presentation-close')).toBeVisible();

    // Browser fullscreen should NOT be active by default.
    const fullscreenElement = await page.evaluate(() => document.fullscreenElement?.tagName ?? null);
    expect(fullscreenElement).toBeNull();
  });

  test('close button exits presentation', async ({ page }) => {
    await setupPresentationMocks(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();

    const overlay = presentationOverlay(page);
    await expect(overlay).toBeVisible({ timeout: 5000 });

    await page.getByTestId('presentation-close').click();
    await expect(overlay).not.toBeVisible({ timeout: 5000 });
  });

  test('slide-container is pinned to 720px so deck CSS body padding cannot squash it', async ({ page }) => {
    // Wishlist item / truncation root cause: when deck CSS added body
    // padding, the flex-shrinkable .slide-container collapsed below 720px
    // and content was clipped on both edges.
    await setupPresentationMocks(page);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();

    await expect(presentationOverlay(page)).toBeVisible({ timeout: 5000 });

    // Inject body padding into the iframe document, mimicking what a styled
    // deck would do, then assert the slide-container is still 720px tall.
    const containerHeight = await page.evaluate(() => {
      const iframes = Array.from(document.querySelectorAll('iframe'))
        .filter((f) => f.title?.startsWith('Slide '));
      const presentIframe = iframes[iframes.length - 1] as HTMLIFrameElement | undefined;
      if (!presentIframe) return null;
      const doc = presentIframe.contentDocument;
      if (!doc) return null;
      doc.body.style.padding = '40px 0';
      const sc = doc.querySelector('.slide-container') as HTMLElement | null;
      return sc ? sc.getBoundingClientRect().height : null;
    });

    expect(containerHeight).toBe(720);
  });
});
