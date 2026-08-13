import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import {
  buildSlideDocument,
  slideHostFrameStyle,
  SLIDE_PREVIEW_RESET_STYLE,
  SLIDE_ROOT_RESET_STYLE,
} from '../../src/services/slideDocument';

/**
 * Slide-host frame contract: a slide root that paints no background of its own
 * must still show the DECK's background, not the page behind it.
 *
 * THE MECHANISM (measured against real uploaded design-system bytes). Templates
 * nest the slide two levels deep:
 *
 *   <deck-stage width="1280" height="720">
 *     <section>              <- carries the deck background, via a bare `section`
 *                               TYPE selector, so no class can be "lost"
 *       <div class="slide">  <- position:absolute; inset:0
 *
 * `section` and `.slide` are DIFFERENT elements. `.slide` is out of flow, so the
 * section has no in-flow content and collapses to height:0. The collapsed
 * element is the one carrying the background, so the deck background never
 * paints and the deck's own dark `html,body` background shows through instead.
 * `color` and `font-family` DO apply (they inherit), which is why the symptom is
 * READABLE dark-on-dark rather than a blank slide. The absolute `.slide` also
 * escapes the static section and resolves against the viewport, so an affected
 * surface renders the slide at the wrong height too (measured 1280x800, not
 * 1280x720) — wrong vertical rhythm, not only wrong colour.
 *
 * ROOT SIZING DOES NOT FIX IT: sizing/positioning the ROOT leaves the section a
 * static-flow child that still collapses. The load-bearing rule is CHILD
 * STRETCH — the host's child must be stretched to the frame. Presentation mode
 * was the only surface that already declared one, which is the only reason it
 * escaped the defect; {@link slideHostFrameStyle} promotes that rule into one
 * shared mechanism every surface uses.
 *
 * These tests therefore assert on NON-ZERO SECTION HEIGHT as well as on painted
 * contrast: colour alone would go green for the wrong reason (e.g. if something
 * repainted the page background light while the section stayed collapsed).
 *
 * All fixtures synthetic; the greys below are generic, not brand values.
 *
 * Run: cd frontend && npx playwright test tests/e2e/slide-host-frame.spec.ts
 */

const PAGE_BG = '#101010';   // the deck's own dark page background
const STAGE_BG = '#f0f0f0';  // the background the <section> carries
const INK = '#303030';       // inherited text colour

// Reproduces the real template cascade: the background lives on a bare `section`
// TYPE selector with NO geometry of its own, and `.slide` is absolutely
// positioned. `.own-bg` stands in for the immune archetypes (.dark/.white/.event)
// that paint their own background and were never affected.
const TEMPLATE_CSS = `
  html, body { margin: 0; background: ${PAGE_BG}; }
  section { background: ${STAGE_BG}; color: ${INK}; overflow: hidden; }
  .slide { position: absolute; inset: 0; padding: 72px 88px; display: flex; flex-direction: column; }
  .slide.own-bg { background: #ffffff; }
  .slide.compact { width: 640px !important; height: 360px !important; }
`;

const bareSlide = (label: string) =>
  `<section data-label="${label}"><div class="slide"><p class="probe">Body copy ${label}</p></div></section>`;
const immuneSlide = (label: string) =>
  `<section data-label="${label}"><div class="slide own-bg"><p class="probe">Body copy ${label}</p></div></section>`;
// A slide root with NO wrapper — the legacy no-design-system shape, where the
// slide root itself is the host's direct child — that declares a size SMALLER
// than the frame, with `!important`. The opt-out probe.
const compactRoot = (label: string) =>
  `<div class="slide compact" data-label="${label}"><p class="probe">Body copy ${label}</p></div>`;

/** A multi-slide template document, the shape an uploaded template really has. */
const templateLayout = (slides: string[]) =>
  `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head>` +
  `<body><deck-stage width="1280" height="720">${slides.join('')}</deck-stage></body></html>`;

/**
 * The same template one level shallower: the background-carrying wrapper sits
 * DIRECTLY under <body>, with no custom-element harness around it. This is a
 * supported upload shape — `template-cards.spec.ts` serves exactly
 * `<body><section><div class="slide">…</div></section></body>` — and a
 * `:not(:defined)` host selector cannot reach it, because `:not(:defined)`
 * matches only unregistered CUSTOM elements while every built-in counts as
 * defined. The pop-out must therefore recognise the wrapper structurally.
 */
