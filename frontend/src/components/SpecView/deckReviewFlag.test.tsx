/**
 * E2b — "Agentic deck review in progress" flag.
 *
 * Four assertions, split across two groups so shape and behaviour never share
 * a test (rule 7 from the standing instructions — a mixed test passes when a
 * different assertion in the same test fired):
 *
 *   1. Timing formula: three behaviour tests against _isReviewInProgress.
 *   2. Non-blocking: one source-scan test proving reviewInProgress is absent
 *      from every disabled= expression in the shipped files.
 *   3. Badge: one render test per visible/absent state (shape, not behaviour).
 *
 * Sabotage target for the NON-BLOCKING test:
 *   In page-header.tsx, change ONE of the `disabled={isGenerating}` lines on
 *   an export DropdownMenuItem to `disabled={isGenerating || reviewInProgress}`.
 *   The non-blocking test goes red.  Revert, confirm it goes green.
 */
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { render, screen } from '@testing-library/react';
import { _isReviewInProgress } from '../Layout/AppLayout';
import { SpecView } from './SpecView';
import type { SlideDeck } from '../../types/slide';

// ── helpers ───────────────────────────────────────────────────────────────────

const REPO_ROOT = resolve(__dirname, '../../../../');

function readSource(relPath: string): string {
  return readFileSync(resolve(REPO_ROOT, relPath), 'utf8');
}

function makeMinimalDeck(): SlideDeck {
  return {
    title: '',
    slide_count: 0,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: [],
  };
}

// ── 1. Timing formula ─────────────────────────────────────────────────────────
//
// These are pure-function behaviour tests.  No React rendering.
// Each test exercises a single distinct condition of the formula.

describe('_isReviewInProgress — timing formula', () => {
  // The formula is:
  //   specSlideCount !== null  (null guard)
  //   && releasedCount > 0     (zero guard — an empty deck is not "all released")
  //   && releasedCount === specSlideCount  (every position out)
  //   && isGenerating          (turn still running)

  it('is OFF mid-build: some positions still outstanding', () => {
    // 2 of 3 slides released; the deck reviewer has not started yet.
    // Third assertion from the brief: off mid-build distinguishes "building" from "reviewing".
    expect(_isReviewInProgress(2, 3, true)).toBe(false);
  });

  it('is ON once every position is released and the turn is still open', () => {
    // All 3 of 3 slides released, isGenerating=true.
    // This is the window the deck reviewer runs in.
    expect(_isReviewInProgress(3, 3, true)).toBe(true);
  });

  it('is OFF when the turn completes', () => {
    // All slides released BUT isGenerating has flipped to false — deck review done.
    expect(_isReviewInProgress(3, 3, false)).toBe(false);
  });

  it('is OFF when deckSpec is null (null guard — no deck or specless deck)', () => {
    // Null guard: before any architect turn, slideDeck.deck_spec is null/absent.
    // Without the guard the comparison would run against null and return false
    // due to coercion, but we enforce it explicitly.
    expect(_isReviewInProgress(0, null, true)).toBe(false);
    expect(_isReviewInProgress(3, null, true)).toBe(false);
  });

  it('is OFF when releasedCount is 0 even if specSlideCount is also 0 (zero guard)', () => {
    // An empty spec produces 0 === 0, which would fire spuriously without the guard.
    expect(_isReviewInProgress(0, 0, true)).toBe(false);
  });
});

// ── 2. Non-blocking — no control reads reviewInProgress in disabled ───────────
//
// This is the assertion most likely to be written so that it cannot fail.
// "Assert the absence of the coupling, not just that the buttons happen to
// work" — a test that clicks export and sees it work passes whether or not
// anything reads the flag.
//
// Sabotage to verify:
//   In page-header.tsx, change one export DropdownMenuItem disabled= to
//   `disabled={isGenerating || reviewInProgress}`.
//   The test below goes red.  Revert; it goes green.

describe('non-blocking — reviewInProgress absent from disabled props', () => {
  const FILES_TO_SCAN = [
    'frontend/src/components/Layout/page-header.tsx',
    'frontend/src/components/Layout/AppLayout.tsx',
    'frontend/src/components/SpecView/SpecView.tsx',
  ];

  it('reviewInProgress does not appear in any disabled= expression', () => {
    // Pattern: `disabled={...reviewInProgress...}` — any template that puts
    // reviewInProgress inside a JSX disabled attribute.
    // Written as a token search rather than a regex over the full prop so that
    // it catches both `disabled={reviewInProgress}` and `disabled={x || reviewInProgress}`.
    const COUPLING_PATTERN = /disabled=\{[^}]*reviewInProgress[^}]*\}/;

    for (const relPath of FILES_TO_SCAN) {
      const src = readSource(relPath);
      const lines = src.split('\n');
      const offendingLines = lines
        .map((line, i) => ({ line, lineNo: i + 1 }))
        .filter(({ line }) => COUPLING_PATTERN.test(line));

      expect(
        offendingLines,
        `${relPath} has a disabled= prop that reads reviewInProgress:\n` +
          offendingLines.map(({ lineNo, line }) => `  L${lineNo}: ${line.trim()}`).join('\n'),
      ).toEqual([]);
    }
  });
});

// ── 3. Badge render — shape, not behaviour ────────────────────────────────────
//
// Tests that the badge element is present / absent in the DOM.
// These are shape tests: they pin the rendered structure, not the timing logic
// (which is covered above by pure-function tests against _isReviewInProgress).

describe('deck-review-in-progress badge — render shape', () => {
  it('badge is visible in the spec header when reviewInProgress is true', () => {
    render(
      <SpecView
        slideDeck={makeMinimalDeck()}
        onDiscuss={() => undefined}
        reviewInProgress={true}
      />,
    );
    expect(screen.getByTestId('deck-review-in-progress')).toBeInTheDocument();
  });

  it('badge is absent when reviewInProgress is false (default)', () => {
    render(
      <SpecView
        slideDeck={makeMinimalDeck()}
        onDiscuss={() => undefined}
        reviewInProgress={false}
      />,
    );
    expect(screen.queryByTestId('deck-review-in-progress')).not.toBeInTheDocument();
  });

  it('badge is absent when reviewInProgress is omitted (default false)', () => {
    render(
      <SpecView slideDeck={makeMinimalDeck()} onDiscuss={() => undefined} />,
    );
    expect(screen.queryByTestId('deck-review-in-progress')).not.toBeInTheDocument();
  });
});
