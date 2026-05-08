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
 */

import html2canvas from 'html2canvas';
import type { SlideDeck } from '../types/slide';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

function buildSlideHtml(deck: SlideDeck, slideIndex: number): string {
  const slide = deck.slides[slideIndex];
  const externalScripts = (deck.external_scripts || [])
    .map(s => `<script src="${s}"></script>`).join('\n');
  const slideScripts = slide.scripts || '';
  const deckScripts = deck.scripts || '';
  const css = deck.css || '';
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>${deck.title || 'Slide'}</title>
${externalScripts}
<style>
  html, body { margin:0; padding:0; box-sizing:border-box; }
  html { width:${SLIDE_WIDTH}px; height:${SLIDE_HEIGHT}px; overflow:hidden; }
  body { width:${SLIDE_WIDTH}px; height:${SLIDE_HEIGHT}px; overflow:hidden; position:relative; }
  ${css}
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
      const slideEl = (doc.querySelector('.slide') || doc.body) as HTMLElement;
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
