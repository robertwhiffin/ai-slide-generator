'use strict';
// Writes one native table of the slide model (snapshot_table.mjs) as a
// pptxgenjs table: one editable a:tbl in a p:graphicFrame, on the browser's grid.
//
// The table's own options are geometry only: x, y, the grid's column widths
// and row heights, w and h their sums (so the frame is the table's rect, not
// pptxgenjs's default one-inch height), and no auto-paging. pptxgenjs copies a
// table-level align, bold, border, colour, fill, fontFace, fontSize, margin,
// underline or valign onto every cell that has none, and every option of a
// cell onto each of its runs whose own value is falsy (bold: false,
// charSpacing: 0), so every run carries its whole style itself
// (emit_typography.cjs runOptions) and the table none.
//
// Each cell carries:
// * colspan and rowspan above 1; pptxgenjs writes the hMerge placeholders
//   after a spanning cell and the vMerge ones below it;
// * its fill, its alpha as transparency;
// * its borders [top, right, bottom, left], each {type, pt, color}: the line
//   CSS collapses its edge to, the same on the cell across it, or 'none', so
//   every side is written and none contradicts its neighbour's. pptxgenjs
//   writes a table border solid or dashed (prstDash solid or sysDash), so a
//   dotted side is passed dashed and its prstDash is written sysDot once the
//   deck is written (emit_rewrite.cjs rewriteDeck): PowerPoint draws sysDot one width on
//   and one off, as CSS paints a dotted border, and Drive converts it to its
//   DOT, one on and three off, the nearest dash a Google table border has
//   (scripts/export_fidelity/CALIBRATION.md D10). A cell border is one a:ln,
//   which holds no second stroke, so the deck for Google Slides cannot draw
//   it twice as it does a dotted line (emit_dotted.cjs). A double side is
//   passed solid and written a double compound line (cmpd="dbl") in the deck
//   for PowerPoint, which draws it; Drive makes a double table border one
//   solid line, so in the deck for Google Slides it is no line on its cells
//   and drawn over the table as its two lines (pushDoubleEdges; CALIBRATION.md T7);
// * its margins [top, right, bottom, left]. pptxgenjs 3.12 reads all four as
//   points when the TOP one is 1 or more, and as inches otherwise
//   (pptxgen.cjs.js:5327): a cell whose top margin is an inch or more passes
//   all four in points, any other in inches, uncapped, so each keeps its size;
// * valign, its text's anchor, and align, its paragraphs' alignment;
// * fontFace and fontSize, its own face. pptxgenjs writes them on each
//   paragraph's end mark (a:endParaRPr), at the table default of 12 pt when a
//   cell has none, and PowerPoint sets a line at least as tall as the end mark
//   on it: under 12 pt marks, a row of 11 px text would grow past the
//   browser's height. A run always names its own face and size, so neither
//   option reaches one;
// * its text: the runs of its paragraphs as a text box writes them
//   (emit_text.cjs textObjects: soft breaks, line spacing, right-to-left), or
//   none for a cell whose text is overlay items, or that holds none. A line
//   set tighter than the apps' single spacing carries its spacing even alone
//   in its cell (emit_text.cjs cellSpacingOf), so the apps do not grow its row.

const path = require('path');
const { textObjects } = require('./emit_text.cjs');
const { runOptions, transparencyOf } = require('./emit_typography.cjs');
const { EMU_PER_IN, PT_PER_PX, PX_PER_IN, inches } = require('./units.cjs');

