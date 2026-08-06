/**
 * useAutoVerification — shared auto-verify logic for SlidePanel and SlideViewer.
 *
 * Extracted so both paths share identical guards:
 *   • content_hash dedupe via autoVerifyTriggeredRef (never re-verify the same hash)
 *   • deckEditCounterRef / editId staleness check (discard if deck mutated mid-flight)
 *   • isAutoVerifying re-entry guard (only one batch runs at a time)
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import type { SlideDeck } from '../types/slide';
import { api } from '../services/api';

interface UseAutoVerificationOptions {
  slideDeck: SlideDeck | null;
  sessionId: string | null;
  /**
   * Called after a successful verification batch so callers can persist the
   * updated verification state (e.g. syncVersionVerification).
   */
  onVerificationComplete?: () => void;
  /**
   * Called with the freshly merged deck after verification results land so the
   * parent can update its deck state.
   */
  onSlideChange?: (deck: SlideDeck) => void;
  /**
   * Ref to an external edit counter so the hook can detect staleness caused by
   * concurrent edits outside the hook (e.g. delete/update in SlidePanel). When
   * omitted, the hook maintains its own internal counter.
   */
  deckEditCounterRef?: React.MutableRefObject<number>;
}

interface UseAutoVerificationReturn {
  /** Indices of slides currently being auto-verified. */
  verifyingSlides: Set<number>;
  /** True while any auto-verify batch is running. */
  isAutoVerifying: boolean;
}

export function useAutoVerification({
  slideDeck,
  sessionId,
  onVerificationComplete,
  onSlideChange,
  deckEditCounterRef: externalEditCounterRef,
}: UseAutoVerificationOptions): UseAutoVerificationReturn {
  const [isAutoVerifying, setIsAutoVerifying] = useState(false);
  const [verifyingSlides, setVerifyingSlides] = useState<Set<number>>(new Set());

  // Dedupe: never re-trigger verification for a hash already attempted this session.
  const autoVerifyTriggeredRef = useRef<Set<string>>(new Set());

  // Re-entry / staleness counter. Use the caller's ref if provided so concurrent
  // edits (delete, update) in the parent component also abort in-flight batches.
  const internalEditCounterRef = useRef(0);
  const deckEditCounterRef = externalEditCounterRef ?? internalEditCounterRef;

  // Track the current sessionId so we can discard results for stale sessions.
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // Track the current deck so we can merge results onto the latest state.
  const slideDeckRef = useRef(slideDeck);
  slideDeckRef.current = slideDeck;

  const runAutoVerification = useCallback(
    async (slidesToVerify: Array<{ index: number; contentHash: string }>) => {
      if (!sessionId || slidesToVerify.length === 0 || isAutoVerifying) return;
      const capturedSessionId = sessionId;
      const editIdAtStart = deckEditCounterRef.current;

      setIsAutoVerifying(true);
      console.log(
        `[Auto-verify] Starting verification for ${slidesToVerify.length} slides`,
      );
      setVerifyingSlides(new Set(slidesToVerify.map((s) => s.index)));

      const verificationPromises = slidesToVerify.map(async ({ index, contentHash }) => {
        try {
          autoVerifyTriggeredRef.current.add(contentHash);
          console.log(
            `[Auto-verify] Verifying slide ${index + 1} (hash: ${contentHash.substring(0, 8)}...)`,
          );
          await api.verifySlide(capturedSessionId, index);
          console.log(`[Auto-verify] Slide ${index + 1} verified`);
          return { index, success: true };
        } catch (error) {
          console.error(`[Auto-verify] Failed to verify slide ${index + 1}:`, error);
          return { index, success: false, error };
        }
      });

      await Promise.all(verificationPromises);

      // Discard results if the session changed while we were running.
      if (sessionIdRef.current !== capturedSessionId) {
        console.log('[Auto-verify] Session changed, discarding stale results');
        setIsAutoVerifying(false);
        setVerifyingSlides(new Set());
        return;
      }

      try {
        const result = await api.getSlides(capturedSessionId);
        const currentDeck = slideDeckRef.current;
        // Discard if a concurrent edit bumped the counter while we were verifying.
        if (result.slide_deck && currentDeck && deckEditCounterRef.current === editIdAtStart) {
          const serverSlides = result.slide_deck.slides ?? [];
          const mergedSlides = currentDeck.slides.map((localSlide) => {
            const match = serverSlides.find(
              (s: { content_hash?: string }) =>
                s.content_hash && s.content_hash === localSlide.content_hash,
            );
            if (match?.verification) {
              return { ...localSlide, verification: match.verification };
            }
            return localSlide;
          });
          onSlideChange?.({ ...currentDeck, slides: mergedSlides });
        }
      } catch (error) {
        console.error('[Auto-verify] Failed to refresh verification:', error);
      }

      setVerifyingSlides(new Set());
      setIsAutoVerifying(false);
      console.log('[Auto-verify] Completed');

      onVerificationComplete?.();
    },
    // isAutoVerifying is intentionally excluded from the dependency array to avoid
    // stale-closure captures — it is read via its state setter only. The session /
    // callback refs are stable. deckEditCounterRef is a stable ref object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, onSlideChange, onVerificationComplete],
  );

  // Trigger auto-verify whenever the deck changes and there are unverified slides.
  useEffect(() => {
    if (!slideDeck || !sessionId || isAutoVerifying) return;

    const slidesNeedingVerification = slideDeck.slides
      .map((slide, index) => ({
        index,
        slide,
        contentHash: slide.content_hash ?? '',
      }))
      .filter(({ slide, contentHash }) => {
        if (slide.verification) return false;
        if (!contentHash) return false;
        if (autoVerifyTriggeredRef.current.has(contentHash)) return false;
        return true;
      });

    if (slidesNeedingVerification.length > 0) {
      console.log(
        `[Auto-verify] Found ${slidesNeedingVerification.length} slides needing verification`,
      );
      runAutoVerification(slidesNeedingVerification);
    }
  }, [slideDeck, sessionId, isAutoVerifying, runAutoVerification]);

  // Reset all state when switching sessions.
  useEffect(() => {
    autoVerifyTriggeredRef.current.clear();
    setIsAutoVerifying(false);
    setVerifyingSlides(new Set());
  }, [sessionId]);

  return { verifyingSlides, isAutoVerifying };
}
