import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  InvalidDraftSaveResponseError,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type AssemblyCondition,
  type AssemblyRulesV2,
  type CustomAnchor,
  type CustomTextBlock,
  type DraftDefinition,
  type DraftFieldError,
  type DraftMetadata,
  type DraftSaveConflictResponse,
  type DraftSaveSuccessResponse,
  type DraftValidationErrorResponse,
  type EditableModelDraft,
  type LegacyPromptSourceResponse,
} from '../../../api/agentDefinitions';

export type DraftStatus = 'Clean' | 'Unsaved' | 'Needs test';
export type DraftNumberInput = number | '';
export type EditableDraftField =
  | 'prompt_text'
  | 'endpoint_name'
  | 'temperature'
  | 'max_tokens'
  | 'top_p';

/** The two roles whose Graph Version 1 prompt is a protected legacy composite. */
export const LEGACY_COMPOSITE_ROLES: readonly AgentKey[] = ['data_analyst', 'build_reviewer'];

export interface EditableModelDraftForm {
  prompt_text: string;
  endpoint_name: string;
  temperature: DraftNumberInput;
  max_tokens: DraftNumberInput;
  top_p: DraftNumberInput;
  /** Local v2 custom blocks, or `null` while the role is still on v1. */
  assembly_rules: AssemblyRulesV2 | null;
}

export type RetainedFormSource =
  | 'reload_server'
  | 'dirty_legacy_prompt'
  | 'pending_prompt_quarantine'
  | 'version_adoption'
  | 'legacy_source_recovery';

/**
 * One displaced alternative, addressed by a stable deterministic reducer ID.
 *
 * `form` is savable and has already been sanitized against `sanitizedFormatVersion`.
 * `manualOnlyPrompt` holds the exact displaced prompt bytes and is never read by
 * candidate construction, never auto-stripped, and never auto-reapplied.
 */
export interface RetainedDraftForm {
  id: string;
  source: RetainedFormSource;
  reason: string;
  form: EditableModelDraftForm;
  manualOnlyPrompt: string;
  sanitizedFormatVersion: 1 | 2;
}

export interface DraftEditorEntry {
  publishedHash: string;
  saved: DraftDefinition;
  local: EditableModelDraftForm;
  fieldErrors: Partial<Record<EditableDraftField, string>>;
  conflict: DraftSaveConflictResponse | null;
  /** Ordered, append-only until an explicit discard. */
  retainedForms: RetainedDraftForm[];
  nextRetainedOrdinal: number;
  /** Exact ordered server issues that have no inline field owner. */
  responseIssues: DraftFieldError[];
  requestError: string | null;
}

export type DraftOperationKind = 'save' | 'upgrade' | 'sourceRecovery';

/**
 * The one aggregate pending slot, now discriminated by operation. Save, Upgrade,
 * and SourceRecovery share this single gate; there is no second gate.
 */
export interface PendingDraftSave {
  operation: DraftOperationKind;
  requestId: number;
  agentKey: AgentKey;
  expectedLockVersion: number;
  submittedCandidate: EditableModelDraft | null;
}

export interface DraftEditorState {
  draft: DraftMetadata;
  byAgent: Record<AgentKey, DraftEditorEntry>;
  pendingSave: PendingDraftSave | null;
}

