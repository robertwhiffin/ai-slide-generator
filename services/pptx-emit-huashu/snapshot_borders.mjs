// Borders and rings: what a painted box draws besides its fill, as the
// snapshot (snapshot.mjs) emits a box. snapshot.mjs composes BORDERS_SOURCE
// into its page IIFE and makes it once (createBorders); emitBox is what its
// walk calls for every box that paints.
//
// A border that is the same on all four sides is the box shape's outline; one
// that differs between sides is a line per painted side, or, on a box whose
// corners round, the region CSS paints for each solid side (pushSideBorders). A
// spread-only box-shadow layer is a ring: the box's outline when it is opaque
// and on top, else an unfilled shape of its own. The blurred or offset layers
// are the box's one outer shadow, on its own shape (shadowOf): one layer as it
// is, more than one fitted to the one closest to them all. paintsBox says
// whether a box paints anything of that, and the walk and the text layout ask
// it.
//
// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE and
// GRADIENT_SOURCE: splitTopLevelCommas and diagnose are its free names. It is
// stringified, so it closes over nothing on the Node side;
// what it needs from the snapshot arrives in `env`, functions of snapshotPage
// documented there:
//   paintedColour     (css colour, opacity) -> {color, alpha} | null, as painted;
//   normalisedAngle   degrees -> the same angle in 0..360;
//   cornerShape       (style, box) -> {geometry, radius, radii}, the box's corners;
//   cornerGeometry    corners [{h, v}] -> {geometry, radius, radii}, as cornerShape
//                     classes the four corners of a box that is no ellipse;
//   shownPart         (bounds, clip) -> what the clip shows of them | null;
//   boundsOf          box -> its bounds {left, top, right, bottom};
//   pushShape         shape -> pushes it as a shape item, and returns the item;
//   pushClippedShape  (shape, clip) -> pushes the part of it the clip shows, and
//                     returns the items pushed;
//   roundsCut         (shape, clip) -> whether the clip's rounded padding boxes
//                     (its rounds) cut what its rect shows of the shape;
//   usedCornerRadii   (style, box) -> its corners' used radii [{h, v}], top left first;
//   pushSideLines     (box, sides, order, clip) -> pushes each painted side as a
//                     line along it (or the triangle a side with no inner edge
//                     paints);
//   pushPath          (order, polylines, closed, fill, line, shadow) -> pushes a
//                     custom path shape;
//   clipPolygon       (points, clip) -> what the clip's rect shows of a polygon;
//   clipConvex        (points, clipper) -> a polygon cut to a convex one;
//   cuttingRounds     (clip, points, grow) -> the clip's rounded padding boxes that
//                     cut the points, as convex polygons;
//   arcSteps          radius -> the segments that stand for a quarter arc of it
//                     within the snapshot's arc tolerance.
// It gives back SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox,
// reportShadowFits and sliceOf.

