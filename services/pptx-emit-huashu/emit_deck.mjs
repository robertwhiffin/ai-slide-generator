#!/usr/bin/env node
// Tellr ⇄ huashu-design bridge — local-only.
//
// Read deck-shape JSON from stdin, run alchaincyf/huashu-design's
// html2pptx.js (server-side Playwright + DOM walk + pptxgenjs) over
// every slide, write a single editable .pptx to argv[2].
//
// stdin payload (UTF-8 JSON, no schema validation here — wrapper enforces):
//   { title?: string, slides: [{ html: string, notes?: string }] }
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
import { PREPROCESS_SOURCE } from './preprocess.mjs';

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

  // Lazily resolve html2pptx.js (CommonJS, sibling file). If playwright/
  // chromium isn't installed yet, the require itself succeeds but the
  // first call throws. We surface that as a single "setup" failure.
  let html2pptx;
  try {
    html2pptx = require(path.join(__dirname, 'html2pptx.js'));
  } catch (e) {
    console.error('[huashu] failed to load html2pptx.js:', e.message);
    console.error('[huashu] hint: cd services/pptx-emit-huashu && npm install && npx playwright install chromium');
    process.exit(4);
  }

  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';  // 13.333" × 7.5", matches our 1280×720 px @ 96 dpi
  pres.title = payload.title || 'slides';

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
      const result = await html2pptx(tmpHtml, pres, {
        preProcessSource: PREPROCESS_SOURCE,
        bypassValidation,
      });
      if (slide.notes && result.slide && typeof result.slide.addNotes === 'function') {
        result.slide.addNotes(slide.notes);
      }
      succeeded += 1;
      console.error(`[huashu] [${i + 1}/${slides.length}] OK`);
    } catch (e) {
      // html2pptx prefixes its message with the htmlFile path; strip the
      // tmp prefix so the user sees a clean message.
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
    process.exit(5);
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
  process.exit(99);
});
