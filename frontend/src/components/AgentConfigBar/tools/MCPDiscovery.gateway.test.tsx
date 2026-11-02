/**
 * Gateway MCP Task 7: the deck's MCP Server picker lists admin-registered AI Gateway connections
 * (`gateway_items` from GET /api/tools/discover/mcp) in an "AI Gateway" group, FIRST, then the
 * existing Unity Catalog connections (`items`). One search box filters both groups. Picking a
 * Gateway item previews it as `toolType: 'gateway_mcp'`, and saving the preview adds the entry
 * `{type: 'gateway_mcp', service_name, display_name}`.
 *
 * The network is stubbed at `fetch` (as MCPDiscovery.test.tsx does), so the real
 * `api.discoverMCPConnections()` runs, including its non-OK branch (PLAN-CORRECTIONS T7.3).
 */
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ToolEntry } from '../../../types/agentConfig';

// --- contexts for the AgentConfigBar end-to-end add flow (MCPDiscovery itself uses none) ---
const ctx = vi.hoisted(() => ({
  addTool: vi.fn(),
  tools: [] as unknown[],
}));

vi.mock('../../../contexts/SessionContext', () => ({
  useSession: () => ({ sessionId: 'sess-1', storedDeckMode: 'agent', selectedDeckMode: 'agent' }),
}));

vi.mock('../../../contexts/AgentConfigContext', () => ({
  useAgentConfig: () => ({
    agentConfig: {
      tools: ctx.tools,
      slide_style_id: null,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
    },
    addTool: ctx.addTool,
    removeTool: vi.fn(),
    updateTool: vi.fn(),
    updateToolEntry: vi.fn(),
    setStyle: vi.fn(),
    setDesignSystem: vi.fn(),
    setTemplate: vi.fn(),
    setDeckPrompt: vi.fn(),
    saveAsProfile: vi.fn(),
    loadProfile: vi.fn(),
  }),
}));

vi.mock('../../../api/config', () => ({
  configApi: {
    listSlideStyles: vi.fn(async () => ({ styles: [] })),
    listDesignSystems: vi.fn(async () => ({ design_systems: [] })),
    listDeckPrompts: vi.fn(async () => ({ prompts: [] })),
    listDesignSystemTemplates: vi.fn(async () => ({ templates: [] })),
  },
}));

import { MCPDiscovery } from './MCPDiscovery';
import { AgentConfigBar } from '../AgentConfigBar';

const DISCOVER_SUFFIX = '/api/tools/discover/mcp';

const LAKEDRAW_SVC = 'db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw';
const LAKEDRAW_ITEM = {
  service_name: LAKEDRAW_SVC,
  display_name: 'LakeDraw',
  description: 'Draws system diagrams',
  agent: 'architect',
};
const WEB_SEARCH_ITEM = {
  service_name: 'system.ai.web_search',
  display_name: 'Web Search',
  description: null,
  agent: 'architect',
};
const UC_ITEM = { id: 'sales_http', name: 'sales_http', description: 'Sales CRM connection' };

const CONSENT_LINE =
  "Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.";

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

function reply(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: vi.fn().mockResolvedValue(body),
  };
}

function stubDiscover(response: unknown) {
  const mock = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).endsWith(DISCOVER_SUFFIX)) return response;
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function renderDiscovery(existingTools: ToolEntry[] = []) {
  const onPreview = vi.fn();
  const onClose = vi.fn();
  const onSelect = vi.fn();
  render(
    <MCPDiscovery
      onSelect={onSelect}
      onPreview={onPreview}
      onClose={onClose}
      existingTools={existingTools}
    />,
  );
  return { onPreview, onClose, onSelect };
}

