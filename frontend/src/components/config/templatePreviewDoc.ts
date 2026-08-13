/**
 * Sandboxed template-preview DOCUMENT builder — the security-critical core
 * shared by the card thumbnails and the expanded viewer.
 *
 * Pure functions only (no React), so the single hardened document builder can
 * be reused by both surfaces and unit-reasoned about in isolation. The output
 * is only ever rendered inside a FULLY-sandboxed iframe (`sandbox=""` — no
 * scripts, no same-origin); this module supplies the second layer, a strict
 * CSP that blocks the passive-fetch channel sandbox does not cover.
 */

import {
  slideHostFrameStyle,
  SLIDE_FRAME_H,
  SLIDE_FRAME_W,
} from '../../services/slideDocument';

/**
 * CSP for the preview document: uploaded template HTML/CSS must not be able
 * to trigger ANY external network fetch from the frame (img/link tags, css
 * url()/@import — passive egress). The legit live render only needs inline
 * styles plus data:/blob: resources: the /source endpoint resolves
 * {{ds-asset:ID}} handles to data: URIs at serve time, and token CSS arrives
 * inline. sandbox="" on the iframe already blocks scripts/same-origin; this
 * closes the passive-fetch channel sandbox does not.
 */
export const PREVIEW_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:;";

/**
 * A {{ds-asset:ID}} handle that still reaches the builder (a backend that
 * predates serve-time resolution, or an id its resolver could not satisfy)
 * would resolve as a relative URL inside the frame and be refused by the CSP
 * above — one failed-resource console error per occurrence, in every card.
 * Neutralize to the inert `data:,` placeholder (the import rewrite's own
 * convention for unresolvable refs): renders as nothing, never fetches.
 */
const DS_ASSET_HANDLE_RE = /\{\{ds-asset:\d+\}\}/g;

