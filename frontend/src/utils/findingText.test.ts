/**
 * findingText — the drawer's plain-text getters and the Apply/Discuss request
 * writers (#316, plan Task 4, decisions D3/D4/D6).
 *
 * Every expected request string is spelled out from the plan's constants as
 * LITERAL strings (`LITERAL_*` below), never rebuilt from the module's own
 * exports, so a drifted constant goes red here as well as in the Python pin
 * (tests/unit/test_finding_conformance.py::
 * TestFindingConformance::test_ts_reviewer_details_separator_matches_python).
 *
 * TECH is the #316 example message verbatim (hex codes, `≈`, `—` and the
 * double quotes kept): it is what the plain lead must never carry and what
 * the details part must carry byte-for-byte.
 *
 * Sabotage notes (each turns the named tests red):
 *  - Build the lead from `findingPlainText(f)` / `f.plainMessage` instead of
 *    `findingPlainIssue(f)` -> both writers' strict-equality and
 *    "never the status sentence" tests.
 *  - Drop the `+ 1` on `slideIndex` -> the strict-equality and 1-based tests.
 *  - Drop `.trim()` from the `withReviewerDetails` guard -> the
 *    whitespace-only-message cases of "a blank message gives exactly the lead".
 *  - Fall back to `f.message` (or `f.plainMessage` in `findingPlainIssue`)
 *    instead of PLAIN_MESSAGE_FALLBACK -> the fallback tests.
 *  - Change any of the three constants -> "the constants are the plan's values".
 */
import { describe, expect, it } from 'vitest';
import {
  APPLY_REQUEST_LEAD,
  DISCUSS_REQUEST_LEAD,
  REVIEWER_DETAILS_SEPARATOR,
  applyFindingRequest,
  discussFindingRequest,
  findingPlainIssue,
  findingPlainText,
} from './findingText';
import { PLAIN_MESSAGE_FALLBACK, type SlideFinding } from '../types/finding';

/** The technical message quoted in #316, verbatim. */
const TECH =
  'The "NOTE" label in the bottom callout is Coral #FF5F46 at 13px/700 over the ' +
  'box fill (rgba(255,95,70,0.12) composited on navy #1B3139 ≈ #2D3A3C), ' +
  'giving roughly 3.9:1 — below the 4.5:1 AA floor for text this size. The ' +
  "template's own dark-background eyebrow colour (#FFC9BF) clears AA; use that " +
  'instead of raw coral.';

/** Plan D8, contrast_failure, open + objective (what the projection derives). */
const I = 'Some text is hard to read against its background.';
const STATUS = 'This was not fixed automatically.';
const M = `${I} ${STATUS}`;

/** Plan D4 constants, as literals. */
const LITERAL_SEPARATOR = "\n\nReviewer's details:\n";
const LITERAL_APPLY_LEAD = 'Please fix this on slide';
const LITERAL_DISCUSS_LEAD = "I'd like to discuss this on slide";

const finding: SlideFinding = {
  id: 'f-316',
  slideIndex: 2,
  category: 'design',
  criterion: 'contrast_failure',
  message: TECH,
  plainMessage: M,
  plainIssue: I,
  objective: true,
  status: 'open',
  seen: false,
};

/** Values a stale cache or an untyped mock can hand the frontend. */
const BLANK_OR_MISSING: Array<[string, unknown]> = [
  ['empty', ''],
  ['whitespace only', '   '],
  ['undefined', undefined],
  ['null', null],
];

describe('findingText — the constants are the plan\'s values', () => {
  it('REVIEWER_DETAILS_SEPARATOR, APPLY_REQUEST_LEAD and DISCUSS_REQUEST_LEAD', () => {
    expect(REVIEWER_DETAILS_SEPARATOR).toBe(LITERAL_SEPARATOR);
    expect(APPLY_REQUEST_LEAD).toBe(LITERAL_APPLY_LEAD);
    expect(DISCUSS_REQUEST_LEAD).toBe(LITERAL_DISCUSS_LEAD);
  });
});

