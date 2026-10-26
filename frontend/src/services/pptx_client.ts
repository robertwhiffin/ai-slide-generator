/**
 * Client-side PPTX export utilities.
 * Captures Chart.js canvas screenshots before sending to backend.
 */

import type { SlideDeck } from '../types/slide';
import { SLIDE_CSP, SLIDE_ROOT_RESET_STYLE } from './slideDocument';
import { trustedExportRuntimeMarkup } from './exportFrameRuntime';
import {
  runSandboxedExportFrame,
  type CaptureCanvasesResult,
} from './sandboxedExportFrame';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

/**
 * Build HTML for a single slide (same as PDF client).
 * Exported so tests can pin the document's layout guarantees.
 */
export function buildSlideHTML(slideDeck: SlideDeck, slideIndex: number): string {
  const slide = slideDeck.slides[slideIndex];
  const externalScripts = slideDeck.external_scripts
    .map((src) => `    <script src="${src}"></script>`)
    .join('\n');

  // F-CR-25: CSP stays first; chart canvases are read inside an opaque sandbox.
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
  </style>
</head>
<body>
${slide.html}
  <script>
    // Wait for Chart.js to be available before running chart initialization scripts
    function waitForChartJs(callback, maxAttempts = 50) {
      let attempts = 0;
      const check = () => {
        attempts++;
        if (typeof Chart !== 'undefined') {
          callback();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 100);
        } else {
          console.error('[CAPTURE] Chart.js failed to load');
        }
      };
      check();
    }

    function initializeCharts() {
      console.log('[CAPTURE] Initializing charts...');
      try {
        // First, destroy any existing Chart.js instances to avoid "canvas already in use" errors
        if (typeof Chart !== 'undefined' && Chart.getChart) {
          const canvases = document.querySelectorAll('canvas');
          canvases.forEach((canvas) => {
            const existingChart = Chart.getChart(canvas);
            if (existingChart) {
              console.log('[CAPTURE] Destroying existing chart on canvas:', canvas.id || 'unnamed');
              existingChart.destroy();
            }
          });
        }
        
        // Now initialize charts
        ${slideDeck.scripts}
        console.log('[CAPTURE] Charts initialized successfully');
      } catch (err) {
        console.error('[CAPTURE] Chart initialization error:', err);
      }
    }

    // Initialize charts after DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        waitForChartJs(initializeCharts);
      });
    } else {
      waitForChartJs(initializeCharts);
    }
  </script>
</body>
</html>`;
}

async function captureSlideCharts(
  slideDeck: SlideDeck,
  slideIndex: number
): Promise<Record<string, string>> {
  console.log(`[CAPTURE] Slide ${slideIndex + 1}: Starting capture`);
  const result = await runSandboxedExportFrame<CaptureCanvasesResult>(
    buildSlideHTML(slideDeck, slideIndex),
    {
      kind: 'capture-canvases',
      requestId: crypto.randomUUID(),
      waitForChartsMs: 20000,
    },
  );
  const chartImages = result.canvases;
  console.log(
    `[CAPTURE] Slide ${slideIndex + 1}: Captured ${Object.keys(chartImages).length} charts`,
  );
  return chartImages;
}

/**
 * Capture Chart.js screenshots for all slides in a deck.
 * Returns an array of maps, one per slide, with canvas IDs to base64 PNG data URLs.
 */
export async function captureSlideDeckCharts(
  slideDeck: SlideDeck
): Promise<Array<Record<string, string>>> {
  console.log(`[CAPTURE] Starting capture for ${slideDeck.slides.length} slides`);
  const allChartImages: Array<Record<string, string>> = [];
  
  for (let i = 0; i < slideDeck.slides.length; i++) {
    try {
      console.log(`[CAPTURE] Processing slide ${i + 1}/${slideDeck.slides.length}`);
      const chartImages = await captureSlideCharts(slideDeck, i);
      console.log(`[CAPTURE] Slide ${i + 1}: Captured ${Object.keys(chartImages).length} charts (IDs: ${Object.keys(chartImages).join(', ') || 'none'})`);
      allChartImages.push(chartImages);
    } catch (error) {
      console.error(`[CAPTURE] Failed to capture charts for slide ${i + 1}:`, error);
      console.error(`[CAPTURE] Error details:`, error instanceof Error ? error.stack : String(error));
      allChartImages.push({}); // Empty map for this slide
    }
  }
  
  const totalCharts = allChartImages.reduce((sum, slide) => sum + Object.keys(slide).length, 0);
  console.log(`[CAPTURE] Completed: ${totalCharts} total charts captured across ${slideDeck.slides.length} slides`);
  
  return allChartImages;
}

