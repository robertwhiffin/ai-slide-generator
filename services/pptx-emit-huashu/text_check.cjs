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
//     The reference's words, as it spells them and in its order, that are
//     written in no emitted text (writtenIn) and are no hidden word. A word is
//     a run of characters between white space. `emitted` is the slide's
//     emitted text: one string, or the text of each item that holds some
//     (its lines one a line), each compared alone, never run on into the next
//     item's. A word is written in a text when its normalised form is inside
//     one of the text's normalised words, or is two or more of them whole, one
//     after the other: so the words of one text a renderer runs together
//     ("Revenueup10.7%") are not missing, and a short word the end of one word
//     and the start of the next spell ("AI" in "Data Insights") is.
//     Normalising folds compatibility forms (NFKC: a literal "¹" is "1", a
//     ligature its letters, a fullwidth form its ASCII), then removes white
//     space and default-ignorable code points (a word joiner, which the
//     PowerPoint deck writes after a line-ending script run, a zero-width
//     space, a soft hyphen), then lower-cases. `hidden` is the slide's hidden
//     text (snapshot.mjs model.reference.hiddenText): words the page reads
//     that the slide does not show, each whole, which are no loss.
//   acrossWords(items) -> string[][]
//     The normalised words a slide model's items hold across neighbours: each
//     chain of neighbouring text items (neighbourChains), its items' words in
//     its order. An atomic inline (an inline-block numeral, a chip) is a text
//     item of its own, painted after the text around it, so a word the page
//     runs across its edge ("1Financials", a numeral and the word after it;
//     "Iceberg,", a chip and the comma after it) is written in two items,
//     which are neighbours, as the tail's last word and the head's first,
//     each whole. A word written in items that are not neighbours, or only in
//     part of the words either side of a join (the letters of a lost chip
//     that end and start the boxes either side of where it was), is not
//     written across them.
//   lostWords(reference, items, hidden) -> string[]
//     The words missingWords finds in no item's text that no chain of
//     acrossWords(items) writes either: the slide's lost words.
//   textLossLine(reference, items, hidden) -> string | null
//     '[html2pptx] text missing: <json array>' naming lostWords, or null when
//     none is missing. It names a slide's own words, so render_slide.cjs logs
//     it with the debug text on alone (log_line.cjs debugText), and their
//     count and the slide otherwise. An item's text is every run of a text item
//     (an outside list marker is a text item of its own; an inside one is a
//     token of its line) or of a native table cell (a cell whose text is
//     overlay items, paragraphs null, holds none of its own). No other item
//     holds text.
//   wordsOf(text) -> string[]
//     The words of `text`: its runs of characters between white space.
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

// The normalised words of `text`, less those that normalise to nothing.
function normalisedWords(text) {
  return wordsOf(text).map(normalise).filter((word) => word.length > 0);
}

// Whether `word` (normalised) is written in `words` (a text's normalised
// words, in order): inside one of them, or as two or more of them whole, one
// after the other. A word read across words holds each of them whole: "AI" is
// in neither "data" nor "insights", nor is it the two of them, so "Data
// Insights" does not write it.
function writtenIn(word, words) {
  for (let first = 0; first < words.length; first++) {
    if (words[first].includes(word)) return true;
    let joined = words[first];
    for (let next = first + 1; next < words.length && word.startsWith(joined) && joined.length < word.length; next++) {
      joined += words[next];
      if (joined === word) return true;
    }
  }
  return false;
}

// A word that normalises to nothing (default-ignorable code points alone) is
// in every text.
function missingWords(reference, emitted, hidden) {
  const texts = (Array.isArray(emitted) ? emitted : [emitted]).map(normalisedWords).filter((words) => words.length > 0);
  const hiddenWords = new Set(wordsOf(hidden).map(normalise));
  const missing = [];
  for (const word of wordsOf(reference)) {
    const normalised = normalise(word);
    if (!normalised || hiddenWords.has(normalised) || texts.some((words) => writtenIn(normalised, words))) continue;
    missing.push(word);
  }
  return missing;
}

