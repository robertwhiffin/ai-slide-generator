import { test, expect, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';
import { buildSlideHTML as buildPdfSlideHTML } from '../../src/services/pdf_client';
import { buildSlideHTML as buildPptxSlideHTML } from '../../src/services/pptx_client';
import { buildSlideHtml as buildScreenshotSlideHtml } from '../../src/services/screenshotCapture';
import { buildCompositeHtml } from '../../src/services/domWalker';

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

// A deck whose slide root carries a model-authored print-preview margin —
// the exact dsv2 F3 pattern (`.slide { margin: 32px auto }`): every clipping
// surface must pin the root back to the frame origin or the bottom 32px of
// content is silently truncated.
const MARGIN_DECK_CSS =
  '.slide { margin: 32px auto; width: 1280px; height: 720px; background: #204060; }';
const MARGIN_SLIDE_HTML = '<div class="slide"><h1 style="margin:0">Margin probe</h1></div>';

async function setupSurfaceMocks(page: Page, css: string, slideHtml?: string) {
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
  // stock slides mock, letting each test choose its deck CSS (and,
  // optionally, its slide markup).
  const slideDeck: Record<string, unknown> = {
    ...mockSlidesResponse.slide_deck,
    css,
  };
  if (slideHtml) {
    slideDeck.slides = (
      mockSlidesResponse.slide_deck.slides as Array<Record<string, unknown>>
    ).map((s) => ({ ...s, html: slideHtml }));
  }
  await page.route(
    `http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/slides`,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockSlidesResponse, slide_deck: slideDeck }),
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

test.describe('Slide-root outer margin neutralization (dsv2 F3)', () => {
  test('tile and filmstrip previews pin a margined slide root to the frame origin', async ({ page }) => {
    await setupSurfaceMocks(page, MARGIN_DECK_CSS, MARGIN_SLIDE_HTML);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const tileRoot = page
      .frameLocator('iframe[title="Slide 1"]')
      .locator('.slide')
      .first();
    await expect(tileRoot).toBeVisible({ timeout: 15000 });
    expect(
      await tileRoot.evaluate((el) => el.getBoundingClientRect().top),
      'SlideTile (shared SLIDE_PREVIEW_RESET_STYLE surface)',
    ).toBe(0);

    const stripRoot = page
      .frameLocator('iframe[title="Slide 1 preview"]')
      .locator('.slide')
      .first();
    await expect(stripRoot).toBeVisible({ timeout: 15000 });
    expect(
      await stripRoot.evaluate((el) => el.getBoundingClientRect().top),
      'filmstrip (SlideSelection reset surface)',
    ).toBe(0);
  });

  test('single-slide export documents pin a margined slide root to the frame origin', async ({ page }) => {
    // WYSIWYG invariant: the pdf / huashu-screenshot / thumbnail documents all
    // force-wrap the slide at 1280x720 with overflow:hidden, so a root margin
    // that survives into them clips the bottom edge of the EXPORT too.
    const deck = {
      title: 'T',
      css: MARGIN_DECK_CSS,
      scripts: '',
      external_scripts: [],
      slides: [{ slide_id: 's1', html: MARGIN_SLIDE_HTML, scripts: '' }],
    } as never;

    const documents: Array<[string, string]> = [
      ['pdf export', buildPdfSlideHTML(deck, 0)],
      ['pptx capture', buildPptxSlideHTML(deck, 0)],
      ['screenshot capture', buildScreenshotSlideHtml(deck, 0)],
    ];
    for (const [name, doc] of documents) {
      await page.setContent(doc, { waitUntil: 'load' });
      const top = await page.evaluate(
        () => document.querySelector('.slide')!.getBoundingClientRect().top,
      );
      expect(top, `${name} document`).toBe(0);
    }
  });

  test('records-export composite pins margined roots regardless of class name', async ({ page }) => {
    // The composite already neutralized `.slide`-classed roots; the guarantee
    // must hold for ANY root element the model authored.
    const deck = {
      title: 'T',
      css: 'article.frame { margin: 40px auto; width: 1280px; height: 720px; }',
      scripts: '',
      external_scripts: [],
      slides: [
        {
          slide_id: 's1',
          html: '<article class="frame"><h1 style="margin:0">Any-root probe</h1></article>',
          scripts: '',
        },
      ],
    } as never;

    await page.setContent(buildCompositeHtml(deck), { waitUntil: 'load' });
    const top = await page.evaluate(
      () => document.querySelector('article.frame')!.getBoundingClientRect().top,
    );
    expect(top).toBe(0);
  });
});
