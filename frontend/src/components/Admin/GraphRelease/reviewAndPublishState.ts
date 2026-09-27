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
  type DraftEffect,
  type ReleaseComparisonResponse,
  type ReleaseDetailResponse,
  type ReleaseEvidenceKind,
  type ReleaseHistoryListResponse,
  type ReleaseIdentity,
  type ReleaseRunVerdict,
  type RollbackBlock,
  type RollbackFailure,
  type RollbackPreviewResponse,
  type RollbackSuccessResponse,
  type StaleRollbackResponse,
} from '../../../api/agentDefinitions';
import type { DraftStatus } from '../AgentDefinitionWorkbench/draftEditorState';

/**
 * The Review & Publish page's one state machine (#269 Task 6; #270 Task 7 adds the
 * Release History slices to it, not a second reducer).
 *
 * `publish` is allowed only from `ready` (see `canPublish`). Every other outcome waits
 * for an explicit `reloadPreview`: nothing here retries a publish. Responses carry the
 * request id they answer, and any response for a request that is no longer current is
 * dropped.
 *
 * The page has one write gate for both writes (Correction 39): `publishStarted` is
 * refused while a rollback is `rollingBack`, and `rollbackOpened`, `rollbackReloaded`
 * and `rollbackStarted` are refused while the page is `publishing`.
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
  /** #270: the Release History list. */
  history: HistorySlice;
  /** #270: the one inspected Graph Version (detail and comparison with active). */
  inspection: InspectionSlice;
  /** #270: the one rollback being previewed, confirmed or settled. */
  rollback: RollbackSlice;
}

export type HistoryStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface HistorySlice {
  status: HistoryStatus;
  /** The latest applied list; kept while a refetch loads. */
  list: ReleaseHistoryListResponse | null;
  requestId: number | null;
  errorMessage: string | null;
}

export type InspectionStatus = 'none' | 'loading' | 'shown';

export interface InspectionSlice {
  status: InspectionStatus;
  versionNumber: number | null;
  detail: ReleaseDetailResponse | null;
  comparison: ReleaseComparisonResponse | null;
  requestId: number | null;
  /** A failed read returns to `none` with this message. */
  errorMessage: string | null;
}

export type RollbackStatus =
  | 'closed'
  | 'previewLoading'
  | 'confirming'
  | 'rollingBack'
  | 'stale'
  | 'blocked'
  | 'invalid'
  | 'restored'
  | 'error';

/** Why nothing was restored: a blocked preview, or a refused rollback POST. */
export interface RollbackBlocked {
  reason: RollbackBlock;
  source: ReleaseIdentity;
  active: ReleaseIdentity;
  issues: DraftFieldError[];
}

