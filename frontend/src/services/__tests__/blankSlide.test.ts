/**
 * #314 Task 7: the TS twin of the structural blank-slide predicates (plan D4, D11; PLAN-CORRECTIONS C4).
 *
 * The rows are NOT restated here. They are read from the case table the Python predicates are tested
 * against (tests/fixtures/blank_slide_cases.json, Task 1), so the two languages answer one table: a row
 * the TS predicate gets wrong is a row where the auto-verify skip, the Spec view label and the Markdown
 * export would disagree with the architect's N1/N2 guards about which slide is blank. Read the table's
 * `about` field for the rules (HTML ASCII whitespace only; the `slide` token is case-sensitive; anything
 * DOMParser hoists into <head> is off the root->.slide chain).
 *
 * One `it` per row (it.each), so a failure names the row.
 *
 * SABOTAGE (each run against a throwaway implementation in a copy, then reverted):
 *   - the text test uses `trim()` (JS whitespace)                -> nbsp / U+00A0 / U+FEFF / U+3000 / VT rows RED
 *   - the walk finds the slide with `querySelector('.slide')` or `matches('.slide')`
 *     (case-INSENSITIVE: DOMParser text/html with no doctype is quirks mode) -> 'capitalised class Slide' RED
 *   - the walk starts at <body> and ignores <head>               -> 'a style element before the root' RED
 *   - the predicate ignores text                                 -> 'text inside the slide' (and others) RED
 *   - no `<div>` wrapper requirement (any .slide element)        -> 'section.slide alone' RED
 *   - the spec predicate uses `trim()`                           -> the U+00A0 / U+FEFF / U+3000 / VT spec rows RED
 *   - the spec predicate needs only ONE empty field              -> 'purpose set' / 'brief set' RED
 *   - BLANK_SLIDE_HTML drifts from the Python constant           -> the constant test RED
 */
import { describe, expect, it } from 'vitest';
import casesJson from '../../../../tests/fixtures/blank_slide_cases.json?raw';
import deckSpecSlidesPy from '../../../../src/domain/deck_spec_slides.py?raw';
import { BLANK_SLIDE_HTML, isBlankSlideHtml, isBlankSlideSpec } from '../blankSlide';

interface HtmlCase { name: string; html: string; blank: boolean }
interface SpecCase { name: string; purpose: string; content_brief: string; blank: boolean }

const TABLE: { about: string; html_cases: HtmlCase[]; spec_cases: SpecCase[] } = JSON.parse(casesJson);
const HTML_CASES = TABLE.html_cases;
const SPEC_CASES = TABLE.spec_cases;