/**
 * An `@import` pulling an EXTERNAL stylesheet — Claude Design bundles reach for
 * a Google Fonts family (`@import url('https://fonts.googleapis.com/css2?...')`
 * in their colors_and_type.css) whose files their own fonts/ directory does not
 * ship.
 *
 * PREVIEW_CSP refuses it: `style-src` allows 'unsafe-inline' and nothing else,
 * deliberately. That is not a gap to widen — an @import URL is attacker-chosen
 * text, so allowing a stylesheet host would hand uploaded USER CONTENT exactly
 * the egress channel this frame exists to deny. The slide/export path is a
 * different trust context and already allows the font hosts (SLIDE_CSP), so the
 * family still loads where decks are actually rendered.
 *
 * The refusal is correct but NOISY: one CSP violation per card, every load.
 * Dropping the rule keeps the frame quiet and costs nothing real — the bundle's
 * font stacks name a self-hosted family after the remote one (e.g.
 * `--font-display: <remote>, <self-hosted>, system-ui`) and those @font-face
 * rules arrive as base64 `data:` URIs that `font-src data:` already permits.
 *
 * EVERY `@import` goes, not just external ones: `style-src 'unsafe-inline'` does
 * not admit `data:` either (measured — "Loading the stylesheet 'data:text/css,…'
 * violates … style-src 'unsafe-inline'"), so a data: import is equally dead and
 * equally noisy, and rewriting an external one to `data:,` would just trade one
 * violation for another. Inline `<style>` is how CSS legitimately reaches this
 * frame; @import never works here at all.
 *
 * The URL can itself contain semicolons (`...wght@400;500;600;700`), so the rule
 * cannot be matched to the first `;` — it has to be followed through its
 * bracketing. {@link skipImportAtRule} tracks paren depth for exactly that.
 *
 * SCOPE is the other half of getting this right. A text-level pattern over the
 * whole document does not remove an at-rule, it removes anything SHAPED like
 * one, wherever it appears:
 *
 *   - `pre::before{content:"@import url('x');";color:red}` — the declaration is
 *     CSS *data*, not an at-rule; erasing it silently empties the pseudo-element.
 *   - `<pre>@import url('theme.css'); keep this text</pre>` — VISIBLE PAGE TEXT.
 *     Documentation-style templates legitimately show CSS to the reader.
 *   - an `@import` COMMENTED OUT in the sheet, followed by a real rule — the
 *     match runs out of the comment and eats the rule after it.
 *
 * So the removal is CSS-aware and applied ONLY to stylesheet text: `<style>`
 * element content (see {@link stripImportsFromStyleElements}) and the token CSS,
 * which is a stylesheet in its own right. Inside that text, quoted string
 * literals and comments are copied through untouched, so an `@import` that is
 * merely being *quoted* or *commented out* survives — only a real at-rule goes.
 *
 * GRAMMAR is the last part, and being CSS-aware about strings and comments is not
 * enough on its own. An at-keyword only starts an at-rule at a RULE POSITION. In
 * a declaration VALUE the same text is just a value, and CSS allows no at-rule
 * there — so removing it is not "removing an at-rule", it is corrupting a
 * declaration, and it takes that declaration's `;` with it:
 *
 *   in    :root{--lesson:@import url('inert.css');--after:#123456}
 *   out   :root{--lesson:--after:#123456}
 *
 * `--after` is then never declared and every `var(--after)` in the sheet falls
 * back — a following declaration EATEN by the removal of the one before it.
 * {@link atRulePosition} is what confines the removal to the positions CSS
 * actually admits one.
 *
 * Inline `style="..."` attributes are deliberately NOT scanned: an at-rule is
 * invalid in a declaration list, so `@import` there never loads anything and has
 * no violation to silence.
 *
 * KNOWN AND ACCEPTED: an ESCAPED at-keyword (`@\69mport url(...)`) is a valid
 * spelling that a browser honours, and this scan does not recognise it. That is a
 * deliberate limit, not an oversight. The scan is not a security control —
 * PREVIEW_CSP (`style-src 'unsafe-inline'` and nothing else) plus `sandbox=""`
 * deny the fetch for every spelling equally, escaped or not. All the scan does is
 * drop a rule that is ALREADY dead so it stops logging one console violation per
 * card, so an escaped keyword costs exactly one console line and no egress.
 * Teaching the scan CSS ident escapes would widen the very machinery whose
 * over-reach caused the declaration-value bug above, for no security gain; the
 * narrow scan is the point. Pinned by an e2e test so the limit stays documented
 * and the no-egress claim stays measured.
 */
const IMPORT_AT_KEYWORD = '@import';

/** CSS ident characters, used to keep `@import` from matching `@imports`. */
const IDENT_CHAR_RE = /[A-Za-z0-9_-]/;

/** CSS white space, which never ends a rule position. */
const WHITESPACE_RE = /\s/;

/**
 * Index just past the string literal starting at `start`.
 *
 * Backslash escapes are skipped as a unit so an escaped quote does not end the
 * string early. An unterminated string ends at the newline, as CSS says it does,
 * rather than swallowing the remainder of the sheet.
 */
function skipString(css: string, start: number): number {
  const quote = css[start];
  let index = start + 1;
  while (index < css.length) {
    const char = css[index];
    if (char === '\\') {
      index += 2;
      continue;
    }
    if (char === quote) return index + 1;
    if (char === '\n') return index;
    index += 1;
  }
  return css.length;
}

/** Index just past the CSS block comment starting at `start`. */
function skipComment(css: string, start: number): number {
  const close = css.indexOf('*/', start + 2);
  return close < 0 ? css.length : close + 2;
}

/** Whether a real `@import` at-keyword (not `@imports`, `@import-x`) starts here. */
function startsImportAtRule(css: string, start: number): boolean {
  const candidate = css.slice(start, start + IMPORT_AT_KEYWORD.length);
  if (candidate.toLowerCase() !== IMPORT_AT_KEYWORD) return false;
  const next = css[start + IMPORT_AT_KEYWORD.length];
  return next === undefined || !IDENT_CHAR_RE.test(next);
}

