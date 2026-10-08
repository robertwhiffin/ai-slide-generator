/**
 * Client-side PDF generation service.
 * Uses jsPDF and html2canvas to convert slide decks to PDF without server-side binaries.
 */

import jsPDF from 'jspdf';
import type { SlideDeck } from '../types/slide';
import { SLIDE_CSP, SLIDE_ROOT_RESET_STYLE } from './slideDocument';
import { trustedExportRuntimeMarkup } from './exportFrameRuntime';
import {
  runSandboxedExportFrame,
  type CaptureImageResult,
} from './sandboxedExportFrame';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

/**
 * Build HTML for a single slide.
 * Matches the structure used in SlideTile for consistent rendering.
 * Exported so tests can pin the document's layout guarantees.
 *
 * NO SLIDE-HOST FRAME CONTRACT HERE, DELIBERATELY. A rule framing `body` and
 * stretching its CHILD to `position: absolute !important; inset: 0 !important;
 * width/height: 100% !important` was injected here at 0.4.2.dev17 and is
 * REVERTED: it is the same shared rule the server document injected, and there it
 * collapsed every flattened table cell onto one rect on the huashu path. The
 * export builders now inject no frame contract at all — see the reverted comment
 * in src/api/routes/export.py for the mechanism and the measurements.
 *
 * What the DS-pinned dark-on-dark defect actually needs on this surface is the
 * capture step aiming at the element that carries the ground — see
 * {@link findSlideRoot} in exportSlideDeckToPDF. That locator alone produces the
 * corrected artifact, measured on the delivered PDF's own DCTDecode streams:
 * ground rgb(248,247,243) with brand inks at 12.6794 / 10.8670 / 6.6878, against
 * rgb(0,0,0) at 1.5450 / 1.8027 / 2.9292 before. It works because
 * exportSlideDeckToPDF force-sizes its capture target inline (see below), and
 * that block reaches the wrapper once the locator resolves to it. The locator
 * injects no CSS, so unlike the contract it cannot perturb emitted geometry.
 */
export function buildSlideHTML(slideDeck: SlideDeck, slideIndex: number): string {
  const slide = slideDeck.slides[slideIndex];
  const externalScripts = slideDeck.external_scripts
    .map((src) => `    <script src="${src}"></script>`)
    .join('\n');

  // F-CR-25: CSP stays first; the trusted runtime captures inside an opaque sandbox.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  ${cspMeta}
  ${trustedExportRuntimeMarkup()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${slideDeck.title || 'Slide Deck'} - Slide ${slideIndex + 1}</title>
${externalScripts}
  <style>
    /* Only reset root elements, preserve content spacing */
    html, body {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    html {
      width: ${SLIDE_WIDTH}px;
      height: ${SLIDE_HEIGHT}px;
      overflow: hidden;
    }
    body {
      margin: 0 !important;
      padding: 0 !important;
      width: ${SLIDE_WIDTH}px !important;
      height: ${SLIDE_HEIGHT}px !important;
      overflow: hidden !important;
      position: relative;
    }
    ${slideDeck.css}
    /* After deck CSS: flatten the slide root (outer margin / radius / shadow) —
       inside this fixed 1280x720 overflow:hidden document a root margin
       shifts content past the clip and truncates the export's bottom edge
       (same neutralization as every other surface). */
    ${SLIDE_ROOT_RESET_STYLE}
    /* CRITICAL: Explicitly preserve subtitle spacing - override any global resets */
    /* This must come AFTER slideDeck.css to override any * { margin: 0; } resets */
    .subtitle, p.subtitle, h2.subtitle, div.subtitle, [class*="subtitle"] {
      margin-bottom: 40px !important;
      margin-top: 0 !important;
    }
    /* Also ensure subtitle spacing works even if global reset is applied */
    * .subtitle, * p.subtitle, * div.subtitle {
      margin-bottom: 40px !important;
    }
  </style>
</head>
<body>
${slide.html}
  <script>
    // Wrap scripts in try-catch to handle chart initialization
    try {
      ${slideDeck.scripts}
    } catch (error) {
      console.debug('Chart initialization error:', error.message);
    }
  </script>
</body>
</html>`;
}

/**
 * Export slide deck as PDF using client-side generation.
 * No server-side binaries required.
 * Renders each slide individually using iframe to ensure Chart.js loads correctly.
 *
 * @param slideDeck - The slide deck to export
 * @param filename - Optional filename (default: slides.pdf)
 * @param options - PDF export options
 */
export async function exportSlideDeckToPDF(
  slideDeck: SlideDeck,
  filename: string = 'slides.pdf',
  options: {
    format?: 'a4' | 'letter';
    orientation?: 'portrait' | 'landscape';
    scale?: number;
    waitForCharts?: number;
    imageQuality?: number; // JPEG quality 0-1 (default: 0.85)
  } = {}
): Promise<void> {
  const {
    format = 'a4',
    orientation = 'landscape',
    scale = 1.2, // Optimized: 1.2x provides good quality without huge file size
    waitForCharts = 5000, // Wait up to 5 seconds for Chart.js to render
    imageQuality = 0.85, // JPEG quality: 0.85 provides good balance
  } = options;

  // Create PDF document
  const pdf = new jsPDF({
    orientation: orientation === 'landscape' ? 'l' : 'p',
    unit: 'mm',
    format: format,
  });

  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();

  // Process each slide individually
  for (let i = 0; i < slideDeck.slides.length; i++) {
    try {
      const captured = await runSandboxedExportFrame<CaptureImageResult>(
        buildSlideHTML(slideDeck, i),
        {
          kind: 'capture-image',
          requestId: crypto.randomUUID(),
          format: 'image/jpeg',
          quality: imageQuality,
          scale,
          width: SLIDE_WIDTH,
          height: SLIDE_HEIGHT,
          rootMode: 'slide-root',
          applyPdfSubtitleFixes: true,
          waitForChartsMs: waitForCharts,
        },
      );

      const slideAspectRatio = SLIDE_WIDTH / SLIDE_HEIGHT;
      const pageAspectRatio = pageWidth / pageHeight;

      let imgWidth: number;
      let imgHeight: number;
      let xOffset = 0;
      let yOffset = 0;

      if (slideAspectRatio > pageAspectRatio) {
        imgWidth = pageWidth;
        imgHeight = pageWidth / slideAspectRatio;
        yOffset = (pageHeight - imgHeight) / 2;
      } else {
        imgHeight = pageHeight;
        imgWidth = pageHeight * slideAspectRatio;
        xOffset = (pageWidth - imgWidth) / 2;
      }

      if (i > 0) {
        pdf.addPage();
      }

      pdf.addImage(captured.dataUrl, 'JPEG', xOffset, yOffset, imgWidth, imgHeight);
    } catch (error) {
      console.error(`Failed to export slide ${i + 1}:`, error);
    }
  }

  // Download PDF
  pdf.save(filename);
}
