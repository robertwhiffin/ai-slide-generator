// The one pass the export runs on a slide before the snapshot reads it
// (render_slide.cjs): the slide root's ground moved onto body. It runs as a
// Playwright page.evaluate() source against the loaded slide document.
//
// Tellr decks paint the slide's ground on its root element (a .slide div, or
// the outermost <section> wrapper of a pinned design-system template), not on
// <body>, and the snapshot reads the slide background from body
// (snapshot.mjs slideBackground). So the root's ground is copied onto body
// here, and the root is marked so the snapshot does not paint it a second
// time as a slide-sized shape. Nothing else is touched: the snapshot reads the
// page as the browser laid it out, so a pass that rewrapped text, flattened
// tables or swapped elements for pictures would move the very layout it then
// reads.
//
// The tree, body included, is read through DOM_ACCESS_SOURCE (dom_access.mjs):
// slide script runs in this page first and can replace document.body, the
// lookups and the child accessors. A gradient ground is rasterized with
// GRADIENT_SOURCE (gradient.mjs).

import { DOM_ACCESS_SOURCE } from './dom_access.mjs';
import { GRADIENT_SOURCE } from './gradient.mjs';

// The attribute PREPROCESS_SOURCE puts on the slide root it resolved, so the
// snapshot can route that element's ground to the slide background alone.
export const SLIDE_ROOT_MARKER = 'data-tellr-slide-root';