/**
 * Index just past the `@import` at-rule starting at `start`.
 *
 * The prelude is followed through its own bracketing rather than to the first
 * `;`, so a `;` inside `url(...)` or inside a quoted string does not end it
 * early — that is what keeps a webfont URL such as `...wght@400;500;600;700`
 * from being cut in half and leaving an orphaned fragment behind.
 *
 * An at-rule with no block ends at its `;`, which is consumed.
 *
 * The two ways that can fail to happen are handled the way a CSS parser handles
 * them, so what is removed matches what a browser would refuse to apply:
 *
 *  - a `{` arrives first: per CSS Syntax, consuming an at-rule takes the block
 *    that follows, and `@import` does not accept one, so the whole at-rule
 *    INCLUDING that block is invalid and dropped. The block is consumed
 *    (brace-balanced) rather than left behind as a dangling `{...}` fragment.
 *  - a `}` arrives first: that brace closes an ENCLOSING block, so the at-rule
 *    ended without a terminator. The scan stops without consuming it, leaving
 *    the enclosing structure intact.
 */
function skipImportAtRule(css: string, start: number): number {
  let index = start + IMPORT_AT_KEYWORD.length;
  let parenDepth = 0;
  while (index < css.length) {
    const char = css[index];
    if (char === '"' || char === "'") {
      index = skipString(css, index);
      continue;
    }
    if (char === '/' && css[index + 1] === '*') {
      index = skipComment(css, index);
      continue;
    }
    if (char === '(') {
      parenDepth += 1;
    } else if (char === ')') {
      parenDepth = Math.max(0, parenDepth - 1);
    } else if (parenDepth === 0) {
      if (char === ';') return index + 1;
      if (char === '{') return skipBlock(css, index);
      if (char === '}') return index;
    }
    index += 1;
  }
  return css.length;
}

/**
 * Index just past the brace-balanced `{ ... }` block starting at `start`.
 *
 * Strings and comments are skipped so a brace inside either does not throw the
 * balance off.
 */
function skipBlock(css: string, start: number): number {
  let index = start;
  let depth = 0;
  while (index < css.length) {
    const char = css[index];
    if (char === '"' || char === "'") {
      index = skipString(css, index);
      continue;
    }
    if (char === '/' && css[index + 1] === '*') {
      index = skipComment(css, index);
      continue;
    }
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
    index += 1;
  }
  return css.length;
}

/**
 * Remove every `@import` at-rule from ONE stylesheet's text.
 *
 * Everything that is not an at-rule is copied through byte-for-byte, including
 * string literals and comments that merely happen to contain the word `@import`,
 * and declaration values that contain it. A sheet with no `@import` at-rule
 * therefore comes back identical to what went in.
 *
 * `atStatementStart` tracks the one piece of grammar this needs. A rule — or an
 * at-rule — can only begin where the previous construct ended: at the start of the
 * sheet, or after a `;`, `{` or `}`. Anywhere else the scanner is partway through a
 * selector or a declaration, and an at-keyword there does not start an at-rule at
 * all. Whitespace and comments are transparent, exactly as they are to a CSS
 * parser; any other token ends the rule position.
 *
 * That makes an `@import` at the top of a sheet, after a rule, or inside an
 * `@media`/`@supports` block an at-rule (all removed), while one inside a
 * declaration value is left exactly where it is.
 *
 * The flag only ever gates a REMOVAL, so it is deliberately conservative: too few
 * removals leaves a dead rule in place and costs one console violation, while too
 * many destroy author CSS.
 */
export function stripCssImports(css: string): string {
  let out = '';
  let index = 0;
  let atStatementStart = true;
  while (index < css.length) {
    const char = css[index];
    if (char === '"' || char === "'") {
      const end = skipString(css, index);
      out += css.slice(index, end);
      index = end;
      // A string literal is a token like any other: it can only appear partway
      // through a construct, so it ends the rule position.
      atStatementStart = false;
      continue;
    }
    if (char === '/' && css[index + 1] === '*') {
      const end = skipComment(css, index);
      out += css.slice(index, end);
      index = end;
      // Comments are transparent — a rule may still start after one.
      continue;
    }
    if (char === '@' && atStatementStart && startsImportAtRule(css, index)) {
      index = skipImportAtRule(css, index);
      // The at-rule (and its terminating `;`) is gone, so the next construct
      // starts here — which is what lets consecutive `@import`s all be removed.
      atStatementStart = true;
      continue;
    }
    if (char === ';' || char === '{' || char === '}') {
      atStatementStart = true;
    } else if (!WHITESPACE_RE.test(char)) {
      atStatementStart = false;
    }
    out += char;
    index += 1;
  }
  return out;
}

