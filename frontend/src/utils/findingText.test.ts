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
 *
 * Task 7 (decision D14) adds the chat-collapse parsers `splitFindingRequest`
 * (role user) and `splitDeckAdvisory` (role assistant) and the three deck
 * constants.  Their expected inputs are the writers' exact outputs, spelled as
 * literals: the TS writers above, and `nodes._advisory_text`'s output copied
 * verbatim from tests/unit/test_graph_nodes.py::TestDeckAdvisoryIsPlain.
 * Sabotage notes for those (each turns the named tests red):
 *  - Either parser always returns null -> every round trip and every
 *    "accepts the Python output" case (and the Message bubble tests).
 *  - Split at the LAST separator (lastIndexOf) -> "the lead is everything
 *    before the FIRST separator".
 *  - Drop the `details.trim() !== ''` guard -> the blank-tail cases.
 *  - Drop the `^`/`$` anchors, or loosen `[1-9]\d*` / `[^\n]+` / `(?:- …\n)+`
 *    -> the wrong-lead, prefixed, suffixed, newline-in-lead, slide 0,
 *    0 things and no-bullet cases.
 *  - Drop the closing-line requirement -> "the closing line altered".
 *
 * #316 M3: those literals are hand copies, so a Python format edit with its own
 * goldens updated would leave them green while the parser stopped matching.
 * The shared golden frontend/tests/fixtures/deckAdvisoryGoldens.json closes
 * that: tests/unit/test_finding_conformance.py::TestDeckAdvisoryGolden requires
 * it to equal the real writer's output, and "the shared golden" below requires
 * `splitDeckAdvisory` to return each recorded split.  Sabotage notes:
 *  - Require `things` only (drop the `?`) -> the golden's single-finding cases.
 *  - Write the plain lines as `* ` bullets, or join them with "\n\n", in
 *    nodes._advisory_text and regenerate the golden -> every golden case with
 *    a details section.
 *  Writer edits the parser still accepts (the "(noted N times)" wording, the
 *  details bullets) stay green by design: those advisories still collapse.
 */
import { describe, expect, it } from 'vitest';
import {
  APPLY_REQUEST_LEAD,
  DECK_ADVISORY_CLOSING,
  DECK_ADVISORY_HEADER_PREFIX,
  DECK_ADVISORY_HEADER_SUFFIX,
  DISCUSS_REQUEST_LEAD,
  REVIEWER_DETAILS_SEPARATOR,
  type SplitMessage,
  applyFindingRequest,
  discussFindingRequest,
  findingPlainIssue,
  findingPlainText,
  splitDeckAdvisory,
  splitFindingRequest,
} from './findingText';
import { PLAIN_MESSAGE_FALLBACK, type SlideFinding } from '../types/finding';
import deckAdvisoryGoldens from '../../tests/fixtures/deckAdvisoryGoldens.json';

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

// ---------------------------------------------------------------------------
// Task 7 (D5/D14): the chat-collapse parsers and the deck-advisory constants
// ---------------------------------------------------------------------------

/** Plan D8 deck-advisory constants, as literals (pinned to Python by
 *  tests/unit/test_finding_conformance.py::test_ts_deck_advisory_constants_match_python). */
const LITERAL_DECK_PREFIX = 'Deck review found ';
const LITERAL_DECK_SUFFIX = ' to look at in how the deck reads as a whole:';
const LITERAL_DECK_CLOSING =
  "None of these were changed automatically. Reply here if you'd like any of them addressed.";

/** The writers' leads for `finding` (slideIndex 2 -> slide 3), as literals. */
const APPLY_LEAD_3 = `Please fix this on slide 3: ${I}`;
const DISCUSS_LEAD_3 = `I'd like to discuss this on slide 3: ${I}`;

/** The plan's synthetic deck sample (Task 7 Step 1), built from the literals
 *  exactly as nodes._advisory_text lays it out. */
const SAMPLE_DECK_LEAD =
  `${LITERAL_DECK_PREFIX}2 things${LITERAL_DECK_SUFFIX}\n- A.\n- B.\n${LITERAL_DECK_CLOSING}`;
const SAMPLE_DECK = `${SAMPLE_DECK_LEAD}${LITERAL_SEPARATOR}- m1\n- m2`;

/**
 * nodes._advisory_text's real outputs, byte for byte, with the split each must
 * produce.  Inputs are the findings of the named test in
 * tests/unit/test_graph_nodes.py::TestDeckAdvisoryIsPlain.
 */
