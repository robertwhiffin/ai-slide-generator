import { describe, expect, it } from 'vitest';
import {
  RELEASE_NOTE_BLANK_ERROR,
  syntheticNothingToPublish,
  syntheticPublicationInvalid,
  syntheticPublicationNotReady,
  syntheticPublishSuccess,
  syntheticPublishedReleasePreview,
  syntheticReleasePreview,
  syntheticStalePublication,
  releaseRef,
  syntheticBlockedRollbackPreview,
  syntheticReleaseComparison,
  syntheticReleaseDetail,
  syntheticReleaseHistory,
  syntheticRestoredReleaseHistory,
  syntheticRollbackIncompatible,
  syntheticRollbackInvalid,
  syntheticRollbackPreview,
  syntheticRollbackSuccess,
  syntheticStaleRollback,
} from '../../../../tests/fixtures/mocks';
import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  type ReadinessStatus,
} from '../../../api/agentDefinitions';
import type { DraftStatus } from '../AgentDefinitionWorkbench/draftEditorState';
import {
  DRAFT_EFFECT_LABELS,
  canConfirmRollback,
  rollbackBlockedMessage,
  rollbackErrorMessage,
  rollbackFailureAction,
  ROLE_LABELS,
  canPublish,
  createReviewAndPublishState,
  publicationErrorMessage,
  publicationGapLabel,
  publishFailureAction,
  readinessStatusLabel,
  releaseNoteLength,
  reviewAndPublishReducer,
  type ReviewAndPublishAction,
  type ReviewAndPublishState,
} from './reviewAndPublishState';

function run(actions: ReviewAndPublishAction[], state = createReviewAndPublishState()): ReviewAndPublishState {
  return actions.reduce(reviewAndPublishReducer, state);
}

/** A loaded, publishable preview with `note` typed. */
function ready(note = 'Tighten the outline', preview = syntheticReleasePreview()): ReviewAndPublishState {
  return run([
    { type: 'reloadPreview', requestId: 1 },
    { type: 'previewSucceeded', requestId: 1, preview },
    { type: 'noteChanged', note },
  ]);
}

function publishing(note = 'Tighten the outline'): ReviewAndPublishState {
  return reviewAndPublishReducer(ready(note), { type: 'publishStarted', requestId: 2 });
}

describe('reviewAndPublishReducer: loading the preview', () => {
  it('starts loading with no preview and an empty note', () => {
    const state = createReviewAndPublishState();
    expect(state.status).toBe('loading');
    expect(state.preview).toBeNull();
    expect(state.note).toBe('');
  });

  it('becomes ready with the preview of the current request', () => {
    const state = run([
      { type: 'reloadPreview', requestId: 1 },
      { type: 'previewSucceeded', requestId: 1, preview: syntheticReleasePreview() },
    ]);
    expect(state.status).toBe('ready');
    expect(state.preview).toEqual(syntheticReleasePreview());
    expect(state.previewRequestId).toBeNull();
  });

  it('drops a preview response from a superseded request', () => {
    const newer = syntheticReleasePreview({ draft: { ...syntheticReleasePreview().draft, lock_version: 9 } });
    const state = run([
      { type: 'reloadPreview', requestId: 1 },
      { type: 'reloadPreview', requestId: 2 },
      { type: 'previewSucceeded', requestId: 1, preview: syntheticReleasePreview() },
    ]);
    expect(state.status).toBe('loading');
    expect(state.preview).toBeNull();
    const settled = run([{ type: 'previewSucceeded', requestId: 2, preview: newer }], state);
    expect(settled.preview?.draft.lock_version).toBe(9);
    // The superseded read's late failure changes nothing either.
    expect(run([{ type: 'previewFailed', requestId: 1, message: 'late' }], settled)).toBe(settled);
  });

  it('shows a failed read as an error, keeping any typed note', () => {
    const state = run([
      { type: 'reloadPreview', requestId: 3 },
      { type: 'previewFailed', requestId: 3, message: 'Unable to load the release preview (500).' },
    ], ready('keep me'));
    expect(state.status).toBe('error');
    expect(state.errorMessage).toBe('Unable to load the release preview (500).');
    expect(state.note).toBe('keep me');
  });
});

