'use strict';
// The snapshot engine, one slide at a time:
//
//   1. load and settle   networkidle, every font face the text asks for loaded
//                        (pageFontsSettled), the canvas wait, then every
//                        animation finished, so a fade-in exports settled, and
//                        the fonts waited for again: an animation's end state
//                        can set text in a face nothing had asked for;
//   2. preprocess        PREPROCESS_SOURCE (preprocess.mjs): the slide root's
//                        ground onto body (an image ground's colour alone:
//                        the ground stays on the root, captured as the
//                        slide's background picture), nothing that moves layout;
//   3. validate          body overflow, the layout's size and text too near
//                        the bottom edge;
//   4. pseudo-elements   pseudo.mjs: every ::before, ::after and list item
//                        ::marker, read from Node through the DevTools
//                        protocol, read-only; nothing is inserted into the
//                        page for them;
//   5. snapshot          SNAPSHOT_SOURCE: one read-only page.evaluate of what
//                        step 4 read, which returns the slide model (snapshot.mjs),
//                        checked in Node before any use (model_check.cjs): the
//                        slide's realm built it, so what slide script made of it
//                        is dropped and counted;
//   6. capture           capture.cjs: an element-isolated 2x screenshot of each
//                        capture target the model names, from the same page
//                        (the slide root's image ground among them);
//   7. reference         the page's rendered text, read once every capture is
//                        taken, so it changes no picture (pageRenderedText);
//   8. emit              emit_model.cjs writes the model to a pptxgenjs slide;
//   9. checks            text_check.cjs: the text-loss line when the model
//                        lacks a word of the reference, then the slide's
//                        summary line, both on stderr (spec §6).
//
// Each slide has a browser and a browser context of its own, whose every
// request the request guard decides (request_guard.cjs): the page reads its
// slide's own file, data: and blob: URLs and the hosts the slide CSP allows
// (`requestHosts`, emit_deck.mjs), and nothing else. A slide whose page
// navigates away from it is stopped at once and fails, and so is a slide still
// unread at SLIDE_DEADLINE_MS (its page blocked by its own script, or its
// browser no longer answering): its browser is closed, nothing it read is
// exported, and the deck goes on. A browser that does not close within
// BROWSER_CLOSE_TIMEOUT_MS is killed.
//
// renderSlide(htmlFile, pres, { bypassValidation, target, tmpDir, requestHosts, slideIndex })
//   -> { slide, summary }
// A slide it cannot export throws: the error's message for the slide's failure
// entry, which goes to the user who exported the deck, and its `logMessage`,
// when it has one, for the log; one without it may hold the page's text.
// Each slide that renders logs
//   [html2pptx] text missing: {"slideIndex", "words"}   when a word is
//                                         missing: the slide and how many,
//   [html2pptx] slide summary <json>      always, the summary on one line,
// which pptx_from_html_huashu.py echoes into the app's log and the export
// fidelity harness reads (scripts/export_fidelity/run.py export_pptx). A slide
// that fails logs neither. The app's log is read outside Tellr's per-deck
// permissions, so no line holds a slide's own text: with the debug text on
// (log_line.cjs debugText), which no app sets, the summary adds its
// hiddenText and a second text-loss line names the words,
//   [html2pptx] text missing: <json array>,
// and every message below quotes what it is about.
// target is the renderer the deck is written for, 'pptx' (the default) or
// 'gslides': emit_model.cjs writes the few constructs the two draw apart
// for it (emit_text.cjs writtenParagraphs; emit_typography.cjs fontSizePt,
// the tracking, italic typefaces, synthetic bolds and hyphens of runOptions
// and runText; emit_dotted.cjs, a dotted line or outline), and the snapshot
// a native table's grid and its rounded corner fills (snapshot.mjs
// WHOLE_PIXEL_TABLES, CORNER_RUN_UNDER_PX).
// emit_deck.mjs attaches the speaker notes to the returned `slide`.

