#!/usr/bin/env node
// Test-side browser measurement for the snapshot-engine export tests.
//
// Loads one complete slide document with the SAME Playwright build and browser
// channel the huashu sidecar uses, on the same 1280x720 viewport at device scale
// 2 (render_slide.cjs's page), and with the same settle sequence: networkidle,
// document.fonts.ready, the canvas wait, then every animation finished (or
// cancelled when it has no end). So the rect it reports comes from the layout the
// export itself reads.
//
// usage: node measure.cjs <document.html> <selector> [index] [--mode=rect|rects|padding-box|lines|style|text]
//        node measure.cjs <document.html> <selector> --mode=each-rect|each-padding-box
//        node measure.cjs <document.html> --mode=fonts
//        node measure.cjs <document.html> <probes-json> --mode=probe
//        node measure.cjs <document.html> <point-json> --mode=hit
//        node measure.cjs <document.html> <pseudo-json> --mode=each-pseudo
// Measures the index-th (default 0) match of selector, in CSS px. Exits 2 when
// nothing matches.
//   --mode=rect  (the default) prints {"x":…,"y":…,"w":…,"h":…}, the element's
//                getBoundingClientRect().
//   --mode=each-rect prints [{"x":…,"y":…,"w":…,"h":…}, …], the
//                getBoundingClientRect() of EVERY match of selector, in document
//                order, from one page load. The index is ignored.
//   --mode=each-padding-box prints the padding box (as --mode=padding-box) of
//                every match of selector, in document order.
//   --mode=rects prints [{"x":…,"y":…,"w":…,"h":…}, …], the element's
//                getClientRects(): one border-box rect per box fragment, which
//                for an inline element is one per line it spans. See
//                measureClientRects.
//   --mode=padding-box prints {"x":…,"y":…,"w":…,"h":…}, the element's padding
//                box: where its overflow clips what it holds. See
//                measurePaddingBox.
//   --mode=lines prints [{"text":…,"x":…,"y":…,"w":…,"h":…}, …], the element's
//                rendered text lines in reading order, each with the union of its
//                character rects. See measureLines for how lines are found.
//   --mode=style prints {"fontFamily":…, "fontWeight":…, …}, the element's computed
//                typography (STYLE_PROPERTIES), as getComputedStyle serialises it.
//   --mode=text  prints {"text":…}, the element's innerText once every <svg> and
//                <canvas> in the document is hidden. See measureText.
//   --mode=fonts prints [{"family","weight","style","status"}, …], every face in
//                document.fonts. It reads the whole document, so it takes no
//                selector.
//   --mode=probe takes, in place of the selector, a JSON array of probes
//                [{"text":…, "css":…, "baseline":bool}, …] and prints
//                [{"w":…,"h":…}, …], the size of each probe's text set in the
//                document with that inline CSS, plus "ascent" for a baseline
//                probe. See measureProbes.
//   --mode=hit   takes, in place of the selector, a point as JSON {"x":…,"y":…}
//                in CSS px and prints {"id":…}: the id of the element the
//                browser hit-tests there, or of its nearest ancestor that has
//                one, else null. See measureHit.
//   --mode=each-pseudo takes, in place of the selector, JSON
//                {"selector":…, "pseudo":"before"|"after"} and prints, for EVERY
//                match of the selector in document order, null when it
//                generates no such pseudo-element box, else
//                {"x":…,"y":…,"w":…,"h":…,"text":…,"style":{…}}: the
//                pseudo-element's own border box and its rendered text, read
//                from the browser's layout through the DevTools protocol, and
//                its computed style (PSEUDO_STYLE_PROPERTIES). See measurePseudo.
//
// Called from tests/fixtures/export_snapshot_support.py (browser_rect,
// browser_each_rect, browser_client_rects, browser_padding_box,
// browser_each_padding_box, browser_line_boxes, browser_lines, browser_style,
// browser_text, browser_loaded_weights, browser_probes, browser_hit_id,
// browser_each_pseudo).

const path = require('path');

const SIDECAR_DIR = path.resolve(__dirname, '..', '..', '..', 'services', 'pptx-emit-huashu');
const { chromium } = require(path.join(SIDECAR_DIR, 'node_modules', 'playwright'));

