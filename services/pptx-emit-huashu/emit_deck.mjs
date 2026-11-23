#!/usr/bin/env node
// Tellr's PPTX export sidecar: the snapshot engine over a whole deck.
//
// Read deck-shape JSON from stdin, render every slide with render_slide.cjs
// (server-side Playwright: the page read as the browser laid it out, then
// written with pptxgenjs), write a single editable .pptx to argv[2].
//
// stdin payload (UTF-8 JSON, no schema validation here — wrapper enforces):
//   { title?: string, slides: [{ html: string, notes?: string }],
//     bypassValidation?: boolean, target?: 'pptx' | 'gslides',
//     allowedHosts?: { [resourceType]: string[] } }
//
// allowedHosts is the https hosts a slide's page may load, by kind of request:
// the wrapper's are the slide CSP's (src/utils/html_safety.py
// SLIDE_CSP_REQUEST_HOSTS). The request guard aborts every other request a
// slide's page makes (request_guard.cjs); without the field, a page loads no
// https host at all.
//
// target is the renderer the deck is written for: 'pptx' (the default) for
// PowerPoint, 'gslides' for the Google Slides conversion. The engine writes
// the few constructs the two apps draw apart for it: around script runs,
// their size, and for PowerPoint the lines they end or grow (emit_text.cjs);
// each run's tracking, which for PowerPoint folds in its kerning; an italic
// webfont run's typeface, for PowerPoint its italic static's name; the
// browser's synthetic bold, for Google Slides the lighter face alone; U+2011,
// written as U+002D for Google Slides (emit_typography.cjs); a dotted line or
// outline, for Google Slides a stroke drawn twice (emit_dotted.cjs); and a
// native table's grid, for PowerPoint on whole px, and its rounded corner
// fills, for Google Slides run under their opaque neighbours (snapshot.mjs;
// scripts/export_fidelity/CALIBRATION.md X1, D1, D12, D8, D6, D7 and D13).
//
// pptxgenjs writes the deck; its dotted table-cell borders are then written
// sysDot, a dash pptxgenjs cannot write a table border in (emit_table.cjs
// dotTableBorders). A rewrite that fails costs only that dash: the deck is
// written as pptxgenjs wrote it, those borders dashed, with one [huashu] line.
//
// argv:  emit_deck.mjs <out.pptx>
//
// stderr: progress lines + a final marker line
//   __HUASHU_RESULT__ <json>
// where <json> is { totalSlides, succeeded, failed: [{ slide_index, error }] }
// so the Python wrapper can surface per-slide validation messages.
//
// The HTML arrives over a pipe, and each slide is still written to a tmp
// .html file, because the browser loads it from a file:// URL (render_slide.cjs),
// in a huashu-deck-* directory removed however the deck ends.

import pptxgen from 'pptxgenjs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
// Every line printed here is one line as the Python wrapper reads it: a
// failure's message can carry text the slide's page threw. The wrapper echoes
// stderr into the app's log, so a line says such text by its length alone,
// unless the debug text is on (log_line.cjs); the failure list, which goes to
// the user who exported the deck, keeps each message whole.
const { bounded, debugText, logJson, oneLine, pageText } = require('./log_line.cjs');

// A SIGTERM (pptx_from_html_huashu.py run_sidecar_process, on a timeout) ends
// node through its exit path, where Playwright's exit handler kills every
// browser it launched: each runs detached, in a process group of its own,
// which no signal to this process's group reaches. Exiting at once is the
// point: Playwright's own SIGTERM handler only closes the browsers gracefully
// and leaves node running, which a hung slide can outlast.
process.on('SIGTERM', () => process.exit(143));

// The most of a message holding no page text (a launch failure, a slide past
// its deadline) a line logs.
const LOGGED_MESSAGE_LIMIT = 2000;

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf-8');
}

