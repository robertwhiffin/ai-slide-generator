/**
 * deckSpecMarkdown — the deck-spec Markdown export's contract (#318, plan Task 3; D2, D4, D5, D6).
 *
 * How the tests are shaped, and why:
 *  - The GOLDEN pair (frontend/tests/fixtures/deck-spec-markdown/) pins the exact bytes. It is
 *    the cross-language contract a later backend/MCP renderer must reproduce, so it is compared
 *    byte for byte and its own integrity is a precondition here.
 *  - Escaping is asserted on STRUCTURE, not on escape strings. The output is parsed with a real
 *    CommonMark parser (src/test/markdownStructure.ts). Every hostile value, in every slot, must
 *    leave the block skeleton, the node-type set, the bold-label set and the line layout exactly
 *    as a benign value does, while its text round-trips. Passing those checks IS escaping
 *    correctly; there is no string to game.
 *  - The only string-matched outputs are the GitHub-only characters | ~ $ @ (a CommonMark parser
 *    cannot see them, D4) and the exact control/whitespace code-point sets (a cross-language
 *    contract: D4 spells them out because JavaScript's and Python's `\s` differ).
 *
 * Every test names its sabotage target: the production change that must turn it red.
 * Two groups are preconditions, green with or without a renderer: "parser sanity" proves the
 * structure helpers can see the injections the escaping tests look for, and "golden fixture
 * integrity" proves each half of the golden is really exercised.
 */
import { describe, expect, it, vi } from 'vitest';
import goldenSpecJson from '../../../tests/fixtures/deck-spec-markdown/full.deck-spec.json?raw';
import goldenMarkdown from '../../../tests/fixtures/deck-spec-markdown/full.md?raw';
import type { DeckSpec, ResolvedData, SlideSpec } from '../../types/slide';
import {
  DECK_SPEC_MARKDOWN_MIME,
  deckSpecMarkdownFilename,
  renderDeckSpecMarkdown,
} from '../deckSpecMarkdown';
import {
  ALLOWED_NODE_TYPES,
  blockSkeleton,
  blockTexts,
  headings,
  nodeTypes,
  normaliseText,
  parseMarkdown,
  plainText,
  strongTexts,
  type MdNode,
  type Skeleton,
} from '../../test/markdownStructure';

// ── fixtures and helpers ──────────────────────────────────────────────────────

const GOLDEN: DeckSpec = JSON.parse(goldenSpecJson);
/** A fresh deep copy of the golden input. Tests mutate copies, never GOLDEN. */
const golden = (): DeckSpec => structuredClone(GOLDEN);
const render = renderDeckSpecMarkdown;
const parse = parseMarkdown;
const cp = (codePoint: number): string => String.fromCodePoint(codePoint);
const hex = (codePoint: number): string => `U+${codePoint.toString(16).toUpperCase().padStart(4, '0')}`;
const range = (from: number, to: number): number[] => Array.from({ length: to - from + 1 }, (_, i) => from + i);
const linesOf = (out: string): string[] => out.split('\n');

/** An unvalidated-JSON write: puts a value of the wrong type where the TS type says otherwise. */
function setRaw(target: object, key: string, value: unknown): void {
  (target as Record<string, unknown>)[key] = value;
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Every object's own keys in reverse order, recursively. Arrays keep their order. */
function reverseKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reverseKeys);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).reverse().map(([k, v]) => [k, reverseKeys(v)]));
  }
  return value;
}

/** Every string anywhere in a JSON value. */
function allStrings(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value !== null && typeof value === 'object') return Object.values(value).flatMap(allStrings);
  return [];
}

