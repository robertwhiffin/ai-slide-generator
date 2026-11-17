'use strict';
// Writes one slide model (snapshot.mjs) to a pptxgenjs slide.
//
// The model is in CSS px on a 1280x720 slide, which is LAYOUT_WIDE at 96 dpi:
// inches = px / 96 and points = px * 0.75. Every item is written in the order
// the model holds it, which is CSS paint order, so the slide's z-order is the
// screen's.
//
// Only raster data: pictures are embedded (SDR-4437): from a capture or from the
// item's own data: src. Anything else is skipped and announced on stderr. Text
// items are written by emit_text.cjs.

const { emitText } = require('./emit_text.cjs');

const PX_PER_IN = 96;
const PT_PER_PX = 0.75;
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

function inches(px) {
  return px / PX_PER_IN;
}

function points(px) {
  return px * PT_PER_PX;
}

// pptxgenjs transparency is a whole percentage; 0 means opaque and writes no alpha.
function transparencyOf(alpha) {
  return Math.round((1 - alpha) * 100);
}

function withinInchLimit(...values) {
  return values.every((value) => Math.abs(inches(value)) < PPTXGENJS_INCH_LIMIT);
}

// The picture bytes an image item embeds, or null when it has none to embed.
// Shared by emitSlide and the per-slide summary, so both agree on what was skipped.
function pictureData(item, captures) {
  const data = item.captureId ? (captures && captures.get(item.captureId)) : item.src;
  return typeof data === 'string' && RASTER_DATA_URI.test(data) ? data : null;
}

function applyBackground(slide, background) {
  if (background && typeof background.image === 'string' && RASTER_DATA_URI.test(background.image)) {
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

function emitShape(slide, pres, item) {
  const shapeType = pres.ShapeType[item.geometry];
  if (!shapeType) throw new Error(`[html2pptx] unknown shape geometry: ${item.geometry}`);
  const options = {
    x: inches(item.x),
    y: inches(item.y),
    w: inches(item.w),
    h: inches(item.h),
    line: item.line ? lineOptions(item.line) : { type: 'none' },
  };
  if (item.fill) {
    options.fill = { color: item.fill.color };
    const transparency = transparencyOf(item.fill.alpha);
    if (transparency > 0) options.fill.transparency = transparency;
  }
  // rectRadius is in inches; pptxgenjs turns it into the preset's adj over the short side.
  if (item.geometry === 'roundRect') options.rectRadius = inches(item.radius);
  if (item.shadow) options.shadow = shadowOptions(item.shadow);
  if (item.rotate) options.rotate = item.rotate;
  slide.addShape(shapeType, options);
}

// A line runs left to right; one that rises is the same box flipped vertically.
function emitLine(slide, pres, item) {
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

function inRange(item) {
  if (item.kind === 'line') return withinInchLimit(item.x1, item.y1, item.x2, item.y2);
  return withinInchLimit(item.x, item.y, item.w, item.h);
}

// emitSlide(pres, model, captures) -> slide
//   captures: Map<captureId, 'data:image/png;base64,…'>
function emitSlide(pres, model, captures) {
  const slide = pres.addSlide();
  applyBackground(slide, model.background);
  let skippedPictures = 0;
  let outOfRange = 0;
  for (const item of model.items) {
    if (!inRange(item)) {
      outOfRange += 1;
      continue;
    }
    if (item.kind === 'shape') {
      emitShape(slide, pres, item);
    } else if (item.kind === 'line') {
      if (item.x1 !== item.x2 || item.y1 !== item.y2) emitLine(slide, pres, item);
    } else if (item.kind === 'image') {
      const data = pictureData(item, captures);
      if (data) emitImage(slide, item, data);
      else skippedPictures += 1;
    } else if (item.kind === 'text') {
      emitText(slide, item);
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

module.exports = { emitSlide, pictureData };
