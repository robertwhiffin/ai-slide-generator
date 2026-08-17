/**
 * Phase 5 — editable-export SVG rasterization, records path.
 *
 * pptxgenjs 3.12.0 in Node writes `data:image/svg+xml` images with a
 * hardcoded broken-image placeholder PNG as the primary <a:blip> (the real
 * SVG survives only in the <asvg:svgBlip> extension, which Google Drive's
 * PPTX→Slides conversion and LibreOffice ignore). The fix rasterizes SVG
 * <img>s to PNG inside the walker — in the browser, where an SVG renderer
 * exists — so the sidecar (services/pptx-emit/emit.bundle.mjs, intentionally
 * NOT rebuilt) only ever sees PNG data URIs.
 *
 * Covered here, driving the real WALKER_SOURCE in a real Chromium page:
 *  1. payload identity — an SVG-free page must extract to records that are
 *     deep-equal to the committed golden (captured pre-fix at d50b716), so
 *     the sidecar's stdin payload is provably unchanged for SVG-free decks;
 *  2. new behavior — an SVG <img> becomes a PNG record at 2x its layout box
 *     while a sibling PNG <img> passes through byte-unchanged;
 *  3. fallback — an undecodable SVG keeps its raw data URI (today's
 *     behavior) and warns, never throws;
 *  4. end-to-end — walker records piped through the actual sidecar bundle
 *     yield a pptx with no .svg media, no svgBlip, no IMG_BROKEN bytes.
 *
 * Run with: npx playwright test tests/e2e/svg-raster-export.spec.ts
 * (also wired into the CI e2e matrix in .github/workflows/test.yml).
 * Regenerate the walker golden (same machine/browser class) with:
 *   TELLR_REGEN_EXPORT_GOLDENS=1 npx playwright test tests/e2e/svg-raster-export.spec.ts
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';
import { WALKER_SOURCE } from '../../src/services/domWalker';
import { pngDimensions, readZipEntries } from '../helpers/pptxZip';

// Synthetic assets — mirror tests/fixtures/export_svg_raster/ on the Python
// side (duplicated because the two runtimes cannot share fixture loaders).
const PNG_NAVY_24x16 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAQCAIAAACDRijCAAAAGklEQVR42mPgtk2jCmIYNWjUoFGDRg2iDAEABu0FEHVYOK4AAAAASUVORK5CYII=';
const SVG_LOGO_240x80 =
  'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNDAiIGhlaWdodD0iODAiIHZpZXdCb3g9IjAgMCAyNDAgODAiPjxyZWN0IHdpZHRoPSIyNDAiIGhlaWdodD0iODAiIHJ4PSI4IiBmaWxsPSIjMEIzRDY2Ii8+PGNpcmNsZSBjeD0iNDAiIGN5PSI0MCIgcj0iMjIiIGZpbGw9IiNFODcyMkEiLz48dGV4dCB4PSI3NiIgeT0iNTIiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIzNCIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiNGRkZGRkYiPkFDTUU8L3RleHQ+PC9zdmc+';
// Truncated XML — loads into the error state, so decode/draw must fail.
const SVG_BROKEN = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxyZWN0';

const REGEN = process.env.TELLR_REGEN_EXPORT_GOLDENS === '1';
const WALKER_GOLDEN = fileURLToPath(
  new URL('../fixtures/svg-raster-walker-records.golden.json', import.meta.url),
);
const SIDECAR_BUNDLE = fileURLToPath(
  new URL('../../../services/pptx-emit/emit.bundle.mjs', import.meta.url),
);

function slidePage(inner: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;}</style></head>
<body>
<section id="root" style="position:relative;width:1280px;height:720px;overflow:hidden;background:#ffffff;font-family:Arial, Helvetica, sans-serif;">
${inner}
</section>
</body></html>`;
}

const PNG_CONTROL_PAGE = slidePage(`
  <img alt="" src="${PNG_NAVY_24x16}" style="position:absolute;left:88px;top:72px;width:240px;height:80px;">
  <div style="position:absolute;left:88px;top:200px;width:420px;height:220px;background:#F2E8DA;border:2px solid #0B3D66;border-radius:12px;"></div>
  <h1 style="position:absolute;left:480px;top:220px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Quarterly Report</h1>
`);

const MIXED_SVG_PAGE = slidePage(`
  <img id="svg-img" alt="" src="${SVG_LOGO_240x80}" style="position:absolute;left:88px;top:72px;width:240px;height:80px;">
  <img id="png-img" alt="" src="${PNG_NAVY_24x16}" style="position:absolute;left:400px;top:72px;width:240px;height:80px;">
  <h1 style="position:absolute;left:88px;top:220px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Vector Assets Slide</h1>
`);

const BROKEN_SVG_PAGE = slidePage(`
  <img id="broken-img" alt="" src="${SVG_BROKEN}" style="position:absolute;left:88px;top:72px;width:240px;height:80px;">
`);

interface WalkerImageRecord {
  kind: 'image';
  x: number;
  y: number;
  w: number;
  h: number;
  src: string;
}

async function extractRecords(page: Page, html: string) {
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForFunction(() =>
    Array.from(document.images).every((img) => img.complete),
  );
  await page.addScriptTag({ content: WALKER_SOURCE });
  return page.evaluate(() =>
    (window as unknown as { __extractSlide: (el: Element) => unknown }).__extractSlide(
      document.getElementById('root')!,
    ),
  ) as Promise<{ width: number; height: number; records: Record<string, unknown>[] }>;
}

/** Round every number to 2dp so subpixel text metrics can't flake the golden. */
function roundNumbers<T>(value: T): T {
  if (typeof value === 'number') return (Math.round(value * 100) / 100) as unknown as T;
  if (Array.isArray(value)) return value.map(roundNumbers) as unknown as T;
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, roundNumbers(v)]),
    ) as unknown as T;
  }
  return value;
}

