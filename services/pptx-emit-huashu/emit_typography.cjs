'use strict';
// Run typography: one run of the slide model (snapshot_text.mjs) as pptxgenjs
// run options, the colour blend every text colour is composited with, and the
// transparency every fill and line alpha is written as.
//
// Weights (spec §5). A run has one bold flag, so 400 is the family and 700 is
// the family plus bold. Any other weight of a webfont the page loaded is that
// weight's named face ("DM Sans SemiBold"), never bold. The static fonts carry
// those legacy family names, so PowerPoint and Google Slides render the real
// weight. A family the page did not load is a font on the viewer's machine,
// whose weight-named faces may not exist: PowerPoint would swap "Arial
// SemiBold" for its default font. So that family keeps its own name and is
// bold from 600. A single-weight face (Impact) is never bold.
//
// The weight named is the face the browser painted with. That is CSS font
// matching over the weights the page loaded, so 600 with only 400 and 700
// loaded is 700. A bold request that only a lighter face could meet is the
// browser's synthetic bold, so it is written as that face plus bold.
//
// Italics, in the deck for PowerPoint (target 'pptx'). The static fonts name
// each italic but Bold Italic a family of its own, with no italic bit ("DM Sans
// Italic", "DM Sans Medium Italic"), so the one italic member of family "DM
// Sans" is its Bold Italic, and PowerPoint draws "DM Sans" plus italic as Bold
// Italic. So an italic run of a loaded webfont is written as its italic static's
// own family, named as the weight's face is plus "Italic", with italic off; at
// 700 it is the family plus bold and italic, the family's Bold Italic (measured
// in PowerPoint for Mac: scripts/export_fidelity/CALIBRATION.md, D1). The
// italic named is the one the browser painted: CSS matching over the weights of
// the family's italic faces the page loaded (model.italicFonts), or over its
// upright faces, which the browser slants, where it loaded no italic. Google
// Slides (target 'gslides') has no family "DM Sans Italic" (it draws another
// font) and draws "DM Sans" plus italic as the italic, so its deck keeps the
// family and the italic flag. A family the page did not load keeps its own
// name and the flag in both decks.
//
// Every option lives on the run. pptxgenjs copies a shape option onto any run
// whose own value is falsy (bold: false, charSpacing: 0), so the text box
// carries geometry only.
//
// Tracking is the run's CSS letter-spacing plus what the snapshot measured
// restores the browser's width in the deck's renderer (snapshot_text_metrics.mjs
// applyMetrics). The browser draws a variable font with an opsz axis (DM Sans)
// at the automatic optical size, PowerPoint and Google Slides the static
// opsz-14 cut, about 9% wider at title sizes. Google Slides kerns, so its deck
// adds that width's delta (opticalTrackingPx; CALIBRATION.md A1). PowerPoint
// for Mac kerns no DM Sans, and pptxgenjs turns its kerning off with every spc
// it writes (kern="0"), Arial's too, so the deck for PowerPoint adds the delta
// with the run's kerning folded in (unkernedTrackingPx; CALIBRATION.md X1).
//
// Super- and subscript size. PowerPoint and Google Slides draw a run with a
// baseline shift at a fraction of its size, on top of the size the browser
// already reduced it to (font-size: smaller). So the run is written at the
// browser's size over that fraction, and the renderer's shrink brings it back
// to the size the browser drew. That is the deck for PowerPoint (target
// 'pptx'), which places the run's line by its other runs as long as one
// follows it (emit_text.cjs writes a word joiner after a run that ends its
// line, lineEndOptions). Google Slides
// (target 'gslides') sizes the LINE by the run's written size, so a larger
// written size pushes the whole line down (about 0.28 em): written for it, a
// script run is capped at the size its line should be sized by (sizing.capPx,
// emit_text.cjs), which keeps the line where the browser has it, the script
// glyph up to some 20% small (measured in both apps; CALIBRATION.md A4).
//
// Hyphens a face lacks. The browser draws U+2010 HYPHEN and U+2011
// NON-BREAKING HYPHEN with the face's own hyphen-minus where the face has
// neither (DM Sans has neither). PowerPoint draws U+2011 so too, but U+2010
// from another font (Cambria Math, 20 px short over two hyphens at 48 px), and
// Google Slides both from MS PGothic (U+2011 22 px short over "end-to-end"),
// and U+2010 there too. Written as U+002D, either is the face's own hyphen in
// every app, the glyph the browser drew (measured: CALIBRATION.md D8). So the
// deck for PowerPoint writes U+2010 as U+002D and keeps U+2011, which keeps its
// no-break meaning when the text is edited; the deck for Google Slides writes
// both as U+002D.