// The slide-root locator and the background transfer.
const ROOT_AND_BACKGROUND_SRC = `
  // ─── Slide-root background → body background ──────────────────────
  // Tellr decks set the slide's background on its root div (e.g.
  // .slide-title { background: linear-gradient(...); }), not on <body>,
  // and the snapshot reads the slide background from body, so without this
  // a cover or CTA slide exports on body's default white and white-on-dark
  // text becomes invisible. Strategy: if the slide root has a gradient,
  // rasterize the gradient to a PNG data URL via canvas and set it as
  // body's background-image, which the slide background embeds as a
  // full-slide picture. Solid colors (or the gradient fallback if
  // rasterization fails) go to body's backgroundColor.
  // rasterizeGradientToDataURL is GRADIENT_SOURCE's (gradient.mjs), composed
  // ahead of this fragment.
  //
  // body itself is the document's real <body>, found through the pristine
  // lookup (queryOne): slide script can replace document.body with a decoy,
  // and a ground written to the decoy reaches no page the snapshot reads,
  // so the slide exports white.

  // ─── locate the slide root ─────────────────────────────────────────
  // The slide root is the outermost element standing for the whole slide.
  // Two shapes reach us:
  //
  //   * wrapperless (unpinned DS decks, no-DS decks) — body's direct child
  //     either carries the slide class or is a bare <div>. Both are resolved
  //     exactly as before, so those decks are untouched.
  //   * pinned template — the model emits the template's own structure, one
  //     or more semantic <section>/<article> levels around the div.slide
  //     body. Those wrappers carry no class and are not divs, so neither
  //     lookup below used to match and the transfer silently stopped. The
  //     OUTERMOST wrapper is the root: a pinned bundle's sole
  //     "section { ... }" rule is what paints the slide, and the .slide
  //     inside it often carries no ground of its own.
  //
  // Promotion has to agree with the backend's _promote_through_slide_wrapper()
  // (src/utils/html_utils.py), which walks outward through EVERY consecutive
  // sole-child semantic wrapper. The backend serialises the root it chose as
  // the slide's HTML, so whatever it promoted to is exactly what arrives here
  // as body's direct child. Stopping after a single level therefore left a
  // section > article > div.slide deck rootless here — exported white — while
  // the app rendered it correctly: the two surfaces disagreeing about one
  // deck, which is the whole class of bug this locator exists to prevent.
  //
  // The walk stays deliberately narrow, matching the count the backend takes
  // from find_all(recursive=False): each level must hold exactly one ELEMENT
  // child. So a wrapper holding several slides stays a container, and an
  // <h2>/<style>/<script>/SVG sibling stops the walk, while comments,
  // whitespace and text never block it. A <div> is never promoted at any
  // depth — it is neither a candidate wrapper nor a link in the chain — since
  // it would risk swallowing a deck-level container holding one slide.
  // Exactly one element is ever returned, so a wrapper and its inner .slide
  // can never both count as roots.
  const SLIDE_WRAPPER_TAGS = new Set(['SECTION', 'ARTICLE']);

  function findSlideRoot() {
    const direct = queryOne('body > [class*="slide"]');
    if (direct) return direct;
    const wrappers = queryAll('body > section, body > article');
    const walks = [];
    // Still gated on there being a chain to walk — not to avoid the capture, which
    // the snapshot above has already made, but because a null dom is how
    // reportNoSlideRoot is told no wrapper was ever read. A deck with no wrappers
    // therefore reports exactly the diagnostic it reported before.
    const dom = wrappers.length ? domAccess() : null;
    for (let index = 0; index < wrappers.length; index++) {
      const walk = walkToSlideBody(wrappers[index], dom);
      if (walk.matched) return wrappers[index];
      walks.push(walk);
    }
    const fallback = queryOne('body > div');
    if (!fallback) reportNoSlideRoot(walks, dom);
    return fallback;
  }

  // Why the no-root case is REPORTED and not merely returned. It is reachable on
  // input that is nobody's bug: past 509 wrapper levels Chromium's parser stops
  // nesting and reparents the overflow, so a 510-level chain arrives as an
  // innermost wrapper holding the remaining wrappers AND the .slide as SIBLINGS
  // (measured: 3 element children at 510, 13 at 520). The chain the backend
  // promoted through — BeautifulSoup has no such limit, so it serialises the
  // outermost wrapper as the slide's HTML — is simply not present in the DOM that
  // arrives here, and this locator correctly reports it cannot find a root.
  //
  // That is deliberately NOT chased. Matching it would mean promoting a wrapper
  // with several element children, which is exactly what the backend refuses
  // (find_all(recursive=False) length 1) and what TestPromotionBlockers pins as
  // must-block. So the reparsed shape is not resolvable without contradicting the
  // spec the sidecar exists to conform to; a 510-deep chain of sole-child
  // semantic wrappers is also a shape no real bundle produces (deepest observed
  // in a real bundle: two).
  //
  // What it must never do is fail SILENTLY, since a rootless deck and a broken
  // locator both export white. The line below is what tells those apart: it
  // names the shape the walk actually saw, so "the deck was pathological" is
  // distinguishable from "our locator regressed". render_slide.cjs routes
  // [preprocess] console lines to stderr, which is the stream
  // pptx_from_html_huashu.py echoes into the app log.
  function reportNoSlideRoot(walks, dom) {
    const access = dom || OWN_DOM_ACCESS;
    const bodyTags = [];
    // Bounded: in a hostile realm the sibling accessor is itself a loop risk.
    const body = queryOne('body');
    let sibling = body ? access.firstElementChild(body) : null;
    while (sibling && bodyTags.length < 8) {
      bodyTags.push(access.tagName(sibling));
      sibling = access.nextElementSibling(sibling);
    }
    const candidates = walks.map(
      (walk) => walk.stoppedAt + ' after ' + walk.steps + ' level(s): ' + walk.reason
    );
    console.warn(
      '[preprocess] no slide root: body children [' + bodyTags.join(', ') + ']' +
      '; wrapper candidates ' + (candidates.length ? candidates.join(' | ') : '(none)') +
      '; tree reads ' + (access.pristine ? 'pristine' : 'this-realm') +
      '. A chain over 509 levels deep is reparsed by Chromium into siblings and ' +
      'is not resolvable here by design.'
    );
  }

  // Whether this wrapper stands for a whole slide: following its sole-element-
  // child chain down through consecutive semantic wrappers lands on the slide
  // body. Only ELEMENT children are looked at, which is what makes comments,
  // whitespace and text nodes transparent to the walk — firstElementChild with a
  // null nextElementSibling is exactly the old children.length === 1 test, read
  // through accessors that can be taken from a clean realm.
  //
  // The descent carries NO PROMOTION cap, matching the backend's unbounded
  // _promote_through_slide_wrapper(): a number there is a silent wrong-output
  // boundary, because the backend promotes past it and serialises that root as
  // body's direct child, so the deck arrives here unrecognisable and exports
  // WHITE — the same surfaces-disagree defect this locator exists to prevent,
  // just relocated to the cap. What it does carry is WALK_STEP_LIMIT, which is a
  // different thing: not a belief about how deep decks go, but a guarantee that a
  // realm lying about the tree cannot make this loop run forever. It sits eight
  // times above the depth Chromium can even parse, so no legitimate chain reaches
  // it.
  //
  // Returns the walk as data rather than a boolean so the no-root diagnostic can
  // report where each candidate stopped without walking anything twice.
  function walkToSlideBody(wrapper, dom) {
    let node = wrapper;
    for (let steps = 0; steps < WALK_STEP_LIMIT; steps++) {
      const child = dom.firstElementChild(node);
      if (!child) {
        return { matched: false, steps, stoppedAt: dom.tagName(node), reason: 'no element children' };
      }
      if (dom.nextElementSibling(child)) {
        return { matched: false, steps, stoppedAt: dom.tagName(node), reason: 'several element children' };
      }
      if (dom.matches(child, '[class*="slide"]')) return { matched: true, steps: steps + 1 };
      if (!SLIDE_WRAPPER_TAGS.has(dom.tagName(child))) {
        return { matched: false, steps: steps + 1, stoppedAt: dom.tagName(child), reason: 'not a promotable wrapper' };
      }
      node = child;
    }
    return { matched: false, steps: WALK_STEP_LIMIT, stoppedAt: '(unread)', reason: 'iteration limit reached' };
  }

  // The root is passed in, located once by the caller, so a rootless deck reports
  // its no-root diagnostic exactly once.
  function transferSlideRootBackground(root) {
    if (!root) return 'no-root';
    const body = queryOne('body');
    const cs = window.getComputedStyle(root);
    const bgImage = cs.backgroundImage;
    if (bgImage && bgImage !== 'none' && /gradient/.test(bgImage)) {
      // Rasterize the gradient at slide dims so the export sees a real
      // image (preserving the 135° sweep). 1280×720 is our standard.
      const dataUrl = rasterizeGradientToDataURL(bgImage, 1280, 720);
      if (dataUrl) {
        body.style.backgroundImage = "url('" + dataUrl + "')";
        body.style.backgroundSize = '100% 100%';
        body.style.backgroundColor = 'transparent';
        return 'gradient-raster';
      }
      // Fallback: pick first stop color.
      const m = bgImage.match(/rgba?\\([^)]+\\)|#[0-9a-fA-F]{3,8}/);
      if (m) {
        body.style.backgroundColor = m[0];
        return 'gradient-firststop';
      }
    }
    const bg = cs.backgroundColor;
    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
      const bodyBg = window.getComputedStyle(body).backgroundColor;
      if (bg !== bodyBg) {
        body.style.backgroundColor = bg;
        return 'solid';
      }
    }
    return 'unchanged';
  }

  // The snapshot moves the slide root's ground to the slide background and
  // must not paint it again as a slide-sized shape over it, so it needs to
  // know which element this locator chose. The answer is a data-tellr-* marker
  // attribute, which no deck CSS targets and which moves no layout. Best effort:
  // a realm that refuses the write costs a repeated ground, never the export.
  function markSlideRoot(root) {
    if (!root) return;
    try {
      root.setAttribute('${SLIDE_ROOT_MARKER}', '');
    } catch (e) {
      console.warn('[preprocess] could not mark the slide root: ' + (e && e.message));
    }
  }
`;

// Evaluated into the slide's page by render_slide.cjs before the snapshot, and
// by probe_bg_transfer.mjs, which reports the branch it took. Returns
// { bgTransferred }: 'gradient-raster', 'gradient-firststop', 'solid' or
// 'unchanged' for a slide root, 'no-root' when the locator resolves none.
export const PREPROCESS_SOURCE = `
(function () {
  const DOM_ACCESS_LOG_PREFIX = '[preprocess]';
${DOM_ACCESS_SOURCE}
${GRADIENT_SOURCE}
${ROOT_AND_BACKGROUND_SRC}
  const root = findSlideRoot();
  markSlideRoot(root);
  const bgTransferred = transferSlideRootBackground(root);
  return { bgTransferred };
})();
`;