// pptxgenjs reads a cell's margins as points from a top margin of this many px (1 in) up.
const POINT_MARGINS_FROM_PX = PX_PER_IN;
// pptxgenjs replaces a row height of 0 with an even share of the frame's
// height, so a grid line pair that meets is written one EMU apart.
const SMALLEST_SIZE_IN = 1 / EMU_PER_IN;
// pptxgenjs table borders are solid or dashed; a dotted one is passed dashed
// and written sysDot, a double one passed solid and written double, once the
// deck is written (emit_rewrite.cjs rewriteDeck, rewrittenTablesXml).
const BORDER_TYPES = { solid: 'solid', dash: 'dash', dot: 'dash', double: 'solid' };
// The a:tcPr border element of each side, and the dashes pptxgenjs and a
// dotted side write.
const SIDE_ELEMENTS = { top: 'lnT', right: 'lnR', bottom: 'lnB', left: 'lnL' };
const PPTXGENJS_DASH = '<a:prstDash val="sysDash"/>';
const DOTTED_DASH = '<a:prstDash val="sysDot"/>';
// The compound pptxgenjs writes on a table border, and the one a double side is
// written with (its two lines each a third of its width, a third apart).
const SINGLE_COMPOUND = 'cmpd="sng"';
const DOUBLE_COMPOUND = 'cmpd="dbl"';

// pptxgenjs slide -> the sides of each table emitted on it that are rewritten,
// in the order emitted, which is the order of its a:tbl elements in the
// slide's XML: Map<'row:col', Map<'lnT' | 'lnR' | 'lnB' | 'lnL', 'dot' |
// 'double'>> per table, one per table so the n-th belongs to the n-th a:tbl.
// Keyed weakly, per slide object.
const rewrittenSides = new WeakMap();

// Records the dotted sides of `item` on `slide`, and, but in the deck for
// Google Slides (`forGoogle`), which draws them as strokes over the table
// (pushDoubleEdges), its double ones.
function recordRewrittenSides(slide, item, forGoogle) {
  const sides = new Map();
  for (const cell of item.cells) {
    for (const side of Object.keys(SIDE_ELEMENTS)) {
      const border = cell.borders[side];
      if (!border || !(border.dash === 'dot' || (border.dash === 'double' && !forGoogle))) continue;
      const key = `${cell.row}:${cell.col}`;
      if (!sides.has(key)) sides.set(key, new Map());
      sides.get(key).set(SIDE_ELEMENTS[side], border.dash);
    }
  }
  if (!rewrittenSides.has(slide)) rewrittenSides.set(slide, []);
  rewrittenSides.get(slide).push(sides);
}

// tableSidesOf(slide) -> the recorded sides of each table on `slide`, in its
// a:tbl order (recordRewrittenSides), [] for none; whether any of them is to be
// rewritten is whether any map holds an entry.
function tableSidesOf(slide) {
  return rewrittenSides.get(slide) || [];
}

// One table side's a:ln as its recorded dash writes it: a dotted one sysDot,
// a double one a double compound line.
function rewrittenSide(line, dash) {
  if (dash === 'dot') return line.replace(PPTXGENJS_DASH, DOTTED_DASH);
  if (dash === 'double') return line.replace(SINGLE_COMPOUND, DOUBLE_COMPOUND);
  return line;
}

// rewrittenTablesXml(xml, tables) -> one slide's XML with the recorded sides of
// its tables (tableSidesOf) written as their dashes draw them. pptxgenjs writes
// an a:tbl's rows in order, each row one a:tc per grid slot (a merge
// placeholder among them), and each cell's sides as a:lnL, a:lnR, a:lnT and
// a:lnB in its a:tcPr; no table holds another, and text in a cell is escaped,
// so none of these tags occurs in it.
function rewrittenTablesXml(xml, tables) {
  let table = 0;
  return xml.replace(/<a:tbl>[\s\S]*?<\/a:tbl>/g, (tbl) => {
    const sides = tables[table++];
    if (!sides || !sides.size) return tbl;
    let row = -1;
    return tbl.replace(/<a:tr\b[\s\S]*?<\/a:tr>/g, (tr) => {
      row += 1;
      let col = -1;
      return tr.replace(/<a:tc\b[\s\S]*?<\/a:tc>/g, (tc) => {
        col += 1;
        const rewritten = sides.get(`${row}:${col}`);
        if (!rewritten) return tc;
        return tc.replace(/<a:(ln[LRTB])\b[\s\S]*?<\/a:\1>/g, (line, name) =>
          (rewritten.has(name) ? rewrittenSide(line, rewritten.get(name)) : line));
      });
    });
  });
}

