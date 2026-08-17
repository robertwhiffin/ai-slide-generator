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
 * How many frame-contract RULES in the live document match a given element,
 * split by ROLE: a `host` rule pins the fixed 1280x720 frame, a `child` rule
 * stretches a host's direct child to fill it.
 *
 * WHAT THIS CAN SEE: both roles landing on the SAME element — the real failure
 * mode of a mis-written host union, and invisible to computed style alone,
 * because `position: relative` and `position: absolute` both compute to
 * something plausible and only the resulting box gives it away.
 *
 * WHAT THIS CANNOT SEE: how many ARMS of one selector matched. `el.matches()`
 * is boolean per rule, and there is no API that reports which arms of a
 * selector list matched. That is not a gap in the probe but in the premise: a
 * selector list is ONE rule, so its declarations apply to an element exactly
 * once however many arms match, and nothing in the page can distinguish one
 * matching arm from two. Tests that care assert the observable consequence —
 * the resulting geometry — not an arm count.
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

// ------------------------------------------------- alternative host selectors
/**
 * Geometry + frame-contract ROLE of every interesting element, so a claim about
 * a host selector can be MEASURED instead of asserted.
 */
const PROBE = (selectors: string[]) => {
  const out: Record<string, { w: number; h: number; top: number; position: string;
    host: number; child: number }[]> = {};
  for (const sel of selectors) {
    out[sel] = [...document.querySelectorAll(sel)].map((el) => {
      const r = el.getBoundingClientRect();
      let host = 0;
      let child = 0;
      for (const sheet of [...document.styleSheets]) {
        let rules: CSSRuleList;
        try {
          rules = sheet.cssRules;
        } catch {
          continue;
        }
        for (const rule of [...rules]) {
          const sr = rule as CSSStyleRule;
          if (!sr.selectorText) continue;
          let hit = false;
          try {
            hit = el.matches(sr.selectorText);
          } catch {
            continue;
          }
          if (!hit) continue;
          if (sr.style.getPropertyValue('width') === '1280px'
            && sr.style.getPropertyValue('height') === '720px') host++;
          else if (sr.style.getPropertyValue('position') === 'absolute'
            && sr.style.getPropertyValue('height') === '100%') child++;
        }
      }
      return {
        w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top),
        position: getComputedStyle(el).position, host, child,
      };
    });
  }
  return out;
};

/**
 * The pop-out's preview shim, with the host selector as the VARIABLE. Mirrors
 * `PREVIEW_STAGE_SHIM` in templatePreviewDoc.ts; the shipped host selector is
 * imported rather than retyped, and a test below pins that the real pop-out
 * document still contains it, so this mirror cannot drift from the real one.
 */
const shimmedDoc = (hostSelector: string, bodyHtml: string) =>
  `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style><style>`
  + ':not(:defined){visibility:visible!important}'
  + 'body>:not(:defined){display:block!important}'
  + `${slideHostFrameStyle(hostSelector)}</style></head><body>${bodyHtml}</body></html>`;

async function probeHost(page: Page, hostSelector: string, bodyHtml: string,
  selectors: string[]) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(shimmedDoc(hostSelector, bodyHtml), { waitUntil: 'load' });
  return page.evaluate(PROBE, selectors);
}

