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
import { buildCompositeHtml, WALKER_SOURCE } from '../../src/services/domWalker';
import {
  buildSlideDocument,
  buildStandaloneDeckDocument,
  findSlideRoot,
  slideHostFrameStyle,
  SLIDE_PREVIEW_RESET_STYLE,
} from '../../src/services/slideDocument';

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
  "body { margin: 0; background: #102030; font-family: 'Acme Sans', sans-serif; } " +
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
    expect(style.background).toBe('rgb(16, 32, 48)');
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

// ─── Uniform root-slide reset (dsv2 cross-review F2) ────────────────────────
// A model-authored print-preview card on the slide ROOT — outer margin,
// rounded corners and a drop shadow, all !important — must be flattened
// IDENTICALLY on every surface: a PPTX canvas cannot render root rounding or
// shadows, so preview/export parity is only achievable by stripping them
// everywhere. Inner elements (cards, buttons, images) keep their own radius
// and shadow. Before the shared reset, the records walker was the only
// surface that stripped radius/shadow, and the `body > *` margin reset used
// by tile/filmstrip/pdf/pptx/screenshot lost the specificity fight against
// authored `.slide { margin: 40px auto !important }`.

const HOSTILE_ROOT_DECK_CSS =
  '.slide { margin: 40px auto !important; border-radius: 18px !important; ' +
  'box-shadow: 0 12px 40px rgba(16, 32, 48, 0.5) !important; ' +
  'width: 1280px; height: 720px; background: #204060; } ' +
  '.card { width: 320px; height: 120px; background: #f0f4f8; ' +
  'border-radius: 12px; box-shadow: 0 4px 10px rgba(16, 32, 48, 0.35); }';
const HOSTILE_ROOT_SLIDE_HTML =
  '<div class="slide"><h1 style="margin:0">Reset probe</h1>' +
  '<div class="card">Inner card</div></div>';

/** Serializable computed-style probe for a slide root element. */
const ROOT_PROBE = (el: Element) => {
  const cs = getComputedStyle(el);
  return {
    marginTop: cs.marginTop,
    borderRadius: cs.borderRadius,
    boxShadow: cs.boxShadow,
    top: el.getBoundingClientRect().top,
  };
};

/** Serializable computed-style probe for the inner card. */
const CARD_PROBE = (el: Element) => {
  const cs = getComputedStyle(el);
  return { borderRadius: cs.borderRadius, boxShadow: cs.boxShadow };
};

test.describe('Uniform root-slide reset (dsv2 cross-review F2)', () => {
  test('tile and filmstrip previews flatten a hostile !important root card', async ({ page }) => {
    await setupSurfaceMocks(page, HOSTILE_ROOT_DECK_CSS, HOSTILE_ROOT_SLIDE_HTML);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    for (const [name, title] of [
      ['SlideTile', 'Slide 1'],
      ['filmstrip', 'Slide 1 preview'],
    ] as const) {
      const frame = page.frameLocator(`iframe[title="${title}"]`);
      const root = frame.locator('.slide').first();
      await expect(root).toBeVisible({ timeout: 15000 });

      const rootStyle = await root.evaluate(ROOT_PROBE);
      expect.soft(rootStyle.marginTop, `${name}: root outer margin`).toBe('0px');
      expect.soft(rootStyle.top, `${name}: root pinned to frame origin`).toBe(0);
      expect.soft(rootStyle.borderRadius, `${name}: root corner radius`).toBe('0px');
      expect.soft(rootStyle.boxShadow, `${name}: root drop shadow`).toBe('none');

      const card = await frame.locator('.card').first().evaluate(CARD_PROBE);
      expect.soft(card.borderRadius, `${name}: inner card keeps radius`).toBe('12px');
      expect
        .soft(card.boxShadow, `${name}: inner card keeps shadow`)
        .toContain('rgba(16, 32, 48, 0.35)');
    }
  });

  test('presentation mode flattens the hostile root like the records walker', async ({ page }) => {
    await setupSurfaceMocks(page, HOSTILE_ROOT_DECK_CSS, HOSTILE_ROOT_SLIDE_HTML);
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present' });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();
    await expect(
      page.locator('div[style*="position: fixed"][style*="z-index: 9999"]'),
    ).toBeVisible({ timeout: 5000 });

    const frame = page.frameLocator('div[style*="z-index: 9999"] iframe');
    const root = frame.locator('.slide-container > .slide').first();
    await expect(root).toBeVisible({ timeout: 5000 });

    const rootStyle = await root.evaluate(ROOT_PROBE);
    expect.soft(rootStyle.marginTop, 'presentation: root outer margin').toBe('0px');
    expect.soft(rootStyle.borderRadius, 'presentation: root corner radius').toBe('0px');
    expect.soft(rootStyle.boxShadow, 'presentation: root drop shadow').toBe('none');

    const card = await frame.locator('.card').first().evaluate(CARD_PROBE);
    expect.soft(card.borderRadius, 'presentation: inner card keeps radius').toBe('12px');
    expect
      .soft(card.boxShadow, 'presentation: inner card keeps shadow')
      .toContain('rgba(16, 32, 48, 0.35)');
  });

  test('export documents flatten the hostile root and keep inner card styling', async ({ page }) => {
    const deck = {
      title: 'T',
      css: HOSTILE_ROOT_DECK_CSS,
      scripts: '',
      external_scripts: [],
      slides: [{ slide_id: 's1', html: HOSTILE_ROOT_SLIDE_HTML, scripts: '' }],
    } as never;

    const documents: Array<{
      name: string;
      doc: string;
      rootSelector: string;
      pinnedToOrigin: boolean;
    }> = [
      { name: 'pdf export', doc: buildPdfSlideHTML(deck, 0), rootSelector: '.slide', pinnedToOrigin: true },
      { name: 'pptx capture', doc: buildPptxSlideHTML(deck, 0), rootSelector: '.slide', pinnedToOrigin: true },
      { name: 'screenshot capture', doc: buildScreenshotSlideHtml(deck, 0), rootSelector: '.slide', pinnedToOrigin: true },
      { name: 'records composite', doc: buildCompositeHtml(deck), rootSelector: 'section.slide-container > .slide', pinnedToOrigin: true },
      // The standalone document lays slides out as a scrollable page (body
      // padding + card chrome), so the root is flattened INSIDE its
      // .slide-container rather than pinned to the viewport origin.
      { name: 'standalone html export', doc: buildStandaloneDeckDocument(deck), rootSelector: '.slide-container > .slide', pinnedToOrigin: false },
    ];
    for (const { name, doc, rootSelector, pinnedToOrigin } of documents) {
      await page.setContent(doc, { waitUntil: 'load' });
      const probe = await page.evaluate((sel) => {
        const root = document.querySelector(sel) as HTMLElement;
        const card = document.querySelector('.card') as HTMLElement;
        const rootCs = getComputedStyle(root);
        const cardCs = getComputedStyle(card);
        return {
          marginTop: rootCs.marginTop,
          borderRadius: rootCs.borderRadius,
          boxShadow: rootCs.boxShadow,
          top: root.getBoundingClientRect().top,
          cardRadius: cardCs.borderRadius,
          cardShadow: cardCs.boxShadow,
        };
      }, rootSelector);

      expect.soft(probe.marginTop, `${name}: root outer margin`).toBe('0px');
      if (pinnedToOrigin) {
        expect.soft(probe.top, `${name}: root pinned to frame origin`).toBe(0);
      }
      expect.soft(probe.borderRadius, `${name}: root corner radius`).toBe('0px');
      expect.soft(probe.boxShadow, `${name}: root drop shadow`).toBe('none');
      expect.soft(probe.cardRadius, `${name}: inner card keeps radius`).toBe('12px');
      expect
        .soft(probe.cardShadow, `${name}: inner card keeps shadow`)
        .toContain('rgba(16, 32, 48, 0.35)');
    }
  });
});

