import { useReducer, useRef } from 'react';
import {
  AgentDefinitionApiError,
  readDraftLegacyPromptSource,
  saveDraftDefinition,
  upgradeDraftProtectedAssembly,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type AssemblyCondition,
  type CustomAnchor,
  type DraftSaveConflictResponse,
  type DraftValidationErrorResponse,
} from '../../../api/agentDefinitions';
import {
  createDraftEditorState,
  definitionFormatVersion,
  draftEditorReducer,
  draftSaveErrorMessage,
  isLegacyCompositeRole,
  validateDraftForm,
  type EditableDraftField,
} from './draftEditorState';

function editableValue(field: EditableDraftField, value: string): string | number {
  if (field === 'prompt_text' || field === 'endpoint_name') return value;
  return value === '' ? '' : Number(value);
}

export function useDraftEditor(workbench: AgentDefinitionWorkbenchResponse) {
  const [state, dispatch] = useReducer(draftEditorReducer, workbench, createDraftEditorState);
  const nextRequestIdRef = useRef(1);
  const inFlightRequestIdRef = useRef<number | null>(null);

  const edit = (agentKey: AgentKey, field: EditableDraftField, value: string) => {
    dispatch({ type: 'edit', agentKey, field, value: editableValue(field, value) });
  };

  /** The one aggregate gate shared by Save, Upgrade, and SourceRecovery. */
  const operationBlocked = () => inFlightRequestIdRef.current !== null || state.pendingSave !== null;

  const save = async (agentKey: AgentKey): Promise<void> => {
    if (operationBlocked()) return;
    const validation = validateDraftForm(state.byAgent[agentKey].local);
    if (!validation.ok) {
      dispatch({ type: 'saveInvalid', agentKey, errors: validation.errors });
      return;
    }

    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'saveStarted',
      pending: {
        operation: 'save',
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: validation.candidate,
      },
    });

    try {
      const result = await saveDraftDefinition(agentKey, {
        lock_version: expectedLockVersion,
        candidate: validation.candidate,
      });
      dispatch({ type: 'saveSucceeded', requestId, result });
    } catch (error) {
      if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({
          type: 'saveRejected',
          requestId,
          error: error.payload as DraftValidationErrorResponse,
        });
      } else if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({
          type: 'saveConflicted',
          requestId,
          conflict: error.payload as DraftSaveConflictResponse,
        });
      } else {
        dispatch({ type: 'saveFailed', requestId, message: draftSaveErrorMessage(error) });
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
    }
  };

  const upgradeProtectedAssembly = async (agentKey: AgentKey): Promise<void> => {
    if (operationBlocked()) return;
    const entry = state.byAgent[agentKey];
    // An affected v1 role must match its authoritative saved prompt byte-for-byte.
    // A dirty attempt allocates no request ID and sends no POST.
    if (isLegacyCompositeRole(agentKey)
      && definitionFormatVersion(entry.saved) === 1
      && entry.local.prompt_text !== entry.saved.prompt_text) {
      dispatch({ type: 'dirtyLegacyPromptRetained', agentKey });
      return;
    }

    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'upgradeStarted',
      pending: {
        operation: 'upgrade',
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: null,
      },
    });

    try {
      const result = await upgradeDraftProtectedAssembly(agentKey, {
        lock_version: expectedLockVersion,
      });
      dispatch({ type: 'upgradeSucceeded', requestId, result });
    } catch (error) {
      if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({
          type: 'upgradeRejected',
          requestId,
          error: error.payload as DraftValidationErrorResponse,
        });
      } else if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({
          type: 'upgradeConflicted',
          requestId,
          conflict: error.payload as DraftSaveConflictResponse,
        });
      } else {
        dispatch({ type: 'upgradeFailed', requestId, message: draftSaveErrorMessage(error) });
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
    }
  };

  const restorePublishedV1Prompt = async (agentKey: AgentKey): Promise<void> => {
    if (operationBlocked()) return;

    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'sourceRecoveryStarted',
      pending: {
        operation: 'sourceRecovery',
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: null,
      },
    });

    try {
      const result = await readDraftLegacyPromptSource(agentKey, {
        lock_version: expectedLockVersion,
      });
      dispatch({ type: 'sourceRecoverySucceeded', requestId, result });
    } catch (error) {
      if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({
          type: 'sourceRecoveryRejected',
          requestId,
          error: error.payload as DraftValidationErrorResponse,
        });
      } else if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({
          type: 'sourceRecoveryConflicted',
          requestId,
          conflict: error.payload as DraftSaveConflictResponse,
        });
      } else {
        dispatch({ type: 'sourceRecoveryFailed', requestId, message: draftSaveErrorMessage(error) });
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
    }
  };

  return {
    state,
    edit,
    save,
    upgradeProtectedAssembly,
    restorePublishedV1Prompt,
    /** The UUID is allocated here so the reducer stays deterministic. */
    addAssemblyBlock: (agentKey: AgentKey, anchor: CustomAnchor) => dispatch({
      type: 'assemblyBlockAdded', agentKey, blockId: crypto.randomUUID(), anchor,
    }),
    editAssemblyBlockText: (agentKey: AgentKey, blockId: string, text: string) => dispatch({
      type: 'assemblyBlockTextChanged', agentKey, blockId, text,
    }),
    editAssemblyBlockCondition: (
      agentKey: AgentKey,
      blockId: string,
      condition: AssemblyCondition,
    ) => dispatch({ type: 'assemblyBlockConditionChanged', agentKey, blockId, condition }),
    deleteAssemblyBlock: (agentKey: AgentKey, blockId: string) => dispatch({
      type: 'assemblyBlockDeleted', agentKey, blockId,
    }),
    moveAssemblyBlock: (agentKey: AgentKey, blockId: string, direction: 'up' | 'down') => dispatch({
      type: 'assemblyBlockMoved', agentKey, blockId, direction,
    }),
    reloadServer: (agentKey: AgentKey) => dispatch({ type: 'reloadServer', agentKey }),
    keepLocal: (agentKey: AgentKey) => dispatch({ type: 'keepLocal', agentKey }),
    restoreSavedPrompt: (agentKey: AgentKey) => dispatch({ type: 'restoreSavedPrompt', agentKey }),
    restoreRetained: (agentKey: AgentKey, retainedId: string) => dispatch({
      type: 'restoreRetained', agentKey, retainedId,
    }),
    discardRetained: (agentKey: AgentKey, retainedId: string) => dispatch({
      type: 'discardRetained', agentKey, retainedId,
    }),
  };
}