function launchOptions() {
  // Same launch as html2pptx.js: Chrome on macOS, Chromium without the sandbox
  // elsewhere, and the inherited env so LD_LIBRARY_PATH reaches the browser.
  const options = { env: { ...process.env } };
  if (process.platform === 'darwin') {
    options.channel = 'chrome';
  } else {
    options.args = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'];
  }
  return options;
}

// The same settle as render_slide.cjs, step for step and with the same bounds,
// so a test measures the state the engine exports. Written out here rather than
// imported from the engine, so the measurement stays an independent oracle.
const NETWORK_IDLE_TIMEOUT_MS = 4000;
const FONTS_READY_TIMEOUT_MS = 5000;
const CANVAS_READY_TIMEOUT_MS = 5000;
const CANVAS_SETTLE_MS = 2000;

async function waitForFonts(page) {
  let timer;
  try {
    await Promise.race([
      page.evaluate(() => document.fonts.ready.then(() => true)),
      new Promise((resolve) => { timer = setTimeout(resolve, FONTS_READY_TIMEOUT_MS); }),
    ]);
  } catch (error) {
    // The engine continues without fonts.ready too.
  } finally {
    clearTimeout(timer);
  }
}

async function settle(page) {
  try {
    await page.waitForLoadState('networkidle', { timeout: NETWORK_IDLE_TIMEOUT_MS });
  } catch (error) {
    // A slide may legitimately keep a request open; the sidecar ignores this too.
  }
  await waitForFonts(page);
  const canvasCount = await page.evaluate(() => document.querySelectorAll('canvas').length);
  if (canvasCount > 0) {
    // The options are waitForFunction's THIRD argument; the second is the page function's arg.
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('canvas')).every((canvas) => canvas.width > 0 && canvas.height > 0),
      undefined,
      { timeout: CANVAS_READY_TIMEOUT_MS },
    ).catch(() => {});
    await page.waitForTimeout(CANVAS_SETTLE_MS);
  }
  // The settled state: an entrance animation is measured where it ends. Each
  // finish() is guarded on its own, because an infinite animation throws; such
  // an animation is cancelled instead, so it is measured in its un-animated style.
  await page.evaluate(() => {
    const animations = document.getAnimations();
    for (let index = 0; index < animations.length; index++) {
      try {
        animations[index].finish();
      } catch (error) {
        try {
          animations[index].cancel();
        } catch (cancelError) {
          // Neither finished nor cancelled: it is measured as it stands.
        }
      }
    }
  });
}