/**
 * Strip `@import` from every `<style>` in the parsed layout, in place.
 *
 * Rewriting the parsed DOM instead of the HTML source is what confines the
 * removal to CSS: an `@import` sitting in a text node is not in a stylesheet and
 * is never touched. `<style>` is a raw-text element, so its content round-trips
 * through serialization unescaped. Each element is written back only when it
 * actually changed, so a layout with no `@import` serializes byte-identically.
 */
function stripImportsFromStyleElements(doc: Document): void {
  doc.querySelectorAll('style').forEach((style) => {
    const css = style.textContent ?? '';
    const stripped = stripCssImports(css);
    if (stripped !== css) style.textContent = stripped;
  });
}

/**
 * Slide roots inside a template layout. Templates mark each slide section with
 * the `slide` class (on `<section>` or `<div>` — see the backend's
 * `_detect_slide_root_tags`), which is what makes a multi-slide template
 * paginable in the viewer.
 */
const SLIDE_ROOT_SELECTOR = '.slide';

/**
 * The fixed 16:9 stage a preview renders into (the deck canvas the cards scale).
 * Aliases the shared slide frame so the pop-out and the in-app slide surfaces
 * cannot drift to different dimensions.
 */
export const PREVIEW_STAGE_W = SLIDE_FRAME_W;
export const PREVIEW_STAGE_H = SLIDE_FRAME_H;

