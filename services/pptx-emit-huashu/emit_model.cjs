'use strict';
// Writes one slide model (snapshot.mjs) to a pptxgenjs slide.
//
// The model is in CSS px on a 1280x720 slide, which is LAYOUT_WIDE at 96 dpi:
// inches = px / 96 and points = px * 0.75 (units.cjs). Every item is written
// in the order the model holds it, which is CSS paint order, so the slide's
// z-order is the screen's.
//
// Only raster data: pictures are embedded (SDR-4437): from a capture or from the
// item's own data: src. Anything else is skipped and announced on stderr. Text
// items are written by emit_text.cjs, which names each run's typeface from the
// webfonts the page loaded (model.fonts, and model.italicFonts for an italic
// run), and native tables by emit_table.cjs. The deck for Google Slides writes
// a dotted line or outline as emit_dotted.cjs draws it, Drive having no 1:1 dot.
//
// A box whose corners round by different radii (geometry 'roundCorners', a card
// header's 16px 16px 0 0) is written as the preset that draws it exactly, when
// one does (cornerPreset: round2SameRect, round2DiagRect, round1Rect), and
// otherwise as a custom path of one quarter arc (arcTo) per rounded corner.
// PowerPoint and Google Slides draw all of them as CSS draws the box, within
// their raster's own rounding, and keep a preset a preset (Drive:
// ROUND_2_SAME_RECTANGLE, ROUND_2_DIAGONAL_RECTANGLE, ROUND_1_RECTANGLE), so it
// resizes with circular corners and keeps its handles (Task 14 B4, D11,
// measured in both apps; scripts/export_fidelity/CALIBRATION.md D11).

const { dottedLine, dottedOutline, strokePoints } = require('./emit_dotted.cjs');
const { emitTable } = require('./emit_table.cjs');
const { emitText } = require('./emit_text.cjs');
const { transparencyOf } = require('./emit_typography.cjs');
const { inches, points } = require('./units.cjs');

const RASTER_DATA_URI = /^data:image\/(png|jpe?g|gif);base64,/i;

// pptxgenjs reads a number of 100 or more as EMU rather than inches, so a
// coordinate that far out (8,320 px off the slide) would land near the origin.
const PPTXGENJS_INCH_LIMIT = 100;

// pptxgenjs replaces a falsy shadow blur, offset or angle with its own default
// (8 pt, 4 pt, 270 degrees), so a true zero is written as the smallest value
// each field can hold: one EMU, and one 60000th of a degree.
const ONE_EMU_IN_PT = 1 / 12700;
const SMALLEST_ANGLE_DEG = 1 / 60000;

const DASH_TYPES = { solid: 'solid', dash: 'dash', dot: 'sysDot' };

function withinInchLimit(...values) {
  return values.every((value) => Math.abs(inches(value)) < PPTXGENJS_INCH_LIMIT);
}

// The picture bytes an image item embeds, or null when it has none to embed.
// Shared by emitSlide and the per-slide summary, so both agree on what was skipped.
function pictureData(item, captures) {
  const data = item.captureId ? (captures && captures.get(item.captureId)) : item.src;
  return typeof data === 'string' && RASTER_DATA_URI.test(data) ? data : null;
}

// The slide's ground: the slide root's image ground, its capture's picture
// (snapshot.mjs groundCapture), when it was taken; a raster image; else its colour.
function applyBackground(slide, background, captures) {
  const ground = background && background.captureId && captures ? captures.get(background.captureId) : null;
  if (typeof ground === 'string' && RASTER_DATA_URI.test(ground)) {
    slide.background = { data: ground };
  } else if (background && typeof background.image === 'string' && RASTER_DATA_URI.test(background.image)) {
    slide.background = { data: background.image };
  } else if (background && background.color) {
    slide.background = { color: background.color };
  }
}

function lineOptions(line) {
  const options = {
    color: line.color,
    width: points(line.widthPx),
    dashType: DASH_TYPES[line.dash] || 'solid',
  };
  const transparency = transparencyOf(line.alpha);
  if (transparency > 0) options.transparency = transparency;
  return options;
}

