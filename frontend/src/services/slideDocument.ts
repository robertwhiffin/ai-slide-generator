// frontend/src/services/slideDocument.ts
// AISEC-248 PR1: single source of truth for slide iframe documents.
// Injects a Content-Security-Policy <meta> so LLM-generated slide JS cannot
// exfiltrate data (connect-src 'none' blocks fetch/XHR/WebSocket/beacon;
// img-src data: blocks image beacons; scripts only from the Chart.js / Tailwind
// CDNs; form-action 'none' blocks form-POST exfil — form-action does NOT fall
// back to default-src, so it must be set explicitly; base-uri 'none' stops a
// rewritten <base> from re-pointing relative URLs).
//
// Google Fonts (fonts.googleapis.com stylesheet + fonts.gstatic.com font files)
// are allowed: decks routinely use them (e.g. Inter), and a render-blocking
// <link rel="stylesheet"> that CSP blocks leaves the slide blank until a reflow
// (the "black screen until you toggle fullscreen" bug). They are static,
// well-known hosts and are not an exfiltration channel (connect-src stays 'none').
import type { SlideDeck } from '../types/slide';

export const SLIDE_CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; " +
  "style-src 'unsafe-inline' https://fonts.googleapis.com; " +
  "img-src data:; " +
  "font-src data: https://cdn.jsdelivr.net https://fonts.gstatic.com; " +
  "connect-src 'none'; " +
  "form-action 'none'; " +
  "base-uri 'none';";

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;

// Forwards keyboard events out of a sandboxed (no allow-same-origin) iframe so
// the parent can drive slide navigation. Trusted: authored here, not by the LLM.
export const KEY_BRIDGE_SCRIPT = `
<script>
  document.addEventListener('keydown', function (e) {
    parent.postMessage({
      type: 'tellr:slide-key',
      key: e.key, code: e.code, shiftKey: e.shiftKey,
      ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey
    }, '*');
  }, true);
</script>`;

// Uniform root-slide reset shared by EVERY render/export surface (tile and
// visual-editor previews, filmstrip, presentation, screenshot capture, PDF,
// PPTX chart capture, records-walker composite, standalone HTML export; the
// Python huashu / Google-Slides builder carries a byte-identical mirror,
// parity-pinned by tests/unit/test_export_csp.py). The slide ROOT — the
// direct child of <body> or of a surface's .slide-container wrapper — is
// pinned to the frame origin and flattened: a PPTX canvas cannot render root
// rounding or shadows, so preview/export parity is only achievable by
// stripping them on every surface. Inner elements keep their radius/shadow.
// The :not(#…) clause never matches (no such id is ever minted); it lifts
// each arm to id-level specificity so the reset outguns deck-authored
// !important card styling (".slide { margin: 40px auto !important }" and
// friends) no matter where a surface injects it relative to deck CSS.
export const SLIDE_ROOT_RESET_STYLE = `
  body > :not(#tellr-root-reset-boost),
  .slide-container > :not(#tellr-root-reset-boost) {
    margin: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
  }
`;

/** The fixed 16:9 frame every preview surface renders a single slide into. */
export const SLIDE_FRAME_W = 1280;
export const SLIDE_FRAME_H = 720;

/**
 * The slide-host frame contract: give `hostSelector` the fixed frame and STRETCH
 * ITS CHILD to fill it.
 *
 * Why the child, and not just the host. Design-system templates nest the slide
 * two levels deep — a wrapper element (`<section>`) carries the deck background
 * via a bare TYPE selector, and inside it `.slide` is `position: absolute;
 * inset: 0`. Because the slide is out of flow, the wrapper has no in-flow
 * content and collapses to `height: 0`. The collapsed element is the one
 * carrying the background, so the deck background never paints and whatever is
 * behind it (typically the deck's own dark `html,body` background) shows
 * through. `color` and `font-family` still apply — they inherit — which is why
 * the result is READABLE DARK-ON-DARK rather than an obviously blank slide.
 * The absolute slide also escapes its static wrapper and resolves against the
 * viewport, so the same surfaces lay content out against the wrong height.
 *
 * Sizing the ROOT does not fix this: the wrapper stays a static-flow child and
 * still collapses. Only stretching the host's CHILD gives the
 * background-carrying element area. Presentation mode was the one surface that
 * already declared such a rule, which is the only reason it escaped the defect;
 * this is that rule, promoted so every surface shares one mechanism.
 *
 * Every declaration is load-bearing (each was measured by removing it):
 *  - host `position: relative` — else the absolute slide escapes to the viewport
 *  - host width/height — else the frame collapses and nothing has area
 *  - child `height: 100%` — the actual fix; a sized, positioned host is not enough
 *  - child `box-sizing: border-box` — slide roots are content-box with a safe-area
 *    padding, so a bare `width/height: 100%` overshoots the frame
 *  - `overflow: hidden` — else a preview grows where an export clips
 *  - `!important`, at id-level specificity via the `:not(#…)` clause (which never
 *    matches — no such id is ever minted) — templates author their own
 *    `position` on the slide root and would otherwise reintroduce the collapse
 *
 * `.slide-wrapper` is excluded deliberately: that is the per-slide block of the
 * standalone MULTI-slide HTML export, where every block is meant to stay in flow
 * and scroll. Stretching those to one frame would stack the whole deck into a
 * single pile, so the contract is written to be incapable of it wherever it is
 * injected.
 */
