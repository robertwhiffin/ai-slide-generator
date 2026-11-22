'use strict';
// The per-slide text-loss check (spec §6): the words the browser renders that
// the slide written for it does not hold, logged on stderr so text loss is
// visible in the app log. render_slide.cjs reads the reference, the page's
// innerText with every <svg> and <canvas> hidden (their text travels inside
// their pictures), once the captures are taken, and logs what this module
// formats. The export fidelity harness (scripts/export_fidelity/run.py
// check_text_loss) makes the same comparison on the written .pptx, with the
// same normalisation but one fold: it reads U+2010 HYPHEN (which NFKC also
// makes of U+2011) as U+002D, because the decks write those hyphens as U+002D
// where an app would draw them from another font (emit_typography.cjs
// runText). This check reads the slide model, which keeps the page's own
// characters, so it needs no fold, and the two report the same words.
//
//   missingWords(reference, emitted, hidden) -> string[]
//     The reference's words, as it spells them and in its order, whose
//     normalised form is no substring of the normalised emitted text, is not
//     written across items' edges (writtenAcross) and is no hidden word. A
//     word is a run of characters between white space. `emitted` is the
//     slide's emitted text: one string, or the text of each item that holds
//     some, in the slide's order. Normalising folds compatibility forms (NFKC:
//     a literal "¹" is "1", a ligature its letters, a fullwidth form its
//     ASCII), then removes white space and default-ignorable code points (a
//     word joiner, which the PowerPoint deck writes after a line-ending script
//     run, a zero-width space, a soft hyphen), then lower-cases. The emitted
//     text is compared whole, so words a renderer runs together
//     ("Revenueup10.7%") are not missing. An atomic inline (an inline-block
//     numeral, a chip) is an item of its own, painted after the text around
//     it, so a word the page runs across its edge ("1Financials", a numeral
//     and the word after it; "Iceberg,", a chip and the comma after it) is
//     written in two items the slide does not hold side by side, and is not
//     missing (Task 15 H2). `hidden` is the slide's hidden text (snapshot.mjs
//     model.reference.hiddenText): words the page reads that the slide does
//     not show, each whole, which are no loss.
//   textLossLine(reference, items, hidden) -> string | null
//     '[html2pptx] text missing: <json array>' naming missingWords over the
//     text a slide model's items hold, item by item, or null when none is
//     missing. That text is every run of every text item (an outside list
//     marker is a text item of its own; an inside one is a token of its line)
//     and of every native table cell (a cell whose text is overlay items,
//     paragraphs null, holds none of its own). No other item holds text.
//   isWhiteSpace(character) -> boolean
//   isDefaultIgnorable(character) -> boolean
//     Whether one character is white space (a word ends at it, and it is
//     removed) or default-ignorable (it is removed): the two sets the
//     comparison is made with, which the harness's _normalise_text matches.
//
// White space here is what Python's str.split() splits on, Unicode White_Space
// and U+001C..U+001F, so the harness reads the same words. The text-loss line
// is written on one line (log_line.cjs logJson).

const { logJson } = require('./log_line.cjs');

const TEXT_MISSING_PREFIX = '[html2pptx] text missing: ';
// The two sets, as regular-expression class bodies.
const WHITE_SPACE_CLASS = '\\p{White_Space}\\x1c-\\x1f';
const DEFAULT_IGNORABLE_CLASS = '\\p{Default_Ignorable_Code_Point}';
const WORD_SEPARATOR = new RegExp(`[${WHITE_SPACE_CLASS}]+`, 'u');
const IGNORED = new RegExp(`[${WHITE_SPACE_CLASS}${DEFAULT_IGNORABLE_CLASS}]`, 'gu');
const WHITE_SPACE_CHARACTER = new RegExp(`^[${WHITE_SPACE_CLASS}]$`, 'u');
const DEFAULT_IGNORABLE_CHARACTER = new RegExp(`^[${DEFAULT_IGNORABLE_CLASS}]$`, 'u');

function textOf(value) {
  return typeof value === 'string' ? value : '';
}

