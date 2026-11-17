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
//  *   reference: {hiddenText: string},      // the words the page reads (its innerText)
//  *                                         // that the slide does not show, single-spaced:
//  *                                         // clipped, transparent and off-slide text
//  *   stats: {elements, shapes, images, texts, truncated},
//  * }
//  *
//  * Every Item carries:
//  *   id     the item's sequence number in DOM pre-order (stable, deterministic);
//  *   order  its CSS paint-order key, a number[] compared lexicographically.
//  *
//  * Item =
//  *  {kind:'shape', x,y,w,h, geometry:'rect'|'roundRect'|'ellipse'|'path', radius,
//  *   fill:{color:'RRGGBB', alpha}|null, line:{color, alpha, widthPx, dash:'solid'|'dash'|'dot'}|null,
//  *   shadow:{color, alpha, blurPx, offsetPx, angle}|null, rotate,
//  *   path:[{x,y}[]], closed:boolean}   (path and closed for geometry 'path' only: the
//  *   polylines it draws, in px from its top left, each closed or each open; a
//  *   shape a clip cuts that is not a plain rect, see pushClippedShape)
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

  // A box ({x, y, w, h, rotate}) as bounds {left, top, right, bottom}: its
  // axis-aligned extent on the slide, the turned box's when it is rotated.
  function boundsOf(box) {
    if (!box.rotate) return { left: box.x, top: box.y, right: box.x + box.w, bottom: box.y + box.h };
    const radians = box.rotate * Math.PI / 180;
    const halfWidth = (Math.abs(box.w * Math.cos(radians)) + Math.abs(box.h * Math.sin(radians))) / 2;
    const halfHeight = (Math.abs(box.w * Math.sin(radians)) + Math.abs(box.h * Math.cos(radians))) / 2;
    const centreX = box.x + box.w / 2;
    const centreY = box.y + box.h / 2;
    return { left: centreX - halfWidth, top: centreY - halfHeight, right: centreX + halfWidth, bottom: centreY + halfHeight };
  }

  function boundsOfRect(rect) {
    const left = Number(rect.left);
    const top = Number(rect.top);
    return { left, top, right: left + Number(rect.width), bottom: top + Number(rect.height) };
  }

  // ─── visibility and clipping ─────────────────────────────────────────
  // Spec §3 Visibility. A clip is bounds {left, top, right, bottom} in slide
  // px; an axis nothing clips runs to ±Infinity. The walk carries Clips =
  // {tree, flow, absolute, fixed} down the tree:
  //   tree      the intersection of every ancestor's clip: rect() and
  //             clip-path: inset(), each of which clips its element and
  //             everything it holds;
  //   flow      what clips an in-flow box: the slide rect, narrowed by the
  //             padding box of each overflow box its containing-block chain
  //             passes through;
  //   absolute  the same for an absolutely positioned box: the flow clip of its
  //             containing block, so an overflow box between that block and the
  //             box does not clip it (CSS 2.1 §11.1.1);
  //   fixed     the same for a fixed box, whose containing block is the
  //             viewport, the slide, unless an ancestor makes one (containsFixed).
  // What a clip shows of a box, a picture or a word is shownPart. What it shows
  // under MINIMUM_VISIBLE_PX of, along an axis it cuts, is hidden: the
  // visually-hidden pattern clips to 1 px.
  const SLIDE_CLIP = { left: 0, top: 0, right: SLIDE_WIDTH, bottom: SLIDE_HEIGHT };
  const NO_CLIP = { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };
  const VIEWPORT_CLIPS = { tree: NO_CLIP, flow: SLIDE_CLIP, absolute: SLIDE_CLIP, fixed: SLIDE_CLIP };
  const MINIMUM_VISIBLE_PX = 2;
  // A clip edge within this of an edge of what it clips cuts nothing (layout rounding).
  const CUT_EPSILON_PX = 0.01;
  // overflow applies to block, flex and grid containers: not to an inline box,
  // nor to a table's rows, columns and their groups.
  const NO_OVERFLOW_DISPLAY = /^(inline|contents|none|table-(row|row-group|header-group|footer-group|column|column-group))$/;
  // Chrome computes clip: rect(0 0 0 0) as "rect(0px, 0px, 0px, 0px)", keeping each auto.
  const CLIP_RECT = /^rect\(\s*([^,\s]+)[\s,]+([^,\s]+)[\s,]+([^,\s]+)[\s,]+([^,\s)]+)\s*\)$/;
  const CLIP_PATH_INSET = /^inset\(([^)]*)\)/;
  const REFERENCE_BOX = /\b(margin-box|border-box|padding-box|content-box|fill-box|stroke-box|view-box)\b/;

  function intersectClips(a, b) {
    return {
      left: Math.max(a.left, b.left),
      top: Math.max(a.top, b.top),
      right: Math.min(a.right, b.right),
      bottom: Math.min(a.bottom, b.bottom),
    };
  }

  function clipIsEmpty(clip) {
    return !(clip.right > clip.left && clip.bottom > clip.top);
  }

  // What a clip from clipStart to clipEnd shows of [start, end] on one axis:
  // {from, to, cut}, or null when it cuts it and shows under MINIMUM_VISIBLE_PX.
  function shownSpan(start, end, clipStart, clipEnd) {
    const cutsStart = clipStart - start > CUT_EPSILON_PX;
    const cutsEnd = end - clipEnd > CUT_EPSILON_PX;
    if (!cutsStart && !cutsEnd) return { from: start, to: end, cut: false };
    const from = cutsStart ? clipStart : start;
    const to = cutsEnd ? clipEnd : end;
    return to - from >= MINIMUM_VISIBLE_PX ? { from, to, cut: true } : null;
  }

  // shownPart(bounds, clip) -> {left, top, right, bottom, cut} | null: what the
  // clip shows of `bounds`, `cut` when it takes any of it away. An axis the clip
  // does not cut keeps its extent, so a 1 px rule the clip only shortens still
  // shows. An empty clip shows nothing.
  function shownPart(bounds, clip) {
    if (clipIsEmpty(clip)) return null;
    const x = shownSpan(bounds.left, bounds.right, clip.left, clip.right);
    const y = x && shownSpan(bounds.top, bounds.bottom, clip.top, clip.bottom);
    if (!y) return null;
    return { left: x.from, top: y.from, right: x.to, bottom: y.to, cut: x.cut || y.cut };
  }

  function clipsOverflow(s) {
    return !NO_OVERFLOW_DISPLAY.test(String(s.display)) && (s.overflowX !== 'visible' || s.overflowY !== 'visible');
  }

  // An overflow box clips what it holds to its padding box (CSS Overflow 3, the
  // overflow clip edge), on each axis whose overflow is not visible: hidden,
  // clip, auto and scroll all clip. Under a rotation the bounds hold the turned
  // box and are the clip, which hides nothing the box shows.
  function overflowClipOf(s, bounds, frame) {
    const clipsX = s.overflowX !== 'visible';
    const clipsY = s.overflowY !== 'visible';
    const border = (side, scale) => (frame.angle ? 0 : (parseFloat(s['border' + side + 'Width']) || 0) * scale);
    return {
      left: clipsX ? bounds.left + border('Left', frame.scaleX) : -Infinity,
      top: clipsY ? bounds.top + border('Top', frame.scaleY) : -Infinity,
      right: clipsX ? bounds.right - border('Right', frame.scaleX) : Infinity,
      bottom: clipsY ? bounds.bottom - border('Bottom', frame.scaleY) : Infinity,
    };
  }

  function hasClipRect(s) {
    return (s.position === 'absolute' || s.position === 'fixed') && Boolean(s.clip) && s.clip !== 'auto';
  }

  function hasOwnClip(s) {
    return hasClipRect(s) || (Boolean(s.clipPath) && s.clipPath !== 'none');
  }

  // clip: rect(top, right, bottom, left) on an absolutely positioned box:
  // offsets from its border box's top left corner, each auto that box's own
  // edge (CSS 2.1 §11.1.2). Under a rotation only a clip with no area is
  // read: it hides the box in any frame.
  function clipRectOf(s, bounds, frame) {
    const match = hasClipRect(s) ? CLIP_RECT.exec(String(s.clip)) : null;
    if (!match) return NO_CLIP;
    const offset = (value, auto, scale) => (value === 'auto' ? auto : (parseFloat(value) || 0) * scale);
    const clip = {
      left: bounds.left + offset(match[4], 0, frame.scaleX),
      top: bounds.top + offset(match[1], 0, frame.scaleY),
      right: bounds.left + offset(match[2], bounds.right - bounds.left, frame.scaleX),
      bottom: bounds.top + offset(match[3], bounds.bottom - bounds.top, frame.scaleY),
    };
    return frame.angle && !clipIsEmpty(clip) ? NO_CLIP : clip;
  }

  // The box a clip-path is drawn in: the border box unless it names another
  // (an SVG box is the border box for an HTML element).
  function referenceBox(s, bounds, frame, name) {
    const edge = (side, kind, scale) => (parseFloat(s[kind === 'border' ? 'border' + side + 'Width' : kind + side]) || 0) * scale;
    const inward = { Left: 0, Top: 0, Right: 0, Bottom: 0 };
    const sides = ['Left', 'Top', 'Right', 'Bottom'];
    for (let index = 0; index < sides.length; index++) {
      const side = sides[index];
      const scale = side === 'Left' || side === 'Right' ? frame.scaleX : frame.scaleY;
      if (name === 'margin-box') inward[side] = -edge(side, 'margin', scale);
      if (name === 'padding-box' || name === 'content-box') inward[side] = edge(side, 'border', scale);
      if (name === 'content-box') inward[side] += edge(side, 'padding', scale);
    }
    return {
      left: bounds.left + inward.Left,
      top: bounds.top + inward.Top,
      right: bounds.right - inward.Right,
      bottom: bounds.bottom - inward.Bottom,
    };
  }

  // clip-path: inset(top right bottom left [round …]) [box], or a box alone:
  // the element and all it holds are clipped to its reference box less the
  // insets, a percentage taken of the box's width for left and right and of
  // its height for top and bottom. Round corners are not read: the clip is the
  // rect around them. No other shape is read: it clips nothing here.
  function clipPathOf(s, bounds, frame) {
    const value = String(s.clipPath || 'none').trim();
    const inset = CLIP_PATH_INSET.exec(value);
    const rest = inset ? value.slice(inset[0].length).trim() : value;
    const named = REFERENCE_BOX.exec(rest);
    if (!inset && !(named && rest === named[0])) return NO_CLIP;
    const box = referenceBox(s, bounds, frame, named ? named[1] : 'border-box');
    const lengths = inset ? inset[1].split(/\s+round\s+/)[0].trim().split(/\s+/) : ['0px'];
    const top = lengths[0];
    const right = lengths.length > 1 ? lengths[1] : top;
    const bottom = lengths.length > 2 ? lengths[2] : top;
    const left = lengths.length > 3 ? lengths[3] : right;
    const width = box.right - box.left;
    const height = box.bottom - box.top;
    const clip = {
      left: box.left + lengthAgainst(left, width, frame.scaleX),
      top: box.top + lengthAgainst(top, height, frame.scaleY),
      right: box.right - lengthAgainst(right, width, frame.scaleX),
      bottom: box.bottom - lengthAgainst(bottom, height, frame.scaleY),
    };
    return frame.angle && !clipIsEmpty(clip) ? NO_CLIP : clip;
  }

  // Whether an element is the containing block of the fixed boxes it holds,
  // as a transform, a filter or containment makes it; else the viewport is.
  function containsFixed(s) {
    return s.transform !== 'none' || (Boolean(s.perspective) && s.perspective !== 'none') ||
      (Boolean(s.rotate) && s.rotate !== 'none') || (Boolean(s.scale) && s.scale !== 'none') ||
      (Boolean(s.translate) && s.translate !== 'none') ||
      s.filter !== 'none' || (Boolean(s.backdropFilter) && s.backdropFilter !== 'none') ||
      /\b(paint|layout|strict|content)\b/.test(s.contain || '') ||
      /\bsize\b/.test(s.containerType || '') ||
      /\b(transform|perspective|filter|translate|rotate|scale)\b/.test(s.willChange || '');
  }

  // ... and of the absolutely positioned ones, as every positioned box is too.
  function containsAbsolute(s) {
    return s.position !== 'static' || containsFixed(s);
  }

  // clipsOf(clips, element, s, frame, overflowToViewport) -> {rect, box, content, children}
  //   clips     the Clips its parent hands down;
  //   overflowToViewport  its overflow is the viewport's (html's, or body's when
  //             html's is visible), where the slide rect already clips;
  //   rect      its getBoundingClientRect() when a clip of its own needed it, else null;
  //   box       what clips its own background, border and picture;
  //   content   what clips its own inline content: its text and inline boxes;
  //   children  the Clips its child elements inherit.
  // Its overflow clips what it holds, not its own box; its clip and clip-path clip both.
  function clipsOf(clips, element, s, frame, overflowToViewport) {
    const overflows = !overflowToViewport && clipsOverflow(s);
    const own = hasOwnClip(s);
    const rect = overflows || own ? element.getBoundingClientRect() : null;
    const bounds = rect ? boundsOfRect(rect) : null;
    const tree = own ? intersectClips(clips.tree, intersectClips(clipRectOf(s, bounds, frame), clipPathOf(s, bounds, frame))) : clips.tree;
    const outer = s.position === 'absolute' ? clips.absolute : s.position === 'fixed' ? clips.fixed : clips.flow;
    const flow = overflows ? intersectClips(outer, overflowClipOf(s, bounds, frame)) : outer;
    return {
      rect,
      box: intersectClips(outer, tree),
      content: intersectClips(flow, tree),
      children: {
        tree,
        flow,
        absolute: containsAbsolute(s) ? flow : clips.absolute,
        fixed: containsFixed(s) ? flow : clips.fixed,
      },
    };
  }

  // The clip of an inline element's content, given the clip of the text around
  // it: its own clip-path narrows it. An inline box has no overflow clip, and
  // clip needs an absolutely positioned box.
  function inlineClip(clip, element, s, frame) {
    if (!hasOwnClip(s)) return clip;
    const bounds = boundsOfRect(element.getBoundingClientRect());
    return intersectClips(clip, intersectClips(clipRectOf(s, bounds, frame), clipPathOf(s, bounds, frame)));
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

  // Whether an element's box paints anything emitBox draws: a fill, a uniform
  // border or an outer shadow, at its cumulative opacity. Its geometry changes
  // none of the three, so an untransformed unit box stands in for it.
  const UNIT_BOX = { scale: 1, rotate: null };
  function paintsBox(s, opacity) {
    return Boolean((!clipsToText(s) && paintedColour(s.backgroundColor, opacity)) ||
      uniformBorder(s, opacity, UNIT_BOX.scale) || outerShadow(s.boxShadow, opacity, UNIT_BOX));
  }

  // A painted box becomes a shape: background colour, uniform border and outer
  // shadow, cut to its clip. The slide root's ground is the slide background
  // (BG_TRANSFER put it on body), so its fill and shadow are never painted a
  // second time here.
  function emitBox(s, box, opacity, order, isSlideRoot, clip) {
    const fill = isSlideRoot || clipsToText(s) ? null : paintedColour(s.backgroundColor, opacity);
    let line = uniformBorder(s, opacity, box.scale);
    const shadow = isSlideRoot ? null : outerShadow(s.boxShadow, opacity, box);
    if (!fill && !line && !shadow) return;
    const shown = shownPart(boundsOf(box), clip);
    if (!shown) return;
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
    const shape = {
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
    };
    if (!shown.cut) {
      pushShape(shape);
    } else if (geometry === 'rect' && !box.rotate && !line) {
      // A plain rect the clip cuts is the rect it shows (no line, so no inset).
      pushShape({
        ...shape,
        x: shown.left,
        y: shown.top,
        w: shown.right - shown.left,
        h: shown.bottom - shown.top,
      });
    } else {
      pushClippedShape(shape, clip);
    }
  }

  function pushShape(shape) {
    items.push({
      kind: 'shape',
      id: nextItemId++,
      order: shape.order,
      x: shape.x,
      y: shape.y,
      w: shape.w,
      h: shape.h,
      geometry: shape.geometry,
      radius: shape.radius,
      fill: shape.fill,
      line: shape.line,
      shadow: shape.shadow,
      rotate: shape.rotate,
    });
    stats.shapes++;
  }

  // ─── clipped shapes ──────────────────────────────────────────────────
  // A shape a clip cuts that is not a plain rect (round corners, an ellipse, a
  // rotation or an outline) is drawn as the part of it the clip shows: its
  // outline as a polygon (outlineOf), cut to the clip. The cut polygon is one
  // closed path holding the fill and the shadow. The line runs only along what
  // is left of the shape's own outline, never along the cut, as the browser
  // draws a clipped border: a second path, open where the clip cuts it, with
  // no fill, painted over the first.
  // Arcs become polygons that stray from them by at most ARC_TOLERANCE_PX.
  const ARC_TOLERANCE_PX = 0.05;
  const ARC_STEP_LIMIT = 64;
  // A path's box keeps at least this extent, so a straight one still has a frame to scale.
  const PATH_MIN_EXTENT_PX = 0.01;
  const SAME_POINT_PX = 1e-6;

  // The segments that stand for a quarter arc of `radius`.
  function arcSteps(radius) {
    if (!(radius > ARC_TOLERANCE_PX)) return 1;
    const step = 2 * Math.acos(1 - ARC_TOLERANCE_PX / radius);
    return Math.max(2, Math.min(ARC_STEP_LIMIT, Math.ceil(Math.PI / 2 / step)));
  }

  // A shape's outline as a polygon of slide px, clockwise from its left: each
  // corner's arc for a roundRect, the ellipse's four quarters, turned about the
  // centre by its rotation.
  function outlineOf(shape) {
    const points = [];
    const centreX = shape.x + shape.w / 2;
    const centreY = shape.y + shape.h / 2;
    // A quarter arc about (x, y) from `start` radians (clockwise, from 3 o'clock).
    const arc = (x, y, radiusX, radiusY, start) => {
      const steps = arcSteps(Math.max(radiusX, radiusY));
      for (let step = 0; step <= steps; step++) {
        const angle = start + (Math.PI / 2) * (step / steps);
        points.push({ x: x + radiusX * Math.cos(angle), y: y + radiusY * Math.sin(angle) });
      }
    };
    const right = shape.x + shape.w;
    const bottom = shape.y + shape.h;
    if (shape.geometry === 'ellipse') {
      for (let quarter = 0; quarter < 4; quarter++) {
        arc(centreX, centreY, shape.w / 2, shape.h / 2, Math.PI * (1 + quarter / 2));
      }
    } else if (shape.geometry === 'roundRect') {
      const radius = Math.min(shape.radius, shape.w / 2, shape.h / 2);
      arc(shape.x + radius, shape.y + radius, radius, radius, Math.PI);
      arc(right - radius, shape.y + radius, radius, radius, Math.PI * 1.5);
      arc(right - radius, bottom - radius, radius, radius, 0);
      arc(shape.x + radius, bottom - radius, radius, radius, Math.PI * 0.5);
    } else {
      points.push({ x: shape.x, y: bottom }, { x: shape.x, y: shape.y }, { x: right, y: shape.y }, { x: right, y: bottom });
    }
    const outline = [];
    const radians = (shape.rotate || 0) * Math.PI / 180;
    for (let index = 0; index < points.length; index++) {
      const dx = points[index].x - centreX;
      const dy = points[index].y - centreY;
      const point = radians
        ? { x: centreX + dx * Math.cos(radians) - dy * Math.sin(radians), y: centreY + dx * Math.sin(radians) + dy * Math.cos(radians) }
        : points[index];
      const previous = outline.length ? outline[outline.length - 1] : null;
      if (!previous || Math.abs(previous.x - point.x) > SAME_POINT_PX || Math.abs(previous.y - point.y) > SAME_POINT_PX) {
        outline.push(point);
      }
    }
    const first = outline[0];
    const last = outline[outline.length - 1];
    if (outline.length > 1 && Math.abs(first.x - last.x) <= SAME_POINT_PX && Math.abs(first.y - last.y) <= SAME_POINT_PX) {
      outline.pop();
    }
    return outline;
  }

  // The four edges of a clip; an edge at infinity cuts nothing.
  function clipEdges(clip) {
    return [
      { axis: 'x', bound: clip.left, keepsBelow: false },
      { axis: 'x', bound: clip.right, keepsBelow: true },
      { axis: 'y', bound: clip.top, keepsBelow: false },
      { axis: 'y', bound: clip.bottom, keepsBelow: true },
    ];
  }

  function crossing(from, to, axis, bound) {
    const fraction = (bound - from[axis]) / (to[axis] - from[axis]);
    const point = { x: from.x + (to.x - from.x) * fraction, y: from.y + (to.y - from.y) * fraction };
    point[axis] = bound;
    return point;
  }

  // The convex polygon `points` cut to the clip, one clip edge at a time
  // (Sutherland-Hodgman).
  function clipPolygon(points, clip) {
    let polygon = points;
    const edges = clipEdges(clip);
    for (let edge = 0; edge < edges.length && polygon.length; edge++) {
      const axis = edges[edge].axis;
      const bound = edges[edge].bound;
      const keepsBelow = edges[edge].keepsBelow;
      if (!Number.isFinite(bound)) continue;
      const inside = (point) => (keepsBelow ? point[axis] <= bound : point[axis] >= bound);
      const kept = [];
      for (let index = 0; index < polygon.length; index++) {
        const current = polygon[index];
        const previous = polygon[(index + polygon.length - 1) % polygon.length];
        if (inside(current) !== inside(previous)) kept.push(crossing(previous, current, axis, bound));
        if (inside(current)) kept.push(current);
      }
      polygon = kept;
    }
    return polygon;
  }

  // What the clip shows of the segment from -> to (Liang-Barsky):
  // {from, to, cutsStart, cutsEnd}, or null for none of it.
  function clipSegment(from, to, clip) {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const sides = [
      { direction: -dx, room: from.x - clip.left },
      { direction: dx, room: clip.right - from.x },
      { direction: -dy, room: from.y - clip.top },
      { direction: dy, room: clip.bottom - from.y },
    ];
    let enter = 0;
    let leave = 1;
    for (let index = 0; index < sides.length; index++) {
      const direction = sides[index].direction;
      const room = sides[index].room;
      if (direction === 0) {
        if (room < 0) return null;
        continue;
      }
      const at = room / direction;
      if (direction < 0) {
        if (at > leave) return null;
        if (at > enter) enter = at;
      } else {
        if (at < enter) return null;
        if (at < leave) leave = at;
      }
    }
    if (!(leave > enter)) return null;
    const point = (at) => ({ x: from.x + dx * at, y: from.y + dy * at });
    return { from: enter > 0 ? point(enter) : from, to: leave < 1 ? point(leave) : to, cutsStart: enter > 0, cutsEnd: leave < 1 };
  }

  // What the clip shows of the closed outline `points`, as polylines in order:
  // {pieces, closed}. `closed` when it cuts none of it: then the one piece is
  // the outline itself. Otherwise each piece is open, ending where it is cut.
  function clipOutline(points, clip) {
    const pieces = [];
    let piece = null;
    let cut = false;
    let leavesFirstUncut = false;
    let reachesFirstUncut = false;
    for (let index = 0; index < points.length; index++) {
      const segment = clipSegment(points[index], points[(index + 1) % points.length], clip);
      if (!segment || segment.cutsStart) {
        piece = null;
        cut = true;
      }
      if (!segment) continue;
      if (index === 0) leavesFirstUncut = !segment.cutsStart;
      if (index === points.length - 1) reachesFirstUncut = !segment.cutsEnd;
      if (!piece) {
        piece = [segment.from];
        pieces.push(piece);
      }
      piece.push(segment.to);
      if (segment.cutsEnd) {
        piece = null;
        cut = true;
      }
    }
    if (!cut) return { pieces: [points], closed: true };
    // The outline is closed: the piece that reaches its first point carries on into the one leaving it.
    if (leavesFirstUncut && reachesFirstUncut && pieces.length > 1) {
      const first = pieces.shift();
      const last = pieces[pieces.length - 1];
      for (let index = 1; index < first.length; index++) last.push(first[index]);
    }
    return { pieces, closed: false };
  }

  function pushClippedShape(shape, clip) {
    const outline = outlineOf(shape);
    if (shape.fill || shape.shadow) {
      const region = clipPolygon(outline, clip);
      if (region.length >= 3) pushPath(shape.order, [region], true, shape.fill, null, shape.shadow);
    }
    if (shape.line) {
      // Widened by the rounding a clip edge may differ by, so an outline that
      // only touches the clip is not cut into pieces.
      const visible = clipOutline(outline, {
        left: clip.left - CUT_EPSILON_PX,
        top: clip.top - CUT_EPSILON_PX,
        right: clip.right + CUT_EPSILON_PX,
        bottom: clip.bottom + CUT_EPSILON_PX,
      });
      if (visible.pieces.length) pushPath(shape.order, visible.pieces, visible.closed, null, shape.line, null);
    }
  }

  // A path item over `polylines` (slide px), placed at their bounds.
  function pushPath(order, polylines, closed, fill, line, shadow) {
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (let index = 0; index < polylines.length; index++) {
      for (let point = 0; point < polylines[index].length; point++) {
        left = Math.min(left, polylines[index][point].x);
        top = Math.min(top, polylines[index][point].y);
        right = Math.max(right, polylines[index][point].x);
        bottom = Math.max(bottom, polylines[index][point].y);
      }
    }
    const path = [];
    for (let index = 0; index < polylines.length; index++) {
      const relative = [];
      for (let point = 0; point < polylines[index].length; point++) {
        relative.push({ x: polylines[index][point].x - left, y: polylines[index][point].y - top });
      }
      path.push(relative);
    }
    items.push({
      kind: 'shape',
      id: nextItemId++,
      order,
      x: left,
      y: top,
      w: Math.max(right - left, PATH_MIN_EXTENT_PX),
      h: Math.max(bottom - top, PATH_MIN_EXTENT_PX),
      geometry: 'path',
      radius: 0,
      fill,
      line,
      shadow,
      rotate: null,
      path,
      closed,
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

  // A picture its clip hides is not on the slide; one it only cuts is drawn whole.
  function emitReplaced(element, name, s, box, opacity, order, clip) {
    const area = contentBox(s, box);
    if (!area) return;
    const embedded = name === 'img' ? embeddedImage(element, s, area) : null;
    const placed = embedded ? embedded.area : area;
    if (!shownPart(boundsOf({ x: placed.x, y: placed.y, w: placed.w, h: placed.h, rotate: box.rotate }), clip)) return;
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
  // Each element the walk visits holds the inline groups of its own inline
  // content (snapshot_text.mjs): each run's decorations (the boxes of its
  // inline elements, per line fragment) and text blocks. An inline element's
  // text and box belong to its block. A group before the element's first
  // block-level child is emitted at the element's visit, at its sequence. A
  // group after a block-level child comes, in tree order, after that child's
  // whole subtree, so it waits until the walk leaves the subtree and takes the
  // sequence half-way between the subtree's last element and the next one:
  // its paint order and its ids both follow the document.
  const textLayout = createTextLayout({
    replaced: REPLACED,
    opacityOf,
    backdropInside,
    textColour,
    boxGeometry,
    contentBox,
    paintsBox,
    inlineClip,
    shows: (bounds, clip) => shownPart(bounds, clip) !== null,
  });
  // follows element -> its waiting {group, paint} entries, and every entry in the
  // order it was collected (the Map is only ever read by key).
  const waitingText = new Map();
  const waitingInOrder = [];
  // Subtrees the walk is inside whose end releases waiting text: {depth, entries}.
  const openSubtrees = [];

  function pushText(block) {
    items.push({ kind: 'text', id: nextItemId++, ...block });
    stats.texts++;
  }

  // One group at its block's place in the inline content layer (4) of `paint`:
  // each decoration at paint + [4, 0, blockSeq, 0, elSeq], every fragment of
  // it, then each text block at paint + [4, 0, blockSeq, 1]. So a block's
  // decorations paint over every block background of their stacking context
  // and under that block's own text, as CSS paints inline content (CSS 2.1
  // Appendix E, step 7 after step 4). elSeq is the decoration's place in DOM
  // order among its block's decorations, which orders them as the walk's own
  // sequence numbers would: both follow the document, and no other key of the
  // slide compares with it.
  function pushGroup(group, paint, blockSeq) {
    for (let index = 0; index < group.decorations.length; index++) {
      const decoration = group.decorations[index];
      for (let fragment = 0; fragment < decoration.boxes.length; fragment++) {
        emitBox(decoration.style, decoration.boxes[fragment], decoration.opacity,
          paint.concat([4, 0, blockSeq, 0, index]), false, decoration.clip);
      }
    }
    for (let index = 0; index < group.blocks.length; index++) {
      pushText({ ...group.blocks[index], order: paint.concat([4, 0, blockSeq, 1]) });
    }
  }

  function releaseText(entry, lastSeq) {
    if (entry.released) return;
    entry.released = true;
    pushGroup(entry.group, entry.paint, lastSeq + 0.5);
  }

  // The element's inline groups, as items now or waiting for the subtree they follow.
  function collectText(element, s, paint, seq, walk) {
    const groups = textLayout.collectTextBlocks(element, s, walk);
    for (let index = 0; index < groups.length; index++) {
      const group = groups[index];
      if (!group.follows) {
        pushGroup(group, paint, seq);
        continue;
      }
      const entry = { group, paint, released: false };
      const waiting = waitingText.get(group.follows);
      if (waiting) waiting.push(entry);
      else waitingText.set(group.follows, [entry]);
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

  // A subtree that shows nothing still holds text the page reads (its
  // innerText, which a screen reader and the text-loss oracle read), so it is
  // the slide's hidden text. An inline box's text belongs to its block's
  // layout, which records it there.
  function recordHiddenSubtree(element, name, s) {
    if (textLayout.isInlineBox(name, s)) return;
    let text;
    try {
      text = String(dom.innerText(element) || '');
    } catch (e) {
      // Not an HTML element (an <svg>): its text is drawn in its picture, not set as text.
      return;
    }
    textLayout.recordHiddenText(text);
  }

  function visit(element, state, seq) {
    stats.elements++;
    const name = String(dom.tagName(element) || '').toLowerCase();
    const s = window.getComputedStyle(element);
    if (s.display === 'none') return;
    // display: contents generates no box: no paint, no opacity, no clip, no
    // context of its own. Its children lay out (and stack) as children of its parent.
    if (s.display === 'contents') {
      pushChildren(element, { ...state, depth: state.depth + 1 });
      return;
    }
    const opacity = state.opacity * opacityOf(s);
    const frame = frameOf(s, state.frame);
    const clips = clipsOf(state.clips, element, s, frame, false);
    // Opacity applies to the whole subtree, and so do clip and clip-path: when
    // either leaves nothing, nothing beneath can show. An overflow clip does
    // not prune: a box positioned outside it may hold what escapes it.
    if (!(opacity > 0) || clipIsEmpty(clips.children.tree)) {
      recordHiddenSubtree(element, name, s);
      return;
    }
    const replaced = REPLACED.has(name);
    const place = placement(s, state.layoutStyle, state.ctx, state.paint, seq, replaced);
    // An inline box paints one box per line fragment, under its block's text:
    // the text layout collects it with that block (pushGroup), so its bounding
    // rect, which spans every line it is on, is never a box of its own.
    if (s.visibility === 'visible' && !textLayout.isInlineBox(name, s)) {
      const box = boxGeometry(element, clips.rect || element.getBoundingClientRect(), frame);
      if (box) {
        emitBox(s, box, opacity, place.box, element === slideRoot, clips.box);
        if (replaced) emitReplaced(element, name, s, box, opacity, place.paint.concat([4, 0, seq, 0]), clips.box);
      }
    }
    if (replaced) return;
    const backdrop = backdropInside(state.backdrop, s);
    const decoration = textLayout.decorationOf(state.decoration, element, s);
    collectText(element, s, place.paint, seq, { opacity, frame, backdrop, decoration, clip: clips.content });
    pushChildren(element, {
      ctx: place.ctx,
      paint: place.paint,
      opacity,
      layoutStyle: s,
      frame,
      backdrop,
      decoration,
      clips: clips.children,
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
  // The viewport is the slide, and it clips everything, off-slide content
  // included. html's overflow is the viewport's, and so is body's while html's
  // is visible (CSS Overflow 3, overflow propagation), so neither clips again.
  const htmlClips = clipsOf(VIEWPORT_CLIPS, html, htmlStyle, { angle: 0, scaleX: 1, scaleY: 1, scale: 1 }, true);
  const bodyOverflowToViewport = htmlStyle.overflowX === 'visible' && htmlStyle.overflowY === 'visible';
  const bodyClips = clipsOf(htmlClips.children, body, bodyStyle, bodyFrame, bodyOverflowToViewport);
  // Body is the walk's root, so its own inline content is collected here, as
  // sequence 0, ahead of every element the walk visits.
  collectText(body, bodyStyle, [], 0, {
    opacity: bodyOpacity,
    frame: bodyFrame,
    backdrop: bodyBackdrop,
    decoration: bodyDecoration,
    clip: bodyClips.content,
  });
  pushChildren(body, {
    ctx: { prefix: [] },
    paint: [],
    opacity: bodyOpacity,
    layoutStyle: bodyStyle,
    frame: bodyFrame,
    backdrop: bodyBackdrop,
    decoration: bodyDecoration,
    clips: bodyClips.children,
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
    reference: { hiddenText: textLayout.hiddenText() },
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
