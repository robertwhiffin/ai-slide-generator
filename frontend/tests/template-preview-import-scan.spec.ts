/**
 * Unit + rendering tests for the template-preview `@import` scan (stripCssImports).
 *
 * WHY THIS FILE EXISTS. Three rounds of review found tokenizer defects in this scan, and
 * each round's evidence lived only in throwaway harness scripts — so nothing stopped a
 * regression. These are those cases, committed.
 *
 * WHY IT IS A PLAYWRIGHT SPEC. This repo has NO frontend unit-test runner: no vitest, no
 * jest, no `*.test.ts` anywhere under src. Playwright is the only frontend test mechanism
 * there is, so the cases go here rather than staying external. The scan itself is pure
 * string work, so most of this imports the module directly and never opens a page; the
 * claims that are about RENDERING use `page.setContent`. Nothing here navigates to
 * `baseURL`, deliberately — the shared config points at a dev server on :3000 that may be
 * serving another worktree, and a stale server must not be able to turn these green.
 */
import { test, expect } from '@playwright/test';

import { PREVIEW_CSP, stripCssImports } from '../src/components/config/templatePreviewDoc';

// The one that must always go: an ordinary external webfont import, semicolons and all.
const ORDINARY_IMPORT =
  "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');";

test.describe('stripCssImports removes a real at-rule and nothing else', () => {
  test('an ordinary leading @import is removed (positive control)', () => {
    expect(stripCssImports(`${ORDINARY_IMPORT}\n.x { color: red }`)).toBe(
      '\n.x { color: red }',
    );
  });

  test('a NBSP before the @import means there is no at-rule to remove', () => {
    // U+00A0 is an IDENT code point, not CSS white space: it starts an ident, which opens
    // a qualified rule whose prelude swallows the `@import`. Nothing here is an at-rule,
    // so the sheet must come back untouched.
    const css = '\u00a0@import url(https://example.invalid/x.css);\n.x { color: rgb(1, 2, 3); }';
    expect(stripCssImports(css)).toBe(css);
  });

  test('an escaped paren inside an unquoted url() does not end the rule early', () => {
    // `\)` is DATA, so the whole line is ONE valid @import. Cutting at the `;` after it
    // used to leave a malformed `bar.css);` fragment behind in the sheet.
    const css = '@import url(https://example.invalid/foo\\);bar.css);\n.x { color: red }';
    expect(stripCssImports(css)).toBe('\n.x { color: red }');
  });

  test('@importé is a different at-keyword and is left alone', () => {
    const css = "@importé url('https://example.invalid/x.css');\n.x { color: red }";
    expect(stripCssImports(css)).toBe(css);
  });

  test('@import followed by NUL is a different at-keyword and is left alone', () => {
    // CSS preprocessing turns NUL into U+FFFD, an ident code point.
    const css = '@import\u0000url(x);.x{color:red}';
    expect(stripCssImports(css)).toBe(css);
  });

  test('an escaped semicolon in a declaration value is not a statement boundary', () => {
    // The round-3 blocker. `\;` kept the `--lesson` declaration open, so the `@import`
    // after it is a VALUE, not an at-rule. Removing it shortened the value so that it ran
    // on and swallowed `--after`.
    const css =
      ":root{--lesson:\\;@import url('inert.css');--after:#123456}.ok{color:var(--after)}";
    expect(stripCssImports(css)).toBe(css);
  });

  test('a lone CR ends an unterminated string, so the rule after it survives', () => {
    // CSS normalises a lone CR to LF, which ends an unterminated string. Recognising only
    // LF let the string swallow the rest of the sheet, and the removal then took `.y` with
    // it. Chosen because it DISCRIMINATES: with the CR honoured the removal stops at the
    // `;` and `.y` survives; without it, the whole sheet is consumed.
    const css = '@import "u\r;.y{color:blue}';
    expect(stripCssImports(css)).toBe('.y{color:blue}');
  });
});

test.describe('the four behaviours the card/viewer e2e specs pin', () => {
  // Verbatim from tests/e2e/template-cards.spec.ts. These must not shift.
  test('a commented-out @import, and the rule after it, survive', () => {
    const css =
      '.slide{position:absolute;inset:0;width:1280px;height:720px;}' +
      "/* @import url('https://inert.example/old.css') is disabled */\n" +
      '.after{color:#123456;}\n' +
      'pre::before{content:"@import url(\'inert.css\');";}';
    expect(stripCssImports(css)).toBe(css);
  });

  test('the token sheet loses its webfont import and keeps everything else', () => {
    const css =
      "@import url('https://fonts.example/css2?family=Acme+Display:wght@400;500;600;700');\n" +
      ':root{--brand-core-primary:#123456;}';
    expect(stripCssImports(css)).toBe('\n:root{--brand-core-primary:#123456;}');
  });

  test('an @import in a declaration value is not an at-rule', () => {
    const css = ":root{--lesson:@import url('inert.css');--after:#123456}";
    expect(stripCssImports(css)).toBe(css);
  });

  test('visible HTML text that looks like CSS is not stylesheet text', () => {
    // stripCssImports is only ever applied to stylesheet text; page text reaches it only
    // if a caller misroutes it. Pinning the string form keeps that contract visible.
    const text = "@import url('theme.css'); keep this lesson text";
    expect(stripCssImports(text)).toBe(' keep this lesson text');
  });
});

test.describe('measured in the browser, not just as strings', () => {
  test('the escaped-semicolon sheet still declares the following custom property', async ({
    page,
  }) => {
    // The defect was only visible as RENDERING: `--after` stopped being declared, so
    // every `var(--after)` fell back and `.ok` went black.
    const css =
      ":root{--lesson:\\;@import url('inert.css');--after:#123456}.ok{color:var(--after)}";
    const scanned = stripCssImports(css);

    for (const [label, sheet] of [
      ['original', css],
      ['scanned', scanned],
    ] as const) {
      await page.setContent(
        `<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" ` +
          `content="${PREVIEW_CSP}"><style>${sheet}</style></head>` +
          `<body><div class="ok">probe</div></body></html>`,
        { waitUntil: 'load' },
      );
      const measured = await page.evaluate(() => ({
        after: getComputedStyle(document.documentElement)
          .getPropertyValue('--after')
          .trim(),
        color: getComputedStyle(document.querySelector('.ok')!).color,
      }));
      expect(measured.after, `${label}: --after must still be declared`).toBe('#123456');
      expect(measured.color, `${label}: .ok must resolve var(--after)`).toBe(
        'rgb(18, 52, 86)',
      );
    }
  });
});
