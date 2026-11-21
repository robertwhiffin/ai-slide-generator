'use strict';
// The slide model as Node takes it: checked before any of it is used.
//
// The snapshot (snapshot.mjs) builds the model in the slide's own realm, with the
// Array.prototype.push, the setters and every other built-in slide script can
// replace, and page.evaluate hands back whatever that realm made of it. So slide
// script can shape any part of the model: a capture's id, which capture.cjs
// prints and keys its pictures by; a box's numbers; a colour, which pptxgenjs
// writes into the deck's XML as it is; an item's kind. Node trusts none of it.
//
//   checkModel(model) -> {model, dropped: {items, captures, fields}}
//     The model with every capture and item the snapshot could not have written
//     dropped, and each field of the model itself that it could not have
//     written reset, as an empty slide has it. Everything else is kept as it is,
//     the same objects, so the slide exports all that is valid:
//     * a capture is kept when its id is c<n> and no other capture has it, its
//       rect is four finite numbers, its mode is 'subtree' or 'box' and its
//       selector is a string (capture.cjs checks what that string names);
//     * an item is kept when its kind is one the emitters write and every field
//       they read is as the snapshot writes it (snapshot.mjs SlideModel,
//       snapshot_text.mjs TextBlock and Run, snapshot_table.mjs TableItem): each
//       number finite, each colour RRGGBB, each value of a set one of that set,
//       each text a string; an image item also names a capture that is kept, or
//       none; a native table's cells, spans included, lie inside its grid
//       and cover each of its slots once;
//     * the fields: items and captures are lists, background is a raster data:
//       image or else a colour (as emit_model.cjs applyBackground takes it),
//       fonts and italicFonts map families to weights, reference.hiddenText is a
//       string, and stats.elements and stats.pseudoElements are counts.
//   dropLine(dropped) -> '[html2pptx] model: …' | null
//     The one log line that says what was dropped; null when nothing was.

const { RASTER_DATA_URI } = require('./emit_model.cjs');

const CAPTURE_ID = /^c\d+$/;
const COLOUR = /^[0-9A-Fa-f]{6}$/;
const CAPTURE_MODES = new Set(['subtree', 'box']);
const PSEUDO_ELEMENTS = new Set(['before', 'after', 'marker']);
const GEOMETRIES = new Set(['rect', 'roundRect', 'ellipse', 'path']);
const DASHES = new Set(['solid', 'dash', 'dot']);
// What a shape may be besides itself (snapshot.mjs SlideModel): a shadow shape.
const SHAPE_ROLES = new Set(['shadow']);
const ALIGNMENTS = new Set(['left', 'center', 'right', 'justify']);
const ANCHORS = new Set(['top', 'middle', 'bottom']);
const BASELINES = new Set(['super', 'sub']);
const SIDES = ['top', 'right', 'bottom', 'left'];
// The most grid slots a native table may have: the snapshot's own bound
// (snapshot_table.mjs slotsOf, dom_access.mjs COLLECTION_ITEM_LIMIT), which
// also bounds the walk over its slots here.
const GRID_SLOT_LIMIT = 1000000;

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

// A number the snapshot may leave out (null, or no field at all).
function isOptionalNumber(value) {
  return value === null || value === undefined || isNumber(value);
}

function isCount(value) {
  return Number.isInteger(value) && value >= 0;
}

function isColour(value) {
  return typeof value === 'string' && COLOUR.test(value);
}

function isObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isListOf(value, check) {
  return Array.isArray(value) && value.every(check);
}

function hasNumbers(value, keys) {
  return isObject(value) && keys.every((key) => isNumber(value[key]));
}

function isBox(value) {
  return hasNumbers(value, ['x', 'y', 'w', 'h']);
}

// A shape's fill, or a native table cell's: {color, alpha}.
function isFill(value) {
  return isObject(value) && isColour(value.color) && isNumber(value.alpha);
}

// A shape's outline, a line item, or a cell's border: {color, alpha, widthPx, dash}.
function isStroke(value) {
  return isFill(value) && isNumber(value.widthPx) && DASHES.has(value.dash);
}

function isShadow(value) {
  return isFill(value) && hasNumbers(value, ['blurPx', 'offsetPx', 'angle']);
}

