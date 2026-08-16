/**
 * Screenshot-mode capture for the editable-PPTX export dialog.
 *
 * Mirrors frontend/src/services/pdf_client.ts's iframe+html2canvas flow
 * but returns one base64 PNG data URL per slide instead of piping into
 * a PDF. Backend (/api/export/pptx/editable/from-images) embeds each
 * PNG as a full-slide picture in a .pptx.
 *
 * Used only for the "Screenshot-based PPTX" option where the user
 * picks pixel-perfect fidelity over editability.
 *
 * NO SLIDE-HOST FRAME CONTRACT HERE, DELIBERATELY — reverted with every other
 * export builder, because on the huashu path that shared rule collapsed flattened
 * table cells onto one rect (see src/api/routes/export.py).
 *
 * The slide-root locator is not sufficient on its own here, and for a while this
 * file said so and stopped there: on a section-wrapped design-system deck the
 * delivered PNG measured 100.00% transparent, 0 non-white colours, entirely
 * blank. Locating the ground-carrying element does not give it AREA, and
 * html2canvas photographs the box it is handed.
 *
 * FIXED at the capture site, the way the PDF surface always did it: force the
 * resolved element's geometry with INLINE styles before capturing (see the
 * force-size in captureDeckAsPngDataUrls, mirroring pdf_client.ts:290-298).
 * Measured on the wrapped deck, 100.00% transparent / 0 colours / 0 ink pixels
 * becomes 0.00% transparent, ground rgb(249,247,244), 47,369 ink pixels, darkest
 * ink rgb(27,49,57) at contrast 12.7110 against that ground. Unwrapped decks that
 * are ALREADY frame-sized — root 1280x720 at (0,0), margin-reset, no padding or
 * border — do not move: byte-identical capture, FNV-1a 68079f00 either side.
 *
 * A content-box root declaring 1280x720 PLUS padding DOES move, intentionally: it
 * measures 1456x864, overflowing its own frame by 176px, and `border-box` refits it
 * to 1280x720 (FNV-1a bbcab96b -> a36bd956, ink 67,316 -> 68,885, both sides 0.00%
 * transparent / 495 non-white colours). That refit is the product-wide fixed-frame
 * contract, applied identically on the certified PDF path at pdf_client.ts:290-298
 * all along — a consistency consequence, not new behaviour here. It is not a free
 * win either: 1456x864 -> 1280x720 necessarily shrinks the content area to
 * 1104x576, so text may re-wrap and flex content reflow, and the higher ink count
 * therefore does NOT by itself prove recovered clipping — it cannot tell reflow
 * from recovered clipping.
 *
 * That is a force-size, NOT the frame contract, and the distinction is the whole
 * point — it injects no CSS, so it cannot outrank the inline coordinates
 * preprocess.mjs::flattenTables() gives each flattened table cell. Pinned by
 * 'captureDeckAsPngDataUrls paints the ground AND the ink on a wrapped deck' in
 * frontend/tests/e2e/slide-surface-fidelity.spec.ts, which asserts the ground and
 * the ink SEPARATELY so neither half can regress alone.
 */

import html2canvas from 'html2canvas';
import type { SlideDeck } from '../types/slide';
import { SLIDE_CSP, SLIDE_ROOT_RESET_STYLE, findSlideRoot } from './slideDocument';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