describe('reviewAndPublishReducer: a failed refetch after a publish (fix round 1, m2)', () => {
  function publishedThenRefetchFailed(): ReviewAndPublishState {
    return run([
      { type: 'publishSucceeded', requestId: 2, result: syntheticPublishSuccess() },
      { type: 'reloadPreview', requestId: 3 },
      { type: 'previewFailed', requestId: 3, message: 'Unable to load the release preview (500).' },
    ], publishing());
  }

  it('leaves published for error, keeping the published release on record', () => {
    const state = publishedThenRefetchFailed();
    expect(state.status).toBe('error');
    expect(state.errorMessage).toBe('Unable to load the release preview (500).');
    expect(state.published?.release.version_number).toBe(2);
  });

  it('recovers through an explicit reloadPreview: loading, then ready on the new preview', () => {
    const loading = reviewAndPublishReducer(publishedThenRefetchFailed(), { type: 'reloadPreview', requestId: 4 });
    expect(loading.status).toBe('loading');
    expect(loading.errorMessage).toBeNull();
    const settled = reviewAndPublishReducer(loading, {
      type: 'previewSucceeded', requestId: 4, preview: syntheticPublishedReleasePreview(),
    });
    expect(settled.status).toBe('ready');
    expect(settled.preview?.draft.base_version_number).toBe(2);
  });
});

describe('canPublish (Correction 22)', () => {
  it('is true only from ready with a publishable preview and a non-blank note', () => {
    expect(canPublish(ready())).toBe(true);
    expect(canPublish(createReviewAndPublishState())).toBe(false);
  });

  it.each(['', '   ', '\n\t'])('is false for the blank note %j', (note) => {
    expect(canPublish(ready(note))).toBe(false);
  });

  it('is false when the server says the draft is not publishable, whatever the note', () => {
    expect(canPublish(ready('A real note', syntheticReleasePreview({ publishable: false })))).toBe(false);
  });

  it('never decides with readiness: a blocking readiness beside publishable=true stays publishable (C32)', () => {
    const preview = syntheticReleasePreview({
      readiness: { ...syntheticReleasePreview().readiness, all_ready: false, blocking_agents: ['architect'] },
    });
    expect(canPublish(ready('A real note', preview))).toBe(true);
  });

  it('caps the note at 2000 code points, as the server counts them (Correction 10)', () => {
    expect(canPublish(ready('x'.repeat(2000)))).toBe(true);
    expect(canPublish(ready('x'.repeat(2001)))).toBe(false);
    // 2000 astral characters are 4000 UTF-16 units but 2000 Python code points.
    const astral = '\u{1F680}'.repeat(2000);
    expect(astral.length).toBe(4000);
    expect(releaseNoteLength(astral)).toBe(2000);
    expect(canPublish(ready(astral))).toBe(true);
    expect(canPublish(ready(`${astral}x`))).toBe(false);
  });

  it.each(['publishing', 'stale', 'notReady', 'invalid', 'nothingToPublish', 'published', 'error', 'loading'] as const)(
    'is false from %s',
    (status) => {
      expect(canPublish({ ...ready(), status })).toBe(false);
    },
  );
});

