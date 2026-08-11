/**
 * Sandboxed template-preview DOCUMENT builder — the security-critical core
 * shared by the card thumbnails and the expanded viewer.
 *
 * Pure functions only (no React), so the single hardened document builder can
 * be reused by both surfaces and unit-reasoned about in isolation. The output
 * is only ever rendered inside a FULLY-sandboxed iframe (`sandbox=""` — no
 * scripts, no same-origin); this module supplies the second layer, a strict
 * CSP that blocks the passive-fetch channel sandbox does not cover.
 */

/**
 * CSP for the preview document: uploaded template HTML/CSS must not be able
 * to trigger ANY external network fetch from the frame (img/link tags, css
 * url()/@import — passive egress). The legit live render only needs inline
 * styles plus data:/blob: resources: the /source endpoint resolves
 * {{ds-asset:ID}} handles to data: URIs at serve time, and token CSS arrives
 * inline. sandbox="" on the iframe already blocks scripts/same-origin; this
 * closes the passive-fetch channel sandbox does not.
 */
export const PREVIEW_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:;";

/**
 * A {{ds-asset:ID}} handle that still reaches the builder (a backend that
 * predates serve-time resolution, or an id its resolver could not satisfy)
 * would resolve as a relative URL inside the frame and be refused by the CSP
 * above — one failed-resource console error per occurrence, in every card.
 * Neutralize to the inert `data:,` placeholder (the import rewrite's own
 * convention for unresolvable refs): renders as nothing, never fetches.
 */
const DS_ASSET_HANDLE_RE = /\{\{ds-asset:\d+\}\}/g;

/**
 * Slide roots inside a template layout. Templates mark each slide section with
 * the `slide` class (on `<section>` or `<div>` — see the backend's
 * `_detect_slide_root_tags`), which is what makes a multi-slide template
 * paginable in the viewer.
 */
const SLIDE_ROOT_SELECTOR = '.slide';

/** The fixed 16:9 stage a preview renders into (the deck canvas the cards scale). */
export const PREVIEW_STAGE_W = 1280;
export const PREVIEW_STAGE_H = 720;

/**
 * Shim for custom elements this frame can never upgrade.
 *
 * Scripts NEVER run in a preview frame (`sandbox=""` plus a CSP with no
 * script-src), so a custom element used as the deck harness — Claude Design
 * exports wrap their slide sections in `<deck-stage width="1280" height="720">`
 * — is permanently un-upgraded and therefore permanently matches
 * `:not(:defined)`. Two consequences, both of which blank the whole preview:
 *
 *  1. Authors guard the pre-upgrade flash with
 *     `deck-stage:not(:defined){visibility:hidden}`. Here that hide is
 *     permanent, so every slide inherits `visibility:hidden` and the only
 *     thing left to see is the body background — the reported "dark
 *     rectangle".
 *  2. An un-upgraded custom element is display:inline and contributes no box,
 *     so it never establishes the stage the harness would have built itself.
 *
 * CASCADE: `deck-stage:not(:defined)` scores (0,1,1), so a bare `deck-stage`
 * type rule (0,0,1) would LOSE and the preview would stay blank — `!important`
 * is what actually settles it, independent of author order or specificity.
 *
 * `:not(:defined)` matches only valid-named custom elements that were never
 * registered; built-ins (and non-hyphenated unknown tags) count as defined, so
 * this cannot reach ordinary template markup.
 */
const UNDEFINED_ELEMENT_SHIM =
  '<style>' +
  ':not(:defined){visibility:visible!important}' +
  'body>:not(:defined){display:block!important;position:relative!important;' +
  `width:${PREVIEW_STAGE_W}px!important;height:${PREVIEW_STAGE_H}px!important}` +
  '</style>';

/** Parse layout HTML inertly (no fetch, no script execution). */
function parseLayout(layoutHtml: string): Document {
  return new DOMParser().parseFromString(layoutHtml, 'text/html');
}

/**
 * How many slide sections a template layout contains (0 when it is not
 * structured as slide sections — the whole layout is then one page).
 */
export function countTemplateSlides(layoutHtml: string): number {
  try {
    return parseLayout(layoutHtml).querySelectorAll(SLIDE_ROOT_SELECTOR).length;
  } catch {
    return 0;
  }
}

/**
 * Compose the preview document: the template layout with its token
 * stylesheet resolved and preview-only overflow clipping. Rendered ONLY in a
 * fully-sandboxed iframe.
 *
 * The wrapper is SYNTHESIZED — the CSP meta is the first fetch-capable byte
 * of the document, unconditionally. Injecting into a found <head> is not
 * enough: malformed-but-parser-preserved markup (e.g. an <img> BEFORE the
 * <html> tag) would declare resources ahead of the policy. DOMParser gives
 * browser-grade handling of malformed input without fetching or executing
 * anything; the parsed head content is re-emitted AFTER the guard block and
 * the parsed body (attributes included, via its own serialization) follows.
 *
 * {@link UNDEFINED_ELEMENT_SHIM} trails the template head so a deck harness
 * built from an unregisterable custom element still lays out and is not left
 * hidden by its own pre-upgrade guard.
 *
 * `slideIndex` isolates ONE slide section for the paginated viewer: the other
 * sections are REMOVED from the parsed DOM before serialization rather than
 * hidden with injected CSS, so the surviving slide keeps the template's own
 * cascade exactly (an author `display` value is never fought over) and no
 * extra rules are layered on. Out-of-range or non-slide layouts fall through
 * to the full document unchanged.
 */
export function buildTemplatePreviewDoc(
  layoutHtml: string,
  tokenCss: string | null,
  slideIndex?: number,
): string {
  const inlineLayout = layoutHtml.replace(DS_ASSET_HANDLE_RE, 'data:,');
  const inlineTokenCss = tokenCss ? tokenCss.replace(DS_ASSET_HANDLE_RE, 'data:,') : tokenCss;
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`;
  const previewReset = '<style>html,body{margin:0;overflow:hidden}</style>';
  const guard = cspMeta + (inlineTokenCss ? `<style>${inlineTokenCss}</style>` : '') + previewReset;
  const parsed = parseLayout(inlineLayout);
  if (slideIndex !== undefined) {
    const slides = Array.from(parsed.querySelectorAll(SLIDE_ROOT_SELECTOR));
    if (slides.length > 1 && slideIndex >= 0 && slideIndex < slides.length) {
      slides.forEach((slide, idx) => {
        if (idx !== slideIndex) slide.remove();
      });
    }
  }
  const templateHead = parsed.head?.innerHTML ?? '';
  const templateBody = parsed.body?.outerHTML ?? '<body></body>';
  // The shim trails the template's own head so it wins on cascade ORDER as well
  // as importance; the CSP meta stays the first fetch-capable byte regardless.
  return `<!DOCTYPE html><html><head>${guard}${templateHead}${UNDEFINED_ELEMENT_SHIM}</head>${templateBody}</html>`;
}