export interface RollbackSlice {
  status: RollbackStatus;
  /** The Graph Version being restored (a version, never an id). */
  versionNumber: number | null;
  preview: RollbackPreviewResponse | null;
  /** Starts as the preview's `default_release_note`; an edit survives a stale reload. */
  note: string;
  noteEdited: boolean;
  previewRequestId: number | null;
  postRequestId: number | null;
  stale: StaleRollbackResponse | null;
  blocked: RollbackBlocked | null;
  /** The refused `invalid_rollback` issues. */
  errors: DraftFieldError[];
  restored: RollbackSuccessResponse | null;
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
  | { type: 'publishFailed'; requestId: number; message: string }
  | { type: 'historyRequested'; requestId: number }
  | { type: 'historySucceeded'; requestId: number; history: ReleaseHistoryListResponse }
  | { type: 'historyFailed'; requestId: number; message: string }
  | { type: 'inspectRequested'; requestId: number; versionNumber: number }
  | { type: 'inspectSucceeded'; requestId: number; detail: ReleaseDetailResponse; comparison: ReleaseComparisonResponse }
  | { type: 'inspectFailed'; requestId: number; message: string }
  | { type: 'rollbackOpened'; requestId: number; versionNumber: number }
  | { type: 'rollbackReloaded'; requestId: number }
  | { type: 'rollbackPreviewSucceeded'; requestId: number; preview: RollbackPreviewResponse }
  | { type: 'rollbackPreviewFailed'; requestId: number; message: string }
  | { type: 'rollbackNoteChanged'; note: string }
  | { type: 'rollbackCancelled' }
  | { type: 'rollbackStarted'; requestId: number }
  | { type: 'rollbackSucceeded'; requestId: number; result: RollbackSuccessResponse }
  | { type: 'rollbackStale'; requestId: number; conflict: StaleRollbackResponse }
  | { type: 'rollbackBlocked'; requestId: number; blocked: RollbackBlocked }
  | { type: 'rollbackInvalid'; requestId: number; errors: DraftFieldError[] }
  | { type: 'rollbackFailed'; requestId: number; message: string };

function createHistorySlice(): HistorySlice {
  return { status: 'idle', list: null, requestId: null, errorMessage: null };
}

function createInspectionSlice(): InspectionSlice {
  return { status: 'none', versionNumber: null, detail: null, comparison: null, requestId: null, errorMessage: null };
}

function createRollbackSlice(): RollbackSlice {
  return {
    status: 'closed',
    versionNumber: null,
    preview: null,
    note: '',
    noteEdited: false,
    previewRequestId: null,
    postRequestId: null,
    stale: null,
    blocked: null,
    errors: [],
    restored: null,
    errorMessage: null,
  };
}

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
    history: createHistorySlice(),
    inspection: createInspectionSlice(),
    rollback: createRollbackSlice(),
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
    // The one write gate (Correction 39): no publish while a rollback is in flight.
    && state.rollback.status !== 'rollingBack'
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

type PublishOutcome = Extract<ReviewAndPublishAction, {
  type: 'publishSucceeded' | 'publishStale' | 'publishNotReady' | 'publishNothing' | 'publishInvalid' | 'publishFailed';
}>;

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
      if (state.status === 'publishing' || state.rollback.status === 'rollingBack') return state;
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
    case 'publishSucceeded':
    case 'publishStale':
    case 'publishNotReady':
    case 'publishNothing':
    case 'publishInvalid':
    case 'publishFailed':
      return settlePublish(state, action);
    case 'historyRequested':
    case 'historySucceeded':
    case 'historyFailed': {
      const history = historyReducer(state.history, action);
      return history === state.history ? state : { ...state, history };
    }
    case 'inspectRequested':
    case 'inspectSucceeded':
    case 'inspectFailed': {
      const inspection = inspectionReducer(state.inspection, action);
      return inspection === state.inspection ? state : { ...state, inspection };
    }
    default:
      return rollbackReducer(state, action);
  }
}

type HistoryAction = Extract<ReviewAndPublishAction, { type: 'historyRequested' | 'historySucceeded' | 'historyFailed' }>;

function historyReducer(history: HistorySlice, action: HistoryAction): HistorySlice {
  if (action.type === 'historyRequested') {
    return { ...history, status: 'loading', requestId: action.requestId, errorMessage: null };
  }
  if (action.requestId !== history.requestId) return history;
  if (action.type === 'historySucceeded') {
    return { status: 'ready', list: action.history, requestId: null, errorMessage: null };
  }
  return { ...history, status: 'error', requestId: null, errorMessage: action.message };
}

type InspectionAction = Extract<ReviewAndPublishAction, { type: 'inspectRequested' | 'inspectSucceeded' | 'inspectFailed' }>;

function inspectionReducer(inspection: InspectionSlice, action: InspectionAction): InspectionSlice {
  if (action.type === 'inspectRequested') {
    return {
      status: 'loading',
      versionNumber: action.versionNumber,
      detail: null,
      comparison: null,
      requestId: action.requestId,
      errorMessage: null,
    };
  }
  if (action.requestId !== inspection.requestId) return inspection;
  if (action.type === 'inspectSucceeded') {
    return { ...inspection, status: 'shown', detail: action.detail, comparison: action.comparison, requestId: null };
  }
  return { ...createInspectionSlice(), errorMessage: action.message };
}

/**
 * `confirm` (Correction 39, #270 brief): only from `confirming`, with a restorable
 * preview, a non-blank note of at most 2000 code points (the server's count, as for
 * publish), and while the page's one write gate is free.
 */
export function canConfirmRollback(state: ReviewAndPublishState): boolean {
  const { rollback } = state;
  return rollback.status === 'confirming'
    && state.status !== 'publishing'
    && rollback.preview !== null
    && rollback.preview.restorable
    && rollback.note.trim() !== ''
    && releaseNoteLength(rollback.note) <= RELEASE_NOTE_MAX_LENGTH;
}

type RollbackAction = Extract<ReviewAndPublishAction, { type: `rollback${string}` }>;