describe('reviewAndPublishReducer: publishing', () => {
  it('starts publishing only when canPublish holds', () => {
    expect(publishing().status).toBe('publishing');
    expect(publishing().publishRequestId).toBe(2);
    const blank = ready('  ');
    expect(reviewAndPublishReducer(blank, { type: 'publishStarted', requestId: 2 })).toBe(blank);
    const unpublishable = ready('note', syntheticReleasePreview({ publishable: false }));
    expect(reviewAndPublishReducer(unpublishable, { type: 'publishStarted', requestId: 2 })).toBe(unpublishable);
    const again = publishing();
    expect(reviewAndPublishReducer(again, { type: 'publishStarted', requestId: 3 })).toBe(again);
  });

  it('ignores note edits and preview reloads while the publish is in flight', () => {
    const state = publishing('first');
    expect(reviewAndPublishReducer(state, { type: 'noteChanged', note: 'second' })).toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'reloadPreview', requestId: 3 })).toBe(state);
  });

  it('drops a publish outcome from another request id', () => {
    const state = publishing();
    expect(reviewAndPublishReducer(state, { type: 'publishSucceeded', requestId: 7, result: syntheticPublishSuccess() }))
      .toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'publishStale', requestId: 7, conflict: syntheticStalePublication() }))
      .toBe(state);
  });

  it('stores the published release, then keeps the success while one refetch shows nothing changed', () => {
    const published = reviewAndPublishReducer(publishing(), {
      type: 'publishSucceeded', requestId: 2, result: syntheticPublishSuccess(),
    });
    expect(published.status).toBe('published');
    expect(published.published?.release.version_number).toBe(2);
    expect(published.published?.draft.base_version_number).toBe(2);

    const refetched = run([
      { type: 'reloadPreview', requestId: 3 },
      { type: 'previewSucceeded', requestId: 3, preview: syntheticPublishedReleasePreview() },
    ], published);
    expect(refetched.status).toBe('published');
    expect(refetched.preview?.changed).toEqual([]);
    expect(refetched.preview?.draft.base_version_number).toBe(2);
    expect(canPublish(refetched)).toBe(false);
  });

  it('keeps the typed note on a stale 409 and waits for an explicit reloadPreview', () => {
    const stale = reviewAndPublishReducer(publishing('my careful note'), {
      type: 'publishStale', requestId: 2, conflict: syntheticStalePublication(),
    });
    expect(stale.status).toBe('stale');
    expect(stale.note).toBe('my careful note');
    expect(stale.stale).toEqual(syntheticStalePublication());
    expect(stale.publishRequestId).toBeNull();
    expect(stale.previewRequestId).toBeNull();
    expect(canPublish(stale)).toBe(false);

    const reloaded = run([
      { type: 'reloadPreview', requestId: 3 },
      { type: 'previewSucceeded', requestId: 3, preview: syntheticReleasePreview({ draft: syntheticStalePublication().draft }) },
    ], stale);
    expect(reloaded.status).toBe('ready');
    expect(reloaded.note).toBe('my careful note');
    expect(reloaded.stale).toBeNull();
    expect(reloaded.preview?.draft.lock_version).toBe(5);
    expect(canPublish(reloaded)).toBe(true);
  });

  it('shows the not-ready, nothing-to-publish and invalid refusals, keeping the note', () => {
    const notReady = reviewAndPublishReducer(publishing('n'), {
      type: 'publishNotReady', requestId: 2, refusal: syntheticPublicationNotReady(),
    });
    expect(notReady.status).toBe('notReady');
    expect(notReady.notReady).toEqual(syntheticPublicationNotReady());
    expect(notReady.note).toBe('n');

    const nothing = reviewAndPublishReducer(publishing('n'), {
      type: 'publishNothing', requestId: 2, refusal: syntheticNothingToPublish(),
    });
    expect(nothing.status).toBe('nothingToPublish');
    expect(nothing.nothingToPublish).toEqual(syntheticNothingToPublish());

    const invalid = reviewAndPublishReducer(publishing('n'), {
      type: 'publishInvalid', requestId: 2, rejection: syntheticPublicationInvalid(),
    });
    expect(invalid.status).toBe('invalid');
    expect(invalid.errors).toEqual([RELEASE_NOTE_BLANK_ERROR]);
    expect(invalid.note).toBe('n');
    expect(canPublish(invalid)).toBe(false);
  });

  it('returns an invalid publish to ready once the note is edited, clearing the refused issues', () => {
    const invalid = reviewAndPublishReducer(publishing('n'), {
      type: 'publishInvalid', requestId: 2, rejection: syntheticPublicationInvalid(),
    });
    const edited = reviewAndPublishReducer(invalid, { type: 'noteChanged', note: 'A better note' });
    expect(edited.status).toBe('ready');
    expect(edited.errors).toEqual([]);
    expect(canPublish(edited)).toBe(true);
  });

  it('keeps the note and the preview on an unexpected failure', () => {
    const failed = reviewAndPublishReducer(publishing('n'), { type: 'publishFailed', requestId: 2, message: 'boom' });
    expect(failed.status).toBe('error');
    expect(failed.errorMessage).toBe('boom');
    expect(failed.note).toBe('n');
    expect(failed.preview).toEqual(syntheticReleasePreview());
  });
});

