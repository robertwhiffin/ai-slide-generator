// CSS gradient parsing, shared by every page-side pass that reads a gradient
// (PLAN-CORRECTIONS C6): preprocess.mjs's slide-root background transfer
// rasterizes a gradient ground with rasterizeGradientToDataURL, and
// snapshot.mjs takes the colour at the middle of a gradient for the text it
// paints under (gradient text, a gradient card) with parseLinearGradient. One
// copy, composed into each pass's IIFE the way DOM_ACCESS_SOURCE is; it needs
// nothing from the composing pass.
//
// splitTopLevelCommas, parseLinearGradient and rasterizeGradientToDataURL are
// the background transfer's parser and rasterizer, moved out of preprocess.mjs
// with their behaviour unchanged. The only edit is the colour-stop loop, which
// indexes the array instead of `for…of`: page script can replace
// Array.prototype[Symbol.iterator], and the loop must stay bounded.
export const GRADIENT_SOURCE = `
  // Split at top-level commas (paren-aware, like our walker): the commas
  // inside rgba(...) separate nothing.
  function splitTopLevelCommas(text) {
    const parts = [];
    let depth = 0, current = '';
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { parts.push(current.trim()); current = ''; }
      else current += ch;
    }
    if (current.trim()) parts.push(current.trim());
    return parts;
  }

  // linear-gradient(<angle>, <stop1>, <stop2>, ...) -> {angle, stops: [{color, pos}]},
  // or null when it is not one. A stop's pos is its percentage over 100, else
  // its index spread evenly over 0..1; color is the stop's text as written.
  function parseLinearGradient(gradientCss) {
    // Match linear-gradient(<angle>, <stop1>, <stop2>, ...)
    const m = gradientCss.match(/linear-gradient\\((.+)\\)\\s*\$/);
    if (!m) return null;
    const parts = splitTopLevelCommas(m[1]);
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
    return { angle: angle, stops: stops };
  }

  // A linear gradient drawn on a w x h canvas, as a PNG data URL; null when it
  // does not parse or the canvas refuses it.
  function rasterizeGradientToDataURL(gradientCss, w, h) {
    try {
      const c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(w));
      c.height = Math.max(1, Math.round(h));
      const ctx = c.getContext('2d');
      const parsed = parseLinearGradient(gradientCss);
      if (!parsed) return null;
      const angle = parsed.angle;
      const stops = parsed.stops;
      const rad = (angle - 90) * Math.PI / 180;
      const cx = c.width / 2, cy = c.height / 2;
      const len = Math.abs(c.width * Math.cos(rad)) + Math.abs(c.height * Math.sin(rad));
      const dx = Math.cos(rad) * len / 2;
      const dy = Math.sin(rad) * len / 2;
      const grad = ctx.createLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy);
      for (let i = 0; i < stops.length; i++) {
        const s = stops[i];
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
`;
