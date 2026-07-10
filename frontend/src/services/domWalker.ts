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
import { SLIDE_CSP } from './slideDocument';

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

// Exported so tests can pin the composite document's layout guarantees.
export function buildCompositeHtml(deck: SlideDeck): string {
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

  // AISEC-248 #3: this walker mounts a same-origin iframe and reads its
  // contentDocument to measure layout, so it cannot be sandboxed. CSP is the
  // egress containment — same restrictive policy as the pdf/pptx/screenshot
  // exports. The slide scripts run as native inline <script> under
  // 'unsafe-inline'; extraction is driven by direct same-origin calls (no
  // eval), so 'unsafe-eval' is intentionally NOT granted.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${SLIDE_CSP}">`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
${cspMeta}
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
/* Same guarantee for roots the model did NOT class ".slide" — whatever the
   slide's outermost element is, it must sit at the frame origin. */
section.slide-container > * { margin: 0 !important; }
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
 *
 * Exported so tests/e2e/svg-raster-export.spec.ts can drive the exact
 * shipped walker string in a Playwright page.
 */
export const WALKER_SOURCE = `
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

  // ─── SVG-image rasterization ────────────────────────────────────────
  // pptxgenjs in Node emits data:image/svg+xml images with a hardcoded
  // broken-image placeholder PNG as the primary <a:blip>; the vector only
  // survives in the <asvg:svgBlip> extension, which Google Slides' PPTX
  // conversion and LibreOffice ignore. Rasterize here instead — this
  // browser already decoded the SVG. 2x the layout box keeps it crisp.
  // Returns a PNG data URI, or null so the caller keeps the raw SVG src
  // (exactly the pre-fix payload).
  function rasterizeSvgImage(el) {
    try {
      if (!el.complete || !el.naturalWidth) return null;
      const r = el.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width * 2));
      const h = Math.max(1, Math.round(r.height * 2));
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d');
      if (!ctx) return null;
      ctx.drawImage(el, 0, 0, w, h);
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
        let src = el.currentSrc || el.src;
        if (/^data:image\\/svg\\+xml/i.test(src)) {
          const png = rasterizeSvgImage(el);
          if (png) {
            src = png;
          } else {
            console.warn('[walker] svg raster failed, keeping raw SVG data URI');
          }
        }
        const rec = Object.assign({ kind: 'image' }, ibox, {
          src: src,
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

  // ─── pre-walk mutation: inline <svg> → <img data:image/svg+xml> ──────
  // visit() covers text leaves, <img> (with SVG-src raster), <canvas>, and
  // background fills — but inline <svg> ELEMENTS had no handler: the walk
  // recursed into SVG children and emitted nothing, so icon glyphs vanished
  // from the records export (the huashu path materializes them). Swap each
  // top-level svg for an equal-box <img> whose src is the serialized svg;
  // the existing IMG branch + rasterizeSvgImage then emit a PNG record.
  // Layout-critical styles are copied so the swap holds the svg's box in
  // flex/absolute layouts; currentColor is frozen via an explicit color.
  // Serialization failures keep the svg in place (warn, never throw).
  function materializeInlineSvgs(root, decodes) {
    const svgs = Array.prototype.filter.call(
      root.querySelectorAll('svg'),
      function (s) { return !s.ownerSVGElement; }
    );
    let converted = 0;
    for (const svg of svgs) {
      const cs = getComputedStyle(svg);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const r = svg.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || !svg.parentNode) continue;
      let src;
      try {
        const clone = svg.cloneNode(true);
        if (!clone.getAttribute('xmlns')) {
          clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        }
        // Standalone svg loses the CSS-sized box and inherited currentColor;
        // freeze both so the raster matches the rendered glyph.
        if (!clone.getAttribute('viewBox') && svg.hasAttribute('width') && svg.hasAttribute('height')) {
          clone.setAttribute('viewBox', '0 0 ' + svg.getAttribute('width') + ' ' + svg.getAttribute('height'));
        }
        clone.setAttribute('width', String(r.width));
        clone.setAttribute('height', String(r.height));
        clone.style.color = cs.color;
        src = 'data:image/svg+xml;charset=utf-8,' +
          encodeURIComponent(new XMLSerializer().serializeToString(clone));
      } catch (e) {
        console.warn('[walker] inline svg serialize failed, glyph kept as-is:', e.message);
        continue;
      }
      const img = document.createElement('img');
      img.src = src;
      img.style.cssText =
        'width:' + r.width + 'px;height:' + r.height + 'px;' +
        'position:' + cs.position + ';left:' + cs.left + ';top:' + cs.top + ';' +
        'right:' + cs.right + ';bottom:' + cs.bottom + ';margin:' + cs.margin + ';' +
        'transform:' + cs.transform + ';vertical-align:' + cs.verticalAlign + ';' +
        'z-index:' + cs.zIndex + ';flex-shrink:0;';
      svg.parentNode.replaceChild(img, svg);
      converted++;
      decodes.push(img.decode().catch(function () {
        console.warn('[walker] inline svg decode failed, record keeps raw src: ' + img.src.slice(0, 80));
      }));
    }
    return converted;
  }

  // ─── pre-walk mutation: CSS background-image url() → real <img> ──────
  // The walker has no handler for non-gradient background-image layers:
  // hasVisualFill() sees them but only ever emits the solid backgroundColor
  // rect, so url() assets (logos, photos, data-URI icons) are silently
  // dropped from the export. Materialize each one as an absolutely-
  // positioned <img> child before walking — the existing image branch then
  // emits it (including the SVG→PNG raster for data:image/svg+xml sources,
  // whose sync .complete/.naturalWidth check is why decodes are awaited
  // here). Idempotent: the source backgroundImage is cleared on conversion.
  // Inline <svg> elements are materialized first (same decode barrier).
  async function prepareSlideForExtract(root) {
    const decodes = [];
    materializeInlineSvgs(root, decodes);
    const candidates = [root].concat(Array.from(root.querySelectorAll('*')));
    for (const el of candidates) {
      if (el.tagName === 'IMG' || el.tagName === 'CANVAS') continue;
      const cs = getComputedStyle(el);
      const bg = cs.backgroundImage;
      if (!bg || bg === 'none' || bg.indexOf('url(') === -1) continue;
      if (bg.indexOf('gradient') !== -1) continue; // gradient raster path owns these
      const m = bg.match(/url\\((["']?)([^"')]+)\\1\\)/);
      if (!m) continue;
      el.style.backgroundImage = 'none';
      if (cs.position === 'static' || !cs.position) el.style.position = 'relative';
      const img = document.createElement('img');
      img.src = m[2];
      img.style.cssText =
        'position:absolute;left:0;top:0;width:100%;height:100%;' +
        'object-fit:' + (cs.backgroundSize === 'contain' ? 'contain' : 'cover') + ';' +
        'pointer-events:none;';
      el.insertBefore(img, el.firstChild);
      decodes.push(img.decode().catch(function () {
        console.warn('[walker] bg-image decode failed, record keeps raw src: ' + img.src.slice(0, 80));
      }));
    }
    await Promise.all(decodes);
    return decodes.length;
  }

  window.__extractSlide = walk;
  window.__prepareSlideForExtract = prepareSlideForExtract;
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

    // Force brand fonts → fallback on every element (inline style = max specificity).
    // Injected as a <script> (runs under CSP 'unsafe-inline') rather than eval()
    // so the slide CSP need not allow 'unsafe-eval' (AISEC-248).
    if (fontMode === 'universal') {
      try {
        const fontScript = d.createElement('script');
        fontScript.textContent = FONT_REWRITE_SRC;
        d.head.appendChild(fontScript);
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
      // Same-origin frame (no sandbox) → drive it via direct DOM/function calls
      // instead of eval(), so the CSP need not allow 'unsafe-eval' (AISEC-248).
      try {
        d.querySelectorAll('section.slide-container').forEach((s, j) => {
          (s as HTMLElement).style.display = j === i ? 'block' : 'none';
        });
      } catch (e) {
        console.error(`[walker] toggle display failed on slide ${i}:`, e);
      }
      await new Promise(r => setTimeout(r, SLIDE_SETTLE_MS));
      try { await (w as any).document.fonts.ready; } catch (_) {}

      let extract;
      try {
        const root = d.querySelector(
          `section.slide-container[data-slide-index="${i}"]`
        );
        if (root) {
          // Materialize inline <svg> elements and CSS background-image url()
          // layers as <img> before the walk — the walker has handlers for
          // neither, so without this pass those visuals drop out of the
          // export entirely.
          try {
            await (
              w as unknown as {
                __prepareSlideForExtract: (el: Element) => Promise<number>;
              }
            ).__prepareSlideForExtract(root);
          } catch (prepErr) {
            console.warn(`[walker] bg-image prepare failed on slide ${i}:`, prepErr);
          }
        }
        extract = root ? (w as any).__extractSlide(root) : null;
      } catch (e) {
        console.error(`[walker] extract failed on slide ${i}:`, e);
        throw e;
      }
      if (!extract) {
        console.warn(`[walker] slide ${i} returned null (selector missed?)`);
        continue;
      }
      console.log(`[walker] slide ${i} records:`, extract.records.length);

      let notes = '';
      try {
        const t = d.getElementById('speaker-notes');
        if (t) notes = JSON.parse(t.textContent || '[]')[i] || '';
      } catch (_) {
        notes = '';
      }

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