function imgBrokenSha256(): string {
  const bundle = readFileSync(SIDECAR_BUNDLE, 'utf8');
  const match = bundle.match(/IMG_BROKEN = "data:image\/png;base64,([^"]+)"/);
  if (!match) throw new Error('IMG_BROKEN constant not found in emit.bundle.mjs');
  return createHash('sha256').update(Buffer.from(match[1], 'base64')).digest('hex');
}

// sha256 of pptxgenjs 3.12.0's Node-side placeholder PNG (1594 bytes) — the
// bytes Google Slides shows as a broken icon. Kept in sync with the Python
// twin (tests/unit/test_export_svg_raster.py::IMG_BROKEN_SHA256).
const IMG_BROKEN_SHA256 = '0db2447fffb75ae48f57c711c26783f619591d48b1713f997a7bc34626c95ff1';

function dataUriPng(src: string): Buffer {
  expect(src).toMatch(/^data:image\/png;base64,/);
  return Buffer.from(src.slice('data:image/png;base64,'.length), 'base64');
}

test('walker records for an SVG-free page match the pre-fix golden (payload identity)', async ({ page }) => {
  const extract = roundNumbers(await extractRecords(page, PNG_CONTROL_PAGE));
  if (REGEN) {
    writeFileSync(
      WALKER_GOLDEN,
      JSON.stringify({ capturedOn: process.platform, extract }, null, 2) + '\n',
    );
    test.skip(true, `regenerated ${WALKER_GOLDEN}`);
  }
  // Runs on EVERY platform: the PNG src survives byte-for-byte — the payload
  // property the SVG raster branch could have broken.
  const images = extract.records.filter((r) => r.kind === 'image') as unknown as WalkerImageRecord[];
  expect(images.map((r) => r.src)).toEqual([PNG_NAVY_24x16]);

  const golden = JSON.parse(readFileSync(WALKER_GOLDEN, 'utf8'));
  expect(golden.capturedOn).toBeTruthy();
  // Text-record geometry depends on platform font metrics, so the full
  // deep-equal is pinned to the platform that captured the golden (re-pin
  // with TELLR_REGEN_EXPORT_GOLDENS=1). The raster-behavior tests below are
  // geometry-explicit and run everywhere, CI included.
  test.skip(
    process.platform !== golden.capturedOn,
    `walker golden captured on ${golden.capturedOn}; font metrics differ on ${process.platform}`,
  );
  // Deep equality over the full extract = the from-records POST body (and so
  // the sidecar stdin payload) is identical before/after the SVG fix.
  expect(extract).toEqual(golden.extract);
});

