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
// usage: node measure.cjs <document.html> <selector> [index] [--mode=rect|lines|style|text]
//        node measure.cjs <document.html> --mode=fonts
// Measures the index-th (default 0) match of selector, in CSS px. Exits 2 when
// nothing matches.
//   --mode=rect  (the default) prints {"x":…,"y":…,"w":…,"h":…}, the element's
//                getBoundingClientRect().
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
//
// Called from tests/fixtures/export_snapshot_support.py (browser_rect,
// browser_line_boxes, browser_lines, browser_style, browser_text,
// browser_loaded_weights).

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
// typography tests guard their fixtures with (the backdrop and gradient text).
const STYLE_PROPERTIES = [
  'fontFamily', 'fontWeight', 'fontStyle', 'fontSize', 'letterSpacing', 'textTransform',
  'textDecorationLine', 'verticalAlign', 'direction', 'color', 'opacity',
  'backgroundColor', 'backgroundImage', 'backgroundClip', 'webkitBackgroundClip',
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

const MODES = {
  rect: measureRect,
  lines: async (page, selector, index) => {
    const measured = await measureLines(page, selector, index);
    return measured.error ? measured : measured.lines;
  },
  style: measureStyle,
  text: measureText,
  fonts: measureFonts,
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
      'usage: node measure.cjs <document.html> <selector> [index] [--mode=rect|lines|style|text]\n' +
      '       node measure.cjs <document.html> --mode=fonts',
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
