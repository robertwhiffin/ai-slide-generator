import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

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
    const frame = await openPresentation(page);

    // Inject body padding into the iframe document, mimicking what a styled
    // deck would do, then assert the slide-container is still 720px tall.
    // Driven through Playwright's frame handling (origin-agnostic): the
    // presentation iframe is sandboxed WITHOUT allow-same-origin (AISEC-248),
    // so parent-page contentDocument access returns null.
    const container = frame.locator('.slide-container').first();
    await expect(container).toBeVisible({ timeout: 5000 });
    const containerHeight = await container.evaluate((sc) => {
      document.body.style.padding = '40px 0';
      return sc.getBoundingClientRect().height;
    });

    expect(containerHeight).toBe(720);
  });
});

// Deck CSS whose brand background lives at DECK level (body) while the slide
// roots stay transparent — the pattern both Claude-Design template families
// ship (transparent .slide variants over a body background). Presentation
// mode's reset must not paint white over it.
const DARK_DECK_CSS =
  'body { margin: 0; background: #102030; } ' +
  '.slide { width: 1280px; height: 720px; }';

/** Re-mock the slides endpoint with custom deck CSS (registered after
 *  setupPresentationMocks, so it wins Playwright's LIFO route matching). */
async function mockDeckCss(page: Page, css: string) {
  await page.route(
    `http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/slides`,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSlidesResponse,
          slide_deck: { ...mockSlidesResponse.slide_deck, css },
        }),
      });
    },
  );
}

async function openPresentation(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  const presentButton = page.getByRole('button', { name: 'Present' });
  await presentButton.waitFor({ state: 'visible', timeout: 15000 });
  await presentButton.click();
  await expect(presentationOverlay(page)).toBeVisible({ timeout: 5000 });
  return page.frameLocator('div[style*="z-index: 9999"] iframe');
}

test.describe('Presentation Mode deck background fidelity', () => {
  test('deck-level body background survives into presentation mode', async ({ page }) => {
    // dsv2 battery F1: the reset styles appended after deck CSS forced
    // html/body AND .slide-container to #ffffff, so any deck whose brand
    // background lives in `body { background: … }` presented WHITE while
    // tiles/editor showed the brand color.
    await setupPresentationMocks(page);
    await mockDeckCss(page, DARK_DECK_CSS);
    const frame = await openPresentation(page);

    // .first(): the outermost .slide-container is the presentation wrapper —
    // mock slide HTML may nest its own element of the same class.
    await expect(frame.locator('.slide-container').first()).toBeVisible({ timeout: 5000 });
    const backgrounds = await frame.locator('body').evaluate((body) => {
      const container = body.querySelector('.slide-container') as HTMLElement;
      return {
        body: getComputedStyle(body).backgroundColor,
        container: getComputedStyle(container).backgroundColor,
      };
    });

    // Deck CSS keeps painting the canvas…
    expect(backgrounds.body).toBe('rgb(16, 32, 48)');
    // …and the slide container no longer paints white over it.
    expect(backgrounds.container).toBe('rgba(0, 0, 0, 0)');
  });

  test('decks that paint no background still get a white canvas', async ({ page }) => {
    // Zero-regression guard for no-DS decks: with no deck-authored
    // background at all, the presentation canvas must stay white (not the
    // black letterbox bleeding through a fully transparent document).
    await setupPresentationMocks(page); // stock mock deck: css ''
    const frame = await openPresentation(page);

    // .first(): the outermost .slide-container is the presentation wrapper —
    // mock slide HTML may nest its own element of the same class.
    await expect(frame.locator('.slide-container').first()).toBeVisible({ timeout: 5000 });
    const htmlBackground = await frame
      .locator('html')
      .evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(htmlBackground).toBe('rgb(255, 255, 255)');
  });
});
