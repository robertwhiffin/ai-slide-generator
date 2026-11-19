'use strict';
// The snapshot engine, one slide at a time:
//
//   1. load and settle   networkidle, document.fonts.ready, the canvas wait, then
//                        every animation finished, so a fade-in exports settled;
//   2. preprocess        BG_TRANSFER_SOURCE: the slide root's ground onto body,
//                        nothing that moves layout;
//   3. validate          the legacy converter's body and text-box checks;
//   4. pseudo-elements   pseudo.mjs: every ::before, ::after and list item
//                        ::marker, read from Node through the DevTools
//                        protocol, read-only; nothing is inserted into the
//                        page for them (ruling R8);
//   5. snapshot          SNAPSHOT_SOURCE: one read-only page.evaluate of what
//                        step 4 read, which returns the slide model (snapshot.mjs);
//   6. capture           capture.cjs: an element-isolated 2x screenshot of each
//                        capture target the model names, from the same page;
//   7. emit              emit_model.cjs writes the model to a pptxgenjs slide.
//
// renderSlide(htmlFile, pres, { bypassValidation, preProcessSource, target })
//   -> { slide, summary }
// preProcessSource defaults to BG_TRANSFER_SOURCE; null runs no preprocess.
// target is the renderer the deck is written for, 'pptx' (the default) or
// 'gslides': emit_model.cjs writes the few constructs the two place apart
// for it (emit_text.cjs writtenParagraphs, emit_typography.cjs fontSizePt).
// The `slide` matches what html2pptx.js returns, so emit_deck.mjs attaches
// speaker notes to it the same way for both engines.

const path = require('path');
const { chromium } = require('playwright');
const { captureAll } = require('./capture.cjs');
const { emitSlide, pictureData } = require('./emit_model.cjs');

const PT_PER_PX = 0.75;
const PX_PER_IN = 96;
const EMU_PER_IN = 914400;

// The slide's own size in CSS px. Device scale 2 changes no layout; it makes
// every screenshot of the page (captures) twice the box.
const SLIDE_VIEWPORT = { width: 1280, height: 720 };
const DEVICE_SCALE_FACTOR = 2;

const NETWORK_IDLE_TIMEOUT_MS = 4000;
const FONTS_READY_TIMEOUT_MS = 5000;
const CANVAS_READY_TIMEOUT_MS = 5000;
// Chart.js animates for 1000 ms by default, after the chart-init IIFE's own
// setTimeout chain in build_slide_html; 2000 ms covers both.
const CANVAS_SETTLE_MS = 2000;
// Tellr decks overflow body by ~80 px (a footer or one extra section), clipped
// by overflow: hidden. Only a dramatic overflow is an authoring error.
const TELLR_OVERFLOW_TOLERANCE_PX = 100;
const MIN_BOTTOM_MARGIN_IN = 0.5;

// ─── page-side reads ───────────────────────────────────────────────────
// Each runs in the page after DOM_ACCESS_SOURCE, whose helpers (queryAll,
// queryOne) and limits are their free names. They are stringified, so they
// close over nothing here. Slide script has already run in this page by the
// time any of them fires, so none of them walks the DOM any other way.

function pageCanvasCount() {
  return queryAll('canvas').length;
}

// Every canvas has a drawing buffer: Chart.js sets the size once it initialises.
function pageCanvasesReady() {
  const canvases = queryAll('canvas');
  for (let index = 0; index < canvases.length; index++) {
    if (!(canvases[index].width > 0 && canvases[index].height > 0)) return false;
  }
  return true;
}

// The settled state: each CSS animation and transition jumps to its end. Each
// finish() is guarded on its own, because an infinite animation throws and must
// not leave the rest unfinished. An animation with no end is cancelled instead,
// so it shows its un-animated style: caught mid-cycle, a spinner's angle would
// depend on timing, and identical slides must export identically.
function pageFinishAnimations() {
  let animations;
  try {
    animations = document.getAnimations();
  } catch (e) {
    return { finished: 0, cancelled: 0, unfinished: 0 };
  }
  const length = Math.min(Number(animations && animations.length) || 0, COLLECTION_ITEM_LIMIT);
  let finished = 0;
  let cancelled = 0;
  let unfinished = 0;
  for (let index = 0; index < length; index++) {
    const animation = animations[index];
    try {
      animation.finish();
      finished += 1;
    } catch (e) {
      try {
        animation.cancel();
        cancelled += 1;
      } catch (cancelError) {
        unfinished += 1;
      }
    }
  }
  return { finished, cancelled, unfinished };
}

