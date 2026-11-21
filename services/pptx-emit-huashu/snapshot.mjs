// The snapshot: one read-only page.evaluate that turns the slide the browser
// rendered into a JSON slide model, which emit_model.cjs writes to pptxgenjs.
//
// It reads; it does not rewrite. Layout is taken exactly as the browser laid it
// out (getComputedStyle and getBoundingClientRect per element), so nothing the
// export emits can drift from what the user saw because a pass moved it first.
// Its one lasting write comes after the last read: it names its capture
// targets with an attribute (which moves nothing) for capture.cjs.
// Every DOM traversal goes through DOM_ACCESS_SOURCE (pristine-realm accessors,
// bounded collections), because slide script runs in this page before we do.
//
// Pseudo-elements (::before, ::after, a list item's ::marker) are no DOM
// nodes. pseudo.mjs reads them from Node through the DevTools protocol, and
// SNAPSHOT_SOURCE is a function of what it read (PseudoData): each ::before
// and ::after is walked and laid out as its host's first child or last, and
// each ::marker is drawn when its item is (emitMarker).
//
// Tables. A <table> the slide shows whole, as a grid an a:tbl can draw, is one
// table item (snapshot_table.mjs), which holds its cells' fills, borders and
// text; the walk still visits what its cells hold (nativeTable).
//
// /**
//  * SlideModel = {
//  *   width, height,                       // CSS px; the slide is 1280x720
//  *   background: {color: 'RRGGBB'} | {image: 'data:image/…;base64,…'},
//  *   items: Item[],                        // sorted back to front, by `order` then `id`
//  *   captures: Capture[],
//  *   fonts: {'<family>': number[]},        // the weights (100..900) of its faces in
//  *                                         // document.fonts that loaded: the page's webfonts
//  *   italicFonts: {'<family>': number[]},  // the same, of its italic and oblique faces alone
//  *   reference: {hiddenText: string},      // the words the page reads (its innerText)
//  *                                         // that the slide does not show whole, each
//  *                                         // whole, single-spaced: clipped, transparent,
//  *                                         // off-slide and ellipsis-cut text
//  *   stats: {elements, pseudoElements, shapes, lines, images, texts, tables, truncated},
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
//  *  {kind:'line', x1,y1,x2,y2, color, alpha, widthPx, dash}   (one painted side of a
//  *   border that differs between sides, along its centre line; see pushSideLines)
//  *  {kind:'image', x,y,w,h, src:'data:…'|null, captureId:'c<n>'|null, alpha, rotate}
//  *  {kind:'text', x,y,w,h, rotate:number|null, wrap:boolean, align:'left'|'center'|'right',
//  *   rtl:boolean, paragraphs:[{sizePx, lineHeightPx:number|null, ascentPx:number|null,
//  *   lines:[{runs:Run[], growthPx?}]}], inset?:{left, top, right, bottom}}
//  *   (one text block; snapshot_text.mjs documents Run, lines, the metrics and the
//  *   geometry. A turned block, the text of a turn root (TurnedText), carries
//  *   rotate and inset: its box is the root's layout box, its text inside it;
//  *   a piece of a turned root a gap cuts, and a turned list marker, carry
//  *   rotate alone: a box turned about its centre, whose own top is its
//  *   first line's glyph top.)
//  *  {kind:'table', x,y, colWidths, rowHeights, cells}
//  *   (one native table; snapshot_table.mjs documents TableItem and TableCell)
//  *
//  * Capture = {id, x,y,w,h, mode:'subtree'|'box', selector:'[data-tellr-capture="c<n>"]',
//  *   pseudo:null|'before'|'after'|'marker', hiddenWithin:boolean,
//  *   paint:{borderColors:string[4], boxShadow:string}|null, bordersHidden:boolean}
//  *   (the picture's rect, which its image item shares; selector, the target
//  *   element, or for a pseudo-element target (pseudo set) its host, named by
//  *   the host attribute '[data-tellr-pseudo-host="<n>"]'; hiddenWithin when
//  *   descendants of a subtree target carry data-tellr-capture-hidden; paint,
//  *   for a box target, its computed border colours and shadow; bordersHidden
//  *   for a box target whose borders, and those of all it holds, the picture
//  *   leaves out: a collapsed native table, whose grid draws them; capture.cjs
//  *   reads them. `failed` when the target could not be named.)
//  *
//  * Units: CSS px on the slide. `alpha` is 0..1 and already includes the cumulative
//  * opacity of the element and its ancestors. A shape's box is where its outline's
//  * centre runs, so a bordered box is inset by half the border width, and `radius`
//  * is the radius of that centre line. `rotate` is degrees clockwise, or null.
//  * An image's `alpha` is the opacity the emitter still has to apply: 1 for a
//  * capture, whose pixels already carry it.
//  */

import { CAPTURE_ATTRIBUTE, HIDDEN_ATTRIBUTE } from './capture.cjs';
import { COVERAGE_ADVANCE_EM, COVERAGE_FONT_BYTES, COVERAGE_FONT_FAMILY } from './coverage_font.mjs';
import { DOM_ACCESS_SOURCE } from './dom_access.mjs';
import { blendOver } from './emit_typography.cjs';
import { GRADIENT_SOURCE } from './gradient.mjs';
import { SLIDE_ROOT_MARKER } from './preprocess.mjs';
import { PSEUDO_HOST_ATTRIBUTE } from './pseudo.mjs';
import { BORDERS_SOURCE } from './snapshot_borders.mjs';
import { TABLE_SOURCE } from './snapshot_table.mjs';
import { TEXT_SOURCE } from './snapshot_text.mjs';

