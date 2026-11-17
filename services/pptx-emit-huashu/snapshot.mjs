// The snapshot: one read-only page.evaluate that turns the slide the browser
// rendered into a JSON slide model, which emit_model.cjs writes to pptxgenjs.
//
// It reads; it does not rewrite. Layout is taken exactly as the browser laid it
// out (getComputedStyle and getBoundingClientRect per element), so nothing the
// export emits can drift from what the user saw because a pass moved it first.
// Every DOM traversal goes through DOM_ACCESS_SOURCE (pristine-realm accessors,
// bounded collections), because slide script runs in this page before we do.
//
// /**
//  * SlideModel = {
//  *   width, height,                       // CSS px; the slide is 1280x720
//  *   background: {color: 'RRGGBB'} | {image: 'data:image/…;base64,…'},
//  *   items: Item[],                        // sorted back to front, by `order` then `id`
//  *   captures: Capture[],
//  *   fonts: {'<family>': number[]},        // the weights (100..900) of its faces in
//  *                                         // document.fonts that loaded: the page's webfonts
//  *   reference: {hiddenText: string},
//  *   stats: {elements, shapes, images, texts, truncated},
//  * }
//  *
//  * Every Item carries:
//  *   id     the item's sequence number in DOM pre-order (stable, deterministic);
//  *   order  its CSS paint-order key, a number[] compared lexicographically.
//  *
//  * Item =
//  *  {kind:'shape', x,y,w,h, geometry:'rect'|'roundRect'|'ellipse', radius,
//  *   fill:{color:'RRGGBB', alpha}|null, line:{color, alpha, widthPx, dash:'solid'|'dash'|'dot'}|null,
//  *   shadow:{color, alpha, blurPx, offsetPx, angle}|null, rotate}
//  *  {kind:'line', x1,y1,x2,y2, color, alpha, widthPx, dash}
//  *  {kind:'image', x,y,w,h, src:'data:…'|null, captureId:'c<n>'|null, alpha, rotate}
//  *  {kind:'text', x,y,w,h, rotate:null, wrap:boolean, align:'left'|'center'|'right',
//  *   rtl:boolean, paragraphs:[{sizePx, lineHeightPx:number|null, ascentPx:number|null,
//  *   lines:[{runs:Run[]}]}]}
//  *   (one text block; snapshot_text.mjs documents Run, lines, the metrics and the geometry)
//  *
//  * Capture = {id, x,y,w,h, mode:'subtree'|'box', selector:'[data-tellr-capture="c<n>"]'}
//  *
//  * Units: CSS px on the slide. `alpha` is 0..1 and already includes the cumulative
//  * opacity of the element and its ancestors. A shape's box is where its outline's
//  * centre runs, so a bordered box is inset by half the border width, and `radius`
//  * is the radius of that centre line. `rotate` is degrees clockwise, or null.
//  * An image's `alpha` is the opacity the emitter still has to apply: 1 for a
//  * capture, whose pixels already carry it.
//  */

import { DOM_ACCESS_SOURCE } from './dom_access.mjs';
import { blendOver } from './emit_typography.cjs';
import { GRADIENT_SOURCE } from './gradient.mjs';
import { SLIDE_ROOT_MARKER } from './preprocess.mjs';
import { TEXT_SOURCE } from './snapshot_text.mjs';

