// Borders and rings: what a painted box draws besides its fill, as the
// snapshot (snapshot.mjs) emits a box. snapshot.mjs composes BORDERS_SOURCE
// into its page IIFE and makes it once (createBorders); emitBox is what its
// walk calls for every box that paints.
//
// A border that is the same on all four sides is the box shape's outline; one
// that differs between sides is a line per painted side (pushSideLines). A
// spread-only box-shadow is an outline ring; the first painted outer shadow is
// the shape's shadow. paintsBox says whether a box paints anything of that, and
// the walk and the text layout ask it.
//
// Runs in the page, inside the snapshot IIFE, after GRADIENT_SOURCE:
// splitTopLevelCommas is its free name. It is stringified, so it closes over
// nothing on the Node side; what it needs from the snapshot arrives in `env`,
// functions of snapshotPage documented there:
//   paintedColour     (css colour, opacity) -> {color, alpha} | null, as painted;
//   normalisedAngle   degrees -> the same angle in 0..360;
//   cornerShape       (style, box) -> {geometry, radius}, the box's corners;
//   shownPart         (bounds, clip) -> what the clip shows of them | null;
//   boundsOf          box -> its bounds {left, top, right, bottom};
//   pushShape         shape -> pushes it as a shape item;
//   pushClippedShape  (shape, clip) -> pushes the part of it the clip shows;
//   pushSideLines     (box, sides, order, clip) -> pushes a line per painted side.
// It gives back SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox and
// sliceOf.

