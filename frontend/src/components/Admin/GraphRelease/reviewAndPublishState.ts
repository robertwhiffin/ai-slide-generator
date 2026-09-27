import {
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  RELEASE_NOTE_MAX_LENGTH,
  type AgentKey,
  type DraftFieldError,
  type DraftReadiness,
  type NothingToPublishResponse,
  type PublicationGap,
  type PublicationNotReadyResponse,
  type PublicationValidationErrorResponse,
  type PublishReleaseFailure,
  type PublishReleaseSuccessResponse,
  type ReadinessStatus,
  type ReleasePreviewResponse,
  type StalePublicationResponse,
} from '../../../api/agentDefinitions';
import type { DraftStatus } from '../AgentDefinitionWorkbench/draftEditorState';

/**
 * The Review & Publish page's one state machine (#269 Task 6).
 *
 * `publish` is allowed only from `ready` (see `canPublish`). Every other outcome waits
 * for an explicit `reloadPreview`: nothing here retries a publish. Responses carry the
 * request id they answer, and any response for a request that is no longer current is
 * dropped.
 */
export type ReviewStatus =
  | 'loading'
  | 'ready'
  | 'publishing'
  | 'stale'
  | 'notReady'
  | 'invalid'
  | 'nothingToPublish'
  | 'published'
  | 'error';

export interface ReviewAndPublishState {
  status: ReviewStatus;
  /** The latest applied preview; kept through every refusal so the review stays visible. */
  preview: ReleasePreviewResponse | null;
  /** The typed release note. Only a successful publish clears it. */
  note: string;
  /** The one preview read whose response may be applied. */
  previewRequestId: number | null;
  /** The one publish whose outcome may be applied. */
  publishRequestId: number | null;
  stale: StalePublicationResponse | null;
  notReady: PublicationNotReadyResponse | null;
  nothingToPublish: NothingToPublishResponse | null;
  /** The refused 422 issues. */
  errors: DraftFieldError[];
  published: PublishReleaseSuccessResponse | null;
  errorMessage: string | null;
}

export type ReviewAndPublishAction =
  | { type: 'reloadPreview'; requestId: number }
  | { type: 'previewSucceeded'; requestId: number; preview: ReleasePreviewResponse }
  | { type: 'previewFailed'; requestId: number; message: string }
  | { type: 'noteChanged'; note: string }
  | { type: 'publishStarted'; requestId: number }
  | { type: 'publishSucceeded'; requestId: number; result: PublishReleaseSuccessResponse }
  | { type: 'publishStale'; requestId: number; conflict: StalePublicationResponse }
  | { type: 'publishNotReady'; requestId: number; refusal: PublicationNotReadyResponse }
  | { type: 'publishNothing'; requestId: number; refusal: NothingToPublishResponse }
  | { type: 'publishInvalid'; requestId: number; rejection: PublicationValidationErrorResponse }
  | { type: 'publishFailed'; requestId: number; message: string };

export function createReviewAndPublishState(): ReviewAndPublishState {
  return {
    status: 'loading',
    preview: null,
    note: '',
    previewRequestId: null,
    publishRequestId: null,
    stale: null,
    notReady: null,
    nothingToPublish: null,
    errors: [],
    published: null,
    errorMessage: null,
  };
}

/** The note's length as the server counts it: Python `len`, i.e. code points (C10). */
export function releaseNoteLength(note: string): number {
  return [...note].length;
}

/**
 * Correction 22: `ready`, the server's `publishable`, a non-blank note, and at most 2000
 * code points. Readiness never enters this decision (C32): it is shown, not used.
 */
export function canPublish(state: ReviewAndPublishState): boolean {
  return state.status === 'ready'
    && state.preview !== null
    && state.preview.publishable
    && state.note.trim() !== ''
    && releaseNoteLength(state.note) <= RELEASE_NOTE_MAX_LENGTH;
}

const CLEARED_REFUSALS: Pick<ReviewAndPublishState, 'stale' | 'notReady' | 'nothingToPublish' | 'errors' | 'errorMessage'> = {
  stale: null,
  notReady: null,
  nothingToPublish: null,
  errors: [],
  errorMessage: null,
};

type PublishOutcome = Exclude<ReviewAndPublishAction, { type: 'publishStarted' | 'reloadPreview' | 'previewSucceeded' | 'previewFailed' | 'noteChanged' }>;

function settlePublish(state: ReviewAndPublishState, action: PublishOutcome): ReviewAndPublishState {
  if (state.status !== 'publishing' || action.requestId !== state.publishRequestId) return state;
  const settled = { ...state, ...CLEARED_REFUSALS, publishRequestId: null };
  switch (action.type) {
    case 'publishSucceeded':
      return { ...settled, status: 'published', published: action.result, note: '' };
    case 'publishStale':
      return { ...settled, status: 'stale', stale: action.conflict };
    case 'publishNotReady':
      return { ...settled, status: 'notReady', notReady: action.refusal };
    case 'publishNothing':
      return { ...settled, status: 'nothingToPublish', nothingToPublish: action.refusal };
    case 'publishInvalid':
      return { ...settled, status: 'invalid', errors: action.rejection.errors };
    case 'publishFailed':
      return { ...settled, status: 'error', errorMessage: action.message };
  }
}