function pageBodyDimensions() {
  const body = queryOne('body');
  const style = window.getComputedStyle(body);
  return {
    width: parseFloat(style.width),
    height: parseFloat(style.height),
    scrollWidth: body.scrollWidth,
    scrollHeight: body.scrollHeight,
  };
}

// The ESM page sources, and the Node-side pseudo-element read, loaded once per process.
let pageSourcesPromise = null;
function loadPageSources() {
  if (!pageSourcesPromise) {
    pageSourcesPromise = Promise.all([
      import('./dom_access.mjs'),
      import('./preprocess.mjs'),
      import('./snapshot.mjs'),
      import('./pseudo.mjs'),
    ])
      .then(([access, preprocess, snapshot, pseudo]) => {
        const withDomAccess = (pageFunction) => `(() => {
  const DOM_ACCESS_LOG_PREFIX = '[html2pptx]';
${access.DOM_ACCESS_SOURCE}
  return (${pageFunction.toString()})();
})()`;
        return {
          canvasCount: withDomAccess(pageCanvasCount),
          canvasesReady: withDomAccess(pageCanvasesReady),
          finishAnimations: withDomAccess(pageFinishAnimations),
          bodyDimensions: withDomAccess(pageBodyDimensions),
          bgTransfer: preprocess.BG_TRANSFER_SOURCE,
          // The snapshot page function applied to what pseudo.mjs read: JSON is
          // a JavaScript expression, so the data is the call's argument.
          snapshotOf: (pseudoData) => `${snapshot.SNAPSHOT_SOURCE}(${JSON.stringify(pseudoData)})`,
          readPseudoElements: pseudo.readPseudoElements,
        };
      });
  }
  return pageSourcesPromise;
}

// ─── browser ───────────────────────────────────────────────────────────
// Chrome on macOS, Chromium elsewhere. On Linux (Databricks Apps) the sidecar
// runs as non-root, so the sandbox is off and /dev/shm is not used. The env is
// merged with process.env so Chromium inherits LD_LIBRARY_PATH, which
// sidecar_subprocess_env() points at the bundled sys-libs.
// Rasterization is in software everywhere (--disable-gpu): identical pages
// must export byte-identical pictures, and GPU rasterization on macOS
// anti-aliased a chart's edges differently in about one capture in twenty.
// Databricks Apps has no GPU, so this is how it renders anyway.
function launchOptions(tmpDir) {
  const options = { env: { ...process.env, TMPDIR: tmpDir }, args: ['--disable-gpu'] };
  if (process.platform === 'darwin') {
    options.channel = 'chrome';
  } else {
    options.args.push(
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
    );
  }
  return options;
}

// [preprocess] and [html2pptx] lines report content leaving the deck, so they go
// to stderr, the only stream pptx_from_html_huashu.py echoes into the app log.
// Page chatter stays on stdout.
function forwardConsole(page) {
  page.on('console', (msg) => {
    const text = msg.text();
    if (text.startsWith('[preprocess]') || text.startsWith('[html2pptx]')) {
      console.error(`Browser console: ${text}`);
      return;
    }
    console.log(`Browser console: ${text}`);
  });
}

// ─── settle ────────────────────────────────────────────────────────────
async function waitForFonts(page) {
  // Bounded here, not in the page: a font set that never reports ready must
  // cost seconds, not the export.
  let timer;
  try {
    await Promise.race([
      page.evaluate('document.fonts.ready.then(() => true)'),
      new Promise((resolve) => { timer = setTimeout(resolve, FONTS_READY_TIMEOUT_MS); }),
    ]);
  } catch (e) {
    console.error(`[html2pptx] document.fonts.ready failed: ${e.message} — continuing`);
  } finally {
    clearTimeout(timer);
  }
}

async function waitForCanvases(page, sources) {
  const canvasCount = await page.evaluate(sources.canvasCount);
  if (canvasCount > 0) {
    await page.waitForFunction(sources.canvasesReady, undefined, { timeout: CANVAS_READY_TIMEOUT_MS })
      .catch(() => {});
    await new Promise((resolve) => setTimeout(resolve, CANVAS_SETTLE_MS));
  }
}

async function finishAnimations(page, sources) {
  try {
    return await page.evaluate(sources.finishAnimations);
  } catch (e) {
    console.error(`[html2pptx] finishing animations failed: ${e.message} — continuing`);
    return { finished: 0, cancelled: 0, unfinished: 0 };
  }
}

async function settle(page, sources) {
  try {
    await page.waitForLoadState('networkidle', { timeout: NETWORK_IDLE_TIMEOUT_MS });
  } catch (e) { /* ignore — some slides legitimately keep a long-poll open */ }
  await waitForFonts(page);
  await waitForCanvases(page, sources);
  return finishAnimations(page, sources);
}

