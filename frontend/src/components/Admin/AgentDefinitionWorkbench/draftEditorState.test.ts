import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AgentDefinitionApiError,
  CUSTOM_ANCHORS,
  InvalidDraftSaveResponseError,
  parseDraftSaveConflictResponse,
  parseDraftSaveSuccessResponse,
  parseDraftValidationErrorResponse,
  parseLegacyPromptSourceResponse,
  readDraftLegacyPromptSource,
  saveDraftDefinition,
  upgradeDraftProtectedAssembly,
  upgradeDraftSchemaContract,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type AssemblyRulesV1,
  type AssemblyRulesV2,
  type CustomTextBlock,
  type DraftDefinition,
  type DraftSaveConflictResponse,
  type DraftSaveRequest,
  type DraftSaveSuccessResponse,
} from '../../../api/agentDefinitions';
import {
  ALREADY_CURRENT_REJECTION,
  CANONICAL_FIELD_DESCRIPTORS,
  DIAGNOSTIC_NOTES_DESCRIPTORS,
  DIRTY_LEGACY_PROMPT,
  EMPTY_V2_ASSEMBLY_RULES,
  MANUAL_RESOLUTION_REJECTION,
  PUBLISHED_V1_PROMPT_SOURCE,
  SCHEMA_ALREADY_CURRENT_REJECTION,
  V2_AUTHORED_PROMPT,
  syntheticAgentDefinitionWorkbench,
  syntheticLegacyPromptSource,
  syntheticNullCandidateConflict,
  syntheticSchemaUpgradeSuccess,
  syntheticSchemaV2DraftDefinition,
  syntheticUpgradeSuccess,
  syntheticV2DraftDefinition,
} from '../../../../tests/fixtures/mocks';
import {
  createDraftEditorState,
  draftEditorReducer,
  draftSaveErrorMessage,
  draftStatus,
  formFromDefinition,
  LEGACY_COMPOSITE_ROLES,
  retainedFormId,
  RETAINED_REASONS,
  validateDraftForm,
  type DraftEditorState,
  type EditableModelDraftForm,
  type PendingDraftSave,
} from './draftEditorState';

/** The v1 arm is the only arm the inherited #263 fixtures use. */
function v1Rules(definition: DraftDefinition): AssemblyRulesV1 {
  if (definition.assembly_rules.format_version !== 1) throw new Error('expected v1 assembly rules');
  return definition.assembly_rules;
}

function v2Rules(form: { assembly_rules: AssemblyRulesV2 | null }): AssemblyRulesV2 {
  if (form.assembly_rules === null) throw new Error('expected local v2 assembly rules');
  return form.assembly_rules;
}

const AGENT_KEYS: AgentKey[] = [
  'architect',
  'data_analyst',
  'builder',
  'build_reviewer',
  'fixer',
  'fix_reviewer',
  'deck_reviewer',
];

/**
 * The affected-role matrix for this file, owned here rather than hand-typed at each
 * `it.each`. Six matrices used to carry their own copy of the pair, so narrowing them
 * dropped six brief-mandated Build Reviewer behaviours and still reported all-green in
 * both lanes — the silent-shrink failure the browser lane closed at
 * `agent-definition-workbench.spec.ts` and this lane did not. The agreement test below
 * makes narrowing this constant RED instead, and the server's canonical transition list
 * is joined to `LEGACY_COMPOSITE_ROLES` by
 * `test_every_affected_role_copy_matches_the_canonical_transition_list`.
 */
const AFFECTED_ROLES = ['data_analyst', 'build_reviewer'] as const;

function workbench(): AgentDefinitionWorkbenchResponse {
  return structuredClone(syntheticAgentDefinitionWorkbench);
}

describe('the affected-role Vitest matrix', () => {
  it('cannot silently narrow', () => {
    expect([...AFFECTED_ROLES]).toEqual([...LEGACY_COMPOSITE_ROLES]);
    expect(AFFECTED_ROLES).toHaveLength(2);
    expect(new Set(AFFECTED_ROLES).size).toBe(AFFECTED_ROLES.length);
    for (const agentKey of AFFECTED_ROLES) {
      // Each role must really be a legacy composite in the fixture world, or the
      // matrices below would run their sequences against a role with no v1 source.
      expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).toBeTruthy();
      expect(V2_AUTHORED_PROMPT[agentKey]).toBeTruthy();
      expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).not.toEqual(V2_AUTHORED_PROMPT[agentKey]);
    }
  });
});

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
      'definition.schema_contract.digest', 'definition.protected_stage_view', 'changed',
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

  it('rejects an unknown extra key at every level of the 200 envelope', () => {
    const valid = success('architect', 'Architect A2', 1);
    expect(parseDraftSaveSuccessResponse(valid)).not.toBeNull();

    // `hasExactKeys` checks cardinality as well as membership, so no level may carry
    // a field the contract does not name. The definition level is the one this ticket
    // widened, which is why it is pinned here alongside its siblings.
    const levels = [
      'extra',
      'draft.extra',
      'definition.extra',
      'definition.model.extra',
      'definition.schema_overlay.extra',
      'definition.assembly_rules.extra',
      'definition.protected_assembly.extra',
      'definition.schema_contract.extra',
      'definition.protected_stage_view.0.extra',
    ];
    for (const path of levels) {
      expect(parseDraftSaveSuccessResponse(setAtPath(valid, path, true)), `extra ${path}`).toBeNull();
    }

    // The same exactness holds for the definitions carried by a conflict envelope.
    const conflicted = conflict(0, 1);
    expect(parseDraftSaveConflictResponse(conflicted)).not.toBeNull();
    for (const path of [
      'server.definitions.architect.extra',
      'server.definitions.deck_reviewer.extra',
      'server.definitions.architect.protected_stage_view.0.extra',
    ]) {
      expect(parseDraftSaveConflictResponse(setAtPath(conflicted, path, true)), `extra ${path}`).toBeNull();
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
    expect(v1Rules(architect).blocks).not.toBe(v1Rules(sourceArchitect.draft).blocks);
    expect(v1Rules(architect).blocks[0]).not.toBe(v1Rules(sourceArchitect.draft).blocks[0]);

    const sourceEndpoint = sourceArchitect.draft.model.endpoint_name;
    const builderEndpoint = builder.model.endpoint_name;
    architect.model.endpoint_name = 'mutated endpoint';
    architect.schema_overlay.field_overrides.injected = true;
    v1Rules(architect).blocks.push({ kind: 'authored_prompt', condition: 'always' });

    expect(sourceArchitect.draft.model.endpoint_name).toBe(sourceEndpoint);
    expect(builder.model.endpoint_name).toBe(builderEndpoint);
    expect(sourceArchitect.draft.schema_overlay.field_overrides).not.toHaveProperty('injected');
    expect(builder.schema_overlay.field_overrides).not.toHaveProperty('injected');
    expect(v1Rules(sourceArchitect.draft).blocks).toHaveLength(5);
    expect(v1Rules(builder).blocks).toHaveLength(5);
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
    [{ prompt_text: ' ', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 10, top_p: 0.8, assembly_rules: null }, 'prompt_text', 'Prompt text must not be blank.'],
    [{ prompt_text: 'prompt', endpoint_name: '\n', temperature: 0.2, max_tokens: 10, top_p: 0.8, assembly_rules: null }, 'endpoint_name', 'Endpoint name must not be blank.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: '', max_tokens: 10, top_p: 0.8, assembly_rules: null }, 'temperature', 'Temperature must be between 0 and 1.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: Number.NaN, max_tokens: 10, top_p: 0.8, assembly_rules: null }, 'temperature', 'Temperature must be between 0 and 1.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 0, top_p: 0.8, assembly_rules: null }, 'max_tokens', 'Maximum tokens must be a positive integer.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 1.5, top_p: 0.8, assembly_rules: null }, 'max_tokens', 'Maximum tokens must be a positive integer.'],
    [{ prompt_text: 'prompt', endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 10, top_p: 2, assembly_rules: null }, 'top_p', 'Top-p must be between 0 and 1.'],
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
    const pending: PendingDraftSave = {
      operation: 'save',
      requestId: 1,
      agentKey: 'architect',
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
    const pending: PendingDraftSave = {
      operation: 'save',
      requestId: 1,
      agentKey: 'architect',
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
    expect(reloaded.byAgent.architect.retainedForms.map((item) => item.manualOnlyPrompt))
      .toEqual(['Architect A3']);
    expect(reloaded.byAgent.architect.local.prompt_text).toBe('Architect A0');
  });

  it('rejects a second aggregate save while the first remains pending', () => {
    const state = createDraftEditorState(workbench());
    const first = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    const second = draftEditorReducer(first, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 2, agentKey: 'builder', expectedLockVersion: 0, submittedCandidate: { ...request().candidate, prompt_text: 'B2' } },
    });
    expect(second).toBe(first);
    expect(second.pendingSave).toEqual(first.pendingSave);
  });

  it('rejects old response while newer request remains pending', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
    state = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 1, result: success('architect', 'A2', 1) });
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { operation: 'save', requestId: 2, agentKey: 'builder', expectedLockVersion: 1, submittedCandidate: { ...request().candidate, prompt_text: 'B2' } } });
    const staleResult = success('architect', 'stale but lock-valid for request 2', 2);
    const next = draftEditorReducer(state, { type: 'saveSucceeded', requestId: 1, result: staleResult });
    expect(next).toBe(state);
    expect(next.pendingSave?.requestId).toBe(2);
    expect(next.draft.lock_version).toBe(1);
  });

  it('clears a current invalid lower-lock response without changing drafts or forms', () => {
    let state = createDraftEditorState(workbench());
    state = { ...state, draft: metadata(2) };
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { operation: 'save', requestId: 3, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
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
      state = draftEditorReducer(state, { type: 'saveStarted', pending: { operation: 'save', requestId: index + 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
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
    state = draftEditorReducer(state, { type: 'saveStarted', pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate } });
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

  it('appends, restores by ID, and discards ordered retained forms without overwriting', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'A3' });
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'architect' });
    const first = retainedFormId('architect', 1);
    expect(state.byAgent.architect.retainedForms.map((item) => item.id)).toEqual([first]);
    expect(state.byAgent.architect.retainedForms[0].form.prompt_text).toBe('A3');
    expect(state.byAgent.architect.retainedForms[0].manualOnlyPrompt).toBe('A3');
    expect(state.byAgent.architect.local.prompt_text)
      .toBe(definition('architect').prompt_text);

    // A second Reload server appends rather than replacing the first alternative.
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'A4' });
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'architect' });
    const second = retainedFormId('architect', 2);
    expect(state.byAgent.architect.retainedForms.map((item) => item.id)).toEqual([first, second]);
    expect(state.byAgent.architect.retainedForms.map((item) => item.manualOnlyPrompt)).toEqual(['A3', 'A4']);

    // Restore addresses exactly one stable ID and leaves the collection intact.
    state = draftEditorReducer(state, { type: 'restoreRetained', agentKey: 'architect', retainedId: first });
    expect(state.byAgent.architect.local.prompt_text).toBe('A3');
    expect(state.byAgent.architect.retainedForms.map((item) => item.id)).toEqual([first, second]);

    state = draftEditorReducer(state, { type: 'discardRetained', agentKey: 'architect', retainedId: first });
    expect(state.byAgent.architect.retainedForms.map((item) => item.id)).toEqual([second]);
    const unchanged = draftEditorReducer(state, { type: 'discardRetained', agentKey: 'architect', retainedId: first });
    expect(unchanged).toBe(state);
    const noSuchRestore = draftEditorReducer(state, { type: 'restoreRetained', agentKey: 'architect', retainedId: first });
    expect(noSuchRestore).toBe(state);
  });
});

