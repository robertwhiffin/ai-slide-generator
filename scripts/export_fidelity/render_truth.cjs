#!/usr/bin/env node
// Ground-truth renderer for the export fidelity harness.
//
// Screenshots each complete slide document at 1280x720 with the SAME
// Playwright build and browser channel the huashu sidecar uses, and with the
// same settle sequence (networkidle, then a canvas readiness wait), so the
// truth image and the exported slide come from one identical layout.
//
// usage: node render_truth.cjs <out_dir> <slide.html>...
// writes <out_dir>/<basename>.png for every input.

const path = require('path');

const SIDECAR_DIR = path.resolve(__dirname, '..', '..', 'services', 'pptx-emit-huashu');
const { chromium } = require(path.join(SIDECAR_DIR, 'node_modules', 'playwright'));

async function renderOne(browser, htmlPath, outDir) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
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
  await page.close();
  return outPath;
}

async function main() {
  const [outDir, ...htmlPaths] = process.argv.slice(2);
  if (!outDir || htmlPaths.length === 0) {
    console.error('usage: node render_truth.cjs <out_dir> <slide.html>...');
    process.exit(1);
  }
  const launchOptions = process.platform === 'darwin'
    ? { channel: 'chrome' }
    : { args: ['--no-sandbox', '--disable-dev-shm-usage'] };
  const browser = await chromium.launch(launchOptions);
  try {
    for (const htmlPath of htmlPaths) {
      console.log(await renderOne(browser, htmlPath, outDir));
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
