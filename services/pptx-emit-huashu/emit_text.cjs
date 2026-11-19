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
//
// Spacing (spec §3 Text, Spacing; scripts/export_fidelity/CALIBRATION.md).
// PowerPoint and Google Slides draw single (100%) spacing at 1.2 times the
// font size, whatever the font's own metrics, so the spacing of a paragraph of
// a block the browser laid out on more than one line is written against that:
// * a line height up to 1.2 x its largest run's size is a percentage of it
//   (lineSpacingMultiple, <a:spcPct>), the lines soft breaks in one paragraph.
//   Never points in <a:lnSpc>: Drive turns them into a percentage of the
//   natural line height and mis-scales them (RC6);
// * a looser line height is single spacing with every line a paragraph of its
//   own, and the leading beyond single goes before each line after the first
//   as space before (paraSpaceBefore, <a:spcBef> in points). Above 100% the
//   renderers disagree on where the first line goes (Google adds the leading
//   below a line, PowerPoint mostly above it); with single spacing and space
//   before, they agree. The first line of a later paragraph of the block gets
//   half its own leading and half the paragraph's before it, as CSS splits
//   leading above and below each line.
// A block of one line has neither, so its line stays where the renderer's
// single spacing puts it (upstream pitfall 6). pptxgenjs writes a paragraph's
// <a:pPr> from each of its runs' own options, so every run of a paragraph
// carries the same spacing.
//
// Placement. The snapshot's y is the top of the first line's glyphs. The
// renderers set a single-spaced first line by its font size where the browser
// sets it by the font's ascent, and spacing below 100% raises it, so the box is
// raised by firstLineOffsetPx, fitted against both renderers.
//
// A turned block (snapshot_text.mjs turnedBlock: rotated text, or text a
// vertical writing mode sets sideways) is its root's layout box, grown by its
// slack and turned about its centre, so that box stays where it is. Its text
// sits inside it by its insets, written as the box's own (bodyPr lIns, tIns,
// rIns, bIns), none below 0, which Google Slides ignores: the top inset is
// where its first line's glyphs start, less the same first-line offset, and
// no less than 0. A turned box with no insets (a piece of a turned root a gap
// cuts, a turned list marker) has its first line's glyph top as its own top,
// so it is raised by the offset along its own up, which a turn takes off the
// slide's.

const { runOptions, xmlText } = require('./emit_typography.cjs');

const PX_PER_IN = 96;
const PT_PER_PX = 0.75;
const NBSP = '\u00a0';
// PowerPoint's and Google Slides' single spacing, as a multiple of the font size.
const RENDERER_SINGLE_SPACING_EM = 1.2;
const SINGLE_SPACING_PCT = 100;
// The first-line offset, fitted against PowerPoint and Google Slides renders of
// the calibration deck (scripts/export_fidelity/calibrate_text.py), whose
// residuals scripts/export_fidelity/CALIBRATION.md records with these values.
const FIRST_LINE_A = 0.8241;
const FIRST_LINE_B = 1.4338;
const FIRST_LINE_C = -1.5;
// How far Google Slides lowers a line per px its largest written run is
// larger than the line's other runs, measured with DM Sans in Drive's PDF of
// the conversion: 5.57 px for 5.8 px at 20 px, 11.13 px for 11.6 px at 40 px
// (task-11 ruling R11g).
const GOOGLE_LINE_GROWTH_PER_PX = 0.96;

function inches(px) {
  return px / PX_PER_IN;
}

// firstLineOffsetPx(pct, sizePx, ascentPx) -> how far the box's top sits above
// the first line's glyph top, in px:
//   pct       the first paragraph's line spacing, at most 100 (single);
//   sizePx    its largest run's font size;
//   ascentPx  that run's ascent in the browser, glyph top to baseline.
function firstLineOffsetPx(pct, sizePx, ascentPx) {
  const size = Number(sizePx) || 0;
  return FIRST_LINE_A * (pct / 100 - 1) * RENDERER_SINGLE_SPACING_EM * size +
    FIRST_LINE_B * size + FIRST_LINE_C * (Number(ascentPx) || 0);
}