export function slideHostFrameStyle(hostSelector: string): string {
  return `
  ${hostSelector} {
    position: relative !important;
    width: ${SLIDE_FRAME_W}px !important;
    height: ${SLIDE_FRAME_H}px !important;
    overflow: hidden;
  }
  ${hostSelector} > :not(#tellr-host-frame-boost):not(.slide-wrapper) {
    position: absolute !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    box-sizing: border-box !important;
    overflow: hidden;
  }
`;
}

// Layout reset for fixed-frame preview surfaces (slide tiles, visual editor).
// The UA's default 8px body margin alone pushes 1280x720 content past the
// frame and draws scrollbars inside the preview; these surfaces clip instead
// (the filmstrip and presentation mode carry their own frame sizing). The
// shared root reset pins the slide root to the frame origin instead of
// truncating its bottom edge, and the frame contract gives a
// background-carrying slide wrapper the area it needs to paint at all.
export const SLIDE_PREVIEW_RESET_STYLE = `
  html, body { margin: 0; padding: 0; overflow: hidden; }
  ${SLIDE_ROOT_RESET_STYLE}
  ${slideHostFrameStyle('body')}
`;

export interface SlideDocumentOptions {
  css?: string;
  externalScripts?: string[];
  /** Inline chart-init JS (already validated server-side). */
  scripts?: string;
  /** Extra CSS appended after deck CSS (layout resets etc.). */
  extraHeadStyle?: string;
  /** Include the keyboard bridge (presentation mode only). */
  includeKeyBridge?: boolean;
}

/** Build a complete, CSP-protected HTML document for a single slide. */
export function buildSlideDocument(
  slideHtml: string,
  opts: SlideDocumentOptions = {}
): string {
  const externalScriptsHtml = (opts.externalScripts ?? [])
    .map((src) => `<script src="${src}"></script>`)
    .join('\n');
  const css = opts.css ?? '';
  const extra = opts.extraHeadStyle ?? '';
  const scripts = opts.scripts ?? '';
  const bridge = opts.includeKeyBridge ? KEY_BRIDGE_SCRIPT : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  ${CSP_META}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${externalScriptsHtml}
  <style>${css}\n${extra}</style>
</head>
<body>
  ${slideHtml}
  ${scripts ? `<script>${scripts}</script>` : ''}
  ${bridge}
</body>
</html>`;
}

/**
 * Standalone multi-slide HTML document for the "Save as HTML" export. Pure on
 * the deck so the slide-surface-fidelity spec can pin its layout guarantees
 * the same way it pins the pdf/pptx/screenshot documents.
 */
export function buildStandaloneDeckDocument(deck: SlideDeck): string {
  const slidesHtml = deck.slides
    .map((slide, index) => {
      const slideScripts = slide.scripts || '';
      return `
    <div class="slide-wrapper" data-slide-index="${index}">
      <div class="slide-container">
        ${slide.html}
      </div>
      ${slideScripts ? `<script>
        (function() {
          ${slideScripts}
        })();
      </script>` : ''}
    </div>`;
    })
    .join('\n');

  // Multi-slide wrapper/reset layout for the standalone export document.
  const wrapperStyle = `
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    html, body {
      width: 100%;
      height: 100%;
      overflow: auto;
      background: #f9fafb;
    }
    body {
      padding: 40px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 40px;
    }
    .slide-wrapper {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      page-break-after: always;
    }
    .slide-container {
      width: 1280px;
      height: 720px;
      max-width: 100%;
      max-height: calc(100vh - 80px);
      position: relative;
      background: #ffffff;
      overflow: auto;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      border-radius: 8px;
    }
    .slide-container > * {
      width: 100%;
      min-height: 100%;
    }
    canvas {
      max-width: 100%;
      height: auto;
    }
    ${SLIDE_ROOT_RESET_STYLE}`;

  const bootstrapScripts = `
    function waitForChartJs(callback, maxAttempts = 50) {
      let attempts = 0;
      const check = () => {
        attempts++;
        if (typeof Chart !== 'undefined') {
          callback();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 100);
        } else {
          console.error('Chart.js failed to load');
        }
      };
      check();
    }

    function initializeCharts() {
      try {
        ${deck.scripts || ''}
      } catch (err) {
        console.error('Chart initialization error:', err);
      }
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        waitForChartJs(initializeCharts);
      });
    } else {
      waitForChartJs(initializeCharts);
    }`;

  return buildSlideDocument(
    `<title>${deck.title || 'Presentation'}</title>\n${slidesHtml}`,
    {
      css: deck.css,
      externalScripts: deck.external_scripts,
      extraHeadStyle: wrapperStyle,
      scripts: bootstrapScripts,
    }
  );
}
