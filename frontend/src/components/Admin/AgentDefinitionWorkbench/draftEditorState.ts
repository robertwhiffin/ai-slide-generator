import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  InvalidDraftSaveResponseError,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type DraftDefinition,
  type DraftMetadata,
  type DraftSaveConflictResponse,
  type DraftSaveSuccessResponse,
  type DraftValidationErrorResponse,
  type EditableModelDraft,
} from '../../../api/agentDefinitions';

export type DraftStatus = 'Clean' | 'Unsaved' | 'Needs test';
export type DraftNumberInput = number | '';
export type EditableDraftField =
  | 'prompt_text'
  | 'endpoint_name'
  | 'temperature'
  | 'max_tokens'
  | 'top_p';

export interface EditableModelDraftForm {
  prompt_text: string;
  endpoint_name: string;
  temperature: DraftNumberInput;
  max_tokens: DraftNumberInput;
  top_p: DraftNumberInput;
}

export interface DraftEditorEntry {
  publishedHash: string;
  saved: DraftDefinition;
  local: EditableModelDraftForm;
  fieldErrors: Partial<Record<EditableDraftField, string>>;
  conflict: DraftSaveConflictResponse | null;
  recoveryForm: EditableModelDraftForm | null;
  requestError: string | null;
}

export interface PendingDraftSave {
  requestId: number;
  agentKey: AgentKey;
  expectedLockVersion: number;
  submittedCandidate: EditableModelDraft;
}

export interface DraftEditorState {
  draft: DraftMetadata;
  byAgent: Record<AgentKey, DraftEditorEntry>;
  pendingSave: PendingDraftSave | null;
}

