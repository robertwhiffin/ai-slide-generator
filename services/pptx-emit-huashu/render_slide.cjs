'use strict';
// The snapshot engine, one slide at a time:
//
//   1. load and settle   networkidle, every font face the text asks for loaded
//                        (pageFontsSettled), the canvas wait, then every
//                        animation finished, so a fade-in exports settled, and
//                        the fonts waited for again: an animation's end state
//                        can set text in a face nothing had asked for;
//   2. preprocess        PREPROCESS_SOURCE (preprocess.mjs): the slide root's
//                        ground onto body, nothing that moves layout;
//   3. validate          body overflow, the layout's size and text too near
//                        the bottom edge;
//   4. pseudo-elements   pseudo.mjs: every ::before, ::after and list item
//                        ::marker, read from Node through the DevTools
//                        protocol, read-only; nothing is inserted into the
//                        page for them (ruling R8);
//   5. snapshot          SNAPSHOT_SOURCE: one read-only page.evaluate of what
//                        step 4 read, which returns the slide model (snapshot.mjs),
//                        checked in Node before any use (model_check.cjs): the
//                        slide's realm built it, so what slide script made of it
//                        is dropped and counted (ruling R12d);
//   6. capture           capture.cjs: an element-isolated 2x screenshot of each
//                        capture target the model names, from the same page;
//   7. reference         the page's rendered text, read once every capture is
//                        taken, so it changes no picture (pageRenderedText);
//   8. emit              emit_model.cjs writes the model to a pptxgenjs slide;
//   9. checks            text_check.cjs: the text-loss line when the model
//                        lacks a word of the reference, then the slide's
//                        summary line, both on stderr (spec §6).
//
// renderSlide(htmlFile, pres, { bypassValidation, target, tmpDir })
//   -> { slide, summary }
// Each slide that renders logs
//   [html2pptx] text missing: <json array>   when a word is missing, then
//   [html2pptx] slide summary <json>         always, the summary on one line,
// which pptx_from_html_huashu.py echoes and the export fidelity harness reads
// (scripts/export_fidelity/run.py export_pptx). A slide that fails logs
// neither.
// target is the renderer the deck is written for, 'pptx' (the default) or
// 'gslides': emit_model.cjs writes the few constructs the two place apart
// for it (emit_text.cjs writtenParagraphs, emit_typography.cjs fontSizePt).
// emit_deck.mjs attaches the speaker notes to the returned `slide`.

const path = require('path');
const { chromium } = require('playwright');
const { captureAll } = require('./capture.cjs');
const { emitSlide, pictureData } = require('./emit_model.cjs');
const { logJson, oneLine } = require('./log_line.cjs');
const { checkModel, dropLine } = require('./model_check.cjs');
const { textLossLine } = require('./text_check.cjs');

const PT_PER_PX = 0.75;
const PX_PER_IN = 96;
const EMU_PER_IN = 914400;

// The slide's own size in CSS px. Device scale 2 changes no layout; it makes
// every screenshot of the page (captures) twice the box.
const SLIDE_VIEWPORT = { width: 1280, height: 720 };
const DEVICE_SCALE_FACTOR = 2;

const NETWORK_IDLE_TIMEOUT_MS = 4000;
const FONTS_READY_TIMEOUT_MS = 5000;
// How many times the font wait reads the faces again after one started
// loading: each round waits for document.fonts.ready, all within
// FONTS_READY_TIMEOUT_MS.
const FONT_SETTLE_ROUNDS = 8;
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
// queryOne) and limits are their free names, and after the constants it is
// composed with. They are stringified, so they close over nothing here. Slide
// script has already run in this page by the time any of them fires, so none
// of them walks the DOM any other way.

function pageCanvasCount() {
  return queryAll('canvas').length;
}