const { PT_PER_PX } = require('./units.cjs');

// The fraction of a superscript or subscript run's size the renderers draw it at,
// calibrated against PowerPoint and Google Slides (scripts/export_fidelity/CALIBRATION.md).
const SUPERSCRIPT_SIZE_FACTOR = 0.646;
const LIGHTEST_WEIGHT = 100;
const HEAVIEST_WEIGHT = 900;
const WEIGHT_STEP = 100;
const REGULAR_WEIGHT = 400;
const BOLD_WEIGHT = 700;
// CSS font matching treats 400 to 500 as one band (CSS Fonts 4 §5.2).
const MEDIUM_WEIGHT = 500;
// From this weight up a weight is bold, and the browser synthesises bold for a lighter face.
const BOLD_FROM_WEIGHT = 600;
// Faces named for each weight other than 400 and 700, which are the family itself.
const WEIGHT_NAMES = {
  100: 'Thin',
  200: 'ExtraLight',
  300: 'Light',
  500: 'Medium',
  600: 'SemiBold',
  800: 'ExtraBold',
  900: 'Black',
};
// Families that ship one weight only, compared lower-cased: a bold flag would only smear them.
const SINGLE_WEIGHT_FAMILIES = new Set(['impact', 'arial black']);
// XML 1.0 cannot carry C0 controls other than tab, LF and CR, nor an unpaired
// surrogate. One of them in a run would make the slide part unreadable.
const XML_UNSAFE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
const XML_ATTRIBUTE_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
// The hyphens each target writes as U+002D (see Hyphens a face lacks).
const HYPHENS_WRITTEN_AS_MINUS = { pptx: /\u2010/g, gslides: /[\u2010\u2011]/g };

// A CSS weight as one of 100..900: a variable font's 450 is 500. Unreadable is 400.
function cssWeight(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return REGULAR_WEIGHT;
  const rounded = Math.round(number / WEIGHT_STEP) * WEIGHT_STEP;
  return Math.min(HEAVIEST_WEIGHT, Math.max(LIGHTEST_WEIGHT, rounded));
}

// The loaded weight the browser paints `desired` with (CSS Fonts 4 §5.2):
// * below 400: the nearest lighter weight, then the nearest heavier;
// * above 500: the nearest heavier weight, then the nearest lighter;
// * 400 to 500: heavier up to 500, then lighter, then heavier past 500.
function matchedWeight(desired, available) {
  if (available.includes(desired)) return desired;
  const lighter = available.filter((weight) => weight < desired).sort((a, b) => b - a);
  const heavier = available.filter((weight) => weight > desired).sort((a, b) => a - b);
  if (desired < REGULAR_WEIGHT) return lighter.length ? lighter[0] : heavier[0];
  if (desired > MEDIUM_WEIGHT) return heavier.length ? heavier[0] : lighter[0];
  const withinBand = heavier.filter((weight) => weight <= MEDIUM_WEIGHT);
  if (withinBand.length) return withinBand[0];
  return lighter.length ? lighter[0] : heavier[0];
}