// ─── UI <-> export box-model parity ─────────────────────────────────────────
// f19627d removed the universal `* { box-sizing: border-box }` from the four
// PREVIEW resets, because Claude Design ground truth lays slide content out in
// CONTENT-box. It left the one remaining occurrence in the export builders, so
// slide descendants became content-box on screen and border-box in the export.
//
// The deck below is the shape that is EXPOSED to this: it declares `box-sizing`
// only SCOPED, on `.slide`, so its descendants inherit nothing and take whatever
// the host injects. 17 of 46 live decks are shaped this way. The other 29 declare
// a universal rule of their OWN, which masks an injected one entirely — measuring
// only those is what let this ship, so IMMUNE_DECK_CSS is pinned here too as the
// control that proves the probe is reading the host and not the deck.
const EXPOSED_DECK_CSS =
  '.slide { box-sizing: border-box; width: 1280px; height: 720px; padding: 72px 88px; }'
  + '.step-card { width: 256px; padding: 18px; border: 1px solid #ccd; background: #eef; }';
const IMMUNE_DECK_CSS = `* { box-sizing: border-box; } ${EXPOSED_DECK_CSS}`;
// The `h1`/`p` are load-bearing, not decoration. The reset that replaced the
// universal rule has TWO halves — `box-sizing` AND `margin: 0; padding: 0` — and
// the card alone cannot see the second one: a bare `div` carries no UA margin, so
// a universal margin reset and a scoped one look identical through it. These two
// elements DO carry UA margins, so they fail if the scoped `html, body` reset is
// dropped (the standalone document then takes the UA's 8px body margin) or if it
// is re-universalised (slide descendants then lose UA margins the previews keep).
const BOX_SLIDE_HTML =
  '<div class="slide"><h1>Heading</h1><p>Body copy</p>'
  + '<div class="step-card">Discover</div></div>';

/** Box model of the probe card, plus the UA-margin and shell witnesses. */
async function boxProbe(page: Page, doc: string, selector: string) {
  await page.setContent(doc, { waitUntil: 'load' });
  return page.evaluate((sel) => {
    const el = document.querySelector(sel) as HTMLElement;
    const slide = el.closest('.slide') as HTMLElement;
    return {
      width: +el.getBoundingClientRect().width.toFixed(2),
      boxSizing: getComputedStyle(el).boxSizing,
      h1MarginTop: getComputedStyle(slide.querySelector('h1')!).marginTop,
      pMarginTop: getComputedStyle(slide.querySelector('p')!).marginTop,
      bodyMarginTop: getComputedStyle(document.body).marginTop,
    };
  }, selector);
}

