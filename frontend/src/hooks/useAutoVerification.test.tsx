/**
 * #314 Task 7: auto-verification skips a blank slide (plan D11; D4's structural predicate).
 *
 * A blank slide — the bare fallback or the deck-derived shell (D1) — has a `content_hash` and no
 * verdict, exactly like a freshly built slide, so without a skip the hook spends a judge call on it
 * and badges an empty frame against an empty brief. The skip is on the slide's CURRENT html through
 * `isBlankSlideHtml`: a literal compare against the bare div misses every shell, and a skip that is
 * remembered by slide id would never verify the blank once the agent fills it in place (D5 keeps the
 * blank's `slide_id`).
 *
 * SABOTAGE (each run against a throwaway implementation in a copy, then reverted):
 *   - drop the skip from the filter                            -> "skips blanks" RED (3 calls, not 1)
 *   - skip only `slide.html === BLANK_SLIDE_HTML`              -> "skips blanks" RED (the section shell is verified)
 *   - remember a blank's slide_id and keep skipping it         -> "verifies a filled blank" RED
 */
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import type { Slide, SlideDeck } from '../types/slide';
import type { VerificationResult } from '../types/verification';
import { ToastProvider } from '../contexts/ToastContext';
import { api } from '../services/api';
import { useAutoVerification } from './useAutoVerification';

vi.mock('../services/api', () => ({
  api: {
    verifySlide: vi.fn(),
    getSlides: vi.fn(),
  },
}));

const verifySlide = api.verifySlide as unknown as Mock;
const getSlides = api.getSlides as unknown as Mock;

const SESSION = 'sess-314-autoverify';

/** The fallback blank (`BLANK_SLIDE_HTML`). */
const BARE_BLANK = '<div class="slide"></div>';
/** A deck-derived shell on the shipped section-wrapper design system (D1). */
const SECTION_SHELL = '<section data-label="Acme Ground"><div class="slide"></div></section>';
const NORMAL = '<div class="slide"><h1>Pricing</h1><p>Three tiers, one table.</p></div>';
const FILLED = '<section data-label="Acme Ground"><div class="slide"><h1>Roadmap</h1></div></section>';

const GREEN: VerificationResult = {
  score: 92, rating: 'green', explanation: 'Matches its sources.', issues: [], duration_ms: 10, error: false,
};

function slide(index: number, slideId: string, html: string, contentHash: string): Slide {
  return { index, slide_id: slideId, html, scripts: '', content_hash: contentHash };
}

function deckOf(slides: Slide[]): SlideDeck {
  return { title: 'Deck', slide_count: slides.length, css: '', external_scripts: [], scripts: '', slides };
}

const wrapper = ({ children }: { children: ReactNode }) => <ToastProvider>{children}</ToastProvider>;

/** verifySlide's calls as [sessionId, index] pairs, in call order. */
const verifiedPairs = () => verifySlide.mock.calls.map(([sessionId, index]) => [sessionId, index]);

beforeEach(() => {
  verifySlide.mockReset();
  getSlides.mockReset();
  verifySlide.mockResolvedValue({});
  getSlides.mockResolvedValue({ session_id: SESSION, slide_deck: null });
  vi.spyOn(console, 'log').mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useAutoVerification — blank slides are not auto-verified', () => {
  it('skips the bare blank and the section shell, and verifies the normal slide between them', async () => {
    // The normal slide sits BETWEEN the two blanks, so "verify only index 0" or "only the last" is
    // not mistaken for the skip. All three carry a content_hash and no verdict.
    const deck = deckOf([
      slide(0, 'slide-bare-blank', BARE_BLANK, 'hash-bare-blank'),
      slide(1, 'slide-normal', NORMAL, 'hash-normal'),
      slide(2, 'slide-section-shell', SECTION_SHELL, 'hash-section-shell'),
    ]);

    const { result } = renderHook(
      () => useAutoVerification({ slideDeck: deck, sessionId: SESSION }),
      { wrapper },
    );

    // The batch has run to its end (the refresh after verifying), and no second batch is pending.
    await waitFor(() => expect(getSlides).toHaveBeenCalled());
    await waitFor(() => expect(result.current.isAutoVerifying).toBe(false));

    expect(verifiedPairs()).toEqual([[SESSION, 1]]);
  });

  it('verifies a blank once it is filled in place (same slide_id, new html and hash)', async () => {
    const before = deckOf([
      slide(0, 'slide-normal', NORMAL, 'hash-normal'),
      slide(1, 'slide-blank', SECTION_SHELL, 'hash-section-shell'),
    ]);
    const { result, rerender } = renderHook(
      ({ deck }: { deck: SlideDeck }) => useAutoVerification({ slideDeck: deck, sessionId: SESSION }),
      { wrapper, initialProps: { deck: before } },
    );
    await waitFor(() => expect(getSlides).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.isAutoVerifying).toBe(false));
    // Precondition: the blank was skipped while it was blank.
    expect(verifiedPairs()).toEqual([[SESSION, 0]]);

    // The agent fills the blank: D5 keeps its slide_id, the html and the hash change. The normal
    // slide now carries the verdict the parent merged after the first batch. (It must: the hook's
    // mount-time session reset empties the hash dedupe set while that first batch is in flight, so
    // without a verdict the normal slide would be verified again on the next deck.)
    rerender({
      deck: deckOf([
        { ...slide(0, 'slide-normal', NORMAL, 'hash-normal'), verification: GREEN },
        slide(1, 'slide-blank', FILLED, 'hash-filled'),
      ]),
    });

    await waitFor(() => expect(getSlides).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.isAutoVerifying).toBe(false));
    expect(verifiedPairs()).toEqual([[SESSION, 0], [SESSION, 1]]);
  });
});
