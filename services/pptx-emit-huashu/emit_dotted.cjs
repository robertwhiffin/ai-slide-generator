'use strict';
// Dotted strokes in the deck for Google Slides.
//
// CSS paints a dotted border as dots one border width long, one width apart.
// PowerPoint draws prstDash sysDot so, and the deck for PowerPoint writes it.
// Drive converts both sysDot and dot to its DOT dash, which draws a dot one
// line width long every four widths ([w 3w], measured in its PDF and its
// thumbnails at 1, 2 and 4 px), and every custDash to DASH_DOT: no dash Drive
// offers is a 1:1 dot. So the deck for Google Slides writes a dotted stroke as
// one unfilled custom shape that draws its centre line twice, as two
// subpaths, the second starting two widths further along: Drive keeps both and
// starts the dash afresh on each, so the second pass's dots fall in the
// first's gaps, one width on and one off (measured 1:1 at 1, 2 and 3 px; the
// PowerPoint deck draws the same shape as one sysDot stroke, the passes on the
// same dots). It stays one shape, which moves and recolours whole; it is a
// freeform rather than a preset.
//
//   dottedLine(item)    -> {frame, polylines, closed} for a line item;
//   dottedOutline(item) -> the same for a shape item's outline, in its frame;
//   strokePoints(polylines, closed, widthPx) -> pptxgenjs custom-geometry
//     points, each polyline drawn twice, the second pass a pitch along.
// A frame is {x, y, w, h} in slide px; polylines are points in px from its top
// left.

const { inches } = require('./units.cjs');

// The second pass starts this many line widths along the first.
const DOT_PITCH_WIDTHS = 2;
// A frame keeps at least this extent, so a straight stroke still has a path
// space to draw in (as snapshot.mjs pushPath's paths do).
const FRAME_MIN_EXTENT_PX = 0.01;
// Arcs become polygons that stray from them by at most this.
const ARC_TOLERANCE_PX = 0.05;
const ARC_STEP_LIMIT = 64;

function arcSteps(radius) {
  if (!(radius > ARC_TOLERANCE_PX)) return 1;
  const step = 2 * Math.acos(1 - ARC_TOLERANCE_PX / radius);
  return Math.max(2, Math.min(ARC_STEP_LIMIT, Math.ceil(Math.PI / 2 / step)));
}

// A line item's centre line, run from its second point back to its first.
// A side line runs left to right or top to bottom (snapshot.mjs pushSideLines),
// and Chrome lays a dotted side's dots back from its right or bottom end: its
// last dot ends there, one width on and one off, and what the length leaves
// over is a narrower gap after its first dot (measured at 1, 2 and 3 px on
// sides of 97 to 549 px, all four sides). A dash runs from its path's start,
// so the passes start at that end, and the dots fall where Chrome's do.
function dottedLine(item) {
  const left = Math.min(item.x1, item.x2);
  const top = Math.min(item.y1, item.y2);
  const frame = {
    x: left,
    y: top,
    w: Math.max(Math.abs(item.x2 - item.x1), FRAME_MIN_EXTENT_PX),
    h: Math.max(Math.abs(item.y2 - item.y1), FRAME_MIN_EXTENT_PX),
  };
  return { frame, polylines: [[{ x: item.x2 - left, y: item.y2 - top }, { x: item.x1 - left, y: item.y1 - top }]], closed: false };
}

// A shape item's outline in its own frame (its box, turned with it by its
// rotation): a path's own polylines; else the rect, rounded rect or ellipse,
// clockwise from its top left (its left, for an ellipse).
function dottedOutline(item) {
  const frame = { x: item.x, y: item.y, w: item.w, h: item.h };
  if (item.geometry === 'path') return { frame, polylines: item.path, closed: item.closed };
  const points = [];
  const arc = (centreX, centreY, radiusX, radiusY, start) => {
    const steps = arcSteps(Math.max(radiusX, radiusY));
    for (let step = 0; step <= steps; step++) {
      const angle = start + (Math.PI / 2) * (step / steps);
      points.push({ x: centreX + radiusX * Math.cos(angle), y: centreY + radiusY * Math.sin(angle) });
    }
  };
  const { w, h } = item;
  if (item.geometry === 'ellipse') {
    for (let quarter = 0; quarter < 4; quarter++) arc(w / 2, h / 2, w / 2, h / 2, Math.PI * (1 + quarter / 2));
  } else if (item.geometry === 'roundRect' && Math.min(item.radius, w / 2, h / 2) > 0) {
    const radius = Math.min(item.radius, w / 2, h / 2);
    arc(radius, radius, radius, radius, Math.PI);
    arc(w - radius, radius, radius, radius, Math.PI * 1.5);
    arc(w - radius, h - radius, radius, radius, 0);
    arc(radius, h - radius, radius, radius, Math.PI * 0.5);
  } else {
    points.push({ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h });
  }
  return { frame, polylines: [points], closed: true };
}

// `polyline` from `distance` along it to its end, or, closed, round to where it
// starts: the same course, begun later. Null for an open one no longer than that.
function begunLater(polyline, closed, distance) {
  const course = closed ? polyline.concat([polyline[0]]) : polyline;
  let left = distance;
  for (let index = 0; index + 1 < course.length; index++) {
    const from = course[index];
    const to = course[index + 1];
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    if (length > left) {
      const share = left / length;
      const start = { x: from.x + (to.x - from.x) * share, y: from.y + (to.y - from.y) * share };
      if (!closed) return [start].concat(polyline.slice(index + 1));
      // Round the rest of the course and back along the first part to the start.
      return [start].concat(polyline.slice(index + 1), polyline.slice(0, index + 1));
    }
    left -= length;
  }
  return null;
}

function strokePoints(polylines, closed, widthPx) {
  const pitch = DOT_PITCH_WIDTHS * widthPx;
  const passes = [];
  for (const polyline of polylines) {
    if (polyline.length < 2) continue;
    passes.push(polyline);
    const later = begunLater(polyline, closed, pitch);
    if (later) passes.push(later);
  }
  const points = [];
  for (const pass of passes) {
    pass.forEach((point, index) => points.push({ x: inches(point.x), y: inches(point.y), moveTo: index === 0 }));
    if (closed) points.push({ close: true });
  }
  return points;
}

module.exports = { DOT_PITCH_WIDTHS, dottedLine, dottedOutline, strokePoints };