// Runs in the page, inside the IIFE below, after DOM_ACCESS_SOURCE,
// GRADIENT_SOURCE, TEXT_SOURCE and blendOver: queryOne, elementChildrenOf,
// domAccess, reportCollectionLoss, the two limits, splitTopLevelCommas,
// parseLinearGradient, createTextLayout and blendOver are its free names. It is
// stringified, so it closes over nothing on the Node side; everything it needs
// from here arrives in `config`.
async function snapshotPage(config) {
  const SLIDE_WIDTH = 1280;
  const SLIDE_HEIGHT = 720;
  // Replaced elements paint content the walker cannot read as boxes, so they are
  // picture items and the walk does not descend into them.
  const REPLACED = new Set(['img', 'svg', 'canvas', 'video', 'audio', 'iframe', 'object', 'embed']);
  // Only raster data: sources are ever embedded (SDR-4437); SVG data would land
  // in pptxgenjs's broken-image placeholder.
  const RASTER_DATA_URI = /^data:image\/(png|jpe?g|gif);base64,/i;
  // Radii within this of half a side count as reaching it (layout rounding).
  const RADIUS_EPSILON_PX = 0.01;

  const dom = domAccess();
  const html = queryOne('html');
  const body = queryOne('body');
  if (!body || !html) throw new Error('[html2pptx] the slide document has no body');
  const slideRoot = queryOne('[' + config.slideRootMarker + ']');

  const items = [];
  const captures = [];
  const stats = { elements: 0, shapes: 0, images: 0, texts: 0, truncated: false };
  let nextItemId = 0;

  // ─── colours ─────────────────────────────────────────────────────────
  // Chrome serializes legacy-syntax colours as rgb()/rgba(), and keeps modern
  // ones (oklch(), lab(), color-mix()) in their own space. The fast path parses
  // the first two; anything else is converted by the canvas, which speaks every
  // syntax the page does. Cached per string: a pure function of its input.
  const colourCache = new Map();
  let colourContext = null;

  function colourFrom(red, green, blue, alpha) {
    // A non-finite channel would serialize as the hex "NaN" and corrupt the slide XML.
    const channel = (value) => (Number.isFinite(value) ? Math.max(0, Math.min(255, Math.round(value))) : 0);
    const r = channel(red);
    const g = channel(green);
    const b = channel(blue);
    const hex = [r, g, b].map((value) => value.toString(16).padStart(2, '0')).join('').toUpperCase();
    return { color: hex, alpha: Math.max(0, Math.min(1, alpha)), r, g, b };
  }

  function alphaComponent(text) {
    if (text === undefined) return 1;
    return /%$/.test(text) ? parseFloat(text) / 100 : parseFloat(text);
  }

  function colourByCanvas(value) {
    try {
      if (!colourContext) {
        const canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        colourContext = canvas.getContext('2d', { willReadFrequently: true });
      }
      colourContext.fillStyle = 'transparent';
      const unset = colourContext.fillStyle;
      colourContext.fillStyle = value;
      // An unparseable value leaves fillStyle untouched; so does a transparent one.
      if (colourContext.fillStyle === unset) return null;
      colourContext.clearRect(0, 0, 1, 1);
      colourContext.fillRect(0, 0, 1, 1);
      const pixel = colourContext.getImageData(0, 0, 1, 1).data;
      return colourFrom(pixel[0], pixel[1], pixel[2], pixel[3] / 255);
    } catch (e) {
      return null;
    }
  }

  // {color: 'RRGGBB', alpha, r, g, b}, or null for no colour at all.
  function parseColour(value) {
    if (!value || value === 'none' || value === 'transparent') return null;
    if (colourCache.has(value)) return colourCache.get(value);
    let parsed = null;
    const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*(?:[,/]\s*([\d.]+%?)\s*)?\)$/i.exec(value);
    const srgb = /^color\(srgb\s+([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)\s*(?:\/\s*([\d.]+%?)\s*)?\)$/i.exec(value);
    if (rgb) {
      parsed = colourFrom(+rgb[1], +rgb[2], +rgb[3], alphaComponent(rgb[4]));
    } else if (srgb) {
      parsed = colourFrom(+srgb[1] * 255, +srgb[2] * 255, +srgb[3] * 255, alphaComponent(srgb[4]));
    } else {
      parsed = colourByCanvas(value);
    }
    colourCache.set(value, parsed);
    return parsed;
  }

  // The colour as painted: its own alpha times the cumulative opacity. Null when nothing shows.
  function paintedColour(value, opacity) {
    const colour = parseColour(value);
    if (!colour) return null;
    const alpha = colour.alpha * opacity;
    return alpha > 0 ? { color: colour.color, alpha } : null;
  }

  // ─── gradient colour ─────────────────────────────────────────────────
  // The colour at the middle of a background-image's first gradient, as
  // parseColour gives a colour, or null for none. Halfway along a linear
  // gradient's line its stops are interpolated there (premultiplied, as CSS
  // interpolates legacy colours), so a three-stop gradient gives its middle
  // stop and a two-stop one the mix of both, whether its stops are placed in
  // percentages or lengths. A gradient the stop parser (GRADIENT_SOURCE) does
  // not read, a radial or conic one, gives its first colour.
  const gradientCache = new Map();
  const COLOUR_IN_GRADIENT = /(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^)]*\)|#[0-9a-f]{3,8}\b/i;

  function colourAt(stops, position) {
    let lower = null;
    let upper = null;
    for (let index = 0; index < stops.length; index++) {
      if (stops[index].pos <= position) {
        lower = stops[index];
      } else {
        upper = stops[index];
        break;
      }
    }
    if (!lower) return upper.colour;
    if (!upper) return lower.colour;
    const fraction = (position - lower.pos) / (upper.pos - lower.pos);
    const from = lower.colour;
    const to = upper.colour;
    const alpha = from.alpha + (to.alpha - from.alpha) * fraction;
    if (!(alpha > 0)) return colourFrom(0, 0, 0, 0);
    const channel = (start, end) => (start * from.alpha + (end * to.alpha - start * from.alpha) * fraction) / alpha;
    return colourFrom(channel(from.r, to.r), channel(from.g, to.g), channel(from.b, to.b), alpha);
  }

  // The stop parser strips only a trailing percentage, so a stop placed at a
  // length still carries it: Chrome computes "#FF3621 0px" and "#FF3621 2em"
  // alike to "rgb(255, 54, 33) 0px". So do the two positions of a two-position stop.
  const TRAILING_STOP_LENGTHS = /(?:\s+-?[\d.]+(?:e[-+]?\d+)?[a-z%]*){1,2}\s*$/i;

  function firstColourIn(layer) {
    const first = COLOUR_IN_GRADIENT.exec(layer);
    return first ? parseColour(first[0]) : null;
  }

  // A stop's colour, its positions stripped. A stop with no percentage keeps
  // the parser's position, its index spread evenly over the line: where a
  // length falls on the gradient line depends on a box the parser never sees.
  function stopColour(text) {
    return parseColour(text) || parseColour(String(text).replace(TRAILING_STOP_LENGTHS, '').trim());
  }

  function gradientLayerMiddle(layer) {
    const parsed = /^(repeating-)?linear-gradient\(/i.test(layer) ? parseLinearGradient(layer) : null;
    if (!parsed) return firstColourIn(layer);
    // Stops in order: CSS moves a stop placed before the one ahead of it up to it.
    const stops = [];
    for (let index = 0; index < parsed.stops.length; index++) {
      const colour = stopColour(parsed.stops[index].color);
      if (!colour) continue;
      const floor = stops.length ? stops[stops.length - 1].pos : -Infinity;
      stops.push({ colour, pos: Math.max(parsed.stops[index].pos, floor) });
    }
    // Stops none of which reads still name colours: text clipped to them must not vanish.
    return stops.length ? colourAt(stops, 0.5) : firstColourIn(layer);
  }

  function gradientMiddle(value) {
    if (!value || value === 'none' || !/gradient\(/i.test(value)) return null;
    if (gradientCache.has(value)) return gradientCache.get(value);
    let middle = null;
    try {
      const layers = splitTopLevelCommas(String(value));
      for (let index = 0; index < layers.length; index++) {
        if (!/gradient\(/i.test(layers[index])) continue;
        middle = gradientLayerMiddle(layers[index]);
        break;
      }
    } catch (e) {
      middle = null;
    }
    gradientCache.set(value, middle);
    return middle;
  }

  // ─── text colour ─────────────────────────────────────────────────────
  // Drive drops text alpha, so every run is written in the solid colour the
  // browser paints its glyphs with (spec §3 Runs). The walk carries a backdrop
  // down the tree, and the text layout extends it through inline elements:
  //   Backdrop = {color:'RRGGBB', alpha, group: {opacity, beneath: Backdrop} | null}
  // `color` at `alpha` is what is painted so far inside the innermost opacity
  // group, or on the slide's opaque ground when the group is null.
  // * An element with opacity below 1 opens a group. Its content, its own
  //   background first, paints on a transparent layer, which is then faded as
  //   a whole over what lies beneath it.
  // * A visible element's background colour, then the colour at the middle of
  //   its gradient, are layers over the backdrop. They lie under its text
  //   whatever they are clipped to: background-clip: text clips them to exactly
  //   the glyphs, which is how gradient text shows its gradient. A url() image
  //   has no colour to read and adds no layer.
  // * Only ancestors are read. A sibling box drawn under the text is not.
  // The glyphs (-webkit-text-fill-color, which defaults to color) paint over
  // their backdrop inside the innermost group. Then each group, inner to outer,
  // is faded at its opacity over the backdrop beneath it. Every step is
  // blendOver (emit_typography.cjs) on 'RRGGBB', rounded at each step.
  const TRANSPARENT_LAYER = { color: '000000', alpha: 0 };
  // A text colour no parser reads is painted black rather than dropped, so its words still show.
  const UNREADABLE_TEXT_COLOUR = { color: '000000', alpha: 1 };

  // `layer` ({color, alpha}) painted over `backdrop`, inside the backdrop's group.
  function paintOver(layer, backdrop) {
    if (!(layer.alpha > 0)) return backdrop;
    if (layer.alpha >= 1 || backdrop.alpha >= 1) {
      return { color: blendOver(layer.color, layer.alpha, backdrop.color), alpha: 1, group: backdrop.group };
    }
    const alpha = layer.alpha + backdrop.alpha * (1 - layer.alpha);
    return { color: blendOver(layer.color, layer.alpha / alpha, backdrop.color), alpha, group: backdrop.group };
  }

  // backdropInside(backdrop, s) -> the backdrop of the content inside the
  // element whose computed style is `s`, given the backdrop it sits on.
  function backdropInside(backdrop, s) {
    let inside = backdrop;
    const opacity = opacityOf(s);
    if (opacity < 1) {
      inside = { color: TRANSPARENT_LAYER.color, alpha: TRANSPARENT_LAYER.alpha, group: { opacity, beneath: inside } };
    }
    if (s.visibility !== 'visible') return inside;
    const colour = parseColour(s.backgroundColor);
    if (colour) inside = paintOver(colour, inside);
    const middle = gradientMiddle(s.backgroundImage);
    if (middle) inside = paintOver(middle, inside);
    return inside;
  }

  // textColour(backdrop, s) -> 'RRGGBB': the solid colour the text of the
  // element whose computed style is `s` paints, over `backdrop`.
  function textColour(backdrop, s) {
    const fill = parseColour(s.webkitTextFillColor) || parseColour(s.color) || UNREADABLE_TEXT_COLOUR;
    let layer = paintOver(fill, backdrop);
    for (let depth = 0; layer.group && depth < WALK_STEP_LIMIT; depth++) {
      const group = layer.group;
      layer = paintOver({ color: layer.color, alpha: layer.alpha * group.opacity }, group.beneath);
    }
    return layer.color;
  }

  // ─── the slide background ────────────────────────────────────────────
  // The background transfer (BG_TRANSFER_SOURCE) has already moved the slide
  // root's ground onto body, so body is the slide's ground: its raster image if
  // it has one, else its colour composited over html's over the white canvas.
  function backgroundImageOf(value) {
    if (!value || value === 'none') return null;
    if (/gradient\(/i.test(value)) {
      console.warn('[html2pptx] gradient on the slide body: the slide background uses its colour instead');
      return null;
    }
    const match = /url\(["']?([^"')]+)["']?\)/.exec(value);
    if (!match) return null;
    if (RASTER_DATA_URI.test(match[1])) return match[1];
    console.warn('[html2pptx] skipped a non-data: background image');
    return null;
  }

  function slideBackground(htmlStyle, bodyStyle) {
    const image = backgroundImageOf(bodyStyle.backgroundImage);
    if (image) return { image };
    return { color: groundColour(htmlStyle, bodyStyle) };
  }

  // The slide's ground colour: body's background colour over html's over the
  // white canvas. Under a background image it is still what the text backdrop
  // starts from; the slide root that painted the image adds its own layer.
  function groundColour(htmlStyle, bodyStyle) {
    let ground = { r: 255, g: 255, b: 255 };
    const layers = [parseColour(htmlStyle.backgroundColor), parseColour(bodyStyle.backgroundColor)];
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      if (!layer || !(layer.alpha > 0)) continue;
      ground = {
        r: layer.r * layer.alpha + ground.r * (1 - layer.alpha),
        g: layer.g * layer.alpha + ground.g * (1 - layer.alpha),
        b: layer.b * layer.alpha + ground.b * (1 - layer.alpha),
      };
    }
    return colourFrom(ground.r, ground.g, ground.b, 1).color;
  }

  // ─── paint order ─────────────────────────────────────────────────────
  // ctx = {prefix: number[]} is the current REAL stacking context; paint is
  // where this element's own non-context content is painted (a pseudo-context
  // for positioned z:auto elements, flex and grid items, atomic inlines and floats).
  // Within a context the layers are: 0 its own box, 1 negative z-index,
  // 2 in-flow blocks, 3 floats, 4 inline content and atomic boxes, 5 positioned
  // z:auto/0 in tree order, 6 positive z-index. Item order keys extend these.
  function opacityOf(style) {
    const value = parseFloat(style.opacity);
    return Number.isFinite(value) ? value : 1;
  }

  function createsStackingContext(s, positioned, zAuto, flexItem) {
    return (positioned && !zAuto) || (flexItem && !zAuto) ||
      s.position === 'fixed' || s.position === 'sticky' ||
      opacityOf(s) < 1 || s.transform !== 'none' ||
      (s.rotate && s.rotate !== 'none') || (s.scale && s.scale !== 'none') ||
      (s.translate && s.translate !== 'none') ||
      s.filter !== 'none' || (s.backdropFilter && s.backdropFilter !== 'none') ||
      s.isolation === 'isolate' || s.mixBlendMode !== 'normal' ||
      (s.clipPath && s.clipPath !== 'none') || (s.maskImage && s.maskImage !== 'none') ||
      /\b(paint|layout|strict|content)\b/.test(s.contain || '');
  }

  function placement(s, layoutStyle, ctx, paint, seq, replaced) {
    const positioned = s.position !== 'static';
    const zAuto = s.zIndex === 'auto';
    const flexItem = /flex|grid/.test(layoutStyle.display);
    const z = zAuto ? 0 : parseInt(s.zIndex, 10) || 0;
    if (createsStackingContext(s, positioned, zAuto, flexItem)) {
      const prefix = ctx.prefix.concat(z < 0 ? [1, z, seq] : z > 0 ? [6, z, seq] : [5, 0, seq]);
      return { ctx: { prefix }, paint: prefix, box: prefix.concat([0, 0, 0]) };
    }
    // An inline replaced element (an <img> in a line) is an atomic inline box too.
    const atomicInline = /^inline-(block|flex|grid|table)$/.test(s.display) ||
      (replaced && s.display === 'inline');
    if (positioned || flexItem || atomicInline) {
      const group = (positioned ? ctx.prefix : paint).concat(positioned ? [5, 0, seq] : [4, 0, seq]);
      return { ctx, paint: group, box: group.concat([0, 0, 0]) };
    }
    // A float paints atomically (CSS 2.1 Appendix E): after every in-flow block
    // of its context, and with its own content above its own background. After
    // the branch above, so a positioned float keeps the positioned layer.
    if (s.float !== 'none') {
      const group = paint.concat([3, 0, seq]);
      return { ctx, paint: group, box: group.concat([0, 0, 0]) };
    }
    return { ctx, paint, box: paint.concat([2, 0, seq]) };
  }

  function compareItems(a, b) {
    const shared = Math.min(a.order.length, b.order.length);
    for (let index = 0; index < shared; index++) {
      if (a.order[index] !== b.order[index]) return a.order[index] - b.order[index];
    }
    if (a.order.length !== b.order.length) return a.order.length - b.order.length;
    return a.id - b.id;
  }

  // ─── geometry ────────────────────────────────────────────────────────
  // getBoundingClientRect is the transformed box's axis-aligned bounds. For a
  // rotated element the emitted box is the untransformed layout box (offset
  // size times the cumulative scale), centred where the bounds are centred,
  // plus the cumulative angle. Bounds of a rotated rectangle share its centre.
  function normalisedAngle(degrees) {
    const angle = ((degrees % 360) + 360) % 360;
    return Math.abs(angle) < 0.01 || Math.abs(angle - 360) < 0.01 ? 0 : angle;
  }

  function ownTransform(s) {
    let angle = 0;
    let scaleX = 1;
    let scaleY = 1;
    const matrix = /^matrix(3d)?\(([^)]*)\)$/.exec(s.transform || '');
    if (matrix) {
      const values = matrix[2].split(',').map(Number);
      const a = values[0];
      const b = values[1];
      const c = matrix[1] ? values[4] : values[2];
      const d = matrix[1] ? values[5] : values[3];
      const horizontal = Math.hypot(a, b);
      if (horizontal > 0) {
        angle += Math.atan2(b, a) * 180 / Math.PI;
        scaleX *= horizontal;
        scaleY *= Math.abs(a * d - b * c) / horizontal;
      }
    }
    const rotate = /^(-?[\d.]+)deg$/.exec(s.rotate || '');
    if (rotate) angle += parseFloat(rotate[1]);
    if (s.scale && s.scale !== 'none') {
      const factors = s.scale.split(/\s+/).map(Number);
      if (Number.isFinite(factors[0])) scaleX *= Math.abs(factors[0]);
      const vertical = factors.length > 1 ? factors[1] : factors[0];
      if (Number.isFinite(vertical)) scaleY *= Math.abs(vertical);
    }
    return { angle, scaleX, scaleY };
  }

  function frameOf(s, parentFrame) {
    const own = ownTransform(s);
    const scaleX = parentFrame.scaleX * own.scaleX;
    const scaleY = parentFrame.scaleY * own.scaleY;
    return {
      angle: normalisedAngle(parentFrame.angle + own.angle),
      scaleX,
      scaleY,
      scale: Math.sqrt(scaleX * scaleY),
    };
  }

  function boxGeometry(element, rect, frame) {
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const bounds = { x: rect.left, y: rect.top, w: rect.width, h: rect.height, scale: frame.scale, rotate: null };
    if (!frame.angle) return bounds;
    const layoutWidth = Number(element.offsetWidth);
    const layoutHeight = Number(element.offsetHeight);
    if (!(layoutWidth > 0 && layoutHeight > 0)) return bounds;
    const w = layoutWidth * frame.scaleX;
    const h = layoutHeight * frame.scaleY;
    const centreX = rect.left + rect.width / 2;
    const centreY = rect.top + rect.height / 2;
    return { x: centreX - w / 2, y: centreY - h / 2, w, h, scale: frame.scale, rotate: frame.angle };
  }

  // ─── boxes ───────────────────────────────────────────────────────────
  function lengthAgainst(token, basis, scale) {
    if (/%$/.test(token)) return parseFloat(token) / 100 * basis;
    return (parseFloat(token) || 0) * scale;
  }

  function cornerRadius(value, box) {
    const parts = String(value || '0').trim().split(/\s+/);
    return {
      h: lengthAgainst(parts[0], box.w, box.scale),
      v: lengthAgainst(parts.length > 1 ? parts[1] : parts[0], box.h, box.scale),
    };
  }

  // The used corner radii after CSS's overlap rule (all scaled down together
  // until no two adjacent radii exceed their side), then the preset they need:
  // an ellipse when every corner reaches half its side, else a roundRect
  // carrying the largest corner.
  function cornerShape(s, box) {
    const corners = [
      cornerRadius(s.borderTopLeftRadius, box),
      cornerRadius(s.borderTopRightRadius, box),
      cornerRadius(s.borderBottomRightRadius, box),
      cornerRadius(s.borderBottomLeftRadius, box),
    ];
    // Indexed, not destructured: destructuring reads Array.prototype[Symbol.iterator], which page script can replace.
    const topLeft = corners[0];
    const topRight = corners[1];
    const bottomRight = corners[2];
    const bottomLeft = corners[3];
    let factor = 1;
    const sums = [
      [topLeft.h + topRight.h, box.w],
      [bottomLeft.h + bottomRight.h, box.w],
      [topLeft.v + bottomLeft.v, box.h],
      [topRight.v + bottomRight.v, box.h],
    ];
    for (let index = 0; index < sums.length; index++) {
      if (sums[index][0] > sums[index][1]) factor = Math.min(factor, sums[index][1] / sums[index][0]);
    }
    let ellipse = true;
    let largest = 0;
    for (let index = 0; index < corners.length; index++) {
      const horizontal = corners[index].h * factor;
      const vertical = corners[index].v * factor;
      if (horizontal < box.w / 2 - RADIUS_EPSILON_PX || vertical < box.h / 2 - RADIUS_EPSILON_PX) ellipse = false;
      largest = Math.max(largest, Math.min(horizontal, vertical));
    }
    if (ellipse) return { geometry: 'ellipse', radius: 0 };
    return { geometry: largest > 0 ? 'roundRect' : 'rect', radius: largest };
  }

  // A border that is the same on all four sides is the shape's outline. Per-side
  // borders paint as separate lines and are not an outline.
  const SIDES = ['Top', 'Right', 'Bottom', 'Left'];
  function uniformBorder(s, opacity, scale) {
    const width = parseFloat(s.borderTopWidth) || 0;
    const style = s.borderTopStyle;
    const colour = s.borderTopColor;
    if (!(width > 0) || style === 'none' || style === 'hidden') return null;
    for (let index = 1; index < SIDES.length; index++) {
      const side = SIDES[index];
      if (Math.abs((parseFloat(s['border' + side + 'Width']) || 0) - width) > 0.01 ||
          s['border' + side + 'Style'] !== style || s['border' + side + 'Color'] !== colour) {
        return null;
      }
    }
    const painted = paintedColour(colour, opacity);
    if (!painted) return null;
    const dash = style === 'dashed' ? 'dash' : style === 'dotted' ? 'dot' : 'solid';
    return { color: painted.color, alpha: painted.alpha, widthPx: width * scale, dash };
  }

  // The first painted outer shadow (PowerPoint keeps one per shape). Chrome
  // writes each layer colour first, then offset-x, offset-y, blur, spread. A
  // spread with no blur or offset is an outline ring, not a shadow. The
  // direction is screen-fixed, because the emitted shadow does not rotate with
  // its shape. Layers split at top-level commas (GRADIENT_SOURCE): the commas
  // inside rgba(...) separate nothing.
  function outerShadow(value, opacity, box) {
    if (!value || value === 'none') return null;
    const layers = splitTopLevelCommas(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      if (/\binset\b/.test(layer)) continue;
      const functional = /^[a-z-]+\([^)]*\)/i.exec(layer);
      const colourText = functional ? functional[0] : layer.split(/\s+/)[0];
      const painted = paintedColour(colourText, opacity);
      if (!painted) continue;
      const lengths = (layer.slice(colourText.length).match(/-?[\d.]+(?:e[-+]?\d+)?px/g) || []).map(parseFloat);
      const offsetX = lengths[0] || 0;
      const offsetY = lengths[1] || 0;
      const blur = lengths[2] || 0;
      const spread = lengths[3] || 0;
      if (spread !== 0 && blur === 0 && offsetX === 0 && offsetY === 0) continue;
      return {
        color: painted.color,
        alpha: painted.alpha,
        blurPx: blur * box.scale,
        offsetPx: Math.hypot(offsetX, offsetY) * box.scale,
        angle: normalisedAngle(Math.atan2(offsetY, offsetX) * 180 / Math.PI + (box.rotate || 0)),
      };
    }
    return null;
  }

  // background-clip: text paints the background inside the glyphs only, where
  // the text's own colour carries it (textColour), so it fills no box.
  function clipsToText(s) {
    return /\btext\b/.test(String(s.backgroundClip || '')) || /\btext\b/.test(String(s.webkitBackgroundClip || ''));
  }

  // A painted box becomes a shape: background colour, uniform border and outer
  // shadow. The slide root's ground is the slide background (BG_TRANSFER put
  // it on body), so its fill and shadow are never painted a second time here.
  function emitBox(s, box, opacity, order, isSlideRoot) {
    const fill = isSlideRoot || clipsToText(s) ? null : paintedColour(s.backgroundColor, opacity);
    let line = uniformBorder(s, opacity, box.scale);
    const shadow = isSlideRoot ? null : outerShadow(s.boxShadow, opacity, box);
    if (!fill && !line && !shadow) return;
    // The outline is stroked on the shape's edge, centred on it; CSS paints the
    // border inside the border box. Inset by half the width so the two coincide.
    let inset = line ? line.widthPx / 2 : 0;
    if (!(box.w - 2 * inset > 0 && box.h - 2 * inset > 0)) {
      line = null;
      inset = 0;
      if (!fill && !shadow) return;
    }
    const w = box.w - 2 * inset;
    const h = box.h - 2 * inset;
    const corners = cornerShape(s, box);
    let geometry = corners.geometry;
    let radius = 0;
    if (geometry === 'roundRect') {
      radius = Math.min(corners.radius - inset, Math.min(w, h) / 2);
      if (!(radius > 0)) geometry = 'rect';
    }
    items.push({
      kind: 'shape',
      id: nextItemId++,
      order,
      x: box.x + inset,
      y: box.y + inset,
      w,
      h,
      geometry,
      radius: geometry === 'roundRect' ? radius : 0,
      fill,
      line,
      shadow,
      rotate: box.rotate,
    });
    stats.shapes++;
  }

  // ─── replaced content ────────────────────────────────────────────────
  // The picture sits in the content box (inside border and padding), and a
  // raster data: <img> is embedded as is when its fit keeps the whole image:
  // object-fit fill stretches it to the content box, contain letterboxes it at
  // the centre. Every other picture carries no data until it is captured.
  function contentBox(s, box) {
    const edge = (side) => ((parseFloat(s['border' + side + 'Width']) || 0) +
      (parseFloat(s['padding' + side]) || 0)) * box.scale;
    const left = edge('Left');
    const right = edge('Right');
    const top = edge('Top');
    const bottom = edge('Bottom');
    const w = box.w - left - right;
    const h = box.h - top - bottom;
    if (!(w > 0 && h > 0)) return null;
    // Asymmetric edges move the centre in the element's own frame; rotate that shift.
    const radians = (box.rotate || 0) * Math.PI / 180;
    const shiftX = (left - right) / 2;
    const shiftY = (top - bottom) / 2;
    const centreX = box.x + box.w / 2 + shiftX * Math.cos(radians) - shiftY * Math.sin(radians);
    const centreY = box.y + box.h / 2 + shiftX * Math.sin(radians) + shiftY * Math.cos(radians);
    return { x: centreX - w / 2, y: centreY - h / 2, w, h };
  }

  function embeddedImage(element, s, area) {
    const source = String(element.currentSrc || element.src || '');
    const naturalWidth = Number(element.naturalWidth);
    const naturalHeight = Number(element.naturalHeight);
    if (!RASTER_DATA_URI.test(source) || !(naturalWidth > 0 && naturalHeight > 0)) return null;
    const fit = s.objectFit || 'fill';
    if (fit === 'fill') return { src: source, area };
    const centred = /^50% 50%$/.test(s.objectPosition || '50% 50%');
    if (fit === 'contain' && centred) {
      const scale = Math.min(area.w / naturalWidth, area.h / naturalHeight);
      const w = naturalWidth * scale;
      const h = naturalHeight * scale;
      return { src: source, area: { x: area.x + (area.w - w) / 2, y: area.y + (area.h - h) / 2, w, h } };
    }
    return null;
  }

  function emitReplaced(element, name, s, box, opacity, order) {
    const area = contentBox(s, box);
    if (!area) return;
    const embedded = name === 'img' ? embeddedImage(element, s, area) : null;
    const placed = embedded ? embedded.area : area;
    items.push({
      kind: 'image',
      id: nextItemId++,
      order,
      x: placed.x,
      y: placed.y,
      w: placed.w,
      h: placed.h,
      src: embedded ? embedded.src : null,
      captureId: null,
      alpha: opacity,
      rotate: box.rotate,
    });
    stats.images++;
  }

  // ─── text ────────────────────────────────────────────────────────────
  // Each element the walk visits holds the text blocks of its own inline
  // content (snapshot_text.mjs); an inline element's text belongs to its block.
  // Text before the element's first block-level child is emitted at the
  // element's visit, at its sequence. Text after a block-level child comes, in
  // tree order, after that child's whole subtree, so it waits until the walk
  // leaves the subtree and takes the sequence half-way between the subtree's
  // last element and the next one: its paint order and its id both follow the
  // document.
  const textLayout = createTextLayout({
    replaced: REPLACED,
    opacityOf,
    backdropInside,
    textColour,
    boxGeometry,
    contentBox,
  });
  // follows element -> its waiting {block, paint} entries, and every entry in the
  // order it was collected (the Map is only ever read by key).
  const waitingText = new Map();
  const waitingInOrder = [];
  // Subtrees the walk is inside whose end releases waiting text: {depth, entries}.
  const openSubtrees = [];

  function pushText(block) {
    items.push({ kind: 'text', id: nextItemId++, ...block });
    stats.texts++;
  }

  function releaseText(entry, lastSeq) {
    if (entry.released) return;
    entry.released = true;
    pushText({ ...entry.block, order: entry.paint.concat([4, 0, lastSeq + 0.5, 1]) });
  }

  // The element's text blocks, as items now or waiting for the subtree they follow.
  function collectText(element, s, paint, seq, walk) {
    const blocks = textLayout.collectTextBlocks(element, s, paint, seq, walk);
    for (let index = 0; index < blocks.length; index++) {
      const { follows, ...block } = blocks[index];
      if (!follows) {
        pushText(block);
        continue;
      }
      const entry = { block, paint, released: false };
      const waiting = waitingText.get(follows);
      if (waiting) waiting.push(entry);
      else waitingText.set(follows, [entry]);
      waitingInOrder.push(entry);
    }
  }

  // The walk is about to visit an element at `depth`, so every open subtree at
  // that depth or deeper ended with the element visited at `lastSeq`.
  function closeSubtrees(depth, lastSeq) {
    while (openSubtrees.length && openSubtrees[openSubtrees.length - 1].depth >= depth) {
      const entries = openSubtrees.pop().entries;
      for (let index = 0; index < entries.length; index++) releaseText(entries[index], lastSeq);
    }
  }

  function openSubtree(element, depth) {
    const entries = waitingText.get(element);
    if (!entries) return;
    waitingText.delete(element);
    openSubtrees.push({ depth, entries });
  }

  // ─── the walk ────────────────────────────────────────────────────────
  // Depth-first from body over an explicit stack, in DOM pre-order. Depth is
  // bounded by WALK_STEP_LIMIT and the elements visited by COLLECTION_ITEM_LIMIT,
  // so a realm lying about the tree cannot make it run forever; meeting either
  // bound is announced, because what lies past it is missing from the slide.
  const stack = [];
  let pushed = 0;

  function pushChildren(element, state) {
    if (state.depth > WALK_STEP_LIMIT) {
      stats.truncated = true;
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'cut at depth ' + WALK_STEP_LIMIT, 'the snapshot walk');
      return;
    }
    const children = elementChildrenOf(element);
    for (let index = children.length - 1; index >= 0; index--) {
      if (pushed >= COLLECTION_ITEM_LIMIT) {
        stats.truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' elements', 'the snapshot walk');
        return;
      }
      stack.push({ element: children[index], state });
      pushed++;
    }
  }

  function visit(element, state, seq) {
    stats.elements++;
    const name = String(dom.tagName(element) || '').toLowerCase();
    const s = window.getComputedStyle(element);
    if (s.display === 'none') return;
    // display: contents generates no box: no paint, no opacity, no context of
    // its own. Its children lay out (and stack) as children of its parent.
    if (s.display === 'contents') {
      pushChildren(element, { ...state, depth: state.depth + 1 });
      return;
    }
    const opacity = state.opacity * opacityOf(s);
    // Opacity applies to the whole subtree, so nothing beneath can show.
    if (!(opacity > 0)) return;
    const replaced = REPLACED.has(name);
    const place = placement(s, state.layoutStyle, state.ctx, state.paint, seq, replaced);
    const frame = frameOf(s, state.frame);
    if (s.visibility === 'visible') {
      const box = boxGeometry(element, element.getBoundingClientRect(), frame);
      if (box) {
        emitBox(s, box, opacity, place.box, element === slideRoot);
        if (replaced) emitReplaced(element, name, s, box, opacity, place.paint.concat([4, 0, seq, 0]));
      }
    }
    if (replaced) return;
    const backdrop = backdropInside(state.backdrop, s);
    const decoration = textLayout.decorationOf(state.decoration, element, s);
    collectText(element, s, place.paint, seq, { opacity, frame, backdrop, decoration });
    pushChildren(element, {
      ctx: place.ctx,
      paint: place.paint,
      opacity,
      layoutStyle: s,
      frame,
      backdrop,
      decoration,
      depth: state.depth + 1,
    });
  }

  const htmlStyle = window.getComputedStyle(html);
  const bodyStyle = window.getComputedStyle(body);
  const background = slideBackground(htmlStyle, bodyStyle);
  const bodyOpacity = opacityOf(htmlStyle) * opacityOf(bodyStyle);
  const bodyFrame = frameOf(bodyStyle, { angle: 0, scaleX: 1, scaleY: 1 });
  // Text starts on the slide's opaque ground. html's and body's backgrounds are
  // that ground already, so only their opacity, if any, opens a group over it.
  const ground = { color: groundColour(htmlStyle, bodyStyle), alpha: 1, group: null };
  const bodyBackdrop = bodyOpacity < 1
    ? { color: TRANSPARENT_LAYER.color, alpha: TRANSPARENT_LAYER.alpha, group: { opacity: bodyOpacity, beneath: ground } }
    : ground;
  const bodyDecoration = textLayout.decorationOf(textLayout.decorationOf(null, html, htmlStyle), body, bodyStyle);
  // Body is the walk's root, so its own inline content is collected here, as
  // sequence 0, ahead of every element the walk visits.
  collectText(body, bodyStyle, [], 0, {
    opacity: bodyOpacity,
    frame: bodyFrame,
    backdrop: bodyBackdrop,
    decoration: bodyDecoration,
  });
  pushChildren(body, {
    ctx: { prefix: [] },
    paint: [],
    opacity: bodyOpacity,
    layoutStyle: bodyStyle,
    frame: bodyFrame,
    backdrop: bodyBackdrop,
    decoration: bodyDecoration,
    depth: 1,
  });
  let seq = 0;
  while (stack.length) {
    const next = stack.pop();
    seq++;
    closeSubtrees(next.state.depth, seq - 1);
    openSubtree(next.element, next.state.depth);
    visit(next.element, next.state, seq);
  }
  closeSubtrees(0, seq);
  // Text after a child the walk never reached (it was cut short) still paints, last.
  for (let index = 0; index < waitingInOrder.length; index++) releaseText(waitingInOrder[index], seq);
  // Line spacing and optical-size tracking, from offscreen probes read once the
  // walk has read every rect (snapshot_text.mjs applyMetrics).
  textLayout.applyMetrics();
  const fonts = textLayout.loadedFonts();
  if (textLayout.truncated()) stats.truncated = true;

  items.sort(compareItems);
  return {
    width: SLIDE_WIDTH,
    height: SLIDE_HEIGHT,
    background,
    items,
    captures,
    fonts,
    reference: { hiddenText: '' },
    stats,
  };
}

export const SNAPSHOT_SOURCE = `
(async function () {
  const DOM_ACCESS_LOG_PREFIX = '[html2pptx]';
${DOM_ACCESS_SOURCE}
${GRADIENT_SOURCE}
${TEXT_SOURCE}
${blendOver.toString()}
  return await (${snapshotPage.toString()})(${JSON.stringify({ slideRootMarker: SLIDE_ROOT_MARKER })});
})()
`;
