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
//     normalised form is in no emitted text and is no hidden word. A word is a
//     run of characters between white space. `emitted` is the slide's emitted
//     text: one string, or the text of each item that holds some, each
//     compared alone, never run on into the next item's. Normalising folds
//     compatibility forms (NFKC: a literal "¹" is "1", a ligature its letters,
//     a fullwidth form its ASCII), then removes white space and
//     default-ignorable code points (a word joiner, which the PowerPoint deck
//     writes after a line-ending script run, a zero-width space, a soft
//     hyphen), then lower-cases, so the words of one text a renderer runs
//     together ("Revenueup10.7%") are not missing. `hidden` is the slide's
//     hidden text (snapshot.mjs model.reference.hiddenText): words the page
//     reads that the slide does not show, each whole, which are no loss.
//   acrossText(items) -> string
//     The normalised text a slide model's items hold across neighbours: each
//     chain of neighbouring text items (neighbourChains), its items' texts run
//     together in its order, one chain a line. An atomic inline (an
//     inline-block numeral, a chip) is a text item of its own, painted after
//     the text around it, so a word the page runs across its edge
//     ("1Financials", a numeral and the word after it; "Iceberg,", a chip and
//     the comma after it) is written in two items, which are neighbours. A
//     word written in items that are not neighbours (the letters of a lost
//     chip that end and start the boxes either side of where it was) is not
//     in this text (Task 15 H2, fix round 1).
//   textLossLine(reference, items, hidden) -> string | null
//     '[html2pptx] text missing: <json array>' naming the words missingWords
//     finds in no item's text that are not in acrossText(items) either, or
//     null when none is missing. An item's text is every run of a text item
//     (an outside list marker is a text item of its own; an inside one is a
//     token of its line) or of a native table cell (a cell whose text is
//     overlay items, paragraphs null, holds none of its own). No other item
//     holds text.
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

// A word that normalises to nothing (default-ignorable code points alone) is
// in every text.
function missingWords(reference, emitted, hidden) {
  const texts = (Array.isArray(emitted) ? emitted : [emitted]).map(normalise).filter((text) => text.length > 0);
  const hiddenWords = new Set(wordsOf(hidden).map(normalise));
  const missing = [];
  for (const word of wordsOf(reference)) {
    const normalised = normalise(word);
    if (!normalised || hiddenWords.has(normalised) || texts.some((text) => text.includes(normalised))) continue;
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

// ─── words across neighbours ─────────────────────────────────────────
// A word no item holds whole is written when it lies across the joins of a
// chain of neighbouring text items. Two items are neighbours, the tail and
// then the head, when both are unturned and of one line, run the same way,
// share a line, and the head's text starts within an atomic inline's edge of
// where the tail's ends. An atomic inline's edge (its padding, border and
// margin, and the room its content box leaves its text) is the gap between
// its text and the text beside it: 18 px (1 em) for long-off 02's numerals and
// 9 px (0.45 em) for dense-tpl18 03's chips, measured on the slide models the
// Task 15 matrix decks export. A lost chip leaves both its edges, its own text
// and the spaces either side of it between the boxes around it: 43 to 51 px
// (2.1 to 2.5 em) on the review's probe. The rule reads the boxes the
// snapshot laid out, less their slack, which the harness's twin reads from the
// written deck (scripts/export_fidelity/run.py _across_text), with the same
// constants.
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
// this many, the first the slide paints, page script being free to paint any
// number: no slide of the Task 15 matrix or the corpora paints more than 51
// text items. An item past them is no neighbour.
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

// A text item as the neighbour rule reads it: its normalised text; where its
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
  const text = normalise(paragraphsText(item.paragraphs));
  if (!text) return null;
  const extent = Math.max(0, (w - SLACK_PX) / (1 + SLACK_FRACTION));
  const left = item.align === 'center' ? x + (w - extent) / 2 : item.align === 'right' ? x + w - extent : x;
  const rtl = Boolean(item.rtl);
  return {
    text,
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
// slide paints them), each its items' texts run together. Each item is
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
    let text = '';
    for (let at = start; at >= 0; at = next[at]) text += placed[at].text;
    chains.push(text);
  }
  return chains;
}

function acrossText(items) {
  const placed = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (placed.length >= ACROSS_ITEM_LIMIT) break;
    const text = placedText(item);
    if (text) placed.push(text);
  }
  return neighbourChains(placed).join('\n');
}

// The chains are read only when a word is in no item's own text.
function textLossLine(reference, items, hidden) {
  let missing = missingWords(reference, emittedTexts(items), hidden);
  if (missing.length) {
    const across = acrossText(items);
    missing = missing.filter((word) => !across.includes(normalise(word)));
  }
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
  acrossText,
  textLossLine,
  isWhiteSpace,
  isDefaultIgnorable,
  SLACK_FRACTION,
  SLACK_PX,
  SAME_LINE_OVERLAP,
  NEIGHBOUR_GAP_EM,
  NEIGHBOUR_OVERLAP_EM,
  ACROSS_ITEM_LIMIT,
};
