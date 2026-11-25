// The coverage probe font: a TrueType font in which every code point is one
// glyph COVERAGE_ADVANCE_EM wide, nothing else. The text metrics
// (snapshot_text_metrics.mjs splitFallbackRuns) set a character in a run's
// own webfont with this font after it, offscreen: the probe is that face's
// advance where the face draws the character, and exactly the probe font's
// where it does not, whatever fonts the machine has. So which characters a
// deck's webfont lacks is read from the face itself, the same on Linux
// Chromium (Databricks Apps), whose fallback fonts differ, as on a Mac.
//
// It is built here, in Node, once per process, and handed to the page as a
// list of bytes (snapshot.mjs config): the page makes a FontFace of them,
// which a font's bytes load synchronously, adds it to the document's fonts
// for the one probe pass and deletes it again. Its tables are the ones
// Chrome's font sanitizer (OTS) requires of a TrueType font: cmap, glyf,
// head, hhea, hmtx, loca, maxp, name, OS/2 and post. The cmap is one format
// 13 (many-to-one) group, U+0000..U+10FFFF to glyph 1. Both glyphs are a
// small square, so neither outline is empty. Every field is fixed, the
// timestamps included, so the bytes are the same on every build.

export const COVERAGE_FONT_FAMILY = 'tellr-coverage-probe';
// The probe glyph's advance, in ems: wider than any glyph a text face draws.
export const COVERAGE_ADVANCE_EM = 4;

const UNITS_PER_EM = 1000;
const ASCENDER = 800;
const DESCENDER = -200;
const NOTDEF_ADVANCE = 500;
const PROBE_ADVANCE = COVERAGE_ADVANCE_EM * UNITS_PER_EM;
const SQUARE_UNITS = 100;
const LAST_CODE_POINT = 0x10ffff;
const SFNT_VERSION = 0x00010000;
const HEAD_MAGIC = 0x5f0f3cf5;
const CHECKSUM_TARGET = 0xb1b0afba;
const TABLE_RECORD_BYTES = 16;
const OFFSET_TABLE_BYTES = 12;

function uint16(value) {
  const bytes = Buffer.alloc(2);
  bytes.writeUInt16BE(value);
  return bytes;
}

function int16(value) {
  const bytes = Buffer.alloc(2);
  bytes.writeInt16BE(value);
  return bytes;
}

function uint32(value) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32BE(value >>> 0);
  return bytes;
}

function padded(table) {
  return Buffer.concat([table, Buffer.alloc((4 - (table.length % 4)) % 4)]);
}

// The OpenType table checksum: the sum of its big-endian 32-bit words, zero-padded.
function checksum(table) {
  const words = padded(table);
  let sum = 0;
  for (let offset = 0; offset < words.length; offset += 4) sum = (sum + words.readUInt32BE(offset)) >>> 0;
  return sum;
}

function utf16(text) {
  const bytes = Buffer.alloc(text.length * 2);
  for (let index = 0; index < text.length; index++) bytes.writeUInt16BE(text.charCodeAt(index), index * 2);
  return bytes;
}

// One glyph: a square of SQUARE_UNITS, one contour of four on-curve points.
function squareGlyph() {
  const contours = Buffer.concat([int16(1), int16(0), int16(0), int16(SQUARE_UNITS), int16(SQUARE_UNITS)]);
  const endPoints = uint16(3);
  const instructions = uint16(0);
  const flags = Buffer.from([1, 1, 1, 1]);
  const xDeltas = Buffer.concat([int16(0), int16(SQUARE_UNITS), int16(0), int16(-SQUARE_UNITS)]);
  const yDeltas = Buffer.concat([int16(0), int16(0), int16(SQUARE_UNITS), int16(0)]);
  return padded(Buffer.concat([contours, endPoints, instructions, flags, xDeltas, yDeltas]));
}

function nameTable(family) {
  const records = [
    [1, family],
    [2, 'Regular'],
    [3, family],
    [4, family],
    [5, 'Version 1.000'],
    [6, family],
  ];
  const strings = records.map(([, text]) => utf16(text));
  const headers = [];
  let offset = 0;
  records.forEach(([nameId], index) => {
    // Windows, Unicode BMP, US English.
    headers.push(Buffer.concat([uint16(3), uint16(1), uint16(0x409), uint16(nameId), uint16(strings[index].length), uint16(offset)]));
    offset += strings[index].length;
  });
  return Buffer.concat([uint16(0), uint16(records.length), uint16(6 + 12 * records.length), ...headers, ...strings]);
}

