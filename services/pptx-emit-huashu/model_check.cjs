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
//       rect is four finite numbers, its mode is 'subtree', 'box' or 'ground' and its
//       selector is a string (capture.cjs checks what that string names); and,
//       for a 'ground' capture, when it is the model's only one, as the snapshot
//       takes one at most (the slide root's image ground, snapshot.mjs groundCapture);
//     * an item is kept when its kind is one the emitters write and every field
//       they read is as the snapshot writes it (snapshot.mjs SlideModel,
//       snapshot_text.mjs TextBlock and Run, snapshot_table.mjs TableItem): each
//       number finite and in the range the emitters can write it in (RANGES,
//       below), each colour RRGGBB, each value of a set one of that set,
//       each text a string (a roundCorners shape's radii four corners, each
//       two lengths above 0 or both 0); an image item also names a capture that is kept, or
//       none; a native table's cells, spans included, lie inside its grid
//       and cover each of its slots once;
//     * the fields: items and captures are lists, background is a raster data:
//       image, a colour, or a colour beside the kept 'ground' capture it names
//       (the slide root's image ground), as emit_model.cjs applyBackground takes it,
//       fonts and italicFonts map families to weights, reference.hiddenText is a
//       string, and stats.elements and stats.pseudoElements are counts.
//   dropLine(dropped) -> '[html2pptx] model: …' | null
//     The one log line that says what was dropped; null when nothing was.
//
// The page-side passes return more than the model (dom_access.mjs passResult),
// and Node checks that too:
//
//   checkDiagnostics(stream, over) -> {entries, over, dropped}
//     What one pass diagnosed: `stream`, its entries in the encoding
//     dom_access.mjs diagnose writes, each read against the engine's own
//     wordings, DIAGNOSTIC_LINES and DIAGNOSTIC_PARTS (below), and taken as
//     the parts log_line.cjs diagnosticLine writes: a wording's text and a
//     number as Node holds them, a page's text as {pageText, length}. So a
//     line says nothing but the engine's wordings, numbers and the page text
//     its slots hold, whatever the page made of the stream. An entry that is
//     no wording of the engine's is dropped and counted; `over`, how many the
//     pass did not keep, is a count or 0.
//   checkBackgroundTransfer(value) -> {value, dropped}
//     The background transfer's result (preprocess.mjs), {bgTransferred} one
//     of BACKGROUND_TRANSFERS, or null, dropped, as the summary logs it.
//   checkAnimations(value) -> {value, dropped}
//     The animations finished (render_slide.cjs pageFinishAnimations),
//     {finished, cancelled, unfinished} three counts, or all 0, dropped.
//   passDropLine(dropped, what) -> '[html2pptx] model: …' | null
//     The log line that says how many of a pass's diagnostics or results
//     (`what`) were dropped; null when none was.

const { PPTXGENJS_INCH_LIMIT, RASTER_DATA_URI } = require('./emit_model.cjs');
const { DIAGNOSTICS_PER_PASS, PAGE_TEXT_LIMIT } = require('./log_line.cjs');
const { PT_PER_PX, PX_PER_IN } = require('./units.cjs');