const PYTHON_ADVISORIES: Array<{ name: string; content: string; lead: string; details: string }> = [
  {
    name: 'one finding (test_one_finding_reads_as_plain_language_then_details)',
    content:
      'Deck review found 1 thing to look at in how the deck reads as a whole:\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.\n" +
      '\n' +
      "Reviewer's details:\n" +
      '- arc_gap between narrative_arc[1] and positions 3,4 (#1B3139 callout)',
    lead:
      'Deck review found 1 thing to look at in how the deck reads as a whole:\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.",
    details: '- arc_gap between narrative_arc[1] and positions 3,4 (#1B3139 callout)',
  },
  {
    name: '"(noted N times)" (test_repeated_lines_collapse_with_a_count)',
    content:
      'Deck review found 3 things to look at in how the deck reads as a whole:\n' +
      '- The story has a gap or an unexplained jump between slides (noted 2 times).\n' +
      '- The deck has no clear conclusion or call to action.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.\n" +
      '\n' +
      "Reviewer's details:\n" +
      '- Slides 2 and 3 jump from cost to roadmap.\n' +
      '- The last slide restates the agenda.\n' +
      '- Slide 5 introduces a pilot never set up.',
    lead:
      'Deck review found 3 things to look at in how the deck reads as a whole:\n' +
      '- The story has a gap or an unexplained jump between slides (noted 2 times).\n' +
      '- The deck has no clear conclusion or call to action.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.",
    details:
      '- Slides 2 and 3 jump from cost to roadmap.\n' +
      '- The last slide restates the agenda.\n' +
      '- Slide 5 introduces a pilot never set up.',
  },
  {
    name: 'the deck-grain line (test_slide_level_criteria_get_the_deck_grain_line)',
    content:
      'Deck review found 4 things to look at in how the deck reads as a whole:\n' +
      '- One of the slides may need a closer look (noted 3 times).\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.\n" +
      '\n' +
      "Reviewer's details:\n" +
      '- The chart on slide 3 runs off the bottom edge.\n' +
      '- Slide 4 presents results before the method.\n' +
      '- Slide 2 uses an off-palette orange.\n' +
      '- Slide 6 omits the planned timeline.',
    lead:
      'Deck review found 4 things to look at in how the deck reads as a whole:\n' +
      '- One of the slides may need a closer look (noted 3 times).\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.",
    details:
      '- The chart on slide 3 runs off the bottom edge.\n' +
      '- Slide 4 presents results before the method.\n' +
      '- Slide 2 uses an off-palette orange.\n' +
      '- Slide 6 omits the planned timeline.',
  },
  {
    name: 'a two-digit count (test_the_head_never_carries_a_slug_or_a_reviewer_message)',
    content:
      'Deck review found 11 things to look at in how the deck reads as a whole:\n' +
      '- One of the slides may need a closer look (noted 8 times).\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      '- The same point is made on more than one slide.\n' +
      '- The deck has no clear conclusion or call to action.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.\n" +
      '\n' +
      "Reviewer's details:\n" +
      '- MSG-overflow-#ABCDEF\n- MSG-contrast_failure-#ABCDEF\n- MSG-rogue_colour-#ABCDEF\n' +
      '- MSG-distorted_image-#ABCDEF\n- MSG-source_contradiction-#ABCDEF\n' +
      '- MSG-brief_not_delivered-#ABCDEF\n- MSG-arc_gap-#ABCDEF\n' +
      '- MSG-cross_slide_repetition-#ABCDEF\n- MSG-missing_conclusion-#ABCDEF\n' +
      '- MSG-off_template_treatment-#ABCDEF\n- MSG-layout_binding_mismatch-#ABCDEF',
    lead:
      'Deck review found 11 things to look at in how the deck reads as a whole:\n' +
      '- One of the slides may need a closer look (noted 8 times).\n' +
      '- The story has a gap or an unexplained jump between slides.\n' +
      '- The same point is made on more than one slide.\n' +
      '- The deck has no clear conclusion or call to action.\n' +
      "None of these were changed automatically. Reply here if you'd like any of them addressed.",
    details:
      '- MSG-overflow-#ABCDEF\n- MSG-contrast_failure-#ABCDEF\n- MSG-rogue_colour-#ABCDEF\n' +
      '- MSG-distorted_image-#ABCDEF\n- MSG-source_contradiction-#ABCDEF\n' +
      '- MSG-brief_not_delivered-#ABCDEF\n- MSG-arc_gap-#ABCDEF\n' +
      '- MSG-cross_slide_repetition-#ABCDEF\n- MSG-missing_conclusion-#ABCDEF\n' +
      '- MSG-off_template_treatment-#ABCDEF\n- MSG-layout_binding_mismatch-#ABCDEF',
  },
];

