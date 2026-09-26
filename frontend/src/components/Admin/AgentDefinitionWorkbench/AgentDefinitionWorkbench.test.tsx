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
  syntheticAgentTestCase,
  syntheticAgentTestCaseList,
  syntheticInvalidTestCase,
  syntheticStaleTestCase,
  syntheticTestRunEvidence,
  syntheticTestRunUnavailable,
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

/**
 * #267's routes are routed by URL too (C38): a candidate run, a published-baseline
 * rerun, the case list, a case create and a case retire. Harnesses that do not answer
 * them throw, like the unrouted-probe tripwire, so none can be answered as a PUT.
 */
const CANDIDATE_RUN_URL = /\/api\/admin\/agent-definitions\/draft\/([a-z_]+)\/test-runs$/;
const BASELINE_RUN_URL = /\/api\/admin\/agent-definitions\/published\/([a-z_]+)\/test-runs$/;
const TEST_CASES_URL = /\/api\/admin\/agent-definitions\/test-cases(?:\?agent_key=([a-z_]+))?$/;
const TEST_CASE_URL = /\/api\/admin\/agent-definitions\/test-cases\/(\d+)$/;
const TEST_CASE_RUNS_URL = /\/api\/admin\/agent-definitions\/test-cases\/(\d+)\/runs\?limit=100$/;

function isAgentTestUrl(url: unknown) {
  const text = String(url);
  // Singular stems, so a mistyped path cannot fall through to the PUT route either.
  return text.includes('/test-run') || text.includes('/test-case');
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
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => {
    if (isAgentTestUrl(url)) throw new Error(`unexpected Agent Test request ${url}`);
    return mockedResponse(url, status, body);
  }));
}

