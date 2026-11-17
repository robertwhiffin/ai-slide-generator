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
// /**
//  * TextBlock = {order, x,y,w,h, rotate:null, wrap, align:'left'|'center'|'right'|'justify', rtl,
//  *              paragraphs:[{lineSpacingPct:number|null, lines:[{runs:Run[]}]}],
//  *              follows:Element|null}   (page-side only; never in the slide model)
//  * Run = {text, family, weight, italic, sizePx, color:'RRGGBB', alpha, letterSpacingPx,
//  *        underline, strike, baseline:null|'super'|'sub'}
//  *
//  * A line after the first in its paragraph is a soft break; a line with no runs
//  * is a blank line (two <br>s, an empty pre line). `alpha` is the colour's own
//  * alpha times the cumulative opacity. Sizes are CSS px on the slide.
//  */

// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE: domAccess,
// childNodesOf, reportCollectionLoss, DOM_ACCESS_LOG_PREFIX and the two limits are
// its free names. It is stringified, so it closes over nothing on the Node side;
// what it needs from the snapshot arrives in `env`:
//   replaced      the Set of tag names whose content is drawn, not laid out as text;
//   parseColour   CSS colour -> {color:'RRGGBB', alpha} | null;
//   opacityOf     computed style -> its own opacity;
//   boxGeometry   (element, rect, frame) -> the element's box | null;
//   contentBox    (style, box) -> the box inside border and padding | null.
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
    'family', 'weight', 'italic', 'sizePx', 'color', 'alpha',
    'letterSpacingPx', 'underline', 'strike', 'baseline',
  ];
  const BREAK = { kind: 'break' };
  // Chrome's default tab-size; a computed length instead of a count falls back to it.
  const DEFAULT_TAB_SIZE = 8;

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

  function openChildren(stack, node, style, opacity, depth) {
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
    stack.push({ nodes, index: 0, style, opacity, depth });
  }

  // The container's runs, in DOM order. Each is {nodes, follows}: `follows` is
  // the block-level child the run comes after (null for the leading run), and
  // `nodes` its pieces in DOM order:
  //   {kind:'text', node, style, opacity}  a text node, its parent's computed style
  //                                        and the cumulative opacity it paints at;
  //   {kind:'break'}                       a <br>;
  //   {kind:'atomic', element}             an atomic inline: it paints its own
  //                                        content (its own block, or a picture)
  //                                        and gives the run no text.
  // display:contents children are transparent; display:none ones are skipped.
  function collectRuns(container, containerStyle, opacity, itemsAreBlocks) {
    const runs = [];
    let run = [];
    let follows = null;
    const stack = [];
    openChildren(stack, container, containerStyle, opacity, 1);
    while (stack.length) {
      const frame = stack[stack.length - 1];
      if (frame.index >= frame.nodes.length) {
        stack.pop();
        continue;
      }
      const node = frame.nodes[frame.index++];
      const type = dom.nodeType(node);
      if (type === TEXT_NODE) {
        run.push({ kind: 'text', node, style: frame.style, opacity: frame.opacity });
        continue;
      }
      if (type !== ELEMENT_NODE) continue;
      const name = String(dom.tagName(node) || '').toLowerCase();
      const cs = window.getComputedStyle(node);
      if (cs.display === 'none') continue;
      if (cs.display === 'contents') {
        openChildren(stack, node, cs, frame.opacity, frame.depth + 1);
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
        const nested = frame.opacity * env.opacityOf(cs);
        if (nested > 0) openChildren(stack, node, cs, nested, frame.depth + 1);
      }
      // An out-of-flow child (a float, an absolute box) leaves the line where it
      // is: it is a block of its own and does not split the text around it.
    }
    if (run.length) runs.push({ nodes: run, follows });
    return runs;
  }

  // ─── run style ───────────────────────────────────────────────────────
  // The first face in a font-family stack, quotes stripped. Commas inside a
  // quoted name do not separate faces.
  function firstFamily(stack) {
    const value = String(stack || '');
    let quote = '';
    let end = value.length;
    for (let index = 0; index < value.length; index++) {
      const character = value[index];
      if (quote) {
        if (character === quote) quote = '';
      } else if (character === '"' || character === "'") {
        quote = character;
      } else if (character === ',') {
        end = index;
        break;
      }
    }
    return value.slice(0, end).trim().replace(/^["']|["']$/g, '').trim();
  }

  function runStyle(ps, opacity, scale) {
    const colour = env.parseColour(ps.color);
    const decoration = String(ps.textDecorationLine || '');
    const letterSpacing = parseFloat(ps.letterSpacing);
    return {
      family: firstFamily(ps.fontFamily),
      weight: parseInt(ps.fontWeight, 10) || 400,
      italic: ps.fontStyle !== 'normal',
      sizePx: (parseFloat(ps.fontSize) || 0) * scale,
      color: colour ? colour.color : '000000',
      alpha: (colour ? colour.alpha : 0) * opacity,
      letterSpacingPx: Number.isFinite(letterSpacing) ? letterSpacing * scale : 0,
      underline: /\bunderline\b/.test(decoration),
      strike: /\bline-through\b/.test(decoration),
      baseline: ps.verticalAlign === 'super' ? 'super' : ps.verticalAlign === 'sub' ? 'sub' : null,
    };
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
  // character is lost.
  function splitToken(node, data, start, end, space, style, tabSize, range, tokens) {
    const pieces = [];
    let pending = '';
    let index = start;
    while (index < end) {
      const length = codePointLength(data, index);
      const raw = data.slice(index, index + length);
      const text = space ? preservedSpaces(raw) : raw;
      range.setStart(node, index);
      range.setEnd(node, index + length);
      index += length;
      const rects = paintedRects(range, space);
      if (!rects.length) {
        if (pieces.length) pieces[pieces.length - 1].text += text;
        else pending += text;
        continue;
      }
      pieces.push({ kind: 'text', text: pending + text, rect: rects[0], style, collapsible: false, tabSize });
      pending = '';
    }
    for (let piece = 0; piece < pieces.length; piece++) tokens.push(pieces[piece]);
    return pieces.length > 0;
  }

  function measureToken(node, data, start, end, space, mode, style, tabSize, range, tokens) {
    range.setStart(node, start);
    range.setEnd(node, end);
    const rects = paintedRects(range, space);
    if (!rects.length) return;
    const collapsible = space && !mode.spaces;
    const raw = data.slice(start, end);
    const text = !space ? raw : collapsible ? ' ' : preservedSpaces(raw);
    if (rects.length > 1 && !collapsible &&
        splitToken(node, data, start, end, space, style, tabSize, range, tokens)) {
      return;
    }
    tokens.push({ kind: 'text', text, rect: rects[0], style, collapsible, tabSize });
  }

  // Word and space tokens of one text node, plus a break for each preserved newline.
  function readTokens(piece, scale, range, tokens) {
    const ps = piece.style;
    // A hidden text node keeps its place in the layout, line breaks included,
    // but paints nothing.
    const hidden = ps.visibility !== 'visible';
    const data = String(dom.textData(piece.node) || '');
    const length = Math.min(data.length, COLLECTION_ITEM_LIMIT);
    if (!length) return;
    const mode = whiteSpaceOf(ps);
    const style = runStyle(ps, piece.opacity, scale);
    const tabSize = mode.spaces ? tabSizeOf(ps) : DEFAULT_TAB_SIZE;
    let start = 0;
    while (start < length) {
      const kind = characterKind(data.charCodeAt(start), mode);
      let end = start + 1;
      if (kind === 'break') {
        tokens.push(BREAK);
        start = end;
        continue;
      }
      while (end < length && characterKind(data.charCodeAt(end), mode) === kind) end++;
      if (!hidden) measureToken(piece.node, data, start, end, kind === 'space', mode, style, tabSize, range, tokens);
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
    for (let index = 0; index < nodes.length; index++) {
      const piece = nodes[index];
      if (piece.kind === 'break') tokens.push(BREAK);
      else if (piece.kind === 'text') readTokens(piece, scale, range, tokens);
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
  //   walk    {opacity, frame}: its cumulative opacity and transform frame.
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
    const runs = collectRuns(el, s, walk.opacity, itemsAreBlocks);
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
    layoutInlineRun,
    truncated: () => truncated,
  };
}

export const TEXT_SOURCE = createTextLayout.toString();
