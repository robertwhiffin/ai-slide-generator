// frontend/src/services/slideDocument.ts
// AISEC-248 PR1: single source of truth for slide iframe documents.
// Injects a Content-Security-Policy <meta> so LLM-generated slide JS cannot
// exfiltrate data (connect-src 'none' blocks fetch/XHR; img-src data: blocks
// image beacons; scripts only from the Chart.js / Tailwind CDNs).

export const SLIDE_CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; " +
  "style-src 'unsafe-inline'; " +
  "img-src data:; " +
  "font-src data: https://cdn.jsdelivr.net; " +
  "connect-src 'none';";

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