type RollbackOutcome = Extract<RollbackAction, {
  type: 'rollbackSucceeded' | 'rollbackStale' | 'rollbackBlocked' | 'rollbackInvalid' | 'rollbackFailed';
}>;

function withRollback(state: ReviewAndPublishState, rollback: Partial<RollbackSlice>): ReviewAndPublishState {
  return { ...state, rollback: { ...state.rollback, ...rollback } };
}

const CLEARED_ROLLBACK_REFUSALS: Pick<RollbackSlice, 'stale' | 'blocked' | 'errors' | 'errorMessage'> = {
  stale: null,
  blocked: null,
  errors: [],
  errorMessage: null,
};

function blockedByPreview(preview: RollbackPreviewResponse): RollbackBlocked | null {
  if (preview.blocked === null) return null;
  return { reason: preview.blocked, source: preview.source, active: preview.active_release, issues: preview.issues };
}

function rollbackReducer(state: ReviewAndPublishState, action: RollbackAction): ReviewAndPublishState {
  const { rollback } = state;
  const writing = state.status === 'publishing' || rollback.status === 'rollingBack';
  switch (action.type) {
    case 'rollbackOpened':
      if (writing) return state;
      return {
        ...state,
        rollback: {
          ...createRollbackSlice(),
          status: 'previewLoading',
          versionNumber: action.versionNumber,
          previewRequestId: action.requestId,
        },
      };
    case 'rollbackReloaded':
      // An explicit reload after a refusal; the typed note is kept.
      if (writing || rollback.versionNumber === null || rollback.status === 'closed' || rollback.status === 'restored') {
        return state;
      }
      return withRollback(state, { ...CLEARED_ROLLBACK_REFUSALS, status: 'previewLoading', previewRequestId: action.requestId });
    case 'rollbackPreviewSucceeded': {
      if (rollback.status !== 'previewLoading' || action.requestId !== rollback.previewRequestId) return state;
      const blocked = blockedByPreview(action.preview);
      return withRollback(state, {
        status: blocked === null ? 'confirming' : 'blocked',
        preview: action.preview,
        previewRequestId: null,
        note: rollback.noteEdited ? rollback.note : action.preview.default_release_note,
        blocked,
      });
    }
    case 'rollbackPreviewFailed':
      if (rollback.status !== 'previewLoading' || action.requestId !== rollback.previewRequestId) return state;
      return withRollback(state, { status: 'error', previewRequestId: null, errorMessage: action.message });
    case 'rollbackNoteChanged':
      if (rollback.status === 'rollingBack' || rollback.status === 'closed' || rollback.status === 'restored') return state;
      // Editing the note answers a refused note, as on publish.
      return withRollback(state, rollback.status === 'invalid'
        ? { note: action.note, noteEdited: true, status: 'confirming', errors: [] }
        : { note: action.note, noteEdited: true });
    case 'rollbackCancelled':
      if (rollback.status === 'rollingBack') return state;
      return { ...state, rollback: createRollbackSlice() };
    case 'rollbackStarted':
      if (!canConfirmRollback(state)) return state;
      return withRollback(state, { ...CLEARED_ROLLBACK_REFUSALS, status: 'rollingBack', postRequestId: action.requestId });
    default:
      return settleRollback(state, action);
  }
}