export type DraftEditorAction =
  | { type: 'edit'; agentKey: AgentKey; field: EditableDraftField; value: string | number }
  | { type: 'assemblyBlockAdded'; agentKey: AgentKey; blockId: string; anchor: CustomAnchor }
  | { type: 'assemblyBlockTextChanged'; agentKey: AgentKey; blockId: string; text: string }
  | {
    type: 'assemblyBlockConditionChanged';
    agentKey: AgentKey;
    blockId: string;
    condition: AssemblyCondition;
  }
  | { type: 'assemblyBlockDeleted'; agentKey: AgentKey; blockId: string }
  | { type: 'assemblyBlockMoved'; agentKey: AgentKey; blockId: string; direction: 'up' | 'down' }
  | { type: 'saveStarted'; pending: PendingDraftSave }
  | { type: 'saveSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'saveInvalid'; agentKey: AgentKey; errors: Partial<Record<EditableDraftField, string>> }
  | { type: 'saveRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'saveConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'saveFailed'; requestId: number; message: string }
  | { type: 'dirtyLegacyPromptRetained'; agentKey: AgentKey }
  | { type: 'upgradeStarted'; pending: PendingDraftSave }
  | { type: 'upgradeSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'upgradeRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'upgradeConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'upgradeFailed'; requestId: number; message: string }
  | { type: 'sourceRecoveryStarted'; pending: PendingDraftSave }
  | { type: 'sourceRecoverySucceeded'; requestId: number; result: LegacyPromptSourceResponse }
  | { type: 'sourceRecoveryRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'sourceRecoveryConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'sourceRecoveryFailed'; requestId: number; message: string }
  | { type: 'reloadServer'; agentKey: AgentKey }
  | { type: 'keepLocal'; agentKey: AgentKey }
  | { type: 'restoreSavedPrompt'; agentKey: AgentKey }
  | { type: 'restoreRetained'; agentKey: AgentKey; retainedId: string }
  | { type: 'discardRetained'; agentKey: AgentKey; retainedId: string };

const INVALID_RESPONSE_MESSAGE = 'Unable to save draft because the server response was invalid.';

export const RETAINED_REASONS = {
  reload_server: 'Replaced by the server draft values.',
  dirty_legacy_prompt:
    'Upgrade needs the exact Graph Version 1 prompt. This edited prompt was retained for '
    + 'manual reapplication.',
  pending_prompt_quarantine:
    'Prompt edits are not accepted while this Upgrade is in flight. The proposed prompt was '
    + 'retained for manual reapplication.',
  version_adoption:
    'The server moved this role to Graph Version 2. The displaced Graph Version 1 prompt was '
    + 'retained for manual reapplication.',
  legacy_source_recovery_saved:
    'The edited saved Graph Version 1 prompt was retained before the published source was '
    + 'installed.',
  legacy_source_recovery_local:
    'The edited local Graph Version 1 prompt was retained before the published source was '
    + 'installed.',
} as const;

const INLINE_FIELD_OWNERS: Record<string, EditableDraftField> = {
  'candidate.prompt_text': 'prompt_text',
  'candidate.model.endpoint_name': 'endpoint_name',
  'candidate.model.temperature': 'temperature',
  'candidate.model.max_tokens': 'max_tokens',
  'candidate.model.top_p': 'top_p',
};

export function isLegacyCompositeRole(agentKey: AgentKey): boolean {
  return LEGACY_COMPOSITE_ROLES.includes(agentKey);
}

export function definitionFormatVersion(definition: DraftDefinition): 1 | 2 {
  return definition.assembly_rules.format_version;
}

/** Local editable rules exist only for a v2 definition; v1 has no editable rules. */
export function localRulesFor(definition: DraftDefinition): AssemblyRulesV2 | null {
  return definition.assembly_rules.format_version === 2
    ? structuredClone(definition.assembly_rules)
    : null;
}

export function formFromDefinition(definition: DraftDefinition): EditableModelDraftForm {
  return {
    prompt_text: definition.prompt_text,
    endpoint_name: definition.model.endpoint_name,
    temperature: definition.model.temperature,
    max_tokens: definition.model.max_tokens,
    top_p: definition.model.top_p,
    assembly_rules: localRulesFor(definition),
  };
}

export function formFromCandidate(candidate: EditableModelDraft): EditableModelDraftForm {
  return {
    prompt_text: candidate.prompt_text,
    endpoint_name: candidate.model.endpoint_name,
    temperature: candidate.model.temperature,
    max_tokens: candidate.model.max_tokens,
    top_p: candidate.model.top_p,
    assembly_rules: candidate.assembly_rules ?? null,
  };
}

export function candidateFromForm(form: EditableModelDraftForm): EditableModelDraft | null {
  const validation = validateDraftForm(form);
  return validation.ok ? validation.candidate : null;
}

function assemblyRulesEqual(
  left: AssemblyRulesV2 | null,
  right: AssemblyRulesV2 | null,
): boolean {
  if (left === null || right === null) return left === right;
  if (left.custom_blocks.length !== right.custom_blocks.length) return false;
  return left.custom_blocks.every((block, index) => {
    const other = right.custom_blocks[index];
    return block.kind === other.kind
      && block.block_id === other.block_id
      && block.anchor === other.anchor
      && block.condition === other.condition
      && block.text === other.text;
  });
}

export function editableFormsEqual(
  left: EditableModelDraftForm,
  right: EditableModelDraftForm,
): boolean {
  return left.prompt_text === right.prompt_text
    && left.endpoint_name === right.endpoint_name
    && left.temperature === right.temperature
    && left.max_tokens === right.max_tokens
    && left.top_p === right.top_p
    && assemblyRulesEqual(left.assembly_rules, right.assembly_rules);
}

function cloneDefinition(definition: DraftDefinition): DraftDefinition {
  return structuredClone(definition);
}

export function retainedFormId(agentKey: AgentKey, ordinal: number): string {
  return `retained:${agentKey}:${ordinal}`;
}

/**
 * A form built while the role was on one format version cannot keep its prompt or
 * rules beside an authoritative definition on the other. Sanitizing installs the
 * authoritative prompt and rules and leaves every safe non-prompt field alone.
 */
function sanitizeForm(
  form: EditableModelDraftForm,
  fromVersion: 1 | 2,
  definition: DraftDefinition,
): EditableModelDraftForm {
  if (fromVersion === definitionFormatVersion(definition)) return { ...form };
  return {
    ...form,
    prompt_text: definition.prompt_text,
    assembly_rules: localRulesFor(definition),
  };
}

function sanitizeRetained(
  record: RetainedDraftForm,
  definition: DraftDefinition,
): RetainedDraftForm {
  return {
    ...record,
    form: sanitizeForm(record.form, record.sanitizedFormatVersion, definition),
    sanitizedFormatVersion: definitionFormatVersion(definition),
  };
}

function appendRetained(
  entry: DraftEditorEntry,
  agentKey: AgentKey,
  options: {
    source: RetainedFormSource;
    reason: string;
    form: EditableModelDraftForm;
    manualOnlyPrompt: string;
    fromVersion: 1 | 2;
    definition: DraftDefinition;
  },
): DraftEditorEntry {
  const ordinal = entry.nextRetainedOrdinal;
  return {
    ...entry,
    retainedForms: [
      ...entry.retainedForms,
      {
        id: retainedFormId(agentKey, ordinal),
        source: options.source,
        reason: options.reason,
        form: sanitizeForm(options.form, options.fromVersion, options.definition),
        manualOnlyPrompt: options.manualOnlyPrompt,
        sanitizedFormatVersion: definitionFormatVersion(options.definition),
      },
    ],
    nextRetainedOrdinal: ordinal + 1,
  };
}

/**
 * The single version-aware authoritative-definition adoption rule. Save 200,
 * Save 409, Upgrade 200, Upgrade 409, Keep local, and Reload server all reach the
 * authoritative definition through here, for the selected entry and for every
 * unselected entry alike — selection never decides whether legacy bytes are
 * quarantined.
 */
function adoptAuthoritativeDefinition(
  entry: DraftEditorEntry,
  agentKey: AgentKey,
  definition: DraftDefinition,
  options: { keepLocal: boolean; source: RetainedFormSource; reason: string },
): DraftEditorEntry {
  const fromVersion = definitionFormatVersion(entry.saved);
  const toVersion = definitionFormatVersion(definition);
  const sanitizedRetained = fromVersion === toVersion
    ? entry.retainedForms
    : entry.retainedForms.map((record) => sanitizeRetained(record, definition));
  const base: DraftEditorEntry = { ...entry, saved: definition, retainedForms: sanitizedRetained };

  if (fromVersion === toVersion) {
    return { ...base, local: options.keepLocal ? entry.local : formFromDefinition(definition) };
  }

  const quarantined = appendRetained(base, agentKey, {
    source: options.source,
    reason: options.reason,
    form: entry.local,
    manualOnlyPrompt: entry.local.prompt_text,
    fromVersion,
    definition,
  });
  return {
    ...quarantined,
    local: {
      ...entry.local,
      prompt_text: definition.prompt_text,
      assembly_rules: localRulesFor(definition),
    },
  };
}

export function createDraftEditorState(
  workbench: AgentDefinitionWorkbenchResponse,
): DraftEditorState {
  const byAgent = {} as Record<AgentKey, DraftEditorEntry>;
  for (const agentKey of AGENT_KEYS) {
    const node = workbench.nodes.find((candidate) => candidate.agent_key === agentKey);
    if (!node || node.execution_kind !== 'model') {
      throw new Error(`Agent Definition workbench is missing model role ${agentKey}.`);
    }
    const saved = cloneDefinition(node.draft);
    byAgent[agentKey] = {
      publishedHash: node.published.content_hash,
      saved,
      local: formFromDefinition(saved),
      fieldErrors: {},
      conflict: null,
      retainedForms: [],
      nextRetainedOrdinal: 1,
      responseIssues: [],
      requestError: null,
    };
  }
  return { draft: structuredClone(workbench.draft), byAgent, pendingSave: null };
}

export function draftStatus(entry: DraftEditorEntry): DraftStatus {
  if (!editableFormsEqual(entry.local, formFromDefinition(entry.saved))) return 'Unsaved';
  if (entry.saved.candidate_hash === entry.publishedHash) return 'Clean';
  return 'Needs test';
}

export function validateDraftForm(form: EditableModelDraftForm):
  | { ok: true; candidate: EditableModelDraft }
  | { ok: false; errors: Partial<Record<EditableDraftField, string>> } {
  const errors: Partial<Record<EditableDraftField, string>> = {};
  if (!form.prompt_text.trim()) errors.prompt_text = 'Prompt text must not be blank.';
  if (!form.endpoint_name.trim()) errors.endpoint_name = 'Endpoint name must not be blank.';
  if (typeof form.temperature !== 'number'
    || !Number.isFinite(form.temperature)
    || form.temperature < 0
    || form.temperature > 1) {
    errors.temperature = 'Temperature must be between 0 and 1.';
  }
  if (typeof form.max_tokens !== 'number'
    || !Number.isInteger(form.max_tokens)
    || form.max_tokens <= 0) {
    errors.max_tokens = 'Maximum tokens must be a positive integer.';
  }
  if (typeof form.top_p !== 'number'
    || !Number.isFinite(form.top_p)
    || form.top_p < 0
    || form.top_p > 1) {
    errors.top_p = 'Top-p must be between 0 and 1.';
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    candidate: {
      prompt_text: form.prompt_text,
      model: {
        endpoint_name: form.endpoint_name,
        temperature: form.temperature as number,
        max_tokens: form.max_tokens as number,
        top_p: form.top_p as number,
      },
      // A v1 candidate omits the key entirely, keeping #263's save body unchanged.
      ...(form.assembly_rules === null
        ? {}
        : { assembly_rules: structuredClone(form.assembly_rules) }),
    },
  };
}

export function draftSaveErrorMessage(error: unknown): string {
  if (error instanceof InvalidDraftSaveResponseError) return INVALID_RESPONSE_MESSAGE;
  if (error instanceof AgentDefinitionApiError) return error.detail;
  return 'Unable to save draft. Check your connection and try again.';
}

function replaceEntry(
  state: DraftEditorState,
  agentKey: AgentKey,
  entry: DraftEditorEntry,
): DraftEditorState {
  return { ...state, byAgent: { ...state.byAgent, [agentKey]: entry } };
}

function invalidCompletion(state: DraftEditorState, pending: PendingDraftSave): DraftEditorState {
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...state.byAgent[pending.agentKey],
        requestError: INVALID_RESPONSE_MESSAGE,
      },
    },
  };
}