// A fresh object per shape: pptxgenjs converts the shadow's units in place.
function shadowOptions(shadow) {
  return {
    type: 'outer',
    color: shadow.color,
    opacity: shadow.alpha,
    blur: Math.max(points(shadow.blurPx), ONE_EMU_IN_PT),
    offset: Math.max(points(shadow.offsetPx), ONE_EMU_IN_PT),
    angle: shadow.angle > 0 ? shadow.angle : SMALLEST_ANGLE_DEG,
  };
}

// Two corner radii within this of each other, or of half a side, are one (layout rounding).
const RADIUS_EPSILON_PX = 0.01;
// A preset's adjustment is a length over the shape's short side, times this.
const ADJUST_SCALE = 100000;
// pptxgenjs writes options.angleRange[i] as the preset's adjustment adj(i + 1),
// times this and rounded (pptxgen.cjs.js:5459), its one way to write a
// preset's two adjustments: an adjustment a is passed as a / this.
const PPTXGENJS_ANGLE_UNITS = 60000;

// A roundCorners item's corners, top left first, each its radii {h, v}: a
// corner either radius of which is 0 is square, {0, 0}, as CSS draws it (and
// as the snapshot writes it, cornerGeometry).
function squaredCorners(item) {
  return item.radii.map((corner) => (corner.h > 0 && corner.v > 0 ? corner : { h: 0, v: 0 }));
}

// The preset that draws a roundCorners item exactly, {name, radii: px[]}, its
// adjustments' radii in its own order, or null. A preset rounds its corners by
// circles, each adjustment a radius over the shape's short side pinned at half
// of it (the presets' definitions, measured in both apps):
//   round2SameRect  adj1 the top corners, adj2 the bottom ones;
//   round2DiagRect  adj1 the top left and bottom right, adj2 the top right and
//                   bottom left;
//   round1Rect      adj the top right, the others square.
// So a box is one when each corner is a circle, they pair as the preset's do,
// and each radius is at most half its short side.
function cornerPreset(item) {
  const [topLeft, topRight, bottomRight, bottomLeft] = squaredCorners(item);
  const near = (a, b) => Math.abs(a - b) <= RADIUS_EPSILON_PX;
  if (![topLeft, topRight, bottomRight, bottomLeft].every((corner) => near(corner.h, corner.v))) return null;
  const half = Math.min(item.w, item.h) / 2;
  const fits = (...corners) => corners.every((corner) => corner.h <= half + RADIUS_EPSILON_PX);
  const radius = (corner) => Math.min(corner.h, half);
  if (near(topLeft.h, topRight.h) && near(bottomLeft.h, bottomRight.h) && fits(topLeft, bottomRight)) {
    return { name: 'round2SameRect', radii: [radius(topLeft), radius(bottomRight)] };
  }
  if (near(topLeft.h, bottomRight.h) && near(topRight.h, bottomLeft.h) && fits(topLeft, topRight)) {
    return { name: 'round2DiagRect', radii: [radius(topLeft), radius(topRight)] };
  }
  if (!topLeft.h && !bottomRight.h && !bottomLeft.h && fits(topRight)) {
    return { name: 'round1Rect', radii: [radius(topRight)] };
  }
  return null;
}

// A roundCorners item's outline as pptxgenjs custom-geometry points, in inches
// from its top left, clockwise from its top edge: a line along each side, and
// a quarter arc of each rounded corner's own radii (arcTo, angles clockwise
// from 3 o'clock); a square corner is the corner itself.
function cornerPathPoints(item) {
  const [topLeft, topRight, bottomRight, bottomLeft] = squaredCorners(item);
  const { w, h } = item;
  const points = [{ x: inches(topLeft.h), y: 0, moveTo: true }, { x: inches(w - topRight.h), y: 0 }];
  const arc = (corner, startAngle) => {
    if (corner.h > 0 && corner.v > 0) {
      points.push({ x: 0, y: 0, curve: { type: 'arc', wR: inches(corner.h), hR: inches(corner.v), stAng: startAngle, swAng: 90 } });
    }
  };
  arc(topRight, 270);
  points.push({ x: inches(w), y: inches(h - bottomRight.v) });
  arc(bottomRight, 0);
  points.push({ x: inches(bottomLeft.h), y: inches(h) });
  arc(bottomLeft, 90);
  points.push({ x: 0, y: inches(topLeft.v) });
  arc(topLeft, 180);
  points.push({ close: true });
  return points;
}