function isRun(run) {
  return isObject(run) &&
    typeof run.text === 'string' &&
    typeof run.family === 'string' &&
    isNumber(run.weight) &&
    typeof run.italic === 'boolean' &&
    isNumber(run.sizePx) &&
    isColour(run.color) &&
    isNumber(run.letterSpacingPx) &&
    typeof run.underline === 'boolean' &&
    typeof run.strike === 'boolean' &&
    (run.baseline === null || BASELINES.has(run.baseline)) &&
    isNumber(run.opticalTrackingPx) &&
    isNumber(run.unkernedTrackingPx);
}

function isLine(line) {
  return isObject(line) && isListOf(line.runs, isRun) && (line.growthPx === undefined || isNumber(line.growthPx));
}

function isParagraph(paragraph) {
  return isObject(paragraph) &&
    isNumber(paragraph.sizePx) &&
    isOptionalNumber(paragraph.lineHeightPx) &&
    isOptionalNumber(paragraph.ascentPx) &&
    isListOf(paragraph.lines, isLine);
}

function isShape(item) {
  if (!isBox(item) || !GEOMETRIES.has(item.geometry) || !isOptionalNumber(item.rotate)) return false;
  if (item.role !== undefined && !SHAPE_ROLES.has(item.role)) return false;
  if (item.geometry === 'roundRect' ? !isNumber(item.radius) : !isOptionalNumber(item.radius)) return false;
  if (item.fill !== null && !isFill(item.fill)) return false;
  if (item.line !== null && !isStroke(item.line)) return false;
  if (item.shadow !== null && !isShadow(item.shadow)) return false;
  if (item.geometry !== 'path') return true;
  return typeof item.closed === 'boolean' &&
    isListOf(item.path, (polyline) => isListOf(polyline, (point) => hasNumbers(point, ['x', 'y'])));
}

function isLineItem(item) {
  return hasNumbers(item, ['x1', 'y1', 'x2', 'y2']) && isStroke(item);
}

function isImage(item, captureIds) {
  return isBox(item) &&
    isOptionalNumber(item.rotate) &&
    isOptionalNumber(item.alpha) &&
    (item.src === null || item.src === undefined || typeof item.src === 'string') &&
    (item.captureId === null || item.captureId === undefined || captureIds.has(item.captureId));
}

function isText(item) {
  return isBox(item) &&
    isOptionalNumber(item.rotate) &&
    typeof item.wrap === 'boolean' &&
    ALIGNMENTS.has(item.align) &&
    typeof item.rtl === 'boolean' &&
    (item.inset === undefined || hasNumbers(item.inset, ['left', 'top', 'right', 'bottom'])) &&
    isListOf(item.paragraphs, isParagraph);
}

// A native table cell, in a grid of `rows` by `columns` slots: it and its
// spans lie inside the grid.
function isCell(cell, rows, columns) {
  return isObject(cell) &&
    isCount(cell.row) && isCount(cell.rowspan) && cell.rowspan >= 1 && cell.row + cell.rowspan <= rows &&
    isCount(cell.col) && isCount(cell.colspan) && cell.colspan >= 1 && cell.col + cell.colspan <= columns &&
    (cell.fill === null || isFill(cell.fill)) &&
    isObject(cell.borders) && SIDES.every((side) => cell.borders[side] === null || isStroke(cell.borders[side])) &&
    hasNumbers(cell.margin, SIDES) &&
    ANCHORS.has(cell.valign) &&
    ALIGNMENTS.has(cell.align) &&
    (cell.rtl === undefined || typeof cell.rtl === 'boolean') &&
    (cell.font === null || cell.font === undefined || (isObject(cell.font) &&
      typeof cell.font.family === 'string' && isNumber(cell.font.weight) &&
      typeof cell.font.italic === 'boolean' && isNumber(cell.font.sizePx))) &&
    (cell.paragraphs === null || isListOf(cell.paragraphs, isParagraph));
}

// Whether `cells` (each inside the grid, isCell) cover every slot of a grid of
// `rows` by `columns`, each slot once, as the snapshot writes an a:tbl: every
// slot is a cell of it, those no HTML cell covers included, and pptxgenjs
// lays a row's cells out by their order and spans, so a slot two cells cover,
// or none, shifts the rest of the row. A grid of more than GRID_SLOT_LIMIT
// slots is none the snapshot writes.
function fillsGrid(cells, rows, columns) {
  if (rows * columns > GRID_SLOT_LIMIT) return false;
  const covered = new Uint8Array(rows * columns);
  let count = 0;
  for (const cell of cells) {
    for (let row = cell.row; row < cell.row + cell.rowspan; row++) {
      for (let column = cell.col; column < cell.col + cell.colspan; column++) {
        const slot = row * columns + column;
        if (covered[slot]) return false;
        covered[slot] = 1;
        count += 1;
      }
    }
  }
  return count === rows * columns;
}