/** The matching pending identity is the operation kind plus its request ID. */
function matchingPending(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
): PendingDraftSave | null {
  if (state.pendingSave === null) return null;
  if (state.pendingSave.operation !== operation) return null;
  if (state.pendingSave.requestId !== requestId) return null;
  return state.pendingSave;
}

function fieldErrorsFromResponse(
  error: DraftValidationErrorResponse,
): Partial<Record<EditableDraftField, string>> {
  const result: Partial<Record<EditableDraftField, string>> = {};
  for (const item of error.errors) {
    const field = INLINE_FIELD_OWNERS[item.field];
    if (field) result[field] = item.message;
  }
  return result;
}

/** Issues without an inline field owner keep their exact server order. */
function nonInlineIssues(error: DraftValidationErrorResponse): DraftFieldError[] {
  return error.errors.filter((item) => INLINE_FIELD_OWNERS[item.field] === undefined);
}

function startOperation(
  state: DraftEditorState,
  pending: PendingDraftSave,
): DraftEditorState {
  const entry = state.byAgent[pending.agentKey];
  return {
    ...replaceEntry(state, pending.agentKey, {
      ...entry,
      fieldErrors: {},
      responseIssues: [],
      requestError: null,
    }),
    pendingSave: pending,
  };
}

function rejectOperation(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  error: DraftValidationErrorResponse,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  const entry = state.byAgent[pending.agentKey];
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...entry,
        fieldErrors: operation === 'save' ? fieldErrorsFromResponse(error) : entry.fieldErrors,
        responseIssues: nonInlineIssues(error),
      },
    },
  };
}

