#!/usr/bin/env node
// Test-side browser measurement for the snapshot-engine export tests.
//
// Loads one complete slide document with the SAME Playwright build and browser
// channel the huashu sidecar uses, on the same 1280x720 viewport at device scale
// 2 (render_slide.cjs's page), and with the same settle sequence: networkidle,
// document.fonts.ready, the canvas wait, then every animation finished. So the
// rect it reports comes from the layout the export itself reads.
//
// usage: node measure.cjs <document.html> <selector> [index]
// prints {"x":…,"y":…,"w":…,"h":…}: getBoundingClientRect() of the index-th
// (default 0) match of selector, in CSS px. Exits 2 when nothing matches.
//
// Called from tests/fixtures/export_snapshot_support.py::browser_rect.

const path = require('path');

const SIDECAR_DIR = path.resolve(__dirname, '..', '..', '..', 'services', 'pptx-emit-huashu');
const { chromium } = require(path.join(SIDECAR_DIR, 'node_modules', 'playwright'));

function launchOptions() {
  // Same launch as html2pptx.js: Chrome on macOS, Chromium without the sandbox
  // elsewhere, and the inherited env so LD_LIBRARY_PATH reaches the browser.
  const options = { env: { ...process.env } };
  if (process.platform === 'darwin') {
    options.channel = 'chrome';
  } else {
    options.args = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'];
  }
  return options;
}

async function settle(page) {
  try {
    await page.waitForLoadState('networkidle', { timeout: 4000 });
  } catch (error) {
    // A slide may legitimately keep a request open; the sidecar ignores this too.
  }
  await page.evaluate(() => document.fonts.ready);
  const canvasCount = await page.evaluate(() => document.querySelectorAll('canvas').length);
  if (canvasCount > 0) {
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('canvas')).every((canvas) => canvas.width > 0 && canvas.height > 0),
      { timeout: 5000 },
    ).catch(() => {});
    await page.waitForTimeout(2000);
  }
  // The settled state: an entrance animation is measured where it ends. Each
  // finish() is guarded on its own, because an infinite animation throws.
  await page.evaluate(() => {
    const animations = document.getAnimations();
    for (let index = 0; index < animations.length; index++) {
      try {
        animations[index].finish();
      } catch (error) {
        // An infinite animation cannot finish; it is measured as it stands.
      }
    }
  });
}

async function measureRect(page, selector, index) {
  return page.evaluate(({ selector, index }) => {
    const matches = document.querySelectorAll(selector);
    if (index >= matches.length) {
      return { error: `selector ${selector} matched ${matches.length} element(s); index ${index} is out of range` };
    }
    const rect = matches[index].getBoundingClientRect();
    return { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
  }, { selector, index });
}

async function main() {
  const [documentPath, selector, indexArgument] = process.argv.slice(2);
  if (!documentPath || !selector) {
    console.error('usage: node measure.cjs <document.html> <selector> [index]');
    process.exit(1);
  }
  const index = indexArgument === undefined ? 0 : Number.parseInt(indexArgument, 10);
  if (!Number.isInteger(index) || index < 0) {
    console.error(`index must be a non-negative integer, got ${indexArgument}`);
    process.exit(1);
  }
  const browser = await chromium.launch(launchOptions());
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 });
    await page.goto('file://' + path.resolve(documentPath));
    await settle(page);
    const rect = await measureRect(page, selector, index);
    if (rect.error) {
      console.error(rect.error);
      process.exitCode = 2;
      return;
    }
    process.stdout.write(JSON.stringify(rect) + '\n');
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
