/**
 * Gateway MCP Task 7: the deck chip for a `gateway_mcp` tool entry.
 *
 * PLAN-CORRECTIONS T7.2: the chip's status UI lives in its own component,
 * `GatewayChipStatus` (./GatewayChipStatus.tsx), rendered by AgentConfigBar's ToolChip. ToolChip
 * is not exported, so `GatewayChipStatus` is tested directly, and the chip as a whole through
 * AgentConfigBar (label, legacy suffix, remove, no edit panel - T7.4).
 *
 * Contract:
 * - Legacy deck: the suffix " · agent mode only" and NO status call.
 * - Agent deck: `api.getGatewayMcpStatus(service_name)` once on mount, then by state:
 *   - sign_in_required: a "Sign in to {display_name}" link to `sign_in_url` (new tab) and a
 *     "Check again" button that re-fetches;
 *   - access_denied / missing_scope / not_found / unavailable: `message` as a tooltip (title);
 *   - not_registered: "unavailable";
 *   - ready: nothing extra.
 *
 * Props: `<GatewayChipStatus tool={GatewayMcpTool} legacyDeck={boolean} />` (ToolChip already
 * computes `legacyDeck` as `(storedDeckMode ?? selectedDeckMode) === 'legacy'`). The session mock
 * below agrees with the prop in every direct test.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import type { GatewayMcpTool, ToolEntry } from '../../types/agentConfig';

const statusMock = vi.hoisted(() => vi.fn());
const sessionState = vi.hoisted(() => ({
  storedDeckMode: null as 'agent' | 'legacy' | null,
  selectedDeckMode: 'agent' as 'agent' | 'legacy',
}));
const ctx = vi.hoisted(() => ({
  tools: [] as ToolEntry[],
  removeTool: vi.fn(),
  updateToolEntry: vi.fn(),
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { ...actual.api, getGatewayMcpStatus: statusMock } };
});

vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: 'sess-1',
    storedDeckMode: sessionState.storedDeckMode,
    selectedDeckMode: sessionState.selectedDeckMode,
  }),
}));

vi.mock('../../contexts/AgentConfigContext', () => ({
  useAgentConfig: () => ({
    agentConfig: {
      tools: ctx.tools,
      slide_style_id: null,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
    },
    addTool: vi.fn(),
    removeTool: ctx.removeTool,
    updateTool: vi.fn(),
    updateToolEntry: ctx.updateToolEntry,
    setStyle: vi.fn(),
    setDesignSystem: vi.fn(),
    setTemplate: vi.fn(),
    setDeckPrompt: vi.fn(),
    saveAsProfile: vi.fn(),
    loadProfile: vi.fn(),
  }),
}));

vi.mock('../../api/config', () => ({
  configApi: {
    listSlideStyles: vi.fn(async () => ({ styles: [] })),
    listDesignSystems: vi.fn(async () => ({ design_systems: [] })),
    listDeckPrompts: vi.fn(async () => ({ prompts: [] })),
    listDesignSystemTemplates: vi.fn(async () => ({ templates: [] })),
  },
}));

import { AgentConfigBar } from './AgentConfigBar';
import { GatewayChipStatus } from './GatewayChipStatus';

/** In-memory Storage: local Node 26 exposes no `localStorage` to the jsdom environment. */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

const LAKEDRAW_SVC = 'db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw';
const WEB_SEARCH_SVC = 'system.ai.web_search';
const SIGN_IN_URL =
  'https://fevm-db-tellr-dev-workspace.cloud.databricks.com/mcp-service-login?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749';

const LAKEDRAW_TOOL: GatewayMcpTool = {
  type: 'gateway_mcp',
  service_name: LAKEDRAW_SVC,
  display_name: 'LakeDraw',
};
const WEB_SEARCH_TOOL: GatewayMcpTool = {
  type: 'gateway_mcp',
  service_name: WEB_SEARCH_SVC,
  display_name: 'Web Search',
};

const status = (state: string, extra: Record<string, unknown> = {}) => ({
  state,
  message: null,
  sign_in_url: null,
  tools: [],
  ...extra,
});
const SIGN_IN_REQUIRED = status('sign_in_required', {
  message: `To use LakeDraw, sign in here: ${SIGN_IN_URL} — then ask again.`,
  sign_in_url: SIGN_IN_URL,
});
const READY = status('ready', {
  tools: [{ name: 'lakedraw_create_from_spec', description: 'Create a diagram' }],
});

