'use strict';
// Element-isolated captures (spec §4): what the slide cannot draw natively is a
// picture of exactly what the browser painted for it, taken from the original,
// untouched page.
//
//   captureAll(page, captures) -> Map<captureId, 'data:image/png;base64,…'>
//
// `captures` is model.captures (snapshot.mjs): {id, x,y,w,h, mode, selector,
// hiddenWithin, paint}. The snapshot has already named each target with
// data-tellr-capture="<id>". For each capture, in id order and one at a time:
//   1. an isolation stylesheet hides every element but the target: its whole
//      subtree in 'subtree' mode (svg, canvas, video, img), its own box alone
//      in 'box' mode, with its text transparent so the text and the children
//      stay native and editable. Visibility changes no layout, and every
//      ancestor keeps its overflow clip and opacity, so the picture is cut and
//      faded as the slide shows it;
//   2. the target's rect is screenshotted at the page's device scale (2) on a
//      transparent ground;
//   3. the stylesheet is removed.
// A capture that fails is logged and has no entry in the map: its picture is
// skipped (emit_model.cjs) and counted in the slide summary. The slide stays.
//
// The stylesheet goes in through the screenshot's own `style` option, not
// page.addStyleTag. Playwright applies that option from its utility world, an
// isolated JS world no slide script runs in, and removes it after the shot
// whether or not the shot succeeds. addStyleTag runs in the page's main world
// and awaits the style element's onload, so two lines of slide script (an
// HTMLElement.prototype.onload setter that does nothing) leave it pending
// forever: an uploaded template could deny itself an export.
//
// `animations: 'disabled'` fast-forwards every transition and animation before
// the shot, including those the isolation stylesheet itself starts: under a
// deck rule like `* { transition: all 1s }`, hiding the page is a visibility
// transition that keeps it visible for a second, and the whole page would be
// in the picture. The settle (render_slide.cjs) has already finished the
// slide's own animations, so this changes nothing else.

// The attribute the snapshot names a target with, and the one it puts on
// each descendant of a subtree target that the slide does not show.
const CAPTURE_ATTRIBUTE = 'data-tellr-capture';
const HIDDEN_ATTRIBUTE = 'data-tellr-capture-hidden';

// One capture normally takes tens of milliseconds. The screenshot waits for
// document.fonts.ready first; a font that never settles must cost one bounded
// wait per slide, not one per capture: after a capture times out, the slide's
// remaining captures are not attempted.
const CAPTURE_TIMEOUT_MS = 5000;