// The zip library pptxgenjs writes the deck with, resolved as pptxgenjs's own
// require resolves it, so the rewrite reads and writes the deck with the very
// module pptxgenjs loads (it ships in the committed node_modules with
// pptxgenjs; package.json names no zip library of the sidecar's own).
function pptxgenjsZipPath() {
  return require.resolve('jszip', { paths: [path.dirname(require.resolve('pptxgenjs'))] });
}

function sizeOf(px) {
  return Math.max(inches(px), SMALLEST_SIZE_IN);
}

function marginOf(margin) {
  const sides = [margin.top, margin.right, margin.bottom, margin.left];
  if (margin.top >= POINT_MARGINS_FROM_PX) return sides.map((px) => px * PT_PER_PX);
  return sides.map((px) => inches(px));
}

// A cell side's pptxgenjs border. In the deck for Google Slides (`forGoogle`)
// a double side is none: its edge is drawn over the table (pushDoubleEdges).
function borderOf(border, forGoogle) {
  if (!border || (forGoogle && border.dash === 'double')) return { type: 'none' };
  return { type: BORDER_TYPES[border.dash] || 'solid', pt: border.widthPx * PT_PER_PX, color: border.color };
}

// pptxgenjs's custom geometry shape (ShapeType.custGeom).
const CUSTOM_GEOMETRY = 'custGeom';
// A double border's lines are each this share of its width, its outer and
// inner thirds, as a double compound line draws them.
const DOUBLE_LINE_SHARE = 1 / 3;

// The double edges of a table item, each once: {horizontal, at, from, to,
// border}, along the grid line at `at` from `from` to `to` (slide px), in the
// order its cells give them. A cell writes the line of an edge on its side, as
// does the cell across it, so a side its neighbour's gives too is the same edge.
function doubleEdges(item) {
  const columns = [item.x];
  const rows = [item.y];
  for (let index = 0; index < item.colWidths.length; index++) columns.push(columns[index] + item.colWidths[index]);
  for (let index = 0; index < item.rowHeights.length; index++) rows.push(rows[index] + item.rowHeights[index]);
  const edges = new Map();
  for (const cell of item.cells) {
    for (const side of Object.keys(SIDE_ELEMENTS)) {
      const border = cell.borders[side];
      if (!border || border.dash !== 'double') continue;
      const horizontal = side === 'top' || side === 'bottom';
      const at = horizontal
        ? rows[side === 'top' ? cell.row : cell.row + cell.rowspan]
        : columns[side === 'left' ? cell.col : cell.col + cell.colspan];
      const from = horizontal ? columns[cell.col] : rows[cell.row];
      const to = horizontal ? columns[cell.col + cell.colspan] : rows[cell.row + cell.rowspan];
      const key = `${horizontal ? 'h' : 'v'}:${at}:${from}:${to}`;
      if (!edges.has(key)) edges.set(key, { horizontal, at, from, to, border });
    }
  }
  return [...edges.values()];
}

