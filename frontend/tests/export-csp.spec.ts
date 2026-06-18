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