// RANGES. pptxgenjs writes a number it is given as it is, so one past the range
// its XML attribute takes (ECMA-376 Part 1) writes a deck outside its schema,
// which PowerPoint repairs or refuses. The snapshot writes every number of a
// real slide inside these (an angle it turns to 0..360, a length from 0), so
// only a model slide script shaped falls outside them:
// * an alpha is 0..1 (a:alpha, ST_PositiveFixedPercentage);
// * a length (a box's size, a line's width, a shadow's blur and offset, a
//   radius, a column or row) is from 0 (a:ext, ST_PositiveCoordinate; a:ln w,
//   ST_LineWidth); a line's width at most ST_LineWidth's 20116800 EMU,
//   2112 px. A text box's insets and a cell's margins are no lengths: bodyPr's
//   lIns and a cell's marL are ST_Coordinate32, which runs either way, and a
//   turned box's top inset comes out a hair under 0 (-0.00002 px measured);
// * a shadow's angle is 0 up to a turn (dir, ST_PositiveFixedAngle);
// * a rotation is a turn either way at most;
// * a run's size is 0 (none written) or 1 to 4000 pt (sz, ST_TextFontSize
//   100..400000); a run's three trackings, which emit_typography.cjs adds,
//   2000 pt either way each, so their sum is inside spc's 4000 pt (ST_TextPoint);
// * a line height, a line's growth and a script run's raise, written as
//   spacing and a baseline offset, at most 1584 pt either way,
//   2112 px (spcPts, ST_TextSpacingPoint 0..158400);
// * a path's point lies within PPTXGENJS_INCH_LIMIT inches of the origin, as
//   each item's box must (emit_model.cjs inRange).
const FULL_TURN_DEG = 360;
const LINE_WIDTH_LIMIT_PX = 2112;
const SPACING_LIMIT_PX = 2112;
const RUN_SIZE_MIN_PT = 1;
const RUN_SIZE_MAX_PT = 4000;
const TRACKING_LIMIT_PT = 2000;
const COORDINATE_LIMIT_PX = PPTXGENJS_INCH_LIMIT * PX_PER_IN;

const CAPTURE_ID = /^c\d+$/;
const COLOUR = /^[0-9A-Fa-f]{6}$/;
const CAPTURE_MODES = new Set(['subtree', 'box', 'ground']);
const PSEUDO_ELEMENTS = new Set(['before', 'after', 'marker']);
const GEOMETRIES = new Set(['rect', 'roundRect', 'roundCorners', 'ellipse', 'path']);
// A roundCorners shape's corners: top left, top right, bottom right, bottom left.
const CORNER_COUNT = 4;
const DASHES = new Set(['solid', 'dash', 'dot', 'double']);
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

function isCount(value) {
  return Number.isInteger(value) && value >= 0;
}

function isAlpha(value) {
  return isNumber(value) && value >= 0 && value <= 1;
}

function isLength(value) {
  return isNumber(value) && value >= 0;
}

// A length the snapshot may leave out.
function isOptionalLength(value, limit = Infinity) {
  return value === null || value === undefined || (isLength(value) && value <= limit);
}

// A rotation the snapshot may leave out (null for an unturned item).
function isRotation(value) {
  return value === null || value === undefined || (isNumber(value) && Math.abs(value) <= FULL_TURN_DEG);
}

function isRunSize(px) {
  return isNumber(px) &&
    (px === 0 || (px * PT_PER_PX >= RUN_SIZE_MIN_PT && px * PT_PER_PX <= RUN_SIZE_MAX_PT));
}

function isTracking(px) {
  return isNumber(px) && Math.abs(px * PT_PER_PX) <= TRACKING_LIMIT_PT;
}

