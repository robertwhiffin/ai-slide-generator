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
// bold from 600 (Review Focus 3). A single-weight face (Impact) is never bold.
//
// The weight named is the face the browser painted with. That is CSS font
// matching over the weights the page loaded, so 600 with only 400 and 700
// loaded is 700. A bold request that only a lighter face could meet is the
// browser's synthetic bold, so it is written as that face plus bold.
//
// Every option lives on the run. pptxgenjs copies a shape option onto any run
// whose own value is falsy (bold: false, charSpacing: 0), so the text box
// carries geometry only (Global Constraints).
//
// Tracking is the run's CSS letter-spacing plus its optical-size tracking: the
// browser draws a variable font with an opsz axis (DM Sans) at the automatic
// optical size, PowerPoint and Google Slides the static opsz-14 cut, about 9%
// wider at title sizes, so the snapshot measured what restores the browser's
// width (snapshot_text.mjs applyMetrics).
//
// Super- and subscript size. PowerPoint and Google Slides draw a run with a
// baseline shift at a fraction of its size, on top of the size the browser
// already reduced it to (font-size: smaller). So the run is written at the
// browser's size over that fraction, and the renderer's shrink brings it back
// to the size the browser drew.

const PT_PER_PX = 0.75;
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

// typefaceFor(family, weight, loadedWeights) -> {fontFace, bold}
//   family         the run's CSS family;
//   weight         its CSS weight;
//   loadedWeights  the weights of that family's webfont faces the page loaded
//                  (model.fonts), empty for a family that is not a loaded webfont.
function typefaceFor(family, weight, loadedWeights) {
  const name = String(family || '');
  const requested = cssWeight(weight);
  const loaded = [];
  const reported = Array.isArray(loadedWeights) ? loadedWeights : [];
  for (const value of reported) {
    const hundred = cssWeight(value);
    if (Number.isFinite(Number(value)) && !loaded.includes(hundred)) loaded.push(hundred);
  }
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

// The weights model.fonts lists for `family`; CSS family names match case-insensitively.
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

// pptxgenjs writes a typeface into an XML attribute as is, so a family named
// with & or a quote would break the slide part.
function xmlAttribute(value) {
  return xmlText(value).replace(/[&<>"]/g, (character) => XML_ATTRIBUTE_ESCAPES[character]);
}

// The size a run is written at, in pt: the browser's, over the renderers'
// shrink for a superscript or subscript run.
function fontSizePt(run) {
  const size = (Number(run.sizePx) || 0) * PT_PER_PX;
  return run.baseline === 'super' || run.baseline === 'sub' ? size / SUPERSCRIPT_SIZE_FACTOR : size;
}

// runOptions(run, fonts) -> the pptxgenjs options of one run.
//   fonts  model.fonts: family -> the webfont weights the page loaded.
// The colour is the run's own: the snapshot wrote it pre-blended and solid,
// because Drive drops text alpha.
function runOptions(run, fonts) {
  const face = typefaceFor(run.family, run.weight, loadedWeightsOf(fonts, run.family));
  const trackingPx = (Number(run.letterSpacingPx) || 0) + (Number(run.opticalTrackingPx) || 0);
  return {
    fontFace: xmlAttribute(face.fontFace),
    bold: face.bold,
    italic: Boolean(run.italic),
    fontSize: fontSizePt(run),
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

module.exports = { typefaceFor, runOptions, blendOver, transparencyOf, xmlText };