// The text of a text item's or a table cell's paragraphs: each line's runs
// run on into each other, the lines one a line, so a line's end ends a word,
// as the deck's line break does where the harness reads it.
function paragraphsText(paragraphs) {
  const lines = [];
  for (const paragraph of Array.isArray(paragraphs) ? paragraphs : []) {
    for (const line of (paragraph && paragraph.lines) || []) {
      const parts = [];
      for (const run of (line && line.runs) || []) parts.push(textOf(run && run.text));
      lines.push(parts.join(''));
    }
  }
  return lines.join('\n');
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

// ─── words across neighbours ─────────────────────────────────────────
// A word no item holds whole is written when it lies across the joins of a
// chain of neighbouring text items, holding the tail's last word and the
// head's first whole at each join it crosses (writtenIn over the chain's
// words). Two items are neighbours, the tail and then the head, when both are
// unturned and of one line, run the same way, share a line, and the head's
// text starts within an atomic inline's edge of where the tail's ends. An
// atomic inline's edge (its padding, border and margin, and the room its
// content box leaves its text) is the gap between its text and the text
// beside it: 18 px (1 em) for long-off 02's numerals and 9 px (0.45 em) for
// dense-tpl18 03's chips, measured on the slide models those matrix decks
// export. A lost chip leaves both its edges, its own text and the spaces
// either side of it between the boxes around it: 43 to 51 px (2.1 to 2.5 em)
// for padded chips, no neighbours; 1.25 to 1.45 em for a 16 px "AI" with no
// padding or 2 px of it, which are neighbours, and whose letters the
// whole-word rule does not read across them. The rule reads the boxes the
// snapshot laid out, less their slack, which the harness's twin reads from
// the written deck (scripts/export_fidelity/run.py _across_words), with the
// same constants.
//
// snapshot_text.mjs textBlock's width slack: a text box is its text, or a
// centred or right-aligned block's content box, widened by SLACK_FRACTION of
// that width and SLACK_PX on the side its alignment grows (both sides for
// centred text, the left for right-aligned).
const SLACK_FRACTION = 0.06;
const SLACK_PX = 4;
// Two items share a line when they overlap by more than this fraction of the
// shorter's height: snapshot_text.mjs SAME_LINE_OVERLAP, with which the
// snapshot puts a block's tokens on lines.
const SAME_LINE_OVERLAP = 0.5;
// The head's text starts from NEIGHBOUR_OVERLAP_EM before the tail's text ends
// (a negative margin, rounding) to NEIGHBOUR_GAP_EM after it, in ems of the
// larger of the two items' sizes.
const NEIGHBOUR_GAP_EM = 1.5;
const NEIGHBOUR_OVERLAP_EM = 0.25;
// The rule compares every item it reads with every other, so it reads at most
// this many of the items it can read (unturned one-line text items), the
// first the slide paints, page script being free to paint any number: no
// slide of the corpora or the matrix decks paints more than 51 text items.
// An item past them is no neighbour.
const ACROSS_ITEM_LIMIT = 1024;

// The largest size (px) of an item's runs that are no superscript or
// subscript: the deck writes a script run larger than the browser draws it
// (emit_typography.cjs fontSizePt), so the twins read only the others.
function sizeOf(paragraphs) {
  let size = 0;
  for (const paragraph of Array.isArray(paragraphs) ? paragraphs : []) {
    for (const line of (paragraph && paragraph.lines) || []) {
      for (const run of (line && line.runs) || []) {
        if (!run || run.baseline === 'super' || run.baseline === 'sub') continue;
        const px = Number(run.sizePx);
        if (px > size) size = px;
      }
    }
  }
  return size;
}

// A text item as the neighbour rule reads it: its normalised words; where its
// text starts and ends along its line, mirrored for right-to-left text so that
// a line always runs on to larger values; its top and bottom; its size; and
// its direction. Null for an item that is turned, of more than one line, has
// no box, or holds no text.
function placedText(item) {
  if (!item || item.kind !== 'text' || item.wrap || item.rotate) return null;
  const { x, y, w, h } = item;
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(w) || !Number.isFinite(h) || !(h > 0)) {
    return null;
  }
  const words = normalisedWords(paragraphsText(item.paragraphs));
  if (!words.length) return null;
  const extent = Math.max(0, (w - SLACK_PX) / (1 + SLACK_FRACTION));
  const left = item.align === 'center' ? x + (w - extent) / 2 : item.align === 'right' ? x + w - extent : x;
  const rtl = Boolean(item.rtl);
  return {
    words,
    start: rtl ? -(left + extent) : left,
    end: rtl ? -left : left + extent,
    top: y,
    bottom: y + h,
    size: sizeOf(item.paragraphs),
    rtl,
  };
}