function isCoordinate(value) {
  return isNumber(value) && Math.abs(value) <= COORDINATE_LIMIT_PX;
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

// An item's box: its size a length.
function isSizedBox(value) {
  return isBox(value) && isLength(value.w) && isLength(value.h);
}

// A shape's fill, or a native table cell's: {color, alpha}.
function isFill(value) {
  return isObject(value) && isColour(value.color) && isAlpha(value.alpha);
}

// A shape's outline, a line item, or a cell's border: {color, alpha, widthPx, dash}.
function isStroke(value) {
  return isFill(value) && isLength(value.widthPx) && value.widthPx <= LINE_WIDTH_LIMIT_PX &&
    DASHES.has(value.dash);
}

function isShadow(value) {
  return isFill(value) && isLength(value.blurPx) && isLength(value.offsetPx) &&
    isNumber(value.angle) && value.angle >= 0 && value.angle < FULL_TURN_DEG;
}

function isRun(run) {
  return isObject(run) &&
    typeof run.text === 'string' &&
    typeof run.family === 'string' &&
    isNumber(run.weight) &&
    typeof run.italic === 'boolean' &&
    isRunSize(run.sizePx) &&
    isColour(run.color) &&
    isTracking(run.letterSpacingPx) &&
    typeof run.underline === 'boolean' &&
    typeof run.strike === 'boolean' &&
    (run.baseline === null || BASELINES.has(run.baseline)) &&
    (run.raisePx === undefined || (isNumber(run.raisePx) && Math.abs(run.raisePx) <= SPACING_LIMIT_PX)) &&
    isTracking(run.opticalTrackingPx) &&
    isTracking(run.unkernedTrackingPx);
}

function isLine(line) {
  return isObject(line) && isListOf(line.runs, isRun) &&
    (line.growthPx === undefined || isOptionalLength(line.growthPx, SPACING_LIMIT_PX));
}

function isParagraph(paragraph) {
  return isObject(paragraph) &&
    isLength(paragraph.sizePx) &&
    isOptionalLength(paragraph.lineHeightPx, SPACING_LIMIT_PX) &&
    isOptionalLength(paragraph.ascentPx) &&
    isListOf(paragraph.lines, isLine);
}

// A corner's radii {h, v}: two finite lengths above 0, or both 0 for a square
// corner, as the snapshot writes them (cornerGeometry: a corner either radius
// of which is 0 is square).
function isCorner(corner) {
  return hasNumbers(corner, ['h', 'v']) && ((corner.h > 0 && corner.v > 0) || (corner.h === 0 && corner.v === 0));
}

function isShape(item) {
  if (!isSizedBox(item) || !GEOMETRIES.has(item.geometry) || !isRotation(item.rotate)) return false;
  if (item.geometry === 'roundRect' ? !isLength(item.radius) : !isOptionalLength(item.radius)) return false;
  if (item.geometry === 'roundCorners' && !(isListOf(item.radii, isCorner) && item.radii.length === CORNER_COUNT)) return false;
  if (item.fill !== null && !isFill(item.fill)) return false;
  if (item.line !== null && !isStroke(item.line)) return false;
  if (item.shadow !== null && !isShadow(item.shadow)) return false;
  if (item.geometry !== 'path') return true;
  return typeof item.closed === 'boolean' &&
    isListOf(item.path, (polyline) => isListOf(polyline, (point) =>
      isObject(point) && isCoordinate(point.x) && isCoordinate(point.y)));
}

function isLineItem(item) {
  return hasNumbers(item, ['x1', 'y1', 'x2', 'y2']) && isStroke(item);
}

function isImage(item, captureIds) {
  return isSizedBox(item) &&
    isRotation(item.rotate) &&
    (item.alpha === null || item.alpha === undefined || isAlpha(item.alpha)) &&
    (item.src === null || item.src === undefined || typeof item.src === 'string') &&
    (item.captureId === null || item.captureId === undefined || captureIds.has(item.captureId));
}

function isText(item) {
  return isSizedBox(item) &&
    isRotation(item.rotate) &&
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
      typeof cell.font.italic === 'boolean' && isLength(cell.font.sizePx))) &&
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
    isListOf(item.colWidths, isLength) &&
    isListOf(item.rowHeights, isLength);
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

// The captures kept, in order: each well formed, with an id no other has, and
// a ground capture only when no other capture is one.
function checkCaptures(captures) {
  const seen = new Map();
  let grounds = 0;
  for (const capture of captures) {
    if (!isCapture(capture)) continue;
    seen.set(capture.id, (seen.get(capture.id) || 0) + 1);
    if (capture.mode === 'ground') grounds += 1;
  }
  return captures.filter((capture) => isCapture(capture) && seen.get(capture.id) === 1 &&
    (capture.mode !== 'ground' || grounds === 1));
}