// Runs in the page, inside the IIFE below, after DOM_ACCESS_SOURCE,
// GRADIENT_SOURCE, BORDERS_SOURCE, TEXT_SOURCE, TABLE_SOURCE and blendOver:
// queryOne, queryAll, elementChildrenOf, domAccess, reportCollectionLoss, the
// two limits, splitTopLevelCommas, parseLinearGradient, createBorders,
// createTextLayout, createTableLayout and blendOver are its free names. It is
// stringified, so it closes over nothing on the Node side; everything it needs
// from here arrives in `config`, and what pseudo.mjs read of the page's
// pseudo-elements in `pseudoData` (PseudoData).
async function snapshotPage(config, pseudoData) {
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
  const stats = { elements: 0, pseudoElements: 0, shapes: 0, lines: 0, images: 0, texts: 0, tables: 0, truncated: false };
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

  // groupInside(backdrop, s) -> the backdrop inside the opacity group the
  // element whose computed style is `s` opens, given the backdrop it sits on;
  // that backdrop itself when it opens none. What the element paints, its own
  // background included, paints inside the group.
  function groupInside(backdrop, s) {
    const opacity = opacityOf(s);
    if (!(opacity < 1)) return backdrop;
    return { color: TRANSPARENT_LAYER.color, alpha: TRANSPARENT_LAYER.alpha, group: { opacity, beneath: backdrop } };
  }

  // backdropInside(backdrop, s) -> the backdrop of the content inside the
  // element whose computed style is `s`, given the backdrop it sits on: its
  // opacity group (groupInside), then its own background over it.
  function backdropInside(backdrop, s) {
    let inside = groupInside(backdrop, s);
    if (s.visibility !== 'visible') return inside;
    const colour = parseColour(s.backgroundColor);
    if (colour) inside = paintOver(colour, inside);
    const middle = gradientMiddle(s.backgroundImage);
    if (middle) inside = paintOver(middle, inside);
    return inside;
  }

  // solidColour(layer, backdrop) -> 'RRGGBB': the solid colour `layer`
  // ({color, alpha}) shows painted over `backdrop` inside its innermost
  // opacity group, each group then faded over the backdrop beneath it.
  function solidColour(layer, backdrop) {
    let painted = paintOver(layer, backdrop);
    for (let depth = 0; painted.group && depth < WALK_STEP_LIMIT; depth++) {
      const group = painted.group;
      painted = paintOver({ color: painted.color, alpha: painted.alpha * group.opacity }, group.beneath);
    }
    return painted.color;
  }

  // textColour(backdrop, s) -> 'RRGGBB': the solid colour the text of the
  // element whose computed style is `s` paints, over `backdrop`.
  function textColour(backdrop, s) {
    return solidColour(parseColour(s.webkitTextFillColor) || parseColour(s.color) || UNREADABLE_TEXT_COLOUR, backdrop);
  }

  // ─── the slide background ────────────────────────────────────────────
  // The background transfer (preprocess.mjs) has already moved the slide
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

  // ─── pseudo-elements ─────────────────────────────────────────────────
  // Each ::before, ::after and ::marker the page generates, as pseudo.mjs read
  // it through the DevTools protocol: its border box, its box fragments and
  // its rendered text. Its host carries config.pseudoHostAttribute, whose
  // value is the host's index in pseudoData.hosts. The walk visits each
  // ::before and ::after as its host's first child or last, and the text
  // layout lays out its text there, so it is drawn like an element at that
  // place in paint order; a list item's ::marker is drawn with its item
  // (emitMarker). Its computed style is the page's own,
  // getComputedStyle(host, '::before'), read by property name like every element's.
  //   PseudoRecord = {host, type, name, style, rect, edges, fragments, pieces, text,
  //                   extent, selector, list}
  //   type       'before' | 'after' | 'marker'; name '::before' | '::after' | '::marker';
  //   rect       its border box's bounds, {left, top, width, height} as a DOMRect has them;
  //   edges      {width, height}: its border box's own sides, the quad's, which a
  //              rotation does not change (boxGeometry);
  //   fragments  its box fragments' bounds, as rect, in the browser's order;
  //   pieces     its text: [{boxes: [{text, left, top, right, bottom}]}], one piece
  //              per layout text object, each box one line fragment of it;
  //   text       its rendered text in logical order, white space as laid out ("1. ");
  //   extent     bounds {left, top, right, bottom} of all it generates (an image may
  //              be taller than its line), or null; its picture covers them;
  //   selector   its host's attribute, '[data-tellr-pseudo-host="<n>"]', for a capture;
  //   list       for a ::marker, ListMarker (markerOf); null for the others.
  // A record is no node: the walk and the text layout tell one apart with
  // isPseudo, which reads nothing of a DOM node.
  const pseudoRecords = new Set();
  // host element -> {before, after, marker}: PseudoRecord | null each
  const pseudoHosts = new Map();
  // Every ::marker record, in document order, for the text layout's probes.
  const markerRecords = [];

  function isPseudo(node) {
    return pseudoRecords.has(node);
  }

  // What the walk reads of an element or a pseudo-element: its tag name
  // ('::before' for a pseudo-element), its computed style and its border box.
  function tagNameOf(element) {
    return isPseudo(element) ? element.name : String(dom.tagName(element) || '').toLowerCase();
  }

  function styleOf(element) {
    return isPseudo(element) ? element.style : window.getComputedStyle(element);
  }

  function rectOf(element) {
    return isPseudo(element) ? element.rect : element.getBoundingClientRect();
  }

  // The bounds of a quad (four corners as x, y pairs), as rect.
  function quadBounds(quad) {
    const xs = [quad[0], quad[2], quad[4], quad[6]];
    const ys = [quad[1], quad[3], quad[5], quad[7]];
    const left = Math.min(xs[0], xs[1], xs[2], xs[3]);
    const top = Math.min(ys[0], ys[1], ys[2], ys[3]);
    return { left, top, width: Math.max(xs[0], xs[1], xs[2], xs[3]) - left, height: Math.max(ys[0], ys[1], ys[2], ys[3]) - top };
  }

  // Eight finite numbers, or null.
  function quadOf(value) {
    if (!Array.isArray(value) || value.length !== 8) return null;
    const quad = [];
    for (let index = 0; index < 8; index++) {
      const number = Number(value[index]);
      if (!Number.isFinite(number)) return null;
      quad.push(number);
    }
    return quad;
  }

  // Every pseudo-element box and text box handed in spends from one budget,
  // as the text layout's reads do.
  let pseudoBudget = COLLECTION_ITEM_LIMIT;

  function pseudoPieces(listed) {
    const pieces = [];
    const length = Array.isArray(listed) ? listed.length : 0;
    for (let index = 0; index < length && pseudoBudget > 0; index++) {
      const boxes = [];
      const listedBoxes = Array.isArray(listed[index]) ? listed[index] : [];
      for (let box = 0; box < listedBoxes.length && pseudoBudget > 0; box++, pseudoBudget--) {
        const read = listedBoxes[box] || {};
        const left = Number(read.x);
        const top = Number(read.y);
        const width = Number(read.w);
        const height = Number(read.h);
        if (typeof read.text !== 'string' || !read.text ||
            !(Number.isFinite(left) && Number.isFinite(top) && width >= 0 && height >= 0)) continue;
        boxes.push({ text: read.text, left, top, right: left + width, bottom: top + height });
      }
      if (boxes.length) pieces.push({ boxes });
    }
    return pieces;
  }

  function pseudoRecord(host, type, read, hostIndex) {
    const quad = read ? quadOf(read.quad) : null;
    if (!quad || pseudoBudget <= 0) return null;
    pseudoBudget--;
    const fragments = [];
    const listed = Array.isArray(read.fragments) ? read.fragments : [];
    for (let index = 0; index < listed.length && index < WALK_STEP_LIMIT && pseudoBudget > 0; index++, pseudoBudget--) {
      const fragment = quadOf(listed[index]);
      if (fragment) fragments.push(quadBounds(fragment));
    }
    const extent = read.extent || {};
    const extentLeft = Number(extent.x);
    const extentTop = Number(extent.y);
    const extentWidth = Number(extent.w);
    const extentHeight = Number(extent.h);
    const style = window.getComputedStyle(host, '::' + type);
    const text = typeof read.text === 'string' ? read.text : '';
    const record = {
      host,
      type,
      name: '::' + type,
      style,
      rect: quadBounds(quad),
      edges: { width: Math.hypot(quad[2] - quad[0], quad[3] - quad[1]), height: Math.hypot(quad[6] - quad[0], quad[7] - quad[1]) },
      fragments,
      pieces: pseudoPieces(read.pieces),
      text,
      extent: Number.isFinite(extentLeft) && Number.isFinite(extentTop) && extentWidth > 0 && extentHeight > 0
        ? { left: extentLeft, top: extentTop, right: extentLeft + extentWidth, bottom: extentTop + extentHeight }
        : null,
      selector: '[' + config.pseudoHostAttribute + '="' + hostIndex + '"]',
      list: type === 'marker' ? markerOf(style, text) : null,
    };
    pseudoRecords.add(record);
    if (record.list) markerRecords.push(record);
    return record;
  }

  // ─── list markers ────────────────────────────────────────────────────
  // What a list item's ::marker is, from Chrome's text for it and its
  // computed style, which carries its item's list-style (CSS Lists 3):
  //   ListMarker = {inside, symbol, image, glyphs, trailing, advance}
  //   inside    list-style-position: inside: it is laid out on its item's first
  //             line, and the text layout lays it out with the item's text;
  //   symbol    Chrome paints it as a shape (a disc, circle, square or disclosure
  //             triangle) in a box the size of that shape, which holds no space,
  //             though its text is "• ": the list-style-type is a predefined
  //             symbol and its content is normal;
  //   image     it paints an image, which only a picture shows: a list-style-image
  //             in place of any text, or content holding url(), image-set() or a
  //             gradient;
  //   glyphs    its text less its trailing white space ("1."): what it exports as;
  //   trailing  that white space (" ");
  //   advance   {full, glyphs}: how wide its whole text and its glyphs are in its
  //             own font as the browser lays them out, unscaled CSS px; the text
  //             layout measures them before the walk (measureMarkers): null until
  //             then, and when the measurement could not be read.
  // Read with hasOwnProperty, a plain table: page script can replace Set.
  const SYMBOL_MARKER_TYPES = { 'disc': true, 'circle': true, 'square': true, 'disclosure-open': true, 'disclosure-closed': true };

  // CSS white space: space, tab, line feed, carriage return, form feed; never NBSP.
  function isCssWhiteSpace(code) {
    return code === 32 || code === 9 || code === 10 || code === 13 || code === 12;
  }

  function markerOf(s, text) {
    const content = String(s.content || 'normal');
    // Scanned back from the end, once: a pattern anchored at the end would
    // rescan every run of white space inside a long content string.
    let end = text.length;
    while (end > 0 && isCssWhiteSpace(text.charCodeAt(end - 1))) end--;
    const glyphs = text.slice(0, end);
    const image = GENERATED_IMAGE.test(content) ||
      (!glyphs && String(s.listStyleImage || 'none') !== 'none');
    return {
      inside: s.listStylePosition === 'inside',
      symbol: !image && content === 'normal' &&
        Object.prototype.hasOwnProperty.call(SYMBOL_MARKER_TYPES, String(s.listStyleType)),
      image,
      glyphs,
      trailing: text.slice(glyphs.length),
      advance: null,
    };
  }

  // The marked hosts, through the pristine realm and bounded like every lookup:
  // each host attribute value names one entry of pseudoData.hosts, and the first
  // element in document order that carries it is that host.
  function readPseudoHosts() {
    const hosts = pseudoData && Array.isArray(pseudoData.hosts) ? pseudoData.hosts : [];
    if (!hosts.length) return;
    const claimed = [];
    const marked = queryAll('[' + config.pseudoHostAttribute + ']');
    for (let index = 0; index < marked.length; index++) {
      const element = marked[index];
      const value = String(dom.getAttribute(element, config.pseudoHostAttribute));
      const hostIndex = /^\d{1,7}$/.test(value) ? Number(value) : -1;
      if (!(hostIndex >= 0 && hostIndex < hosts.length) || claimed[hostIndex]) continue;
      claimed[hostIndex] = true;
      const entry = hosts[hostIndex] || {};
      const before = pseudoRecord(element, 'before', entry.before, hostIndex);
      const after = pseudoRecord(element, 'after', entry.after, hostIndex);
      const marker = pseudoRecord(element, 'marker', entry.marker, hostIndex);
      if (before || after || marker) pseudoHosts.set(element, { before, after, marker });
    }
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

  // A pseudo-element has no offset size; its quad's sides are its box's own
  // sides, scaled as it is drawn.
  function boxGeometry(element, rect, frame) {
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const bounds = { x: rect.left, y: rect.top, w: rect.width, h: rect.height, scale: frame.scale, rotate: null };
    if (!frame.angle) return bounds;
    const box = layoutBox(element, rect, frame);
    return box.w > 0 && box.h > 0 ? box : bounds;
  }

  // layoutBox(element, rect, frame) -> the element's untransformed layout box
  // (its offset size, or a pseudo-element's quad sides), times the frame's
  // scale, centred where its bounds `rect` are centred and turned by the
  // frame: {x, y, w, h, scale, rotate}. A side the layout gives no length is 0.
  function layoutBox(element, rect, frame) {
    const generated = isPseudo(element);
    const layoutWidth = generated ? element.edges.width : Number(element.offsetWidth);
    const layoutHeight = generated ? element.edges.height : Number(element.offsetHeight);
    const w = layoutWidth > 0 ? (generated ? layoutWidth : layoutWidth * frame.scaleX) : 0;
    const h = layoutHeight > 0 ? (generated ? layoutHeight : layoutHeight * frame.scaleY) : 0;
    const centreX = Number(rect.left) + Number(rect.width) / 2;
    const centreY = Number(rect.top) + Number(rect.height) / 2;
    return { x: centreX - w / 2, y: centreY - h / 2, w, h, scale: frame.scale, rotate: frame.angle || null };
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
    const rect = overflows || own ? rectOf(element) : null;
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
    const bounds = boundsOfRect(rectOf(element));
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

  // ─── borders and rings ───────────────────────────────────────────────
  // What a painted box draws beyond its fill (snapshot_borders.mjs): its
  // border as an outline or a line per side, its outline rings and its outer
  // shadow, each a shape or a line pushed here.
  const { SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox, sliceOf } = createBorders({
    paintedColour,
    normalisedAngle,
    cornerShape,
    shownPart,
    boundsOf,
    pushShape,
    pushClippedShape,
    pushSideLines,
  });

  // ─── side lines ──────────────────────────────────────────────────────
  // Each painted side of a border that differs between sides is one line item
  // along its centre line: half its width in from its edge, over the box's
  // whole side, so neighbouring sides overlap at their corners. It is turned
  // with the box, cut to the clip, and painted over the box's fill (the same
  // order, emitted after it). A side with no inner edge left (a box that is
  // all border along it, as in the CSS triangle of an arrowhead) cannot be a
  // line along it: it is the region CSS paints for it, the triangle between
  // its outer edge and where its two corner diagonals meet, a filled path.
  // The sides run clockwise: from corner `from` to corner `to`, along `along`
  // (a unit vector), with `inward` pointing into the box, and the widths of the
  // sides before and after it at those corners.
  function sideFrames(box, widths) {
    const left = box.x;
    const top = box.y;
    const right = box.x + box.w;
    const bottom = box.y + box.h;
    return {
      Top: { from: { x: left, y: top }, to: { x: right, y: top }, along: { x: 1, y: 0 }, inward: { x: 0, y: 1 }, length: box.w, before: widths.Left, after: widths.Right },
      Right: { from: { x: right, y: top }, to: { x: right, y: bottom }, along: { x: 0, y: 1 }, inward: { x: -1, y: 0 }, length: box.h, before: widths.Top, after: widths.Bottom },
      Bottom: { from: { x: right, y: bottom }, to: { x: left, y: bottom }, along: { x: -1, y: 0 }, inward: { x: 0, y: -1 }, length: box.w, before: widths.Right, after: widths.Left },
      Left: { from: { x: left, y: bottom }, to: { x: left, y: top }, along: { x: 0, y: -1 }, inward: { x: 1, y: 0 }, length: box.h, before: widths.Bottom, after: widths.Top },
    };
  }

  function pushSideLines(box, sides, order, clip) {
    const frames = sideFrames(box, sides.widths);
    const centreX = box.x + box.w / 2;
    const centreY = box.y + box.h / 2;
    const radians = (box.rotate || 0) * Math.PI / 180;
    const turned = (point) => (radians
      ? {
        x: centreX + (point.x - centreX) * Math.cos(radians) - (point.y - centreY) * Math.sin(radians),
        y: centreY + (point.x - centreX) * Math.sin(radians) + (point.y - centreY) * Math.cos(radians),
      }
      : point);
    const offset = (point, vector, distance) => ({ x: point.x + vector.x * distance, y: point.y + vector.y * distance });
    // Widened by the rounding a clip edge may differ by, so a side that only
    // touches the clip is not cut.
    const lineClip = {
      left: clip.left - CUT_EPSILON_PX,
      top: clip.top - CUT_EPSILON_PX,
      right: clip.right + CUT_EPSILON_PX,
      bottom: clip.bottom + CUT_EPSILON_PX,
    };
    for (let index = 0; index < sides.painted.length; index++) {
      const side = sides.painted[index];
      const frame = frames[side.side];
      if (!(frame.length > 0)) continue;
      const corners = frame.before + frame.after;
      if (corners > 0 && frame.length - corners <= CUT_EPSILON_PX) {
        // The diagonals from both corners meet at `reach` along the side.
        const reach = frame.length / corners;
        const apex = offset(offset(frame.from, frame.along, reach * frame.before), frame.inward, reach * side.widthPx);
        const region = clipPolygon([turned(frame.from), turned(apex), turned(frame.to)], clip);
        if (region.length >= 3) pushPath(order, [region], true, { color: side.color, alpha: side.alpha }, null, null);
        continue;
      }
      const start = turned(offset(frame.from, frame.inward, side.widthPx / 2));
      const end = turned(offset(frame.to, frame.inward, side.widthPx / 2));
      const shown = clipSegment(start, end, lineClip);
      if (!shown) continue;
      if ((shown.cutsStart || shown.cutsEnd) &&
          Math.hypot(shown.to.x - shown.from.x, shown.to.y - shown.from.y) < MINIMUM_VISIBLE_PX) continue;
      // Written left to right, or top to bottom: the same line whichever corner it ran from.
      const forward = shown.from.x < shown.to.x - SAME_POINT_PX ||
        (Math.abs(shown.from.x - shown.to.x) <= SAME_POINT_PX && shown.from.y <= shown.to.y);
      pushLine(order, forward ? shown.from : shown.to, forward ? shown.to : shown.from, side);
    }
  }

  function pushLine(order, from, to, side) {
    items.push({
      kind: 'line',
      id: nextItemId++,
      order,
      x1: from.x,
      y1: from.y,
      x2: to.x,
      y2: to.y,
      color: side.color,
      alpha: side.alpha,
      widthPx: side.widthPx,
      dash: side.dash,
    });
    stats.lines++;
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

  // ─── captures ────────────────────────────────────────────────────────
  // Spec §4. What no item can draw is a picture of what the browser painted
  // for it, which capture.cjs takes from this very page once the snapshot has
  // returned: a capture target, named for it with config.captureAttribute.
  //   subtree  an inline <svg>, a <canvas>, a <video>, and an <img> that
  //            cannot be embedded as it is (emitReplaced): the element and
  //            everything it holds, its own box included;
  //   box      an element whose own box paints what no shape can (capturesBox):
  //            its box alone, its text, children and own ::before, ::after
  //            and list marker staying native. The picture
  //            replaces its native box (fill, outline and shadow). A
  //            pseudo-element's box is captured the same way, on its own, and
  //            so is one whose content is an image (an icon bullet), its
  //            picture covering all it generates: capture.cjs isolates its
  //            host's ::before or ::after, named by the host attribute, which
  //            is already on the page (pseudo.mjs). So is a list marker that
  //            paints an image (emitMarker), through its item.
  // The picture is what the target's clip shows of all it paints: its bounds,
  // grown by the reach of its outer shadow and filter (paintReach), cut to the
  // clip. Its pixels already carry the target's cumulative opacity, so
  // its alpha is 1. Its rect is axis-aligned, so a turned target is drawn
  // turned in it, with no rotation.
  //   captureTargets: {element, capture, hidden: Element[]}, in capture order.
  const captureTargets = [];
  let nextCaptureSeq = 0;

  // The background layers a shape cannot paint: a gradient of any kind, or a
  // url() image. background-clip: text gives them to the glyphs instead, where
  // the run's solid colour carries them (snapshot_text.mjs), so gradient text is
  // never a box capture: it would paint a gradient rectangle under its words.
  function paintsBackgroundImage(s) {
    return !clipsToText(s) && /(?:gradient|url)\(/i.test(String(s.backgroundImage || ''));
  }

  // The effects that change how a box paints, which no shape carries.
  function hasBoxEffect(s) {
    const set = (value, none) => Boolean(value) && value !== none;
    return set(s.filter, 'none') || set(s.backdropFilter, 'none') || set(s.mixBlendMode, 'normal') ||
      set(s.clipPath, 'none') || set(s.maskImage, 'none') || set(s.webkitMaskImage, 'none');
  }

  // A pseudo-element whose content holds an image (content: url(), image-set()
  // or a gradient, an icon bullet): the image is generated content no shape
  // and no text run can draw.
  const GENERATED_IMAGE = /(?:url|image-set|gradient)\(/i;
  function generatesImage(element, s) {
    return isPseudo(element) && GENERATED_IMAGE.test(String(s.content || ''));
  }

  // capturesBox(s, opacity, element) -> whether the element's own box is a
  // box-only capture: a background image, an effect on a box that paints, or
  // for a pseudo-element, an image it generates.
  function capturesBox(s, opacity, element) {
    if (generatesImage(element, s)) return true;
    if (clipsToText(s)) return false;
    return paintsBackgroundImage(s) || (hasBoxEffect(s) && paintsBox(s, opacity));
  }

  // How far a box's outer shadows paint past its bounds, in slide px: the
  // widest painted layer's max(|offset|) + blur + spread, a ring of spread
  // alone included.
  function shadowReach(s, box) {
    const layers = outerShadowLayers(s.boxShadow);
    let reach = 0;
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      if (!paintedColour(layer.colourText, 1)) continue;
      reach = Math.max(reach, Math.max(Math.abs(layer.offsetX), Math.abs(layer.offsetY)) + layer.blur + layer.spread);
    }
    return reach * box.scale;
  }

  // How far a filter paints past its element's bounds, in slide px. blur()
  // and a drop-shadow()'s blur take a standard deviation σ, and Chrome paints
  // ~2.45σ past the edge they blur, under 3% alpha past ~1.75σ. A box-shadow's
  // blur radius is 2σ, so 2σ is the reach shadowReach gives a shadow; a drop
  // shadow is offset as well. The functions apply one after another, so their
  // reaches add. No other function moves paint.
  const PAINT_MOVING_FILTER = /(drop-shadow|blur)\(((?:[^()]|\([^()]*\))*)\)/gi;
  function filterReach(s, box) {
    const value = String(s.filter || 'none');
    if (value === 'none') return 0;
    let reach = 0;
    PAINT_MOVING_FILTER.lastIndex = 0;
    let match = PAINT_MOVING_FILTER.exec(value);
    for (let count = 0; match && count < WALK_STEP_LIMIT; count++) {
      // A drop shadow's colour comes first, and may be a function: only its lengths count.
      const lengths = (match[2].replace(/[a-z-]+\([^()]*\)/gi, ' ').match(/-?[\d.]+(?:e[-+]?\d+)?px/g) || []).map(parseFloat);
      if (match[1].toLowerCase() === 'blur') {
        reach += 2 * Math.abs(lengths[0] || 0);
      } else {
        reach += Math.max(Math.abs(lengths[0] || 0), Math.abs(lengths[1] || 0)) + 2 * Math.abs(lengths[2] || 0);
      }
      match = PAINT_MOVING_FILTER.exec(value);
    }
    return reach * box.scale;
  }

  // How far everything a target paints reaches past its bounds: its outer
  // shadows, then its filter, which blurs and shadows those too.
  function paintReach(s, box) {
    return shadowReach(s, box) + filterReach(s, box);
  }

  function grown(bounds, reach) {
    return { left: bounds.left - reach, top: bounds.top - reach, right: bounds.right + reach, bottom: bounds.bottom + reach };
  }

  // The descendants of a subtree target that the slide does not show (their
  // computed visibility is not visible, as an SVG group's visibility="hidden"
  // makes it): the isolation shows a target's whole subtree, so capture.cjs
  // hides these again. Read only for an <svg>, the one target whose
  // descendants paint, over the pristine tree and bounded like the walk.
  function hiddenDescendants(element) {
    const hidden = [];
    const pending = [{ element, depth: 0 }];
    let read = 0;
    while (pending.length) {
      const next = pending.pop();
      if (next.depth >= WALK_STEP_LIMIT) {
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'cut at depth ' + WALK_STEP_LIMIT, 'the snapshot capture targets');
        continue;
      }
      const children = elementChildrenOf(next.element);
      for (let index = children.length - 1; index >= 0; index--) {
        if (++read > COLLECTION_ITEM_LIMIT) {
          reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' elements', 'the snapshot capture targets');
          return hidden;
        }
        if (window.getComputedStyle(children[index]).visibility !== 'visible') hidden.push(children[index]);
        pending.push({ element: children[index], depth: next.depth + 1 });
      }
    }
    return hidden;
  }

  // What a capture of `element` paints, given the bounds of its box: those
  // bounds, and for a pseudo-element all it generates, since an icon may stand
  // out of its line.
  function paintedBounds(element, bounds) {
    const extent = isPseudo(element) ? element.extent : null;
    if (!extent) return bounds;
    return {
      left: Math.min(bounds.left, extent.left),
      top: Math.min(bounds.top, extent.top),
      right: Math.max(bounds.right, extent.right),
      bottom: Math.max(bounds.bottom, extent.bottom),
    };
  }

  // Whether a capture's picture (or null) covers bounds {left, top, right,
  // bottom}, to within layout rounding.
  function holds(capture, bounds) {
    return Boolean(capture) &&
      capture.x <= bounds.left + CUT_EPSILON_PX && capture.y <= bounds.top + CUT_EPSILON_PX &&
      capture.x + capture.w >= bounds.right - CUT_EPSILON_PX &&
      capture.y + capture.h >= bounds.bottom - CUT_EPSILON_PX;
  }

  // A capture of `element` (computed style `s`) in `mode`, for what `clip`
  // shows of `bounds`, and its picture item at `order`. Returns the Capture,
  // or null when the clip hides it all. `withoutBorders` leaves the borders of
  // a box target and of all it holds out of its picture: a collapsed native
  // table's grid draws them, as emitBox's withoutBorder does for its shape.
  function pushCapture(element, s, mode, bounds, order, clip, withoutBorders) {
    const generated = isPseudo(element);
    const shown = shownPart(paintedBounds(element, bounds), clip);
    if (!shown) return null;
    const id = 'c' + nextCaptureSeq++;
    const x = shown.left;
    const y = shown.top;
    const w = shown.right - shown.left;
    const h = shown.bottom - shown.top;
    const hidden = mode === 'subtree' && tagNameOf(element) === 'svg' ? hiddenDescendants(element) : [];
    const capture = {
      id,
      x,
      y,
      w,
      h,
      mode,
      selector: generated ? element.selector : '[' + config.captureAttribute + '="' + id + '"]',
      pseudo: generated ? element.type : null,
      hiddenWithin: hidden.length > 0,
      // What box mode's transparent text colour must not take from the box:
      // a border or shadow painted in currentColor (capture.cjs retainedCss).
      // A ::marker paints neither.
      paint: mode === 'box' && !(generated && element.type === 'marker')
        ? { borderColors: [s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor], boxShadow: s.boxShadow }
        : null,
      bordersHidden: Boolean(withoutBorders) && mode === 'box',
    };
    captures.push(capture);
    // A pseudo-element's host is named already; every other target is named once the reads are done.
    if (!generated) captureTargets.push({ element, capture, hidden });
    items.push({ kind: 'image', id: nextItemId++, order, x, y, w, h, src: null, captureId: id, alpha: 1, rotate: null });
    stats.images++;
    return capture;
  }

  // The snapshot's one lasting write, made once every read is done (the metric
  // probes are gone by then), so no read saw a changed page: each target is
  // named for capture.cjs, through the pristine realm, and each descendant
  // it must hide again is marked. A name the slide carried already is taken
  // off first, so nothing but the target answers to its selector. A target
  // that cannot be named is not captured, and says so.
  function nameCaptureTargets() {
    if (!captureTargets.length) return;
    const names = [config.captureAttribute, config.hiddenAttribute];
    const stale = queryAll('[' + names[0] + '],[' + names[1] + ']');
    for (let index = 0; index < stale.length; index++) {
      try {
        dom.removeAttribute(stale[index], names[0]);
        dom.removeAttribute(stale[index], names[1]);
      } catch (e) { /* a name that will not come off: its element may show in a capture */ }
    }
    for (let index = 0; index < captureTargets.length; index++) {
      const target = captureTargets[index];
      try {
        dom.setAttribute(target.element, names[0], target.capture.id);
        for (let hidden = 0; hidden < target.hidden.length; hidden++) {
          dom.setAttribute(target.hidden[hidden], names[1], '');
        }
      } catch (e) {
        target.capture.failed = true;
        console.error('[html2pptx] capture failed: ' + target.capture.id + ' the target could not be named (' +
          (e && e.message) + ')');
      }
    }
  }

  // ─── replaced content ────────────────────────────────────────────────
  // The picture sits in the content box (inside border and padding), and a
  // raster data: <img> is embedded as is when the browser shows it as it is
  // (embeddedImage). Every other <img> with a data: source, and every inline
  // <svg>, <canvas> and <video>, is captured. The rest (audio, iframe, object,
  // embed, and an image from anywhere but data:, SDR-4437) has nothing the
  // slide can take: its picture carries no data and is skipped.
  const CAPTURED_REPLACED = new Set(['img', 'svg', 'canvas', 'video']);

  // boxEdges(s, scaleX, scaleY) -> {Top, Right, Bottom, Left}: the border and
  // padding on each side of the box whose computed style is `s`, {border,
  // padding} in slide px, its left and right scaled by scaleX, its top and
  // bottom by scaleY.
  function boxEdges(s, scaleX, scaleY) {
    const edges = {};
    for (let index = 0; index < SIDES.length; index++) {
      const side = SIDES[index];
      const scale = side === 'Left' || side === 'Right' ? scaleX : scaleY;
      edges[side] = {
        border: (parseFloat(s['border' + side + 'Width']) || 0) * scale,
        padding: (parseFloat(s['padding' + side]) || 0) * scale,
      };
    }
    return edges;
  }

  function contentBox(s, box) {
    const edges = boxEdges(s, box.scale, box.scale);
    const edge = (side) => edges[side].border + edges[side].padding;
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

  function imageSource(element) {
    return String(element.currentSrc || element.src || '');
  }

  // Whether an <img>'s own painting changes what its pixels show, so its
  // source embedded as is would not be what the slide shows: a corner radius,
  // a shadow or outline ring, a filter, a blend, a clip-path or a mask.
  function decoratesImage(s) {
    const corners = [s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius];
    for (let index = 0; index < corners.length; index++) {
      const radii = String(corners[index] || '0').trim().split(/\s+/);
      for (let radius = 0; radius < radii.length; radius++) {
        if (parseFloat(radii[radius]) > 0) return true;
      }
    }
    return (Boolean(s.boxShadow) && s.boxShadow !== 'none') || hasBoxEffect(s);
  }

  // A raster data: <img> whose fit keeps the whole image ({src, area}), else
  // null: object-fit fill stretches it to the content box, contain letterboxes
  // it at the centre. Any other fit or position crops it.
  function embeddedImage(element, s, area) {
    const source = imageSource(element);
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

  function pushImage(order, area, src, alpha, rotate) {
    items.push({
      kind: 'image',
      id: nextItemId++,
      order,
      x: area.x,
      y: area.y,
      w: area.w,
      h: area.h,
      src,
      captureId: null,
      alpha,
      rotate,
    });
    stats.images++;
  }

  // A replaced element's box and picture. An image embedded as it is sits on
  // its native box (emitBox), at its cumulative opacity; a picture its clip
  // hides is not on the slide, and one the clip cuts is captured cut. A
  // capture holds the element's own box as well, so that box is no shape.
  function emitReplaced(element, name, s, box, opacity, place, seq, clip) {
    const order = place.paint.concat([4, 0, seq, 0]);
    const isSlideRoot = element === slideRoot;
    if (name === 'img' && !decoratesImage(s)) {
      const area = contentBox(s, box);
      const embedded = area ? embeddedImage(element, s, area) : null;
      const shown = embedded && shownPart(boundsOf({ ...embedded.area, rotate: box.rotate }), clip);
      if (embedded && !(shown && shown.cut)) {
        emitBox(s, box, opacity, place.box, isSlideRoot, clip);
        if (shown) pushImage(order, embedded.area, embedded.src, opacity, box.rotate);
        return;
      }
    }
    if (CAPTURED_REPLACED.has(name) && (name !== 'img' || /^data:/i.test(imageSource(element)))) {
      pushCapture(element, s, 'subtree', grown(boundsOf(box), paintReach(s, box)), order, clip);
      return;
    }
    emitBox(s, box, opacity, place.box, isSlideRoot, clip);
    const area = contentBox(s, box);
    if (area && shownPart(boundsOf({ ...area, rotate: box.rotate }), clip)) pushImage(order, area, null, opacity, box.rotate);
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
    layoutBox,
    boxEdges,
    contentBox,
    // A box drawn as a shape or captured (capturesBox) paints: a span whose
    // only paint is a gradient is a decoration too.
    paintsBox: (s, opacity, element) => paintsBox(s, opacity) || capturesBox(s, opacity, element),
    inlineClip,
    shows: (bounds, clip) => shownPart(bounds, clip) !== null,
    isPseudo,
    pseudoOf: (element) => pseudoHosts.get(element) || null,
    rectOf,
    coverageFont: config.coverageFont,
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

  // ─── turned text ─────────────────────────────────────────────────────
  // Text under a rotation, or set sideways by a vertical writing mode, is
  // turned: its Range rects bound turned glyphs, and a renderer turns a whole
  // text box or nothing. So the text of each turn root is ONE text item
  // (snapshot_text.mjs turnedBlocks): the root's unrotated layout box from the
  // walk's frame (boxGeometry), turned by the text's angle about the centre it
  // shares with the root's bounds, holding the root's lines, and grown by the
  // slack its padding cannot hold with that layout box kept in place.
  // A turn root is an element whose text is turned (its frame's cumulative
  // angle, plus the turn of its writing mode, writingTurn) and that does not
  // paint with the turned text around it: it has a paint group of its own
  // (placement: a transform, a positioned box, a flex or grid item, an atomic
  // inline, a float), a writing mode of its own, or a table cell's grid slot,
  // or no turned text is around it. An in-flow block inside a turn root paints
  // in the root's inline content layer (CSS 2.1 Appendix E), so its text joins
  // the root's item, in DOM order, as further lines. Anything with its own
  // paint group is an item of its own over its own box, so its box never
  // paints over text it holds; so is a table cell, laid out beside its
  // neighbours, not under them. A root whose line a gap cuts (an atomic inline,
  // a hidden word, an inline element's edges) is cut as unturned text is, each
  // piece a turned item where its text lies (snapshot_text.mjs turnedBlocks).
  //   TurnedText = {root, style, frame, angle, turn, reversed, writingMode,
  //                 centre, paint, id, lines, lastSeq}
  //   root, style, frame  the root, its computed style and transform frame;
  //   angle      the text's angle, degrees clockwise, 0..360: frame.angle + turn;
  //   turn       its writing mode's turn (0, 90 or 270), which swaps its box's sides;
  //   reversed   its lines stack the other way from the turned box's (vertical-lr);
  //   centre     its bounds' centre, about which its box turns;
  //   paint      its paint group, whose inline layer its item paints in;
  //   id         its first item's sequence number, taken at the root's visit
  //              (DOM pre-order); the pieces of a cut root number on from the walk's end;
  //   lines      its lines so far, in DOM order (snapshot_text.mjs layoutTurnedRun);
  //   lastSeq    the sequence of the last group added: its items paint over
  //              every decoration of its text (pushGroup).
  const turnedTexts = [];

  // The TurnedText the text of `element` joins, or null for text that is not
  // turned. `state` is the walk's state for it, `place` its placement.
  function turnedTextOf(element, name, s, frame, place, state, seq) {
    // An inline box's text is its block's, laid out with it.
    if (textLayout.isInlineBox(name, s)) return state.turned;
    const turn = textLayout.writingTurn(s);
    if (!frame.angle && !turn.angle) return null;
    const outer = state.turned;
    if (outer && place.paint === state.paint && outer.writingMode === turn.writingMode &&
        String(s.display) !== 'table-cell') {
      return outer;
    }
    const rect = rectOf(element);
    const turned = {
      root: element,
      style: s,
      frame,
      angle: normalisedAngle(frame.angle + turn.angle),
      turn: turn.angle,
      reversed: turn.reversed,
      writingMode: turn.writingMode,
      centre: { x: Number(rect.left) + Number(rect.width) / 2, y: Number(rect.top) + Number(rect.height) / 2 },
      paint: place.paint,
      id: nextItemId++,
      lines: [],
      lastSeq: seq,
    };
    turnedTexts.push(turned);
    return turned;
  }

  // Adds a group's turned lines to its TurnedText, in the order the walk
  // releases groups, which is DOM order.
  function addTurnedLines(turned, lines, blockSeq) {
    turned.lastSeq = Math.max(turned.lastSeq, blockSeq);
    for (let index = 0; index < lines.length; index++) turned.lines.push(lines[index]);
  }

  // Each turn root's items, once the walk has given it every line: the first
  // at the root's own id, in its paint group's inline content layer, over
  // every decoration of the text it holds, its pieces in order after it.
  // Nothing for a root whose text paints nothing.
  function pushTurnedTexts() {
    for (let index = 0; index < turnedTexts.length; index++) {
      const turned = turnedTexts[index];
      const blocks = textLayout.turnedBlocks(turned);
      const order = turned.paint.concat([4, 0, turned.lastSeq, 1]);
      for (let block = 0; block < blocks.length; block++) {
        items.push({ kind: 'text', id: block === 0 ? turned.id : nextItemId++, order, ...blocks[block] });
        stats.texts++;
      }
    }
  }

  // One group at its block's place in the inline content layer (4) of `paint`:
  // each decoration at paint + [4, 0, blockSeq, 0, elSeq], every fragment of
  // it, then each text block at paint + [4, 0, blockSeq, 1]. So a block's
  // decorations paint over every block background of their stacking context
  // and under that block's own text, as CSS paints inline content (CSS 2.1
  // Appendix E, step 7 after step 4). elSeq is the decoration's place in DOM
  // order among its block's decorations, which orders them as the walk's own
  // sequence numbers would: both follow the document, and no other key of the
  // slide compares with it. A decoration whose box needs a capture (a
  // highlight gradient, a filtered chip) is one box-only picture at that
  // place: its fragments' bounds, grown by its shadow and filter, so every fragment is in it.
  // A turned group's lines go to its TurnedText instead of being blocks,
  // whose item is pushed once the walk is done (pushTurnedTexts).
  function pushGroup(group, paint, blockSeq) {
    for (let index = 0; index < group.decorations.length; index++) {
      const decoration = group.decorations[index];
      const order = paint.concat([4, 0, blockSeq, 0, index]);
      if (capturesBox(decoration.style, decoration.opacity, decoration.element)) {
        let bounds = boundsOf(decoration.boxes[0]);
        for (let fragment = 1; fragment < decoration.boxes.length; fragment++) {
          const next = boundsOf(decoration.boxes[fragment]);
          bounds = {
            left: Math.min(bounds.left, next.left),
            top: Math.min(bounds.top, next.top),
            right: Math.max(bounds.right, next.right),
            bottom: Math.max(bounds.bottom, next.bottom),
          };
        }
        const reach = paintReach(decoration.style, decoration.boxes[0]);
        pushCapture(decoration.element, decoration.style, 'box', grown(bounds, reach), order, decoration.clip);
        continue;
      }
      for (let fragment = 0; fragment < decoration.boxes.length; fragment++) {
        emitBox(decoration.style, decoration.boxes[fragment], decoration.opacity, order, false, decoration.clip,
          sliceOf(decoration, fragment));
      }
    }
    if (group.turned) {
      addTurnedLines(group.turned, group.lines, blockSeq);
      return;
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

  // A list item's ::marker, drawn when the walk visits its item (`paint` and
  // `seq` its item's): the first thing the item's first line paints, so ahead
  // of its decorations and text, at paint + [4, 0, seq, 0], which sorts before
  // both. `walk` is the context of its item's inline content, its backdrop
  // what the item sits on inside the item's opacity group: Chrome lays an
  // outside marker out before its item's border box, so the item's own
  // background is never under it. `picture` is the item's own box-only
  // capture, or null.
  // * Outside its item, a marker with text is a single-line text item of its
  //   own (snapshot_text.mjs markerBlock); under a turn, a turned one at its
  //   box, turned with its item's text (turnedMarkerBlock).
  // * Inside, its text is a token of its item's first line, or a segment of
  //   it, which the text layout lays out with its item's text (collectRuns),
  //   over the item's background.
  // * A marker that paints an image is a box-only picture of its box, which
  //   capture.cjs isolates: its item shown with nothing of its own painted.
  //   The item's own picture holds that image already where it holds all the
  //   marker shows, so the marker then gets no picture of its own.
  // Never a native bullet: the slide's text has none.
  function emitMarker(element, paint, seq, walk, picture) {
    const pseudo = pseudoHosts.get(element);
    const marker = pseudo ? pseudo.marker : null;
    if (!marker) return;
    stats.pseudoElements++;
    const order = paint.concat([4, 0, seq, 0]);
    if (marker.list.image && marker.style.visibility === 'visible') {
      const bounds = boundsOfRect(marker.rect);
      const shown = shownPart(paintedBounds(marker, bounds), walk.clip);
      if (shown && !holds(picture, shown)) pushCapture(marker, marker.style, 'box', bounds, order, walk.clip);
    }
    if (marker.list.inside) return;
    const block = walk.turned ? textLayout.turnedMarkerBlock(marker, walk) : textLayout.markerBlock(marker, walk);
    if (block) pushText({ ...block, order });
  }

  // The element's inline groups, as items now or waiting for the subtree they follow.
  function collectText(element, s, paint, seq, walk) {
    placeGroups(textLayout.collectTextBlocks(element, s, walk), paint, seq);
  }

  function placeGroups(groups, paint, seq) {
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

  // ─── tables ──────────────────────────────────────────────────────────
  // A <table> the slide shows whole, laid out as a grid an a:tbl can draw
  // (snapshot_table.mjs collectTable), is one table item over its own box: the
  // walk then draws no box of its parts and gives each cell's text to the cell
  // (snapshot_table.mjs collectCellText), and visits everything the cells hold
  // as anywhere else, so a pill, a picture or a cell's ::before is an item of
  // its own over the table: the inline content of the table's context paints
  // after its own box.
  // Any other table is positioned items, as every slide box is drawn: one an
  // a:tbl cannot draw, and one a clip cuts, which items are cut to and
  // an a:tbl cannot be; a table the clip hides shows nothing either way.
  //   tableParts: part element -> {cell: {model: TableCell, grid} | null}
  const tableParts = new Map();
  const tableLayout = createTableLayout({
    parseColour,
    paintedColour,
    paintOver,
    solidColour,
    backdropInside,
    opacityOf,
    pseudoOf: (element) => pseudoHosts.get(element) || null,
    rectOf,
    fontOf: textLayout.fontOf,
    layoutCell: textLayout.layoutCell,
    collectText,
    placeGroups,
  });

  // The TableLayout of a <table> drawn as a native table, its parts now owned
  // by it, or null. `box` is its border box, `clips` its clipsOf, `walk`
  // {opacity, frame, backdrop}: its cumulative opacity, its frame and what it sits on.
  function nativeTable(element, name, s, box, clips, walk) {
    // A table whose own text is turned (a vertical writing mode) is set
    // sideways throughout, which no a:tbl draws.
    if (name !== 'table' || walk.frame.angle || textLayout.writingTurn(s).angle || hasBoxEffect(s)) return null;
    const shown = shownPart(boundsOf(box), clips.box);
    if (!shown || shown.cut) return null;
    const layout = tableLayout.collectTable(element, s, walk);
    if (!layout) return null;
    for (let index = 0; index < layout.parts.length; index++) {
      tableParts.set(layout.parts[index], { cell: layout.cells.get(layout.parts[index]) || null });
    }
    return layout;
  }

  function pushTable(layout, order) {
    items.push({ ...layout.item, id: nextItemId++, order });
    stats.tables++;
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
  // An element's ::before is visited as its first child and its ::after as its
  // last, so their items take those places in paint order and ids.
  const stack = [];
  let pushed = 0;

  function pushEntry(element, state) {
    if (pushed >= COLLECTION_ITEM_LIMIT) {
      stats.truncated = true;
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' elements', 'the snapshot walk');
      return false;
    }
    stack.push({ element, state });
    pushed++;
    return true;
  }

  // Pushed last first, so the stack pops them in tree order. Generated content
  // holds no elements, so a pseudo-element has no children.
  function pushChildren(element, state) {
    if (state.depth > WALK_STEP_LIMIT) {
      stats.truncated = true;
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'cut at depth ' + WALK_STEP_LIMIT, 'the snapshot walk');
      return;
    }
    if (isPseudo(element)) return;
    const pseudo = pseudoHosts.get(element) || null;
    if (pseudo && pseudo.after && !pushEntry(pseudo.after, state)) return;
    const children = elementChildrenOf(element);
    for (let index = children.length - 1; index >= 0; index--) {
      if (!pushEntry(children[index], state)) return;
    }
    if (pseudo && pseudo.before) pushEntry(pseudo.before, state);
  }

  // A subtree that shows nothing still holds text the page reads (its
  // innerText, which a screen reader and the text-loss oracle read), so it is
  // the slide's hidden text. An inline box's text belongs to its block's
  // layout, which records it there. Generated content is no part of innerText.
  function recordHiddenSubtree(element, name, s) {
    if (isPseudo(element) || textLayout.isInlineBox(name, s)) return;
    let text;
    try {
      text = String(dom.innerText(element) || '');
    } catch (e) {
      // Not an HTML element (an <svg>): its text is drawn in its picture, not set as text.
      return;
    }
    textLayout.recordHiddenText(text);
  }

  // `element` is an element or a pseudo-element (PseudoRecord), which is
  // drawn the same way: its box, its text, at its place in paint order.
  function visit(element, state, seq) {
    if (isPseudo(element)) stats.pseudoElements++;
    else stats.elements++;
    const name = tagNameOf(element);
    const s = styleOf(element);
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
    // A box-only capture is the element's box: no native shape beside it.
    // A box-only capture of the element's own box, which a list marker may lie in.
    // A part of a native table has no box of its own: the table item draws it.
    const part = tableParts.get(element) || null;
    let picture = null;
    if (s.visibility === 'visible' && !textLayout.isInlineBox(name, s) && !part) {
      const box = boxGeometry(element, clips.rect || rectOf(element), frame);
      const table = box && !replaced ? nativeTable(element, name, s, box, clips, { opacity, frame, backdrop: state.backdrop }) : null;
      if (box && replaced) {
        emitReplaced(element, name, s, box, opacity, place, seq, clips.box);
      } else if (box && element !== slideRoot && capturesBox(s, opacity, element)) {
        picture = pushCapture(element, s, 'box', grown(boundsOf(box), paintReach(s, box)), place.box, clips.box,
          Boolean(table && table.collapse));
      } else if (box) {
        emitBox(s, box, opacity, place.box, element === slideRoot, clips.box, null, Boolean(table && table.collapse));
      }
      // Over the table's own box, under everything its cells hold.
      if (table) pushTable(table, place.box);
    }
    if (replaced) return;
    const backdrop = backdropInside(state.backdrop, s);
    const decoration = textLayout.decorationOf(state.decoration, element, s);
    const turned = turnedTextOf(element, name, s, frame, place, state, seq);
    const inline = { opacity, frame, backdrop, decoration, clip: clips.content, turned };
    // An outside marker is inside its item's opacity group but not on its
    // background (emitMarker): its backdrop is what the item sits on.
    emitMarker(element, place.paint, seq, { ...inline, backdrop: groupInside(state.backdrop, s) }, picture);
    // A table part holds no text but its cells' (snapshot_table.mjs readStructure).
    if (part && part.cell) tableLayout.collectCellText(element, s, place.paint, seq, inline, part.cell);
    else if (!part) collectText(element, s, place.paint, seq, inline);
    pushChildren(element, {
      ctx: place.ctx,
      paint: place.paint,
      opacity,
      layoutStyle: s,
      frame,
      backdrop,
      decoration,
      clips: clips.children,
      turned,
      depth: state.depth + 1,
    });
  }

  readPseudoHosts();
  // Marker advances, by probe in the page's own fonts, before the walk reads any rect.
  textLayout.measureMarkers(markerRecords);
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
    turned: null,
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
    turned: null,
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
  // Every turn root's text is gathered by now; its blocks are placed as they
  // are made (snapshot_text.mjs turnedBlocks, and turnedMarkerBlock during
  // the walk), from probes of their faces made on the way.
  pushTurnedTexts();
  // The webfonts the page loaded, read before the metric probes, which add a
  // face of their own for a moment (snapshot_text_metrics.mjs splitFallbackRuns).
  const { fonts, italicFonts } = textLayout.loadedFonts();
  // Line spacing, optical-size and kerning tracking, and the characters a
  // webfont lacks, from offscreen probes read once the walk has read every
  // rect (snapshot_text.mjs applyMetrics).
  textLayout.applyMetrics(fonts);
  if (textLayout.truncated()) stats.truncated = true;
  nameCaptureTargets();

  items.sort(compareItems);
  return {
    width: SLIDE_WIDTH,
    height: SLIDE_HEIGHT,
    background,
    items,
    captures,
    fonts,
    italicFonts,
    reference: { hiddenText: textLayout.hiddenText() },
    stats,
  };
}

// A page function of one argument, the PseudoData pseudo.mjs read: render_slide.cjs
// evaluates it applied to that data.
export const SNAPSHOT_SOURCE = `
(async function (pseudoData) {
  const DOM_ACCESS_LOG_PREFIX = '[html2pptx]';
${DOM_ACCESS_SOURCE}
${GRADIENT_SOURCE}
${BORDERS_SOURCE}
${TEXT_SOURCE}
${TABLE_SOURCE}
${blendOver.toString()}
  return await (${snapshotPage.toString()})(${JSON.stringify({
    slideRootMarker: SLIDE_ROOT_MARKER,
    captureAttribute: CAPTURE_ATTRIBUTE,
    hiddenAttribute: HIDDEN_ATTRIBUTE,
    pseudoHostAttribute: PSEUDO_HOST_ATTRIBUTE,
    coverageFont: { family: COVERAGE_FONT_FAMILY, advanceEm: COVERAGE_ADVANCE_EM, bytes: COVERAGE_FONT_BYTES },
  })}, pseudoData);
})
`;