function createBorders(env) {
  const {
    paintedColour,
    normalisedAngle,
    cornerShape,
    shownPart,
    boundsOf,
    pushShape,
    pushClippedShape,
    pushSideLines,
  } = env;
  // A border that is the same on all four sides is the shape's outline. A
  // border that differs between sides is a line per painted side (pushSideLines).
  // A spread-only box-shadow is an outline ring (spreadRings).
  const SIDES = ['Top', 'Right', 'Bottom', 'Left'];

  // The dash a border style paints with: dashed and dotted keep theirs, and
  // every other style that paints (solid, double, groove, ridge, inset,
  // outset) is drawn solid.
  function borderDash(style) {
    return style === 'dashed' ? 'dash' : style === 'dotted' ? 'dot' : 'solid';
  }

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
    return { color: painted.color, alpha: painted.alpha, widthPx: width * scale, dash: borderDash(style) };
  }

  // A border that is no single outline, side by side: {widths, painted}.
  //   widths   every side's width in slide px, by side name: 0 where its style
  //            paints nothing or `slice` takes it off. They shape the corners;
  //   painted  {side, color, alpha, widthPx, dash} for each side with a width
  //            and a colour that shows, in Top, Right, Bottom, Left order.
  // `slice` ({Left, Right} booleans, or null) names the sides that
  // box-decoration-break: slice takes off one fragment of an inline box (sliceOf).
  function sideBorders(s, opacity, scale, slice) {
    const widths = {};
    const painted = [];
    for (let index = 0; index < SIDES.length; index++) {
      const side = SIDES[index];
      const style = s['border' + side + 'Style'];
      const off = style === 'none' || style === 'hidden' || Boolean(slice && slice[side]);
      const width = off ? 0 : (parseFloat(s['border' + side + 'Width']) || 0) * scale;
      widths[side] = width;
      if (!(width > 0)) continue;
      const colour = paintedColour(s['border' + side + 'Color'], opacity);
      if (colour) painted.push({ side, color: colour.color, alpha: colour.alpha, widthPx: width, dash: borderDash(style) });
    }
    return { widths, painted };
  }

  // The outer layers of a computed box-shadow, in order: {colourText,
  // offsetX, offsetY, blur, spread}, lengths in the element's own px. Chrome
  // writes each layer colour first, then offset-x, offset-y, blur, spread.
  // Layers split at top-level commas (GRADIENT_SOURCE): the commas inside
  // rgba(...) separate nothing. An inset layer paints inside the box, so it is
  // no outer layer.
  function outerShadowLayers(value) {
    const outer = [];
    if (!value || value === 'none') return outer;
    const layers = splitTopLevelCommas(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      if (/\binset\b/.test(layer)) continue;
      const functional = /^[a-z-]+\([^)]*\)/i.exec(layer);
      const colourText = functional ? functional[0] : layer.split(/\s+/)[0];
      const lengths = (layer.slice(colourText.length).match(/-?[\d.]+(?:e[-+]?\d+)?px/g) || []).map(parseFloat);
      outer.push({
        colourText,
        offsetX: lengths[0] || 0,
        offsetY: lengths[1] || 0,
        blur: lengths[2] || 0,
        spread: lengths[3] || 0,
      });
    }
    return outer;
  }

  // The first painted outer shadow (PowerPoint keeps one per shape). A spread
  // with no blur or offset is an outline ring, not a shadow. The direction is
  // screen-fixed, because the emitted shadow does not rotate with its shape.
  function outerShadow(value, opacity, box) {
    const layers = outerShadowLayers(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      const painted = paintedColour(layer.colourText, opacity);
      if (!painted) continue;
      const offsetX = layer.offsetX;
      const offsetY = layer.offsetY;
      const blur = layer.blur;
      if (layer.spread !== 0 && blur === 0 && offsetX === 0 && offsetY === 0) continue;
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

  // The spread-only layers of a computed box-shadow, in the order listed,
  // which is top first: a layer with no offset and no blur paints a ring as
  // wide as its spread around the border box. Each is the outline it draws,
  // {color, alpha, widthPx, dash: 'solid'}. A spread of 0 or less paints
  // nothing outside the box.
  function spreadRings(value, opacity, box) {
    const rings = [];
    const layers = outerShadowLayers(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      if (!(layer.spread > 0) || layer.blur !== 0 || layer.offsetX !== 0 || layer.offsetY !== 0) continue;
      const painted = paintedColour(layer.colourText, opacity);
      if (painted) rings.push({ color: painted.color, alpha: painted.alpha, widthPx: layer.spread * box.scale, dash: 'solid' });
    }
    return rings;
  }

  // The corner radius of a ring's centre line, for a border box corner of
  // `radius` and a ring as wide as `spread`. The spread shadow's corner is the
  // border radius plus the spread, the spread first scaled by 1 + (r - 1)^3
  // where r = radius / spread is under 1 (CSS Backgrounds 3, box-shadow), so a
  // square corner stays square; the ring runs half way between the two.
  function ringRadius(radius, spread) {
    if (!(radius > 0)) return 0;
    const ratio = radius / spread;
    const outer = radius + (ratio < 1 ? spread * (1 + Math.pow(ratio - 1, 3)) : spread);
    return (radius + outer) / 2;
  }

  // background-clip: text paints the background inside the glyphs only, where
  // the text's own colour carries it (textColour), so it fills no box.
  function clipsToText(s) {
    return /\btext\b/.test(String(s.backgroundClip || '')) || /\btext\b/.test(String(s.webkitBackgroundClip || ''));
  }

  // Whether an element's box paints anything emitBox draws: a fill, a border,
  // an outer shadow or a ring, at its cumulative opacity. Its geometry changes
  // none of them, so an untransformed unit box stands in for it.
  const UNIT_BOX = { scale: 1, rotate: null };
  function paintsBox(s, opacity) {
    return Boolean((!clipsToText(s) && paintedColour(s.backgroundColor, opacity)) ||
      uniformBorder(s, opacity, UNIT_BOX.scale) || outerShadow(s.boxShadow, opacity, UNIT_BOX) ||
      spreadRings(s.boxShadow, opacity, UNIT_BOX).length ||
      sideBorders(s, opacity, UNIT_BOX.scale, null).painted.length);
  }

  // A painted box becomes shapes and lines, cut to its clip, in the order CSS
  // paints a box (CSS 2.1 Appendix E: its shadows under its background, its
  // border over it):
  // * every spread-only ring but the one that is the box's outline, each an
  //   unfilled shape of its own, the last listed lowest;
  // * the box's own shape: its background colour and outer shadow, outlined
  //   by its uniform border or, with none, by its first ring (ringedShape);
  // * a border that differs between sides, over the fill (pushSideLines).
  // The slide root's ground is the slide background (the background transfer,
  // preprocess.mjs, put it on body), so its fill, shadow and rings are never painted a second time here.
  // `slice` is sideBorders': the sides a fragment of an inline box loses.
  // `withoutBorder` leaves the border out: a collapsed native table's border
  // is its grid's outer edges (snapshot_table.mjs).
  function emitBox(s, box, opacity, order, isSlideRoot, clip, slice, withoutBorder) {
    const fill = isSlideRoot || clipsToText(s) ? null : paintedColour(s.backgroundColor, opacity);
    const sliced = Boolean(slice && (slice.Left || slice.Right));
    let line = sliced || withoutBorder ? null : uniformBorder(s, opacity, box.scale);
    const shadow = isSlideRoot ? null : outerShadow(s.boxShadow, opacity, box);
    const rings = isSlideRoot ? [] : spreadRings(s.boxShadow, opacity, box);
    const sides = line || withoutBorder ? null : sideBorders(s, opacity, box.scale, slice);
    if (!fill && !line && !shadow && !rings.length && !(sides && sides.painted.length)) return;
    const corners = cornerShape(s, box);
    // The stroke centred on a bordered shape's edge needs a shape left inside the border box.
    if (line && !(box.w - line.widthPx > 0 && box.h - line.widthPx > 0)) line = null;
    const outlineRing = !line && rings.length ? rings[0] : null;
    for (let index = rings.length - 1; index >= (outlineRing ? 1 : 0); index--) {
      pushBoxShape(ringedShape(box, corners, null, rings[index], null, order), clip);
    }
    if (fill || line || shadow || outlineRing) {
      pushBoxShape(outlineRing
        ? ringedShape(box, corners, fill, outlineRing, shadow, order)
        : borderedShape(box, corners, fill, line, shadow, order), clip);
    }
    if (sides) pushSideLines(box, sides, order, clip);
  }

  // The shape of a box outlined by `line` (or null), which CSS paints inside
  // the border box: the stroke is centred on the shape's edge, so the shape is
  // inset by half the width, its corner radius with it.
  function borderedShape(box, corners, fill, line, shadow, order) {
    const inset = line ? line.widthPx / 2 : 0;
    return boxShape(box, corners, inset, corners.radius - inset, { fill, line, shadow, order, extent: box });
  }

  // The shape of a box outlined by `ring`, which paints outside the border
  // box: grown by half the spread, its corner radius to the ring's centre
  // line. What it paints reaches the ring's outer edge.
  function ringedShape(box, corners, fill, ring, shadow, order) {
    const half = ring.widthPx / 2;
    const extent = { x: box.x - ring.widthPx, y: box.y - ring.widthPx, w: box.w + 2 * ring.widthPx, h: box.h + 2 * ring.widthPx, rotate: box.rotate };
    return boxShape(box, corners, -half, ringRadius(corners.radius, ring.widthPx), { fill, line: ring, shadow, order, extent });
  }

  // `box` moved in by `inset` on every side (out, for a negative one), with
  // the corner geometry and `radius` it keeps. `paint` is {fill, line, shadow,
  // order, extent}: extent is the box whose bounds a clip is held against.
  function boxShape(box, corners, inset, radius, paint) {
    const w = box.w - 2 * inset;
    const h = box.h - 2 * inset;
    let geometry = corners.geometry;
    let cornerRadius = 0;
    if (geometry === 'roundRect') {
      cornerRadius = Math.min(radius, Math.min(w, h) / 2);
      if (!(cornerRadius > 0)) geometry = 'rect';
    }
    return {
      order: paint.order,
      x: box.x + inset,
      y: box.y + inset,
      w,
      h,
      geometry,
      radius: geometry === 'roundRect' ? cornerRadius : 0,
      fill: paint.fill,
      line: paint.line,
      shadow: paint.shadow,
      rotate: box.rotate,
      extent: paint.extent,
    };
  }

  // A shape cut to its clip: whole when the clip cuts nothing it paints (its
  // extent), the part shown of a plain rect, or else the part shown of its
  // outline (pushClippedShape). Nothing when the clip hides it.
  function pushBoxShape(shape, clip) {
    const shown = shownPart(boundsOf(shape.extent), clip);
    if (!shown) return;
    if (!shown.cut) {
      pushShape(shape);
    } else if (shape.geometry === 'rect' && !shape.rotate && !shape.line) {
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

  // The sides box-decoration-break: slice takes off one fragment of an inline
  // box: its inline start on every fragment but the first, its inline end on
  // every fragment but the last. Null for a box in one fragment, or one that
  // clones its decoration onto each.
  function sliceOf(decoration, fragment) {
    const count = decoration.boxes.length;
    const s = decoration.style;
    const mode = String(s.boxDecorationBreak || s.webkitBoxDecorationBreak || 'slice');
    if (count < 2 || mode === 'clone') return null;
    const notFirst = fragment > 0;
    const notLast = fragment < count - 1;
    return s.direction === 'rtl' ? { Left: notLast, Right: notFirst } : { Left: notFirst, Right: notLast };
  }

  return { SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox, sliceOf };
}

export const BORDERS_SOURCE = createBorders.toString();
