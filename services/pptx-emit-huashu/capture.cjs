'use strict';
// Element-isolated captures (spec §4): what the slide cannot draw natively is a
// picture of exactly what the browser painted for it, taken from the original,
// untouched page.
//
//   captureAll(page, captures) -> Map<captureId, 'data:image/png;base64,…'>
//
// `captures` is model.captures (snapshot.mjs): {id, x,y,w,h, mode, selector,
// pseudo, hiddenWithin, paint, bordersHidden}. The snapshot has already named each target
// with data-tellr-capture="<id>"; a pseudo-element target is named by its
// host's data-tellr-pseudo-host attribute, which pseudo.mjs set. For each
// capture, in id order and one at a time:
//   1. an isolation stylesheet hides every element but the target: its whole
//      subtree in 'subtree' mode (svg, canvas, video, img), its own box alone
//      in 'box' mode, with its text transparent so the text and the children
//      stay native and editable. A box target's own ::before, ::after and
//      list marker are drawn natively too (ruling R8b), so they are hidden
//      with the rest. A pseudo-element target is a box target of its own: its
//      host is hidden like everything else, and of every pseudo-element only
//      the target shows, its text transparent. A ::marker takes no visibility
//      of its own, only its item's, so a marker target's item is shown
//      instead, painting nothing of its own: its box, its text and its
//      children hidden or transparent, and the marker's text transparent, so
//      only the image the marker paints is left. Visibility changes no
//      layout, and every ancestor keeps its overflow clip and opacity, so the
//      picture is cut and faded as the slide shows it;
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

const { oneLine } = require('./log_line.cjs');

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

// The only targets the snapshot names, and the pseudo-elements it captures.
// Anything else is no capture of ours and is not written into a stylesheet.
const TARGET_SELECTOR = /^\[data-tellr-(?:capture|pseudo-host)="[a-z0-9]{1,16}"\]$/;
const PSEUDO_ELEMENTS = new Set(['before', 'after', 'marker']);

// Each :not(#…) adds id-level specificity, so these rules beat the deck's own
// !important rules on classes and elements (Review Focus 5); the trick of
// SLIDE_ROOT_RESET_STYLE's #tellr-root-reset-boost.
const BOOST = ':not(#tellr-capture-a):not(#tellr-capture-b):not(#tellr-capture-c)';

// {selector, pseudo}: the target element's selector (a pseudo-element's host)
// and the pseudo-element captured, or null. Throws for anything else.
function targetOf(capture) {
  const selector = String(capture.selector || '');
  if (!TARGET_SELECTOR.test(selector)) throw new Error(`the capture target ${selector.slice(0, 80)} is not one the snapshot names`);
  const pseudo = capture.pseudo === null || capture.pseudo === undefined ? null : String(capture.pseudo);
  if (pseudo !== null && !PSEUDO_ELEMENTS.has(pseudo)) throw new Error(`the capture pseudo-element ${pseudo.slice(0, 20)} is not ::before, ::after or ::marker`);
  return { selector, pseudo };
}