/** An ASCII-only rendering of a value for test names: invisible characters as escapes. */
function show(value: string): string {
  return JSON.stringify(value).replace(/[^ -~]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/** Node types outside the format's own vocabulary. */
function disallowedTypes(root: MdNode): string[] {
  return [...nodeTypes(root)].filter((t) => !ALLOWED_NODE_TYPES.has(t));
}

/** The top-level block directly after the heading with this (normalised) text. */
function blockAfter(root: MdNode, headingText: string): MdNode | undefined {
  const blocks = root.children ?? [];
  const i = blocks.findIndex((b) => b.type === 'heading' && normaliseText(plainText(b)) === headingText);
  return i >= 0 ? blocks[i + 1] : undefined;
}

/** The raw text from the line `### {heading}` up to (not including) the next heading line. */
function slideBlock(out: string, heading: string): string {
  const start = out.indexOf(`\n### ${heading}\n`);
  if (start < 0) throw new Error(`no "### ${heading}" line in the output`);
  const next = out.indexOf('\n#', start + 1);
  return out.slice(start + 1, next < 0 ? undefined : next + 1);
}

/** D5's line discipline. Empty when the output is LF-only, unpadded, single-spaced and ends in one LF. */
function formatViolations(out: string): string[] {
  const found: string[] = [];
  if (out.includes('\r')) found.push('contains CR');
  if (out.includes('\n\n\n')) found.push('contains two consecutive blank lines');
  if (!out.endsWith('\n') || out.endsWith('\n\n')) found.push('does not end with exactly one LF');
  linesOf(out).forEach((line, i) => {
    if (/^[ \t]|[ \t]$/.test(line)) found.push(`line ${i + 1} has leading/trailing whitespace: ${show(line)}`);
  });
  return found;
}

function renderAudience(audience: string): string {
  const spec = golden();
  spec.audience = audience;
  return render(spec);
}

// ── parser sanity (preconditions) ─────────────────────────────────────────────

describe('parser sanity (preconditions: the helpers can see what the escaping tests look for)', () => {
  // Sabotage target: none in production. These go red only if markdownStructure.ts or the
  // parser stopped reporting structure, which would make every structural assertion vacuous.
  const PROBE = '# a\n\n<b>x</b>\n\n- y\n';

  it('reads an ATX heading with its depth and text', () => {
    expect(headings(parse(PROBE))).toEqual([[1, 'a']]);
  });

  it('reports raw HTML as an html node, which the allowed-type check rejects', () => {
    expect(nodeTypes(parse(PROBE)).has('html')).toBe(true);
    expect(ALLOWED_NODE_TYPES.has('html')).toBe(false);
  });

  it('keeps a list in the block skeleton, so an injected list changes the skeleton', () => {
    const types: string[] = [];
    const visit = (s: Skeleton): void => { types.push(s.type); s.children.forEach(visit); };
    visit(blockSkeleton(parse(PROBE))!);
    expect(types).toContain('list');
    expect(blockSkeleton(parse('x\n'))).not.toEqual(blockSkeleton(parse('- x\n')));
  });

  it('reads a backslash escape as its literal character, so a text round-trip sees through escapes', () => {
    const root = parse('\\# not a heading \\*nor\\* \\[a\\](link) \\<b\\>\n');
    expect(headings(root)).toEqual([]);
    expect(blockTexts(root)).toEqual(['# not a heading *nor* [a](link) <b>']);
    expect([...nodeTypes(root)].sort()).toEqual(['paragraph', 'root', 'text']);
  });

  it('reads **Label:** as a strong node carrying the label text', () => {
    expect(strongTexts(parse('- **Purpose:** x\n'))).toEqual(['Purpose:']);
  });

  it('is strict CommonMark: a GFM table and strikethrough are plain text (hence the one string-match test)', () => {
    const root = parse('| a | b |\n|---|---|\n\n~~gone~~\n');
    expect([...nodeTypes(root)].sort()).toEqual(['paragraph', 'root', 'text']);
  });
});

// ── golden ────────────────────────────────────────────────────────────────────

describe('golden', () => {
  it('renders full.deck-spec.json to full.md byte for byte', () => {
    // Sabotage target: any format change, e.g. `## Audience` -> `## Audience:`.
    expect(render(golden())).toBe(goldenMarkdown);
  });

  it('declares the RFC 7763 Markdown media type with UTF-8', () => {
    // Sabotage target: DECK_SPEC_MARKDOWN_MIME (e.g. 'text/plain').
    expect(DECK_SPEC_MARKDOWN_MIME).toBe('text/markdown;charset=utf-8');
  });
});

// ── golden fixture integrity (preconditions) ──────────────────────────────────

describe('golden fixture integrity (preconditions: every escape and normalisation class is exercised)', () => {
  // Sabotage target: the fixture, not production. If full.deck-spec.json lost one of these, the
  // matching half of the golden would be inert: a renderer mishandling it would still match full.md.
  const values = allStrings(GOLDEN);

  it.each([
    ['a CRLF', '\r\n'], ['<b>', '<b>'], ['*', '*'], ['_', '_'], ['#', '#'], ['|', '|'],
    ['&', '&'], ['$', '$'], ['~', '~'], ['a backtick', '`'],
  ])('some value carries %s', (_label, needle) => {
    expect(values.some((v) => v.includes(needle))).toBe(true);
  });

  it('the narrative arc has a beat starting "2024. " and one starting "- ", in neither sorted nor reversed order', () => {
    const arc = GOLDEN.narrative_arc;
    expect(arc.some((beat) => beat.startsWith('2024. '))).toBe(true);
    expect(arc.some((beat) => beat.startsWith('- '))).toBe(true);
    expect([...arc].sort()).not.toEqual(arc);
    expect([...arc].reverse()).not.toEqual(arc);
  });

  it('the slides carry both slide_type cases, a template_section_index, an empty scalar, an empty list and a position gap', () => {
    const slides = GOLDEN.slides;
    expect(slides.some((s) => s.slide_type === null)).toBe(true);
    expect(slides.some((s) => typeof s.slide_type === 'string' && s.slide_type !== '')).toBe(true);
    expect(slides.some((s) => typeof s.template_section_index === 'number')).toBe(true);
    expect(slides.some((s) => s.assumes === '')).toBe(true);
    expect(slides.some((s) => s.data_references.length === 0)).toBe(true);
    expect(slides.map((s) => s.position)).toEqual([0, 1, 3]);
  });

  const SPECIALS: Array<{ name: string; field: string; get: (s: DeckSpec) => string; code: number }> = [
    { name: 'a tab', field: 'audience', get: (s) => s.audience, code: 0x09 },
    { name: 'U+00A0', field: 'purpose', get: (s) => s.purpose, code: 0xa0 },
    { name: 'U+2028', field: 'slides[0].hands_off', get: (s) => s.slides[0].hands_off, code: 0x2028 },
    { name: 'U+0085', field: 'slides[1].assumes', get: (s) => s.slides[1].assumes, code: 0x85 },
    { name: 'U+001F', field: 'slides[1].purpose', get: (s) => s.slides[1].purpose, code: 0x1f },
  ];
  it.each(SPECIALS)('decoded from its JSON escape, $name sits in $field', ({ get, code }) => {
    expect(get(GOLDEN)).toContain(String.fromCharCode(code));
  });

  it('the fixture files carry no raw control or line-separator characters (the JSON spells them as escapes)', () => {
    // eslint-disable-next-line no-control-regex -- detecting raw control characters is the point
    const RAW_SPECIAL = /[\u0000-\u0009\u000B-\u001F\u007F-\u00A0\u2028\u2029]/;
    expect(goldenSpecJson).not.toMatch(RAW_SPECIAL);
    expect(goldenMarkdown).not.toMatch(RAW_SPECIAL);
    expect(goldenMarkdown.charCodeAt(0)).not.toBe(0xfeff);
    expect(formatViolations(goldenMarkdown)).toEqual([]);
  });
});

// ── structure of the rendered golden ──────────────────────────────────────────

describe('structure of the rendered golden', () => {
  const root = (): MdNode => parse(render(golden()));

  it('has exactly the D2 heading sequence', () => {
    // Sabotage target: reorder, rename or drop a section; a slide heading off by one (`Slide ${position}`).
    expect(headings(root())).toEqual([
      [1, 'Renewal risk, Q3 — EMEA/APAC'], [2, 'Audience'], [2, 'Purpose'], [2, 'Argument'],
      [2, 'Call to action'], [2, 'Narrative arc'], [2, 'Design contract'], [2, 'Slide briefs'],
      [3, 'Slide 1'], [3, 'Slide 2'], [3, 'Slide 4'], [2, 'Data'], [3, 'Synthesis'], [3, 'Figures'], [3, 'Gaps'],
    ]);
  });

  it('builds only the node types the format uses', () => {
    // Sabotage target: drop an escape the golden exercises (`<` -> html, `*` -> emphasis, backtick -> inlineCode).
    expect(disallowedTypes(root())).toEqual([]);
  });

  it('bolds exactly the six slide labels', () => {
    // Sabotage target: drop or rename a label (e.g. omit `Data references`), or bold a value.
    expect(new Set(strongTexts(root()))).toEqual(
      new Set(['Purpose:', 'Content brief:', 'Assumes:', 'Hands off:', 'Slide type:', 'Data references:']),
    );
  });

  it('renders the narrative arc as an ordered list in the given order, neither sorted nor reversed', () => {
    // Sabotage target: `.sort()` or `.reverse()` on the arc.
    const list = blockAfter(root(), 'Narrative arc');
    expect(list?.type).toBe('list');
    expect(list?.ordered).toBe(true);
    expect((list?.children ?? []).map((item) => normaliseText(plainText(item))))
      .toEqual(GOLDEN.narrative_arc.map(normaliseText));
  });
});

// ── escaping (D4), table-driven ───────────────────────────────────────────────

const HOSTILE: string[] = [
  // headings and block quotes
  '# injected heading', '###### h6', 'Issue #', 'C# and F#', '> quoted', '#',
  // list markers, including ones only reached after normalising and trimming
  '- bullet', '+ bullet', '* bullet', '1. ordered', '1) ordered', '2024. a year', '-', '*', '1.',
  '123456789. nine digits', '   - spaced bullet', '\t- tab bullet', '\u00a0# nbsp heading', '\n1. after a newline',
  // thematic breaks and setext underlines
  '---', '***', '___', '- - -', '===', 'x\n===', 'x\n---',
  // code
  '```js', '~~~', '    indented code', '\tindented code', '`inline code`',
  // emphasis
  '*em*', '**strong**', '_em_', '__strong__', 'snake_case_name',
  // links, images and reference definitions
  '[link](http://example.com)', '![image](x.png)', '[ref]: http://example.com', '\\[link](http://x)',
  // raw HTML and autolinks
  '<b>bold</b>', '<script>alert(1)</script>', '<div>', '<!-- comment -->', '<http://example.com>', '\\<b>x\\</b>',
  // entities, backslashes and hard breaks
  '&amp; &copy; &#35;', 'trailing backslash \\', 'hard  \nbreak',
  // an input backslash must not pair with an inserted one (D4: `\` itself is escaped)
  '\\*em\\*', '\\_em\\_', '\\`code\\`',
  // multi-line values collapse onto one line
  'line one\nline two', 'a\r\n\r\nb', 'a\rb', 'para\n\n# heading after blank', 'a\u2028b\u2029c',
  // GFM / GitHub-only syntax (invisible to CommonMark; also string-pinned below)
  '| a | b |\n|---|---|\n| 1 | 2 |', '~~strike~~', '$x$ and $4.2M', '@team mention',
];

interface Slot { name: string; set: (spec: DeckSpec, value: string) => void }

const SLOTS: Slot[] = [
  { name: 'title (H1)', set: (s, v) => { s.title = v; } },
  { name: 'audience (paragraph)', set: (s, v) => { s.audience = v; } },
  { name: 'resolved_data.synthesis (paragraph)', set: (s, v) => { s.resolved_data.synthesis = v; } },
  { name: 'narrative_arc[0] (ordered item start)', set: (s, v) => { s.narrative_arc[0] = v; } },
  { name: 'slides[0].purpose (after a bold label)', set: (s, v) => { s.slides[0].purpose = v; } },
  { name: 'slides[0].slide_type (after a bold label)', set: (s, v) => { s.slides[0].slide_type = v; } },
  { name: 'slides[0].data_references[0] (after a bold label)', set: (s, v) => { s.slides[0].data_references[0] = v; } },
  { name: 'figures[0].key (bullet start)', set: (s, v) => { s.resolved_data.figures[0].key = v; } },
  { name: 'figures[0].value (after "key: ")', set: (s, v) => { s.resolved_data.figures[0].value = v; } },
  { name: 'gaps[0] (bullet start)', set: (s, v) => { s.resolved_data.gaps[0] = v; } },
  // Positions beyond the plan's ten: mid-line after a separator, inside parentheses, and the two
  // numeric slots fed a string by unvalidated JSON (D4 `num`).
  { name: 'slides[1].data_references[1] (after ", ")', set: (s, v) => { s.slides[1].data_references[1] = v; } },
  { name: 'figures[0].source (inside "(source: ...)")', set: (s, v) => { s.resolved_data.figures[0].source = v; } },
  { name: 'slides[0].position as a string (### Slide heading)', set: (s, v) => { setRaw(s.slides[0], 'position', v); } },
  { name: 'design_system_id as a string (after "#")', set: (s, v) => { setRaw(s.design_contract, 'design_system_id', v); } },
];

describe('escaping (D4): every hostile value, in every slot, stays inert text on its own line', () => {
  // Sabotage targets (each turns cases red):
  //  - remove `#`, `<`, `>`, a backtick, `*`, `_`, `&` or `\` from ESCAPE_ANYWHERE, or remove BOTH `[` and `]`
  //    (removing only one bracket stays green, correctly: the other escape already breaks links);
  //  - delete the leading `[-+=]` rule; delete the ordered-marker rule;
  //  - replace WHITESPACE_RUN with `/ +/g`; escape before normalising/trimming;
  //  - render a numeric slot without `num` (raw string position or id).
  const BENIGN = 'benign value';
  const baselines = new Map<string, { out: string; root: MdNode }>();
  function baseline(slot: Slot): { out: string; root: MdNode } {
    let hit = baselines.get(slot.name);
    if (!hit) {
      const spec = golden();
      slot.set(spec, BENIGN);
      const out = render(spec);
      hit = { out, root: parse(out) };
      baselines.set(slot.name, hit);
    }
    return hit;
  }

  it('precondition: every hostile value has visible text and the set exercises every D4 escape class', () => {
    // Sabotage target: the HOSTILE table itself (a value that normalises to '' would round-trip vacuously).
    expect(HOSTILE.filter((v) => normaliseText(v) === '').map(show)).toEqual([]);
    expect(new Set(HOSTILE).size).toBe(HOSTILE.length);
    const missing = [...'\\`*_[]<>#|~$&@'].filter((c) => !HOSTILE.some((v) => v.includes(c)));
    expect(missing).toEqual([]);
    for (const leading of [/^[-+=]/, /^\d{1,9}[.)]( |$)/]) {
      expect(HOSTILE.some((v) => leading.test(normaliseText(v)))).toBe(true);
    }
  });

  // A plain loop rather than it.each: it.each truncates `$name`, and a red case must say which value broke.
  for (const slot of SLOTS) {
    for (const value of HOSTILE) {
      it(`${slot.name} <- ${show(value)}`, () => {
        const base = baseline(slot);
        expect(base.out.split(BENIGN), 'the slot marker occurs once in the baseline').toHaveLength(2);

        const spec = golden();
        slot.set(spec, value);
        const out = render(spec);
        const root = parse(out);
        const text = normaliseText(value);

        // (i) the block skeleton is the benign one: nothing injected, split or merged
        expect(blockSkeleton(root), '(i) block skeleton').toEqual(blockSkeleton(base.root));
        // (ii) only the node types the format itself uses
        expect(disallowedTypes(root), '(ii) node types').toEqual([]);
        // (iii) the bold-label set is unchanged
        expect(strongTexts(root), '(iii) bold labels').toEqual(strongTexts(base.root));
        // (iv) the text round-trips: every heading/paragraph text is the benign one with the value in the
        //      marker's place, so the value is present, intact, and leaks nowhere else
        expect(blockTexts(root), '(iv) text round-trip').toEqual(blockTexts(base.root).map((t) => t.split(BENIGN).join(text)));
        // (v) no CR, no padded line, no double blank line, one trailing LF
        expect(formatViolations(out), '(v) line discipline').toEqual([]);
        // (vi) the value occupies exactly the line it starts on: same line count, one line changed
        const lines = linesOf(out);
        const baseLines = linesOf(base.out);
        expect(lines, '(vi) line count').toHaveLength(baseLines.length);
        expect(lines.filter((line, i) => line !== baseLines[i]), '(vi) lines changed').toHaveLength(1);
      });
    }
  }
});

describe('long values (D4 collapses whitespace but never truncates)', () => {
  // Sabotage target: any length cap, e.g. `.slice(0, 300)` in normalise/escapeText or on one slot's write.
  /** 5,000 characters of distinct numbered tokens, each carrying an escape (`_`): a cut or a dropped piece shows. */
  const LONG = `${Array.from({ length: 625 }, (_, i) => `b_${String(i).padStart(5, '0')}`).join(' ')}.`;
  const LONG_SLOTS: Slot[] = [
    ...SLOTS,
    { name: 'slides[0].content_brief (after a bold label)', set: (s, v) => { s.slides[0].content_brief = v; } },
  ];

  it('precondition: the long value is 5,000 characters of 625 distinct tokens', () => {
    expect(LONG).toHaveLength(5000);
    expect(new Set(LONG.split(' ')).size).toBe(625);
  });

  for (const slot of LONG_SLOTS) {
    it(`${slot.name} renders a 5,000-character value in full`, () => {
      const spec = golden();
      slot.set(spec, LONG);
      const out = render(spec);
      expect(blockTexts(parse(out)).filter((t) => t.includes(LONG)), 'the whole value, in one block').toHaveLength(1);
      expect(formatViolations(out)).toEqual([]);
    });
  }
});

describe('GitHub-only characters (the one string-match test: a CommonMark parser cannot see these, D4)', () => {
  it('escapes | ~ $ @ so GFM tables, strikethrough, math and @-mentions stay inert on GitHub', () => {
    // Sabotage target: drop `|`, `~`, `$` or `@` from ESCAPE_ANYWHERE.
    expect(linesOf(renderAudience('a | b ~~c~~ $d$ @team'))).toContain('a \\| b \\~\\~c\\~\\~ \\$d\\$ \\@team');
  });
});

describe('the ordered-marker rule is exactly CommonMark\'s (a byte-level contract a port must reproduce, D4)', () => {
  it('escapes a leading 1-9 digit marker before a space or the end, and leaves a longer or unspaced one alone', () => {
    // Sabotage targets: widen `\d{1,9}` to `\d+` (a 10-digit "marker" is not a list in CommonMark, so no
    // parse-based test sees the extra escape, but the bytes change); narrow it to `\d{1,8}`; drop `(?= |$)`.
    expect(linesOf(renderAudience('123456789. nine digits'))).toContain('123456789\\. nine digits');
    expect(linesOf(renderAudience('123456789)'))).toContain('123456789\\)');
    expect(linesOf(renderAudience('1234567890. ten digits'))).toContain('1234567890. ten digits');
    expect(linesOf(renderAudience('11.4% of Q4'))).toContain('11.4% of Q4');
  });
});

// ── control characters and whitespace (D4 steps 1 and 2) ─────────────────────

describe('control characters and NEL (D4 steps 1-2: the code-point sets are a cross-language contract)', () => {
  it('removes controls and turns NEL into a space', () => {
    // Sabotage targets: drop the CONTROL_CHARS replace (raw controls remain); move U+0085 from
    // WHITESPACE_RUN into CONTROL_CHARS (gives `nelend`).
    expect(linesOf(renderAudience('nul\u0000 esc\u001b[31m bell\u0007 del\u007f us\u001fx nel\u0085end')))
      .toContain('nul esc\\[31m bell del usx nel end');
  });

  const CONTROL_SET = [...range(0x00, 0x08), ...range(0x0e, 0x1f), ...range(0x7f, 0x84), ...range(0x86, 0x9f)];
  const WHITESPACE_SET = [
    ...range(0x09, 0x0d), 0x20, 0x85, 0xa0, 0x1680, ...range(0x2000, 0x200a), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff,
  ];
  /** Format and zero-width characters in neither set: D4 passes them through (bidi/format is out of scope). */
  const NEITHER = [0x00ad, 0x180e, 0x200b, 0x200c, 0x200d, 0x200e, 0x2060];

  it('removes exactly the D4 control set: U+0000-0008, U+000E-001F, U+007F-0084, U+0086-009F', () => {
    // Sabotage target: narrow CONTROL_CHARS (e.g. stop at U+001F, so C1 controls survive).
    const wrong = CONTROL_SET.filter((code) => !linesOf(renderAudience(`a${cp(code)}b`)).includes('ab'));
    expect(wrong.map(hex)).toEqual([]);
  });

  it('collapses every run of ECMAScript whitespace plus NEL to one space', () => {
    // Sabotage target: WHITESPACE_RUN as `/ +/g`, or as `/\s+/g` (misses NEL), or missing any code point.
    const wrong = WHITESPACE_SET.filter((code) => !linesOf(renderAudience(`a${cp(code)}${cp(code)}b`)).includes('a b'));
    expect(wrong.map(hex)).toEqual([]);
  });

  it('passes through format characters that are in neither set', () => {
    // Sabotage target: widen CONTROL_CHARS or WHITESPACE_RUN beyond D4 (e.g. a `\p{C}` or `\p{Z}`-style class).
    const wrong = NEITHER.filter((code) => !linesOf(renderAudience(`a${cp(code)}b`)).includes(`a${cp(code)}b`));
    expect(wrong.map(hex)).toEqual([]);
  });
});

// ── empty and optional values ─────────────────────────────────────────────────

describe('empty and optional values (D2)', () => {
  const EMPTY: DeckSpec = {
    title: 'Empty plan',
    audience: '',
    purpose: '   ',
    argument: '\n',
    call_to_action: '',
    narrative_arc: [],
    design_contract: { design_system_id: null, template_id: null, slide_style_id: null },
    resolved_data: { synthesis: '', figures: [], gaps: [] },
    slides: [],
  };

  it('renders an empty spec exactly, with its placeholders unescaped', () => {
    // Sabotage target: any placeholder wording, a missing empty-list `None.`, or escaping a placeholder (`Not set\.`).
    expect(render(structuredClone(EMPTY))).toBe(
      '# Empty plan\n\n## Audience\n\nNot set.\n\n## Purpose\n\nNot set.\n\n## Argument\n\nNot set.\n\n'
      + '## Call to action\n\nNot set.\n\n## Narrative arc\n\nNone.\n\n## Design contract\n\n'
      + 'No design system or slide style pinned\n\n## Slide briefs\n\nNone.\n\n## Data\n\n### Synthesis\n\nNot set.\n\n'
      + '### Figures\n\nNone.\n\n### Gaps\n\nNone.\n',
    );
  });

  it('a slide-style-only contract lists just the slide style', () => {
    // Sabotage target: drop the `- Slide style #N` line, or print the null ids.
    const spec = golden();
    spec.design_contract = { design_system_id: null, template_id: null, slide_style_id: 5 };
    expect(render(spec)).toContain('## Design contract\n\n- Slide style #5\n\n');
  });

  it('lists pinned ids in the order design system, template, slide style', () => {
    // Unvalidated JSON may carry all three (L1 is enforced server-side). Sabotage target: reorder the id lines.
    const spec = golden();
    spec.design_contract = { design_system_id: 1, template_id: 2, slide_style_id: 3 };
    expect(render(spec)).toContain('## Design contract\n\n- Design system #1\n- Template #2\n- Slide style #3\n\n');
  });

  it('an id of 0 is pinned, not absent (ids are tested with != null, not truthiness)', () => {
    // Sabotage target: `if (contract.design_system_id)`.
    const spec = golden();
    spec.design_contract = { design_system_id: 0, template_id: 0, slide_style_id: null };
    expect(render(spec)).toContain('## Design contract\n\n- Design system #0\n- Template #0\n\n');
  });

  it('a contract with its id keys absent (pre-field JSON) renders the no-contract sentence', () => {
    // Sabotage target: `!== null` on the ids (an absent id would print `#Not set.`).
    const spec = golden();
    spec.design_contract = {};
    expect(render(spec)).toContain('## Design contract\n\nNo design system or slide style pinned\n\n');
  });

  it.each([['spaces', '   '], ['empty', ''], ['newline and tab', '\n\t'], ['NBSP and U+2028', '\u00a0\u2028']])(
    'a blank title (%s) renders "# Untitled deck spec"',
    (_label, title) => {
      // Sabotage target: the blank-title fallback (`# Not set.` or a bare `#` would appear).
      const spec = golden();
      spec.title = title;
      expect(linesOf(render(spec))[0]).toBe('# Untitled deck spec');
    },
  );

  it('slide_type absent (pre-field JSON) renders exactly like slide_type null: no Slide type line', () => {
    // Sabotage target: `slide.slide_type !== null` (absent would print `- **Slide type:** Not set.`).
    const absent = golden();
    absent.slides.forEach((s) => { delete s.slide_type; });
    const nulled = golden();
    nulled.slides.forEach((s) => { s.slide_type = null; });
    expect('slide_type' in absent.slides[0]).toBe(false);
    const out = render(absent);
    expect(out).toBe(render(nulled));
    expect(out).not.toContain('Slide type');
  });

  it('an empty-string slide_type is non-null, so its line is kept and reads Not set.', () => {
    // Sabotage target: a truthiness test `if (slide.slide_type)` instead of `!= null`.
    const spec = golden();
    spec.slides[0].slide_type = '';
    expect(slideBlock(render(spec), 'Slide 1')).toContain('\n- **Slide type:** Not set.\n');
  });

  const DATA_DEFAULTS = '## Data\n\n### Synthesis\n\nNot set.\n\n### Figures\n\nNone.\n\n### Gaps\n\nNone.\n';

  it('absent resolved_data and data_references (unvalidated JSON) are defaulted, not thrown on', () => {
    // Sabotage target: drop `spec.resolved_data ?? {}` or `slide.data_references ?? []` (throws).
    const spec = golden();
    delete (spec as Partial<DeckSpec>).resolved_data;
    delete (spec.slides[0] as Partial<SlideSpec>).data_references;
    const out = render(spec);
    expect(out.slice(-DATA_DEFAULTS.length)).toBe(DATA_DEFAULTS);
    expect(out.split('\n## Data\n')).toHaveLength(2);
    expect(slideBlock(out, 'Slide 1')).toContain('\n- **Data references:** None.\n');
    expect(slideBlock(out, 'Slide 2')).toContain('\n- **Data references:** churn\\_rate, arr\\_at\\_risk\n');
  });

  it('resolved_data: {} gives the same defaulted Data section', () => {
    // Sabotage target: drop `data.figures ?? []`, `data.gaps ?? []` or the synthesis default.
    const spec = golden();
    spec.resolved_data = {} as ResolvedData;
    const out = render(spec);
    expect(out.slice(-DATA_DEFAULTS.length)).toBe(DATA_DEFAULTS);
    expect(out.split('\n## Data\n')).toHaveLength(2);
  });

  it('defaults are not written back: a deep-frozen spec with absent containers renders', () => {
    // Sabotage target: `spec.resolved_data ??= {}` or `slide.data_references ??= []` (TypeError on a frozen object).
    const spec = golden();
    delete (spec as Partial<DeckSpec>).resolved_data;
    delete (spec.slides[0] as Partial<SlideSpec>).data_references;
    const out = render(deepFreeze(spec));
    expect(out.slice(-DATA_DEFAULTS.length)).toBe(DATA_DEFAULTS);
  });
});

// ── numeric slots (D4 num) ────────────────────────────────────────────────────

describe('numeric slots (D4 num): integers verbatim, anything else from unvalidated JSON escaped as text', () => {
  it('a string position and a string design_system_id carrying HTML stay inert', () => {
    // Sabotage targets: `### Slide ${slide.position + 1}` without the integer check; `#${id}` without num
    // (an html node appears).
    const spec = golden();
    setRaw(spec.slides[0], 'position', '<b>x</b>');
    setRaw(spec.design_contract, 'design_system_id', '<b>x</b>');
    const out = render(spec);
    expect(linesOf(out)).toContain('### Slide \\<b\\>x\\</b\\>');
    expect(linesOf(out)).toContain('- Design system #\\<b\\>x\\</b\\>');
    expect(disallowedTypes(parse(out))).toEqual([]);
    expect(blockSkeleton(parse(out))).toEqual(blockSkeleton(parse(render(golden()))));
  });

  it.each([
    ['design_system_id', 'Design system'],
    ['template_id', 'Template'],
    ['slide_style_id', 'Slide style'],
  ])('%s goes through num', (key, label) => {
    // Sabotage target: render this one id as `#${id}` without num.
    const spec = golden();
    spec.design_contract = { design_system_id: null, template_id: null, slide_style_id: null };
    setRaw(spec.design_contract, key, '<b>x</b>');
    const out = render(spec);
    expect(linesOf(out)).toContain(`- ${label} #\\<b\\>x\\</b\\>`);
    expect(disallowedTypes(parse(out))).toEqual([]);
  });

  it.each([
    ['null', null, '### Slide Not set.'],
    ['a numeric string: no arithmetic, no concatenation', '3', '### Slide 3'],
    ['a non-integer number: no arithmetic', 2.5, '### Slide 2.5'],
    ['a large integer: plus one, no locale grouping', 1234566, '### Slide 1234567'],
  ])('a position that is %s', (_label, position, heading) => {
    // Sabotage targets: `position + 1` without Number.isInteger ('3' -> `Slide 31`, 2.5 -> `Slide 3.5`,
    // null -> `Slide 1`); `toLocaleString()`.
    const spec = golden();
    setRaw(spec.slides[0], 'position', position);
    expect(linesOf(render(spec))).toContain(heading);
  });
});

// ── slide order ───────────────────────────────────────────────────────────────

describe('slide order', () => {
  it('keeps the given list order, not position order, and each brief under its own heading', () => {
    // Sabotage target: sort the slides by position (in place or on a copy).
    const spec = golden();
    [0, 5, 2].forEach((position, i) => { spec.slides[i].position = position; });
    const out = render(spec);
    const slideHeadings = headings(parse(out)).filter(([depth, t]) => depth === 3 && t.startsWith('Slide ')).map(([, t]) => t);
    expect(slideHeadings).toEqual(['Slide 1', 'Slide 6', 'Slide 3']);
    expect(slideBlock(out, 'Slide 6')).toContain('\n- **Purpose:** Show the money at stake.\n');
    expect(slideBlock(out, 'Slide 3')).toContain('\n- **Purpose:** Land the ask while the cause is still fresh.\n');
  });
});

// ── determinism (D5) ──────────────────────────────────────────────────────────

describe('determinism (D5)', () => {
  it('rendering twice gives the same bytes, from fresh copies and from the same object', () => {
    // Sabotage target: randomness or module-level state (e.g. a render counter), or consuming the input arrays.
    expect(render(golden())).toBe(render(golden()));
    const spec = golden();
    const first = render(spec);
    expect(render(spec)).toBe(first);
  });

  it("ignores key order: with every object's keys reversed it still renders the golden", () => {
    // Sabotage target: emit fields by iterating Object.entries/Object.keys instead of reading them by name.
    const reversed = reverseKeys(golden()) as DeckSpec;
    expect(Object.keys(reversed)[0]).toBe('slides'); // precondition: really reversed
    expect(Object.keys(reversed.slides[0])[0]).toBe('template_section_index');
    expect(render(reversed)).toBe(goldenMarkdown);
  });

  it('does not depend on the clock', () => {
    // Sabotage target: append `new Date().toISOString()` (or any Date-derived text).
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2020-01-01T00:00:00Z'));
      const early = render(golden());
      vi.setSystemTime(new Date('2031-06-15T12:00:00Z'));
      const late = render(golden());
      expect(late).toBe(early);
      expect(early).toBe(goldenMarkdown);
    } finally {
      vi.useRealTimers();
    }
  });

  it('formats integers without locale grouping', () => {
    // Sabotage target: `toLocaleString()` on an id.
    const spec = golden();
    spec.design_contract = { design_system_id: 1234567, template_id: null, slide_style_id: null };
    expect(linesOf(render(spec))).toContain('- Design system #1234567');
  });

  it('does not mutate its input: a deep-frozen copy of the golden renders to the golden', () => {
    // Sabotage target: in-place `spec.slides.sort(...)` (or any write to the spec).
    expect(render(deepFreeze(golden()))).toBe(goldenMarkdown);
  });
});

