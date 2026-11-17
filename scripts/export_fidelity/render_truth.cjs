#!/usr/bin/env node
// Ground-truth renderer for the export fidelity harness.
//
// Screenshots each complete slide document at 1280x720 with the SAME
// Playwright build and browser channel the huashu sidecar uses, and with the
// same settle sequence (networkidle, then a canvas readiness wait), so the
// truth image and the exported slide come from one identical layout.
//
// usage: node render_truth.cjs [--scale=<n>] <out_dir> <slide.html>...
// writes <out_dir>/<basename>.png and <out_dir>/<basename>.txt (rendered text) for every input.
// --scale is the device scale factor (default 1): the layout is the same
// 1280x720, and the screenshot is n times as many pixels each way. The text
// calibration (calibrate_text.py) takes it at 2, the sidecar's own scale.

const fs = require('fs');
const path = require('path');

const SIDECAR_DIR = path.resolve(__dirname, '..', '..', 'services', 'pptx-emit-huashu');
const { chromium } = require(path.join(SIDECAR_DIR, 'node_modules', 'playwright'));

async function renderOne(browser, htmlPath, outDir, scale) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: scale });
  await page.goto('file://' + path.resolve(htmlPath));
  try {
    await page.waitForLoadState('networkidle', { timeout: 4000 });
  } catch (error) {
    // A slide may legitimately keep a request open; the screenshot still reflects it.
  }
  await page.evaluate(() => document.fonts.ready);
  const canvasCount = await page.evaluate(() => document.querySelectorAll('canvas').length);
  if (canvasCount > 0) {
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('canvas')).every((c) => c.width > 0 && c.height > 0),
      { timeout: 5000 },
    ).catch(() => {});
    await page.waitForTimeout(2000);
  }
  const outPath = path.join(outDir, path.basename(htmlPath, '.html') + '.png');
  await page.screenshot({ path: outPath, clip: { x: 0, y: 0, width: 1280, height: 720 } });
  // The text-loss reference: what the browser itself renders as text. SVG and
  // canvas text travels inside a picture in the export, so it is excluded.
  // Hiding them happens after the screenshot, so it cannot affect the truth image.
  const renderedText = await page.evaluate(() => {
    for (const graphic of document.querySelectorAll('svg, canvas')) graphic.style.display = 'none';
    return document.body.innerText;
  });
  fs.writeFileSync(outPath.replace(/\.png$/, '.txt'), renderedText, 'utf-8');
  await page.close();
  return outPath;
}

async function main() {
  const argv = process.argv.slice(2);
  let scale = 1;
  if (argv.length && argv[0].startsWith('--scale=')) {
    scale = Number(argv.shift().slice('--scale='.length));
  }
  const [outDir, ...htmlPaths] = argv;
  if (!outDir || htmlPaths.length === 0 || !(scale > 0)) {
    console.error('usage: node render_truth.cjs [--scale=<n>] <out_dir> <slide.html>...');
    process.exit(1);
  }
  const launchOptions = process.platform === 'darwin'
    ? { channel: 'chrome' }
    : { args: ['--no-sandbox', '--disable-dev-shm-usage'] };
  const browser = await chromium.launch(launchOptions);
  try {
    for (const htmlPath of htmlPaths) {
      console.log(await renderOne(browser, htmlPath, outDir, scale));
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