const plainLayout = (slides: string[]) =>
  `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head>` +
  `<body>${slides.join('')}</body></html>`;

// --------------------------------------------------------------- measurement
/**
 * Geometry of the slide root and its background-carrying wrapper, plus the
 * contrast of the probe text against the background actually painted behind it.
 *
 * The backdrop is resolved by walking up from the probe to the nearest ancestor
 * with a non-transparent background, compositing any alpha on the way — so a
 * collapsed (zero-area) wrapper cannot be mistaken for one that paints.
 */
const MEASURE = () => {
  const slide = document.querySelector('.slide');
  if (!slide) return null;
  const section = slide.closest('section');
  const probe = slide.querySelector('.probe') as HTMLElement | null;

  const parse = (c: string): [number, number, number, number] => {
    const n = (c.match(/[\d.]+/g) ?? []).map(Number);
    return [n[0] ?? 0, n[1] ?? 0, n[2] ?? 0, n.length > 3 ? n[3] : 1];
  };
  const over = (fg: number[], bg: number[]) =>
    [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));

  // Painted backdrop behind the probe: nearest ancestor that actually paints,
  // and only if it has area. A zero-height section paints nothing.
  let backdrop = [255, 255, 255];
  const layers: number[][] = [];
  for (let el: Element | null = probe; el; el = el.parentElement) {
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const col = parse(cs.backgroundColor);
    if (col[3] > 0 && rect.width > 0 && rect.height > 0) layers.push(col);
  }
  // html/body are the last painters; composite from the bottom up.
  backdrop = layers.reverse().reduce((acc, l) => over(l, acc), [255, 255, 255]);

  const fgRaw = probe ? parse(getComputedStyle(probe).color) : [0, 0, 0, 1];
  const fg = over(fgRaw, backdrop);

  const srgb = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const lum = (c: number[]) => 0.2126 * srgb(c[0]) + 0.7152 * srgb(c[1]) + 0.0722 * srgb(c[2]);
  const [hi, lo] = [lum(fg), lum(backdrop)].sort((a, b) => b - a);

  const box = (el: Element | null) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  return {
    section: box(section),
    slide: box(slide),
    contrast: Number(((hi + 0.05) / (lo + 0.05)).toFixed(3)),
    backdrop: `rgb(${backdrop.map(Math.round).join(', ')})`,
  };
};

async function measure(page: Page, doc: string) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(doc, { waitUntil: 'load' });
  const result = await page.evaluate(MEASURE);
  expect(result, 'fixture should render a .slide').not.toBeNull();
  return result!;
}

/**
 * How many frame-contract rules in the live document match a given element,
 * split by ROLE: a `host` rule pins the fixed 1280x720 frame, a `child` rule
 * stretches a host's direct child to fill it.
 *
 * The frame must be declared ONCE per element and the two roles must never land
 * on the SAME element. A host selector written as a comma list whose arms both
 * match would apply one role twice; a host selector that reaches a nested
 * wrapper would apply BOTH roles to it, stacking `position: relative` against
 * `position: absolute` with equal importance and letting specificity decide the
 * geometry. Counting matched rules catches both, where computed style cannot:
 * duplicate identical declarations compute the same as one.
 */
const COUNT_FRAME_RULES = (selector: string) => {
  const el = document.querySelector(selector);
  if (!el) return null;
  let host = 0;
  let child = 0;
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // cross-origin sheet; none in these fixtures
    }
    for (const rule of Array.from(rules)) {
      const styleRule = rule as CSSStyleRule;
      if (!styleRule.selectorText) continue;
      let hit = false;
      try {
        hit = el.matches(styleRule.selectorText);
      } catch {
        continue; // a selector this browser cannot parse cannot be applying
      }
      if (!hit) continue;
      const style = styleRule.style;
      if (
        style.getPropertyValue('width') === '1280px' &&
        style.getPropertyValue('height') === '720px'
      ) {
        host++;
      } else if (
        style.getPropertyValue('position') === 'absolute' &&
        style.getPropertyValue('height') === '100%'
      ) {
        child++;
      }
    }
  }
  return { host, child, position: getComputedStyle(el).position };
};

async function frameRoles(page: Page, doc: string, selector: string) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(doc, { waitUntil: 'load' });
  const result = await page.evaluate(COUNT_FRAME_RULES, selector);
  expect(result, `fixture should contain ${selector}`).not.toBeNull();
  return result!;
}