function buildCoverageFont() {
  const glyph = squareGlyph();
  const tables = {
    'OS/2': Buffer.concat([
      uint16(4), int16(PROBE_ADVANCE), uint16(400), uint16(5), uint16(0),
      int16(650), int16(600), int16(0), int16(75), int16(650), int16(600), int16(0), int16(350),
      int16(50), int16(250), int16(0), Buffer.alloc(10),
      uint32(0), uint32(0), uint32(0), uint32(0), Buffer.from('NONE'),
      uint16(0x40), uint16(0x20), uint16(0xffff),
      int16(ASCENDER), int16(DESCENDER), int16(0), uint16(ASCENDER), uint16(-DESCENDER),
      uint32(1), uint32(0), int16(500), int16(700), uint16(0), uint16(0x20), uint16(1),
    ]),
    // Format 13: one group mapping every code point to glyph 1.
    cmap: Buffer.concat([
      uint16(0), uint16(1), uint16(3), uint16(10), uint32(12),
      uint16(13), uint16(0), uint32(28), uint32(0), uint32(1),
      uint32(0), uint32(LAST_CODE_POINT), uint32(1),
    ]),
    glyf: Buffer.concat([glyph, glyph]),
    head: Buffer.concat([
      uint32(SFNT_VERSION), uint32(SFNT_VERSION), uint32(0), uint32(HEAD_MAGIC), uint16(0x000b), uint16(UNITS_PER_EM),
      Buffer.alloc(8), Buffer.alloc(8),
      int16(0), int16(0), int16(SQUARE_UNITS), int16(SQUARE_UNITS),
      uint16(0), uint16(8), int16(2), int16(0), int16(0),
    ]),
    hhea: Buffer.concat([
      uint32(SFNT_VERSION), int16(ASCENDER), int16(DESCENDER), int16(0), uint16(PROBE_ADVANCE),
      int16(0), int16(0), int16(SQUARE_UNITS), int16(1), int16(0), int16(0), Buffer.alloc(8), int16(0), uint16(2),
    ]),
    hmtx: Buffer.concat([uint16(NOTDEF_ADVANCE), int16(0), uint16(PROBE_ADVANCE), int16(0)]),
    // Short offsets, in words.
    loca: Buffer.concat([uint16(0), uint16(glyph.length / 2), uint16(glyph.length)]),
    maxp: Buffer.concat([
      uint32(SFNT_VERSION), uint16(2), uint16(4), uint16(1), uint16(0), uint16(0), uint16(2),
      uint16(0), uint16(0), uint16(0), uint16(0), uint16(0), uint16(0), uint16(0), uint16(0),
    ]),
    name: nameTable(COVERAGE_FONT_FAMILY),
    post: Buffer.concat([uint32(0x00030000), uint32(0), int16(-100), int16(50), uint32(0), uint32(0), uint32(0), uint32(0), uint32(0)]),
  };
  const tags = Object.keys(tables).sort();
  let entrySelector = 0;
  while (2 ** (entrySelector + 1) <= tags.length) entrySelector += 1;
  const searchRange = 2 ** entrySelector * TABLE_RECORD_BYTES;
  const offsetTable = Buffer.concat([
    uint32(SFNT_VERSION), uint16(tags.length), uint16(searchRange), uint16(entrySelector),
    uint16(tags.length * TABLE_RECORD_BYTES - searchRange),
  ]);
  const records = [];
  const bodies = [];
  let offset = OFFSET_TABLE_BYTES + TABLE_RECORD_BYTES * tags.length;
  let headOffset = 0;
  for (const tag of tags) {
    const table = tables[tag];
    if (tag === 'head') headOffset = offset;
    records.push(Buffer.concat([Buffer.from(tag), uint32(checksum(table)), uint32(offset), uint32(table.length)]));
    bodies.push(padded(table));
    offset += padded(table).length;
  }
  const font = Buffer.concat([offsetTable, ...records, ...bodies]);
  // head.checkSumAdjustment, so the whole font sums to the OpenType constant.
  font.writeUInt32BE((CHECKSUM_TARGET - checksum(font)) >>> 0, headOffset + 8);
  return font;
}

// The font's bytes, a plain list of numbers, as the page source carries them.
export const COVERAGE_FONT_BYTES = Array.prototype.slice.call(buildCoverageFont());
