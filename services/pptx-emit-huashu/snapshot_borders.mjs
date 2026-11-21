// Borders and rings: what a painted box draws besides its fill, as the
// snapshot (snapshot.mjs) emits a box. snapshot.mjs composes BORDERS_SOURCE
// into its page IIFE and makes it once (createBorders); emitBox is what its
// walk calls for every box that paints.
//
// A border that is the same on all four sides is the box shape's outline; one
// that differs between sides is a line per painted side (pushSideLines). Each
// layer of a box-shadow is drawn in the order CSS paints the layers: a
// spread-only layer is a ring, the box's outline when it is opaque and on top;
// a blurred or offset layer is an outer shadow, the box's own when the box's
// fill is opaque and the layer the first, and else a shadow shape of its own
// under the box (shadowShape). paintsBox says whether a box paints anything of
// that, and the walk and the text layout ask it.
//
// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE and
// GRADIENT_SOURCE and with emit_typography.cjs's blendOver:
// COLLECTION_ITEM_LIMIT, splitTopLevelCommas and blendOver are its free names.
// It is stringified, so it closes over nothing on the Node side;
// what it needs from the snapshot arrives in `env`, functions of snapshotPage
// documented there:
//   paintedColour     (css colour, opacity) -> {color, alpha} | null, as painted;
//   normalisedAngle   degrees -> the same angle in 0..360;
//   cornerShape       (style, box) -> {geometry, radius}, the box's corners;
//   shownPart         (bounds, clip) -> what the clip shows of them | null;
//   boundsOf          box -> its bounds {left, top, right, bottom};
//   pushShape         shape -> pushes it as a shape item, and returns the item;
//   pushClippedShape  (shape, clip) -> pushes the part of it the clip shows, and
//                     returns the items pushed;
//   pushSideLines     (box, sides, order, clip) -> pushes a line per painted side.
// It gives back SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox,
// resolveShadowShapes and sliceOf.

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
  // A spread-only box-shadow layer is a ring (paintedLayers).
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

  // The outer layers of a computed box-shadow that paint, in the order listed,
  // which is top first, each {ring, shadow, spreadPx}:
  //   ring     a layer with no blur and no offset paints a ring as wide as its
  //            spread around the border box: the outline it draws, {color,
  //            alpha, widthPx, dash: 'solid'}; such a layer with a spread of 0
  //            or less paints nothing outside the box and is no layer here;
  //   shadow   a blurred or offset layer: the outer shadow it casts, {color,
  //            alpha, blurPx, offsetPx, angle}. An outer shadow has no spread,
  //            so spreadPx, the layer's own in slide px, is for the shape that
  //            casts it (shadowShape). The direction is screen-fixed, because
  //            the emitted shadow does not rotate with its shape.
  function paintedLayers(value, opacity, box) {
    const painted = [];
    const layers = outerShadowLayers(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      const colour = paintedColour(layer.colourText, opacity);
      if (!colour) continue;
      if (layer.blur === 0 && layer.offsetX === 0 && layer.offsetY === 0) {
        if (layer.spread > 0) {
          painted.push({ ring: { color: colour.color, alpha: colour.alpha, widthPx: layer.spread * box.scale, dash: 'solid' }, shadow: null, spreadPx: 0 });
        }
        continue;
      }
      painted.push({
        ring: null,
        shadow: {
          color: colour.color,
          alpha: colour.alpha,
          blurPx: layer.blur * box.scale,
          offsetPx: Math.hypot(layer.offsetX, layer.offsetY) * box.scale,
          angle: normalisedAngle(Math.atan2(layer.offsetY, layer.offsetX) * 180 / Math.PI + (box.rotate || 0)),
        },
        spreadPx: layer.spread * box.scale,
      });
    }
    return painted;
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
      uniformBorder(s, opacity, UNIT_BOX.scale) || paintedLayers(s.boxShadow, opacity, UNIT_BOX).length ||
      sideBorders(s, opacity, UNIT_BOX.scale, null).painted.length);
  }

  // What a shadow shape's role is, which emit_model.cjs names it by.
  const SHADOW_ROLE = 'shadow';
  // The shadow shapes of boxes that paint no opaque fill, to be filled once
  // every item is known (resolveShadowShapes): {shapes, box, shadow, footprint}.
  const pendingShadows = [];

  // A painted box becomes shapes and lines, cut to its clip, in the order CSS
  // paints a box (CSS 2.1 Appendix E: its shadows under its background, its
  // border over it):
  // * its box-shadow layers, the last listed lowest (CSS Backgrounds 3):
  //   - a ring, a spread-only layer: an unfilled shape of its own, unless it is
  //     the box's outline. It is that when it is the first layer listed (no
  //     shadow paints over it), it is opaque, and the box has no uniform
  //     border. A translucent ring shows what lies under it, which is never
  //     the box's fill (a box-shadow paints outside the border box only), so
  //     its box keeps its fill at the border box;
  //   - a shadow, a blurred or offset layer: the box's own when the box's fill
  //     is opaque, this is the first such layer and no ring listed before it is
  //     a shape of its own, since one shape carries one outer shadow, a shadow
  //     under an opaque fill shows outside the box alone, and a box's shadow
  //     paints with the box, over every shape under it; every other one a
  //     shadow shape of its own (shadowShape). Under a
  //     box with no fill, or a translucent one, every shadow is a shadow shape:
  //     neither app casts a shadow from an unfilled shape, and both draw one
  //     under a translucent fill, through it, where the browser shows what
  //     lies beneath the box. Those shapes are filled once the slide is known
  //     (resolveShadowShapes); until then the box carries its first shadow;
  // * the box's own shape: its background colour and its shadow, outlined by
  //   its uniform border or else by its outline ring (ringedShape);
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
    const layers = isSlideRoot ? [] : paintedLayers(s.boxShadow, opacity, box);
    const sides = line || withoutBorder ? null : sideBorders(s, opacity, box.scale, slice);
    if (!fill && !line && !layers.length && !(sides && sides.painted.length)) return;
    const corners = cornerShape(s, box);
    // The stroke centred on a bordered shape's edge needs a shape left inside the border box.
    if (line && !(box.w - line.widthPx > 0 && box.h - line.widthPx > 0)) line = null;
    const top = layers.length ? layers[0] : null;
    const outlineRing = !line && top && top.ring && top.ring.alpha >= 1 ? top.ring : null;
    const opaque = Boolean(fill) && fill.alpha >= 1;
    let firstShadow = null;
    // A ring listed before the first shadow paints over it (Tailwind's ring,
    // then shadow); drawn as a shape under the box, it would lie under the
    // box's own shadow, so then every shadow is a shape, in order.
    let ringOverShadow = false;
    for (let index = 0; index < layers.length && !firstShadow; index++) {
      if (layers[index].shadow) firstShadow = layers[index];
      else if (layers[index].ring !== outlineRing) ringOverShadow = true;
    }
    const ownShadow = opaque && !ringOverShadow ? firstShadow : null;
    // What the shadow shapes of a box with no opaque fill cover at most: its border box.
    const footprint = { x: box.x, y: box.y, w: box.w, h: box.h, geometry: corners.geometry, radius: corners.radius, rotate: box.rotate };
    const pending = !opaque && firstShadow ? { shapes: [], box: [], shadow: firstShadow.shadow, footprint } : null;
    for (let index = layers.length - 1; index >= 0; index--) {
      const layer = layers[index];
      if (layer.ring) {
        if (layer.ring !== outlineRing) pushBoxShape(ringedShape(box, corners, null, layer.ring, null, order), clip);
        continue;
      }
      if (layer === ownShadow) continue;
      const shape = shadowShape(box, corners, layer, opaque ? { color: fill.color, alpha: 1 } : null, order);
      if (!shape) continue;
      const pushed = pushBoxShape(shape, clip);
      for (let item = 0; item < pushed.length; item++) {
        pushed[item].role = SHADOW_ROLE;
        if (pending) pending.shapes.push(pushed[item]);
      }
    }
    const shadow = ownShadow ? ownShadow.shadow : pending ? pending.shadow : null;
    if (fill || line || shadow || outlineRing) {
      const pushed = pushBoxShape(outlineRing
        ? ringedShape(box, corners, fill, outlineRing, shadow, order)
        : borderedShape(box, corners, fill, line, shadow, order), clip);
      if (pending) pending.box = pushed;
    }
    if (pending && pending.shapes.length) pendingShadows.push(pending);
    if (sides) pushSideLines(box, sides, order, clip);
  }

  // The shape that casts a shadow layer its box's own shape does not: the
  // border box and its corners, moved in by a negative spread with its radii
  // (CSS Backgrounds 3: the spread shadow's radii are the border radii plus the
  // spread, floored at 0), filled `fill`, unoutlined. Drawn under its box, it
  // shows nothing but its shadow. A positive spread is not drawn, as for the
  // box's own shadow: grown past the box, the shape would show. Null for a
  // spread that leaves no shape, which paints nothing.
  function shadowShape(box, corners, layer, fill, order) {
    const inset = layer.spreadPx < 0 ? -layer.spreadPx : 0;
    if (!(box.w - 2 * inset > 0 && box.h - 2 * inset > 0)) return null;
    return boxShape(box, corners, inset, Math.max(0, corners.radius - inset), { fill, line: null, shadow: layer.shadow, order, extent: box });
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
  // outline (pushClippedShape). Nothing when the clip hides it. Returns the
  // items pushed.
  function pushBoxShape(shape, clip) {
    const shown = shownPart(boundsOf(shape.extent), clip);
    if (!shown) return [];
    if (!shown.cut) return [pushShape(shape)];
    if (shape.geometry === 'rect' && !shape.rotate && !shape.line) {
      // A plain rect the clip cuts is the rect it shows (no line, so no inset).
      return [pushShape({
        ...shape,
        x: shown.left,
        y: shown.top,
        w: shown.right - shown.left,
        h: shown.bottom - shown.top,
      })];
    }
    return pushClippedShape(shape, clip);
  }

  // ─── the fill of shadow shapes ───────────────────────────────────────
  // The shadow shapes of a box that paints no opaque fill must show nothing
  // but their shadow, so each is filled with the one colour the slide shows
  // beneath it: what the export itself paints there, read from the items under
  // it in paint order (`items` sorted back to front) over the slide's ground
  // colour (`background`). That colour is known only when the box is unturned
  // and everything under its shapes that reaches into its border box is a
  // plain shape that covers that box whole with a fill (or paints nothing
  // inside it), down to an opaque one or to a ground of a colour. Then the
  // shapes take it and the box casts nothing itself. Otherwise (text, a
  // picture, a line, a table, a shape's edge or its translucent shadow there,
  // or a picture ground) a filled shape would hide what shows through the box,
  // so the shapes are dropped and the box keeps its first shadow, as with no
  // shapes at all. Returns the items left, in order, and how many it dropped.
  // Comparing each box with what lies under it is bounded, in all, by
  // COLLECTION_ITEM_LIMIT steps: past that, the rest keep their box's shadow.
  // Bounds within this of each other only touch (layout rounding).
  const TOUCH_EPSILON_PX = 0.01;
  // A round corner of a footprint is tested at this many points along its arc.
  const ARC_TEST_POINTS = 6;

  function resolveShadowShapes(items, background) {
    if (!pendingShadows.length) return { items, dropped: 0 };
    const positions = new Map();
    for (let index = 0; index < items.length && index < COLLECTION_ITEM_LIMIT; index++) positions.set(items[index], index);
    const dropped = new Set();
    let budget = COLLECTION_ITEM_LIMIT;
    for (let group = 0; group < pendingShadows.length; group++) {
      const pending = pendingShadows[group];
      let lowest = Infinity;
      for (let index = 0; index < pending.shapes.length; index++) {
        const position = positions.get(pending.shapes[index]);
        if (position !== undefined) lowest = Math.min(lowest, position);
      }
      const beneath = Number.isFinite(lowest) && !pending.footprint.rotate
        ? colourBeneath(items, lowest, pending.footprint, background, budget)
        : { color: null, budget };
      budget = beneath.budget;
      if (beneath.color) {
        for (let index = 0; index < pending.shapes.length; index++) pending.shapes[index].fill = { color: beneath.color, alpha: 1 };
        for (let index = 0; index < pending.box.length; index++) {
          const item = pending.box[index];
          item.shadow = null;
          // A shape whose only paint was the shadow now paints nothing.
          if (!item.fill && !item.line) dropped.add(item);
        }
      } else {
        for (let index = 0; index < pending.shapes.length; index++) dropped.add(pending.shapes[index]);
      }
    }
    if (!dropped.size) return { items, dropped: 0 };
    const kept = [];
    for (let index = 0; index < items.length && index < COLLECTION_ITEM_LIMIT; index++) {
      if (!dropped.has(items[index])) kept.push(items[index]);
    }
    return { items: kept, dropped: dropped.size };
  }

  // {color, budget}: the one colour the items under items[position] paint over
  // the unturned `footprint` ({x, y, w, h, geometry, radius}), on the slide's
  // ground, or color null when they paint no one colour there
  // (resolveShadowShapes); budget is what is left of `budget`.
  function colourBeneath(items, position, footprint, background, budget) {
    const bounds = { left: footprint.x, top: footprint.y, right: footprint.x + footprint.w, bottom: footprint.y + footprint.h };
    const outline = outlinePoints(footprint);
    const covers = [];
    let base = null;
    for (let index = position - 1; index >= 0; index--) {
      if (--budget < 0) return { color: null, budget: 0 };
      const item = items[index];
      if (!reaches(item, bounds)) continue;
      if (!coversWith(item, outline)) return { color: null, budget };
      if (!item.fill) continue;
      if (item.fill.alpha >= 1) {
        base = item.fill.color;
        break;
      }
      covers.push(item.fill);
    }
    if (base === null) {
      if (!background || !background.color || background.image) return { color: null, budget };
      base = background.color;
    }
    let colour = base;
    for (let index = covers.length - 1; index >= 0; index--) colour = blendOver(covers[index].color, covers[index].alpha, colour);
    return { color: colour, budget };
  }

  // Whether what an item paints reaches into `bounds` past their edges: its
  // box, with a line's or an outline's half width and a shadow's blur and
  // offset around it.
  function reaches(item, bounds) {
    let painted;
    if (item.kind === 'line') {
      const half = (Number(item.widthPx) || 0) / 2;
      painted = {
        left: Math.min(item.x1, item.x2) - half,
        top: Math.min(item.y1, item.y2) - half,
        right: Math.max(item.x1, item.x2) + half,
        bottom: Math.max(item.y1, item.y2) + half,
      };
    } else if (item.kind === 'table') {
      let width = 0;
      let height = 0;
      for (let index = 0; index < item.colWidths.length && index < COLLECTION_ITEM_LIMIT; index++) width += item.colWidths[index];
      for (let index = 0; index < item.rowHeights.length && index < COLLECTION_ITEM_LIMIT; index++) height += item.rowHeights[index];
      painted = { left: item.x, top: item.y, right: item.x + width, bottom: item.y + height };
    } else {
      painted = boundsOf(item);
      if (item.kind === 'shape') {
        const reach = (item.line ? item.line.widthPx / 2 : 0) + (item.shadow ? item.shadow.blurPx + item.shadow.offsetPx : 0);
        painted = { left: painted.left - reach, top: painted.top - reach, right: painted.right + reach, bottom: painted.bottom + reach };
      }
    }
    return painted.left < bounds.right - TOUCH_EPSILON_PX && painted.right > bounds.left + TOUCH_EPSILON_PX &&
      painted.top < bounds.bottom - TOUCH_EPSILON_PX && painted.bottom > bounds.top + TOUCH_EPSILON_PX;
  }

  // Whether an item that reaches into a footprint paints it with its fill
  // alone or not at all: an unturned rect, roundRect or ellipse whose fill
  // holds every point of the footprint's `outline` (outlinePoints), inside its
  // own outline's inner edge, with no shadow that shows through a translucent
  // fill. Both are convex, so holding the outline is holding the footprint.
  function coversWith(item, outline) {
    if (item.kind !== 'shape' || item.rotate || item.geometry === 'path') return false;
    if (item.shadow && !(item.fill && item.fill.alpha >= 1)) return false;
    const inset = item.line ? item.line.widthPx / 2 : 0;
    const inner = { x: item.x + inset, y: item.y + inset, w: item.w - 2 * inset, h: item.h - 2 * inset };
    if (!(inner.w > 0 && inner.h > 0)) return false;
    const radius = item.geometry === 'roundRect' ? Math.max(0, item.radius - inset) : 0;
    for (let index = 0; index < outline.length; index++) {
      if (!holds(item.geometry, inner, radius, outline[index])) return false;
    }
    return true;
  }

  // Points on the outline of a footprint ({x, y, w, h, geometry, radius}): a
  // rect's corners, a rounded rect's corner arcs, an ellipse's arc.
  function outlinePoints(footprint) {
    const points = [];
    const right = footprint.x + footprint.w;
    const bottom = footprint.y + footprint.h;
    if (footprint.geometry === 'ellipse') {
      for (let step = 0; step < 4 * ARC_TEST_POINTS; step++) {
        const angle = (2 * Math.PI * step) / (4 * ARC_TEST_POINTS);
        points.push({
          x: footprint.x + footprint.w / 2 * (1 + Math.cos(angle)),
          y: footprint.y + footprint.h / 2 * (1 + Math.sin(angle)),
        });
      }
      return points;
    }
    const radius = footprint.geometry === 'roundRect' ? Math.min(footprint.radius, footprint.w / 2, footprint.h / 2) : 0;
    const centres = [
      { x: footprint.x + radius, y: footprint.y + radius, start: Math.PI },
      { x: right - radius, y: footprint.y + radius, start: 1.5 * Math.PI },
      { x: right - radius, y: bottom - radius, start: 0 },
      { x: footprint.x + radius, y: bottom - radius, start: 0.5 * Math.PI },
    ];
    for (let corner = 0; corner < centres.length; corner++) {
      const centre = centres[corner];
      const steps = radius > 0 ? ARC_TEST_POINTS : 0;
      for (let step = 0; step <= steps; step++) {
        const angle = centre.start + (Math.PI / 2) * (steps ? step / steps : 0.5);
        points.push({ x: centre.x + radius * Math.cos(angle), y: centre.y + radius * Math.sin(angle) });
      }
    }
    return points;
  }

  // Whether the point lies in the rect, rounded rect or ellipse `box`.
  function holds(geometry, box, radius, point) {
    const right = box.x + box.w;
    const bottom = box.y + box.h;
    if (point.x < box.x - TOUCH_EPSILON_PX || point.x > right + TOUCH_EPSILON_PX ||
        point.y < box.y - TOUCH_EPSILON_PX || point.y > bottom + TOUCH_EPSILON_PX) return false;
    if (geometry === 'ellipse') {
      const dx = (point.x - (box.x + box.w / 2)) / (box.w / 2);
      const dy = (point.y - (box.y + box.h / 2)) / (box.h / 2);
      return dx * dx + dy * dy <= 1 + TOUCH_EPSILON_PX;
    }
    if (!(radius > 0)) return true;
    const centreX = Math.min(Math.max(point.x, box.x + radius), right - radius);
    const centreY = Math.min(Math.max(point.y, box.y + radius), bottom - radius);
    return Math.hypot(point.x - centreX, point.y - centreY) <= radius + TOUCH_EPSILON_PX;
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

  return { SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox, resolveShadowShapes, sliceOf };
}

export const BORDERS_SOURCE = createBorders.toString();