// ------------------------------------------------------- surface documents
// Each mirrors the real call site, so the spec fails if a surface stops using
// the shared contract.
const surfaces = {
  // SlideTile.tsx / VisualEditorPanel.tsx
  SlideTile: (slideHtml: string) =>
    buildSlideDocument(slideHtml, {
      css: TEMPLATE_CSS,
      extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE,
    }),
  // SlideSelection.tsx
  SlideSelection: (slideHtml: string) =>
    buildSlideDocument(slideHtml, {
      css: TEMPLATE_CSS,
      extraHeadStyle: `* { box-sizing: border-box; }
        body { margin: 0; }
        ${SLIDE_ROOT_RESET_STYLE}
        ${slideHostFrameStyle('body')}`,
    }),
  // PresentationMode.tsx — wraps the slide in .slide-container
  PresentationMode: (slideHtml: string) =>
    buildSlideDocument(`<div class="slide-container">${slideHtml}</div>`, {
      css: TEMPLATE_CSS,
      extraHeadStyle: `* { box-sizing: border-box; }
        html, body { width: 100%; height: 100%; overflow: hidden; }
        body { display: flex !important; justify-content: center !important;
               align-items: flex-start !important; padding: 0 !important; margin: 0 !important; }
        .slide-container { flex-shrink: 0; flex-grow: 0; margin: 0; }
        ${SLIDE_ROOT_RESET_STYLE}
        ${slideHostFrameStyle('.slide-container')}`,
    }),
} as const;

const SURFACE_NAMES = Object.keys(surfaces) as (keyof typeof surfaces)[];

// ---------------------------------------------------- pop-out document builder
// The pop-out builder parses the layout with DOMParser, so it only runs in a
// real DOM. It is bundled from its absolute path (never fetched through the dev
// server, which `reuseExistingServer` can point at a different worktree) and
// executed IN the page, so the test exercises the shipped module rather than a
// reimplementation of it.
const SPEC_DIR = fileURLToPath(new URL('.', import.meta.url));
let popoutBundle = '';

test.beforeAll(async () => {
  const result = await build({
    entryPoints: [SPEC_DIR + '../../src/components/config/templatePreviewDoc.ts'],
    bundle: true,
    format: 'iife',
    globalName: 'TemplatePreviewDoc',
    write: false,
    logLevel: 'silent',
  });
  popoutBundle = result.outputFiles[0].text;
});

async function buildPopoutDoc(page: Page, layout: string, slideIndex?: number) {
  await page.goto('about:blank');
  await page.addScriptTag({ content: popoutBundle });
  return page.evaluate(
    ([l, i]) =>
      (window as unknown as {
        TemplatePreviewDoc: {
          buildTemplatePreviewDoc: (h: string, t: string | null, i?: number) => string;
        };
      }).TemplatePreviewDoc.buildTemplatePreviewDoc(l as string, null, i as number),
    [layout, slideIndex] as [string, number | undefined]);
}