function failOperation(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  message: string,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  const entry = state.byAgent[pending.agentKey];
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: { ...entry, requestError: message },
    },
  };
}

function mergeConflict(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  conflict: DraftSaveConflictResponse,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  if (conflict.current_lock_version !== conflict.server.draft.lock_version
    || conflict.current_lock_version <= pending.expectedLockVersion
    || conflict.current_lock_version < state.draft.lock_version) {
    return invalidCompletion(state, pending);
  }
  const serverDefinitions = conflict.server.definitions;
  const byAgent = {} as Record<AgentKey, DraftEditorEntry>;
  for (const agentKey of AGENT_KEYS) {
    const entry = state.byAgent[agentKey];
    const wasLocallyClean = editableFormsEqual(entry.local, formFromDefinition(entry.saved));
    const adopted = adoptAuthoritativeDefinition(entry, agentKey, serverDefinitions[agentKey], {
      keepLocal: agentKey === pending.agentKey || !wasLocallyClean,
      source: 'version_adoption',
      reason: RETAINED_REASONS.version_adoption,
    });
    byAgent[agentKey] = {
      ...adopted,
      fieldErrors: agentKey === pending.agentKey ? {} : entry.fieldErrors,
      conflict: agentKey === pending.agentKey ? conflict : null,
      requestError: agentKey === pending.agentKey ? null : entry.requestError,
    };
  }
  return { draft: conflict.server.draft, byAgent, pendingSave: null };
}

