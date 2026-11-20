'use strict';
// The emitter's units. The slide model is in CSS px on a 1280x720 slide, which
// is pptxgenjs's LAYOUT_WIDE (13.333 x 7.5 in) at 96 px to the inch: an inch
// is 96 px, a px is 0.75 pt, and an inch is 914400 EMU. pptxgenjs reads
// positions and sizes in inches, and font sizes, line widths, spacing and
// most margins in points.

const PX_PER_IN = 96;
const PT_PER_PX = 0.75;
const EMU_PER_IN = 914400;

function inches(px) {
  return px / PX_PER_IN;
}

function points(px) {
  return px * PT_PER_PX;
}

module.exports = { PX_PER_IN, PT_PER_PX, EMU_PER_IN, inches, points };
