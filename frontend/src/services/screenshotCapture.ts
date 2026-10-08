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

import type { SlideDeck } from '../types/slide';
import { SLIDE_CSP, SLIDE_ROOT_RESET_STYLE } from './slideDocument';
import { trustedExportRuntimeMarkup } from './exportFrameRuntime';
import {
  runSandboxedExportFrame,
  type CaptureImageResult,
} from './sandboxedExportFrame';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

export function buildSlideHtml(deck: SlideDeck, slideIndex: number): string {
  const slide = deck.slides[slideIndex];
  const externalScripts = (deck.external_scripts || [])
    .map(s => `<script src="${s}"></script>`).join('\n');
  const slideScripts = slide.scripts || '';
  const deckScripts = deck.scripts || '';
  const css = deck.css || '';
  // F-CR-25: CSP stays first; the trusted runtime captures inside an opaque sandbox.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
${cspMeta}
${trustedExportRuntimeMarkup()}
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

export async function captureDeckAsPngDataUrls(deck: SlideDeck): Promise<string[]> {
  const out: string[] = [];
  for (let i = 0; i < (deck.slides || []).length; i++) {
    const captured = await runSandboxedExportFrame<CaptureImageResult>(
      buildSlideHtml(deck, i),
      {
        kind: 'capture-image',
        requestId: crypto.randomUUID(),
        format: 'image/png',
        scale: 2,
        width: SLIDE_WIDTH,
        height: SLIDE_HEIGHT,
        rootMode: 'slide-root',
        applyPdfSubtitleFixes: false,
        waitForChartsMs: 4000,
      },
    );
    out.push(captured.dataUrl);
  }
  return out;
}
