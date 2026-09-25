import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ALREADY_CURRENT_REJECTION,
  DIRTY_LEGACY_PROMPT,
  ENDPOINT_NAME_POLICY_CASES,
  MANUAL_RESOLUTION_REJECTION,
  MODEL_ENDPOINT_DISCOVERY_FORBIDDEN,
  MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE,
  PUBLISHED_V1_PROMPT_SOURCE,
  SCHEMA_ALREADY_CURRENT_REJECTION,
  SEED_CANDIDATE_HASH,
  SEED_MODEL_ENDPOINT_NAME,
  STRUCTURED_OUTPUT_PROBE_FAILURES,
  V2_AUTHORED_PROMPT,
  syntheticAgentDefinitionWorkbench,
  syntheticDraftDefinitions,
  syntheticLegacyPromptSource,
  syntheticModelEndpointDiscovery,
  syntheticNewerModelEndpoint,
  syntheticNullCandidateConflict,
  syntheticProbeFailure,
  syntheticProbeSuccess,
  syntheticSchemaV2DraftDefinition,
  syntheticSystemModelEndpoints,
  syntheticUpgradeSuccess,
  syntheticV2DraftDefinition,
} from '../../../../tests/fixtures/mocks';
import {
  ALLOWED_ACTION_NAMES,
  forbidsActionName,
} from '../../../../tests/fixtures/forbiddenActionNames';
import type {
  AgentDefinitionWorkbenchResponse,
  AgentKey,
  AssemblyRulesV2,
  DraftSaveConflictResponse,
  DraftSaveRequest,
  DraftSaveSuccessResponse,
  EditableModelDraft,
} from '../../../api/agentDefinitions';
import {
  AgentDefinitionApiError,
  InvalidModelEndpointCatalogResponseError,
  ModelEndpointCatalogApiError,
  getSystemModelEndpoints,
} from '../../../api/agentDefinitions';
import { AdminPage } from '../AdminPage';
import { AgentDefinitionWorkbench } from './AgentDefinitionWorkbench';
import { LEGACY_COMPOSITE_ROLES, validateDraftForm } from './draftEditorState';
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

function apiResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 409 ? 'Conflict' : status === 422 ? 'Unprocessable Entity' : 'OK',
    json: vi.fn().mockResolvedValue(body),
  };
}

/**
 * Every harness routes by URL (#266 correction 17). The workbench aggregate is answered
 * only on its own URL, and the discovery catalog gets a default accepting list, so a
 * catalog GET can never be answered with a workbench body (or vice versa).
 */
const WORKBENCH_SUFFIX = '/api/admin/agent-definitions/workbench';
const CATALOG_SUFFIX = '/api/admin/agent-definitions/model-endpoints';

function isCatalogUrl(url: unknown) {
  return String(url).endsWith(CATALOG_SUFFIX);
}

function isWorkbenchUrl(url: unknown) {
  return String(url).endsWith(WORKBENCH_SUFFIX);
}

/**
 * The #266 probe POST is routed by URL (correction 17): every harness below otherwise
 * parses an unmatched non-GET as a PUT, which would answer a probe with a save body.
 */
const PROBE_SUFFIX = '/model-endpoint-probe';

function isProbeUrl(url: unknown) {
  return String(url).endsWith(PROBE_SUFFIX);
}

function probeCalls(fetchMock = vi.mocked(fetch)) {
  return fetchMock.mock.calls.filter(([url]) => isProbeUrl(url));
}

function defaultCatalogResponse() {
  return apiResponse(200, syntheticModelEndpointDiscovery());
}

function workbenchGets(fetchMock = vi.mocked(fetch)) {
  return fetchMock.mock.calls.filter(([url, init]) =>
    isWorkbenchUrl(url) && (init as RequestInit | undefined)?.method === 'GET');
}

/** Every GET to any URL: the "exactly these reads and no others" backstop. */
function allGets(fetchMock = vi.mocked(fetch)) {
  return fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'GET');
}

function catalogGets(fetchMock = vi.mocked(fetch)) {
  return fetchMock.mock.calls.filter(([url]) => isCatalogUrl(url));
}