test('SVG <img> extracts as a 2x PNG record; sibling PNG passes through unchanged', async ({ page }) => {
  const extract = await extractRecords(page, MIXED_SVG_PAGE);
  const images = extract.records.filter((r) => r.kind === 'image') as unknown as WalkerImageRecord[];
  expect(images).toHaveLength(2);

  const [svgRecord, pngRecord] = images; // paint order: svg-img first
  expect(pngRecord.src).toBe(PNG_NAVY_24x16);

  // New behavior: the SVG data URI has been rasterized to a real PNG…
  const raster = dataUriPng(svgRecord.src);
  // …at 2x the 240x80 layout box for crispness…
  expect(pngDimensions(raster)).toEqual({ width: 480, height: 160 });
  // …while the record geometry still tracks the layout box, not the raster.
  expect(Math.round(svgRecord.w)).toBe(240);
  expect(Math.round(svgRecord.h)).toBe(80);
  expect(Math.round(svgRecord.x)).toBe(88);
  expect(Math.round(svgRecord.y)).toBe(72);
});

test('undecodable SVG keeps its raw data URI and warns instead of throwing', async ({ page }) => {
  const warnings: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'warning') warnings.push(msg.text());
  });
  const extract = await extractRecords(page, BROKEN_SVG_PAGE);
  const images = extract.records.filter((r) => r.kind === 'image') as unknown as WalkerImageRecord[];
  // Fallback = exactly today's behavior: the raw SVG URI flows through…
  expect(images).toHaveLength(1);
  expect(images[0].src).toBe(SVG_BROKEN);
  // …but the raster attempt must announce itself (proves the new code ran).
  expect(warnings.some((w) => w.includes('svg raster failed'))).toBe(true);
});

test('end-to-end: SVG deck through the real sidecar has no svg media / svgBlip / placeholder', async ({ page }) => {
  const extract = await extractRecords(page, MIXED_SVG_PAGE);
  const payload = {
    title: 'P5 SVG deck (records e2e)',
    font_mode: 'universal',
    slides: [{ width: extract.width, height: extract.height, records: extract.records, notes: '' }],
  };

  const workDir = mkdtempSync(join(tmpdir(), 'p5-records-e2e-'));
  try {
    const outPath = join(workDir, 'out.pptx');
    execFileSync('node', [SIDECAR_BUNDLE, '-', outPath], {
      input: JSON.stringify(payload),
    });
    const entries = readZipEntries(readFileSync(outPath));

    const names = [...entries.keys()];
    expect(names.filter((n) => n.startsWith('ppt/media/') && n.endsWith('.svg'))).toEqual([]);

    const slideXml = entries.get('ppt/slides/slide1.xml')!.toString('utf8');
    expect(slideXml).not.toContain('svgBlip');

    // jszip writes explicit directory entries (`ppt/media/`) — skip those.
    const mediaNames = names.filter((n) => n.startsWith('ppt/media/') && !n.endsWith('/'));
    expect(imgBrokenSha256()).toBe(IMG_BROKEN_SHA256); // tripwire vs. bundle drift
    const mediaShas = mediaNames.map((n) =>
      createHash('sha256').update(entries.get(n)!).digest('hex'),
    );
    expect(mediaShas).not.toContain(IMG_BROKEN_SHA256);

    // Media = the untouched 24x16 control PNG + the 480x160 SVG raster.
    const dims = mediaNames
      .map((n) => pngDimensions(entries.get(n)!))
      .sort((a, b) => a.width - b.width);
    expect(dims).toEqual([
      { width: 24, height: 16 },
      { width: 480, height: 160 },
    ]);
  } finally {
    rmSync(workDir, { recursive: true, force: true });
  }
});
