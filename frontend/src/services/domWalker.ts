/**
 * Client-side DOM walker for the editable PPTX exporter.
 *
 * Wholesale adopted from the reference scaffold (walker.js) that Claude Design
 * published. Runs inside a hidden iframe that renders the composite slide deck;
 * for each slide we call __extractSlide(slideRoot) which returns
 *   { width, height, records: [rect|image|text] }
 * in paint order (pre-order DOM walk). These are POSTed to the backend, which
 * spawns a Node subprocess (services/pptx-emit/emit.bundle.mjs) using pptxgenjs.
 *
 * Why this architecture: Databricks Apps containers have no Chromium (non-root
 * + memory-constrained). The user's browser already rendered the deck.
 *
 * F-CR-25: the composite document runs in an opaque sandbox. The parent never
 * reads the iframe document; the trusted export runtime walks the DOM inside
 * the frame and returns records via postMessage.
 */

import type { SlideDeck } from '../types/slide';
import { SLIDE_CSP, SLIDE_ROOT_RESET_STYLE } from './slideDocument';
import {
  runSandboxedExportFrame,
  type ExtractRecordsResult,
} from './sandboxedExportFrame';
import { trustedExportRuntimeMarkup } from './exportFrameRuntime';

export { WALKER_SOURCE } from './exportWalkerSource';

/** Font strategy for the editable export. */
export type EditableFontMode =
  | 'custom'
  | 'universal'
  | 'google_slides';

export interface RunRecord {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  color: string;
  size: number;
  family: string;
  breakLine?: boolean;
}
export interface ShadowSpec {
  type: 'outer';
  angle: number;
  blur: number;
  color: string;
  offset: number;
  opacity: number;
}
export interface RectRecord {
  kind: 'rect';
  x: number; y: number; w: number; h: number;
  fill: string | null;
  stroke?: string | null;
  strokeW?: number;
  radius?: number;
  shadow?: ShadowSpec;
  _depth?: number;
}
export interface ImageRecord {
  kind: 'image';
  x: number; y: number; w: number; h: number;
  src: string;
  rotate?: number;
  _depth?: number;
}
export interface TextRecord {
  kind: 'text';
  x: number; y: number; w: number; h: number;
  runs: RunRecord[];
  align: string;
  valign: string;
  rotate?: number;
  _depth?: number;
}
export type SlideRecord = RectRecord | ImageRecord | TextRecord;

export interface SlideExtract {
  width: number;
  height: number;
  records: SlideRecord[];
  notes: string;
}

const DESIGN_W = 1280;
const DESIGN_H = 720;

// Exported so tests can pin the composite document's layout guarantees.
//
// NO SLIDE-HOST FRAME CONTRACT HERE, DELIBERATELY. This document injected
// slideHostFrameStyle on `section.slide-container` at 0.4.2.dev17; it is reverted
// with every other export builder because the same shared rule collapses
// flattened table cells onto one rect on the huashu path (see
// src/api/routes/export.py for the mechanism and measurements).
//
// THE ACCEPTED COST, stated plainly. On a section-wrapped design-system deck the
// wrapper carries no in-flow content and collapses to 1280x0 in this document. The
// walker's isVisible() is false at height === 0 and visit() returns WITHOUT
// descending, so the whole slide subtree is pruned: 1 rect and 0 text records per
// slide, and a .pptx built from that has no text in it. That is the dev16
// behaviour and it was equally broken before dev17.
//
// It is accepted because this composite is the RECORDS FALLBACK: it only runs when
// the huashu sidecar is unavailable, which in practice is the startup 503 window.
// Trading a working table export on the primary path for a text-bearing fallback
// on a wrapped deck is the wrong trade, and there is no locator equivalent here —
// the walker is handed `section.slide-container` by selector, so there is nothing
// to re-aim.
export function buildCompositeHtml(deck: SlideDeck): string {
  const slides = deck.slides || [];
  const sections = slides.map((s, i) => {
    const hidden = i === 0 ? '' : ' style="display:none"';
    const scripts = s.scripts
      ? `<script>try{${s.scripts}}catch(e){console.debug(e)}</script>`
      : '';
    return `<section class="slide-container" data-slide-index="${i}"${hidden}>${s.html || ''}${scripts}</section>`;
  }).join('\n');

  const ext = (deck.external_scripts || []).map(src => `<script src="${src}"></script>`).join('\n');
  const notes = JSON.stringify(
    slides.map((s) => {
      const extra = s as unknown as { speaker_notes?: string; notes?: string };
      return extra.speaker_notes || extra.notes || '';
    }),
  );

  // F-CR-25: CSP stays first; the trusted runtime follows. Slide scripts still
  // run as inline <script> under 'unsafe-inline'. 'unsafe-eval' is withheld.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
${cspMeta}
${trustedExportRuntimeMarkup()}
<meta charset="UTF-8">
<title>${deck.title || 'Presentation'}</title>
${ext}
<style>
html, body { margin: 0; padding: 0; }
html { width: ${DESIGN_W}px; height: ${DESIGN_H}px; }
section.slide-container { width: ${DESIGN_W}px; height: ${DESIGN_H}px; position: relative; overflow: hidden; }
/* Authored decks often style the slide root like a print-preview card
   (margin: 40px auto; border-radius: 12px; box-shadow: ...). The 40px margin
   shifts every absolutely-positioned descendant out past the 720px clip rect,
   and pptxgenjs cannot render root rounding/shadows. The shared reset
   flattens the root — whatever its class — exactly like every other surface. */
${SLIDE_ROOT_RESET_STYLE}
${deck.css || ''}
</style>
</head>
<body>
${sections}
<script id="speaker-notes" type="application/json">${notes}</script>
<script>try{${deck.scripts || ''}}catch(e){console.debug(e)}</script>
</body>
</html>`;
}

function protocolFontMode(
  fontMode: EditableFontMode,
): 'universal' | 'google_slides' | 'preserve' {
  if (fontMode === 'universal') return 'universal';
  if (fontMode === 'google_slides') return 'google_slides';
  return 'preserve';
}

/** Mount a hidden sandboxed iframe and collect records via the export runtime. */
export async function extractSlideRecordsForExport(
  deck: SlideDeck,
  fontMode: EditableFontMode = 'universal',
): Promise<SlideExtract[]> {
  const slides = deck.slides || [];
  if (!slides.length) return [];

  const result = await runSandboxedExportFrame<ExtractRecordsResult>(
    buildCompositeHtml(deck),
    {
      kind: 'extract-records',
      requestId: crypto.randomUUID(),
      fontMode: protocolFontMode(fontMode),
    },
  );
  return result.records as SlideExtract[];
}
