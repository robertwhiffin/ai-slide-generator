import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AgentDefinitionApiError,
  InvalidDraftSaveResponseError,
  parseDraftSaveConflictResponse,
  parseDraftSaveSuccessResponse,
  parseDraftValidationErrorResponse,
  saveDraftDefinition,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type DraftDefinition,
  type DraftSaveConflictResponse,
  type DraftSaveRequest,
  type DraftSaveSuccessResponse,
} from '../../../api/agentDefinitions';
import { syntheticAgentDefinitionWorkbench } from '../../../../tests/fixtures/mocks';
import {
  createDraftEditorState,
  draftEditorReducer,
  draftSaveErrorMessage,
  draftStatus,
  formFromDefinition,
  validateDraftForm,
  type EditableModelDraftForm,
} from './draftEditorState';

const AGENT_KEYS: AgentKey[] = [
  'architect',
  'data_analyst',
  'builder',
  'build_reviewer',
  'fixer',
  'fix_reviewer',
  'deck_reviewer',
];

function workbench(): AgentDefinitionWorkbenchResponse {
  return structuredClone(syntheticAgentDefinitionWorkbench);
}

function definition(agentKey: AgentKey, prompt?: string, hash?: string): DraftDefinition {
  const node = workbench().nodes.find((candidate) => candidate.agent_key === agentKey);
  if (!node || node.execution_kind !== 'model') throw new Error(`missing ${agentKey}`);
  return {
    ...structuredClone(node.draft),
    ...(prompt === undefined ? {} : { prompt_text: prompt }),
    ...(hash === undefined ? {} : { candidate_hash: hash }),
  };
}

function metadata(lockVersion: number) {
  return { ...workbench().draft, lock_version: lockVersion };
}

function success(
  agentKey: AgentKey,
  prompt: string,
  lockVersion: number,
): DraftSaveSuccessResponse {
  return {
    draft: metadata(lockVersion),
    definition: definition(agentKey, prompt, `${lockVersion}`.repeat(64)),
    changed: true,
  };
}

function conflict(
  expectedLockVersion: number,
  currentLockVersion: number,
  prompts: Partial<Record<AgentKey, string>> = {},
): DraftSaveConflictResponse {
  return {
    code: 'stale_draft',
    expected_lock_version: expectedLockVersion,
    current_lock_version: currentLockVersion,
    client_candidate: {
      prompt_text: 'Architect A2',
      model: structuredClone(definition('architect').model),
    },
    server: {
      draft: metadata(currentLockVersion),
      definitions: Object.fromEntries(AGENT_KEYS.map((agentKey) => [
        agentKey,
        definition(
          agentKey,
          prompts[agentKey] ?? definition(agentKey).prompt_text,
          `${AGENT_KEYS.indexOf(agentKey) + currentLockVersion + 1}`.repeat(64).slice(0, 64),
        ),
      ])) as Record<AgentKey, DraftDefinition>,
    },
  };
}

function request(prompt = 'Architect A2'): DraftSaveRequest {
  return {
    lock_version: 0,
    candidate: {
      prompt_text: prompt,
      model: {
        endpoint_name: 'endpoint',
        temperature: 0.2,
        max_tokens: 4096,
        top_p: 0.8,
      },
    },
  };
}

function response(status: number, body: unknown, statusText = 'OK') {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: vi.fn().mockResolvedValue(body),
  };
}

