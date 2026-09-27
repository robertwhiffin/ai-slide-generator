import { useCallback, useEffect, useReducer, useRef } from 'react';
import { getReleasePreview, publishRelease } from '../../../api/agentDefinitions';
import {
  canPublish,
  createReviewAndPublishState,
  previewErrorMessage,
  publishFailureAction,
  reviewAndPublishReducer,
} from './reviewAndPublishState';

/**
 * The page's one reducer, request counter and in-flight gate, after the workbench's
 * `useDraftEditor`. The gate is a ref so two clicks inside one render still send exactly
 * one POST; the counter tags every request so a superseded response is dropped.
 */
export function useReviewAndPublish() {
  const [state, dispatch] = useReducer(reviewAndPublishReducer, undefined, createReviewAndPublishState);
  const nextRequestIdRef = useRef(1);
  const publishInFlightRef = useRef<number | null>(null);

  const reloadPreview = useCallback(async (): Promise<void> => {
    if (publishInFlightRef.current !== null) return;
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'reloadPreview', requestId });
    try {
      const preview = await getReleasePreview();
      dispatch({ type: 'previewSucceeded', requestId, preview });
    } catch (error) {
      dispatch({ type: 'previewFailed', requestId, message: previewErrorMessage(error) });
    }
  }, []);

  useEffect(() => {
    void reloadPreview();
  }, [reloadPreview]);

  const setNote = (note: string) => dispatch({ type: 'noteChanged', note });

  const publish = async (): Promise<void> => {
    if (publishInFlightRef.current !== null || !canPublish(state) || state.preview === null) return;
    const requestId = nextRequestIdRef.current++;
    publishInFlightRef.current = requestId;
    dispatch({ type: 'publishStarted', requestId });
    let published = false;
    try {
      const result = await publishRelease({
        lock_version: state.preview.draft.lock_version,
        release_note: state.note,
      });
      dispatch({ type: 'publishSucceeded', requestId, result });
      published = true;
    } catch (error) {
      // Every refusal waits for an explicit Reload preview: nothing here retries.
      dispatch(publishFailureAction(requestId, error));
    } finally {
      if (publishInFlightRef.current === requestId) publishInFlightRef.current = null;
    }
    // Exactly one refetch, so the page shows the rebased draft (#269).
    if (published) await reloadPreview();
  };

  return { state, setNote, publish, reloadPreview };
}