// ============================================================
// #265 strict v2 transport
// ============================================================

const BLOCK_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const BLOCK_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const BLOCK_C = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const BLOCK_D = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';

function block(id: string, anchor: CustomTextBlock['anchor'], text: string): CustomTextBlock {
  return { kind: 'custom_text', block_id: id, anchor, condition: 'always', text };
}

function v2Definition(agentKey: AgentKey, blocks: CustomTextBlock[] = []): DraftDefinition {
  return syntheticV2DraftDefinition(agentKey, {
    assembly_rules: { format_version: 2, custom_blocks: blocks },
  });
}

function v2Success(agentKey: AgentKey, lockVersion: number): DraftSaveSuccessResponse {
  return syntheticUpgradeSuccess(agentKey, lockVersion);
}

describe('strict v2 assembly-rules parsing', () => {
  function withRules(rules: unknown) {
    const valid = success('architect', 'A2', 1);
    return setAtPath(valid, 'definition.assembly_rules', rules);
  }

  it('accepts exactly the v1 and v2 arms and rejects every hybrid', () => {
    const v1 = structuredClone(v1Rules(definition('architect')));
    const v2 = structuredClone(EMPTY_V2_ASSEMBLY_RULES);
    expect(parseDraftSaveSuccessResponse(withRules(v1))).not.toBeNull();
    expect(parseDraftSaveSuccessResponse(withRules(v2))).not.toBeNull();
    expect(parseDraftSaveSuccessResponse(withRules({
      format_version: 2,
      custom_blocks: [block(BLOCK_A, 'after_authored_prompt', 'text')],
    }))).not.toBeNull();

    const rejected: unknown[] = [
      { format_version: 1, custom_blocks: [] },
      { format_version: 2, separator: '\n\n', blocks: [] },
      { ...v2, separator: '\n\n' },
      { ...v1, custom_blocks: [] },
      { format_version: 3, custom_blocks: [] },
      { format_version: '2', custom_blocks: [] },
      { format_version: 2 },
      { format_version: 2, custom_blocks: {} },
      [v2],
      null,
      'v2',
      2,
    ];
    for (const invalid of rejected) {
      expect(parseDraftSaveSuccessResponse(withRules(invalid)), JSON.stringify(invalid)).toBeNull();
    }
  });

  it('rejects every malformed custom block field', () => {
    const valid = block(BLOCK_A, 'after_deck_brief', 'body');
    expect(parseDraftSaveSuccessResponse(withRules({ format_version: 2, custom_blocks: [valid] })))
      .not.toBeNull();

    const rejected: unknown[] = [
      { ...valid, kind: 'protected' },
      { ...valid, block_id: 'not-a-uuid' },
      { ...valid, block_id: BLOCK_A.toUpperCase() },
      { ...valid, block_id: 1 },
      { ...valid, anchor: 'after_payload' },
      { ...valid, anchor: null },
      { ...valid, condition: 'sometimes' },
      { ...valid, text: 2 },
      { ...valid, extra: true },
      Object.fromEntries(Object.entries(valid).filter(([key]) => key !== 'text')),
      null,
      [valid],
    ];
    for (const invalid of rejected) {
      expect(
        parseDraftSaveSuccessResponse(withRules({ format_version: 2, custom_blocks: [invalid] })),
        JSON.stringify(invalid),
      ).toBeNull();
    }
  });

  it('rejects every malformed protected stage view row', () => {
    const valid = structuredClone(definition('architect').protected_stage_view[0]);
    const base = success('architect', 'A2', 1);
    expect(parseDraftSaveSuccessResponse(
      setAtPath(base, 'definition.protected_stage_view', [valid]),
    )).not.toBeNull();

    const rejected: unknown[] = [
      { ...valid, locked: false },
      { ...valid, locked: 'true' },
      { ...valid, condition: 'never' },
      { ...valid, bundle_digest: 'z'.repeat(64) },
      { ...valid, bundle_digest: 'a'.repeat(63) },
      { ...valid, bundle_version: 0 },
      { ...valid, bundle_version: 1.5 },
      { ...valid, stage_id: 1 },
      { ...valid, display_text: null },
      { ...valid, legal_adjacent_custom_anchors: ['after_payload'] },
      { ...valid, legal_adjacent_custom_anchors: 'after_deck_brief' },
      { ...valid, extra: true },
      Object.fromEntries(Object.entries(valid).filter(([key]) => key !== 'label')),
      null,
    ];
    for (const invalid of rejected) {
      expect(
        parseDraftSaveSuccessResponse(setAtPath(base, 'definition.protected_stage_view', [invalid])),
        JSON.stringify(invalid),
      ).toBeNull();
    }
    expect(parseDraftSaveSuccessResponse(
      setAtPath(base, 'definition.protected_stage_view', {}),
    )).toBeNull();
  });

  it('requires an editable candidate for an ordinary conflict and null for an upgrade conflict', () => {
    const ordinary = conflict(0, 1);
    const nullCandidate = syntheticNullCandidateConflict(0, 1);

    expect(parseDraftSaveConflictResponse(ordinary)).toEqual(ordinary);
    expect(parseDraftSaveConflictResponse(ordinary, 'editable')).toEqual(ordinary);
    expect(parseDraftSaveConflictResponse(ordinary, 'null')).toBeNull();
    expect(parseDraftSaveConflictResponse(nullCandidate, 'null')).toEqual(nullCandidate);
    expect(parseDraftSaveConflictResponse(nullCandidate)).toBeNull();
    expect(parseDraftSaveConflictResponse(nullCandidate, 'editable')).toBeNull();
  });

  it('accepts exactly the two-key and three-key candidate shapes', () => {
    const ordinary = conflict(0, 1);
    const model = structuredClone(definition('architect').model);
    const accepted: unknown[] = [
      { prompt_text: 'p', model },
      { prompt_text: 'p', model, assembly_rules: null },
      { prompt_text: 'p', model, assembly_rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES) },
      {
        prompt_text: 'p',
        model,
        assembly_rules: { format_version: 2, custom_blocks: [block(BLOCK_A, 'after_authored_prompt', 't')] },
      },
    ];
    for (const candidate of accepted) {
      expect(
        parseDraftSaveConflictResponse(setAtPath(ordinary, 'client_candidate', candidate)),
        JSON.stringify(candidate),
      ).not.toBeNull();
    }

    const rejected: unknown[] = [
      { prompt_text: 'p' },
      { model },
      { prompt_text: 'p', model, assembly_rules: structuredClone(v1Rules(definition('architect'))) },
      { prompt_text: 'p', model, assembly_rules: {} },
      { prompt_text: 'p', model, assembly_rules: null, extra: true },
      { prompt_text: 'p', model, extra: true },
      { prompt_text: 1, model },
    ];
    for (const candidate of rejected) {
      expect(
        parseDraftSaveConflictResponse(setAtPath(ordinary, 'client_candidate', candidate)),
        JSON.stringify(candidate),
      ).toBeNull();
    }
  });

  it('parses the legacy prompt source DTO strictly', () => {
    const valid = syntheticLegacyPromptSource('data_analyst', 0);
    expect(parseLegacyPromptSourceResponse(valid)).toEqual(valid);

    const rejected: unknown[] = [
      setAtPath(valid, 'agent_key', 'foreman'),
      setAtPath(valid, 'agent_key', 1),
      setAtPath(valid, 'lock_version', 1),
      setAtPath(valid, 'lock_version', -1),
      setAtPath(valid, 'source.prompt_text', 1),
      setAtPath(valid, 'source.revision_id', 0),
      setAtPath(valid, 'source.content_hash', 'a'.repeat(63)),
      setAtPath(valid, 'source.extra', true),
      setAtPath(valid, 'source', null, true),
      { ...valid, extra: true },
      [valid],
      null,
      'body',
    ];
    for (const invalid of rejected) {
      expect(parseLegacyPromptSourceResponse(invalid), JSON.stringify(invalid)).toBeNull();
    }
  });

  it('sends exactly the lock body to the upgrade route and parses each contract status', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, v2Success('data_analyst', 1)));
    vi.stubGlobal('fetch', fetchMock);

    await expect(upgradeDraftProtectedAssembly('data_analyst', { lock_version: 0 }))
      .resolves.toEqual(v2Success('data_analyst', 1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/data_analyst\/protected-assembly-upgrade$/);
    expect(init).toEqual({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"lock_version":0}',
    });
    expect(JSON.parse(String(init.body))).toEqual({ lock_version: 0 });

    for (const rejection of [MANUAL_RESOLUTION_REJECTION, ALREADY_CURRENT_REJECTION]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(422, rejection, 'Unprocessable Entity')));
      const thrown = await upgradeDraftProtectedAssembly('data_analyst', { lock_version: 0 })
        .catch((error: unknown) => error);
      expect(thrown).toBeInstanceOf(AgentDefinitionApiError);
      expect((thrown as AgentDefinitionApiError).payload).toEqual(rejection);
    }

    const nullConflict = syntheticNullCandidateConflict(0, 1, ['data_analyst']);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(409, nullConflict, 'Conflict')));
    const conflicted = await upgradeDraftProtectedAssembly('data_analyst', { lock_version: 0 })
      .catch((error: unknown) => error);
    expect((conflicted as AgentDefinitionApiError).payload).toEqual(nullConflict);

    // An upgrade 409 that echoes a candidate is not the upgrade contract.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(409, conflict(0, 1), 'Conflict')));
    await expect(upgradeDraftProtectedAssembly('data_analyst', { lock_version: 0 }))
      .rejects.toBeInstanceOf(InvalidDraftSaveResponseError);
  });

  it('sends exactly the lock body to the legacy-source route and parses each contract status', async () => {
    const source = syntheticLegacyPromptSource('build_reviewer', 0);
    const fetchMock = vi.fn().mockResolvedValue(response(200, source));
    vi.stubGlobal('fetch', fetchMock);

    await expect(readDraftLegacyPromptSource('build_reviewer', { lock_version: 0 }))
      .resolves.toEqual(source);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/build_reviewer\/legacy-prompt-source$/);
    expect(init).toEqual({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"lock_version":0}',
    });

    for (const code of [
      'legacy_prompt_source_unsupported',
      'legacy_prompt_source_not_required',
      'legacy_prompt_source_unavailable',
    ]) {
      const rejection = {
        code: 'invalid_draft',
        errors: [{ field: 'prompt_text', code, message: `rejected: ${code}` }],
      };
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(422, rejection, 'Unprocessable Entity')));
      const thrown = await readDraftLegacyPromptSource('build_reviewer', { lock_version: 0 })
        .catch((error: unknown) => error);
      expect((thrown as AgentDefinitionApiError).payload).toEqual(rejection);
    }

    const nullConflict = syntheticNullCandidateConflict(0, 1);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(409, nullConflict, 'Conflict')));
    const conflicted = await readDraftLegacyPromptSource('build_reviewer', { lock_version: 0 })
      .catch((error: unknown) => error);
    expect((conflicted as AgentDefinitionApiError).payload).toEqual(nullConflict);

    for (const body of [{ ...source, extra: true }, [], null, 1]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, body)));
      await expect(readDraftLegacyPromptSource('build_reviewer', { lock_version: 0 }))
        .rejects.toBeInstanceOf(InvalidDraftSaveResponseError);
    }
  });

  it('serializes v2 custom blocks in the ordinary save candidate and omits the key on v1', async () => {
    const v2: AssemblyRulesV2 = {
      format_version: 2,
      custom_blocks: [block(BLOCK_A, 'after_authored_prompt', 'body')],
    };
    const withRulesForm: EditableModelDraftForm = {
      prompt_text: 'authored only',
      endpoint_name: 'endpoint',
      temperature: 0.2,
      max_tokens: 4096,
      top_p: 0.8,
      assembly_rules: structuredClone(v2),
    };
    const v2Validation = validateDraftForm(withRulesForm);
    expect(v2Validation.ok).toBe(true);
    if (v2Validation.ok) {
      expect(v2Validation.candidate).toEqual({
        prompt_text: 'authored only',
        model: { endpoint_name: 'endpoint', temperature: 0.2, max_tokens: 4096, top_p: 0.8 },
        assembly_rules: structuredClone(v2),
      });
    }

    const v1Validation = validateDraftForm({ ...withRulesForm, assembly_rules: null });
    expect(v1Validation.ok).toBe(true);
    if (v1Validation.ok) {
      expect(Object.keys(v1Validation.candidate)).toEqual(['prompt_text', 'model']);
    }
  });
});