/**
 * Preview stage shim: neutralise custom elements this frame can never upgrade,
 * and give the template's slide wrapper the fixed frame.
 *
 * Scripts NEVER run in a preview frame (`sandbox=""` plus a CSP with no
 * script-src), so a custom element used as the deck harness — Claude Design
 * exports wrap their slide sections in `<deck-stage width="1280" height="720">`
 * — is permanently un-upgraded and therefore permanently matches
 * `:not(:defined)`. Two consequences, both of which blank the whole preview:
 *
 *  1. Authors guard the pre-upgrade flash with
 *     `deck-stage:not(:defined){visibility:hidden}`. Here that hide is
 *     permanent, so every slide inherits `visibility:hidden` and the only
 *     thing left to see is the body background — the reported "dark
 *     rectangle".
 *  2. An un-upgraded custom element is display:inline and contributes no box,
 *     so it never establishes the stage the harness would have built itself.
 *
 * CASCADE: `deck-stage:not(:defined)` scores (0,1,1), so a bare `deck-stage`
 * type rule (0,0,1) would LOSE and the preview would stay blank — `!important`
 * is what actually settles it, independent of author order or specificity.
 *
 * `:not(:defined)` matches only valid-named custom elements that were never
 * registered; built-ins (and non-hyphenated unknown tags) count as defined, so
 * this cannot reach ordinary template markup.
 *
 * Sizing the stage is necessary but NOT sufficient. Inside it the template nests
 * a wrapper (`<section>`) that carries the deck background, and inside that a
 * `position: absolute` slide root — so the wrapper holds no in-flow content and
 * collapses to height 0, and the background it carries never paints (readable
 * dark-on-dark, since colour and font still inherit). {@link slideHostFrameStyle}
 * stretches the stage's child to the frame, which is what gives that wrapper
 * area; it is the same shared contract every in-app slide surface uses.
 *
 * TWO HOST SHAPES, ONE SELECTOR. The frame host is whichever body child sits on
 * the path to the slide, and uploaded templates come both ways:
 *
 *   <body><deck-stage><section><div class="slide">   custom-element harness
 *   <body><section><div class="slide">               wrapper straight under body
 *
 * `:not(:defined)` reaches only the first: it matches valid-named custom
 * elements that were never registered, and every built-in counts as defined, so
 * it can never match a `<section>`. The second shape is a supported upload (see
 * `template-cards.spec.ts`) and collapsed identically — measured 1280x0, with
 * the out-of-flow slide escaping to the viewport at 1280x800. `:has()` covers it
 * structurally: the body child that CONTAINS a slide root is the wrapper needing
 * the frame, whatever its tag.
 *
 * ONE `:is()`, NOT A COMMA LIST. The reason is the CHILD rule, not the host
 * rule. {@link slideHostFrameStyle} appends ` > :not(…)` to whatever it is
 * given, and a child combinator binds only to the LAST arm of a selector list.
 * Written with a comma, the first arm therefore degenerates into a SECOND rule
 * matching the HOST itself, stamping it with the child declarations
 * (`position:absolute; inset:0; width:100%; height:100%`). The host stops
 * holding the fixed frame and resolves against the initial containing block
 * instead. Measured on the deck-stage shape at a 1280x800 viewport, the comma
 * form gives deck-stage, `<section>` and `.slide` all 1280x800 with the host
 * computed `position: absolute` — the wrong HEIGHT, not a collapse. (1280x0 is
 * what NO frame produces; and the wrapper is still stretched, because
 * `:has(.slide)` — the last arm — also matches deck-stage, so the child rule
 * does reach its children.) `slide-host-frame.spec.ts` renders both forms and
 * measures them, so this is checked rather than asserted.
 *
 * NOT a reason: "two arms would apply the block twice". A selector list is ONE
 * rule; its declarations apply to an element once however many arms match, and
 * no page API reports an arm count. A `<deck-stage>` containing a slide
 * satisfies BOTH arms of the `:is()` today and is framed exactly once.
 *
 * `:is()` is also a FORGIVING selector list: in a browser without `:has()` the
 * unknown arm is dropped and the custom-element arm keeps working, where an
 * invalid selector in a plain comma list would invalidate the whole rule and
 * un-frame both shapes.
 *
 * DELIBERATELY BROAD. `:has()` matches a body child containing a slide root at
 * ANY depth, not only as a direct child. Narrowing it to `:has(> .slide)` was
 * measured and REJECTED: the two shapes above measure 1280x720 either way, but
 * the direct-child form regresses two reachable shapes to the 1280x800 defect —
 * a template with an intermediate wrapper (`main > article > .slide`), and a
 * standalone multi-slide export uploaded as a template. The cost of the breadth
 * is that several matching body children each become their own 720px stage;
 * they stay `position: relative` and IN FLOW (measured at 0 and 720), so a
 * multi-slide layout preview stacks and scrolls rather than piling every slide
 * at the origin as it did before this contract. All pinned by the spec.
 *
 * Two limits, both pre-existing and unchanged by the widening:
 *  - `<body><div class="slide">`, where the slide IS the body child, matches
 *    NEITHER arm — every built-in counts as defined, and a slide root does not
 *    contain one — so it is not framed and measures 1280x800.
 *  - the HOST arm can match a `.slide-wrapper`, which the CHILD arm excludes.
 *    That needs a document carrying `.slide-wrapper` AND this selector, and
 *    `buildStandaloneDeckDocument` never injects the frame, so it means an
 *    export-shaped document uploaded as a template. Measured benign: the
 *    wrappers stay in flow, 720 apart, not piled into one stack.
 *
 * Specificity is unchanged by the widening: `:is()` and `:has()` each take the
 * specificity of their most specific argument, so the host still scores (0,1,1).
 */
const PREVIEW_STAGE_SHIM =
  '<style>' +
  ':not(:defined){visibility:visible!important}' +
  'body>:not(:defined){display:block!important}' +
  slideHostFrameStyle(`body>:is(:not(:defined),:has(${SLIDE_ROOT_SELECTOR}))`) +
  '</style>';

/** Parse layout HTML inertly (no fetch, no script execution). */
function parseLayout(layoutHtml: string): Document {
  return new DOMParser().parseFromString(layoutHtml, 'text/html');
}

