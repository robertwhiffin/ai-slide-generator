// Text blocks: the snapshot's text, read from the page as the browser laid it
// out (spec §3 Text). snapshot.mjs composes TEXT_SOURCE into its page IIFE and
// calls the layout once per element its walk visits.
//
// Grouping. A text block is an element whose display is not inline (nor
// contents), plus the anonymous runs inside it. Each block becomes one text box:
// * a block container's consecutive inline-level content (text, display:inline
//   elements, atomic inlines and <br>) is one inline run; a block-level child
//   ends the run and is a block of its own, so bare text after a block child is
//   its own anonymous block (upstream #56);
// * every child element of a flex or grid container is its own block (CSS
//   blockifies it), and each run of child text is an anonymous item of its own,
//   so a footer's brand line and page number never share a paragraph (RC2);
// * an <svg>, <canvas> or other replaced element paints its own content: the
//   text walk never descends into it (RC3).
//
// Lines are the browser's: every word and space is measured with a Range, and
// tokens are clustered into lines in DOM order. White space collapses the way
// the browser collapsed it, read from the rects rather than re-derived.
//
// Pseudo-elements. An element's ::before is laid out as its first child and its
// ::after as its last (snapshot.mjs PseudoRecord): an inline one's text joins
// its host's line, so a quote's “ and ” are in the sentence's own text block,
// and a block, absolutely positioned or flex-item one is a text block of its
// own. Generated text is no DOM text, so no Range can measure it: each of its
// tokens is one inline text box the browser laid it out in, read through the
// DevTools protocol, at that box's rect (readGeneratedTokens).
//
// List markers. A list item's ::marker is Chrome's own text and box for it,
// never counted here, in its own computed style. Outside its item it is a
// single-line text item of its own where its glyphs end (markerBlock); inside,
// it is the first thing on its item's first line, a token of that line when
// the text runs straight on from it and a segment of its own when a gap
// follows it (readMarkerTokens, joinMarkers). See "list markers" below.
//
// Geometry comes from the text's own rects, not the element box, so an icon or
// logo beside the text never overlaps it; centred, right-aligned and justified
// text spans its container's content box so the alignment survives a slightly
// wider font. Every box carries width slack on the side its alignment grows.
//
// Inline decorations (spec §3 Text). A display:inline element that paints a
// box (a background, a uniform border or a shadow: a chip, <mark>, <kbd>, an
// empty status dot) is one box per fragment the browser laid it out in, its
// getClientRects(), so a chip that wraps is a box on each line. It belongs to
// the block its text is in, and paints under that block's text: the snapshot
// walk orders it there and draws no box of its own for the element.
//
// Inline boxes. An atomic inline (an inline <svg> or <img>, an inline-block
// pill or track) leaves a gap in its line that no text box can hold. A line
// that holds one is cut there: the text on each side of it is a block of its
// own, one line at its own bounds, so the text after an icon keeps its x
// instead of sliding into the icon's gap (RC13). The lines around it keep
// their own block. An inline element whose horizontal margin, border and
// padding take space (a chip, a <kbd>) leaves such gaps too, at either end of
// it, so its line is cut at both ends the same way: its own text is a
// segment, inside its decoration, and the text after it keeps its x.
//
// Visibility (spec §3 Visibility). A word that paints nothing is a gap in its
// line, cut like an atomic inline: hidden or transparent text keeps its room,
// so the text after it keeps its x, and a word a clip shows under 2 px of (a
// line a box cuts off, the visually-hidden pattern, text off the slide) is
// not slide text. The words a slide drops but the page still reads (its
// innerText, which leaves out visibility: hidden) are its hidden text, which
// the snapshot reports as model.reference.hiddenText.
//
// Ellipsis (R11e). A line of a block with text-overflow: ellipsis and an
// overflow other than visible that runs past its content box's end edge (the
// line box's, where Chrome ends the "…") shows the characters whose end lies
// within that edge less the "…"'s advance, then the "…": no more, whatever
// the overflow clip shows past it. The advance is the "…" in the block's own
// face, measured by probe; the cut word is measured character by character;
// and the "…" is a run in the block's own style, which is what Chrome paints
// it in even where the cut falls inside a differently styled inline
// (truncateAtEllipsis). The cut word and all after it are hidden text.
//
// Turned text. Under a rotation, and under a vertical writing mode, which sets
// Latin glyphs sideways, a Range rect is the axis-aligned bounds of a turned
// glyph run, so lines cannot be clustered from rects, and a renderer turns a
// whole text box or nothing. So the text of a turn root (snapshot.mjs
// TurnedText) is ONE text item (turnedBlock): the root's unrotated layout
// box, turned by its text's angle about the centre it shares with the root's
// bounds, its text set inside the content box by the box's insets, and the
// box grown by the slack its padding cannot hold, the layout box held where
// the browser has it (R11f). Its lines
// are its text in DOM order, broken at each <br>, preserved newline and block
// boundary (layoutTurnedRun), and where the browser wrapped a line: the
// centre of a turned rect is the centre of the run it bounds at any angle, so
// turned back about the root's centre it says where along the line, and on
// which line, the run lies (softWrapped). A vertical-lr root stacks its lines
// left to right, the other way from a box turned 90 degrees, so its lines are
// written in reverse.
//
// Runs carry the browser's typography (spec §3 Runs, RC7). It is read from the
// computed style of the text node's parent element. Three things CSS does not
// inherit reach a run from further up:
// * the backdrop its colour is composited over (snapshot.mjs backdropInside);
// * underline and line-through, which CSS propagates to in-flow inline
//   content: a <b> inside a <u> computes none and is underlined;
// * super- and subscript, from an inline ancestor's vertical-align.
// The weights of the webfonts the page loaded go to the slide model as
// model.fonts (loadedFonts), so the emitter can name a weight's face.
//
// Metrics (spec §3 Text, Spacing and Metrics) are read with offscreen probes
// in the page's own fonts, after the walk (applyMetrics):
// * a paragraph's line height in px (line-height: normal resolved to the
//   face's natural line height) and its largest run's ascent, from which the
//   emitter writes the renderers' line spacing and first-line offset;
// * a run whose width at the export cut (the static opsz-14 face PowerPoint and
//   Google Slides draw) differs from the width the browser drew by more than
//   0.5% carries the difference per character as tracking (task-4 A1).
//
// /**
//  * InlineGroup = {follows:Element|null, decorations:Decoration[], blocks:TextBlock[]}
//  *              (page-side only; never in the slide model): one run of a block's
//  *              inline content. The walk gives every item of it its order.
//  * Decoration = {element, style, opacity, boxes, clip}: an inline element, its computed
//  *              style, its cumulative opacity, one box (snapshot.mjs boxGeometry) per
//  *              fragment and the clip its boxes are cut to.
//  * TextBlock = {x,y,w,h, rotate:number|null, wrap, align:'left'|'center'|'right', rtl,
//  *              paragraphs:[{sizePx, lineHeightPx:number|null, ascentPx:number|null,
//  *                           lines:[{runs:Run[]}]}],
//  *              inset?: {left, top, right, bottom}}
//  * Run = {text, family, weight, italic, sizePx, color:'RRGGBB', letterSpacingPx,
//  *        underline, strike, baseline:null|'super'|'sub', opticalTrackingPx}
//  *
//  * A line after the first in its paragraph is a soft break; a line with no runs
//  * is a blank line (two <br>s, an empty pre line). Sizes are CSS px on the slide.
//  * y        the top of the first line's glyphs (its text's rects); the emitter
//  *          places the box above it by the calibrated first-line offset;
//  * rotate   degrees clockwise about the box's centre, 0..360: set on a turned
//  *          block (turnedBlock) alone, whose box is its root's layout box
//  *          grown by the part of its slack its padding does not hold;
//  * inset    a turned block's alone: where its text sits inside its box, px in
//  *          the box's own frame, each 0 or more. left and right are its
//  *          content box's edges, less the slack its padding holds on the side
//  *          its alignment grows; top is how far below the box's top its first
//  *          line's glyphs start; bottom is 0. Its y is the box's top, and the
//  *          emitter takes the first-line offset off the top inset instead;
//  * align    a justified block is 'left' ('right' when right-to-left): see textBlock;
//  * sizePx   the size of the paragraph's largest run;
//  * lineHeightPx  the paragraph's CSS line height, the natural one for
//  *          line-height: normal; null when unread;
//  * ascentPx the largest run's ascent: its glyph top to its baseline; null when unread;
//  * text     as painted: text-transform applied;
//  * family   the first face in the stack that is not a generic or a system alias;
//  *          a stack of generics alone is Arial, Times New Roman or Courier New;
//  * weight   100..900, the computed weight to the nearest hundred;
//  * color    solid, pre-blended: what the browser paints the glyphs with, composited
//  *          layer by layer over the backdrop (Drive drops text alpha);
//  * opticalTrackingPx    tracking added to letterSpacingPx after every character,
//  *          so the run is as wide at the export cut as the browser drew it; 0
//  *          when the two widths agree within 0.5%.
//  */

// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE: domAccess,
// childNodesOf, queryOne, reportCollectionLoss, DOM_ACCESS_LOG_PREFIX and the two
// limits are its free names. It is stringified, so it closes over nothing on the
// Node side; what it needs from the snapshot arrives in `env`:
//   replaced        the Set of tag names whose content is drawn, not laid out as text;
//   opacityOf       computed style -> its own opacity;
//   backdropInside  (backdrop, style) -> the backdrop of the content inside that element;
//   textColour      (backdrop, style) -> 'RRGGBB', the solid colour its text paints;
//   boxGeometry     (element, rect, frame) -> the element's box | null;
//   contentBox      (style, box) -> the box inside border and padding | null;
//   paintsBox       (style, opacity, element) -> whether the element's box paints
//                   anything, as a shape or as a box-only capture (a pseudo-element
//                   that generates an image is one);
//   inlineClip      (clip, element, style, frame) -> the clip of an inline element's
//                   content, given the clip of the text around it;
//   shows           (bounds, clip) -> whether the clip shows {left, top, right, bottom};
//   isPseudo        node -> whether it is a pseudo-element (a PseudoRecord), read
//                   without touching a DOM node's own properties;
//   pseudoOf        element -> {before, after}, its pseudo-elements, or null;
//   rectOf          element -> its border box bounds, {left, top, width, height}.
// Wherever this layout takes an element, a pseudo-element will do.
function createTextLayout(env) {
  const TEXT_NODE = 3;
  const ELEMENT_NODE = 1;
  const NBSP = '\u00a0';
  // Spec §3 Text, Wrapping: width slack, because Google's importer ignores wrap="none".
  const SLACK_FRACTION = 0.06;
  const SLACK_PX = 4;
  // Metric probes: a <div> on documentElement, offscreen and hidden, so it
  // moves nothing in body's layout; white-space: pre so it never wraps, and no
  // box edges, so its border box is its text.
  const PROBE_STYLE = 'position:absolute;left:-10000px;top:0;visibility:hidden;white-space:pre;' +
    'margin:0;padding:0;border:0;text-indent:0;text-transform:none;';
  // Under line-height: normal the probe's height is the face's natural line height.
  const LINE_PROBE_TEXT = 'Hg';
  // An empty inline-block sits with its bottom on the baseline; at zero height
  // its top is the baseline too.
  const BASELINE_MARKER_STYLE = 'display:inline-block;width:0;height:0;vertical-align:baseline;' +
    'margin:0;padding:0;border:0;';
  // The optical size of the static cut PowerPoint and Google Slides draw (DM Sans
  // ships it as its text cut), and how far a run's width there may differ from
  // the browser's before it is compensated (task-4 A1).
  const EXPORT_CUT_OPTICAL_SIZE = 14;
  const OPTICAL_SIZE_THRESHOLD = 0.005;
  // Characters a renderer spaces as one with the character before them: combining
  // marks, the zero-width joiners and the variation selectors.
  const JOINS_PREVIOUS = /^[\p{M}‌‍︀-️\u{E0100}-\u{E01EF}]$/u;
  // A token is on a new line only when its vertical overlap with the line is at
  // most this fraction of the smaller height. Not "any overlap": glyph rects are
  // the font's ascent plus descent, so under a line-height below about 1.3 (the
  // corpus titles use 1.08) consecutive lines' rects overlap by several px.
  const SAME_LINE_OVERLAP = 0.5;
  // ... and only when it also moved back towards the line start, past the
  // previous token's far edge by more than this (sub-pixel kerning between
  // adjacent tokens on one line is never a wrap).
  const WRAP_BACKSTEP_PX = 1;
  // Every field a Run carries besides its text. Adjacent tokens equal in all of
  // them are one run.
  const RUN_STYLE_FIELDS = [
    'family', 'weight', 'italic', 'sizePx', 'color',
    'letterSpacingPx', 'underline', 'strike', 'baseline',
  ];
  const BREAK = { kind: 'break' };
  // Either edge of an inline element whose horizontal margin, border and padding
  // add up to more than this moves the text after it by more than a renderer's
  // own rounding, so the element is a cut in its line (collectRuns).
  const INLINE_EDGE_PX = 0.5;
  const OPENING_EDGE = { kind: 'edge', opens: true };
  const CLOSING_EDGE = { kind: 'edge', opens: false };
  // An inside marker joins its item's first line only when the text after it
  // starts within this of where the marker's text, trailing space included,
  // ends in its font: then a renderer that sets the two as one line puts the
  // text where the browser did. Else a gap follows it (an inside disc's margin).
  const INSIDE_JOIN_PX = 1;
  // Chrome's default tab-size; a computed length instead of a count falls back to it.
  const DEFAULT_TAB_SIZE = 8;
  // A generic family keyword or a system alias names no face an importer can
  // resolve, so a run takes the first face after them. A stack of nothing else
  // takes, for its first one, a face every machine has. A plain table, read
  // with hasOwnProperty: page script can replace Map and Set.
  const GENERIC_FACES = {
    'serif': 'Times New Roman',
    'ui-serif': 'Times New Roman',
    'fangsong': 'Times New Roman',
    'monospace': 'Courier New',
    'ui-monospace': 'Courier New',
    'sans-serif': 'Arial',
    'ui-sans-serif': 'Arial',
    'ui-rounded': 'Arial',
    'system-ui': 'Arial',
    '-apple-system': 'Arial',
    'blinkmacsystemfont': 'Arial',
    'cursive': 'Arial',
    'fantasy': 'Arial',
    'emoji': 'Arial',
    'math': 'Arial',
  };
  const DEFAULT_FACE = 'Arial';
  const REGULAR_WEIGHT = 400;
  const BOLD_WEIGHT = 700;
  const LIGHTEST_WEIGHT = 100;
  const HEAVIEST_WEIGHT = 900;
  const WEIGHT_STEP = 100;
  const NO_DECORATION = { underline: false, strike: false };
  // What continues a word for capitalize: the browser upper-cases a lowercase
  // letter after any other character.
  const INSIDE_A_WORD = /[\p{L}\p{N}\p{M}'’]/u;
  const LOWERCASE_LETTER = /^\p{Ll}$/u;
  // What Chrome paints where text-overflow: ellipsis cuts a line.
  const ELLIPSIS = '…';
  // A line runs past its content box's end edge when its text ends beyond it
  // by more than this: the layout unit (1/64 px), so a line that fits exactly
  // is never cut.
  const ELLIPSIS_OVERFLOW_PX = 1 / 64;
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
  // A word under a turn starts a line of its own where the browser wrapped
  // before it: its centre lies more than this fraction of the larger font size
  // across the line from the word before it, and back towards the line start.
  // A wrap moves a word a whole line height; a baseline shift or a mixed size
  // on one line moves it under half its size.
  const SOFT_WRAP_FRACTION = 0.5;

  const dom = domAccess();
  // Text layout is bounded on its own: every child node listed and every rect
  // read spends from one budget, so a realm that lies about the tree or about a
  // Range's rects cannot make the text pass run forever. Meeting the bound is
  // announced; the text past it is missing from the slide.
  let budget = COLLECTION_ITEM_LIMIT;
  let truncated = false;
  // What applyMetrics reads once the walk is done, so no probe is in the page
  // while the walk reads its Range rects:
  //   paragraphs  {paragraph, face, lineHeight}
  //   runs        {run, face, width: the browser's px | null (a justified line,
  //                whose drawn width includes the stretch)}
  const pendingParagraphs = [];
  const pendingRuns = [];
  //   turned      {block, line, centre, angle}: a turned block, whose top inset
  //               comes from where its first line lies (applyMetrics)
  const pendingTurned = [];
  // The advance of the "…" per probe face, in unscaled px (null when it could
  // not be measured), measured once each (ellipsisAdvance).
  const ellipsisAdvances = Object.create(null);
  // The slide's hidden text (hiddenText), in the order it is read. `dropping`
  // is true while the tokens read in a row are all dropped, so a word split
  // over two text nodes ("Rev<b>enue</b>") is recorded whole.
  const hiddenParts = [];
  let dropping = false;

  function spend(count) {
    if (budget <= 0 || count > budget) {
      budget = 0;
      if (!truncated) {
        truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' text reads', 'the snapshot text layout');
      }
      return false;
    }
    budget -= count;
    return true;
  }

  // ─── grouping ────────────────────────────────────────────────────────
  // An element's tag name in lower case; a pseudo-element's is '::before' or '::after'.
  function nameOf(element) {
    return env.isPseudo(element) ? element.name : String(dom.tagName(element) || '').toLowerCase();
  }

  // How a child element takes part in its block container's inline content.
  function inlineRole(name, cs) {
    if (cs.position === 'absolute' || cs.position === 'fixed' || (cs.float && cs.float !== 'none')) {
      return 'out-of-flow';
    }
    const display = String(cs.display);
    const ruby = /^ruby/.test(display);
    if (!(display === 'inline' || ruby || /^inline[- ]/.test(display))) return 'block';
    if (env.replaced.has(name)) return 'atomic';
    return display === 'inline' || ruby ? 'inline' : 'atomic';
  }

  // What a text node paints with, carried down the inline descent:
  //   {style, opacity, backdrop, decoration, baseline, clip}
  //   style       its parent element's computed style;
  //   opacity     the cumulative opacity it paints at;
  //   backdrop    what it is composited over (snapshot.mjs backdropInside);
  //   decoration  {underline, strike} propagated to it;
  //   baseline    'super' | 'sub' from an inline ancestor's vertical-align, else null;
  //   clip        what clips it (snapshot.mjs shownPart): its block's content clip,
  //               narrowed by each inline ancestor's own clip-path.
  // `closesWith` is a piece the run takes once the node's children are done, or
  // null. Returns whether the children were opened. An element's children are
  // its child nodes between its own ::before and ::after, a list item's inside
  // ::marker ahead of them all; a pseudo-element's are the pieces of its
  // generated text (`generated`). An outside marker is no part of its item's
  // lines: it is drawn on its own (markerBlock).
  function openChildren(stack, node, context, depth, closesWith) {
    if (depth > WALK_STEP_LIMIT) {
      if (!truncated) {
        truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'cut at depth ' + WALK_STEP_LIMIT, 'the snapshot text layout');
      }
      return false;
    }
    if (budget <= 0) return false;
    const generated = env.isPseudo(node);
    const nodes = generated ? node.pieces : childNodesOf(node);
    if (!spend(nodes.length)) return false;
    const pseudo = generated ? null : env.pseudoOf(node);
    stack.push({
      nodes,
      index: 0,
      context,
      depth,
      closesWith: closesWith || null,
      generated,
      marker: pseudo && pseudo.marker && pseudo.marker.list.inside ? pseudo.marker : null,
      before: pseudo ? pseudo.before : null,
      after: pseudo ? pseudo.after : null,
    });
    return true;
  }

  // The next child of a frame: its inside ::marker, its ::before, then its
  // child nodes, then its ::after. Null once all are taken.
  function nextChild(frame) {
    if (frame.marker) {
      const marker = frame.marker;
      frame.marker = null;
      return marker;
    }
    if (frame.before) {
      const before = frame.before;
      frame.before = null;
      return before;
    }
    if (frame.index < frame.nodes.length) return frame.nodes[frame.index++];
    if (frame.after) {
      const after = frame.after;
      frame.after = null;
      return after;
    }
    return null;
  }

  // The horizontal space an inline element takes on one side of what it holds:
  // its margin, border and padding there (a border with no style computes to 0).
  function inlineEdge(cs, side) {
    return (parseFloat(cs['margin' + side]) || 0) + (parseFloat(cs['border' + side + 'Width']) || 0) +
      (parseFloat(cs['padding' + side]) || 0);
  }

  // Whether an inline element's edges move the text around it: PowerPoint and
  // Google Slides lay a paragraph's runs out with no room for them, so the text
  // inside a chip would start at its left edge and the text after it slide left
  // into it.
  function hasInlineEdges(cs) {
    return Math.abs(inlineEdge(cs, 'Left')) > INLINE_EDGE_PX || Math.abs(inlineEdge(cs, 'Right')) > INLINE_EDGE_PX;
  }

  // The context inside an inline child element. Its own opacity, background,
  // decoration, vertical-align and clip-path apply to the text it holds.
  // `frame` is its block's transform frame: an inline box has none of its own.
  function inlineContext(outer, element, cs, frame) {
    return {
      style: cs,
      opacity: outer.opacity * env.opacityOf(cs),
      backdrop: env.backdropInside(outer.backdrop, cs),
      decoration: decorationInside(outer.decoration, cs, false),
      baseline: baselineShiftOf(cs) || outer.baseline,
      clip: env.inlineClip(outer.clip, element, cs, frame),
    };
  }

  // The container's runs, in DOM order. Each is {nodes, follows}: `follows` is
  // the block-level child the run comes after (null for the leading run), and
  // `nodes` its pieces in DOM order:
  //   {kind:'text', node, context}  a text node and what it paints with;
  //   {kind:'break'}                a <br>;
  //   {kind:'atomic', element}      an atomic inline: it paints its own
  //                                 content (its own block, or a picture)
  //                                 and gives the run no text;
  //   {kind:'decoration', element, style, opacity, clip}
  //                                 a visible inline element whose box paints,
  //                                 at its cumulative opacity and cut to its
  //                                 clip, before the pieces it holds. It keeps
  //                                 a run with no text (an empty status dot) a run;
  //   {kind:'edge', opens}          either end of an inline element with
  //                                 edges (hasInlineEdges): an opening one
  //                                 before the pieces it holds and a closing
  //                                 one after, so its lines are cut there, as
  //                                 at an atomic inline;
  //   {kind:'generated', piece, context}
  //                                 one piece of a pseudo-element's generated
  //                                 text and what it paints with;
  //   {kind:'marker', marker, context}
  //                                 a list item's inside ::marker with text
  //                                 (snapshot.mjs PseudoRecord) and what it
  //                                 paints with: its own style. One that
  //                                 paints an image instead is an atomic
  //                                 inline, a gap where its picture is.
  // A pseudo-element takes part like an element child, at its host's start or
  // end. display:contents children are transparent: no box, so no opacity,
  // background, decoration or clip of their own. display:none ones are skipped.
  // A transparent inline element's text is still read: it keeps its room in
  // the line, so it is a gap there (readTokens).
  // `walk` is the container's {opacity, frame, backdrop, decoration, clip}
  // from the snapshot walk; the container's own vertical-align is already
  // where the browser placed its text, so its runs start on the baseline.
  function collectRuns(container, containerStyle, walk, itemsAreBlocks) {
    const runs = [];
    let run = [];
    let follows = null;
    const stack = [];
    openChildren(stack, container, {
      style: containerStyle,
      opacity: walk.opacity,
      backdrop: walk.backdrop,
      decoration: walk.decoration,
      baseline: null,
      clip: walk.clip,
    }, 1);
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const node = nextChild(frame);
      if (!node) {
        stack.pop();
        if (frame.closesWith) run.push(frame.closesWith);
        continue;
      }
      if (frame.generated) {
        run.push({ kind: 'generated', piece: node, context: frame.context });
        continue;
      }
      const generated = env.isPseudo(node);
      if (generated && node.list) {
        run.push(node.list.glyphs
          ? { kind: 'marker', marker: node, context: inlineContext(frame.context, node, node.style, walk.frame) }
          : { kind: 'atomic', element: node });
        continue;
      }
      const type = generated ? ELEMENT_NODE : dom.nodeType(node);
      if (type === TEXT_NODE) {
        run.push({ kind: 'text', node, context: frame.context });
        continue;
      }
      if (type !== ELEMENT_NODE) continue;
      const name = nameOf(node);
      const cs = generated ? node.style : window.getComputedStyle(node);
      if (cs.display === 'none') continue;
      if (cs.display === 'contents') {
        const outer = frame.context;
        openChildren(stack, node, {
          style: cs,
          opacity: outer.opacity,
          backdrop: outer.backdrop,
          decoration: outer.decoration,
          baseline: outer.baseline,
          clip: outer.clip,
        }, frame.depth + 1);
        continue;
      }
      const role = itemsAreBlocks ? 'block' : name === 'br' ? 'break' : inlineRole(name, cs);
      if (role === 'break') {
        run.push(BREAK);
      } else if (role === 'block') {
        if (run.length) runs.push({ nodes: run, follows });
        run = [];
        follows = node;
      } else if (role === 'atomic') {
        run.push({ kind: 'atomic', element: node });
      } else if (role === 'inline') {
        const context = inlineContext(frame.context, node, cs, walk.frame);
        // Its edges take their space even where nothing of it shows, so they
        // cut the line whatever its opacity or visibility.
        const edged = hasInlineEdges(cs);
        if (edged) run.push(OPENING_EDGE);
        if (context.opacity > 0 && cs.visibility === 'visible' && env.paintsBox(cs, context.opacity, node)) {
          run.push({ kind: 'decoration', element: node, style: cs, opacity: context.opacity, clip: context.clip });
        }
        if (openChildren(stack, node, context, frame.depth + 1, edged ? CLOSING_EDGE : null)) continue;
        if (edged) run.push(CLOSING_EDGE);
      }
      // An out-of-flow child (a float, an absolute box) leaves the line where it
      // is: it is a block of its own and does not split the text around it.
    }
    if (run.length) runs.push({ nodes: run, follows });
    return runs;
  }

  // ─── run style ───────────────────────────────────────────────────────
  // The faces of a font-family stack in order, quotes stripped. Commas inside
  // a quoted name do not separate faces.
  function familyNames(stack) {
    const value = String(stack || '');
    const names = [];
    let quote = '';
    let start = 0;
    for (let index = 0; index <= value.length; index++) {
      const end = index === value.length;
      const character = value[index];
      if (quote && !end) {
        if (character === quote) quote = '';
      } else if (!end && (character === '"' || character === "'")) {
        quote = character;
      } else if (end || character === ',') {
        const name = value.slice(start, index).trim().replace(/^["']|["']$/g, '').trim();
        if (name) names.push(name);
        start = index + 1;
      }
    }
    return names;
  }

  // The run's family: the first face that is not a generic keyword or a system
  // alias, else the face the first generic maps to. Quoted or not: Chrome
  // serialises BlinkMacSystemFont as the quoted family "system-ui".
  function familyOf(stack) {
    const names = familyNames(stack);
    let generic = null;
    for (let index = 0; index < names.length; index++) {
      const key = names[index].toLowerCase();
      if (Object.prototype.hasOwnProperty.call(GENERIC_FACES, key)) {
        if (generic === null) generic = GENERIC_FACES[key];
        continue;
      }
      return names[index];
    }
    return generic || DEFAULT_FACE;
  }

  // The computed weight to the nearest hundred: a variable font's 450 is 500.
  function weightOf(value) {
    const weight = parseFloat(value);
    if (!Number.isFinite(weight)) return REGULAR_WEIGHT;
    const rounded = Math.round(weight / WEIGHT_STEP) * WEIGHT_STEP;
    return Math.min(HEAVIEST_WEIGHT, Math.max(LIGHTEST_WEIGHT, rounded));
  }

  // The decorations painted on an element's text: its own text-decoration-line
  // plus the ones propagated to it. CSS propagates a decoration to in-flow
  // content and not into an `isolated` box, one that is out of flow (absolute,
  // fixed, float) or an atomic inline (inline-block, inline-flex…). It is not
  // inherited: a <b> inside a <u> computes none and is still underlined.
  function decorationInside(outer, s, isolated) {
    const own = String(s.textDecorationLine || '');
    const underline = /\bunderline\b/.test(own);
    const strike = /\bline-through\b/.test(own);
    const propagated = isolated || !outer ? NO_DECORATION : outer;
    if (!underline && !strike) return propagated;
    return { underline: underline || propagated.underline, strike: strike || propagated.strike };
  }

  // decorationOf(outer, element, s) -> {underline, strike}: the decorations on
  // the text of an element the snapshot walk visits, given its parent's (null
  // at the root).
  function decorationOf(outer, element, s) {
    const role = inlineRole(nameOf(element), s);
    return decorationInside(outer, s, role === 'out-of-flow' || role === 'atomic');
  }

  // isInlineBox(name, s) -> whether the element (tag name, computed style) is a
  // non-atomic inline box: its box paints per line fragment, as a decoration
  // of the block whose text it is in (collectRuns), never as one box of its own.
  function isInlineBox(name, s) {
    return inlineRole(name, s) === 'inline';
  }

  function baselineShiftOf(s) {
    return s.verticalAlign === 'super' ? 'super' : s.verticalAlign === 'sub' ? 'sub' : null;
  }

  function runStyle(context, scale) {
    const ps = context.style;
    const letterSpacing = parseFloat(ps.letterSpacing);
    return {
      family: familyOf(ps.fontFamily),
      weight: weightOf(ps.fontWeight),
      italic: ps.fontStyle !== 'normal',
      sizePx: (parseFloat(ps.fontSize) || 0) * scale,
      color: env.textColour(context.backdrop, ps),
      letterSpacingPx: Number.isFinite(letterSpacing) ? letterSpacing * scale : 0,
      underline: context.decoration.underline,
      strike: context.decoration.strike,
      baseline: context.baseline,
    };
  }

  // The face a run is set in, as CSS for the metric probes (applyMetrics):
  //   font         style, weight, size, stretch and family. The family is the
  //                run's own first, then the element's stack: the run's family is
  //                what the export names and the renderers draw, and where the
  //                page has no such face the probe falls back as the text did;
  //   typesetting  what else sets the width: tracking, word spacing, kerning,
  //                features and variants;
  //   variation    the element's font-variation-settings;
  //   optical      its font-optical-sizing;
  //   scale        the block's transform scale: probes are set at the computed,
  //                unscaled size, and their widths and heights scale with it.
  function probeFaceOf(ps, family, scale) {
    const quoted = '"' + String(family).replace(/[\u0000-\u001F]/g, '').replace(/["\\]/g, '\\$&') + '"';
    return {
      font: 'font-style:' + ps.fontStyle + ';font-weight:' + ps.fontWeight + ';font-size:' + ps.fontSize +
        ';font-stretch:' + ps.fontStretch + ';font-family:' + quoted + ',' + ps.fontFamily + ';',
      typesetting: 'letter-spacing:' + ps.letterSpacing + ';word-spacing:' + ps.wordSpacing +
        ';font-kerning:' + ps.fontKerning + ';font-feature-settings:' + ps.fontFeatureSettings +
        ';font-variant:' + ps.fontVariant + ';',
      variation: String(ps.fontVariationSettings || 'normal'),
      optical: String(ps.fontOpticalSizing || 'auto'),
      scale,
    };
  }

  // A word's text as text-transform paints it. `previous` is the character just
  // before it in the inline content, '' at a start, after a break or after an
  // atomic inline. capitalize upper-cases each lowercase letter that follows
  // anything but a letter, a digit, a combining mark or an apostrophe, which
  // are the browser's word boundaries: "well-known (hello) 1st o’neil e.g." is
  // "Well-Known (Hello) 1st O’neil E.G.".
  function casedText(text, transform, previous) {
    if (transform === 'uppercase') return text.toUpperCase();
    if (transform === 'lowercase') return text.toLowerCase();
    if (transform !== 'capitalize') return text;
    let result = '';
    let before = previous;
    let index = 0;
    while (index < text.length) {
      const character = text.slice(index, index + codePointLength(text, index));
      index += character.length;
      result += LOWERCASE_LETTER.test(character) && !INSIDE_A_WORD.test(before) ? character.toUpperCase() : character;
      before = character;
    }
    return result;
  }

  // The last code point of data[start, end), the character the next token follows.
  function lastCodePoint(data, start, end) {
    const pairStart = end - 2;
    if (pairStart >= start && codePointLength(data, pairStart) === 2) return data.slice(pairStart, end);
    return data.slice(end - 1, end);
  }

  // ─── webfonts ────────────────────────────────────────────────────────
  // A face's weight descriptor as the hundreds it covers: "600" is [600], a
  // variable face's "100 900" every hundred from 100 to 900.
  function faceWeights(descriptor) {
    const parts = String(descriptor || '').trim().split(/\s+/);
    const bounds = [];
    for (let index = 0; index < parts.length && index < 2; index++) {
      const value = parts[index] === 'normal' ? REGULAR_WEIGHT : parts[index] === 'bold' ? BOLD_WEIGHT : parseFloat(parts[index]);
      if (Number.isFinite(value)) bounds.push(value);
    }
    if (!bounds.length) return [];
    const low = Math.min(bounds[0], bounds[bounds.length - 1]);
    const high = Math.max(bounds[0], bounds[bounds.length - 1]);
    const weights = [];
    for (let weight = LIGHTEST_WEIGHT; weight <= HEAVIEST_WEIGHT; weight += WEIGHT_STEP) {
      if (weight >= low && weight <= high) weights.push(weight);
    }
    return weights.length ? weights : [weightOf(low)];
  }

  // loadedFonts() -> model.fonts: family -> the weights (100..900) of its faces
  // in document.fonts whose status is 'loaded', the webfonts the page painted
  // with. The emitter names a weight's face only for such a family
  // (emit_typography.cjs typefaceFor). document.fonts is a FontFaceSet, not a
  // DOM collection, so it is read with its own iterator. Page script can
  // replace that iterator too, so the read is bounded by COLLECTION_ITEM_LIMIT,
  // and a throw keeps the faces read before it.
  function loadedFonts() {
    // No prototype, so no family name can reach an inherited property or setter.
    const fonts = Object.create(null);
    try {
      const iterator = document.fonts.values();
      let read = 0;
      for (; read < COLLECTION_ITEM_LIMIT; read++) {
        const step = iterator.next();
        if (!step || step.done) break;
        const face = step.value;
        if (!face || face.status !== 'loaded') continue;
        const family = String(face.family || '').trim().replace(/^["']|["']$/g, '').trim();
        if (!family) continue;
        if (!fonts[family]) fonts[family] = [];
        const weights = faceWeights(face.weight);
        for (let index = 0; index < weights.length; index++) {
          if (fonts[family].indexOf(weights[index]) < 0) fonts[family].push(weights[index]);
        }
      }
      if (read >= COLLECTION_ITEM_LIMIT) {
        truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' font faces', 'the snapshot webfont read');
      }
    } catch (e) {
      console.warn('[html2pptx] document.fonts could not be read (' + (e && e.message) +
        '); a family whose faces were not read exports without weight-named faces');
    }
    const families = Object.keys(fonts);
    for (let index = 0; index < families.length; index++) fonts[families[index]].sort((a, b) => a - b);
    return fonts;
  }

  function sameStyle(a, b) {
    for (let index = 0; index < RUN_STYLE_FIELDS.length; index++) {
      if (a[RUN_STYLE_FIELDS[index]] !== b[RUN_STYLE_FIELDS[index]]) return false;
    }
    return true;
  }

  // ─── tokens ──────────────────────────────────────────────────────────
  // What white-space keeps. white-space-collapse is the longhand Chrome
  // computes; the white-space keyword is the fallback for an engine without it.
  function whiteSpaceOf(ps) {
    const collapse = String(ps.whiteSpaceCollapse || '');
    if (collapse) {
      return {
        spaces: collapse === 'preserve' || collapse === 'break-spaces' || collapse === 'preserve-spaces',
        newlines: collapse === 'preserve' || collapse === 'break-spaces' || collapse === 'preserve-breaks',
      };
    }
    const keyword = String(ps.whiteSpace || 'normal');
    const preserved = keyword === 'pre' || keyword === 'pre-wrap' || keyword === 'break-spaces';
    return { spaces: preserved, newlines: preserved || keyword === 'pre-line' };
  }

  function tabSizeOf(ps) {
    const value = Number(ps.tabSize);
    return Number.isInteger(value) && value > 0 ? value : DEFAULT_TAB_SIZE;
  }

  // CSS white space: space, tab, line feed, carriage return, form feed. Never
  // NBSP, which JS \s would include.
  function characterKind(code, mode) {
    if (code === 10 && mode.newlines) return 'break';
    if (code === 32 || code === 9 || code === 10 || code === 13 || code === 12) return 'space';
    return 'word';
  }

  // The token's painted rects. A word paints when a rect has any extent. A
  // space paints only when a rect has width: Chrome reports a collapsed space
  // as a zero-width rect, and the space at a wrap point as a zero-width rect
  // on each line, never as no rect at all.
  function paintedRects(range, space) {
    const rects = range.getClientRects();
    const reported = Number(rects && rects.length) || 0;
    const length = Math.min(Math.max(reported, 0), COLLECTION_ITEM_LIMIT);
    if (!spend(length)) return [];
    const painted = [];
    for (let index = 0; index < length; index++) {
      const rect = rects[index];
      if (!rect) continue;
      const width = Number(rect.width);
      const height = Number(rect.height);
      if (space ? width > 0 : width > 0 || height > 0) {
        painted.push({
          left: Number(rect.left),
          top: Number(rect.top),
          right: Number(rect.right),
          bottom: Number(rect.bottom),
        });
      }
    }
    return painted;
  }

  // ─── fragments ───────────────────────────────────────────────────────
  // An element's box fragments, its getClientRects() as {left, top, width,
  // height}, in the browser's order. The method, the DOMRectList it returns
  // and the DOMRects in it are read through the pristine realm (dom_access.mjs),
  // because page script can replace each of them. An element has one fragment
  // per line box it lies on, so a list longer than WALK_STEP_LIMIT is a lie:
  // the read stops there and the loss is announced. Every rect read spends from
  // the layout's budget. A rect whose values are not finite numbers is dropped.
  // A pseudo-element's fragments were read through the DevTools protocol
  // (snapshot.mjs PseudoRecord), already bounded and checked.
  function fragmentsOf(element) {
    const fragments = [];
    if (env.isPseudo(element)) {
      const read = element.fragments;
      if (!spend(read.length)) return fragments;
      for (let index = 0; index < read.length; index++) fragments.push(read[index]);
      return fragments;
    }
    let list;
    let reported;
    try {
      list = dom.clientRects(element);
      reported = Number(dom.rectListLength(list));
    } catch (e) {
      console.warn('[html2pptx] the box fragments of an inline element could not be read (' +
        (e && e.message) + '); its box is not in the exported deck');
      return fragments;
    }
    if (!(reported >= 0)) {
      truncated = true;
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'dropped entirely, length read as ' + String(reported), 'the snapshot inline fragments');
      return fragments;
    }
    if (reported > WALK_STEP_LIMIT) {
      truncated = true;
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + WALK_STEP_LIMIT + ' of ' + reported + ' box fragments', 'the snapshot inline fragments');
    }
    const length = Math.min(reported, WALK_STEP_LIMIT);
    if (!spend(length)) return fragments;
    try {
      for (let index = 0; index < length; index++) {
        const rect = dom.rectAt(list, index);
        if (!rect) continue;
        const bounds = dom.rectBounds(rect);
        const fragment = {
          left: Number(bounds.left),
          top: Number(bounds.top),
          width: Number(bounds.width),
          height: Number(bounds.height),
        };
        if (Number.isFinite(fragment.left) && Number.isFinite(fragment.top) &&
            Number.isFinite(fragment.width) && Number.isFinite(fragment.height)) {
          fragments.push(fragment);
        }
      }
    } catch (e) {
      console.warn('[html2pptx] reading the box fragments of an inline element failed (' +
        (e && e.message) + '); the fragments past that point are not in the exported deck');
    }
    return fragments;
  }

  // The union {left, top, width, height} of fragments, or null for none.
  function unionOf(fragments) {
    if (!fragments.length) return null;
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (let index = 0; index < fragments.length; index++) {
      const fragment = fragments[index];
      left = Math.min(left, fragment.left);
      top = Math.min(top, fragment.top);
      right = Math.max(right, fragment.left + fragment.width);
      bottom = Math.max(bottom, fragment.top + fragment.height);
    }
    return { left, top, width: right - left, height: bottom - top };
  }

  // An atomic inline's place in its line, {left, top, right, bottom}: the union
  // of its fragments that have width. Null when it has none, because then it
  // leaves no gap in the line to cut it at.
  function atomicRect(element) {
    const fragments = fragmentsOf(element);
    const wide = [];
    for (let index = 0; index < fragments.length; index++) {
      if (fragments[index].width > 0) wide.push(fragments[index]);
    }
    const union = unionOf(wide);
    if (!union) return null;
    return { left: union.left, top: union.top, right: union.left + union.width, bottom: union.top + union.height };
  }

  // A preserved space token's text: every space a NBSP, so no importer
  // collapses or trims it. A tab stays a tab until its line is assembled,
  // where its column is known.
  function preservedSpaces(text) {
    let result = '';
    for (let index = 0; index < text.length; index++) {
      const character = text[index];
      if (character === '\t') result += '\t';
      else if (character === ' ' || character === '\n') result += NBSP;
    }
    return result;
  }

  function codePointLength(data, index) {
    const code = data.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff && index + 1 < data.length) {
      const next = data.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) return 2;
    }
    return 1;
  }

  // A token whose range painted on more than one rect crossed a line (a wrap
  // at a hyphen, CJK text that breaks anywhere) or a direction change. It is
  // split into code points, each measured on its own; a code point that paints
  // nothing (a joiner, a combining mark) travels with its neighbour, so no
  // character is lost. Each code point is cased after the one before it, so a
  // word that wraps at its hyphen capitalises as it would on one line. A code
  // point the clip hides is dropped (dropToken), so a word cut off on its
  // second line keeps its first.
  //   source    one text node's {node, data, mode, style, tabSize, transform,
  //             segment, hidden, recordsHidden, clip} (readTokens);
  //   previous  the character before the token (casedText).
  function splitToken(source, start, end, space, previous, range, tokens) {
    const pieces = [];
    let pending = '';
    let pendingStart = start;
    let pendingBefore = previous;
    let before = previous;
    let index = start;
    while (index < end) {
      const length = codePointLength(source.data, index);
      const raw = source.data.slice(index, index + length);
      const text = space ? preservedSpaces(raw) : casedText(raw, source.transform, before);
      const charBefore = before;
      before = raw;
      range.setStart(source.node, index);
      range.setEnd(source.node, index + length);
      const charStart = index;
      index += length;
      const rects = paintedRects(range, space);
      if (!rects.length) {
        if (pieces.length) {
          pieces[pieces.length - 1].text += text;
          pieces[pieces.length - 1].end = index;
        } else {
          if (!pending) {
            pendingStart = charStart;
            pendingBefore = charBefore;
          }
          pending += text;
        }
        continue;
      }
      pieces.push({
        text: pending + text,
        rects,
        shown: anyShown(rects, source.clip),
        start: pending ? pendingStart : charStart,
        end: index,
        previous: pending ? pendingBefore : charBefore,
      });
      pending = '';
    }
    for (let piece = 0; piece < pieces.length; piece++) {
      const read = pieces[piece];
      if (read.shown) {
        pushTextToken(source, read.text, read.rects[0], false, tokens,
          space ? null : { source, start: read.start, end: read.end, previous: read.previous });
      } else {
        dropToken(source, read.text, read.rects, tokens);
      }
    }
    return pieces.length > 0;
  }

  // Whether the clip shows any of a token's rects.
  function anyShown(rects, clip) {
    for (let index = 0; index < rects.length; index++) {
      if (env.shows(rects[index], clip)) return true;
    }
    return false;
  }

  // The source of generated text's tokens (a pseudo-element's, a marker's):
  // what pushTextToken and dropToken read, plus the white-space `mode` its
  // text is written in. Generated text is never hidden text.
  function generatedSource(context, scale, segment) {
    const ps = context.style;
    const mode = whiteSpaceOf(ps);
    const style = runStyle(context, scale);
    return {
      style,
      face: probeFaceOf(ps, style.family, scale),
      tabSize: mode.spaces ? tabSizeOf(ps) : DEFAULT_TAB_SIZE,
      segment,
      recordsHidden: false,
      clip: context.clip,
      mode,
    };
  }

  // `origin` is where a word of a text node lies in it, so an ellipsis cut can
  // measure it character by character (truncateAtEllipsis): {source, start,
  // end, previous}, readTokens' source, the word's offsets in its data and the
  // character before it (casedText). Null for generated text and for spaces.
  function pushTextToken(source, text, rect, collapsible, tokens, origin) {
    tokens.push({
      kind: 'text', text, rect, style: source.style, face: source.face, collapsible, tabSize: source.tabSize,
      segment: source.segment, origin: origin || null,
    });
    dropping = false;
  }

  // A token that paints nothing: hidden or transparent text, which keeps its
  // room in the line, or text its clip shows under 2 px of. Each of its rects
  // that takes width is a gap in its line, as an atomic inline is (isCut), so
  // the text after it keeps its x. Its text is hidden text unless it is
  // visibility: hidden, which the page's innerText leaves out too.
  function dropToken(source, text, rects, tokens) {
    for (let index = 0; index < rects.length; index++) {
      if (rects[index].right > rects[index].left) tokens.push({ kind: 'gap', rect: rects[index] });
    }
    if (!source.recordsHidden) return;
    hiddenParts.push(dropping ? text : ' ' + text);
    dropping = true;
  }

  function measureToken(source, start, end, space, previous, range, tokens) {
    range.setStart(source.node, start);
    range.setEnd(source.node, end);
    const rects = paintedRects(range, space);
    if (!rects.length) return;
    const collapsible = space && !source.mode.spaces;
    const raw = source.data.slice(start, end);
    const text = !space ? casedText(raw, source.transform, previous) : collapsible ? ' ' : preservedSpaces(raw);
    if (source.hidden || !anyShown(rects, source.clip)) {
      dropToken(source, text, rects, tokens);
      return;
    }
    if (rects.length > 1 && !collapsible &&
        splitToken(source, start, end, space, previous, range, tokens)) {
      return;
    }
    pushTextToken(source, text, rects[0], collapsible, tokens, space ? null : { source, start, end, previous });
  }

  // Word and space tokens of one text node, plus a break for each preserved
  // newline. `words.previous` is the character the next token follows
  // (casedText); it carries over from one text node to the next, hidden ones
  // included, because they are still in the text. `words.segment` counts the
  // inline edges crossed so far: every token carries it, and a line is cut
  // where it changes (segmentsOf).
  function readTokens(piece, scale, range, tokens, words) {
    const ps = piece.context.style;
    // Hidden or transparent text keeps its place in the layout, line breaks
    // included, but paints nothing: its tokens are gaps (dropToken).
    const visible = ps.visibility === 'visible';
    const data = String(dom.textData(piece.node) || '');
    const length = Math.min(data.length, COLLECTION_ITEM_LIMIT);
    if (!length) return;
    const mode = whiteSpaceOf(ps);
    const style = runStyle(piece.context, scale);
    const source = {
      node: piece.node,
      data,
      mode,
      style,
      face: probeFaceOf(ps, style.family, scale),
      tabSize: mode.spaces ? tabSizeOf(ps) : DEFAULT_TAB_SIZE,
      transform: String(ps.textTransform || 'none'),
      segment: words.segment,
      hidden: !visible || !(piece.context.opacity > 0),
      recordsHidden: visible,
      clip: piece.context.clip,
    };
    let start = 0;
    while (start < length) {
      const kind = characterKind(data.charCodeAt(start), mode);
      let end = start + 1;
      if (kind === 'break') {
        tokens.push(BREAK);
        words.previous = '';
        dropping = false;
        start = end;
        continue;
      }
      while (end < length && characterKind(data.charCodeAt(end), mode) === kind) end++;
      measureToken(source, start, end, kind === 'space', words.previous, range, tokens);
      words.previous = kind === 'space' ? ' ' : lastCodePoint(data, start, end);
      start = end;
    }
  }

  // A generated text box's characters as a run writes them. Where white space
  // collapses, a run of it is one space (the browser leaves what it collapsed
  // out of the boxes, splitting a box there, so a run rarely reaches one);
  // where it is preserved, a space is a NBSP and a tab stays a tab until its
  // line is assembled, as in a text node's tokens. A newline that breaks the
  // line ends its box, so it adds nothing.
  function generatedText(text, mode) {
    let result = '';
    let spaced = false;
    const length = Math.min(text.length, COLLECTION_ITEM_LIMIT);
    for (let index = 0; index < length; index++) {
      const kind = characterKind(text.charCodeAt(index), mode);
      if (kind === 'word') {
        result += text[index];
        spaced = false;
      } else if (kind === 'space' && mode.spaces) {
        result += text[index] === '\t' ? '\t' : NBSP;
      } else if (kind === 'space' && !spaced) {
        result += ' ';
        spaced = true;
      }
    }
    return result;
  }

  // The tokens of one piece of a pseudo-element's generated text, and its
  // gaps. Each token is one inline text box the browser laid the piece out in
  // (pseudo.mjs), with its text as painted (text-transform applied, counters
  // and quotes evaluated) at the box's rect, so it clusters into lines with
  // the words around it. Text that paints nothing (hidden, transparent, or
  // shown under 2 px by its clip) is a gap that keeps its room. Generated text
  // is no part of the page's innerText, so it is never hidden text.
  function readGeneratedTokens(piece, scale, tokens, words) {
    const ps = piece.context.style;
    const source = generatedSource(piece.context, scale, words.segment);
    const mode = source.mode;
    const paints = ps.visibility === 'visible' && piece.context.opacity > 0;
    const boxes = piece.piece.boxes;
    if (!spend(boxes.length)) return;
    for (let index = 0; index < boxes.length; index++) {
      const box = boxes[index];
      const text = generatedText(box.text, mode);
      if (!text) continue;
      const rect = { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
      if (!paints || !anyShown([rect], source.clip)) {
        dropToken(source, text, [rect], tokens);
      } else {
        pushTextToken(source, text, rect, text === ' ' && !mode.spaces, tokens);
      }
      words.previous = lastCodePoint(text, 0, text.length);
    }
  }

  // ─── list markers ────────────────────────────────────────────────────
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
    const read = markerGlyphLine(marker, walk, '');
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
      paragraphs: paragraphsOf([line]),
    };
  }

  // markerGlyphLine(marker, walk, after) -> {line, parts} | null: an outside
  // marker's glyphs as one assembled line in its own style, `after` (white
  // space, or '') written after them, and where its text lies (markerParts).
  // Null when it paints nothing: no glyphs, hidden, or clipped away.
  function markerGlyphLine(marker, walk, after) {
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
      clip: walk.clip,
    };
    const source = generatedSource(context, scale, 0);
    const tokens = [];
    pushTextToken(source, generatedText(glyphs, source.mode) + after, parts.glyphs, false, tokens);
    tokens[0].shape = marker.list.symbol;
    const line = assembleLine({ tokens }, String(ps.lineHeight));
    if (!line || !line.runs.length) return null;
    return { line, parts };
  }

  // markerLine(marker, walk) -> the line an outside marker leads its item's
  // first line with in a turned block (snapshot.mjs TurnedText): its glyphs,
  // then its trailing white space as one space the line keeps, for the room
  // its box leaves before the text. Null when it paints nothing.
  function markerLine(marker, walk) {
    const read = markerGlyphLine(marker, walk, marker.list.trailing && whiteSpaceOf(marker.style).spaces
      ? preservedSpaces(marker.list.trailing)
      : ' ');
    return read ? read.line : null;
  }

  // ─── lines ───────────────────────────────────────────────────────────
  // A token starts a new line when it is a <br> (or a preserved newline), or
  // when both hold: its vertical overlap with the current line is at most half
  // the smaller of the two heights, and it starts back towards the line start,
  // past the previous token's far edge (left of its right edge in LTR, right of
  // its left edge in RTL), because the wrap moved it there.
  function startsNewLine(line, rect, previous, rtl) {
    const overlap = Math.min(line.bottom, rect.bottom) - Math.max(line.top, rect.top);
    const smaller = Math.min(line.bottom - line.top, rect.bottom - rect.top);
    if (overlap > smaller * SAME_LINE_OVERLAP) return false;
    return rtl
      ? rect.right > previous.left + WRAP_BACKSTEP_PX
      : rect.left < previous.right - WRAP_BACKSTEP_PX;
  }

  function openLine(lines) {
    const line = { tokens: [], top: 0, bottom: 0 };
    lines.push(line);
    return line;
  }

  function clusterLines(tokens, rtl) {
    const lines = [];
    let line = null;
    let previous = null;
    for (let index = 0; index < tokens.length; index++) {
      const token = tokens[index];
      if (token.kind === 'break') {
        // A break ends the line it is on, even an empty one: two in a row leave a blank line.
        if (!line) openLine(lines);
        line = openLine(lines);
        continue;
      }
      const rect = token.rect;
      if (!line || (line.tokens.length && startsNewLine(line, rect, previous, rtl))) {
        line = openLine(lines);
      }
      if (!line.tokens.length) {
        line.top = rect.top;
        line.bottom = rect.bottom;
      } else {
        line.top = Math.min(line.top, rect.top);
        line.bottom = Math.max(line.bottom, rect.bottom);
      }
      line.tokens.push(token);
      previous = rect;
    }
    return lines;
  }

  // A tab advances to the next multiple of tab-size columns, written as NBSPs.
  function expandTabs(text, column, tabSize) {
    let result = '';
    let at = column;
    for (let index = 0; index < text.length; index++) {
      if (text[index] === '\t') {
        const width = tabSize - (at % tabSize);
        for (let space = 0; space < width; space++) result += NBSP;
        at += width;
      } else {
        result += text[index];
        at += 1;
      }
    }
    return result;
  }

  // The line's runs and rect. Collapsible spaces at either end are dropped
  // (the browser paints none there); preserved spaces are kept as written.
  // Null for a line that held only collapsible spaces: it shows nothing, so it
  // is no blank line (only breaks make those).
  // `extents[i]` is runs[i]'s probe face and the left and right of its tokens'
  // rects, the width the browser drew it at, and `advance`, false when a token
  // of it was drawn as a shape (a symbol marker), whose rect is no advance.
  function assembleLine(line, lineHeight) {
    const tokens = line.tokens;
    let first = 0;
    let last = tokens.length - 1;
    while (first <= last && tokens[first].collapsible) first++;
    while (last >= first && tokens[last].collapsible) last--;
    const runs = [];
    const extents = [];
    let rect = null;
    let column = 0;
    let previousCollapsible = false;
    for (let index = first; index <= last; index++) {
      const token = tokens[index];
      if (token.collapsible && previousCollapsible) continue;
      previousCollapsible = token.collapsible;
      const text = token.text.indexOf('\t') >= 0 ? expandTabs(token.text, column, token.tabSize) : token.text;
      column += text.length;
      const run = runs.length ? runs[runs.length - 1] : null;
      const bounds = token.rect;
      if (run && sameStyle(run, token.style)) {
        run.text += text;
        const extent = extents[extents.length - 1];
        extent.left = Math.min(extent.left, bounds.left);
        extent.right = Math.max(extent.right, bounds.right);
        extent.advance = extent.advance && !token.shape;
      } else {
        const created = { text };
        for (let field = 0; field < RUN_STYLE_FIELDS.length; field++) {
          created[RUN_STYLE_FIELDS[field]] = token.style[RUN_STYLE_FIELDS[field]];
        }
        created.opticalTrackingPx = 0;
        runs.push(created);
        extents.push({ face: token.face, left: bounds.left, right: bounds.right, advance: !token.shape });
      }
      if (!rect) {
        rect = { left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom };
      } else {
        rect.left = Math.min(rect.left, bounds.left);
        rect.top = Math.min(rect.top, bounds.top);
        rect.right = Math.max(rect.right, bounds.right);
        rect.bottom = Math.max(rect.bottom, bounds.bottom);
      }
    }
    if (tokens.length && !runs.length) return null;
    return { runs, extents, rect, lineHeight };
  }

  // Whether a token is room in its line that holds no text: an atomic inline,
  // or a word that paints nothing (dropToken).
  function isGap(token) {
    return token.kind === 'atomic' || token.kind === 'gap';
  }

  // A cut line (isCut), cut at each gap and at each inline edge: the text
  // between the cuts as lines of their own, in order, each assembled like a
  // whole line, so the spaces either side of a cut are dropped as at a line's
  // ends. Text between two cuts that is only spaces, or nothing, is no segment.
  function segmentsOf(line, lineHeight) {
    const segments = [];
    let tokens = [];
    for (let index = 0; index <= line.tokens.length; index++) {
      const token = index < line.tokens.length ? line.tokens[index] : null;
      const cut = !token || isGap(token) ||
        (tokens.length && token.segment !== tokens[tokens.length - 1].segment);
      if (cut && tokens.length) {
        const segment = assembleLine({ tokens }, lineHeight);
        if (segment && segment.runs.length) segments.push(segment);
        tokens = [];
      }
      if (token && !isGap(token)) tokens.push(token);
    }
    return segments;
  }

  // Whether a line is cut: it holds a gap, text on both sides of an
  // inline edge (its tokens' segments differ), or an inset with text on one
  // side of it only. Under box-decoration-break: slice an element's start inset
  // is on the line of the text after its opening edge, and its end inset on
  // the line of the text before its closing edge (markEdges), so a line that
  // starts with the one or ends with the other holds an inset too: a dot that
  // leads a paragraph pushes in its first line alone.
  function isCut(line) {
    const tokens = line.tokens;
    if (tokens.length && (tokens[0].afterOpening || tokens[tokens.length - 1].beforeClosing)) return true;
    let segment = null;
    for (let index = 0; index < tokens.length; index++) {
      const token = tokens[index];
      if (isGap(token)) return true;
      if (segment !== null && token.segment !== segment) return true;
      segment = token.segment;
    }
    return false;
  }

  // Marks the text tokens an inline edge sits against: after an opening edge,
  // the first text token that follows (from `from`, the tokens a text node
  // just added) is `afterOpening`; at a closing edge, the last text token so
  // far is `beforeClosing`. A break between them ends the line the inset is
  // on, so neither mark crosses one. `edges` carries the opening edge not yet
  // met by a text token: {opening}.
  function markAfterOpening(tokens, from, edges) {
    for (let index = from; edges.opening && index < tokens.length; index++) {
      if (tokens[index].kind === 'break') edges.opening = false;
      else if (tokens[index].kind === 'text') {
        tokens[index].afterOpening = true;
        edges.opening = false;
      }
    }
  }

  // At a closing edge: the last token so far, when it is text, is `beforeClosing`.
  function markBeforeClosing(tokens) {
    const last = tokens.length ? tokens[tokens.length - 1] : null;
    if (last && last.kind === 'text') last.beforeClosing = true;
  }

  // A line that paints nothing: a blank line (only breaks make those). A cut
  // line is never blank, even with no text: it stands where its atomic is.
  function isBlank(line) {
    return !line.segments && !line.runs.length;
  }

  // ─── ellipsis ────────────────────────────────────────────────────────
  // R11e. A block container whose text-overflow is ellipsis and whose overflow
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
      const width = sizes ? Number(sizes[0].w) : NaN;
      ellipsisAdvances[css] = Number.isFinite(width) && width >= 0 ? width : null;
    }
    const advance = ellipsisAdvances[css];
    return advance === null ? null : advance * scale;
  }

  // The characters of a word token, {text, rect} each as painted: its text
  // node read one code point at a time (its origin), cased as the word was. A
  // code point that paints nothing (a joiner, a combining mark) travels with
  // its neighbour, as in splitToken.
  function characterPieces(token, range) {
    const origin = token.origin;
    const source = origin.source;
    const pieces = [];
    let pending = '';
    let before = origin.previous;
    let index = origin.start;
    while (index < origin.end) {
      const length = codePointLength(source.data, index);
      const raw = source.data.slice(index, index + length);
      const text = casedText(raw, source.transform, before);
      before = raw;
      range.setStart(source.node, index);
      range.setEnd(source.node, index + length);
      index += length;
      const rects = paintedRects(range, false);
      if (!rects.length) {
        if (pieces.length) pieces[pieces.length - 1].text += text;
        else pending += text;
        continue;
      }
      pieces.push({ text: pending + text, rect: rects[0] });
      pending = '';
    }
    return pieces;
  }

  // Cuts a clustered line (clusterLines) that runs past its block's ellipsis
  // edge as Chrome cuts it. Every token whose rect ends within the edge less
  // the "…"'s advance stays; the word that limit falls in keeps the characters
  // that end within it, a character partly past it being hidden under the
  // "…"; a "…" token in the block's own style follows them; and every token
  // after is gone. A line whose text ends within the edge is left as it is,
  // and so is one whose "…" could not be measured (its overflow clip still
  // cuts it). The cut word and the words after it are hidden text: the page
  // reads them, the slide does not show them.
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
    const hidden = [];
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
      // A word read from a visible text node, and the spaces between such words.
      if (token.kind === 'text' && (token.collapsible || (token.origin && token.origin.source.recordsHidden))) {
        hidden.push(token.text);
      }
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
    kept.push({
      kind: 'text',
      text: ELLIPSIS,
      rect: rtl
        ? { left: at - advance, top: line.top, right: at, bottom: line.bottom }
        : { left: at, top: line.top, right: at + advance, bottom: line.bottom },
      style,
      face: probeFaceOf(ellipsis.context.style, style.family, scale),
      collapsible: false,
      tabSize: DEFAULT_TAB_SIZE,
      segment,
      origin: null,
    });
    line.tokens = kept;
    const words = hidden.join('').trim();
    if (words) hiddenParts.push(' ' + words);
    dropping = false;
  }

  // The tokens of one run's pieces, in DOM order (readTokens and its kin):
  // words, spaces, breaks, gaps and atomic inlines, each inside marker joined
  // to its line where the text runs straight on from it (joinMarkers).
  // `range` is the Range every token is measured with.
  function readRunTokens(nodes, scale, range) {
    const tokens = [];
    const words = { previous: '', segment: 0 };
    const edges = { opening: false };
    dropping = false;
    for (let index = 0; index < nodes.length; index++) {
      const piece = nodes[index];
      if (piece.kind === 'text' || piece.kind === 'generated' || piece.kind === 'marker') {
        const from = tokens.length;
        if (piece.kind === 'text') readTokens(piece, scale, range, tokens, words);
        else if (piece.kind === 'generated') readGeneratedTokens(piece, scale, tokens, words);
        else readMarkerTokens(piece, scale, tokens, words);
        markAfterOpening(tokens, from, edges);
        continue;
      }
      // An inline element's box and its edges are no word boundary in its text.
      if (piece.kind === 'decoration') continue;
      if (piece.kind === 'edge') {
        words.segment++;
        if (piece.opens) edges.opening = true;
        else markBeforeClosing(tokens);
        continue;
      }
      if (piece.kind === 'break') {
        edges.opening = false;
        tokens.push(BREAK);
      } else if (piece.kind === 'atomic') {
        const rect = atomicRect(piece.element);
        if (rect) tokens.push({ kind: 'atomic', rect });
      }
      // A break or an atomic inline ends the word before it.
      words.previous = '';
      dropping = false;
    }
    joinMarkers(tokens);
    return tokens;
  }

  // layoutInlineRun(nodes, s, scale, ellipsis) -> {lines, rtl} | null
  //   nodes     one run's pieces, as collectRuns gathers them;
  //   s         the computed style of the block that holds the run;
  //   scale     the block's cumulative transform scale (font sizes and tracking scale with it);
  //   ellipsis  the block's EllipsisCut (ellipsisOf), or null.
  // Each line is {runs, extents, rect, lineHeight}, or {segments} for a cut
  // line (isCut): its text between the gaps and inline edges on it, each
  // segment a line of that first form. A gap (an atomic inline, or a word that
  // paints nothing) is a token with the rect it fills in its line, so lines
  // cluster around it as around a word; an inline edge moves no token, it only
  // starts a new segment, and so does an inside marker the text does not run
  // straight on from (joinMarkers). A line a clip cuts off is a cut line of
  // gaps alone, which has no segment. A line that runs past the block's
  // ellipsis edge ends where Chrome's does, in a "…" (truncateAtEllipsis).
  // Leading and trailing blank lines paint nothing and are dropped; null when
  // no text in the run paints.
  function layoutInlineRun(nodes, s, scale, ellipsis) {
    const rtl = s.direction === 'rtl';
    const range = document.createRange();
    const tokens = readRunTokens(nodes, scale, range);
    const clustered = clusterLines(tokens, rtl);
    for (let index = 0; ellipsis && index < clustered.length; index++) {
      truncateAtEllipsis(clustered[index], ellipsis, scale, range);
    }
    const lineHeight = String(s.lineHeight);
    const lines = [];
    let painted = false;
    for (let index = 0; index < clustered.length; index++) {
      if (isCut(clustered[index])) {
        const segments = segmentsOf(clustered[index], lineHeight);
        if (segments.length) painted = true;
        lines.push({ segments });
        continue;
      }
      const line = assembleLine(clustered[index], lineHeight);
      if (!line) continue;
      if (line.runs.length) painted = true;
      lines.push(line);
    }
    if (!painted) return null;
    let first = 0;
    let last = lines.length - 1;
    while (first <= last && isBlank(lines[first])) first++;
    while (last >= first && isBlank(lines[last])) last--;
    return { lines: lines.slice(first, last + 1), rtl };
  }

  // ─── paragraphs and geometry ─────────────────────────────────────────
  // Lines of one size are soft breaks inside one paragraph. A line whose largest
  // run differs in size, or whose line-height differs, starts a paragraph of its
  // own, because PowerPoint spacing is per paragraph. A blank line stays in the
  // paragraph before it.
  // Spacing and the first-line offset use the paragraph's largest run (spec §3
  // Metrics), so each paragraph is queued for applyMetrics with that run's
  // face, the first run at that size.
  // The index of a line's largest run, the first at that size; -1 for a line
  // with no runs.
  function largestRunOf(line) {
    let largest = -1;
    for (let run = 0; run < line.runs.length; run++) {
      if (largest < 0 || line.runs[run].sizePx > line.runs[largest].sizePx) largest = run;
    }
    return largest;
  }

  // The probe face of a line's largest run, or null for a line with no runs.
  function largestFaceOf(line) {
    const largest = largestRunOf(line);
    return largest < 0 ? null : line.extents[largest].face;
  }

  function paragraphsOf(lines) {
    const paragraphs = [];
    let paragraph = null;
    let key = null;
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      if (line.runs.length) {
        const run = largestRunOf(line);
        const largest = line.runs[run].sizePx;
        const face = line.extents[run].face;
        const lineKey = largest + '|' + line.lineHeight;
        if (!paragraph || lineKey !== key) {
          paragraph = { sizePx: largest, lineHeightPx: null, ascentPx: null, lines: [] };
          paragraphs.push(paragraph);
          pendingParagraphs.push({ paragraph, face, lineHeight: line.lineHeight });
          key = lineKey;
        }
      }
      paragraph.lines.push({ runs: line.runs });
    }
    return paragraphs;
  }

  // Queues every run of the block for the optical-size comparison.
  // `advancesRead` is whether its tokens' rects measured their advances: not
  // under a turn, where they bound the turned glyphs. A justified line is drawn
  // stretched, a symbol marker is drawn as a shape, and turned text's rects are
  // no widths, so their natural width at the browser's own cut is probed
  // instead (width null).
  function queueRuns(lines, align, advancesRead) {
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      for (let run = 0; run < line.runs.length; run++) {
        const extent = line.extents[run];
        pendingRuns.push({
          run: line.runs[run],
          face: extent.face,
          width: align === 'justify' || !extent.advance || !advancesRead ? null : extent.right - extent.left,
        });
      }
    }
  }

  function alignmentOf(s, rtl) {
    const value = String(s.textAlign || 'start');
    if (/center/.test(value)) return 'center';
    if (/^justify/.test(value)) return 'justify';
    if (/right/.test(value)) return 'right';
    if (/left/.test(value)) return 'left';
    if (value === 'end') return rtl ? 'left' : 'right';
    return rtl ? 'right' : 'left';
  }

  // The text box of one laid-out run, or of the lines of one between cut lines.
  // `placement` is how its box is found:
  //   'container'  the element's own text;
  //   'text'       an anonymous flex or grid item, whose own box the page never
  //                exposes: placed by its text bounds whatever its alignment;
  //   'segment'    one segment of a cut line (segmentsOf): placed by its text
  //                bounds and written from the line's start side, because the
  //                alignment placed the whole line, not the piece of it.
  // * Left-aligned text is placed by its text bounds: the union of its lines.
  // * Centred, right-aligned and justified text spans its container's content
  //   box, widened to the text where the text overflows it.
  // * Slack (6% + 4 px) widens the box on the side its alignment grows: right
  //   for left-aligned text, both sides for centred, left for right-aligned.
  // * Vertically it spans its lines: from the first line's top to the last
  //   line's bottom in normal flow. Taken as the union, so lines that run
  //   another way (text under a rotation runs bottom to top) still get a box.
  //   Its top is the first line's glyph top; the emitter (emit_text.cjs)
  //   raises the box by the first-line offset calibrated against PowerPoint
  //   and Google Slides.
  // * Justified text is written aligned to the edge its lines start from, with
  //   the browser's line breaks: PowerPoint and Google Slides justify a line
  //   to the full box, slack included, so every justified line ran about 35 px
  //   past the browser's (scripts/export_fidelity/CALIBRATION.md, A3).
  function textBlock(layout, element, s, frame, placement) {
    const lines = layout.lines;
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    for (let index = 0; index < lines.length; index++) {
      const rect = lines[index].rect;
      if (!rect) continue;
      left = Math.min(left, rect.left);
      right = Math.max(right, rect.right);
      top = Math.min(top, rect.top);
      bottom = Math.max(bottom, rect.bottom);
    }
    if (!(bottom > top) || !(right >= left)) return null;
    const align = alignmentOf(s, layout.rtl);
    let x = left;
    let w = right - left;
    if (align !== 'left' && placement === 'container') {
      const box = env.boxGeometry(element, env.rectOf(element), frame);
      const area = box ? env.contentBox(s, box) : null;
      if (area) {
        x = Math.min(area.x, left);
        w = Math.max(area.x + area.w, right) - x;
      }
    }
    const start = layout.rtl ? 'right' : 'left';
    const written = placement === 'segment' || align === 'justify' ? start : align;
    const extra = w * SLACK_FRACTION + SLACK_PX;
    const shift = written === 'center' ? extra / 2 : written === 'right' ? extra : 0;
    queueRuns(lines, align, !frame.angle);
    return {
      x: x - shift,
      y: top,
      w: w + extra,
      h: bottom - top,
      rotate: null,
      wrap: lines.length > 1,
      align: written,
      rtl: layout.rtl,
      paragraphs: paragraphsOf(lines),
    };
  }

  // ─── metrics ─────────────────────────────────────────────────────────
  // The characters a renderer spaces after: code points, less the ones that
  // join the character before them.
  function characterCount(text) {
    let count = 0;
    let index = 0;
    while (index < text.length) {
      const length = codePointLength(text, index);
      if (!JOINS_PREVIOUS.test(text.slice(index, index + length))) count++;
      index += length;
    }
    return count;
  }

  // The size of each {css, text, baseline} probe, in order: one <div> per probe
  // on documentElement (PROBE_STYLE plus its css), all appended first so one
  // layout serves every read, then each read and removed. A baseline probe
  // also holds, before its text, a zero-size inline-block on the baseline, and
  // reports `ascent`: from its text's top (the glyph top the walk reads with a
  // Range) down to that baseline; and `content`, how tall its text's Range
  // rect is, the face's content area. Null when the page would not take them,
  // which is announced with `loss`, what the slide then exports without. The
  // text goes in as a text node: page script can take away the textContent
  // setter (hostile_text_nodes). Every probe is made, put in and taken off
  // through the pristine realm (dom_access.mjs): page script can make the
  // page's own remove do nothing, and a probe left after body would restyle
  // what the walk reads (html > body:not(:last-child)).
  function measureProbes(probes, loss) {
    const elements = [];
    const parts = [];
    let sizes = [];
    try {
      const root = queryOne('html');
      for (let index = 0; index < probes.length; index++) {
        const element = dom.createElement('div');
        dom.setAttribute(element, 'style', PROBE_STYLE + probes[index].css);
        let marker = null;
        if (probes[index].baseline) {
          marker = dom.createElement('span');
          dom.setAttribute(marker, 'style', BASELINE_MARKER_STYLE);
          dom.appendChild(element, marker);
        }
        const text = dom.createTextNode(probes[index].text);
        dom.appendChild(element, text);
        dom.appendChild(root, element);
        elements.push(element);
        parts.push({ marker, text });
      }
      const range = document.createRange();
      for (let index = 0; index < elements.length; index++) {
        const rect = elements[index].getBoundingClientRect();
        const size = { w: Number(rect.width), h: Number(rect.height) };
        if (parts[index].marker) {
          range.setStart(parts[index].text, 0);
          range.setEnd(parts[index].text, probes[index].text.length);
          const textRect = range.getBoundingClientRect();
          size.ascent = Number(parts[index].marker.getBoundingClientRect().top) - Number(textRect.top);
          size.content = Number(textRect.height);
        }
        sizes.push(size);
      }
    } catch (e) {
      console.warn('[html2pptx] the text metric probes could not be read (' + (e && e.message) + '); ' + loss);
      sizes = null;
    } finally {
      for (let index = 0; index < elements.length; index++) {
        try { dom.remove(elements[index]); } catch (e) { /* already detached: nothing to undo */ }
      }
    }
    return sizes;
  }

  // A face's line, as line-height: normal sets it: its height is the natural
  // line height, its baseline probe the ascent.
  function lineProbeCss(face) {
    return face.font + 'font-optical-sizing:' + face.optical + ';font-variation-settings:' + face.variation +
      ';line-height:normal;letter-spacing:0;';
  }

  // The width the browser draws a run at: its face as the element sets it.
  function browserCutCss(face) {
    return face.font + face.typesetting + 'font-optical-sizing:' + face.optical +
      ';font-variation-settings:' + face.variation + ';';
  }

  // The width PowerPoint and Google Slides draw it at: the same face at the
  // export cut's optical size. A repeated axis takes its last value, so the
  // element's own settings keep every other axis.
  function exportCutCss(face) {
    const own = face.variation === 'normal' ? '' : face.variation + ',';
    return face.font + face.typesetting + 'font-optical-sizing:auto;font-variation-settings:' + own +
      '"opsz" ' + EXPORT_CUT_OPTICAL_SIZE + ';';
  }

  // The distinct probes of one measureProbes pass: probe(css, text, baseline)
  // adds one unless it is there already, and returns its index in `probes`.
  function probeList() {
    const probes = [];
    const probeIndex = Object.create(null);
    function probe(css, text, baseline) {
      const key = (baseline ? 'b' : 'w') + css + '\u0000' + text;
      if (probeIndex[key] === undefined) {
        probeIndex[key] = probes.length;
        probes.push({ css, text, baseline });
      }
      return probeIndex[key];
    }
    return { probes, probe };
  }

  // measureMarkers(markers): every marker's advance (snapshot.mjs ListMarker),
  // {full, glyphs}, the widths its whole text and its glyphs take in its own
  // face as the browser lays them out, its tabular-nums and every other
  // feature included, in unscaled CSS px. A probe of a text marker's whole
  // text is as wide as the box Chrome laid it out in, so the two widths give
  // the trailing white space that box holds. One probe pass, made before the
  // walk reads any rect: the probes are gone again by then. A marker whose
  // probes could not be read keeps a null advance.
  function measureMarkers(markers) {
    const list = probeList();
    const wanted = [];
    const length = Math.min(markers.length, COLLECTION_ITEM_LIMIT);
    for (let index = 0; index < length; index++) {
      const marker = markers[index];
      if (!marker.list.glyphs) continue;
      const css = browserCutCss(probeFaceOf(marker.style, familyOf(marker.style.fontFamily), 1));
      wanted.push({
        marker,
        full: list.probe(css, marker.text, false),
        glyphs: list.probe(css, marker.list.glyphs, false),
      });
    }
    if (!wanted.length) return;
    const sizes = measureProbes(list.probes, 'this slide exports its list markers at their boxes, ' +
      'trailing space included, and joins each inside one to its line as the browser laid it out');
    if (!sizes) return;
    let unmeasured = 0;
    for (let index = 0; index < wanted.length; index++) {
      const full = sizes[wanted[index].full].w;
      const glyphs = sizes[wanted[index].glyphs].w;
      if (Number.isFinite(full) && Number.isFinite(glyphs) && full >= 0 && glyphs >= 0) {
        wanted[index].marker.list.advance = { full, glyphs };
      } else {
        unmeasured += 1;
      }
    }
    if (unmeasured) {
      console.warn('[html2pptx] list markers: ' + unmeasured + ' of ' + wanted.length + ' marker width(s) ' +
        'measured no finite size; those markers are placed at their boxes, trailing space included, ' +
        'and an inside one joins its line as the browser laid it out');
    }
  }

  // applyMetrics() fills in what the walk queued, in place on the blocks it
  // returned (they are the slide model's items by then):
  // * every paragraph's lineHeightPx, its CSS line height (line-height: normal
  //   is the natural one, from the probe), and ascentPx, its largest run's
  //   distance from glyph top to baseline. The emitter turns them into the
  //   renderers' spacing and the first-line offset (emit_text.cjs);
  // * every run's opticalTrackingPx, where the export cut and the browser's
  //   width differ by more than OPTICAL_SIZE_THRESHOLD: the browser's width
  //   less the export cut's, per character. Both widths carry the run's CSS
  //   tracking, which the emitter writes on top, so it is not counted twice;
  // * every turned block's top inset (turnedBlock): where its first line's
  //   glyphs start below its box's top. The centre of that line's rect,
  //   turned back about the box's centre, is the line's centre in the box's
  //   own frame at any angle, and its glyphs reach half the face's content
  //   area above it (the largest run's face, whose line probe reads it).
  // Each distinct probe is measured once.
  function applyMetrics() {
    const list = probeList();
    const probes = list.probes;
    const probe = list.probe;
    const paragraphProbes = [];
    for (let index = 0; index < pendingParagraphs.length; index++) {
      const face = pendingParagraphs[index].face;
      paragraphProbes.push(face ? probe(lineProbeCss(face), LINE_PROBE_TEXT, true) : -1);
    }
    const turnedProbes = [];
    for (let index = 0; index < pendingTurned.length; index++) {
      const face = largestFaceOf(pendingTurned[index].line);
      turnedProbes.push(face && pendingTurned[index].line.rect ? probe(lineProbeCss(face), LINE_PROBE_TEXT, true) : -1);
    }
    const runProbes = [];
    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      runProbes.push({
        exportCut: probe(exportCutCss(pending.face), pending.run.text, false),
        browserCut: pending.width === null ? probe(browserCutCss(pending.face), pending.run.text, false) : -1,
      });
    }
    const sizes = probes.length
      ? measureProbes(probes, 'this slide exports without line spacing and optical-size tracking')
      : [];
    if (!sizes) return;

    for (let index = 0; index < pendingParagraphs.length; index++) {
      const pending = pendingParagraphs[index];
      if (paragraphProbes[index] < 0) continue;
      const line = sizes[paragraphProbes[index]];
      if (!(line.h > 0)) continue;
      const lineHeight = /px$/.test(pending.lineHeight) ? parseFloat(pending.lineHeight) : line.h;
      if (lineHeight > 0) pending.paragraph.lineHeightPx = lineHeight * pending.face.scale;
      if (line.ascent > 0) pending.paragraph.ascentPx = line.ascent * pending.face.scale;
    }

    for (let index = 0; index < pendingTurned.length; index++) {
      if (turnedProbes[index] < 0) continue;
      const pending = pendingTurned[index];
      const content = sizes[turnedProbes[index]].content * largestFaceOf(pending.line).scale;
      if (!(content > 0)) continue;
      const rect = pending.line.rect;
      const middle = turnedPoint(pending.centre, pending.angle, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
      const top = middle.v + pending.block.h / 2 - content / 2;
      if (Number.isFinite(top)) pending.block.inset.top = top;
    }

    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      const scale = pending.face.scale;
      const drawn = pending.width === null ? sizes[runProbes[index].browserCut].w * scale : pending.width;
      const exportCut = sizes[runProbes[index].exportCut].w * scale;
      if (!(drawn > 0 && exportCut > 0)) continue;
      if (Math.abs(exportCut - drawn) / drawn <= OPTICAL_SIZE_THRESHOLD) continue;
      const characters = characterCount(pending.run.text);
      if (characters > 0) pending.run.opticalTrackingPx = (drawn - exportCut) / characters;
    }
  }

  // The text blocks of one laid-out run, appended to `blocks` in order. Each cut
  // line gives one block per segment; the lines between cut lines are a block
  // together, less the blank lines at its ends, which paint nothing there.
  function blocksOf(layout, element, s, frame, placement, blocks) {
    let pending = [];
    const flush = () => {
      let first = 0;
      let last = pending.length - 1;
      while (first <= last && isBlank(pending[first])) first++;
      while (last >= first && isBlank(pending[last])) last--;
      if (first <= last) {
        const block = textBlock({ lines: pending.slice(first, last + 1), rtl: layout.rtl }, element, s, frame, placement);
        if (block) blocks.push(block);
      }
      pending = [];
    };
    for (let index = 0; index < layout.lines.length; index++) {
      const line = layout.lines[index];
      if (!line.segments) {
        pending.push(line);
        continue;
      }
      flush();
      for (let segment = 0; segment < line.segments.length; segment++) {
        const block = textBlock({ lines: [line.segments[segment]], rtl: layout.rtl }, element, s, frame, 'segment');
        if (block) blocks.push(block);
      }
    }
    flush();
  }

  // The decorations of one run, in DOM order: one box per fragment that has
  // area. Under a rotation the fragments' rects bound the turned fragments,
  // not their boxes, so the element is one box: its unrotated offset size,
  // centred on the union of its fragments (boxGeometry), as getBoundingClientRect
  // would bound it.
  function decorationsOf(nodes, frame) {
    const decorations = [];
    for (let index = 0; index < nodes.length; index++) {
      const piece = nodes[index];
      if (piece.kind !== 'decoration') continue;
      const fragments = fragmentsOf(piece.element);
      const painted = [];
      for (let fragment = 0; fragment < fragments.length; fragment++) {
        if (fragments[fragment].width > 0 && fragments[fragment].height > 0) painted.push(fragments[fragment]);
      }
      const rects = frame.angle && painted.length ? [unionOf(painted)] : painted;
      const boxes = [];
      for (let rect = 0; rect < rects.length; rect++) {
        const box = env.boxGeometry(piece.element, rects[rect], frame);
        if (box) boxes.push(box);
      }
      if (boxes.length) {
        decorations.push({ element: piece.element, style: piece.style, opacity: piece.opacity, boxes, clip: piece.clip });
      }
    }
    return decorations;
  }

  // recordHiddenText(text): the rendered text (innerText) of a subtree the
  // walk skips because nothing in it shows (opacity 0, an empty clip). It is
  // still what a screen reader reads, so it is hidden text.
  function recordHiddenText(text) {
    hiddenParts.push(' ' + text);
    dropping = false;
  }

  // hiddenText() -> model.reference.hiddenText: the words of every token
  // dropped and every subtree recorded, in order, single-spaced.
  function hiddenText() {
    return hiddenParts.join('').replace(/\s+/g, ' ').trim();
  }

  // The InlineGroup of one run of `el`'s inline content, from its decorations
  // and its layout (layoutInlineRun, or null when none of its text paints),
  // each read once; null when it paints nothing. `placement` is textBlock's.
  function groupOf(run, decorations, layout, el, s, frame, placement) {
    const blocks = [];
    if (layout) blocksOf(layout, el, s, frame, placement, blocks);
    if (!decorations.length && !blocks.length) return null;
    return { follows: run.follows, decorations, blocks };
  }

  // collectTextBlocks(el, s, walk) -> InlineGroup[]
  //   el, s   the element the snapshot walk is visiting and its computed style;
  //   walk    {opacity, frame, backdrop, decoration, clip, turned}: its
  //           cumulative opacity, its transform frame, the backdrop of its
  //           content (backdropInside), the decorations on its text
  //           (decorationOf), what clips its inline content (snapshot.mjs
  //           clipsOf), and the TurnedText its text joins, or null.
  // One group per run of its inline content that paints: the run's decorations
  // and its text blocks. The walk orders them: every decoration of the group
  // under every text block of it (snapshot.mjs pushGroup). A group that comes
  // after a block-level child also names that child in `follows`: in tree order
  // it paints after the child's whole subtree, which only the walk can place,
  // so the walk re-sequences it there. Under a turn, a group holds the run's
  // turned lines instead of blocks (layoutTurnedRun), which the walk adds to
  // its TurnedText, in that same order.
  // The text of an inline element belongs to the block that contains it, so an
  // inline element, a replaced element or a box-less one holds no block of its own.
  function collectTextBlocks(el, s, walk) {
    const name = nameOf(el);
    const display = String(s.display);
    if (env.replaced.has(name) || display === 'inline' || display === 'none' ||
        display === 'contents' || /^ruby/.test(display) || budget <= 0) {
      return [];
    }
    const itemsAreBlocks = /flex|grid/.test(display);
    const runs = collectRuns(el, s, walk, itemsAreBlocks);
    // An anonymous flex or grid item's text-overflow is its initial clip: only
    // the block's own lines end in a "…".
    const ellipsis = runs.length && !itemsAreBlocks ? ellipsisOf(el, s, walk) : null;
    const groups = [];
    for (let index = 0; index < runs.length; index++) {
      const decorations = decorationsOf(runs[index].nodes, walk.frame);
      if (walk.turned) {
        const lines = layoutTurnedRun(runs[index].nodes, s, walk.frame.scale, walk.turned);
        if (decorations.length || lines.length) {
          groups.push({ follows: runs[index].follows, decorations, blocks: [], lines, turned: walk.turned });
        }
        continue;
      }
      const layout = layoutInlineRun(runs[index].nodes, s, walk.frame.scale, ellipsis);
      const group = groupOf(runs[index], decorations, layout, el, s, walk.frame, itemsAreBlocks ? 'text' : 'container');
      if (group) groups.push(group);
    }
    return groups;
  }

  // ─── turned text ─────────────────────────────────────────────────────
  // The text of a turn root (snapshot.mjs TurnedText) is one block: each run
  // the walk lays out under the root gives its lines (layoutTurnedRun), which
  // the walk gathers in DOM order, and turnedBlock makes the block of them.

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
  // (softWrapped), each line assembled as assembleLine does. A turned rect
  // places nothing along its line, so a gap (an atomic inline, which is its
  // own item, or a word that paints nothing) and an inline edge cut nothing:
  // the words around them join. A line of collapsed white space is no line; a
  // blank line between two breaks is one. [] when none of its text paints.
  function layoutTurnedRun(nodes, s, scale, turned) {
    const range = document.createRange();
    const tokens = readRunTokens(nodes, scale, range);
    const rtl = s.direction === 'rtl';
    const lineHeight = String(s.lineHeight);
    const lines = [];
    let painted = false;
    let explicit = [];
    for (let index = 0; index <= tokens.length; index++) {
      const token = index < tokens.length ? tokens[index] : null;
      if (token && token.kind !== 'break') {
        if (!isGap(token)) explicit.push(token);
        continue;
      }
      const wrapped = softWrapped(explicit, turned, rtl);
      for (let line = 0; line < wrapped.length; line++) {
        const assembled = assembleLine({ tokens: wrapped[line] }, lineHeight);
        if (!assembled) continue;
        if (assembled.runs.length) painted = true;
        lines.push(assembled);
      }
      explicit = [];
    }
    return painted ? lines : [];
  }

  // The layout box of a turn root whose bounds have no area (a zero-width
  // anchor its text overflows), which boxGeometry gives none: its offset size,
  // times its frame's scale, about its bounds' centre, turned by its frame,
  // as boxGeometry places every turned box.
  function emptyLayoutBox(element, rect, frame) {
    const generated = env.isPseudo(element);
    const width = generated ? element.edges.width : Number(element.offsetWidth) * frame.scaleX;
    const height = generated ? element.edges.height : Number(element.offsetHeight) * frame.scaleY;
    const w = Number.isFinite(width) && width > 0 ? width : 0;
    const h = Number.isFinite(height) && height > 0 ? height : 0;
    const centreX = Number(rect.left) + Number(rect.width) / 2;
    const centreY = Number(rect.top) + Number(rect.height) / 2;
    return { x: centreX - w / 2, y: centreY - h / 2, w, h, scale: frame.scale, rotate: frame.angle || null };
  }

  // The insets of a turned block's content box in its own frame, px: the
  // root's border and padding on each side, scaled, taken from the side the
  // writing mode's turn brings there. Turned 90 degrees, its top is the
  // root's right side; turned 270, its left.
  function turnedInsets(s, frame, turn) {
    const edge = (side, scale) => ((parseFloat(s['border' + side + 'Width']) || 0) + (parseFloat(s['padding' + side]) || 0)) * scale;
    const top = edge('Top', frame.scaleY);
    const right = edge('Right', frame.scaleX);
    const bottom = edge('Bottom', frame.scaleY);
    const left = edge('Left', frame.scaleX);
    if (turn === 90) return { left: top, top: right, right: bottom, bottom: left };
    if (turn === 270) return { left: bottom, top: left, right: top, bottom: right };
    return { left, top, right, bottom };
  }

  // turnedBlock(turned) -> TextBlock | null: the one text block of a turn
  // root's text (snapshot.mjs TurnedText), once the walk has gathered all its
  // lines; null when none of them paints.
  // * Its box is the root's unrotated layout box (boxGeometry), the inline
  //   length by the block length under a vertical writing mode, centred where
  //   the root's bounds are, turned by the text's angle, plus its slack.
  // * Its lines are the gathered ones, in the order the turned box stacks
  //   them (reversed for vertical-lr), less blank lines at either end; the
  //   browser's, so it never wraps.
  // * Its text sits in the root's content box by the box's insets
  //   (turnedInsets). The usual slack (6% + 4 px of the content width) goes
  //   on the side its alignment grows (half each side when centred), so
  //   Google Slides, which ignores wrap="none" and every inset below 0, has
  //   room for a slightly wider font (R11f): the padding on that side holds
  //   what it can, and the rest grows the box there, its centre moved along
  //   its own inline axis, so the layout box and the text's start stay where
  //   the browser has them. Its top inset is the content box's top until
  //   applyMetrics reads where its first line lies.
  // Its runs are probed for optical-size tracking at the browser's own cut:
  // their turned rects are no widths.
  function turnedBlock(turned) {
    if (turned.marker) {
      turned.lines.push(turned.marker);
      turned.marker = null;
    }
    const lines = turned.reversed ? turned.lines.slice().reverse() : turned.lines.slice();
    let first = 0;
    let last = lines.length - 1;
    while (first <= last && !lines[first].runs.length) first++;
    while (last >= first && !lines[last].runs.length) last--;
    if (first > last) return null;
    const kept = lines.slice(first, last + 1);
    const s = turned.style;
    const frame = turned.frame;
    const rect = env.rectOf(turned.root);
    const box = env.boxGeometry(turned.root, rect, frame) || emptyLayoutBox(turned.root, rect, frame);
    const sideways = turned.turn === 90 || turned.turn === 270;
    const w = sideways ? box.h : box.w;
    const h = sideways ? box.w : box.h;
    const centre = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
    const inset = turnedInsets(s, frame, turned.turn);
    const rtl = s.direction === 'rtl';
    const align = alignmentOf(s, rtl);
    const written = align === 'justify' ? (rtl ? 'right' : 'left') : align;
    const extra = Math.max(0, w - inset.left - inset.right) * SLACK_FRACTION + SLACK_PX;
    // R11f: the inset on a growth side holds what it can of its share of the
    // slack; the rest grows the box on that side.
    const take = (side, share) => {
      const held = Math.min(Math.max(inset[side], 0), share);
      inset[side] -= held;
      return share - held;
    };
    const growsLeft = written === 'center' ? take('left', extra / 2) : written === 'right' ? take('left', extra) : 0;
    const growsRight = written === 'center' ? take('right', extra / 2) : written === 'left' ? take('right', extra) : 0;
    // Grown along its own inline axis, the box's centre moves half the
    // difference that way, so the layout box stays where the browser has it.
    const radians = (turned.angle || 0) * Math.PI / 180;
    const along = (growsRight - growsLeft) / 2;
    const grownCentre = { x: centre.x + along * Math.cos(radians), y: centre.y + along * Math.sin(radians) };
    const grownWidth = w + growsLeft + growsRight;
    queueRuns(kept, align, false);
    const block = {
      x: grownCentre.x - grownWidth / 2,
      y: grownCentre.y - h / 2,
      w: grownWidth,
      h,
      rotate: turned.angle || null,
      wrap: false,
      align: written,
      rtl,
      paragraphs: paragraphsOf(kept),
      inset: { left: inset.left, top: inset.top, right: inset.right, bottom: 0 },
    };
    pendingTurned.push({ block, line: kept[0], centre, angle: turned.angle });
    return block;
  }

  // ─── table cells ─────────────────────────────────────────────────────
  // A native table's cell (snapshot_table.mjs) holds its text as the a:tc's
  // own paragraphs, laid out by the table's renderer inside the cell's
  // margins. That keeps the browser's lines only while each line is one run of
  // text the renderer sets straight through: a line cut at an atomic inline (a
  // pill, a Harvey ball), at an inline element's edges (a chip) or at a word
  // that paints nothing (isCut) has segments placed at their own x, and an
  // inline element's box (a <mark>) is a decoration that must paint under its
  // text, which a shape over the table cannot. Such a cell's text is overlay
  // text items instead, as anywhere else on the slide. So is all a cell holding
  // block layout holds (snapshot_table.mjs holdsInlineContent), which never
  // comes here. A cell whose text-overflow: ellipsis cuts its line keeps
  // nothing past the "…" (truncateAtEllipsis), so its line is no cut line and
  // can stay its own; one its overflow clip alone cuts keeps the gaps of the
  // words it drops, and is overlaid.
  //
  // layoutCell(el, s, walk) -> CellText, reading the cell's inline content
  // once (`walk` is collectTextBlocks'):
  //   CellText = {native, rtl, align, extent, slack, paragraphs(), groups()}
  //   native      its text can be the cell's own paragraphs (none at all included);
  //   rtl         its paragraphs run right to left;
  //   align       'left' | 'center' | 'right' as its paragraphs are written: a
  //               justified cell starts from its start side, as textBlock writes it;
  //   extent      {left, right} of its lines' text, or null for none;
  //   slack       the width beyond its widest line its renderer needs so as not
  //               to wrap a line the browser did not (spec §3 Text, Wrapping);
  //   paragraphs  () -> Paragraph[]: its lines as text paragraphs, queued for the
  //               metric probes (applyMetrics); call it once, and only when native;
  //   groups      () -> InlineGroup[]: its text as overlay items, as
  //               collectTextBlocks gives them; call it once, instead.
  function layoutCell(el, s, walk) {
    const runs = budget > 0 ? collectRuns(el, s, walk, false) : [];
    const rtl = s.direction === 'rtl';
    const align = alignmentOf(s, rtl);
    const written = align === 'justify' ? (rtl ? 'right' : 'left') : align;
    // A cell holding block layout never comes here (snapshot.mjs collectCellText
    // overlays it whole), so a cell's inline content is one run; more than one
    // is a layout no a:tc paragraph keeps, and is overlaid.
    const single = runs.length === 1 && !runs[0].follows;
    const ellipsis = runs.length ? ellipsisOf(el, s, walk) : null;
    const decorations = [];
    const layouts = [];
    for (let index = 0; index < runs.length; index++) {
      decorations.push(decorationsOf(runs[index].nodes, walk.frame));
      layouts.push(layoutInlineRun(runs[index].nodes, s, walk.frame.scale, ellipsis));
    }
    const layout = single ? layouts[0] : null;
    let cut = false;
    let left = Infinity;
    let right = -Infinity;
    for (let index = 0; layout && index < layout.lines.length; index++) {
      const line = layout.lines[index];
      if (line.segments) cut = true;
      if (!line.rect) continue;
      left = Math.min(left, line.rect.left);
      right = Math.max(right, line.rect.right);
    }
    const extent = right >= left ? { left, right } : null;
    return {
      native: runs.length === 0 || (single && !decorations[0].length && !cut),
      rtl: layout ? layout.rtl : rtl,
      align: written,
      extent,
      slack: extent ? (extent.right - extent.left) * SLACK_FRACTION + SLACK_PX : 0,
      paragraphs: () => {
        if (!layout) return [];
        queueRuns(layout.lines, align, !walk.frame.angle);
        return paragraphsOf(layout.lines);
      },
      groups: () => {
        const groups = [];
        for (let index = 0; index < runs.length; index++) {
          const group = groupOf(runs[index], decorations[index], layouts[index], el, s, walk.frame, 'container');
          if (group) groups.push(group);
        }
        return groups;
      },
    };
  }

  // fontOf(s, scale) -> {family, weight, italic, sizePx}: the face the element
  // whose computed style is `s` sets its own text in, as a Run carries it: in a
  // table cell, the face its renderer sizes an empty line, and each line's
  // paragraph mark, by (the browser's line box holds a strut of it too).
  function fontOf(s, scale) {
    return {
      family: familyOf(s.fontFamily),
      weight: weightOf(s.fontWeight),
      italic: s.fontStyle !== 'normal',
      sizePx: (parseFloat(s.fontSize) || 0) * scale,
    };
  }

  return {
    applyMetrics,
    collectTextBlocks,
    decorationOf,
    fontOf,
    hiddenText,
    isInlineBox,
    layoutCell,
    layoutInlineRun,
    loadedFonts,
    markerBlock,
    markerLine,
    measureMarkers,
    recordHiddenText,
    turnedBlock,
    writingTurn,
    truncated: () => truncated,
  };
}

export const TEXT_SOURCE = createTextLayout.toString();