test.describe('slide-host frame contract', () => {
  for (const name of SURFACE_NAMES) {
    test(`${name}: a bare slide root paints the deck background at full frame height`, async ({ page }) => {
      const m = await measure(page, surfaces[name](bareSlide('bare')));

      // The defect: the background-carrying wrapper collapses to height 0.
      expect(m.section, `${name}: section must fill the frame, not collapse`)
        .toEqual({ w: 1280, h: 720 });
      // And the out-of-flow slide must not escape to the viewport height.
      expect(m.slide, `${name}: slide must be the 720px frame, not the viewport`)
        .toEqual({ w: 1280, h: 720 });
      // The user-visible symptom.
      expect(m.contrast, `${name}: painted contrast (backdrop ${m.backdrop})`)
        .toBeGreaterThanOrEqual(4.5);
    });

    test(`${name}: a slide root with its own background is unaffected`, async ({ page }) => {
      const m = await measure(page, surfaces[name](immuneSlide('immune')));
      expect(m.contrast, `${name}: immune slide must stay readable`)
        .toBeGreaterThanOrEqual(4.5);
      expect(m.section, `${name}: immune slide frame`).toEqual({ w: 1280, h: 720 });
    });
  }

  // ------------------------------------------------------ template pop-out
  // The user-reported surface. It has its OWN document builder and never used
  // the shared reset, so a fix confined to the shared reset would not reach it.
  test('template pop-out: a bare slide root paints the deck background at full frame height', async ({ page }) => {
    const layout = templateLayout([
      immuneSlide('cover'), bareSlide('target'), immuneSlide('closing'),
    ]);
    const m = await measure(page, await buildPopoutDoc(page, layout, 1));

    expect(m.section, 'pop-out: section must fill the frame, not collapse')
      .toEqual({ w: 1280, h: 720 });
    expect(m.contrast, `pop-out: painted contrast (backdrop ${m.backdrop})`)
      .toBeGreaterThanOrEqual(4.5);
  });

  test('template pop-out: isolating a slide shows THAT slide, not an emptied wrapper', async ({ page }) => {
    // Isolating one slide removes the other .slide elements but historically
    // left their <section> wrappers behind. Those wrappers carry the deck
    // background, so once the host stretch contract gives them the full frame
    // an emptied wrapper AFTER the surviving slide would paint over it — the
    // slide would vanish behind a blank stage. The wrappers must go with it.
    const layout = templateLayout([
      bareSlide('first'), bareSlide('target'), bareSlide('trailing'),
    ]);
    const doc = await buildPopoutDoc(page, layout, 1);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(doc, { waitUntil: 'load' });

    const visible = await page.evaluate(() => {
      const el = document.elementFromPoint(640, 360);
      const slide = el?.closest('.slide') ?? null;
      return {
        sections: document.querySelectorAll('section').length,
        emptySections: [...document.querySelectorAll('section')]
          .filter((s) => !s.querySelector('.slide')).length,
        labelAtCentre: slide?.closest('section')?.getAttribute('data-label') ?? null,
      };
    });

    expect(visible.emptySections, 'no background-carrying wrapper may be left empty').toBe(0);
    expect(visible.sections, 'only the isolated slide’s wrapper survives').toBe(1);
    expect(visible.labelAtCentre, 'the isolated slide is what the frame shows').toBe('target');
  });

  // ------------------------------- pop-out: a plain wrapper under <body>
  // The gap the `:not(:defined)` host selector cannot cover. Everything about
  // the defect is identical — a background-carrying wrapper collapsed by an
  // out-of-flow slide — only the un-upgradable custom element is missing.
  test('template pop-out: a wrapper directly under body, with no deck-stage, paints the deck background at full frame height', async ({ page }) => {
    const layout = plainLayout([
      immuneSlide('cover'), bareSlide('target'), immuneSlide('closing'),
    ]);
    const m = await measure(page, await buildPopoutDoc(page, layout, 1));

    expect(m.section, 'plain wrapper: section must fill the frame, not collapse')
      .toEqual({ w: 1280, h: 720 });
    expect(m.slide, 'plain wrapper: slide must be the 720px frame, not the viewport')
      .toEqual({ w: 1280, h: 720 });
    expect(m.contrast, `plain wrapper: painted contrast (backdrop ${m.backdrop})`)
      .toBeGreaterThanOrEqual(4.5);
  });

  test('template pop-out: isolating a slide in a plain wrapper leaves no emptied background wrapper', async ({ page }) => {
    // Same hazard as the deck-stage shape: an emptied `section` still matches
    // the bare `section` background rule, and under the frame contract a later
    // empty sibling would paint over the slide that survives.
    const doc = await buildPopoutDoc(
      page,
      plainLayout([bareSlide('first'), bareSlide('target'), bareSlide('trailing')]),
      1,
    );
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(doc, { waitUntil: 'load' });

    const visible = await page.evaluate(() => {
      const el = document.elementFromPoint(640, 360);
      const slide = el?.closest('.slide') ?? null;
      return {
        sections: document.querySelectorAll('section').length,
        emptySections: [...document.querySelectorAll('section')]
          .filter((s) => !s.querySelector('.slide')).length,
        labelAtCentre: slide?.closest('section')?.getAttribute('data-label') ?? null,
      };
    });

    expect(visible.emptySections, 'no background-carrying wrapper may be left empty').toBe(0);
    expect(visible.sections, 'only the isolated slide’s wrapper survives').toBe(1);
    expect(visible.labelAtCentre, 'the isolated slide is what the frame shows').toBe('target');
  });

  test('template pop-out: the frame is declared once, on the wrapper, in BOTH template shapes', async ({ page }) => {
    // One host, one child, never both roles on one element — see
    // COUNT_FRAME_RULES. This is what keeps a selector that covers both shapes
    // from double-applying to the shape that already worked.
    const withStage = await buildPopoutDoc(page, templateLayout([bareSlide('only')]));
    const stageHost = await frameRoles(page, withStage, 'deck-stage');
    expect(stageHost.host, 'deck-stage is framed exactly once').toBe(1);
    expect(stageHost.child, 'deck-stage is a host, never also a stretched child').toBe(0);

    const stageWrapper = await frameRoles(page, withStage, 'section');
    expect(stageWrapper.child, 'the section inside deck-stage is stretched exactly once').toBe(1);
    expect(stageWrapper.host, 'the nested section must NOT become a second frame').toBe(0);

    const plain = await buildPopoutDoc(page, plainLayout([bareSlide('only')]));
    const plainWrapper = await frameRoles(page, plain, 'section');
    expect(plainWrapper.host, 'a wrapper directly under body is framed exactly once').toBe(1);
    expect(plainWrapper.child, 'that wrapper is the host, so it is not also stretched').toBe(0);

    const plainSlide = await frameRoles(page, plain, '.slide');
    expect(plainSlide.child, 'the slide inside it is stretched exactly once').toBe(1);
  });

  // ------------------------------------------- deliberate: no size opt-out
  test('an authored slide root smaller than the frame is still stretched to it', async ({ page }) => {
    // DELIBERATE, not incidental. The product canvas is a FIXED 1280x720 16:9
    // frame, so honouring a smaller authored root would leave the page
    // background painting around it — the very defect this contract fixes.
    // It is also what the platform itself does: every shipped `deck-stage.js`
    // stretches its slotted child with a byte-identical
    // `position/inset/width/height/box-sizing` `!important` block from inside
    // its shadow root, where important declarations in the inner tree beat
    // author important declarations in the outer one — so a bundle cannot opt
    // out of the stretch in a real deck-stage either. Honouring an opt-out here
    // would make the preview disagree with the shipped renderer.
    const m = await measure(page, surfaces.SlideTile(compactRoot('compact')));
    expect(m.slide, 'a 640x360 !important authored root is still framed at 1280x720')
      .toEqual({ w: 1280, h: 720 });
  });

  // ------------------------------------------------------------ drift guard
  test('every slide surface builds its document from the shared frame contract', async () => {
    // The documents above are mirrors of the real call sites. That mirroring is
    // only meaningful if the real surfaces still use the shared contract, so
    // pin it at the source: one mechanism, no per-surface reimplementation.
    const here = fileURLToPath(new URL('.', import.meta.url));
    const surfaceSources = {
      'SlideTile / VisualEditorPanel (via SLIDE_PREVIEW_RESET_STYLE)':
        '../../src/services/slideDocument.ts',
      SlideSelection: '../../src/components/SlidePanel/SlideSelection.tsx',
      PresentationMode: '../../src/components/PresentationMode/PresentationMode.tsx',
      'template pop-out': '../../src/components/config/templatePreviewDoc.ts',
    };
    for (const [surface, relPath] of Object.entries(surfaceSources)) {
      const src = readFileSync(here + relPath, 'utf8');
      expect(src, `${surface} must build its frame from slideHostFrameStyle`)
        .toContain('slideHostFrameStyle(');
    }
  });

  // ------------------------------------------------- trap: standalone export
  test('the multi-slide standalone export document is not stretched into a stack', async ({ page }) => {
    // The shared root reset also matches `.slide-wrapper`, the per-slide block
    // of the standalone multi-slide HTML export. Stretching THOSE to the frame
    // would stack every slide of the export on top of one another. The frame
    // contract must be unable to do that, whatever surface injects it.
    const { buildStandaloneDeckDocument } = await import('../../src/services/slideDocument');
    const deck = {
      title: 'Stack probe',
      css: TEMPLATE_CSS,
      scripts: '',
      external_scripts: [],
      slides: [
        { slide_id: 'a', html: bareSlide('one'), scripts: '' },
        { slide_id: 'b', html: bareSlide('two'), scripts: '' },
      ],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(buildStandaloneDeckDocument(deck), { waitUntil: 'load' });

    const wrappers = await page.evaluate(() =>
      [...document.querySelectorAll('.slide-wrapper')].map((w) => {
        const r = w.getBoundingClientRect();
        return { top: Math.round(r.top), position: getComputedStyle(w).position };
      }));

    expect(wrappers).toHaveLength(2);
    expect(wrappers[0].position, 'standalone wrappers stay in flow').toBe('static');
    expect(wrappers[1].position, 'standalone wrappers stay in flow').toBe('static');
    expect(wrappers[1].top, 'the second slide sits BELOW the first, not on top of it')
      .toBeGreaterThan(wrappers[0].top);
  });
});