// The double edges of a table in the deck for Google Slides. Drive keeps a
// shape's double compound line but makes a table border's one solid line of
// its whole width (measured, scripts/export_fidelity/CALIBRATION.md T7), and a
// cell border is one a:ln, which holds no second stroke. So each double edge is
// no line on its cells (borderOf) and is drawn over the table as one unfilled
// custom shape stroking the edge's outer and inner thirds, its two lines, each
// a third of the border's width.
function pushDoubleEdges(slide, item) {
  for (const edge of doubleEdges(item)) {
    const widthPx = edge.border.widthPx;
    const line = widthPx * DOUBLE_LINE_SHARE;
    const offset = (widthPx - line) / 2;
    const length = Math.max(edge.to - edge.from, 0);
    const frame = edge.horizontal
      ? { x: edge.from, y: edge.at - offset, w: length, h: 2 * offset }
      : { x: edge.at - offset, y: edge.from, w: 2 * offset, h: length };
    const ends = edge.horizontal
      ? [[{ x: 0, y: 0 }, { x: length, y: 0 }], [{ x: 0, y: 2 * offset }, { x: length, y: 2 * offset }]]
      : [[{ x: 0, y: 0 }, { x: 0, y: length }], [{ x: 2 * offset, y: 0 }, { x: 2 * offset, y: length }]];
    const points = [];
    for (const [start, end] of ends) {
      points.push({ x: inches(start.x), y: inches(start.y), moveTo: true }, { x: inches(end.x), y: inches(end.y) });
    }
    slide.addShape(CUSTOM_GEOMETRY, {
      x: inches(frame.x),
      y: inches(frame.y),
      w: sizeOf(frame.w),
      h: sizeOf(frame.h),
      points,
      line: { color: edge.border.color, width: line * PT_PER_PX, dashType: 'solid' },
    });
  }
}

function fillOf(fill) {
  const options = { color: fill.color };
  const transparency = transparencyOf(fill.alpha);
  if (transparency > 0) options.transparency = transparency;
  return options;
}

// One cell as a pptxgenjs table cell: {text, options}. `faces` and `renderer`
// are emitText's.
function cellObject(cell, faces, renderer) {
  const forGoogle = Boolean(renderer && renderer.target === 'gslides');
  const options = {
    border: [cell.borders.top, cell.borders.right, cell.borders.bottom, cell.borders.left].map((border) => borderOf(border, forGoogle)),
    margin: marginOf(cell.margin),
    valign: cell.valign,
    align: cell.align,
  };
  if (cell.colspan > 1) options.colspan = cell.colspan;
  if (cell.rowspan > 1) options.rowspan = cell.rowspan;
  if (cell.fill) options.fill = fillOf(cell.fill);
  if (cell.font && cell.font.sizePx > 0) {
    const face = runOptions(
      { family: cell.font.family, weight: cell.font.weight, italic: cell.font.italic, sizePx: cell.font.sizePx },
      faces,
      { target: renderer && renderer.target },
    );
    options.fontFace = face.fontFace;
    options.fontSize = face.fontSize;
  }
  const paragraphs = cell.paragraphs || [];
  const text = paragraphs.length ? textObjects({ paragraphs, rtl: cell.rtl }, faces, renderer, { tableCell: true }) : [];
  return { text: text.length ? text : '', options };
}

// emitTable(slide, item, faces, renderer): one table item as one pptxgenjs
// table, and in the deck for Google Slides its double edges over it
// (pushDoubleEdges).
//   faces     the webfonts the page loaded (emit_text.cjs emitText);
//   renderer  the renderer the deck is written for (emit_text.cjs emitText).
function emitTable(slide, item, faces, renderer) {
  const forGoogle = Boolean(renderer && renderer.target === 'gslides');
  const rows = item.rowHeights.map(() => []);
  for (const cell of item.cells) rows[cell.row].push(cell);
  const tableRows = rows.map((cells) => cells
    .slice()
    .sort((a, b) => a.col - b.col)
    .map((cell) => cellObject(cell, faces, renderer)));
  recordRewrittenSides(slide, item, forGoogle);
  const colW = item.colWidths.map(sizeOf);
  const rowH = item.rowHeights.map(sizeOf);
  slide.addTable(tableRows, {
    x: inches(item.x),
    y: inches(item.y),
    w: colW.reduce((total, width) => total + width, 0),
    h: rowH.reduce((total, height) => total + height, 0),
    colW,
    rowH,
    autoPage: false,
  });
  if (forGoogle) pushDoubleEdges(slide, item);
}

module.exports = { emitTable, pptxgenjsZipPath, rewrittenTablesXml, tableSidesOf };
