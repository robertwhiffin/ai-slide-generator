// Pre-process Tellr LLM-generated HTML so it satisfies huashu-design's
// 4 hard rules. Runs as a Playwright page.evaluate() callback against the
// loaded slide DOM, mutating in place before html2pptx walks it.
//
// Rules (from references/editable-pptx.md):
//   1. No raw text in <div> — must be in <p>/<h1>-<h6>/<ul>/<ol>
//   2. No CSS gradients
//   3. No background/border/shadow on text tags (<p>, <h*>)
//   4. No background-image on <div> — use <img> instead
//
// We fix 1 and 4 mechanically here. 2 and 3 are tolerated by softening
// huashu's html2pptx.js validator (see html2pptx.js patch). Class 5
// "body overflow" we also soften in html2pptx.js because Tellr decks
// consistently overflow by ~60pt and the LLM doesn't know to leave a
// margin.
//
// Why an HTML mutation pass instead of an LLM prompt change: Tellr decks
// are already generated. Mutating the DOM is reversible per-export. An
// LLM prompt change affects every future deck and requires re-validating
// all existing slide-style outputs.

// The IIFE is async (rasterizeSvgDataUriImages awaits image decodes), so the
// source expression evaluates to a Promise — page.evaluate() awaits promise
// results, string-expression or not (html2pptx.js:1026 needs no change).
export const PREPROCESS_SOURCE = `
(async function () {
  // ─── Monospace code blocks → single text frame ─────────────────────
  // Tellr renders SQL/code as: parent <div style="font-family: monospace">
  // containing N child <div>s (one per code line) and <br>s between
  // sections. Without this step, each child div becomes its own text
  // frame in the PPT, producing visible blank-line gaps between lines
  // (since each text frame is line-height tall). And our existing
  // wrapBareTextInDivs would also wrap the inter-div <br>s into empty
  // <p>s, doubling the gap. Fix: collapse the entire panel into a
  // single <p> with <br> separators so huashu emits one text frame
  // with paragraph-break runs (already tight thanks to paraSpaceAfter=0
  // and the breakLine fix in parseInlineFormatting).
  function flattenMonospaceCodeBlocks() {
    let count = 0;
    document.querySelectorAll('div').forEach((panel) => {
      const cs = window.getComputedStyle(panel);
      const fam = (cs.fontFamily || '').toLowerCase();
      const isMono = /\\bmono(space)?\\b|courier|consolas|menlo|monaco/i.test(fam);
      if (!isMono) return;
      const childDivs = Array.from(panel.children).filter((c) => c.tagName === 'DIV');
      if (childDivs.length < 2) return;

      // Collect inline content from each child div + a <br> after, plus
      // honor any direct <br> children (used between code sections in
      // the source).
      const fragment = document.createDocumentFragment();
      let lastWasBr = false;
      Array.from(panel.childNodes).forEach((child) => {
        if (child.nodeType === 1 && child.tagName === 'DIV') {
          // Replace leading runs of regular spaces in text-node descendants
          // with NBSP so huashu's whitespace-collapse doesn't eat the
          // indent. Only at the start of the line; mid-line spaces stay
          // single (matches monospace rendering of "  prod_catalog").
          const inlineChildren = Array.from(child.childNodes);
          for (let i = 0; i < inlineChildren.length; i++) {
            const n = inlineChildren[i];
            if (n.nodeType === 3 /* TEXT_NODE */) {
              const t = n.textContent;
              const m = t.match(/^( +)/);
              if (m) {
                n.textContent = '\\u00A0'.repeat(m[1].length) + t.slice(m[1].length);
              }
              fragment.appendChild(n);
            } else {
              fragment.appendChild(n);
            }
            // Only replace leading on the FIRST text-node of the line.
            // Subsequent text nodes don't get NBSP'd (mid-line).
          }
          fragment.appendChild(document.createElement('br'));
          lastWasBr = true;
        } else if (child.nodeType === 1 && child.tagName === 'BR') {
          // Explicit <br> in source = blank-line separator between code
          // sections. huashu/pptxgenjs collapses back-to-back <br>s into
          // a single line break, so we materialize the blank line as
          // NBSP + <br> — the NBSP becomes its own paragraph (visually
          // blank), giving content1 / content2 / [blank] / content3.
          fragment.appendChild(document.createTextNode('\\u00A0'));
          fragment.appendChild(document.createElement('br'));
          lastWasBr = true;
        } else if (child.nodeType === 3 /* TEXT_NODE */ && !child.textContent.trim()) {
          // skip whitespace-only text nodes between block siblings
        } else {
          // unrecognized — preserve as-is
          fragment.appendChild(child.cloneNode(true));
          lastWasBr = false;
        }
      });

      // Replace the panel's children with one <p> wrapping everything.
      // Pin computed font/color on the <p> inline so deck CSS rules for
      // generic <p> don't change them. text-align: left for code panels.
      panel.innerHTML = '';
      const p = document.createElement('p');
      p.style.margin = '0';
      p.style.padding = '0';
      p.style.fontSize = cs.fontSize;
      p.style.fontFamily = cs.fontFamily;
      p.style.fontWeight = cs.fontWeight;
      p.style.color = cs.color;
      p.style.lineHeight = cs.lineHeight;
      p.style.textAlign = 'left';
      p.style.whiteSpace = 'normal';  // huashu collapses whitespace anyway
      p.appendChild(fragment);
      panel.appendChild(p);
      count++;
    });
    return count;
  }

  // ─── Rule 1: wrap inline content (text + inline elements) in <p> ───
  // huashu's text walker only emits records for P/H1-6/UL/OL/LI. Anything
  // direct-inline inside a <div>/<pre>/<code> — bare text nodes AND inline
  // elements like <strong>, <span>, <b>, <em>, <a> — gets walked but
  // produces no record. Fix: walk parents that aren't already block-text
  // tags, find runs of contiguous inline content, wrap each run in a <p>.
  // huashu's parseInlineFormatting then processes the inline children to
  // build runs with bold/italic/color etc.
  const BLOCK_TAGS = new Set([
    'DIV', 'P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
    'UL', 'OL', 'LI', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TD', 'TH',
    'IMG', 'CANVAS', 'VIDEO', 'AUDIO', 'IFRAME', 'SVG',
    'SECTION', 'ARTICLE', 'ASIDE', 'HEADER', 'FOOTER', 'NAV',
    'FIGURE', 'FIGCAPTION', 'PRE', 'HR',
  ]);
  function isInlineNode(node) {
    if (node.nodeType === 3 /* TEXT_NODE */) {
      return node.textContent.trim().length > 0;
    }
    if (node.nodeType !== 1 /* ELEMENT_NODE */) return false;
    return !BLOCK_TAGS.has(node.tagName);
  }
  function wrapInlineRunsIn(parent) {
    let count = 0;
    const children = Array.from(parent.childNodes);
    let i = 0;
    // Snapshot parent's computed font props so the new <p> doesn't get
    // subjected to existing <p> CSS rules. Example: a deck CSS
    // ".takeaway-card p { font-size: 13px }" would shrink an emoji
    // that should inherit the parent .tk-icon's 28px. Inline styles
    // win over class selectors.
    const parentCs = window.getComputedStyle(parent);
    const inheritedFont = {
      fontSize: parentCs.fontSize,
      fontFamily: parentCs.fontFamily,
      fontWeight: parentCs.fontWeight,
      fontStyle: parentCs.fontStyle,
      color: parentCs.color,
      lineHeight: parentCs.lineHeight,
      textAlign: parentCs.textAlign,
      letterSpacing: parentCs.letterSpacing,
    };
    while (i < children.length) {
      if (!isInlineNode(children[i])) { i++; continue; }
      const run = [];
      while (i < children.length && isInlineNode(children[i])) {
        run.push(children[i]);
        i++;
      }
      const p = document.createElement('p');
      p.style.margin = '0';
      p.style.padding = '0';
      // Force inheritance by copying parent's resolved font props inline.
      Object.assign(p.style, inheritedFont);
      parent.insertBefore(p, run[0]);
      run.forEach((n) => p.appendChild(n));
      count++;
    }
    return count;
  }
  function wrapBareTextInDivs() {
    let wrapped = 0;
    // Also walk <pre> and <code> so SQL/code blocks survive (they're
    // BLOCK_TAGS, but we want to wrap their inline children too).
    document.querySelectorAll('div, pre, code').forEach((parent) => {
      wrapped += wrapInlineRunsIn(parent);
    });
    return wrapped;
  }

  // ─── Slide-root background → body background ──────────────────────
  // Tellr decks set the slide's background on its root div (e.g.
  // .slide-title { background: linear-gradient(...); }), not on <body>.
  // huashu only reads body.bg, so cover/CTA slides export with the body's
  // default light-gray bg and white-on-light text becomes invisible.
  // Strategy: if the slide root has a gradient, rasterize the gradient
  // to a PNG dataURL via canvas, set as body's background-image so
  // huashu's addBackground emits it as a full-slide picture. Solid
  // colors (or the gradient fallback if rasterization fails) go to
  // body's backgroundColor.
  function rasterizeGradientToDataURL(gradientCss, w, h) {
    try {
      const c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(w));
      c.height = Math.max(1, Math.round(h));
      const ctx = c.getContext('2d');
      // Match linear-gradient(<angle>, <stop1>, <stop2>, ...)
      const m = gradientCss.match(/linear-gradient\\((.+)\\)\\s*\$/);
      if (!m) return null;
      // Split top-level commas (paren-aware, like our walker).
      const inner = m[1];
      const parts = [];
      let depth = 0, current = '';
      for (let i = 0; i < inner.length; i++) {
        const ch = inner[i];
        if (ch === '(') depth++;
        else if (ch === ')') depth--;
        if (ch === ',' && depth === 0) { parts.push(current.trim()); current = ''; }
        else current += ch;
      }
      if (current.trim()) parts.push(current.trim());
      let angle = 180, stopStart = 0;
      if (/deg|turn|rad|to /.test(parts[0])) {
        const a = parts[0].match(/(-?\\d+(?:\\.\\d+)?)deg/);
        if (a) angle = parseFloat(a[1]);
        stopStart = 1;
      }
      const stops = [];
      const rawStops = parts.slice(stopStart);
      for (let i = 0; i < rawStops.length; i++) {
        const s = rawStops[i];
        const pctMatch = s.match(/\\s+(\\d+(?:\\.\\d+)?)%\\s*\$/);
        const color = (pctMatch ? s.slice(0, pctMatch.index) : s).trim();
        const pos = pctMatch ? parseFloat(pctMatch[1]) / 100 : i / Math.max(1, rawStops.length - 1);
        if (color) stops.push({ color: color, pos: pos });
      }
      if (!stops.length) return null;
      const rad = (angle - 90) * Math.PI / 180;
      const cx = c.width / 2, cy = c.height / 2;
      const len = Math.abs(c.width * Math.cos(rad)) + Math.abs(c.height * Math.sin(rad));
      const dx = Math.cos(rad) * len / 2;
      const dy = Math.sin(rad) * len / 2;
      const grad = ctx.createLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy);
      for (const s of stops) {
        try { grad.addColorStop(Math.max(0, Math.min(1, s.pos)), s.color); }
        catch (e) { return null; }
      }
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, c.width, c.height);
      return c.toDataURL('image/png');
    } catch (e) {
      return null;
    }
  }

  // ─── locate the slide root ─────────────────────────────────────────
  // The slide root is the outermost element standing for the whole slide.
  // Two shapes reach us:
  //
  //   * wrapperless (unpinned DS decks, no-DS decks) — body's direct child
  //     either carries the slide class or is a bare <div>. Both are resolved
  //     exactly as before, so those decks are untouched.
  //   * pinned template — the model emits the template's own structure, one
  //     or more semantic <section>/<article> levels around the div.slide
  //     body. Those wrappers carry no class and are not divs, so neither
  //     lookup below used to match and the transfer silently stopped. The
  //     OUTERMOST wrapper is the root: a pinned bundle's sole
  //     "section { ... }" rule is what paints the slide, and the .slide
  //     inside it often carries no ground of its own.
  //
  // Promotion has to agree with the backend's _promote_through_slide_wrapper()
  // (src/utils/html_utils.py), which walks outward through EVERY consecutive
  // sole-child semantic wrapper. The backend serialises the root it chose as
  // the slide's HTML, so whatever it promoted to is exactly what arrives here
  // as body's direct child. Stopping after a single level therefore left a
  // section > article > div.slide deck rootless here — exported white — while
  // the app rendered it correctly: the two surfaces disagreeing about one
  // deck, which is the whole class of bug this locator exists to prevent.
  //
  // The walk stays deliberately narrow, matching the count the backend takes
  // from find_all(recursive=False): each level must hold exactly one ELEMENT
  // child. So a wrapper holding several slides stays a container, and an
  // <h2>/<style>/<script>/SVG sibling stops the walk, while comments,
  // whitespace and text never block it. A <div> is never promoted at any
  // depth — it is neither a candidate wrapper nor a link in the chain — since
  // it would risk swallowing a deck-level container holding one slide.
  // Exactly one element is ever returned, so a wrapper and its inner .slide
  // can never both count as roots.
  const SLIDE_WRAPPER_TAGS = new Set(['SECTION', 'ARTICLE']);

  // Hard stop on the descent below. NOT the promotion cap this walk deliberately
  // does not have: Chromium caps a PARSED document's tree depth at 512 (measured
  // — a 520-wrapper chain arrives 512 deep), so the longest sole-child chain any
  // slide document can present is under 512 and the deepest that resolves is 509.
  // 4096 is eight times the browser's own ceiling: no parsed input can reach it,
  // so it cannot move where a legitimate chain resolves. It exists only for the
  // case below where the realm is lying about the tree and the walk therefore
  // isn't descending a real one.
  const WALK_STEP_LIMIT = 4096;

  // ─── reading the tree, in a realm that may be hostile ──────────────────
  // The descent's termination argument is about the DOM: each step moves to a
  // sole ELEMENT CHILD, and a parent → child chain is finite and acyclic. True of
  // the DOM — and not true of the JS realm the pass runs in.
  // Element.prototype.children / firstElementChild are CONFIGURABLE accessors, so
  // page script can replace them with ones reporting the node itself (or a fresh
  // node every read) as the sole child, and the descent then never ends.
  //
  // That is reachable, not theoretical: SLIDE_CSP (src/utils/html_safety.py)
  // carries script-src 'unsafe-inline', so inline script in a slide document runs
  // in the export page, at load, before this pass is evaluated. A malicious or
  // merely broken uploaded template could hang the export worker.
  //
  // The fix reads the tree through primitives taken from a realm no page script
  // has ever run in: a src-less iframe. Its intrinsics are separate objects from
  // this realm's, and a native DOM accessor invoked with an explicit receiver
  // works across realms, so the walk sees the real tree whatever this realm's
  // prototypes now say. (An about:blank frame is not a fetch, so
  // default-src 'none' does not block it — measured under the real SLIDE_CSP.)
  //
  // This is best-effort by nature and says so: page script runs first, so the
  // means of reaching a pristine realm are themselves replaceable. What is NOT
  // best-effort is TERMINATION — that is guaranteed by WALK_STEP_LIMIT, whatever
  // the realm does. Correct in a hostile realm where it can be; terminating
  // always.
  function capturePristineElementAccess() {
    let frame = null;
    try {
      frame = document.createElement('iframe');
      frame.style.display = 'none';
      // documentElement, not body: nothing here may perturb body's child list,
      // which the selectors in findSlideRoot() read.
      document.documentElement.appendChild(frame);
      const realm = frame.contentWindow;
      // A replaced createElement/contentWindow could hand back THIS realm, whose
      // accessors are the poisoned ones. Distinct intrinsics is the check.
      if (!realm || realm === window || realm.Element === window.Element) return null;
      const describe = realm.Object.getOwnPropertyDescriptor;
      const firstChild = describe(realm.Element.prototype, 'firstElementChild');
      const nextSibling = describe(realm.Element.prototype, 'nextElementSibling');
      const tag = describe(realm.Element.prototype, 'tagName');
      const matches = realm.Element.prototype.matches;
      if (typeof firstChild.get !== 'function' ||
          typeof nextSibling.get !== 'function' ||
          typeof tag.get !== 'function' ||
          typeof matches !== 'function') return null;
      return {
        pristine: true,
        firstElementChild: (el) => firstChild.get.call(el),
        nextElementSibling: (el) => nextSibling.get.call(el),
        tagName: (el) => tag.get.call(el),
        matches: (el, selector) => matches.call(el, selector),
      };
    } catch (e) {
      return null;
    } finally {
      // The captured accessors keep working once the frame is gone (measured), so
      // the pristine realm never outlives the capture and the export DOM never
      // contains the iframe.
      if (frame) {
        try { frame.remove(); } catch (e) { /* already detached — nothing to undo */ }
      }
    }
  }

  // Fallback when the capture above could not be trusted. Ordinary property
  // access: correct in a clean realm, subvertible in a hostile one — which is
  // what WALK_STEP_LIMIT is for.
  const OWN_ELEMENT_ACCESS = {
    pristine: false,
    firstElementChild: (el) => el.firstElementChild,
    nextElementSibling: (el) => el.nextElementSibling,
    tagName: (el) => el.tagName,
    matches: (el, selector) => el.matches(selector),
  };

  function findSlideRoot() {
    const direct = document.querySelector('body > [class*="slide"]');
    if (direct) return direct;
    const wrappers = document.querySelectorAll('body > section, body > article');
    // Captured only when there is actually a chain to walk, so the wrapperless
    // shapes (unpinned DS decks, no-DS decks) resolve exactly as before, through
    // the same two selectors and nothing else.
    const dom = wrappers.length ? (capturePristineElementAccess() || OWN_ELEMENT_ACCESS) : null;
    for (const wrapper of wrappers) {
      if (walkToSlideBody(wrapper, dom).matched) return wrapper;
    }
    return document.querySelector('body > div');
  }

  // Whether this wrapper stands for a whole slide: following its sole-element-
  // child chain down through consecutive semantic wrappers lands on the slide
  // body. Only ELEMENT children are looked at, which is what makes comments,
  // whitespace and text nodes transparent to the walk — firstElementChild with a
  // null nextElementSibling is exactly the old children.length === 1 test, read
  // through accessors that can be taken from a clean realm.
  //
  // The descent carries NO PROMOTION cap, matching the backend's unbounded
  // _promote_through_slide_wrapper(): a number there is a silent wrong-output
  // boundary, because the backend promotes past it and serialises that root as
  // body's direct child, so the deck arrives here unrecognisable and exports
  // WHITE — the same surfaces-disagree defect this locator exists to prevent,
  // just relocated to the cap. What it does carry is WALK_STEP_LIMIT, which is a
  // different thing: not a belief about how deep decks go, but a guarantee that a
  // realm lying about the tree cannot make this loop run forever. It sits eight
  // times above the depth Chromium can even parse, so no legitimate chain reaches
  // it.
  //
  // Returns the walk as data rather than a boolean: the reason it stopped is what
  // the no-root diagnostic reports, without walking anything twice.
  function walkToSlideBody(wrapper, dom) {
    let node = wrapper;
    for (let steps = 0; steps < WALK_STEP_LIMIT; steps++) {
      const child = dom.firstElementChild(node);
      if (!child) {
        return { matched: false, steps, stoppedAt: dom.tagName(node), reason: 'no element children' };
      }
      if (dom.nextElementSibling(child)) {
        return { matched: false, steps, stoppedAt: dom.tagName(node), reason: 'several element children' };
      }
      if (dom.matches(child, '[class*="slide"]')) return { matched: true, steps: steps + 1 };
      if (!SLIDE_WRAPPER_TAGS.has(dom.tagName(child))) {
        return { matched: false, steps: steps + 1, stoppedAt: dom.tagName(child), reason: 'not a promotable wrapper' };
      }
      node = child;
    }
    return { matched: false, steps: WALK_STEP_LIMIT, stoppedAt: '(unread)', reason: 'iteration limit reached' };
  }

  function transferSlideRootBackground() {
    const root = findSlideRoot();
    if (!root) return 'no-root';
    const cs = window.getComputedStyle(root);
    const bgImage = cs.backgroundImage;
    if (bgImage && bgImage !== 'none' && /gradient/.test(bgImage)) {
      // Rasterize the gradient at slide dims so the export sees a real
      // image (preserving the 135° sweep). 1280×720 is our standard.
      const dataUrl = rasterizeGradientToDataURL(bgImage, 1280, 720);
      if (dataUrl) {
        document.body.style.backgroundImage = "url('" + dataUrl + "')";
        document.body.style.backgroundSize = '100% 100%';
        document.body.style.backgroundColor = 'transparent';
        return 'gradient-raster';
      }
      // Fallback: pick first stop color.
      const m = bgImage.match(/rgba?\\([^)]+\\)|#[0-9a-fA-F]{3,8}/);
      if (m) {
        document.body.style.backgroundColor = m[0];
        return 'gradient-firststop';
      }
    }
    const bg = cs.backgroundColor;
    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
      const bodyBg = window.getComputedStyle(document.body).backgroundColor;
      if (bg !== bodyBg) {
        document.body.style.backgroundColor = bg;
        return 'solid';
      }
    }
    return 'unchanged';
  }

  // ─── Rule 4: replace background-image on divs with nested <img> ────
  // Extract the url(...) from computed background-image, build an
  // absolutely-positioned <img> at full container size, prepend it as
  // the div's first child so existing content paints on top.
  function replaceBackgroundImageWithImg() {
    const divs = document.querySelectorAll('div');
    let replaced = 0;
    divs.forEach((div) => {
      const cs = window.getComputedStyle(div);
      const bg = cs.backgroundImage;
      if (!bg || bg === 'none') return;
      // Skip CSS gradients — they're a separate rule huashu rejects.
      // Soften pass on html2pptx.js handles gradient warnings.
      if (bg.includes('gradient')) return;
      const m = bg.match(/url\\((["']?)([^"')]+)\\1\\)/);
      if (!m) return;
      const url = m[2];
      // Strip the bg from the div so huashu's validator doesn't flag it.
      div.style.backgroundImage = 'none';
      // Container must be positioned for absolute child to anchor to it.
      const pos = cs.position;
      if (pos === 'static' || !pos) div.style.position = 'relative';
      const img = document.createElement('img');
      img.src = url;
      img.style.cssText =
        'position:absolute;left:0;top:0;width:100%;height:100%;' +
        'object-fit:' + (cs.backgroundSize === 'contain' ? 'contain' : 'cover') + ';' +
        'z-index:-1;pointer-events:none;';
      div.insertBefore(img, div.firstChild);
      replaced++;
    });
    return replaced;
  }

  // ─── Rule 3: peel backgrounds off text tags ────────────────────────
  // If a <p>/<h*> has a background, border, or shadow, move those to
  // an inserted wrapper <div> so the text tag itself is plain.
  // (Common pattern: <p style="background: gold; padding: 4px;"> labels.)
  function peelBackgroundsOffTextTags() {
    const textTags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
    let peeled = 0;
    textTags.forEach((tag) => {
      document.querySelectorAll(tag).forEach((el) => {
        const cs = window.getComputedStyle(el);
        const hasBg = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent';
        const hasBorder = parseFloat(cs.borderTopWidth) > 0 ||
                          parseFloat(cs.borderRightWidth) > 0 ||
                          parseFloat(cs.borderBottomWidth) > 0 ||
                          parseFloat(cs.borderLeftWidth) > 0;
        const hasShadow = cs.boxShadow && cs.boxShadow !== 'none';
        if (!hasBg && !hasBorder && !hasShadow) return;
        // Move bg/border/shadow to a wrapper div. Inline style overrides
        // any class-based rule.
        const wrap = document.createElement('div');
        wrap.style.cssText =
          'display:inline-block;' +
          (hasBg ? 'background:' + cs.backgroundColor + ';' : '') +
          (hasBorder ? 'border:' + cs.borderTopWidth + ' ' + cs.borderTopStyle + ' ' + cs.borderTopColor + ';' : '') +
          (hasShadow ? 'box-shadow:' + cs.boxShadow + ';' : '') +
          'border-radius:' + cs.borderRadius + ';' +
          'padding:' + cs.padding + ';';
        el.parentNode.insertBefore(wrap, el);
        wrap.appendChild(el);
        // Strip the now-duplicated styles from el so huashu doesn't flag it.
        el.style.background = 'none';
        el.style.border = '0';
        el.style.boxShadow = 'none';
        el.style.padding = '0';
        peeled++;
      });
    });
    return peeled;
  }

  // ─── Tables → flat positioned divs ─────────────────────────────────
  // huashu's element walker only emits text for P/H1-6/UL/OL/LI; <td>,
  // <th> are walked but produce no records, so tables come out empty.
  // Fix: read each cell's getBoundingClientRect, build an absolutely-
  // positioned <div> at that rect with the cell's text wrapped in <p>,
  // copy borders/bg/padding/color so the visual styling survives, then
  // hide the original <table> so the walker ignores it.
  function flattenTables() {
    let cellCount = 0;
    document.querySelectorAll('table').forEach((table) => {
      const cells = table.querySelectorAll('th, td');
      if (!cells.length) return;
      const bodyRect = document.body.getBoundingClientRect();
      cells.forEach((cell) => {
        const cellRect = cell.getBoundingClientRect();
        if (cellRect.width === 0 || cellRect.height === 0) return;
        const x = cellRect.left - bodyRect.left;
        const y = cellRect.top - bodyRect.top;
        const w = cellRect.width;
        const h = cellRect.height;
        const cs = window.getComputedStyle(cell);

        const div = document.createElement('div');
        // box-sizing: border-box so explicit width/height include border + padding,
        // matching the cell's actual rendered footprint.
        const styleParts = [
          'position: absolute',
          'left: ' + x + 'px',
          'top: ' + y + 'px',
          'width: ' + w + 'px',
          'height: ' + h + 'px',
          'box-sizing: border-box',
          'padding: ' + cs.padding,
          'background: ' + cs.backgroundColor,
          'font-family: ' + cs.fontFamily,
          'font-size: ' + cs.fontSize,
          'color: ' + cs.color,
          'text-align: ' + cs.textAlign,
          // Native <td> defaults to vertical-align: middle, which centers
          // labels and badges at the row's vertical middle. Replicate
          // with flex so the wrapping <p> inside is vertically centered.
          'display: flex',
          'flex-direction: column',
          'justify-content: center',
        ];
        // Copy borders only when present (>0). Match each side individually
        // so cells with only border-bottom (huashu's data-table style) don't
        // gain spurious side borders.
        const sides = ['Top', 'Right', 'Bottom', 'Left'];
        sides.forEach((side) => {
          const w_ = cs['border' + side + 'Width'];
          if (w_ && parseFloat(w_) > 0) {
            styleParts.push(
              'border-' + side.toLowerCase() + ': ' + w_ + ' ' +
              cs['border' + side + 'Style'] + ' ' + cs['border' + side + 'Color']
            );
          }
        });
        div.style.cssText = styleParts.join('; ') + ';';

        // Wrap inner content in <p> if not already a block-level text tag.
        // Preserve nested <strong>, <span class="badge">, etc. — huashu's
        // parseInlineFormatting handles those via computed styles.
        const innerHtml = cell.innerHTML.trim();
        if (/^<(p|h[1-6]|ul|ol)\\b/i.test(innerHtml)) {
          div.innerHTML = innerHtml;
        } else {
          const p = document.createElement('p');
          p.style.margin = '0';
          p.style.padding = '0';
          p.innerHTML = innerHtml;
          div.appendChild(p);
        }
        document.body.appendChild(div);
        cellCount++;
      });
      // Hide the original — huashu's walker checks display: none and bails.
      table.style.display = 'none';
    });
    return cellCount;
  }

  // ─── Inline elements with backgrounds → standalone positioned cells
  // huashu's parseInlineFormatting reads color/bold/italic from <span>,
  // but ignores its CSS background, AND huashu emits text at the
  // wrapping <p>'s bbox (full container width), not the span's tight
  // bbox. Result: a "X Not supported" badge ends up rendered as a wide
  // colored stripe (the cell-width <p>) with text floating at the left
  // edge — pill bg and text don't agree on position.
  //
  // Fix: replace each badge inline element with a brand-new
  // absolute-positioned <div> at the span's exact bbox, containing a
  // <p> with the inner text. huashu emits this as: shape (with bg) +
  // text (positioned, sized, centered to the pill). Both at the same
  // rect → text correctly inside the pill, like the native render.
  function emitInlineBackgrounds() {
    let count = 0;
    const SELECTOR = 'span, mark, kbd';
    document.querySelectorAll(SELECTOR).forEach((el) => {
      const cs = window.getComputedStyle(el);
      const bg = cs.backgroundColor;
      if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') return;
      const elRect = el.getBoundingClientRect();
      if (elRect.width === 0 || elRect.height === 0) return;

      // Snapshot the inline's text content + computed type styles BEFORE
      // we remove it.
      const innerHtml = el.innerHTML;
      if (!innerHtml.trim()) return;

      // Find positioned ancestor (cell-div from flattenTables, or slide
      // root). Compute coords relative to its content area (subtract
      // padding+border, since absolute children anchor to padding edge).
      const wrapper = el.closest('p, h1, h2, h3, h4, h5, h6, li');
      const ancestor = (wrapper ? wrapper.parentElement : el.parentElement);
      if (!ancestor) return;

      const ancestorRect = ancestor.getBoundingClientRect();
      const acs = window.getComputedStyle(ancestor);
      const padLeft = parseFloat(acs.paddingLeft) || 0;
      const padRight = parseFloat(acs.paddingRight) || 0;
      const padTop = parseFloat(acs.paddingTop) || 0;
      const padBottom = parseFloat(acs.paddingBottom) || 0;
      const borderLeft = parseFloat(acs.borderLeftWidth) || 0;
      const borderRight = parseFloat(acs.borderRightWidth) || 0;
      const borderTop = parseFloat(acs.borderTopWidth) || 0;
      const borderBottom = parseFloat(acs.borderBottomWidth) || 0;
      // Where to place the standalone pill depends on how the ORIGINAL inline
      // element was positioned:
      //
      //   * Author-positioned (position: absolute / fixed) — e.g. a corner
      //     "eyebrow" / "cadence" tag anchored top-left / top-right of the
      //     slide. Preserve its measured position. Recentering these yanks
      //     them to the geometric middle of their (slide-sized) ancestor —
      //     the "corner pills drift to the centre on Google/PPTX export" bug.
      //
      //   * Normal flow (static / relative) — e.g. a badge inside a flattened
      //     table cell. Centre it in the ancestor's content area so it sits on
      //     the same baseline as the row label and the flex-centred plain-text
      //     cells. This is the case emitInlineBackgrounds was written for.
      const contentWidth =
        ancestorRect.width - padLeft - padRight - borderLeft - borderRight;
      const contentHeight =
        ancestorRect.height - padTop - padBottom - borderTop - borderBottom;
      const isAuthorPositioned = cs.position === 'absolute' || cs.position === 'fixed';
      let x, y;
      if (isAuthorPositioned) {
        // Offset from the ancestor's padding box (where absolute children
        // anchor) = measured position, so the pill lands exactly where the
        // author placed it. ancestor is promoted to a positioned context
        // below, so the pill resolves against it rather than a higher one.
        x = elRect.left - (ancestorRect.left + borderLeft);
        y = elRect.top - (ancestorRect.top + borderTop);
      } else {
        x = Math.max(0, (contentWidth - elRect.width) / 2);
        y = Math.max(0, (contentHeight - elRect.height) / 2);
      }

      // Build the standalone pill: a positioned <div> with the bg,
      // border-radius, and same dims as the span, containing a <p>
      // with the original inner content. The <p>'s font properties
      // are pinned inline so deck CSS rules (.badge, .takeaway-card p,
      // etc.) don't change them. text-align: center centers the text
      // within the pill horizontally, matching .badge's natural look.
      const pill = document.createElement('div');
      pill.style.cssText =
        'position: absolute;' +
        'left: ' + x + 'px;' +
        'top: ' + y + 'px;' +
        'width: ' + elRect.width + 'px;' +
        'height: ' + elRect.height + 'px;' +
        'background: ' + bg + ';' +
        'border-radius: ' + cs.borderRadius + ';' +
        'padding: ' + cs.padding + ';' +
        'box-sizing: border-box;' +
        'pointer-events: none;' +
        'display: flex; align-items: center; justify-content: center;';

      const p = document.createElement('p');
      p.style.margin = '0';
      p.style.padding = '0';
      p.style.fontSize = cs.fontSize;
      p.style.fontFamily = cs.fontFamily;
      p.style.fontWeight = cs.fontWeight;
      p.style.fontStyle = cs.fontStyle;
      p.style.color = cs.color;
      p.style.lineHeight = cs.lineHeight;
      p.style.letterSpacing = cs.letterSpacing;
      p.style.textAlign = 'center';
      p.style.whiteSpace = 'nowrap';
      p.innerHTML = innerHtml;
      pill.appendChild(p);

      // Promote ancestor to positioned context.
      const ap = window.getComputedStyle(ancestor).position;
      if (ap === 'static' || !ap) ancestor.style.position = 'relative';

      // Insert before the wrapping <p> so paint order is ancestor →
      // pill (with text). Then remove the original span so huashu's
      // <p> walker (the wrapping <p>) doesn't double-emit the text at
      // the wrong (full-width) position.
      const insertRef = wrapper && wrapper.parentElement === ancestor
        ? wrapper
        : ancestor.firstChild;
      ancestor.insertBefore(pill, insertRef);
      el.remove();
      count++;
    });
    return count;
  }

  // ─── Canvas → embedded image ───────────────────────────────────────
  // huashu has no canvas handler; charts come out as empty whitespace.
  // Convert each <canvas> to an <img src="dataURL"> at the same rect, so
  // huashu's <img> emit path picks it up. Tainted canvases (cross-origin
  // upstream images) throw on toDataURL — skip those silently.
  function rasterizeCanvases() {
    let count = 0;
    document.querySelectorAll('canvas').forEach((canvas) => {
      try {
        // Skip canvases that are still 0×0 (chart never initialized).
        if (!canvas.width || !canvas.height) return;
        const dataUrl = canvas.toDataURL('image/png');
        // Bail if the data URL is the empty-canvas signature (no chart
        // rendered yet — better to leave it absent than embed a blank).
        if (dataUrl.length < 200) return;
        const rect = canvas.getBoundingClientRect();
        const img = document.createElement('img');
        img.src = dataUrl;
        img.style.cssText =
          'display: block;' +
          'width: ' + rect.width + 'px;' +
          'height: ' + rect.height + 'px;';
        canvas.parentNode.insertBefore(img, canvas);
        canvas.style.display = 'none';
        count++;
      } catch (e) {
        // Tainted canvas — give up
      }
    });
    return count;
  }

  // ─── SVG data-URI <img> → rasterized PNG ───────────────────────────
  // pptxgenjs in Node writes data:image/svg+xml images with a hardcoded
  // broken-image placeholder PNG as the primary <a:blip>; the real vector
  // survives only in the <asvg:svgBlip> extension, which PowerPoint reads
  // but Google Slides' Drive conversion and LibreOffice ignore. This page
  // already rendered the SVG, so draw it to a canvas at 2x the layout box
  // (crispness) and swap the src to a PNG data URI. The decode() await
  // covers the <img>s replaceBackgroundImageWithImg minted moments ago —
  // those may not have finished loading. Per-image try/catch: an
  // undecodable SVG keeps its raw src, which is exactly the pre-existing
  // pipeline behavior.
  // Destination rect for drawing a srcW x srcH image into a w x h canvas
  // WITHOUT distorting it: scale by the smaller axis ratio and center the
  // result (letterbox, i.e. CSS object-fit: contain). The stretch-fill this
  // replaces baked distortion into the PNG whenever the layout box's aspect
  // ratio differed from the artwork's — the reported symptom was a footer
  // logo box flex-stretched to the full row width, which smeared a 3:1 logo
  // across ~14:1. A ratio-true box (slide 1's logo) is unaffected: the
  // computed scale is then identical on both axes and the offsets are 0.
  function containFitRect(srcW, srcH, w, h) {
    if (!srcW || !srcH) return { dx: 0, dy: 0, dw: w, dh: h };
    const scale = Math.min(w / srcW, h / srcH);
    const dw = srcW * scale;
    const dh = srcH * scale;
    return { dx: (w - dw) / 2, dy: (h - dh) / 2, dw: dw, dh: dh };
  }

  // Source rect for object-fit: cover — fill the destination box by
  // CROPPING the overflowing axis, centered — never by stretching (a
  // background minted with background-size:cover carries this intent).
  function coverFitSourceRect(srcW, srcH, w, h) {
    if (!srcW || !srcH) return { sx: 0, sy: 0, sw: srcW, sh: srcH };
    const scale = Math.max(w / srcW, h / srcH);
    const sw = Math.min(srcW, w / scale);
    const sh = Math.min(srcH, h / scale);
    return { sx: (srcW - sw) / 2, sy: (srcH - sh) / 2, sw: sw, sh: sh };
  }

  async function rasterizeSvgDataUriImages() {
    let count = 0;
    const imgs = Array.from(document.querySelectorAll('img')).filter((img) =>
      /^data:image\\/svg\\+xml/i.test(img.src || '')
    );
    for (const img of imgs) {
      try {
        await img.decode();
        const rect = img.getBoundingClientRect();
        const w = Math.max(1, Math.round((rect.width || img.naturalWidth || 1) * 2));
        const h = Math.max(1, Math.round((rect.height || img.naturalHeight || 1) * 2));
        const c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        const ctx = c.getContext('2d');
        // Honour the image's own fit intent, but NEVER by stretching:
        // cover fills the box by center-cropping the overflowing axis,
        // anything else letterboxes. The canvas keeps the BOX size so
        // downstream placement is unchanged — only the drawn geometry inside
        // it is corrected. replaceBackgroundImageWithImg mints its
        // <img>s with an explicit object-fit, so a background-size:cover
        // layer still fills its box.
        const objectFit = window.getComputedStyle(img).objectFit;
        if (objectFit === 'cover') {
          const src = coverFitSourceRect(img.naturalWidth, img.naturalHeight, w, h);
          ctx.drawImage(img, src.sx, src.sy, src.sw, src.sh, 0, 0, w, h);
        } else {
          const fit = containFitRect(img.naturalWidth, img.naturalHeight, w, h);
          ctx.drawImage(img, fit.dx, fit.dy, fit.dw, fit.dh);
        }
        const dataUrl = c.toDataURL('image/png');
        // Pin the rendered size before the swap: an <img> sized by its
        // intrinsic dimensions would otherwise reflow when the 2x PNG
        // lands. Same-value inline px for explicitly-sized images.
        if (rect.width && rect.height) {
          img.style.width = rect.width + 'px';
          img.style.height = rect.height + 'px';
        }
        img.src = dataUrl;
        count++;
      } catch (e) {
        // decode/raster failed — keep the raw SVG src (pre-existing behavior)
      }
    }
    return count;
  }

  // ─── Inline <svg> → rasterized PNG <img> ───────────────────────────
  // huashu's walker has no svg handler: inline icons produce nothing, and
  // (pre-guard) the walker's string-assumed el.className even threw on
  // SVGAnimatedString, dropping the whole slide. Serialize each top-level
  // inline <svg>, decode it as an image, draw to a canvas at 2x the layout
  // box (crispness), and swap in a same-size PNG <img> at the svg's DOM
  // position so paint order and flow layout are preserved. Per-svg
  // try/catch: a failed raster leaves the svg in place — the walker now
  // ignores it (className guard), so the slide exports without the icon
  // instead of vanishing.
  async function rasterizeInlineSvgs() {
    let count = 0;
    const svgs = Array.from(document.querySelectorAll('svg')).filter(
      (svg) => !(svg.parentElement && svg.parentElement.closest('svg'))
    );
    for (const svg of svgs) {
      try {
        const cs = window.getComputedStyle(svg);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;

        const clone = svg.cloneNode(true);
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        // CSS-sized svgs serialize without intrinsic dimensions; pin the
        // rendered box so the standalone document decodes at a real size.
        clone.setAttribute('width', String(rect.width));
        clone.setAttribute('height', String(rect.height));
        // currentColor resolves against the element's own color in the
        // standalone doc — pin the computed inherited color.
        clone.style.color = cs.color;
        const xml = new XMLSerializer().serializeToString(clone);
        const probe = new Image();
        probe.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
        await probe.decode();

        const w = Math.max(1, Math.round(rect.width * 2));
        const h = Math.max(1, Math.round(rect.height * 2));
        const c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        c.getContext('2d').drawImage(probe, 0, 0, w, h);
        const dataUrl = c.toDataURL('image/png');

        const img = document.createElement('img');
        img.src = dataUrl;
        // Occupy the svg's exact slot: same box for in-flow svgs, same
        // resolved offsets for positioned ones, so neither siblings nor
        // the svg's own paint position move.
        img.style.display = 'block';
        img.style.width = rect.width + 'px';
        img.style.height = rect.height + 'px';
        img.style.margin = cs.margin;
        if (cs.position === 'absolute' || cs.position === 'fixed') {
          img.style.position = cs.position;
          img.style.left = cs.left;
          img.style.top = cs.top;
          if (cs.transform && cs.transform !== 'none') img.style.transform = cs.transform;
        }
        svg.parentNode.insertBefore(img, svg);
        svg.style.display = 'none';
        count++;
      } catch (e) {
        console.warn('[preprocess] inline svg raster failed — exporting slide without it: ' + (e && e.message));
      }
    }
    return count;
  }

  // ─── orchestrator ──────────────────────────────────────────────────
  // Order matters: bg transfer first (cheap, mutates body only); flatten
  // code blocks BEFORE wrapBareTextInDivs (so the per-line <div>s become
  // a single <p> with <br>s before the inline-content wrapper sees them);
  // SVG raster right after replaceBackgroundImageWithImg so it covers the
  // <img>s that pass just minted from CSS backgrounds; other structural
  // mutations next; canvas raster + inline-bg LAST so they read final
  // post-mutation positions.
  const bgTransferred = transferSlideRootBackground();
  const codeBlocks = flattenMonospaceCodeBlocks();
  const wrapped = wrapBareTextInDivs();
  const replacedImgs = replaceBackgroundImageWithImg();
  const svgImgsRasterized = await rasterizeSvgDataUriImages();
  const inlineSvgsRasterized = await rasterizeInlineSvgs();
  const peeledTextTags = peelBackgroundsOffTextTags();
  const tableCells = flattenTables();
  const canvasImgs = rasterizeCanvases();
  const inlineBgs = emitInlineBackgrounds();
  return { bgTransferred, codeBlocks, wrapped, replacedImgs, svgImgsRasterized, inlineSvgsRasterized, peeledTextTags, tableCells, canvasImgs, inlineBgs };
})();
`;