function succeedWrite(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  result: DraftSaveSuccessResponse,
  keepLocal: (entry: DraftEditorEntry, pending: PendingDraftSave) => boolean,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  if (result.draft.lock_version !== pending.expectedLockVersion + 1
    || result.draft.lock_version < state.draft.lock_version) {
    return invalidCompletion(state, pending);
  }
  const entry = state.byAgent[pending.agentKey];
  const adopted = adoptAuthoritativeDefinition(entry, pending.agentKey, result.definition, {
    keepLocal: keepLocal(entry, pending),
    source: 'version_adoption',
    reason: RETAINED_REASONS.version_adoption,
  });
  return {
    draft: result.draft,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...adopted,
        fieldErrors: {},
        conflict: null,
        responseIssues: [],
        requestError: null,
      },
    },
  };
}

function withLocalRules(
  entry: DraftEditorEntry,
  update: (blocks: CustomTextBlock[]) => CustomTextBlock[],
): DraftEditorEntry {
  const rules = entry.local.assembly_rules;
  if (rules === null) return entry;
  return {
    ...entry,
    local: {
      ...entry.local,
      assembly_rules: { format_version: 2, custom_blocks: update(rules.custom_blocks) },
    },
    requestError: null,
  };
}

export function draftEditorReducer(
  state: DraftEditorState,
  action: DraftEditorAction,
): DraftEditorState {
  switch (action.type) {
    case 'edit': {
      const entry = state.byAgent[action.agentKey];
      const pending = state.pendingSave;
      const quarantine = action.field === 'prompt_text'
        && pending !== null
        && pending.operation === 'upgrade'
        && pending.agentKey === action.agentKey
        && isLegacyCompositeRole(action.agentKey)
        && definitionFormatVersion(entry.saved) === 1;
      if (quarantine) {
        // Backstop: keep the savable local prompt at the authoritative v1 value and
        // retain the proposed prompt as manual-only bytes.
        const authoritative: EditableModelDraftForm = {
          ...entry.local,
          prompt_text: entry.saved.prompt_text,
        };
        return replaceEntry(state, action.agentKey, appendRetained(
          { ...entry, local: authoritative },
          action.agentKey,
          {
            source: 'pending_prompt_quarantine',
            reason: RETAINED_REASONS.pending_prompt_quarantine,
            form: authoritative,
            manualOnlyPrompt: String(action.value),
            fromVersion: definitionFormatVersion(entry.saved),
            definition: entry.saved,
          },
        ));
      }
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, [action.field]: action.value },
        fieldErrors: { ...entry.fieldErrors, [action.field]: undefined },
        responseIssues: [],
        requestError: null,
      });
    }
    case 'assemblyBlockAdded': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => {
        const block: CustomTextBlock = {
          kind: 'custom_text',
          block_id: action.blockId,
          anchor: action.anchor,
          condition: 'always',
          text: '',
        };
        const lastAtAnchor = blocks.reduce(
          (found, candidate, index) => (candidate.anchor === action.anchor ? index : found),
          -1,
        );
        if (lastAtAnchor === -1) return [...blocks, block];
        return [...blocks.slice(0, lastAtAnchor + 1), block, ...blocks.slice(lastAtAnchor + 1)];
      }));
    }
    case 'assemblyBlockTextChanged': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => blocks.map(
        (block) => (block.block_id === action.blockId ? { ...block, text: action.text } : block),
      )));
    }
    case 'assemblyBlockConditionChanged': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => blocks.map(
        (block) => (
          block.block_id === action.blockId ? { ...block, condition: action.condition } : block
        ),
      )));
    }
    case 'assemblyBlockDeleted': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(
        entry,
        (blocks) => blocks.filter((block) => block.block_id !== action.blockId),
      ));
    }
    case 'assemblyBlockMoved': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => {
        const index = blocks.findIndex((block) => block.block_id === action.blockId);
        if (index === -1) return blocks;
        const anchor = blocks[index].anchor;
        const siblings = blocks
          .map((block, position) => ({ block, position }))
          .filter((item) => item.block.anchor === anchor);
        const offset = siblings.findIndex((item) => item.position === index);
        const target = action.direction === 'up' ? offset - 1 : offset + 1;
        // An arrow can never cross an anchor boundary.
        if (target < 0 || target >= siblings.length) return blocks;
        const next = [...blocks];
        const swapIndex = siblings[target].position;
        next[index] = blocks[swapIndex];
        next[swapIndex] = blocks[index];
        return next;
      }));
    }
    case 'saveInvalid': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, fieldErrors: action.errors });
    }
    case 'saveStarted': {
      if (state.pendingSave !== null) return state;
      return startOperation(state, action.pending);
    }
    case 'upgradeStarted': {
      if (state.pendingSave !== null) return state;
      const entry = state.byAgent[action.pending.agentKey];
      // Reducer backstop: an affected v1 role may not start an Upgrade while its
      // local prompt differs from the authoritative saved prompt.
      if (isLegacyCompositeRole(action.pending.agentKey)
        && definitionFormatVersion(entry.saved) === 1
        && entry.local.prompt_text !== entry.saved.prompt_text) {
        return state;
      }
      return startOperation(state, action.pending);
    }
    case 'sourceRecoveryStarted': {
      if (state.pendingSave !== null) return state;
      return startOperation(state, action.pending);
    }
    case 'saveSucceeded':
      return succeedWrite(state, 'save', action.requestId, action.result, (entry, pending) => (
        pending.submittedCandidate === null
        || !editableFormsEqual(entry.local, formFromCandidate(pending.submittedCandidate))
      ));
    case 'upgradeSucceeded':
      // Safe non-prompt edits made while pending survive; prompt and rules come
      // only from the server-authored v2 definition.
      return succeedWrite(state, 'upgrade', action.requestId, action.result, () => true);
    case 'saveRejected':
      return rejectOperation(state, 'save', action.requestId, action.error);
    case 'upgradeRejected':
      return rejectOperation(state, 'upgrade', action.requestId, action.error);
    case 'sourceRecoveryRejected':
      return rejectOperation(state, 'sourceRecovery', action.requestId, action.error);
    case 'saveConflicted':
      return mergeConflict(state, 'save', action.requestId, action.conflict);
    case 'upgradeConflicted':
      return mergeConflict(state, 'upgrade', action.requestId, action.conflict);
    case 'sourceRecoveryConflicted':
      return mergeConflict(state, 'sourceRecovery', action.requestId, action.conflict);
    case 'saveFailed':
      return failOperation(state, 'save', action.requestId, action.message);
    case 'upgradeFailed':
      return failOperation(state, 'upgrade', action.requestId, action.message);
    case 'sourceRecoveryFailed':
      return failOperation(state, 'sourceRecovery', action.requestId, action.message);
    case 'sourceRecoverySucceeded': {
      const pending = matchingPending(state, 'sourceRecovery', action.requestId);
      if (pending === null) return state;
      // This route never writes, so the lock must not have moved and the record
      // must describe the role that asked for it.
      if (action.result.agent_key !== pending.agentKey
        || action.result.lock_version !== pending.expectedLockVersion
        || action.result.draft.lock_version !== pending.expectedLockVersion) {
        return invalidCompletion(state, pending);
      }
      const entry = state.byAgent[pending.agentKey];
      const fromVersion = definitionFormatVersion(entry.saved);
      let next = appendRetained(entry, pending.agentKey, {
        source: 'legacy_source_recovery',
        reason: RETAINED_REASONS.legacy_source_recovery_saved,
        form: formFromDefinition(entry.saved),
        manualOnlyPrompt: entry.saved.prompt_text,
        fromVersion,
        definition: entry.saved,
      });
      next = appendRetained(next, pending.agentKey, {
        source: 'legacy_source_recovery',
        reason: RETAINED_REASONS.legacy_source_recovery_local,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion,
        definition: entry.saved,
      });
      return {
        ...state,
        pendingSave: null,
        byAgent: {
          ...state.byAgent,
          [pending.agentKey]: {
            ...next,
            local: { ...entry.local, prompt_text: action.result.source.prompt_text },
            responseIssues: [],
            requestError: null,
          },
        },
      };
    }
    case 'dirtyLegacyPromptRetained': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, appendRetained(entry, action.agentKey, {
        source: 'dirty_legacy_prompt',
        reason: RETAINED_REASONS.dirty_legacy_prompt,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion: definitionFormatVersion(entry.saved),
        definition: entry.saved,
      }));
    }
    case 'reloadServer': {
      const entry = state.byAgent[action.agentKey];
      const appended = appendRetained(entry, action.agentKey, {
        source: 'reload_server',
        reason: RETAINED_REASONS.reload_server,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion: definitionFormatVersion(entry.saved),
        definition: entry.saved,
      });
      return replaceEntry(state, action.agentKey, {
        ...appended,
        local: formFromDefinition(entry.saved),
        conflict: null,
        fieldErrors: {},
      });
    }
    case 'keepLocal': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, conflict: null });
    }
    case 'restoreSavedPrompt': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, prompt_text: entry.saved.prompt_text },
        fieldErrors: { ...entry.fieldErrors, prompt_text: undefined },
      });
    }
    case 'restoreRetained': {
      const entry = state.byAgent[action.agentKey];
      const record = entry.retainedForms.find((item) => item.id === action.retainedId);
      if (record === undefined) return state;
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: sanitizeForm(record.form, record.sanitizedFormatVersion, entry.saved),
        fieldErrors: {},
      });
    }
    case 'discardRetained': {
      const entry = state.byAgent[action.agentKey];
      if (!entry.retainedForms.some((item) => item.id === action.retainedId)) return state;
      return replaceEntry(state, action.agentKey, {
        ...entry,
        retainedForms: entry.retainedForms.filter((item) => item.id !== action.retainedId),
      });
    }
  }
}
