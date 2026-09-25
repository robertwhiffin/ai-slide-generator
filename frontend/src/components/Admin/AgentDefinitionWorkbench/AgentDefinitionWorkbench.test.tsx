import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ALREADY_CURRENT_REJECTION,
  DIRTY_LEGACY_PROMPT,
  MANUAL_RESOLUTION_REJECTION,
  PUBLISHED_V1_PROMPT_SOURCE,
  V2_AUTHORED_PROMPT,
  syntheticAgentDefinitionWorkbench,
  syntheticDraftDefinitions,
  syntheticLegacyPromptSource,
  syntheticNullCandidateConflict,
  syntheticUpgradeSuccess,
  syntheticV2DraftDefinition,
} from '../../../../tests/fixtures/mocks';
import {
  ALLOWED_ACTION_NAMES,
  forbidsActionName,
} from '../../../../tests/fixtures/forbiddenActionNames';
import type {
  AgentKey,
  AssemblyRulesV2,
  DraftSaveConflictResponse,
  DraftSaveRequest,
  DraftSaveSuccessResponse,
  EditableModelDraft,
} from '../../../api/agentDefinitions';
import { AdminPage } from '../AdminPage';
import { AgentDefinitionWorkbench } from './AgentDefinitionWorkbench';
import { LEGACY_COMPOSITE_ROLES } from './draftEditorState';
import { useDraftEditor } from './useDraftEditor';

vi.mock('../UsageDashboard', () => ({ UsageDashboard: () => <div>Usage panel fixture</div> }));
vi.mock('../../Feedback/FeedbackDashboard', () => ({ FeedbackDashboard: () => <div>Feedback panel fixture</div> }));
vi.mock('../../config/GoogleSlidesAuthForm', () => ({ GoogleSlidesAuthForm: () => <div>Google Slides fixture</div> }));
vi.mock('../AdminDesignSystemDefault', () => ({ AdminDesignSystemDefault: () => <div>Design System fixture</div> }));
vi.mock('../AdminJudgeSettings', () => ({ AdminJudgeSettings: () => <div>Judge fixture</div> }));
vi.mock('../AdminSlideStyleDefault', () => ({ AdminSlideStyleDefault: () => <div>Slide Style fixture</div> }));

const NODE_ORDER = [
  'Architect',
  'Data Analyst',
  'Builder',
  'Build Reviewer',
  'Foreman',
  'Fixer',
  'Fix Reviewer',
  'Deck Reviewer',
];

/**
 * The affected-role matrix for this file, owned here rather than hand-typed at each
 * `it.each`. Two matrices carried their own copy of the pair and a third hand-typed the
 * display-name-to-key mapping, so narrowing any of them dropped the Build Reviewer half
 * with an all-green report. The agreement test below makes narrowing this RED, and the
 * server's canonical transition list is joined to `LEGACY_COMPOSITE_ROLES` by
 * `test_every_affected_role_copy_matches_the_canonical_transition_list`.
 */
const AFFECTED_ROLES = [
  ['Data Analyst', 'data_analyst'],
  ['Build Reviewer', 'build_reviewer'],
] as const;
const AFFECTED_ROLE_KEYS = AFFECTED_ROLES.map(([, agentKey]) => agentKey);

function interactiveControls() {
  return [...screen.queryAllByRole('button'), ...screen.queryAllByRole('link')];
}

function expectNoForbiddenActionNames() {
  // `name` as a predicate hands the sweep each control's *computed* accessible name, so
  // aria-labelledby, `title` and `alt` resolve exactly as a screen reader resolves them,
  // and the shared rule decides. Collecting the offenders reports the names rather than
  // DOM nodes, which is what a failure needs to be actionable.
  const offenders: string[] = [];
  const collect = (accessibleName: string) => {
    if (!forbidsActionName(accessibleName)) return false;
    offenders.push(accessibleName);
    return true;
  };
  screen.queryAllByRole('button', { name: collect });
  screen.queryAllByRole('link', { name: collect });
  expect(offenders).toEqual([]);
  // Not vacuous: the sweep must have had at least one control to walk.
  expect(interactiveControls().length).toBeGreaterThan(0);
}

function mockFetchResponse(status: number, body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 403 ? 'Forbidden' : status === 500 ? 'Internal Server Error' : 'OK',
    json: vi.fn().mockResolvedValue(body),
  }));
}

function apiResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 409 ? 'Conflict' : status === 422 ? 'Unprocessable Entity' : 'OK',
    json: vi.fn().mockResolvedValue(body),
  };
}

function modelNode(agentKey: AgentKey) {
  const node = syntheticAgentDefinitionWorkbench.nodes.find((candidate) => candidate.agent_key === agentKey);
  if (!node || node.execution_kind !== 'model') throw new Error(`missing ${agentKey}`);
  return node;
}

function saveSuccess(
  agentKey: AgentKey,
  candidate: EditableModelDraft,
  lockVersion: number,
  changed = true,
): DraftSaveSuccessResponse {
  const base = modelNode(agentKey).draft;
  return {
    draft: {
      ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
      lock_version: lockVersion,
      updated_by: 'admin@example.com',
      updated_at: `2026-09-22T12:00:0${lockVersion}Z`,
    },
    definition: {
      ...structuredClone(base),
      prompt_text: candidate.prompt_text,
      model: structuredClone(candidate.model),
      candidate_hash: 'd'.repeat(64),
    },
    changed,
  };
}

function saveConflict(
  request: DraftSaveRequest,
  currentLockVersion = 1,
): DraftSaveConflictResponse {
  return {
    code: 'stale_draft',
    expected_lock_version: request.lock_version,
    current_lock_version: currentLockVersion,
    client_candidate: structuredClone(request.candidate),
    server: {
      draft: {
        ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
        lock_version: currentLockVersion,
      },
      definitions: Object.fromEntries(
        syntheticAgentDefinitionWorkbench.nodes
          .filter((node) => node.execution_kind === 'model')
          .map((node) => [node.agent_key, structuredClone(node.draft)]),
      ) as unknown as DraftSaveConflictResponse['server']['definitions'],
    },
  };
}

function conflictWithServerEdits(
  request: DraftSaveRequest,
  edits: Partial<Record<AgentKey, string>>,
): DraftSaveConflictResponse {
  const conflict = saveConflict(request);
  for (const [agentKey, promptText] of Object.entries(edits) as Array<[AgentKey, string]>) {
    conflict.server.definitions[agentKey] = {
      ...conflict.server.definitions[agentKey],
      prompt_text: promptText,
      candidate_hash: 'd'.repeat(64),
    };
  }
  return conflict;
}

function mockWorkbenchWithPuts(
  put: (agentKey: AgentKey, request: DraftSaveRequest, call: number) => Promise<object> | object,
) {
  let putCall = 0;
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === 'GET') return apiResponse(200, syntheticAgentDefinitionWorkbench);
    const agentKey = url.split('/').at(-1) as AgentKey;
    const request = JSON.parse(String(init?.body)) as DraftSaveRequest;
    const result = await put(agentKey, request, putCall++);
    return result;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function putCalls(fetchMock = vi.mocked(fetch)) {
  return fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT');
}

async function editArchitectFiveFields(assertNoPut?: () => void) {
  const prompt = await screen.findByRole('textbox', { name: 'Prompt text' });
  fireEvent.change(prompt, { target: { value: 'Architect A2' } });
  assertNoPut?.();
  fireEvent.blur(prompt);
  assertNoPut?.();
  fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
  assertNoPut?.();
  fireEvent.change(screen.getByRole('textbox', { name: 'Endpoint' }), { target: { value: 'endpoint-a2' } });
  assertNoPut?.();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '0.4' } });
  assertNoPut?.();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Maximum tokens' }), { target: { value: '8192' } });
  assertNoPut?.();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Top-p' }), { target: { value: '0.8' } });
  assertNoPut?.();
}

function renderSuccessfulWorkbench() {
  mockFetchResponse(200, syntheticAgentDefinitionWorkbench);
  return render(<AgentDefinitionWorkbench />);
}