/**
 * The shared golden (#316 M3): nodes._advisory_text's outputs, recorded from the
 * real writer and re-checked against it by
 * tests/unit/test_finding_conformance.py::TestDeckAdvisoryGolden, with each
 * output's split at its first separator (`null` when it has none).
 */
const DECK_ADVISORY_GOLDENS: ReadonlyArray<{ name: string; advisory: string; split: SplitMessage | null }> =
  deckAdvisoryGoldens.cases;

/** What the old code wrote; rows stored before #316 keep these (D6, S22). */
const LEGACY_APPLY = `Please apply this review suggestion for slide 2: ${TECH}`;
const LEGACY_DISCUSS = `I'd like to discuss this review finding for slide 2: ${TECH}`;
const LEGACY_ADVISORY =
  'Deck review found 2 narrative issues:\n' +
  '- arc_gap: Slides 2 and 3 jump from cost to roadmap.\n' +
  '- missing_conclusion: The last slide restates the agenda.';
/** The no-findings advisory, byte-identical to before (D5). */
const NO_FINDINGS = 'Deck review complete: no narrative issues found across the deck.';
/** nodes._advisory_text when every reviewer message is blank: no details section. */
const ALL_BLANK_ADVISORY =
  'Deck review found 2 things to look at in how the deck reads as a whole:\n' +
  '- The story has a gap or an unexplained jump between slides.\n' +
  '- The deck has no clear conclusion or call to action.\n' +
  "None of these were changed automatically. Reply here if you'd like any of them addressed.";

describe('findingText — the deck-advisory constants are the plan\'s values (D8)', () => {
  it('DECK_ADVISORY_HEADER_PREFIX, DECK_ADVISORY_HEADER_SUFFIX and DECK_ADVISORY_CLOSING', () => {
    expect(DECK_ADVISORY_HEADER_PREFIX).toBe(LITERAL_DECK_PREFIX);
    expect(DECK_ADVISORY_HEADER_SUFFIX).toBe(LITERAL_DECK_SUFFIX);
    expect(DECK_ADVISORY_CLOSING).toBe(LITERAL_DECK_CLOSING);
  });
});

describe('splitFindingRequest — accepts exactly what the Apply/Discuss writers emit', () => {
  it.each([
    { name: 'applyFindingRequest', write: applyFindingRequest, lead: APPLY_LEAD_3 },
    { name: 'discussFindingRequest', write: discussFindingRequest, lead: DISCUSS_LEAD_3 },
  ])('round-trips $name: the plain lead, and the technical message verbatim', ({ write, lead }) => {
    expect(splitFindingRequest(write(finding))).toStrictEqual({ lead, details: TECH });
  });

  it.each([
    { name: 'applyFindingRequest', write: applyFindingRequest, lead: APPLY_LEAD_3 },
    { name: 'discussFindingRequest', write: discussFindingRequest, lead: DISCUSS_LEAD_3 },
  ])('round-trips $name after ChatPanel trims it before sending', ({ write, lead }) => {
    expect(splitFindingRequest(write(finding).trim())).toStrictEqual({ lead, details: TECH });
  });

  it('accepts the literal Apply and Discuss shapes', () => {
    expect(splitFindingRequest(`${APPLY_LEAD_3}${LITERAL_SEPARATOR}${TECH}`)).toStrictEqual({
      lead: APPLY_LEAD_3,
      details: TECH,
    });
    expect(splitFindingRequest(`${DISCUSS_LEAD_3}${LITERAL_SEPARATOR}${TECH}`)).toStrictEqual({
      lead: DISCUSS_LEAD_3,
      details: TECH,
    });
  });

  it('accepts a multi-digit slide number', () => {
    expect(splitFindingRequest(applyFindingRequest({ ...finding, slideIndex: 11 }))).toStrictEqual({
      lead: `Please fix this on slide 12: ${I}`,
      details: TECH,
    });
  });

  it('accepts the fallback lead a finding without plainIssue gets', () => {
    const f = { ...finding, plainIssue: undefined } as unknown as SlideFinding;
    expect(splitFindingRequest(discussFindingRequest(f))).toStrictEqual({
      lead: `I'd like to discuss this on slide 3: ${PLAIN_MESSAGE_FALLBACK}`,
      details: TECH,
    });
  });

  it('carries a multi-line technical message verbatim in the details', () => {
    const multi = `${TECH}\nSecond line:\n  - indented point`;
    expect(splitFindingRequest(applyFindingRequest({ ...finding, message: multi }))).toStrictEqual({
      lead: APPLY_LEAD_3,
      details: multi,
    });
  });

  it('the lead is everything before the FIRST separator; later ones stay in the details', () => {
    const details = `first part${LITERAL_SEPARATOR}second part`;
    expect(splitFindingRequest(`${APPLY_LEAD_3}${LITERAL_SEPARATOR}${details}`)).toStrictEqual({
      lead: APPLY_LEAD_3,
      details,
    });
  });

  it('a request written for a blank message has nothing to collapse', () => {
    expect(splitFindingRequest(applyFindingRequest({ ...finding, message: '   ' }))).toBeNull();
  });
});