// Match an attribute/text verbatim, with no whitespace collapsing (multi-line messages).
const exact = { normalizer: (s: string) => s };

/** Let pending promise callbacks and the state updates they trigger settle. */
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderStatus(tool: GatewayMcpTool, legacyDeck: boolean) {
  sessionState.storedDeckMode = legacyDeck ? 'legacy' : 'agent';
  sessionState.selectedDeckMode = legacyDeck ? 'legacy' : 'agent';
  return render(
    <GatewayChipStatus tool={tool} legacyDeck={legacyDeck} />,
  );
}

beforeEach(() => {
  statusMock.mockReset();
  ctx.removeTool.mockReset();
  ctx.updateToolEntry.mockReset();
  ctx.tools = [];
  sessionState.storedDeckMode = null;
  sessionState.selectedDeckMode = 'agent';
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('GatewayChipStatus', () => {
  it('sign_in_required renders a new-tab "Sign in to LakeDraw" link to sign_in_url', async () => {
    statusMock.mockResolvedValue(SIGN_IN_REQUIRED);
    await renderStatus(LAKEDRAW_TOOL, false);

    const link = await screen.findByRole('link', { name: 'Sign in to LakeDraw' });
    expect(link.getAttribute('href')).toBe(SIGN_IN_URL);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel') ?? '').toContain('noopener');
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();

    // Fetched once, on mount, for this service.
    expect(statusMock).toHaveBeenCalledTimes(1);
    expect(statusMock.mock.calls[0][0]).toBe(LAKEDRAW_SVC);
  });

  it('"Check again" re-fetches the status and shows the new state', async () => {
    statusMock.mockResolvedValueOnce(SIGN_IN_REQUIRED).mockResolvedValueOnce(READY);
    await renderStatus(LAKEDRAW_TOOL, false);
    await screen.findByRole('link', { name: 'Sign in to LakeDraw' });

    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));

    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(2));
    expect(statusMock.mock.calls[1][0]).toBe(LAKEDRAW_SVC);
    // Now signed in: the link and the button are gone.
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Sign in to LakeDraw' })).toBeNull());
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
  });

  it('a legacy deck shows " · agent mode only" and makes no status call', async () => {
    statusMock.mockResolvedValue(SIGN_IN_REQUIRED);
    await renderStatus(LAKEDRAW_TOOL, true);
    await flush();

    expect(screen.getByText(/agent mode only/).textContent).toBe(' · agent mode only');
    expect(statusMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
  });

  it('ready shows nothing extra', async () => {
    statusMock.mockResolvedValue(READY);
    const { container } = await renderStatus(LAKEDRAW_TOOL, false);

    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
    await flush();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    expect(container.textContent).toBe('');
  });

  it('not_registered shows "unavailable"', async () => {
    statusMock.mockResolvedValue(
      status('not_registered', { message: 'LakeDraw is no longer available.' }),
    );
    await renderStatus(LAKEDRAW_TOOL, false);

    const el = await screen.findByText(/unavailable/);
    // The word itself, optionally after the chip's " · " separator.
    expect(el.textContent?.replace(/^[\s·]+/, '')).toBe('unavailable');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it.each([
    [
      'access_denied',
      "You don't have access to LakeDraw (db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw). Ask an admin to grant EXECUTE on it.",
    ],
    [
      'missing_scope',
      "Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.\n\nThere are two possible causes:",
    ],
    [
      'not_found',
      'LakeDraw (db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw) was not found on this workspace. Ask an admin to check the connection.',
    ],
    [
      'unavailable',
      'LakeDraw is unavailable right now (timed out). The deck was built without it.',
    ],
  ])('%s shows the message as a tooltip, with no sign-in link', async (state, message) => {
    statusMock.mockResolvedValue(status(state, { message }));
    await renderStatus(LAKEDRAW_TOOL, false);

    expect(await screen.findByTitle(message, exact)).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
  });

  it('a failed status call leaves the chip usable: no link, no crash', async () => {
    statusMock.mockRejectedValue(new Error('network down'));
    const { container } = await renderStatus(LAKEDRAW_TOOL, false);

    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
    await flush();
    expect(container).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('api.getGatewayMcpStatus', () => {
  it('GETs /api/tools/gateway-mcp/status?service_name=<service> and returns the body', async () => {
    const { api: realApi } = await vi.importActual<typeof import('../../services/api')>(
      '../../services/api',
    );
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: vi.fn().mockResolvedValue(SIGN_IN_REQUIRED),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await realApi.getGatewayMcpStatus(LAKEDRAW_SVC);

    expect(result).toEqual(SIGN_IN_REQUIRED);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(url.pathname).toBe('/api/tools/gateway-mcp/status');
    expect(url.searchParams.get('service_name')).toBe(LAKEDRAW_SVC);
  });

  it('rejects on a non-OK response', async () => {
    const { api: realApi } = await vi.importActual<typeof import('../../services/api')>(
      '../../services/api',
    );
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Error',
        json: vi.fn().mockResolvedValue({ detail: 'boom' }),
      }),
    );

    await expect(realApi.getGatewayMcpStatus(LAKEDRAW_SVC)).rejects.toBeTruthy();
  });
});

describe('AgentConfigBar: Gateway chip', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
    ctx.tools = [LAKEDRAW_TOOL];
  });

  function renderExpandedBar() {
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));
  }

  it('labels the chip with the display name and the "Gateway" badge', async () => {
    statusMock.mockResolvedValue(READY);
    sessionState.storedDeckMode = 'agent';
    renderExpandedBar();

    expect(screen.getByLabelText('Remove LakeDraw')).toBeInTheDocument();
    expect(screen.getByText('LakeDraw')).toBeInTheDocument();
    expect(screen.getByText('Gateway')).toBeInTheDocument();
    await flush();
  });

  it('on an agent deck the chip fetches its status and shows the sign-in link', async () => {
    statusMock.mockResolvedValue(SIGN_IN_REQUIRED);
    sessionState.storedDeckMode = 'agent';
    renderExpandedBar();

    const link = await screen.findByRole('link', { name: 'Sign in to LakeDraw' });
    expect(link.getAttribute('href')).toBe(SIGN_IN_URL);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(statusMock).toHaveBeenCalledTimes(1);
    expect(statusMock.mock.calls[0][0]).toBe(LAKEDRAW_SVC);
  });

  it('each Gateway chip fetches its own status', async () => {
    ctx.tools = [LAKEDRAW_TOOL, WEB_SEARCH_TOOL];
    statusMock.mockImplementation(async (svc: string) =>
      svc === LAKEDRAW_SVC ? SIGN_IN_REQUIRED : READY,
    );
    sessionState.storedDeckMode = 'agent';
    renderExpandedBar();

    expect(await screen.findByRole('link', { name: 'Sign in to LakeDraw' })).toBeInTheDocument();
    expect(statusMock.mock.calls.map((c) => c[0]).sort()).toEqual([LAKEDRAW_SVC, WEB_SEARCH_SVC].sort());
    expect(screen.getByLabelText('Remove Web Search')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in to Web Search' })).toBeNull();
  });

  it('on a legacy deck the chip says " · agent mode only" and makes no status call', async () => {
    statusMock.mockResolvedValue(SIGN_IN_REQUIRED);
    sessionState.storedDeckMode = 'legacy';
    renderExpandedBar();
    await flush();

    expect(screen.getByText(/agent mode only/).textContent).toBe(' · agent mode only');
    expect(statusMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: 'Sign in to LakeDraw' })).toBeNull();
  });

  it('a legacy deck chosen but not yet locked (selectedDeckMode) is treated the same', async () => {
    statusMock.mockResolvedValue(SIGN_IN_REQUIRED);
    sessionState.storedDeckMode = null;
    sessionState.selectedDeckMode = 'legacy';
    renderExpandedBar();
    await flush();

    expect(screen.getByText(/agent mode only/)).toBeInTheDocument();
    expect(statusMock).not.toHaveBeenCalled();
  });

  it('the remove button removes the Gateway entry', async () => {
    statusMock.mockResolvedValue(READY);
    sessionState.storedDeckMode = 'agent';
    renderExpandedBar();

    fireEvent.click(screen.getByLabelText('Remove LakeDraw'));

    expect(ctx.removeTool).toHaveBeenCalledTimes(1);
    expect(ctx.removeTool.mock.calls[0][0]).toEqual(LAKEDRAW_TOOL);
    await flush();
  });

  it('clicking the chip label opens no edit panel (T7.4)', async () => {
    statusMock.mockResolvedValue(READY);
    sessionState.storedDeckMode = 'agent';
    renderExpandedBar();
    await flush();

    fireEvent.click(screen.getByText('LakeDraw'));
    await flush();

    expect(screen.queryByTestId('tool-edit-panel')).toBeNull();
    expect(screen.queryByTestId('tool-detail-panel')).toBeNull();
    expect(ctx.updateToolEntry).not.toHaveBeenCalled();
  });
});