async function loadedNodeNavigation() {
  return screen.findByRole('navigation', { name: 'Graph nodes' });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('the forbidden-action guard', () => {
  it('fires on every banned name, including the four a word-bounded publish stem spared', () => {
    for (const forbidden of [
      'Run isolated test', 'Approve draft', 'Reject draft', 'Review & publish',
      'Publish draft', 'Publishes the release', 'Publishing', 'Release history',
      'Rollback release',
      // Regression guard: all four of these were missed while the stem was word-bounded.
      'Republish release', 'Unpublish draft', 'Publisher settings', 'Published versions',
    ]) {
      expect(forbidsActionName(forbidden)).toBe(true);
    }
  });

  it('spares the panel\'s legitimate restore controls without spared names shielding a stem', () => {
    for (const allowed of ALLOWED_ACTION_NAMES) expect(forbidsActionName(allowed)).toBe(false);
    expect(ALLOWED_ACTION_NAMES).toHaveLength(3);
    // An exempt name is removed, not treated as a licence for the rest of the string.
    expect(forbidsActionName('Restore saved prompt and publish')).toBe(true);
    expect(forbidsActionName('Restore retained values, then approve')).toBe(true);
  });

  it('spares every other name the panel actually renders', () => {
    for (const name of [
      'Save Draft', 'Keep local', 'Reload server', 'Upgrade protected assembly',
      'Add custom block After authored prompt', 'Add custom block After deck brief',
      'Add custom block After environment constraints', 'Go to Assembly tab',
      'Go to Prompt tab', 'Delete custom block 1 at After authored prompt',
      'Move custom block 1 up', 'Move custom block 1 down', 'Discard retained values',
      ...NODE_ORDER,
    ]) {
      expect(forbidsActionName(name)).toBe(false);
    }
  });
});

describe('the affected-role Vitest matrix', () => {
  it('cannot silently narrow', () => {
    expect([...AFFECTED_ROLE_KEYS]).toEqual([...LEGACY_COMPOSITE_ROLES]);
    expect(AFFECTED_ROLES).toHaveLength(2);
    expect(new Set(AFFECTED_ROLE_KEYS).size).toBe(AFFECTED_ROLE_KEYS.length);
    for (const [displayName, agentKey] of AFFECTED_ROLES) {
      // The display name each matrix clicks must be the one the panel renders for that
      // key, or a narrowed or mistyped pair would select the wrong role and still pass.
      expect(NODE_ORDER).toContain(displayName);
      expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).toBeTruthy();
      expect(V2_AUTHORED_PROMPT[agentKey]).toBeTruthy();
      expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).not.toEqual(V2_AUTHORED_PROMPT[agentKey]);
    }
  });
});

