/**
 * Client-side PPTX export using html2canvas screenshots + pptxgenjs.
 * Produces pixel-perfect slides in seconds — no server calls or LLM needed.
 */

import html2canvas from 'html2canvas';
import PptxGenJS from 'pptxgenjs';
import type { SlideDeck } from '../types/slide';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

/**
 * Build HTML for a single slide (reuses pattern from pdf_client.ts).
 */
function buildSlideHTML(slideDeck: SlideDeck, slideIndex: number): string {
  const slide = slideDeck.slides[slideIndex];
  const externalScripts = slideDeck.external_scripts
    .map((src) => `    <script src="${src}"></script>`)
    .join('\n');

  return `<!DOCTYPE html>
<html lang="en">
<head>
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
    .subtitle, p.subtitle, h2.subtitle, div.subtitle, [class*="subtitle"] {
      margin-bottom: 40px !important;
      margin-top: 0 !important;
    }
  </style>
</head>
<body>
${slide.html}
  <script>
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
 * Wait for Chart.js charts to render in an iframe.
 */
async function waitForCharts(
  iframeWindow: Window | null,
  maxWait: number = 8000
): Promise<void> {
  if (!iframeWindow) return;
  const start = Date.now();
  const win = iframeWindow as any;

  // Wait for Chart.js to load
  while (typeof win.Chart === 'undefined' && Date.now() - start < maxWait) {
    await new Promise((r) => setTimeout(r, 100));
  }

  // Wait for canvases to render
  const canvases = iframeWindow.document.querySelectorAll('canvas');
  if (canvases.length === 0) return;

  let attempts = 0;
  while (attempts < 40 && Date.now() - start < maxWait) {
    const allReady = Array.from(canvases).every((c) => c.width > 0 && c.height > 0);
    if (allReady) {
      await new Promise((r) => setTimeout(r, 500));
      return;
    }
    await new Promise((r) => setTimeout(r, 100));
    attempts++;
  }
}

/**
 * Render a slide in a hidden iframe and capture it as a data URL.
 */
async function captureSlide(slideDeck: SlideDeck, slideIndex: number): Promise<string> {
  const container = document.createElement('div');
  container.style.cssText =
    'position:fixed;left:-99999px;top:0;width:1280px;height:720px;visibility:hidden;opacity:0;pointer-events:none;z-index:-9999;overflow:hidden';

  const iframe = document.createElement('iframe');
  iframe.style.cssText = `width:${SLIDE_WIDTH}px;height:${SLIDE_HEIGHT}px;border:none;display:block;margin:0;padding:0`;
  container.appendChild(iframe);
  document.body.appendChild(container);

  try {
    const html = buildSlideHTML(slideDeck, slideIndex);
    const doc = iframe.contentDocument;
    if (!doc) throw new Error('No iframe document');

    doc.open();
    doc.write(html);
    doc.close();

    // Wait for content + charts
    await new Promise((r) => setTimeout(r, 500));
    await waitForCharts(iframe.contentWindow);

    // Capture with html2canvas
    const canvas = await html2canvas(doc.body, {
      width: SLIDE_WIDTH,
      height: SLIDE_HEIGHT,
      scale: 2, // 2x for crisp text
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff',
    });

    return canvas.toDataURL('image/png');
  } finally {
    document.body.removeChild(container);
  }
}

/**
 * Export slide deck as PPTX with screenshot-based slides.
 * Fast (~3-5 seconds), pixel-perfect, all client-side.
 */
export async function exportSlideDeckToPPTXImage(
  slideDeck: SlideDeck,
  filename?: string,
  onProgress?: (current: number, total: number) => void
): Promise<void> {
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_16x9';
  pptx.title = slideDeck.title || 'Presentation';

  const total = slideDeck.slides.length;

  for (let i = 0; i < total; i++) {
    onProgress?.(i + 1, total);

    const dataUrl = await captureSlide(slideDeck, i);

    const slide = pptx.addSlide();
    slide.addImage({
      data: dataUrl,
      x: 0,
      y: 0,
      w: '100%',
      h: '100%',
    });
  }

  const finalName = filename || `${slideDeck.title || 'slides'}.pptx`;
  await pptx.writeFile({ fileName: finalName });
}