/**
 * How many slide sections a template layout contains (0 when it is not
 * structured as slide sections — the whole layout is then one page).
 */
export function countTemplateSlides(layoutHtml: string): number {
  try {
    return parseLayout(layoutHtml).querySelectorAll(SLIDE_ROOT_SELECTOR).length;
  } catch {
    return 0;
  }
}

/**
 * Compose the preview document: the template layout with its token
 * stylesheet resolved and preview-only overflow clipping. Rendered ONLY in a
 * fully-sandboxed iframe.
 *
 * The wrapper is SYNTHESIZED — the CSP meta is the first fetch-capable byte
 * of the document, unconditionally. Injecting into a found <head> is not
 * enough: malformed-but-parser-preserved markup (e.g. an <img> BEFORE the
 * <html> tag) would declare resources ahead of the policy. DOMParser gives
 * browser-grade handling of malformed input without fetching or executing
 * anything; the parsed head content is re-emitted AFTER the guard block and
 * the parsed body (attributes included, via its own serialization) follows.
 *
 * {@link PREVIEW_STAGE_SHIM} trails the template head so a deck harness
 * built from an unregisterable custom element still lays out and is not left
 * hidden by its own pre-upgrade guard.
 *
 * `slideIndex` isolates ONE slide section for the paginated viewer: the other
 * sections are REMOVED from the parsed DOM before serialization rather than
 * hidden with injected CSS, so the surviving slide keeps the template's own
 * cascade exactly (an author `display` value is never fought over) and no
 * extra rules are layered on. Out-of-range or non-slide layouts fall through
 * to the full document unchanged.
 */
export function buildTemplatePreviewDoc(
  layoutHtml: string,
  tokenCss: string | null,
  slideIndex?: number,
): string {
  const inlineLayout = layoutHtml.replace(DS_ASSET_HANDLE_RE, 'data:,');
  // Token CSS is a stylesheet in its own right, so it is stripped directly; the
  // layout's @import rules are stripped from its parsed <style> elements below,
  // which is what keeps the removal out of HTML text.
  const inlineTokenCss = tokenCss
    ? stripCssImports(tokenCss.replace(DS_ASSET_HANDLE_RE, 'data:,'))
    : tokenCss;
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`;
  const previewReset = '<style>html,body{margin:0;overflow:hidden}</style>';
  const guard = cspMeta + (inlineTokenCss ? `<style>${inlineTokenCss}</style>` : '') + previewReset;
  const parsed = parseLayout(inlineLayout);
  stripImportsFromStyleElements(parsed);
  if (slideIndex !== undefined) {
    const slides = Array.from(parsed.querySelectorAll(SLIDE_ROOT_SELECTOR));
    if (slides.length > 1 && slideIndex >= 0 && slideIndex < slides.length) {
      // Nothing on the path to the surviving slide may be removed.
      const keep = new Set<Element>();
      for (let n: Element | null = slides[slideIndex]; n; n = n.parentElement) keep.add(n);
      slides.forEach((slide, idx) => {
        if (idx === slideIndex) return;
        // Drop the slide, then any wrapper it leaves EMPTY. An emptied wrapper
        // is not inert: templates put the deck background on the wrapper
        // (`section`), so under the frame contract it would stretch to the full
        // stage and — being a later sibling — paint over the slide that
        // survives, blanking the preview. Walk up only while the parent has no
        // element children left, so a wrapper holding anything else stays.
        let node: Element | null = slide;
        while (node && !keep.has(node)) {
          const parent: Element | null = node.parentElement;
          node.remove();
          if (!parent || keep.has(parent) || parent.children.length > 0) break;
          node = parent;
        }
      });
    }
  }
  const templateHead = parsed.head?.innerHTML ?? '';
  const templateBody = parsed.body?.outerHTML ?? '<body></body>';
  // The shim trails the template's own head so it wins on cascade ORDER as well
  // as importance; the CSP meta stays the first fetch-capable byte regardless.
  return `<!DOCTYPE html><html><head>${guard}${templateHead}${PREVIEW_STAGE_SHIM}</head>${templateBody}</html>`;
}