const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');
const { captureAll } = require('./capture.cjs');
const { emitSlide, pictureData } = require('./emit_model.cjs');
const { bounded, debugText, logJson, oneLine, pageText, DEBUG_TEXT_ENV } = require('./log_line.cjs');
const { checkModel, dropLine } = require('./model_check.cjs');
const { guardContext } = require('./request_guard.cjs');
const { lostWords, wordsOf, TEXT_MISSING_PREFIX } = require('./text_check.cjs');
const { EMU_PER_IN, PT_PER_PX, PX_PER_IN } = require('./units.cjs');

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
// How often the canvas wait reads the canvases again.
const CANVAS_POLL_MS = 100;
// How long one slide may take, from its browser's launch to its last read:
// every step of it, the launch, the browser context, the request guard's
// routing of it, the page and each read. A slide whose script blocks its page
// (a busy loop), or whose browser stops answering (seen of Chrome under the
// test suites' parallel load: a 12-slide deck sat after its third slide until
// the timeout), would hang every step after it, and the deck
// with it until the sidecar's timeout (180 s), losing every slide: at this it
// is stopped instead, its browser closed, and it fails alone. Measured on a
// dev Mac: the slowest slide of both corpora
// and of the long-off, dataviz-tpl18 and finance-off matrix decks takes 3.2 s
// (a Chart.js slide, its 2 s canvas settle), the median 1.0 s, and Apps
// renders a slide in about a Mac's time (25.3 s for the 28-slide long deck).
// The engine's own bounded waits add up to 26 s (network idle,
// the fonts before and after the animations, the canvases and their settle,
// one capture), so the deadline fails no slide those waits let through, slow
// and exported as far as it settled; and a deck with one blocked slide, its
// browser closed or killed within BROWSER_CLOSE_TIMEOUT_MS and
// BROWSER_KILL_TIMEOUT_MS after it, still has 140 s of the sidecar's 180 s
// for the rest.
const SLIDE_DEADLINE_MS = 30000;
// How long a slide's browser has to close once the slide is read or stopped,
// and its process then to end once killed. Measured on a dev Mac: a close
// takes 0.1 to 0.3 s, a kill 0.02 s. A browser that does not close in time
// (one stalled under load) is killed, so no slide's browser outlives it and no
// close holds up the deck (closeBrowser).
const BROWSER_CLOSE_TIMEOUT_MS = 5000;
const BROWSER_KILL_TIMEOUT_MS = 5000;
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
          // The snapshot page function applied to what pseudo.mjs read and to
          // the renderer the deck is written for: JSON is a JavaScript
          // expression, so each is an argument of the call.
          snapshotOf: (pseudoData, renderer) =>
            `${snapshot.SNAPSHOT_SOURCE}(${JSON.stringify(pseudoData)}, ${JSON.stringify(renderer)})`,
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
// On Linux glyphs are laid out unhinted (--font-render-hinting=none): headless
// Chromium there hints outlines fully, which rounds every glyph's advance, and
// measured on Apps' Chromium a webfont line came out 0.95 to 1.08 of its width
// on a Mac; unhinted it is within 0.0004. Chrome on a Mac lays text out with
// CoreText, which the flag does not change (CALIBRATION.md N3).
// WebRTC sends no UDP but through a proxy, which the browser has none of
// (request_guard.cjs, WebRTC): Chrome takes the policy from
// --webrtc-ip-handling-policy, Playwright's Chromium from
// --force-webrtc-ip-handling-policy, each measured to send a local STUN
// listener nothing and ignoring the other flag, so both are passed.
const WEBRTC_POLICY = 'disable_non_proxied_udp';
function launchOptions(tmpDir) {
  const options = {
    env: { ...process.env, TMPDIR: tmpDir },
    args: [
      '--disable-gpu',
      `--webrtc-ip-handling-policy=${WEBRTC_POLICY}`,
      `--force-webrtc-ip-handling-policy=${WEBRTC_POLICY}`,
    ],
  };
  if (process.platform === 'darwin') {
    options.channel = 'chrome';
  } else {
    options.args.push(
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--font-render-hinting=none',
    );
  }
  return options;
}