/** True when `a` comes before `b` in document order. */
function precedes(a: Node, b: Node): boolean {
  return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

/** The clickable row for an item: the button whose content includes the item's name. */
function row(name: string): HTMLButtonElement {
  return screen.getByText(name).closest('button') as HTMLButtonElement;
}

const search = (q: string) =>
  fireEvent.change(screen.getByPlaceholderText('Search connections...'), { target: { value: q } });

beforeEach(() => {
  ctx.addTool.mockReset();
  ctx.tools = [];
});

afterEach(() => {
  // Not restoreAllMocks: it would strip the module mocks' implementations for later tests.
  vi.unstubAllGlobals();
});

describe('MCPDiscovery: AI Gateway group', () => {
  it('renders Gateway items under "AI Gateway", before the UC items', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderDiscovery();

    const heading = await screen.findByText('AI Gateway');
    const lakedraw = screen.getByText('LakeDraw');
    const webSearch = screen.getByText('Web Search');
    const uc = screen.getByText('sales_http');

    expect(precedes(heading, lakedraw)).toBe(true);
    expect(precedes(lakedraw, webSearch)).toBe(true);
    expect(precedes(webSearch, uc)).toBe(true);
    // The Gateway item shows its description, like a UC item does.
    expect(screen.getByText('Draws system diagrams')).toBeInTheDocument();
  });

  it('heads the UC items "Unity Catalog" below a Gateway group, and only then', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderDiscovery();

    const ucHeading = await screen.findByText('Unity Catalog');
    expect(precedes(screen.getByText('Web Search'), ucHeading)).toBe(true);
    expect(precedes(ucHeading, screen.getByText('sales_http'))).toBe(true);

    // Only Gateway items match: no UC heading over an empty UC group.
    search('lake');
    expect(screen.queryByText('Unity Catalog')).toBeNull();
    // Only UC items match: no Gateway group, so the UC list looks as it did before.
    search('sales');
    expect(screen.queryByText('Unity Catalog')).toBeNull();
    expect(screen.queryByText('AI Gateway')).toBeNull();
  });

  it('shows no "AI Gateway" group when there are no Gateway items, and UC items as before', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [] }));
    renderDiscovery();

    expect(await screen.findByText('sales_http')).toBeInTheDocument();
    expect(screen.queryByText('AI Gateway')).toBeNull();
    expect(screen.queryByText('Unity Catalog')).toBeNull();
  });

  it('does not show the empty state when only Gateway items exist', async () => {
    stubDiscover(reply(200, { items: [], gateway_items: [LAKEDRAW_ITEM] }));
    renderDiscovery();

    expect(await screen.findByText('LakeDraw')).toBeInTheDocument();
    expect(screen.queryByText('No MCP connections available.')).toBeNull();
  });

  it('the search filters both groups', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderDiscovery();
    await screen.findByText('LakeDraw');

    search('lake');
    expect(screen.getByText('LakeDraw')).toBeInTheDocument();
    expect(screen.queryByText('Web Search')).toBeNull();
    expect(screen.queryByText('sales_http')).toBeNull();
    expect(screen.queryByText('No matching connections.')).toBeNull();

    // A Gateway item's description is searched too, as a UC item's is.
    search('diagrams');
    expect(screen.getByText('LakeDraw')).toBeInTheDocument();
    expect(screen.queryByText('Web Search')).toBeNull();
    expect(screen.queryByText('sales_http')).toBeNull();

    search('sales');
    expect(screen.getByText('sales_http')).toBeInTheDocument();
    expect(screen.queryByText('LakeDraw')).toBeNull();
    expect(screen.queryByText('Web Search')).toBeNull();

    search('zzz-nothing');
    expect(screen.queryByText('LakeDraw')).toBeNull();
    expect(screen.queryByText('Web Search')).toBeNull();
    expect(screen.queryByText('sales_http')).toBeNull();
    expect(screen.getByText('No matching connections.')).toBeInTheDocument();
  });

  it('picking a Gateway item calls onPreview with toolType gateway_mcp and the service name, then closes', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM] }));
    const { onPreview, onClose, onSelect } = renderDiscovery();
    await screen.findByText('LakeDraw');

    fireEvent.click(row('LakeDraw'));

    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        toolType: 'gateway_mcp',
        name: 'LakeDraw',
        serviceName: LAKEDRAW_SVC,
      }),
    );
    expect(onClose).toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('still previews a UC item as toolType mcp', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM] }));
    const { onPreview } = renderDiscovery();
    await screen.findByText('sales_http');

    fireEvent.click(row('sales_http'));

    expect(onPreview).toHaveBeenCalledWith(
      expect.objectContaining({ toolType: 'mcp', connectionName: 'sales_http' }),
    );
  });

  it('the UC error message still renders while Gateway items show', async () => {
    stubDiscover(
      reply(200, {
        items: [],
        error: CONSENT_LINE,
        error_code: 'missing_scope',
        gateway_items: [LAKEDRAW_ITEM],
      }),
    );
    const { onPreview } = renderDiscovery();

    expect(await screen.findByText(CONSENT_LINE)).toBeInTheDocument();
    expect(screen.getByText('AI Gateway')).toBeInTheDocument();
    expect(row('LakeDraw').disabled).toBe(false);

    fireEvent.click(row('LakeDraw'));
    expect(onPreview).toHaveBeenCalledWith(
      expect.objectContaining({ toolType: 'gateway_mcp', serviceName: LAKEDRAW_SVC }),
    );
  });

  it('keeps Gateway items from a non-OK response body alongside its error', async () => {
    const backendError = 'Could not list MCP connections: RuntimeError';
    stubDiscover(
      reply(500, {
        items: [],
        error: backendError,
        error_code: 'discovery_failed',
        gateway_items: [LAKEDRAW_ITEM],
      }),
    );
    renderDiscovery();

    expect(await screen.findByText(backendError)).toBeInTheDocument();
    expect(screen.getByText('LakeDraw')).toBeInTheDocument();
  });

  it('marks and disables an already-added Gateway item, like an already-added UC item', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    const existing = [
      { type: 'gateway_mcp', service_name: LAKEDRAW_SVC, display_name: 'LakeDraw' },
      { type: 'mcp', connection_name: 'sales_http', server_name: 'sales_http' },
    ] as unknown as ToolEntry[];
    const { onPreview } = renderDiscovery(existing);
    await screen.findByText('LakeDraw');

    const added = row('LakeDraw');
    expect(added.disabled).toBe(true);
    expect(within(added).getByText('added')).toBeInTheDocument();
    fireEvent.click(added);
    expect(onPreview).not.toHaveBeenCalled();

    // The UC item is marked the same way (existing behaviour, same rule).
    expect(row('sales_http').disabled).toBe(true);
    expect(within(row('sales_http')).getByText('added')).toBeInTheDocument();

    // A Gateway item that is not in the config stays pickable.
    const fresh = row('Web Search');
    expect(fresh.disabled).toBe(false);
    expect(within(fresh).queryByText('added')).toBeNull();
  });
});

