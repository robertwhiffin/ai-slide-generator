/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminConnections } from './AdminConnections';
import { AdminPage } from './AdminPage';
import { ApiError } from '../../services/api';

const listGatewayConnections = vi.fn();
const createGatewayConnection = vi.fn();
const updateGatewayConnection = vi.fn();
const deleteGatewayConnection = vi.fn();
const testGatewayConnection = vi.fn();

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listGatewayConnections: (...a: unknown[]) => listGatewayConnections(...a),
      createGatewayConnection: (...a: unknown[]) => createGatewayConnection(...a),
      updateGatewayConnection: (...a: unknown[]) => updateGatewayConnection(...a),
      deleteGatewayConnection: (...a: unknown[]) => deleteGatewayConnection(...a),
      testGatewayConnection: (...a: unknown[]) => testGatewayConnection(...a),
    },
  };
});

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));
vi.mock('./UsageDashboard', () => ({ UsageDashboard: () => <div>Usage fixture</div> }));
vi.mock('../Feedback/FeedbackDashboard', () => ({ FeedbackDashboard: () => <div>Feedback fixture</div> }));
vi.mock('../config/GoogleSlidesAuthForm', () => ({ GoogleSlidesAuthForm: () => <div>GS fixture</div> }));
vi.mock('./AdminDesignSystemDefault', () => ({ AdminDesignSystemDefault: () => <div>DS fixture</div> }));
vi.mock('./AdminJudgeSettings', () => ({ AdminJudgeSettings: () => <div>Judge fixture</div> }));
vi.mock('./AdminSlideStyleDefault', () => ({ AdminSlideStyleDefault: () => <div>Style fixture</div> }));

const conn = (over: Record<string, unknown> = {}) => ({
  id: 1,
  service_name: 'cat.sch.websearch',
  display_name: 'Web search',
  description: 'Searches the web',
  agent: 'architect',
  instructions: 'Use for research',
  tool_allowlist: null,
  enabled: true,
  created_by: 'a@x.com',
  created_at: '2026-11-01T00:00:00Z',
  updated_by: null,
  updated_at: null,
  ...over,
});

const READY = {
  state: 'ready',
  message: null,
  sign_in_url: null,
  tools: [
    { name: 'search', description: 'Search' },
    { name: 'fetch', description: 'Fetch' },
    { name: 'image', description: 'Image' },
  ],
};

const SIX_KEYS = ['agent', 'description', 'display_name', 'enabled', 'instructions', 'tool_allowlist'];

const rowFor = (text: string) => screen.getByText(text).closest('tr') as HTMLElement;

async function openAddForm() {
  fireEvent.click(await screen.findByRole('button', { name: 'Add connection' }));
}

function fillBasics(service = 'cat.sch.newsvc', display = 'New svc') {
  fireEvent.change(screen.getByLabelText('Service name'), { target: { value: service } });
  fireEvent.change(screen.getByLabelText('Display name'), { target: { value: display } });
}

function runTest() {
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
}

