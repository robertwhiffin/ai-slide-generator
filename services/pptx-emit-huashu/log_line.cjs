'use strict';
// What the sidecar prints on stderr and stdout, one line per message as the
// Python side reads it. pptx_from_html_huashu.py splits the sidecar's stderr
// with str.splitlines() to echo it and to find the __HUASHU_RESULT__ failure
// list, and the export fidelity harness splits that echo again to find each
// slide's summary line (scripts/export_fidelity/run.py). str.splitlines() ends
// a line at ten characters, not only at a line feed. So a message holding one
// of them (a slide's console text, an error a page threw, a slide's own text
// in a validation message) would print a line of its own, which slide script
// could make read as the sidecar's: a forged slide summary or failure list.
//
//   oneLine(text) -> string
//     `text` with each of those characters written as its \u escape: one line.
//   logJson(value) -> string
//     JSON.stringify(value) on one line. JSON.stringify escapes every control
//     character but leaves U+0085, U+2028 and U+2029 as they are; written as
//     \u escapes they are still the same JSON.
//
// Every message the sidecar prints that holds text it did not write itself
// goes through oneLine, and every JSON line through logJson.
//
// The wrapper echoes stderr into the app's log, which every manager of the app
// reads, outside Tellr's per-deck permissions. So a line holds no text of a
// slide's own (its words, a quote of it, a message its page made) unless
// DEBUG_TEXT_ENV is 1, which no app sets (pptx_from_html_huashu.py keeps it
// out of the sidecar's env; the export fidelity harness sets it for its own
// runs, scripts/export_fidelity/run.py sidecar_debug_text):
//
//   debugText() -> boolean
//     Whether DEBUG_TEXT_ENV is 1: a slide's own text may be logged.
//   bounded(text, limit) -> string
//     oneLine(text), cut at `limit` characters, the cut said with how many
//     characters it left out.
//   pageText(text, limit) -> string
//     How a line says text that came from a slide's page: bounded(text,
//     limit) with the flag, its length alone without it.

// The characters str.splitlines() ends a line at: line feed, line tabulation,
// form feed, carriage return, the file, group and record separators, next
// line, line separator and paragraph separator.
const LINE_BREAK_CODE_POINTS = [0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029];

function escapeOf(codePoint) {
  return '\\u' + codePoint.toString(16).padStart(4, '0');
}

const LINE_BREAKS = new RegExp(`[${LINE_BREAK_CODE_POINTS.map(escapeOf).join('')}]`, 'g');

function oneLine(text) {
  return String(text).replace(LINE_BREAKS, (character) => escapeOf(character.charCodeAt(0)));
}

function logJson(value) {
  return oneLine(JSON.stringify(value));
}

const DEBUG_TEXT_ENV = 'TELLR_EXPORT_DEBUG_TEXT';
// What a line quotes of a page's text at most: a message its page threw.
const PAGE_TEXT_LIMIT = 300;

function debugText() {
  return process.env[DEBUG_TEXT_ENV] === '1';
}

function bounded(text, limit) {
  const line = oneLine(text);
  return line.length <= limit ? line : `${line.slice(0, limit)}… (${line.length - limit} more characters)`;
}

function pageText(text, limit = PAGE_TEXT_LIMIT) {
  const value = String(text);
  return debugText()
    ? bounded(value, limit)
    : `${value.length} characters, not logged (${DEBUG_TEXT_ENV}=1 logs them)`;
}

module.exports = { bounded, debugText, logJson, oneLine, pageText, DEBUG_TEXT_ENV, PAGE_TEXT_LIMIT };
