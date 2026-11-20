// Turned text: text under a rotation or a vertical writing mode, as the text
// layout (snapshot_text.mjs) lays it out. snapshot_text.mjs composes
// TURNED_TEXT_SOURCE into TEXT_SOURCE, and createTextLayout makes it once
// (createTurnedText). Its header's "Turned text" says what a turn root
// becomes: one text item on its layout box, turned by its text's angle, or
// one per piece where a gap cuts it.
//
// Runs in the page, inside the snapshot IIFE. It is stringified, so it closes
// over nothing on the Node side. It reads the text layout's `env` (boxEdges,
// rectOf, boxGeometry, layoutBox), and what it needs from the layout itself
// arrives in `layout`, documented in snapshot_text.mjs and the modules named:
// SLACK_FRACTION, SLACK_PX, alignmentOf, assembleLine, contentHeightOf
// (snapshot_text_metrics.mjs), isBlank, isCut, largestRunOf, markerGlyphLine
// (snapshot_text_markers.mjs), paragraphsOf, queueRuns, readRunTokens,
// recordHiddenWords and segmentsOf. It gives back TURNED_SIDES (which the
// layout also reads inline edges by), layoutTurnedRun, turnedBlocks,
// turnedMarkerBlock and writingTurn.

function createTurnedText(env, layout) {
  const {
    SLACK_FRACTION,
    SLACK_PX,
    alignmentOf,
    assembleLine,
    contentHeightOf,
    isBlank,
    isCut,
    largestRunOf,
    markerGlyphLine,
    paragraphsOf,
    queueRuns,
    readRunTokens,
    recordHiddenWords,
    segmentsOf,
  } = layout;

  // How far a vertical writing mode turns its Latin glyphs, set sideways,
  // clockwise from upright, and whether its lines stack the other way from the
  // paragraphs of a box turned by that angle (CSS Writing Modes 4). A plain
  // table, read with hasOwnProperty: page script can replace Map and Set.
  const WRITING_MODE_TURNS = {
    'vertical-rl': { angle: 90, reversed: false },
    'vertical-lr': { angle: 90, reversed: true },
    'sideways-rl': { angle: 90, reversed: false },
    'sideways-lr': { angle: 270, reversed: false },
  };
  const UPRIGHT = { angle: 0, reversed: false };
  // The page side each side of a turned box lies on, by the writing mode's
  // turn: turned 90 degrees its top is the root's right side, turned 270 its
  // left. A plain table, as above.
  const TURNED_SIDES = {
    0: { left: 'Left', top: 'Top', right: 'Right', bottom: 'Bottom' },
    90: { left: 'Top', top: 'Right', right: 'Bottom', bottom: 'Left' },
    270: { left: 'Bottom', top: 'Left', right: 'Top', bottom: 'Right' },
  };
  const LOCAL_SIDES = ['left', 'top', 'right', 'bottom'];
  // A word under a turn starts a line of its own where the browser wrapped
  // before it: its centre lies more than this fraction of the larger font size
  // across the line from the word before it, and back towards the line start.
  // A wrap moves a word a whole line height; a baseline shift or a mixed size
  // on one line moves it under half its size.
  const SOFT_WRAP_FRACTION = 0.5;

  // The text of a turn root (snapshot.mjs TurnedText) is one block, or one per
  // piece when a gap cuts it: each run the walk lays out under the root gives
  // its lines (layoutTurnedRun), which the walk gathers in DOM order, and
  // turnedBlocks makes its blocks of them.

  // writingTurn(s) -> {angle, reversed, writingMode}: how far the writing mode
  // of computed style `s` turns its Latin glyphs, set sideways, clockwise from
  // upright (0, 90 or 270), and whether its lines stack the other way from a
  // box turned by that angle (vertical-lr). text-orientation: upright and the
  // upright CJK it sets are not read: their glyphs turn with the rest.
  function writingTurn(s) {
    const writingMode = String(s.writingMode || 'horizontal-tb');
    const turn = Object.prototype.hasOwnProperty.call(WRITING_MODE_TURNS, writingMode)
      ? WRITING_MODE_TURNS[writingMode]
      : UPRIGHT;
    return { angle: turn.angle, reversed: turn.reversed, writingMode };
  }

  // Where the slide point (x, y) lies in the frame of text turned by `angle`
  // degrees clockwise about `centre`: {u, v}, px along its lines and down
  // across them, from the centre.
  function turnedPoint(centre, angle, x, y) {
    const radians = angle * Math.PI / 180;
    const dx = x - centre.x;
    const dy = y - centre.y;
    return { u: dx * Math.cos(radians) + dy * Math.sin(radians), v: -dx * Math.sin(radians) + dy * Math.cos(radians) };
  }

  // The tokens of one line between breaks of a turned run, as the lines the
  // browser wrapped it into. A word's rect is the bounds of its turned glyph
  // run, which share that run's centre at any angle, so its centre turned back
  // about the root's centre says where the word lies along its line and across
  // it. A word starts a line when it lies across the line from the word before
  // it by more than SOFT_WRAP_FRACTION of the larger size, and back towards
  // the line's start: a wrap. The spaces travel with the words before them.
  function softWrapped(tokens, turned, rtl) {
    const lines = [[]];
    let previous = null;
    for (let index = 0; index < tokens.length; index++) {
      const token = tokens[index];
      if (token.kind === 'text' && !token.collapsible) {
        const rect = token.rect;
        const at = turnedPoint(turned.centre, turned.angle, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
        if (previous) {
          const across = Math.abs(at.v - previous.at.v);
          const back = rtl ? at.u > previous.at.u : at.u < previous.at.u;
          if (across > SOFT_WRAP_FRACTION * Math.max(token.style.sizePx, previous.sizePx) && back) lines.push([]);
        }
        previous = { at, sizePx: token.style.sizePx };
      }
      lines[lines.length - 1].push(token);
    }
    return lines;
  }

  // layoutTurnedRun(nodes, s, scale, turned) -> Line[]: the lines of one run
  // of a turned root's text (collectRuns pieces; `s` the style of the block
  // holding it, `scale` its transform scale), in DOM order: its text broken at
  // each <br> and preserved newline, and where the browser wrapped it
  // (softWrapped). Each line is assembled as assembleLine does, or, where a
  // gap (an atomic inline, which is an item of its own, or a word that paints
  // nothing) or an inline element's edges cut it (isCut), is a cut line,
  // {segments}, as layoutInlineRun gives one (segmentsOf); turnedBlocks
  // places each segment where its text lies. A line of collapsed white space
  // is no line. A blank line is one, at the run's start too: it takes its room
  // in the turned box's stack, as a leading <br>'s empty line does on screen.
  // Only the empty line after the run's final <br> is none: the browser lays
  // none out there. [] when none of its text paints. Turned text is cut by no
  // ellipsis, so the words it does not show whole are known once it is read
  // (recordHiddenWords).
  function layoutTurnedRun(nodes, s, scale, turned) {
    const range = document.createRange();
    const read = [];
    const tokens = readRunTokens(nodes, scale, range, read);
    recordHiddenWords(read);
    const rtl = s.direction === 'rtl';
    const lineHeight = String(s.lineHeight);
    const lines = [];
    let painted = false;
    let explicit = [];
    for (let index = 0; index <= tokens.length; index++) {
      const token = index < tokens.length ? tokens[index] : null;
      if (token && token.kind !== 'break') {
        explicit.push(token);
        continue;
      }
      if (!token && !explicit.length && tokens.length && tokens[tokens.length - 1].kind === 'break') break;
      const wrapped = softWrapped(explicit, turned, rtl);
      for (let line = 0; line < wrapped.length; line++) {
        const read = { tokens: wrapped[line] };
        if (isCut(read)) {
          const segments = segmentsOf(read, lineHeight);
          if (segments.length) painted = true;
          lines.push({ segments });
          continue;
        }
        const assembled = assembleLine(read, lineHeight);
        if (!assembled) continue;
        if (assembled.runs.length) painted = true;
        lines.push(assembled);
      }
      explicit = [];
    }
    return painted ? lines : [];
  }

  // The slide point at {u, v} in the frame of text turned by `angle` degrees
  // clockwise about `centre`: turnedPoint's inverse.
  function turnedSlidePoint(centre, angle, u, v) {
    const radians = angle * Math.PI / 180;
    return {
      x: centre.x + u * Math.cos(radians) - v * Math.sin(radians),
      y: centre.y + u * Math.sin(radians) + v * Math.cos(radians),
    };
  }

  // Where one turned run lies in the frame of text turned by `angle` about
  // `centre` (turnedPoint), from `bounds`, the bounds of its turned glyph run
  // ({left, top, right, bottom}, which share its centre), and `across`, how
  // tall it is across its line, the content area of its face: {left, right,
  // top, bottom}. Turned by the angle, a run `along` long is bounded by a box
  // along|cos| + across|sin| wide and along|sin| + across|cos| tall, so its
  // length is read from the side nearer the run's own: the width when the
  // turn is nearer upright, the height when it is nearer a quarter.
  function turnedRunExtent(bounds, across, centre, angle) {
    const radians = angle * Math.PI / 180;
    const cosine = Math.abs(Math.cos(radians));
    const sine = Math.abs(Math.sin(radians));
    const along = Math.max(0, cosine >= sine
      ? (bounds.right - bounds.left - across * sine) / cosine
      : (bounds.bottom - bounds.top - across * cosine) / sine);
    const middle = turnedPoint(centre, angle, (bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2);
    return { left: middle.u - along / 2, right: middle.u + along / 2, top: middle.v - across / 2, bottom: middle.v + across / 2 };
  }

  // Where a turned line lies in the frame of text turned by `angle` about
  // `centre`: {left, right, top, bottom}, along and across it; null for a line
  // with no runs. Each run is placed on its own (turnedRunExtent), as tall as
  // its own face's content area (contentHeightOf): off a quarter turn, a line
  // of runs of different sizes is no one rectangle. Along, the line runs from
  // its first run's start to its last's end; across, it is where its largest
  // run is, on the line's own baseline, so a superscript or a smaller run does
  // not move it.
  function turnedLineExtent(line, centre, angle) {
    const largest = largestRunOf(line);
    if (!line.rect || largest < 0) return null;
    let left = Infinity;
    let right = -Infinity;
    let across = null;
    for (let run = 0; run < line.runs.length; run++) {
      const extent = line.extents[run];
      const placed = turnedRunExtent(extent, contentHeightOf(extent.face, line.runs[run].sizePx), centre, angle);
      left = Math.min(left, placed.left);
      right = Math.max(right, placed.right);
      if (run === largest) across = placed;
    }
    return { left, right, top: across.top, bottom: across.bottom };
  }

  // The insets of a turned box's content box in its own frame, px: {inset,
  // padding}, each {left, top, right, bottom}: the root's border and padding
  // on each side, scaled (boxEdges), and its padding alone, each taken from
  // the side the writing mode's turn brings there (TURNED_SIDES).
  function turnedInsets(s, frame, turn) {
    const edges = env.boxEdges(s, frame.scaleX, frame.scaleY);
    const sides = turn === 90 || turn === 270 ? TURNED_SIDES[turn] : TURNED_SIDES[0];
    const inset = {};
    const padding = {};
    for (let index = 0; index < LOCAL_SIDES.length; index++) {
      const local = LOCAL_SIDES[index];
      const edge = edges[sides[local]];
      inset[local] = edge.border + edge.padding;
      padding[local] = edge.padding;
    }
    return { inset, padding };
  }

  // A turn root's frame, {centre, angle, w, h, inset, padding, area, rtl,
  // align}: its layout box (boxGeometry, or layoutBox where its bounds have no
  // area, a zero-width anchor its text overflows), the inline length by the
  // block length under a vertical writing mode, about its bounds' centre; the
  // insets of its content box in that frame (turnedInsets), and the content
  // box's span along the line from the centre, `area` {left, right}; and how
  // its text aligns.
  function turnedFrameOf(turned) {
    const s = turned.style;
    const rect = env.rectOf(turned.root);
    const box = env.boxGeometry(turned.root, rect, turned.frame) || env.layoutBox(turned.root, rect, turned.frame);
    const sideways = turned.turn === 90 || turned.turn === 270;
    const w = sideways ? box.h : box.w;
    const edges = turnedInsets(s, turned.frame, turned.turn);
    const rtl = s.direction === 'rtl';
    return {
      centre: { x: box.x + box.w / 2, y: box.y + box.h / 2 },
      angle: turned.angle,
      w,
      h: sideways ? box.w : box.h,
      inset: edges.inset,
      padding: edges.padding,
      area: { left: -w / 2 + edges.inset.left, right: w / 2 - edges.inset.right },
      rtl,
      align: alignmentOf(s, rtl),
    };
  }

  // The one block of a turn root no gap cuts, holding all its `lines`, in its
  // frame `place` (turnedFrameOf).
  // * Its box is the root's layout box, turned by the text's angle.
  // * Its text sits in the root's content box by the box's insets. The usual
  //   slack (6% + 4 px of the content width) goes on the side its alignment
  //   grows (half each side when centred), so Google Slides, which ignores
  //   wrap="none" and every inset below 0, has room for a slightly wider
  //   font: the padding on that side holds what it can, and the rest grows
  //   the box there, its centre moved along its own inline axis, so the
  //   layout box and the text's start stay where the browser has them.
  // * Its top inset is where its first line's glyphs start below the box's
  //   top (turnedLineExtent), the content box's top for a line it cannot read.
  // * Its lines are the browser's, so it never wraps.
  function turnedRootBlock(lines, place) {
    const inset = { left: place.inset.left, top: place.inset.top, right: place.inset.right };
    const written = place.align === 'justify' ? (place.rtl ? 'right' : 'left') : place.align;
    const extra = Math.max(0, place.w - inset.left - inset.right) * SLACK_FRACTION + SLACK_PX;
    // The padding on a growth side holds what it can of its share of the
    // slack; the rest grows the box on that side.
    const take = (side, share) => {
      const held = Math.min(Math.max(place.padding[side], 0), share);
      inset[side] -= held;
      return share - held;
    };
    const growsLeft = written === 'center' ? take('left', extra / 2) : written === 'right' ? take('left', extra) : 0;
    const growsRight = written === 'center' ? take('right', extra / 2) : written === 'left' ? take('right', extra) : 0;
    // Grown along its own inline axis, the box's centre moves half the
    // difference that way, so the layout box stays where the browser has it.
    const middle = turnedSlidePoint(place.centre, place.angle, (growsRight - growsLeft) / 2, 0);
    const w = place.w + growsLeft + growsRight;
    const first = turnedLineExtent(lines[0], place.centre, place.angle);
    queueRuns(lines, place.align, false);
    return {
      x: middle.x - w / 2,
      y: middle.y - place.h / 2,
      w,
      h: place.h,
      rotate: place.angle || null,
      wrap: false,
      align: written,
      rtl: place.rtl,
      paragraphs: paragraphsOf(lines, false),
      inset: { left: inset.left, top: first ? first.top + place.h / 2 : inset.top, right: inset.right, bottom: 0 },
    };
  }

  // A turned block over the box `local` {left, right, top, bottom} of the
  // frame `place` ({centre, angle, rtl}), holding `lines`, written `written`
  // (`align` the alignment it was laid out with): a box turned by the angle
  // about its own centre, whose own top is its first line's glyph top, as an
  // unturned block's y is (the emitter raises it by the first-line offset
  // along its own up). Its lines are the browser's, so it never wraps.
  function turnedPieceBlock(place, local, written, lines, align) {
    const w = local.right - local.left;
    const h = local.bottom - local.top;
    const middle = turnedSlidePoint(place.centre, place.angle, (local.left + local.right) / 2, (local.top + local.bottom) / 2);
    queueRuns(lines, align, false);
    return {
      x: middle.x - w / 2,
      y: middle.y - h / 2,
      w,
      h,
      rotate: place.angle || null,
      wrap: false,
      align: written,
      rtl: place.rtl,
      paragraphs: paragraphsOf(lines, false),
    };
  }

  // The block of `lines` of a turn root a gap cuts, where they lie in its
  // frame `place` (turnedLineExtent), placed as textBlock places unturned
  // text (`placement` 'container' or 'segment'): by its lines' extent, across
  // the content box for text aligned other than left, written from the line's
  // start side for a segment, with the slack on the side its alignment grows.
  // Null when none of its lines can be placed.
  function turnedLocalBlock(lines, place, placement) {
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    for (let index = 0; index < lines.length; index++) {
      const extent = turnedLineExtent(lines[index], place.centre, place.angle);
      if (!extent) continue;
      left = Math.min(left, extent.left);
      right = Math.max(right, extent.right);
      top = Math.min(top, extent.top);
      bottom = Math.max(bottom, extent.bottom);
    }
    if (!(bottom > top) || !(right >= left)) return null;
    let x = left;
    let w = right - left;
    if (place.align !== 'left' && placement === 'container') {
      x = Math.min(place.area.left, left);
      w = Math.max(place.area.right, right) - x;
    }
    const start = place.rtl ? 'right' : 'left';
    const written = placement === 'segment' || place.align === 'justify' ? start : place.align;
    const extra = w * SLACK_FRACTION + SLACK_PX;
    const shift = written === 'center' ? extra / 2 : written === 'right' ? extra : 0;
    return turnedPieceBlock(place, { left: x - shift, right: x - shift + w + extra, top, bottom }, written, lines, place.align);
  }

  // turnedBlocks(turned) -> TextBlock[]: the text blocks of a turn root
  // (snapshot.mjs TurnedText), once the walk has gathered all its lines, in
  // order; [] when none of them paints. Its lines are taken in the order the
  // turned box stacks them (reversed for vertical-lr), less blank lines at
  // either end.
  // * A root no gap cuts is one block on its layout box (turnedRootBlock).
  // * A root a gap cuts is cut as blocksOf cuts unturned text: the lines
  //   between cut lines are one block together and each segment of a cut line
  //   one block, each where its text lies in the root's frame
  //   (turnedLocalBlock), so the text after a chip or a hidden word starts
  //   where the browser has it.
  function turnedBlocks(turned) {
    const lines = turned.reversed ? turned.lines.slice().reverse() : turned.lines.slice();
    let first = 0;
    let last = lines.length - 1;
    while (first <= last && isBlank(lines[first])) first++;
    while (last >= first && isBlank(lines[last])) last--;
    if (first > last) return [];
    const kept = lines.slice(first, last + 1);
    const place = turnedFrameOf(turned);
    let cut = false;
    for (let index = 0; index < kept.length; index++) {
      if (kept[index].segments) cut = true;
    }
    if (!cut) return [turnedRootBlock(kept, place)];
    const blocks = [];
    let pending = [];
    const flush = () => {
      let from = 0;
      let to = pending.length - 1;
      while (from <= to && isBlank(pending[from])) from++;
      while (to >= from && isBlank(pending[to])) to--;
      if (from <= to) {
        const block = turnedLocalBlock(pending.slice(from, to + 1), place, 'container');
        if (block) blocks.push(block);
      }
      pending = [];
    };
    for (let index = 0; index < kept.length; index++) {
      const line = kept[index];
      if (!line.segments) {
        pending.push(line);
        continue;
      }
      flush();
      for (let segment = 0; segment < line.segments.length; segment++) {
        const block = turnedLocalBlock([line.segments[segment]], place, 'segment');
        if (block) blocks.push(block);
      }
    }
    flush();
    return blocks;
  }

  // turnedMarkerBlock(marker, walk) -> TextBlock | null: an outside list
  // marker under a turn (walk.turned, the TurnedText of its item's text), a
  // turned single-line item of its own, as markerBlock makes one unturned.
  // Its box is the one the DevTools protocol read: its quad's own
  // sides, along and across the line (a vertical writing mode's turn swaps
  // them), about its bounds' centre, turned back into its item's frame. Its
  // glyphs end where that box ends less the trailing white space it holds
  // (markerParts: a symbol holds none), and start there plus that space right
  // to left. The block is right-aligned where they end, its slack before them
  // (left-aligned where they start, its slack after, right to left), one line
  // across the content area of its face. Null when it paints nothing.
  function turnedMarkerBlock(marker, walk) {
    const read = markerGlyphLine(marker, walk);
    if (!read) return null;
    const turned = walk.turned;
    const rtl = read.parts.rtl;
    const sideways = turned.turn === 90 || turned.turn === 270;
    const along = sideways ? marker.edges.height : marker.edges.width;
    const box = marker.rect;
    const middle = turnedPoint(turned.centre, turned.angle, box.left + box.width / 2, box.top + box.height / 2);
    const advance = marker.list.advance;
    const held = advance && !marker.list.symbol && marker.list.trailing ? (advance.full - advance.glyphs) * walk.frame.scale : 0;
    const trailing = Math.min(Math.max(Number.isFinite(held) ? held : 0, 0), along);
    const glyphs = along - trailing;
    const start = middle.u - along / 2;
    const largest = largestRunOf(read.line);
    const across = contentHeightOf(read.line.extents[largest].face, read.line.runs[largest].sizePx);
    const extra = glyphs * SLACK_FRACTION + SLACK_PX;
    const local = rtl
      ? { left: start + trailing, right: start + along + extra, top: middle.v - across / 2, bottom: middle.v + across / 2 }
      : { left: start - extra, right: start + glyphs, top: middle.v - across / 2, bottom: middle.v + across / 2 };
    return turnedPieceBlock({ centre: turned.centre, angle: turned.angle, rtl }, local, rtl ? 'left' : 'right', [read.line], 'right');
  }

  return { TURNED_SIDES, layoutTurnedRun, turnedBlocks, turnedMarkerBlock, writingTurn };
}

export const TURNED_TEXT_SOURCE = createTurnedText.toString();