describe('AgentDefinitionWorkbench', () => {
  it('shows a contained loading status until the workbench request resolves', async () => {
    let resolveResponse!: (response: object) => void;
    const response = new Promise<object>((resolve) => { resolveResponse = resolve; });
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(response));

    render(<AgentDefinitionWorkbench />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading Agent Definitions');

    resolveResponse({ ok: true, status: 200, statusText: 'OK', json: async () => syntheticAgentDefinitionWorkbench });
    await loadedNodeNavigation();
  });

  it('renders the exact eight graph nodes as navigation buttons in wire order', async () => {
    renderSuccessfulWorkbench();
    const navigation = await loadedNodeNavigation();

    expect(within(navigation).getAllByRole('button').map((button) => button.getAttribute('aria-label')))
      .toEqual(NODE_ORDER);
    expect(screen.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
    expect(screen.getByText('Draft base').parentElement).toHaveTextContent('Draft baseGraph Version 1');
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
  });

  it('defaults deterministically to Prompt and supports keyboard and click tab selection', async () => {
    renderSuccessfulWorkbench();
    await loadedNodeNavigation();
    const tabs = within(screen.getByRole('tablist', { name: 'Architect definition' }));
    const promptTab = tabs.getByRole('tab', { name: 'Prompt' });
    const modelTab = tabs.getByRole('tab', { name: 'Model' });

    expect(tabs.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Prompt', 'Model', 'Output Schema', 'Assembly',
    ]);
    expect(promptTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel', { name: 'Prompt' }))
      .toHaveTextContent('Synthetic Architect prompt — exact fixture value.');

    fireEvent.keyDown(promptTab, { key: 'ArrowRight' });
    expect(modelTab).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(modelTab).toHaveFocus());
    expect(screen.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('databricks-claude-opus-4-6');
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(60000);

    fireEvent.click(tabs.getByRole('tab', { name: 'Output Schema' }));
    const outputSchemaPanel = screen.getByRole('tabpanel', { name: 'Output Schema' });
    // The panel now shows the OutputSchemaEditor with field override values (not raw JSON).
    // The architect fixture has a title field override with this description.
    expect(outputSchemaPanel).toHaveTextContent('Synthetic title override');
    // v1 schema contract shows the Schema Upgrade button (picker is hidden until upgrade).
    expect(within(outputSchemaPanel).getByRole('button', { name: 'Schema Upgrade' })).toBeInTheDocument();

    fireEvent.click(tabs.getByRole('tab', { name: 'Assembly' }));
    const assembly = screen.getByRole('tabpanel', { name: 'Assembly' });
    expect(within(assembly).getByRole('group', { name: 'Protected stage: Slide frame constraints' }))
      .toBeVisible();
    expect(within(assembly).getByRole('group', { name: 'Protected stage: Structured-output binding' }))
      .toHaveTextContent('langchain.with_structured_output');
    expect(within(assembly).getByText('Protected assembly version 1')).toBeVisible();
  });

  it('replaces the model definition tabs with only the deterministic Foreman explanation', async () => {
    renderSuccessfulWorkbench();
    const navigation = await loadedNodeNavigation();

    fireEvent.click(within(navigation).getByRole('button', { name: 'Foreman' }));

    const centre = screen.getByTestId('definition-pane');
    expect(within(centre).getByRole('heading', { name: 'Foreman' })).toBeVisible();
    expect(centre).toHaveTextContent(
      'Foreman is deterministic scheduling and routing code; it has no Agent Definition.',
    );
    expect(within(centre).queryByRole('tablist')).not.toBeInTheDocument();
    expect(within(centre).queryByRole('button', { name: 'Save Draft' })).not.toBeInTheDocument();
    expect(within(centre).queryByRole('status')).not.toBeInTheDocument();
  });

  it.each([
    [403, 'Administrator access required'],
    [500, 'Graph configuration is incomplete'],
  ])('contains a typed %i error inside the workbench panel', async (status, detail) => {
    mockFetchResponse(status, { detail });
    render(<AgentDefinitionWorkbench />);

    const panel = screen.getByTestId('agent-definition-workbench');
    const alert = await within(panel).findByRole('alert');
    expect(alert).toHaveTextContent(String(status));
    expect(alert).toHaveTextContent(detail);
    expect(screen.queryByRole('navigation', { name: 'Graph nodes' })).not.toBeInTheDocument();
  });

  it('offers explicit draft save but no execution, review, publication, history, or rollback action', async () => {
    renderSuccessfulWorkbench();
    await loadedNodeNavigation();

    expectNoForbiddenActionNames();
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
    expect(screen.getByText('Isolated testing is not available in this release.')).toBeVisible();
  });

  it.each([
    [
      'aria-labelledby',
      () => (
        <>
          <span id="forbidden-labelled-action">Approve draft</span>
          <button type="button" aria-labelledby="forbidden-labelled-action"><svg aria-hidden="true" /></button>
        </>
      ),
    ],
    [
      'title',
      () => <a href="/history" title="Release history"><span aria-hidden="true">Details</span></a>,
    ],
    [
      'a non-text alternative',
      () => <button type="button"><img src="/probe.svg" alt="Run isolated test" /></button>,
    ],
  ])('the forbidden-action guard detects a name supplied by %s', (_source, renderProbe) => {
    render(renderProbe());

    expect(() => expectNoForbiddenActionNames()).toThrow();
  });

  it('issues exactly one read when mounted', async () => {
    renderSuccessfulWorkbench();
    await loadedNodeNavigation();

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/agent-definitions\/workbench$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('keeps the inactive tab panel target while deferring the workbench mount and request until selection', async () => {
    mockFetchResponse(200, syntheticAgentDefinitionWorkbench);
    render(<AdminPage />);
    const workbenchCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) =>
      String(url).endsWith('/api/admin/agent-definitions/workbench'),
    );
    const tab = screen.getByRole('tab', { name: 'Agent Definitions' });
    const panel = document.getElementById(tab.getAttribute('aria-controls')!);

    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute('role', 'tabpanel');
    expect(panel).toHaveAttribute('aria-labelledby', tab.id);
    expect(panel).toHaveAttribute('hidden');
    expect(panel).not.toBeVisible();
    expect(screen.queryByTestId('agent-definition-workbench')).not.toBeInTheDocument();
    expect(workbenchCalls()).toHaveLength(0);
    fireEvent.click(tab);
    await loadedNodeNavigation();

    expect(panel).not.toHaveAttribute('hidden');
    expect(panel).toBeVisible();
    expect(within(panel!).getByTestId('agent-definition-workbench')).toBeVisible();
    expect(workbenchCalls()).toHaveLength(1);
  });

  it('typing and navigation never save and preserves all five local fields by agent and editor tab', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();

    await editArchitectFiveFields(() => expect(putCalls(fetchMock)).toHaveLength(0));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '' } });
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '0.4' } });
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: 'Output Schema' }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: 'Assembly' }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(putCalls(fetchMock)).toHaveLength(0);

    expect(screen.getByRole('tab', { name: 'Assembly' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A2');
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('endpoint-a2');
    expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue(0.4);
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(8192);
    expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(0.8);
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');
  });

  it('saves exactly the five-field candidate with the global lock and preserves another local draft', async () => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, 1)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await editArchitectFiveFields();
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Builder B2' } });
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    const [, init] = putCalls(fetchMock)[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      lock_version: 0,
      candidate: {
        prompt_text: 'Architect A2',
        model: { endpoint_name: 'endpoint-a2', temperature: 0.4, max_tokens: 8192, top_p: 0.8 },
      },
    });
    await waitFor(() => expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version1'));
    expect(screen.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
    expect(screen.getByText('Draft base').parentElement).toHaveTextContent('Graph Version 1');
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Needs test');
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder B2');
    expect(within(navigation).getByRole('button', { name: /Builder/ })).toHaveTextContent('Unsaved');
  });

  it('allows explicit same-content save and adopts its incremented lock without claiming Clean', async () => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request, call) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, call + 1, call === 0)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Needs test'));

    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((putCalls(fetchMock)[1][1] as RequestInit).body))).toMatchObject({ lock_version: 1 });
    await waitFor(() => expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version2'));
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Needs test');
  });

  it('retains A3 typed while A2 is pending and globally locks saves until it settles', async () => {
    let resolvePut!: (response: object) => void;
    const pendingPut = new Promise<object>((resolve) => { resolvePut = resolve; });
    const fetchMock = mockWorkbenchWithPuts((_agentKey, request, call) => {
      if (call === 0) return pendingPut;
      return apiResponse(200, saveSuccess('builder', request.candidate, 2));
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const prompt = await screen.findByRole('textbox', { name: 'Prompt text' });
    fireEvent.change(prompt, { target: { value: 'Architect A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    fireEvent.change(prompt, { target: { value: 'Architect A3' } });
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(putCalls(fetchMock)).toHaveLength(1);

    resolvePut(apiResponse(200, saveSuccess('architect', {
      prompt_text: 'Architect A2',
      model: structuredClone(modelNode('architect').draft.model),
    }, 1)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((putCalls(fetchMock)[1][1] as RequestInit).body))).toMatchObject({ lock_version: 1 });
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A3');
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');
  });

  it('renders a conflict comparison and reconciles every clean role from the exact-seven response', async () => {
    const fetchMock = mockWorkbenchWithPuts((_agentKey, request, call) => {
      if (call === 0) return apiResponse(409, conflictWithServerEdits(request, {
        architect: 'Architect server A1',
        data_analyst: 'Data Analyst server D1',
        builder: 'Builder server B1',
        build_reviewer: 'Build Reviewer server BR1',
        fixer: 'Fixer server F1',
        fix_reviewer: 'Fix Reviewer server FR1',
        deck_reviewer: 'Deck Reviewer server DR1',
      }));
      return apiResponse(200, saveSuccess('architect', request.candidate, 2));
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const prompt = screen.getByRole('textbox', { name: 'Prompt text' });
    fireEvent.change(prompt, { target: { value: 'Architect submitted A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    const conflict = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(conflict).toHaveTextContent('Expected lock 0');
    expect(conflict).toHaveTextContent('Current lock 1');
    expect(within(conflict).getByRole('group', { name: 'Server values' })).toHaveTextContent('Architect server A1');
    expect(within(conflict).getByRole('group', { name: 'Submitted values' })).toHaveTextContent('Architect submitted A2');
    expect(within(conflict).queryByRole('group', { name: 'Current local values' })).not.toBeInTheDocument();
    expect(within(conflict).getByRole('button', { name: 'Reload server' })).toBeEnabled();
    expect(within(conflict).getByRole('button', { name: 'Keep local' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');

    for (const [buttonName, promptText] of [
      ['Data Analyst', 'Data Analyst server D1'],
      ['Builder', 'Builder server B1'],
      ['Build Reviewer', 'Build Reviewer server BR1'],
      ['Fixer', 'Fixer server F1'],
      ['Fix Reviewer', 'Fix Reviewer server FR1'],
      ['Deck Reviewer', 'Deck Reviewer server DR1'],
    ]) {
      fireEvent.click(within(navigation).getByRole('button', { name: new RegExp(buttonName) }));
      expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(promptText);
      expect(within(navigation).getByRole('button', { name: new RegExp(buttonName) })).toHaveTextContent('Needs test');
    }
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('retains a dirty Builder while reconciling its saved baseline during an Architect conflict', async () => {
    const fetchMock = mockWorkbenchWithPuts((_agentKey, request) => apiResponse(409, conflictWithServerEdits(request, {
      architect: 'Architect server A1',
      builder: 'Builder server B1',
    })));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Builder local B2' } });
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await screen.findByRole('region', { name: 'Draft changed on the server' });

    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder local B2');
    expect(within(navigation).getByRole('button', { name: /Builder/ })).toHaveTextContent('Unsaved');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('keeps local conflict values without writing and retries with the refreshed global lock', async () => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request, call) => call === 0
      ? apiResponse(409, conflictWithServerEdits(request, { architect: 'Architect server A1' }))
      : apiResponse(200, saveSuccess(agentKey, request.candidate, 2)));
    render(<AgentDefinitionWorkbench />);
    const prompt = await screen.findByRole('textbox', { name: 'Prompt text' });
    fireEvent.change(prompt, { target: { value: 'Architect local A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    const conflict = await screen.findByRole('region', { name: 'Draft changed on the server' });

    fireEvent.click(within(conflict).getByRole('button', { name: 'Keep local' }));
    expect(screen.queryByRole('region', { name: 'Draft changed on the server' })).not.toBeInTheDocument();
    expect(prompt).toHaveValue('Architect local A2');
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version1');
    expect(putCalls(fetchMock)).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((putCalls(fetchMock)[1][1] as RequestInit).body))).toMatchObject({ lock_version: 1 });
  });

  it('shows current local values and losslessly recovers A3 rather than submitted A2 after a deferred conflict', async () => {
    let resolvePut!: (response: object) => void;
    const pendingPut = new Promise<object>((resolve) => { resolvePut = resolve; });
    const fetchMock = mockWorkbenchWithPuts(() => pendingPut);
    render(<AgentDefinitionWorkbench />);
    const prompt = await screen.findByRole('textbox', { name: 'Prompt text' });
    fireEvent.change(prompt, { target: { value: 'Architect A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    fireEvent.change(prompt, { target: { value: 'Architect A3' } });
    const [, init] = putCalls(fetchMock)[0] as [string, RequestInit];
    const request = JSON.parse(String(init.body)) as DraftSaveRequest;
    resolvePut(apiResponse(409, conflictWithServerEdits(request, { architect: 'Architect server A1' })));

    const conflict = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(within(conflict).getByRole('group', { name: 'Submitted values' })).toHaveTextContent('Architect A2');
    expect(within(conflict).getByRole('group', { name: 'Current local values' })).toHaveTextContent('Architect A3');
    const reload = within(conflict).getByRole('button', { name: 'Reload server' });
    fireEvent.click(reload);
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect server A1');
    const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
    expect(recovery).toHaveTextContent('Architect A3');
    expect(putCalls(fetchMock)).toHaveLength(1);
    fireEvent.click(within(recovery).getByRole('button', { name: 'Restore retained values' }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A3');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('dismisses only the recovery copy after Reload server without writing', async () => {
    const fetchMock = mockWorkbenchWithPuts((_agentKey, request) => apiResponse(
      409,
      conflictWithServerEdits(request, { architect: 'Architect server A1' }),
    ));
    render(<AgentDefinitionWorkbench />);
    fireEvent.change(await screen.findByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Reload server' }));

    const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
    expect(recovery).toHaveTextContent('Architect A3');
    fireEvent.click(within(recovery).getByRole('button', { name: 'Discard retained values' }));
    expect(screen.queryByRole('region', { name: 'Values retained for recovery' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect server A1');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('associates all five 422 messages with their labelled inputs without an opaque request alert', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(422, {
      code: 'invalid_draft',
      errors: [
        ['candidate.prompt_text', 'Prompt rejected.'],
        ['candidate.model.endpoint_name', 'Endpoint rejected.'],
        ['candidate.model.temperature', 'Temperature rejected.'],
        ['candidate.model.max_tokens', 'Maximum tokens rejected.'],
        ['candidate.model.top_p', 'Top-p rejected.'],
      ].map(([field, message]) => ({ field, code: 'rejected', message })),
    }));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await screen.findByText('Prompt rejected.');

    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveAccessibleDescription('Prompt rejected.');
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('textbox', { name: 'Endpoint' })).toHaveAccessibleDescription('Endpoint rejected.');
    expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveAccessibleDescription('Temperature rejected.');
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveAccessibleDescription('Maximum tokens rejected.');
    expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveAccessibleDescription('Top-p rejected.');
    expect(screen.getAllByRole('alert')).toHaveLength(4);
    expect(screen.queryByText(/Unable to save draft/)).not.toBeInTheDocument();
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it.each([
    ['malformed 200', () => apiResponse(200, { changed: true })],
    ['six-role 409', (request: DraftSaveRequest) => {
      const conflict = saveConflict(request);
      const definitions = { ...conflict.server.definitions } as Record<string, unknown>;
      delete definitions.builder;
      return apiResponse(409, { ...conflict, server: { ...conflict.server, definitions } });
    }],
    ['eight-role 409', (request: DraftSaveRequest) => {
      const conflict = saveConflict(request);
      return apiResponse(409, {
        ...conflict,
        server: {
          ...conflict.server,
          definitions: { ...conflict.server.definitions, foreman: conflict.server.definitions.architect },
        },
      });
    }],
    ['mistyped 422', () => apiResponse(422, {
      code: 'invalid_draft',
      errors: [{ field: 'candidate.prompt_text', code: 'rejected', message: 42 }],
    })],
    ['non-object JSON', () => apiResponse(200, [])],
  ])('rejects %s as an invalid response, preserves every form, and permits explicit retry', async (_name, invalidResponse) => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request, call) => call === 0
      ? invalidResponse(request)
      : apiResponse(200, saveSuccess(agentKey, request.candidate, 1)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await editArchitectFiveFields();
    fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Builder retained B2' } });
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Unable to save draft because the server response was invalid.',
    );
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A2');
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('endpoint-a2');
    expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue(0.4);
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(8192);
    expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(0.8);
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder retained B2');
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A2');
  });

  it('contains transport failures to the selected role and clears them only on edit or a new save', async () => {
    const fetchMock = mockWorkbenchWithPuts((_agentKey, _request, call) => call === 0
      ? Promise.reject(new TypeError('network failed'))
      : call === 1
        ? {
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          json: vi.fn().mockRejectedValue(new SyntaxError('not JSON')),
        }
        : apiResponse(200, saveSuccess('architect', _request.candidate, 1)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to save draft. Check your connection and try again.');
    expect(putCalls(fetchMock)).toHaveLength(1);

    fireEvent.click(within(navigation).getByRole('button', { name: 'Builder' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole('button', { name: 'Architect' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to save draft. Check your connection and try again.');
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'clear network error' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to save draft (500 Internal Server Error).');
    expect(putCalls(fetchMock)).toHaveLength(2);
  });

  it('Admin tab preserves unsaved draft after first lazy visit without another GET or any PUT', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AdminPage />);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('tab', { name: 'Agent Definitions' }));
    const navigation = await loadedNodeNavigation();
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect persisted' } });
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');
    fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: 'Agent Definitions' }));

    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect persisted');
    expect(within(screen.getByRole('navigation', { name: 'Graph nodes' }))
      .getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'GET')).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
  });
});

// ============================================================
// #265 protected-assembly upgrade, source recovery, custom blocks
// ============================================================

const UPGRADE_SUFFIX = '/protected-assembly-upgrade';
const SOURCE_SUFFIX = '/legacy-prompt-source';

type RouteResponder = (
  agentKey: AgentKey,
  body: Record<string, unknown>,
  call: number,
) => Promise<object> | object;

function mockWorkbenchApi(routes: {
  put?: RouteResponder;
  upgrade?: RouteResponder;
  source?: RouteResponder;
}) {
  const counts = { put: 0, upgrade: 0, source: 0 };
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === 'GET') return apiResponse(200, syntheticAgentDefinitionWorkbench);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (url.endsWith(UPGRADE_SUFFIX)) {
      const agentKey = url.slice(0, -UPGRADE_SUFFIX.length).split('/').at(-1) as AgentKey;
      if (!routes.upgrade) throw new Error('unexpected upgrade POST');
      return routes.upgrade(agentKey, body, counts.upgrade++);
    }
    if (url.endsWith(SOURCE_SUFFIX)) {
      const agentKey = url.slice(0, -SOURCE_SUFFIX.length).split('/').at(-1) as AgentKey;
      if (!routes.source) throw new Error('unexpected legacy-source POST');
      return routes.source(agentKey, body, counts.source++);
    }
    const agentKey = url.split('/').at(-1) as AgentKey;
    if (!routes.put) throw new Error('unexpected PUT');
    return routes.put(agentKey, body, counts.put++);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function callsTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith(suffix));
}

function upgradeCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return callsTo(fetchMock, UPGRADE_SUFFIX);
}

function sourceCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return callsTo(fetchMock, SOURCE_SUFFIX);
}

async function selectRole(name: string) {
  const navigation = await loadedNodeNavigation();
  fireEvent.click(within(navigation).getByRole('button', { name: new RegExp(name) }));
  return navigation;
}

function assemblyPanel() {
  fireEvent.click(screen.getByRole('tab', { name: 'Assembly' }));
  return screen.getByRole('tabpanel', { name: 'Assembly' });
}

function promptPanel() {
  fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
  return screen.getByRole('tabpanel', { name: 'Prompt' });
}

describe('AgentDefinitionWorkbench protected assembly upgrade', () => {
  it('sends exactly one lock-only POST and installs the server-authored v2 prompt', async () => {
    const fetchMock = mockWorkbenchApi({
      upgrade: (agentKey) => apiResponse(200, syntheticUpgradeSuccess(agentKey, 1)),
      put: (agentKey, body) => apiResponse(200, {
        ...syntheticUpgradeSuccess(agentKey, 2),
        definition: {
          ...syntheticV2DraftDefinition(agentKey),
          prompt_text: (body.candidate as { prompt_text: string }).prompt_text,
        },
      }),
    });
    render(<AgentDefinitionWorkbench />);
    await selectRole('Data Analyst');
    const panel = assemblyPanel();

    // v1 offers no custom-block control at all.
    expect(within(panel).queryByRole('button', { name: /^Add custom block/ })).not.toBeInTheDocument();
    expect(within(panel).getByText('Custom text blocks require the Graph Version 2 protected assembly.'))
      .toBeVisible();

    fireEvent.click(within(panel).getByRole('button', { name: 'Upgrade protected assembly' }));
    await waitFor(() => expect(upgradeCalls(fetchMock)).toHaveLength(1));
    const [url, init] = upgradeCalls(fetchMock)[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/data_analyst\/protected-assembly-upgrade$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ lock_version: 0 });
    expect(String(init.body)).toBe('{"lock_version":0}');

    await waitFor(() => expect(screen.getByText('Lock version').parentElement)
      .toHaveTextContent('Lock version1'));
    expect(promptPanel()).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);

    // Only now are custom-block controls available.
    const upgraded = assemblyPanel();
    expect(within(upgraded).getByRole('button', { name: 'Add custom block After authored prompt' }))
      .toBeEnabled();
    expect(within(upgraded).getByRole('button', { name: 'Add custom block After environment constraints' }))
      .toBeEnabled();
    expect(within(upgraded).queryByRole('button', { name: 'Upgrade protected assembly' }))
      .not.toBeInTheDocument();
    expect(within(upgraded).getByRole('group', { name: 'Protected stage: Untrusted-data opening delimiter' }))
      .toBeVisible();

    // The next ordinary PUT carries the authored-only v2 prompt plus v2 rules.
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    const putBody = JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body)) as DraftSaveRequest;
    expect(putBody).toEqual({
      lock_version: 1,
      candidate: {
        prompt_text: V2_AUTHORED_PROMPT.data_analyst,
        model: structuredClone(modelNode('data_analyst').draft.model),
        assembly_rules: { format_version: 2, custom_blocks: [] },
      },
    });
  });

  it.each(AFFECTED_ROLES)(
    '%s with a dirty prompt sends no POST and retains the exact bytes for manual reapplication',
    async (displayName) => {
      const fetchMock = mockWorkbenchApi({});
      render(<AgentDefinitionWorkbench />);
      await selectRole(displayName);
      const prompt = screen.getByRole('textbox', { name: 'Prompt text' });
      const savedPrompt = String((prompt as HTMLTextAreaElement).value);
      fireEvent.change(prompt, { target: { value: DIRTY_LEGACY_PROMPT } });

      fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));

      expect(upgradeCalls(fetchMock)).toHaveLength(0);
      expect(putCalls(fetchMock)).toHaveLength(0);
      expect(sourceCalls(fetchMock)).toHaveLength(0);
      // Not one byte of the dirty prompt changed.
      expect(promptPanel()).toBeVisible();
      expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(DIRTY_LEGACY_PROMPT);

      const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
      const retained = within(recovery).getByRole('group', { name: 'Retained alternative 1' });
      // The entry container and its values group must not be prefix-related, or any
      // name-substring query resolves to both.
      expect(within(recovery).getAllByRole('group', { name: /Retained alternative/ })).toHaveLength(1);
      expect(within(recovery).getAllByRole('group', { name: /Retained values/ })).toHaveLength(1);
      expect(within(retained).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveValue(DIRTY_LEGACY_PROMPT);
      expect(within(retained).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveAttribute('readonly');

      // Local restore returns the saved prompt without any request.
      fireEvent.click(screen.getByRole('button', { name: 'Restore saved prompt' }));
      expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(savedPrompt);
      expect(within(retained).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveValue(DIRTY_LEGACY_PROMPT);
      expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method !== 'GET'))
        .toHaveLength(0);
    },
  );

  it('links a manual-resolution 422 to the Prompt tab and offers only the server-backed recovery', async () => {
    const fetchMock = mockWorkbenchApi({
      upgrade: () => apiResponse(422, MANUAL_RESOLUTION_REJECTION),
      source: () => apiResponse(200, syntheticLegacyPromptSource('data_analyst', 0)),
    });
    render(<AgentDefinitionWorkbench />);
    await selectRole('Data Analyst');
    const savedPrompt = String((screen.getByRole('textbox', { name: 'Prompt text' }) as HTMLTextAreaElement).value);
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));

    const issues = await screen.findByRole('region', { name: 'Server rejected this request' });
    expect(issues).toHaveTextContent('prompt_text — legacy_prompt_manual_resolution_required');
    expect(issues).toHaveTextContent(MANUAL_RESOLUTION_REJECTION.errors[0].message);
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(within(issues).getByRole('button', { name: 'Go to Prompt tab' }));
    expect(screen.getByRole('tab', { name: 'Prompt' })).toHaveAttribute('aria-selected', 'true');
    // Nothing was saved, retried, rewritten, or upgraded.
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(savedPrompt);
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toBeEnabled();
    expect(screen.queryByRole('region', { name: 'Values retained for recovery' })).not.toBeInTheDocument();

    // Make the local prompt differ from the saved prompt before recovering, so the two
    // quarantined alternatives carry distinguishable bytes. Restoring a retained
    // alternative is the only prompt change that keeps the server verdict on screen.
    const dirtyAttempt = screen.getByRole('textbox', { name: 'Prompt text' });
    fireEvent.change(dirtyAttempt, { target: { value: DIRTY_LEGACY_PROMPT } });
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
    expect(promptPanel()).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Restore saved prompt' }));
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    await waitFor(() => expect(upgradeCalls(fetchMock)).toHaveLength(2));
    expect(promptPanel()).toBeVisible();
    fireEvent.click(within(screen.getByRole('group', { name: 'Retained alternative 1' }))
      .getByRole('button', { name: 'Restore retained values' }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(DIRTY_LEGACY_PROMPT);

    const recover = screen.getByRole('button', { name: 'Restore published Graph Version 1 prompt' });
    fireEvent.click(recover);
    await waitFor(() => expect(sourceCalls(fetchMock)).toHaveLength(1));
    const [sourceUrl, sourceInit] = sourceCalls(fetchMock)[0] as [string, RequestInit];
    expect(sourceUrl).toMatch(/\/draft\/data_analyst\/legacy-prompt-source$/);
    expect(sourceInit.method).toBe('POST');
    expect(String(sourceInit.body)).toBe('{"lock_version":0}');

    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(PUBLISHED_V1_PROMPT_SOURCE.data_analyst));
    // Recovery never writes: the lock is unchanged and no PUT or second POST fired.
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(upgradeCalls(fetchMock)).toHaveLength(2);

    // Three alternatives: the refused dirty attempt, then the edited saved form and the
    // edited local form the recovery quarantined. The last two are deliberately
    // distinct, so the assertion cannot pass on the wrong order or a duplicated form.
    const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
    expect(within(recovery).getAllByRole('group', { name: /^Retained alternative \d+$/ })).toHaveLength(3);
    expect(within(recovery).getAllByRole('group', { name: /^Retained values \d+$/ })).toHaveLength(3);
    expect(savedPrompt).not.toBe(DIRTY_LEGACY_PROMPT);
    expect(within(recovery).getAllByRole('textbox', { name: 'Manual-only prompt bytes' })
      .map((box) => (box as HTMLTextAreaElement).value))
      .toEqual([DIRTY_LEGACY_PROMPT, savedPrompt, DIRTY_LEGACY_PROMPT]);
  });

  it.each([
    'legacy_prompt_source_unsupported',
    'legacy_prompt_source_not_required',
    'legacy_prompt_source_unavailable',
  ])('surfaces the %s recovery rejection without writing anything', async (code) => {
    const rejection = {
      code: 'invalid_draft',
      errors: [{ field: 'prompt_text', code, message: `Recovery refused: ${code}.` }],
    };
    const fetchMock = mockWorkbenchApi({
      upgrade: () => apiResponse(422, MANUAL_RESOLUTION_REJECTION),
      source: () => apiResponse(422, rejection),
    });
    render(<AgentDefinitionWorkbench />);
    await selectRole('Build Reviewer');
    const savedPrompt = String((screen.getByRole('textbox', { name: 'Prompt text' }) as HTMLTextAreaElement).value);
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    await screen.findByRole('region', { name: 'Server rejected this request' });
    fireEvent.click(promptPanel().querySelector('button:last-of-type')!);

    await waitFor(() => expect(sourceCalls(fetchMock)).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Server rejected this request' }))
      .toHaveTextContent(`Recovery refused: ${code}.`));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(savedPrompt);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(screen.queryByRole('region', { name: 'Values retained for recovery' })).not.toBeInTheDocument();
  });

  it('links an already_current 422 to the Assembly tab and changes no local byte', async () => {
    const fetchMock = mockWorkbenchApi({ upgrade: () => apiResponse(422, ALREADY_CURRENT_REJECTION) });
    render(<AgentDefinitionWorkbench />);
    await selectRole('Architect');
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect local edit' } });
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));

    const issues = await screen.findByRole('region', { name: 'Server rejected this request' });
    expect(issues).toHaveTextContent('protected_assembly.version — already_current');
    expect(issues).toHaveTextContent('Protected assembly is already current.');
    fireEvent.click(within(issues).getByRole('button', { name: 'Go to Assembly tab' }));
    expect(screen.getByRole('tab', { name: 'Assembly' })).toHaveAttribute('aria-selected', 'true');
    expect(within(screen.getByRole('tabpanel', { name: 'Assembly' }))
      .getByRole('button', { name: 'Upgrade protected assembly' })).toBeEnabled();

    // No reload, save, retry, or second state check.
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'GET'))
      .toHaveLength(1);
    expect(promptPanel()).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect local edit');
    expect(screen.queryByRole('region', { name: 'Values retained for recovery' })).not.toBeInTheDocument();
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
  });

  it('one aggregate gate blocks every second operation, across roles, until the first settles', async () => {
    let releaseUpgrade!: (response: object) => void;
    const held = new Promise<object>((resolve) => { releaseUpgrade = resolve; });
    const fetchMock = mockWorkbenchApi({
      upgrade: () => held,
      put: (agentKey, body) => apiResponse(200, saveSuccess(
        agentKey,
        body.candidate as EditableModelDraft,
        2,
      )),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Data Analyst');
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(1);

    // Same role: the prompt control is disabled but safe model fields are not.
    expect(within(promptPanel()).getByRole('textbox', { name: 'Prompt text' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    const maxTokens = screen.getByRole('spinbutton', { name: 'Maximum tokens' });
    expect(maxTokens).toBeEnabled();
    fireEvent.change(maxTokens, { target: { value: '4096' } });
    expect(maxTokens).toHaveValue(4096);

    // A second Upgrade, and a Save on another role, issue no request at all.
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(1);

    releaseUpgrade(apiResponse(200, syntheticUpgradeSuccess('data_analyst', 1)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());

    // The safe edit made while pending survived the upgrade.
    fireEvent.click(within(navigation).getByRole('button', { name: /Data Analyst/ }));
    expect(promptPanel()).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toBeEnabled();
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(4096);

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    const body = JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body)) as DraftSaveRequest;
    expect(body.lock_version).toBe(1);
    expect(body.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
    expect(body.candidate.model.max_tokens).toBe(4096);
  });

  it('a pending Save blocks Upgrade and SourceRecovery on every role', async () => {
    let releasePut!: (response: object) => void;
    const held = new Promise<object>((resolve) => { releasePut = resolve; });
    const fetchMock = mockWorkbenchApi({ put: () => held });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Architect');
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(putCalls(fetchMock)).toHaveLength(1);

    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(within(navigation).getByRole('button', { name: /Data Analyst/ }));
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    expect(upgradeCalls(fetchMock)).toHaveLength(0);

    releasePut(apiResponse(200, saveSuccess('architect', {
      prompt_text: 'Architect A2',
      model: structuredClone(modelNode('architect').draft.model),
    }, 1)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
    expect(upgradeCalls(fetchMock)).toHaveLength(0);
  });

  it('edits custom blocks locally and sends them only on an explicit Save', async () => {
    const fetchMock = mockWorkbenchApi({
      upgrade: (agentKey) => apiResponse(200, syntheticUpgradeSuccess(agentKey, 1)),
      put: (agentKey, body) => apiResponse(200, {
        ...syntheticUpgradeSuccess(agentKey, 2),
        definition: syntheticV2DraftDefinition(agentKey, {
          prompt_text: (body.candidate as { prompt_text: string }).prompt_text,
          assembly_rules: (body.candidate as { assembly_rules: AssemblyRulesV2 }).assembly_rules,
        }),
      }),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Build Reviewer');
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    await waitFor(() => expect(upgradeCalls(fetchMock)).toHaveLength(1));

    const panel = assemblyPanel();
    fireEvent.click(within(panel).getByRole('button', { name: 'Add custom block After deck-brief re-review' }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Add custom block After deck-brief re-review' }));
    const deckGroup = within(assemblyPanel())
      .getByRole('group', { name: 'Custom blocks: After deck-brief re-review' });
    const blocks = within(deckGroup).getAllByRole('group', { name: /^Custom block \d at/ });
    expect(blocks).toHaveLength(2);
    fireEvent.change(within(blocks[0]).getByRole('textbox', { name: 'Block text' }), {
      target: { value: 'first deck note' },
    });
    fireEvent.change(within(blocks[1]).getByRole('textbox', { name: 'Block text' }), {
      target: { value: 'second deck note' },
    });
    fireEvent.change(within(blocks[1]).getByRole('combobox', { name: 'Condition' }), {
      target: { value: 'payload_has_deck_brief' },
    });
    expect(within(navigation).getByRole('button', { name: /Build Reviewer/ })).toHaveTextContent('Unsaved');
    // Editing, reordering, and deleting never write.
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Move up' }));
    const reordered = within(within(assemblyPanel())
      .getByRole('group', { name: 'Custom blocks: After deck-brief re-review' }))
      .getAllByRole('group', { name: /^Custom block \d at/ });
    expect(within(reordered[0]).getByRole('textbox', { name: 'Block text' })).toHaveValue('second deck note');
    expect(within(reordered[1]).getByRole('textbox', { name: 'Block text' })).toHaveValue('first deck note');
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    const body = JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body)) as DraftSaveRequest;
    const sent = body.candidate.assembly_rules;
    expect(sent?.format_version).toBe(2);
    expect(sent?.custom_blocks.map((block) => [block.anchor, block.condition, block.text])).toEqual([
      ['after_deck_brief', 'payload_has_deck_brief', 'second deck note'],
      ['after_deck_brief', 'always', 'first deck note'],
    ]);
    for (const block of sent?.custom_blocks ?? []) {
      expect(block.block_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
      expect(block.kind).toBe('custom_text');
    }
    expect(new Set((sent?.custom_blocks ?? []).map((block) => block.block_id)).size).toBe(2);

    fireEvent.click(within(assemblyPanel())
      .getAllByRole('button', { name: 'Delete' })[0]);
    expect(within(within(assemblyPanel())
      .getByRole('group', { name: 'Custom blocks: After deck-brief re-review' }))
      .getAllByRole('group', { name: /^Custom block \d at/ })).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('renders the authoritative block-id and cross-anchor 422 issues in exact server order', async () => {
    const errors = [
      {
        field: 'candidate.assembly_rules.custom_blocks.0.block_id',
        code: 'strict_type',
        message: 'Custom block ID must be a UUID string.',
      },
      {
        field: 'candidate.assembly_rules',
        code: 'invalid_protected_placement',
        message: 'Assembly rules must satisfy the persisted assembly contract.',
      },
    ];
    const fetchMock = mockWorkbenchApi({
      upgrade: (agentKey) => apiResponse(200, syntheticUpgradeSuccess(agentKey, 1)),
      put: () => apiResponse(422, { code: 'invalid_draft', errors }),
    });
    render(<AgentDefinitionWorkbench />);
    await selectRole('Architect');
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    await waitFor(() => expect(upgradeCalls(fetchMock)).toHaveLength(1));
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Add custom block After authored prompt' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    const issues = await screen.findByRole('region', { name: 'Server rejected this request' });
    expect([...issues.querySelectorAll('li')].map((item) => item.querySelector('p')?.textContent)).toEqual([
      'candidate.assembly_rules.custom_blocks.0.block_id — strict_type',
      'candidate.assembly_rules — invalid_protected_placement',
    ]);
    expect(issues).toHaveTextContent('Custom block ID must be a UUID string.');
    expect(issues).toHaveTextContent('Assembly rules must satisfy the persisted assembly contract.');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('adopts a v2 conflict winner, quarantines legacy bytes, and never puts them back', async () => {
    const fetchMock = mockWorkbenchApi({
      put: (agentKey, body, call) => (call === 0
        ? apiResponse(409, (() => {
          const conflict = saveConflict(body as unknown as DraftSaveRequest);
          conflict.server.definitions.data_analyst = syntheticV2DraftDefinition('data_analyst');
          return conflict;
        })())
        : apiResponse(200, {
          ...syntheticUpgradeSuccess(agentKey, 2),
          definition: syntheticV2DraftDefinition(agentKey),
        })),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Data Analyst');
    const savedPrompt = String((screen.getByRole('textbox', { name: 'Prompt text' }) as HTMLTextAreaElement).value);
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: DIRTY_LEGACY_PROMPT } });
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Top-p' }), { target: { value: '0.55' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    const conflictRegion = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(within(conflictRegion).getByRole('group', { name: 'Server values' }))
      .toHaveTextContent(V2_AUTHORED_PROMPT.data_analyst);
    expect(promptPanel()).toBeVisible();
    // The v1 composite is gone from every savable form and lives only as bytes.
    expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);
    const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
    expect(within(recovery).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(DIRTY_LEGACY_PROMPT);

    fireEvent.click(within(conflictRegion).getByRole('button', { name: 'Keep local' }));
    expect(screen.queryByRole('region', { name: 'Draft changed on the server' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(0.55);

    // Restoring the retained alternative re-sanitizes the prompt against v2.
    fireEvent.click(within(screen.getByRole('region', { name: 'Values retained for recovery' }))
      .getByRole('button', { name: 'Restore retained values' }));
    expect(promptPanel()).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    const body = JSON.parse(String((putCalls(fetchMock)[1][1] as RequestInit).body)) as DraftSaveRequest;
    expect(body.lock_version).toBe(1);
    expect(body.candidate.prompt_text).toBe(V2_AUTHORED_PROMPT.data_analyst);
    expect(body.candidate.prompt_text).not.toBe(DIRTY_LEGACY_PROMPT);
    expect(body.candidate.prompt_text).not.toBe(savedPrompt);
    expect(body.candidate.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });
    expect(within(navigation).getByRole('button', { name: /Data Analyst/ })).toBeVisible();
  });

  it('reconciles an upgrade 409 to v2 across every role without surfacing already_current', async () => {
    const fetchMock = mockWorkbenchApi({
      upgrade: () => apiResponse(409, syntheticNullCandidateConflict(0, 1, [...AFFECTED_ROLE_KEYS])),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Data Analyst');
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));

    const conflictRegion = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(conflictRegion).toHaveTextContent('Expected lock 0');
    expect(conflictRegion).toHaveTextContent('Current lock 1');
    // No candidate was submitted, so no Submitted values group exists.
    expect(within(conflictRegion).queryByRole('group', { name: 'Submitted values' })).not.toBeInTheDocument();
    expect(within(conflictRegion).getByRole('group', { name: 'Server values' }))
      .toHaveTextContent(V2_AUTHORED_PROMPT.data_analyst);
    expect(screen.queryByText('Protected assembly is already current.')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Server rejected this request' })).not.toBeInTheDocument();

    // Both affected roles reconciled to v2; the unaffected role stayed on v1.
    expect(within(assemblyPanel()).queryByRole('button', { name: 'Upgrade protected assembly' }))
      .not.toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole('button', { name: /Build Reviewer/ }));
    expect(within(assemblyPanel()).getByRole('button', { name: 'Add custom block After deck-brief re-review' }))
      .toBeEnabled();
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' })).toBeEnabled();
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('keeps an unaffected role losslessly editable while another role upgrades', async () => {
    let releaseUpgrade!: (response: object) => void;
    const held = new Promise<object>((resolve) => { releaseUpgrade = resolve; });
    const fetchMock = mockWorkbenchApi({ upgrade: () => held });
    render(<AgentDefinitionWorkbench />);
    const navigation = await selectRole('Data Analyst');
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));

    fireEvent.click(within(navigation).getByRole('button', { name: /Fixer/ }));
    const prompt = promptPanel().querySelector('textarea')!;
    expect(prompt).toBeEnabled();
    fireEvent.change(prompt, { target: { value: 'Fixer lossless edit' } });
    expect(prompt).toHaveValue('Fixer lossless edit');
    expect(screen.queryByRole('region', { name: 'Values retained for recovery' })).not.toBeInTheDocument();

    releaseUpgrade(apiResponse(200, syntheticUpgradeSuccess('data_analyst', 1)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Fixer lossless edit');
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
  });

  it('persists role, tab, and Admin-tab state across an upgrade without another GET', async () => {
    const fetchMock = mockWorkbenchApi({
      upgrade: (agentKey) => apiResponse(200, syntheticUpgradeSuccess(agentKey, 1)),
    });
    render(<AdminPage />);
    fireEvent.click(screen.getByRole('tab', { name: 'Agent Definitions' }));
    const navigation = await loadedNodeNavigation();
    fireEvent.click(within(navigation).getByRole('button', { name: /Data Analyst/ }));
    fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
    await waitFor(() => expect(upgradeCalls(fetchMock)).toHaveLength(1));
    fireEvent.click(within(assemblyPanel())
      .getByRole('button', { name: 'Add custom block After authored prompt' }));

    fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Agent Definitions' }));

    expect(within(screen.getByRole('navigation', { name: 'Graph nodes' }))
      .getByRole('button', { name: /Data Analyst/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('tab', { name: 'Assembly' })).toHaveAttribute('aria-selected', 'true');
    expect(within(screen.getByRole('tabpanel', { name: 'Assembly' }))
      .getAllByRole('group', { name: /^Custom block \d at/ })).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'GET'))
      .toHaveLength(1);
    expect(upgradeCalls(fetchMock)).toHaveLength(1);
  });
});

/**
 * Drives `useDraftEditor` through controls that are never disabled, so the hook's own
 * shared request-ID gate is the only thing that can stop a second request. A test that
 * goes through `DefinitionEditor` cannot prove this: the button's `disabled` attribute
 * masks the hook, and the DOM is not the state invariant.
 */
function GateHarness() {
  const editor = useDraftEditor(syntheticAgentDefinitionWorkbench);
  const operations: Array<[string, () => Promise<void>]> = [
    ['save architect', () => editor.save('architect')],
    ['save builder', () => editor.save('builder')],
    ['upgrade architect', () => editor.upgradeProtectedAssembly('architect')],
    ['upgrade builder', () => editor.upgradeProtectedAssembly('builder')],
    ['recover data analyst', () => editor.restorePublishedV1Prompt('data_analyst')],
    ['schema upgrade architect', () => editor.upgradeSchemaContract('architect')],
  ];
  // Pairs fired inside one handler never see a re-render, so the hook's shared
  // in-flight ref is the only guard the second call can meet.
  const sameTickPairs: Array<[string, () => void]> = [
    ['double upgrade architect', () => {
      void editor.upgradeProtectedAssembly('architect');
      void editor.upgradeProtectedAssembly('architect');
    }],
    ['save then upgrade architect', () => {
      void editor.save('architect');
      void editor.upgradeProtectedAssembly('architect');
    }],
    ['upgrade then recover', () => {
      void editor.upgradeProtectedAssembly('architect');
      void editor.restorePublishedV1Prompt('data_analyst');
    }],
    ['recover then save builder', () => {
      void editor.restorePublishedV1Prompt('data_analyst');
      void editor.save('builder');
    }],
    ['schema upgrade then save architect', () => {
      void editor.upgradeSchemaContract('architect');
      void editor.save('architect');
    }],
    ['save architect then schema upgrade', () => {
      void editor.save('architect');
      void editor.upgradeSchemaContract('architect');
    }],
  ];
  return (
    <>
      {operations.map(([name, run]) => (
        <button key={name} type="button" onClick={() => { void run(); }}>{`harness ${name}`}</button>
      ))}
      {sameTickPairs.map(([name, run]) => (
        <button key={name} type="button" onClick={run}>{`harness ${name}`}</button>
      ))}
    </>
  );
}

describe('schema contract upgrade via useDraftEditor', () => {
  function mockForSchemaUpgrade(upgradeRespond: (key: string) => object) {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('schema-contract-upgrade')) {
        const agentKey = url.split('/').at(-2) ?? 'architect';
        return Promise.resolve(apiResponse(200, upgradeRespond(agentKey)));
      }
      return Promise.resolve(apiResponse(200, syntheticAgentDefinitionWorkbench));
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('schema upgrade sends a lock-only POST to the schema-contract-upgrade endpoint', async () => {
    const fetchMock = mockForSchemaUpgrade(() => ({
      draft: { ...syntheticAgentDefinitionWorkbench.draft, lock_version: 1 },
      definition: structuredClone(syntheticDraftDefinitions['architect']),
      changed: true,
    }));
    const { result } = renderHook(() => useDraftEditor(syntheticAgentDefinitionWorkbench));
    await act(() => result.current.upgradeSchemaContract('architect'));

    const schemaCalls = (fetchMock.mock.calls as unknown[]).filter(
      (call) => typeof (call as unknown[])[0] === 'string'
        && String((call as unknown[])[0]).includes('schema-contract-upgrade'),
    );
    expect(schemaCalls).toHaveLength(1);
    const [url, init] = schemaCalls[0] as [string, RequestInit];
    expect(url).toMatch(/\/draft\/architect\/schema-contract-upgrade$/);
    const body = JSON.parse(init.body as string);
    // Must be exactly { lock_version: 0 } with no candidate.
    expect(body).toEqual({ lock_version: 0 });
  });
});

describe('prompt-change backstop reaches the retained-forms controls', () => {
  it.each(AFFECTED_ROLES)(
    '%s: restoring an alternative mid-Upgrade restores safe fields but not the prompt',
    async (displayName, agentKey) => {
      let releaseUpgrade!: (response: object) => void;
      const held = new Promise<object>((resolve) => { releaseUpgrade = resolve; });
      const fetchMock = mockWorkbenchApi({ upgrade: () => held });
      render(<AgentDefinitionWorkbench />);
      await selectRole(displayName);
      const savedPrompt = String((screen.getByRole('textbox', { name: 'Prompt text' }) as HTMLTextAreaElement).value);

      // Four clicks reach the cell: dirty Upgrade (refused, retains) → Restore saved
      // prompt → Upgrade (now in flight) → Restore retained values.
      fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: DIRTY_LEGACY_PROMPT } });
      fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
      fireEvent.change(screen.getByRole('spinbutton', { name: 'Top-p' }), { target: { value: '0.66' } });
      fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
      expect(upgradeCalls(fetchMock)).toHaveLength(0);
      expect(promptPanel()).toBeVisible();
      fireEvent.click(screen.getByRole('button', { name: 'Restore saved prompt' }));
      fireEvent.click(within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' }));
      expect(upgradeCalls(fetchMock)).toHaveLength(1);

      // The prompt control is disabled, but the retained-forms controls are not, which
      // is why the reducer and not the DOM has to hold the invariant.
      expect(within(promptPanel()).getByRole('textbox', { name: 'Prompt text' })).toBeDisabled();
      const alternative = screen.getByRole('group', { name: 'Retained alternative 1' });
      const restore = within(alternative).getByRole('button', { name: 'Restore retained values' });
      expect(restore).toBeEnabled();
      expect(within(alternative).getByRole('button', { name: 'Discard retained values' })).toBeEnabled();

      fireEvent.click(restore);

      // The savable prompt is still authoritative; the safe field was restored.
      expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(savedPrompt);
      fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
      expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(0.66);
      // The refused prompt is quarantined a second time rather than dropped.
      const recovery = screen.getByRole('region', { name: 'Values retained for recovery' });
      expect(within(recovery).getAllByRole('textbox', { name: 'Manual-only prompt bytes' })
        .map((box) => (box as HTMLTextAreaElement).value))
        .toEqual([DIRTY_LEGACY_PROMPT, DIRTY_LEGACY_PROMPT]);
      expect(upgradeCalls(fetchMock)).toHaveLength(1);
      expect(putCalls(fetchMock)).toHaveLength(0);

      // On success the server-authored v2 prompt wins and every byte is kept.
      releaseUpgrade(apiResponse(200, syntheticUpgradeSuccess(agentKey, 1)));
      await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
      expect(promptPanel()).toBeVisible();
      expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);
      expect(within(screen.getByRole('region', { name: 'Values retained for recovery' }))
        .getAllByRole('textbox', { name: 'Manual-only prompt bytes' })
        .map((box) => (box as HTMLTextAreaElement).value))
        .toEqual([DIRTY_LEGACY_PROMPT, DIRTY_LEGACY_PROMPT, savedPrompt]);
    },
  );
});

describe('useDraftEditor shared request gate', () => {
  function heldFetch() {
    const release: Array<(response: object) => void> = [];
    const fetchMock = vi.fn().mockImplementation(() => new Promise<object>((resolve) => {
      release.push(resolve);
    }));
    vi.stubGlobal('fetch', fetchMock);
    return { fetchMock, release };
  }

  function requestCount(fetchMock: ReturnType<typeof vi.fn>) {
    return fetchMock.mock.calls.length;
  }

  it.each([
    ['save architect', 'upgrade architect'],
    ['upgrade architect', 'save architect'],
    ['recover data analyst', 'save architect'],
    ['upgrade architect', 'upgrade architect'],
    ['save architect', 'save builder'],
    ['upgrade architect', 'upgrade builder'],
    ['upgrade architect', 'recover data analyst'],
    ['recover data analyst', 'upgrade builder'],
    ['schema upgrade architect', 'save architect'],
    ['save architect', 'schema upgrade architect'],
    ['schema upgrade architect', 'upgrade architect'],
    ['upgrade architect', 'schema upgrade architect'],
  ])('%s then %s issues only the first request', (first, second) => {
    const { fetchMock } = heldFetch();
    render(<GateHarness />);

    fireEvent.click(screen.getByRole('button', { name: `harness ${first}` }));
    expect(requestCount(fetchMock)).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: `harness ${second}` }));
    expect(requestCount(fetchMock)).toBe(1);
    // A third attempt on a further role is refused by the same one gate.
    fireEvent.click(screen.getByRole('button', { name: 'harness save builder' }));
    expect(requestCount(fetchMock)).toBe(1);
  });

  it.each([
    'double upgrade architect',
    'save then upgrade architect',
    'upgrade then recover',
    'recover then save builder',
    'schema upgrade then save architect',
    'save architect then schema upgrade',
  ])('%s inside one tick issues only the first request', (name) => {
    const { fetchMock } = heldFetch();
    render(<GateHarness />);

    fireEvent.click(screen.getByRole('button', { name: `harness ${name}` }));

    expect(requestCount(fetchMock)).toBe(1);
  });

  it('releases the shared gate only after the pending operation settles', async () => {
    const { fetchMock, release } = heldFetch();
    render(<GateHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'harness upgrade architect' }));
    expect(requestCount(fetchMock)).toBe(1);

    release[0](apiResponse(200, syntheticUpgradeSuccess('architect', 1)));
    await waitFor(() => expect(requestCount(fetchMock)).toBe(1));
    fireEvent.click(screen.getByRole('button', { name: 'harness save builder' }));
    await waitFor(() => expect(requestCount(fetchMock)).toBe(2));
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/draft\/builder$/);
  });
});
