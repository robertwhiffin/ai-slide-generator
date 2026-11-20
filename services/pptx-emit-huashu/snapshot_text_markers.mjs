// List markers: a list item's ::marker as the text layout (snapshot_text.mjs)
// lays it out. snapshot_text.mjs composes LIST_MARKERS_SOURCE into
// TEXT_SOURCE, and createTextLayout makes it once (createListMarkers). Its
// header's "List markers" says where a marker goes: outside its item, a
// single-line text item of its own where its glyphs end (markerBlock);
// inside, a token of its item's first line when the text runs straight on
// from it, else a segment of its own (readMarkerTokens, joinMarkers).
//
// Runs in the page, inside the snapshot IIFE. It is stringified, so it closes
// over nothing on the Node side. It reads the text layout's `env` (shows), and
// what it needs from the layout itself arrives in `layout`, documented in
// snapshot_text.mjs: SLACK_FRACTION, SLACK_PX, anyShown, assembleLine,
// decorationOf, dropToken, generatedSource, generatedText, lastCodePoint,
// paragraphsOf, preservedSpaces, pushTextToken and queueRuns. It gives back
// joinMarkers, markerBlock, markerGlyphLine (for turned text) and
// readMarkerTokens.

function createListMarkers(env, layout) {
  const {
    SLACK_FRACTION,
    SLACK_PX,
    anyShown,
    assembleLine,
    decorationOf,
    dropToken,
    generatedSource,
    generatedText,
    lastCodePoint,
    paragraphsOf,
    preservedSpaces,
    pushTextToken,
    queueRuns,
  } = layout;

  // An inside marker joins its item's first line only when the text after it
  // starts within this of where the marker's text, trailing space included,
  // ends in its font: then a renderer that sets the two as one line puts the
  // text where the browser did. Else a gap follows it (an inside disc's margin).
  const INSIDE_JOIN_PX = 1;

  // A ::marker's text ends with white space ("1. ") that is no glyph, so it is
  // exported trimmed (snapshot.mjs ListMarker: glyphs and trailing), and its
  // glyphs end where its box does, less the trailing white space the box
  // holds: the space's advance in the marker's font for a text marker, whose
  // box is that text laid out, and nothing for a symbol, whose box is the
  // shape Chrome paints. Right to left, the trailing space is the leftmost.

  // Where a marker's text was laid out: the union of its text boxes, or its
  // box when the protocol listed none. {left, top, right, bottom}.
  function markerTextRect(marker) {
    let rect = null;
    for (let piece = 0; piece < marker.pieces.length; piece++) {
      const boxes = marker.pieces[piece].boxes;
      for (let index = 0; index < boxes.length; index++) {
        const box = boxes[index];
        if (!rect) {
          rect = { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
          continue;
        }
        rect.left = Math.min(rect.left, box.left);
        rect.top = Math.min(rect.top, box.top);
        rect.right = Math.max(rect.right, box.right);
        rect.bottom = Math.max(rect.bottom, box.bottom);
      }
    }
    if (rect) return rect;
    const box = marker.rect;
    return { left: box.left, top: box.top, right: box.left + box.width, bottom: box.top + box.height };
  }

  // markerParts(marker, scale) -> {rect, glyphs, space, rtl, ends}: its text
  // rect, split into where its glyphs paint and where its trailing white space
  // lies, and `ends`, the x at which its text, trailing space included, ends
  // in its font (where Chrome ended its box when that advance is unread).
  // `scale` is its transform scale; the advances were measured unscaled.
  function markerParts(marker, scale) {
    const rect = markerTextRect(marker);
    const rtl = marker.style.direction === 'rtl';
    const width = Math.max(0, rect.right - rect.left);
    const advance = marker.list.advance;
    const held = advance && !marker.list.symbol && marker.list.trailing ? (advance.full - advance.glyphs) * scale : 0;
    const trailing = Math.min(Math.max(Number.isFinite(held) ? held : 0, 0), width);
    const glyphs = rtl
      ? { left: rect.left + trailing, top: rect.top, right: rect.right, bottom: rect.bottom }
      : { left: rect.left, top: rect.top, right: rect.right - trailing, bottom: rect.bottom };
    const space = rtl
      ? { left: rect.left, top: rect.top, right: rect.left + trailing, bottom: rect.bottom }
      : { left: rect.right - trailing, top: rect.top, right: rect.right, bottom: rect.bottom };
    const full = advance ? advance.full * scale : NaN;
    const ends = Number.isFinite(full)
      ? (rtl ? rect.right - full : rect.left + full)
      : (rtl ? rect.left : rect.right);
    return { rect, glyphs, space, rtl, ends };
  }

  // The tokens of an inside marker: its glyphs, then its trailing white space
  // as a space (which a line's end drops, as it drops any collapsible one),
  // each at its part of the marker's text rect, in the marker's own style. A
  // symbol's glyph token is a `shape`: its rect is the box Chrome paints the
  // shape in, no advance (assembleLine).
  // Both carry `joining` {rtl, ends} (markerParts), and the tokens after them
  // start a new segment, so the line is cut after the marker unless
  // joinMarkers finds the text runs straight on from it. A marker that paints
  // nothing (hidden, or clipped away) is a gap that keeps its room. Generated
  // text is no part of the page's innerText, so it is never hidden text.
  function readMarkerTokens(piece, scale, tokens, words) {
    const marker = piece.marker;
    const ps = piece.context.style;
    const source = generatedSource(piece.context, scale, words.segment);
    const mode = source.mode;
    const parts = markerParts(marker, scale);
    const glyphs = marker.list.glyphs;
    const trailing = marker.list.trailing;
    const paints = ps.visibility === 'visible' && piece.context.opacity > 0;
    if (!paints || !anyShown([parts.rect], source.clip)) {
      dropToken(source, glyphs, [parts.rect], tokens);
    } else {
      const joining = { rtl: parts.rtl, ends: parts.ends };
      pushTextToken(source, generatedText(glyphs, mode), parts.glyphs, false, tokens);
      tokens[tokens.length - 1].joining = joining;
      tokens[tokens.length - 1].shape = marker.list.symbol;
      if (trailing) {
        pushTextToken(source, mode.spaces ? preservedSpaces(trailing) : ' ', parts.space, !mode.spaces, tokens);
        tokens[tokens.length - 1].joining = joining;
      }
    }
    words.previous = trailing ? ' ' : lastCodePoint(glyphs, 0, glyphs.length);
    words.segment++;
  }

  // Joins each inside marker to its line when the text after it runs straight
  // on from it: when the first token after the marker's starts within
  // INSIDE_JOIN_PX of where the marker's text, trailing space included, ends
  // in its font. The marker's tokens then take that token's segment, so the
  // line is not cut there and the marker is a token of it; otherwise they keep
  // their own segment, and the line is cut at the marker as at an inline edge:
  // the marker is a segment at its box and the text keeps its own x.
  function joinMarkers(tokens) {
    for (let index = 0; index < tokens.length; index++) {
      const joining = tokens[index].joining;
      if (!joining) continue;
      let last = index;
      while (last + 1 < tokens.length && tokens[last + 1].joining === joining) last++;
      const next = last + 1 < tokens.length ? tokens[last + 1] : null;
      if (next && next.kind === 'text' && !next.collapsible) {
        const starts = joining.rtl ? next.rect.right : next.rect.left;
        if (Math.abs(starts - joining.ends) <= INSIDE_JOIN_PX) {
          for (let token = index; token <= last; token++) tokens[token].segment = next.segment;
        }
      }
      index = last;
    }
  }

  // markerBlock(marker, walk) -> TextBlock | null: a marker outside its item,
  // as a single-line text item of its own in the marker's own style, its
  // glyphs (markerParts) alone. Left to right it is right-aligned, its right
  // edge where the glyphs end and its slack (spec §3 Text, Wrapping) grown to
  // the left, so a renderer that ignores wrap="none" can never move the edge
  // the browser drew; right to left it is the mirror: left-aligned at the
  // glyphs' left edge, its slack to the right, its paragraph right to left.
  // An outside marker is an inline-block: its item's underline does not reach
  // it. `walk` is its item's inline context (snapshot.mjs visit). Null when it
  // paints nothing.
  function markerBlock(marker, walk) {
    const read = markerGlyphLine(marker, walk);
    if (!read) return null;
    const line = read.line;
    const parts = read.parts;
    queueRuns([line], 'right', !walk.frame.angle);
    const width = parts.glyphs.right - parts.glyphs.left;
    const extra = width * SLACK_FRACTION + SLACK_PX;
    return {
      x: parts.rtl ? parts.glyphs.left : parts.glyphs.right - width - extra,
      y: parts.glyphs.top,
      w: width + extra,
      h: parts.glyphs.bottom - parts.glyphs.top,
      rotate: null,
      wrap: false,
      align: parts.rtl ? 'left' : 'right',
      rtl: parts.rtl,
      paragraphs: paragraphsOf([line], true),
    };
  }

  // markerGlyphLine(marker, walk) -> {line, parts} | null: an outside
  // marker's glyphs as one assembled line in its own style, and where its text
  // lies (markerParts). Null when it paints nothing: no glyphs, hidden, or
  // clipped away.
  function markerGlyphLine(marker, walk) {
    const ps = marker.style;
    const glyphs = marker.list.glyphs;
    if (!glyphs || ps.visibility !== 'visible' || !(walk.opacity > 0)) return null;
    const scale = walk.frame.scale;
    const parts = markerParts(marker, scale);
    if (!env.shows(parts.rect, walk.clip)) return null;
    const context = {
      style: ps,
      opacity: walk.opacity,
      backdrop: walk.backdrop,
      decoration: decorationOf(walk.decoration, marker, ps),
      baseline: null,
      nudgePx: 0,
      clip: walk.clip,
    };
    const source = generatedSource(context, scale, 0);
    const tokens = [];
    pushTextToken(source, generatedText(glyphs, source.mode), parts.glyphs, false, tokens);
    tokens[0].shape = marker.list.symbol;
    const line = assembleLine({ tokens }, String(ps.lineHeight));
    if (!line || !line.runs.length) return null;
    return { line, parts };
  }

  return { joinMarkers, markerBlock, markerGlyphLine, readMarkerTokens };
}

export const LIST_MARKERS_SOURCE = createListMarkers.toString();
