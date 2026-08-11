// Slide-root background-transfer probe.
//
// Runs the REAL PREPROCESS_SOURCE against a slide HTML in a real chromium
// page and reports what transferSlideRootBackground() actually returned,
// plus the body background it actually left behind. The emitted .pptx is the
// proof that the export is correct; this probe is how we assert the *branch*
// taken — in particular that the 'no-root' sentinel is still reachable for
// genuinely rootless input, which no artifact can show on its own (a rootless
// deck and a broken locator both end up white).
//
// usage:  node probe_bg_transfer.mjs <slide.html> [...]
// stdout: one JSON object per input, in order:
//         { file, bgTransferred, bodyBackgroundColor }

import { chromium } from 'playwright';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { PREPROCESS_SOURCE } from './preprocess.mjs';

const launchOptions = {
  headless: true,
  channel: 'chromium',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
};

async function main() {
  const files = process.argv.slice(2);
  if (!files.length) {
    console.error('Usage: node probe_bg_transfer.mjs <slide.html> [...]');
    process.exit(1);
  }

  const browser = await chromium.launch(launchOptions);
  try {
    for (const file of files) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
      const page = await ctx.newPage();
      await page.goto(pathToFileURL(path.resolve(file)).href);
      const result = await page.evaluate(PREPROCESS_SOURCE);
      const bodyBackgroundColor = await page.evaluate(
        'window.getComputedStyle(document.body).backgroundColor'
      );
      console.log(JSON.stringify({
        file: path.basename(file),
        bgTransferred: result.bgTransferred,
        bodyBackgroundColor,
      }));
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error('[probe-bg] FAIL:', err.stack || err);
  process.exit(1);
});