// ============================================================
// #265 local assembly editing
// ============================================================

function v2State(agentKey: AgentKey, blocks: CustomTextBlock[] = []): DraftEditorState {
  const base = workbench();
  base.nodes = base.nodes.map((node) => {
    if (node.execution_kind !== 'model' || node.agent_key !== agentKey) return node;
    return { ...node, draft: v2Definition(agentKey, blocks) };
  });
  return createDraftEditorState(base);
}

describe('local assembly editing', () => {
  it('adds, edits, deletes, and reorders inside one anchor without any request', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    let state = v2State('architect');

    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'architect', blockId: BLOCK_A, anchor: 'after_authored_prompt',
    });
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'architect', blockId: BLOCK_B, anchor: 'after_environment_constraints',
    });
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'architect', blockId: BLOCK_C, anchor: 'after_authored_prompt',
    });

    // A new sibling lands immediately after the last sibling at its own anchor.
    expect(v2Rules(state.byAgent.architect.local).custom_blocks).toEqual([
      { kind: 'custom_text', block_id: BLOCK_A, anchor: 'after_authored_prompt', condition: 'always', text: '' },
      { kind: 'custom_text', block_id: BLOCK_C, anchor: 'after_authored_prompt', condition: 'always', text: '' },
      { kind: 'custom_text', block_id: BLOCK_B, anchor: 'after_environment_constraints', condition: 'always', text: '' },
    ]);
    expect(draftStatus(state.byAgent.architect)).toBe('Unsaved');

    state = draftEditorReducer(state, {
      type: 'assemblyBlockTextChanged', agentKey: 'architect', blockId: BLOCK_C, text: 'C body',
    });
    state = draftEditorReducer(state, {
      type: 'assemblyBlockConditionChanged',
      agentKey: 'architect',
      blockId: BLOCK_C,
      condition: 'design_system_active',
    });
    expect(v2Rules(state.byAgent.architect.local).custom_blocks[1]).toEqual({
      kind: 'custom_text',
      block_id: BLOCK_C,
      anchor: 'after_authored_prompt',
      condition: 'design_system_active',
      text: 'C body',
    });
    expect(v2Rules(state.byAgent.architect.local).custom_blocks[0].text).toBe('');

    // Moving swaps same-anchor siblings only.
    state = draftEditorReducer(state, {
      type: 'assemblyBlockMoved', agentKey: 'architect', blockId: BLOCK_C, direction: 'up',
    });
    expect(v2Rules(state.byAgent.architect.local).custom_blocks.map((item) => item.block_id))
      .toEqual([BLOCK_C, BLOCK_A, BLOCK_B]);

    // An arrow cannot cross an anchor, so the edge move is a no-op.
    const atEdge = draftEditorReducer(state, {
      type: 'assemblyBlockMoved', agentKey: 'architect', blockId: BLOCK_C, direction: 'up',
    });
    expect(v2Rules(atEdge.byAgent.architect.local).custom_blocks.map((item) => item.block_id))
      .toEqual([BLOCK_C, BLOCK_A, BLOCK_B]);
    const loneDown = draftEditorReducer(state, {
      type: 'assemblyBlockMoved', agentKey: 'architect', blockId: BLOCK_B, direction: 'down',
    });
    expect(v2Rules(loneDown.byAgent.architect.local).custom_blocks.map((item) => item.block_id))
      .toEqual([BLOCK_C, BLOCK_A, BLOCK_B]);
    const loneUp = draftEditorReducer(state, {
      type: 'assemblyBlockMoved', agentKey: 'architect', blockId: BLOCK_B, direction: 'up',
    });
    expect(v2Rules(loneUp.byAgent.architect.local).custom_blocks.map((item) => item.block_id))
      .toEqual([BLOCK_C, BLOCK_A, BLOCK_B]);

    state = draftEditorReducer(state, {
      type: 'assemblyBlockDeleted', agentKey: 'architect', blockId: BLOCK_A,
    });
    expect(v2Rules(state.byAgent.architect.local).custom_blocks.map((item) => item.block_id))
      .toEqual([BLOCK_C, BLOCK_B]);
    expect(state.byAgent.architect.saved.assembly_rules).toEqual(
      { format_version: 2, custom_blocks: [] },
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('inserts by anchor rank, so no click order can build a server-rejected array', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    // Every `Add custom block …` button renders at once for an upgraded role, so a
    // descending sequence is two or three ordinary clicks at valid anchors. Appending
    // when no sibling exists built ["after_environment_constraints",
    // "after_authored_prompt"], which the server refuses as `invalid_anchor_order`
    // (`_ANCHOR_RANK`, `prompt_assembler.py`) while the UI still groups the blocks by
    // anchor — so the admin saw the right order and got a 422 that named the wrong one.
    let state = v2State('build_reviewer');
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'build_reviewer', blockId: BLOCK_A, anchor: 'after_environment_constraints',
    });
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'build_reviewer', blockId: BLOCK_B, anchor: 'after_authored_prompt',
    });
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'build_reviewer', blockId: BLOCK_C, anchor: 'after_deck_brief',
    });

    const blocks = v2Rules(state.byAgent.build_reviewer.local).custom_blocks;
    expect(blocks.map((block) => block.block_id)).toEqual([BLOCK_B, BLOCK_C, BLOCK_A]);
    const anchors = blocks.map((block) => block.anchor);
    // Non-decreasing in the rank order the server enforces, which the client holds as
    // `CUSTOM_ANCHORS` and `test_client_condition_and_anchor_vocabularies_match_the_server`
    // pins to that server rank map.
    const ranks = anchors.map((anchor) => CUSTOM_ANCHORS.indexOf(anchor));
    expect(ranks).toEqual([...ranks].sort((left, right) => left - right));
    expect(anchors).toEqual([
      'after_authored_prompt', 'after_deck_brief', 'after_environment_constraints',
    ]);

    // A later sibling still lands after the last block at its own anchor, so ordinary
    // ascending authoring is unchanged and same-anchor order stays the admin's.
    state = draftEditorReducer(state, {
      type: 'assemblyBlockAdded', agentKey: 'build_reviewer', blockId: BLOCK_D, anchor: 'after_authored_prompt',
    });
    expect(v2Rules(state.byAgent.build_reviewer.local).custom_blocks.map((block) => block.block_id))
      .toEqual([BLOCK_B, BLOCK_D, BLOCK_C, BLOCK_A]);

    // `validateDraftForm` passes `assembly_rules` through verbatim, so what the reducer
    // built is exactly what the save body carries.
    const validation = validateDraftForm(state.byAgent.build_reviewer.local);
    expect(validation.ok).toBe(true);
    if (validation.ok) {
      expect(validation.candidate.assembly_rules).toEqual(
        v2Rules(state.byAgent.build_reviewer.local),
      );
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ignores every assembly action while the role is still on v1', () => {
    const state = createDraftEditorState(workbench());
    const actions = [
      { type: 'assemblyBlockAdded', agentKey: 'architect', blockId: BLOCK_A, anchor: 'after_authored_prompt' },
      { type: 'assemblyBlockTextChanged', agentKey: 'architect', blockId: BLOCK_A, text: 'x' },
      { type: 'assemblyBlockConditionChanged', agentKey: 'architect', blockId: BLOCK_A, condition: 'always' },
      { type: 'assemblyBlockDeleted', agentKey: 'architect', blockId: BLOCK_A },
      { type: 'assemblyBlockMoved', agentKey: 'architect', blockId: BLOCK_A, direction: 'up' },
    ] as const;
    for (const action of actions) {
      const next = draftEditorReducer(state, action);
      expect(next.byAgent.architect.local.assembly_rules).toBeNull();
      expect(draftStatus(next.byAgent.architect)).toBe('Clean');
    }
  });
});

