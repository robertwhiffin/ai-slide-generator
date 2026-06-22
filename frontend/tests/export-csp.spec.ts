import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';
import { SLIDE_CSP } from '../src/services/slideDocument';
// Import the doc builder used by screenshotCapture (export it if not already).
import { buildSlideHtml } from '../src/services/screenshotCapture';

test('screenshot export document carries the slide CSP', () => {
  // NB: SlideDeck uses snake_case `external_scripts` (see screenshotCapture.ts:21).
  const deck = { slides: [{ html: '<div class="slide">x</div>', scripts: '' }], css: '', external_scripts: [] } as any;
  const doc = buildSlideHtml(deck, 0);
  expect(doc).toContain('Content-Security-Policy');
  expect(doc).toContain(SLIDE_CSP);
});

// Regression: the slide CSP must NOT grant 'unsafe-eval', and the domWalker
// export path must therefore not depend on eval(). Injecting SLIDE_CSP into
// domWalker's composite while it still used iframe.contentWindow.eval(...) broke
// the editable-PPTX / Google-Slides export at runtime (EvalError). The walker now
// drives extraction via direct same-origin DOM/function calls.
test('slide CSP withholds unsafe-eval', () => {
  expect(SLIDE_CSP).not.toContain('unsafe-eval');
});

test('domWalker performs no eval() (would throw under the slide CSP)', () => {
  const src = readFileSync(
    fileURLToPath(new URL('../src/services/domWalker.ts', import.meta.url)),
    'utf8',
  );
  // Strip line comments so the AISEC-248 explanatory comments don't trip this.
  const code = src.replace(/\/\/.*$/gm, '');
  expect(code).not.toMatch(/\beval\s*\(/);
  expect(code).not.toMatch(/\.eval\b/);
});