describe('AgentConfigBar: adding a Gateway connection from the MCP Server picker', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
  });

  it('pick → detail panel (name, service, agent, Gateway badge) → Save & Add adds {type, service_name, display_name}', async () => {
    stubDiscover(reply(200, { items: [UC_ITEM], gateway_items: [LAKEDRAW_ITEM] }));
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));
    fireEvent.click(screen.getByTestId('add-tool-mcp'));

    await screen.findByText('LakeDraw');
    fireEvent.click(row('LakeDraw'));

    const panel = await screen.findByTestId('tool-detail-panel');
    expect(within(panel).getAllByText('LakeDraw').length).toBeGreaterThan(0);
    expect(within(panel).getAllByText(LAKEDRAW_SVC).length).toBeGreaterThan(0);
    expect(within(panel).getByText('Gateway')).toBeInTheDocument();
    // The connection's agent (architect / data analyst), in whatever casing.
    expect(within(panel).getAllByText(/architect/i).length).toBeGreaterThan(0);
    expect(
      within(panel).queryByText('Draws system diagrams')
        ?? within(panel).queryByDisplayValue('Draws system diagrams'),
    ).not.toBeNull();

    fireEvent.click(within(panel).getByRole('button', { name: 'Save & Add' }));

    await waitFor(() => expect(ctx.addTool).toHaveBeenCalledTimes(1));
    expect(ctx.addTool.mock.calls[0][0]).toEqual({
      type: 'gateway_mcp',
      service_name: LAKEDRAW_SVC,
      display_name: 'LakeDraw',
    });
  });
});