// What a slide's page logs is its own text: the slide's script can log its
// words, under the engine's own prefix too, and the engine's page-side passes
// run in the page's realm, which builds what they say. So it reaches no log
// unless the debug text is on (log_line.cjs debugText), which no app sets:
// without it, once the slide has been read, one [html2pptx] page console line
// counts its messages by level (Playwright's console message type) and says
// how many carry the engine's prefix ([preprocess] or [html2pptx]); a slide
// that logged nothing says nothing.
//
// With the debug text on, [preprocess] and [html2pptx] lines, which report
// content leaving the deck, go to stderr, the only stream
// pptx_from_html_huashu.py echoes into the app log, and the rest of a page's
// chatter to stdout. Slide script can log anything, so each message is written
// on one line (log_line.cjs oneLine), behind "Browser console:": no line break
// in it can start a line of the sidecar's own (a slide summary, the
// __HUASHU_RESULT__ failure list). Each is cut at PAGE_MESSAGE_LIMIT
// characters, and a slide logs PAGE_MESSAGES_PER_SLIDE of them at most to
// each stream. Measured over the engine's suites, its longest page-side line
// is 249 characters (a slide with no root, preprocess.mjs, which names each of
// the body's section and article wrappers); a longer one keeps its first
// PAGE_MESSAGE_LIMIT characters and says how many it left out.
const PAGE_MESSAGE_LIMIT = 1000;
const PAGE_MESSAGES_PER_SLIDE = 100;
const ENGINE_PREFIXES = ['[preprocess]', '[html2pptx]'];

// Returns {report()}, which, once the slide has been read, logs its count line
// (debug text off), or says on each stream how many of the page's messages
// went past the bound (debug text on).
function forwardConsole(page) {
  const forwarding = debugText();
  const streams = {
    stderr: { write: (line) => console.error(line), left: PAGE_MESSAGES_PER_SLIDE, over: 0 },
    stdout: { write: (line) => console.log(line), left: PAGE_MESSAGES_PER_SLIDE, over: 0 },
  };
  const levels = Object.create(null);
  let messages = 0;
  let engine = 0;
  page.on('console', (msg) => {
    const text = String(msg.text());
    const engineLine = ENGINE_PREFIXES.some((prefix) => text.startsWith(prefix));
    if (!forwarding) {
      const level = String(msg.type());
      levels[level] = (levels[level] || 0) + 1;
      messages += 1;
      if (engineLine) engine += 1;
      return;
    }
    const stream = engineLine ? streams.stderr : streams.stdout;
    if (stream.left <= 0) {
      stream.over += 1;
      return;
    }
    stream.left -= 1;
    stream.write(`Browser console: ${bounded(text, PAGE_MESSAGE_LIMIT)}`);
  });
  return {
    report() {
      if (!forwarding) {
        if (!messages) return;
        const byLevel = Object.keys(levels).sort().map((level) => `${levels[level]} ${level}`).join(', ');
        console.error(`[html2pptx] page console: ${messages} message(s) (${byLevel}), ${engine} with the ` +
          `engine's prefix, not logged (${DEBUG_TEXT_ENV}=1 logs them)`);
        return;
      }
      for (const stream of Object.values(streams)) {
        if (!stream.over) continue;
        stream.write(`[html2pptx] page console: ${stream.over} more message(s) not logged: ` +
          `a slide logs ${PAGE_MESSAGES_PER_SLIDE} at most`);
      }
    },
  };
}

// ─── the slide's log ───────────────────────────────────────────────────
// What the reads of one slide say on stderr. A slide that is stopped (its page
// left the slide) has its browser closed under reads still under way, and
// what those say once it is gone is about no page at all, so it is dropped:
// none of it lands among the next slide's lines.
function slideLog() {
  let live = true;
  return {
    error(line) {
      if (live) console.error(line);
    },
    stop() {
      live = false;
    },
  };
}

