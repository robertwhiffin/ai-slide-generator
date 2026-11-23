// Ellipsis: a line that text-overflow: ellipsis cuts, cut where Chrome cuts
// it, as the text layout (snapshot_text.mjs) lays it out.
// snapshot_text.mjs composes ELLIPSIS_SOURCE into TEXT_SOURCE, and
// createTextLayout makes it once (createEllipsis). Its header's "Ellipsis"
// says what the cut keeps: the characters that end within the content box's
// end edge less the "…"'s advance, then a "…" in the block's own style.
//
// Runs in the page, inside the snapshot IIFE. It is stringified, so it closes
// over nothing on the Node side. It reads the text layout's `env`
// (boxGeometry, rectOf, contentBox), and what it needs from the layout itself
// arrives in `layout`, documented in snapshot_text.mjs and
// snapshot_text_metrics.mjs: DEFAULT_TAB_SIZE, browserCutCss, familyOf,
// measureProbes, paintedCodePoints, probeFaceOf, runStyle, settledBounds,
// sharedNudgeOf and unionBounds. It gives back ellipsisOf and
// truncateAtEllipsis.

function createEllipsis(env, layout) {
  const {
    DEFAULT_TAB_SIZE,
    browserCutCss,
    familyOf,
    measureProbes,
    paintedCodePoints,
    probeFaceOf,
    runStyle,
    settledBounds,
    sharedNudgeOf,
    unionBounds,
  } = layout;

  // What Chrome paints where text-overflow: ellipsis cuts a line.
  const ELLIPSIS = '…';
  // A line runs past its content box's end edge when its text ends beyond it
  // by more than this: the layout unit (1/64 px), so a line that fits exactly
  // is never cut.
  const ELLIPSIS_OVERFLOW_PX = 1 / 64;

  // The advance of the "…" per probe face, in unscaled px (null when it could
  // not be measured), measured once each (ellipsisAdvance).
  const ellipsisAdvances = Object.create(null);

  // A block container whose text-overflow is ellipsis and whose overflow
  // is not visible ends each line that runs past its line box in a "…". The
  // line box is its content box, where Chrome ends the "…", not the padding
  // box its overflow clips to. Chrome keeps the characters whose advance ends
  // within the end edge less the "…"'s own advance, paints the "…" straight
  // after them in the block's own style, and nothing else of the line,
  // whatever its overflow clip would show.
  //   EllipsisCut = {edge, rtl, context}
  //   edge     the content box's end edge, slide px: its right, or its left
  //            right to left;
  //   context  the block's own text context (collectRuns), which the "…" is
  //            set in: its style, the backdrop and decorations of its content.

  // ellipsisOf(el, s, walk) -> EllipsisCut | null for the block `el`
  // (computed style `s`) the walk is laying out; null unless its lines end in a
  // "…" where they overflow. Turned text is not cut: its rects do not say
  // where along its line a character lies, and its overflow clip, the turned
  // box's bounds, cuts it.
  function ellipsisOf(el, s, walk) {
    if (String(s.textOverflow) !== 'ellipsis' || s.overflowX === 'visible' || walk.frame.angle || walk.turned) {
      return null;
    }
    const box = env.boxGeometry(el, env.rectOf(el), walk.frame);
    const area = box ? env.contentBox(s, box) : null;
    if (!area) return null;
    const rtl = s.direction === 'rtl';
    return {
      edge: rtl ? area.x : area.x + area.w,
      rtl,
      context: {
        style: s,
        opacity: walk.opacity,
        backdrop: walk.backdrop,
        decoration: walk.decoration,
        baseline: null,
        nudgePx: 0,
        clip: walk.clip,
      },
    };
  }

  // The advance of the "…" in the face of the computed style `ps`, as the
  // browser sets it, in slide px at `scale`; null when its probe could not be
  // read. One probe per face, through the pristine probe measurer
  // (measureProbes), made when a line first needs it: it is off the page again
  // before the layout reads another rect.
  function ellipsisAdvance(ps, scale) {
    const css = browserCutCss(probeFaceOf(ps, familyOf(ps.fontFamily), 1));
    if (ellipsisAdvances[css] === undefined) {
      const sizes = measureProbes([{ css, text: ELLIPSIS, baseline: false }],
        'a text-overflow: ellipsis line exports as its overflow clip shows it, without its "…"');
      const width = sizes && sizes[0] ? Number(sizes[0].w) : NaN;
      ellipsisAdvances[css] = Number.isFinite(width) && width >= 0 ? width : null;
    }
    const advance = ellipsisAdvances[css];
    return advance === null ? null : advance * scale;
  }

  // The characters of a word token, {text, rect} each as painted: its text
  // node read one code point at a time from its origin (paintedCodePoints),
  // cased as the word was.
  function characterPieces(token, range) {
    const origin = token.origin;
    const pieces = paintedCodePoints(origin.source, origin.start, origin.end, false, origin.previous, range);
    const characters = [];
    for (let index = 0; index < pieces.length; index++) {
      characters.push({ text: pieces[index].text, rect: pieces[index].rects[0] });
    }
    return characters;
  }

  // Cuts a clustered line (clusterLines) that runs past its block's ellipsis
  // edge as Chrome cuts it. Every token whose rect ends within the edge less
  // the "…"'s advance stays; the word that limit falls in keeps the characters
  // that end within it, a character partly past it being hidden under the
  // "…"; a "…" token in the block's own style follows them; and every token
  // after is gone. A line whose text ends within the edge is left as it is,
  // and so is one whose "…" could not be measured (its overflow clip still
  // cuts it). The cut word, whole, and the words after it are hidden text: the
  // page reads them, the slide does not show them whole (each token's word,
  // recordHiddenWords).
  function truncateAtEllipsis(line, ellipsis, scale, range) {
    const rtl = ellipsis.rtl;
    const tokens = line.tokens;
    const beyond = (rect, edge) => (rtl ? rect.left < edge - ELLIPSIS_OVERFLOW_PX : rect.right > edge + ELLIPSIS_OVERFLOW_PX);
    let overflows = false;
    for (let index = 0; index < tokens.length && !overflows; index++) {
      if (!tokens[index].collapsible && beyond(tokens[index].rect, ellipsis.edge)) overflows = true;
    }
    if (!overflows) return;
    const advance = ellipsisAdvance(ellipsis.context.style, scale);
    if (advance === null) return;
    const limit = rtl ? ellipsis.edge + advance : ellipsis.edge - advance;
    const kept = [];
    let cut = false;
    for (let index = 0; index < tokens.length; index++) {
      const token = tokens[index];
      if (!cut && !beyond(token.rect, limit)) {
        kept.push(token);
        continue;
      }
      if (!cut && token.kind === 'text' && token.origin) {
        const characters = characterPieces(token, range);
        let text = '';
        let rect = null;
        for (let character = 0; character < characters.length; character++) {
          const piece = characters[character];
          if (beyond(piece.rect, limit)) break;
          text += piece.text;
          rect = rect
            ? { left: Math.min(rect.left, piece.rect.left), top: Math.min(rect.top, piece.rect.top), right: Math.max(rect.right, piece.rect.right), bottom: Math.max(rect.bottom, piece.rect.bottom) }
            : piece.rect;
        }
        if (text) kept.push({ ...token, text, rect, origin: null });
      }
      cut = true;
      // The word this token is part of is not shown whole, the cut one included.
      if (token.word) token.word.hidden = true;
    }
    // The "…" starts where the last token kept ends, or where the line starts
    // when none fits; it joins the segment of the last word kept.
    const last = kept.length ? kept[kept.length - 1] : tokens[0];
    const at = kept.length ? (rtl ? last.rect.left : last.rect.right) : (rtl ? last.rect.right : last.rect.left);
    let segment = 0;
    for (let index = kept.length - 1; index >= 0; index--) {
      if (kept[index].kind !== 'text') continue;
      segment = kept[index].segment;
      break;
    }
    const style = runStyle(ellipsis.context, scale);
    // The "…" stands on the line's own baseline, in the block's style: across,
    // it spans the body of the words the cut keeps, the text no super- or
    // subscript moves (assembleLine body), all of it where all of it is
    // moved. Chrome paints it unmoved, but the renderers draw it with its
    // line, so where every word the cut keeps shares one move it shares that
    // move too (its nudge, at the moved body): it then neither settles a moved
    // box nor, settled, moves a mixed one. The words cut away are not drawn,
    // so their moves count for nothing, and spaces paint nothing.
    const shared = sharedNudgeOf(kept, 0, kept.length - 1);
    const nudge = shared ? shared : 0;
    let body = null;
    for (let index = 0; index < kept.length; index++) {
      const token = kept[index];
      if (token.kind !== 'text' || token.style.baseline || !/\S/.test(token.text)) continue;
      body = unionBounds(body, nudge ? token.rect : settledBounds(token));
    }
    const top = body ? body.top : line.top;
    const bottom = body ? body.bottom : line.bottom;
    kept.push({
      kind: 'text',
      text: ELLIPSIS,
      rect: rtl
        ? { left: at - advance, top, right: at, bottom }
        : { left: at, top, right: at + advance, bottom },
      style,
      face: probeFaceOf(ellipsis.context.style, style.family, scale),
      collapsible: false,
      tabSize: DEFAULT_TAB_SIZE,
      segment,
      origin: null,
      nudge,
      word: null,
    });
    line.tokens = kept;
  }

  return { ellipsisOf, truncateAtEllipsis };
}

export const ELLIPSIS_SOURCE = createEllipsis.toString();