// ============================================================
// #265 discriminated operations on the one aggregate gate
// ============================================================

function upgradePending(agentKey: AgentKey, requestId = 1, expectedLockVersion = 0): PendingDraftSave {
  return { operation: 'upgrade', requestId, agentKey, expectedLockVersion, submittedCandidate: null };
}

function sourcePending(agentKey: AgentKey, requestId = 1, expectedLockVersion = 0): PendingDraftSave {
  return {
    operation: 'sourceRecovery', requestId, agentKey, expectedLockVersion, submittedCandidate: null,
  };
}

describe('discriminated draft operations', () => {
  it('shares one gate across Save, Upgrade, and SourceRecovery', () => {
    const base = createDraftEditorState(workbench());
    const started = draftEditorReducer(base, { type: 'upgradeStarted', pending: upgradePending('data_analyst') });
    expect(started.pendingSave).toEqual(upgradePending('data_analyst'));

    for (const action of [
      { type: 'saveStarted', pending: { operation: 'save', requestId: 2, agentKey: 'builder', expectedLockVersion: 0, submittedCandidate: request().candidate } },
      { type: 'upgradeStarted', pending: upgradePending('build_reviewer', 2) },
      { type: 'sourceRecoveryStarted', pending: sourcePending('data_analyst', 2) },
    ] as const) {
      expect(draftEditorReducer(started, action)).toBe(started);
    }

    const saveFirst = draftEditorReducer(base, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    expect(draftEditorReducer(saveFirst, { type: 'upgradeStarted', pending: upgradePending('data_analyst', 2) }))
      .toBe(saveFirst);
    expect(draftEditorReducer(saveFirst, { type: 'sourceRecoveryStarted', pending: sourcePending('data_analyst', 2) }))
      .toBe(saveFirst);
  });

  it('only the matching operation identity may complete a pending operation', () => {
    const base = createDraftEditorState(workbench());
    const pending = draftEditorReducer(base, { type: 'upgradeStarted', pending: upgradePending('data_analyst', 7) });

    // Wrong request ID, and the right ID under the wrong operation, are no-ops.
    expect(draftEditorReducer(pending, { type: 'upgradeSucceeded', requestId: 6, result: v2Success('data_analyst', 1) })).toBe(pending);
    expect(draftEditorReducer(pending, { type: 'saveSucceeded', requestId: 7, result: v2Success('data_analyst', 1) })).toBe(pending);
    expect(draftEditorReducer(pending, { type: 'saveFailed', requestId: 7, message: 'x' })).toBe(pending);
    expect(draftEditorReducer(pending, { type: 'sourceRecoveryFailed', requestId: 7, message: 'x' })).toBe(pending);
    expect(draftEditorReducer(pending, { type: 'saveRejected', requestId: 7, error: MANUAL_RESOLUTION_REJECTION })).toBe(pending);

    const settled = draftEditorReducer(pending, { type: 'upgradeFailed', requestId: 7, message: 'Upgrade failed.' });
    expect(settled.pendingSave).toBeNull();
    expect(settled.byAgent.data_analyst.requestError).toBe('Upgrade failed.');
  });

  it.each(AFFECTED_ROLES)(
    'refuses to start %s Upgrade while its prompt differs from the saved prompt',
    (agentKey) => {
      let state = createDraftEditorState(workbench());
      state = draftEditorReducer(state, {
        type: 'edit', agentKey, field: 'prompt_text', value: DIRTY_LEGACY_PROMPT,
      });
      const refused = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending(agentKey) });
      expect(refused).toBe(state);
      expect(refused.pendingSave).toBeNull();

      // An unaffected role is not gated on prompt cleanliness.
      let other = createDraftEditorState(workbench());
      other = draftEditorReducer(other, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'dirty' });
      const allowed = draftEditorReducer(other, { type: 'upgradeStarted', pending: upgradePending('architect') });
      expect(allowed.pendingSave).toEqual(upgradePending('architect'));
    },
  );

  it.each(AFFECTED_ROLES)(
    'retains the exact dirty %s prompt as manual-only bytes and leaves the form untouched',
    (agentKey) => {
      let state = createDraftEditorState(workbench());
      state = draftEditorReducer(state, {
        type: 'edit', agentKey, field: 'prompt_text', value: DIRTY_LEGACY_PROMPT,
      });
      const before = state.byAgent[agentKey].local;
      state = draftEditorReducer(state, { type: 'dirtyLegacyPromptRetained', agentKey });

      expect(state.byAgent[agentKey].local).toEqual(before);
      expect(state.byAgent[agentKey].local.prompt_text).toBe(DIRTY_LEGACY_PROMPT);
      expect(state.byAgent[agentKey].retainedForms).toHaveLength(1);
      const retained = state.byAgent[agentKey].retainedForms[0];
      expect(retained.id).toBe(retainedFormId(agentKey, 1));
      expect(retained.source).toBe('dirty_legacy_prompt');
      expect(retained.manualOnlyPrompt).toBe(DIRTY_LEGACY_PROMPT);
      expect(retained.form.prompt_text).toBe(DIRTY_LEGACY_PROMPT);
      expect(state.pendingSave).toBeNull();

      const restored = draftEditorReducer(state, { type: 'restoreSavedPrompt', agentKey });
      expect(restored.byAgent[agentKey].local.prompt_text)
        .toBe(restored.byAgent[agentKey].saved.prompt_text);
      expect(restored.byAgent[agentKey].retainedForms[0].manualOnlyPrompt).toBe(DIRTY_LEGACY_PROMPT);
    },
  );

  it('quarantines a prompt event queued during a pending Upgrade but keeps safe edits live', () => {
    let state = createDraftEditorState(workbench());
    const savedPrompt = state.byAgent.data_analyst.saved.prompt_text;
    state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending('data_analyst') });
    state = draftEditorReducer(state, {
      type: 'edit', agentKey: 'data_analyst', field: 'prompt_text', value: 'queued during flight',
    });

    expect(state.byAgent.data_analyst.local.prompt_text).toBe(savedPrompt);
    expect(state.byAgent.data_analyst.retainedForms).toHaveLength(1);
    expect(state.byAgent.data_analyst.retainedForms[0].source).toBe('pending_prompt_quarantine');
    expect(state.byAgent.data_analyst.retainedForms[0].manualOnlyPrompt).toBe('queued during flight');
    expect(state.byAgent.data_analyst.retainedForms[0].form.prompt_text).toBe(savedPrompt);

    // Safe model fields and other roles stay editable during the same request.
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'data_analyst', field: 'max_tokens', value: 4096 });
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'architect dirty' });
    expect(state.byAgent.data_analyst.local.max_tokens).toBe(4096);
    expect(state.byAgent.architect.local.prompt_text).toBe('architect dirty');
    expect(state.byAgent.architect.retainedForms).toEqual([]);

    const succeeded = draftEditorReducer(state, {
      type: 'upgradeSucceeded', requestId: 1, result: v2Success('data_analyst', 1),
    });
    // The server-authored v2 text wins; never the in-flight or pre-request composite.
    expect(succeeded.byAgent.data_analyst.local.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
    expect(succeeded.byAgent.data_analyst.local.max_tokens).toBe(4096);
    expect(succeeded.byAgent.data_analyst.local.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
    expect(succeeded.byAgent.data_analyst.saved.protected_assembly).toEqual({ version: 2, digest: 'e'.repeat(64) });
    expect(succeeded.byAgent.data_analyst.saved.protected_stage_view.map((row) => row.stage_id)).toEqual([
      'slide_frame_constraints', 'design_system_precedence', 'untrusted_data_notice',
      'untrusted_data_open', 'runtime_payload', 'untrusted_data_close', 'structured_output_binding',
    ]);

    // Every retained form is sanitized against the new authoritative version and
    // the displaced v1 alternative is appended, not overwritten.
    expect(succeeded.byAgent.data_analyst.retainedForms.map((item) => item.id))
      .toEqual([retainedFormId('data_analyst', 1), retainedFormId('data_analyst', 2)]);
    for (const retained of succeeded.byAgent.data_analyst.retainedForms) {
      expect(retained.form.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
      expect(retained.form.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      expect(retained.sanitizedFormatVersion).toBe(2);
    }
    expect(succeeded.byAgent.data_analyst.retainedForms[0].manualOnlyPrompt).toBe('queued during flight');
    expect(succeeded.byAgent.data_analyst.retainedForms[1].manualOnlyPrompt).toBe(savedPrompt);

    // The next ordinary save carries only the authored-only v2 prompt.
    const validation = validateDraftForm(succeeded.byAgent.data_analyst.local);
    expect(validation.ok).toBe(true);
    if (validation.ok) {
      expect(validation.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
      expect(validation.candidate.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
    }
  });

  it.each([
    ['upgradeRejected' as const, MANUAL_RESOLUTION_REJECTION],
    ['upgradeRejected' as const, ALREADY_CURRENT_REJECTION],
  ])('%s retains the exact ordered issues and mutates no definition', (type, rejection) => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending('data_analyst') });
    const before = state.byAgent.data_analyst;
    const next = draftEditorReducer(state, { type, requestId: 1, error: rejection });

    expect(next.pendingSave).toBeNull();
    expect(next.draft).toBe(state.draft);
    expect(next.byAgent.data_analyst.saved).toBe(before.saved);
    expect(next.byAgent.data_analyst.local).toBe(before.local);
    expect(next.byAgent.data_analyst.fieldErrors).toEqual({});
    expect(next.byAgent.data_analyst.responseIssues).toEqual(rejection.errors);
    expect(next.byAgent.data_analyst.requestError).toBeNull();
  });

  it('preserves exact server issue order across a multi-issue rejection', () => {
    let state = v2State('architect');
    state = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    const errors = [
      { field: 'candidate.assembly_rules.custom_blocks.0.block_id', code: 'strict_type', message: 'Custom block ID must be a UUID string.' },
      { field: 'candidate.prompt_text', code: 'blank', message: 'Prompt text must not be blank.' },
      { field: 'candidate.assembly_rules', code: 'invalid_protected_placement', message: 'Assembly rules must satisfy the persisted assembly contract.' },
      { field: 'candidate.assembly_rules.custom_blocks.1.anchor', code: 'unknown_anchor', message: 'Custom block anchor is not supported.' },
    ];
    const next = draftEditorReducer(state, { type: 'saveRejected', requestId: 1, error: { code: 'invalid_draft', errors } });

    // The inline field keeps its own owner; every other issue keeps server order.
    expect(next.byAgent.architect.fieldErrors).toEqual({ prompt_text: 'Prompt text must not be blank.' });
    expect(next.byAgent.architect.responseIssues).toEqual([errors[0], errors[2], errors[3]]);
  });

  it('installs only the returned published source and never writes on recovery', () => {
    let state = createDraftEditorState(workbench());
    const savedPrompt = state.byAgent.build_reviewer.saved.prompt_text;
    const savedDefinition = state.byAgent.build_reviewer.saved;
    state = draftEditorReducer(state, {
      type: 'edit', agentKey: 'build_reviewer', field: 'prompt_text', value: DIRTY_LEGACY_PROMPT,
    });
    state = draftEditorReducer(state, { type: 'sourceRecoveryStarted', pending: sourcePending('build_reviewer') });
    const next = draftEditorReducer(state, {
      type: 'sourceRecoverySucceeded', requestId: 1, result: syntheticLegacyPromptSource('build_reviewer', 0),
    });

    expect(next.pendingSave).toBeNull();
    expect(next.draft).toBe(state.draft);
    expect(next.draft.lock_version).toBe(0);
    expect(next.byAgent.build_reviewer.saved).toBe(savedDefinition);
    expect(next.byAgent.build_reviewer.local.prompt_text)
      .toBe(PUBLISHED_V1_PROMPT_SOURCE.build_reviewer);
    expect(next.byAgent.build_reviewer.local.assembly_rules).toBeNull();

    // Both the edited saved and the edited local alternatives are quarantined.
    expect(next.byAgent.build_reviewer.retainedForms.map((item) => item.id)).toEqual([
      retainedFormId('build_reviewer', 1), retainedFormId('build_reviewer', 2),
    ]);
    expect(next.byAgent.build_reviewer.retainedForms.map((item) => item.manualOnlyPrompt))
      .toEqual([savedPrompt, DIRTY_LEGACY_PROMPT]);
    expect(next.byAgent.build_reviewer.retainedForms.map((item) => item.source))
      .toEqual(['legacy_source_recovery', 'legacy_source_recovery']);
  });

  it('rejects an incoherent legacy-source completion without touching local state', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'sourceRecoveryStarted', pending: sourcePending('build_reviewer') });
    const before = state.byAgent.build_reviewer;

    for (const result of [
      syntheticLegacyPromptSource('data_analyst', 0),
      syntheticLegacyPromptSource('build_reviewer', 1),
    ]) {
      const next = draftEditorReducer(state, { type: 'sourceRecoverySucceeded', requestId: 1, result });
      expect(next.pendingSave).toBeNull();
      expect(next.byAgent.build_reviewer.local).toBe(before.local);
      expect(next.byAgent.build_reviewer.retainedForms).toEqual([]);
      expect(next.byAgent.build_reviewer.requestError)
        .toBe('Unable to save draft because the server response was invalid.');
    }
  });
});

