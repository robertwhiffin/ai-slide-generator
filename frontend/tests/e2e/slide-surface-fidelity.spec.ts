import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

/**
 * Slide preview-surface fidelity tests (dsv2 battery F2/F3).
 *
 * Every preview surface (tile, visual editor, filmstrip) renders the SAME
 * deck the exports render. These tests pin the two fidelity properties the
 * battery found broken:
 *  - F2: the filmstrip's reset forced background:#ffffff + Inter, repainting
 *    deck-level brand backgrounds/fonts on every thumbnail.
 *  - F3: a model-authored outer margin on the slide root (.slide
 *    { margin: 32px auto }) shifted content past the 720px clip on
 *    tiles/editor/filmstrip while presentation mode neutralized it —
 *    per-surface WYSIWYG divergence.
 *
 * Run: cd frontend && npx playwright test tests/e2e/slide-surface-fidelity.spec.ts
 */

// Deck CSS that carries brand identity at DECK level: body background + font
// stack. Preview resets must not repaint/refont it. ("Acme Sans" is synthetic —
// computed font-family reports the specified stack whether or not a face
// resolves, which keeps the assertion hermetic.)
const BRAND_DECK_CSS =
  "body { margin: 0; background: #0e1a1f; font-family: 'Acme Sans', sans-serif; } " +
  '.slide-container { width: 1280px; height: 720px; }';

async function setupSurfaceMocks(page: Page, css: string) {
  await setupMocks(page);
  await mockSessionWithSlides(page, TEST_SESSION_ID);

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

  // Registered last → wins Playwright's LIFO route matching over the
  // stock slides mock, letting each test choose its deck CSS.
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

test.describe('Filmstrip (SlideSelection) preview fidelity', () => {
  test('filmstrip previews keep the deck background and font stack', async ({ page }) => {
    // dsv2 F2: SlideSelection's reset appended background:#ffffff and
    // font-family:'Inter' after deck CSS, so every filmstrip thumbnail
    // repainted brand decks white in the brand-less UI font.
    await setupSurfaceMocks(page, BRAND_DECK_CSS);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const stripBody = page
      .frameLocator('iframe[title="Slide 1 preview"]')
      .locator('body');
    await expect(stripBody).toBeVisible({ timeout: 15000 });

    const style = await stripBody.evaluate((body) => {
      const cs = getComputedStyle(body);
      return { background: cs.backgroundColor, font: cs.fontFamily, width: cs.width };
    });

    // Deck-authored values survive the reset…
    expect(style.background).toBe('rgb(14, 26, 31)');
    expect(style.font).toContain('Acme Sans');
    // …while the fixed 1280x720 preview frame sizing is kept.
    expect(style.width).toBe('1280px');
  });
});
