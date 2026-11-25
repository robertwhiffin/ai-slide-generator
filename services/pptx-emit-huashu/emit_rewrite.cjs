'use strict';
// What the deck is given once pptxgenjs has written it, where pptxgenjs writes
// no such thing itself (emit_deck.mjs runs rewriteDeck on the written deck):
// * a native table's dotted sides, written sysDot, and, in the deck for
//   PowerPoint, its double sides, written a double compound line
//   (emit_table.cjs rewrittenTablesXml, from the sides emitTable recorded);
// * a shape's double outline or a double line, a double compound line
//   (a:ln cmpd="dbl"): pptxgenjs writes no compound, so emit_model.cjs writes
//   such a stroke solid and names its shape (doubleBorderName);
// * a shape's inner shadow (a:innerShdw): pptxgenjs writes one closed as an
//   a:outerShdw, which no app reads, so emit_model.cjs writes such a shape
//   with no shadow, names it and gives the shadow here (innerShadowName).
// A shape is found by its name, its p:cNvPr name, which pptxgenjs writes from
// the name given, and gives every other shape and text box as "Shape N" and
// "Text N"; the names given are these prefixes and a number per slide. A deck
// with nothing to rewrite is returned as pptxgenjs wrote it.

const { pptxgenjsZipPath, rewrittenTablesXml, tableSidesOf } = require('./emit_table.cjs');
const { PT_PER_PX } = require('./units.cjs');

// What a shape with a double border, and one with an inner shadow, is named:
// this and its number on its slide.
const DOUBLE_BORDER_NAME = 'Double border';
const INNER_SHADOW_NAME = 'Inner shadow';
const DOUBLE_COMPOUND = 'cmpd="dbl"';
// A shape's a:ln as pptxgenjs writes it, with its width or with none.
const SHAPE_LINE = /<a:ln( w="\d+")?>/;
// DrawingML units: EMU per point, 60000ths of a degree, 1000ths of a percent.
const EMU_PER_PT = 12700;
const ANGLE_UNITS = 60000;
const ALPHA_UNITS = 100000;

// pptxgenjs slide -> its named shapes: {doubles: how many double borders,
// shadows: the a:effectLst of each inner shadow, by its shape's name}. Keyed
// weakly, per slide object.
const namedShapes = new WeakMap();

function namedOn(slide) {
  if (!namedShapes.has(slide)) namedShapes.set(slide, { doubles: 0, shadows: [] });
  return namedShapes.get(slide);
}

// doubleBorderName(slide) -> the name of the next shape with a double border
// on `slide`, whose a:ln rewriteDeck makes double.
function doubleBorderName(slide) {
  const named = namedOn(slide);
  named.doubles += 1;
  return `${DOUBLE_BORDER_NAME} ${named.doubles}`;
}

// innerShadowName(slide, shadow) -> the name of the next shape with an inner
// shadow on `slide`, to which rewriteDeck gives `shadow` ({color, alpha,
// blurPx, offsetPx, angle}, as emit_model.cjs reads a shadow) as an
// a:innerShdw: blur and distance in EMU, direction in 60000ths of a degree.
function innerShadowName(slide, shadow) {
  const named = namedOn(slide);
  const name = `${INNER_SHADOW_NAME} ${named.shadows.length + 1}`;
  const emu = (px) => Math.max(0, Math.round(px * PT_PER_PX * EMU_PER_PT));
  const effect = `<a:effectLst><a:innerShdw blurRad="${emu(shadow.blurPx)}" dist="${emu(shadow.offsetPx)}"` +
    ` dir="${Math.round(shadow.angle * ANGLE_UNITS)}"><a:srgbClr val="${shadow.color}">` +
    `<a:alpha val="${Math.round(shadow.alpha * ALPHA_UNITS)}"/></a:srgbClr></a:innerShdw></a:effectLst>`;
  named.shadows.push({ name, effect });
  return name;
}

// The shape named `name` in a p:sp's XML, matched on its p:cNvPr name whole.
function namedShape(shape, name) {
  return shape.indexOf(`name="${name}"`) >= 0 && new RegExp(`<p:cNvPr [^>]*name="${name}"`).test(shape);
}

// One slide's XML with its named shapes rewritten: each double border's a:ln
// made double, each inner shadow's a:effectLst written at the end of its
// shape's p:spPr, where an effect list follows the outline.
function rewrittenShapesXml(xml, named) {
  if (!named || (!named.doubles && !named.shadows.length)) return xml;
  return xml.replace(/<p:sp>[\s\S]*?<\/p:sp>/g, (shape) => {
    if (new RegExp(`<p:cNvPr [^>]*name="${DOUBLE_BORDER_NAME} \\d+"`).test(shape)) {
      return shape.replace(SHAPE_LINE, (line) => line.replace(/>$/, ` ${DOUBLE_COMPOUND}>`));
    }
    for (const { name, effect } of named.shadows) {
      if (namedShape(shape, name)) return shape.replace('</p:spPr>', `${effect}</p:spPr>`);
    }
    return shape;
  });
}

// rewriteDeck(deck, slides) -> the deck pptxgenjs wrote (a .pptx Buffer), each
// slide of `slides` (pres.slides, in order) with what it was recorded to need:
// its tables' dotted and double sides (emit_table.cjs) and its named shapes.
// The parts are rewritten with the zip library pptxgenjs writes with
// (emit_table.cjs pptxgenjsZipPath), as it writes them: in order, stored, each
// part's date kept. It throws when the deck cannot be read or written back,
// and emit_deck.mjs then writes the deck as pptxgenjs wrote it.
async function rewriteDeck(deck, slides) {
  const pending = [];
  slides.forEach((slide, index) => {
    const tables = tableSidesOf(slide);
    const named = namedShapes.get(slide) || null;
    if (tables.some((sides) => sides.size) || named) pending.push({ name: `ppt/slides/slide${index + 1}.xml`, tables, named });
  });
  if (!pending.length) return deck;
  const JSZip = require(pptxgenjsZipPath());
  const zip = await JSZip.loadAsync(deck);
  for (const { name, tables, named } of pending) {
    const part = zip.file(name);
    if (!part) continue;
    const xml = rewrittenShapesXml(rewrittenTablesXml(await part.async('string'), tables), named);
    zip.file(name, xml, { date: part.date });
  }
  return zip.generateAsync({ type: 'nodebuffer', compression: 'STORE' });
}

module.exports = { DOUBLE_BORDER_NAME, INNER_SHADOW_NAME, doubleBorderName, innerShadowName, rewriteDeck };