async function measureRect(page, selector, index) {
  return page.evaluate(({ selector, index }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const rect = matches[index].getBoundingClientRect();
    return { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
  }, { selector, index });
}

// More rects than any real slide element has fragments: a document reporting
// more is lying about its rects, and is reported rather than read.
const CLIENT_RECT_LIMIT = 10000;

// The element's box fragments, getClientRects() in the order the browser lists
// them. An inline element that wraps has one border-box rect per line box it
// lies on; under the default box-decoration-break: slice its start padding and
// border are on the first fragment only and its end ones on the last. Every
// rect is reported, zero-width ones included, so a test decides which count.
async function measureClientRects(page, selector, index) {
  return page.evaluate(({ selector, index, limit }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const rects = matches[index].getClientRects();
    if (!(rects.length <= limit)) {
      return { error: `selector ${selector} reported ${rects.length} client rects; more than ${limit} is not a real layout` };
    }
    const result = [];
    for (let rectIndex = 0; rectIndex < rects.length; rectIndex++) {
      const rect = rects[rectIndex];
      result.push({ x: rect.x, y: rect.y, w: rect.width, h: rect.height });
    }
    return { rects: result };
  }, { selector, index, limit: CLIENT_RECT_LIMIT });
}

// The element's padding box: its border box (getBoundingClientRect()) less its
// computed border width on each side. An element's overflow (hidden, clip,
// auto, scroll) clips what it holds to this box, its overflow clip edge under
// the default overflow-clip-margin of 0. Read from the computed widths, not
// clientLeft/clientWidth, which round to whole pixels. The element must not be
// transformed: the bounding rect of a rotated box is not its border box.
async function measurePaddingBox(page, selector, index) {
  return page.evaluate(({ selector, index }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const element = matches[index];
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const left = parseFloat(style.borderLeftWidth) || 0;
    const right = parseFloat(style.borderRightWidth) || 0;
    const top = parseFloat(style.borderTopWidth) || 0;
    const bottom = parseFloat(style.borderBottomWidth) || 0;
    return { x: rect.x + left, y: rect.y + top, w: rect.width - left - right, h: rect.height - top - bottom };
  }, { selector, index });
}

// More matches than any real slide has elements of one kind: a document
// reporting more is lying about its tree, and is reported rather than read.
const MATCH_LIMIT = 10000;

// The border box (getBoundingClientRect()) or the padding box (as
// measurePaddingBox reads it: the border box less the computed border widths)
// of every match of selector, in document order, from the one settled page. So
// a test measuring many elements of a slide pays for one browser launch.
async function measureEach(page, selector, box) {
  return page.evaluate(({ selector, box, limit }) => {
    const matches = document.querySelectorAll(selector);
    if (matches.length === 0) {
      return { error: `selector ${selector} matched no element` };
    }
    if (!(matches.length <= limit)) {
      return { error: `selector ${selector} matched ${matches.length} elements; more than ${limit} is not a real slide` };
    }
    const boxes = [];
    for (let index = 0; index < matches.length; index++) {
      const rect = matches[index].getBoundingClientRect();
      if (box !== 'padding') {
        boxes.push({ x: rect.x, y: rect.y, w: rect.width, h: rect.height });
        continue;
      }
      const style = getComputedStyle(matches[index]);
      const left = parseFloat(style.borderLeftWidth) || 0;
      const right = parseFloat(style.borderRightWidth) || 0;
      const top = parseFloat(style.borderTopWidth) || 0;
      const bottom = parseFloat(style.borderBottomWidth) || 0;
      boxes.push({ x: rect.x + left, y: rect.y + top, w: rect.width - left - right, h: rect.height - top - bottom });
    }
    return { boxes };
  }, { selector, box, limit: MATCH_LIMIT });
}

// What the browser shows at a point, by hit testing: document.elementFromPoint
// returns the topmost element painted there. Hit testing honours everything
// that clips or hides an element (an overflow ancestor, clip, clip-path,
// visibility: hidden) but not opacity, so it tells whether an element is
// visible at that point without trusting any reading of the CSS. It tells
// shown from hidden, not where a clip's edge lies: Chrome hit-tests an
// overflow clip at the clipping element's border box, though it paints the
// clip at the padding box. The point arrives as JSON in place of the selector
// and must lie in the viewport; outside it nothing is hit. Reports the id of
// the hit element or of its nearest ancestor that has one, else null.
async function measureHit(page, pointArgument) {
  let point;
  try {
    point = JSON.parse(pointArgument);
  } catch (error) {
    return { error: `the point is not JSON: ${error.message}` };
  }
  if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
    return { error: 'the point must be JSON {"x": number, "y": number}' };
  }
  return page.evaluate(({ x, y }) => {
    const hit = document.elementFromPoint(x, y);
    const owner = hit ? hit.closest('[id]') : null;
    return { id: owner ? owner.id : null };
  }, { x: point.x, y: point.y });
}