describe('publishFailureAction: keyed on the typed code, never on message text', () => {
  it.each([
    [409, syntheticStalePublication(), 'publishStale'],
    [409, syntheticNothingToPublish(), 'publishNothing'],
    [409, syntheticPublicationNotReady(), 'publishNotReady'],
    [422, syntheticPublicationInvalid(), 'publishInvalid'],
  ])('maps a %i %o to its action', (status, payload, type) => {
    expect(publishFailureAction(4, new AgentDefinitionApiError(status, payload)).type).toBe(type);
  });

  it('maps an invalid response, another status and a network failure to fixed client copy', () => {
    expect(publishFailureAction(4, new InvalidReleaseResponseError())).toEqual({
      type: 'publishFailed', requestId: 4, message: 'The server returned an invalid publication response. Reload the preview.',
    });
    expect(publishFailureAction(4, new AgentDefinitionApiError(500, { detail: 'Graph configuration is incomplete' }))).toEqual({
      type: 'publishFailed', requestId: 4, message: 'Unable to publish (500). Reload the preview to see the current Graph Version.',
    });
    expect(publishFailureAction(4, new TypeError('Failed to fetch'))).toEqual({
      type: 'publishFailed', requestId: 4, message: 'Unable to confirm the publication. Reload the preview to see the current Graph Version.',
    });
  });
});

describe('labels', () => {
  it('labels every readiness code with the matching workbench DraftStatus (Correction 54)', () => {
    const expected = {
      needs_test: 'Needs test',
      test_failed: 'Test failed',
      awaiting_review: 'Awaiting review',
      approved: 'Approved',
    } as const satisfies Record<ReadinessStatus, DraftStatus>;
    for (const [status, label] of Object.entries(expected) as Array<[ReadinessStatus, DraftStatus]>) {
      expect(readinessStatusLabel(status)).toBe(label);
    }
  });

  it('labels every role in Graph order', () => {
    expect(Object.keys(ROLE_LABELS)).toEqual([...AGENT_KEYS]);
    expect(Object.values(ROLE_LABELS)).toEqual([
      'Architect', 'Data Analyst', 'Builder', 'Build Reviewer', 'Fixer', 'Fix Reviewer', 'Deck Reviewer',
    ]);
  });

  it('labels both gap codes on the client (Correction 1)', () => {
    const readiness = syntheticPublicationNotReady().readiness;
    expect(publicationGapLabel({ agent_key: 'builder', test_case_id: null, code: 'no_required_case' }, readiness))
      .toBe('Builder: no active required test case');
    expect(publicationGapLabel({ agent_key: 'architect', test_case_id: 101, code: 'no_eligible_approval' }, readiness))
      .toBe('Architect: Architect quarterly revenue outline has no eligible approval');
    // A case the informational readiness does not list is named by id, never dropped.
    expect(publicationGapLabel({ agent_key: 'fixer', test_case_id: 909, code: 'no_eligible_approval' }, readiness))
      .toBe('Fixer: test case 909 has no eligible approval');
  });

  it('labels 422 issues by code, never echoing Pydantic text', () => {
    expect(publicationErrorMessage(RELEASE_NOTE_BLANK_ERROR)).toBe('Enter a release note.');
    expect(publicationErrorMessage({ field: 'release_note', code: 'too_long', message: 'x' }))
      .toBe('Release note must be at most 2000 characters.');
    expect(publicationErrorMessage({ field: 'release_note', code: 'strict_type', message: 'Input should be a valid string' }))
      .toBe('The release note was refused.');
    expect(publicationErrorMessage({ field: 'lock_version', code: 'out_of_range', message: 'x' }))
      .toBe('The draft lock version was refused. Reload the preview.');
    const leak = {
      field: '$', code: 'strict_type', message: 'Input should be a valid dictionary or instance of PublishReleaseRequest',
    };
    expect(publicationErrorMessage(leak)).toBe('The publish request was refused.');
    expect(publicationErrorMessage(leak)).not.toContain('PublishReleaseRequest');
    // Candidate issues are the service's own triples (the workbench shows the same ones).
    expect(publicationErrorMessage({
      field: 'definitions.architect.prompt_text', code: 'blank', message: 'Prompt text must not be blank.',
    })).toBe('Architect: Prompt text must not be blank.');
  });

  it.each(['constructor', '__proto__', 'toString', 'hasOwnProperty'])(
    'refuses the inherited Object key %s as a role (fix round 1, m3)',
    (key) => {
      expect(publicationErrorMessage({ field: `definitions.${key}.prompt_text`, code: 'blank', message: 'leaked text' }))
        .toBe('The publish request was refused.');
    },
  );
});