// ─── DS-pinned (WRAPPED) deck export fidelity ────────────────────────────────
// THE DEFECT: "Download PDF" shipped a design-system-pinned deck on a PURE BLACK
// ground. A pinned deck's slide root is a <section> carrying the ground via a bare
// TYPE selector, with `.slide` absolutely positioned inside it — so the <section>
// holds no in-flow content, collapses to height 0, and the ground it carries never
// paints. Measured on the delivered PDF's own DCTDecode streams: ground rgb(0,0,0)
// at 90.9%, brand inks at 1.5450 / 1.8027 / 2.9292, failing WCAG AA at both 4.5:1
// and 3:1 for every ink except --db-ink-muted.
//
// TWO CANDIDATE FIXES WERE SHIPPED TOGETHER AT 0.4.2.dev17; ONE IS REVERTED.
//
//   REVERTED — the slide-host frame contract in the four export builders. It
//   framed `body` and stretched its CHILD with `position: absolute !important;
//   inset: 0 !important; width/height: 100% !important`. On the huashu path that
//   DESTROYS TABLES: preprocess.mjs::flattenTables() appends every <td>/<th> to
//   `body` as an absolutely positioned <div> whose left/top/width/height are
//   NON-important INLINE styles, so the stylesheet !important rule outranks each
//   cell's own position. Measured on a real 21-cell deck: distinct cell rects in
//   ppt/slides/slide1.xml 42 -> 11, with 12 shapes stacked at (12.0, 349.8).
//   The built DOCUMENT is unchanged by it, so a document probe reads 0.00 px and
//   is blind — the damage is EMIT-TIME.
//
//   KEPT — the slide-root LOCATOR (findSlideRoot). It aims the capture at the
//   element that carries the ground instead of at `.slide`. Locator-only measures
//   the delivered PDF at rgb(248,247,243) with inks 12.6794 / 10.8670 / 6.6878,
//   because exportSlideDeckToPDF force-sizes whatever the locator resolves to. It
//   injects no CSS, so it cannot perturb emitted geometry.
//
// So the tests below pin the contract's ABSENCE in the documents, and pin the
// ground on the DELIVERED ARTIFACTS rather than on the documents.
//
// WHY THIS FIXTURE SHAPE. An UNWRAPPED corpus cannot see this defect at all — 0 of
// 47 pre-existing decks wrap, which is exactly how it shipped — and a
// `dark`/`event`/`white` variant class paints its own ground and is immune. So the
// deck below WRAPS, and its slide carries a BARE class="slide".
const DS_GROUND_RGBA = '249,247,244,255';
const DS_WRAPPED_DECK_CSS =
  'html, body { background: #0E1A1F; }'
  + 'section { background: #F9F7F4; color: #3A3838; font-family: Arial, Helvetica, sans-serif; overflow: hidden; }'
  + '.slide { position: absolute; inset: 0; padding: 72px 88px; display: flex; flex-direction: column; gap: 24px; }'
  + 'h1.headline { color: #1B3139; font-size: 64px; margin: 0; }'
  + 'p.bodycopy { color: #3A3838; font-size: 24px; margin: 0; }'
  + 'p.mutedink { color: #5A5755; font-size: 20px; margin: 0; }';
const DS_WRAPPED_SLIDE_HTML =
  '<section data-label="Ground"><div class="slide">'
  + '<h1 class="headline">Acme Quarterly</h1>'
  + '<p class="bodycopy">Body copy on the brand paper ground.</p>'
  + '<p class="mutedink">Muted supporting line.</p>'
  + '</div></section>';

/** The three brand inks from the defect report, with their AA thresholds. */
const BRAND_INKS: Record<string, readonly [number, number, number]> = {
  'headline 1B3139': [0x1b, 0x31, 0x39],
  'body 3A3838': [0x3a, 0x38, 0x38],
  'subtitle 5A5755': [0x5a, 0x57, 0x55],
};

function srgbChannel(c: number): number {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}
function relativeLuminance(rgb: readonly number[]): number {
  return (
    0.2126 * srgbChannel(rgb[0])
    + 0.7152 * srgbChannel(rgb[1])
    + 0.0722 * srgbChannel(rgb[2])
  );
}
function contrastRatio(a: readonly number[], b: readonly number[]): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const dsWrappedDeck = () =>
  ({
    title: 'DS-pinned wrapped deck',
    css: DS_WRAPPED_DECK_CSS,
    scripts: '',
    external_scripts: [],
    slides: [{ slide_id: 's1', html: DS_WRAPPED_SLIDE_HTML, scripts: '' }],
  }) as never;

// The UNWRAPPED counterpart — the shape 47 of 47 pre-existing decks have, and the
// control for the capture-site force-size. `.slide` is the direct child of <body>
// here, so findSlideRoot's walk-up never executes and it returns `.slide` ITSELF,
// not <body>: the force-size's guard is `!== doc.body`, so this deck goes down the
// SAME branch as a wrapped one and is the deck that would show collateral damage.
// Same palette as the wrapped fixture so the two are directly comparable.
const DS_UNWRAPPED_DECK_CSS =
  'html, body { background: #0E1A1F; }'
  + '.slide { width: 1280px; height: 720px; background: #F9F7F4; color: #3A3838;'
  + ' font-family: Arial, Helvetica, sans-serif; display: flex; flex-direction: column;'
  + ' gap: 24px; overflow: hidden; }'
  + 'h1.headline { color: #1B3139; font-size: 64px; margin: 0; }'
  + 'p.bodycopy { color: #3A3838; font-size: 24px; margin: 0; }'
  + 'p.mutedink { color: #5A5755; font-size: 20px; margin: 0; }';
const DS_UNWRAPPED_SLIDE_HTML =
  '<div class="slide">'
  + '<h1 class="headline">Acme Quarterly</h1>'
  + '<p class="bodycopy">Body copy on the brand paper ground.</p>'
  + '<p class="mutedink">Muted supporting line.</p>'
  + '</div>';

const dsUnwrappedDeck = () =>
  ({
    title: 'unwrapped deck',
    css: DS_UNWRAPPED_DECK_CSS,
    scripts: '',
    external_scripts: [],
    slides: [{ slide_id: 's1', html: DS_UNWRAPPED_SLIDE_HTML, scripts: '' }],
  }) as never;

/**
 * Assert a built EXPORT document carries no slide-host frame contract.
 *
 * The contract was injected into all four export builders at 0.4.2.dev17 and is
 * reverted: on the huashu path it collapses every flattened table cell onto one
 * rect (preprocess.mjs::flattenTables appends each cell to `body` with its
 * position as NON-important inline styles, so a `body > *` !important rule
 * outranks them — 42 -> 11 distinct cell rects measured on a real 21-cell deck).
 *
 * Checked two ways so a reintroduction under a different host selector is still
 * caught: the exact rendered rule for this host, and the `#tellr-host-frame-boost`
 * specificity id, which is never minted on any element and therefore appears in a
 * document only when the contract rendered into it.
 */