// A computed value the snapshot read (a colour, a shadow list) is only ever
// these characters ("/" separates an oklch() or color() alpha). Anything else
// (a realm lying about getComputedStyle) is not written into the stylesheet:
// none of these can end a declaration or a rule.
const COMPUTED_VALUE = /^[a-z0-9\s(),.%#+/-]*$/i;

// Each :not(#…) adds id-level specificity, so these rules beat the deck's own
// !important rules on classes and elements (Review Focus 5); the trick of
// SLIDE_ROOT_RESET_STYLE's #tellr-root-reset-boost. `*` never matches a
// ::before or ::after, and a pseudo-element's own visibility beats the one it
// would inherit from its hidden element, so every other element's
// pseudo-elements are hidden by a rule of their own. The target's (and, in
// subtree mode, those of what it holds) are left to inherit the visibility the
// isolation gives their element, or to keep their own declaration, so a
// pseudo-element the slide hides stays hidden in the picture.
function isolationCss(id, mode) {
  const target = `[data-tellr-capture="${id}"]`;
  const boost = ':not(#tellr-capture-a):not(#tellr-capture-b):not(#tellr-capture-c)';
  const others = mode === 'subtree' ? `*${boost}:not(${target}):not(${target} *)` : `*${boost}:not(${target})`;
  return `html${boost}, body${boost} { background: transparent !important; }\n` +
    `*${boost} { visibility: hidden !important; }\n` +
    `${others}::before, ${others}::after { visibility: hidden !important; }\n` +
    (mode === 'subtree'
      ? `${target}${boost}, ${target} *${boost} { visibility: visible !important; }`
      : `${target}${boost} { visibility: visible !important; color: transparent !important;` +
        ` -webkit-text-fill-color: transparent !important; text-shadow: none !important; }`);
}

// What the isolation must not change about the target's own painting.
// * Subtree mode shows every descendant, so a descendant the slide hides
//   (an SVG group with visibility="hidden") is hidden again, one attribute
//   selector more specific than the rule that shows it; its pseudo-elements
//   inherit that, as they do on the slide.
// * Box mode makes the target's text transparent by setting `color`, which a
//   border or shadow drawn in currentColor follows; each is pinned to the
//   colour the slide paints it in.
function retainedCss(capture) {
  const target = `[${CAPTURE_ATTRIBUTE}="${capture.id}"]`;
  const boost = ':not(#tellr-capture-a):not(#tellr-capture-b):not(#tellr-capture-c)';
  const rules = [];
  if (capture.mode === 'subtree' && capture.hiddenWithin) {
    rules.push(`${target} [${HIDDEN_ATTRIBUTE}]${boost} { visibility: hidden !important; }`);
  }
  const paint = capture.mode === 'box' && capture.paint ? capture.paint : null;
  if (paint) {
    const declarations = [];
    const sides = ['top', 'right', 'bottom', 'left'];
    const colours = Array.isArray(paint.borderColors) ? paint.borderColors : [];
    for (let index = 0; index < sides.length; index++) {
      const colour = colours[index];
      if (typeof colour === 'string' && colour && COMPUTED_VALUE.test(colour)) {
        declarations.push(`border-${sides[index]}-color: ${colour} !important;`);
      }
    }
    if (typeof paint.boxShadow === 'string' && paint.boxShadow && COMPUTED_VALUE.test(paint.boxShadow)) {
      declarations.push(`box-shadow: ${paint.boxShadow} !important;`);
    }
    if (declarations.length) rules.push(`${target}${boost} { ${declarations.join(' ')} }`);
  }
  return rules.join('\n');
}

function captureNumber(capture) {
  return Number(String(capture.id).slice(1));
}

// The clip a capture's PNG is taken from. Playwright floors a page clip's
// width and height to whole CSS px (helper.enclosingIntSize), first cutting
// the clip to the viewport (trimClipToSize), and Chrome snaps its origin to a
// device pixel: a PNG covers a whole number of CSS px from about its corner.
// So the clip's size is the rect's, rounded to whole px, and where that would
// pass the viewport's right or bottom edge (a rect the slide's edge cuts) its
// origin moves in by the difference, at most half a pixel. The PNG then
// covers the picture's rect to within half a pixel at each edge, and is twice
// it to within one device pixel; the picture keeps the exact rect, so the
// PNG is stretched or squeezed by at most half a pixel.
function clipOf(capture, viewport) {
  const width = Math.min(Math.max(1, Math.round(capture.w)), viewport.width);
  const height = Math.min(Math.max(1, Math.round(capture.h)), viewport.height);
  return {
    x: Math.max(0, Math.min(capture.x, viewport.width - width)),
    y: Math.max(0, Math.min(capture.y, viewport.height - height)),
    width,
    height,
  };
}

async function captureOne(page, capture, viewport) {
  const retained = retainedCss(capture);
  const png = await page.screenshot({
    clip: clipOf(capture, viewport),
    omitBackground: true,
    type: 'png',
    scale: 'device',
    animations: 'disabled',
    style: isolationCss(capture.id, capture.mode) + (retained ? '\n' + retained : ''),
    timeout: CAPTURE_TIMEOUT_MS,
  });
  return 'data:image/png;base64,' + png.toString('base64');
}

// Sequential and in capture-id order (DOM pre-order), so the same page gives
// the same pictures in the same order every time.
async function captureAll(page, captures) {
  const pictures = new Map();
  const ordered = (captures || []).slice().sort((a, b) => captureNumber(a) - captureNumber(b));
  // A page with no fixed viewport has no edge a clip must stay inside.
  const viewport = page.viewportSize() || { width: Infinity, height: Infinity };
  let timedOut = false;
  for (let index = 0; index < ordered.length; index++) {
    const capture = ordered[index];
    // The snapshot could not name its target, and has said so.
    if (capture.failed) continue;
    if (timedOut) {
      console.error(`[html2pptx] capture failed: ${capture.id} not attempted: an earlier capture of this slide timed out`);
      continue;
    }
    try {
      pictures.set(capture.id, await captureOne(page, capture, viewport));
    } catch (error) {
      if (error && error.name === 'TimeoutError') timedOut = true;
      const message = String((error && error.message) || error).split('\n')[0];
      console.error(`[html2pptx] capture failed: ${capture.id} ${message}`);
    }
  }
  return pictures;
}

module.exports = { captureAll, isolationCss, CAPTURE_ATTRIBUTE, HIDDEN_ATTRIBUTE };