// ─── settle ────────────────────────────────────────────────────────────
// pageFontsSettled, bounded here, not in the page: a font set that never
// reports ready, or a face that never finishes loading, must cost seconds, not
// the export. Either is said on stderr, since the slide is then read with the
// fonts it has.
async function waitForFonts(page, sources, log) {
  let timer;
  try {
    const settled = await Promise.race([
      page.evaluate(sources.fontsSettled),
      new Promise((resolve) => { timer = setTimeout(() => resolve(null), FONTS_READY_TIMEOUT_MS); }),
    ]);
    if (settled !== true) {
      log.error(`[html2pptx] the slide's fonts did not finish loading within ${FONTS_READY_TIMEOUT_MS} ms — continuing`);
    }
  } catch (e) {
    log.error(`[html2pptx] document.fonts.ready failed: ${pageText(e.message)} — continuing`);
  } finally {
    clearTimeout(timer);
  }
}

// Every <canvas> given a drawing buffer (Chart.js sizes its canvas when it
// first draws), bounded: a canvas that never gets one ends the wait at
// CANVAS_READY_TIMEOUT_MS, and the slide is read with its canvases as they
// are, which is said. The readiness is polled with page.evaluate, which the
// DevTools protocol runs whatever the page's CSP: page.waitForFunction
// evaluates its predicate inside the page, which the slide CSP (no
// 'unsafe-eval') refuses at once, so the wait waited for nothing. A read that
// fails (its page function threw) says its message by its length alone
// (log_line.cjs pageText).
async function waitForCanvases(page, sources, log) {
  const canvasCount = Number(await page.evaluate(sources.canvasCount));
  if (!(canvasCount > 0)) return;
  const deadline = Date.now() + CANVAS_READY_TIMEOUT_MS;
  try {
    let ready = (await page.evaluate(sources.canvasesReady)) === true;
    while (!ready && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, CANVAS_POLL_MS));
      ready = (await page.evaluate(sources.canvasesReady)) === true;
    }
    if (!ready) {
      log.error(`[html2pptx] canvases: ${canvasCount} canvas(es), not every one with a drawing buffer ` +
        `within ${CANVAS_READY_TIMEOUT_MS} ms — continuing`);
    }
  } catch (error) {
    log.error(`[html2pptx] the canvas wait failed: ${pageText(error && error.message)} — continuing`);
  }
  await new Promise((resolve) => setTimeout(resolve, CANVAS_SETTLE_MS));
}

async function finishAnimations(page, sources, log) {
  try {
    return await page.evaluate(sources.finishAnimations);
  } catch (e) {
    log.error(`[html2pptx] finishing animations failed: ${pageText(e.message)} — continuing`);
    return { finished: 0, cancelled: 0, unfinished: 0 };
  }
}

async function settle(page, sources, log) {
  try {
    await page.waitForLoadState('networkidle', { timeout: NETWORK_IDLE_TIMEOUT_MS });
  } catch (e) { /* ignore — some slides legitimately keep a long-poll open */ }
  await waitForFonts(page, sources, log);
  await waitForCanvases(page, sources, log);
  return finishAnimations(page, sources, log);
}

// ─── preprocess ────────────────────────────────────────────────────────
async function runPreprocess(page, sources, log) {
  try {
    const result = await page.evaluate(sources.preprocess);
    if (result && typeof result === 'object') {
      // No slide root means no background transfer, so this slide exports on the
      // untouched body default (white): indistinguishable in the .pptx from a
      // locator regression. The page-side '[preprocess] no slide root' line
      // carries the shape that was actually seen.
      if (result.bgTransferred === 'no-root') {
        log.error('[preprocess] slide-root locator resolved NO root: this slide ' +
                  'exports with the untouched body background (white).');
      }
    }
    return result;
  } catch (e) {
    log.error(`[preprocess] failed: ${pageText(e.message)} — continuing without`);
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
      const where = `ends too close to bottom edge ` +
        `(${distanceFromBottom.toFixed(2)}" from bottom, minimum ${MIN_BOTTOM_MARGIN_IN}" required)`;
      errors.push({
        message: `Text box "${textPrefix}" ${where}`,
        logged: `Text box (${text.length} characters) ${where}`,
      });
    }
  }
  return errors;
}

