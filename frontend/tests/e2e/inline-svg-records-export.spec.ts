/**
 * dsv2 battery WB-2 — inline <svg> elements through the RECORDS export path.
 *
 * The walker's visit() covers text leaves, <img> (with SVG-src raster),
 * <canvas>, and background fills — but inline <svg> ELEMENTS had no handler:
 * visit() recursed into the SVG's children and emitted nothing, so icon
 * glyphs authored as inline <svg> vanished from the records PPTX (the huashu
 * path materializes them; Wave B measured pics 2,4,2,4,2 huashu vs
 * 2,1,1,1,2 records on the same deck).
 *
 * Artifact-level proof, driving the real WALKER_SOURCE in a real Chromium
 * page in production order (__prepareSlideForExtract, then __extractSlide)
 * and piping the records through the actual sidecar bundle:
 *  1. an inline <svg> yields a PNG image record at its layout box;
 *  2. a two-slide deck's pptx keeps BOTH slides and carries the raster
 *     media, with no .svg media / svgBlip / placeholder bytes;
 *  3. an svg-free page extracts records with no image entries at all
 *     (payload identity for decks this fix does not concern).
 *
 * Run: cd frontend && npx playwright test tests/e2e/inline-svg-records-export.spec.ts
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';
import { WALKER_SOURCE } from '../../src/services/domWalker';
import { pngDimensions, readZipEntries } from '../helpers/pptxZip';

const SIDECAR_BUNDLE = fileURLToPath(
  new URL('../../../services/pptx-emit/emit.bundle.mjs', import.meta.url),
);

// Synthetic inline icon: currentColor circle + accent path, sized by
// attributes like model-authored shield/bolt icons are.
const INLINE_SVG_ICON = `
  <svg id="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="96" height="96"
       style="position:absolute;left:88px;top:72px;color:#0B3D66">
    <circle cx="12" cy="12" r="10" fill="currentColor"/>
    <path d="M8 12h8" stroke="#E8722A" stroke-width="2" fill="none"/>
  </svg>`;

function slidePage(inner: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;}</style></head>
<body>
<section id="root" style="position:relative;width:1280px;height:720px;overflow:hidden;background:#ffffff;font-family:Arial, Helvetica, sans-serif;">
${inner}
</section>
</body></html>`;
}

const INLINE_SVG_PAGE = slidePage(`
  ${INLINE_SVG_ICON}
  <h1 style="position:absolute;left:88px;top:220px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Inline Vector Slide</h1>
`);

const TEXT_ONLY_PAGE = slidePage(`
  <h1 style="position:absolute;left:88px;top:220px;width:600px;margin:0;font-size:40px;color:#0B3D66;">Text Only Slide</h1>
`);

interface WalkerImageRecord {
  kind: 'image';
  x: number;
  y: number;
  w: number;
  h: number;
  src: string;
}

/** Production order: prepare (pre-walk mutations), then extract. */
async function prepareAndExtract(page: Page, html: string) {
  await page.setContent(html, { waitUntil: 'load' });
  await page.addScriptTag({ content: WALKER_SOURCE });
  return page.evaluate(async () => {
    const w = window as unknown as {
      __prepareSlideForExtract: (el: Element) => Promise<number>;
      __extractSlide: (el: Element) => unknown;
    };
    const root = document.getElementById('root')!;
    await w.__prepareSlideForExtract(root);
    return w.__extractSlide(root);
  }) as Promise<{ width: number; height: number; records: Record<string, unknown>[] }>;
}

function dataUriPng(src: string): Buffer {
  expect(src).toMatch(/^data:image\/png;base64,/);
  return Buffer.from(src.slice('data:image/png;base64,'.length), 'base64');
}

test('inline <svg> yields a PNG image record at its layout box', async ({ page }) => {
  const extract = await prepareAndExtract(page, INLINE_SVG_PAGE);
  const images = extract.records.filter(
    (r) => r.kind === 'image',
  ) as unknown as WalkerImageRecord[];

  // Pre-fix: the walker emitted NO image record for the inline svg at all.
  expect(images).toHaveLength(1);
  const [icon] = images;

  // Rasterized to a real PNG at 2x the 96x96 layout box…
  const raster = dataUriPng(icon.src);
  expect(pngDimensions(raster)).toEqual({ width: 192, height: 192 });
  // …with record geometry tracking the layout box, not the raster.
  expect(Math.round(icon.w)).toBe(96);
  expect(Math.round(icon.h)).toBe(96);
  expect(Math.round(icon.x)).toBe(88);
  expect(Math.round(icon.y)).toBe(72);

  // The slide's text still extracts alongside the icon.
  const texts = extract.records.filter((r) => r.kind === 'text');
  expect(texts.length).toBeGreaterThan(0);
});

test('two-slide inline-svg deck through the real sidecar keeps all slides and the svg raster', async ({ page }) => {
  const withSvg = await prepareAndExtract(page, INLINE_SVG_PAGE);
  const textOnly = await prepareAndExtract(page, TEXT_ONLY_PAGE);

  const payload = {
    title: 'WB-2 inline-svg deck (records e2e)',
    font_mode: 'universal',
    slides: [
      { width: withSvg.width, height: withSvg.height, records: withSvg.records, notes: '' },
      { width: textOnly.width, height: textOnly.height, records: textOnly.records, notes: '' },
    ],
  };

  const workDir = mkdtempSync(join(tmpdir(), 'wb2-records-e2e-'));
  try {
    const outPath = join(workDir, 'out.pptx');
    execFileSync('node', [SIDECAR_BUNDLE, '-', outPath], {
      input: JSON.stringify(payload),
    });
    const entries = readZipEntries(readFileSync(outPath));
    const names = [...entries.keys()];

    // ALL slides present.
    const slideXmls = names.filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n));
    expect(slideXmls.sort()).toEqual(['ppt/slides/slide1.xml', 'ppt/slides/slide2.xml']);

    // SVG content present — as PNG raster media, never as .svg / svgBlip.
    const mediaNames = names.filter((n) => n.startsWith('ppt/media/') && !n.endsWith('/'));
    expect(mediaNames.length).toBeGreaterThan(0);
    const dims = mediaNames.map((n) => pngDimensions(entries.get(n)!));
    expect(dims).toContainEqual({ width: 192, height: 192 });
    expect(names.filter((n) => n.startsWith('ppt/media/') && n.endsWith('.svg'))).toEqual([]);
    expect(entries.get('ppt/slides/slide1.xml')!.toString('utf8')).not.toContain('svgBlip');

    // No pptxgenjs broken-image placeholder bytes anywhere.
    const bundle = readFileSync(SIDECAR_BUNDLE, 'utf8');
    const brokenMatch = bundle.match(/IMG_BROKEN = "data:image\/png;base64,([^"]+)"/);
    expect(brokenMatch).toBeTruthy();
    const brokenSha = createHash('sha256')
      .update(Buffer.from(brokenMatch![1], 'base64'))
      .digest('hex');
    const mediaShas = mediaNames.map((n) =>
      createHash('sha256').update(entries.get(n)!).digest('hex'),
    );
    expect(mediaShas).not.toContain(brokenSha);
  } finally {
    rmSync(workDir, { recursive: true, force: true });
  }
});

test('svg-free pages still extract with no image records (payload identity)', async ({ page }) => {
  const extract = await prepareAndExtract(page, TEXT_ONLY_PAGE);
  const images = extract.records.filter((r) => r.kind === 'image');
  expect(images).toEqual([]);
});