// ============================================================
// #270 Task 7: the history, inspection and rollback slices of the one reducer
// ============================================================

/** A rollback to Graph Version 2 with its preview loaded (note = the default). */
function confirming(state = ready(), preview = syntheticRollbackPreview()): ReviewAndPublishState {
  return run([
    { type: 'rollbackOpened', requestId: 10, versionNumber: 2 },
    { type: 'rollbackPreviewSucceeded', requestId: 10, preview },
  ], state);
}

function rollingBack(state = confirming()): ReviewAndPublishState {
  return reviewAndPublishReducer(state, { type: 'rollbackStarted', requestId: 11 });
}

describe('reviewAndPublishReducer: the history list', () => {
  it('starts idle, loads, and shows the list of the current request', () => {
    expect(createReviewAndPublishState().history.status).toBe('idle');
    const loading = run([{ type: 'historyRequested', requestId: 1 }]);
    expect(loading.history.status).toBe('loading');
    const loaded = run([{ type: 'historySucceeded', requestId: 1, history: syntheticReleaseHistory() }], loading);
    expect(loaded.history).toEqual({ status: 'ready', list: syntheticReleaseHistory(), requestId: null, errorMessage: null });
  });

  it('drops an out-of-order history answer by the one request counter', () => {
    const state = run([
      { type: 'historyRequested', requestId: 1 },
      { type: 'historyRequested', requestId: 2 },
      { type: 'historySucceeded', requestId: 2, history: syntheticRestoredReleaseHistory() },
    ]);
    const late = run([{ type: 'historySucceeded', requestId: 1, history: syntheticReleaseHistory() }], state);
    expect(late).toBe(state);
    expect(late.history.list?.active_release.version_number).toBe(5);
    expect(run([{ type: 'historyFailed', requestId: 1, message: 'late' }], state)).toBe(state);
  });

  it('keeps the shown list while a refetch loads, and shows a failed read as an error', () => {
    const loaded = run([
      { type: 'historyRequested', requestId: 1 },
      { type: 'historySucceeded', requestId: 1, history: syntheticReleaseHistory() },
      { type: 'historyRequested', requestId: 2 },
    ]);
    expect(loaded.history.list).toEqual(syntheticReleaseHistory());
    const failed = run([{ type: 'historyFailed', requestId: 2, message: 'boom' }], loaded);
    expect(failed.history.status).toBe('error');
    expect(failed.history.errorMessage).toBe('boom');
  });
});

describe('reviewAndPublishReducer: inspection', () => {
  it('goes none -> loading -> shown for the current request only', () => {
    expect(createReviewAndPublishState().inspection.status).toBe('none');
    const loading = run([{ type: 'inspectRequested', requestId: 3, versionNumber: 2 }]);
    expect(loading.inspection.status).toBe('loading');
    expect(loading.inspection.versionNumber).toBe(2);
    const newer = run([{ type: 'inspectRequested', requestId: 4, versionNumber: 3 }], loading);
    const stale = run([{ type: 'inspectSucceeded', requestId: 3, detail: syntheticReleaseDetail(), comparison: syntheticReleaseComparison() }], newer);
    expect(stale).toBe(newer);
    const shown = run([{ type: 'inspectSucceeded', requestId: 4, detail: syntheticReleaseDetail(), comparison: syntheticReleaseComparison() }], newer);
    expect(shown.inspection.status).toBe('shown');
    expect(shown.inspection.detail).toEqual(syntheticReleaseDetail());
  });

  it('returns a failed inspection to none with a message', () => {
    const failed = run([
      { type: 'inspectRequested', requestId: 3, versionNumber: 2 },
      { type: 'inspectFailed', requestId: 3, message: 'boom' },
    ]);
    expect(failed.inspection.status).toBe('none');
    expect(failed.inspection.errorMessage).toBe('boom');
  });
});

