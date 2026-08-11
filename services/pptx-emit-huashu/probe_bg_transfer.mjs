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
//         { file, bgTransferred, bodyBackgroundColor, title, timedOut, error,
//           counts, ms }
//
// `ms` times the preprocess pass itself (page already loaded), which is how the
// slide-root walk's cost is shown to scale with wrapper-chain depth rather than
// with browser startup.
//
// PROBE_EVALUATE_TIMEOUT_MS (opt-in, off by default) bounds that pass and
// reports `timedOut: true` instead of waiting for it. A preprocess pass that
// never returns is a real failure mode — a hostile page script can make the
// slide-root walk non-terminating (see tests/fixtures/export_slide_root/
// hostile_*.html) — and "the probe hung" is not a result a test can assert on.
// Turning non-termination into DATA is what lets the hostile-realm suite state
// it as an ordinary expectation. `error` does the same for the pass RAISING,
// which is the other way those fixtures stop the export. `title` carries
// whatever the page published there, which those fixtures use to report that
// their poisoning took effect.

import { chromium } from 'playwright';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { PREPROCESS_SOURCE } from './preprocess.mjs';

const launchOptions = {
  headless: true,
  channel: 'chromium',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
};

const EVALUATE_TIMEOUT_MS = Number(process.env.PROBE_EVALUATE_TIMEOUT_MS || 0);

// A page whose JS never yields cannot be asked anything more, so the timeout
// path reports what it knows and skips the follow-up reads rather than adding a
// second wait to every hostile case.
const TIMED_OUT = Symbol('timed-out');

// Hanging is not the only way a hostile realm stops the pass. An endless
// [Symbol.iterator] makes `Array.from()` grow a result array until it exceeds
// the maximum array length and RAISES — measured: `RangeError: Invalid array
// length` out of flattenMonospaceCodeBlocks. That kills the export just as
// dead, and letting it take the probe process down with it would report the
// whole run as infrastructure failure rather than as the fixture's outcome. So a
// throwing pass is DATA too, for the same reason non-termination is.
class PassFailed {
  constructor(message) {
    this.message = message;
  }
}

async function evaluatePreprocess(page) {
  try {
    return await page.evaluate(PREPROCESS_SOURCE);
  } catch (error) {
    // First line only: the stack names this file's own frames, which would make
    // the reported message move whenever the sidecar is edited.
    return new PassFailed(String((error && error.message) || error).split('\n')[0]);
  }
}

async function runPreprocess(page) {
  if (EVALUATE_TIMEOUT_MS <= 0) return evaluatePreprocess(page);
  let timer;
  try {
    return await Promise.race([
      evaluatePreprocess(page),
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(TIMED_OUT), EVALUATE_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

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
      // Read before the pass: a page that hangs cannot answer afterwards, and
      // the fixtures publish their self-report here at load time.
      const title = await page.title();
      const startedAt = Date.now();
      const result = await runPreprocess(page);
      const ms = Date.now() - startedAt;
      const timedOut = result === TIMED_OUT;
      const failed = result instanceof PassFailed;
      const returned = !timedOut && !failed;
      const bodyBackgroundColor = returned
        ? await page.evaluate('window.getComputedStyle(document.body).backgroundColor')
        : null;
      console.log(JSON.stringify({
        file: path.basename(file),
        bgTransferred: returned ? result.bgTransferred : null,
        bodyBackgroundColor,
        title,
        timedOut,
        // null when the pass returned. Non-null names the other failure mode, so
        // "did not hang" and "did not raise" are separable expectations.
        error: failed ? result.message : null,
        // The pass's whole return value: every count it reports, which is how the
        // per-pass ELEMENT COUNTS are compared between a benign document and its
        // hostile twin (same elements, or the counts differ).
        counts: returned ? result : null,
        ms,
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
