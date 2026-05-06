/**
 * Client-side DOM walker for the editable PPTX exporter.
 *
 * Wholesale adopted from the reference scaffold (walker.js) that Claude Design
 * published. Runs inside a hidden iframe that renders the composite slide deck;
 * for each slide we call __extractSlide(slideRoot) which returns
 *   { width, height, records: [rect|image|text] }
 * in paint order (pre-order DOM walk). These are POSTed to the backend, which
 * spawns a Node subprocess (services/pptx-emit/emit.bundle.mjs) using pptxgenjs.
 *
 * Why this architecture: Databricks Apps containers have no Chromium (non-root
 * + memory-constrained). The user's browser already rendered the deck.
 */

import type { SlideDeck } from '../types/slide';

/** Font strategy for the editable export. */
export type EditableFontMode =
  | 'custom'
  | 'universal'
  | 'google_slides';

export interface RunRecord {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  color: string;
  size: number;
  family: string;
  breakLine?: boolean;
}
export interface ShadowSpec {
  type: 'outer';
  angle: number;
  blur: number;
  color: string;
  offset: number;
  opacity: number;
}
export interface RectRecord {
  kind: 'rect';
  x: number; y: number; w: number; h: number;
  fill: string | null;
  stroke?: string | null;
  strokeW?: number;
  radius?: number;
  shadow?: ShadowSpec;
  _depth?: number;
}
export interface ImageRecord {
  kind: 'image';
  x: number; y: number; w: number; h: number;
  src: string;
  rotate?: number;
  _depth?: number;
}
export interface TextRecord {
  kind: 'text';
  x: number; y: number; w: number; h: number;
  runs: RunRecord[];
  align: string;
  valign: string;
  rotate?: number;
  _depth?: number;
}
export type SlideRecord = RectRecord | ImageRecord | TextRecord;

export interface SlideExtract {
  width: number;
  height: number;
  records: SlideRecord[];
  notes: string;
}

const DESIGN_W = 1280;
const DESIGN_H = 720;
const SLIDE_SETTLE_MS = 400;