// ============================================================
// #265 cross-version authoritative adoption
// ============================================================

function saveConflictWithV2(
  expectedLockVersion: number,
  currentLockVersion: number,
  v2Roles: readonly AgentKey[],
): DraftSaveConflictResponse {
  const base = conflict(expectedLockVersion, currentLockVersion);
  for (const role of v2Roles) base.server.definitions[role] = v2Definition(role);
  return base;
}

const SENTINEL_SAFE_FIELDS = {
  endpoint_name: 'retained-endpoint',
  temperature: 0.11,
  max_tokens: 2222,
  top_p: 0.33,
} as const;

describe('cross-version authoritative adoption', () => {
  it.each([
    ['data_analyst' as AgentKey, 'saveConflicted' as const],
    ['build_reviewer' as AgentKey, 'saveConflicted' as const],
    ['data_analyst' as AgentKey, 'upgradeConflicted' as const],
    ['build_reviewer' as AgentKey, 'upgradeConflicted' as const],
  ])('quarantines the displaced %s v1 form on %s for a selected entry', (agentKey, type) => {
    // An entry cannot *start* its own Upgrade dirty, so this matrix covers the dirty
    // local prompt under `saveConflicted`. The dirty-prompt-under-Upgrade cell is
    // reachable after the request is in flight and has its own two tests below:
    // `a restored alternative cannot dirty the prompt while its Upgrade is in flight`
    // and `an Upgrade 409 adopts v2 after the prompt was made dirty mid-flight`.
    const dirtyCases = type === 'saveConflicted' ? [false, true] : [false];
    for (const dirty of dirtyCases) {
      let state = createDraftEditorState(workbench());
      const savedPrompt = state.byAgent[agentKey].saved.prompt_text;
      if (dirty) {
        state = draftEditorReducer(state, { type: 'edit', agentKey, field: 'prompt_text', value: DIRTY_LEGACY_PROMPT });
      }
      state = draftEditorReducer(state, { type: 'edit', agentKey, field: 'max_tokens', value: 1234 });
      state = type === 'saveConflicted'
        ? draftEditorReducer(state, {
          type: 'saveStarted',
          pending: { operation: 'save', requestId: 1, agentKey, expectedLockVersion: 0, submittedCandidate: request().candidate },
        })
        : draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending(agentKey) });
      const conflictBody = type === 'saveConflicted'
        ? saveConflictWithV2(0, 1, [agentKey])
        : syntheticNullCandidateConflict(0, 1, [agentKey]);
      state = draftEditorReducer(state, { type, requestId: 1, conflict: conflictBody });

      const entry = state.byAgent[agentKey];
      expect(entry.saved.assembly_rules.format_version).toBe(2);
      expect(entry.local.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
      expect(entry.local.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      // Safe non-prompt local values survive the version change.
      expect(entry.local.max_tokens).toBe(1234);
      expect(entry.retainedForms).toHaveLength(1);
      expect(entry.retainedForms[0].manualOnlyPrompt).toBe(dirty ? DIRTY_LEGACY_PROMPT : savedPrompt);
      expect(entry.retainedForms[0].form.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
      expect(entry.retainedForms[0].form.max_tokens).toBe(1234);
      expect(entry.retainedForms[0].sanitizedFormatVersion).toBe(2);

      // Keep local clears the conflict but cannot restore the legacy prompt.
      const kept = draftEditorReducer(state, { type: 'keepLocal', agentKey });
      expect(kept.byAgent[agentKey].conflict).toBeNull();
      expect(kept.byAgent[agentKey].local.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
      expect(kept.byAgent[agentKey].local.max_tokens).toBe(1234);

      // The immediate PUT excludes every manual-only byte.
      const validation = validateDraftForm(kept.byAgent[agentKey].local);
      expect(validation.ok).toBe(true);
      if (validation.ok) {
        expect(validation.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
        expect(validation.candidate.prompt_text).not.toBe(savedPrompt);
        expect(validation.candidate.prompt_text).not.toBe(DIRTY_LEGACY_PROMPT);
      }
    }
  });

  it.each([
    [AFFECTED_ROLES[0], AFFECTED_ROLES[1]],
    [AFFECTED_ROLES[1], AFFECTED_ROLES[0]],
  ])('an Upgrade 409 for %s quarantines the dirty v1 prompt of unselected %s', (started, other) => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, {
      type: 'edit', agentKey: other, field: 'prompt_text', value: DIRTY_LEGACY_PROMPT,
    });
    state = draftEditorReducer(state, { type: 'edit', agentKey: other, field: 'top_p', value: 0.77 });
    state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending(started) });
    expect(state.pendingSave).toEqual(upgradePending(started));
    state = draftEditorReducer(state, {
      type: 'upgradeConflicted',
      requestId: 1,
      conflict: syntheticNullCandidateConflict(0, 1, [started, other]),
    });

    const entry = state.byAgent[other];
    expect(entry.saved.assembly_rules.format_version).toBe(2);
    expect(entry.local.prompt_text).toBe(V2_AUTHORED_PROMPT[other]);
    expect(entry.local.top_p).toBe(0.77);
    expect(entry.retainedForms).toHaveLength(1);
    expect(entry.retainedForms[0].manualOnlyPrompt).toBe(DIRTY_LEGACY_PROMPT);
    expect(entry.retainedForms[0].form.top_p).toBe(0.77);
    expect(entry.retainedForms[0].form.prompt_text).toBe(V2_AUTHORED_PROMPT[other]);

    const validation = validateDraftForm(entry.local);
    expect(validation.ok).toBe(true);
    if (validation.ok) {
      expect(validation.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT[other]);
      expect(validation.candidate.prompt_text).not.toBe(DIRTY_LEGACY_PROMPT);
    }
  });

  it.each(AFFECTED_ROLES)(
    'quarantines %s legacy bytes even while another role is selected',
    (agentKey) => {
      let state = createDraftEditorState(workbench());
      const savedPrompt = state.byAgent[agentKey].saved.prompt_text;
      state = draftEditorReducer(state, {
        type: 'saveStarted',
        pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
      });
      state = draftEditorReducer(state, {
        type: 'saveConflicted', requestId: 1, conflict: saveConflictWithV2(0, 1, [agentKey]),
      });

      const entry = state.byAgent[agentKey];
      expect(entry.conflict).toBeNull();
      expect(entry.local.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
      expect(entry.retainedForms).toHaveLength(1);
      expect(entry.retainedForms[0].manualOnlyPrompt).toBe(savedPrompt);
      expect(state.byAgent.architect.retainedForms).toEqual([]);
    },
  );

  it('sanitizes a pre-existing alternative while preserving both distinct safe tuples', () => {
    let state = createDraftEditorState(workbench());
    const savedPrompt = state.byAgent.data_analyst.saved.prompt_text;

    // A pre-existing retained alternative with four distinct safe sentinels.
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'data_analyst', field: 'prompt_text', value: 'pre-existing alternative' });
    for (const [field, value] of Object.entries(SENTINEL_SAFE_FIELDS)) {
      state = draftEditorReducer(state, {
        type: 'edit', agentKey: 'data_analyst', field: field as 'endpoint_name', value,
      });
    }
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'data_analyst' });
    expect(state.byAgent.data_analyst.retainedForms).toHaveLength(1);
    expect(state.byAgent.data_analyst.local.endpoint_name)
      .toBe(state.byAgent.data_analyst.saved.model.endpoint_name);

    // Current local values carry a different safe tuple.
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'data_analyst', field: 'max_tokens', value: 9999 });
    state = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'data_analyst', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    state = draftEditorReducer(state, {
      type: 'saveConflicted', requestId: 1, conflict: saveConflictWithV2(0, 1, ['data_analyst']),
    });

    const entry = state.byAgent.data_analyst;
    expect(entry.retainedForms.map((item) => item.id)).toEqual([
      retainedFormId('data_analyst', 1), retainedFormId('data_analyst', 2),
    ]);
    // Both entries are sanitized to the v2 prompt and rules...
    for (const retained of entry.retainedForms) {
      expect(retained.form.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
      expect(retained.form.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      expect(retained.sanitizedFormatVersion).toBe(2);
    }
    // ...while each keeps its own distinct safe tuple and manual-only bytes.
    expect(entry.retainedForms[0].form).toMatchObject(SENTINEL_SAFE_FIELDS);
    expect(entry.retainedForms[0].manualOnlyPrompt).toBe('pre-existing alternative');
    expect(entry.retainedForms[1].form.max_tokens).toBe(9999);
    expect(entry.retainedForms[1].form.endpoint_name).toBe(entry.saved.model.endpoint_name);
    expect(entry.retainedForms[1].manualOnlyPrompt).toBe(savedPrompt);

    // Restoring each ID re-sanitizes the prompt and rules against the saved version.
    for (const [index, retained] of entry.retainedForms.entries()) {
      const restored = draftEditorReducer(state, {
        type: 'restoreRetained', agentKey: 'data_analyst', retainedId: retained.id,
      });
      const local = restored.byAgent.data_analyst.local;
      expect(local.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
      expect(local.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      if (index === 0) expect(local).toMatchObject(SENTINEL_SAFE_FIELDS);
      else expect(local.max_tokens).toBe(9999);

      const validation = validateDraftForm(local);
      expect(validation.ok).toBe(true);
      if (validation.ok) {
        expect(validation.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
        for (const bytes of entry.retainedForms.map((item) => item.manualOnlyPrompt)) {
          expect(validation.candidate.prompt_text).not.toBe(bytes);
        }
      }
    }
  });

  it('Reload server after adoption appends the current alternative beside the existing one', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'data_analyst', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    state = draftEditorReducer(state, {
      type: 'saveConflicted', requestId: 1, conflict: saveConflictWithV2(0, 1, ['data_analyst']),
    });
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'data_analyst', field: 'top_p', value: 0.42 });
    state = draftEditorReducer(state, { type: 'reloadServer', agentKey: 'data_analyst' });

    const entry = state.byAgent.data_analyst;
    expect(entry.retainedForms.map((item) => item.id)).toEqual([
      retainedFormId('data_analyst', 1), retainedFormId('data_analyst', 2),
    ]);
    expect(entry.retainedForms[1].form.top_p).toBe(0.42);
    expect(entry.retainedForms[1].manualOnlyPrompt).toBe(V2_AUTHORED_PROMPT.data_analyst);
    expect(entry.local).toEqual(formFromDefinition(entry.saved));
    expect(entry.local.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
  });

  it('never leaves a v1 prompt beside a v2 saved definition on any path', () => {
    const paths: Array<(state: DraftEditorState) => DraftEditorState> = [
      (state) => draftEditorReducer(state, { type: 'keepLocal', agentKey: 'data_analyst' }),
      (state) => draftEditorReducer(state, { type: 'reloadServer', agentKey: 'data_analyst' }),
      (state) => draftEditorReducer(state, {
        type: 'restoreRetained', agentKey: 'data_analyst', retainedId: retainedFormId('data_analyst', 1),
      }),
      (state) => draftEditorReducer(state, { type: 'restoreSavedPrompt', agentKey: 'data_analyst' }),
      (state) => draftEditorReducer(state, {
        type: 'discardRetained', agentKey: 'data_analyst', retainedId: retainedFormId('data_analyst', 1),
      }),
    ];
    let adopted = createDraftEditorState(workbench());
    const legacyPrompt = adopted.byAgent.data_analyst.saved.prompt_text;
    adopted = draftEditorReducer(adopted, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'data_analyst', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    adopted = draftEditorReducer(adopted, {
      type: 'saveConflicted', requestId: 1, conflict: saveConflictWithV2(0, 1, ['data_analyst']),
    });

    for (const path of paths) {
      const next = path(adopted);
      const entry = next.byAgent.data_analyst;
      expect(entry.saved.assembly_rules.format_version).toBe(2);
      expect(entry.local.prompt_text).not.toBe(legacyPrompt);
      expect(entry.local.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      for (const retained of entry.retainedForms) {
        expect(retained.form.prompt_text).not.toBe(legacyPrompt);
        expect(retained.sanitizedFormatVersion).toBe(2);
      }
    }
  });

  it('reconciles a concurrent upgrade winner to v2 instead of surfacing already_current', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending('data_analyst') });
    state = draftEditorReducer(state, {
      type: 'upgradeConflicted',
      requestId: 1,
      conflict: syntheticNullCandidateConflict(0, 1, ['data_analyst']),
    });

    expect(state.byAgent.data_analyst.saved.assembly_rules.format_version).toBe(2);
    expect(state.byAgent.data_analyst.responseIssues).toEqual([]);
    expect(state.byAgent.data_analyst.conflict?.client_candidate).toBeNull();
    expect(state.draft.lock_version).toBe(1);
  });

  it('merges every one of the seven definitions from a null-candidate conflict', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending('build_reviewer') });
    const body = syntheticNullCandidateConflict(0, 1, [...AFFECTED_ROLES]);
    state = draftEditorReducer(state, { type: 'upgradeConflicted', requestId: 1, conflict: body });

    for (const agentKey of AGENT_KEYS) {
      expect(state.byAgent[agentKey].saved).toEqual(body.server.definitions[agentKey]);
    }
    expect(state.byAgent.architect.saved.assembly_rules.format_version).toBe(1);
    expect(state.byAgent.data_analyst.retainedForms).toHaveLength(1);
    expect(state.byAgent.build_reviewer.retainedForms).toHaveLength(1);
    expect(state.byAgent.architect.retainedForms).toEqual([]);
  });
});

