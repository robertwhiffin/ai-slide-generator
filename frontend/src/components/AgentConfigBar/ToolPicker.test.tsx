/**
 * ToolPicker: the Tools row's pills, and the AgentConfigBar chips they produce.
 *
 * The row is "+ Genie One", then one one-click pill per enabled admin-registered AI Gateway
 * connection (GET /api/tools/discover/gateway-mcp), then an "Other tools" toggle that
 * reveals the original category pills. A vanilla install (no connections) shows two pills.
 *
 * The network is stubbed at `fetch`, so the real `api.discoverGatewayConnections()` runs.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import type { ToolEntry } from '../../types/agentConfig';

const sessionState = vi.hoisted(() => ({
  storedDeckMode: null as 'agent' | 'legacy' | null,
  selectedDeckMode: 'agent' as 'agent' | 'legacy',
}));
const configState = vi.hoisted(() => ({ tools: [] as unknown[], addTool: vi.fn() }));

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
      tools: configState.tools,
      slide_style_id: null,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
    },
    addTool: configState.addTool,
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

vi.mock('../../api/config', () => ({
  configApi: {
    listSlideStyles: vi.fn().mockResolvedValue({ styles: [] }),
    listDesignSystems: vi.fn().mockResolvedValue({ design_systems: [] }),
    listDeckPrompts: vi.fn().mockResolvedValue({ prompts: [] }),
    listDesignSystemTemplates: vi.fn().mockResolvedValue({ templates: [] }),
  },
}));

import { ToolPicker } from './ToolPicker';
import { AgentConfigBar } from './AgentConfigBar';


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

const GENIE_ONE: ToolEntry = { type: 'genie_one' };

const GATEWAY_SUFFIX = '/api/tools/discover/gateway-mcp';
const LAKEDRAW_SVC = 'db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw';
const LAKEDRAW_ITEM = {
  service_name: LAKEDRAW_SVC,
  display_name: 'LakeDraw',
  description: 'Draws architecture diagrams',
  agent: 'architect',
};
const WEB_SEARCH_ITEM = {
  service_name: 'system.ai.web_search',
  display_name: 'Web search',
  description: null,
  agent: 'data_analyst',
};

/** The original category pills, in their original order, behind "Other tools". */
const OTHER_TOOL_LABELS = [
  '+ Genie Agent',
  '+ Agent Bricks',
  '+ Vector Index',
  '+ MCP Server',
  '+ Model Endpoint',
];
const OTHER_TOOL_TESTIDS = ['genie', 'agent_bricks', 'vector_index', 'mcp', 'model_endpoint'].map(
  (t) => `add-tool-${t}`,
);

function reply(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: vi.fn().mockResolvedValue(body),
  };
}

/** Answer the Gateway discovery call with `response` (or reject with it); 404 anything else. */
function stubGateway(response: unknown) {
  const mock = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).endsWith(GATEWAY_SUFFIX)) {
      if (response instanceof Error) throw response;
      return response;
    }
    return reply(404, {});
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

const gatewayCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.filter(([url]) => String(url).endsWith(GATEWAY_SUFFIX));

/** Let the Gateway discovery request and its `json()` settle. */
async function settle(mock: ReturnType<typeof vi.fn>) {
  await waitFor(() => expect(gatewayCalls(mock).length).toBeGreaterThan(0));
  await act(() => new Promise((r) => setTimeout(r, 0)));
}

function renderPicker(existingTools: ToolEntry[] = []) {
  const onSelect = vi.fn();
  const utils = render(
    <ToolPicker
      onSelect={onSelect}
      onPreview={vi.fn()}
      onToolPreview={vi.fn()}
      existingTools={existingTools}
    />,
  );
  return { onSelect, ...utils };
}

const labels = () => screen.getAllByRole('button').map((b) => b.textContent);

afterEach(() => {
  // Not restoreAllMocks: it would strip the module mocks' implementations for later tests.
  vi.unstubAllGlobals();
});