// The distinct hundreds (100..900) of the weights a model.fonts entry lists;
// none for anything that is not a list of numbers.
function loadedHundreds(loadedWeights) {
  const loaded = [];
  const reported = Array.isArray(loadedWeights) ? loadedWeights : [];
  for (const value of reported) {
    const hundred = cssWeight(value);
    if (Number.isFinite(Number(value)) && !loaded.includes(hundred)) loaded.push(hundred);
  }
  return loaded;
}

// typefaceFor(family, weight, loadedWeights) -> {fontFace, bold}
//   family         the run's CSS family;
//   weight         its CSS weight;
//   loadedWeights  the weights of that family's webfont faces the page loaded
//                  (model.fonts), empty for a family that is not a loaded webfont.
function typefaceFor(family, weight, loadedWeights) {
  const name = String(family || '');
  const requested = cssWeight(weight);
  const loaded = loadedHundreds(loadedWeights);
  if (!loaded.length) {
    const singleWeight = SINGLE_WEIGHT_FAMILIES.has(name.toLowerCase());
    return { fontFace: name, bold: requested >= BOLD_FROM_WEIGHT && !singleWeight };
  }
  const face = matchedWeight(requested, loaded);
  if (face === BOLD_WEIGHT) return { fontFace: name, bold: true };
  const weightName = WEIGHT_NAMES[face];
  return {
    fontFace: weightName ? `${name} ${weightName}` : name,
    bold: requested >= BOLD_FROM_WEIGHT && face < BOLD_FROM_WEIGHT,
  };
}

// italicTypefaceFor(family, weight, loadedWeights, italicWeights)
//   -> {fontFace, bold, italic}: an italic run in the deck for PowerPoint (see
//   Italics above). loadedWeights is typefaceFor's; italicWeights the weights
//   of the family's italic faces the page loaded (model.italicFonts), empty
//   where it loaded none.
function italicTypefaceFor(family, weight, loadedWeights, italicWeights) {
  const loaded = loadedHundreds(loadedWeights);
  if (!loaded.length) return { ...typefaceFor(family, weight, loadedWeights), italic: true };
  const italics = loadedHundreds(italicWeights);
  const requested = cssWeight(weight);
  const face = matchedWeight(requested, italics.length ? italics : loaded);
  const name = String(family || '');
  if (face === BOLD_WEIGHT) return { fontFace: name, bold: true, italic: true };
  const weightName = WEIGHT_NAMES[face];
  return {
    fontFace: `${name} ${weightName ? `${weightName} ` : ''}Italic`,
    bold: requested >= BOLD_FROM_WEIGHT && face < BOLD_FROM_WEIGHT,
    italic: false,
  };
}

// The weights a family -> weights map (model.fonts, model.italicFonts) lists
// for `family`; CSS family names match case-insensitively.
function loadedWeightsOf(fonts, family) {
  if (!fonts || typeof fonts !== 'object') return [];
  if (Object.prototype.hasOwnProperty.call(fonts, family)) return fonts[family];
  const wanted = String(family || '').toLowerCase();
  const names = Object.keys(fonts);
  for (const name of names) {
    if (name.toLowerCase() === wanted) return fonts[name];
  }
  return [];
}

// Run text, and any text pptxgenjs writes into the XML, without the characters XML cannot hold.
function xmlText(value) {
  return String(value || '').replace(XML_UNSAFE, '');
}

// runText(text, sizing) -> a run's text as the deck for sizing.target writes
// it: xmlText, with the hyphens that target's app would draw from another font
// written as U+002D.
function runText(text, sizing) {
  return xmlText(text).replace(HYPHENS_WRITTEN_AS_MINUS[targetOf(sizing)], '-');
}