// The element's rendered text, line by line, read character by character with a
// Range, which is how the browser itself reports where each glyph was painted.
// Written independently of the engine's tokenizer, so a test can hold the
// engine's lines against it.
//
// * Text inside <svg> is skipped: it is part of the drawing, not of a CSS line.
// * A character counts when it painted a rect: white space (CSS's: space, tab,
//   LF, CR, FF, never NBSP) needs a rect with width, because Chrome reports a
//   collapsed space as a zero-width rect (and a space at a wrap point as a
//   zero-width rect on both lines); any other character needs a rect at all. A
//   painted white-space character is the single space it renders as; under
//   white-space pre, pre-wrap and break-spaces it is kept as written. Where
//   newlines are preserved (those three and pre-line) a newline is a forced
//   break and never paints; elsewhere it is collapsible white space like a space.
// * Lines are clustered by vertical overlap, in DOM order: a character joins the
//   current line when its rect overlaps the line's vertical range by more than
//   half the smaller of the two heights. Half, not any overlap: glyph rects are
//   the font's ascent plus descent, so with a line-height under about 1.3 (the
//   corpus titles use 1.08) consecutive lines' rects overlap by several px.
// * A collapsible line is trimmed at both ends. A line with no painted
//   character (an empty pre line) is not reported.
//
// Measures one text block: side-by-side flex or grid items on the same band
// would cluster into one line.
async function measureLines(page, selector, index) {
  return page.evaluate(({ selector, index }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const PRESERVED_WHITE_SPACE = /^(pre|pre-wrap|break-spaces)$/;
    const PRESERVED_NEWLINES = /^(pre|pre-wrap|pre-line|break-spaces)$/;
    // CSS's collapsible white space; NBSP is not, and JS \s would include it.
    const CSS_WHITE_SPACE = /^[ \t\n\r\f]$/;
    const lines = [];
    let current = null;
    const walker = document.createTreeWalker(matches[index], NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || parent.closest('svg')) continue;
      const whiteSpace = getComputedStyle(parent).whiteSpace;
      const preserved = PRESERVED_WHITE_SPACE.test(whiteSpace);
      const newlinesPreserved = PRESERVED_NEWLINES.test(whiteSpace);
      const data = node.data;
      let offset = 0;
      while (offset < data.length) {
        // One code point at a time, so an astral character (emoji) is one Range.
        const length = data.codePointAt(offset) > 0xffff ? 2 : 1;
        const character = data.slice(offset, offset + length);
        const range = document.createRange();
        range.setStart(node, offset);
        range.setEnd(node, offset + length);
        offset += length;
        if (newlinesPreserved && (character === '\n' || character === '\r')) continue;
        const whitespace = CSS_WHITE_SPACE.test(character);
        const rects = range.getClientRects();
        let rect = null;
        for (let rectIndex = 0; rectIndex < rects.length; rectIndex++) {
          if (rects[rectIndex].width > 0 || (!whitespace && rects[rectIndex].height > 0)) {
            rect = rects[rectIndex];
            break;
          }
        }
        if (!rect) continue;
        const text = whitespace && !preserved ? ' ' : character;
        const overlap = current
          ? Math.min(current.bottom, rect.bottom) - Math.max(current.top, rect.top)
          : 0;
        const sameLine = current &&
          overlap > Math.min(current.bottom - current.top, rect.height) / 2;
        if (!sameLine) {
          current = {
            text: '',
            preserved,
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
          };
          lines.push(current);
        }
        current.text += text;
        current.left = Math.min(current.left, rect.left);
        current.top = Math.min(current.top, rect.top);
        current.right = Math.max(current.right, rect.right);
        current.bottom = Math.max(current.bottom, rect.bottom);
      }
    }
    const result = [];
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      const line = lines[lineIndex];
      const text = line.preserved ? line.text : line.text.replace(/ {2,}/g, ' ').replace(/^ | $/g, '');
      if (!text) continue;
      result.push({ text, x: line.left, y: line.top, w: line.right - line.left, h: line.bottom - line.top });
    }
    return { lines: result };
  }, { selector, index });
}

// The computed properties a run's style is read from, plus the ones the
// typography tests guard their fixtures with (the backdrop and gradient text)
// and the line-spacing tests with (the line height, the optical size the
// browser draws a variable font at, and the alignment).
const STYLE_PROPERTIES = [
  'fontFamily', 'fontWeight', 'fontStyle', 'fontSize', 'letterSpacing', 'textTransform',
  'textDecorationLine', 'verticalAlign', 'direction', 'color', 'webkitTextFillColor', 'opacity',
  'backgroundColor', 'backgroundImage', 'backgroundClip', 'webkitBackgroundClip',
  'lineHeight', 'fontOpticalSizing', 'fontVariationSettings', 'textAlign',
];

// What --mode=each-pseudo reports of a pseudo-element's computed style: the
// typography above, plus what its box paints with and where it stacks.
const PSEUDO_STYLE_PROPERTIES = [
  ...STYLE_PROPERTIES,
  'borderTopWidth', 'borderTopStyle', 'borderTopColor', 'boxShadow', 'zIndex', 'display', 'position',
];

async function measureStyle(page, selector, index) {
  return page.evaluate(({ selector, index, properties }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const style = getComputedStyle(matches[index]);
    const result = {};
    for (const property of properties) result[property] = String(style[property]);
    return result;
  }, { selector, index, properties: STYLE_PROPERTIES });
}