function mockFetchResponse(status: number, body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => (isCatalogUrl(url)
    ? defaultCatalogResponse()
    : {
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 403 ? 'Forbidden' : status === 500 ? 'Internal Server Error' : 'OK',
      json: vi.fn().mockResolvedValue(body),
    })));
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
  workbench: object = syntheticAgentDefinitionWorkbench,
  catalog: (call: number) => Promise<object> | object = defaultCatalogResponse,
  probe?: (agentKey: AgentKey, body: Record<string, unknown>, call: number) => Promise<object> | object,
) {
  let putCall = 0;
  let catalogCall = 0;
  let probeCall = 0;
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (isCatalogUrl(url)) return catalog(catalogCall++);
    if (isWorkbenchUrl(url)) return apiResponse(200, workbench);
    if (isProbeUrl(url)) {
      if (!probe) throw new Error('unexpected probe POST');
      const agentKey = url.slice(0, -PROBE_SUFFIX.length).split('/').at(-1) as AgentKey;
      return probe(agentKey, JSON.parse(String(init?.body)) as Record<string, unknown>, probeCall++);
    }
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
  fireEvent.change(screen.getByRole('textbox', { name: 'Custom endpoint name' }), { target: { value: 'endpoint-a2' } });
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
      'Refresh models',
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
    expect(screen.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('databricks-claude-opus-4-6');
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
    expect(workbenchGets()).toHaveLength(1);
    expect(catalogGets()).toHaveLength(0);
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
    expect(screen.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-a2');
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
    expect(screen.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveAccessibleDescription('Endpoint rejected.');
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
    expect(screen.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-a2');
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
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    expect(catalogGets(fetchMock)).toHaveLength(0);
    expect(allGets(fetchMock)).toHaveLength(1);
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
  probe?: RouteResponder;
}) {
  const counts = { put: 0, upgrade: 0, source: 0, probe: 0 };
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (isCatalogUrl(url)) return defaultCatalogResponse();
    if (isWorkbenchUrl(url)) return apiResponse(200, syntheticAgentDefinitionWorkbench);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (isProbeUrl(url)) {
      const agentKey = url.slice(0, -PROBE_SUFFIX.length).split('/').at(-1) as AgentKey;
      if (!routes.probe) throw new Error('unexpected probe POST');
      return routes.probe(agentKey, body, counts.probe++);
    }
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
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    expect(catalogGets(fetchMock)).toHaveLength(0);
    expect(allGets(fetchMock)).toHaveLength(1);
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
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    expect(catalogGets(fetchMock)).toHaveLength(0);
    expect(allGets(fetchMock)).toHaveLength(1);
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
    ['probe architect', () => editor.probeStructuredOutput('architect')],
    ['probe builder', () => editor.probeStructuredOutput('builder')],
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
    ['double probe architect', () => {
      void editor.probeStructuredOutput('architect');
      void editor.probeStructuredOutput('architect');
    }],
    ['probe then save architect', () => {
      void editor.probeStructuredOutput('architect');
      void editor.save('architect');
    }],
    ['save then probe architect', () => {
      void editor.save('architect');
      void editor.probeStructuredOutput('architect');
    }],
    ['probe then schema upgrade builder', () => {
      void editor.probeStructuredOutput('architect');
      void editor.upgradeSchemaContract('builder');
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
      if (isCatalogUrl(url)) return Promise.resolve(defaultCatalogResponse());
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
    ['probe architect', 'save architect'],
    ['save architect', 'probe architect'],
    ['probe architect', 'upgrade architect'],
    ['upgrade architect', 'probe builder'],
    ['probe architect', 'schema upgrade architect'],
    ['schema upgrade architect', 'probe builder'],
    ['recover data analyst', 'probe architect'],
    ['probe architect', 'recover data analyst'],
    ['probe architect', 'probe builder'],
    ['probe architect', 'probe architect'],
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
    'double probe architect',
    'probe then save architect',
    'save then probe architect',
    'probe then schema upgrade builder',
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


// ============================================================
// #264 Task 6 fix round 1 — Output Schema tab (review I1, I2 M5, I3, I4)
// ============================================================

function workbenchWithArchitectSchemaV2(): AgentDefinitionWorkbenchResponse {
  const body: AgentDefinitionWorkbenchResponse = structuredClone(syntheticAgentDefinitionWorkbench);
  for (const node of body.nodes) {
    if (node.execution_kind === 'model' && node.agent_key === 'architect') {
      node.draft = syntheticSchemaV2DraftDefinition('architect');
    }
  }
  return body;
}

describe('AgentDefinitionWorkbench Output Schema tab', () => {
  it('toggling the picker, typing guidance and navigating send zero requests', async () => {
    const body = workbenchWithArchitectSchemaV2();
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (isCatalogUrl(url)) return defaultCatalogResponse();
      return isWorkbenchUrl(url) ? apiResponse(200, body) : apiResponse(500, null);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    const requests = () => fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole('tab', { name: 'Output Schema' }));
    expect(requests()).toBe(1);
    const picker = screen.getByRole('checkbox', { name: 'Select diagnostic_notes' });
    fireEvent.click(picker);
    expect(requests()).toBe(1);
    // The optional descriptor's text is code-owned: its row offers no textbox (#264 I2).
    const optional = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    expect(within(optional).queryAllByRole('textbox')).toEqual([]);
    const intent = screen.getByRole('group', { name: 'Canonical field: intent' });
    fireEvent.change(within(intent).getByRole('textbox', { name: 'Description guidance for intent' }), {
      target: { value: 'Intent guidance' },
    });
    expect(requests()).toBe(1);
    fireEvent.change(within(intent).getByRole('textbox', { name: 'Examples guidance for intent (JSON array)' }), {
      target: { value: '["build"]' },
    });
    expect(requests()).toBe(1);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' }));
    expect(requests()).toBe(1);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' }));
    expect(requests()).toBe(1);
    fireEvent.click(screen.getByRole('tab', { name: 'Assembly' }));
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    fireEvent.click(screen.getByRole('tab', { name: 'Output Schema' }));
    expect(requests()).toBe(1);

    // The edits were local and persisted across tab and role navigation.
    expect(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Description guidance for intent' })).toHaveValue('Intent guidance');
    expect(within(navigation).getByRole('button', { name: /Architect/ })).toHaveTextContent('Unsaved');
    expect(fetchMock.mock.calls.every(([, init]) => (init as RequestInit | undefined)?.method === 'GET')).toBe(true);
  });

  it('malformed examples block Save with a visible field error and send nothing; fixed guidance is sent', async () => {
    // Canonical guidance is editable only under a v2 schema contract (#264 I1).
    const fetchMock = mockWorkbenchWithPuts((agentKey, request) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, 1)), workbenchWithArchitectSchemaV2());
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    fireEvent.click(screen.getByRole('tab', { name: 'Output Schema' }));

    const intent = screen.getByRole('group', { name: 'Canonical field: intent' });
    fireEvent.change(within(intent).getByRole('textbox', { name: 'Description guidance for intent' }), {
      target: { value: 'Prefer build for new decks.' },
    });
    const examples = within(intent).getByRole('textbox', { name: 'Examples guidance for intent (JSON array)' });
    fireEvent.change(examples, { target: { value: '["build"' } });

    expect(within(intent).getByRole('alert')).toHaveTextContent('Examples must be a JSON array.');
    const saveButton = screen.getByRole('button', { name: 'Save Draft' });
    expect(saveButton).toBeDisabled();
    fireEvent.click(saveButton);
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.change(examples, { target: { value: '["build"]' } });
    expect(within(intent).queryByRole('alert')).toBeNull();
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    const sent = JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body)) as DraftSaveRequest;
    expect(sent.candidate.schema_overlay?.field_overrides.intent).toEqual({
      description: 'Prefer build for new decks.',
      examples: ['build'],
    });
  });

  it('links a Schema Upgrade already_current 422 to the Output Schema tab', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (isCatalogUrl(url)) return defaultCatalogResponse();
      if (isWorkbenchUrl(url)) return apiResponse(200, syntheticAgentDefinitionWorkbench);
      if (url.endsWith('/schema-contract-upgrade')) return apiResponse(422, SCHEMA_ALREADY_CURRENT_REJECTION);
      return apiResponse(500, null);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    fireEvent.click(screen.getByRole('tab', { name: 'Output Schema' }));
    fireEvent.click(screen.getByRole('button', { name: 'Schema Upgrade' }));

    const issues = await screen.findByRole('region', { name: 'Server rejected this request' });
    expect(issues).toHaveTextContent('schema_contract — already_current');
    expect(issues).toHaveTextContent('Schema contract is already current.');
    fireEvent.click(within(issues).getByRole('button', { name: 'Go to Output Schema tab' }));
    expect(screen.getByRole('tab', { name: 'Output Schema' })).toHaveAttribute('aria-selected', 'true');
  });

  it('a hook Save with malformed examples records the field error and allocates no request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useDraftEditor(syntheticAgentDefinitionWorkbench));
    act(() => result.current.editSchemaOverlayFieldExamples('architect', 'intent', 'not json'));
    await act(() => result.current.save('architect'));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.state.pendingSave).toBeNull();
    expect(result.current.state.byAgent.architect.fieldErrors).toEqual({
      'schema_overlay.field_overrides.intent.examples': 'Examples must be a JSON array.',
    });
  });
});