async function main() {
  const outArg = process.argv[2];
  if (!outArg) {
    console.error('Usage: node emit_deck.mjs <out.pptx>  (deck JSON via stdin)');
    process.exit(1);
  }

  let payload;
  try {
    payload = JSON.parse(await readStdin());
  } catch (e) {
    // The parser quotes the input, which holds the deck.
    console.error('[huashu] invalid JSON on stdin:', pageText(e.message));
    process.exit(2);
  }

  const slides = payload.slides || [];
  // When set by the caller, a slide's validation errors become console
  // warnings instead of throws — slides that violate design rules still get
  // emitted into the pptx. Used by both export routes.
  const bypassValidation = !!payload.bypassValidation;
  if (!slides.length) {
    console.error('[huashu] no slides in payload');
    process.exit(3);
  }

  const target = payload.target === 'gslides' ? 'gslides' : 'pptx';
  if (payload.target !== undefined && payload.target !== 'gslides' && payload.target !== 'pptx') {
    console.error(`[huashu] unknown target ${logJson(payload.target)}; writing for pptx`);
  }

  // Lazily resolve the renderer (CommonJS, sibling file), so a sidecar whose
  // node_modules are missing fails with one "setup" message. If chromium
  // isn't installed yet, the require itself succeeds but the first slide throws.
  let renderSlide;
  let dotTableBorders;
  let requestHostsOf;
  try {
    ({ renderSlide } = require('./render_slide.cjs'));
    ({ dotTableBorders } = require('./emit_table.cjs'));
    ({ requestHostsOf } = require('./request_guard.cjs'));
  } catch (e) {
    console.error('[huashu] failed to load render_slide.cjs:', oneLine(e.message));
    console.error('[huashu] hint: cd services/pptx-emit-huashu && npm install && npx playwright install chromium');
    process.exit(4);
  }

  const { hosts: requestHosts, ignored } = requestHostsOf(payload.allowedHosts);
  if (ignored) {
    console.error(`[huashu] allowedHosts: ${ignored} entr${ignored === 1 ? 'y is' : 'ies are'} no request ` +
      'type and host names, and allow nothing');
  }

  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';  // 13.333" × 7.5", matches our 1280×720 px @ 96 dpi
  pres.title = payload.title || 'slides';

  // Each slide is written to a file of this directory for the browser to load
  // (render_slide.cjs). It holds the deck's content, so it is removed however
  // the deck ends; a sidecar ended before its finally runs (a timeout) leaves
  // it in the TMPDIR the wrapper made for this run, which the wrapper removes
  // (pptx_from_html_huashu.py _export_deck).
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'huashu-deck-'));
  try {
    await writeDeck({ slides, pres, tmpDir, outArg, renderSlide, dotTableBorders, bypassValidation, target, requestHosts });
  } finally {
    await fs.rm(tmpDir, { recursive: true, force: true }).catch((e) => {
      console.error('[huashu] the slides\' temporary directory could not be removed: ' + oneLine((e && e.message) || e));
    });
  }
}

// Every slide rendered in turn, then the deck written (all but the slides
// that failed), and the __HUASHU_RESULT__ line last.
async function writeDeck({ slides, pres, tmpDir, outArg, renderSlide, dotTableBorders, bypassValidation, target, requestHosts }) {
  const failed = [];
  let succeeded = 0;

  for (let i = 0; i < slides.length; i++) {
    const slide = slides[i];
    if (!slide.html) {
      failed.push({ slide_index: i, error: 'slide.html is empty' });
      continue;
    }
    const tmpHtml = path.join(tmpDir, `slide-${String(i).padStart(3, '0')}.html`);
    try {
      await fs.writeFile(tmpHtml, slide.html, 'utf-8');
      // { slide } for the notes below; throws for a slide it rejects.
      const result = await renderSlide(tmpHtml, pres, { bypassValidation, target, requestHosts, slideIndex: i });
      if (slide.notes && result.slide && typeof result.slide.addNotes === 'function') {
        result.slide.addNotes(slide.notes);
      }
      succeeded += 1;
      console.error(`[huashu] [${i + 1}/${slides.length}] OK`);
    } catch (e) {
      // renderSlide prefixes its message with the htmlFile path; strip the
      // tmp prefix so the user sees a clean message. The log has the message
      // whole only where renderSlide says it holds no page text (logMessage).
      const msg = String(e.message || e).replace(tmpHtml + ': ', '');
      failed.push({ slide_index: i, error: msg });
      const logged = debugText() || !e || typeof e.logMessage !== 'string'
        ? pageText(msg.split('\n')[0])
        : bounded(e.logMessage.split('\n')[0], LOGGED_MESSAGE_LIMIT);
      console.error(`[huashu] [${i + 1}/${slides.length}] FAIL: ${logged}`);
    }
  }

  if (failed.length === slides.length) {
    console.error('[huashu] all slides failed; not writing pptx');
    console.error('__HUASHU_RESULT__ ' + logJson({ totalSlides: slides.length, succeeded: 0, failed }));
    // Set the code and return rather than process.exit(): stderr to a pipe is
    // async, and exiting discards the undrained write, which truncates the
    // sentinel above mid-JSON. The wrapper then parses nothing and reports the
    // export as a hard failure instead of the per-slide errors it just printed.
    process.exitCode = 5;
    return;
  }

  // As pptxgenjs's writeFile names the file: with .pptx added when it lacks one.
  const fileName = outArg.toLowerCase().endsWith('.pptx') ? outArg : outArg + '.pptx';
  const deck = await pres.write({ outputType: 'nodebuffer' });
  let written = deck;
  try {
    written = await dotTableBorders(deck, pres.slides);
  } catch (e) {
    console.error('[huashu] dotted table borders left dashed: their rewrite failed: ' +
      oneLine((e && e.message) || e));
  }
  await fs.writeFile(fileName, written);
  console.error(`[huashu] wrote ${outArg} (${succeeded}/${slides.length} slides)`);
  console.error('__HUASHU_RESULT__ ' + logJson({ totalSlides: slides.length, succeeded, failed }));
}

main().catch((e) => {
  console.error('[huashu] fatal:', bounded(e && e.stack || e, LOGGED_MESSAGE_LIMIT));
  console.error('__HUASHU_RESULT__ ' + logJson({
    totalSlides: 0, succeeded: 0, failed: [{ slide_index: -1, error: String(e.message || e) }],
  }));
  // Same reason as the all-failed path above — let node exit naturally so the
  // sentinel drains. This is the last statement, so there is nothing to skip.
  process.exitCode = 99;
});