// The element's text as the browser renders it, read with innerText, which
// applies text-transform and the rendered line breaks. Every <svg> and <canvas>
// in the document is hidden first, exactly as the export fidelity harness's
// text-loss reference is taken (scripts/export_fidelity/render_truth.cjs): their
// text travels inside a picture, never as slide text. Hiding them changes the
// layout, so this mode reads nothing else, and with the selector "body" it is
// that reference.
async function measureText(page, selector, index) {
  return page.evaluate(({ selector, index }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const graphics = document.querySelectorAll('svg, canvas');
    for (let graphicIndex = 0; graphicIndex < graphics.length; graphicIndex++) {
      graphics[graphicIndex].style.display = 'none';
    }
    return { text: matches[index].innerText };
  }, { selector, index });
}

// Every face in document.fonts (a FontFaceSet), with the status it settled at:
// a face is 'loaded' only once the page used it.
async function measureFonts(page) {
  return page.evaluate(() => {
    const faces = [];
    document.fonts.forEach((face) => {
      faces.push({ family: face.family, weight: face.weight, style: face.style, status: face.status });
    });
    return faces;
  });
}

// Text set in the document's own fonts, outside its layout. Each probe is a
// <div> appended to documentElement, absolutely positioned offscreen and
// hidden, so it moves nothing else on the page, with white-space: pre so it
// never wraps and no margin, padding or border. Its `css` is appended to that
// inline style and sets the font, for example
//   "font: 600 64px 'DM Sans'; line-height: normal"
//   "font: 600 64px 'DM Sans'; letter-spacing: 0; font-variation-settings: 'opsz' 14".
// The probe's size is its border box: its width is the advance width of its
// text, and with line-height: normal its height is the font's natural line
// height. A probe with "baseline": true also reports "ascent": the distance
// from its text's top (a Range over the text, the glyph top the engine reads)
// down to its baseline, found with a zero-size inline-block placed on the
// baseline ahead of the text. Every probe is appended first, then
// document.fonts.ready is awaited again (a probe may ask for a face the page
// has not used yet), then each is read and removed.
async function measureProbes(page, probesArgument) {
  let probes;
  try {
    probes = JSON.parse(probesArgument);
  } catch (error) {
    return { error: `the probes are not JSON: ${error.message}` };
  }
  if (!Array.isArray(probes)) {
    return { error: 'the probes must be a JSON array of {"text", "css"}' };
  }
  return page.evaluate(async ({ probes, timeoutMs }) => {
    const PROBE_STYLE = 'position:absolute;left:-10000px;top:0;visibility:hidden;' +
      'white-space:pre;margin:0;padding:0;border:0;';
    const MARKER_STYLE = 'display:inline-block;width:0;height:0;vertical-align:baseline;' +
      'margin:0;padding:0;border:0;';
    const elements = [];
    for (let index = 0; index < probes.length; index++) {
      const element = document.createElement('div');
      element.setAttribute('style', PROBE_STYLE + String(probes[index].css || ''));
      let marker = null;
      if (probes[index].baseline) {
        marker = document.createElement('span');
        marker.setAttribute('style', MARKER_STYLE);
        element.appendChild(marker);
      }
      const text = document.createTextNode(String(probes[index].text || ''));
      element.appendChild(text);
      document.documentElement.appendChild(element);
      elements.push({ element, marker, text });
    }
    let timer;
    await Promise.race([
      document.fonts.ready,
      new Promise((resolve) => { timer = setTimeout(resolve, timeoutMs); }),
    ]);
    clearTimeout(timer);
    const sizes = [];
    for (let index = 0; index < elements.length; index++) {
      const { element, marker, text } = elements[index];
      const rect = element.getBoundingClientRect();
      const size = { w: rect.width, h: rect.height };
      if (marker) {
        const range = document.createRange();
        range.selectNodeContents(text);
        size.ascent = marker.getBoundingClientRect().top - range.getBoundingClientRect().top;
      }
      sizes.push(size);
      element.remove();
    }
    return { sizes };
  }, { probes, timeoutMs: FONTS_READY_TIMEOUT_MS });
}