// A paragraph's spacing in a block of `multiLine` lines: {pct, gapPx}, pct its
// <a:spcPct> (null for none) and gapPx the leading beyond single its lines
// after the first take as space before (0 for none).
function spacingOf(paragraph, multiLine) {
  const size = Number(paragraph.sizePx) || 0;
  const lineHeight = Number(paragraph.lineHeightPx) || 0;
  if (!multiLine || !(size > 0) || !(lineHeight > 0)) return { pct: null, gapPx: 0 };
  const single = RENDERER_SINGLE_SPACING_EM * size;
  const pct = Math.round(1000 * lineHeight / single) / 10;
  if (pct > SINGLE_SPACING_PCT) return { pct: SINGLE_SPACING_PCT, gapPx: lineHeight - single };
  return { pct, gapPx: 0 };
}

function lineCount(paragraphs) {
  let count = 0;
  for (const paragraph of paragraphs) count += (paragraph.lines || []).length;
  return count;
}

// A run's options in this item: its style and the item's direction.
// `sizing` is runOptions': the renderer target and the line's size.
function itemRunOptions(run, item, fonts, sizing) {
  const options = runOptions(run, fonts, sizing);
  if (item.rtl) options.rtlMode = true;
  return options;
}

// The size (px) a renderer that sizes a line by every run on it (Google
// Slides) should size `line` by, so it sets the line where the browser did:
// the largest size of its runs that no baseline shift moves, plus what grows
// the line in the browser (its growthPx: a raised script run's line box), in
// the size that grows a renderer's line as much (GOOGLE_LINE_GROWTH_PER_PX).
// A script run is written no larger (emit_typography.cjs fontSizePt). 0 for a
// line of script runs alone, which nothing caps.
function scriptCapPx(line) {
  let largest = 0;
  for (const run of line.runs || []) {
    if (!run.baseline) largest = Math.max(largest, Number(run.sizePx) || 0);
  }
  if (!(largest > 0)) return 0;
  return largest + (Number(line.growthPx) || 0) / GOOGLE_LINE_GROWTH_PER_PX;
}

// A blank line's NBSP run: the previous run's face and size without its glyph
// marks, so neither an underline nor a baseline shift, nor the size a script
// run is enlarged to for the renderer's own shrink.
function blankLineOptions(run, item, fonts) {
  const plain = { ...run, underline: false, strike: false, baseline: null };
  return itemRunOptions(plain, item, fonts);
}

// The item's written paragraphs, in order: {objects, pct, beforePx}, one per
// paragraph of the model, or one per line of a loosely spaced one. `renderer`
// is {target}: the renderer the deck is written for (emitText).
function writtenParagraphs(item, fonts, renderer) {
  const target = renderer && renderer.target;
  const paragraphs = item.paragraphs || [];
  const multiLine = lineCount(paragraphs) > 1;
  const written = [];
  // The last run written, whose style a following blank line takes.
  let previousRun = null;
  let previousGapPx = 0;
  for (let paragraphIndex = 0; paragraphIndex < paragraphs.length; paragraphIndex++) {
    const paragraph = paragraphs[paragraphIndex];
    const spacing = spacingOf(paragraph, multiLine);
    const lines = paragraph.lines || [];
    let current = null;
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      if (!current || spacing.gapPx > 0) {
        let beforePx = spacing.gapPx;
        if (lineIndex === 0) beforePx = paragraphIndex > 0 ? (previousGapPx + spacing.gapPx) / 2 : 0;
        current = { objects: [], pct: spacing.pct, beforePx };
        written.push(current);
      }
      const opensParagraph = current.objects.length === 0;
      const runs = lines[lineIndex].runs || [];
      if (!runs.length) {
        // A blank line never opens its block, so a run precedes it.
        const options = previousRun ? blankLineOptions(previousRun, item, fonts) : {};
        options.softBreakBefore = !opensParagraph;
        current.objects.push({ text: NBSP, options });
        continue;
      }
      const sizing = { target, capPx: scriptCapPx(lines[lineIndex]) };
      for (let runIndex = 0; runIndex < runs.length; runIndex++) {
        const options = itemRunOptions(runs[runIndex], item, fonts, sizing);
        if (runIndex === 0 && !opensParagraph) options.softBreakBefore = true;
        current.objects.push({ text: xmlText(runs[runIndex].text), options });
        previousRun = runs[runIndex];
      }
    }
    previousGapPx = spacing.gapPx;
  }
  return written;
}