describe('ToolPicker: the pill row', () => {
  it('a vanilla install (no connections) shows only "+ Genie One" and "Other tools"', async () => {
    const mock = stubGateway(reply(200, { items: [] }));
    renderPicker();
    await settle(mock);

    expect(labels()).toEqual(['+ Genie One', 'Other tools']);
    expect(screen.getAllByRole('button')[0]).toBe(screen.getByTestId('add-tool-genie_one'));
    for (const id of OTHER_TOOL_TESTIDS) expect(screen.queryByTestId(id)).toBeNull();
  });

  it('"Other tools" reveals the original pills in their original order, and hides them again', async () => {
    const mock = stubGateway(reply(200, { items: [] }));
    renderPicker();
    await settle(mock);

    const toggle = screen.getByTestId('toggle-other-tools');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(labels()).toEqual(['+ Genie One', 'Other tools', ...OTHER_TOOL_LABELS]);

    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(labels()).toEqual(['+ Genie One', 'Other tools']);
  });

  it('a category pill behind "Other tools" still opens its discovery panel', async () => {
    const mock = stubGateway(reply(200, { items: [] }));
    renderPicker();
    await settle(mock);

    fireEvent.click(screen.getByTestId('toggle-other-tools'));
    fireEvent.click(screen.getByTestId('add-tool-mcp'));

    expect(await screen.findByTestId('mcp-discovery')).toBeInTheDocument();
  });

  it('clicking "+ Genie One" calls onSelect with {type: genie_one} and opens no discovery panel', async () => {
    const mock = stubGateway(reply(200, { items: [] }));
    const { onSelect } = renderPicker();
    await settle(mock);

    fireEvent.click(screen.getByTestId('add-tool-genie_one'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith({ type: 'genie_one' });
    expect(labels()).toEqual(['+ Genie One', 'Other tools']);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('searchbox')).toBeNull();
  });

  it('"+ Genie One" is absent once existingTools already holds a genie_one entry', async () => {
    const mock = stubGateway(reply(200, { items: [] }));
    renderPicker([GENIE_ONE]);
    await settle(mock);

    expect(screen.queryByTestId('add-tool-genie_one')).toBeNull();
    expect(labels()).toEqual(['Other tools']);
  });
});

describe('ToolPicker: admin-registered connection pills', () => {
  it('each enabled connection gets a pill, in order, between "+ Genie One" and "Other tools"', async () => {
    stubGateway(reply(200, { items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderPicker();

    await screen.findByText('+ LakeDraw');
    expect(labels()).toEqual(['+ Genie One', '+ LakeDraw', '+ Web search', 'Other tools']);
  });

  it('clicking a connection pill adds {type, service_name, display_name} in one click, with no panel', async () => {
    stubGateway(reply(200, { items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    const { onSelect } = renderPicker();

    fireEvent.click(await screen.findByText('+ LakeDraw'));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0]).toEqual({
      type: 'gateway_mcp',
      service_name: LAKEDRAW_SVC,
      display_name: 'LakeDraw',
    });
    expect(screen.queryByTestId('mcp-discovery')).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('a connection pill shows its description as a tooltip', async () => {
    stubGateway(reply(200, { items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderPicker();

    expect((await screen.findByText('+ LakeDraw')).getAttribute('title')).toBe(
      'Draws architecture diagrams',
    );
    expect(screen.getByText('+ Web search').getAttribute('title')).toBeNull();
  });

  it('a connection already in the deck has no pill; the others stay', async () => {
    stubGateway(reply(200, { items: [LAKEDRAW_ITEM, WEB_SEARCH_ITEM] }));
    renderPicker([
      { type: 'gateway_mcp', service_name: LAKEDRAW_SVC, display_name: 'LakeDraw' },
      GENIE_ONE,
    ]);

    await screen.findByText('+ Web search');
    expect(labels()).toEqual(['+ Web search', 'Other tools']);
  });

  it('asks for the connections once, not on every re-render', async () => {
    const mock = stubGateway(reply(200, { items: [LAKEDRAW_ITEM] }));
    const { rerender } = renderPicker();
    await screen.findByText('+ LakeDraw');

    rerender(
      <ToolPicker onSelect={vi.fn()} onPreview={vi.fn()} onToolPreview={vi.fn()} existingTools={[GENIE_ONE]} />,
    );
    await act(() => new Promise((r) => setTimeout(r, 0)));

    expect(gatewayCalls(mock)).toHaveLength(1);
  });

  it.each([
    ['the request fails', new TypeError('Failed to fetch')],
    ['the server answers 500', reply(500, { detail: 'boom' })],
  ])('when %s, the row is "+ Genie One" and "Other tools"', async (_label, response) => {
    const mock = stubGateway(response);
    renderPicker();
    await settle(mock);

    expect(labels()).toEqual(['+ Genie One', 'Other tools']);
  });
});

describe('AgentConfigBar: adding a connection from its pill', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
    configState.tools = [];
    configState.addTool.mockReset();
    sessionState.storedDeckMode = null;
    sessionState.selectedDeckMode = 'agent';
  });

  it('expand the bar → "+ LakeDraw" → the Gateway entry is added to the deck', async () => {
    stubGateway(reply(200, { items: [LAKEDRAW_ITEM] }));
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));

    fireEvent.click(await screen.findByText('+ LakeDraw'));

    expect(configState.addTool).toHaveBeenCalledTimes(1);
    expect(configState.addTool.mock.calls[0][0]).toEqual({
      type: 'gateway_mcp',
      service_name: LAKEDRAW_SVC,
      display_name: 'LakeDraw',
    });
  });
});

describe('AgentConfigBar: Genie One chip', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
    stubGateway(reply(200, { items: [] }));
    configState.tools = [{ type: 'genie_one', conversation_id: null }];
    sessionState.storedDeckMode = null;
    sessionState.selectedDeckMode = 'agent';
  });

  function renderExpandedBar() {
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));
  }

  it('labels the chip "Genie One"', () => {
    renderExpandedBar();
    expect(screen.getByLabelText('Remove Genie One')).toBeTruthy();
    expect(screen.getAllByText('Genie One').length).toBeGreaterThan(0);
  });

  it('on a legacy deck the chip carries the agent-mode-only title and visible suffix', () => {
    sessionState.storedDeckMode = 'legacy';
    renderExpandedBar();
    expect(screen.getByTitle('Genie One works in agent mode only')).toBeTruthy();
    expect(screen.getByText(/· agent mode only/)).toBeTruthy();
    expect(screen.getByText(/· agent mode only/).textContent).toBe(' · agent mode only');
  });

  it('on a legacy deck chosen but not yet locked (selectedDeckMode) the same applies', () => {
    sessionState.storedDeckMode = null;
    sessionState.selectedDeckMode = 'legacy';
    renderExpandedBar();
    expect(screen.getByTitle('Genie One works in agent mode only')).toBeTruthy();
  });

  it('on an agent deck there is no suffix and no title, even while the picker says legacy', () => {
    // A locked agent deck wins over the picker: storedDeckMode ?? selectedDeckMode.
    sessionState.storedDeckMode = 'agent';
    sessionState.selectedDeckMode = 'legacy';
    renderExpandedBar();
    expect(screen.queryByText(/agent mode only/)).toBeNull();
    expect(screen.queryByTitle('Genie One works in agent mode only')).toBeNull();
  });
});