// `*` never matches a ::before or ::after, and a pseudo-element's own
// visibility beats the one it would inherit from its hidden element, so the
// pseudo-elements are hidden by a rule of their own:
// * subtree mode hides every other element's. Those of the target and of what
//   it holds are left to inherit the visibility the isolation gives their
//   element, or to keep their own declaration, so a pseudo-element the slide
//   hides stays hidden in the picture;
// * box mode hides every one, the target's own included: those are native. A
//   ::marker takes no visibility, so the target's own list marker, which
//   inherits its transparent colour, is made transparent in case the slide
//   gave it one of its own;
// * a ::before or ::after target shows alone, one class more specific than
//   the rule that hides every pseudo-element;
// * a ::marker target shows through its item, the only element shown, which
//   paints no box, its text and the marker's transparent: what is left is the
//   image the marker paints.
function isolationCss(capture) {
  const { selector, pseudo } = targetOf(capture);
  const transparentText = 'color: transparent !important; -webkit-text-fill-color: transparent !important;' +
    ' text-shadow: none !important;';
  const hidden = `html${BOOST}, body${BOOST} { background: transparent !important; }\n` +
    `*${BOOST} { visibility: hidden !important; }\n`;
  if (capture.mode === 'subtree' && !pseudo) {
    const others = `*${BOOST}:not(${selector}):not(${selector} *)`;
    return hidden +
      `${others}::before, ${others}::after { visibility: hidden !important; }\n` +
      `${selector}${BOOST}, ${selector} *${BOOST} { visibility: visible !important; }`;
  }
  const pseudoHidden = `*${BOOST}::before, *${BOOST}::after { visibility: hidden !important; }\n`;
  const ownMarker = `${selector}${BOOST}::marker { color: transparent !important; }`;
  if (pseudo === 'marker') {
    const unpainted = 'background: transparent !important; border-color: transparent !important;' +
      ' box-shadow: none !important; outline-color: transparent !important;' +
      ' text-decoration-color: transparent !important; -webkit-text-stroke-color: transparent !important;';
    return hidden + pseudoHidden +
      `${selector}${BOOST} { visibility: visible !important; ${transparentText} ${unpainted} }\n` + ownMarker;
  }
  const shown = pseudo ? `${selector}${BOOST}::${pseudo}` : `${selector}${BOOST}`;
  return hidden + pseudoHidden +
    `${shown} { visibility: visible !important; ${transparentText} }` + (pseudo ? '' : '\n' + ownMarker);
}

// What the isolation must not change about the target's own painting.
// * Subtree mode shows every descendant, so a descendant the slide hides
//   (an SVG group with visibility="hidden") is hidden again, one attribute
//   selector more specific than the rule that shows it; its pseudo-elements
//   inherit that, as they do on the slide.
// * Box mode makes the target's text transparent by setting `color`, which a
//   border or shadow drawn in currentColor follows; each is pinned to the
//   colour the slide paints it in, on the pseudo-element for a pseudo-element
//   target.
// * A box target whose borders are drawn elsewhere (bordersHidden: a
//   collapsed native table, whose grid draws its own and its cells' collapsed
//   borders, which the browser paints even for hidden cells) has every border
//   of it and of all it holds transparent instead. A border's colour moves
//   nothing, so the picture is laid out as the slide is.
function retainedCss(capture) {
  const { selector, pseudo } = targetOf(capture);
  const boost = BOOST;
  const target = pseudo ? `${selector}${boost}::${pseudo}` : `${selector}${boost}`;
  const rules = [];
  if (capture.mode === 'subtree' && capture.hiddenWithin) {
    rules.push(`${selector} [${HIDDEN_ATTRIBUTE}]${boost} { visibility: hidden !important; }`);
  }
  const bordersHidden = capture.mode === 'box' && capture.bordersHidden === true && !pseudo;
  if (bordersHidden) {
    rules.push(`${selector}${boost}, ${selector} *${boost} { border-color: transparent !important; }`);
  }
  const paint = capture.mode === 'box' && capture.paint ? capture.paint : null;
  if (paint) {
    const declarations = [];
    const sides = ['top', 'right', 'bottom', 'left'];
    const colours = Array.isArray(paint.borderColors) && !bordersHidden ? paint.borderColors : [];
    for (let index = 0; index < sides.length; index++) {
      const colour = colours[index];
      if (typeof colour === 'string' && colour && COMPUTED_VALUE.test(colour)) {
        declarations.push(`border-${sides[index]}-color: ${colour} !important;`);
      }
    }
    if (typeof paint.boxShadow === 'string' && paint.boxShadow && COMPUTED_VALUE.test(paint.boxShadow)) {
      declarations.push(`box-shadow: ${paint.boxShadow} !important;`);
    }
    if (declarations.length) rules.push(`${target} { ${declarations.join(' ')} }`);
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
    style: isolationCss(capture) + (retained ? '\n' + retained : ''),
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
      const message = oneLine(String((error && error.message) || error).split('\n')[0]);
      console.error(`[html2pptx] capture failed: ${capture.id} ${message}`);
    }
  }
  return pictures;
}

module.exports = { captureAll, isolationCss, CAPTURE_ATTRIBUTE, HIDDEN_ATTRIBUTE };
