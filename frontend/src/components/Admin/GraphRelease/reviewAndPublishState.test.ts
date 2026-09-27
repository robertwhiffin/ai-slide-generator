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
} from '../../../../tests/fixtures/mocks';
import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  type ReadinessStatus,
} from '../../../api/agentDefinitions';
import type { DraftStatus } from '../AgentDefinitionWorkbench/draftEditorState';
import {
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