// Every font face the slide's text uses has loaded. document.fonts.ready alone
// can resolve while one has yet to start: it settles on the loads in flight
// when it is read, and the layout asks for a face (a weight, a unicode-range
// subset) only once it lays out text that needs it. So each round forces the
// layout, through body's box, and the faces are settled once none is loading.
// A face that stays unloaded is one no text on the slide asks for (a Google
// Fonts sheet declares a latin-ext subset of every weight: measured, 8 of the
// corpus deck's 12 faces stay unloaded), so it is not waited for. The faces,
// their status and the ready promise are read through the pristine accessors:
// slide script can replace document.fonts, its iteration and a face's status.
// Resolves whether the faces settled within FONT_SETTLE_ROUNDS.
async function pageFontsSettled() {
  const dom = domAccess();
  const body = queryOne('body');
  for (let round = 0; round < FONT_SETTLE_ROUNDS; round++) {
    await dom.fontsReady();
    if (body) dom.clientRects(body);
    if (dom.loadingFontFaces() === 0) return true;
  }
  return false;
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

// The text-loss reference (text_check.cjs): body's innerText once every <svg>
// and <canvas> is hidden, whose text is in its picture, as the export fidelity
// harness reads it (render_truth.cjs). It runs once the captures are taken, so
// hiding them changes no picture. Each graphic is hidden by its style
// attribute, set through the pristine setAttribute: once hidden its own style
// no longer matters, and an !important inline display beats every author rule
// and the slide's settled animations; a transition the change starts (a
// display that transitions discretely) is finished straight away. One
// synchronous read, so no slide script (a mutation observer) runs between the
// hiding and the reading.
function pageRenderedText() {
  const dom = domAccess();
  const graphics = queryAll('svg, canvas');
  for (let index = 0; index < graphics.length; index++) {
    dom.setAttribute(graphics[index], 'style', 'display: none !important');
  }
  pageFinishAnimations();
  const body = queryOne('body');
  return body ? String(dom.innerText(body)) : '';
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
        // `helpers` are the page functions `pageFunction` calls by name, and
        // `constants` the values it reads by name, each written as a const.
        const withDomAccess = (pageFunction, helpers = [], constants = {}) => `(() => {
  const DOM_ACCESS_LOG_PREFIX = '[html2pptx]';
${access.DOM_ACCESS_SOURCE}
${Object.entries(constants).map(([name, value]) => `  const ${name} = ${JSON.stringify(value)};`).join('\n')}
${helpers.map((helper) => helper.toString()).join('\n')}
  return (${pageFunction.toString()})();
})()`;
        return {
          canvasCount: withDomAccess(pageCanvasCount),
          canvasesReady: withDomAccess(pageCanvasesReady),
          finishAnimations: withDomAccess(pageFinishAnimations),
          fontsSettled: withDomAccess(pageFontsSettled, [], { FONT_SETTLE_ROUNDS }),
          bodyDimensions: withDomAccess(pageBodyDimensions),
          renderedText: withDomAccess(pageRenderedText, [pageFinishAnimations]),
          preprocess: preprocess.PREPROCESS_SOURCE,
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
// Page chatter stays on stdout. Slide script can log anything, so each message
// is written on one line (log_line.cjs oneLine), behind "Browser console:": no
// line break in it can start a line of the sidecar's own (a slide summary, the
// __HUASHU_RESULT__ failure list).
function forwardConsole(page) {
  page.on('console', (msg) => {
    const text = oneLine(msg.text());
    if (text.startsWith('[preprocess]') || text.startsWith('[html2pptx]')) {
      console.error(`Browser console: ${text}`);
      return;
    }
    console.log(`Browser console: ${text}`);
  });
}

// ─── settle ────────────────────────────────────────────────────────────
// pageFontsSettled, bounded here, not in the page: a font set that never
// reports ready, or a face that never finishes loading, must cost seconds, not
// the export. Either is said on stderr, since the slide is then read with the
// fonts it has.
async function waitForFonts(page, sources) {
  let timer;
  try {
    const settled = await Promise.race([
      page.evaluate(sources.fontsSettled),
      new Promise((resolve) => { timer = setTimeout(() => resolve(null), FONTS_READY_TIMEOUT_MS); }),
    ]);
    if (settled !== true) {
      console.error(`[html2pptx] the slide's fonts did not finish loading within ${FONTS_READY_TIMEOUT_MS} ms — continuing`);
    }
  } catch (e) {
    console.error(`[html2pptx] document.fonts.ready failed: ${oneLine(e.message)} — continuing`);
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
    console.error(`[html2pptx] finishing animations failed: ${oneLine(e.message)} — continuing`);
    return { finished: 0, cancelled: 0, unfinished: 0 };
  }
}

async function settle(page, sources) {
  try {
    await page.waitForLoadState('networkidle', { timeout: NETWORK_IDLE_TIMEOUT_MS });
  } catch (e) { /* ignore — some slides legitimately keep a long-poll open */ }
  await waitForFonts(page, sources);
  await waitForCanvases(page, sources);
  return finishAnimations(page, sources);
}

// ─── preprocess ────────────────────────────────────────────────────────
async function runPreprocess(page, sources) {
  try {
    const result = await page.evaluate(sources.preprocess);
    if (result && typeof result === 'object') {
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
    console.error(`[preprocess] failed: ${oneLine(e.message)} — continuing without`);
    return null;
  }
}

// ─── validation ────────────────────────────────────────────────────────
// Three authoring checks, with the message texts the export has always given:
// body overflowing by more than TELLR_OVERFLOW_TOLERANCE_PX, a body whose size
// is not the presentation layout's, and text over 12 pt too near the bottom.
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

// An error can quote the slide's own text (a text box's first words), so each
// is one line (log_line.cjs oneLine); the message's own line breaks part them.
function reportValidation(validationErrors, bypassValidation) {
  if (!validationErrors.length) return;
  const errors = validationErrors.map(oneLine);
  const errorMessage = errors.length === 1
    ? errors[0]
    : `Multiple validation errors found:\n${errors.map((e, i) => `  ${i + 1}. ${e}`).join('\n')}`;
  if (bypassValidation) {
    console.warn('[html2pptx] validation errors bypassed (slide will still emit):\n' + errorMessage);
  } else {
    throw new Error(errorMessage);
  }
}

// ─── checks ────────────────────────────────────────────────────────────
// The page's rendered text (pageRenderedText), or null when it could not be
// read: the slide still exports, unchecked, and the log says so.
async function readRenderedText(page, sources) {
  try {
    const text = await page.evaluate(sources.renderedText);
    return typeof text === 'string' ? text : null;
  } catch (e) {
    console.error(`[html2pptx] reading the slide's rendered text failed: ${oneLine(e.message)} — its text is not checked for loss`);
    return null;
  }
}

// The wall time, in ms to the microsecond, since `start` (performance.now()).
function elapsedMs(start) {
  return Math.round((performance.now() - start) * 1000) / 1000;
}

// ─── summary ───────────────────────────────────────────────────────────
// `pseudoElements` is how many ::before, ::after and ::marker pseudo.mjs read,
// and how many of them the snapshot walked or drew with its list item (a
// pseudo-element inside a picture, an <svg>'s, is in that picture instead).
// `text`, `shapes`, `lines` and `tables` count the model's items of each kind,
// as `kinds` does (`pictures` counts the images written, `skippedPictures`
// those that had no picture). `captureMs` is the wall time of the slide's
// captures, 0 when it has none: a clock reading, so it goes to the log alone,
// never into the deck. `hiddenText` is the words the page reads that the
// slide does not show (snapshot.mjs model.reference), which the text-loss
// check leaves out, and `target` the renderer the deck is written for.
// `modelDrops` is how many captures, items and model fields Node could not
// take from the page as the snapshot writes them (model_check.cjs), 0 for a
// slide whose script shaped none of its model.
//   readings  {preprocessResult, animations, pseudoData, captureMs, target,
//             dropped}: what the slide's render read besides the model.
function summarise(model, captures, readings) {
  const { preprocessResult, animations, pseudoData, captureMs, target, dropped } = readings;
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
    text: kinds.text || 0,
    shapes: kinds.shape || 0,
    lines: kinds.line || 0,
    tables: kinds.table || 0,
    captureMs,
    hiddenText: model.reference.hiddenText,
    target,
    modelDrops: dropped.items + dropped.captures + dropped.fields,
  };
}

// The slide's check lines on stderr (spec §6): what of the page's rendered
// text the model lacks, when anything (text_check.cjs), then its summary.
function reportChecks(summary, model, renderedText) {
  if (renderedText !== null) {
    const missing = textLossLine(renderedText, model.items, summary.hiddenText);
    if (missing) console.error(missing);
  }
  console.error('[html2pptx] slide summary ' + logJson(summary));
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
    const browser = await chromium.launch(launchOptions(tmpDir));
    const filePath = path.isAbsolute(htmlFile) ? htmlFile : path.join(process.cwd(), htmlFile);
    let bodyDimensions;
    let model;
    let preprocessResult;
    let animations;
    let pseudoData;
    let captures;
    let captureMs;
    let renderedText;
    let dropped;
    try {
      const page = await browser.newPage({ viewport: SLIDE_VIEWPORT, deviceScaleFactor: DEVICE_SCALE_FACTOR });
      forwardConsole(page);
      await page.goto(`file://${filePath}`);
      animations = await settle(page, sources);
      preprocessResult = await runPreprocess(page, sources);
      // The background transfer writes body's inline style, which starts any
      // transition a deck declares on it; finish that too before reading.
      await finishAnimations(page, sources);
      // A finished animation can set text in a face nothing had asked for yet
      // (its end state's font-family or weight), which loads only now.
      await waitForFonts(page, sources);
      bodyDimensions = await readBodyDimensions(page, sources);
      // Read from the settled page the snapshot reads, just before it.
      pseudoData = await sources.readPseudoElements(page);
      // Checked before the captures and everything after use any of it.
      ({ model, dropped } = checkModel(await page.evaluate(sources.snapshotOf(pseudoData))));
      const drops = dropLine(dropped);
      if (drops) console.error(drops);
      // Capture id -> data: PNG for the targets the model names in model.captures,
      // taken from this page as the snapshot left it. A target without an entry
      // is a failed capture: its picture is skipped.
      const captureStart = performance.now();
      captures = await captureAll(page, model.captures);
      captureMs = model.captures.length ? elapsedMs(captureStart) : 0;
      // Last, once every picture is taken: the read hides the graphics.
      renderedText = await readRenderedText(page, sources);
    } finally {
      await browser.close();
    }

    reportValidation([
      ...bodyDimensions.errors,
      ...validateDimensions(bodyDimensions, pres),
      ...validateTextBoxPosition(model, bodyDimensions),
    ], bypassValidation);

    const slide = emitSlide(pres, model, captures, { target });
    const summary = summarise(model, captures, {
      preprocessResult, animations, pseudoData, captureMs, target, dropped,
    });
    reportChecks(summary, model, renderedText);
    return { slide, summary };
  } catch (error) {
    if (!error.message.startsWith(htmlFile)) {
      throw new Error(`${htmlFile}: ${error.message}`);
    }
    throw error;
  }
}

module.exports = { renderSlide };
