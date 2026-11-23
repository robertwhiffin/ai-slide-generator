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
//   so a footer's brand line and page number never share a paragraph;
// * an <svg>, <canvas> or other replaced element paints its own content: the
//   text walk never descends into it.
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
// follows it (readMarkerTokens, joinMarkers): snapshot_text_markers.mjs.
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
// instead of sliding into the icon's gap. The lines around it keep
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
// the snapshot reports as model.reference.hiddenText. A word the slide shows
// only part of is hidden text whole, as the page reads it: a fragment names
// no word of the page's text (recordHiddenWords).
//
// Ellipsis. A line of a block with text-overflow: ellipsis and an
// overflow other than visible that runs past its content box's end edge (the
// line box's, where Chrome ends the "…") shows the characters whose end lies
// within that edge less the "…"'s advance, then the "…": no more, whatever
// the overflow clip shows past it. The advance is the "…" in the block's own
// face, measured by probe; the cut word is measured character by character;
// and the "…" is a run in the block's own style, which is what Chrome paints
// it in even where the cut falls inside a differently styled inline
// (truncateAtEllipsis). The cut word, whole, and all after it are hidden text.
// The cut is snapshot_text_ellipsis.mjs.
//
// Turned text. Under a rotation, and under a vertical writing mode, which sets
// Latin glyphs sideways, a Range rect is the axis-aligned bounds of a turned
// glyph run, so lines cannot be clustered from rects, and a renderer turns a
// whole text box or nothing. So the text of a turn root (snapshot.mjs
// TurnedText) is ONE text item (turnedBlocks): the root's unrotated layout
// box, turned by its text's angle about the centre it shares with the root's
// bounds, its text set inside the content box by the box's insets, and the
// box grown by the slack its padding cannot hold, the layout box held where
// the browser has it. Its lines are its text in DOM order, broken at
// each <br>, preserved newline and block boundary (layoutTurnedRun), and
// where the browser wrapped a line. The centre of a turned rect is the centre
// of the run it bounds at any angle, so turned back about the root's centre
// it says where along the line, and on which line, the run lies
// (softWrapped). A vertical-lr root stacks its lines left to right, the other
// way from a box turned 90 degrees, so its lines are written in reverse.
// A line a gap cuts (an atomic inline, a word that paints nothing, an inline
// element's edges) is cut as unturned text is, and so is the root: each
// segment, and the lines between cut lines, is a turned item of its own
// where its text lies along and across the line (turnedLocalBlock). So is
// each anonymous item of a flex or grid turn root, which the container, not
// text-align, places: a turned item over its own text, where the browser
// draws it, as an unturned anonymous item is (its 'text' placement). A list
// marker under a turn is a turned item of its own at its box
// (turnedMarkerBlock). Turned text is snapshot_text_turned.mjs.
//
// Runs carry the browser's typography (spec §3 Runs). It is read from the
// computed style of the text node's parent element. Three things CSS does not
// inherit reach a run from further up:
// * the backdrop its colour is composited over (snapshot.mjs backdropInside);
// * underline and line-through, which CSS propagates to in-flow inline
//   content: a <b> inside a <u> computes none and is underlined;
// * super- and subscript, from an inline ancestor's vertical-align.
// The weights of the webfonts the page loaded go to the slide model as
// model.fonts, and those of their italic faces as model.italicFonts
// (loadedFonts), so the emitter can name a weight's face and an italic's.
//
// Metrics (spec §3 Text, Spacing and Metrics) are read with offscreen probes
// in the page's own fonts, after the walk (applyMetrics, snapshot_text_metrics.mjs):
// * a paragraph's line height in px (line-height: normal resolved to the
//   face's natural line height) and its largest run's ascent, from which the
//   emitter writes the renderers' line spacing and first-line offset;
// * a run whose width at the export cut (the static opsz-14 face PowerPoint and
//   Google Slides draw) differs from the width the browser drew by more than
//   0.5% carries the difference per character as tracking
//   (scripts/export_fidelity/CALIBRATION.md A1); and every run carries the
//   tracking that makes it as wide drawn at the export cut with no pair
//   kerning, as PowerPoint draws it (CALIBRATION.md X1).
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
//  *                           lines:[{runs:Run[], growthPx?}]}],
//  *              inset?: {left, top, right, bottom}}
//  * Run = {text, family, weight, italic, sizePx, color:'RRGGBB', letterSpacingPx,
//  *        underline, strike, baseline:null|'super'|'sub', opticalTrackingPx,
//  *        unkernedTrackingPx}
//  *
//  * growthPx how much further down than its spacing the browser set a line
//  *          after the block's first (a raised inline grew its line box;
//  *          markLineGrowth); absent when it is where the spacing puts it.
//  * A line after the first in its paragraph is a soft break; a line with no runs
//  * is a blank line (two <br>s, an empty pre line). Sizes are CSS px on the slide.
//  * y        the top of the first line's glyphs (its text's rects); the emitter
//  *          places the box above it by the calibrated first-line offset;
//  * rotate   degrees clockwise about the box's centre, 0..360: set on turned
//  *          blocks (turnedBlocks, turnedMarkerBlock) alone. A turned root's
//  *          box is its root's layout box grown by the part of its slack its
//  *          padding does not hold, its y that box's top (see inset); a piece
//  *          of a cut root, and a turned marker, has its own box, whose own
//  *          top is its first line's glyph top, as y is for unturned text;
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
//  * family   the face the run is written in: a webfont the page loaded, by its
//  *          family; any other face, by the name of the face the browser drew it
//  *          in that all three apps draw with its metrics (snapshot_text_metrics.mjs
//  *          resolveWrittenFaces): Arial, Times New Roman or Courier New for
//  *          their metric-compatible faces and for the generic and system faces,
//  *          Times New Roman where nothing in the stack draws (the standard face),
//  *          and a face installed on the machine as itself. Characters the
//  *          written face lacks in the apps are runs of their own in a face every
//  *          app has (snapshot_text_metrics.mjs splitFallbackRuns);
//  * weight   100..900, the computed weight to the nearest hundred;
//  * color    solid, pre-blended: what the browser paints the glyphs with, composited
//  *          layer by layer over the backdrop (Drive drops text alpha);
//  * opticalTrackingPx    tracking added to letterSpacingPx after every character,
//  *          so the run is as wide at the export cut as the browser drew it; 0
//  *          when the two widths agree within 0.5%;
//  * unkernedTrackingPx   the same for the export cut drawn with no pair
//  *          kerning, with no 0.5% band: the width delta per character plus
//  *          the run's kerning per gap its tracking can close (one fewer than
//  *          its characters where the run ends its line); 0 where unread.
//  */