export function buildSlideHtml(deck: SlideDeck, slideIndex: number): string {
  const slide = deck.slides[slideIndex];
  const externalScripts = (deck.external_scripts || [])
    .map(s => `<script src="${s}"></script>`).join('\n');
  const slideScripts = slide.scripts || '';
  const deckScripts = deck.scripts || '';
  const css = deck.css || '';
  // AISEC-248 #3: same-origin is required for html2canvas to read contentDocument,
  // so we cannot sandbox these capture frames. CSP is the egress containment.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
${cspMeta}
<meta charset="UTF-8">
<title>${deck.title || 'Slide'}</title>
${externalScripts}
<style>
  html, body { margin:0; padding:0; box-sizing:border-box; }
  html { width:${SLIDE_WIDTH}px; height:${SLIDE_HEIGHT}px; overflow:hidden; }
  body { width:${SLIDE_WIDTH}px; height:${SLIDE_HEIGHT}px; overflow:hidden; position:relative; }
  ${css}
  /* After deck CSS: flatten the slide root (outer margin / radius / shadow) —
     a root margin inside this fixed 1280x720 overflow:hidden document shifts
     content past the clip and truncates the capture's bottom edge. */
  ${SLIDE_ROOT_RESET_STYLE}
</style>
</head>
<body>
${slide.html}
<script>try{${slideScripts}}catch(e){console.debug(e)}</script>
<script>try{${deckScripts}}catch(e){console.debug(e)}</script>
</body>
</html>`;
}

async function waitForCharts(win: Window | null, maxMs: number): Promise<void> {
  if (!win) return;
  const start = Date.now();
  const anyWin = win as any;
  while (typeof anyWin.Chart === 'undefined' && Date.now() - start < 1500) {
    await new Promise(r => setTimeout(r, 80));
  }
  const doc = win.document;
  const canvases = doc.querySelectorAll('canvas');
  if (!canvases.length) return;
  const deadline = start + maxMs;
  while (Date.now() < deadline) {
    const ready = Array.from(canvases).every(c => c.width > 0 && c.height > 0);
    if (ready) break;
    await new Promise(r => setTimeout(r, 80));
  }
}

export async function captureDeckAsPngDataUrls(deck: SlideDeck): Promise<string[]> {
  const out: string[] = [];
  for (let i = 0; i < (deck.slides || []).length; i++) {
    const container = document.createElement('div');
    container.style.cssText =
      `position:fixed;left:-99999px;top:0;width:${SLIDE_WIDTH}px;height:${SLIDE_HEIGHT}px;visibility:hidden;opacity:0;pointer-events:none;z-index:-9999;overflow:hidden;`;
    const iframe = document.createElement('iframe');
    iframe.style.cssText = `width:${SLIDE_WIDTH}px;height:${SLIDE_HEIGHT}px;border:0;display:block;`;
    container.appendChild(iframe);
    document.body.appendChild(container);
    try {
      iframe.srcdoc = buildSlideHtml(deck, i);
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(() => reject(new Error('iframe timeout')), 15000);
        iframe.onload = () => { clearTimeout(t); resolve(); };
        iframe.onerror = () => { clearTimeout(t); reject(new Error('iframe error')); };
      });
      const doc = iframe.contentDocument; const win = iframe.contentWindow;
      if (!doc || !win) throw new Error('iframe not accessible');
      await new Promise(r => setTimeout(r, 300));
      await waitForCharts(win, 4000);
      try { await (win as any).document.fonts.ready; } catch (_) { /* best effort */ }
      await new Promise(r => setTimeout(r, 150));
      // The slide ROOT, which is NOT `.slide` once a design system wraps it.
      const slideEl = findSlideRoot(doc);
      // Force the resolved element's geometry, exactly as exportSlideDeckToPDF
      // does (pdf_client.ts): on a section-wrapped deck the root is 1280x0 in the
      // document — `.slide` inside it is out of flow, so the wrapper has no
      // in-flow content — and html2canvas photographs that collapsed box, which
      // with `backgroundColor: null` delivers an entirely transparent PNG.
      //
      // INLINE, ON THIS ONE ELEMENT, never a stylesheet: a document-level rule is
      // what destroyed table layout on the huashu path, where
      // preprocess.mjs::flattenTables() appends every cell to `body` with its
      // coordinates as NON-important inline styles that a `body > *` rule outranks.
      // An inline style on the element html2canvas was already given cannot reach
      // a sibling, so that path is untouched.
      //
      // Padding is preserved — the slide's safe area lives there — and
      // `border-box` is what keeps a padded root at frame size instead of
      // overflowing to 1280+padding, which is why the width/height and the box
      // model have to be set together.
      if (slideEl !== doc.body) {
        slideEl.style.width = `${SLIDE_WIDTH}px`;
        slideEl.style.height = `${SLIDE_HEIGHT}px`;
        slideEl.style.margin = '0';
        slideEl.style.boxSizing = 'border-box';
      }
      const canvas = await html2canvas(slideEl, {
        width: SLIDE_WIDTH,
        height: SLIDE_HEIGHT,
        scale: 2,
        useCORS: true,
        backgroundColor: null,
        windowWidth: SLIDE_WIDTH,
        windowHeight: SLIDE_HEIGHT,
      });
      out.push(canvas.toDataURL('image/png'));
    } finally {
      if (container.parentNode) document.body.removeChild(container);
    }
  }
  return out;
}