function expectNoFrameContract(doc: string, hostSelector: string, label: string): void {
  expect(doc, `${label} must not inject slideHostFrameStyle('${hostSelector}')`)
    .not.toContain(slideHostFrameStyle(hostSelector));
  expect(doc, `${label} must not carry the frame contract under ANY selector`)
    .not.toContain('#tellr-host-frame-boost');
}

/**
 * The MODAL PAINTED COLOUR of a region, read from a real screenshot's pixels.
 *
 * Deliberately not getComputedStyle: a 1280x0 <section> still COMPUTES
 * rgb(249,247,244), so computed style cannot see this defect at all. Only paint
 * can. Alpha is included because the screenshot-PPTX path emits PNG, where a
 * transparent capture stays transparent rather than flattening to black.
 */
async function paintedGround(page: Page, doc: string) {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.setContent(doc, { waitUntil: 'load' });
  const shot = await page.screenshot({
    clip: { x: 0, y: 0, width: 1280, height: 720 },
  });
  const dataUrl = `data:image/png;base64,${shot.toString('base64')}`;
  return page.evaluate(async (url) => {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error('decode failed'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const counts = new Map<string, number>();
    for (let i = 0; i < data.length; i += 4) {
      const key = `${data[i]},${data[i + 1]},${data[i + 2]},${data[i + 3]}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    let best = '';
    let bestN = -1;
    for (const [k, n] of counts) if (n > bestN) { best = k; bestN = n; }
    return {
      rgba: best,
      rgb: best.split(',').slice(0, 3).map(Number),
      share: bestN / (data.length / 4),
    };
  }, dataUrl);
}

test.describe('DS-pinned (wrapped) deck export fidelity', () => {
  for (const [name, build, host] of [
    ['pdf export', buildPdfSlideHTML, 'body'],
    ['screenshot capture', buildScreenshotSlideHtml, 'body'],
  ] as const) {
    test(`${name} injects no frame contract, even on a wrapped deck`, async ({ page }) => {
      // THE REGRESSION GUARD on this surface. The wrapped deck is the fixture the
      // contract was added for, so it is where a reintroduction is most tempting.
      const doc = build(dsWrappedDeck(), 0);
      expectNoFrameContract(doc, host, name);

      // And the honest consequence, measured rather than asserted away: WITHOUT
      // the contract this DOCUMENT's wrapper collapses and its ground does not
      // paint. That is the dev16 behaviour.
      //
      // It does not follow that the delivered artifact is wrong. For the PDF the
      // slide-root LOCATOR repairs it at capture time, because
      // exportSlideDeckToPDF force-sizes whatever the locator resolves to — see
      // 'exportSlideDeckToPDF captures the wrapper' below, which measures the
      // DELIVERED PDF's own pixels. Document-level ground is therefore recorded
      // here, not required.
      const ground = await paintedGround(page, doc);
      expect(
        ground.rgba,
        `${name}: the wrapper ground must NOT paint in the document — if it does, `
          + 'something is stretching the wrapper again and tables are at risk',
      ).not.toBe(DS_GROUND_RGBA);
    });
  }

  test('the records composite injects no contract, and prunes a wrapped slide', async ({
    page,
  }) => {
    // THE ACCEPTED REGRESSION, pinned rather than hidden.
    //
    // The walker's isVisible() is false at height === 0 and visit() returns
    // WITHOUT descending, so on a section-wrapped deck a collapsed wrapper does
    // not merely fail to paint — it PRUNES THE WHOLE SLIDE SUBTREE, giving 1 rect
    // and 0 text records per slide. The frame contract gave the wrapper area and
    // brought the text back, but it is reverted because the same rule destroys
    // tables on the PRIMARY (huashu) path, and this composite is only the records
    // FALLBACK: it runs when the sidecar is unavailable, i.e. the startup 503
    // window. It was equally broken before 0.4.2.dev17.
    //
    // There is no locator to keep here, unlike the PDF and screenshot surfaces:
    // the walker is handed `section.slide-container` by selector.
    //
    // This test is a guard in BOTH directions — it fails if the contract comes
    // back, and it fails if the pruning silently changes.
    const doc = buildCompositeHtml(dsWrappedDeck());
    expectNoFrameContract(doc, 'section.slide-container', 'records composite');

    await page.setContent(doc, { waitUntil: 'load' });
    await page.addScriptTag({ content: WALKER_SOURCE });
    const counted = await page.evaluate(() => {
      const extract = (window as unknown as {
        __extractSlide: (el: Element) => { records: { kind: string }[] };
      }).__extractSlide(document.querySelector('section.slide-container')!);
      return {
        text: extract.records.filter((r) => r.kind === 'text').length,
        total: extract.records.length,
      };
    });

    expect(counted.text, 'accepted: a collapsed wrapper prunes every text run').toBe(0);
    expect(counted.total, 'accepted: one rect survives for the wrapper itself').toBe(1);
  });

  test('findSlideRoot resolves to the ground-carrying wrapper, not .slide', async ({ page }) => {
    // Root cause #2, independent of the contract: the capture surfaces aimed at
    // `.slide`, which on a pinned deck is the TRANSPARENT child of the wrapper.
    // Captured with backgroundColor: null that transparency reaches the artifact,
    // where JPEG (no alpha) flattens it to BLACK.
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.setContent(buildPdfSlideHTML(dsWrappedDeck(), 0), { waitUntil: 'load' });
    // Injected as an inline <script> (allowed by SLIDE_CSP's 'unsafe-inline'),
    // never new Function() — the slide CSP withholds 'unsafe-eval' on purpose.
    await page.addScriptTag({
      content: `window.__findSlideRoot = ${findSlideRoot.toString()};`,
    });

    const probe = await page.evaluate(() => {
      const root = (window as unknown as {
        __findSlideRoot: (d: Document) => HTMLElement;
      }).__findSlideRoot(document);
      const legacy = document.querySelector('.slide') as HTMLElement;
      return {
        rootTag: root.tagName.toLowerCase(),
        rootBg: getComputedStyle(root).backgroundColor,
        rootHeight: Math.round(root.getBoundingClientRect().height),
        legacyTag: legacy.tagName.toLowerCase(),
        legacyBg: getComputedStyle(legacy).backgroundColor,
      };
    });

    expect(probe.rootTag, 'the slide root is the wrapper').toBe('section');
    expect(probe.rootBg, 'the wrapper is what carries the ground').toBe('rgb(249, 247, 244)');
    // The wrapper has NO area in the document — it holds no in-flow content and
    // `.slide` inside it is out of flow. That is the point of the locator rather
    // than an argument against it: it names the element that CARRIES THE GROUND,
    // and exportSlideDeckToPDF then force-sizes exactly that element inline before
    // capturing. Asserting 720 here would be asserting the reverted frame
    // contract, which is what destroyed tables on the huashu path.
    expect(probe.rootHeight, 'the wrapper is collapsed in the document itself').toBe(0);
    // CONTROL — what the old locator returned: a transparent element. This is the
    // whole of root cause #2, and it is why the delivered JPEG was pure black.
    expect(probe.legacyTag).toBe('div');
    expect(probe.legacyBg, 'the old target paints nothing').toBe('rgba(0, 0, 0, 0)');
  });
});

// ─── The two CAPTURE CALL SITES ──────────────────────────────────────────────
// The block above pins findSlideRoot itself, and the documents' painted ground.
// Neither reaches the two lines that actually USE the locator —
// `findSlideRoot(iframeDoc)` in exportSlideDeckToPDF and `findSlideRoot(doc)` in
// captureDeckAsPngDataUrls. Those two lines ARE root cause #2, and reverting both
// to the legacy `.slide` target left every other test in this file green.
//
// So these two tests run the REAL SHIPPED FUNCTIONS in a real page, via the Vite
// dev server, and assert on what the capture ACTUALLY PRODUCES — the delivered PDF
// and the delivered PNG — rather than on the locator in isolation. Testing a
// function while leaving its callers unpinned is precisely the gap.
//
// Each carries a STALENESS GUARD. `reuseExistingServer` will happily serve a vite
// from a different worktree on port 3000, which is how a spec silently tests code
// that is not the code under review; importing the module and requiring
// findSlideRoot to exist turns that into a loud failure instead of a false green.
//
// No <canvas> in this fixture, deliberately: the Chart.js trap (a canvas left at
// 300x150 on one side only) needs a chart to bite, and a CDN dependency would add
// nothing to a defect about which element gets painted. Both `scripts` and
// `external_scripts` are still passed, so the deck shape is the real one.

/** Decode a data URL and report its modal pixel plus how much is transparent. */
async function measureDataUrl(page: Page, dataUrl: string) {
  return page.evaluate(async (url) => {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error('decode failed'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const counts = new Map<string, number>();
    let transparent = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] === 0) transparent++;
      const key = `${data[i]},${data[i + 1]},${data[i + 2]},${data[i + 3]}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    let best = '';
    let bestN = -1;
    for (const [k, n] of counts) if (n > bestN) { best = k; bestN = n; }
    const total = data.length / 4;
    return {
      w: canvas.width,
      h: canvas.height,
      rgba: best,
      rgb: best.split(',').slice(0, 3).map(Number),
      share: bestN / total,
      transparentShare: transparent / total,
    };
  }, dataUrl);
}

/**
 * Composite a delivered PNG over WHITE, then report its GROUND and its INK
 * separately — because on this surface those two failure modes are independent.
 *
 * `backgroundColor: null` means a capture can ship ink with no ground (the
 * pre-locator behaviour: 98.50% transparent, its darkest ink contrasting 13.5922
 * against the white it lands on) or a ground with no ink (a force-sized wrapper
 * whose text never resolved), and only one of those four combinations is a
 * correct slide. A single scalar cannot tell them apart, so this returns both.
 *
 * White is the right compositing ground because white is what every consumer of
 * these PNGs actually supplies: /api/export/pptx/editable/from-images embeds
 * each one as a full-slide picture on a PPTX slide. Raw alpha is reported too —
 * a fully transparent PNG composites to pure white and would otherwise read as
 * a perfectly clean white slide rather than as the blank it is.
 *
 * Ink is defined as "clears WCAG AA against the modal painted colour", which
 * counts glyph cores and excludes antialiased edges, and is the same measure
 * the delivered-PDF test applies to its ground.
 */
async function measurePngOverWhite(page: Page, dataUrl: string) {
  return page.evaluate(async (url) => {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error('decode failed'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);

    // WCAG maths, restated here because this body is evaluated in the page.
    const chan = (c: number) => {
      const v = c / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    const lum = (r: number, g: number, b: number) =>
      0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
    const ratio = (a: number, b: number) =>
      (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const over = (c: number, a: number) => Math.round((c * a) / 255 + 255 * (1 - a / 255));

    // Pass 1 — the ground: modal composited colour, distinct non-white colours,
    // and the UNCOMPOSITED alpha share.
    const counts = new Map<number, number>();
    let transparent = 0;
    for (let i = 0; i < data.length; i += 4) {
      const a = data[i + 3];
      if (a === 0) transparent++;
      const key = (over(data[i], a) << 16) | (over(data[i + 1], a) << 8) | over(data[i + 2], a);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    let ground = 0;
    let groundN = -1;
    let uniqueNonWhite = 0;
    for (const [k, n] of counts) {
      if (k !== 0xffffff) uniqueNonWhite++;
      if (n > groundN) {
        groundN = n;
        ground = k;
      }
    }
    const groundRgb = [(ground >> 16) & 255, (ground >> 8) & 255, ground & 255];
    const groundLum = lum(groundRgb[0], groundRgb[1], groundRgb[2]);

    // Pass 2 — the ink: every composited pixel clearing AA against that ground,
    // plus the darkest pixel in the image, which is the headline.
    let inkPixels = 0;
    let darkest = ground;
    let darkestLum = groundLum;
    for (let i = 0; i < data.length; i += 4) {
      const a = data[i + 3];
      const r = over(data[i], a);
      const g = over(data[i + 1], a);
      const b = over(data[i + 2], a);
      const l = lum(r, g, b);
      if (ratio(l, groundLum) >= 4.5) inkPixels++;
      if (l < darkestLum) {
        darkestLum = l;
        darkest = (r << 16) | (g << 8) | b;
      }
    }
    const total = data.length / 4;
    return {
      w: canvas.width,
      h: canvas.height,
      transparentShare: transparent / total,
      groundRgb,
      groundShare: groundN / total,
      uniqueNonWhite,
      inkPixels,
      darkestRgb: [(darkest >> 16) & 255, (darkest >> 8) & 255, darkest & 255],
    };
  }, dataUrl);
}

/** Require that port 3000 is serving THIS worktree, not another one. */
async function assertFreshDevServer(page: Page) {
  const kinds = await page.evaluate(async () => {
    const m = (await import('/src/services/slideDocument.ts')) as Record<string, unknown>;
    return { findSlideRoot: typeof m.findSlideRoot, hostFrame: typeof m.slideHostFrameStyle };
  });
  expect(
    kinds.findSlideRoot,
    'dev server on :3000 is serving a worktree without findSlideRoot — stale vite, results would be meaningless',
  ).toBe('function');
  expect(kinds.hostFrame).toBe('function');
}

/** Every JPEG the PDF actually ships, anchored on /DCTDecode. */
function extractJpegStreams(buf: Buffer): Buffer[] {
  const out: Buffer[] = [];
  const hay = buf.toString('latin1');
  let idx = 0;
  while ((idx = hay.indexOf('/DCTDecode', idx)) !== -1) {
    const s = hay.indexOf('stream', idx);
    if (s === -1) break;
    let p = s + 'stream'.length;
    if (hay[p] === '\r') p++;
    if (hay[p] === '\n') p++;
    const e = hay.indexOf('endstream', p);
    if (e === -1) break;
    let end = e;
    while (end > p && (hay[end - 1] === '\n' || hay[end - 1] === '\r')) end--;
    const bytes = buf.subarray(p, end);
    if (bytes[0] === 0xff && bytes[1] === 0xd8) out.push(bytes);
    idx = e;
  }
  return out;
}

test.describe('Export capture call sites (root cause #2)', () => {
  test('exportSlideDeckToPDF captures the wrapper, so the delivered PDF has a ground', async ({
    page,
  }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await assertFreshDevServer(page);

    const download = page.waitForEvent('download', { timeout: 90000 });
    await page.evaluate(async (deck) => {
      const m = (await import('/src/services/pdf_client.ts')) as {
        exportSlideDeckToPDF: (d: unknown, f: string, o: unknown) => Promise<void>;
      };
      await m.exportSlideDeckToPDF(deck, 'capture-site.pdf', {});
    }, dsWrappedDeck());

    const stream = await (await download).createReadStream();
    const chunks: Buffer[] = [];
    for await (const c of stream) chunks.push(c as Buffer);
    const jpegs = extractJpegStreams(Buffer.concat(chunks));
    expect(jpegs.length, 'the PDF must ship one DCTDecode image per slide').toBe(1);

    const m = await measureDataUrl(page, `data:image/jpeg;base64,${jpegs[0].toString('base64')}`);

    // The failure mode this pins: aiming at the transparent `.slide` sends
    // transparency into toDataURL('image/jpeg'), which has no alpha channel and
    // flattens it to BLACK. Measured with the legacy target: rgb(0,0,0) at 1.5450.
    for (const [i, channel] of ['r', 'g', 'b'].entries()) {
      expect(
        m.rgb[i],
        `delivered PDF ground ${channel} — rgb(${m.rgb.join(',')}) must be the brand paper, not black`,
      ).toBeGreaterThan(240);
    }
    // Tight enough to pin the actual colour, loose enough for JPEG quantisation.
    const expected: Record<string, number> = {
      'headline 1B3139': 12.6794,
      'body 3A3838': 10.867,
      'subtitle 5A5755': 6.6878,
    };
    for (const [ink, rgb] of Object.entries(BRAND_INKS)) {
      const ratio = contrastRatio(rgb, m.rgb);
      expect(ratio, `${ink} must clear WCAG AA in the delivered PDF`).toBeGreaterThanOrEqual(4.5);
      expect(
        Math.abs(ratio - expected[ink]),
        `${ink} measured ${ratio.toFixed(4)}, expected ~${expected[ink]}`,
      ).toBeLessThan(0.25);
    }
  });

  test('captureDeckAsPngDataUrls paints the ground AND the ink on a wrapped deck', async ({
    page,
  }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await assertFreshDevServer(page);

    const dataUrl = await page.evaluate(async (deck) => {
      const m = (await import('/src/services/screenshotCapture.ts')) as {
        captureDeckAsPngDataUrls: (d: unknown) => Promise<string[]>;
      };
      return (await m.captureDeckAsPngDataUrls(deck))[0];
    }, dsWrappedDeck());

    const m = await measurePngOverWhite(page, dataUrl);

    // WHAT THIS TEST USED TO SAY, AND WHY IT WAS WRONG.
    //
    // Until this commit the assertion here was `transparentShare > 0.99`, under
    // the name '...stays transparent on a wrapped deck (accepted)'. That pinned a
    // 100.00%-transparent, ZERO-COLOUR, ENTIRELY BLANK PNG as the correct output
    // of an export. It encoded a wrong belief: that because the only alternative
    // on offer was the slide-host frame contract — which collapses flattened
    // table cells onto one rect on the huashu path — a blank artifact was the
    // best this surface could do, and the number was worth pinning so it could
    // not drift.
    //
    // The premise was false. The contract was never the only alternative: the
    // capture site can force the resolved element's geometry with INLINE styles
    // on that one element, which is what exportSlideDeckToPDF has always done
    // (pdf_client.ts) and which injects no CSS into the document at all — so it
    // cannot reach a flattened table cell, and the huashu path is untouched.
    // Both halves below now hold, so there is nothing left to accept.
    //
    // Do not restore the old assertion. A test that passes on a blank export is
    // worse than no test: it reports the defect as a settled decision.
    expect([m.w, m.h], 'scale:2 over a 1280x720 frame').toEqual([2560, 1440]);

    // GROUND half — pinned INDEPENDENTLY of the ink, so a text-only capture (the
    // pre-locator behaviour, 98.50% transparent) fails here even though its ink
    // assertions would pass. On a wrapped deck the ground lives on the <section>,
    // which is 1280x0 in the document; nothing paints unless it is sized first.
    expect(m.transparentShare, 'the delivered PNG must not be transparent').toBeLessThan(0.005);
    expect(m.groundRgb, 'the modal painted colour must be the brand paper').toEqual([
      249, 247, 244,
    ]);
    expect(m.groundShare, 'the paper must be most of the slide').toBeGreaterThan(0.5);

    // INK half — pinned INDEPENDENTLY of the ground, so a ground-only capture (a
    // sized wrapper whose text never resolved) fails here even though its ground
    // assertions would pass. The pre-locator capture measured 47,660 ink pixels
    // for these same three text runs at scale:2; a floor well under that cannot
    // be reached by antialiasing noise, and 0 is what a blank export scores.
    expect(m.inkPixels, 'the three text runs must survive into the PNG').toBeGreaterThan(20000);
    expect(m.uniqueNonWhite, 'a blank export has exactly 0 non-white colours').toBeGreaterThan(100);
    for (const [i, channel] of ['r', 'g', 'b'].entries()) {
      expect(
        Math.abs(m.darkestRgb[i] - BRAND_INKS['headline 1B3139'][i]),
        `darkest ink ${channel} — rgb(${m.darkestRgb.join(',')}) must be the #1B3139 headline`,
      ).toBeLessThanOrEqual(2);
    }

    // …and the two halves TOGETHER: the ink has to be legible against the ground
    // that now exists. Both figures are asserted because the fix changes which
    // comparison is even meaningful. 12.7110 is the headline against the brand
    // paper — the delivered PDF measures the same ink at 12.6794, the difference
    // being JPEG quantisation of the ground. 13.5922 is that same ink against
    // pure white, which is exactly what the pre-locator capture scored back when
    // it shipped ink and NO paper; holding it proves the INK did not change while
    // the ground appeared, rather than some new colour arriving.
    const overGround = contrastRatio(m.darkestRgb, m.groundRgb);
    expect(overGround, 'the headline must clear WCAG AA against the paper').toBeGreaterThanOrEqual(
      4.5,
    );
    expect(
      Math.abs(overGround - 12.711),
      `headline vs paper measured ${overGround.toFixed(4)}, expected ~12.7110`,
    ).toBeLessThan(0.25);
    const overWhite = contrastRatio(m.darkestRgb, [255, 255, 255]);
    expect(
      Math.abs(overWhite - 13.5922),
      `headline vs white measured ${overWhite.toFixed(4)}, expected ~13.5922 (the pre-locator figure)`,
    ).toBeLessThan(0.25);
  });

  test('the force-size does not move an UNWRAPPED deck', async ({ page }) => {
    // THE COLLATERAL-DAMAGE CONTROL for the test above. The fix it pins force-sizes
    // whatever findSlideRoot resolves to, and on an unwrapped deck that is `.slide`
    // ITSELF — not <body> — so this deck takes the same branch. 47 of 47
    // pre-existing decks are this shape, so a regression here would be the whole
    // corpus, while the wrapped test would stay happily green.
    test.setTimeout(120000);
    await page.goto('/');
    await assertFreshDevServer(page);

    // GEOMETRY IDENTITY, asserted by applying the force-size to a live document
    // and re-measuring: the point is not that some numbers look right, it is that
    // these four properties are a NO-OP on a deck that already declares its frame.
    // This is machine-independent, where an exact glyph count would not be.
    const geom = await page.evaluate(async (deck) => {
      const sd = (await import('/src/services/slideDocument.ts')) as {
        findSlideRoot: (doc: Document) => HTMLElement;
      };
      const sc = (await import('/src/services/screenshotCapture.ts')) as {
        buildSlideHtml: (d: unknown, i: number) => string;
      };
      const frame = document.createElement('iframe');
      frame.style.cssText = 'width:1280px;height:720px;position:fixed;left:-99999px;top:0;';
      document.body.appendChild(frame);
      frame.srcdoc = sc.buildSlideHtml(deck, 0);
      await new Promise((r) => {
        frame.onload = r;
      });
      const doc = frame.contentDocument!;
      const root = sd.findSlideRoot(doc);
      const read = () => {
        const r = root.getBoundingClientRect();
        const cs = doc.defaultView!.getComputedStyle(root);
        return `${Math.round(r.width)}x${Math.round(r.height)} @${Math.round(r.left)},${Math.round(
          r.top,
        )} pad=${cs.paddingTop}/${cs.paddingLeft} margin=${cs.marginTop}/${cs.marginLeft}`;
      };
      const before = read();
      root.style.width = '1280px';
      root.style.height = '720px';
      root.style.margin = '0';
      root.style.boxSizing = 'border-box';
      const after = read();
      const out = {
        isBody: root === doc.body,
        tag: root.tagName.toLowerCase(),
        cls: root.className,
        before,
        after,
      };
      document.body.removeChild(frame);
      return out;
    }, dsUnwrappedDeck());

    // Non-vacuity FIRST: if the locator returned <body> the force-size would be
    // skipped and "nothing moved" would prove nothing at all.
    expect(geom.isBody, 'the locator must NOT fall back to body on this deck').toBe(false);
    expect([geom.tag, geom.cls], 'the resolved root is `.slide` itself').toEqual(['div', 'slide']);
    expect(geom.after, 'the force-size must be a no-op on an unwrapped deck').toBe(geom.before);

    // …and the delivered PNG, which is what actually ships. Measured identical
    // either side of the fix — FNV-1a of the raw pixels 68079f00 both times.
    // Pinned as invariants rather than as that hash: glyph rasterisation is
    // platform-specific, so an exact count would fail on CI while proving nothing
    // extra here.
    const dataUrl = await page.evaluate(async (deck) => {
      const m = (await import('/src/services/screenshotCapture.ts')) as {
        captureDeckAsPngDataUrls: (d: unknown) => Promise<string[]>;
      };
      return (await m.captureDeckAsPngDataUrls(deck))[0];
    }, dsUnwrappedDeck());

    const m = await measurePngOverWhite(page, dataUrl);
    expect(m.transparentShare, 'an unwrapped capture was never transparent').toBe(0);
    expect(m.groundRgb, 'and its ground is still the brand paper').toEqual([249, 247, 244]);
    expect(m.inkPixels, 'and its text is still there').toBeGreaterThan(20000);
    for (const [i, channel] of ['r', 'g', 'b'].entries()) {
      expect(
        Math.abs(m.darkestRgb[i] - BRAND_INKS['headline 1B3139'][i]),
        `darkest ink ${channel} — rgb(${m.darkestRgb.join(',')}) must still be #1B3139`,
      ).toBeLessThanOrEqual(2);
    }
  });
});

test.describe('UI <-> export box-model parity', () => {
  for (const [label, css] of [
    ['deck scoping box-sizing to .slide (17/46 live decks)', EXPOSED_DECK_CSS],
    ['deck declaring its own universal rule (29/46, immune)', IMMUNE_DECK_CSS],
  ] as const) {
    test(`standalone export matches the preview box model — ${label}`, async ({ page }) => {
      const deck = {
        title: 'T',
        css,
        scripts: '',
        external_scripts: [],
        slides: [{ slide_id: 's1', html: BOX_SLIDE_HTML, scripts: '' }],
      } as never;

      await page.setViewportSize({ width: 1280, height: 720 });
      const ui = await boxProbe(
        page,
        buildSlideDocument(BOX_SLIDE_HTML, { css, extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE }),
        '.step-card',
      );
      await page.setViewportSize({ width: 1600, height: 1000 });
      const exported = await boxProbe(
        page,
        buildStandaloneDeckDocument(deck),
        '.slide-container > .slide > .step-card',
      );

      expect(exported.boxSizing, 'computed box-sizing must agree').toBe(ui.boxSizing);
      expect(exported.width, 'card width must agree').toBe(ui.width);

      // The MARGIN half of the scoped reset. Non-vacuity first: if the witnesses
      // ever stop carrying a UA margin they pin nothing, so assert they do before
      // asserting they agree.
      expect(ui.h1MarginTop, 'h1 witness must carry a UA margin').not.toBe('0px');
      expect(ui.pMarginTop, 'p witness must carry a UA margin').not.toBe('0px');
      expect(exported.h1MarginTop, 'h1 UA margin must agree').toBe(ui.h1MarginTop);
      expect(exported.pMarginTop, 'p UA margin must agree').toBe(ui.pMarginTop);
      // …and the other direction: the scoped reset must still zero the SHELL, or a
      // standalone document (no app shell above it) takes the UA's 8px body margin.
      expect(exported.bodyMarginTop, 'export shell must zero its own body margin').toBe('0px');
      expect(exported.bodyMarginTop, 'shell margin must match the preview').toBe(ui.bodyMarginTop);

      // CONTROL — re-inject the universal reset the fix removed and show the
      // divergence coming straight back, so this test cannot pass vacuously.
      // On the exposed deck THIS FIXTURE's card goes 294 (content-box: authored
      // 256 + 36 padding + 2 border) -> 256 (border-box); the live deck that
      // exposed the defect authored 220 and so measured 256 -> 220. On the immune
      // deck the deck's own rule already wins, which is precisely why a corpus of
      // those measured 0.00 and missed this.
      const broken = buildStandaloneDeckDocument(deck).replace(
        '<body>',
        '<style>* { box-sizing: border-box; margin: 0; padding: 0; }</style><body>',
      );
      const reinjected = await boxProbe(page, broken, '.slide-container > .slide > .step-card');
      if (css === EXPOSED_DECK_CSS) {
        expect(reinjected.boxSizing, 'control: reset must reach the card').toBe('border-box');
        expect(
          Math.abs(reinjected.width - ui.width),
          'control: re-injecting the universal reset must reintroduce the drift',
        ).toBeGreaterThan(1);
      } else {
        expect(
          reinjected.width,
          'control: a deck with its own universal rule is immune either way',
        ).toBe(ui.width);
      }
      // Holds on BOTH decks: neither declares a universal MARGIN rule of its own,
      // so re-universalising strips the UA margins the previews keep. This is the
      // control for the margin half, which `_universal_box_sizing_rules` — keyed on
      // `box-sizing` — would not catch on its own.
      expect(
        reinjected.h1MarginTop,
        'control: a universal reset must strip the h1 UA margin',
      ).toBe('0px');
      expect(
        reinjected.pMarginTop,
        'control: a universal reset must strip the p UA margin',
      ).toBe('0px');
    });
  }
});