function setAtPath(value: unknown, path: string, replacement: unknown, remove = false) {
  const clone = structuredClone(value) as Record<string, unknown>;
  const parts = path.split('.');
  let target: Record<string, unknown> = clone;
  for (const part of parts.slice(0, -1)) target = target[part] as Record<string, unknown>;
  if (remove) delete target[parts.at(-1)!];
  else target[parts.at(-1)!] = replacement;
  return clone;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('draft save transport', () => {
  it('serializes only editable fields in exactly one direct PUT', async () => {
    const result = success('architect', 'Architect A2', 1);
    const fetchMock = vi.fn().mockResolvedValue(response(200, result));
    vi.stubGlobal('fetch', fetchMock);

    await expect(saveDraftDefinition('architect', request())).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/architect$/);
    expect(init).toEqual({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request()),
    });
    expect(JSON.parse(String(init.body))).toEqual(request());
  });

  it.each([
    [409, conflict(0, 1)],
    [422, { code: 'invalid_draft', errors: [{ field: 'candidate.prompt_text', code: 'blank', message: 'Prompt text must not be blank.' }] }],
  ])('preserves a valid %i payload on AgentDefinitionApiError', async (status, payload) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(status, payload)));

    const thrown = await saveDraftDefinition('architect', request()).catch((error: unknown) => error);

    expect(thrown).toBeInstanceOf(AgentDefinitionApiError);
    expect((thrown as AgentDefinitionApiError).payload).toBe(payload);
  });

  it('keeps GET-style error detail compatibility', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(403, { detail: 'Administrator access required' }, 'Forbidden')));
    const { getAgentDefinitionWorkbench } = await import('../../../api/agentDefinitions');

    const thrown = await getAgentDefinitionWorkbench().catch((error: unknown) => error);

    expect(thrown).toMatchObject({ status: 403, detail: 'Administrator access required' });
  });

  it('rejects every missing or mistyped required nested 200 field', () => {
    const valid = success('architect', 'Architect A2', 1);
    const paths = [
      'draft', 'draft.draft_id', 'draft.base_release_id', 'draft.base_version_number',
      'draft.lock_version', 'draft.updated_by', 'draft.updated_at', 'definition',
      'definition.base_revision_id', 'definition.candidate_hash', 'definition.definition_version',
      'definition.prompt_text', 'definition.model', 'definition.model.endpoint_name',
      'definition.model.temperature', 'definition.model.max_tokens', 'definition.model.top_p',
      'definition.schema_overlay', 'definition.schema_overlay.field_overrides',
      'definition.schema_overlay.additional_optional_fields', 'definition.assembly_rules',
      'definition.assembly_rules.format_version', 'definition.assembly_rules.separator',
      'definition.assembly_rules.blocks', 'definition.protected_assembly',
      'definition.protected_assembly.version', 'definition.protected_assembly.digest',
      'definition.schema_contract', 'definition.schema_contract.version',
      'definition.schema_contract.digest', 'changed',
    ];

    for (const path of paths) {
      expect(parseDraftSaveSuccessResponse(setAtPath(valid, path, null, true)), `missing ${path}`).toBeNull();
      expect(parseDraftSaveSuccessResponse(setAtPath(valid, path, null)), `mistyped ${path}`).toBeNull();
    }
    for (const invalid of [[valid], null, 1, 'body']) {
      expect(parseDraftSaveSuccessResponse(invalid)).toBeNull();
    }

    const blockPaths = [
      'definition.assembly_rules.blocks.0.kind',
      'definition.assembly_rules.blocks.0.condition',
      'definition.assembly_rules.blocks.1.kind',
      'definition.assembly_rules.blocks.1.name',
      'definition.assembly_rules.blocks.1.condition',
      'definition.assembly_rules.blocks.3.kind',
      'definition.assembly_rules.blocks.3.condition',
      'definition.assembly_rules.blocks.3.indent',
      'definition.assembly_rules.blocks.3.default',
      'definition.assembly_rules.blocks.4.kind',
      'definition.assembly_rules.blocks.4.condition',
      'definition.assembly_rules.blocks.4.binding',
      'definition.assembly_rules.blocks.4.terminal',
    ];
    for (const path of blockPaths) {
      expect(parseDraftSaveSuccessResponse(setAtPath(valid, path, null, true)), `missing ${path}`).toBeNull();
      expect(parseDraftSaveSuccessResponse(setAtPath(valid, path, null)), `mistyped ${path}`).toBeNull();
    }
  });

  it('rejects six-role and eight-role conflicts', () => {
    const sixRole = conflict(0, 1);
    delete (sixRole.server.definitions as Partial<Record<AgentKey, DraftDefinition>>).deck_reviewer;
    const eightRole = conflict(0, 1) as unknown as { server: { definitions: Record<string, DraftDefinition> } };
    eightRole.server.definitions.foreman = definition('architect');

    expect(parseDraftSaveConflictResponse(sixRole)).toBeNull();
    expect(parseDraftSaveConflictResponse(eightRole)).toBeNull();
  });

  it('rejects malformed conflict and validation envelopes', () => {
    const validConflict = conflict(0, 1);
    expect(parseDraftSaveConflictResponse(setAtPath(validConflict, 'current_lock_version', 2))).toBeNull();
    expect(parseDraftSaveConflictResponse({ ...validConflict, extra: true })).toBeNull();
    const validValidation = {
      code: 'invalid_draft',
      errors: [{ field: 'candidate.prompt_text', code: 'blank', message: 'Prompt text must not be blank.' }],
    };
    expect(parseDraftValidationErrorResponse(validValidation)).toEqual(validValidation);
    expect(parseDraftValidationErrorResponse({ ...validValidation, errors: [] })).toBeNull();
    expect(parseDraftValidationErrorResponse(setAtPath(validValidation, 'errors.0.message', 1))).toBeNull();
    for (const invalid of [[validConflict], null, 1, 'body']) {
      expect(parseDraftSaveConflictResponse(invalid)).toBeNull();
      expect(parseDraftValidationErrorResponse(invalid)).toBeNull();
    }
  });

  it.each([
    [200, { changed: true }],
    [409, { code: 'stale_draft' }],
    [422, { code: 'invalid_draft', errors: [] }],
  ])('throws InvalidDraftSaveResponseError before invalid %i reaches state', async (status, body) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(status, body)));
    await expect(saveDraftDefinition('architect', request())).rejects.toBeInstanceOf(InvalidDraftSaveResponseError);
  });

  it.each([200, 409, 422])('rejects array, null, and scalar JSON for contract status %i', async (status) => {
    for (const body of [[], null, 'body', 1]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(status, body)));
      await expect(saveDraftDefinition('architect', request())).rejects.toBeInstanceOf(InvalidDraftSaveResponseError);
    }
  });

  it('classifies network, HTTP, and invalid-contract failures without retrying', async () => {
    const cases = [
      [new TypeError('network down'), 'Unable to save draft. Check your connection and try again.'],
      [new AgentDefinitionApiError(500, null, 'Internal Server Error', true), 'Unable to save draft (500 Internal Server Error).'],
      [new InvalidDraftSaveResponseError(), 'Unable to save draft because the server response was invalid.'],
    ] as const;
    for (const [error, message] of cases) expect(draftSaveErrorMessage(error)).toBe(message);

    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network down'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(saveDraftDefinition('architect', request())).rejects.toThrow('network down');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ...response(500, null, 'Internal Server Error'), json: vi.fn().mockRejectedValue(new SyntaxError('no json')) }));
    const httpError = await saveDraftDefinition('architect', request()).catch((error: unknown) => error);
    expect(draftSaveErrorMessage(httpError)).toBe('Unable to save draft (500 Internal Server Error).');
  });
});

