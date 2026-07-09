/**
 * Records-path export — CSS background-image url() assets.
 *
 * The walker (`WALKER_SOURCE` in frontend/src/services/domWalker.ts) has no
 * handler for non-gradient background-image layers: `hasVisualFill()` sees
 * them but only ever emits the solid backgroundColor rect, so `url()` assets
 * (logos, photos, data-URI icons) were silently dropped from the export.
 *
 * The fix is `__prepareSlideForExtract`, an async pre-walk mutation that
 * materializes each url() background as an absolutely-positioned <img> child
 * (mirroring the huashu preprocess pass), so the walker's existing image
 * branch — including the Phase-5 SVG→PNG raster — emits it.
 *
 * Covered here, driving the real WALKER_SOURCE in a real Chromium page:
 *  1. payload identity — for a page with no url() backgrounds, records with
 *     and without the prepare pass are deep-equal (the pass is a no-op);
 *  2. new behavior — a PNG data-URI background becomes an image record at
 *     the host div's box, painted above that div's fill rect;
 *  3. new behavior — an SVG data-URI background is rasterized to a PNG
 *     record at 2x the layout box (the Phase-5 branch applies to minted imgs).
 *
 * Run with: npx playwright test tests/e2e/css-bg-export.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';
import { WALKER_SOURCE } from '../../src/services/domWalker';
import { pngDimensions } from '../helpers/pptxZip';

// Synthetic assets — same palette as the Phase-5 spec fixtures.
const PNG_NAVY_24x16 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAQCAIAAACDRijCAAAAGklEQVR42mPgtk2jCmIYNWjUoFGDRg2iDAEABu0FEHVYOK4AAAAASUVORK5CYII=';
const SVG_WAVE_300x200 =
  'data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22300%22%20height%3D%22200%22%20viewBox%3D%220%200%20300%20200%22%3E%3Crect%20width%3D%22300%22%20height%3D%22200%22%20fill%3D%22%23F2E8DA%22%2F%3E%3Cpath%20d%3D%22M0%20150%20L75%2090%20L150%20130%20L225%2060%20L300%20110%20L300%20200%20L0%20200%20Z%22%20fill%3D%22%230B3D66%22%2F%3E%3C%2Fsvg%3E';

function slidePage(inner: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;}</style></head>
<body>
<section id="root" style="position:relative;width:1280px;height:720px;overflow:hidden;background:#ffffff;font-family:Arial, Helvetica, sans-serif;">
${inner}
</section>
</body></html>`;
}

const NO_BG_URL_PAGE = slidePage(`
  <img alt="" src="${PNG_NAVY_24x16}" style="position:absolute;left:88px;top:72px;width:240px;height:80px;">
  <div style="position:absolute;left:88px;top:200px;width:420px;height:220px;background:#F2E8DA;border:2px solid #0B3D66;border-radius:12px;"></div>
  <h1 style="position:absolute;left:480px;top:220px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Quarterly Report</h1>
`);

const BG_URL_PAGE = slidePage(`
  <div id="png-bg" style="position:absolute;left:88px;top:72px;width:240px;height:160px;background-color:#0B3D66;background-image:url('${PNG_NAVY_24x16}');background-size:cover;"></div>
  <div id="svg-bg" style="position:absolute;left:400px;top:72px;width:300px;height:200px;background-image:url('${SVG_WAVE_300x200}');background-size:cover;"></div>
  <h1 style="position:absolute;left:88px;top:320px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Background Assets Slide</h1>
`);

interface WalkerImageRecord {
  kind: 'image';
  x: number;
  y: number;
  w: number;
  h: number;
  src: string;
}

interface WalkerRectRecord {
  kind: 'rect';
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string | null;
}

async function loadWalker(page: Page, html: string) {
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForFunction(() =>
    Array.from(document.images).every((img) => img.complete),
  );
  await page.addScriptTag({ content: WALKER_SOURCE });
}

async function extractRecords(page: Page, { prepare }: { prepare: boolean }) {
  return page.evaluate(async (runPrepare) => {
    const w = window as unknown as {
      __extractSlide: (el: Element) => unknown;
      __prepareSlideForExtract: (el: Element) => Promise<number>;
    };
    const root = document.getElementById('root')!;
    if (runPrepare) await w.__prepareSlideForExtract(root);
    return w.__extractSlide(root);
  }, prepare) as Promise<{ width: number; height: number; records: Record<string, unknown>[] }>;
}

function dataUriPng(src: string): Buffer {
  expect(src).toMatch(/^data:image\/png;base64,/);
  return Buffer.from(src.slice('data:image/png;base64,'.length), 'base64');
}

test('prepare pass is a no-op for pages without url() backgrounds (payload identity)', async ({ page }) => {
  await loadWalker(page, NO_BG_URL_PAGE);
  const withoutPrepare = await extractRecords(page, { prepare: false });
  const withPrepare = await extractRecords(page, { prepare: true });
  expect(withPrepare).toEqual(withoutPrepare);
});

test('PNG url() background emits an image record above the host fill rect', async ({ page }) => {
  await loadWalker(page, BG_URL_PAGE);
  const extract = await extractRecords(page, { prepare: true });

  const records = extract.records as unknown as Array<WalkerImageRecord | WalkerRectRecord>;
  const pngBgImage = records.find(
    (r) => r.kind === 'image' && (r as WalkerImageRecord).src === PNG_NAVY_24x16,
  ) as WalkerImageRecord | undefined;
  expect(pngBgImage, 'bg url() PNG should surface as an image record').toBeTruthy();
  expect(Math.round(pngBgImage!.x)).toBe(88);
  expect(Math.round(pngBgImage!.y)).toBe(72);
  expect(Math.round(pngBgImage!.w)).toBe(240);
  expect(Math.round(pngBgImage!.h)).toBe(160);

  // The host div's own backgroundColor rect still paints, before the image.
  const hostRect = records.find(
    (r) => r.kind === 'rect' && Math.round(r.x) === 88 && Math.round(r.y) === 72,
  );
  expect(hostRect, 'host div fill rect should still be emitted').toBeTruthy();
  expect(records.indexOf(hostRect!)).toBeLessThan(records.indexOf(pngBgImage!));
});

test('SVG url() background is rasterized to a 2x PNG record', async ({ page }) => {
  await loadWalker(page, BG_URL_PAGE);
  const extract = await extractRecords(page, { prepare: true });

  const images = (extract.records as unknown as WalkerImageRecord[]).filter(
    (r) => r.kind === 'image',
  );
  // png-bg passthrough + svg-bg raster.
  expect(images).toHaveLength(2);
  const svgBgImage = images.find((r) => r.src !== PNG_NAVY_24x16)!;
  const raster = dataUriPng(svgBgImage.src);
  expect(pngDimensions(raster)).toEqual({ width: 600, height: 400 });
  expect(Math.round(svgBgImage.x)).toBe(400);
  expect(Math.round(svgBgImage.w)).toBe(300);
  expect(Math.round(svgBgImage.h)).toBe(200);
});