describe('findingPlainText', () => {
  it('returns plainMessage, not the technical message', () => {
    expect(findingPlainText(finding)).toBe(M);
  });

  it('trims plainMessage', () => {
    expect(findingPlainText({ ...finding, plainMessage: `\n  ${M} \t` })).toBe(M);
  });

  it.each(BLANK_OR_MISSING)(
    'falls back to PLAIN_MESSAGE_FALLBACK (never the technical message) when plainMessage is %s',
    (_label, value) => {
      const f = { ...finding, plainMessage: value } as unknown as SlideFinding;
      expect(findingPlainText(f)).toBe(PLAIN_MESSAGE_FALLBACK);
    },
  );
});

describe('findingPlainIssue', () => {
  it('returns plainIssue, not plainMessage or the technical message', () => {
    expect(findingPlainIssue(finding)).toBe(I);
  });

  it('trims plainIssue', () => {
    expect(findingPlainIssue({ ...finding, plainIssue: `\n  ${I} \t` })).toBe(I);
  });

  it.each(BLANK_OR_MISSING)(
    'falls back to PLAIN_MESSAGE_FALLBACK (never plainMessage or the technical message) when plainIssue is %s',
    (_label, value) => {
      const f = { ...finding, plainIssue: value } as unknown as SlideFinding;
      expect(findingPlainIssue(f)).toBe(PLAIN_MESSAGE_FALLBACK);
    },
  );
});

describe.each([
  { name: 'applyFindingRequest', write: applyFindingRequest, lead: LITERAL_APPLY_LEAD },
  { name: 'discussFindingRequest', write: discussFindingRequest, lead: LITERAL_DISCUSS_LEAD },
])('$name', ({ write, lead }) => {
  it('is the plain lead, the separator, then the technical message verbatim (strict)', () => {
    expect(write(finding)).toBe(`${lead} 3: ${I}${LITERAL_SEPARATOR}${TECH}`);
  });

  it('leads with plainIssue, never plainMessage: no status sentence (review #2)', () => {
    const out = write(finding);
    expect(out).not.toContain(M);
    expect(out).not.toContain(STATUS);
  });

  it('keeps the technical message out of the lead and puts it, whole, after the first separator', () => {
    const out = write(finding);
    const at = out.indexOf(LITERAL_SEPARATOR);
    expect(at).toBeGreaterThan(0);
    const head = out.slice(0, at);
    expect(head).toBe(`${lead} 3: ${I}`);
    expect(head).not.toContain(TECH);
    expect(head).not.toContain('#FF5F46');
    expect(out.slice(at + LITERAL_SEPARATOR.length)).toBe(TECH);
  });

  it('carries a multi-line technical message verbatim', () => {
    const multi = `${TECH}\nSecond line:\n  - indented point`;
    expect(write({ ...finding, message: multi })).toBe(
      `${lead} 3: ${I}${LITERAL_SEPARATOR}${multi}`,
    );
  });

  it.each([
    [0, 1],
    [2, 3],
    [9, 10],
  ])('numbers the slide 1-based (slideIndex %i -> slide %i)', (slideIndex, slideNumber) => {
    expect(write({ ...finding, slideIndex })).toBe(
      `${lead} ${slideNumber}: ${I}${LITERAL_SEPARATOR}${TECH}`,
    );
  });

  it.each([
    ['empty', ''],
    ['whitespace only', '   '],
    ['newlines and tabs', '\n\t \n'],
  ])('a blank message (%s) gives exactly the lead, with no separator', (_label, message) => {
    const out = write({ ...finding, message });
    expect(out).toBe(`${lead} 3: ${I}`);
    expect(out).not.toContain("Reviewer's details");
  });

  it.each(BLANK_OR_MISSING)(
    'a plainIssue that is %s leads with PLAIN_MESSAGE_FALLBACK',
    (_label, value) => {
      const f = { ...finding, plainIssue: value } as unknown as SlideFinding;
      expect(write(f)).toBe(`${lead} 3: ${PLAIN_MESSAGE_FALLBACK}${LITERAL_SEPARATOR}${TECH}`);
    },
  );
});
