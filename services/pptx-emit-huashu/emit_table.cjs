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
//   deck is written (dotTableBorders): PowerPoint draws sysDot one width on
//   and one off, as CSS paints a dotted border, and Drive converts it to its
//   DOT, one on and three off, the nearest dash a Google table border has
//   (scripts/export_fidelity/CALIBRATION.md D10). A cell border is one a:ln,
//   which holds no second stroke, so the deck for Google Slides cannot draw
//   it twice as it does a dotted line (emit_dotted.cjs);
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
// and written sysDot (dotTableBorders).
const BORDER_TYPES = { solid: 'solid', dash: 'dash', dot: 'dash' };
// The a:tcPr border element of each side, and the dashes pptxgenjs and a
// dotted side write.
const SIDE_ELEMENTS = { top: 'lnT', right: 'lnR', bottom: 'lnB', left: 'lnL' };
const PPTXGENJS_DASH = '<a:prstDash val="sysDash"/>';
const DOTTED_DASH = '<a:prstDash val="sysDot"/>';

// pptxgenjs slide -> the dotted sides of each table emitted on it, in the
// order emitted, which is the order of its a:tbl elements in the slide's XML:
// Map<'row:col', Set<'lnT' | 'lnR' | 'lnB' | 'lnL'>> per table, one per table
// so the n-th belongs to the n-th a:tbl. Keyed weakly, per slide object.
const dottedSides = new WeakMap();

function recordDottedSides(slide, item) {
  const sides = new Map();
  for (const cell of item.cells) {
    for (const side of Object.keys(SIDE_ELEMENTS)) {
      const border = cell.borders[side];
      if (!border || border.dash !== 'dot') continue;
      const key = `${cell.row}:${cell.col}`;
      if (!sides.has(key)) sides.set(key, new Set());
      sides.get(key).add(SIDE_ELEMENTS[side]);
    }
  }
  if (!dottedSides.has(slide)) dottedSides.set(slide, []);
  dottedSides.get(slide).push(sides);
}

// One slide's XML with the dotted sides of its tables (recordDottedSides)
// written sysDot. pptxgenjs writes an a:tbl's rows in order, each row one
// a:tc per grid slot (a merge placeholder among them), and each cell's sides
// as a:lnL, a:lnR, a:lnT and a:lnB in its a:tcPr; no table holds another,
// and text in a cell is escaped, so none of these tags occurs in it.
function dottedSlideXml(xml, tables) {
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
        const dotted = sides.get(`${row}:${col}`);
        if (!dotted) return tc;
        return tc.replace(/<a:(ln[LRTB])\b[\s\S]*?<\/a:\1>/g, (line, name) =>
          (dotted.has(name) ? line.replace(PPTXGENJS_DASH, DOTTED_DASH) : line));
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

// The deck pptxgenjs wrote (a .pptx Buffer), each dotted side of each table
// on `slides` (pres.slides, in order) written sysDot. A deck with none is
// returned as it is. The parts are rewritten with the zip library pptxgenjs
// writes with (pptxgenjsZipPath), as it writes them: in order, stored, each
// part's date kept. It throws when the deck cannot be read or written back,
// and emit_deck.mjs then writes the deck as pptxgenjs wrote it.
async function dotTableBorders(deck, slides) {
  const pending = [];
  slides.forEach((slide, index) => {
    const tables = dottedSides.get(slide);
    if (tables && tables.some((sides) => sides.size)) pending.push({ name: `ppt/slides/slide${index + 1}.xml`, tables });
  });
  if (!pending.length) return deck;
  const JSZip = require(pptxgenjsZipPath());
  const zip = await JSZip.loadAsync(deck);
  for (const { name, tables } of pending) {
    const part = zip.file(name);
    if (!part) continue;
    zip.file(name, dottedSlideXml(await part.async('string'), tables), { date: part.date });
  }
  return zip.generateAsync({ type: 'nodebuffer', compression: 'STORE' });
}

function sizeOf(px) {
  return Math.max(inches(px), SMALLEST_SIZE_IN);
}

function marginOf(margin) {
  const sides = [margin.top, margin.right, margin.bottom, margin.left];
  if (margin.top >= POINT_MARGINS_FROM_PX) return sides.map((px) => px * PT_PER_PX);
  return sides.map((px) => inches(px));
}

function borderOf(border) {
  if (!border) return { type: 'none' };
  return { type: BORDER_TYPES[border.dash] || 'solid', pt: border.widthPx * PT_PER_PX, color: border.color };
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
  const options = {
    border: [borderOf(cell.borders.top), borderOf(cell.borders.right), borderOf(cell.borders.bottom), borderOf(cell.borders.left)],
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

// emitTable(slide, item, faces, renderer): one table item as one pptxgenjs table.
//   faces     the webfonts the page loaded (emit_text.cjs emitText);
//   renderer  the renderer the deck is written for (emit_text.cjs emitText).
function emitTable(slide, item, faces, renderer) {
  const rows = item.rowHeights.map(() => []);
  for (const cell of item.cells) rows[cell.row].push(cell);
  const tableRows = rows.map((cells) => cells
    .slice()
    .sort((a, b) => a.col - b.col)
    .map((cell) => cellObject(cell, faces, renderer)));
  recordDottedSides(slide, item);
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
}

module.exports = { emitTable, dotTableBorders, pptxgenjsZipPath };