describe('reviewAndPublishReducer: the rollback preview', () => {
  it('starts closed, loads, and confirms a restorable preview with the default note', () => {
    expect(createReviewAndPublishState().rollback.status).toBe('closed');
    const loading = run([{ type: 'rollbackOpened', requestId: 10, versionNumber: 2 }], ready());
    expect(loading.rollback.status).toBe('previewLoading');
    const state = confirming();
    expect(state.rollback.status).toBe('confirming');
    expect(state.rollback.note).toBe('Roll back to Graph Version 2.');
    expect(canConfirmRollback(state)).toBe(true);
  });

  it('shows a blocked preview as blocked, with its issues, and refuses confirm', () => {
    const state = confirming(ready(), syntheticBlockedRollbackPreview());
    expect(state.rollback.status).toBe('blocked');
    expect(state.rollback.blocked).toEqual({
      reason: 'incompatible',
      source: releaseRef(2),
      active: releaseRef(4),
      issues: syntheticBlockedRollbackPreview().issues,
    });
    expect(canConfirmRollback(state)).toBe(false);
    expect(reviewAndPublishReducer(state, { type: 'rollbackStarted', requestId: 11 })).toBe(state);
  });

  it('drops an out-of-order rollback preview by the one request counter', () => {
    const state = run([
      { type: 'rollbackOpened', requestId: 10, versionNumber: 2 },
      { type: 'rollbackOpened', requestId: 12, versionNumber: 3 },
    ], ready());
    const late = run([{ type: 'rollbackPreviewSucceeded', requestId: 10, preview: syntheticRollbackPreview() }], state);
    expect(late).toBe(state);
    expect(late.rollback.versionNumber).toBe(3);
    expect(run([{ type: 'rollbackPreviewFailed', requestId: 10, message: 'late' }], state)).toBe(state);
  });

  it('drops an out-of-order release preview while a rollback is open (one counter, both reads)', () => {
    const state = run([
      { type: 'reloadPreview', requestId: 20 },
      { type: 'reloadPreview', requestId: 21 },
    ], confirming());
    expect(run([{ type: 'previewSucceeded', requestId: 20, preview: syntheticPublishedReleasePreview() }], state)).toBe(state);
  });
});

describe('canConfirmRollback: the confirm guard', () => {
  it.each(['', '   ', '\n\t'])('refuses the blank note %j', (note) => {
    const state = reviewAndPublishReducer(confirming(), { type: 'rollbackNoteChanged', note });
    expect(canConfirmRollback(state)).toBe(false);
    expect(reviewAndPublishReducer(state, { type: 'rollbackStarted', requestId: 11 })).toBe(state);
  });

  it('caps the note at 2000 code points, as the server counts them', () => {
    const at = reviewAndPublishReducer(confirming(), { type: 'rollbackNoteChanged', note: '\u{1F680}'.repeat(2000) });
    expect(canConfirmRollback(at)).toBe(true);
    const over = reviewAndPublishReducer(confirming(), { type: 'rollbackNoteChanged', note: 'x'.repeat(2001) });
    expect(canConfirmRollback(over)).toBe(false);
  });

  it('is allowed only from confirming', () => {
    expect(canConfirmRollback(run([{ type: 'rollbackOpened', requestId: 10, versionNumber: 2 }], ready()))).toBe(false);
    expect(canConfirmRollback(rollingBack())).toBe(false);
    expect(canConfirmRollback(ready())).toBe(false);
  });
});