// ============================================================
// #266 Task 4 — typed discovery client and Model-tab endpoint controls
// ============================================================

const URL_NOT_ALLOWED = 'Endpoint must be a Databricks endpoint name, not a URL.';
const EMPTY_DISCOVERY = 'No Databricks foundation-model endpoints are available to this identity.';
const NO_SEARCH_MATCH = 'No discovered models match the search.';
const SEED_NUMERICS = { temperature: 0.7, max_tokens: 60000, top_p: 0.95 };

describe('getSystemModelEndpoints', () => {
  function stubFetch(response: unknown) {
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  async function rejection(promise: Promise<unknown>): Promise<unknown> {
    try {
      await promise;
    } catch (error) {
      return error;
    }
    throw new Error('expected a rejection');
  }

  it('reads the discovery list once with a bare GET and returns the exact items in server order', async () => {
    const response = apiResponse(200, syntheticModelEndpointDiscovery());
    const fetchMock = stubFetch(response);

    await expect(getSystemModelEndpoints()).resolves.toEqual(syntheticSystemModelEndpoints);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/model-endpoints$/);
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
    expect(response.json).toHaveBeenCalledTimes(1);
  });

  it('returns an empty list for an empty success', async () => {
    stubFetch(apiResponse(200, { items: [] }));
    await expect(getSystemModelEndpoints()).resolves.toEqual([]);
  });

  it('never caches or coalesces: every call makes its own GET', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => apiResponse(200, syntheticModelEndpointDiscovery()));
    vi.stubGlobal('fetch', fetchMock);
    await Promise.all([getSystemModelEndpoints(), getSystemModelEndpoints()]);
    await getSystemModelEndpoints();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  class EndpointLike {
    name = 'databricks-gpt-oss-120b';
    display_name = null;
    description = null;
    docs = null;
  }
  class EnvelopeLike {
    items = [];
  }
  const good = syntheticSystemModelEndpoints[1];

  it.each([
    ['a null body', null],
    ['an array body', []],
    ['a class-instance envelope', new EnvelopeLike()],
    ['an extra top-level key', { items: [good], total: 1 }],
    ['a missing items key', {}],
    ['items that are not an array', { items: { 0: good } }],
    ['an array item', { items: [[good.name]] }],
    ['a class-instance item', { items: [new EndpointLike()] }],
    ['an item missing docs', { items: [{ name: good.name, display_name: null, description: null }] }],
    ['an item with a task field', { items: [{ ...good, task: 'llm/v1/chat' }] }],
    ['a numeric name', { items: [{ ...good, name: 7 }] }],
    ['an empty name', { items: [{ ...good, name: '' }] }],
    ['a numeric display name', { items: [{ ...good, display_name: 4 }] }],
    ['a boolean description', { items: [{ ...good, description: false }] }],
    ['an object docs value', { items: [{ ...good, docs: { url: 'https://x.invalid' } }] }],
    ['duplicate names', { items: [good, { ...good }] }],
  ])('rejects a malformed 200 with %s as an invalid catalog response', async (_name, body) => {
    stubFetch(apiResponse(200, body));
    const error = await rejection(getSystemModelEndpoints());
    expect(error).toBeInstanceOf(InvalidModelEndpointCatalogResponseError);
    expect(error).not.toBeInstanceOf(ModelEndpointCatalogApiError);
  });

  it('rejects an unparseable 200 body as an invalid catalog response', async () => {
    stubFetch({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: vi.fn().mockRejectedValue(new SyntaxError('not JSON')),
    });
    await expect(getSystemModelEndpoints()).rejects.toBeInstanceOf(InvalidModelEndpointCatalogResponseError);
  });

  it.each([
    [403, MODEL_ENDPOINT_DISCOVERY_FORBIDDEN],
    [503, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE],
  ] as const)('throws the typed catalog error for a valid %i envelope', async (status, envelope) => {
    const response = apiResponse(status, envelope);
    stubFetch(response);
    const error = await rejection(getSystemModelEndpoints());

    expect(error).toBeInstanceOf(ModelEndpointCatalogApiError);
    const typed = error as ModelEndpointCatalogApiError;
    expect(typed.status).toBe(status);
    expect(typed.code).toBe(envelope.code);
    expect(typed.retryable).toBe(envelope.retryable);
    expect(typed.message).toBe(envelope.message);
    expect(response.json).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['403 admin denial', 403, { detail: 'Admin access required' }],
    ['403 with the unavailable code', 403, { ...MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE, retryable: false }],
    ['503 that is not retryable', 503, { ...MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE, retryable: false }],
    ['503 with an extra key', 503, { ...MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE, detail: 'x' }],
    ['503 with a numeric message', 503, { ...MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE, message: 5 }],
    ['500', 500, null],
    ['200-range but not 200', 204, null],
  ])('does not type a %s as a catalog envelope', async (_name, status, body) => {
    stubFetch({ ...apiResponse(status, body), ok: status >= 200 && status < 300 });
    const error = await rejection(getSystemModelEndpoints());
    expect(error).not.toBeInstanceOf(ModelEndpointCatalogApiError);
    expect(error).toBeInstanceOf(status === 204 ? InvalidModelEndpointCatalogResponseError : AgentDefinitionApiError);
  });

  it('propagates a network failure unchanged', async () => {
    const failure = new TypeError('network failed');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(failure));
    await expect(getSystemModelEndpoints()).rejects.toBe(failure);
  });
});

describe('local endpoint-name policy in validateDraftForm', () => {
  const form = (endpoint_name: string) => ({
    prompt_text: 'prompt',
    endpoint_name,
    temperature: 0.2,
    max_tokens: 10,
    top_p: 0.8,
    assembly_rules: null,
  });

  it.each(ENDPOINT_NAME_POLICY_CASES.rejected)('rejects URL- or path-shaped %j with the table message and no candidate', (name) => {
    const result = validateDraftForm(form(name));
    expect(result).toEqual({ ok: false, errors: { endpoint_name: URL_NOT_ALLOWED } });
  });

  it.each(ENDPOINT_NAME_POLICY_CASES.accepted)('accepts %j verbatim', (name) => {
    const result = validateDraftForm(form(name));
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.candidate.model.endpoint_name).toBe(name);
  });

  it('keeps the blank message for a blank name', () => {
    expect(validateDraftForm(form('  '))).toEqual({
      ok: false,
      errors: { endpoint_name: 'Endpoint name must not be blank.' },
    });
  });
});