function createBorders(env) {
  const {
    paintedColour,
    normalisedAngle,
    cornerShape,
    cornerGeometry,
    shownPart,
    boundsOf,
    pushShape,
    pushClippedShape,
    roundsCut,
    usedCornerRadii,
    pushSideLines,
    pushPath,
    clipPolygon,
    clipConvex,
    cuttingRounds,
    arcSteps,
  } = env;
  // A border that is the same on all four sides is the shape's outline. A
  // border that differs between sides is a line per painted side, or each
  // solid side's region on a box whose corners round (pushSideBorders).
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

  // ─── border regions ──────────────────────────────────────────────────
  // A box whose corners round and whose border differs between sides paints
  // each solid side as CSS does (CSS Backgrounds 3 §5), not as a line along
  // it, whose square ends would stand out past the cut-away corners:
  // * the border area lies between the rounded border box and the rounded
  //   padding box, each inner radius the outer one less the border beside it,
  //   floored at 0 (a corner either of whose radii is then 0 is square), and
  //   not scaled where two of them overlap their side: Chrome draws them as
  //   they are (measured: scaled, a 170 px corner beside a square one lost
  //   17 of the browser's border pixels);
  // * a side's part of it runs between the lines that divide it from its
  //   neighbours at the corners, each from the border box's corner through
  //   the padding box's (Chrome's border painter: the line a square corner's
  //   miter is). Where the neighbour has no width that line runs along the
  //   neighbour's edge, so the side runs on round the corner to where its
  //   outer and inner edges meet, tapering to nothing where the radius is the
  //   wider;
  // * neighbouring sides painted alike are one region together, so no seam
  //   divides them, and four alike (their widths differing) are one too: the
  //   whole border area, its edge cut open along the top left corner's
  //   dividing line, round the box from there and back, so it is one simple
  //   polygon whose edge runs out along that line and back, no ring. Split in
  //   two regions meeting along the dividing lines, Google Slides drew an
  //   anti-aliased seam on each line, 19 to 64 levels lighter than the
  //   border's colour.
  // Each region is one filled path, its arcs polygons within the snapshot's
  // arc tolerance (arcSteps), turned with the box and cut to the clip, its
  // rect and then any rounded padding box of it, as a side's triangle is.
  // Dashed and dotted sides stay lines (pushSideLines). A box whose padding
  // box is empty, and a box no corner of which rounds, keep a line per side.
  // Each side's place in SIDES, which is the index of the corner it starts at clockwise.
  const SIDE_INDEX = { Top: 0, Right: 1, Bottom: 2, Left: 3 };

  // The corners of `box`, clockwise from the top left, in slide px before any
  // turn: each {x, y} its border box corner, {sx, sy} the way into the box,
  // wx and wy the widths of the sides that meet there across x and across y,
  // {h, v} its outer radii and {ih, iv} its inner ones, and the sides before
  // and after it clockwise. Null when the padding box is empty.
  function borderCorners(box, widths, radii) {
    const right = box.x + box.w;
    const bottom = box.y + box.h;
    const corners = [
      { x: box.x, y: box.y, sx: 1, sy: 1, wx: widths.Left, wy: widths.Top, before: 'Left', after: 'Top' },
      { x: right, y: box.y, sx: -1, sy: 1, wx: widths.Right, wy: widths.Top, before: 'Top', after: 'Right' },
      { x: right, y: bottom, sx: -1, sy: -1, wx: widths.Right, wy: widths.Bottom, before: 'Right', after: 'Bottom' },
      { x: box.x, y: bottom, sx: 1, sy: -1, wx: widths.Left, wy: widths.Bottom, before: 'Bottom', after: 'Left' },
    ];
    const innerW = box.w - widths.Left - widths.Right;
    const innerH = box.h - widths.Top - widths.Bottom;
    if (!(innerW > 0 && innerH > 0)) return null;
    for (let index = 0; index < corners.length; index++) {
      const corner = corners[index];
      const radius = radii[index];
      const rounds = radius.h > 0 && radius.v > 0;
      corner.h = rounds ? radius.h : 0;
      corner.v = rounds ? radius.v : 0;
      const ih = rounds ? Math.max(0, radius.h - corner.wx) : 0;
      const iv = rounds ? Math.max(0, radius.v - corner.wy) : 0;
      corner.ih = ih > 0 && iv > 0 ? ih : 0;
      corner.iv = ih > 0 && iv > 0 ? iv : 0;
    }
    return corners;
  }

  // Where the line dividing a corner's two sides crosses one of its
  // quarter-ellipses, as the ellipse's parameter t: a point at t lies
  // (a + h (1 - cos t), b + v (1 - sin t)) into the box from the corner, (a, b)
  // the quarter's own corner (the border box's for the outer edge, the padding
  // box's, (wx, wy), for the inner), so t is 0 on the side across x and pi/2
  // on the side across y. The line runs from the border box's corner along
  // (wx, wy), through the padding box's corner, so in either quarter's frame
  // it is the ray from its own corner along (wx, wy): the nearer root of
  // (s wx / h - 1)^2 + (s wy / v - 1)^2 = 1. A neighbour with no width puts
  // the crossing at the quarter's end on that neighbour's side.
  function crossingParameter(wx, wy, h, v) {
    const p = wx / h;
    const q = wy / v;
    const along = ((p + q) - Math.sqrt(2 * p * q)) / (p * p + q * q);
    return Math.atan2(1 - along * q, 1 - along * p);
  }

  // The points of a corner's outer (inner false) or inner quarter from
  // parameter `from` to `to` (crossingParameter's), in slide px before any
  // turn, appended to `points`; a square corner's one point.
  function cornerArc(corner, inner, from, to, points) {
    const h = inner ? corner.ih : corner.h;
    const v = inner ? corner.iv : corner.v;
    const offsetA = inner ? corner.wx : 0;
    const offsetB = inner ? corner.wy : 0;
    if (!(h > 0 && v > 0)) {
      points.push({ x: corner.x + corner.sx * offsetA, y: corner.y + corner.sy * offsetB });
      return;
    }
    const steps = Math.max(1, Math.ceil(arcSteps(Math.max(h, v)) * Math.abs(to - from) / (Math.PI / 2)));
    for (let step = 0; step <= steps; step++) {
      const angle = from + (to - from) * (step / steps);
      points.push({
        x: corner.x + corner.sx * (offsetA + h * (1 - Math.cos(angle))),
        y: corner.y + corner.sy * (offsetB + v * (1 - Math.sin(angle))),
      });
    }
  }

  // The parameter at which a corner's outer (inner false) or inner quarter
  // meets one of its sides: 0 on the side across x (Left, Right), pi/2 on
  // the side across y (Top, Bottom).
  function sideParameter(side) {
    return side === 'Top' || side === 'Bottom' ? Math.PI / 2 : 0;
  }

  // Where a corner's dividing line crosses its outer (inner false) or inner
  // quarter, as crossingParameter's parameter; 0 for a square quarter, whose
  // one point is the crossing.
  function dividingParameter(corner, inner) {
    const h = inner ? corner.ih : corner.h;
    const v = inner ? corner.iv : corner.v;
    if (!(h > 0 && v > 0)) return 0;
    return crossingParameter(corner.wx, corner.wy, h, v);
  }

  // The runs of solid painted sides one region each draws, in clockwise
  // order from the top: each {sides: [name], paint: {color, alpha}}.
  // Neighbours painted alike share a run, and four alike are one, from the top.
  function borderRuns(solid) {
    const same = (a, b) => Boolean(a && b && a.color === b.color && a.alpha === b.alpha);
    let start = -1;
    for (let index = 0; index < SIDES.length && start < 0; index++) {
      const side = solid[SIDES[index]];
      if (side && !same(solid[SIDES[(index + SIDES.length - 1) % SIDES.length]], side)) start = index;
    }
    if (start < 0) {
      if (!solid.Top) return [];
      return [{ sides: ['Top', 'Right', 'Bottom', 'Left'], paint: solid.Top }];
    }
    const runs = [];
    let run = null;
    for (let step = 0; step < SIDES.length; step++) {
      const name = SIDES[(start + step) % SIDES.length];
      const side = solid[name];
      if (!side) {
        run = null;
        continue;
      }
      if (run && same(run.paint, side)) {
        run.sides.push(name);
        continue;
      }
      run = { sides: [name], paint: side };
      runs.push(run);
    }
    return runs;
  }

  // The border region of a run of sides (borderRuns), as a polygon in slide
  // px before any turn: its outer edge clockwise from the dividing line at
  // its first side's start corner to the one at its last side's end corner,
  // each corner within the run whole, then its inner edge back. For all four
  // sides both are the top left corner's: the edges run round the whole box,
  // the top left corner in two pieces, one at each end.
  function runRegion(corners, sides) {
    const cornerBefore = (side) => corners[SIDE_INDEX[side]];
    const cornerAfter = (side) => corners[(SIDE_INDEX[side] + 1) % corners.length];
    const edge = (inner) => {
      const points = [];
      const first = cornerBefore(sides[0]);
      cornerArc(first, inner, dividingParameter(first, inner), sideParameter(first.after), points);
      for (let index = 0; index + 1 < sides.length; index++) {
        const corner = cornerAfter(sides[index]);
        cornerArc(corner, inner, sideParameter(corner.before), sideParameter(corner.after), points);
      }
      const last = cornerAfter(sides[sides.length - 1]);
      cornerArc(last, inner, sideParameter(last.before), dividingParameter(last, inner), points);
      return points;
    };
    const outer = edge(false);
    const inner = edge(true);
    for (let index = inner.length - 1; index >= 0; index--) outer.push(inner[index]);
    return outer;
  }

  // Pushes the border regions of a box's solid painted sides, the rest as
  // lines (pushSideLines). `radii` are its used corner radii (usedCornerRadii),
  // or null for a box drawn with a line per side whatever its corners (a
  // fragment box-decoration-break slices). A box no corner of which rounds,
  // or whose padding box is empty, is a line per side.
  function pushSideBorders(box, sides, radii, order, clip) {
    let rounds = false;
    for (let index = 0; radii && index < radii.length; index++) {
      if (radii[index].h > 0 && radii[index].v > 0) rounds = true;
    }
    const corners = rounds ? borderCorners(box, sides.widths, radii) : null;
    if (!corners) {
      pushSideLines(box, sides, order, clip);
      return;
    }
    // Every side an own property, so a side that is not solid reads null, never
    // a value page script set on Object.prototype.
    const solid = { Top: null, Right: null, Bottom: null, Left: null };
    const lines = [];
    for (let index = 0; index < sides.painted.length; index++) {
      const side = sides.painted[index];
      if (side.dash === 'solid') solid[side.side] = side;
      else lines.push(side);
    }
    const centreX = box.x + box.w / 2;
    const centreY = box.y + box.h / 2;
    const radians = (box.rotate || 0) * Math.PI / 180;
    const runs = borderRuns(solid);
    for (let index = 0; index < runs.length; index++) {
      const points = runRegion(corners, runs[index].sides);
      let region = [];
      for (let point = 0; point < points.length; point++) {
        const dx = points[point].x - centreX;
        const dy = points[point].y - centreY;
        region.push(radians
          ? {
            x: centreX + dx * Math.cos(radians) - dy * Math.sin(radians),
            y: centreY + dx * Math.sin(radians) + dy * Math.cos(radians),
          }
          : points[point]);
      }
      region = clipPolygon(region, clip);
      const cutting = cuttingRounds(clip, region, 0);
      for (let round = 0; round < cutting.length && region.length; round++) region = clipConvex(region, cutting[round]);
      const paint = runs[index].paint;
      if (region.length >= 3) pushPath(order, [region], true, { color: paint.color, alpha: paint.alpha }, null, null);
    }
    if (lines.length) pushSideLines(box, { widths: sides.widths, painted: lines }, order, clip);
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
  // which is top first, each {ring, shadow}:
  //   ring     a layer with no blur and no offset paints a ring as wide as its
  //            spread around the border box: the outline it draws, {color,
  //            alpha, widthPx, dash: 'solid'}; such a layer with a spread of 0
  //            or less paints nothing outside the box and is no layer here;
  //   shadow   a blurred or offset layer as CSS gives it, in the element's own
  //            px: {color, alpha, x, y, blur, spread}. shadowOf writes a box's
  //            shadow layers as its one outer shadow.
  function paintedLayers(value, opacity, box) {
    const painted = [];
    const layers = outerShadowLayers(value);
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      const colour = paintedColour(layer.colourText, opacity);
      if (!colour) continue;
      if (layer.blur === 0 && layer.offsetX === 0 && layer.offsetY === 0) {
        if (layer.spread > 0) {
          painted.push({ ring: { color: colour.color, alpha: colour.alpha, widthPx: layer.spread * box.scale, dash: 'solid' }, shadow: null });
        }
        continue;
      }
      painted.push({
        ring: null,
        shadow: { color: colour.color, alpha: colour.alpha, x: layer.offsetX, y: layer.offsetY, blur: layer.blur, spread: layer.spread },
      });
    }
    return painted;
  }

  // The one outer shadow a box's shadow layers (paintedLayers) are written as,
  // {color, alpha, blurPx, offsetPx, angle} in slide px, or null for none that
  // shows. One shape carries one outer shadow (a:outerShdw), in either app. One
  // layer with no spread is that layer; any other set, the one layer closest to
  // them all (fittedLayer), since an outer shadow has no spread. The offset is
  // the element's own, turned with it; the direction is screen-fixed, because
  // the emitted shadow does not rotate with its shape.
  function shadowOf(shadows, box) {
    const exact = shadows.length === 1 && shadows[0].spread === 0;
    const layer = exact ? shadows[0] : fittedLayer(shadows);
    // A fit may find no alpha to keep (pptxgenjs would write a falsy one at 0.75).
    if (!exact && !(layer.alpha >= FIT_ALPHA_STEP)) return null;
    return {
      color: layer.color,
      alpha: layer.alpha,
      blurPx: layer.blur * box.scale,
      offsetPx: Math.hypot(layer.x, layer.y) * box.scale,
      angle: normalisedAngle(Math.atan2(layer.y, layer.x) * 180 / Math.PI + (box.rotate || 0)),
    };
  }

  // The fitted shadow (scripts/export_fidelity/CALIBRATION.md, D4 and D5): of
  // the single layers with no spread, the one whose shadow is closest to the
  // layers' own together. A layer (offset x, y; blur B, sigma = B / 2; spread
  // s; alpha a) covers a point d px outside a long edge of the box, n its
  // outward normal, a * Q((d - (x, y).n - s) / sigma), Q the standard normal's
  // upper tail (a step where there is no blur), and layers compose as
  // 1 - prod(1 - c) (CSS Backgrounds 3: the shadow is the box offset, spread
  // and blurred by a Gaussian of half the blur radius). The fit is the layer
  // whose coverage differs least from theirs, summed and squared, over the
  // four edges at d = k R / FIT_SAMPLES, k = 0..FIT_SAMPLES, R the layers'
  // reach (the largest |x| + |y| + max(spread, 0) + 2B) plus 1 px. Its alpha is
  // solved in closed form for each offset and blur, which are found on a grid
  // of FIT_GRID points an axis, the grid narrowed FIT_ROUNDS times to the best
  // point one step either side: offset within the layers' own, widened either
  // way by their largest spread (which moves an edge as an offset does), blur
  // from 0 to their largest plus twice their largest spread. Its colour is
  // theirs, each weighted by what it covers alone over the same points.
  // Lengths are kept to FIT_LENGTH_STEP px and alpha to FIT_ALPHA_STEP. At most
  // FIT_LAYER_LIMIT layers are fitted, the first listed. The fit of one set of
  // layers is made once, and a slide makes at most FIT_BUDGET fits (each costs
  // milliseconds): past them a box carries its first layer as it is, as before
  // the fit, and reportShadowFits counts it.
  const FIT_SAMPLES = 64;
  const FIT_GRID = 9;
  const FIT_ROUNDS = 4;
  const FIT_LAYER_LIMIT = 16;
  const FIT_LENGTH_STEP = 0.01;
  const FIT_ALPHA_STEP = 0.001;
  const FIT_BUDGET = 64;
  // The outward normals of the box's edges: bottom, top, right, left.
  const FIT_EDGES = [[0, 1], [0, -1], [1, 0], [-1, 0]];
  const fittedLayers = new Map();
  // The boxes past the fit budget, which carry their first layer.
  let pastFitBudget = 0;

  // One [html2pptx] line counting the boxes past the fit budget, when any are.
  function reportShadowFits() {
    if (!pastFitBudget) return;
    diagnose('boxShadowFits', pastFitBudget, FIT_BUDGET);
  }

  // The complementary error function, within 1.2e-7 of it (Numerical Recipes, erfcc).
  function erfc(value) {
    const z = Math.abs(value);
    const t = 1 / (1 + 0.5 * z);
    const tail = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
      t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return value >= 0 ? tail : 2 - tail;
  }

  // What a layer at `along` px out along an edge's normal covers d px outside that edge.
  function coverage(d, along, blur, spread, alpha) {
    const edge = d - along - spread;
    const sigma = blur / 2;
    if (!(sigma > 0)) return edge < 0 ? alpha : edge === 0 ? alpha / 2 : 0;
    return alpha * 0.5 * erfc(edge / (sigma * Math.SQRT2));
  }

  function fittedLayer(shadows) {
    const layers = [];
    let key = '';
    for (let index = 0; index < shadows.length && index < FIT_LAYER_LIMIT; index++) {
      const layer = shadows[index];
      layers.push(layer);
      key += layer.color + ' ' + layer.alpha + ' ' + layer.x + ' ' + layer.y + ' ' + layer.blur + ' ' + layer.spread + ',';
    }
    if (fittedLayers.has(key)) return fittedLayers.get(key);
    if (fittedLayers.size >= FIT_BUDGET) {
      pastFitBudget++;
      return shadows[0];
    }
    let reach = 0;
    let largestBlur = 0;
    let largestSpread = 0;
    const ranges = [[Infinity, -Infinity], [Infinity, -Infinity]];
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index];
      reach = Math.max(reach, Math.abs(layer.x) + Math.abs(layer.y) + Math.max(layer.spread, 0) + 2 * layer.blur);
      largestBlur = Math.max(largestBlur, layer.blur);
      largestSpread = Math.max(largestSpread, Math.abs(layer.spread));
      ranges[0] = [Math.min(ranges[0][0], layer.x), Math.max(ranges[0][1], layer.x)];
      ranges[1] = [Math.min(ranges[1][0], layer.y), Math.max(ranges[1][1], layer.y)];
    }
    for (let axis = 0; axis < ranges.length; axis++) ranges[axis] = [ranges[axis][0] - largestSpread, ranges[axis][1] + largestSpread];
    ranges.push([0, largestBlur + 2 * largestSpread]);
    const points = [];
    for (let step = 0; step <= FIT_SAMPLES; step++) points.push(step * (reach + 1) / FIT_SAMPLES);
    // What the layers cover together at each edge's points, and what each covers alone in all.
    const target = [];
    const weights = [];
    for (let index = 0; index < layers.length; index++) weights.push(0);
    let targetSquared = 0;
    for (let edge = 0; edge < FIT_EDGES.length; edge++) {
      const normalX = FIT_EDGES[edge][0];
      const normalY = FIT_EDGES[edge][1];
      for (let point = 0; point < points.length; point++) {
        let keep = 1;
        for (let index = 0; index < layers.length; index++) {
          const layer = layers[index];
          const covered = coverage(points[point], layer.x * normalX + layer.y * normalY, layer.blur, layer.spread, layer.alpha);
          weights[index] += covered;
          keep *= 1 - covered;
        }
        target.push(1 - keep);
        targetSquared += (1 - keep) * (1 - keep);
      }
    }
    // The error of the best alpha for one offset and blur, and that alpha.
    const solve = (x, y, blur) => {
      let single = 0;
      let crossed = 0;
      let sample = 0;
      for (let edge = 0; edge < FIT_EDGES.length; edge++) {
        const along = x * FIT_EDGES[edge][0] + y * FIT_EDGES[edge][1];
        for (let point = 0; point < points.length; point++) {
          const covered = coverage(points[point], along, blur, 0, 1);
          single += covered * covered;
          crossed += covered * target[sample++];
        }
      }
      const alpha = single > 0 ? Math.min(1, Math.max(0, crossed / single)) : 0;
      return { error: alpha * alpha * single - 2 * alpha * crossed + targetSquared, alpha };
    };
    let best = null;
    for (let round = 0; round < FIT_ROUNDS; round++) {
      const axes = [];
      for (let axis = 0; axis < ranges.length; axis++) {
        const low = ranges[axis][0];
        const high = ranges[axis][1];
        const values = [];
        if (high > low) {
          for (let point = 0; point < FIT_GRID; point++) values.push(low + (high - low) * point / (FIT_GRID - 1));
        } else {
          values.push(low);
        }
        axes.push(values);
      }
      for (let ix = 0; ix < axes[0].length; ix++) {
        for (let iy = 0; iy < axes[1].length; iy++) {
          for (let ib = 0; ib < axes[2].length; ib++) {
            const solved = solve(axes[0][ix], axes[1][iy], axes[2][ib]);
            if (!best || solved.error < best.error) {
              best = { error: solved.error, alpha: solved.alpha, values: [axes[0][ix], axes[1][iy], axes[2][ib]] };
            }
          }
        }
      }
      for (let axis = 0; axis < ranges.length; axis++) {
        const low = ranges[axis][0];
        const high = ranges[axis][1];
        if (!(high > low)) continue;
        const step = (high - low) / (FIT_GRID - 1);
        ranges[axis] = [Math.max(low, best.values[axis] - step), Math.min(high, best.values[axis] + step)];
      }
    }
    let total = 0;
    for (let index = 0; index < weights.length; index++) total += weights[index];
    let color = '';
    for (let channel = 0; channel < 6; channel += 2) {
      let mixed = 0;
      for (let index = 0; index < layers.length; index++) {
        mixed += weights[index] * parseInt(layers[index].color.slice(channel, channel + 2), 16);
      }
      const value = total > 0 ? Math.round(mixed / total) : parseInt(layers[0].color.slice(channel, channel + 2), 16);
      color += (value < 16 ? '0' : '') + value.toString(16).toUpperCase();
    }
    const kept = (value, step) => Math.round(value / step) * step;
    const fitted = {
      color,
      alpha: Number(kept(best.alpha, FIT_ALPHA_STEP).toFixed(3)),
      x: Number(kept(best.values[0], FIT_LENGTH_STEP).toFixed(2)),
      y: Number(kept(best.values[1], FIT_LENGTH_STEP).toFixed(2)),
      blur: Number(kept(best.values[2], FIT_LENGTH_STEP).toFixed(2)),
      spread: 0,
    };
    fittedLayers.set(key, fitted);
    return fitted;
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
  //   - the blurred or offset layers: the box's one outer shadow (shadowOf),
  //     on its own shape, since one shape carries one. Only a box that paints
  //     a fill casts it. Neither app casts a shadow from an unfilled shape, and
  //     an outline would cast only a thin frame of itself, which the browser
  //     does not paint: a box with no fill casts none. A translucent fill casts
  //     it as both apps draw it, scaled by the fill's alpha and through it;
  //   - the shadow paints where its first layer does: a ring listed before
  //     that layer is drawn over the box (it lies outside the border box, so it
  //     covers nothing of the box), and every other ring under the box;
  // * the box's own shape: its background colour and its shadow, outlined by
  //   its uniform border or else by its outline ring (ringedShape);
  // * a border that differs between sides, over the fill (pushSideBorders):
  //   on a box whose corners round, each solid side the region CSS paints for
  //   it, which follows the corners and tapers; else, and for a dashed or
  //   dotted side, a line along it. A fragment box-decoration-break slices
  //   keeps a line per side.
  // No shape is drawn for a shadow alone.
  // The slide root's ground is the slide background (the background transfer,
  // preprocess.mjs, put it on body, or for an image ground its picture,
  // snapshot.mjs groundCapture), so its fill, shadow and rings are never painted a second time here.
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
    const shadows = [];
    let firstShadow = layers.length;
    for (let index = 0; index < layers.length; index++) {
      if (!layers[index].shadow) continue;
      if (!shadows.length) firstShadow = index;
      shadows.push(layers[index].shadow);
    }
    const shadow = fill && shadows.length ? shadowOf(shadows, box) : null;
    const ringAt = (index) => {
      const ring = layers[index].ring;
      if (ring && ring !== outlineRing) pushBoxShape(ringedShape(box, corners, null, ring, null, order), clip);
    };
    for (let index = layers.length - 1; index >= 0; index--) {
      if (!(shadow && index < firstShadow)) ringAt(index);
    }
    if (fill || line || outlineRing) {
      pushBoxShape(outlineRing
        ? ringedShape(box, corners, fill, outlineRing, shadow, order)
        : borderedShape(box, corners, fill, line, shadow, order), clip);
    }
    if (shadow) {
      for (let index = firstShadow - 1; index >= 0; index--) ringAt(index);
    }
    if (sides) pushSideBorders(box, sides, sliced ? null : usedCornerRadii(s, box), order, clip);
  }

  // The shape of a box outlined by `line` (or null), which CSS paints inside
  // the border box: the stroke is centred on the shape's edge, so the shape is
  // inset by half the width, each corner's radius with it.
  function borderedShape(box, corners, fill, line, shadow, order) {
    const inset = line ? line.widthPx / 2 : 0;
    return boxShape(box, corners, inset, (radius) => radius - inset, { fill, line, shadow, order, extent: box });
  }

  // The shape of a box outlined by `ring`, which paints outside the border
  // box: grown by half the spread, each corner's radius to the ring's centre
  // line. What it paints reaches the ring's outer edge.
  function ringedShape(box, corners, fill, ring, shadow, order) {
    const half = ring.widthPx / 2;
    const extent = { x: box.x - ring.widthPx, y: box.y - ring.widthPx, w: box.w + 2 * ring.widthPx, h: box.h + 2 * ring.widthPx, rotate: box.rotate };
    return boxShape(box, corners, -half, (radius) => ringRadius(radius, ring.widthPx), { fill, line: ring, shadow, order, extent });
  }

  // `box` moved in by `inset` on every side (out, for a negative one), with
  // the corner geometry it keeps: each corner radius r of the box becomes
  // radiusAt(r) on the moved box (each axis of an elliptical corner alike, a
  // square corner staying square). The box's used radii fit it (CSS's overlap
  // rule, usedCornerRadii), and so do they moved: an inset takes from each
  // radius what it takes from each side, a ring adds at most half its width to
  // a radius and its width to each side. `paint` is {fill, line, shadow,
  // order, extent}: extent is the box whose bounds a clip is held against.
  function boxShape(box, corners, inset, radiusAt, paint) {
    const w = box.w - 2 * inset;
    const h = box.h - 2 * inset;
    let geometry = corners.geometry;
    let cornerRadius = 0;
    let radii = null;
    if (geometry === 'roundRect') {
      cornerRadius = Math.min(radiusAt(corners.radius), Math.min(w, h) / 2);
      if (!(cornerRadius > 0)) geometry = 'rect';
    } else if (geometry === 'roundCorners') {
      const moved = [];
      for (let index = 0; index < corners.radii.length; index++) {
        const corner = corners.radii[index];
        moved.push(corner.h > 0 && corner.v > 0
          ? { h: Math.max(0, radiusAt(corner.h)), v: Math.max(0, radiusAt(corner.v)) }
          : { h: 0, v: 0 });
      }
      const shaped = cornerGeometry(moved);
      geometry = shaped.geometry;
      cornerRadius = shaped.radius;
      radii = shaped.radii || null;
    }
    const shape = {
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
    if (radii) shape.radii = radii;
    return shape;
  }

  // A shape cut to its clip: whole when the clip cuts nothing it paints (its
  // extent) and no rounded padding box of the clip cuts it, the part shown of
  // a plain rect the clip's rect alone cuts, or else the part shown of its
  // outline (pushClippedShape). Nothing when the clip hides it. Returns the
  // items pushed.
  function pushBoxShape(shape, clip) {
    const shown = shownPart(boundsOf(shape.extent), clip);
    if (!shown) return [];
    const rounded = roundsCut(shape, clip);
    if (!shown.cut && !rounded) return [pushShape(shape)];
    if (shape.geometry === 'rect' && !shape.rotate && !shape.line && !rounded) {
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

  return { SIDES, clipsToText, emitBox, outerShadowLayers, paintsBox, reportShadowFits, sliceOf };
}

export const BORDERS_SOURCE = createBorders.toString();
