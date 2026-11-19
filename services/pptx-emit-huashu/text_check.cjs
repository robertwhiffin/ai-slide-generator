'use strict';
// The per-slide text-loss check (spec §6): the words the browser renders that
// the slide written for it does not hold, logged on stderr so text loss is
// visible in the app log. render_slide.cjs reads the reference, the page's
// innerText with every <svg> and <canvas> hidden (their text travels inside
// their pictures), once the captures are taken, and logs what this module
// formats. The export fidelity harness (scripts/export_fidelity/run.py
// check_text_loss) makes the same comparison on the written .pptx, with the
// same normalisation, so the two report the same words.
//
//   missingWords(reference, emitted, hidden) -> string[]
//     The reference's words, as it spells them and in its order, whose
//     normalised form is no substring of the normalised emitted text and is
//     no hidden word. A word is a run of characters between white space.
//     Normalising folds compatibility forms (NFKC: a literal "¹" is "1", a
//     ligature its letters, a fullwidth form its ASCII), then removes white
//     space and default-ignorable code points (a word joiner, which the
//     PowerPoint deck writes after a line-ending script run, a zero-width
//     space, a soft hyphen), then lower-cases. The emitted text is compared
//     whole, so words a renderer runs together ("Revenueup10.7%") are not
//     missing. `hidden` is the slide's hidden text (snapshot.mjs
//     model.reference.hiddenText): words the page reads that the slide does
//     not show, each whole, which are no loss.
//   textLossLine(reference, items, hidden) -> string | null
//     '[html2pptx] text missing: <json array>' naming missingWords over the
//     text a slide model's items hold, or null when none is missing. That text
//     is every run of every text item (an outside list marker is a text item
//     of its own; an inside one is a token of its line) and of every native
//     table cell (a cell whose text is overlay items, paragraphs null, holds
//     none of its own). No other item holds text.
//   logJson(value) -> string
//     JSON.stringify(value) on one line as Python's str.splitlines() reads
//     it: the only line separators JSON.stringify leaves unescaped (U+0085,
//     U+2028, U+2029) are written as \u escapes, so a line that holds them in
//     a string is still one line in pptx_from_html_huashu.py's echo.
//
// White space here is what Python's str.split() splits on, Unicode White_Space
// and U+001C..U+001F, so the harness reads the same words.

const TEXT_MISSING_PREFIX = '[html2pptx] text missing: ';
const WHITE_SPACE = /[\p{White_Space}\u001c-\u001f]+/u;
const IGNORED = /[\p{White_Space}\u001c-\u001f\p{Default_Ignorable_Code_Point}]/gu;
const UNESCAPED_LINE_SEPARATORS = /[\u0085\u2028\u2029]/g;

function textOf(value) {
  return typeof value === 'string' ? value : '';
}

function normalise(text) {
  return textOf(text).normalize('NFKC').replace(IGNORED, '').toLowerCase();
}

function wordsOf(text) {
  return textOf(text).split(WHITE_SPACE).filter((word) => word.length > 0);
}

function missingWords(reference, emitted, hidden) {
  const shown = normalise(emitted);
  const hiddenWords = new Set(wordsOf(hidden).map(normalise));
  const missing = [];
  for (const word of wordsOf(reference)) {
    const normalised = normalise(word);
    if (shown.includes(normalised) || hiddenWords.has(normalised)) continue;
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

function emittedText(items) {
  const parts = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item) continue;
    if (item.kind === 'text') {
      parts.push(paragraphsText(item.paragraphs));
    } else if (item.kind === 'table') {
      for (const cell of item.cells || []) parts.push(paragraphsText(cell && cell.paragraphs));
    }
  }
  return parts.join(' ');
}

function textLossLine(reference, items, hidden) {
  const missing = missingWords(reference, emittedText(items), hidden);
  return missing.length ? TEXT_MISSING_PREFIX + logJson(missing) : null;
}

function logJson(value) {
  return JSON.stringify(value).replace(
    UNESCAPED_LINE_SEPARATORS,
    (character) => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'),
  );
}

module.exports = { missingWords, textLossLine, logJson };