/** The Python constant, read as text: `BLANK_SLIDE_HTML = '<div class="slide"></div>'` (either quote). */
const PY_CONSTANT = /^BLANK_SLIDE_HTML\s*(?::[^=\n]+)?=\s*(['"])(.*?)\1\s*(?:#.*)?$/m.exec(deckSpecSlidesPy);

describe('the shared case table (preconditions: the rows were read at all)', () => {
  it('has both outcomes in each half, with unique row names', () => {
    // A table that failed to parse into rows, or lost one outcome, would let every it.each below pass
    // vacuously (or not run at all).
    expect(HTML_CASES.length).toBeGreaterThanOrEqual(30);
    expect(SPEC_CASES.length).toBeGreaterThanOrEqual(10);
    expect(new Set(HTML_CASES.map((c) => c.blank))).toEqual(new Set([true, false]));
    expect(new Set(SPEC_CASES.map((c) => c.blank))).toEqual(new Set([true, false]));
    expect(new Set(HTML_CASES.map((c) => c.name)).size).toBe(HTML_CASES.length);
    expect(new Set(SPEC_CASES.map((c) => c.name)).size).toBe(SPEC_CASES.length);
  });

  it('carries the rows C4 added (so this suite exercises the cross-language rules)', () => {
    const names = new Set(HTML_CASES.map((c) => c.name));
    for (const name of [
      'capitalised class Slide',
      'a style element before the root',
      'nbsp entity text',
      'U+FEFF text',
      'leading comment and whitespace before the root',
    ]) {
      expect(names.has(name), name).toBe(true);
    }
  });
});

describe('isBlankSlideHtml answers the shared case table', () => {
  it.each(HTML_CASES)('$name -> blank: $blank', ({ html, blank }) => {
    expect(isBlankSlideHtml(html)).toBe(blank);
  });

  it.each([['null', null], ['undefined', undefined]])('%s is not a blank row', (_label, html) => {
    expect(isBlankSlideHtml(html)).toBe(false);
  });
});

describe('isBlankSlideSpec answers the shared case table', () => {
  it.each(SPEC_CASES)('$name -> blank: $blank', ({ purpose, content_brief, blank }) => {
    expect(isBlankSlideSpec({ purpose, content_brief })).toBe(blank);
  });
});

// ── beyond the shared table (added at review) ────────────────────────────────
//
// Rows the shared table does not carry, each one's expected value PROBED against the committed Python
// predicate (`uv run python`, 2026-10-21) rather than reasoned. Candidates for the shared table
// (Task 1's file) so pytest pins them too.
//
// SABOTAGE:
//   - drop the `has_slide_wrapper` gate (SLIDE_DIV_RE)      -> 'unquoted class' / 'encoded space' RED
//   - the head check looks only for <style>                 -> the meta / link / title / script / base / noscript / template rows RED
//   - a non-string field counts as empty                    -> the non-string spec rows RED
//   - a missing / null field counts as set                  -> the missing / null spec rows RED
describe('isBlankSlideHtml beyond the shared table (Python answers probed)', () => {
  it.each<[string, string, boolean]>([
    // Python's first gate is `has_slide_wrapper`, a regex over the raw string that needs a quoted class.
    ['unquoted class', '<div class=slide></div>', false],
    ['an entity-encoded space in the class', '<div class="dark&#32;slide"></div>', false],
    ['an unquoted WRAPPER class over a quoted slide', '<section class=w><div class="slide"></div></section>', true],
    // DOMParser hoists every head-only element that comes before the root into <head>: all off-chain.
    ['a meta before the root', '<meta charset="utf-8"><div class="slide"></div>', false],
    ['a link before the root', '<link rel="stylesheet" href="x.css"><div class="slide"></div>', false],
    ['a title before the root', '<title>Deck</title><div class="slide"></div>', false],
    ['a script before the root', '<script>1</script><div class="slide"></div>', false],
    ['a base before the root', '<base href="https://x/"><div class="slide"></div>', false],
    ['a noscript before the root', '<noscript></noscript><div class="slide"></div>', false],
    ['a template before the root', '<template></template><div class="slide"></div>', false],
    ['a style before a section shell', '<style>.x{}</style><section><div class="slide"></div></section>', false],
  ])('%s: %s -> blank: %s', (_name, html, blank) => {
    expect(isBlankSlideHtml(html)).toBe(blank);
  });
});

describe('isBlankSlideSpec beyond the shared table (Python answers probed)', () => {
  it.each<[string, { purpose?: unknown; content_brief?: unknown }, boolean]>([
    // A missing key or null counts as empty (Python: `.get()` -> None -> empty).
    ['no fields at all', {}, true],
    ['only a position', { position: 2 } as { purpose?: unknown }, true],
    ['both null', { purpose: null, content_brief: null }, true],
    ['null purpose, empty brief', { purpose: null, content_brief: '' }, true],
    ['a missing purpose beside a set brief', { content_brief: 'x' }, false],
    ['a set purpose beside a missing brief', { purpose: 'x' }, false],
    // A non-string value is not blank (unvalidated JSON): Python's `isinstance(value, str)`.
    ['a number purpose', { purpose: 0, content_brief: '' }, false],
    ['an array brief', { purpose: '', content_brief: [] }, false],
    ['a boolean purpose', { purpose: true }, false],
    ['an object purpose', { purpose: {}, content_brief: '' }, false],
  ])('%s: %j -> blank: %s', (_name, entry, blank) => {
    expect(isBlankSlideSpec(entry)).toBe(blank);
  });
});

describe('BLANK_SLIDE_HTML', () => {
  it('is the Python fallback constant, byte for byte, and is itself a blank row', () => {
    expect(PY_CONSTANT, 'BLANK_SLIDE_HTML assignment not found in src/domain/deck_spec_slides.py').not.toBeNull();
    expect(BLANK_SLIDE_HTML).toBe(PY_CONSTANT![2]);
    expect(isBlankSlideHtml(BLANK_SLIDE_HTML)).toBe(true);
  });
});