describe('splitFindingRequest — rejects everything else (D14: strict, legacy never parsed)', () => {
  it.each<[string, string]>([
    ['plain text with no separator', 'Make the title on slide 3 bigger.'],
    ['a valid lead with no separator', APPLY_LEAD_3],
    ['a valid lead, the separator, then nothing', `${APPLY_LEAD_3}${LITERAL_SEPARATOR}`],
    ['a valid lead, the separator, then spaces', `${APPLY_LEAD_3}${LITERAL_SEPARATOR}   `],
    ['a valid lead, the separator, then newlines and tabs', `${DISCUSS_LEAD_3}${LITERAL_SEPARATOR}\n\t \n`],
    ['no lead at all ("Hello")', `Hello${LITERAL_SEPARATOR}x`],
    ['an ordinary message with the exact separator (C5)', "Hello there\n\nReviewer's details:\nnot a finding"],
    ['a lead containing a newline', `Please fix this on slide 3: Some text\nis hard to read.${LITERAL_SEPARATOR}${TECH}`],
    ['text before the lead', `Hi! ${APPLY_LEAD_3}${LITERAL_SEPARATOR}${TECH}`],
    ['a line before the lead', `Hi!\n${APPLY_LEAD_3}${LITERAL_SEPARATOR}${TECH}`],
    ['slide 0', `Please fix this on slide 0: ${I}${LITERAL_SEPARATOR}${TECH}`],
    ['a zero-padded slide number', `Please fix this on slide 03: ${I}${LITERAL_SEPARATOR}${TECH}`],
    ['a negative slide number', `Please fix this on slide -1: ${I}${LITERAL_SEPARATOR}${TECH}`],
    ['no slide number', `Please fix this on slide: ${I}${LITERAL_SEPARATOR}${TECH}`],
    ['nothing after "slide N: "', `Please fix this on slide 3: ${LITERAL_SEPARATOR}${TECH}`],
    ['the legacy Apply request', LEGACY_APPLY],
    ['the legacy Discuss request', LEGACY_DISCUSS],
    ['the legacy Apply lead with a real separator tail', `${LEGACY_APPLY}${LITERAL_SEPARATOR}${TECH}`],
    ['a deck-advisory-shaped string', SAMPLE_DECK],
    ['the Python one-finding advisory', PYTHON_ADVISORIES[0].content],
  ])('%s -> null', (_label, content) => {
    expect(splitFindingRequest(content)).toBeNull();
  });
});

describe('splitDeckAdvisory — accepts exactly what nodes._advisory_text emits', () => {
  it('splits the plan\'s sample into the plain block and the reviewer bullets', () => {
    expect(splitDeckAdvisory(SAMPLE_DECK)).toStrictEqual({
      lead: SAMPLE_DECK_LEAD,
      details: '- m1\n- m2',
    });
  });

  it.each(PYTHON_ADVISORIES)('accepts the Python output: $name', ({ content, lead, details }) => {
    expect(splitDeckAdvisory(content)).toStrictEqual({ lead, details });
  });

  it('carries a multi-line reviewer message verbatim in the details', () => {
    const details = '- Slide 4 presents results\nbefore the method.\n- The last slide restates the agenda.';
    expect(splitDeckAdvisory(`${SAMPLE_DECK_LEAD}${LITERAL_SEPARATOR}${details}`)).toStrictEqual({
      lead: SAMPLE_DECK_LEAD,
      details,
    });
  });

  it('the lead is everything before the FIRST separator; later ones stay in the details', () => {
    const details = `- m1${LITERAL_SEPARATOR}- m2`;
    expect(splitDeckAdvisory(`${SAMPLE_DECK_LEAD}${LITERAL_SEPARATOR}${details}`)).toStrictEqual({
      lead: SAMPLE_DECK_LEAD,
      details,
    });
  });
});