describe('the one write gate (Correction 39)', () => {
  it('publish is refused while rollingBack', () => {
    const state = rollingBack();
    expect(state.rollback.status).toBe('rollingBack');
    expect(canPublish(state)).toBe(false);
    expect(reviewAndPublishReducer(state, { type: 'publishStarted', requestId: 30 })).toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'reloadPreview', requestId: 30 })).toBe(state);
  });

  it('openRollback and confirm are refused while publishing', () => {
    const open = publishing();
    expect(reviewAndPublishReducer(open, { type: 'rollbackOpened', requestId: 30, versionNumber: 2 })).toBe(open);
    const confirmThenPublish = reviewAndPublishReducer(confirming(), { type: 'publishStarted', requestId: 31 });
    expect(confirmThenPublish.status).toBe('publishing');
    expect(canConfirmRollback(confirmThenPublish)).toBe(false);
    expect(reviewAndPublishReducer(confirmThenPublish, { type: 'rollbackStarted', requestId: 32 })).toBe(confirmThenPublish);
  });

  it('a second rollback cannot open, cancel or restart while one is in flight', () => {
    const state = rollingBack();
    expect(reviewAndPublishReducer(state, { type: 'rollbackOpened', requestId: 30, versionNumber: 3 })).toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'rollbackCancelled' })).toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'rollbackStarted', requestId: 31 })).toBe(state);
    expect(reviewAndPublishReducer(state, { type: 'rollbackNoteChanged', note: 'x' })).toBe(state);
  });
});

describe('reviewAndPublishReducer: rollback outcomes', () => {
  it('drops an outcome from another request id', () => {
    const state = rollingBack();
    expect(reviewAndPublishReducer(state, { type: 'rollbackSucceeded', requestId: 99, result: syntheticRollbackSuccess() })).toBe(state);
  });

  it('stores the restored release and clears the note', () => {
    const state = reviewAndPublishReducer(rollingBack(), { type: 'rollbackSucceeded', requestId: 11, result: syntheticRollbackSuccess() });
    expect(state.rollback.status).toBe('restored');
    expect(state.rollback.restored).toEqual(syntheticRollbackSuccess());
    expect(state.rollback.note).toBe('');
    // A restored rollback accepts no further edits.
    expect(reviewAndPublishReducer(state, { type: 'rollbackNoteChanged', note: 'x' })).toBe(state);
  });

  it('keeps an edited note through a stale 409 and its explicit reload', () => {
    const edited = reviewAndPublishReducer(confirming(), { type: 'rollbackNoteChanged', note: 'Emergency: v4 broke outlines' });
    const stale = run([
      { type: 'rollbackStarted', requestId: 11 },
      { type: 'rollbackStale', requestId: 11, conflict: syntheticStaleRollback() },
    ], edited);
    expect(stale.rollback.status).toBe('stale');
    expect(stale.rollback.stale).toEqual(syntheticStaleRollback());
    expect(canConfirmRollback(stale)).toBe(false);
    const reloaded = run([
      { type: 'rollbackReloaded', requestId: 12 },
      { type: 'rollbackPreviewSucceeded', requestId: 12, preview: syntheticRollbackPreview({ lock_version: 5 }) },
    ], stale);
    expect(reloaded.rollback.status).toBe('confirming');
    expect(reloaded.rollback.preview?.lock_version).toBe(5);
    expect(reloaded.rollback.note).toBe('Emergency: v4 broke outlines');
    expect(reloaded.rollback.stale).toBeNull();
  });

  it('resets an unedited note to the reloaded preview\'s default', () => {
    const stale = run([
      { type: 'rollbackStarted', requestId: 11 },
      { type: 'rollbackStale', requestId: 11, conflict: syntheticStaleRollback() },
      { type: 'rollbackReloaded', requestId: 12 },
      { type: 'rollbackPreviewSucceeded', requestId: 12, preview: syntheticRollbackPreview({ default_release_note: 'Roll back to Graph Version 2 again.' }) },
    ], confirming());
    expect(stale.rollback.note).toBe('Roll back to Graph Version 2 again.');
  });

  it('shows an invalid note, and an edit returns to confirming', () => {
    const invalid = run([{ type: 'rollbackInvalid', requestId: 11, errors: syntheticRollbackInvalid().errors }], rollingBack());
    expect(invalid.rollback.status).toBe('invalid');
    expect(canConfirmRollback(invalid)).toBe(false);
    const edited = reviewAndPublishReducer(invalid, { type: 'rollbackNoteChanged', note: 'A real note' });
    expect(edited.rollback.status).toBe('confirming');
    expect(edited.rollback.errors).toEqual([]);
    expect(canConfirmRollback(edited)).toBe(true);
  });

  it('cancels back to closed', () => {
    expect(reviewAndPublishReducer(confirming(), { type: 'rollbackCancelled' }).rollback).toEqual(createReviewAndPublishState().rollback);
  });
});

