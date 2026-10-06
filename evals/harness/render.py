"""Headless render of a slide fragment with in-page overflow/contrast/palette measurements."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js"


@dataclass(frozen=True)
class RenderMeasures:
    overflow_px: float = 0.0
    min_contrast: float = 0.0
    off_palette: tuple[str, ...] = ()
    console_errors: tuple[str, ...] = ()
    rendered: bool = False


def _norm_hex(h: str) -> str:
    h = h.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def palette_hexes(section_css: str) -> set[str]:
    out = {"#ffffff", "#000000"}
    for m in re.finditer(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", section_css):
        out.add(_norm_hex(m.group(1)))
    for m in re.finditer(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", section_css):
        r, g, b = (min(255, int(m.group(i))) for i in (1, 2, 3))
        out.add("#%02x%02x%02x" % (r, g, b))
    return out


_MEASURE_JS = r"""
(args) => {
  const palette = new Set(args.palette);
  const slide = document.querySelector('.slide');
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  };
  const hex = (c) => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const lum = (c) => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const blend = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1});
  const effBg = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let bg = {r: 255, g: 255, b: 255, a: 1};
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return bg;
  };
  const off = new Set();
  let minC = Infinity;
  const els = slide ? [slide, ...slide.querySelectorAll('*')] : [];
  for (const el of els) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const fg = parse(cs.color), bgc = parse(cs.backgroundColor);
    if (bgc && bgc.a > 0 && !palette.has(hex(bgc))) off.add(hex(bgc));
    let hasText = false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { hasText = true; break; }
    if (hasText && fg) {
      if (fg.a > 0 && !palette.has(hex(fg))) off.add(hex(fg));
      const bg = effBg(el);
      const f = blend(fg, bg);
      const l1 = lum(f), l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      if (ratio < minC) minC = ratio;
    }
  }
  const sh = slide ? slide.scrollHeight : 0, sw = slide ? slide.scrollWidth : 0;
  return {
    overflow: Math.max(0, sh - args.height, sw - args.width),
    minContrast: minC === Infinity ? 21 : minC,
    offPalette: [...off].sort(),
  };
}
"""

_CHART_READY_JS = """
() => typeof window.Chart !== 'undefined' &&
  [...document.querySelectorAll('canvas')].every(c =>
    c.width > 0 && c.height > 0 &&
    // A bare <canvas> is 300x150 by default, so size alone does not prove init.
    (typeof window.Chart.getChart !== 'function' || !!window.Chart.getChart(c)))
"""


def _build_doc(html: str, scripts: str, section_css: str, width: int, height: int) -> str:
    has_canvas = "<canvas" in html
    cdn = f'<script src="{CHARTJS_CDN}"></script>' if has_canvas else ""
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{section_css}\nbody{{margin:0}}.slide{{width:{width}px;height:{height}px}}</style>"
        f"</head><body>{html}{cdn}<script>{scripts}</script></body></html>"
    )


def render_slide(
    html: str,
    scripts: str = "",
    *,
    section_css: str,
    width: int = 1280,
    height: int = 720,
    chart_timeout_ms: int = 4000,
) -> RenderMeasures:
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    doc = _build_doc(html, scripts, section_css, width, height)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("crash", lambda: errors.append("page-crash"))
                page.set_content(doc, wait_until="load")
                try:
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass
                if "<canvas" in html:
                    deadline = time.monotonic() + chart_timeout_ms / 1000
                    ready = False
                    while time.monotonic() < deadline:
                        if page.evaluate(_CHART_READY_JS):
                            ready = True
                            break
                        page.wait_for_timeout(50)
                    if not ready:
                        errors.append("chart-init-timeout")
                r = page.evaluate(_MEASURE_JS, {"palette": sorted(palette_hexes(section_css)),
                                                "width": width, "height": height})
            finally:
                browser.close()
    except Exception as e:  # launch/crash/load failure
        return RenderMeasures(rendered=False, console_errors=tuple(errors) + (f"render-failure: {e}",))
    return RenderMeasures(
        overflow_px=float(r["overflow"]),
        min_contrast=float(r["minContrast"]),
        off_palette=tuple(r["offPalette"]),
        console_errors=tuple(errors),
        rendered=True,
    )