// The custom-element host shape, as a bare body fragment for the probes above.
const STAGE_BODY = `<deck-stage width="1280" height="720">${bareSlide('a')}</deck-stage>`;

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

  // --------------------------------- why ONE :is() and not a comma-list union
  // The rationale in templatePreviewDoc.ts is asserted here against a real
  // browser rather than left as prose, because the mechanism is easy to get
  // wrong: the damage is done by the CHILD rule, not the host rule.
  test('a comma-separated host union stamps the HOST with the child rule', async ({ page }) => {
    // slideHostFrameStyle appends ` > :not(…)`, and a child combinator binds
    // only to the LAST arm of a selector list. So the FIRST arm degenerates
    // into a second rule matching the HOST, which stamps it with
    // position:absolute/inset:0/100% — the host abandons the fixed 720 frame
    // and resolves against the initial containing block (the viewport).
    const comma = await probeHost(page, 'body>:not(:defined),body>:has(.slide)',
      STAGE_BODY, ['deck-stage', 'section', '.slide']);

    expect(comma['deck-stage'][0].child,
      'the child rule lands on the HOST — this is what breaks').toBe(1);
    expect(comma['deck-stage'][0].position,
      'so the host is absolutely positioned, not the frame’s relative').toBe('absolute');
    // The wrong HEIGHT, at the viewport's 800 — NOT a collapse to 1280x0, which
    // is what no frame at all produces.
    expect(comma['deck-stage'][0], 'host takes the viewport box')
      .toMatchObject({ w: 1280, h: 800 });
    expect(comma['section'][0], 'the wrapper is stretched to that wrong box')
      .toMatchObject({ w: 1280, h: 800 });
    expect(comma['.slide'][0], 'and so is the slide').toMatchObject({ w: 1280, h: 800 });
    // The wrapper IS still stretched: `:has(.slide)` — the last arm — also
    // matches deck-stage, so the child rule does reach its children.
    expect(comma['section'][0].child, 'the wrapper is not left unstretched').toBe(1);

    // The shipped `:is()` form, same fixture, for contrast.
    const is = await probeHost(page, 'body>:is(:not(:defined),:has(.slide))',
      STAGE_BODY, ['deck-stage', 'section', '.slide']);
    expect(is['deck-stage'][0], 'the :is() host holds the fixed frame')
      .toMatchObject({ w: 1280, h: 720, position: 'relative', host: 1, child: 0 });
    expect(is['section'][0], ':is(): wrapper stretched to the frame')
      .toMatchObject({ w: 1280, h: 720 });
    expect(is['.slide'][0], ':is(): slide at the frame').toMatchObject({ w: 1280, h: 720 });
  });

  test('an unsupported arm degrades gracefully in :is(), fatally in a comma list', async ({ page }) => {
    // The other reason for `:is()`: it takes a FORGIVING selector list, so a
    // browser that does not know one arm drops just that arm. The same union
    // spelled with a comma is invalid as a whole and frames NOTHING.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent('<!DOCTYPE html><html><head><style>'
      + 'body>:is(:not(:defined),:totally-unknown(x)) { height: 720px }'
      + 'body>:not(:defined),body>:totally-unknown(x) { width: 640px }'
      + `</style></head><body>${STAGE_BODY}</body></html>`, { waitUntil: 'load' });

    const cs = await page.evaluate(() => {
      const s = getComputedStyle(document.querySelector('deck-stage')!);
      return { height: s.height, width: s.width };
    });
    expect(cs.height, ':is() keeps the arm it understands').toBe('720px');
    expect(cs.width, 'the comma list is invalidated entirely').toBe('auto');
  });

  test('a host matched by BOTH arms is still framed exactly once', async ({ page }) => {
    // The precondition is real: a <deck-stage> containing a slide satisfies the
    // custom-element arm AND the :has() arm. What does NOT follow is that the
    // block therefore applies twice — a selector list is one rule, so its
    // declarations apply once however many arms match, and no page API reports
    // an arm count (see COUNT_FRAME_RULES). This asserts the precondition, then
    // the observable consequence: the geometry is exactly the single frame.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(shimmedDoc('body>:is(:not(:defined),:has(.slide))', STAGE_BODY),
      { waitUntil: 'load' });

    const arms = await page.evaluate(() => {
      const el = document.querySelector('deck-stage')!;
      return {
        customElementArm: el.matches('body>:not(:defined)'),
        hasSlideArm: el.matches('body>:has(.slide)'),
      };
    });
    expect(arms, 'the host really is matched by both arms')
      .toEqual({ customElementArm: true, hasSlideArm: true });

    const m = await page.evaluate(PROBE, ['deck-stage', 'section', '.slide']);
    expect(m['deck-stage'][0], 'matched twice, framed once')
      .toMatchObject({ w: 1280, h: 720, position: 'relative', host: 1, child: 0 });
    expect(m['section'][0], 'and its wrapper stretched once')
      .toMatchObject({ w: 1280, h: 720, host: 0, child: 1 });
  });

  // ------------------------------------- deliberate breadth of the :has() arm
  test('the frame reaches a slide nested BELOW a direct child', async ({ page }) => {
    // `:has(.slide)` matches a body child containing a slide root at ANY depth.
    // That breadth is load-bearing: narrowing it to `:has(> .slide)` regresses
    // this shape to the 1280x800 defect (the direct-child form matches nothing
    // here, since `main`'s child is `article`).
    const deep = `<main><article>${bareSlide('deep')}</article></main>`;
    const sels = ['main', 'article', '.slide'];

    const broad = await probeHost(page, 'body>:is(:not(:defined),:has(.slide))', deep, sels);
    expect(broad['main'][0], 'the body child is framed').toMatchObject({ w: 1280, h: 720, host: 1 });
    expect(broad['article'][0], 'its direct child is stretched').toMatchObject({ w: 1280, h: 720, child: 1 });
    expect(broad['.slide'][0], 'so the slide resolves against a 720 box')
      .toMatchObject({ w: 1280, h: 720 });

    const tight = await probeHost(page, 'body>:is(:not(:defined),:has(>.slide))', deep, sels);
    expect(tight['main'][0], 'the direct-child form frames nothing here')
      .toMatchObject({ h: 0, host: 0 });
    expect(tight['.slide'][0], 'and the slide escapes to the viewport — the defect')
      .toMatchObject({ w: 1280, h: 800 });

    // Pin it against the SHIPPED selector too, not just the two written above,
    // so narrowing the real one fails here and not only in the comparison.
    const layout = `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head>`
      + `<body><main><article>${bareSlide('deep')}</article></main></body></html>`;
    const doc = await buildPopoutDoc(page, layout);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(doc, { waitUntil: 'load' });
    const real = await page.evaluate(PROBE, ['.slide']);
    expect(real['.slide'][0], 'the shipped selector frames a nested slide')
      .toMatchObject({ w: 1280, h: 720 });
  });

  test('several matching body children each get their own frame, IN FLOW', async ({ page }) => {
    // The cost of the breadth, pinned so it cannot silently worsen: with more
    // than one matching body child, each becomes its own 720px stage. They stay
    // `position: relative` and in normal flow, so a multi-slide layout preview
    // STACKS and scrolls (720 apart) instead of piling every slide at the
    // origin, which is what happened before the contract existed.
    const two = bareSlide('one') + bareSlide('two');
    const framed = await probeHost(page, 'body>:is(:not(:defined),:has(.slide))', two,
      ['section', '.slide']);

    expect(framed['section']).toHaveLength(2);
    expect(framed['section'][0]).toMatchObject({ w: 1280, h: 720, top: 0, position: 'relative' });
    expect(framed['section'][1], 'the second stage sits BELOW the first, not on top of it')
      .toMatchObject({ w: 1280, h: 720, top: 720, position: 'relative' });
    expect(framed['.slide'][0]).toMatchObject({ w: 1280, h: 720, top: 0 });
    expect(framed['.slide'][1]).toMatchObject({ w: 1280, h: 720, top: 720 });

    // Without the frame both wrappers collapse and both slides paint at the
    // SAME origin — the behaviour the stacking replaced.
    await page.setContent(
      `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head><body>${two}</body></html>`,
      { waitUntil: 'load' });
    const bare = await page.evaluate(PROBE, ['section', '.slide']);
    expect(bare['section'][0]).toMatchObject({ h: 0 });
    expect(bare['.slide'][0].top, 'unframed: both slides at the same origin').toBe(0);
    expect(bare['.slide'][1].top, 'unframed: both slides at the same origin').toBe(0);
  });

  test('the pop-out really injects the host selector measured by these tests', async ({ page }) => {
    // The probes above compose the shim themselves, so pin that the shipped
    // pop-out document carries the exact same host selector text. Without this
    // the mirror could drift and the measurements would describe nothing.
    const doc = await buildPopoutDoc(page, templateLayout([bareSlide('only')]));
    expect(doc, 'pop-out host selector').toContain('body>:is(:not(:defined),:has(.slide))');
  });

  // ------------------------------------------- known limits, recorded as-is
  // Both measured through the REAL pop-out builder. These pin CURRENT
  // behaviour, not desired behaviour: if either changes, the comment in
  // templatePreviewDoc.ts describing it must change with it.
  test('a slide root that IS the body child is not framed (pre-existing gap)', async ({ page }) => {
    // Matches neither arm: every built-in element counts as `:defined`, and a
    // slide root does not CONTAIN a slide root. The absolute slide therefore
    // resolves against the viewport. Unchanged by the host-union work.
    const layout = `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head>`
      + '<body><div class="slide"><p class="probe">x</p></div></body></html>';
    const doc = await buildPopoutDoc(page, layout);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(doc, { waitUntil: 'load' });
    const m = await page.evaluate(PROBE, ['.slide']);
    expect(m['.slide'][0], 'not framed: takes the viewport height, not the 720 frame')
      .toMatchObject({ w: 1280, h: 800, host: 0, child: 0 });
  });

  test('an export-shaped upload frames its .slide-wrapper but keeps it in flow', async ({ page }) => {
    // The CHILD arm excludes `.slide-wrapper`; the HOST arm can still match one
    // via `:has(.slide)`. Reaching that needs a document that contains
    // `.slide-wrapper` AND injects this selector — and
    // `buildStandaloneDeckDocument` never injects the frame at all, so the real
    // export is untouched (pinned by the standalone-export test below). It
    // means an export-shaped document uploaded as a TEMPLATE. Measured benign:
    // the wrappers keep `position: relative` and stay 720 apart, so the deck
    // does not pile into a single stack.
    const wrapped = (label: string) =>
      `<div class="slide-wrapper"><div class="slide-container">${bareSlide(label)}</div></div>`;
    const layout = `<!DOCTYPE html><html><head><style>${TEMPLATE_CSS}</style></head>`
      + `<body>${wrapped('one')}${wrapped('two')}</body></html>`;
    const doc = await buildPopoutDoc(page, layout);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.setContent(doc, { waitUntil: 'load' });
    const m = await page.evaluate(PROBE, ['.slide-wrapper', '.slide']);

    expect(m['.slide-wrapper']).toHaveLength(2);
    expect(m['.slide-wrapper'][0], 'the wrapper becomes a host')
      .toMatchObject({ w: 1280, h: 720, top: 0, position: 'relative', host: 1 });
    expect(m['.slide-wrapper'][1], 'and the second stays BELOW it, not stacked on it')
      .toMatchObject({ w: 1280, h: 720, top: 720, position: 'relative', host: 1 });
    expect(m['.slide'][0], 'each slide still measures the frame')
      .toMatchObject({ w: 1280, h: 720 });
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
