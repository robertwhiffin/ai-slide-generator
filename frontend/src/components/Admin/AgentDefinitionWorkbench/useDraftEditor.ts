import { useReducer, useRef } from 'react';
import {
  AgentDefinitionApiError,
  createTestCase,
  executeCandidateTestRun,
  executePublishedBaselineTestRun,
  listTestCases,
  probeDraftStructuredOutput,
  retireTestCase,
  type CreateTestCaseRequest,
  type TestCaseListEntry,
  readDraftLegacyPromptSource,
  StructuredOutputProbeApiError,
  saveDraftDefinition,
  upgradeDraftProtectedAssembly,
  upgradeDraftSchemaContract,
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
  probeEndpointUnsaved,
  probeErrorMessage,
  testOperationFailure,
  testRunCandidateUnsaved,
  validateDraftForm,
  type EditableDraftField,
  type TestOperationKind,
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

  /**
   * The one aggregate gate shared by Save, Upgrade, SourceRecovery, SchemaUpgrade, Probe
   * and #267's candidate run, baseline rerun and case writes.
   */
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

  const upgradeSchemaContract = async (agentKey: AgentKey): Promise<void> => {
    if (operationBlocked()) return;

    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'schemaUpgradeStarted',
      pending: {
        operation: 'schemaUpgrade',
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: null,
      },
    });

    try {
      const result = await upgradeDraftSchemaContract(agentKey, {
        lock_version: expectedLockVersion,
      });
      dispatch({ type: 'schemaUpgradeSucceeded', requestId, result });
    } catch (error) {
      if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({
          type: 'schemaUpgradeRejected',
          requestId,
          error: error.payload as DraftValidationErrorResponse,
        });
      } else if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({
          type: 'schemaUpgradeConflicted',
          requestId,
          conflict: error.payload as DraftSaveConflictResponse,
        });
      } else {
        dispatch({ type: 'schemaUpgradeFailed', requestId, message: draftSaveErrorMessage(error) });
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
    }
  };

  /**
   * Explicitly probes the role's **saved** candidate for structured output (#266). It
   * joins the one gate and request counter, sends only the current lock, and is refused
   * without a request ID while the local endpoint differs from the saved one.
   */
  const probeStructuredOutput = async (agentKey: AgentKey): Promise<void> => {
    if (operationBlocked()) return;
    if (probeEndpointUnsaved(state.byAgent[agentKey])) return;

    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'probeStarted',
      pending: {
        operation: 'probe',
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: null,
      },
    });

    try {
      const result = await probeDraftStructuredOutput(agentKey, {
        lock_version: expectedLockVersion,
      });
      dispatch({ type: 'probeSucceeded', requestId, result });
    } catch (error) {
      if (error instanceof StructuredOutputProbeApiError) {
        dispatch({ type: 'probeUnsuccessful', requestId, failure: error.failure });
      } else if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({
          type: 'probeRejected',
          requestId,
          error: error.payload as DraftValidationErrorResponse,
        });
      } else if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({
          type: 'probeConflicted',
          requestId,
          conflict: error.payload as DraftSaveConflictResponse,
        });
      } else {
        dispatch({ type: 'probeFailed', requestId, message: probeErrorMessage(error) });
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
    }
  };

  /**
   * Reads one role's active Agent Test Cases (#267). A read, never a draft operation:
   * it takes no gate, and its ID from the one counter only lets the reducer drop an
   * out-of-order answer.
   */
  const loadTestCases = async (agentKey: AgentKey): Promise<void> => {
    const requestId = nextRequestIdRef.current++;
    dispatch({ type: 'testCasesLoadStarted', agentKey, requestId });
    try {
      const items = await listTestCases(agentKey);
      dispatch({ type: 'testCasesLoaded', agentKey, requestId, items });
    } catch (error) {
      dispatch({ type: 'testCasesLoadFailed', agentKey, requestId, message: testOperationFailure(error, 'load').message });
    }
  };

  /** Starts one #267 operation on the one gate, or returns `null` when it is held. */
  const startTestOperation = (
    operation: TestOperationKind,
    agentKey: AgentKey,
    testCaseId?: number,
  ): { requestId: number; expectedLockVersion: number } | null => {
    if (operationBlocked()) return null;
    const requestId = nextRequestIdRef.current++;
    const expectedLockVersion = state.draft.lock_version;
    inFlightRequestIdRef.current = requestId;
    dispatch({
      type: 'testOperationStarted',
      pending: {
        operation,
        requestId,
        agentKey,
        expectedLockVersion,
        submittedCandidate: null,
        ...(testCaseId === undefined ? {} : { testCaseId }),
      },
    });
    return { requestId, expectedLockVersion };
  };

  const finishTestOperation = (requestId: number) => {
    if (inFlightRequestIdRef.current === requestId) inFlightRequestIdRef.current = null;
  };

  /**
   * Runs one active case against the role's **saved** candidate. It joins the one gate,
   * sends exactly `{ test_case_id, lock_version }`, and is refused without a request ID
   * while any field of the role is unsaved, as the probe is for its endpoint.
   */
  const runTestCase = async (agentKey: AgentKey, testCaseId: number): Promise<void> => {
    if (operationBlocked()) return;
    if (testRunCandidateUnsaved(state.byAgent[agentKey])) return;
    const started = startTestOperation('testRun', agentKey, testCaseId);
    if (started === null) return;
    const { requestId, expectedLockVersion } = started;
    try {
      const evidence = await executeCandidateTestRun(agentKey, {
        test_case_id: testCaseId,
        lock_version: expectedLockVersion,
      });
      dispatch({ type: 'testRunSucceeded', requestId, evidence });
    } catch (error) {
      if (error instanceof AgentDefinitionApiError && error.status === 409) {
        dispatch({ type: 'testRunConflicted', requestId, conflict: error.payload as DraftSaveConflictResponse });
      } else if (error instanceof AgentDefinitionApiError && error.status === 422) {
        dispatch({ type: 'testRunRejected', requestId, error: error.payload as DraftValidationErrorResponse });
      } else {
        dispatch({ type: 'testOperationFailed', requestId, ...testOperationFailure(error, 'run') });
      }
    } finally {
      finishTestOperation(requestId);
    }
  };

  /** Reruns one active case against the active published definition; no lock is sent. */
  const runPublishedBaseline = async (agentKey: AgentKey, testCaseId: number): Promise<void> => {
    const started = startTestOperation('baselineRun', agentKey, testCaseId);
    if (started === null) return;
    const { requestId } = started;
    try {
      const evidence = await executePublishedBaselineTestRun(agentKey, { test_case_id: testCaseId });
      dispatch({ type: 'testRunSucceeded', requestId, evidence });
    } catch (error) {
      dispatch({ type: 'testOperationFailed', requestId, ...testOperationFailure(error, 'run') });
    } finally {
      finishTestOperation(requestId);
    }
  };

  /** Adds a case lineage. Returns the created version, or `null` when it was refused. */
  const createAgentTestCase = async (
    agentKey: AgentKey,
    request: CreateTestCaseRequest,
  ): Promise<TestCaseListEntry | null> => {
    const started = startTestOperation('testCaseCreate', agentKey);
    if (started === null) return null;
    const { requestId } = started;
    try {
      const testCase = await createTestCase(request);
      dispatch({ type: 'testCaseCreated', requestId, testCase });
      return testCase;
    } catch (error) {
      dispatch({ type: 'testOperationFailed', requestId, ...testOperationFailure(error, 'create') });
      return null;
    } finally {
      finishTestOperation(requestId);
    }
  };

  /** Retires one case version; the last required case of a role is refused by the server. */
  const retireAgentTestCase = async (agentKey: AgentKey, testCaseId: number): Promise<void> => {
    const started = startTestOperation('testCaseRetire', agentKey, testCaseId);
    if (started === null) return;
    const { requestId } = started;
    try {
      const testCase = await retireTestCase(testCaseId);
      dispatch({ type: 'testCaseRetired', requestId, testCase });
    } catch (error) {
      dispatch({ type: 'testOperationFailed', requestId, ...testOperationFailure(error, 'retire') });
    } finally {
      finishTestOperation(requestId);
    }
  };

  return {
    state,
    edit,
    save,
    probeStructuredOutput,
    loadTestCases,
    runTestCase,
    runPublishedBaseline,
    createAgentTestCase,
    retireAgentTestCase,
    upgradeProtectedAssembly,
    upgradeSchemaContract,
    restorePublishedV1Prompt,
    toggleSchemaOverlayOptionalField: (agentKey: AgentKey, fieldName: string) => dispatch({
      type: 'schemaOverlayOptionalFieldToggled', agentKey, fieldName,
    }),
    editSchemaOverlayFieldDescription: (agentKey: AgentKey, fieldName: string, description: string) => dispatch({
      type: 'schemaOverlayFieldDescriptionChanged', agentKey, fieldName, description,
    }),
    editSchemaOverlayFieldExamples: (agentKey: AgentKey, fieldName: string, examples: string) => dispatch({
      type: 'schemaOverlayFieldExamplesChanged', agentKey, fieldName, examples,
    }),
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