// A pseudo-element (::before, ::after) is no DOM element: no page API reports
// its box or the text its `content` generated (innerText leaves it out). The
// DevTools protocol reads both from the browser's own layout of the untouched
// page, so a test holds what the export makes of a pseudo-element against the
// browser's rendering of that very pseudo-element, never against a re-creation
// of it:
// * the box is DOM.getBoxModel's border quad for the pseudo-element node
//   (DOM.getDocument lists each element's pseudoElements), as its bounds in
//   CSS px; a pseudo-element the browser generates no box for (display: none)
//   reports none, and neither does one whose content is none or normal, which
//   the browser does not generate at all;
// * the text is that of the layout text objects DOMSnapshot.captureSnapshot
//   attributes to the pseudo-element node, in layout order: the browser's own
//   evaluation of its content (string escapes decoded, quotes, attr(),
//   counter() and counters() with their styles), before white space collapses.
// Pseudo-element nodes are matched across the two protocol reads by their
// backend node id. Its computed style (getComputedStyle(element, '::before'))
// is read in the page, for the matches in the same document order.
const PSEUDO_TYPES = new Set(['before', 'after']);
// Deeper than any pseudo-element's own layout subtree: a layout text object
// is the pseudo-element node's or a child's.
const PSEUDO_TEXT_DEPTH_LIMIT = 16;

async function measurePseudo(page, argument) {
  let request;
  try {
    request = JSON.parse(argument);
  } catch (error) {
    return { error: `the pseudo request is not JSON: ${error.message}` };
  }
  if (!request || typeof request.selector !== 'string' || !PSEUDO_TYPES.has(request.pseudo)) {
    return { error: 'the pseudo request must be JSON {"selector": string, "pseudo": "before" | "after"}' };
  }
  const session = await page.context().newCDPSession(page);
  try {
    const { root } = await session.send('DOM.getDocument', { depth: -1 });
    const nodes = new Map();
    const pending = [root];
    while (pending.length) {
      const node = pending.pop();
      nodes.set(node.nodeId, node);
      for (const child of node.children || []) pending.push(child);
      for (const child of node.pseudoElements || []) pending.push(child);
    }
    const { nodeIds } = await session.send('DOM.querySelectorAll', { nodeId: root.nodeId, selector: request.selector });
    if (nodeIds.length === 0) {
      return { error: `selector ${request.selector} matched no element` };
    }
    if (!(nodeIds.length <= MATCH_LIMIT)) {
      return { error: `selector ${request.selector} matched ${nodeIds.length} elements; more than ${MATCH_LIMIT} is not a real slide` };
    }

    const snapshot = await session.send('DOMSnapshot.captureSnapshot', { computedStyles: [] });
    const documentSnapshot = snapshot.documents[0];
    const snapshotIndex = new Map();
    documentSnapshot.nodes.backendNodeId.forEach((backendNodeId, index) => snapshotIndex.set(backendNodeId, index));
    const parents = documentSnapshot.nodes.parentIndex;
    const layout = documentSnapshot.layout;
    // Layout text, by the pseudo-element node (or ancestor within the depth limit) it belongs to.
    const textOf = (pseudoIndex) => {
      let text = '';
      for (let entry = 0; entry < layout.nodeIndex.length; entry++) {
        const stringIndex = layout.text[entry];
        if (!(stringIndex >= 0)) continue;
        let owner = layout.nodeIndex[entry];
        for (let depth = 0; depth < PSEUDO_TEXT_DEPTH_LIMIT && owner >= 0 && owner !== pseudoIndex; depth++) {
          owner = parents[owner];
        }
        if (owner === pseudoIndex) text += snapshot.strings[stringIndex];
      }
      return text;
    };

    const styles = await page.evaluate(({ selector, pseudo, properties }) => {
      const matches = document.querySelectorAll(selector);
      const result = [];
      for (let index = 0; index < matches.length; index++) {
        const style = getComputedStyle(matches[index], '::' + pseudo);
        const read = {};
        for (const property of properties) read[property] = String(style[property]);
        result.push(read);
      }
      return result;
    }, { selector: request.selector, pseudo: request.pseudo, properties: PSEUDO_STYLE_PROPERTIES });
    if (styles.length !== nodeIds.length) {
      return { error: `selector ${request.selector} matched ${nodeIds.length} nodes through the protocol but ${styles.length} in the page` };
    }

    const boxes = [];
    for (let matchIndex = 0; matchIndex < nodeIds.length; matchIndex++) {
      const element = nodes.get(nodeIds[matchIndex]);
      const pseudoNode = element && (element.pseudoElements || []).find((candidate) => candidate.pseudoType === request.pseudo);
      if (!pseudoNode) {
        boxes.push(null);
        continue;
      }
      let model;
      try {
        ({ model } = await session.send('DOM.getBoxModel', { nodeId: pseudoNode.nodeId }));
      } catch (error) {
        // Generated, but laid out as no box (display: none).
        boxes.push(null);
        continue;
      }
      const xs = [model.border[0], model.border[2], model.border[4], model.border[6]];
      const ys = [model.border[1], model.border[3], model.border[5], model.border[7]];
      const left = Math.min(...xs);
      const top = Math.min(...ys);
      const pseudoIndex = snapshotIndex.get(pseudoNode.backendNodeId);
      boxes.push({
        x: left,
        y: top,
        w: Math.max(...xs) - left,
        h: Math.max(...ys) - top,
        text: pseudoIndex === undefined ? '' : textOf(pseudoIndex),
        style: styles[matchIndex],
      });
    }
    return { boxes };
  } finally {
    await session.detach().catch(() => {});
  }
}

