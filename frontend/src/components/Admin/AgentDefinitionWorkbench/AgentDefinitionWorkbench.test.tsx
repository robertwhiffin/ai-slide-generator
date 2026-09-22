import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { syntheticAgentDefinitionWorkbench } from '../../../../tests/fixtures/mocks';
import type {
  AgentKey,
  DraftSaveConflictResponse,
  DraftSaveRequest,
  DraftSaveSuccessResponse,
  EditableModelDraft,
} from '../../../api/agentDefinitions';
import { AdminPage } from '../AdminPage';
import { AgentDefinitionWorkbench } from './AgentDefinitionWorkbench';

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

const FORBIDDEN_ACTION_NAME = /\brun\b|approve|reject|review\s*&\s*publish|publish|history|rollback/i;

function interactiveControls() {
  return [...screen.queryAllByRole('button'), ...screen.queryAllByRole('link')];
}

function expectNoForbiddenActionNames() {
  for (const control of interactiveControls()) {
    expect(control).not.toHaveAccessibleName(FORBIDDEN_ACTION_NAME);
  }
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
      ) as DraftSaveConflictResponse['server']['definitions'],
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
    expect(screen.getByRole('tabpanel', { name: 'Output Schema' })).toHaveTextContent(
      'Synthetic title override',
    );
    expect(screen.getByRole('tabpanel', { name: 'Output Schema' })).toHaveTextContent(
      'speaker_notes',
    );

    fireEvent.click(tabs.getByRole('tab', { name: 'Assembly' }));
    expect(screen.getByRole('tabpanel', { name: 'Assembly' })).toHaveTextContent(
      'slide_frame_constraints',
    );
    expect(screen.getByRole('tabpanel', { name: 'Assembly' })).toHaveTextContent(
      'langchain.with_structured_output',
    );
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
    fireEvent.click(within(recovery).getByRole('button', { name: 'Dismiss' }));
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