// ============================================================
// #265 fix round 1 — a dirty prompt is reachable *after* an Upgrade starts
// ============================================================

/**
 * The exact four-step sequence a UI reaches: the dirty attempt is refused and retained,
 * the prompt is restored so the Upgrade may start, and then the retained alternative is
 * restored while the request is still in flight. Only `restoreRetained` can do this, so
 * it needs the same backstop as `edit`.
 */
function pendingUpgradeWithDirtyRestoreAttempt(agentKey: 'data_analyst' | 'build_reviewer') {
  let state = createDraftEditorState(workbench());
  const savedPrompt = state.byAgent[agentKey].saved.prompt_text;
  state = draftEditorReducer(state, { type: 'edit', agentKey, field: 'top_p', value: 0.66 });
  state = draftEditorReducer(state, {
    type: 'edit', agentKey, field: 'prompt_text', value: DIRTY_LEGACY_PROMPT,
  });
  // Step 1: the dirty Upgrade attempt is refused and the bytes are retained.
  state = draftEditorReducer(state, { type: 'dirtyLegacyPromptRetained', agentKey });
  // Step 2: local restore makes the prompt clean again.
  state = draftEditorReducer(state, { type: 'restoreSavedPrompt', agentKey });
  expect(state.byAgent[agentKey].local.prompt_text).toBe(savedPrompt);
  // Step 3: the Upgrade may now start, and does.
  state = draftEditorReducer(state, { type: 'upgradeStarted', pending: upgradePending(agentKey) });
  expect(state.pendingSave).toEqual(upgradePending(agentKey));
  return { state, savedPrompt, retainedId: retainedFormId(agentKey, 1) };
}