function buildCompositeHtml(deck: SlideDeck): string {
  const slides = deck.slides || [];
  const sections = slides.map((s, i) => {
    const hidden = i === 0 ? '' : ' style="display:none"';
    const scripts = s.scripts
      ? `<script>try{${s.scripts}}catch(e){console.debug(e)}</script>`
      : '';
    return `<section class="slide-container" data-slide-index="${i}"${hidden}>${s.html || ''}${scripts}</section>`;
  }).join('\n');

  const ext = (deck.external_scripts || []).map(src => `<script src="${src}"></script>`).join('\n');
  const notes = JSON.stringify(
    slides.map((s: any) => (s.speaker_notes || s.notes || ''))
  );

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>${deck.title || 'Presentation'}</title>
${ext}
<style>
html, body { margin: 0; padding: 0; }
html { width: ${DESIGN_W}px; height: ${DESIGN_H}px; }
section.slide-container { width: ${DESIGN_W}px; height: ${DESIGN_H}px; position: relative; overflow: hidden; }
/* Authored decks often wrap each slide in an inner <div class="slide">
   styled like a print-preview card (margin: 40px auto; border-radius: 12px;
   box-shadow: ...). That 40px margin shifts every absolutely-positioned
   descendant out past the 720px clip rect. Neutralize. */
section.slide-container > .slide, section.slide-container .slide {
  margin: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
}
${deck.css || ''}
</style>
</head>
<body>
${sections}
<script id="speaker-notes" type="application/json">${notes}</script>
<script>try{${deck.scripts || ''}}catch(e){console.debug(e)}</script>
</body>
</html>`;
}

/**
 * Walker JS — stringified for iframe injection. Ported verbatim from the
 * scaffold reference (walker.js), with the font-mode override pass added so
 * iframe measurements reflect the fallback font's metrics when font_mode is
 * "universal".
 */
const WALKER_SOURCE = `
(function () {
  const PX_PER_IN = 96;

  function parseColor(str) {
    if (!str || str === 'transparent' || str === 'rgba(0, 0, 0, 0)') return null;
    const m = str.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const parts = m[1].split(',').map(s => parseFloat(s.trim()));
    const r = parts[0], g = parts[1], b = parts[2], a = parts[3];
    if (a === 0) return null;
    const hex = [r, g, b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();
    return { hex, alpha: a === undefined ? 1 : a };
  }

  function parseRadius(cs) {
    const rs = ['borderTopLeftRadius', 'borderTopRightRadius',
                'borderBottomLeftRadius', 'borderBottomRightRadius']
      .map(k => parseFloat(cs[k]) || 0);
    return Math.max.apply(null, rs);
  }

  // ─── cherry-picks from huashu-design's html2pptx.js ─────────────────
  // CSS text-transform → applied to text content before emission so PPT
  // shows what the browser shows (not what node.textContent returns).
  function applyTextTransform(text, transform) {
    if (!transform || transform === 'none') return text;
    if (transform === 'uppercase') return text.toUpperCase();
    if (transform === 'lowercase') return text.toLowerCase();
    if (transform === 'capitalize') {
      return text.replace(/\\b\\w/g, function (c) { return c.toUpperCase(); });
    }
    return text;
  }

  // Read CSS transform + writing-mode → degrees (0–359) or null.
  // Handles both "rotate(45deg)" and matrix() forms (browser sometimes
  // canonicalizes rotate into matrix). writing-mode: vertical-rl maps to
  // 90deg, vertical-lr to 270deg.
  function getRotation(transform, writingMode) {
    var angle = 0;
    if (writingMode === 'vertical-rl') angle = 90;
    else if (writingMode === 'vertical-lr') angle = 270;
    if (transform && transform !== 'none') {
      var rotateMatch = transform.match(/rotate\\((-?\\d+(?:\\.\\d+)?)deg\\)/);
      if (rotateMatch) {
        angle += parseFloat(rotateMatch[1]);
      } else {
        var matrixMatch = transform.match(/matrix\\(([^)]+)\\)/);
        if (matrixMatch) {
          var values = matrixMatch[1].split(',').map(parseFloat);
          var matrixAngle = Math.atan2(values[1], values[0]) * (180 / Math.PI);
          angle += Math.round(matrixAngle);
        }
      }
    }
    angle = angle % 360;
    if (angle < 0) angle += 360;
    return angle === 0 ? null : angle;
  }

  // Browser getBoundingClientRect on a rotated element returns the
  // axis-aligned bounding box of the rotated content. PowerPoint expects
  // the un-rotated box + a rotation angle (rotated about its center).
  // For 90/270 we can recover unrotated dims by swap; for arbitrary
  // angles we use offsetWidth/Height (always the unrotated CSS dims).
  function getRotatedBox(el, box, rotation) {
    if (rotation === null) return box;
    if (rotation === 90 || rotation === 270) {
      var cx = box.x + box.w / 2;
      var cy = box.y + box.h / 2;
      return { x: cx - box.h / 2, y: cy - box.w / 2, w: box.h, h: box.w };
    }
    var cx2 = box.x + box.w / 2;
    var cy2 = box.y + box.h / 2;
    return {
      x: cx2 - el.offsetWidth / 2,
      y: cy2 - el.offsetHeight / 2,
      w: el.offsetWidth,
      h: el.offsetHeight,
    };
  }

  // CSS box-shadow → pptxgenjs shadow option. Inset shadows skipped
  // (corrupt the PPTX file when round-tripped). Computed-style format:
  //   "rgba(0,0,0,0.3) 2px 2px 8px 0px"
  function parseBoxShadow(boxShadow) {
    if (!boxShadow || boxShadow === 'none') return null;
    if (/inset/.test(boxShadow)) return null;
    var colorMatch = boxShadow.match(/rgba?\\([^)]+\\)/);
    var parts = boxShadow.match(/(-?[\\d.]+)(?:px|pt)/g);
    if (!parts || parts.length < 2) return null;
    var offsetX = parseFloat(parts[0]);
    var offsetY = parseFloat(parts[1]);
    var blur = parts.length > 2 ? parseFloat(parts[2]) : 0;
    var angle = 0;
    if (offsetX !== 0 || offsetY !== 0) {
      angle = Math.atan2(offsetY, offsetX) * (180 / Math.PI);
      if (angle < 0) angle += 360;
    }
    var offset = Math.sqrt(offsetX * offsetX + offsetY * offsetY) * 0.75;  // px → pt
    var opacity = 0.5;
    var colorHex = '000000';
    if (colorMatch) {
      var c = parseColor(colorMatch[0]);
      if (c) { colorHex = c.hex; opacity = c.alpha; }
    }
    return {
      type: 'outer',
      angle: Math.round(angle),
      blur: blur * 0.75,
      color: colorHex,
      offset: offset,
      opacity: opacity,
    };
  }

  function isVisible(el, cs) {
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function hasVisualFill(cs) {
    return (
      parseColor(cs.backgroundColor) !== null ||
      cs.backgroundImage !== 'none' ||
      parseFloat(cs.borderTopWidth) > 0 ||
      parseFloat(cs.borderRightWidth) > 0 ||
      parseFloat(cs.borderBottomWidth) > 0 ||
      parseFloat(cs.borderLeftWidth) > 0
    );
  }

  // ─── gradient rasterization ─────────────────────────────────────────
  // Best-effort: parses only the simplest linear-gradient() form, wraps
  // everything in try/catch so a failure never kills record collection.
  // Caller falls back to the solid first-stop rect.
  function rasterizeGradientBackground(el, cs) {
    try {
      const r = el.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width));
      const h = Math.max(1, Math.round(r.height));
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d');
      const bg = cs.backgroundImage;
      const m = bg.match(/linear-gradient\\((.+)\\)\\s*\$/);
      if (!m) return null;
      const inner = m[1];
      // Split on commas NOT inside parens. Tracks paren depth manually
      // instead of relying on a subtle lookahead regex — more robust
      // for computed styles like "rgb(16, 32, 37) 0%, rgb(26, 58, 68) 50%".
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
        // Pull off trailing "<num>%" if present; everything before it is the color.
        const pctMatch = s.match(/\\s+(\\d+(?:\\.\\d+)?)%\\s*\$/);
        const color = (pctMatch ? s.slice(0, pctMatch.index) : s).trim();
        const pos = pctMatch ? parseFloat(pctMatch[1]) / 100 : i / Math.max(1, rawStops.length - 1);
        if (color) stops.push({ color: color, pos: pos });
      }
      if (!stops.length) return null;
      const rad = (angle - 90) * Math.PI / 180;
      const cx = w / 2, cy = h / 2;
      const len = Math.abs(w * Math.cos(rad)) + Math.abs(h * Math.sin(rad));
      const dx = Math.cos(rad) * len / 2;
      const dy = Math.sin(rad) * len / 2;
      const grad = ctx.createLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy);
      for (const s of stops) {
        try { grad.addColorStop(Math.max(0, Math.min(1, s.pos)), s.color); }
        catch (e) { return null; }  // invalid color → abort, let caller use solid
      }
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      return c.toDataURL('image/png');
    } catch (e) {
      return null;
    }
  }

  // ─── text-run extraction ────────────────────────────────────────────
  function runStyle(cs) {
    const color = parseColor(cs.color);
    return {
      family: (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim(),
      size: parseFloat(cs.fontSize),
      bold: parseInt(cs.fontWeight, 10) >= 600,
      italic: cs.fontStyle === 'italic',
      color: color ? color.hex : '000000',
      underline: !!(cs.textDecorationLine && cs.textDecorationLine.includes('underline')),
    };
  }
  function sameStyle(a, b) {
    if (!a || !b) return false;
    return a.family === b.family && a.size === b.size && a.bold === b.bold &&
           a.italic === b.italic && a.color === b.color && a.underline === b.underline;
  }
  function extractRuns(rootEl) {
    const runs = [];
    const rootCs = getComputedStyle(rootEl);
    const parentStyle = runStyle(rootCs);
    const rootTransform = rootCs.textTransform || 'none';
    let current = Object.assign({ text: '' }, parentStyle);
    const flush = () => {
      if (current.text.length > 0) runs.push(Object.assign({}, current));
      current = Object.assign({ text: '' }, parentStyle);
    };
    function walk(node, inherited, textTransform) {
      for (const child of node.childNodes) {
        if (child.nodeType === 3 /* TEXT_NODE */) {
          var t = child.nodeValue.replace(/\\s+/g, ' ');
          if (!t) continue;
          t = applyTextTransform(t, textTransform);
          if (!sameStyle(current, inherited)) {
            flush();
            current = Object.assign({ text: '' }, inherited);
          }
          current.text += t;
        } else if (child.nodeType === 1 /* ELEMENT_NODE */) {
          if (child.tagName === 'BR') {
            flush();
            runs.push(Object.assign({ text: '', breakLine: true }, inherited));
            continue;
          }
          const cs = getComputedStyle(child);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          const childStyle = runStyle(cs);
          const childTransform = (cs.textTransform && cs.textTransform !== 'none')
            ? cs.textTransform : textTransform;
          const isBlock = cs.display.indexOf('block') === 0 || cs.display === 'flex' || cs.display === 'grid';
          if (isBlock && current.text) {
            flush();
            runs.push(Object.assign({ text: '', breakLine: true }, inherited));
          }
          walk(child, childStyle, childTransform);
          if (isBlock) {
            flush();
            runs.push(Object.assign({ text: '', breakLine: true }, inherited));
          }
        }
      }
    }
    walk(rootEl, parentStyle, rootTransform);
    flush();
    while (runs.length && runs[runs.length - 1].breakLine && !runs[runs.length - 1].text) {
      runs.pop();
    }
    return runs;
  }

  function isTextLeaf(el) {
    if (!el.textContent || !el.textContent.trim()) return false;
    for (const child of el.children) {
      const cs = getComputedStyle(child);
      const d = cs.display;
      const inline = d === 'inline' || d === 'inline-block' || d === 'inline-flex';
      if (!inline) return false;
    }
    return true;
  }

  // ─── main walker ────────────────────────────────────────────────────
  function walk(root) {
    const rootRect = root.getBoundingClientRect();
    const records = [];
    function rel(r) {
      return { x: r.left - rootRect.left, y: r.top - rootRect.top, w: r.width, h: r.height };
    }
    function visit(el, depth) {
      const cs = getComputedStyle(el);
      if (!isVisible(el, cs)) return;
      const box = rel(el.getBoundingClientRect());
      // Rotation is intentionally NOT applied to non-leaf rects — children
      // are already in post-transform browser coords, so rotating a parent
      // container would diverge from its (axis-aligned-in-PPT) children.
      // We apply rotation only to text leaves, <img>, and <canvas>.
      const rotation = getRotation(cs.transform, cs.writingMode);
      const shadow = parseBoxShadow(cs.boxShadow);

      // 1. Background fill (rect + optional rasterized gradient overlay).
      if (hasVisualFill(cs) && box.w > 0 && box.h > 0) {
        const hasGradient = cs.backgroundImage !== 'none' && cs.backgroundImage.indexOf('gradient') !== -1;
        // Always try the solid/first-stop fill path first so shape
        // outline + geometry is present even if gradient rasterization
        // fails. Gradient rasterization is best-effort overlay.
        let fill = parseColor(cs.backgroundColor);
        if (!fill && hasGradient) {
          // extract first stop color from gradient for solid fallback
          try {
            const m = cs.backgroundImage.match(/linear-gradient\\(([^)]+(?:\\([^)]*\\)[^)]*)*)\\)/);
            if (m) {
              const inner = m[1];
              const colorMatch = inner.match(/rgba?\\([^)]+\\)|#[0-9a-fA-F]{3,8}/);
              if (colorMatch) fill = parseColor(colorMatch[0]);
            }
          } catch (e) { /* swallow */ }
        }
        const borderColor = parseColor(cs.borderTopColor);
        const borderW = parseFloat(cs.borderTopWidth) || 0;
        if (fill || borderW > 0) {
          const rect = {
            kind: 'rect',
            x: box.x, y: box.y, w: box.w, h: box.h,
            fill: fill ? fill.hex : null,
            stroke: borderW > 0 && borderColor ? borderColor.hex : null,
            strokeW: borderW,
            radius: parseRadius(cs),
            _depth: depth,
          };
          if (shadow) rect.shadow = shadow;
          records.push(rect);
        }
        // Optional gradient raster overlay on top (so gradient visuals
        // retain their full color range). If canvas rasterization fails
        // we still have the solid fill below.
        // Only rasterize "real" gradient elements — skip thin decorative
        // strips (height < 8px) which produce noisy rainbow-bar
        // artifacts at the bottom of every slide from Tellr's theme.
        // The solid first-stop rect emitted above already handles these.
        if (hasGradient && box.h >= 8 && box.w >= 8) {
          try {
            const dataUrl = rasterizeGradientBackground(el, cs);
            if (dataUrl) {
              records.push(Object.assign({ kind: 'image' }, box, { src: dataUrl, _depth: depth + 0.5 }));
            }
          } catch (e) {
            console.warn('[walker] gradient raster failed, using solid fallback:', e.message);
          }
        }
      }

      // 2. Text leaf (children all inline): extract runs, stop descending.
      if (isTextLeaf(el)) {
        const runs = extractRuns(el);
        if (runs.some(r => r.text)) {
          const tbox = rotation !== null ? getRotatedBox(el, box, rotation) : box;
          const rec = {
            kind: 'text',
            x: tbox.x, y: tbox.y, w: tbox.w, h: tbox.h,
            runs: runs,
            align: cs.textAlign === 'start' ? 'left' : cs.textAlign,
            valign: 'top',
            _depth: depth,
          };
          if (rotation !== null) rec.rotate = rotation;
          records.push(rec);
        }
        return;
      }

      // 3. <img>.
      if (el.tagName === 'IMG' && el.src) {
        const ibox = rotation !== null ? getRotatedBox(el, box, rotation) : box;
        const rec = Object.assign({ kind: 'image' }, ibox, {
          src: el.currentSrc || el.src,
          _depth: depth,
        });
        if (rotation !== null) rec.rotate = rotation;
        records.push(rec);
        return;
      }

      // 4. <canvas> → rasterize.
      if (el.tagName === 'CANVAS') {
        try {
          const cbox = rotation !== null ? getRotatedBox(el, box, rotation) : box;
          const rec = Object.assign({ kind: 'image' }, cbox, {
            src: el.toDataURL('image/png'),
            _depth: depth,
          });
          if (rotation !== null) rec.rotate = rotation;
          records.push(rec);
        } catch (e) { /* tainted canvas */ }
        return;
      }

      // 5. Recurse (paint order = pre-order).
      for (const child of el.children) visit(child, depth + 1);
    }
    visit(root, 0);
    return { width: rootRect.width, height: rootRect.height, records: records };
  }

  window.__extractSlide = walk;
})();
`;

/**
 * Huashu-style DOM mutation pass. Ported from
 * `services/pptx-emit-huashu/preprocess.mjs` (which runs server-side under
 * Playwright in the local-only huashu pipeline). Running these mutations
 * client-side, scoped to the visible slide root, makes our existing walker
 * produce the same fidelity (tables flattened, badge pills centered, code
 * panels collapsed to one text frame, gradient bg picked up by hasVisualFill,
 * etc.) without requiring Chromium server-side. That's why this works on
 * Databricks Apps where the original huashu pipeline can't run.
 *
 * Exposes window.__huashuPreprocess(slideRoot). Called per-slide in
 * extractSlideRecordsForExport before window.__extractSlide(slideRoot).
 */
const PREPROCESS_SOURCE = `
(function () {
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

  // ─── Monospace code blocks → single multi-line text frame ──────────
  function flattenMonospaceCodeBlocks(root) {
    let count = 0;
    root.querySelectorAll('div').forEach((panel) => {
      const cs = window.getComputedStyle(panel);
      const fam = (cs.fontFamily || '').toLowerCase();
      const isMono = /\\bmono(space)?\\b|courier|consolas|menlo|monaco/i.test(fam);
      if (!isMono) return;
      const childDivs = Array.from(panel.children).filter((c) => c.tagName === 'DIV');
      if (childDivs.length < 2) return;
      const fragment = document.createDocumentFragment();
      Array.from(panel.childNodes).forEach((child) => {
        if (child.nodeType === 1 && child.tagName === 'DIV') {
          // Replace leading regular spaces in the FIRST text-node with NBSP
          // so emit.mjs's whitespace-collapse doesn't eat the indent.
          const inlineChildren = Array.from(child.childNodes);
          for (let i = 0; i < inlineChildren.length; i++) {
            const n = inlineChildren[i];
            if (n.nodeType === 3 /* TEXT_NODE */) {
              const t = n.textContent;
              const m = t.match(/^( +)/);
              if (m) {
                n.textContent = '\\u00A0'.repeat(m[1].length) + t.slice(m[1].length);
              }
            }
            fragment.appendChild(n);
          }
          fragment.appendChild(document.createElement('br'));
        } else if (child.nodeType === 1 && child.tagName === 'BR') {
          // Explicit <br> in source = blank-line separator. Emit NBSP+<br>
          // so back-to-back paragraph breaks don't collapse to one.
          fragment.appendChild(document.createTextNode('\\u00A0'));
          fragment.appendChild(document.createElement('br'));
        } else if (child.nodeType === 3 /* TEXT_NODE */ && !child.textContent.trim()) {
          // skip whitespace-only text nodes between block siblings
        } else {
          fragment.appendChild(child.cloneNode(true));
        }
      });
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
      p.style.whiteSpace = 'normal';
      p.appendChild(fragment);
      panel.appendChild(p);
      count++;
    });
    return count;
  }

  // ─── Wrap inline content in <p> with pinned font (preserves emoji/font size) ───
  function wrapInlineRunsIn(parent) {
    let count = 0;
    const children = Array.from(parent.childNodes);
    let i = 0;
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
      Object.assign(p.style, inheritedFont);
      parent.insertBefore(p, run[0]);
      run.forEach((n) => p.appendChild(n));
      count++;
    }
    return count;
  }
  function wrapBareTextInDivs(root) {
    let wrapped = 0;
    root.querySelectorAll('div, pre, code').forEach((parent) => {
      wrapped += wrapInlineRunsIn(parent);
    });
    return wrapped;
  }

  // ─── Replace bg-image divs with nested <img> so the bitmap survives ──
  function replaceBackgroundImageWithImg(root) {
    let replaced = 0;
    root.querySelectorAll('div').forEach((div) => {
      const cs = window.getComputedStyle(div);
      const bg = cs.backgroundImage;
      if (!bg || bg === 'none') return;
      if (bg.includes('gradient')) return;  // walker rasterizes gradients itself
      const m = bg.match(/url\\((["']?)([^"')]+)\\1\\)/);
      if (!m) return;
      const url = m[2];
      div.style.backgroundImage = 'none';
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

  // ─── Peel bg/border/shadow off text tags onto a wrapper div ─────────
  function peelBackgroundsOffTextTags(root) {
    const textTags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
    let peeled = 0;
    textTags.forEach((tag) => {
      root.querySelectorAll(tag).forEach((el) => {
        const cs = window.getComputedStyle(el);
        const hasBg = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent';
        const hasBorder = parseFloat(cs.borderTopWidth) > 0 ||
                          parseFloat(cs.borderRightWidth) > 0 ||
                          parseFloat(cs.borderBottomWidth) > 0 ||
                          parseFloat(cs.borderLeftWidth) > 0;
        const hasShadow = cs.boxShadow && cs.boxShadow !== 'none';
        if (!hasBg && !hasBorder && !hasShadow) return;
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
        el.style.background = 'none';
        el.style.border = '0';
        el.style.boxShadow = 'none';
        el.style.padding = '0';
        peeled++;
      });
    });
    return peeled;
  }

  // ─── Tables → flat positioned cell-divs anchored to slide root ──────
  function flattenTables(root) {
    let cellCount = 0;
    const rootRect = root.getBoundingClientRect();
    root.querySelectorAll('table').forEach((table) => {
      const cells = table.querySelectorAll('th, td');
      if (!cells.length) return;
      cells.forEach((cell) => {
        const cellRect = cell.getBoundingClientRect();
        if (cellRect.width === 0 || cellRect.height === 0) return;
        const x = cellRect.left - rootRect.left;
        const y = cellRect.top - rootRect.top;
        const w = cellRect.width;
        const h = cellRect.height;
        const cs = window.getComputedStyle(cell);

        const div = document.createElement('div');
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
          'display: flex',
          'flex-direction: column',
          'justify-content: center',
        ];
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
        // Append to the SLIDE ROOT (section), not document.body — that way
        // our walker reaches the cell-div via root.children traversal.
        root.appendChild(div);
        cellCount++;
      });
      table.style.display = 'none';
    });
    return cellCount;
  }

  // ─── Inline elements with bg → standalone positioned pill divs ──────
  function emitInlineBackgrounds(root) {
    let count = 0;
    const SELECTOR = 'span, mark, kbd';
    root.querySelectorAll(SELECTOR).forEach((el) => {
      const cs = window.getComputedStyle(el);
      const bg = cs.backgroundColor;
      if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') return;
      const elRect = el.getBoundingClientRect();
      if (elRect.width === 0 || elRect.height === 0) return;
      const innerHtml = el.innerHTML;
      if (!innerHtml.trim()) return;

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
      const contentWidth =
        ancestorRect.width - padLeft - padRight - borderLeft - borderRight;
      const contentHeight =
        ancestorRect.height - padTop - padBottom - borderTop - borderBottom;
      const x = Math.max(0, (contentWidth - elRect.width) / 2);
      const y = Math.max(0, (contentHeight - elRect.height) / 2);

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

      const ap = window.getComputedStyle(ancestor).position;
      if (ap === 'static' || !ap) ancestor.style.position = 'relative';

      const insertRef = wrapper && wrapper.parentElement === ancestor
        ? wrapper
        : ancestor.firstChild;
      ancestor.insertBefore(pill, insertRef);
      el.remove();
      count++;
    });
    return count;
  }

  // ─── Orchestrator: scoped to slide section root ─────────────────────
  function preprocessSlide(root) {
    if (!root) return null;
    const codeBlocks = flattenMonospaceCodeBlocks(root);
    const wrapped = wrapBareTextInDivs(root);
    const replacedImgs = replaceBackgroundImageWithImg(root);
    const peeledTextTags = peelBackgroundsOffTextTags(root);
    const tableCells = flattenTables(root);
    const inlineBgs = emitInlineBackgrounds(root);
    return { codeBlocks, wrapped, replacedImgs, peeledTextTags, tableCells, inlineBgs };
  }

  window.__huashuPreprocess = preprocessSlide;
})();
`;

/**
 * Apply font substitution to every element in the iframe before measurement.
 * Inline style beats system-installed brand fonts unconditionally, so the
 * walker measures against the fallback (Arial/Consolas) that pptxgenjs will
 * emit — long titles don't wrap differently between browser and PPT.
 */
const FONT_REWRITE_SRC = `
(function () {
  const MAP = {
    'Inter':          'Arial, Helvetica, sans-serif',
    'DM Sans':        'Arial, Helvetica, sans-serif',
    'DM Mono':        'Consolas, "Courier New", monospace',
    'Söhne':          'Arial, Helvetica, sans-serif',
    'IBM Plex Sans':  'Arial, Helvetica, sans-serif',
    'IBM Plex Mono':  'Consolas, "Courier New", monospace',
    'Graphik':        'Arial, Helvetica, sans-serif',
    'Tiempos':        'Georgia, Times, serif',
  };
  document.querySelectorAll('*').forEach(function (el) {
    const first = getComputedStyle(el).fontFamily.split(',')[0].replace(/['"]/g, '').trim();
    if (MAP[first]) el.style.fontFamily = MAP[first];
  });
})();
`;

/** Mount a hidden iframe, step each slide, collect records via the walker. */
export async function extractSlideRecordsForExport(
  deck: SlideDeck,
  fontMode: EditableFontMode = 'universal',
): Promise<SlideExtract[]> {
  const slides = deck.slides || [];
  if (!slides.length) return [];

  const composite = buildCompositeHtml(deck);

  const container = document.createElement('div');
  container.style.cssText =
    `position:fixed;left:-99999px;top:0;width:${DESIGN_W}px;height:${DESIGN_H}px;visibility:hidden;opacity:0;pointer-events:none;z-index:-9999;overflow:hidden;`;
  const iframe = document.createElement('iframe');
  iframe.style.cssText = `width:${DESIGN_W}px;height:${DESIGN_H}px;border:0;display:block;margin:0;padding:0;`;
  container.appendChild(iframe);
  document.body.appendChild(container);

  try {
    // Hard-force brand fonts to Arial/Consolas via !important when font_mode
    // is universal. Applied via <style> so it covers pseudo-element content
    // too; the DOM rewrite pass below handles inline-style authored content.
    let fontShim = '';
    if (fontMode === 'universal') {
      fontShim = `<style id="htp-font-shim">
        @font-face { font-family: "Inter"; src: local("Arial"); font-display: block; }
        @font-face { font-family: "DM Sans"; src: local("Arial"); font-display: block; }
        @font-face { font-family: "DM Mono"; src: local("Consolas"); font-display: block; }
        @font-face { font-family: "Söhne"; src: local("Arial"); font-display: block; }
        @font-face { font-family: "IBM Plex Sans"; src: local("Arial"); font-display: block; }
        @font-face { font-family: "IBM Plex Mono"; src: local("Consolas"); font-display: block; }
        @font-face { font-family: "Graphik"; src: local("Arial"); font-display: block; }
        @font-face { font-family: "Tiempos"; src: local("Georgia"); font-display: block; }
        body, body * { font-family: Arial, Helvetica, sans-serif !important; }
        body code, body pre, body kbd, body samp,
        body .mono, body [class*="mono" i], body [class*="Mono"] {
          font-family: Consolas, "Courier New", monospace !important;
        }
      </style>`;
    } else if (fontMode === 'google_slides') {
      fontShim = `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap">`;
    }
    const shimmedComposite = fontShim
      ? composite.replace('</head>', fontShim + '</head>')
      : composite;

    iframe.srcdoc = shimmedComposite;
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('iframe load timeout')), 15000);
      iframe.onload = () => { clearTimeout(t); resolve(); };
      iframe.onerror = () => { clearTimeout(t); reject(new Error('iframe load error')); };
    });
    console.log('[walker] iframe loaded');

    const w = iframe.contentWindow;
    const d = iframe.contentDocument;
    if (!w || !d) throw new Error('iframe document not accessible');

    // Inject walker function.
    const inject = d.createElement('script');
    inject.textContent = WALKER_SOURCE;
    d.head.appendChild(inject);
    const walkerDefined = typeof (w as any).__extractSlide === 'function';
    console.log('[walker] script injected, __extractSlide defined:', walkerDefined);
    if (!walkerDefined) {
      console.error('[walker] WALKER_SOURCE failed to define __extractSlide', {
        walkerSrcLength: WALKER_SOURCE.length,
        firstChars: WALKER_SOURCE.slice(0, 200),
      });
      throw new Error('walker script injection failed — __extractSlide not defined');
    }

    // Inject huashu-style DOM-mutation preprocessor.
    const injectPre = d.createElement('script');
    injectPre.textContent = PREPROCESS_SOURCE;
    d.head.appendChild(injectPre);
    if (typeof (w as any).__huashuPreprocess !== 'function') {
      console.error('[walker] PREPROCESS_SOURCE failed to define __huashuPreprocess');
      throw new Error('preprocess script injection failed');
    }

    // Force brand fonts → fallback on every element (inline style = max specificity).
    if (fontMode === 'universal') {
      try {
        (w as any).eval(FONT_REWRITE_SRC);
      } catch (e) {
        console.error('[walker] font rewrite failed:', e);
      }
    }

    // Double fonts.ready with a 150ms settle in between — covers late
    // @font-face resolution that happens after first layout.
    try { await (w as any).document.fonts.ready; } catch (_) {}
    await new Promise(r => setTimeout(r, 150));
    try { await (w as any).document.fonts.ready; } catch (_) {}

    const out: SlideExtract[] = [];
    for (let i = 0; i < slides.length; i++) {
      try {
        (w as any).eval(`
          document.querySelectorAll('section.slide-container').forEach(function (s, j) {
            s.style.display = j === ${i} ? 'block' : 'none';
          });
        `);
      } catch (e) {
        console.error(`[walker] toggle display failed on slide ${i}:`, e);
      }
      await new Promise(r => setTimeout(r, SLIDE_SETTLE_MS));
      try { await (w as any).document.fonts.ready; } catch (_) {}

      // If this slide has <canvas> elements (Chart.js), wait for them
      // to (a) have non-zero attribute dims and (b) produce a non-empty
      // toDataURL, then add a settle for the chart's animation to flush.
      // Mirrors the post-networkidle wait we do server-side in huashu.
      try {
        const hasCanvases = (w as any).eval(`
          document.querySelectorAll('section.slide-container[data-slide-index="${i}"] canvas').length > 0
        `);
        if (hasCanvases) {
          const deadline = Date.now() + 5000;
          while (Date.now() < deadline) {
            const allReady = (w as any).eval(`
              (function () {
                const cs = document.querySelectorAll('section.slide-container[data-slide-index="${i}"] canvas');
                for (const c of cs) {
                  if (!c.width || !c.height) return false;
                  try { if (c.toDataURL('image/png').length <= 200) return false; } catch (e) {}
                }
                return true;
              })();
            `);
            if (allReady) break;
            await new Promise(r => setTimeout(r, 150));
          }
          // Chart.js default animation is ~1s; let it finish.
          await new Promise(r => setTimeout(r, 1500));
        }
      } catch (e) {
        console.warn(`[walker] canvas wait failed on slide ${i}:`, e);
      }

      // Run huashu-style DOM mutations (flatten tables, badge pills, code
      // panels, etc.) on the slide root BEFORE walking. Best-effort —
      // failure here just means the slide exports without those wins.
      try {
        const stats = (w as any).eval(`
          (function () {
            const root = document.querySelector('section.slide-container[data-slide-index="${i}"]');
            return root ? window.__huashuPreprocess(root) : null;
          })();
        `);
        if (stats) {
          console.log(`[walker] slide ${i} preprocess:`, stats);
        }
      } catch (e) {
        console.warn(`[walker] preprocess failed on slide ${i}:`, e);
      }

      let extract;
      try {
        extract = (w as any).eval(`
          (function () {
            const root = document.querySelector('section.slide-container[data-slide-index="${i}"]');
            return root ? window.__extractSlide(root) : null;
          })();
        `);
      } catch (e) {
        console.error(`[walker] extract failed on slide ${i}:`, e);
        throw e;
      }
      if (!extract) {
        console.warn(`[walker] slide ${i} returned null (selector missed?)`);
        continue;
      }
      console.log(`[walker] slide ${i} records:`, extract.records.length);

      const notes = (w as any).eval(`
        (function () {
          const t = document.getElementById('speaker-notes');
          if (!t) return '';
          try { return JSON.parse(t.textContent)[${i}] || ''; } catch (e) { return ''; }
        })();
      `) as string;

      out.push({
        width: extract.width,
        height: extract.height,
        records: extract.records,
        notes: notes || '',
      });
    }

    return out;
  } finally {
    if (container.parentNode) document.body.removeChild(container);
  }
}
