import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { syntheticAgentDefinitionWorkbench } from '../../../../tests/fixtures/mocks';
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

const FORBIDDEN_ACTION_NAME = /save\s+draft|\brun\b|approve|reject|review\s*&\s*publish|publish|history|rollback/i;

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

    expect(within(navigation).getAllByRole('button').map((button) => button.textContent?.trim()))
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
    expect(screen.getByRole('tabpanel', { name: 'Model' })).toHaveTextContent(
      'databricks-claude-opus-4-6',
    );
    expect(screen.getByRole('tabpanel', { name: 'Model' })).toHaveTextContent('60000');

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

  it('offers no write, execution, review, publication, history, or rollback action', async () => {
    renderSuccessfulWorkbench();
    await loadedNodeNavigation();

    expectNoForbiddenActionNames();
    expect(screen.getByText('Isolated testing is not available in this release.')).toBeVisible();
  });

  it.each([
    [
      'aria-labelledby',
      () => (
        <>
          <span id="forbidden-labelled-action">Save Draft</span>
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

  it('does not mount or request the workbench until the Agent Definitions admin tab is selected', async () => {
    mockFetchResponse(200, syntheticAgentDefinitionWorkbench);
    render(<AdminPage />);
    const workbenchCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) =>
      String(url).endsWith('/api/admin/agent-definitions/workbench'),
    );

    expect(workbenchCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: 'Agent Definitions' }));
    await loadedNodeNavigation();
    expect(workbenchCalls()).toHaveLength(1);
  });
});
