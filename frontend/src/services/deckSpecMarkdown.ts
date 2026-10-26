/**
 * Deterministic Markdown rendering of a deck spec (#318).
 *
 * Pure and frontend-only: the renderer reads nothing but the `DeckSpec` it is given and never
 * mutates it. The output is a function of the spec alone (no clock, locale or randomness), so the
 * same spec always yields the same bytes. Every user value is collapsed to one line and
 * backslash-escaped (`escapeText`), so a value cannot inject structure into the document; renderer
 * constants (labels, `None.`, `Not set.`, `Blank slide.`) are never escaped.
 */
import type { DeckSpec, ResolvedData } from '../types/slide';
import { isBlankSlideSpec } from './blankSlide';

/** RFC 7763 media type, UTF-8, no BOM. */
export const DECK_SPEC_MARKDOWN_MIME = 'text/markdown;charset=utf-8';

const NOT_SET = 'Not set.';
/** A blank slide's line, standing in for its Purpose and Content brief lines. A renderer constant: never escaped. */
const BLANK_SLIDE = 'Blank slide.';
/** CommonMark §2.4 lets any ASCII punctuation be backslash-escaped; these are the ones with meaning (D4). `|` and `~` keep GFM tables and strikethrough inert (GitHub honours these escapes); `$` and `@` keep dollar-math and citation syntax inert where a renderer honours the escape (e.g. pandoc). GitHub's own math, @-mention and #N rendering ignores backslash escapes (checked against GitHub's markdown API, 2026-10-20). */
const ESCAPE_ANYWHERE = /[\\`*_[\]<>#|~$&@]/g;
/** D4 step 1, by code point: C0/C1 controls, except the whitespace ones and NEL (U+0085), which step 2 collapses. */
// eslint-disable-next-line no-control-regex -- removing control characters is this pattern's purpose
const CONTROL_CHARS = /[\u0000-\u0008\u000E-\u001F\u007F-\u0084\u0086-\u009F]/g;
/** D4 step 2, by code point: ECMAScript's whitespace plus NEL. Spelled out so a port to another language cannot drift. */
const WHITESPACE_RUN = /[\t\n\v\f\r \u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]+/g;

function normalise(value: unknown): string {
  return String(value ?? '').replace(CONTROL_CHARS, '').replace(WHITESPACE_RUN, ' ').trim();
}

function escapeText(value: unknown): string {
  const text = normalise(value);
  if (!text) return NOT_SET;
  let out = text.replace(ESCAPE_ANYWHERE, (c) => `\\${c}`);
  if (/^[-+=]/.test(out)) out = `\\${out}`;                    // list / thematic break / setext
  return out.replace(/^(\d{1,9})([.)])(?= |$)/, '$1\\$2');      // ordered-list marker
}

/** Numeric slots (ids, position): an integer verbatim; anything else (unvalidated JSON) is escaped like text. */
function num(value: unknown): string {
  return Number.isInteger(value) ? String(value) : escapeText(value);
}

const UNTITLED = 'Untitled deck spec';
const NONE = 'None.';

/** Bullet lines of `- {line}`, one block; `None.` when there are no items. */
function bullets(lines: string[]): string {
  return lines.length ? lines.map((line) => `- ${line}`).join('\n') : NONE;
}

/**
 * Deterministic Markdown rendering of a deck spec. Pure: never reads anything but `spec`, never mutates it.
 *
 * Sections come in a fixed order and are read by field name. `narrative_arc` and `slides` keep their
 * given order. Fields the Spec view never reads (`resolved_data`, `data_references`, `slide_type`) may be
 * absent in unvalidated JSON and are defaulted rather than thrown on; `narrative_arc` and `slides` are
 * required, as they are by the Spec view itself.
 */
export function renderDeckSpecMarkdown(spec: DeckSpec): string {
  const contract = spec.design_contract ?? {};
  const data: Partial<ResolvedData> = spec.resolved_data ?? {};

  const blocks: string[] = [];

  blocks.push(`# ${normalise(spec.title) ? escapeText(spec.title) : UNTITLED}`);

  blocks.push('## Audience', escapeText(spec.audience));
  blocks.push('## Purpose', escapeText(spec.purpose));
  blocks.push('## Argument', escapeText(spec.argument));
  blocks.push('## Call to action', escapeText(spec.call_to_action));

  blocks.push(
    '## Narrative arc',
    spec.narrative_arc.length
      ? spec.narrative_arc.map((beat, i) => `${i + 1}. ${escapeText(beat)}`).join('\n')
      : NONE,
  );

  const pinned: string[] = [];
  if (contract.design_system_id != null) pinned.push(`Design system #${num(contract.design_system_id)}`);
  if (contract.template_id != null) pinned.push(`Template #${num(contract.template_id)}`);
  if (contract.slide_style_id != null) pinned.push(`Slide style #${num(contract.slide_style_id)}`);
  blocks.push(
    '## Design contract',
    pinned.length ? bullets(pinned) : 'No design system or slide style pinned',
  );

  blocks.push('## Slide briefs');
  if (spec.slides.length === 0) {
    blocks.push(NONE);
  }
  for (const slide of spec.slides) {
    blocks.push(`### Slide ${Number.isInteger(slide.position) ? String(slide.position + 1) : escapeText(slide.position)}`);
    // A blank slide (a manual insert) says so in place of its two empty lines, as the Spec view does.
    // Blankness is the view's rule (`isBlankSlideSpec`: HTML ASCII whitespace only), NOT `normalise()`'s,
    // so the file and the view always agree on which slides are blank.
    const fields = [
      ...(isBlankSlideSpec(slide)
        ? [BLANK_SLIDE]
        : [
            `**Purpose:** ${escapeText(slide.purpose)}`,
            `**Content brief:** ${escapeText(slide.content_brief)}`,
          ]),
      `**Assumes:** ${escapeText(slide.assumes)}`,
      `**Hands off:** ${escapeText(slide.hands_off)}`,
    ];
    if (slide.slide_type != null) fields.push(`**Slide type:** ${escapeText(slide.slide_type)}`);
    const refs = (slide.data_references ?? []).map((ref) => escapeText(ref));
    fields.push(`**Data references:** ${refs.length ? refs.join(', ') : NONE}`);
    blocks.push(bullets(fields));
  }

  blocks.push(
    '## Data',
    '### Synthesis',
    escapeText(data.synthesis),
    '### Figures',
    bullets((data.figures ?? []).map((f) => `${escapeText(f.key)}: ${escapeText(f.value)} (source: ${escapeText(f.source)})`)),
    '### Gaps',
    bullets((data.gaps ?? []).map((gap) => escapeText(gap))),
  );

  return `${blocks.join('\n\n')}\n`;
}

const SLUG_MAX_CODE_POINTS = 60;

/** `<slug>-spec.md` from the spec title (D6); `deck-spec.md` when nothing survives sanitising. */
export function deckSpecMarkdownFilename(title: string): string {
  const slug = Array.from(
    String(title ?? '').toLowerCase().normalize('NFC')
      .replace(/[^\p{L}\p{N}\p{M}]+/gu, '-')
      .replace(/^-+|-+$/g, ''),
  ).slice(0, SLUG_MAX_CODE_POINTS).join('').replace(/-+$/, '');
  return `${slug || 'deck'}-spec.md`;
}