// ─── preprocess ────────────────────────────────────────────────────────
// The same log lines html2pptx.js prints, so both engines read alike in the log.
async function runPreprocess(page, preProcessSource) {
  if (!preProcessSource) return null;
  try {
    const result = await page.evaluate(preProcessSource);
    if (result && typeof result === 'object') {
      console.log(`[preprocess] wrapped ${result.wrapped || 0} text nodes, ` +
                  `replaced ${result.replacedImgs || 0} bg-image divs, ` +
                  `peeled ${result.peeledTextTags || 0} text tags`);
      // No slide root means no background transfer, so this slide exports on the
      // untouched body default (white): indistinguishable in the .pptx from a
      // locator regression. The page-side '[preprocess] no slide root' line
      // carries the shape that was actually seen.
      if (result.bgTransferred === 'no-root') {
        console.error('[preprocess] slide-root locator resolved NO root: this slide ' +
                      'exports with the untouched body background (white).');
      }
    }
    return result;
  } catch (e) {
    console.error(`[preprocess] failed: ${e.message} — continuing without`);
    return null;
  }
}

// ─── validation ────────────────────────────────────────────────────────
// The legacy converter's three checks, with its message texts.
async function readBodyDimensions(page, sources) {
  const bodyDimensions = await page.evaluate(sources.bodyDimensions);
  const errors = [];
  const widthOverflowPx = Math.max(0, bodyDimensions.scrollWidth - bodyDimensions.width - TELLR_OVERFLOW_TOLERANCE_PX);
  const heightOverflowPx = Math.max(0, bodyDimensions.scrollHeight - bodyDimensions.height - TELLR_OVERFLOW_TOLERANCE_PX);
  const widthOverflowPt = widthOverflowPx * PT_PER_PX;
  const heightOverflowPt = heightOverflowPx * PT_PER_PX;
  if (widthOverflowPt > 0 || heightOverflowPt > 0) {
    const directions = [];
    if (widthOverflowPt > 0) directions.push(`${widthOverflowPt.toFixed(1)}pt horizontally`);
    if (heightOverflowPt > 0) directions.push(`${heightOverflowPt.toFixed(1)}pt vertically`);
    const reminder = heightOverflowPt > 0 ? ' (Remember: leave 0.5" margin at bottom of slide)' : '';
    errors.push(`HTML content overflows body by ${directions.join(' and ')}${reminder}`);
  }
  return { ...bodyDimensions, errors };
}

function validateDimensions(bodyDimensions, pres) {
  const errors = [];
  const widthInches = bodyDimensions.width / PX_PER_IN;
  const heightInches = bodyDimensions.height / PX_PER_IN;
  if (pres.presLayout) {
    const layoutWidth = pres.presLayout.width / EMU_PER_IN;
    const layoutHeight = pres.presLayout.height / EMU_PER_IN;
    if (Math.abs(layoutWidth - widthInches) > 0.1 || Math.abs(layoutHeight - heightInches) > 0.1) {
      errors.push(
        `HTML dimensions (${widthInches.toFixed(1)}" × ${heightInches.toFixed(1)}") ` +
        `don't match presentation layout (${layoutWidth.toFixed(1)}" × ${layoutHeight.toFixed(1)}")`
      );
    }
  }
  return errors;
}

// The runs of a text item, in order: paragraphs hold lines, lines hold runs.
function textRuns(item) {
  const runs = [];
  for (const paragraph of item.paragraphs || []) {
    for (const line of paragraph.lines || []) {
      for (const run of line.runs || []) runs.push(run);
    }
  }
  return runs;
}

// The lowest point a text item covers on the slide, in px: its box's bottom,
// or for a turned box (rotate set) the bottom of its turned extent.
function textBottomPx(item) {
  if (!item.rotate) return item.y + item.h;
  const radians = item.rotate * Math.PI / 180;
  const halfHeight = (Math.abs(item.w * Math.sin(radians)) + Math.abs(item.h * Math.cos(radians))) / 2;
  return item.y + item.h / 2 + halfHeight;
}