// A native table: a grid of at least one row and one column, as the snapshot
// writes one (an empty grid is no table there), whose cells fill it. pptxgenjs
// throws on a table with no rows, failing the whole slide, and writes a row of
// no cells for one with no columns.
function isTable(item) {
  const grid = hasNumbers(item, ['x', 'y']) &&
    isListOf(item.colWidths, isNumber) &&
    isListOf(item.rowHeights, isNumber);
  if (!grid) return false;
  const rows = item.rowHeights.length;
  const columns = item.colWidths.length;
  if (rows < 1 || columns < 1) return false;
  return isListOf(item.cells, (cell) => isCell(cell, rows, columns)) && fillsGrid(item.cells, rows, columns);
}

function isItem(item, captureIds) {
  if (!isObject(item)) return false;
  if (item.kind === 'shape') return isShape(item);
  if (item.kind === 'line') return isLineItem(item);
  if (item.kind === 'image') return isImage(item, captureIds);
  if (item.kind === 'text') return isText(item);
  if (item.kind === 'table') return isTable(item);
  return false;
}

function isCapture(capture) {
  return isObject(capture) &&
    typeof capture.id === 'string' && CAPTURE_ID.test(capture.id) &&
    isBox(capture) &&
    CAPTURE_MODES.has(capture.mode) &&
    typeof capture.selector === 'string' &&
    (capture.pseudo === null || capture.pseudo === undefined || PSEUDO_ELEMENTS.has(capture.pseudo));
}

// The captures kept, in order: each well formed, with an id no other has.
function checkCaptures(captures) {
  const seen = new Map();
  for (const capture of captures) {
    if (isCapture(capture)) seen.set(capture.id, (seen.get(capture.id) || 0) + 1);
  }
  return captures.filter((capture) => isCapture(capture) && seen.get(capture.id) === 1);
}

// The slide's ground as emit_model.cjs applyBackground takes it: an image only
// when it is a raster data: URI, and otherwise a colour, which must be one.
function isBackground(background) {
  if (background === null) return true;
  if (!isObject(background)) return false;
  if (typeof background.image === 'string' && RASTER_DATA_URI.test(background.image)) return true;
  return isColour(background.color);
}

function isFonts(fonts) {
  return isObject(fonts) && Object.keys(fonts).every((family) => isListOf(fonts[family], isNumber));
}

function checkModel(model) {
  const source = isObject(model) ? model : {};
  let fields = isObject(model) ? 0 : 1;
  const listOf = (value) => {
    if (Array.isArray(value)) return value;
    fields += 1;
    return [];
  };
  const givenCaptures = listOf(source.captures);
  const givenItems = listOf(source.items);
  const captures = checkCaptures(givenCaptures);
  const captureIds = new Set(captures.map((capture) => capture.id));
  const items = givenItems.filter((item) => isItem(item, captureIds));
  const kept = (valid, value, empty) => {
    if (valid) return value;
    fields += 1;
    return empty;
  };
  const background = kept(isBackground(source.background), source.background, null);
  const fonts = kept(isFonts(source.fonts), source.fonts, {});
  const italicFonts = kept(isFonts(source.italicFonts), source.italicFonts, {});
  const reference = kept(isObject(source.reference) && typeof source.reference.hiddenText === 'string',
    source.reference, { hiddenText: '' });
  const stats = isObject(source.stats) ? source.stats : {};
  const counts = kept(isCount(stats.elements) && isCount(stats.pseudoElements),
    { elements: stats.elements, pseudoElements: stats.pseudoElements }, { elements: 0, pseudoElements: 0 });
  return {
    model: {
      ...source,
      background,
      items,
      captures,
      fonts,
      italicFonts,
      reference,
      stats: { ...stats, ...counts },
    },
    dropped: {
      items: givenItems.length - items.length,
      captures: givenCaptures.length - captures.length,
      fields,
    },
  };
}

function dropLine(dropped) {
  if (!dropped.items && !dropped.captures && !dropped.fields) return null;
  const fields = dropped.fields ? `; ${dropped.fields} model field(s) were reset` : '';
  return `[html2pptx] model: ${dropped.items} item(s) and ${dropped.captures} capture(s) failed validation ` +
    `and were dropped${fields}`;
}

module.exports = { checkModel, dropLine };