// A validation error is a message, or {message, logged}: what the slide's
// failure says, and what the log says of it. The text box one quotes the box's
// first words, which the log names by their length alone, but with the debug
// text on (log_line.cjs debugText). Each is one line (log_line.cjs oneLine);
// the message's own line breaks part them.
function reportValidation(validationErrors, bypassValidation) {
  if (!validationErrors.length) return;
  const errors = validationErrors.map((error) => (
    typeof error === 'string' ? { message: error, logged: error } : error
  ));
  const joined = (texts) => (texts.length === 1
    ? texts[0]
    : `Multiple validation errors found:\n${texts.map((e, i) => `  ${i + 1}. ${e}`).join('\n')}`);
  const errorMessage = joined(errors.map((error) => oneLine(error.message)));
  const logged = debugText() ? errorMessage : joined(errors.map((error) => oneLine(error.logged)));
  if (bypassValidation) {
    console.warn('[html2pptx] validation errors bypassed (slide will still emit):\n' + logged);
  } else {
    const error = new Error(errorMessage);
    error.logMessage = logged;
    throw error;
  }
}

// ─── checks ────────────────────────────────────────────────────────────
// The page's rendered text (pageRenderedText), or null when it could not be
// read: the slide still exports, unchecked, and the log says so.
async function readRenderedText(page, sources, log) {
  try {
    const text = await page.evaluate(sources.renderedText);
    return typeof text === 'string' ? text : null;
  } catch (e) {
    log.error(`[html2pptx] reading the slide's rendered text failed: ${pageText(e.message)} — its text is not checked for loss`);
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
// never into the deck. `hiddenWords` counts the words the page reads that the
// slide does not show (snapshot.mjs model.reference.hiddenText), which the
// text-loss check leaves out; with the debug text on (log_line.cjs debugText)
// `hiddenText` is those words. `target` is the renderer the deck is written for.
// `modelDrops` is how many captures, items and model fields Node could not
// take from the page as the snapshot writes them (model_check.cjs), 0 for a
// slide whose script shaped none of its model. `blockedRequests` is how many
// requests and WebSockets of the slide's page the request guard aborted, and
// `closedPopups` how many popups it closed (request_guard.cjs): 0 and 0 for a
// slide that asks for nothing but its own file and the CSP's hosts.
//   readings  {preprocessResult, animations, pseudoData, captureMs, target,
//             dropped, requests}: what the slide's render read besides the model.
function summarise(model, captures, readings) {
  const { preprocessResult, animations, pseudoData, captureMs, target, dropped, requests } = readings;
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
    hiddenWords: wordsOf(model.reference.hiddenText).length,
    ...(debugText() ? { hiddenText: model.reference.hiddenText } : {}),
    target,
    modelDrops: dropped.items + dropped.captures + dropped.fields,
    blockedRequests: requests.blockedRequests,
    closedPopups: requests.closedPopups,
  };
}

// The slide's check lines on stderr (spec §6): how many words of the page's
// rendered text the model lacks, when any (text_check.cjs lostWords), and on
// which slide (`slideIndex`, its index in the deck), the words themselves with
// the debug text on; then its summary.
function reportChecks(summary, model, renderedText, slideIndex) {
  if (renderedText !== null) {
    const lost = lostWords(renderedText, model.items, model.reference.hiddenText);
    if (lost.length) {
      console.error(TEXT_MISSING_PREFIX + logJson({ slideIndex, words: lost.length }));
      if (debugText()) console.error(TEXT_MISSING_PREFIX + logJson(lost));
    }
  }
  console.error('[html2pptx] slide summary ' + logJson(summary));
}

// ─── the slide ─────────────────────────────────────────────────────────
// An error whose message holds no text of the slide's own, so the log says it
// whole (emit_deck.mjs, its FAIL line): `logMessage`. Any other error's
// message may be the page's, and the log says it by its length alone.
function loggedWhole(error) {
  error.logMessage = error.message;
  return error;
}

// The error a slide whose page navigated away from it fails with. The URL is
// the page's, so only its scheme is said.
function leftSlideError(scheme) {
  return loggedWhole(new Error(
    `the slide's page navigated away from the slide (to a ${scheme}: URL), so it is not ` +
    'exported: an export reads nothing but its own slide'
  ));
}

// Everything the render reads from the slide's page, in order.
async function readPage(page, slideUrl, sources, target, log) {
  await page.goto(slideUrl);
  const animations = await settle(page, sources, log);
  const preprocessResult = await runPreprocess(page, sources, log);
  // The background transfer writes body's inline style, which starts any
  // transition a deck declares on it; finish that too before reading.
  await finishAnimations(page, sources, log);
  // A finished animation can set text in a face nothing had asked for yet
  // (its end state's font-family or weight), which loads only now.
  await waitForFonts(page, sources, log);
  const bodyDimensions = await readBodyDimensions(page, sources);
  // Read from the settled page the snapshot reads, just before it.
  const pseudoData = await sources.readPseudoElements(page, log);
  // Checked before the captures and everything after use any of it.
  const { model, dropped } = checkModel(await page.evaluate(sources.snapshotOf(pseudoData, { target })));
  const drops = dropLine(dropped);
  if (drops) log.error(drops);
  // Capture id -> data: PNG for the targets the model names in model.captures,
  // taken from this page as the snapshot left it. A target without an entry
  // is a failed capture: its picture is skipped.
  const captureStart = performance.now();
  const captures = await captureAll(page, model.captures, log);
  const captureMs = model.captures.length ? elapsedMs(captureStart) : 0;
  // Last, once every picture is taken: the read hides the graphics.
  const renderedText = await readRenderedText(page, sources, log);
  return {
    animations, preprocessResult, bodyDimensions, pseudoData, model, dropped, captures, captureMs, renderedText,
  };
}

// The error a slide past SLIDE_DEADLINE_MS fails with: what it was waiting for,
// its page's reads (`reading`) or its browser, which had not yet opened its page.
function pastDeadlineError(reading) {
  return loggedWhole(new Error(
    `the slide did not finish within ${SLIDE_DEADLINE_MS / 1000} s, so it is not exported: ` +
    (reading ? 'its page may be blocked by its own script' : 'its browser stopped answering')
  ));
}

// Whether `promise` settles, either way, within `milliseconds`.
async function settlesWithin(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([
      promise.then(() => true, () => true),
      new Promise((resolve) => { timer = setTimeout(() => resolve(false), milliseconds); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

// The process Playwright launched for `browser`, {kill()} (which kills its
// process group and resolves once it has exited), or null. Playwright's API
// gives a launched browser no handle on its process, so it is read from the
// server-side browser behind the client one, through the in-process
// connection's toImpl (Playwright 1.59.1, which the committed
// node_modules.tar.gz pins). A browser without one is left to Playwright's own
// close, which kills it 30 s on; until it is gone its pipes keep node, and so
// the deck, from ending.
function browserProcessOf(browser) {
  try {
    const launched = browser._connection.toImpl(browser).options.browserProcess;
    return launched && typeof launched.kill === 'function' ? launched : null;
  } catch (error) {
    return null;
  }
}

// The slide's browser closed, within BROWSER_CLOSE_TIMEOUT_MS, or else its
// process killed, which is said: a browser stalled under load can take
// Playwright's own close 30 s, and one that answers nothing, longer. Never
// waits longer than both bounds.
async function closeBrowser(browser) {
  if (await settlesWithin(Promise.resolve().then(() => browser.close()), BROWSER_CLOSE_TIMEOUT_MS)) return;
  const launched = browserProcessOf(browser);
  const killed = launched !== null &&
    await settlesWithin(Promise.resolve().then(() => launched.kill()), BROWSER_KILL_TIMEOUT_MS);
  console.error(`[html2pptx] the slide's browser did not close within ${BROWSER_CLOSE_TIMEOUT_MS / 1000} s: ` +
    (killed ? 'its process was killed' : "its process could not be killed, so it is left to Playwright's close"));
}

// The slide's page read in a browser of its own, its requests guarded
// (request_guard.cjs), and the browser closed whatever happens. Each step of
// it is raced against the slide's stop: a page that leaves the slide, or a
// slide not done at SLIDE_DEADLINE_MS, whatever step it is waiting on, stops
// it at once: the slide fails, and what was still under way is abandoned with
// the browser, closed then (closeBrowser, bounded). A browser that launches
// only once the slide has stopped is closed as soon as it has; a launch is
// itself bounded by the deadline, past which Playwright kills what it started.
async function readSlide(slideUrl, sources, { tmpDir, target, requestHosts }) {
  const log = slideLog();
  let stopSlide;
  const stopped = new Promise((resolve, reject) => { stopSlide = reject; });
  stopped.catch(() => {});
  let isStopped = false;
  const stop = (error) => {
    if (isStopped) return;
    isStopped = true;
    log.stop();
    stopSlide(error);
  };
  let reading = false;
  const deadline = setTimeout(() => stop(pastDeadlineError(reading)), SLIDE_DEADLINE_MS);
  // A step that loses the race goes on unawaited, so its failure is no one's.
  const step = (promise) => {
    promise.catch(() => {});
    return Promise.race([promise, stopped]);
  };
  const launching = chromium.launch({ ...launchOptions(tmpDir), timeout: SLIDE_DEADLINE_MS });
  let browser = null;
  try {
    // A browser that cannot launch says so whole: no page has been loaded yet.
    browser = await step(launching.catch((error) => { throw loggedWhole(error); }));
    const context = await step(browser.newContext({ viewport: SLIDE_VIEWPORT, deviceScaleFactor: DEVICE_SCALE_FACTOR }));
    const guard = await step(guardContext(context, slideUrl, requestHosts, (scheme) => stop(leftSlideError(scheme))));
    const page = await step(context.newPage());
    guard.watch(page);
    const pageConsole = forwardConsole(page);
    reading = true;
    const readings = await step(readPage(page, slideUrl, sources, target, log));
    pageConsole.report();
    return { ...readings, requests: guard.counts() };
  } finally {
    clearTimeout(deadline);
    log.stop();
    if (browser) await closeBrowser(browser);
    else launching.then((late) => closeBrowser(late), () => {});
  }
}

async function renderSlide(htmlFile, pres, options = {}) {
  const {
    tmpDir = process.env.TMPDIR || '/tmp',
    bypassValidation = false,
    target = 'pptx',
    requestHosts = new Map(),
    slideIndex = null,
  } = options;

  try {
    // The engine's own modules, read from disk: their failure holds no page text.
    const sources = await loadPageSources().catch((error) => { throw loggedWhole(error); });
    const filePath = path.isAbsolute(htmlFile) ? htmlFile : path.join(process.cwd(), htmlFile);
    const slideUrl = pathToFileURL(filePath).href;
    const readings = await readSlide(slideUrl, sources, { tmpDir, target, requestHosts });
    const { bodyDimensions, model, captures, renderedText } = readings;

    reportValidation([
      ...bodyDimensions.errors,
      ...validateDimensions(bodyDimensions, pres),
      ...validateTextBoxPosition(model, bodyDimensions),
    ], bypassValidation);

    const slide = emitSlide(pres, model, captures, { target });
    const summary = summarise(model, captures, { ...readings, target });
    reportChecks(summary, model, renderedText, slideIndex);
    return { slide, summary };
  } catch (error) {
    if (error.message.startsWith(htmlFile)) throw error;
    const named = new Error(`${htmlFile}: ${error.message}`);
    if (typeof error.logMessage === 'string') named.logMessage = error.logMessage;
    throw named;
  }
}

module.exports = {
  launchOptions,
  renderSlide,
  PAGE_MESSAGE_LIMIT,
  PAGE_MESSAGES_PER_SLIDE,
  SLIDE_DEADLINE_MS,
  BROWSER_CLOSE_TIMEOUT_MS,
  BROWSER_KILL_TIMEOUT_MS,
  NETWORK_IDLE_TIMEOUT_MS,
  FONTS_READY_TIMEOUT_MS,
  CANVAS_READY_TIMEOUT_MS,
  CANVAS_SETTLE_MS,
};