// textObjects(item, fonts, renderer) -> the pptxgenjs text array of `item`'s
// paragraphs ({paragraphs, rtl}: a text item, or a native table cell,
// emit_table.cjs): every run carries its paragraph's spacing, and the last run
// of every paragraph but the final one ends it. `renderer` is emitText's.
function textObjects(item, fonts, renderer) {
  const objects = [];
  const written = writtenParagraphs(item, fonts, renderer);
  for (let index = 0; index < written.length; index++) {
    const paragraph = written[index];
    for (const object of paragraph.objects) {
      if (paragraph.pct) object.options.lineSpacingMultiple = paragraph.pct / 100;
      if (paragraph.beforePx > 0) object.options.paraSpaceBefore = paragraph.beforePx * PT_PER_PX;
      objects.push(object);
    }
    if (index < written.length - 1 && paragraph.objects.length) {
      paragraph.objects[paragraph.objects.length - 1].options.breakLine = true;
    }
  }
  return objects;
}

// How far above its first line's glyph top the renderers need the top of the
// item's text: the first-line offset of its first paragraph, in px. Without
// the ascent (the probes failed) the offset is unknown, and is 0.
function firstLineOffsetOf(item) {
  const paragraphs = item.paragraphs || [];
  const first = paragraphs[0];
  if (!first || !(Number(first.ascentPx) > 0)) return 0;
  const spacing = spacingOf(first, lineCount(paragraphs) > 1);
  const pct = spacing.pct || SINGLE_SPACING_PCT;
  return firstLineOffsetPx(pct, first.sizePx, first.ascentPx);
}

// The item's box position and its pptxgenjs margin ([left, right, bottom,
// top] in points): a box raised by the first-line offset with no margin, along
// its own up when it is turned (rotate degrees clockwise: up is (sin, -cos) on
// the slide); or a turned root's own box with its insets, the offset taken off
// the top one.
function placementOf(item) {
  const offset = firstLineOffsetOf(item);
  if (!item.inset) {
    const radians = (Number(item.rotate) || 0) * Math.PI / 180;
    return { x: item.x + offset * Math.sin(radians), y: item.y - offset * Math.cos(radians), margin: 0 };
  }
  const inset = item.inset;
  const top = Math.max(0, (Number(inset.top) || 0) - offset);
  return {
    x: item.x,
    y: item.y,
    margin: [inset.left, inset.right, inset.bottom, top].map((px) => (Number(px) || 0) * PT_PER_PX),
  };
}

// emitText(slide, item, fonts, renderer): one text item as one text box.
//   fonts     model.fonts, the webfont weights the page loaded per family;
//   renderer  {target: 'pptx' | 'gslides'}: the renderer the deck is written
//             for (emit_deck.mjs payload.target), 'pptx' when absent. Only a
//             script run's written size depends on it (emit_typography.cjs).
function emitText(slide, item, fonts, renderer) {
  const objects = textObjects(item, fonts, renderer);
  if (!objects.length) return;
  const placement = placementOf(item);
  const options = {
    x: inches(placement.x),
    y: inches(placement.y),
    w: inches(item.w),
    h: inches(item.h),
    wrap: item.wrap,
    valign: 'top',
    margin: placement.margin,
    inset: 0,
    fit: 'none',
    align: item.align,
  };
  if (item.rotate) options.rotate = item.rotate;
  slide.addText(objects, options);
}

module.exports = { emitText, textObjects };