function validateTextBoxPosition(model, bodyDimensions) {
  const errors = [];
  const slideHeightInches = bodyDimensions.height / PX_PER_IN;
  for (const item of model.items) {
    if (item.kind !== 'text') continue;
    const runs = textRuns(item);
    const fontSize = runs.reduce((largest, run) => Math.max(largest, (run.sizePx || 0) * PT_PER_PX), 0);
    const bottomEdge = textBottomPx(item) / PX_PER_IN;
    const distanceFromBottom = slideHeightInches - bottomEdge;
    if (fontSize > 12 && distanceFromBottom < MIN_BOTTOM_MARGIN_IN) {
      const text = runs.map((run) => run.text || '').join('');
      const textPrefix = text.substring(0, 50) + (text.length > 50 ? '...' : '');
      errors.push(
        `Text box "${textPrefix}" ends too close to bottom edge ` +
        `(${distanceFromBottom.toFixed(2)}" from bottom, minimum ${MIN_BOTTOM_MARGIN_IN}" required)`
      );
    }
  }
  return errors;
}

function reportValidation(validationErrors, bypassValidation) {
  if (!validationErrors.length) return;
  const errorMessage = validationErrors.length === 1
    ? validationErrors[0]
    : `Multiple validation errors found:\n${validationErrors.map((e, i) => `  ${i + 1}. ${e}`).join('\n')}`;
  if (bypassValidation) {
    console.warn('[html2pptx] validation errors bypassed (slide will still emit):\n' + errorMessage);
  } else {
    throw new Error(errorMessage);
  }
}

// ─── summary ───────────────────────────────────────────────────────────
// `pseudoElements` is how many ::before, ::after and ::marker pseudo.mjs read,
// and how many of them the snapshot walked or drew with its list item (a
// pseudo-element inside a picture, an <svg>'s, is in that picture instead).
function summarise(model, captures, preprocessResult, animations, pseudoData) {
  const kinds = {};
  let pictures = 0;
  let skippedPictures = 0;
  for (const item of model.items) {
    kinds[item.kind] = (kinds[item.kind] || 0) + 1;
    if (item.kind !== 'image') continue;
    if (pictureData(item, captures)) pictures += 1;
    else skippedPictures += 1;
  }
  return {
    bgTransferred: preprocessResult && typeof preprocessResult === 'object'
      ? preprocessResult.bgTransferred
      : null,
    animations,
    elements: model.stats.elements,
    pseudoElements: { read: pseudoData.count, walked: model.stats.pseudoElements },
    kinds,
    pictures,
    skippedPictures,
    captures: model.captures.length,
    captureFailures: model.captures.filter((capture) => !captures.has(capture.id)).length,
  };
}

// ─── the slide ─────────────────────────────────────────────────────────
async function renderSlide(htmlFile, pres, options = {}) {
  const {
    tmpDir = process.env.TMPDIR || '/tmp',
    bypassValidation = false,
    target = 'pptx',
  } = options;

  try {
    const sources = await loadPageSources();
    // The snapshot reads the slide root's ground from body, so the background
    // transfer is the default preprocess; only an explicit null skips it.
    const preProcessSource = options.preProcessSource === undefined
      ? sources.bgTransfer
      : options.preProcessSource;
    const browser = await chromium.launch(launchOptions(tmpDir));
    const filePath = path.isAbsolute(htmlFile) ? htmlFile : path.join(process.cwd(), htmlFile);
    let bodyDimensions;
    let model;
    let preprocessResult;
    let animations;
    let pseudoData;
    let captures;
    try {
      const page = await browser.newPage({ viewport: SLIDE_VIEWPORT, deviceScaleFactor: DEVICE_SCALE_FACTOR });
      forwardConsole(page);
      await page.goto(`file://${filePath}`);
      animations = await settle(page, sources);
      preprocessResult = await runPreprocess(page, preProcessSource);
      // The background transfer writes body's inline style, which starts any
      // transition a deck declares on it; finish that too before reading.
      await finishAnimations(page, sources);
      bodyDimensions = await readBodyDimensions(page, sources);
      // Read from the settled page the snapshot reads, just before it.
      pseudoData = await sources.readPseudoElements(page);
      model = await page.evaluate(sources.snapshotOf(pseudoData));
      // Capture id -> data: PNG for the targets the model names in model.captures,
      // taken from this page as the snapshot left it. A target without an entry
      // is a failed capture: its picture is skipped.
      captures = await captureAll(page, model.captures);
    } finally {
      await browser.close();
    }

    reportValidation([
      ...bodyDimensions.errors,
      ...validateDimensions(bodyDimensions, pres),
      ...validateTextBoxPosition(model, bodyDimensions),
    ], bypassValidation);

    const slide = emitSlide(pres, model, captures, { target });
    return { slide, summary: summarise(model, captures, preprocessResult, animations, pseudoData) };
  } catch (error) {
    if (!error.message.startsWith(htmlFile)) {
      throw new Error(`${htmlFile}: ${error.message}`);
    }
    throw error;
  }
}

module.exports = { renderSlide };