export type DraftEditorAction =
  | { type: 'edit'; agentKey: AgentKey; field: EditableDraftField; value: string | number }
  | { type: 'saveStarted'; pending: PendingDraftSave }
  | { type: 'saveSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'saveInvalid'; agentKey: AgentKey; errors: Partial<Record<EditableDraftField, string>> }
  | { type: 'saveRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'saveConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'saveFailed'; requestId: number; message: string }
  | { type: 'reloadServer'; agentKey: AgentKey }
  | { type: 'keepLocal'; agentKey: AgentKey }
  | { type: 'restoreRecovery'; agentKey: AgentKey }
  | { type: 'dismissRecovery'; agentKey: AgentKey };

const INVALID_RESPONSE_MESSAGE = 'Unable to save draft because the server response was invalid.';

export function formFromDefinition(definition: DraftDefinition): EditableModelDraftForm {
  return {
    prompt_text: definition.prompt_text,
    endpoint_name: definition.model.endpoint_name,
    temperature: definition.model.temperature,
    max_tokens: definition.model.max_tokens,
    top_p: definition.model.top_p,
  };
}

export function formFromCandidate(candidate: EditableModelDraft): EditableModelDraftForm {
  return {
    prompt_text: candidate.prompt_text,
    endpoint_name: candidate.model.endpoint_name,
    temperature: candidate.model.temperature,
    max_tokens: candidate.model.max_tokens,
    top_p: candidate.model.top_p,
  };
}

export function candidateFromForm(form: EditableModelDraftForm): EditableModelDraft | null {
  const validation = validateDraftForm(form);
  return validation.ok ? validation.candidate : null;
}

export function editableFormsEqual(
  left: EditableModelDraftForm,
  right: EditableModelDraftForm,
): boolean {
  return left.prompt_text === right.prompt_text
    && left.endpoint_name === right.endpoint_name
    && left.temperature === right.temperature
    && left.max_tokens === right.max_tokens
    && left.top_p === right.top_p;
}

function cloneDefinition(definition: DraftDefinition): DraftDefinition {
  return structuredClone(definition);
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
      recoveryForm: null,
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

function fieldErrorsFromResponse(
  error: DraftValidationErrorResponse,
): Partial<Record<EditableDraftField, string>> {
  const fields: Record<string, EditableDraftField> = {
    'candidate.prompt_text': 'prompt_text',
    'candidate.model.endpoint_name': 'endpoint_name',
    'candidate.model.temperature': 'temperature',
    'candidate.model.max_tokens': 'max_tokens',
    'candidate.model.top_p': 'top_p',
  };
  const result: Partial<Record<EditableDraftField, string>> = {};
  for (const item of error.errors) {
    const field = fields[item.field];
    if (field) result[field] = item.message;
  }
  return result;
}

export function draftEditorReducer(
  state: DraftEditorState,
  action: DraftEditorAction,
): DraftEditorState {
  switch (action.type) {
    case 'edit': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, [action.field]: action.value },
        fieldErrors: { ...entry.fieldErrors, [action.field]: undefined },
        requestError: null,
      });
    }
    case 'saveInvalid': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, fieldErrors: action.errors });
    }
    case 'saveStarted': {
      if (state.pendingSave !== null) return state;
      const entry = state.byAgent[action.pending.agentKey];
      return {
        ...replaceEntry(state, action.pending.agentKey, {
          ...entry,
          fieldErrors: {},
          requestError: null,
        }),
        pendingSave: action.pending,
      };
    }
    case 'saveSucceeded': {
      if (state.pendingSave === null) return state;
      if (state.pendingSave.requestId !== action.requestId) return state;
      const pending = state.pendingSave;
      if (action.result.draft.lock_version !== pending.expectedLockVersion + 1
        || action.result.draft.lock_version < state.draft.lock_version) {
        return invalidCompletion(state, pending);
      }
      const entry = state.byAgent[pending.agentKey];
      const submittedForm = formFromCandidate(pending.submittedCandidate);
      const nextLocal = editableFormsEqual(entry.local, submittedForm)
        ? formFromDefinition(action.result.definition)
        : entry.local;
      return {
        draft: action.result.draft,
        pendingSave: null,
        byAgent: {
          ...state.byAgent,
          [pending.agentKey]: {
            ...entry,
            saved: action.result.definition,
            local: nextLocal,
            fieldErrors: {},
            conflict: null,
            requestError: null,
          },
        },
      };
    }
    case 'saveRejected': {
      if (state.pendingSave === null) return state;
      if (state.pendingSave.requestId !== action.requestId) return state;
      const pending = state.pendingSave;
      const entry = state.byAgent[pending.agentKey];
      return {
        ...state,
        pendingSave: null,
        byAgent: {
          ...state.byAgent,
          [pending.agentKey]: {
            ...entry,
            fieldErrors: fieldErrorsFromResponse(action.error),
          },
        },
      };
    }
    case 'saveConflicted': {
      if (state.pendingSave === null) return state;
      if (state.pendingSave.requestId !== action.requestId) return state;
      const pending = state.pendingSave;
      if (action.conflict.current_lock_version !== action.conflict.server.draft.lock_version
        || action.conflict.current_lock_version <= pending.expectedLockVersion
        || action.conflict.current_lock_version < state.draft.lock_version) {
        return invalidCompletion(state, pending);
      }
      const serverDefinitions = action.conflict.server.definitions;
      const byAgent = {} as Record<AgentKey, DraftEditorEntry>;
      for (const agentKey of AGENT_KEYS) {
        const entry = state.byAgent[agentKey];
        const serverDefinition = serverDefinitions[agentKey];
        const wasLocallyClean = editableFormsEqual(entry.local, formFromDefinition(entry.saved));
        byAgent[agentKey] = {
          ...entry,
          saved: serverDefinition,
          local: agentKey === pending.agentKey || !wasLocallyClean
            ? entry.local
            : formFromDefinition(serverDefinition),
          fieldErrors: agentKey === pending.agentKey ? {} : entry.fieldErrors,
          conflict: agentKey === pending.agentKey ? action.conflict : null,
          requestError: agentKey === pending.agentKey ? null : entry.requestError,
        };
      }
      return {
        draft: action.conflict.server.draft,
        byAgent,
        pendingSave: null,
      };
    }
    case 'saveFailed': {
      if (state.pendingSave === null) return state;
      if (state.pendingSave.requestId !== action.requestId) return state;
      const pending = state.pendingSave;
      const entry = state.byAgent[pending.agentKey];
      return {
        ...state,
        pendingSave: null,
        byAgent: {
          ...state.byAgent,
          [pending.agentKey]: { ...entry, requestError: action.message },
        },
      };
    }
    case 'reloadServer': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: formFromDefinition(entry.saved),
        conflict: null,
        recoveryForm: { ...entry.local },
        fieldErrors: {},
      });
    }
    case 'keepLocal': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, conflict: null });
    }
    case 'restoreRecovery': {
      const entry = state.byAgent[action.agentKey];
      if (entry.recoveryForm === null) return state;
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.recoveryForm },
        recoveryForm: null,
      });
    }
    case 'dismissRecovery': {
      const entry = state.byAgent[action.agentKey];
      if (entry.recoveryForm === null) return state;
      return replaceEntry(state, action.agentKey, { ...entry, recoveryForm: null });
    }
  }
}
