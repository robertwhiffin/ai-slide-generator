import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  compareGraphRelease,
  getGraphRelease,
  getReleasePreview,
  getRollbackPreview,
  listGraphReleases,
  publishRelease,
  rollbackGraphRelease,
} from '../../../api/agentDefinitions';
import {
  canPublish,
  createReviewAndPublishState,
  historyReadErrorMessage,
  previewErrorMessage,
  publishFailureAction,
  reviewAndPublishReducer,
  rollbackFailureAction,
  type ReviewAndPublishAction,
  type ReviewAndPublishState,
} from './reviewAndPublishState';

/**
 * The page's one reducer, request counter and in-flight gate, after the workbench's
 * `useDraftEditor`. The gate is a ref so two clicks inside one render still send exactly
 * one POST; the counter tags every request so a superseded response is dropped.
 *
 * #270 (Correction 39): the same counter tags every history, inspection and rollback
 * read, and the one write-in-flight ref covers both writes, publish and rollback.
 * `stateRef` mirrors the reducer synchronously (every action goes through `dispatch`
 * below), so a rollback POST is sent only if the reducer itself accepted
 * `rollbackStarted`, never on last-render state (#269's parked m4 is not copied).
 */
export function useReviewAndPublish() {
  const [state, reactDispatch] = useReducer(reviewAndPublishReducer, undefined, createReviewAndPublishState);
  const stateRef = useRef<ReviewAndPublishState>(state);
  const nextRequestIdRef = useRef(1);
  const writeInFlightRef = useRef<number | null>(null);

  const dispatch = useCallback((action: ReviewAndPublishAction) => {
    stateRef.current = reviewAndPublishReducer(stateRef.current, action);
    reactDispatch(action);
  }, []);

  const reloadPreview = useCallback(async (): Promise<void> => {
    if (writeInFlightRef.current !== null) return;
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'reloadPreview', requestId });
    try {
      const preview = await getReleasePreview();
      dispatch({ type: 'previewSucceeded', requestId, preview });
    } catch (error) {
      dispatch({ type: 'previewFailed', requestId, message: previewErrorMessage(error) });
    }
  }, [dispatch]);

  useEffect(() => {
    void reloadPreview();
  }, [reloadPreview]);

  const loadHistory = useCallback(async (): Promise<void> => {
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'historyRequested', requestId });
    try {
      const history = await listGraphReleases();
      dispatch({ type: 'historySucceeded', requestId, history });
    } catch (error) {
      dispatch({ type: 'historyFailed', requestId, message: historyReadErrorMessage('release history', error) });
    }
  }, [dispatch]);

  const setNote = (note: string) => dispatch({ type: 'noteChanged', note });

  const publish = async (): Promise<void> => {
    if (writeInFlightRef.current !== null || !canPublish(state) || state.preview === null) return;
    const requestId = nextRequestIdRef.current++;
    writeInFlightRef.current = requestId;
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
      if (writeInFlightRef.current === requestId) writeInFlightRef.current = null;
    }
    // Exactly one refetch, so the page shows the rebased draft (#269); a loaded history
    // is refetched too, so it lists the new Graph Version.
    if (published) {
      await Promise.all([
        reloadPreview(),
        stateRef.current.history.status === 'idle' ? Promise.resolve() : loadHistory(),
      ]);
    }
  };

  const inspectRelease = async (versionNumber: number): Promise<void> => {
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'inspectRequested', requestId, versionNumber });
    try {
      const [detail, comparison] = await Promise.all([getGraphRelease(versionNumber), compareGraphRelease(versionNumber)]);
      dispatch({ type: 'inspectSucceeded', requestId, detail, comparison });
    } catch (error) {
      dispatch({ type: 'inspectFailed', requestId, message: historyReadErrorMessage('Graph Version', error) });
    }
  };

  const readRollbackPreview = async (requestId: number, versionNumber: number): Promise<void> => {
    try {
      const preview = await getRollbackPreview(versionNumber);
      dispatch({ type: 'rollbackPreviewSucceeded', requestId, preview });
    } catch (error) {
      dispatch({ type: 'rollbackPreviewFailed', requestId, message: historyReadErrorMessage('rollback preview', error) });
    }
  };

  /** One preview GET and no POST; refused (no GET) while either write is in flight. */
  const openRollback = async (versionNumber: number): Promise<void> => {
    if (writeInFlightRef.current !== null) return;
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'rollbackOpened', requestId, versionNumber });
    if (stateRef.current.rollback.previewRequestId !== requestId) return;
    await readRollbackPreview(requestId, versionNumber);
  };

  /** The explicit reload after a stale rollback: one GET, the typed note kept, no retry. */
  const reloadRollback = async (): Promise<void> => {
    if (writeInFlightRef.current !== null) return;
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'rollbackReloaded', requestId });
    const { rollback } = stateRef.current;
    if (rollback.previewRequestId !== requestId || rollback.versionNumber === null) return;
    await readRollbackPreview(requestId, rollback.versionNumber);
  };

  const setRollbackNote = (note: string) => dispatch({ type: 'rollbackNoteChanged', note });

  const cancelRollback = () => dispatch({ type: 'rollbackCancelled' });

  const confirmRollback = async (): Promise<void> => {
    if (writeInFlightRef.current !== null) return;
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'rollbackStarted', requestId });
    // The reducer's current state decides, not the last render's.
    const { rollback } = stateRef.current;
    if (rollback.postRequestId !== requestId || rollback.preview === null || rollback.versionNumber === null) return;
    writeInFlightRef.current = requestId;
    let restored = false;
    try {
      const result = await rollbackGraphRelease(rollback.versionNumber, {
        lock_version: rollback.preview.lock_version,
        release_note: rollback.note,
      });
      dispatch({ type: 'rollbackSucceeded', requestId, result });
      restored = true;
    } catch (error) {
      // Every refusal waits for an explicit action: nothing here retries.
      dispatch(rollbackFailureAction(requestId, error));
    } finally {
      if (writeInFlightRef.current === requestId) writeInFlightRef.current = null;
    }
    // Exactly one history refetch and one release-preview refetch.
    if (restored) await Promise.all([loadHistory(), reloadPreview()]);
  };

  return {
    state,
    setNote,
    publish,
    reloadPreview,
    loadHistory,
    inspectRelease,
    openRollback,
    reloadRollback,
    setRollbackNote,
    cancelRollback,
    confirmRollback,
  };
}