function normalise(text) {
  return textOf(text).normalize('NFKC').replace(IGNORED, '').toLowerCase();
}

function wordsOf(text) {
  return textOf(text).split(WORD_SEPARATOR).filter((word) => word.length > 0);
}

// A word longer than this is not looked for across items, nor an item's text
// read further than this from its edges: the words a page runs across an
// atomic inline's edge are short ("1Financials", "Iceberg,"), and the bound
// keeps the check linear in the text a slide holds, page script being free to
// write a word of any length.
const ACROSS_LIMIT = 64;

// The edges of the items' normalised texts a word written across items is
// read from: every suffix and prefix up to ACROSS_LIMIT long, and each whole
// text that short.
function itemEdges(texts) {
  const tails = new Set();
  const heads = new Set();
  const whole = new Set();
  for (const text of texts) {
    const reach = Math.min(text.length, ACROSS_LIMIT);
    for (let length = 1; length <= reach; length++) {
      tails.add(text.slice(text.length - length));
      heads.add(text.slice(0, length));
    }
    if (text.length <= ACROSS_LIMIT) whole.add(text);
  }
  return { tails, heads, whole };
}

// Whether a normalised word is written across items' edges (`edges`,
// itemEdges): a suffix of one item's text, then the whole text of none or
// more items, then a prefix of another's, each piece a character or more. The
// pieces must meet at the items' edges, so a word whose piece is lost, or
// written only inside other text, is not written.
function writtenAcross(word, edges) {
  if (word.length < 2 || word.length > ACROSS_LIMIT) return false;
  // reached[end]: the word's first `end` characters end where an item's text ends.
  const reached = new Array(word.length).fill(false);
  for (let end = 1; end < word.length; end++) {
    reached[end] = edges.tails.has(word.slice(0, end));
    for (let start = 1; start < end && !reached[end]; start++) {
      reached[end] = reached[start] && edges.whole.has(word.slice(start, end));
    }
  }
  for (let start = 1; start < word.length; start++) {
    if (reached[start] && edges.heads.has(word.slice(start))) return true;
  }
  return false;
}

function missingWords(reference, emitted, hidden) {
  const texts = (Array.isArray(emitted) ? emitted : [emitted]).map(normalise).filter((text) => text.length > 0);
  const shown = texts.join('');
  const hiddenWords = new Set(wordsOf(hidden).map(normalise));
  let edges = null;
  const missing = [];
  for (const word of wordsOf(reference)) {
    const normalised = normalise(word);
    if (shown.includes(normalised) || hiddenWords.has(normalised)) continue;
    if (!edges) edges = itemEdges(texts);
    if (writtenAcross(normalised, edges)) continue;
    missing.push(word);
  }
  return missing;
}

// The text of a text item's or a table cell's paragraphs, run by run.
function paragraphsText(paragraphs) {
  const parts = [];
  for (const paragraph of Array.isArray(paragraphs) ? paragraphs : []) {
    for (const line of (paragraph && paragraph.lines) || []) {
      for (const run of (line && line.runs) || []) parts.push(textOf(run && run.text));
    }
  }
  return parts.join('');
}

// The text of each text item and native table cell, in the model's order.
function emittedTexts(items) {
  const parts = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item) continue;
    if (item.kind === 'text') {
      parts.push(paragraphsText(item.paragraphs));
    } else if (item.kind === 'table') {
      for (const cell of item.cells || []) parts.push(paragraphsText(cell && cell.paragraphs));
    }
  }
  return parts;
}

function textLossLine(reference, items, hidden) {
  const missing = missingWords(reference, emittedTexts(items), hidden);
  return missing.length ? TEXT_MISSING_PREFIX + logJson(missing) : null;
}

function isWhiteSpace(character) {
  return WHITE_SPACE_CHARACTER.test(textOf(character));
}

function isDefaultIgnorable(character) {
  return DEFAULT_IGNORABLE_CHARACTER.test(textOf(character));
}

module.exports = { missingWords, textLossLine, isWhiteSpace, isDefaultIgnorable };