describe('rollbackFailureAction: keyed on the typed code, never on message text', () => {
  const failure = (status: number, payload: unknown) => new AgentDefinitionApiError(status, payload);

  it('maps each typed refusal', () => {
    expect(rollbackFailureAction(7, failure(409, syntheticStaleRollback()))).toEqual({
      type: 'rollbackStale', requestId: 7, conflict: syntheticStaleRollback(),
    });
    expect(rollbackFailureAction(7, failure(422, syntheticRollbackInvalid()))).toEqual({
      type: 'rollbackInvalid', requestId: 7, errors: syntheticRollbackInvalid().errors,
    });
    expect(rollbackFailureAction(7, failure(422, syntheticRollbackIncompatible()))).toMatchObject({
      type: 'rollbackBlocked', blocked: { reason: 'incompatible', issues: syntheticRollbackIncompatible().errors },
    });
    expect(rollbackFailureAction(7, failure(409, { code: 'rollback_source_active', active_release: releaseRef(4) })))
      .toMatchObject({ type: 'rollbackBlocked', blocked: { reason: 'source_is_active' } });
    expect(rollbackFailureAction(7, failure(409, { code: 'rollback_matches_active', active_release: releaseRef(4), source: releaseRef(2) })))
      .toMatchObject({ type: 'rollbackBlocked', blocked: { reason: 'matches_active', source: releaseRef(2), active: releaseRef(4) } });
  });

  it('maps an invalid response, another status and a network failure to fixed client copy', () => {
    expect(rollbackFailureAction(7, new InvalidReleaseResponseError())).toMatchObject({ type: 'rollbackFailed' });
    expect(rollbackFailureAction(7, failure(500, { detail: 'Graph configuration is incomplete' }))).toEqual({
      type: 'rollbackFailed', requestId: 7,
      message: 'Unable to roll back (500). Reload Release History to see the active Graph Version.',
    });
    expect(rollbackFailureAction(7, new TypeError('fetch failed'))).toMatchObject({
      message: 'Unable to confirm the rollback. Reload Release History to see the active Graph Version.',
    });
  });
});

describe('rollback labels', () => {
  it('labels the three draft effects (Q7)', () => {
    expect(DRAFT_EFFECT_LABELS).toEqual({
      reset: 'Reset to restored content',
      kept: 'Pending edit kept',
      unchanged: 'Unchanged',
    });
  });

  it('labels rollback 422 issues by code, never echoing Pydantic text', () => {
    expect(rollbackErrorMessage({ field: 'release_note', code: 'blank', message: 'Release note must not be blank.' })).toBe('Enter a rollback note.');
    expect(rollbackErrorMessage({ field: 'release_note', code: 'too_long', message: 'x' })).toBe('Rollback note must be at most 2000 characters.');
    expect(rollbackErrorMessage({ field: '$', code: 'strict_type', message: 'Input should be a valid dictionary or instance of RollbackRequest' }))
      .toBe('The rollback request was refused.');
    expect(rollbackErrorMessage({ field: 'definitions.builder.model.endpoint_name', code: 'c', message: 'Endpoint name is not allowed.' }))
      .toBe('Builder: Endpoint name is not allowed.');
  });

  it('says why nothing was restored, by block code', () => {
    const blocked = { source: releaseRef(2), active: releaseRef(4), issues: [] };
    expect(rollbackBlockedMessage({ ...blocked, reason: 'source_is_active' })).toBe('Graph Version 2 is already active.');
    expect(rollbackBlockedMessage({ ...blocked, reason: 'matches_active' }))
      .toBe('Graph Version 2 has the same definitions as the active Graph Version 4.');
  });
});
