import { useReducer, useRef } from 'react';
import {
  AgentDefinitionApiError,
  saveDraftDefinition,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type DraftSaveConflictResponse,
  type DraftValidationErrorResponse,
} from '../../../api/agentDefinitions';
import {
  createDraftEditorState,
  draftEditorReducer,
  draftSaveErrorMessage,
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

  const save = async (agentKey: AgentKey): Promise<void> => {
    if (inFlightRequestIdRef.current !== null || state.pendingSave !== null) return;
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

  return {
    state,
    edit,
    save,
    reloadServer: (agentKey: AgentKey) => dispatch({ type: 'reloadServer', agentKey }),
    keepLocal: (agentKey: AgentKey) => dispatch({ type: 'keepLocal', agentKey }),
    restoreRecovery: (agentKey: AgentKey) => dispatch({ type: 'restoreRecovery', agentKey }),
    dismissRecovery: (agentKey: AgentKey) => dispatch({ type: 'dismissRecovery', agentKey }),
  };
}
