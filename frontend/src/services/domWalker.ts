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
export interface BackgroundRecord {
  kind: 'background';
  src?: string;   // data/URL for an image background
  fill?: string;  // hex color background (omitted for white — slides default white)
}
export type SlideRecord = RectRecord | ImageRecord | TextRecord | BackgroundRecord;

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
      // Match the first linear-gradient(...) layer, allowing one level of nested
      // parens (rgba(...) stops). NOT end-anchored, so a combined value like
      // "linear-gradient(scrim), url(photo)" (Tellr covers) still matches the scrim.
      const m = bg.match(/linear-gradient\\(((?:[^()]|\\([^()]*\\))*)\\)/);
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
        if (a) {
          angle = parseFloat(a[1]);
        } else if (/to /.test(parts[0])) {
          // CSS keyword directions → angle (0=to top, 90=to right, 180=to bottom, 270=to left).
          const dir = parts[0];
          const right = /right/.test(dir), left = /left/.test(dir);
          const top = /top/.test(dir), bottom = /bottom/.test(dir);
          if (top && right) angle = 45;
          else if (bottom && right) angle = 135;
          else if (bottom && left) angle = 225;
          else if (top && left) angle = 315;
          else if (right) angle = 90;
          else if (left) angle = 270;
          else if (top) angle = 0;
          else angle = 180; // to bottom
        }
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
        // Per-side borders. pptxgenjs 'line' stroke applies to ALL FOUR sides, so it's
        // only correct for a uniform border. A single-side accent (border-top only —
        // common in Tellr cards) must NOT become a full outline: emit each present side
        // as a thin filled bar instead, and leave the box itself unstroked.
        const bTop = { w: parseFloat(cs.borderTopWidth) || 0, c: parseColor(cs.borderTopColor) };
        const bRight = { w: parseFloat(cs.borderRightWidth) || 0, c: parseColor(cs.borderRightColor) };
        const bBottom = { w: parseFloat(cs.borderBottomWidth) || 0, c: parseColor(cs.borderBottomColor) };
        const bLeft = { w: parseFloat(cs.borderLeftWidth) || 0, c: parseColor(cs.borderLeftColor) };
        const sides = [bTop, bRight, bBottom, bLeft];
        const present = sides.filter(sd => sd.w > 0 && sd.c);
        const uniform = present.length === 4 &&
          sides.every(sd => sd.w === bTop.w && sd.c && bTop.c && sd.c.hex === bTop.c.hex);

        // A full-bleed element (covers the whole slide) IS the slide background:
        // set it as the PPTX slide background rather than a slide-sized shape/image
        // that sits on top and is awkward to select/edit. A plain white background
        // emits nothing at all — slides already default to white.
        const fullBleed = box.x <= 1 && box.y <= 1 &&
          box.w >= rootRect.width - 2 && box.h >= rootRect.height - 2;

        if (fullBleed && present.length === 0 && (el.dataset.bgRaster || fill)) {
          // Full-bleed url() photo is emitted as the slide background; a combined
          // gradient-scrim + url-photo cover layers correctly (photo as background,
          // scrim painted over it by the gradient overlay below).
          if (el.dataset.bgRaster) {
            records.push({ kind: 'background', src: el.dataset.bgRaster });
          } else if (fill.hex !== 'FFFFFF') {
            records.push({ kind: 'background', fill: fill.hex });
          }
          // white fill → nothing (default white slide)
        } else {
          if (fill || uniform) {
            const rect = {
              kind: 'rect',
              x: box.x, y: box.y, w: box.w, h: box.h,
              fill: fill ? fill.hex : null,
              stroke: uniform && bTop.c ? bTop.c.hex : null,
              strokeW: uniform ? bTop.w : 0,
              radius: parseRadius(cs),
              _depth: depth,
            };
            if (shadow) rect.shadow = shadow;
            records.push(rect);
          }
          if (!uniform && present.length > 0) {
            const bar = (x, y, w, h, hex) => records.push({
              kind: 'rect', x: x, y: y, w: w, h: h,
              fill: hex, stroke: null, strokeW: 0, radius: 0, _depth: depth + 0.1,
            });
            if (bTop.w > 0 && bTop.c) bar(box.x, box.y, box.w, bTop.w, bTop.c.hex);
            if (bBottom.w > 0 && bBottom.c) bar(box.x, box.y + box.h - bBottom.w, box.w, bBottom.w, bBottom.c.hex);
            if (bLeft.w > 0 && bLeft.c) bar(box.x, box.y, bLeft.w, box.h, bLeft.c.hex);
            if (bRight.w > 0 && bRight.c) bar(box.x + box.w - bRight.w, box.y, bRight.w, box.h, bRight.c.hex);
          }
          // Non-full-bleed background-image url() (rasterized to el.dataset.bgRaster
          // by the export pre-pass, since pptxgenjs can't read CSS backgrounds).
          if (el.dataset.bgRaster) {
            records.push(Object.assign({ kind: 'image' }, box, { src: el.dataset.bgRaster, _depth: depth + 0.3 }));
          }
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

      // 3. <img>. Prefer el.dataset.rasterSrc — the export pre-pass sets it for
      // SVG sources (pptxgenjs can't embed image/svg+xml), rasterized to PNG.
      if (el.tagName === 'IMG' && el.src) {
        const ibox = rotation !== null ? getRotatedBox(el, box, rotation) : box;
        const rec = Object.assign({ kind: 'image' }, ibox, {
          src: el.dataset.rasterSrc || el.currentSrc || el.src,
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

/**
 * Rasterize export-hostile assets to PNG dataURLs before the (synchronous) walker runs.
 *
 * Two things pptxgenjs / the records path can't handle, both rendered fine by the browser:
 *   1. `background-image: url(...)` on a div — the walker only reads `<img>`/canvas/gradient,
 *      so full-bleed CSS backgrounds (Tellr covers/dividers) never became image records.
 *   2. SVG `<img>` sources — pptxgenjs.addImage can't embed `data:image/svg+xml`.
 *
 * For both we draw the already-decoded pixels onto a 2x canvas and stamp the PNG dataURL onto
 * the element (`dataset.bgRaster` / `dataset.rasterSrc`); the walker then emits image records
 * from those. Runs in the iframe context (`win`) so getComputedStyle/canvas match what's shown.
 * Best-effort throughout: any failure just leaves the element to the walker's old behavior.
 */
async function rasterizeExportAssets(win: any, root: HTMLElement): Promise<void> {
  const doc = root.ownerDocument!;
  const loadImage = (url: string): Promise<any> =>
    new Promise((resolve) => {
      const img = new win.Image();
      let settled = false;
      let timer: any;
      // A stalled fetch (hung/blocked remote resource) would otherwise never fire
      // onload/onerror, leaving this promise pending and blocking the whole export.
      // Cap the wait so the loop moves on (element falls back to walker behavior).
      const finish = (val: any) => { if (settled) return; settled = true; clearTimeout(timer); resolve(val); };
      timer = setTimeout(() => finish(null), 5000);
      img.onload = () => finish(img);
      img.onerror = () => finish(null);
      img.src = url;
    });
  const toCanvasPng = (
    img: any, boxW: number, boxH: number, mode: 'cover' | 'fit',
  ): string | null => {
    try {
      const scale = 2; // supersample so logos/backgrounds stay crisp when scaled in PPT
      const cw = Math.max(1, Math.round(boxW * scale));
      const ch = Math.max(1, Math.round(boxH * scale));
      const c = doc.createElement('canvas');
      c.width = cw; c.height = ch;
      const ctx = c.getContext('2d');
      if (!ctx) return null;
      if (mode === 'cover') {
        const iw = img.naturalWidth || img.width;
        const ih = img.naturalHeight || img.height;
        if (!iw || !ih) return null;
        const s = Math.max(cw / iw, ch / ih); // fill box, center-crop (background-size: cover)
        const dw = iw * s, dh = ih * s;
        ctx.drawImage(img, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
      } else {
        ctx.drawImage(img, 0, 0, cw, ch); // stretch to box (aspect already matches for logos)
      }
      return c.toDataURL('image/png');
    } catch { return null; }
  };

  const els = [root, ...Array.from(root.querySelectorAll('*'))] as HTMLElement[];
  for (const el of els) {
    let cs: CSSStyleDeclaration;
    try { cs = win.getComputedStyle(el); } catch { continue; }

    // (1) url() background image. Act whenever a url() layer is present — including a
    // combined `linear-gradient(scrim), url(photo)`, where we rasterize the photo and let
    // the walker rasterize the gradient scrim separately on top. Pure gradients (no url)
    // fall through to the walker.
    const bg = cs.backgroundImage;
    if (bg && bg !== 'none' && bg.indexOf('url(') !== -1) {
      const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
      const r = el.getBoundingClientRect();
      if (m && r.width >= 8 && r.height >= 8) {
        const img = await loadImage(m[1]);
        if (img) {
          const mode = cs.backgroundSize === 'contain' ? 'fit' : 'cover';
          const png = toCanvasPng(img, r.width, r.height, mode);
          if (png) el.dataset.bgRaster = png;
        }
      }
    }

    // (2) SVG <img> — rasterize the already-rendered element to PNG.
    if (el.tagName === 'IMG') {
      const im = el as HTMLImageElement;
      const src = im.currentSrc || im.src;
      if (src && (src.indexOf('image/svg') !== -1 || /\.svg(\?|#|$)/i.test(src))) {
        try { if (im.decode) await im.decode(); } catch { /* fall through */ }
        const r = im.getBoundingClientRect();
        if (r.width >= 1 && r.height >= 1) {
          const png = toCanvasPng(im, r.width, r.height, 'fit');
          if (png) el.dataset.rasterSrc = png;
        }
      }
    }
  }
}

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
        ) as HTMLElement | null;
        if (root) {
          try { await rasterizeExportAssets(w, root); }
          catch (e) { console.warn(`[walker] asset rasterization failed on slide ${i}:`, e); }
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