// The pptxgenjs shape type and geometry options of a shape item.
function shapeGeometry(pres, item) {
  if (item.geometry === 'path') return { shapeType: pres.ShapeType.custGeom, options: { points: pathPoints(item) } };
  // rectRadius is in inches; pptxgenjs turns it into the preset's adj over the short side.
  if (item.geometry === 'roundRect') return { shapeType: pres.ShapeType.roundRect, options: { rectRadius: inches(item.radius) } };
  if (item.geometry === 'roundCorners') {
    const preset = cornerPreset(item);
    if (!preset) return { shapeType: pres.ShapeType.custGeom, options: { points: cornerPathPoints(item) } };
    const shapeType = pres.ShapeType[preset.name];
    // One adjustment is rectRadius, as a roundRect's; two go through angleRange.
    if (preset.radii.length === 1) return { shapeType, options: { rectRadius: inches(preset.radii[0]) } };
    const shortSide = Math.min(item.w, item.h);
    const adjust = (radius) => Math.round((radius / shortSide) * ADJUST_SCALE) / PPTXGENJS_ANGLE_UNITS;
    return { shapeType, options: { angleRange: preset.radii.map(adjust) } };
  }
  const shapeType = pres.ShapeType[item.geometry];
  if (!shapeType) throw new Error(`[html2pptx] unknown shape geometry: ${item.geometry}`);
  return { shapeType, options: {} };
}

// A path item's polylines as pptxgenjs custom-geometry points, in inches from
// the shape's top left: each polyline starts with a move, and a closed one ends
// with a close.
function pathPoints(item) {
  const points = [];
  for (const polyline of item.path) {
    polyline.forEach((point, index) => {
      points.push({ x: inches(point.x), y: inches(point.y), moveTo: index === 0 });
    });
    if (item.closed) points.push({ close: true });
  }
  return points;
}

// Whether the deck is written for Google Slides and the stroke is dotted, which
// emit_dotted.cjs draws there.
function dottedForGoogle(stroke, renderer) {
  return Boolean(stroke) && stroke.dash === 'dot' && Boolean(renderer) && renderer.target === 'gslides';
}

// A dotted stroke for Google Slides: one unfilled custom shape over its frame,
// turned by `rotate` (emit_dotted.cjs).
function emitDottedStroke(slide, pres, stroke, outline, rotate) {
  const options = {
    x: inches(outline.frame.x),
    y: inches(outline.frame.y),
    w: inches(outline.frame.w),
    h: inches(outline.frame.h),
    points: strokePoints(outline.polylines, outline.closed, stroke.widthPx),
    line: lineOptions(stroke),
  };
  if (rotate) options.rotate = rotate;
  slide.addShape(pres.ShapeType.custGeom, options);
}

// `renderer` is emitSlide's. In the deck for Google Slides a dotted outline is
// a stroke of its own over the shape (emitDottedStroke): a path that only
// strokes is that stroke; any other shape is drawn without its outline first.
function emitShape(slide, pres, item, renderer) {
  if (dottedForGoogle(item.line, renderer)) {
    if (item.fill || item.shadow) emitShape(slide, pres, { ...item, line: null }, renderer);
    emitDottedStroke(slide, pres, item.line, dottedOutline(item), item.rotate);
    return;
  }
  const geometry = shapeGeometry(pres, item);
  const options = {
    x: inches(item.x),
    y: inches(item.y),
    w: inches(item.w),
    h: inches(item.h),
    line: item.line ? lineOptions(item.line) : { type: 'none' },
  };
  if (geometry.options.points) options.points = geometry.options.points;
  if (item.fill) {
    options.fill = { color: item.fill.color };
    const transparency = transparencyOf(item.fill.alpha);
    if (transparency > 0) options.fill.transparency = transparency;
  }
  if (geometry.options.rectRadius !== undefined) options.rectRadius = geometry.options.rectRadius;
  if (geometry.options.angleRange) options.angleRange = geometry.options.angleRange;
  if (item.shadow) options.shadow = shadowOptions(item.shadow);
  if (item.rotate) options.rotate = item.rotate;
  slide.addShape(geometry.shapeType, options);
}