function mockedResponse(url: string, status: number, body: unknown) {
  return (isCatalogUrl(url)
    ? defaultCatalogResponse()
    : {
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 403 ? 'Forbidden' : status === 500 ? 'Internal Server Error' : 'OK',
      json: vi.fn().mockResolvedValue(body),
    });
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
    if (isAgentTestUrl(url)) throw new Error(`unexpected Agent Test request ${init?.method} ${url}`);
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
    expect(ALLOWED_ACTION_NAMES).toHaveLength(5);
    // An exempt name is removed, not treated as a licence for the rest of the string.
    expect(forbidsActionName('Restore saved prompt and publish')).toBe(true);
    expect(forbidsActionName('Restore retained values, then approve')).toBe(true);
    // #267's two run controls are exempt by exact name only (C25/C38): the `run` stem
    // still bans every other run control, and neither name shields a banned suffix.
    expect(forbidsActionName('Run test case and publish')).toBe(true);
    expect(forbidsActionName('Run published baseline, then approve')).toBe(true);
    expect(forbidsActionName('Run isolated test')).toBe(true);
    expect(forbidsActionName('View run 12')).toBe(true);
    // Exemptions match the whole name exactly, never as a substring (review m-5).
    for (const near of ['Run test cases', 'Run test case now', 'run test case', 'Rerun: Run published baseline']) {
      expect(forbidsActionName(near), near).toBe(true);
    }
    // Surrounding and repeated whitespace is not part of a name.
    expect(forbidsActionName('  Run test case ')).toBe(false);
  });

  it('spares every other name the panel actually renders', () => {
    for (const name of [
      'Save Draft', 'Keep local', 'Reload server', 'Upgrade protected assembly',
      'Add custom block After authored prompt', 'Add custom block After deck brief',
      'Add custom block After environment constraints', 'Go to Assembly tab',
      'Go to Prompt tab', 'Delete custom block 1 at After authored prompt',
      'Move custom block 1 up', 'Move custom block 1 down', 'Discard retained values',
      'Refresh models',
      'Load Agent Test Cases', 'Refresh test cases', 'Add test case', 'Save test case',
      'Cancel', 'Retire test case', 'Confirm retire', 'Keep test case', 'Edit test case',
      'Save new version',
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
    // #267 replaced the "not available" notice with the Agent Test Case panel, which
    // reads nothing until the admin asks for the role's cases.
    const aside = screen.getByRole('complementary', { name: 'Isolated testing' });
    expect(within(aside).getByRole('button', { name: 'Load Agent Test Cases' })).toBeEnabled();
    expect(screen.queryByText('Isolated testing is not available in this release.')).not.toBeInTheDocument();
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

type TestCaseListResponder = (agentKey: AgentKey, call: number) => Promise<object> | object;
type TestCaseRetireResponder = (testCaseId: number, call: number) => Promise<object> | object;

function mockWorkbenchApi(routes: {
  put?: RouteResponder;
  upgrade?: RouteResponder;
  source?: RouteResponder;
  probe?: RouteResponder;
  candidateRun?: RouteResponder;
  baselineRun?: RouteResponder;
  listCases?: TestCaseListResponder;
  createCase?: RouteResponder;
  retireCase?: TestCaseRetireResponder;
  updateCase?: (testCaseId: number, body: Record<string, unknown>, call: number) => Promise<object> | object;
  listRuns?: (testCaseId: number, call: number) => Promise<object> | object;
}) {
  const counts = {
    put: 0, upgrade: 0, source: 0, probe: 0,
    candidateRun: 0, baselineRun: 0, listCases: 0, createCase: 0, retireCase: 0, updateCase: 0, listRuns: 0,
  };
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (isCatalogUrl(url)) return defaultCatalogResponse();
    if (isWorkbenchUrl(url)) return apiResponse(200, syntheticAgentDefinitionWorkbench);
    // #267's bodyless GET and DELETE are routed before any body is parsed.
    const listMatch = TEST_CASES_URL.exec(url);
    if (listMatch && init?.method === 'GET') {
      if (!routes.listCases) throw new Error('unexpected test case list GET');
      return routes.listCases(listMatch[1] as AgentKey, counts.listCases++);
    }
    const runsMatch = TEST_CASE_RUNS_URL.exec(url);
    if (runsMatch && init?.method === 'GET') {
      if (!routes.listRuns) throw new Error('unexpected test run history GET');
      return routes.listRuns(Number(runsMatch[1]), counts.listRuns++);
    }
    const retireMatch = TEST_CASE_URL.exec(url);
    if (retireMatch && init?.method === 'DELETE') {
      if (!routes.retireCase) throw new Error('unexpected test case DELETE');
      return routes.retireCase(Number(retireMatch[1]), counts.retireCase++);
    }
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    const candidateMatch = CANDIDATE_RUN_URL.exec(url);
    if (candidateMatch && init?.method === 'POST') {
      if (!routes.candidateRun) throw new Error('unexpected candidate test run POST');
      return routes.candidateRun(candidateMatch[1] as AgentKey, body, counts.candidateRun++);
    }
    const baselineMatch = BASELINE_RUN_URL.exec(url);
    if (baselineMatch && init?.method === 'POST') {
      if (!routes.baselineRun) throw new Error('unexpected published baseline test run POST');
      return routes.baselineRun(baselineMatch[1] as AgentKey, body, counts.baselineRun++);
    }
    const updateMatch = TEST_CASE_URL.exec(url);
    if (updateMatch && init?.method === 'PUT') {
      if (!routes.updateCase) throw new Error('unexpected test case PUT');
      return routes.updateCase(Number(updateMatch[1]), body, counts.updateCase++);
    }
    if (listMatch && init?.method === 'POST') {
      if (!routes.createCase) throw new Error('unexpected test case POST');
      return routes.createCase(body.agent_key as AgentKey, body, counts.createCase++);
    }
    if (isAgentTestUrl(url)) throw new Error(`unrouted Agent Test request ${init?.method} ${url}`);
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

  it.each([
    ['forbidden', 403, MODEL_ENDPOINT_DISCOVERY_FORBIDDEN, MODEL_ENDPOINT_DISCOVERY_FORBIDDEN.message],
    [
      'unavailable',
      503,
      MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE,
      `${MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE.message} Use Refresh models to try again.`,
    ],
  ])('a %s catalog alert offers a retry only when the failure is retryable', async (_label, status, failureBody, expected) => {
    mockWorkbenchWithPuts(
      () => apiResponse(500, null),
      syntheticAgentDefinitionWorkbench,
      () => apiResponse(status, failureBody),
    );
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();

    const alert = await within(panel).findByRole('alert');
    expect(alert.textContent).toBe(expected);
    if (!failureBody.retryable) expect(alert.textContent).not.toMatch(/try again/i);
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

// ============================================================
// #267 Task 6 — Agent Test Cases, test runs, and the Input/Compare/Checks views
// ============================================================

const RUN_BUTTON = 'Run test case';
const BASELINE_BUTTON = 'Run published baseline';
const TEST_RUN_UNSAVED_HINT = "Save this role's edits before running a test case.";

function testingAside() {
  return screen.getByRole('complementary', { name: 'Isolated testing' });
}

async function loadTestCasesForSelectedRole() {
  fireEvent.click(within(testingAside()).getByRole('button', { name: 'Load Agent Test Cases' }));
  return within(testingAside()).findByRole('combobox', { name: 'Agent Test Cases' });
}

function asideButton(name: string) {
  return within(testingAside()).getByRole('button', { name });
}

function asideTab(name: 'Input' | 'Compare' | 'Checks') {
  fireEvent.click(within(testingAside()).getByRole('tab', { name }));
  return within(testingAside()).getByRole('tabpanel', { name });
}

function callsMatching(fetchMock: ReturnType<typeof vi.fn>, pattern: RegExp, method: string) {
  return fetchMock.mock.calls.filter(([url, init]) =>
    pattern.test(String(url)) && (init as RequestInit | undefined)?.method === method);
}

function candidateRunBodies(fetchMock: ReturnType<typeof vi.fn>) {
  return callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST').map(([, init]) => String((init as RequestInit).body));
}

/** The history read of a case version with no stored runs. */
function noRuns() {
  return apiResponse(200, { items: [] });
}

function caseList(items = [syntheticAgentTestCase()]) {
  return () => apiResponse(200, syntheticAgentTestCaseList(items));
}

/** #266's accessible names that Playwright resolves by case-insensitive substring (C38). */
const NAMES_266 = [
  'Test structured output', 'Retry structured output test', 'Structured output test result',
  'Refresh models', 'Search discovered models', 'Discovered models', 'Custom endpoint name',
  'Schema Upgrade', 'Description override',
];

/** Every accessible name #267 renders: controls, regions, the selector, fields and views. */
const NAMES_267 = [
  RUN_BUTTON, BASELINE_BUTTON, 'Load Agent Test Cases', 'Refresh test cases', 'Add test case',
  'Save test case', 'Retire test case', 'Confirm retire', 'Keep test case', 'Agent Test Cases',
  'Edit test case', 'Save new version',
  'Test case name', 'Synthetic payload (JSON)', 'Required test case', 'Design system active',
  'Test run views', 'Input', 'Compare', 'Checks', 'Synthetic payload', 'Assembled prompt',
  'Model payload sent', 'Test case evidence', 'Published baseline evidence', 'Test case issues',
];

describe('AgentDefinitionWorkbench isolated testing', () => {
  it('no #267 accessible name contains, or is contained in, a #266 name (C38)', () => {
    for (const ours of NAMES_267) {
      for (const theirs of NAMES_266) {
        const [a, b] = [ours.toLowerCase(), theirs.toLowerCase()];
        expect(a.includes(b) || b.includes(a), `${ours} / ${theirs}`).toBe(false);
      }
      expect(ours.toLowerCase()).not.toMatch(/structured output|test result|retry/);
    }
  });

  it('renders exactly the pinned #267 names once the panel shows a run', async () => {
    mockWorkbenchApi({ listRuns: noRuns, listCases: caseList(), candidateRun: () => apiResponse(201, syntheticTestRunEvidence()) });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();
    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));
    const aside = testingAside();
    const rendered = [
      ...within(aside).getAllByRole('button').map((element) => element.textContent ?? ''),
      ...within(aside).getAllByRole('tab').map((element) => element.textContent ?? ''),
      ...within(aside).getAllByRole('region').map((element) => element.getAttribute('aria-label') ?? ''),
    ];
    for (const name of rendered) expect(NAMES_267).toContain(name);
  });

  it('reads no Agent Test Case on mount, and Load reads exactly the selected role\'s active list', async () => {
    const fetchMock = mockWorkbenchApi({ listRuns: noRuns, listCases: caseList() });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await act(async () => { await Promise.resolve(); });
    expect(allGets(fetchMock)).toHaveLength(1);

    const select = await loadTestCasesForSelectedRole();
    expect(select).toHaveValue('101');
    const lists = callsMatching(fetchMock, TEST_CASES_URL, 'GET');
    expect(lists).toHaveLength(1);
    expect(String(lists[0][0])).toMatch(/\/api\/admin\/agent-definitions\/test-cases\?agent_key=architect$/);
    expect(workbenchGets(fetchMock)).toHaveLength(1);
    // Exactly one history read, for the selected case version.
    await waitFor(() => expect(callsMatching(fetchMock, TEST_CASE_RUNS_URL, 'GET')).toHaveLength(1));
    expect(String(callsMatching(fetchMock, TEST_CASE_RUNS_URL, 'GET')[0][0]))
      .toMatch(/\/api\/admin\/agent-definitions\/test-cases\/101\/runs\?limit=100$/);
    expect(allGets(fetchMock)).toHaveLength(3);

    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    expect(asideButton('Load Agent Test Cases')).toBeEnabled();
    expect(allGets(fetchMock)).toHaveLength(3);
    fireEvent.click(within(navigation).getByRole('button', { name: 'Foreman' }));
    expect(testingAside()).toHaveTextContent('Foreman is deterministic and has no Agent Test Cases.');
    expect(within(testingAside()).queryByRole('button')).not.toBeInTheDocument();
  });

  it('Run test case sends exactly the case and lock for the saved candidate and shows Input, Compare and Checks without a write', async () => {
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      candidateRun: () => apiResponse(201, syntheticTestRunEvidence()),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();
    const statusBefore = architectStatus(navigation).textContent;

    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));

    const runs = callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST');
    expect(runs).toHaveLength(1);
    expect(String(runs[0][0])).toMatch(/\/api\/admin\/agent-definitions\/draft\/architect\/test-runs$/);
    expect(candidateRunBodies(fetchMock)).toEqual(['{"test_case_id":101,"lock_version":0}']);
    expect(asideTab('Compare')).toHaveTextContent('Baseline not recorded');
    expect(asideTab('Input')).toHaveTextContent('Synthetic assembled Architect prompt for the saved candidate.');
    const checks = asideTab('Checks');
    expect(within(checks).getAllByRole('row')).toHaveLength(3);
    expect(checks).toHaveTextContent('Deterministic checks passed');
    // A run is evidence only: no lock, status, form or write moves.
    expect(architectStatus(navigation).textContent).toBe(statusBefore);
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(callsMatching(fetchMock, BASELINE_RUN_URL, 'POST')).toHaveLength(0);
    // The workbench, the case list and the one history read of the selected case.
    expect(allGets(fetchMock)).toHaveLength(3);
    expectNoForbiddenActionNames();
    expect(asideButton(RUN_BUTTON)).toBeEnabled();
    expect(asideButton(BASELINE_BUTTON)).toBeEnabled();
  });

  it('a pending run holds the one gate: Save, the probe, case writes and a second run are refused until it settles', async () => {
    const held = heldResponses();
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      candidateRun: held.responder,
      put: () => apiResponse(500, null),
      probe: () => apiResponse(200, syntheticProbeSuccess()),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(held.pending).toHaveLength(1));
    expect(testingAside()).toHaveTextContent('Running the test case against the saved candidate…');
    for (const name of [RUN_BUTTON, BASELINE_BUTTON, 'Add test case', 'Retire test case']) {
      expect(asideButton(name)).toBeDisabled();
    }
    fireEvent.click(asideButton(RUN_BUTTON));
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    openModelTab();
    expect(probeButton()).toBeDisabled();
    fireEvent.click(probeButton());
    await act(async () => { await Promise.resolve(); });
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(1);
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(probeCalls(fetchMock)).toHaveLength(0);

    await act(async () => { held.pending[0](apiResponse(201, syntheticTestRunEvidence())); });
    await waitFor(() => expect(probeButton()).toBeEnabled());
    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
    expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title');
  });

  it('a pending Save refuses both runs on every role', async () => {
    let releasePut!: (response: object) => void;
    const heldPut = new Promise<object>((resolve) => { releasePut = resolve; });
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      put: () => heldPut,
      candidateRun: () => apiResponse(201, syntheticTestRunEvidence()),
      baselineRun: () => apiResponse(201, syntheticTestRunEvidence({ run_kind: 'published_baseline' })),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    fireEvent.click(within(navigation).getByRole('button', { name: /Builder/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Builder B2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));
    expect(putCalls(fetchMock)).toHaveLength(1);

    fireEvent.click(within(navigation).getByRole('button', { name: /Architect/ }));
    await loadTestCasesForSelectedRole();
    expect(asideButton(RUN_BUTTON)).toBeDisabled();
    expect(asideButton(BASELINE_BUTTON)).toBeDisabled();
    fireEvent.click(asideButton(RUN_BUTTON));
    fireEvent.click(asideButton(BASELINE_BUTTON));
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(0);
    expect(callsMatching(fetchMock, BASELINE_RUN_URL, 'POST')).toHaveLength(0);

    releasePut(apiResponse(200, saveSuccess('builder', {
      prompt_text: 'Builder B2',
      model: structuredClone(modelNode('builder').draft.model),
    }, 1)));
    await waitFor(() => expect(asideButton(RUN_BUTTON)).toBeEnabled());
  });

  it('an unsaved role refuses the candidate run without a request, and the hook allocates nothing', async () => {
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      baselineRun: () => apiResponse(201, syntheticTestRunEvidence({ run_kind: 'published_baseline' })),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();
    fireEvent.click(screen.getByRole('tab', { name: 'Model' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Temperature' }), { target: { value: '0.2' } });

    expect(asideButton(RUN_BUTTON)).toBeDisabled();
    expect(within(testingAside()).getByText(TEST_RUN_UNSAVED_HINT)).toBeInTheDocument();
    fireEvent.click(asideButton(RUN_BUTTON));
    // The published baseline reads no draft, so it is still offered.
    fireEvent.click(asideButton(BASELINE_BUTTON));
    await waitFor(() => expect(callsMatching(fetchMock, BASELINE_RUN_URL, 'POST')).toHaveLength(1));
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(0);

    const hookFetch = vi.fn().mockResolvedValue(apiResponse(201, syntheticTestRunEvidence()));
    vi.stubGlobal('fetch', hookFetch);
    const { result } = renderHook(() => useDraftEditor(syntheticAgentDefinitionWorkbench));
    act(() => result.current.edit('architect', 'prompt_text', 'Architect unsaved'));
    await act(() => result.current.runTestCase('architect', 101));
    expect(hookFetch).not.toHaveBeenCalled();
    expect(result.current.state.pendingSave).toBeNull();

    await act(() => result.current.runTestCase('builder', 301));
    expect(hookFetch).toHaveBeenCalledTimes(1);
    expect(String(hookFetch.mock.calls[0][0])).toMatch(/\/draft\/builder\/test-runs$/);
    expect((hookFetch.mock.calls[0][1] as RequestInit).body).toBe('{"test_case_id":301,"lock_version":0}');
  });

  it('a stale_draft 409 adopts the server draft; Reload server, then an explicit run, sends the adopted lock', async () => {
    const conflict = syntheticNullCandidateConflict(0, 1);
    conflict.server.definitions.architect = {
      ...conflict.server.definitions.architect,
      prompt_text: 'Architect changed on the server',
      candidate_hash: 'd'.repeat(64),
    };
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      candidateRun: (_agentKey, _body, call) => (call === 0
        ? apiResponse(409, conflict)
        : apiResponse(201, syntheticTestRunEvidence({ candidate_hash: 'd'.repeat(64) }))),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(RUN_BUTTON));
    const region = await screen.findByRole('region', { name: 'Draft changed on the server' });
    expect(region).toHaveTextContent('Expected lock 0; Current lock 1');
    expect(within(testingAside()).getByRole('alert'))
      .toHaveTextContent('The draft changed on the server. Review the change, then run the test case again.');
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version1');
    // The run adopted the server's saved candidate but kept the local form, so the
    // role is now unsaved and the next run is refused until the admin reconciles.
    expect(asideButton(RUN_BUTTON)).toBeDisabled();
    expect(asideTab('Compare')).toHaveTextContent('No run yet');

    fireEvent.click(within(region).getByRole('button', { name: 'Reload server' }));
    expect(asideButton(RUN_BUTTON)).toBeEnabled();
    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));
    expect(candidateRunBodies(fetchMock)).toEqual([
      '{"test_case_id":101,"lock_version":0}',
      '{"test_case_id":101,"lock_version":1}',
    ]);
    expect(within(testingAside()).queryByRole('alert')).not.toBeInTheDocument();
    expect(putCalls(fetchMock)).toHaveLength(0);
  });

  it('a 503 test_run_unavailable is a contained retryable alert, and only an explicit retry runs again', async () => {
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      candidateRun: (_agentKey, _body, call) => (call === 0
        ? apiResponse(503, syntheticTestRunUnavailable())
        : apiResponse(201, syntheticTestRunEvidence())),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(RUN_BUTTON));
    const alert = await within(testingAside()).findByRole('alert');
    expect(alert).toHaveTextContent('Test run storage is temporarily unavailable. Retry the request.');
    await act(async () => { await Promise.resolve(); });
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(1);
    expect(asideButton(RUN_BUTTON)).toBeEnabled();
    expect(asideTab('Compare')).toHaveTextContent('No run yet');

    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));
    expect(within(testingAside()).queryByRole('alert')).not.toBeInTheDocument();
    expect(candidateRunBodies(fetchMock)).toHaveLength(2);
  });

  it.each([
    ['a network failure', () => Promise.reject(new TypeError('network failed')),
      'Unable to run the test case. Check your connection and try again.'],
    ['an untyped 500', () => apiResponse(500, { detail: 'Traceback: secret-host.example' }),
      'Unable to run the test case (500).'],
    ['a malformed 201', () => apiResponse(201, { run_id: 1 }),
      'Unable to run the test case because the server response was invalid.'],
    ['a 201 for another case', () => apiResponse(201, syntheticTestRunEvidence({ test_case_id: 999 })),
      'Unable to run the test case because the server response was invalid.'],
    ['a 201 for another role', () => apiResponse(201, syntheticTestRunEvidence({ agent_key: 'builder' })),
      'Unable to run the test case because the server response was invalid.'],
    ['a 201 baseline answering a candidate run', () => apiResponse(201, syntheticTestRunEvidence({ run_kind: 'published_baseline' })),
      'Unable to run the test case because the server response was invalid.'],
    ['a 201 for another saved candidate', () => apiResponse(201, syntheticTestRunEvidence({ candidate_hash: 'e'.repeat(64) })),
      'Unable to run the test case because the server response was invalid.'],
  ])('%s is contained with no evidence, no leak, and no automatic retry', async (_name, respond, message) => {
    const fetchMock = mockWorkbenchApi({ listRuns: noRuns, listCases: caseList(), candidateRun: respond });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(RUN_BUTTON));
    const alert = await within(testingAside()).findByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(document.body).not.toHaveTextContent('secret-host.example');
    expect(asideTab('Compare')).toHaveTextContent('No run yet');
    await act(async () => { await Promise.resolve(); });
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(1);
    expect(asideButton(RUN_BUTTON)).toBeEnabled();
  });

  it('a stale_test_case 409 asks for a refresh, and the refreshed active version is what runs next (P5)', async () => {
    const version2 = syntheticAgentTestCase({ id: 111, version: 2 });
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns,
      listCases: (_agentKey, call) => apiResponse(200, syntheticAgentTestCaseList(
        call === 0 ? [syntheticAgentTestCase()] : [version2],
      )),
      candidateRun: (_agentKey, body) => (body.test_case_id === 101
        ? apiResponse(409, syntheticStaleTestCase(101))
        : apiResponse(201, syntheticTestRunEvidence({ test_case_id: 111, test_case_version: 2 }))),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(RUN_BUTTON));
    expect(await within(testingAside()).findByRole('alert')).toHaveTextContent(
      'This test case version is no longer active. Refresh test cases and run its current version.',
    );
    fireEvent.click(asideButton('Refresh test cases'));
    await waitFor(() => expect(within(testingAside()).getByRole('combobox', { name: 'Agent Test Cases' }))
      .toHaveValue('111'));
    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));
    expect(candidateRunBodies(fetchMock)).toEqual([
      '{"test_case_id":101,"lock_version":0}',
      '{"test_case_id":111,"lock_version":0}',
    ]);
    expect(callsMatching(fetchMock, TEST_CASES_URL, 'GET')).toHaveLength(2);
  });

  it('Run published baseline sends exactly the case with no lock and shows the rerun as not-approved evidence', async () => {
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      baselineRun: () => apiResponse(201, syntheticTestRunEvidence({
        run_id: 777,
        run_kind: 'published_baseline',
        candidate_structured_output: { title: 'Published rerun title' },
      })),
    });
    render(<AgentDefinitionWorkbench />);
    const navigation = await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton(BASELINE_BUTTON));
    const compare = asideTab('Compare');
    const region = await within(compare).findByRole('region', { name: 'Published baseline evidence' });
    expect(region).toHaveTextContent('Published rerun title');
    expect(region).toHaveTextContent('not approved');
    const runs = callsMatching(fetchMock, BASELINE_RUN_URL, 'POST');
    expect(runs).toHaveLength(1);
    expect(String(runs[0][0])).toMatch(/\/api\/admin\/agent-definitions\/published\/architect\/test-runs$/);
    expect(String((runs[0][1] as RequestInit).body)).toBe('{"test_case_id":101}');
    expect(callsMatching(fetchMock, CANDIDATE_RUN_URL, 'POST')).toHaveLength(0);
    // The candidate view still has no run of its own.
    expect(within(compare).getByRole('region', { name: 'Test case evidence' })).toHaveTextContent('No run yet');
    expect(screen.getByText('Lock version').parentElement).toHaveTextContent('Lock version0');
    expect(architectStatus(navigation)).toHaveTextContent('Clean');
    expectNoForbiddenActionNames();
  });

  it('Add test case posts exactly the typed case, keeps the form on an ordered 422, then selects the created case', async () => {
    const created = syntheticAgentTestCase({ id: 202, name: 'Architect board summary', is_required: false });
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      createCase: (_agentKey, _body, call) => (call === 0
        ? apiResponse(422, syntheticInvalidTestCase([
          { field: 'name', code: 'duplicate_name', message: 'A test case with this name already exists for the role.' },
        ]))
        : apiResponse(201, created)),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton('Add test case'));
    fireEvent.change(within(testingAside()).getByRole('textbox', { name: 'Test case name' }), {
      target: { value: 'Architect board summary' },
    });
    fireEvent.change(within(testingAside()).getByRole('textbox', { name: 'Synthetic payload (JSON)' }), {
      target: { value: '{"user_request": "Summarise a fictional board meeting."}' },
    });
    fireEvent.click(asideButton('Save test case'));
    const issues = await within(testingAside()).findByRole('list', { name: 'Test case issues' });
    expect(issues).toHaveTextContent('name: A test case with this name already exists for the role.');
    expect(within(testingAside()).getByRole('textbox', { name: 'Test case name' })).toHaveValue('Architect board summary');

    fireEvent.click(asideButton('Save test case'));
    await waitFor(() => expect(within(testingAside()).getByRole('combobox', { name: 'Agent Test Cases' }))
      .toHaveValue('202'));
    const posts = callsMatching(fetchMock, TEST_CASES_URL, 'POST');
    expect(posts).toHaveLength(2);
    for (const [url, init] of posts) {
      expect(String(url)).toMatch(/\/api\/admin\/agent-definitions\/test-cases$/);
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({
        agent_key: 'architect',
        name: 'Architect board summary',
        synthetic_payload: { user_request: 'Summarise a fictional board meeting.' },
        assembly_context: { design_system_active: false },
        is_required: false,
      });
    }
    expect(within(testingAside()).queryByRole('textbox', { name: 'Test case name' })).not.toBeInTheDocument();
    expect(within(testingAside()).queryByRole('alert')).not.toBeInTheDocument();
    expect(putCalls(fetchMock)).toHaveLength(0);
    expect(callsMatching(fetchMock, TEST_CASES_URL, 'GET')).toHaveLength(1);
  });

  it('Retire test case sends one bodyless DELETE after confirmation, and a last-required 422 keeps the case listed', async () => {
    const optional = syntheticAgentTestCase({ id: 102, name: 'Architect optional case', is_required: false });
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList([syntheticAgentTestCase(), optional]),
      retireCase: (testCaseId) => (testCaseId === 101
        ? apiResponse(422, syntheticInvalidTestCase([{
          field: 'is_active', code: 'last_required_case', message: 'A role must keep one active required test case.',
        }]))
        : apiResponse(200, { ...optional, is_active: false })),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const select = await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton('Retire test case'));
    expect(callsMatching(fetchMock, TEST_CASE_URL, 'DELETE')).toHaveLength(0);
    fireEvent.click(asideButton('Confirm retire'));
    const issues = await within(testingAside()).findByRole('list', { name: 'Test case issues' });
    expect(issues).toHaveTextContent('is_active: A role must keep one active required test case.');
    expect(within(select).getAllByRole('option')).toHaveLength(2);

    fireEvent.change(select, { target: { value: '102' } });
    fireEvent.click(asideButton('Retire test case'));
    fireEvent.click(asideButton('Confirm retire'));
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(1));
    expect(select).toHaveValue('101');
    const deletes = callsMatching(fetchMock, TEST_CASE_URL, 'DELETE');
    expect(deletes.map(([url]) => String(url).split('/').at(-1))).toEqual(['101', '102']);
    for (const [, init] of deletes) expect((init as RequestInit).body).toBeUndefined();
  });

  it('the hook refuses every test operation while another operation holds the gate, without a request', async () => {
    let releasePut!: (response: object) => void;
    const heldPut = new Promise<object>((resolve) => { releasePut = resolve; });
    const hookFetch = vi.fn().mockImplementation(async (url: string) => (isAgentTestUrl(url)
      ? apiResponse(201, syntheticTestRunEvidence())
      : heldPut));
    vi.stubGlobal('fetch', hookFetch);
    const { result } = renderHook(() => useDraftEditor(syntheticAgentDefinitionWorkbench));
    act(() => result.current.edit('builder', 'prompt_text', 'Builder B2'));
    let saving!: Promise<void>;
    act(() => { saving = result.current.save('builder'); });
    expect(result.current.state.pendingSave?.operation).toBe('save');

    await act(() => result.current.runTestCase('architect', 101));
    await act(() => result.current.runPublishedBaseline('architect', 101));
    await act(async () => {
      await result.current.createAgentTestCase('architect', {
        agent_key: 'architect',
        name: 'Blocked',
        synthetic_payload: {},
        assembly_context: { design_system_active: false },
        is_required: false,
      });
    });
    await act(() => result.current.retireAgentTestCase('architect', 101));
    expect(hookFetch.mock.calls.filter(([url]) => isAgentTestUrl(url))).toHaveLength(0);
    expect(result.current.state.pendingSave?.operation).toBe('save');

    await act(async () => {
      releasePut(apiResponse(200, saveSuccess('builder', {
        prompt_text: 'Builder B2',
        model: structuredClone(modelNode('builder').draft.model),
      }, 1)));
      await saving;
    });
    await act(() => result.current.runPublishedBaseline('architect', 101));
    expect(hookFetch.mock.calls.filter(([url]) => isAgentTestUrl(url))).toHaveLength(1);
  });

  it('Edit test case supersedes the selected version through one PUT, selects the new version, and runs it', async () => {
    const version2 = syntheticAgentTestCase({ id: 111, version: 2, synthetic_payload: { user_request: 'Revised ask' } });
    const fetchMock = mockWorkbenchApi({
      listRuns: noRuns, listCases: caseList(),
      updateCase: () => apiResponse(200, version2),
      candidateRun: () => apiResponse(201, syntheticTestRunEvidence({ test_case_id: 111, test_case_version: 2 })),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const select = await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton('Edit test case'));
    fireEvent.change(within(testingAside()).getByRole('textbox', { name: 'Synthetic payload (JSON)' }), {
      target: { value: '{"user_request": "Revised ask"}' },
    });
    fireEvent.click(asideButton('Save new version'));
    await waitFor(() => expect(select).toHaveValue('111'));
    expect(within(select).getAllByRole('option').map((option) => option.textContent))
      .toEqual(['Architect quarterly revenue outline · v2 · required']);
    const puts = callsMatching(fetchMock, TEST_CASE_URL, 'PUT');
    expect(puts).toHaveLength(1);
    expect(String(puts[0][0])).toMatch(/\/api\/admin\/agent-definitions\/test-cases\/101$/);
    expect(JSON.parse(String((puts[0][1] as RequestInit).body))).toEqual({
      name: 'Architect quarterly revenue outline',
      synthetic_payload: { user_request: 'Revised ask' },
      assembly_context: { design_system_active: false },
      is_required: true,
    });
    expect(callsMatching(fetchMock, TEST_CASES_URL, 'POST')).toHaveLength(0);
    expect(putCalls(fetchMock).filter(([url]) => !TEST_CASE_URL.test(String(url)))).toHaveLength(0);

    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Synthetic candidate structured title'));
    expect(candidateRunBodies(fetchMock)).toEqual(['{"test_case_id":111,"lock_version":0}']);
  });

  it('an identical-content edit returns the current version and says that no new version was created', async () => {
    const fetchMock = mockWorkbenchApi({ listRuns: noRuns, listCases: caseList(), updateCase: () => apiResponse(200, syntheticAgentTestCase()) });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const select = await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton('Edit test case'));
    fireEvent.click(asideButton('Save new version'));
    expect(await within(testingAside()).findByText(
      'No change: this content matches version 1, so no new version was created.',
    )).toBeInTheDocument();
    expect(select).toHaveValue('101');
    expect(callsMatching(fetchMock, TEST_CASE_URL, 'PUT')).toHaveLength(1);
    expect(within(testingAside()).queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    ['the last-required 422', () => apiResponse(422, syntheticInvalidTestCase([{
      field: 'is_required',
      code: 'last_required_case',
      message: 'A role must keep at least one active required test case. Add its replacement before retiring this one.',
    }])), 'is_required: A role must keep at least one active required test case. Add its replacement before retiring this one.'],
    ['a stale 409', () => apiResponse(409, syntheticStaleTestCase(101)),
      'This test case version is no longer active. Refresh test cases and run its current version.'],
  ])('an edit refused by %s is shown and keeps the form', async (_label, respond, text) => {
    mockWorkbenchApi({ listRuns: noRuns, listCases: caseList(), updateCase: respond });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();

    fireEvent.click(asideButton('Edit test case'));
    fireEvent.click(within(testingAside()).getByRole('checkbox', { name: 'Required test case' }));
    fireEvent.click(asideButton('Save new version'));
    await waitFor(() => expect(testingAside()).toHaveTextContent(text));
    expect(asideButton('Save new version')).toBeEnabled();
    expect(within(testingAside()).getByRole('checkbox', { name: 'Required test case' })).not.toBeChecked();
  });

  it('after a reload, selecting a case shows its stored run and stored baseline, labelled not approved', async () => {
    const stored = syntheticTestRunEvidence({
      run_id: 900, candidate_is_current: null, base_release_is_current: null,
      baseline_raw_output: { title: 'Stored baseline copy' }, baseline_structured_output: { title: 'Stored baseline copy' },
    });
    const storedBaseline = syntheticTestRunEvidence({
      run_id: 899, run_kind: 'published_baseline', candidate_is_current: null, base_release_is_current: null,
      candidate_structured_output: { title: 'Stored published rerun' },
    });
    const second = syntheticAgentTestCase({ id: 102, name: 'Architect second case' });
    const fetchMock = mockWorkbenchApi({
      listCases: caseList([syntheticAgentTestCase(), second]),
      listRuns: (testCaseId) => apiResponse(200, { items: testCaseId === 101 ? [stored, storedBaseline] : [] }),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const select = await loadTestCasesForSelectedRole();

    const compare = asideTab('Compare');
    await waitFor(() => expect(within(compare).getByRole('region', { name: 'Test case evidence' }))
      .toHaveTextContent('Run 900'));
    expect(within(compare).getByRole('region', { name: 'Test case evidence' })).toHaveTextContent('Stored baseline copy');
    const baseline = within(compare).getByRole('region', { name: 'Published baseline evidence' });
    expect(baseline).toHaveTextContent('Stored published rerun');
    expect(baseline).toHaveTextContent('not approved');
    expect(asideTab('Input')).toHaveTextContent('Synthetic assembled Architect prompt for the saved candidate.');

    // A case switch reloads that version's history; switching back reads it again.
    fireEvent.change(select, { target: { value: '102' } });
    await waitFor(() => expect(callsMatching(fetchMock, TEST_CASE_RUNS_URL, 'GET')).toHaveLength(2));
    expect(asideTab('Compare')).toHaveTextContent('No run yet');
    fireEvent.change(select, { target: { value: '101' } });
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Run 900'));
    expect(callsMatching(fetchMock, TEST_CASE_RUNS_URL, 'GET').map(([url]) => String(url).split('/').at(-2)))
      .toEqual(['101', '102', '101']);
    expect(allGets(fetchMock)).toHaveLength(5);
  });

  it('a history read still in flight when a run completes is dropped, so the newer run stays', async () => {
    const held = heldResponses();
    const fetchMock = mockWorkbenchApi({
      listCases: caseList(),
      listRuns: held.responder,
      candidateRun: () => apiResponse(201, syntheticTestRunEvidence({ run_id: 950 })),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();
    await waitFor(() => expect(held.pending).toHaveLength(1));

    fireEvent.click(asideButton(RUN_BUTTON));
    await waitFor(() => expect(asideTab('Compare')).toHaveTextContent('Run 950'));
    await act(async () => { held.pending[0](apiResponse(200, { items: [syntheticTestRunEvidence({ run_id: 900 })] })); });
    expect(asideTab('Compare')).toHaveTextContent('Run 950');
    expect(asideTab('Compare')).not.toHaveTextContent('Run 900');
    expect(callsMatching(fetchMock, TEST_CASE_RUNS_URL, 'GET')).toHaveLength(1);
  });

  it('a pending case write holds the one gate', async () => {
    const held = heldResponses();
    const fetchMock = mockWorkbenchApi({ listRuns: noRuns, listCases: caseList(), createCase: held.responder });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    await loadTestCasesForSelectedRole();
    fireEvent.click(asideButton('Add test case'));
    fireEvent.change(within(testingAside()).getByRole('textbox', { name: 'Test case name' }), {
      target: { value: 'Held case' },
    });
    fireEvent.click(asideButton('Save test case'));
    await waitFor(() => expect(held.pending).toHaveLength(1));

    fireEvent.change(screen.getByRole('textbox', { name: 'Prompt text' }), { target: { value: 'Architect A2' } });
    expect(screen.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    expect(asideButton(RUN_BUTTON)).toBeDisabled();
    expect(asideButton('Save test case')).toBeDisabled();
    fireEvent.click(asideButton('Save test case'));
    expect(callsMatching(fetchMock, TEST_CASES_URL, 'POST')).toHaveLength(1);

    await act(async () => { held.pending[0](apiResponse(201, syntheticAgentTestCase({ id: 203, name: 'Held case' }))); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Draft' })).toBeEnabled());
  });
});