export function reviewAndPublishReducer(
  state: ReviewAndPublishState,
  action: ReviewAndPublishAction,
): ReviewAndPublishState {
  switch (action.type) {
    case 'reloadPreview':
      if (state.status === 'publishing') return state;
      // After a publish the success panel stays; the refetched preview lands beneath it.
      return state.status === 'published'
        ? { ...state, previewRequestId: action.requestId, errorMessage: null }
        : { ...state, ...CLEARED_REFUSALS, status: 'loading', previewRequestId: action.requestId };
    case 'previewSucceeded':
      if (action.requestId !== state.previewRequestId) return state;
      return {
        ...state,
        preview: action.preview,
        previewRequestId: null,
        status: state.status === 'published' ? 'published' : 'ready',
      };
    case 'previewFailed':
      if (action.requestId !== state.previewRequestId) return state;
      // Even after a publish a failed read is an `error`, whose Reload preview leads back
      // to `loading` and `ready`; `published` keeps the release on record (m2).
      return { ...state, previewRequestId: null, status: 'error', errorMessage: action.message };
    case 'noteChanged':
      if (state.status === 'publishing') return state;
      // Editing the note answers a refused note: the issues are cleared and Publish may
      // be tried again. Every other refusal still needs an explicit reloadPreview.
      return state.status === 'invalid'
        ? { ...state, note: action.note, status: 'ready', errors: [] }
        : { ...state, note: action.note };
    case 'publishStarted':
      if (!canPublish(state)) return state;
      return { ...state, ...CLEARED_REFUSALS, status: 'publishing', publishRequestId: action.requestId };
    default:
      return settlePublish(state, action);
  }
}

/** Maps a `publishRelease` rejection to its outcome action, keyed on the typed `code`. */
export function publishFailureAction(requestId: number, error: unknown): ReviewAndPublishAction {
  if (error instanceof AgentDefinitionApiError && (error.status === 409 || error.status === 422)) {
    // `publishRelease` throws these statuses only with a strictly parsed payload.
    const failure = error.payload as PublishReleaseFailure;
    switch (failure.code) {
      case 'stale_publication':
        return { type: 'publishStale', requestId, conflict: failure };
      case 'nothing_to_publish':
        return { type: 'publishNothing', requestId, refusal: failure };
      case 'publication_not_ready':
        return { type: 'publishNotReady', requestId, refusal: failure };
      case 'invalid_publication':
        return { type: 'publishInvalid', requestId, rejection: failure };
    }
  }
  if (error instanceof InvalidReleaseResponseError) {
    return {
      type: 'publishFailed',
      requestId,
      message: 'The server returned an invalid publication response. Reload the preview.',
    };
  }
  if (error instanceof AgentDefinitionApiError) {
    return {
      type: 'publishFailed',
      requestId,
      message: `Unable to publish (${error.status}). Reload the preview to see the current Graph Version.`,
    };
  }
  // The request may or may not have reached the server: never claim either way.
  return {
    type: 'publishFailed',
    requestId,
    message: 'Unable to confirm the publication. Reload the preview to see the current Graph Version.',
  };
}

/** Fixed client copy for a failed preview read; server or proxy text is never shown. */
export function previewErrorMessage(error: unknown): string {
  if (error instanceof InvalidReleaseResponseError) return 'The release preview response was invalid.';
  if (error instanceof AgentDefinitionApiError) return `Unable to load the release preview (${error.status}).`;
  return 'Unable to load the release preview. Check your connection and try again.';
}

/** Graph-order role labels; `test_graph_release_client_join.py` pins them to the server. */
export const ROLE_LABELS: Record<AgentKey, string> = {
  architect: 'Architect',
  data_analyst: 'Data Analyst',
  builder: 'Builder',
  build_reviewer: 'Build Reviewer',
  fixer: 'Fixer',
  fix_reviewer: 'Fix Reviewer',
  deck_reviewer: 'Deck Reviewer',
};

/** Correction 54: the case-status labels, each one of the workbench's `DraftStatus` values. */
const READINESS_STATUS_LABELS = {
  needs_test: 'Needs test',
  test_failed: 'Test failed',
  awaiting_review: 'Awaiting review',
  approved: 'Approved',
} as const satisfies Record<ReadinessStatus, DraftStatus>;

export function readinessStatusLabel(status: ReadinessStatus): DraftStatus {
  return READINESS_STATUS_LABELS[status];
}

/**
 * A gate gap in client copy (C1). The case name comes from the refusal's informational
 * readiness when it lists the case; otherwise the case is named by id.
 */
export function publicationGapLabel(gap: PublicationGap, readiness: DraftReadiness): string {
  const role = ROLE_LABELS[gap.agent_key];
  switch (gap.code) {
    case 'no_required_case':
      return `${role}: no active required test case`;
    case 'no_eligible_approval': {
      const item = readiness.agents
        .find((agent) => agent.agent_key === gap.agent_key)
        ?.cases.find((entry) => entry.test_case_id === gap.test_case_id);
      return `${role}: ${item ? item.test_case_name : `test case ${gap.test_case_id}`} has no eligible approval`;
    }
  }
}

const DEFINITION_ISSUE_FIELD = /^definitions\.([a-z_]+)\./;

/**
 * One 422 issue in client copy, keyed on `field` and `code`. A Pydantic message can name
 * a Python class, so structural issues get fixed copy. Only a `definitions.<role>.*`
 * candidate issue shows its message: those are the service's own triples, the ones the
 * workbench's save shows.
 */
export function publicationErrorMessage(error: DraftFieldError): string {
  if (error.field === 'release_note') {
    if (error.code === 'blank') return 'Enter a release note.';
    if (error.code === 'too_long') return `Release note must be at most ${RELEASE_NOTE_MAX_LENGTH} characters.`;
    return 'The release note was refused.';
  }
  if (error.field === 'lock_version') return 'The draft lock version was refused. Reload the preview.';
  const role = DEFINITION_ISSUE_FIELD.exec(error.field)?.[1];
  if (role !== undefined && Object.hasOwn(ROLE_LABELS, role)) return `${ROLE_LABELS[role as AgentKey]}: ${error.message}`;
  return 'The publish request was refused.';
}