describe('AdminConnections', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listGatewayConnections.mockResolvedValue([
      conn(),
      conn({
        id: 2,
        service_name: 'cat.sch.analytics',
        display_name: 'Analytics',
        agent: 'data_analyst',
        tool_allowlist: ['a', 'b'],
        enabled: false,
      }),
    ]);
    testGatewayConnection.mockResolvedValue(READY);
    createGatewayConnection.mockResolvedValue(conn({ id: 3 }));
    updateGatewayConnection.mockResolvedValue(conn());
    deleteGatewayConnection.mockResolvedValue(undefined);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('lists connections with name, service, agent label, enabled and allowlist summary', async () => {
    render(<AdminConnections />);
    await screen.findByText('Web search');
    const first = within(rowFor('Web search'));
    expect(first.getByText('cat.sch.websearch')).toBeInTheDocument();
    expect(first.getByText('Architect')).toBeInTheDocument();
    expect(first.getByText('All tools')).toBeInTheDocument();
    expect(first.getByRole('checkbox', { name: /enabled/i })).toBeChecked();
    const second = within(rowFor('Analytics'));
    expect(second.getByText('cat.sch.analytics')).toBeInTheDocument();
    expect(second.getByText('Data analyst')).toBeInTheDocument();
    expect(second.getByText('2 tools')).toBeInTheDocument();
    expect(second.getByRole('checkbox', { name: /enabled/i })).not.toBeChecked();
  });

  it('posts the checked subset as tool_allowlist after a test', async () => {
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    runTest();
    await waitFor(() => expect(testGatewayConnection).toHaveBeenCalledWith('cat.sch.newsvc'));
    const fetchBox = await screen.findByRole('checkbox', { name: 'fetch' });
    expect(screen.getByRole('checkbox', { name: 'search' })).toBeChecked();
    expect(fetchBox).toBeChecked();
    fireEvent.click(fetchBox);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(createGatewayConnection).toHaveBeenCalledTimes(1));
    expect(createGatewayConnection.mock.calls[0][0]).toMatchObject({
      service_name: 'cat.sch.newsvc',
      display_name: 'New svc',
      agent: 'architect',
      tool_allowlist: ['search', 'image'],
    });
  });

  it('posts tool_allowlist null when every tool stays checked', async () => {
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    runTest();
    await screen.findByRole('checkbox', { name: 'search' });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(createGatewayConnection).toHaveBeenCalledTimes(1));
    expect(createGatewayConnection.mock.calls[0][0].tool_allowlist).toBeNull();
  });

  it('allows Save without running a test, and the agent radio can pick Data analyst', async () => {
    render(<AdminConnections />);
    await openAddForm();
    expect(screen.getByRole('radio', { name: 'Architect' })).toBeChecked();
    fireEvent.click(screen.getByRole('radio', { name: 'Data analyst' }));
    fillBasics();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(createGatewayConnection).toHaveBeenCalledTimes(1));
    expect(testGatewayConnection).not.toHaveBeenCalled();
    expect(createGatewayConnection.mock.calls[0][0]).toMatchObject({
      agent: 'data_analyst',
      tool_allowlist: null,
    });
  });

  it('shows a 409 inline', async () => {
    createGatewayConnection.mockRejectedValue(new ApiError(409, 'This service is already registered'));
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('This service is already registered')).toBeInTheDocument();
    // form stays open so the admin can correct it
    expect(screen.getByLabelText('Service name')).toBeInTheDocument();
  });

  it('shows a readable message for a 422 whose detail is an array', async () => {
    const { api: realApi } = await vi.importActual<typeof import('../../services/api')>(
      '../../services/api',
    );
    createGatewayConnection.mockImplementation((body: never) => realApi.createGatewayConnection(body));
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [
            { loc: ['body', 'display_name'], msg: 'display_name must be 1-120 characters', type: 'value_error' },
          ],
        }),
      }),
    );
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent ?? '').not.toMatch(/\[object Object\]/);
    expect(alert.textContent ?? '').toMatch(/display_name must be 1-120 characters/);
  });

  it('asks for confirmation before deleting, and does not delete when cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<AdminConnections />);
    await screen.findByText('Web search');
    fireEvent.click(within(rowFor('Web search')).getByRole('button', { name: /delete/i }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(deleteGatewayConnection).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(within(rowFor('Web search')).getByRole('button', { name: /delete/i }));
    await waitFor(() => expect(deleteGatewayConnection).toHaveBeenCalledWith(1));
  });

  it('disables the service name when editing and PUTs exactly the six editable keys', async () => {
    render(<AdminConnections />);
    await screen.findByText('Web search');
    fireEvent.click(within(rowFor('Web search')).getByRole('button', { name: /edit/i }));
    const service = screen.getByLabelText('Service name');
    expect(service).toBeDisabled();
    expect(service).toHaveValue('cat.sch.websearch');
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Web search v2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateGatewayConnection).toHaveBeenCalledTimes(1));
    const [id, body] = updateGatewayConnection.mock.calls[0];
    expect(id).toBe(1);
    expect(Object.keys(body).sort()).toEqual(SIX_KEYS);
    expect(body.display_name).toBe('Web search v2');
    expect(createGatewayConnection).not.toHaveBeenCalled();
  });

  it('the enable toggle PUTs exactly the six editable keys with enabled flipped', async () => {
    render(<AdminConnections />);
    await screen.findByText('Web search');
    fireEvent.click(within(rowFor('Web search')).getByRole('checkbox', { name: /enabled/i }));
    await waitFor(() => expect(updateGatewayConnection).toHaveBeenCalledTimes(1));
    const [id, body] = updateGatewayConnection.mock.calls[0];
    expect(id).toBe(1);
    expect(Object.keys(body).sort()).toEqual(SIX_KEYS);
    expect(body.enabled).toBe(false);
  });

  it('renders a sign-in test result as a new-tab link with the message', async () => {
    testGatewayConnection.mockResolvedValue({
      state: 'sign_in_required',
      message: 'Sign in to the connection to continue',
      sign_in_url: 'https://example.com/consent?x=1',
      tools: [],
    });
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    runTest();
    const link = await screen.findByRole('link', { name: /sign in/i });
    expect(link).toHaveAttribute('href', 'https://example.com/consent?x=1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText('Sign in to the connection to continue')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'search' })).not.toBeInTheDocument();
  });

  it.each(['http://example.com/consent', 'javascript:alert(1)'])(
    'never renders a non-https sign-in URL (%s) as a link, but still shows the message',
    async (url) => {
      testGatewayConnection.mockResolvedValue({
        state: 'sign_in_required',
        message: 'Sign in to the connection to continue',
        sign_in_url: url,
        tools: [],
      });
      render(<AdminConnections />);
      await openAddForm();
      fillBasics();
      runTest();
      expect(await screen.findByText('Sign in to the connection to continue')).toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
    },
  );

  it('drops a test result when the service name changes, so its allowlist is not saved for another service', async () => {
    render(<AdminConnections />);
    await openAddForm();
    fillBasics('cat.sch.first');
    runTest();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'fetch' }));
    fireEvent.change(screen.getByLabelText('Service name'), { target: { value: 'cat.sch.second' } });
    expect(screen.queryByRole('checkbox', { name: 'search' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(createGatewayConnection).toHaveBeenCalledTimes(1));
    expect(createGatewayConnection.mock.calls[0][0]).toMatchObject({
      service_name: 'cat.sch.second',
      tool_allowlist: null,
    });
  });

  it('shows the error message of a failing test result', async () => {
    testGatewayConnection.mockResolvedValue({
      state: 'not_found',
      message: 'No such service in this workspace',
      sign_in_url: null,
      tools: [],
    });
    render(<AdminConnections />);
    await openAddForm();
    fillBasics();
    runTest();
    expect(await screen.findByText('No such service in this workspace')).toBeInTheDocument();
  });

  it('counts instructions against the 4000-character limit', async () => {
    render(<AdminConnections />);
    await openAddForm();
    expect(screen.getByText('0 / 4000')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'hello world!' } });
    expect(screen.getByText('12 / 4000')).toBeInTheDocument();
  });

  it('has a help panel collapsed by default that expands on click', async () => {
    render(<AdminConnections />);
    const toggle = await screen.findByRole('button', {
      name: 'How to create the service in Databricks',
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/lakedraw/i)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByText(/lakedraw/i).length).toBeGreaterThan(0);
  });
});

describe('AdminPage Connections tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listGatewayConnections.mockResolvedValue([conn()]);
  });
  afterEach(() => cleanup());

  it('shows a Connections tab whose panel renders the component', async () => {
    render(<AdminPage />);
    fireEvent.click(screen.getByRole('tab', { name: 'Connections' }));
    expect(screen.getByRole('tab', { name: 'Connections' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Web search')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add connection' })).toBeInTheDocument();
  });
});
