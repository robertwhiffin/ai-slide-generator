/**
 * How long the object URL outlives the click. Safari and Firefox have historically failed a
 * download whose blob URL was revoked synchronously; a small text blob held for 10 s costs nothing.
 */
export const REVOKE_DELAY_MS = 10_000;

/**
 * Save `text` as a file named `filename`, through a transient object URL and <a download>.
 *
 * Deliberately NOT the synchronous revoke of hooks/useDeckExport.ts: that path's only Playwright
 * test checks the filename, not the bytes.
 */
export function downloadTextFile(text: string, filename: string, mimeType: string): void {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