// The slide's ground as emit_model.cjs applyBackground takes it: an image only
// when it is a raster data: URI, a ground picture only when it names the kept
// 'ground' capture (never a chart's or a box's picture), and otherwise a
// colour, which must be one (a ground picture's too, what the slide falls back
// to). `groundIds` holds the ids of the kept ground captures.
function isBackground(background, groundIds) {
  if (background === null) return true;
  if (!isObject(background)) return false;
  if (typeof background.image === 'string' && RASTER_DATA_URI.test(background.image)) return true;
  if (background.captureId !== undefined && !groundIds.has(background.captureId)) return false;
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
  const groundIds = new Set(captures.filter((capture) => capture.mode === 'ground').map((capture) => capture.id));
  const background = kept(isBackground(source.background, groundIds), source.background, null);
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

// ─── the passes' diagnostics ──────────────────────────────────────────
// The wordings of the engine's page-side diagnostics, by the key the page code
// names each with (dom_access.mjs diagnose): DIAGNOSTIC_LINES a whole line's,
// after the pass's prefix ([preprocess] or [html2pptx], render_slide.cjs),
// DIAGNOSTIC_PARTS the parts a line's slots hold. A slot takes what follows
// the key in the entry, in order:
//   {n}  a number the engine counted, written as JavaScript writes a number;
//   {p}  a page's text: its length, then the first PAGE_TEXT_LIMIT characters
//        of it at most, which log_line.cjs diagnosticLine says with the debug
//        text on and by its length alone without it;
//   {w}  a part: its key, then what its own slots take;
//   {l}  a list of parts: how many there were, how many of them follow (at
//        most DIAGNOSTIC_LIST_LIMIT), then each, said one after the other
//        with ' | ' between, '(none)' for none, and how many more there were.
const DIAGNOSTIC_LINES = {
  // dom_access.mjs reportCollectionLoss: what the collection lost, then where.
  collection: 'collection {w} in {w}: content past that point is NOT in the exported deck. This bound is ' +
    'unreachable for real slide content, so meeting it means the document presented an implausible ' +
    'collection or the realm is lying about one.',
  // preprocess.mjs
  noSlideRoot: 'no slide root: body children [{p}]; wrapper candidates {l}; tree reads {w}. A chain over ' +
    '509 levels deep is reparsed by Chromium into siblings and is not resolvable here by design.',
  rootUnmarked: 'could not mark the slide root: {p}',
  // snapshot.mjs
  gradientUnread: 'a background gradient could not be read; the text over it is blended without its ' +
    'colour (further ones on this slide are not said)',
  bodyGradient: 'gradient on the slide body: the slide background uses its colour instead',
  nonDataBackground: 'skipped a non-data: background image',
  captureUnnamed: 'capture failed: c{n} the target could not be named ({p})',
  // snapshot_text.mjs
  fontsUnread: 'document.fonts could not be read ({p}); a family whose faces were not read exports ' +
    'without weight-named faces',
  fragmentsUnread: 'the box fragments of an inline element could not be read ({p}); its box is not in ' +
    'the exported deck',
  fragmentsFailed: 'reading the box fragments of an inline element failed ({p}); the fragments past ' +
    'that point are not in the exported deck',
  // snapshot_text_metrics.mjs: what a probe could not read, then what the slide exports without.
  probesUnread: 'the text metric probes could not be read ({p}); {w}',
  probesUnmeasured: 'text metric probes: {n} of {n} measured no width, as the page hid or emptied them; ' +
    'where they are read, {w}',
  coverageFontNotAdded: 'the coverage probe font could not be added; {w}',
  coverageFontNotDeleted: 'the coverage probe font could not be deleted ({p})',
  markersUnmeasured: 'list markers: {n} of {n} marker width(s) measured no finite size; those markers ' +
    'are placed at their boxes, trailing space included, and an inside one joins its line as the ' +
    'browser laid it out',
  // snapshot_table.mjs positioned: why.
  nativeTable: 'native table: {w}; it exports as positioned items',
  // snapshot_borders.mjs
  boxShadowFits: 'box-shadow fits: {n} box(es) past the {n} fits a slide makes carry their first shadow layer',
};
const DIAGNOSTIC_PARTS = {
  // What a collection lost (dom_access.mjs reportCollectionLoss).
  truncatedItems: 'truncated at {n} items',
  truncatedOfItems: 'truncated at {n} of {n} items',
  droppedLength: 'dropped entirely, length read as {p}',
  cutAtDepth: 'cut at depth {n}',
  truncatedTextReads: 'truncated at {n} text reads',
  truncatedElements: 'truncated at {n} elements',
  truncatedFontFaces: 'truncated at {n} font faces',
  truncatedOfFragments: 'truncated at {n} of {n} box fragments',
  // Where.
  childNodesOf: 'childNodesOf',
  elementChildrenOf: 'elementChildrenOf',
  nodeListToArray: 'nodeListToArray',
  textLayout: 'the snapshot text layout',
  webfontRead: 'the snapshot webfont read',
  inlineFragments: 'the snapshot inline fragments',
  captureTargets: 'the snapshot capture targets',
  walk: 'the snapshot walk',
  // A slide-root candidate the walk stopped at (preprocess.mjs walkToSlideBody): its tag, then why.
  wrapperCandidate: '{p} after {n} level(s): {w}',
  unreadCandidate: '(unread) after {n} level(s): {w}',
  noElementChildren: 'no element children',
  severalElementChildren: 'several element children',
  notPromotable: 'not a promotable wrapper',
  iterationLimit: 'iteration limit reached',
  pristineTree: 'pristine',
  thisRealmTree: 'this-realm',
  // What a slide exports without where its probes are not read (snapshot_text_metrics.mjs measureProbes).
  lossFirstFamily: "this slide's text with no loaded webfont is written in each stack's first family",
  lossLackingCharacters: 'this slide exports the characters its webfonts lack in its own fonts, as each ' +
    'app falls back',
  lossMarkers: 'this slide exports its list markers at their boxes, trailing space included, and joins ' +
    'each inside one to its line as the browser laid it out',
  lossLineSpacing: 'this slide exports without line spacing, optical-size and kerning tracking',
  lossTurnedLines: 'turned text is placed across its lines by its font size, not by its face',
  lossScriptRaises: 'this slide exports its superscripts and subscripts at the renderers\' own raise',
  lossEllipsis: 'a text-overflow: ellipsis line exports as its overflow clip shows it, without its "…"',
  // Why a table is no a:tbl (snapshot_table.mjs).
  columnSpanUnread: "a column's span could not be read",
  columnsPass: 'its columns pass {n}',
  rowsPass: 'its {n} rows pass {n}',
  cellSpansUnread: "a cell's spans could not be read",
  cellsCover: 'its cells cover more than {n} grid slots',
  slotCoveredTwice: 'two of its cells cover one grid slot',
  gridPasses: 'its grid of {n} rows by {n} columns passes {n} slots',
};
// The most characters one entry holds: its tokens, each after its length. The
// longest the engine writes is a slide with no root naming its body's children
// and DIAGNOSTIC_LIST_LIMIT candidates, under 3,500.
const DIAGNOSTIC_ENTRY_LIMIT = 8192;
const DIAGNOSTIC_TOKEN_LIMIT = 128;
// The parts a list holds (preprocess.mjs: the slide-root candidates it names).
const DIAGNOSTIC_LIST_LIMIT = 8;
// How deep parts hold parts: a list's candidate holds its reason.
const DIAGNOSTIC_DEPTH_LIMIT = 3;
const NUMBER_TEXT = /^(?:-?(?:\d+(?:\.\d+)?(?:e[+-]\d+)?|Infinity)|NaN)$/;
const COUNT_TEXT = /^\d{1,9}$/;

// Each wording as its pieces: its text, and each slot by its letter.
function compiled(wordings) {
  const pieces = new Map();
  for (const [key, wording] of Object.entries(wordings)) {
    pieces.set(key, wording.split(/\{([npwl])\}/).map((piece, index) => (index % 2 ? { slot: piece } : piece))
      .filter((piece) => piece !== ''));
  }
  return pieces;
}
const LINE_PIECES = compiled(DIAGNOSTIC_LINES);
const PART_PIECES = compiled(DIAGNOSTIC_PARTS);

// The string `<length>:<string>` at `at` of `text`, and where it ends, or null.
function lengthPrefixed(text, at) {
  const colon = text.indexOf(':', at);
  if (colon < 0 || !COUNT_TEXT.test(text.slice(at, colon))) return null;
  const end = colon + 1 + Number(text.slice(at, colon));
  return end <= text.length ? { value: text.slice(colon + 1, end), end } : null;
}

// The next token's count, or null.
function countOf(reading) {
  const token = reading.tokens[reading.next++];
  return typeof token === 'string' && COUNT_TEXT.test(token) ? Number(token) : null;
}

// Reads the wording whose key is the next token, of `wordings`, onto `parts`:
// whether the tokens are one the engine writes.
function readWording(wordings, reading, parts, depth) {
  if (depth > DIAGNOSTIC_DEPTH_LIMIT) return false;
  const pieces = wordings.get(reading.tokens[reading.next++]);
  if (!pieces) return false;
  for (const piece of pieces) {
    if (typeof piece === 'string') {
      parts.push(piece);
    } else if (piece.slot === 'n') {
      const token = reading.tokens[reading.next++];
      if (typeof token !== 'string' || !NUMBER_TEXT.test(token)) return false;
      parts.push(token);
    } else if (piece.slot === 'p') {
      const length = countOf(reading);
      const text = reading.tokens[reading.next++];
      if (length === null || typeof text !== 'string' || text.length > PAGE_TEXT_LIMIT || text.length > length) {
        return false;
      }
      parts.push({ pageText: text, length });
    } else if (piece.slot === 'w') {
      if (!readWording(PART_PIECES, reading, parts, depth + 1)) return false;
    } else {
      const total = countOf(reading);
      const listed = countOf(reading);
      if (total === null || listed === null || listed > total || listed > DIAGNOSTIC_LIST_LIMIT ||
          (listed === 0) !== (total === 0)) return false;
      if (total === 0) parts.push('(none)');
      for (let index = 0; index < listed; index++) {
        if (index) parts.push(' | ');
        if (!readWording(PART_PIECES, reading, parts, depth + 1)) return false;
      }
      if (total > listed) parts.push(` | and ${total - listed} more`);
    }
  }
  return true;
}

// One entry's parts, or null when it is no line the engine writes.
function entryParts(entry) {
  if (entry.length > DIAGNOSTIC_ENTRY_LIMIT) return null;
  const tokens = [];
  for (let at = 0; at < entry.length;) {
    const token = lengthPrefixed(entry, at);
    if (token === null || tokens.length >= DIAGNOSTIC_TOKEN_LIMIT) return null;
    tokens.push(token.value);
    at = token.end;
  }
  const reading = { tokens, next: 0 };
  const parts = [];
  return readWording(LINE_PIECES, reading, parts, 0) && reading.next === tokens.length ? parts : null;
}

function checkDiagnostics(stream, over) {
  const kept = isCount(over) ? over : 0;
  let dropped = isCount(over) ? 0 : 1;
  if (typeof stream !== 'string') return { entries: [], over: kept, dropped: dropped + 1 };
  const entries = [];
  for (let at = 0; at < stream.length;) {
    const entry = entries.length + dropped < DIAGNOSTICS_PER_PASS ? lengthPrefixed(stream, at) : null;
    if (entry === null) {
      // What follows is no entry the page side writes: the rest of the stream counts as one.
      dropped += 1;
      break;
    }
    const parts = entryParts(entry.value);
    if (parts) entries.push(parts);
    else dropped += 1;
    at = entry.end;
  }
  return { entries, over: kept, dropped };
}

// What preprocess.mjs transferSlideRootBackground returns.
const BACKGROUND_TRANSFERS = new Set(['image', 'gradient-raster', 'gradient-firststop', 'solid', 'unchanged', 'no-root']);

function checkBackgroundTransfer(value) {
  if (isObject(value) && BACKGROUND_TRANSFERS.has(value.bgTransferred)) {
    return { value: { bgTransferred: value.bgTransferred }, dropped: 0 };
  }
  return { value: null, dropped: 1 };
}

const NO_ANIMATIONS = { finished: 0, cancelled: 0, unfinished: 0 };

function checkAnimations(value) {
  if (isObject(value) && isCount(value.finished) && isCount(value.cancelled) && isCount(value.unfinished)) {
    return { value: { finished: value.finished, cancelled: value.cancelled, unfinished: value.unfinished }, dropped: 0 };
  }
  return { value: { ...NO_ANIMATIONS }, dropped: 1 };
}

function passDropLine(dropped, what) {
  if (!dropped) return null;
  return `[html2pptx] model: ${dropped} ${what} failed validation and were dropped`;
}

module.exports = {
  checkAnimations,
  checkBackgroundTransfer,
  checkDiagnostics,
  checkModel,
  dropLine,
  passDropLine,
  DIAGNOSTIC_LINES,
  DIAGNOSTIC_PARTS,
};