// pptxgenjs writes a typeface into an XML attribute as is, so a family named
// with & or a quote would break the slide part.
function xmlAttribute(value) {
  return xmlText(value).replace(/[&<>"]/g, (character) => XML_ATTRIBUTE_ESCAPES[character]);
}

// The size a run is written at, in pt: the browser's, over the renderers'
// shrink for a superscript or subscript run; for Google Slides, no larger
// than its line's cap (sizing.capPx).
function fontSizePt(run, sizing) {
  const size = (Number(run.sizePx) || 0) * PT_PER_PX;
  if (!(run.baseline === 'super' || run.baseline === 'sub')) return size;
  const written = size / SUPERSCRIPT_SIZE_FACTOR;
  const capPx = sizing && sizing.target === 'gslides' ? Number(sizing.capPx) : 0;
  return capPx > 0 ? Math.min(written, capPx * PT_PER_PX) : written;
}

// The renderer a run is written for: 'gslides', or 'pptx' (also when none is named).
function targetOf(sizing) {
  return sizing && sizing.target === 'gslides' ? 'gslides' : 'pptx';
}

// runOptions(run, faces, sizing) -> the pptxgenjs options of one run.
//   faces   the webfonts the page loaded, {weights: model.fonts, italicWeights:
//           model.italicFonts}: each a family -> the weights of its faces (all
//           of them, and the italic ones);
//   sizing  {target: 'pptx' | 'gslides', capPx}, or none for 'pptx': the
//           renderer the deck is written for, and the size (px) the run's
//           line should be sized by, which a Google Slides script run is
//           capped at (emit_text.cjs scriptCapPx).
// The colour is the run's own: the snapshot wrote it pre-blended and solid,
// because Drive drops text alpha.
function runOptions(run, faces, sizing) {
  const known = faces && typeof faces === 'object' ? faces : {};
  const weights = loadedWeightsOf(known.weights, run.family);
  const face = run.italic && targetOf(sizing) === 'pptx'
    ? italicTypefaceFor(run.family, run.weight, weights, loadedWeightsOf(known.italicWeights, run.family))
    : { ...typefaceFor(run.family, run.weight, weights), italic: Boolean(run.italic) };
  const measuredPx = targetOf(sizing) === 'pptx' ? run.unkernedTrackingPx : run.opticalTrackingPx;
  const trackingPx = (Number(run.letterSpacingPx) || 0) + (Number(measuredPx) || 0);
  return {
    fontFace: xmlAttribute(face.fontFace),
    bold: face.bold,
    italic: face.italic,
    fontSize: fontSizePt(run, sizing),
    color: run.color,
    charSpacing: trackingPx * PT_PER_PX,
    underline: run.underline ? { style: 'sng' } : undefined,
    strike: run.strike ? 'sngStrike' : undefined,
    superscript: run.baseline === 'super',
    subscript: run.baseline === 'sub',
  };
}

// transparencyOf(alpha) -> the pptxgenjs transparency of a fill or line at
// `alpha` (0..1): a whole percentage, where 0 means opaque and writes no alpha.
function transparencyOf(alpha) {
  return Math.round((1 - alpha) * 100);
}

// blendOver(color, alpha, backdrop) -> 'RRGGBB': `color` at `alpha` painted
// over the opaque `backdrop`, each channel round(c * a + b * (1 - a)). Both
// colours are 'RRGGBB'.
//
// The snapshot composes this function's own text into its page source
// (snapshot.mjs) and composites every text colour with it, layer by layer. So
// it reads nothing outside itself.
function blendOver(color, alpha, backdrop) {
  const weight = Math.min(1, Math.max(0, Number(alpha) || 0));
  let blended = '';
  for (let offset = 0; offset < 6; offset += 2) {
    const top = parseInt(String(color).slice(offset, offset + 2), 16);
    const under = parseInt(String(backdrop).slice(offset, offset + 2), 16);
    const channel = Math.round(top * weight + under * (1 - weight));
    // An unreadable channel would serialise as the hex "NaN" and corrupt the slide XML.
    const safe = Number.isFinite(channel) ? Math.min(255, Math.max(0, channel)) : 0;
    blended += (safe < 16 ? '0' : '') + safe.toString(16);
  }
  return blended.toUpperCase();
}

module.exports = { typefaceFor, runOptions, runText, blendOver, transparencyOf, xmlText };
