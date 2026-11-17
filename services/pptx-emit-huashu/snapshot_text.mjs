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
// Geometry comes from the text's own rects, not the element box, so an icon or
// logo beside the text never overlaps it; centred, right-aligned and justified
// text spans its container's content box so the alignment survives a slightly
// wider font. Every box carries width slack on the side its alignment grows.
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
// /**
//  * TextBlock = {order, x,y,w,h, rotate:null, wrap, align:'left'|'center'|'right'|'justify', rtl,
//  *              paragraphs:[{lineSpacingPct:number|null, lines:[{runs:Run[]}]}],
//  *              follows:Element|null}   (page-side only; never in the slide model)
//  * Run = {text, family, weight, italic, sizePx, color:'RRGGBB', letterSpacingPx,
//  *        underline, strike, baseline:null|'super'|'sub'}
//  *
//  * A line after the first in its paragraph is a soft break; a line with no runs
//  * is a blank line (two <br>s, an empty pre line). Sizes are CSS px on the slide.
//  * text     as painted: text-transform applied;
//  * family   the first face in the stack that is not a generic or a system alias;
//  *          a stack of generics alone is Arial, Times New Roman or Courier New;
//  * weight   100..900, the computed weight to the nearest hundred;
//  * color    solid, pre-blended: what the browser paints the glyphs with, composited
//  *          layer by layer over the backdrop (Drive drops text alpha).
//  */

// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE: domAccess,
// childNodesOf, reportCollectionLoss, DOM_ACCESS_LOG_PREFIX and the two limits are
// its free names. It is stringified, so it closes over nothing on the Node side;
// what it needs from the snapshot arrives in `env`:
//   replaced        the Set of tag names whose content is drawn, not laid out as text;
//   opacityOf       computed style -> its own opacity;
//   backdropInside  (backdrop, style) -> the backdrop of the content inside that element;
//   textColour      (backdrop, style) -> 'RRGGBB', the solid colour its text paints;
//   boxGeometry     (element, rect, frame) -> the element's box | null;
//   contentBox      (style, box) -> the box inside border and padding | null.
function createTextLayout(env) {
  const TEXT_NODE = 3;
  const ELEMENT_NODE = 1;
  const NBSP = '\u00a0';
  // Spec §3 Text, Wrapping: width slack, because Google's importer ignores wrap="none".
  const SLACK_FRACTION = 0.06;
  const SLACK_PX = 4;
  // How far the box's top sits above the first line's glyph top. Zero until it
  // is calibrated against PowerPoint and Google Slides renders.
  const FIRST_LINE_OFFSET_PX = 0;
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

  const dom = domAccess();
  // Text layout is bounded on its own: every child node listed and every rect
  // read spends from one budget, so a realm that lies about the tree or about a
  // Range's rects cannot make the text pass run forever. Meeting the bound is
  // announced; the text past it is missing from the slide.
  let budget = COLLECTION_ITEM_LIMIT;
  let truncated = false;

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
  //   {style, opacity, backdrop, decoration, baseline}
  //   style       its parent element's computed style;
  //   opacity     the cumulative opacity it paints at;
  //   backdrop    what it is composited over (snapshot.mjs backdropInside);
  //   decoration  {underline, strike} propagated to it;
  //   baseline    'super' | 'sub' from an inline ancestor's vertical-align, else null.
  function openChildren(stack, node, context, depth) {
    if (depth > WALK_STEP_LIMIT) {
      if (!truncated) {
        truncated = true;
        reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'cut at depth ' + WALK_STEP_LIMIT, 'the snapshot text layout');
      }
      return;
    }
    if (budget <= 0) return;
    const nodes = childNodesOf(node);
    if (!spend(nodes.length)) return;
    stack.push({ nodes, index: 0, context, depth });
  }

  // The context inside an inline child element. Its own opacity, background,
  // decoration and vertical-align apply to the text it holds.
  function inlineContext(outer, cs) {
    return {
      style: cs,
      opacity: outer.opacity * env.opacityOf(cs),
      backdrop: env.backdropInside(outer.backdrop, cs),
      decoration: decorationInside(outer.decoration, cs, false),
      baseline: baselineShiftOf(cs) || outer.baseline,
    };
  }

  // The container's runs, in DOM order. Each is {nodes, follows}: `follows` is
  // the block-level child the run comes after (null for the leading run), and
  // `nodes` its pieces in DOM order:
  //   {kind:'text', node, context}  a text node and what it paints with;
  //   {kind:'break'}                a <br>;
  //   {kind:'atomic', element}      an atomic inline: it paints its own
  //                                 content (its own block, or a picture)
  //                                 and gives the run no text.
  // display:contents children are transparent: no box, so no opacity,
  // background or decoration of their own. display:none ones are skipped.
  // `walk` is the container's {opacity, backdrop, decoration} from the
  // snapshot walk; the container's own vertical-align is already where the
  // browser placed its text, so its runs start on the baseline.
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
    }, 1);
    while (stack.length) {
      const frame = stack[stack.length - 1];
      if (frame.index >= frame.nodes.length) {
        stack.pop();
        continue;
      }
      const node = frame.nodes[frame.index++];
      const type = dom.nodeType(node);
      if (type === TEXT_NODE) {
        run.push({ kind: 'text', node, context: frame.context });
        continue;
      }
      if (type !== ELEMENT_NODE) continue;
      const name = String(dom.tagName(node) || '').toLowerCase();
      const cs = window.getComputedStyle(node);
      if (cs.display === 'none') continue;
      if (cs.display === 'contents') {
        const outer = frame.context;
        openChildren(stack, node, {
          style: cs,
          opacity: outer.opacity,
          backdrop: outer.backdrop,
          decoration: outer.decoration,
          baseline: outer.baseline,
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
        const context = inlineContext(frame.context, cs);
        if (context.opacity > 0) openChildren(stack, node, context, frame.depth + 1);
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
    const role = inlineRole(String(dom.tagName(element) || '').toLowerCase(), s);
    return decorationInside(outer, s, role === 'out-of-flow' || role === 'atomic');
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
  // word that wraps at its hyphen capitalises as it would on one line.
  //   source    one text node's {node, data, mode, style, tabSize, transform};
  //   previous  the character before the token (casedText).
  function splitToken(source, start, end, space, previous, range, tokens) {
    const pieces = [];
    let pending = '';
    let before = previous;
    let index = start;
    while (index < end) {
      const length = codePointLength(source.data, index);
      const raw = source.data.slice(index, index + length);
      const text = space ? preservedSpaces(raw) : casedText(raw, source.transform, before);
      before = raw;
      range.setStart(source.node, index);
      range.setEnd(source.node, index + length);
      index += length;
      const rects = paintedRects(range, space);
      if (!rects.length) {
        if (pieces.length) pieces[pieces.length - 1].text += text;
        else pending += text;
        continue;
      }
      pieces.push({
        kind: 'text', text: pending + text, rect: rects[0], style: source.style, collapsible: false, tabSize: source.tabSize,
      });
      pending = '';
    }
    for (let piece = 0; piece < pieces.length; piece++) tokens.push(pieces[piece]);
    return pieces.length > 0;
  }

  function measureToken(source, start, end, space, previous, range, tokens) {
    range.setStart(source.node, start);
    range.setEnd(source.node, end);
    const rects = paintedRects(range, space);
    if (!rects.length) return;
    const collapsible = space && !source.mode.spaces;
    const raw = source.data.slice(start, end);
    const text = !space ? casedText(raw, source.transform, previous) : collapsible ? ' ' : preservedSpaces(raw);
    if (rects.length > 1 && !collapsible &&
        splitToken(source, start, end, space, previous, range, tokens)) {
      return;
    }
    tokens.push({ kind: 'text', text, rect: rects[0], style: source.style, collapsible, tabSize: source.tabSize });
  }

  // Word and space tokens of one text node, plus a break for each preserved
  // newline. `words.previous` is the character the next token follows
  // (casedText); it carries over from one text node to the next, hidden ones
  // included, because they are still in the text.
  function readTokens(piece, scale, range, tokens, words) {
    const ps = piece.context.style;
    // A hidden text node keeps its place in the layout, line breaks included,
    // but paints nothing.
    const hidden = ps.visibility !== 'visible';
    const data = String(dom.textData(piece.node) || '');
    const length = Math.min(data.length, COLLECTION_ITEM_LIMIT);
    if (!length) return;
    const mode = whiteSpaceOf(ps);
    const source = {
      node: piece.node,
      data,
      mode,
      style: runStyle(piece.context, scale),
      tabSize: mode.spaces ? tabSizeOf(ps) : DEFAULT_TAB_SIZE,
      transform: String(ps.textTransform || 'none'),
    };
    let start = 0;
    while (start < length) {
      const kind = characterKind(data.charCodeAt(start), mode);
      let end = start + 1;
      if (kind === 'break') {
        tokens.push(BREAK);
        words.previous = '';
        start = end;
        continue;
      }
      while (end < length && characterKind(data.charCodeAt(end), mode) === kind) end++;
      if (!hidden) measureToken(source, start, end, kind === 'space', words.previous, range, tokens);
      words.previous = kind === 'space' ? ' ' : lastCodePoint(data, start, end);
      start = end;
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
  function assembleLine(line, lineHeight) {
    const tokens = line.tokens;
    let first = 0;
    let last = tokens.length - 1;
    while (first <= last && tokens[first].collapsible) first++;
    while (last >= first && tokens[last].collapsible) last--;
    const runs = [];
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
      if (run && sameStyle(run, token.style)) {
        run.text += text;
      } else {
        const created = { text };
        for (let field = 0; field < RUN_STYLE_FIELDS.length; field++) {
          created[RUN_STYLE_FIELDS[field]] = token.style[RUN_STYLE_FIELDS[field]];
        }
        runs.push(created);
      }
      const bounds = token.rect;
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
    return { runs, rect, lineHeight };
  }

  // layoutInlineRun(nodes, s, scale) -> {lines:[{runs, rect, lineHeight}], rtl} | null
  //   nodes  one run's pieces, as collectRuns gathers them;
  //   s      the computed style of the block that holds the run;
  //   scale  the block's cumulative transform scale (font sizes and tracking scale with it).
  // Leading and trailing blank lines paint nothing and are dropped; null when
  // nothing in the run paints.
  function layoutInlineRun(nodes, s, scale) {
    const rtl = s.direction === 'rtl';
    const range = document.createRange();
    const tokens = [];
    const words = { previous: '' };
    for (let index = 0; index < nodes.length; index++) {
      const piece = nodes[index];
      if (piece.kind === 'text') {
        readTokens(piece, scale, range, tokens, words);
        continue;
      }
      if (piece.kind === 'break') tokens.push(BREAK);
      // A break or an atomic inline ends the word before it.
      words.previous = '';
    }
    const clustered = clusterLines(tokens, rtl);
    const lines = [];
    for (let index = 0; index < clustered.length; index++) {
      const line = assembleLine(clustered[index], String(s.lineHeight));
      if (line) lines.push(line);
    }
    let first = 0;
    let last = lines.length - 1;
    while (first <= last && !lines[first].runs.length) first++;
    while (last >= first && !lines[last].runs.length) last--;
    if (first > last) return null;
    return { lines: lines.slice(first, last + 1), rtl };
  }

  // ─── paragraphs and geometry ─────────────────────────────────────────
  // Lines of one size are soft breaks inside one paragraph. A line whose largest
  // run differs in size, or whose line-height differs, starts a paragraph of its
  // own, because PowerPoint spacing is per paragraph. A blank line stays in the
  // paragraph before it.
  function paragraphsOf(lines) {
    const paragraphs = [];
    let paragraph = null;
    let key = null;
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      if (line.runs.length) {
        let largest = 0;
        for (let run = 0; run < line.runs.length; run++) largest = Math.max(largest, line.runs[run].sizePx);
        const lineKey = largest + '|' + line.lineHeight;
        if (!paragraph || lineKey !== key) {
          paragraph = { lineSpacingPct: null, lines: [] };
          paragraphs.push(paragraph);
          key = lineKey;
        }
      }
      paragraph.lines.push({ runs: line.runs });
    }
    return paragraphs;
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

  // The text box of one laid-out run.
  // * Left-aligned text, and any anonymous flex or grid item (whose own box the
  //   page never exposes), is placed by its text bounds: the union of its lines.
  // * Centred, right-aligned and justified text spans its container's content
  //   box, widened to the text where the text overflows it.
  // * Slack (6% + 4 px) widens the box on the side its alignment grows: right
  //   for left-aligned text, both sides for centred, left for right-aligned.
  // * Vertically it spans its lines: from the first line's top to the last
  //   line's bottom in normal flow. Taken as the union, so lines that run
  //   another way (text under a rotation runs bottom to top) still get a box.
  function textBlock(layout, element, s, order, frame, anonymous) {
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
    if (align !== 'left' && !anonymous) {
      const box = env.boxGeometry(element, element.getBoundingClientRect(), frame);
      const area = box ? env.contentBox(s, box) : null;
      if (area) {
        x = Math.min(area.x, left);
        w = Math.max(area.x + area.w, right) - x;
      }
    }
    const extra = w * SLACK_FRACTION + SLACK_PX;
    const shift = align === 'center' ? extra / 2 : align === 'right' ? extra : 0;
    return {
      order,
      x: x - shift,
      y: top - FIRST_LINE_OFFSET_PX,
      w: w + extra,
      h: bottom - top,
      rotate: null,
      wrap: lines.length > 1,
      align,
      rtl: layout.rtl,
      paragraphs: paragraphsOf(lines),
    };
  }

  // collectTextBlocks(el, s, paint, seq, walk) -> TextBlock[]
  //   el, s   the element the snapshot walk is visiting and its computed style;
  //   paint   its paint-order prefix; its text paints at paint + [4, 0, seq, 1],
  //           inline content of its layer, above any decoration (sub 0) of the block;
  //   walk    {opacity, frame, backdrop, decoration}: its cumulative opacity, its
  //           transform frame, the backdrop of its content (backdropInside) and
  //           the decorations on its text (decorationOf).
  // A block that comes after a block-level child also names that child in
  // `follows`: in tree order it paints after the child's whole subtree, which
  // only the walk can place, so the walk re-sequences it there.
  // The text of an inline element belongs to the block that contains it, so an
  // inline element, a replaced element or a box-less one holds no block of its own.
  function collectTextBlocks(el, s, paint, seq, walk) {
    const name = String(dom.tagName(el) || '').toLowerCase();
    const display = String(s.display);
    if (env.replaced.has(name) || display === 'inline' || display === 'none' ||
        display === 'contents' || /^ruby/.test(display) || budget <= 0) {
      return [];
    }
    const itemsAreBlocks = /flex|grid/.test(display);
    const runs = collectRuns(el, s, walk, itemsAreBlocks);
    const blocks = [];
    for (let index = 0; index < runs.length; index++) {
      const layout = layoutInlineRun(runs[index].nodes, s, walk.frame.scale);
      if (!layout) continue;
      const block = textBlock(layout, el, s, paint.concat([4, 0, seq, 1]), walk.frame, itemsAreBlocks);
      if (!block) continue;
      block.follows = runs[index].follows;
      blocks.push(block);
    }
    return blocks;
  }

  return {
    collectTextBlocks,
    decorationOf,
    layoutInlineRun,
    loadedFonts,
    truncated: () => truncated,
  };
}

export const TEXT_SOURCE = createTextLayout.toString();