const MODES = {
  rect: measureRect,
  rects: async (page, selector, index) => {
    const measured = await measureClientRects(page, selector, index);
    return measured.error ? measured : measured.rects;
  },
  'padding-box': measurePaddingBox,
  'each-rect': async (page, selector) => {
    const measured = await measureEach(page, selector, 'border');
    return measured.error ? measured : measured.boxes;
  },
  'each-padding-box': async (page, selector) => {
    const measured = await measureEach(page, selector, 'padding');
    return measured.error ? measured : measured.boxes;
  },
  lines: async (page, selector, index) => {
    const measured = await measureLines(page, selector, index);
    return measured.error ? measured : measured.lines;
  },
  style: measureStyle,
  text: measureText,
  fonts: measureFonts,
  probe: async (page, probesArgument) => {
    const measured = await measureProbes(page, probesArgument);
    return measured.error ? measured : measured.sizes;
  },
  hit: measureHit,
  'each-pseudo': async (page, argument) => {
    const measured = await measurePseudo(page, argument);
    return measured.error ? measured : measured.boxes;
  },
};
// Modes that read the whole document rather than one element.
const DOCUMENT_MODES = new Set(['fonts']);

function parseArguments(argv) {
  const positional = [];
  let mode = 'rect';
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument.startsWith('--mode=')) {
      mode = argument.slice('--mode='.length);
    } else {
      positional.push(argument);
    }
  }
  return { documentPath: positional[0], selector: positional[1], indexArgument: positional[2], mode };
}

async function main() {
  const { documentPath, selector, indexArgument, mode } = parseArguments(process.argv.slice(2));
  if (!documentPath || (!selector && !DOCUMENT_MODES.has(mode))) {
    console.error(
      'usage: node measure.cjs <document.html> <selector> [index] [--mode=rect|rects|padding-box|lines|style|text]\n' +
      '       node measure.cjs <document.html> <selector> --mode=each-rect|each-padding-box\n' +
      '       node measure.cjs <document.html> --mode=fonts\n' +
      '       node measure.cjs <document.html> <probes-json> --mode=probe\n' +
      '       node measure.cjs <document.html> <point-json> --mode=hit\n' +
      '       node measure.cjs <document.html> <pseudo-json> --mode=each-pseudo',
    );
    process.exit(1);
  }
  if (!Object.prototype.hasOwnProperty.call(MODES, mode)) {
    console.error(`unknown mode ${mode}; expected one of ${Object.keys(MODES).join(', ')}`);
    process.exit(1);
  }
  const index = indexArgument === undefined ? 0 : Number.parseInt(indexArgument, 10);
  if (!Number.isInteger(index) || index < 0) {
    console.error(`index must be a non-negative integer, got ${indexArgument}`);
    process.exit(1);
  }
  const browser = await chromium.launch(launchOptions());
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 });
    await page.goto('file://' + path.resolve(documentPath));
    await settle(page);
    const measured = await MODES[mode](page, selector, index);
    if (measured.error) {
      console.error(measured.error);
      process.exitCode = 2;
      return;
    }
    process.stdout.write(JSON.stringify(measured) + '\n');
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