describe('prompt-change backstop during a pending Upgrade', () => {
  it.each(AFFECTED_ROLES)(
    'a restored alternative cannot dirty the %s prompt while its Upgrade is in flight',
    (agentKey) => {
      const { state, savedPrompt, retainedId } = pendingUpgradeWithDirtyRestoreAttempt(agentKey);

      // Step 4: restore the retained alternative mid-flight.
      const next = draftEditorReducer(state, { type: 'restoreRetained', agentKey, retainedId });

      // The savable prompt stays at the authoritative v1 value, exactly as the
      // backstop requires for *any* prompt-change action during the request.
      expect(next.byAgent[agentKey].local.prompt_text).toBe(savedPrompt);
      expect(next.byAgent[agentKey].local.prompt_text).not.toBe(DIRTY_LEGACY_PROMPT);
      // The alternative's safe fields are still restored...
      expect(next.byAgent[agentKey].local.top_p).toBe(0.66);
      // ...and the refused prompt is appended as manual-only bytes, not dropped.
      expect(next.byAgent[agentKey].retainedForms.map((item) => item.id)).toEqual([
        retainedFormId(agentKey, 1), retainedFormId(agentKey, 2),
      ]);
      expect(next.byAgent[agentKey].retainedForms[1].source).toBe('pending_prompt_quarantine');
      expect(next.byAgent[agentKey].retainedForms[1].manualOnlyPrompt).toBe(DIRTY_LEGACY_PROMPT);
      expect(next.byAgent[agentKey].retainedForms[1].form.prompt_text).toBe(savedPrompt);
      expect(next.byAgent[agentKey].retainedForms[1].form.top_p).toBe(0.66);
      // The pending operation is untouched: restoring issues nothing.
      expect(next.pendingSave).toEqual(state.pendingSave);

      // The same restore with nothing pending is a plain restore, so the guard is
      // scoped to the in-flight window and does not disable ordinary recovery.
      const settled = draftEditorReducer(state, {
        type: 'upgradeFailed', requestId: 1, message: 'Upgrade failed.',
      });
      const restored = draftEditorReducer(settled, { type: 'restoreRetained', agentKey, retainedId });
      expect(restored.byAgent[agentKey].local.prompt_text).toBe(DIRTY_LEGACY_PROMPT);
      expect(restored.byAgent[agentKey].retainedForms).toHaveLength(1);
    },
  );

  it.each(AFFECTED_ROLES)(
    'discarding an alternative mid-flight moves no %s prompt byte',
    (agentKey) => {
      const { state, savedPrompt, retainedId } = pendingUpgradeWithDirtyRestoreAttempt(agentKey);

      const next = draftEditorReducer(state, { type: 'discardRetained', agentKey, retainedId });

      // Discard never writes to `local`, which is why it needs no pending guard.
      expect(next.byAgent[agentKey].local).toEqual(state.byAgent[agentKey].local);
      expect(next.byAgent[agentKey].local.prompt_text).toBe(savedPrompt);
      expect(next.byAgent[agentKey].retainedForms).toEqual([]);
      expect(next.pendingSave).toEqual(state.pendingSave);
    },
  );

  it.each(AFFECTED_ROLES)(
    'an Upgrade 409 adopts v2 for %s after the prompt was made dirty mid-flight',
    (agentKey) => {
      const { state, savedPrompt, retainedId } = pendingUpgradeWithDirtyRestoreAttempt(agentKey);
      const dirtied = draftEditorReducer(state, { type: 'restoreRetained', agentKey, retainedId });

      const next = draftEditorReducer(dirtied, {
        type: 'upgradeConflicted',
        requestId: 1,
        conflict: syntheticNullCandidateConflict(0, 1, [agentKey]),
      });

      const entry = next.byAgent[agentKey];
      expect(entry.saved.assembly_rules.format_version).toBe(2);
      expect(entry.local.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
      expect(entry.local.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      expect(entry.local.top_p).toBe(0.66);

      // Three alternatives: the refused dirty attempt, the mid-flight quarantine, and
      // the displaced local form. Every one is sanitized to v2; every byte is kept.
      expect(entry.retainedForms.map((item) => item.id)).toEqual([
        retainedFormId(agentKey, 1), retainedFormId(agentKey, 2), retainedFormId(agentKey, 3),
      ]);
      expect(entry.retainedForms.map((item) => item.manualOnlyPrompt))
        .toEqual([DIRTY_LEGACY_PROMPT, DIRTY_LEGACY_PROMPT, savedPrompt]);
      for (const retained of entry.retainedForms) {
        expect(retained.sanitizedFormatVersion).toBe(2);
        expect(retained.form.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
        expect(retained.form.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
      }

      // The immediate PUT carries the authored-only v2 prompt and no retained byte.
      const validation = validateDraftForm(entry.local);
      expect(validation.ok).toBe(true);
      if (validation.ok) {
        expect(validation.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT[agentKey]);
        expect(validation.candidate.prompt_text).not.toBe(DIRTY_LEGACY_PROMPT);
        expect(validation.candidate.prompt_text).not.toBe(savedPrompt);
      }
    },
  );

  it('re-sanitizes a retained record whose format version is stale on restore', () => {
    // Built directly against the reducer's declared contract. `adoptAuthoritativeDefinition`
    // sanitizes eagerly, so no legal action sequence leaves a stale record behind — this
    // pins the mandated restore-time re-application as defence in depth.
    const base = createDraftEditorState(workbench());
    const v2Saved = v2Definition('data_analyst');
    const staleRecord = {
      id: retainedFormId('data_analyst', 1),
      source: 'version_adoption' as const,
      reason: RETAINED_REASONS.version_adoption,
      form: {
        ...formFromDefinition(base.byAgent.data_analyst.saved),
        top_p: 0.44,
      },
      manualOnlyPrompt: DIRTY_LEGACY_PROMPT,
      // Deliberately stale: the form was sanitized against v1 while `saved` is v2.
      sanitizedFormatVersion: 1 as const,
    };
    const stale: DraftEditorState = {
      ...base,
      byAgent: {
        ...base.byAgent,
        data_analyst: {
          ...base.byAgent.data_analyst,
          saved: v2Saved,
          local: formFromDefinition(v2Saved),
          retainedForms: [staleRecord],
          nextRetainedOrdinal: 2,
        },
      },
    };
    const legacyPrompt = staleRecord.form.prompt_text;
    expect(legacyPrompt).not.toBe(V2_AUTHORED_PROMPT.data_analyst);

    const next = draftEditorReducer(stale, {
      type: 'restoreRetained', agentKey: 'data_analyst', retainedId: staleRecord.id,
    });

    // The stale v1 prompt and absent rules are replaced by the authoritative v2 values...
    expect(next.byAgent.data_analyst.local.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
    expect(next.byAgent.data_analyst.local.prompt_text).not.toBe(legacyPrompt);
    expect(next.byAgent.data_analyst.local.assembly_rules)
      .toEqual({ format_version: 2, custom_blocks: [] });
    // ...while the record's safe field is still restored and its bytes are untouched.
    expect(next.byAgent.data_analyst.local.top_p).toBe(0.44);
    expect(next.byAgent.data_analyst.retainedForms[0].manualOnlyPrompt).toBe(DIRTY_LEGACY_PROMPT);
  });
});


// ============================================================
// #264 Task 6 fix round 1 — Schema Upgrade and overlay pins (review I2, I3, I4)
// ============================================================

function schemaUpgradePending(
  agentKey: AgentKey = 'architect',
  requestId = 1,
  expectedLockVersion = 0,
): PendingDraftSave {
  return { operation: 'schemaUpgrade', requestId, agentKey, expectedLockVersion, submittedCandidate: null };
}

describe('Schema Upgrade completion', () => {
  it('keeps prompt, model and overlay edits made while the Schema Upgrade was pending (A2 to A3)', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A2' });
    state = draftEditorReducer(state, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending() });
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'prompt_text', value: 'Architect A3' });
    state = draftEditorReducer(state, { type: 'edit', agentKey: 'architect', field: 'top_p', value: 0.42 });
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged',
      agentKey: 'architect',
      fieldName: 'intent',
      description: 'A3 intent guidance',
    });

    const next = draftEditorReducer(state, {
      type: 'schemaUpgradeSucceeded',
      requestId: 1,
      result: syntheticSchemaUpgradeSuccess('architect', 1),
    });

    expect(next.pendingSave).toBeNull();
    expect(next.draft.lock_version).toBe(1);
    expect(next.byAgent.architect.saved.schema_contract.version).toBe(2);
    expect(next.byAgent.architect.local.prompt_text).toBe('Architect A3');
    expect(next.byAgent.architect.local.top_p).toBe(0.42);
    expect(next.byAgent.architect.local.schema_overlay?.field_overrides.intent?.description)
      .toBe('A3 intent guidance');
    expect(draftStatus(next.byAgent.architect)).toBe('Unsaved');
  });

  it('ignores a Schema Upgrade completion whose request ID is not the pending one', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending('architect', 2) });
    const stale: DraftEditorState[] = [
      draftEditorReducer(state, { type: 'schemaUpgradeSucceeded', requestId: 1, result: syntheticSchemaUpgradeSuccess('architect', 1) }),
      draftEditorReducer(state, { type: 'schemaUpgradeRejected', requestId: 1, error: SCHEMA_ALREADY_CURRENT_REJECTION }),
      draftEditorReducer(state, { type: 'schemaUpgradeConflicted', requestId: 1, conflict: syntheticNullCandidateConflict(0, 1) }),
      draftEditorReducer(state, { type: 'schemaUpgradeFailed', requestId: 1, message: 'late failure' }),
    ];
    for (const next of stale) expect(next).toBe(state);
    expect(state.pendingSave?.requestId).toBe(2);
  });

  it('never lets one operation complete another operation with the same request ID', () => {
    let saving = createDraftEditorState(workbench());
    saving = draftEditorReducer(saving, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'architect', expectedLockVersion: 0, submittedCandidate: request().candidate },
    });
    expect(draftEditorReducer(saving, {
      type: 'schemaUpgradeSucceeded', requestId: 1, result: syntheticSchemaUpgradeSuccess('architect', 1),
    })).toBe(saving);

    let upgrading = createDraftEditorState(workbench());
    upgrading = draftEditorReducer(upgrading, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending('architect', 1) });
    expect(draftEditorReducer(upgrading, {
      type: 'saveSucceeded', requestId: 1, result: success('architect', 'A2', 1),
    })).toBe(upgrading);
    expect(draftEditorReducer(upgrading, {
      type: 'upgradeSucceeded', requestId: 1, result: syntheticUpgradeSuccess('architect', 1),
    })).toBe(upgrading);
  });

  it('ignores a late Schema Upgrade response after a newer request has started (monotonic IDs)', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending('architect', 1) });
    state = draftEditorReducer(state, { type: 'schemaUpgradeSucceeded', requestId: 1, result: syntheticSchemaUpgradeSuccess('architect', 1) });
    state = draftEditorReducer(state, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending('builder', 2, 1) });
    const late = draftEditorReducer(state, {
      type: 'schemaUpgradeSucceeded', requestId: 1, result: syntheticSchemaUpgradeSuccess('builder', 2),
    });
    expect(late).toBe(state);
    expect(late.byAgent.builder.saved.schema_contract.version).toBe(1);
    expect(late.pendingSave?.requestId).toBe(2);
  });

  it('merges every one of the seven definitions from a Schema Upgrade 409 and keeps an overlay-only-dirty role', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged',
      agentKey: 'builder',
      fieldName: 'html',
      description: 'Builder local guidance',
    });
    state = draftEditorReducer(state, { type: 'schemaUpgradeStarted', pending: schemaUpgradePending('architect') });
    const body = syntheticNullCandidateConflict(0, 1);
    body.server.definitions.architect = syntheticSchemaV2DraftDefinition('architect');
    body.server.definitions.fixer = syntheticSchemaV2DraftDefinition('fixer');
    body.server.definitions.builder = {
      ...body.server.definitions.builder,
      prompt_text: 'Builder server B1',
      candidate_hash: '7'.repeat(64),
    };
    // The Schema Upgrade 409 is the null-candidate contract, and this body is valid for it.
    expect(parseDraftSaveConflictResponse(body, 'null')).toEqual(body);

    state = draftEditorReducer(state, { type: 'schemaUpgradeConflicted', requestId: 1, conflict: body });

    expect(state.pendingSave).toBeNull();
    expect(state.draft).toEqual(body.server.draft);
    for (const agentKey of AGENT_KEYS) {
      expect(state.byAgent[agentKey].saved).toEqual(body.server.definitions[agentKey]);
    }
    expect(state.byAgent.architect.conflict).toEqual(body);
    // A clean unselected role adopts the server baseline.
    expect(state.byAgent.fixer.local).toEqual(formFromDefinition(body.server.definitions.fixer));
    // An unselected role whose only local edit is overlay guidance is dirty, so it keeps it.
    expect(state.byAgent.builder.local.schema_overlay?.field_overrides.html?.description)
      .toBe('Builder local guidance');
    expect(draftStatus(state.byAgent.builder)).toBe('Unsaved');
  });
});