import { ELLIPSIS_SOURCE } from './snapshot_text_ellipsis.mjs';
import { LIST_MARKERS_SOURCE } from './snapshot_text_markers.mjs';
import { TEXT_METRICS_SOURCE } from './snapshot_text_metrics.mjs';
import { TURNED_TEXT_SOURCE } from './snapshot_text_turned.mjs';

// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE: domAccess,
// childNodesOf, queryOne, reportCollectionLoss, DOM_ACCESS_LOG_PREFIX and the two
// limits are its free names. It is stringified, so it closes over nothing on the
// Node side; what it needs from the snapshot arrives in `env`:
//   replaced        the Set of tag names whose content is drawn, not laid out as text;
//   opacityOf       computed style -> its own opacity;
//   backdropInside  (backdrop, style) -> the backdrop of the content inside that element;
//   textColour      (backdrop, style) -> 'RRGGBB', the solid colour its text paints;
//   boxGeometry     (element, rect, frame) -> the element's box | null;
//   layoutBox       (element, rect, frame) -> its untransformed layout box, turned
//                   about its bounds' centre, whatever its area;
//   boxEdges        (style, scaleX, scaleY) -> {Top, Right, Bottom, Left: {border,
//                   padding}}, scaled;
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
//   rectOf          element -> its border box bounds, {left, top, width, height};
//   coverageFont    {family, advanceEm, bytes}: the coverage probe font
//                   (coverage_font.mjs), which tells the characters a webfont lacks;
//   target          the renderer the deck is written for, 'pptx' or 'gslides',
//                   which picks the face a symbol is written in
//                   (snapshot_text_metrics.mjs symbolFaceOf).
// Wherever this layout takes an element, a pseudo-element will do.
function createTextLayout(env) {
  const TEXT_NODE = 3;
  const ELEMENT_NODE = 1;
  const NBSP = '\u00a0';
  // Spec §3 Text, Wrapping: width slack, because Google's importer ignores wrap="none".
  const SLACK_FRACTION = 0.06;
  const SLACK_PX = 4;
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
  // Chrome's default tab-size; a computed length instead of a count falls back to it.
  const DEFAULT_TAB_SIZE = 8;
  // A generic family keyword or a system alias names no face an importer can
  // resolve. Where one draws a run, the run is written in the face the
  // export's container draws for it, by its metric-compatible name
  // (CALIBRATION.md N3, measured on Databricks Apps with the sidecar's font
  // bundle): sans-serif and system-ui are Liberation Sans there, Arial; serif
  // Liberation Serif, Times New Roman; monospace Liberation Mono, Courier New.
  // cursive, fantasy, emoji and math draw nothing there, so their text is set
  // in the standard face, Liberation Serif: Times New Roman. The first of them
  // in a stack also names the face a character a webfont lacks is written in
  // (fallbackFaceOf). A plain table, read with hasOwnProperty: page script can
  // replace Map and Set.
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
    'cursive': 'Times New Roman',
    'fantasy': 'Times New Roman',
    'emoji': 'Times New Roman',
    'math': 'Times New Roman',
  };
  const DEFAULT_FACE = 'Arial';
  // The faces PowerPoint (Windows and Mac) and Google Slides all draw, by the
  // families metric-compatible with each: the name a run drawn in one of them is
  // written by, so every app lays it out at the browser's widths. Lower-cased.
  const METRIC_FAMILIES = {
    'arial': 'Arial',
    'helvetica': 'Arial',
    'liberation sans': 'Arial',
    'arimo': 'Arial',
    'times new roman': 'Times New Roman',
    'times': 'Times New Roman',
    'liberation serif': 'Times New Roman',
    'tinos': 'Times New Roman',
    'courier new': 'Courier New',
    'courier': 'Courier New',
    'liberation mono': 'Courier New',
    'cousine': 'Courier New',
  };
  // Text whose stack draws in nothing is set in the browser's standard face:
  // Times on a Mac, Times New Roman on Linux (Liberation Serif in the export's
  // container).
  const STANDARD_FACE = 'Times New Roman';
  // The container's base-image faces, which no desktop has: never a face a run
  // is written in where the machine draws them. The sidecar's fontconfig keeps
  // them for per-character fallback and lets no stack name them; a stack's
  // family of that name that is no webfont the page loaded is read as if it did
  // not draw (baseImageFace). A webfont the page loaded under that name is the
  // page's own face, the same on every machine, and is written as any loaded
  // webfont is. Lower-cased prefix.
  const BASE_IMAGE_FACE_PREFIX = 'dejavu';
  const REGULAR_WEIGHT = 400;
  const BOLD_WEIGHT = 700;
  const LIGHTEST_WEIGHT = 100;
  const HEAVIEST_WEIGHT = 900;
  const WEIGHT_STEP = 100;
  const NO_DECORATION = { underline: false, strike: false };
  // capitalize's word boundaries, as Chrome draws them (UAX #29 word
  // boundaries, measured): the browser upper-cases a lowercase letter that
  // starts a word (casedText). A letter after one of these continues the word:
  // a letter of a script that spaces its words (after Han, kana or Hangul a
  // Latin word starts), a decimal digit or a letter-like numeral (Ⅷ; a
  // superscript digit, ², starts one), or a connector punctuation (total_q3).
  const INSIDE_A_WORD = /^(?![\p{sc=Han}\p{sc=Hiragana}\p{sc=Katakana}\p{sc=Hangul}])[\p{L}\p{Nd}\p{Nl}\p{Pc}]$/u;
  // The letters these join (INSIDE_A_WORD less the digits and connectors).
  const WORD_LETTER = /^(?![\p{sc=Han}\p{sc=Hiragana}\p{sc=Katakana}\p{sc=Hangul}])[\p{L}\p{Nl}]$/u;
  // What continues a word between two letters alone: an apostrophe (o’neil,
  // but 'quoted' and 1’b start one) and a middle dot (col·lecció). A full stop
  // and a colon start a word even there (E.G.).
  const BETWEEN_LETTERS = /^['\u2018\u2019\u00B7\u0387\u055F\u05F4\u2024\u2027\uFE13\uFE52\uFF07]$/u;
  // What the browser looks past, so that the letter after it follows what is
  // before it: combining marks and the format characters (a soft hyphen, a
  // word joiner, the joiners and direction marks), the zero-width space
  // aside, which starts a word.
  const LOOKED_PAST = /^(?!\u200B)[\p{M}\p{Cf}]$/u;
  const LOWERCASE_LETTER = /^\p{Ll}$/u;
  // A relatively positioned inline moved off its line by at least this many
  // of its own ems can be a superscript or subscript (Preflight moves its sub
  // by 0.25em, its sup by 0.5em; baselineShiftOf); a smaller move is a nudge
  // of its text.
  const SCRIPT_MOVE_EM = 0.1;
  // The elements such a move makes a script at any size (baselineShiftOf).
  const SCRIPT_TAGS = new Set(['sub', 'sup']);

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
  //   runs        {run, runs: the line's runs, which hold it, face, width: the
  //                browser's px | null (a justified line, whose drawn width
  //                includes the stretch), endsLine}
  const pendingParagraphs = [];
  const pendingRuns = [];
  //   fonts       {font, face}: a table cell's own face (fontOf), whose family
  //               is resolved as a run's is (resolveWrittenFaces)
  const pendingFonts = [];
  // The slide's hidden text (hiddenText), in the order it is recorded: the
  // rendered text of each subtree that shows nothing (recordHiddenText) and
  // each word of laid-out text the slide does not show whole
  // (recordHiddenWords).
  const hiddenParts = [];

  // Four parts of the layout are modules of their own, composed into
  // TEXT_SOURCE ahead of this function: its metric probes
  // (snapshot_text_metrics.mjs), list markers (snapshot_text_markers.mjs), the
  // text-overflow ellipsis (snapshot_text_ellipsis.mjs) and turned text
  // (snapshot_text_turned.mjs). Each is made here, from the layout functions
  // it calls (and the env, where it reads it), before any function of the
  // layout runs, and gives back the functions the layout calls.
  const { applyMetrics, browserCutCss, contentHeightOf, measureMarkers, measureProbes } = createTextMetrics({
    codePointLength,
    familyOf,
    probeFaceOf,
    drawingTokensOf,
    writtenFamilyOf,
    undrawnFamilyOf,
    pendingParagraphs,
    pendingRuns,
    pendingFonts,
    coverageFont: env.coverageFont,
    target: env.target,
  });
  const { joinMarkers, markerBlock, markerGlyphLine, readMarkerTokens } = createListMarkers(env, {
    SLACK_FRACTION,
    SLACK_PX,
    anyShown,
    assembleLine,
    decorationOf,
    dropToken,
    generatedSource,
    generatedText,
    followingContext,
    paragraphsOf,
    preservedSpaces,
    pushTextToken,
    queueRuns,
  });
  const { ellipsisOf, truncateAtEllipsis } = createEllipsis(env, {
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
  });
  const { TURNED_SIDES, layoutTurnedRun, turnedBlocks, turnedMarkerBlock, writingTurn } = createTurnedText(env, {
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
  });

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
  //   {style, opacity, backdrop, decoration, baseline, nudgePx, clip}
  //   style       its parent element's computed style;
  //   opacity     the cumulative opacity it paints at;
  //   backdrop    what it is composited over (snapshot.mjs backdropInside);
  //   decoration  {underline, strike} propagated to it;
  //   baseline    'super' | 'sub' from an inline ancestor (baselineShiftOf), else null;
  //   nudgePx     how far down its inline ancestors' relative positions move it,
  //               in CSS px, where none of them is a script (relativeRaiseOf);
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
  // into it. Its edges are on its line's own sides, which a vertical writing
  // mode turns onto its top and bottom (TURNED_SIDES).
  function hasInlineEdges(cs) {
    const sides = TURNED_SIDES[writingTurn(cs).angle];
    return Math.abs(inlineEdge(cs, sides.left)) > INLINE_EDGE_PX || Math.abs(inlineEdge(cs, sides.right)) > INLINE_EDGE_PX;
  }

  // The context inside an inline child element. Its own opacity, background,
  // decoration, vertical-align, relative position and clip-path apply to the
  // text it holds. `frame` is its block's transform frame: an inline box has
  // none of its own.
  function inlineContext(outer, element, cs, frame) {
    const shift = baselineShiftOf(cs, nameOf(element), outer.style);
    return {
      style: cs,
      opacity: outer.opacity * env.opacityOf(cs),
      backdrop: env.backdropInside(outer.backdrop, cs),
      decoration: decorationInside(outer.decoration, cs, false),
      baseline: shift || outer.baseline,
      nudgePx: outer.nudgePx - (shift ? 0 : relativeRaiseOf(cs)),
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
      nudgePx: 0,
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
          nudgePx: outer.nudgePx,
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

  // The face a character the run's webfont lacks is written in, a run of its
  // own (snapshot_text_metrics.mjs splitFallbackRuns): of the faces all three
  // apps have whose WGL4 coverage takes it, the one of the stack's generic
  // family, its first generic keyword as GENERIC_FACES maps it (Courier New
  // for monospace, Times New Roman for serif), else Arial. The browser falls
  // back along the same stack, and measured, Courier New keeps a monospace
  // run's cell (0.600 em, the browser's 0.602) where Arial is 0.99 em, and Arial
  // a sans run's (0.99 em, the browser's 1.00) (CALIBRATION.md D8).
  function fallbackFaceOf(stack) {
    const names = familyNames(stack);
    for (let index = 0; index < names.length; index++) {
      const key = names[index].toLowerCase();
      if (Object.prototype.hasOwnProperty.call(GENERIC_FACES, key)) return GENERIC_FACES[key];
    }
    return DEFAULT_FACE;
  }

  // The family a run starts with: the first face that is not a generic keyword
  // or a system alias, else the face the first generic maps to. Quoted or not:
  // Chrome serialises BlinkMacSystemFont as the quoted family "system-ui". Where
  // it is a webfont the page loaded, it is the face the run is written in;
  // where not, the walk keeps it (its probes set it first, then the stack, so
  // they fall back as the text did) and the face the run is written in is
  // resolved once the walk is done (snapshot_text_metrics.mjs resolveWrittenFaces).
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

  // The stack's families in order as each is set alone in a probe's
  // font-family, {name, css}: a generic keyword or system alias bare (so the
  // browser reads it as one, as it read the stack), any other family quoted.
  function drawingTokensOf(stack) {
    const names = familyNames(stack);
    const tokens = [];
    for (let index = 0; index < names.length && index < WALK_STEP_LIMIT; index++) {
      const name = names[index];
      const generic = Object.prototype.hasOwnProperty.call(GENERIC_FACES, name.toLowerCase());
      tokens.push({
        name,
        css: generic ? name.toLowerCase() : '"' + name.replace(/[\u0000-\u001F]/g, '').replace(/["\\]/g, '\\$&') + '"',
        baseImage: baseImageFace(name),
      });
    }
    return tokens;
  }

  // Whether `name` is a base-image face (BASE_IMAGE_FACE_PREFIX), which no run
  // is written in unless the page loaded a webfont of that name.
  function baseImageFace(name) {
    return String(name).toLowerCase().indexOf(BASE_IMAGE_FACE_PREFIX) === 0;
  }

  // The face a run is written in, given the family of its stack that drew it
  // (`name`) and whether that family is a webfont the page loaded: the webfont
  // by its own name; a generic keyword or system alias as the face the
  // container draws for it (GENERIC_FACES); a face metric-compatible with
  // Arial, Times New Roman or Courier New by that name (METRIC_FAMILIES); any
  // other face installed on the machine as itself.
  function writtenFamilyOf(name, webfont) {
    if (webfont) return name;
    const key = String(name).toLowerCase();
    if (Object.prototype.hasOwnProperty.call(GENERIC_FACES, key)) return GENERIC_FACES[key];
    if (Object.prototype.hasOwnProperty.call(METRIC_FAMILIES, key)) return METRIC_FAMILIES[key];
    return name;
  }

  // The face a run is written in when nothing in its stack draws any of its
  // characters: its first generic's (the browser falls back per character from
  // there), else the standard face, which the browser sets such a stack in.
  function undrawnFamilyOf(stack) {
    const names = familyNames(stack);
    for (let index = 0; index < names.length; index++) {
      const key = names[index].toLowerCase();
      if (Object.prototype.hasOwnProperty.call(GENERIC_FACES, key)) return GENERIC_FACES[key];
    }
    return STANDARD_FACE;
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

  // The baseline shift an inline element's text takes (computed style `s`,
  // tag name `name`, its parent's computed style `parentStyle`): 'super' or
  // 'sub' from its vertical-align, or from a relative position that moves it
  // off its line as a script, the way Tailwind's Preflight sets its sub and
  // sup (75% size, vertical-align baseline, then top: -0.5em or bottom:
  // -0.25em). A relative move makes a script only when both hold: it is at
  // least SCRIPT_MOVE_EM of the element's size, and the element is a <sub>
  // or <sup> or is set smaller than its parent. A
  // same-size move (Tailwind's relative -top-0.5 on an arrow beside a figure)
  // is a nudge of its text, a plain run (its nudgePx); null for neither.
  function baselineShiftOf(s, name, parentStyle) {
    if (s.verticalAlign === 'super') return 'super';
    if (s.verticalAlign === 'sub') return 'sub';
    const raise = relativeRaiseOf(s);
    const size = parseFloat(s.fontSize) || 0;
    if (raise === 0 || Math.abs(raise) < SCRIPT_MOVE_EM * size) return null;
    const smaller = size < (parseFloat(parentStyle && parentStyle.fontSize) || 0);
    if (!SCRIPT_TAGS.has(name) && !smaller) return null;
    return raise > 0 ? 'super' : 'sub';
  }

  // How far up a relative position moves an inline element (computed style
  // `s`) off its line, in CSS px; 0 when it is not relatively positioned. Its
  // resolved top is the offset the browser used (the negative of its bottom
  // when only that is set); where it does not resolve, its bottom is read.
  function relativeRaiseOf(s) {
    if (s.position !== 'relative') return 0;
    const top = parseFloat(s.top);
    const bottom = parseFloat(s.bottom);
    return Number.isFinite(top) ? -top : Number.isFinite(bottom) ? bottom : 0;
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
  //   features     its font-feature-settings alone, which a probe that turns
  //                kerning off appends to;
  //   variation    the element's font-variation-settings;
  //   optical      its font-optical-sizing;
  //   scale        the block's transform scale: probes are set at the computed,
  //                unscaled size, and their widths and heights scale with it;
  //   style        the run's style, weight and stretch, the start of a probe of
  //                one family of its stack alone: the coverage probes of
  //                splitFallbackRuns and resolveWrittenFaces;
  //   stack        the element's font-family stack, as computed;
  //   fallback     the face a character the run's family lacks is written in
  //                (fallbackFaceOf).
  function probeFaceOf(ps, family, scale) {
    const quoted = '"' + String(family).replace(/[\u0000-\u001F]/g, '').replace(/["\\]/g, '\\$&') + '"';
    return {
      font: 'font-style:' + ps.fontStyle + ';font-weight:' + ps.fontWeight + ';font-size:' + ps.fontSize +
        ';font-stretch:' + ps.fontStretch + ';font-family:' + quoted + ',' + ps.fontFamily + ';',
      typesetting: 'letter-spacing:' + ps.letterSpacing + ';word-spacing:' + ps.wordSpacing +
        ';font-kerning:' + ps.fontKerning + ';font-feature-settings:' + ps.fontFeatureSettings +
        ';font-variant:' + ps.fontVariant + ';',
      features: String(ps.fontFeatureSettings || 'normal'),
      variation: String(ps.fontVariationSettings || 'normal'),
      optical: String(ps.fontOpticalSizing || 'auto'),
      scale,
      style: 'font-style:' + ps.fontStyle + ';font-weight:' + ps.fontWeight + ';font-stretch:' + ps.fontStretch + ';',
      stack: String(ps.fontFamily || ''),
      fallback: fallbackFaceOf(ps.fontFamily),
    };
  }

  // A word's text as text-transform paints it. `previous` is what it follows in
  // the inline content (followingContext), '' at a start, after a break or
  // after an atomic inline. capitalize upper-cases each lowercase letter that
  // starts a word (startsAWord): "well-known (hello) 1st o’neil e.g.
  // total_q3" is "Well-Known (Hello) 1st O’neil E.G. Total_q3".
  function casedText(text, transform, previous) {
    if (transform === 'uppercase') return text.toUpperCase();
    if (transform === 'lowercase') return text.toLowerCase();
    if (transform !== 'capitalize') return text;
    let result = '';
    let context = previous;
    let index = 0;
    while (index < text.length) {
      const character = text.slice(index, index + codePointLength(text, index));
      index += character.length;
      result += LOWERCASE_LETTER.test(character) && startsAWord(context) ? character.toUpperCase() : character;
      context = followingContext(context, character, 0, character.length);
    }
    return result;
  }

  // Whether a letter after `context` (followingContext) starts a word: after
  // nothing, or after anything INSIDE_A_WORD does not hold, but for a
  // BETWEEN_LETTERS character with a letter before it.
  function startsAWord(context) {
    if (!context) return true;
    const last = lastCodePointOf(context, 0, context.length);
    if (INSIDE_A_WORD.test(last)) return false;
    if (!BETWEEN_LETTERS.test(last)) return true;
    return !WORD_LETTER.test(context.slice(0, context.length - last.length));
  }

  // The last code point of data[start, end), '' where that is empty.
  function lastCodePointOf(data, start, end) {
    if (end - 2 >= start && codePointLength(data, end - 2) === 2) return data.slice(end - 2, end);
    return data.slice(Math.max(start, end - 1), end);
  }

  // What a character after `context` then data[start, end) follows, for
  // casedText: the last two characters of them the browser does not look
  // past (LOOKED_PAST), the one a letter follows and the one before it,
  // which decides a BETWEEN_LETTERS character. Where data[start, end) is all
  // looked past, `context` again.
  function followingContext(context, data, start, end) {
    let kept = '';
    let count = 0;
    let at = end;
    while (at > start && count < 2) {
      const character = lastCodePointOf(data, start, at);
      at -= character.length;
      if (LOOKED_PAST.test(character)) continue;
      kept = character + kept;
      count += 1;
    }
    if (count === 0) return context;
    if (count === 2 || !context) return kept;
    return lastCodePointOf(context, 0, context.length) + kept;
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

  // Adds `weights` to `family`'s list in `map` (a family -> weights map), once each.
  function addWeights(map, family, weights) {
    if (!map[family]) map[family] = [];
    for (let index = 0; index < weights.length; index++) {
      if (map[family].indexOf(weights[index]) < 0) map[family].push(weights[index]);
    }
  }

  // loadedFonts() -> {fonts, italicFonts}: model.fonts, family -> the weights
  // (100..900) of its faces in document.fonts whose status is 'loaded', the
  // webfonts the page painted with; and model.italicFonts, the same for its
  // italic and oblique faces alone. The emitter names a weight's face only for
  // such a family (emit_typography.cjs typefaceFor), and an italic run's face
  // by the italic faces among them (italicTypefaceFor). document.fonts is a
  // FontFaceSet, not a DOM collection, so it is read with its own iterator.
  // Page script can replace that iterator too, so the read is bounded by
  // COLLECTION_ITEM_LIMIT, and a throw keeps the faces read before it.
  function loadedFonts() {
    // No prototype, so no family name can reach an inherited property or setter.
    const fonts = Object.create(null);
    const italicFonts = Object.create(null);
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
        const weights = faceWeights(face.weight);
        addWeights(fonts, family, weights);
        if (String(face.style || 'normal') !== 'normal') addWeights(italicFonts, family, weights);
      }
      if (read >= COLLECTION_ITEM_LIMIT) {
        truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' font faces', 'the snapshot webfont read');
      }
    } catch (e) {
      console.warn('[html2pptx] document.fonts could not be read (' + (e && e.message) +
        '); a family whose faces were not read exports without weight-named faces');
    }
    const maps = [fonts, italicFonts];
    for (let map = 0; map < maps.length; map++) {
      const families = Object.keys(maps[map]);
      for (let index = 0; index < families.length; index++) maps[map][families[index]].sort((a, b) => a - b);
    }
    return { fonts, italicFonts };
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
  // on each line, never as no rect at all. The DOMRectList and its DOMRects
  // are read through the pristine realm (dom_access.mjs), as an element's
  // fragments are: page script can replace DOMRectList's length and item and
  // DOMRect's getters. A list that is no DOMRectList (a realm that replaced
  // Range's getClientRects) holds no rect that can be read: its own length
  // spends from the budget, which bounds a lie, and nothing paints.
  function paintedRects(range, space) {
    const rects = range.getClientRects();
    let pristine = true;
    let reported;
    try {
      reported = Number(dom.rectListLength(rects)) || 0;
    } catch (e) {
      pristine = false;
      reported = Number(rects && rects.length) || 0;
    }
    const length = Math.min(Math.max(reported, 0), COLLECTION_ITEM_LIMIT);
    if (!spend(length) || !pristine) return [];
    const painted = [];
    for (let index = 0; index < length; index++) {
      const rect = dom.rectAt(rects, index);
      if (!rect) continue;
      const bounds = dom.rectBounds(rect);
      const width = Number(bounds.width);
      const height = Number(bounds.height);
      if (space ? width > 0 : width > 0 || height > 0) {
        const left = Number(bounds.left);
        const top = Number(bounds.top);
        painted.push({ left, top, right: left + width, bottom: top + height });
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
  // second line keeps its first, and is hidden text whole.
  //   source    one text node's {node, data, mode, style, tabSize, transform,
  //             segment, hidden, recordsHidden, clip} (readTokens);
  //   previous  what the token follows (followingContext);
  //   word      the word the token is part of (wordAt), or null.
  function splitToken(source, start, end, space, previous, range, tokens, word) {
    const pieces = paintedCodePoints(source, start, end, space, previous, range);
    for (let piece = 0; piece < pieces.length; piece++) {
      const read = pieces[piece];
      if (anyShown(read.rects, source.clip)) {
        pushTextToken(source, read.text, read.rects[0], false, tokens,
          space ? null : { source, start: read.start, end: read.end, previous: read.previous }, word);
      } else {
        dropToken(source, read.text, read.rects, tokens, word);
      }
    }
    return pieces.length > 0;
  }

  // The code points of a text node source's data[start, end), as painted,
  // each measured with `range`: {text, rects, start, end, previous} per code
  // point that paints. One that paints nothing (a joiner, a combining mark)
  // travels with its neighbour, the one before it or, at the start, the one
  // after, so no character is lost. Each is cased after the one before it, so
  // a word that wraps at its hyphen capitalises as it would on one line; a
  // space is written as preserved spaces. `previous` is what data[start] follows
  // (followingContext); each piece's `previous` is what it follows.
  function paintedCodePoints(source, start, end, space, previous, range) {
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
      const characterBefore = before;
      before = followingContext(before, raw, 0, raw.length);
      range.setStart(source.node, index);
      range.setEnd(source.node, index + length);
      const characterStart = index;
      index += length;
      const rects = paintedRects(range, space);
      if (!rects.length) {
        if (pieces.length) {
          pieces[pieces.length - 1].text += text;
          pieces[pieces.length - 1].end = index;
        } else {
          if (!pending) {
            pendingStart = characterStart;
            pendingBefore = characterBefore;
          }
          pending += text;
        }
        continue;
      }
      pieces.push({
        text: pending + text,
        rects,
        start: pending ? pendingStart : characterStart,
        end: index,
        previous: pending ? pendingBefore : characterBefore,
      });
      pending = '';
    }
    return pieces;
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
  // text is written in. Generated text is no part of the page's innerText, so
  // its tokens are part of no word (wordAt) and never hidden text.
  function generatedSource(context, scale, segment) {
    const ps = context.style;
    const mode = whiteSpaceOf(ps);
    const style = runStyle(context, scale);
    return {
      style,
      face: probeFaceOf(ps, style.family, scale),
      tabSize: mode.spaces ? tabSizeOf(ps) : DEFAULT_TAB_SIZE,
      segment,
      clip: context.clip,
      nudge: context.nudgePx * scale,
      mode,
    };
  }

  // `origin` is where a word of a text node lies in it, so an ellipsis cut can
  // measure it character by character (truncateAtEllipsis): {source, start,
  // end, previous}, readTokens' source, the word's offsets in its data and what
  // it follows (followingContext). Null for generated text and for spaces.
  // `nudge` is how far down, in slide px, a relative position that is no
  // script moves the token off its line (context nudgePx).
  // `word` is the word of the page's text the token is part of (wordAt), or
  // null for text the page does not read; the token's text is added to it, and
  // the token carries it, so a cut that leaves the token out later
  // (truncateAtEllipsis) can say the word is not shown whole.
  function pushTextToken(source, text, rect, collapsible, tokens, origin, word) {
    tokens.push({
      kind: 'text', text, rect, style: source.style, face: source.face, collapsible, tabSize: source.tabSize,
      segment: source.segment, origin: origin || null, nudge: source.nudge, word: word || null,
    });
    if (word) word.text += text;
  }

  // A token that paints nothing: hidden or transparent text, which keeps its
  // room in the line, or text its clip shows under 2 px of. Each of its rects
  // that takes width is a gap in its line, as an atomic inline is (isCut), so
  // the text after it keeps its x. The word it is part of (`word`, as
  // pushTextToken's) is not shown whole, so it is hidden text; there is none
  // for visibility: hidden text, which the page's innerText leaves out too,
  // nor for generated text.
  function dropToken(source, text, rects, tokens, word) {
    for (let index = 0; index < rects.length; index++) {
      if (rects[index].right > rects[index].left) tokens.push({ kind: 'gap', rect: rects[index] });
    }
    if (!word) return;
    word.text += text;
    word.hidden = true;
  }

  // `word` is the word a word token is part of (wordAt), null for a space.
  function measureToken(source, start, end, space, previous, range, tokens, word) {
    range.setStart(source.node, start);
    range.setEnd(source.node, end);
    const rects = paintedRects(range, space);
    if (!rects.length) return;
    const collapsible = space && !source.mode.spaces;
    const raw = source.data.slice(start, end);
    const text = !space ? casedText(raw, source.transform, previous) : collapsible ? ' ' : preservedSpaces(raw);
    if (source.hidden || !anyShown(rects, source.clip)) {
      dropToken(source, text, rects, tokens, word);
      return;
    }
    if (rects.length > 1 && !collapsible &&
        splitToken(source, start, end, space, previous, range, tokens, word)) {
      return;
    }
    pushTextToken(source, text, rects[0], collapsible, tokens, space ? null : { source, start, end, previous }, word);
  }

  // The word of the page's text being read (words.current), begun when none
  // is: a word as the page's innerText reads it, the characters between its
  // white space, a break or an atomic inline, which runs on from one text node
  // into the next ("Rev<b>enue</b>"). Word = {text, hidden}: the characters of
  // it the page reads, as painted (text-transform applied), and whether the
  // slide leaves any of them out. Each is listed in words.read, in the order
  // the page reads them, for recordHiddenWords.
  function wordAt(words) {
    if (!words.current) {
      words.current = { text: '', hidden: false };
      words.read.push(words.current);
    }
    return words.current;
  }

  // Word and space tokens of one text node, plus a break for each preserved
  // newline. `words.previous` is what the next token follows (followingContext);
  // it carries over from one text node to the next, hidden ones included,
  // because they are still in the text. `words.segment` counts the
  // inline edges crossed so far: every token carries it, and a line is cut
  // where it changes (segmentsOf). `words.current` is the word of the page's
  // text being read (wordAt): white space and a break the page reads end it;
  // visibility: hidden text, which it does not read, neither ends nor joins it.
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
      nudge: piece.context.nudgePx * scale,
    };
    let start = 0;
    while (start < length) {
      const kind = characterKind(data.charCodeAt(start), mode);
      let end = start + 1;
      if (kind === 'break') {
        tokens.push(BREAK);
        words.previous = '';
        if (source.recordsHidden) words.current = null;
        start = end;
        continue;
      }
      while (end < length && characterKind(data.charCodeAt(end), mode) === kind) end++;
      const space = kind === 'space';
      if (space && source.recordsHidden) words.current = null;
      const word = !space && source.recordsHidden ? wordAt(words) : null;
      measureToken(source, start, end, space, words.previous, range, tokens, word);
      words.previous = space ? ' ' : followingContext(words.previous, data, start, end);
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
      words.previous = followingContext(words.previous, text, 0, text.length);
    }
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
  // `extents[i]` is runs[i]'s probe face and the bounds of its tokens' rects,
  // {left, top, right, bottom} (left to right, the width the browser drew it
  // at), and `advance`, false when a token of it was drawn as a shape (a
  // symbol marker), whose rect is no advance.
  // `rect` bounds every token; `body` the tokens set on the line's own
  // baseline, every run but a superscript or subscript, whose raise or drop
  // moves its rect off the line (null for a line of script runs alone), each
  // settled on that baseline (settledBounds: a nudged token unmoved), which is
  // where the line is placed and its growth read; `movedBody` the words of
  // them where the browser moved them (a space paints nothing, and one
  // between two moved spans is unmoved), and `nudge` the move they all share
  // (sharedNudgeOf), which places a box all of whose text one move shares
  // (textBlock). The script run carries its shift itself.
  function assembleLine(line, lineHeight) {
    const tokens = line.tokens;
    let first = 0;
    let last = tokens.length - 1;
    while (first <= last && tokens[first].collapsible) first++;
    while (last >= first && tokens[last].collapsible) last--;
    const runs = [];
    const extents = [];
    let rect = null;
    let body = null;
    let movedBody = null;
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
        extent.top = Math.min(extent.top, bounds.top);
        extent.right = Math.max(extent.right, bounds.right);
        extent.bottom = Math.max(extent.bottom, bounds.bottom);
        extent.advance = extent.advance && !token.shape;
      } else {
        const created = { text };
        for (let field = 0; field < RUN_STYLE_FIELDS.length; field++) {
          created[RUN_STYLE_FIELDS[field]] = token.style[RUN_STYLE_FIELDS[field]];
        }
        created.opticalTrackingPx = 0;
        created.unkernedTrackingPx = 0;
        runs.push(created);
        extents.push({
          face: token.face,
          left: bounds.left,
          top: bounds.top,
          right: bounds.right,
          bottom: bounds.bottom,
          advance: !token.shape,
        });
      }
      rect = unionBounds(rect, bounds);
      if (!token.style.baseline) {
        body = unionBounds(body, settledBounds(token));
        if (/\S/.test(token.text)) movedBody = unionBounds(movedBody, bounds);
      }
    }
    if (tokens.length && !runs.length) return null;
    return { runs, extents, rect, body, movedBody, nudge: sharedNudgeOf(tokens, first, last), lineHeight };
  }

  // The relative move (slide px down) every word of tokens[first..last]
  // shares, scripts included: 0 for none, NaN where they differ, and null
  // where the tokens hold no word (spaces paint nothing, so they do not count).
  function sharedNudgeOf(tokens, first, last) {
    let shared = null;
    for (let index = first; index <= last; index++) {
      const token = tokens[index];
      if (token.kind !== 'text' || !/\S/.test(token.text)) continue;
      const nudge = token.nudge || 0;
      if (shared === null) shared = nudge;
      else if (shared !== nudge) return NaN;
    }
    return shared;
  }

  // The move every word of a box's lines shares, when it shares one that is
  // not 0: then no word is where its line's baseline sets it, and the whole
  // box is placed where it is moved; 0 for a box whose
  // words are unmoved or moved apart, whose nudged words settle on their
  // lines' baselines.
  function boxNudgeOf(lines) {
    let shared = null;
    for (let index = 0; index < lines.length; index++) {
      const nudge = lines[index].nudge;
      if (nudge === null || nudge === undefined) continue;
      if (Number.isNaN(nudge)) return 0;
      if (shared === null) shared = nudge;
      else if (shared !== nudge) return 0;
    }
    return shared || 0;
  }

  // A text token's bounds settled on its line's baseline, which carries no
  // relative position: its rect, less the move of a relative position that
  // nudges it (its nudge).
  function settledBounds(token) {
    const nudge = token.nudge || 0;
    if (!nudge) return token.rect;
    const rect = token.rect;
    return { left: rect.left, top: rect.top - nudge, right: rect.right, bottom: rect.bottom - nudge };
  }

  // The union of bounds {left, top, right, bottom} `union` (or null) and `bounds`, as new bounds.
  function unionBounds(union, bounds) {
    if (!union) return { left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom };
    return {
      left: Math.min(union.left, bounds.left),
      top: Math.min(union.top, bounds.top),
      right: Math.max(union.right, bounds.right),
      bottom: Math.max(union.bottom, bounds.bottom),
    };
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
  // the line of the text before its closing edge (markAfterOpening,
  // markBeforeClosing), so a line that starts with the one or ends with the
  // other holds an inset too: a dot that leads a paragraph pushes in its first
  // line alone.
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

  // The tokens of one run's pieces, in DOM order (readTokens and its kin):
  // words, spaces, breaks, gaps and atomic inlines, each inside marker joined
  // to its line where the text runs straight on from it (joinMarkers).
  // `range` is the Range every token is measured with. Every word of the
  // page's text the run holds (wordAt) is added to `read`, in order; once the
  // run is laid out, recordHiddenWords reads them.
  function readRunTokens(nodes, scale, range, read) {
    const tokens = [];
    const words = { previous: '', segment: 0, current: null, read };
    const edges = { opening: false };
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
      words.current = null;
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
  // no text in the run paints. The words it does not show whole, the ellipsis
  // cut included, are hidden text (recordHiddenWords).
  function layoutInlineRun(nodes, s, scale, ellipsis) {
    const rtl = s.direction === 'rtl';
    const range = document.createRange();
    const read = [];
    const tokens = readRunTokens(nodes, scale, range, read);
    const clustered = clusterLines(tokens, rtl);
    for (let index = 0; ellipsis && index < clustered.length; index++) {
      truncateAtEllipsis(clustered[index], ellipsis, scale, range);
    }
    recordHiddenWords(read);
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

  // `upright` says the lines' rects are upright on the slide (not turned), so
  // where each line's own text lies (its body's top and height) is queued with
  // its paragraph, for applyMetrics to read how far past its spacing the
  // browser set it (growthPx). Each queued paragraph knows the one before it
  // in the block (`previous`, null for the first).
  function paragraphsOf(lines, upright) {
    const paragraphs = [];
    let paragraph = null;
    let pending = null;
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
          pending = { paragraph, face, lineHeight: line.lineHeight, bodies: [], previous: pending };
          pendingParagraphs.push(pending);
          key = lineKey;
        }
      }
      paragraph.lines.push({ runs: line.runs });
      const body = upright && line.runs.length ? line.body || line.rect : null;
      pending.bodies.push(body ? { top: body.top, height: body.bottom - body.top } : null);
    }
    return paragraphs;
  }

  // Queues every run of the block for the optical-size comparison.
  // `advancesRead` is whether its tokens' rects measured their advances: not
  // under a turn, where they bound the turned glyphs. A justified line is drawn
  // stretched, a symbol marker is drawn as a shape, and turned text's rects are
  // no widths, so their natural width at the browser's own cut is probed
  // instead (width null). `endsLine` says no run follows it on its line, so
  // the tracking after its last character moves nothing.
  function queueRuns(lines, align, advancesRead) {
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      for (let run = 0; run < line.runs.length; run++) {
        const extent = line.extents[run];
        pendingRuns.push({
          run: line.runs[run],
          runs: line.runs,
          face: extent.face,
          width: align === 'justify' || !extent.advance || !advancesRead ? null : extent.right - extent.left,
          endsLine: run === line.runs.length - 1,
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
  //   line's bottom in normal flow, each line's text on its own baseline
  //   (assembleLine body), so a superscript does not lift its line, and a
  //   nudged word settled on that baseline: the export moves no single run.
  //   A box all of whose words one relative move shares is placed where they
  //   are moved instead, whole (boxNudgeOf). Taken as
  //   the union, so the box holds every line whatever order they come in.
  //   Its top is the first line's glyph top; the emitter (emit_text.cjs)
  //   raises the box by the first-line offset calibrated against PowerPoint
  //   and Google Slides.
  // * Justified text is written aligned to the edge its lines start from, with
  //   the browser's line breaks: PowerPoint and Google Slides justify a line
  //   to the full box, slack included, so every justified line ran about 35 px
  //   past the browser's (scripts/export_fidelity/CALIBRATION.md, A3).
  function textBlock(layout, element, s, frame, placement) {
    const lines = layout.lines;
    const moved = boxNudgeOf(lines) !== 0;
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    for (let index = 0; index < lines.length; index++) {
      const rect = lines[index].rect;
      if (!rect) continue;
      // Across, a line is where its own baseline's text is: a superscript
      // stands above it and a subscript below it, carrying its shift itself.
      // A box all of whose words one move shares is where they are moved.
      const body = (moved ? lines[index].movedBody : lines[index].body) || rect;
      left = Math.min(left, rect.left);
      right = Math.max(right, rect.right);
      top = Math.min(top, body.top);
      bottom = Math.max(bottom, body.bottom);
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
      paragraphs: paragraphsOf(lines, !frame.angle),
    };
  }

  // ─── text blocks ──────────────────────────────────────────────────
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
    hiddenParts.push(text);
  }

  // recordHiddenWords(read): each word of a laid-out run's text (wordAt,
  // `read` in the order the page reads them) that the slide does not show
  // whole, whole: a word a clip, a fade to nothing or an ellipsis leaves out
  // in part is a word the page reads that the slide does not show, and a
  // fragment of it ("erv" of "overview") is no word of the page's text.
  function recordHiddenWords(read) {
    for (let index = 0; index < read.length; index++) {
      if (read[index].hidden && read[index].text) hiddenParts.push(read[index].text);
    }
  }

  // hiddenText() -> model.reference.hiddenText: the words of every subtree
  // and every word recorded, in order, single-spaced.
  function hiddenText() {
    return hiddenParts.join(' ').replace(/\s+/g, ' ').trim();
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
        // The run of a flex or grid container is an anonymous item, which the
        // container aligns, not its text-align: its lines carry the item, so
        // turnedBlocks places them by their own bounds, as unturned text's
        // 'text' placement does.
        if (itemsAreBlocks) {
          const anonymousItem = { run: index };
          for (let line = 0; line < lines.length; line++) lines[line].anonymousItem = anonymousItem;
        }
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
        return paragraphsOf(layout.lines, !walk.frame.angle);
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
  // paragraph mark, by (the browser's line box holds a strut of it too). Its
  // family is resolved after the walk, as a run's is (resolveWrittenFaces).
  function fontOf(s, scale) {
    const family = familyOf(s.fontFamily);
    const font = {
      family,
      weight: weightOf(s.fontWeight),
      italic: s.fontStyle !== 'normal',
      sizePx: (parseFloat(s.fontSize) || 0) * scale,
    };
    pendingFonts.push({ font, face: probeFaceOf(s, family, scale) });
    return font;
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
    measureMarkers,
    recordHiddenText,
    turnedBlocks,
    turnedMarkerBlock,
    writingTurn,
    truncated: () => truncated,
  };
}

// The text layout as one page source: its four modules' factories, then
// createTextLayout, which makes them.
export const TEXT_SOURCE = [
  TEXT_METRICS_SOURCE,
  LIST_MARKERS_SOURCE,
  ELLIPSIS_SOURCE,
  TURNED_TEXT_SOURCE,
  createTextLayout.toString(),
].join('\n');