function settleRollback(state: ReviewAndPublishState, action: RollbackOutcome): ReviewAndPublishState {
  const { rollback } = state;
  if (rollback.status !== 'rollingBack' || action.requestId !== rollback.postRequestId) return state;
  const settled: Partial<RollbackSlice> = { ...CLEARED_ROLLBACK_REFUSALS, postRequestId: null };
  switch (action.type) {
    case 'rollbackSucceeded':
      return withRollback(state, { ...settled, status: 'restored', restored: action.result, note: '', noteEdited: false });
    case 'rollbackStale':
      return withRollback(state, { ...settled, status: 'stale', stale: action.conflict });
    case 'rollbackBlocked':
      return withRollback(state, { ...settled, status: 'blocked', blocked: action.blocked });
    case 'rollbackInvalid':
      return withRollback(state, { ...settled, status: 'invalid', errors: action.errors });
    case 'rollbackFailed':
      return withRollback(state, { ...settled, status: 'error', errorMessage: action.message });
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

/** Ruling Q7's three draft effects, in client copy (#270 progress ledger). */
export const DRAFT_EFFECT_LABELS: Record<DraftEffect, string> = {
  reset: 'Reset to restored content',
  kept: 'Pending edit kept',
  unchanged: 'Unchanged',
};

export const EVIDENCE_KIND_LABELS: Record<ReleaseEvidenceKind, string> = {
  approval: 'Approval',
  historical_restore: 'Historical restore',
};

export function runVerdictLabel(verdict: ReleaseRunVerdict | null): string {
  if (verdict === 'approved') return 'Approved';
  if (verdict === 'rejected') return 'Rejected';
  return 'No verdict';
}

/** Maps a `rollbackGraphRelease` rejection to its outcome action, keyed on the typed `code`. */
export function rollbackFailureAction(requestId: number, error: unknown): ReviewAndPublishAction {
  if (error instanceof AgentDefinitionApiError && (error.status === 409 || error.status === 422)) {
    // `rollbackGraphRelease` throws these statuses only with a strictly parsed payload.
    const failure = error.payload as RollbackFailure;
    switch (failure.code) {
      case 'stale_rollback':
        return { type: 'rollbackStale', requestId, conflict: failure };
      case 'invalid_rollback':
        return { type: 'rollbackInvalid', requestId, errors: failure.errors };
      case 'rollback_incompatible':
        return { type: 'rollbackBlocked', requestId, blocked: {
          reason: 'incompatible', source: failure.source, active: failure.source, issues: failure.errors,
        } };
      case 'rollback_source_active':
        return { type: 'rollbackBlocked', requestId, blocked: {
          reason: 'source_is_active', source: failure.active_release, active: failure.active_release, issues: [],
        } };
      case 'rollback_matches_active':
        return { type: 'rollbackBlocked', requestId, blocked: {
          reason: 'matches_active', source: failure.source, active: failure.active_release, issues: [],
        } };
    }
  }
  if (error instanceof InvalidReleaseResponseError) {
    return {
      type: 'rollbackFailed',
      requestId,
      message: 'The server returned an invalid rollback response. Reload Release History.',
    };
  }
  if (error instanceof AgentDefinitionApiError) {
    return {
      type: 'rollbackFailed',
      requestId,
      message: `Unable to roll back (${error.status}). Reload Release History to see the active Graph Version.`,
    };
  }
  // The request may or may not have reached the server: never claim either way.
  return {
    type: 'rollbackFailed',
    requestId,
    message: 'Unable to confirm the rollback. Reload Release History to see the active Graph Version.',
  };
}

/** Fixed client copy for a failed history, inspection or rollback-preview read. */
export function historyReadErrorMessage(subject: string, error: unknown): string {
  if (error instanceof InvalidReleaseResponseError) return `The ${subject} response was invalid.`;
  if (error instanceof AgentDefinitionApiError) return `Unable to load the ${subject} (${error.status}).`;
  return `Unable to load the ${subject}. Check your connection and try again.`;
}

/**
 * One rollback 422 issue in client copy, keyed on `field` and `code` (a Pydantic message
 * can name a Python class). Only a `definitions.<role>.*` issue shows its message: those
 * are the service's own validation triples.
 */
export function rollbackErrorMessage(error: DraftFieldError): string {
  if (error.field === 'release_note') {
    if (error.code === 'blank') return 'Enter a rollback note.';
    if (error.code === 'too_long') return `Rollback note must be at most ${RELEASE_NOTE_MAX_LENGTH} characters.`;
    return 'The rollback note was refused.';
  }
  if (error.field === 'lock_version') return 'The draft lock version was refused. Reload the rollback preview.';
  const role = DEFINITION_ISSUE_FIELD.exec(error.field)?.[1];
  if (role !== undefined && Object.hasOwn(ROLE_LABELS, role)) return `${ROLE_LABELS[role as AgentKey]}: ${error.message}`;
  return 'The rollback request was refused.';
}

/** Why a rollback restored nothing, in client copy keyed on the block code. */
export function rollbackBlockedMessage(blocked: RollbackBlocked): string {
  switch (blocked.reason) {
    case 'source_is_active':
      return `Graph Version ${blocked.source.version_number} is already active.`;
    case 'matches_active':
      return `Graph Version ${blocked.source.version_number} has the same definitions as the active Graph Version ${blocked.active.version_number}.`;
    case 'incompatible':
      return `Graph Version ${blocked.source.version_number} cannot be restored: it fails today's validation.`;
  }
}