function modelPanel() {
  return screen.getByRole('tabpanel', { name: 'Model' });
}

function openModelTab() {
  fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
  return modelPanel();
}

function customEndpoint() {
  return screen.getByRole('textbox', { name: 'Custom endpoint name' });
}

function discoveredNames() {
  const group = within(modelPanel()).queryByRole('radiogroup', { name: 'Discovered models' });
  if (!group) return [];
  return within(group).getAllByRole('radio').map((radio) => radio.getAttribute('value'));
}

function catalogResponse(items = syntheticSystemModelEndpoints) {
  return apiResponse(200, syntheticModelEndpointDiscovery(items));
}

function heldCatalog() {
  const pending: Array<(response: object) => void> = [];
  const responder = () => new Promise<object>((resolve) => { pending.push(resolve); });
  return { pending, responder };
}

function architectStatus(navigation: HTMLElement) {
  return within(navigation).getByRole('button', { name: /Architect/ });
}

describe('AgentDefinitionWorkbench Model-tab endpoint discovery', () => {
  it('fetches the catalog once on the first Model-tab opening of any role and again only on Refresh models', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    expect(catalogGets(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: 'Assembly' }));
    expect(catalogGets(fetchMock)).toHaveLength(0);

    openModelTab();
    await waitFor(() => expect(discoveredNames()).toEqual(syntheticSystemModelEndpoints.map((item) => item.name)));
    expect(catalogGets(fetchMock)).toHaveLength(1);
    const [url, init] = catalogGets(fetchMock)[0] as [string, RequestInit];
    expect(url).not.toContain('?');
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();

    // Every other role's editor is mounted too; none of them reads the catalog again.
    for (const role of ['Builder', 'Data Analyst', 'Deck Reviewer', 'Architect']) {
      fireEvent.click(within(navigation).getByRole('button', { name: role }));
      openModelTab();
      fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
      openModelTab();
    }
    expect(discoveredNames()).toEqual(syntheticSystemModelEndpoints.map((item) => item.name));
    expect(catalogGets(fetchMock)).toHaveLength(1);
    expect(workbenchGets(fetchMock)).toHaveLength(1);

    fireEvent.click(within(modelPanel()).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(catalogGets(fetchMock)).toHaveLength(2));
    fireEvent.click(within(modelPanel()).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(catalogGets(fetchMock)).toHaveLength(3));
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('exposes Refresh models, a labelled search, exact-name entries, and a separate custom endpoint field', async () => {
    mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();

    expect(within(panel).getByRole('button', { name: 'Refresh models' })).toBeEnabled();
    expect(within(panel).getByRole('searchbox', { name: 'Search discovered models' })).toHaveValue('');
    const group = await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    for (const item of syntheticSystemModelEndpoints) {
      // The accessible name of each entry is the exact endpoint name, never its display name.
      expect(within(group).getByRole('radio', { name: item.name })).toHaveAttribute('value', item.name);
    }
    expect(within(group).getAllByRole('radio')).toHaveLength(syntheticSystemModelEndpoints.length);
    expect(within(group).getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME })).toBeChecked();
    expect(within(panel).getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    // Display metadata is shown as description, not as the control's name.
    expect(within(group).getByRole('radio', { name: 'databricks-gpt-oss-120b' }))
      .toHaveAccessibleDescription(/GPT OSS 120B/);
    expectNoForbiddenActionNames();
  });

  it('selection copies exactly the item name into the endpoint form value and nothing else', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    const group = await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    for (const item of [syntheticSystemModelEndpoints[1], syntheticSystemModelEndpoints[2]]) {
      fireEvent.click(within(group).getByRole('radio', { name: item.name }));
      expect(customEndpoint()).toHaveValue(item.name);
      expect(within(group).getByRole('radio', { name: item.name })).toBeChecked();
      expect(within(group).getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME })).not.toBeChecked();
      expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue(SEED_NUMERICS.temperature);
      expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(SEED_NUMERICS.max_tokens);
      expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(SEED_NUMERICS.top_p);
    }
    expect(architectStatus(navigation)).toHaveTextContent('Unsaved');
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(catalogGets(fetchMock)).toHaveLength(1);
  });

  it('selection never saves: no PUT after the selection settles, and Save stays an explicit action', async () => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, 1)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    const group = await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    fireEvent.click(within(group).getByRole('radio', { name: 'databricks-gpt-oss-120b' }));
    await act(async () => { await new Promise((resolve) => { setTimeout(resolve, 0); }); });

    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(architectStatus(navigation)).toHaveTextContent('Unsaved');
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
  });

  it('searches locally and case-insensitively and reports no match without changing the selection', async () => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    const search = within(panel).getByRole('searchbox', { name: 'Search discovered models' });

    fireEvent.change(search, { target: { value: 'OPUS' } });
    expect(discoveredNames()).toEqual([SEED_MODEL_ENDPOINT_NAME]);
    fireEvent.change(search, { target: { value: 'gpt oss' } });
    expect(discoveredNames()).toEqual(['databricks-gpt-oss-120b']);
    fireEvent.change(search, { target: { value: 'OPEN-WEIGHT' } });
    expect(discoveredNames()).toEqual(['databricks-gpt-oss-120b']);
    fireEvent.change(search, { target: { value: 'team shared' } });
    expect(discoveredNames()).toEqual(['Team Shared Endpoint (EU)']);
    fireEvent.change(search, { target: { value: 'no-such-model' } });
    expect(discoveredNames()).toEqual([]);
    expect(panel).toHaveTextContent(NO_SEARCH_MATCH);

    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(architectStatus(navigation)).not.toHaveTextContent('Unsaved');
    fireEvent.change(search, { target: { value: '' } });
    expect(within(panel).getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME })).toBeChecked();
    expect(catalogGets(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('says exactly when no foundation-model endpoint is available and keeps the saved endpoint', async () => {
    mockWorkbenchWithPuts(() => apiResponse(500, null), syntheticAgentDefinitionWorkbench, () => catalogResponse([]));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();

    expect(await within(panel).findByText(EMPTY_DISCOVERY)).toBeVisible();
    expect(within(panel).queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
  });

  it.each([
    [503, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE.message, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE],
    [403, MODEL_ENDPOINT_DISCOVERY_FORBIDDEN.message, MODEL_ENDPOINT_DISCOVERY_FORBIDDEN],
    [500, 'Unable to load discovered models (500).', null],
    // A workbench body answered on the catalog URL is exactly the misrouting c17 names.
    [200, 'Model discovery returned an invalid response.', syntheticAgentDefinitionWorkbench],
  ])('a %i failure is an alert that preserves the saved endpoint and recovers through Refresh models', async (status, message, failureBody) => {
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      (call) => (call === 0 ? apiResponse(status, failureBody) : catalogResponse()),
    );
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();

    const alert = await within(panel).findByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(within(panel).queryByText(EMPTY_DISCOVERY)).not.toBeInTheDocument();
    expect(within(panel).queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(architectStatus(navigation)).not.toHaveTextContent('Unsaved');
    const refresh = within(panel).getByRole('button', { name: 'Refresh models' });
    expect(refresh).toBeEnabled();

    fireEvent.click(refresh);
    await waitFor(() => expect(discoveredNames()).toEqual(syntheticSystemModelEndpoints.map((item) => item.name)));
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    expect(catalogGets(fetchMock)).toHaveLength(2);
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('a network failure is a retryable alert, not an empty catalog', async () => {
    mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      (call) => (call === 0 ? Promise.reject(new TypeError('network failed')) : catalogResponse()),
    );
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    expect(await within(panel).findByRole('alert'))
      .toHaveTextContent('Unable to load discovered models. Check your connection and try again.');
    expect(within(panel).queryByText(EMPTY_DISCOVERY)).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(discoveredNames()).toHaveLength(syntheticSystemModelEndpoints.length));
  });

  it('refresh replaces the prior list only after a success and keeps it through loading and failure', async () => {
    const held = heldCatalog();
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      (call) => (call === 0 ? catalogResponse() : held.responder()),
    );
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    const original = syntheticSystemModelEndpoints.map((item) => item.name);
    await waitFor(() => expect(discoveredNames()).toEqual(original));

    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(held.pending).toHaveLength(1));
    expect(panel).toHaveTextContent('Loading discovered models');
    expect(discoveredNames()).toEqual(original);
    await act(async () => { held.pending[0](apiResponse(503, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE)); });
    expect(await within(panel).findByRole('alert')).toHaveTextContent(MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE.message);
    expect(discoveredNames()).toEqual(original);

    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(held.pending).toHaveLength(2));
    const refreshed = [syntheticNewerModelEndpoint, syntheticSystemModelEndpoints[1]];
    await act(async () => { held.pending[1](catalogResponse(refreshed)); });
    await waitFor(() => expect(discoveredNames()).toEqual(refreshed.map((item) => item.name)));
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    expect(catalogGets(fetchMock)).toHaveLength(3);
  });

  it('an older refresh response never overwrites the newest one', async () => {
    const held = heldCatalog();
    mockWorkbenchWithPuts(() => apiResponse(500, null), syntheticAgentDefinitionWorkbench, held.responder);
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await waitFor(() => expect(held.pending).toHaveLength(1));
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(held.pending).toHaveLength(2));

    const newest = [syntheticNewerModelEndpoint];
    await act(async () => { held.pending[1](catalogResponse(newest)); });
    await waitFor(() => expect(discoveredNames()).toEqual([syntheticNewerModelEndpoint.name]));
    await act(async () => { held.pending[0](catalogResponse()); });
    await act(async () => { await Promise.resolve(); });
    expect(discoveredNames()).toEqual([syntheticNewerModelEndpoint.name]);

    // A stale failure cannot overwrite the newest success either.
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await waitFor(() => expect(held.pending).toHaveLength(4));
    await act(async () => { held.pending[3](catalogResponse(syntheticSystemModelEndpoints)); });
    await waitFor(() => expect(discoveredNames()).toHaveLength(syntheticSystemModelEndpoints.length));
    await act(async () => { held.pending[2](apiResponse(503, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE)); });
    await act(async () => { await Promise.resolve(); });
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
  });

  it('a newer discovered item never moves the seed until it is explicitly selected and saved', async () => {
    const fetchMock = mockWorkbenchWithPuts(
      (agentKey, request) => apiResponse(200, saveSuccess(agentKey, request.candidate, 1)),
      syntheticAgentDefinitionWorkbench,
      (call) => (call === 0
        ? catalogResponse()
        : catalogResponse([syntheticNewerModelEndpoint, ...syntheticSystemModelEndpoints])),
    );
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    const statusBefore = architectStatus(navigation).textContent;

    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await within(panel).findByRole('radio', { name: syntheticNewerModelEndpoint.name });
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(within(panel).getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME })).toBeChecked();
    expect(within(panel).getByRole('radio', { name: syntheticNewerModelEndpoint.name })).not.toBeChecked();
    expect(architectStatus(navigation).textContent).toBe(statusBefore);
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(within(panel).getByRole('radio', { name: syntheticNewerModelEndpoint.name }));
    expect(putCalls(fetchMock)).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    expect(JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body))).toEqual({
      lock_version: 0,
      candidate: {
        prompt_text: modelNode('architect').draft.prompt_text,
        model: { endpoint_name: syntheticNewerModelEndpoint.name, ...SEED_NUMERICS },
      },
    });
    await waitFor(() => expect(architectStatus(navigation)).toHaveTextContent('Needs test'));
    expect(customEndpoint()).toHaveValue(syntheticNewerModelEndpoint.name);
  });

  it('keeps same-content Save enabled with the catalog loaded', async () => {
    const fetchMock = mockWorkbenchWithPuts((agentKey, request) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, 1, false)));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    // Re-selecting the already-selected seed is not an edit.
    fireEvent.click(within(panel).getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME }));

    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    expect((JSON.parse(String((putCalls(fetchMock)[0][1] as RequestInit).body)) as DraftSaveRequest)
      .candidate.model.endpoint_name).toBe(SEED_MODEL_ENDPOINT_NAME);
  });

  it.each([
    'https://example.cloud.databricks.com/serving-endpoints/x/invocations',
    'serving-endpoints/../secrets',
    'x?token=abc',
  ])('a URL- or path-shaped custom name %j shows the local table message and sends zero PUT', async (value) => {
    const fetchMock = mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    fireEvent.change(customEndpoint(), { target: { value } });
    expect(customEndpoint()).toHaveAccessibleDescription(URL_NOT_ALLOWED);
    expect(within(panel).getByRole('alert')).toHaveTextContent(URL_NOT_ALLOWED);
    expect(customEndpoint()).toHaveValue(value);
    const save = screen.getByRole('button', { name: 'Save Draft' });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    await act(async () => { await Promise.resolve(); });
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(within(panel).queryByRole('radio', { checked: true })).not.toBeInTheDocument();

    fireEvent.change(customEndpoint(), { target: { value: 'corrected-endpoint' } });
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    expect(save).toBeEnabled();
  });

  it('saves a manual exact name as only the lock plus the five editable leaves and retains it', async () => {
    const manual = 'Team Exact Endpoint 9';
    const fetchMock = mockWorkbenchWithPuts((agentKey, request) =>
      apiResponse(200, saveSuccess(agentKey, request.candidate, 1)));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    expect(discoveredNames()).not.toContain(manual);

    fireEvent.change(customEndpoint(), { target: { value: manual } });
    expect(within(panel).queryByRole('radio', { checked: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));

    const raw = String((putCalls(fetchMock)[0][1] as RequestInit).body);
    const body = JSON.parse(raw) as DraftSaveRequest;
    expect(Object.keys(body).sort()).toEqual(['candidate', 'lock_version']);
    expect(Object.keys(body.candidate).sort()).toEqual(['model', 'prompt_text']);
    expect(Object.keys(body.candidate.model).sort()).toEqual(['endpoint_name', 'max_tokens', 'temperature', 'top_p']);
    expect(body).toEqual({
      lock_version: 0,
      candidate: {
        prompt_text: modelNode('architect').draft.prompt_text,
        model: { endpoint_name: manual, ...SEED_NUMERICS },
      },
    });
    expect(body.candidate.model.endpoint_name).toBe(manual);
    for (const forbidden of [
      '"display_name"', '"docs"', '"description"', '"items"', '"name"', '"host"', '"token"',
      '"task"', '"provider"', '"url"', 'http', '://',
      ...syntheticSystemModelEndpoints.flatMap((item) => [item.display_name, item.description, item.docs])
        .filter((value): value is string => value !== null),
    ]) {
      expect(raw).not.toContain(forbidden);
    }

    await waitFor(() => expect(architectStatus(navigation)).toHaveTextContent('Needs test'));
    expect(customEndpoint()).toHaveValue(manual);
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version1');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('binds a typed server endpoint issue to the custom field, keeps every unsaved value, and retries without remount', async () => {
    const missing = 'Team Missing Endpoint';
    const corrected = 'Team Found Endpoint';
    const fetchMock = mockWorkbenchWithPuts((agentKey, request, call) => (call === 0
      ? apiResponse(422, {
        code: 'invalid_draft',
        errors: [{
          field: 'candidate.model.endpoint_name',
          code: 'endpoint_unknown',
          message: 'Endpoint name was not found.',
        }],
      })
      : apiResponse(200, saveSuccess(agentKey, request.candidate, 1))));
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect unsaved prompt' } });
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    const endpointInput = customEndpoint();
    fireEvent.change(endpointInput, { target: { value: missing } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '0.3' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Top-p' }), { target: { value: '0.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));

    await waitFor(() => expect(customEndpoint()).toHaveAccessibleDescription('Endpoint name was not found.'));
    const alerts = within(panel).getAllByRole('alert');
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent('Endpoint name was not found.');
    expect(alerts[0].textContent).not.toContain(missing);
    expect(screen.queryByRole('region', { name: 'Server rejected this request' })).not.toBeInTheDocument();
    expect(customEndpoint()).toBe(endpointInput);
    expect(customEndpoint()).toHaveValue(missing);
    expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue(0.3);
    expect(screen.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue(SEED_NUMERICS.max_tokens);
    expect(screen.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue(0.5);
    expect(architectStatus(navigation)).toHaveTextContent('Unsaved');
    fireEvent.click(screen.getByRole('tab', { name: 'Prompt' }));
    expect(screen.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect unsaved prompt');
    openModelTab();

    fireEvent.change(customEndpoint(), { target: { value: corrected } });
    expect(customEndpoint()).not.toHaveAccessibleDescription('Endpoint name was not found.');
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(2));
    const second = JSON.parse(String((putCalls(fetchMock)[1][1] as RequestInit).body)) as DraftSaveRequest;
    expect(second).toEqual({
      lock_version: 0,
      candidate: {
        prompt_text: 'Architect unsaved prompt',
        model: { endpoint_name: corrected, temperature: 0.3, max_tokens: SEED_NUMERICS.max_tokens, top_p: 0.5 },
      },
    });
    await waitFor(() => expect(architectStatus(navigation)).toHaveTextContent('Needs test'));
    expect(customEndpoint()).toBe(endpointInput);
    expect(customEndpoint()).toHaveValue(corrected);
    expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    expect(catalogGets(fetchMock)).toHaveLength(1);
  });

  it('the catalog read stays outside the one pending gate in both directions', async () => {
    const held = heldCatalog();
    let releasePut!: (response: object) => void;
    const heldPut = new Promise<object>((resolve) => { releasePut = resolve; });
    const fetchMock = mockWorkbenchWithPuts(() => heldPut, syntheticAgentDefinitionWorkbench, held.responder);
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await waitFor(() => expect(held.pending).toHaveLength(1));

    // A catalog load in flight does not block Save.
    const save = screen.getByRole('button', { name: 'Save Draft' });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    expect(save).toBeDisabled();

    // A pending Save does not block catalog recovery.
    const refresh = within(panel).getByRole('button', { name: 'Refresh models' });
    expect(refresh).toBeEnabled();
    fireEvent.click(refresh);
    await waitFor(() => expect(held.pending).toHaveLength(2));
    await act(async () => { held.pending[1](catalogResponse()); });
    await waitFor(() => expect(discoveredNames()).toHaveLength(syntheticSystemModelEndpoints.length));
    expect(save).toBeDisabled();

    releasePut(apiResponse(200, saveSuccess('architect', {
      prompt_text: modelNode('architect').draft.prompt_text,
      model: { endpoint_name: SEED_MODEL_ENDPOINT_NAME, ...SEED_NUMERICS },
    }, 1)));
    await waitFor(() => expect(architectStatus(navigation)).toHaveTextContent('Needs test'));
    expect(save).toBeEnabled();
    expect(putCalls(fetchMock)).toHaveLength(1);
  });
});

// ============================================================
// #266 Task 6 — explicit structured-output probe of the saved candidate
// ============================================================

const PROBE_BUTTON = 'Test structured output';
const PROBE_RETRY_BUTTON = 'Retry structured output test';
const PROBE_RESULT_REGION = 'Structured output test result';
const PROBE_SUCCEEDED_TEXT = 'Structured output test succeeded for the saved candidate.';
const PROBE_UNSAVED_HINT = 'Save the endpoint before testing structured output.';
const PROBE_NETWORK_MESSAGE = 'Unable to test structured output. Check your connection and try again.';
const PROBE_IDENTITY_TEXT = (endpoint: string, hash: string, lock: number) =>
  `Endpoint ${endpoint} · Candidate hash ${hash} · Draft lock ${lock}`;

function probeButton() {
  return within(modelPanel()).getByRole('button', { name: PROBE_BUTTON });
}

function probeResult() {
  return within(modelPanel()).queryByRole('region', { name: PROBE_RESULT_REGION });
}

function probeBody(fetchMock: ReturnType<typeof vi.fn>, index: number) {
  return String((probeCalls(fetchMock)[index][1] as RequestInit).body);
}

function heldResponses() {
  const pending: Array<(response: object) => void> = [];
  const responder = () => new Promise<object>((resolve) => { pending.push(resolve); });
  return { pending, responder };
}

describe('AgentDefinitionWorkbench structured-output probe', () => {
  it('Test structured output sends one lock-only POST for the saved candidate and reports its exact identity without a write', async () => {
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      defaultCatalogResponse,
      () => apiResponse(200, syntheticProbeSuccess()),
    );
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    const statusBefore = architectStatus(navigation).textContent;
    expect(probeResult()).not.toBeInTheDocument();
    expect(probeCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());

    expect(probeCalls(fetchMock)).toHaveLength(1);
    const [url, init] = probeCalls(fetchMock)[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/architect\/model-endpoint-probe$/);
    expect(url).not.toContain('?');
    expect(init.method).toBe('POST');
    expect(probeBody(fetchMock, 0)).toBe('{"lock_version":0}');

    const region = probeResult()!;
    expect(region).toHaveTextContent(PROBE_SUCCEEDED_TEXT);
    expect(region).toHaveTextContent(PROBE_IDENTITY_TEXT(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 0));
    expect(within(region).queryByRole('alert')).not.toBeInTheDocument();
    // Success approves nothing: no status, lock, form or write moves.
    expect(region.textContent).not.toMatch(/approv|publish|release|ready|verified|passed/i);
    expect(architectStatus(navigation).textContent).toBe(statusBefore);
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(catalogGets(fetchMock)).toHaveLength(1);
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    expect(within(region).queryByRole('button', { name: PROBE_RETRY_BUTTON })).not.toBeInTheDocument();
    expectNoForbiddenActionNames();
  });

  it('probes the saved endpoint, never a newer discovered family member that was not selected and saved', async () => {
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      (call) => (call === 0
        ? catalogResponse()
        : catalogResponse([syntheticNewerModelEndpoint, ...syntheticSystemModelEndpoints])),
      () => apiResponse(200, syntheticProbeSuccess()),
    );
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh models' }));
    await within(panel).findByRole('radio', { name: syntheticNewerModelEndpoint.name });

    expect(probeButton()).toBeEnabled();
    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());

    expect(probeBody(fetchMock, 0)).toBe('{"lock_version":0}');
    expect(probeBody(fetchMock, 0)).not.toContain(syntheticNewerModelEndpoint.name);
    expect(probeResult()).toHaveTextContent(PROBE_IDENTITY_TEXT(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 0));
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(within(panel).getByRole('radio', { name: syntheticNewerModelEndpoint.name })).not.toBeChecked();
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('is disabled while the local endpoint is unsaved, and probes the newly saved candidate once it is saved', async () => {
    const newer = 'databricks-gpt-oss-120b';
    const fetchMock = mockWorkbenchWithPuts(
      (agentKey, request) => apiResponse(200, saveSuccess(agentKey, request.candidate, 1)),
      syntheticAgentDefinitionWorkbench,
      defaultCatalogResponse,
      () => apiResponse(200, syntheticProbeSuccess({ endpoint_name: newer, candidate_hash: 'd'.repeat(64), lock_version: 1 })),
    );
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    // An unsaved non-endpoint edit does not block it: the probe reads the saved candidate.
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '0.5' } });
    expect(probeButton()).toBeEnabled();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: String(SEED_NUMERICS.temperature) } });

    fireEvent.click(within(panel).getByRole('radio', { name: newer }));
    expect(probeButton()).toBeDisabled();
    expect(panel).toHaveTextContent(PROBE_UNSAVED_HINT);
    fireEvent.click(probeButton());
    fireEvent.change(customEndpoint(), { target: { value: 'Team Manual Endpoint' } });
    expect(probeButton()).toBeDisabled();
    fireEvent.click(probeButton());
    await act(async () => { await Promise.resolve(); });
    expect(probeCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(within(panel).getByRole('radio', { name: newer }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    await waitFor(() => expect(architectStatus(navigation)).toHaveTextContent('Needs test'));
    expect(probeButton()).toBeEnabled();
    expect(panel).not.toHaveTextContent(PROBE_UNSAVED_HINT);

    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());
    expect(probeBody(fetchMock, 0)).toBe('{"lock_version":1}');
    expect(probeResult()).toHaveTextContent(PROBE_IDENTITY_TEXT(newer, 'd'.repeat(64), 1));
    expect(architectStatus(navigation)).toHaveTextContent('Needs test');
    expect(putCalls(fetchMock)).toHaveLength(1);
  });

  it('clears an old result when the local endpoint changes, even back to the saved name', async () => {
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      defaultCatalogResponse,
      () => apiResponse(200, syntheticProbeSuccess()),
    );
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());

    fireEvent.change(customEndpoint(), { target: { value: 'endpoint-b' } });
    expect(probeResult()).not.toBeInTheDocument();
    fireEvent.change(customEndpoint(), { target: { value: SEED_MODEL_ENDPOINT_NAME } });
    expect(probeResult()).not.toBeInTheDocument();
    expect(probeCalls(fetchMock)).toHaveLength(1);

    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());
    expect(probeCalls(fetchMock)).toHaveLength(2);
  });

  it.each([
    'unsupported_structured_output',
    'endpoint_probe_forbidden',
    'structured_output_probe_failed',
  ] as const)('renders the sanitized %s result and offers Retry only when it is retryable', async (code) => {
    const { status, message, retryable } = STRUCTURED_OUTPUT_PROBE_FAILURES[code];
    const fetchMock = mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      defaultCatalogResponse,
      (_agentKey, _body, call) => (call === 0
        ? apiResponse(status, syntheticProbeFailure(code))
        : apiResponse(200, syntheticProbeSuccess())),
    );
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    const statusBefore = architectStatus(navigation).textContent;

    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toBeInTheDocument());
    const region = probeResult()!;
    const alert = within(region).getByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(region).toHaveTextContent(PROBE_IDENTITY_TEXT(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 0));
    expect(region).not.toHaveTextContent(PROBE_SUCCEEDED_TEXT);
    expect(screen.queryByRole('region', { name: 'Server rejected this request' })).not.toBeInTheDocument();
    expect(architectStatus(navigation).textContent).toBe(statusBefore);
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(probeButton()).toBeEnabled();
    expectNoForbiddenActionNames();

    const retry = within(region).queryByRole('button', { name: PROBE_RETRY_BUTTON });
    if (!retryable) {
      expect(retry).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
      expect(probeCalls(fetchMock)).toHaveLength(1);
      return;
    }
    expect(retry).toBeEnabled();
    fireEvent.click(retry!);
    await waitFor(() => expect(probeResult()).toHaveTextContent(PROBE_SUCCEEDED_TEXT));
    expect(probeCalls(fetchMock)).toHaveLength(2);
    expect(probeBody(fetchMock, 1)).toBe('{"lock_version":0}');
    expect(within(probeResult()!).queryByRole('alert')).not.toBeInTheDocument();
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('a pending probe holds the one gate on every role while the catalog read stays outside it', async () => {
    const held = heldResponses();
    const fetchMock = mockWorkbenchApi({
      probe: held.responder,
      put: (agentKey, body) => apiResponse(200, saveSuccess(agentKey, body.candidate as EditableModelDraft, 1)),
      upgrade: () => apiResponse(500, null),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    fireEvent.click(probeButton());
    await waitFor(() => expect(held.pending).toHaveLength(1));
    expect(probeButton()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    expect(within(modelPanel()).getByRole('button', { name: 'Refresh models' })).toBeEnabled();
    fireEvent.click(probeButton());
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    fireEvent.click(within(navigation).getByRole('button', { name: /Data Analyst/ }));
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    const upgrade = within(assemblyPanel()).getByRole('button', { name: 'Upgrade protected assembly' });
    expect(upgrade).toBeDisabled();
    fireEvent.click(upgrade);
    openModelTab();
    expect(probeButton()).toBeDisabled();
    fireEvent.click(probeButton());
    await act(async () => { await Promise.resolve(); });
    expect(probeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(upgradeCalls(fetchMock)).toHaveLength(0);

    await act(async () => { held.pending[0](apiResponse(200, syntheticProbeSuccess())); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
    expect(probeButton()).toBeEnabled();
    // The result belongs to Architect; Data Analyst shows none.
    expect(probeResult()).not.toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    openModelTab();
    expect(probeResult()).toHaveTextContent(PROBE_SUCCEEDED_TEXT);
  });

  it('a pending Save disables Test structured output on every role', async () => {
    let releasePut!: (response: object) => void;
    const heldPut = new Promise<object>((resolve) => { releasePut = resolve; });
    const fetchMock = mockWorkbenchApi({ put: () => heldPut, probe: () => apiResponse(200, syntheticProbeSuccess()) });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(putCalls(fetchMock)).toHaveLength(1);

    openModelTab();
    expect(probeButton()).toBeDisabled();
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    openModelTab();
    expect(probeButton()).toBeDisabled();
    fireEvent.click(probeButton());
    expect(probeCalls(fetchMock)).toHaveLength(0);

    releasePut(apiResponse(200, saveSuccess('architect', {
      prompt_text: 'Architect A2',
      model: structuredClone(modelNode('architect').draft.model),
    }, 1)));
    await waitFor(() => expect(probeButton()).toBeEnabled());
  });

  it('a probe 409 recovers all seven roles and the next explicit probe sends the adopted lock', async () => {
    const fetchMock = mockWorkbenchApi({
      probe: (_agentKey, _body, call) => (call === 0
        ? apiResponse(409, syntheticNullCandidateConflict(0, 1))
        : apiResponse(200, syntheticProbeSuccess({ lock_version: 1 }))),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    fireEvent.click(probeButton());
    const conflict = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(conflict).toHaveTextContent('Expected lock 0; Current lock 1');
    expect(within(conflict).queryByRole('group', { name: 'Submitted values' })).not.toBeInTheDocument();
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version1');
    expect(probeResult()).not.toBeInTheDocument();
    expect(customEndpoint()).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(probeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.click(probeButton());
    await waitFor(() => expect(probeResult()).toHaveTextContent(PROBE_SUCCEEDED_TEXT));
    expect(probeBody(fetchMock, 1)).toBe('{"lock_version":1}');
    expect(probeResult()).toHaveTextContent(PROBE_IDENTITY_TEXT(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 1));
    expect(workbenchGets(fetchMock)).toHaveLength(1);
  });

  it.each([
    ['a network failure', () => Promise.reject(new TypeError('network failed')), PROBE_NETWORK_MESSAGE],
    ['an untyped 500', () => apiResponse(500, { detail: 'Traceback: secret-host.example' }), 'Unable to test structured output (500).'],
    ['a malformed 200', () => apiResponse(200, { code: 'structured_output_probe_succeeded' }), 'Unable to test structured output because the server response was invalid.'],
  ])('%s is a contained alert with no result, no leak, and no automatic retry', async (_name, respond, message) => {
    const fetchMock = mockWorkbenchApi({ probe: respond });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();
    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });

    fireEvent.click(probeButton());
    const alert = await screen.findByText(message);
    expect(alert).toHaveAttribute('role', 'alert');
    expect(document.body).not.toHaveTextContent('secret-host.example');
    expect(probeResult()).not.toBeInTheDocument();
    expect(probeButton()).toBeEnabled();
    await act(async () => { await Promise.resolve(); });
    expect(probeCalls(fetchMock)).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('a hook probe with an unsaved endpoint allocates no request, and a saved one sends only the lock', async () => {
    const fetchMock = vi.fn().mockResolvedValue(apiResponse(200, syntheticProbeSuccess()));
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useDraftEditor(syntheticAgentDefinitionWorkbench));

    act(() => result.current.edit('architect', 'endpoint_name', 'databricks-claude-opus-4-7'));
    await act(() => result.current.probeStructuredOutput('architect'));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.state.pendingSave).toBeNull();

    await act(() => result.current.probeStructuredOutput('builder'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/draft\/builder\/model-endpoint-probe$/);
    expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBe('{"lock_version":0}');
    expect(result.current.state.byAgent.builder.probeResult).toEqual({
      outcome: 'succeeded',
      endpoint_name: SEED_MODEL_ENDPOINT_NAME,
      candidate_hash: SEED_CANDIDATE_HASH,
      lock_version: 0,
    });
    expect(result.current.state.draft.lock_version).toBe(0);
  });
});
