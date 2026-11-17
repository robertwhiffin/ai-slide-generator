'use strict';
// Writes one text item of the slide model (snapshot_text.mjs) as a pptxgenjs
// text box.
//
// pptxgenjs copies a shape-level option onto every run whose own value is
// falsy (bold: false, charSpacing: 0), so all styling lives on the runs and the
// shape carries geometry only (Global Constraints), plus the paragraph
// alignment: a keyword that is never falsy, which pptxgenjs reads from the
// shape before it writes each paragraph.
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
//   ends the paragraph.

const PX_PER_IN = 96;
const PT_PER_PX = 0.75;
// CSS weights from 600 up are written bold.
const BOLD_FROM_WEIGHT = 600;
// XML 1.0 cannot carry C0 controls other than tab, LF and CR, nor an unpaired
// surrogate; one in a run would make the slide part unreadable.
const XML_UNSAFE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

function inches(px) {
  return px / PX_PER_IN;
}

function runOptions(run) {
  return {
    fontFace: run.family,
    fontSize: run.sizePx * PT_PER_PX,
    color: run.color,
    bold: run.weight >= BOLD_FROM_WEIGHT,
  };
}

function textObjects(item) {
  const objects = [];
  const paragraphs = item.paragraphs || [];
  for (let paragraphIndex = 0; paragraphIndex < paragraphs.length; paragraphIndex++) {
    const lines = paragraphs[paragraphIndex].lines || [];
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      const runs = lines[lineIndex].runs || [];
      if (!runs.length) {
        // A blank line is its <a:br/> alone: pptxgenjs writes no run for empty text.
        const options = { softBreakBefore: lineIndex > 0 };
        if (item.rtl) options.rtlMode = true;
        objects.push({ text: '', options });
        continue;
      }
      for (let runIndex = 0; runIndex < runs.length; runIndex++) {
        const options = runOptions(runs[runIndex]);
        if (item.rtl) options.rtlMode = true;
        if (lineIndex > 0 && runIndex === 0) options.softBreakBefore = true;
        objects.push({ text: String(runs[runIndex].text || '').replace(XML_UNSAFE, ''), options });
      }
    }
    if (paragraphIndex < paragraphs.length - 1 && objects.length) {
      objects[objects.length - 1].options.breakLine = true;
    }
  }
  return objects;
}

// emitText(slide, item): one text item as one text box.
function emitText(slide, item) {
  const objects = textObjects(item);
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
