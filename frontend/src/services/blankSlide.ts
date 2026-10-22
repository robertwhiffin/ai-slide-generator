/**
 * The TS twin of the structural blank-slide predicates in src/domain/deck_spec_slides.py
 * (`is_blank_slide_html`, `is_blank_slide_spec`) — #314 plan D4, D11; PLAN-CORRECTIONS C4.
 *
 * A "blank" slide is a frame with nothing on it: what Insert slide adds, and what the architect leaves
 * alone on an edit turn. Three places decide blankness on the client and must agree with each other and
 * with the backend: the auto-verify skip (`useAutoVerification`), the Spec view's "Blank slide" label and
 * the Markdown export. They all call this module. `tests/fixtures/blank_slide_cases.json` is the shared
 * case table both languages are tested against; read its `about` field for the rules.
 *
 * The rules that make the two languages agree (they differ by default):
 *   - Whitespace is HTML's ASCII whitespace `[\t\n\f\r ]` ONLY. Never `String.trim()`: it strips U+00A0,
 *     U+FEFF, U+3000, VT and more, which Python's `str.strip()` and the backend predicate do not.
 *   - The `slide` class token is matched case-sensitively, with `classList.contains`. Never
 *     `querySelector('.slide')` / `matches`: `DOMParser` `text/html` with no doctype is in quirks mode,
 *     where a class selector matches `class="Slide"`.
 *   - The terminal `.slide` must itself be a `<div>`, so `<section class="slide">` or an `<img
 *     class="slide">` is not a blank row.
 */

/** The fallback blank row, byte-identical to `BLANK_SLIDE_HTML` in src/domain/deck_spec_slides.py. */
export const BLANK_SLIDE_HTML = '<div class="slide"></div>';

/** HTML's ASCII whitespace (the WHATWG set), whole string. `$` without the `m` flag is end-of-input only. */
const ONLY_HTML_WHITESPACE = /^[\t\n\f\r ]*$/;

/**
 * `_SLIDE_DIV_RE` in src/domain/slide.py (`has_slide_wrapper`), the Python predicate's first gate, over
 * the RAW string (same pattern as Message.tsx's SLIDE_DIV_PATTERN). Without it the DOM walk alone
 * accepts `<div class=slide>` (unquoted) and `class="dark&#32;slide"` (an encoded space), which Python
 * rejects. It is a gate only: markup in a comment or an attribute value satisfies it, so the walk below
 * still checks the element.
 */
const SLIDE_DIV_RE = /<div\b[^>]*\bclass\s*=\s*["'](?:[^"']*\s)?slide(?:\s[^"']*)?["']/i;

const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const COMMENT_NODE = 8;

/** The element children of *node*, or null when it holds text that is not HTML whitespace (or a node we cannot classify). Comments are ignored. */
function elementChildren(node: Element): Element[] | null {
  const elements: Element[] = [];
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === COMMENT_NODE) continue;
    if (child.nodeType === ELEMENT_NODE) {
      elements.push(child as Element);
    } else if (child.nodeType === TEXT_NODE) {
      if (!ONLY_HTML_WHITESPACE.test((child as Text).data)) return null;
    } else {
      return null;
    }
  }
  return elements;
}

/**
 * True iff *html* is a blank row: a slide frame with nothing on it.
 *
 * The raw string has a `<div>` slide wrapper (`SLIDE_DIV_RE`, Python's `has_slide_wrapper`), and the
 * fragment is a single chain of elements from one top-level root down to its first `.slide`, each
 * chain element holding exactly one element child and the `.slide` none; that `.slide` is itself a
 * `<div>`; every text node is HTML ASCII whitespace; comments are ignored; attributes do not matter.
 * Anything the parser hoists into `<head>` (a `<style>`, `<meta>`, `<link>`, `<title>`, `<script>` or
 * `<base>` ahead of the root) is off that chain, so it is not blank.
 *
 * Known divergences from Python, where html.parser and DOMParser build different trees (the case
 * table leaves them out on purpose): a `<p>`, `<table>` or `<svg>` around the slide, or a stray
 * `</p>`, is blank in Python and not here; an explicit `<html><head></head><body>`, a doctype, CDATA,
 * a processing instruction or a NUL is blank here and not in Python. Each is an empty frame either
 * way, and the auto-verify skip is the only caller that can see the difference.
 */
export function isBlankSlideHtml(html: string | null | undefined): boolean {
  if (!html || !SLIDE_DIV_RE.test(html)) return false;

  const doc = new DOMParser().parseFromString(html, 'text/html');
  if (doc.head && doc.head.children.length > 0) return false;

  let node: Element | null = doc.body;
  while (node) {
    const elements = elementChildren(node);
    if (elements === null) return false;
    // The body (and every wrapper) carries no `slide` of its own to stop at: the chain continues
    // through its single element child until the first `.slide`.
    if (elements.length !== 1) return false;
    const child = elements[0];
    if (child.classList.contains('slide')) {
      return child.localName === 'div' && elementChildren(child)?.length === 0;
    }
    node = child;
  }
  return false;
}

/**
 * True iff the entry's `purpose` and `content_brief` are both empty. Empty is HTML ASCII whitespace
 * only (the same rule as `isBlankSlideHtml`'s text); a missing field or `null` counts as empty; a
 * non-string value is not blank. No other field decides it.
 */
export function isBlankSlideSpec(entry: { purpose?: unknown; content_brief?: unknown }): boolean {
  for (const value of [entry.purpose, entry.content_brief]) {
    if (value === undefined || value === null) continue;
    if (typeof value !== 'string' || !ONLY_HTML_WHITESPACE.test(value)) return false;
  }
  return true;
}