// ── filename (D6) ─────────────────────────────────────────────────────────────

describe('deckSpecMarkdownFilename (D6)', () => {
  /** U+1D49C MATHEMATICAL SCRIPT CAPITAL A: a letter outside the BMP, two UTF-16 units. */
  const ASTRAL = '𝒜';
  const ROWS: Array<[string, string, string]> = [
    ['the golden title', 'Renewal risk, Q3 — EMEA/APAC', 'renewal-risk-q3-emea-apac-spec.md'],
    ['a path traversal', '../../etc/passwd', 'etc-passwd-spec.md'],
    ['a Windows path', 'C:\\Users\\x\\deck.md', 'c-users-x-deck-md-spec.md'],
    ['a leading dot', '.hidden', 'hidden-spec.md'],
    ['only dots', '...', 'deck-spec.md'],
    ['empty', '', 'deck-spec.md'],
    ['blank', '   ', 'deck-spec.md'],
    ['only emoji', '🚀🚀🚀', 'deck-spec.md'],
    ['a Windows device name', 'CON', 'con-spec.md'],
    ['Latin accents', 'Pr\u00e9visions T3 — Ventes', 'pr\u00e9visions-t3-ventes-spec.md'],
    ['decomposed accents (NFC)', 'e\u0301te\u0301', '\u00e9t\u00e9-spec.md'],
    ['CJK', '四半期レビュー', '四半期レビュー-spec.md'],
    ['control characters', 'a\u0000b\u001fc', 'a-b-c-spec.md'],
    ['200 letters, cut to 60', 'A'.repeat(200), `${'a'.repeat(60)}-spec.md`],
    ['a cut landing on a separator', `${'x'.repeat(59)} yz`, `${'x'.repeat(59)}-spec.md`],
    ['astral letters: 60 code points, not 60 UTF-16 units', ASTRAL.repeat(100), `${ASTRAL.repeat(60)}-spec.md`],
    ['a cut that would split a surrogate pair', `a${ASTRAL.repeat(100)}`, `a${ASTRAL.repeat(59)}-spec.md`],
  ];

  it.each(ROWS)('%s', (_label, title, expected) => {
    // Sabotage targets: `.slice(0, 60)` on the string instead of Array.from (both astral rows red: 30 code
    // points); drop the second `-+$` strip (the separator row ends `--spec.md`); drop normalize('NFC').
    expect(deckSpecMarkdownFilename(title)).toBe(expected);
  });

  it.each([['null', null], ['undefined', undefined]])('a %s title (unvalidated JSON) gives deck-spec.md', (_label, title) => {
    // Sabotage target: drop `?? ''` (String(null) gives `null-spec.md`).
    expect(deckSpecMarkdownFilename(title as unknown as string)).toBe('deck-spec.md');
  });

  const PROPERTY_INPUTS: Array<[string, string]> = [
    ...ROWS.map(([label, title]): [string, string] => [label, title]),
    ['300 CJK letters', '四'.repeat(300)],
  ];

  it.each(PROPERTY_INPUTS)('%s: a safe, portable file name', (_label, title) => {
    // Sabotage targets: `.slice(0, 60)` on the string (the surrogate row leaves a lone surrogate);
    // drop the separator replace (`/`, `\` or a leading `.` survive); drop the length cut (over 255 bytes).
    const out = deckSpecMarkdownFilename(title);
    expect(out).toMatch(/^[\p{L}\p{N}\p{M}]+(?:-[\p{L}\p{N}\p{M}]+)*-spec\.md$/u);
    expect(out).not.toMatch(/[/\\]/);
    expect(out.startsWith('.')).toBe(false);
    expect(/\p{Cs}/u.test(out)).toBe(false);
    expect(new TextEncoder().encode(out).length).toBeLessThanOrEqual(255);
  });
});
