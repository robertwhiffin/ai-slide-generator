#!/usr/bin/env node
// Tellr ⇄ huashu-design bridge — local-only.
//
// Read deck-shape JSON from stdin, run alchaincyf/huashu-design's
// html2pptx.js (server-side Playwright + DOM walk + pptxgenjs) over
// every slide, write a single editable .pptx to argv[2].
//
// stdin payload (UTF-8 JSON, no schema validation here — wrapper enforces):
//   { title?: string, slides: [{ html: string, notes?: string }],
//     bypassValidation?: boolean, engine?: 'legacy' | 'snapshot' }
//
// engine selects the per-slide converter: 'legacy' (the default) is
// html2pptx.js after the DOM-mutating PREPROCESS_SOURCE; 'snapshot' is
// render_slide.cjs, which runs only the layout-neutral BG_TRANSFER_SOURCE and
// then reads the page as rendered. Notes and failure handling are the same.
//
// argv:  emit_deck.mjs <out.pptx>
//
// stderr: progress lines + a final marker line
//   __HUASHU_RESULT__ <json>
// where <json> is { totalSlides, succeeded, failed: [{ slide_index, error }] }
// so the Python wrapper can surface per-slide validation messages.
//
// Why a custom orchestrator instead of huashu's export_deck_pptx.mjs:
// theirs reads .html files from a directory; we get HTML over a pipe so
// we don't have to round-trip through the filesystem (we still write a
// tmp .html per slide because html2pptx.js takes a path — see below).

import pptxgen from 'pptxgenjs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { BG_TRANSFER_SOURCE, PREPROCESS_SOURCE } from './preprocess.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

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
    console.error('[huashu] invalid JSON on stdin:', e.message);
    process.exit(2);
  }

  const slides = payload.slides || [];
  // When set by the caller, validation errors in html2pptx become console
  // warnings instead of throws — slides that violate design rules still get
  // emitted into the pptx. Used by the Google Slides upload route.
  const bypassValidation = !!payload.bypassValidation;
  if (!slides.length) {
    console.error('[huashu] no slides in payload');
    process.exit(3);
  }

  const engine = payload.engine === 'snapshot' ? 'snapshot' : 'legacy';
  if (payload.engine !== undefined && payload.engine !== 'snapshot' && payload.engine !== 'legacy') {
    console.error(`[huashu] unknown engine ${JSON.stringify(payload.engine)}; using legacy`);
  }

  // Lazily resolve the converter (CommonJS, sibling file). If playwright/
  // chromium isn't installed yet, the require itself succeeds but the
  // first call throws. We surface that as a single "setup" failure.
  const converterFile = engine === 'snapshot' ? 'render_slide.cjs' : 'html2pptx.js';
  let converter;
  try {
    converter = require(path.join(__dirname, converterFile));
  } catch (e) {
    console.error(`[huashu] failed to load ${converterFile}:`, e.message);
    console.error('[huashu] hint: cd services/pptx-emit-huashu && npm install && npx playwright install chromium');
    process.exit(4);
  }

  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';  // 13.333" × 7.5", matches our 1280×720 px @ 96 dpi
  pres.title = payload.title || 'slides';

  // Both converters return { slide } for the notes below and throw for a slide
  // they reject.
  const convertSlide = engine === 'snapshot'
    ? (htmlFile) => converter.renderSlide(htmlFile, pres, {
      preProcessSource: BG_TRANSFER_SOURCE,
      bypassValidation,
    })
    : (htmlFile) => converter(htmlFile, pres, {
      preProcessSource: PREPROCESS_SOURCE,
      bypassValidation,
    });

  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'huashu-deck-'));
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
      const result = await convertSlide(tmpHtml);
      if (slide.notes && result.slide && typeof result.slide.addNotes === 'function') {
        result.slide.addNotes(slide.notes);
      }
      succeeded += 1;
      console.error(`[huashu] [${i + 1}/${slides.length}] OK`);
    } catch (e) {
      // Both converters prefix their message with the htmlFile path; strip
      // the tmp prefix so the user sees a clean message.
      const msg = String(e.message || e).replace(tmpHtml + ': ', '');
      failed.push({ slide_index: i, error: msg });
      console.error(`[huashu] [${i + 1}/${slides.length}] FAIL: ${msg.split('\n')[0]}`);
    }
  }

  // Don't dump the tmp dir on success — useful for post-mortem if a
  // slide fails. Wrapper deletes it on success.
  if (failed.length === slides.length) {
    console.error('[huashu] all slides failed; not writing pptx');
    console.error('__HUASHU_RESULT__ ' + JSON.stringify({
      totalSlides: slides.length, succeeded: 0, failed, tmpDir,
    }));
    // Set the code and return rather than process.exit(): stderr to a pipe is
    // async, and exiting discards the undrained write, which truncates the
    // sentinel above mid-JSON. The wrapper then parses nothing and reports the
    // export as a hard failure instead of the per-slide errors it just printed.
    process.exitCode = 5;
    return;
  }

  await pres.writeFile({ fileName: outArg });
  console.error(`[huashu] wrote ${outArg} (${succeeded}/${slides.length} slides)`);
  console.error('__HUASHU_RESULT__ ' + JSON.stringify({
    totalSlides: slides.length, succeeded, failed, tmpDir,
  }));
}

main().catch((e) => {
  console.error('[huashu] fatal:', e && e.stack || e);
  console.error('__HUASHU_RESULT__ ' + JSON.stringify({
    totalSlides: 0, succeeded: 0, failed: [{ slide_index: -1, error: String(e.message || e) }],
  }));
  // Same reason as the all-failed path above — let node exit naturally so the
  // sentinel drains. This is the last statement, so there is nothing to skip.
  process.exitCode = 99;
});