describe('splitDeckAdvisory — rejects everything else (D14: strict, legacy never parsed)', () => {
  const tail = `${LITERAL_SEPARATOR}- m1`;
  it.each<[string, string]>([
    ['the no-findings sentence', NO_FINDINGS],
    ['the no-findings sentence with a real separator tail', `${NO_FINDINGS}${tail}`],
    ['the all-blank-messages advisory (no details section)', ALL_BLANK_ADVISORY],
    ['the legacy slug advisory', LEGACY_ADVISORY],
    ['the legacy slug advisory with a real separator tail', `${LEGACY_ADVISORY}${tail}`],
    ['the failure advisory', 'The deck is complete, but the deck-level review could not be completed this turn.'],
    ['a valid plain block, the separator, then nothing', `${SAMPLE_DECK_LEAD}${LITERAL_SEPARATOR}`],
    ['a valid plain block, the separator, then spaces', `${SAMPLE_DECK_LEAD}${LITERAL_SEPARATOR}   `],
    ['the closing line altered', `${LITERAL_DECK_PREFIX}2 things${LITERAL_DECK_SUFFIX}\n- A.\n- B.\nNone of these were changed.${tail}`],
    ['no closing line', `${LITERAL_DECK_PREFIX}2 things${LITERAL_DECK_SUFFIX}\n- A.\n- B.${tail}`],
    ['text after the closing line', `${SAMPLE_DECK_LEAD} Thanks.${tail}`],
    ['text before the header', `Note: ${SAMPLE_DECK_LEAD}${tail}`],
    ['0 things', `${LITERAL_DECK_PREFIX}0 things${LITERAL_DECK_SUFFIX}\n- A.\n${LITERAL_DECK_CLOSING}${tail}`],
    ['no count', `${LITERAL_DECK_PREFIX}things${LITERAL_DECK_SUFFIX}\n- A.\n${LITERAL_DECK_CLOSING}${tail}`],
    ['no bullet lines', `${LITERAL_DECK_PREFIX}2 things${LITERAL_DECK_SUFFIX}\n${LITERAL_DECK_CLOSING}${tail}`],
    ['a plain line that is not a "- " bullet', `${LITERAL_DECK_PREFIX}1 thing${LITERAL_DECK_SUFFIX}\nA.\n${LITERAL_DECK_CLOSING}${tail}`],
    ['the header suffix altered', `${LITERAL_DECK_PREFIX}2 things to look at:\n- A.\n- B.\n${LITERAL_DECK_CLOSING}${tail}`],
    ['an Apply-shaped string', `${APPLY_LEAD_3}${LITERAL_SEPARATOR}${TECH}`],
    ['an ordinary message with the exact separator (C5)', "Here is the plan.\n\nReviewer's details:\nnone"],
  ])('%s -> null', (_label, content) => {
    expect(splitDeckAdvisory(content)).toBeNull();
  });
});

describe('splitDeckAdvisory — the shared golden (frontend/tests/fixtures/deckAdvisoryGoldens.json, #316 M3)', () => {
  it('loads the golden, with cases the parser must accept and cases it must reject', () => {
    expect(DECK_ADVISORY_GOLDENS.length).toBeGreaterThanOrEqual(10);
    expect(DECK_ADVISORY_GOLDENS.filter((c) => c.split !== null).length).toBeGreaterThanOrEqual(8);
    expect(DECK_ADVISORY_GOLDENS.filter((c) => c.split === null).length).toBeGreaterThanOrEqual(2);
  });

  it.each(DECK_ADVISORY_GOLDENS)('returns the recorded split: $name', ({ advisory, split }) => {
    expect(splitDeckAdvisory(advisory)).toStrictEqual(split);
  });

  it.each(DECK_ADVISORY_GOLDENS)('is never taken for an Apply/Discuss request: $name', ({ advisory }) => {
    expect(splitFindingRequest(advisory)).toBeNull();
  });
});