describe('draft editor state', () => {
  it('initializes independent deep-copied entries for exactly seven model agents', () => {
    const source = workbench();
    const state = createDraftEditorState(source);
    const sourceArchitect = source.nodes.find((node) => node.agent_key === 'architect');
    if (!sourceArchitect || sourceArchitect.execution_kind !== 'model') throw new Error('missing architect');
    const architect = state.byAgent.architect.saved;
    const builder = state.byAgent.builder.saved;
    expect(Object.keys(state.byAgent)).toEqual(AGENT_KEYS);
    expect('foreman' in state.byAgent).toBe(false);
    expect(architect).not.toBe(sourceArchitect.draft);
    expect(architect.model).not.toBe(sourceArchitect.draft.model);
    expect(architect.model).not.toBe(builder.model);
    expect(architect.schema_overlay).not.toBe(sourceArchitect.draft.schema_overlay);
    expect(architect.schema_overlay.field_overrides).not.toBe(sourceArchitect.draft.schema_overlay.field_overrides);
    expect(architect.schema_overlay.additional_optional_fields).not.toBe(sourceArchitect.draft.schema_overlay.additional_optional_fields);
    expect(architect.assembly_rules).not.toBe(sourceArchitect.draft.assembly_rules);
    expect(architect.assembly_rules.blocks).not.toBe(sourceArchitect.draft.assembly_rules.blocks);
    expect(architect.assembly_rules.blocks[0]).not.toBe(sourceArchitect.draft.assembly_rules.blocks[0]);

    const sourceEndpoint = sourceArchitect.draft.model.endpoint_name;
    const builderEndpoint = builder.model.endpoint_name;
    architect.model.endpoint_name = 'mutated endpoint';
    architect.schema_overlay.field_overrides.injected = true;
    architect.assembly_rules.blocks.push({ kind: 'authored_prompt', condition: 'always' });

    expect(sourceArchitect.draft.model.endpoint_name).toBe(sourceEndpoint);
    expect(builder.model.endpoint_name).toBe(builderEndpoint);
    expect(sourceArchitect.draft.schema_overlay.field_overrides).not.toHaveProperty('injected');
    expect(builder.schema_overlay.field_overrides).not.toHaveProperty('injected');
    expect(sourceArchitect.draft.assembly_rules.blocks).toHaveLength(5);
    expect(builder.assembly_rules.blocks).toHaveLength(5);
  });

  it('status precedence makes local unsaved changes dominate an untested saved baseline', () => {
    const cleanEntry = createDraftEditorState(workbench()).byAgent.architect;
    const changedLocal = { ...cleanEntry.local, prompt_text: 'changed local' };
    const changedSaved = { ...cleanEntry.saved, candidate_hash: 'd'.repeat(64) };
    const changedSavedEntry = { ...cleanEntry, saved: changedSaved };

    expect(draftStatus(cleanEntry)).toBe('Clean');
    expect(draftStatus({ ...cleanEntry, local: changedLocal })).toBe('Unsaved');
    expect(draftStatus({ ...cleanEntry, saved: changedSaved })).toBe('Needs test');
    expect(draftStatus({ ...changedSavedEntry, local: changedLocal })).toBe('Unsaved');
  });

  it.each([
    [{ prompt_text: ' ', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 10, top_p: 0.8 }, 'prompt_text', 'Prompt text must not be blank.'],
    [{ prompt_text: 'prompt', endpoint_name: '\n', temperature: 0.2, max_tokens: 10, top_p: 0.8 }, 'endpoint_name', 'Endpoint name must not be blank.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: '', max_tokens: 10, top_p: 0.8 }, 'temperature', 'Temperature must be between 0 and 1.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: Number.NaN, max_tokens: 10, top_p: 0.8 }, 'temperature', 'Temperature must be between 0 and 1.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 0, top_p: 0.8 }, 'max_tokens', 'Maximum tokens must be a positive integer.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 1.5, top_p: 0.8 }, 'max_tokens', 'Maximum tokens must be a positive integer.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 10, top_p: 2 }, 'top_p', 'Top-p must be between 0 and 1.'],
  ] satisfies [EditableModelDraftForm, string, string][])('validates local form %# with backend message', (form, field, message) => {
    const result = validateDraftForm(form);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors).toMatchObject({ [field]: message });
  });

  it('edits only one agent without invoking fetch', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const state = createDraftEditorState(workbench());
    const next = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'A2' });
    expect(next.byAgent.architect.local.prompt_text).toBe('A2');
    expect(next.byAgent.builder).toBe(state.byAgent.builder);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('merges every server baseline on conflict without losing clean or dirty cross-role state', () => {
    let state = createDraftEditorState(workbench());
    const originalBuilder = state.byAgent.builder.saved.prompt_text;
    const pending = {
      requestId: 1,
      agentKey: 'architect' as const,
      expectedLockVersion: 0,
      submittedCandidate: { prompt_text: 'Architect A2', model: definition('architect').model },
    };
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A2' });
    state = draftEditorReducer(state, { type: 'saveStarted', pending });
    state = draftEditorReducer(state, { type: 'saveConflicted', requestId: 1, conflict: conflict(0, 1, { architect: 'Architect A0', builder: 'Builder B1' }) });

    expect(state.byAgent.builder.saved.prompt_text).toBe('Builder B1');
    expect(state.byAgent.builder.local.prompt_text).toBe('Builder B1');
    expect(draftStatus(state.byAgent.builder)).toBe('Needs test');
    expect(state.byAgent.architect.saved.prompt_text).toBe('Architect A0');
    expect(state.byAgent.architect.local.prompt_text).toBe('Architect A2');
    expect(draftStatus(state.byAgent.architect)).toBe('Unsaved');
    for (const key of AGENT_KEYS.filter((key) => key !== 'architect' && key !== 'builder')) {
      expect(state.byAgent[key].saved).toEqual(conflict(0, 1).server.definitions[key]);
      expect(state.byAgent[key].local).toEqual(formFromDefinition(state.byAgent[key].saved));
    }

    state = draftEditorReducer(state, { type: 'keepLocal', agentKey: 'architect' });
    expect(state.byAgent.builder.saved.prompt_text).not.toBe(originalBuilder);
    expect(state.byAgent.builder.local.prompt_text).not.toBe(originalBuilder);

    let dirty = createDraftEditorState(workbench());
    dirty = draftEditorReducer(dirty, { type: 'edit', agentKey: 'builder', field: 'prompt_text', value: 'Builder B2' });
    dirty = draftEditorReducer(dirty, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A2' });
    dirty = draftEditorReducer(dirty, { type: 'saveStarted', pending });
    dirty = draftEditorReducer(dirty, { type: 'saveConflicted', requestId: 1, conflict: conflict(0, 1, { builder: 'Builder B1' }) });
    expect(dirty.byAgent.builder.saved.prompt_text).toBe('Builder B1');
    expect(dirty.byAgent.builder.local.prompt_text).toBe('Builder B2');
    expect(draftStatus(dirty.byAgent.builder)).toBe('Unsaved');
  });

  it('preserves edits made after submission across success and conflict reload recovery', () => {
    const base = createDraftEditorState(workbench());
    const pending = {
      requestId: 1,
      agentKey: 'architect' as const,
      expectedLockVersion: 0,
      submittedCandidate: { prompt_text: 'Architect A2', model: definition('architect').model },
    };
    let state = draftEditorReducer(base, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A2' });
    state = draftEditorReducer(state, { type: 'saveStarted', pending });
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A3' });
    const succeeded = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 1, result: success('architect', 'Architect A2', 1) });
    expect(succeeded.byAgent.architect.saved.prompt_text).toBe('Architect A2');
    expect(succeeded.byAgent.architect.local.prompt_text).toBe('Architect A3');
    expect(draftStatus(succeeded.byAgent.architect)).toBe('Unsaved');

    const conflicted = draftEditorReducer(state, { type: 'saveConflicted', requestId: 1, conflict: conflict(0, 1, { architect: 'Architect A0' }) });
    expect(conflicted.byAgent.architect.local.prompt_text).toBe('Architect A3');
    const reloaded = draftEditorReducer(conflicted, { type: 'reloadServer', agentKey: 'architect' });
    expect(reloaded.byAgent.architect.recoveryForm?.prompt_text).toBe('Architect A3');
    expect(reloaded.byAgent.architect.local.prompt_text).toBe('Architect A0');
  });

  it('rejects a second aggregate save while the first remains pending', () => {
    const state = createDraftEditorState(workbench());
    const first = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    const second = draftEditorReducer(first, {
      type: 'saveStarted',
      pending: { requestId: 2, agentKey: 'builder', expectedLockVersion: 0, submittedCandidate: { ...request().candidate, prompt_text: 'B2' } },
    });
    expect(second).toBe(first);
    expect(second.pendingSave).toEqual(first.pendingSave);
  });

  it('rejects old response while newer request remains pending', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
    state = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 1, result: success('architect', 'A2', 1) });
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { requestId: 2, agentKey: 'builder', expectedLockVersion: 1, submittedCandidate: { ...request().candidate, prompt_text: 'B2' } } });
    const staleResult = success('architect', 'stale but lock-valid for request 2', 2);
    const next = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 1, result: staleResult });
    expect(next).toBe(state);
    expect(next.pendingSave?.requestId).toBe(2);
    expect(next.draft.lock_version).toBe(1);
  });

  it('clears a current invalid lower-lock response without changing drafts or forms', () => {
    let state = createDraftEditorState(workbench());
    state = { ...state, draft: metadata(2) };
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { requestId: 3, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
    const beforeEntry = state.byAgent.architect;
    const next = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 3, result: success('architect', 'A2', 1) });
    expect(next.pendingSave).toBeNull();
    expect(next.draft).toEqual(state.draft);
    expect(next.byAgent.architect.saved).toBe(beforeEntry.saved);
    expect(next.byAgent.architect.local).toBe(beforeEntry.local);
    expect(next.byAgent.architect.requestError).toBe('Unable to save draft because the server response was invalid.');
  });

  it('contains save failures to the pending role and preserves every draft value', () => {
    const messages = [
      'Unable to save draft. Check your connection and try again.',
      'Unable to save draft (500 Internal Server Error).',
      'Unable to save draft because the server response was invalid.',
    ];
    for (const [index, message] of messages.entries()) {
      let state = createDraftEditorState(workbench());
      state = draftEditorReducer(state, { type: 'saveStarted', pending: { requestId: index + 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
      const draft = state.draft;
      const entries = state.byAgent;
      const next = draftEditorReducer(state, { type: 'saveFailed', requestId: index + 1, message });
      expect(next.pendingSave).toBeNull();
      expect(next.draft).toBe(draft);
      expect(next.byAgent.architect.saved).toBe(entries.architect.saved);
      expect(next.byAgent.architect.local).toBe(entries.architect.local);
      expect(next.byAgent.architect.requestError).toBe(message);
      for (const key of AGENT_KEYS.filter((key) => key !== 'architect')) expect(next.byAgent[key]).toBe(entries[key]);
    }
  });

  it('maps a current validation rejection only onto the pending role', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
    const builder = state.byAgent.builder;
    const next = draftEditorReducer(state, {
      type: 'saveRejected',
      requestId: 1,
      error: { code: 'invalid_draft', errors: [{ field: 'candidate.model.temperature', code: 'out_of_range', message: 'Temperature must be between 0 and 1.' }] },
    });
    expect(next.pendingSave).toBeNull();
    expect(next.byAgent.architect.fieldErrors).toEqual({ temperature: 'Temperature must be between 0 and 1.' });
    expect(next.byAgent.builder).toBe(builder);
  });

  it('restores and dismisses only the captured recovery form', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'A3' });
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'architect' });
    expect(state.byAgent.architect.recoveryForm?.prompt_text).toBe('A3');
    state = draftEditorReducer(state, { type: 'restoreRecovery', agentKey: 'architect' });
    expect(state.byAgent.architect.local.prompt_text).toBe('A3');
    expect(state.byAgent.architect.recoveryForm).toBeNull();
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'architect' });
    state = draftEditorReducer(state, { type: 'dismissRecovery', agentKey: 'architect' });
    expect(state.byAgent.architect.recoveryForm).toBeNull();
  });
});