// How far the head's text starts after the tail's ends, when the head is the
// tail's neighbour; else null.
function joinGap(tail, head) {
  if (tail.rtl !== head.rtl) return null;
  const overlap = Math.min(tail.bottom, head.bottom) - Math.max(tail.top, head.top);
  if (!(overlap > SAME_LINE_OVERLAP * Math.min(tail.bottom - tail.top, head.bottom - head.top))) return null;
  const em = Math.max(tail.size, head.size);
  const gap = head.start - tail.end;
  return gap >= -NEIGHBOUR_OVERLAP_EM * em && gap <= NEIGHBOUR_GAP_EM * em ? gap : null;
}

// The chains of neighbours among `placed` (placedText's, in the order the
// slide paints them), each its items' words in its order. Each item is
// followed by its nearest neighbour, the head whose text starts soonest after
// its own ends (the first painted, of equals); a head follows only the nearest
// of the tails it is nearest to; and a join that would close a loop is left
// out, the joins taken nearest first.
function neighbourChains(placed) {
  const count = placed.length;
  const nearest = new Array(count).fill(null);
  for (let tail = 0; tail < count; tail++) {
    for (let head = 0; head < count; head++) {
      if (head === tail) continue;
      const gap = joinGap(placed[tail], placed[head]);
      if (gap !== null && (!nearest[tail] || gap < nearest[tail].gap)) nearest[tail] = { gap, head };
    }
  }
  const kept = new Array(count).fill(null);
  for (let tail = 0; tail < count; tail++) {
    const join = nearest[tail];
    if (join && (!kept[join.head] || join.gap < kept[join.head].gap)) kept[join.head] = { gap: join.gap, tail };
  }
  const joins = [];
  for (let head = 0; head < count; head++) {
    if (kept[head]) joins.push({ gap: kept[head].gap, tail: kept[head].tail, head });
  }
  joins.sort((a, b) => a.gap - b.gap || a.tail - b.tail);
  const next = new Array(count).fill(-1);
  const previous = new Array(count).fill(-1);
  for (const join of joins) {
    let first = join.tail;
    while (previous[first] >= 0) first = previous[first];
    if (first === join.head) continue;
    next[join.tail] = join.head;
    previous[join.head] = join.tail;
  }
  const chains = [];
  for (let start = 0; start < count; start++) {
    if (previous[start] >= 0 || next[start] < 0) continue;
    const words = [];
    for (let at = start; at >= 0; at = next[at]) {
      for (const word of placed[at].words) words.push(word);
    }
    chains.push(words);
  }
  return chains;
}

function acrossWords(items) {
  const placed = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (placed.length >= ACROSS_ITEM_LIMIT) break;
    const text = placedText(item);
    if (text) placed.push(text);
  }
  return neighbourChains(placed);
}

// The chains are read only when a word is in no item's own text.
function lostWords(reference, items, hidden) {
  let missing = missingWords(reference, emittedTexts(items), hidden);
  if (missing.length) {
    const chains = acrossWords(items);
    missing = missing.filter((word) => !chains.some((words) => writtenIn(normalise(word), words)));
  }
  return missing;
}

function textLossLine(reference, items, hidden) {
  const missing = lostWords(reference, items, hidden);
  return missing.length ? TEXT_MISSING_PREFIX + logJson(missing) : null;
}

function isWhiteSpace(character) {
  return WHITE_SPACE_CHARACTER.test(textOf(character));
}

function isDefaultIgnorable(character) {
  return DEFAULT_IGNORABLE_CHARACTER.test(textOf(character));
}

module.exports = {
  missingWords,
  acrossWords,
  lostWords,
  textLossLine,
  wordsOf,
  TEXT_MISSING_PREFIX,
  isWhiteSpace,
  isDefaultIgnorable,
  SLACK_FRACTION,
  SLACK_PX,
  SAME_LINE_OVERLAP,
  NEIGHBOUR_GAP_EM,
  NEIGHBOUR_OVERLAP_EM,
  ACROSS_ITEM_LIMIT,
};
