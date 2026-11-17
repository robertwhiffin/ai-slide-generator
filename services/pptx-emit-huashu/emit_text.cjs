'use strict';
// Writes one text item of the slide model (snapshot_text.mjs) as a pptxgenjs
// text box.
//
// pptxgenjs copies a shape-level option onto every run whose own value is
// falsy (bold: false, charSpacing: 0), so all styling lives on the runs
// (emit_typography.cjs runOptions) and the shape carries geometry only (Global
// Constraints), plus the paragraph alignment: a keyword that is never falsy,
// which pptxgenjs reads from the shape before it writes each paragraph.
//
// Right-to-left is a paragraph property, but pptxgenjs 3.12 writes a
// paragraph's rtl from its runs' own options, before it copies the shape's
// options onto them, so rtlMode goes on every run of a right-to-left block.
//
// The text array holds one object per run. Line breaks are the browser's:
// * a line after the first in its paragraph starts with softBreakBefore, which
//   pptxgenjs writes as <a:br/> inside the paragraph (only for a run that is not
//   first in its paragraph, which a later line's first run never is);
// * the last run of every paragraph but the final one carries breakLine, which
//   ends the paragraph;
// * a blank line (two <br>s, an empty pre line) is a NBSP run in the style of
//   the run before it. A bare <a:br/> carries no run properties, so PowerPoint
//   would size the blank line at its 18 pt default and push every later line
//   down. The NBSP takes the run's face and size but none of what it paints on
//   its glyphs: an underline or strike-through on an empty line is a mark the
//   browser never drew, and a baseline shift is not the line's own.

const { runOptions, xmlText } = require('./emit_typography.cjs');

const PX_PER_IN = 96;
const NBSP = '\u00a0';

function inches(px) {
  return px / PX_PER_IN;
}

// A run's options in this item: its style, and the item's direction.
function itemRunOptions(run, item, fonts) {
  const options = runOptions(run, fonts);
  if (item.rtl) options.rtlMode = true;
  return options;
}

// A blank line's NBSP run: the previous run's options without its glyph marks.
function blankLineOptions(run, item, fonts) {
  const options = itemRunOptions(run, item, fonts);
  options.underline = undefined;
  options.strike = undefined;
  options.superscript = false;
  options.subscript = false;
  return options;
}

function textObjects(item, fonts) {
  const objects = [];
  const paragraphs = item.paragraphs || [];
  // The last run written, whose style a following blank line takes.
  let previousRun = null;
  for (let paragraphIndex = 0; paragraphIndex < paragraphs.length; paragraphIndex++) {
    const lines = paragraphs[paragraphIndex].lines || [];
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      const runs = lines[lineIndex].runs || [];
      if (!runs.length) {
        // A blank line never opens its paragraph, so a run precedes it.
        const options = previousRun ? blankLineOptions(previousRun, item, fonts) : {};
        options.softBreakBefore = lineIndex > 0;
        objects.push({ text: NBSP, options });
        continue;
      }
      for (let runIndex = 0; runIndex < runs.length; runIndex++) {
        const options = itemRunOptions(runs[runIndex], item, fonts);
        if (lineIndex > 0 && runIndex === 0) options.softBreakBefore = true;
        objects.push({ text: xmlText(runs[runIndex].text), options });
        previousRun = runs[runIndex];
      }
    }
    if (paragraphIndex < paragraphs.length - 1 && objects.length) {
      objects[objects.length - 1].options.breakLine = true;
    }
  }
  return objects;
}

// emitText(slide, item, fonts): one text item as one text box.
//   fonts  model.fonts, the webfont weights the page loaded per family.
function emitText(slide, item, fonts) {
  const objects = textObjects(item, fonts);
  if (!objects.length) return;
  const options = {
    x: inches(item.x),
    y: inches(item.y),
    w: inches(item.w),
    h: inches(item.h),
    wrap: item.wrap,
    valign: 'top',
    margin: 0,
    inset: 0,
    fit: 'none',
    align: item.align,
  };
  if (item.rotate) options.rotate = item.rotate;
  slide.addText(objects, options);
}

module.exports = { emitText };