describe('schema overlay local edits', () => {
  it('an overlay-only edit makes the role Unsaved', () => {
    let state = createDraftEditorState(workbench());
    expect(draftStatus(state.byAgent.builder)).toBe('Clean');
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged', agentKey: 'builder', fieldName: 'html', description: 'guidance',
    });
    expect(draftStatus(state.byAgent.builder)).toBe('Unsaved');
  });

  it('keeps an overlay edit made after a Save request was sent (A2 to A3)', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged', agentKey: 'builder', fieldName: 'html', description: 'A2 guidance',
    });
    const validation = validateDraftForm(state.byAgent.builder.local);
    if (!validation.ok) throw new Error('expected a valid candidate');
    state = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: { operation: 'save', requestId: 1, agentKey: 'builder', expectedLockVersion: 0, submittedCandidate: validation.candidate },
    });
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged', agentKey: 'builder', fieldName: 'html', description: 'A3 guidance',
    });
    const saved: DraftDefinition = {
      ...definition('builder'),
      schema_overlay: structuredClone(validation.candidate.schema_overlay) as DraftDefinition['schema_overlay'],
      candidate_hash: '1'.repeat(64),
    };

    const next = draftEditorReducer(state, {
      type: 'saveSucceeded', requestId: 1, result: { draft: metadata(1), definition: saved, changed: true },
    });

    expect(next.byAgent.builder.saved.schema_overlay.field_overrides).toEqual({ html: { description: 'A2 guidance' } });
    expect(next.byAgent.builder.local.schema_overlay?.field_overrides.html?.description).toBe('A3 guidance');
  });

  it('refuses to build a candidate from malformed examples instead of silently dropping them', () => {
    const base = formFromDefinition(definition('builder'));
    for (const examples of ['["unterminated"', '"not an array"', '{"a": 1}', 'build']) {
      const result = validateDraftForm({
        ...base,
        schema_overlay: {
          additional_optional_fields: [],
          field_overrides: { html: { description: 'Saved guidance', examples } },
        },
      });
      expect(result.ok, examples).toBe(false);
      if (!result.ok) {
        expect(result.errors).toEqual({
          'schema_overlay.field_overrides.html.examples': 'Examples must be a JSON array.',
        });
      }
    }

    const valid = validateDraftForm({
      ...base,
      schema_overlay: {
        additional_optional_fields: [],
        field_overrides: { html: { description: 'Saved guidance', examples: '["<section>"]' } },
      },
    });
    expect(valid.ok).toBe(true);
    if (valid.ok) {
      expect(valid.candidate.schema_overlay?.field_overrides).toEqual({
        html: { description: 'Saved guidance', examples: ['<section>'] },
      });
    }
  });

  it('clears a field\'s examples error when that field\'s examples change', () => {
    let state = createDraftEditorState(workbench());
    state = draftEditorReducer(state, {
      type: 'saveInvalid',
      agentKey: 'builder',
      errors: {
        prompt_text: 'Prompt text must not be blank.',
        'schema_overlay.field_overrides.html.examples': 'Examples must be a JSON array.',
      },
    });
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldExamplesChanged', agentKey: 'builder', fieldName: 'html', examples: '["ok"]',
    });
    expect(state.byAgent.builder.fieldErrors['schema_overlay.field_overrides.html.examples']).toBeUndefined();
    expect(state.byAgent.builder.fieldErrors.prompt_text).toBe('Prompt text must not be blank.');
  });
});

describe('schema-contract-upgrade transport', () => {
  it('sends exactly the lock body and parses each contract status, including the null-candidate 409', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, syntheticSchemaUpgradeSuccess('architect', 1)));
    vi.stubGlobal('fetch', fetchMock);

    await expect(upgradeDraftSchemaContract('architect', { lock_version: 0 }))
      .resolves.toEqual(syntheticSchemaUpgradeSuccess('architect', 1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/architect\/schema-contract-upgrade$/);
    expect(init).toEqual({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"lock_version":0}',
    });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(422, SCHEMA_ALREADY_CURRENT_REJECTION, 'Unprocessable Entity')));
    const rejected = await upgradeDraftSchemaContract('architect', { lock_version: 0 }).catch((error: unknown) => error);
    expect(rejected).toBeInstanceOf(AgentDefinitionApiError);
    expect((rejected as AgentDefinitionApiError).status).toBe(422);
    expect((rejected as AgentDefinitionApiError).payload).toEqual(SCHEMA_ALREADY_CURRENT_REJECTION);

    const nullConflict = syntheticNullCandidateConflict(0, 1);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(409, nullConflict, 'Conflict')));
    const conflicted = await upgradeDraftSchemaContract('architect', { lock_version: 0 }).catch((error: unknown) => error);
    expect(conflicted).toBeInstanceOf(AgentDefinitionApiError);
    expect((conflicted as AgentDefinitionApiError).status).toBe(409);
    expect((conflicted as AgentDefinitionApiError).payload).toEqual(nullConflict);

    // A Schema Upgrade 409 that echoes a candidate is not this route's contract.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(409, conflict(0, 1), 'Conflict')));
    await expect(upgradeDraftSchemaContract('architect', { lock_version: 0 }))
      .rejects.toBeInstanceOf(InvalidDraftSaveResponseError);
  });
});

describe('strict schema overlay parsing', () => {
  it('accepts each of the seven roles\' own descriptor and rejects every malformed descriptor', () => {
    for (const agentKey of AGENT_KEYS) {
      const body = syntheticSchemaUpgradeSuccess(agentKey, 1);
      expect(body.definition.selectable_optional_fields).toEqual([DIAGNOSTIC_NOTES_DESCRIPTORS[agentKey]]);
      expect(parseDraftSaveSuccessResponse(body), agentKey).toEqual(body);
    }
    const base = syntheticSchemaUpgradeSuccess('architect', 1);
    const good = DIAGNOSTIC_NOTES_DESCRIPTORS.architect;
    const rejected: unknown[] = [
      setAtPath(good, 'name', 1),
      setAtPath(good, 'description', null),
      setAtPath(good, 'examples', 'x'),
      setAtPath(good, 'extra', true),
      setAtPath(good, 'schema', null, true),
      setAtPath(good, 'schema.default', []),
      setAtPath(good, 'schema.max_items', 0),
      setAtPath(good, 'schema.type', 'array'),
      setAtPath(good, 'schema.extra', true),
      setAtPath(good, 'schema.items.extra', true),
      setAtPath(good, 'schema.items.min_length', -1),
      setAtPath(good, 'schema.items.strip_whitespace', 'yes'),
      null,
      'diagnostic_notes',
    ];
    for (const invalid of rejected) {
      expect(
        parseDraftSaveSuccessResponse(setAtPath(base, 'definition.selectable_optional_fields', [invalid])),
        JSON.stringify(invalid),
      ).toBeNull();
    }
  });

  it('accepts every role\'s canonical fields and rejects every malformed canonical-field descriptor', () => {
    for (const agentKey of AGENT_KEYS) {
      const body = syntheticSchemaUpgradeSuccess(agentKey, 1);
      expect(body.definition.canonical_fields).toEqual(CANONICAL_FIELD_DESCRIPTORS[agentKey]);
      expect(parseDraftSaveSuccessResponse(body), agentKey).toEqual(body);
    }
    const base = syntheticSchemaUpgradeSuccess('architect', 1);
    const [intent, , deckSpec] = CANONICAL_FIELD_DESCRIPTORS.architect;
    expect(intent.required).toBe(true);
    expect(deckSpec.required).toBe(false);
    const rejected: unknown[] = [
      setAtPath(intent, 'default', null),
      setAtPath(deckSpec, 'default', null, true),
      setAtPath(intent, 'required', 'true'),
      setAtPath(intent, 'name', ''),
      setAtPath(intent, 'name', 1),
      setAtPath(intent, 'type', 1),
      setAtPath(intent, 'type', ''),
      setAtPath(intent, 'enum', []),
      setAtPath(intent, 'enum', [1]),
      setAtPath(intent, 'enum', 'build'),
      setAtPath(intent, 'enum', null, true),
      setAtPath(intent, 'extra', true),
      null,
      'intent',
    ];
    for (const invalid of rejected) {
      expect(
        parseDraftSaveSuccessResponse(setAtPath(base, 'definition.canonical_fields', [invalid])),
        JSON.stringify(invalid),
      ).toBeNull();
    }
    expect(parseDraftSaveSuccessResponse(setAtPath(base, 'definition.canonical_fields', [intent, intent])))
      .toBeNull();
    expect(parseDraftSaveSuccessResponse(setAtPath(base, 'definition.canonical_fields', null, true)))
      .toBeNull();
  });

  it('accepts exactly the four candidate shapes, including schema_overlay, in a conflict echo', () => {
    const ordinary = conflict(0, 1);
    const model = structuredClone(definition('architect').model);
    const overlay = { field_overrides: { intent: { description: 'd' } }, additional_optional_fields: ['diagnostic_notes'] };
    const accepted: unknown[] = [
      { prompt_text: 'p', model, schema_overlay: null },
      { prompt_text: 'p', model, schema_overlay: overlay },
      { prompt_text: 'p', model, assembly_rules: null, schema_overlay: null },
      { prompt_text: 'p', model, assembly_rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES), schema_overlay: overlay },
    ];
    for (const candidate of accepted) {
      expect(
        parseDraftSaveConflictResponse(setAtPath(ordinary, 'client_candidate', candidate)),
        JSON.stringify(candidate),
      ).not.toBeNull();
    }
    const rejected: unknown[] = [
      { prompt_text: 'p', model, schema_overlay: {} },
      { prompt_text: 'p', model, schema_overlay: 'overlay' },
      { prompt_text: 'p', model, schema_overlay: { field_overrides: [], additional_optional_fields: [] } },
      { prompt_text: 'p', model, schema_overlay: { field_overrides: {}, additional_optional_fields: [1] } },
      { prompt_text: 'p', model, schema_overlay: { ...overlay, extra: true } },
      { prompt_text: 'p', model, schema_overlay: null, extra: true },
    ];
    for (const candidate of rejected) {
      expect(
        parseDraftSaveConflictResponse(setAtPath(ordinary, 'client_candidate', candidate)),
        JSON.stringify(candidate),
      ).toBeNull();
    }
  });
});