// A line runs left to right; one that rises is the same box flipped vertically.
// In the deck for Google Slides a dotted one is a stroke (emitDottedStroke).
function emitLine(slide, pres, item, renderer) {
  if (dottedForGoogle(item, renderer)) {
    emitDottedStroke(slide, pres, item, dottedLine(item), null);
    return;
  }
  const leftToRight = item.x1 <= item.x2;
  const start = leftToRight ? { x: item.x1, y: item.y1 } : { x: item.x2, y: item.y2 };
  const end = leftToRight ? { x: item.x2, y: item.y2 } : { x: item.x1, y: item.y1 };
  const options = {
    x: inches(start.x),
    y: inches(Math.min(start.y, end.y)),
    w: inches(end.x - start.x),
    h: inches(Math.abs(end.y - start.y)),
    line: lineOptions(item),
  };
  if (end.y < start.y) options.flipV = true;
  slide.addShape(pres.ShapeType.line, options);
}

function emitImage(slide, item, data) {
  const options = { data, x: inches(item.x), y: inches(item.y), w: inches(item.w), h: inches(item.h) };
  if (item.rotate) options.rotate = item.rotate;
  const transparency = transparencyOf(typeof item.alpha === 'number' ? item.alpha : 1);
  if (transparency > 0) options.transparency = transparency;
  slide.addImage(options);
}

function sum(values) {
  let total = 0;
  for (const value of values) total += value;
  return total;
}

function inRange(item) {
  if (item.kind === 'line') return withinInchLimit(item.x1, item.y1, item.x2, item.y2);
  if (item.kind === 'table') return withinInchLimit(item.x, item.y, sum(item.colWidths), sum(item.rowHeights));
  return withinInchLimit(item.x, item.y, item.w, item.h);
}

// emitSlide(pres, model, captures, renderer) -> slide
//   captures: Map<captureId, 'data:image/png;base64,…'>
//   renderer: {target: 'pptx' | 'gslides'}, the renderer the deck is written
//             for (emit_text.cjs emitText); 'pptx' when absent.
function emitSlide(pres, model, captures, renderer) {
  const slide = pres.addSlide();
  // The webfonts the page loaded, all faces and the italic ones, which name a run's face.
  const faces = { weights: model.fonts, italicWeights: model.italicFonts };
  applyBackground(slide, model.background, captures);
  let skippedPictures = 0;
  let outOfRange = 0;
  for (const item of model.items) {
    if (!inRange(item)) {
      outOfRange += 1;
      continue;
    }
    if (item.kind === 'shape') {
      emitShape(slide, pres, item, renderer);
    } else if (item.kind === 'line') {
      if (item.x1 !== item.x2 || item.y1 !== item.y2) emitLine(slide, pres, item, renderer);
    } else if (item.kind === 'image') {
      const data = pictureData(item, captures);
      if (data) emitImage(slide, item, data);
      else skippedPictures += 1;
    } else if (item.kind === 'text') {
      emitText(slide, item, faces, renderer);
    } else if (item.kind === 'table') {
      emitTable(slide, item, faces, renderer);
    } else {
      throw new Error(`[html2pptx] the slide model holds an item kind the emitter does not know: ${item.kind}`);
    }
  }
  if (skippedPictures) {
    console.error(`[html2pptx] skipped ${skippedPictures} picture(s) with no embeddable data: (not a raster data: source and not captured)`);
  }
  if (outOfRange) {
    console.error(`[html2pptx] skipped ${outOfRange} item(s) more than ${PPTXGENJS_INCH_LIMIT} inches from the slide origin`);
  }
  return slide;
}

module.exports = { emitSlide, pictureData, RASTER_DATA_URI };
