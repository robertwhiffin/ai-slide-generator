/**
 * The MCP add panel (ToolDetailPanel), the MCP edit panel (ToolEditPanel, reached by clicking a
 * chip in AgentConfigBar) and the chips: each carries the "Which agent uses it?" choice.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import type { ToolEntry } from '../../types/agentConfig';

const sessionState = vi.hoisted(() => ({
  storedDeckMode: null as 'agent' | 'legacy' | null,
  selectedDeckMode: 'agent' as 'agent' | 'legacy',
}));
const configState = vi.hoisted(() => ({
  tools: [] as unknown[],
  addTool: vi.fn(),
  removeTool: vi.fn(),
  updateToolEntry: vi.fn(),
}));

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
    removeTool: configState.removeTool,
    updateTool: vi.fn(),
    updateToolEntry: configState.updateToolEntry,
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

import ToolDetailPanel from './ToolDetailPanel';
import { AgentConfigBar } from './AgentConfigBar';

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

const MCP_PREVIEW = {
  toolType: 'mcp' as const,
  name: 'Docs server',
  connectionName: 'docs_conn',
  serverName: 'Docs server',
};

function renderAddPanel(preview: Record<string, unknown> = {}) {
  const onSave = vi.fn();
  const utils = render(
    <ToolDetailPanel
      preview={{ ...MCP_PREVIEW, ...preview } as never}
      mode="add"
      onSave={onSave}
      onCancel={vi.fn()}
    />,
  );
  return { onSave, ...utils };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  // The Tools row asks for admin-registered connections; none here.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: vi.fn().mockResolvedValue({ items: [] }),
    }),
  );
  configState.tools = [];
  configState.addTool.mockReset();
  configState.removeTool.mockReset();
  configState.updateToolEntry.mockReset();
  sessionState.storedDeckMode = null;
  sessionState.selectedDeckMode = 'agent';
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MCP add panel', () => {
  it('the MCP add panel saves agent data_analyst by default', () => {
    const { onSave } = renderAddPanel();
    expect((screen.getByRole('radio', { name: /^Data analyst/ }) as HTMLInputElement).checked).toBe(
      true,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Save & Add' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toMatchObject({
      type: 'mcp',
      connection_name: 'docs_conn',
      server_name: 'Docs server',
      agent: 'data_analyst',
    });
  });

  it('choosing Architect in the add panel saves agent architect', () => {
    const { onSave } = renderAddPanel();
    fireEvent.click(screen.getByRole('radio', { name: /^Architect/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save & Add' }));

    expect(onSave.mock.calls[0][0]).toMatchObject({ type: 'mcp', agent: 'architect' });
  });

  it('a preview that already names an agent starts on it', () => {
    const { onSave } = renderAddPanel({ agent: 'architect' });
    expect((screen.getByRole('radio', { name: /^Architect/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save & Add' }));
    expect(onSave.mock.calls[0][0]).toMatchObject({ agent: 'architect' });
  });

  it('the choice sits between Display Name and Description', () => {
    renderAddPanel();
    const panel = screen.getByTestId('tool-detail-panel');
    const displayName = screen.getByText('Display Name');
    const choice = screen.getByRole('group', { name: 'Which agent uses it?' });
    const description = screen.getByText('Description');
    const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;

    expect(panel.contains(choice)).toBe(true);
    expect(displayName.compareDocumentPosition(choice) & FOLLOWING).toBeTruthy();
    expect(choice.compareDocumentPosition(description) & FOLLOWING).toBeTruthy();
  });

  it('non-MCP add panels do not show the choice', () => {
    render(
      <ToolDetailPanel
        preview={{ toolType: 'agent_bricks', name: 'AB', endpointName: 'ep' }}
        mode="add"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByRole('group', { name: 'Which agent uses it?' })).toBeNull();
  });
});

describe('MCP edit panel', () => {
  function openEdit(tool: ToolEntry) {
    configState.tools = [tool];
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));
    fireEvent.click(screen.getByTestId('tool-chip-label'));
    return screen.getByTestId('tool-edit-panel');
  }

  it('the MCP edit panel preselects the stored agent and saves a change', () => {
    const panel = openEdit({
      type: 'mcp',
      connection_name: 'docs_conn',
      server_name: 'Docs server',
      description: 'old',
      agent: 'architect',
    });

    expect(
      (within(panel).getByRole('radio', { name: /^Architect/ }) as HTMLInputElement).checked,
    ).toBe(true);

    fireEvent.click(within(panel).getByRole('radio', { name: /^Data analyst/ }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Save' }));

    expect(configState.updateToolEntry).toHaveBeenCalledTimes(1);
    expect(configState.updateToolEntry.mock.calls[0][0]).toEqual({
      type: 'mcp',
      connection_name: 'docs_conn',
      server_name: 'Docs server',
      description: 'old',
      agent: 'data_analyst',
    });
  });

  it('a stored MCP tool with no agent opens on Data analyst and saves it', () => {
    const panel = openEdit({
      type: 'mcp',
      connection_name: 'docs_conn',
      server_name: 'Docs server',
    });
    expect(
      (within(panel).getByRole('radio', { name: /^Data analyst/ }) as HTMLInputElement).checked,
    ).toBe(true);
    fireEvent.click(within(panel).getByRole('button', { name: 'Save' }));
    expect(configState.updateToolEntry.mock.calls[0][0]).toMatchObject({ agent: 'data_analyst' });
  });

  it('the vector index edit panel has no agent choice', () => {
    const panel = openEdit({ type: 'vector_index', endpoint_name: 'ep', index_name: 'cat.s.idx' });
    expect(within(panel).queryByRole('group', { name: 'Which agent uses it?' })).toBeNull();
  });
});

/** The chip suffix: a span whose text is exactly `text` (leading space included). */
const suffix = (text: string) =>
  screen.getByText((_c, el) => el?.tagName === 'SPAN' && el.textContent === text && el.children.length === 0);

describe('chips', () => {
  function renderBar(tools: ToolEntry[]) {
    configState.tools = tools;
    render(<AgentConfigBar />);
    fireEvent.click(screen.getByTestId('agent-config-toggle'));
  }

  it('an mcp chip names its agent', () => {
    renderBar([
      { type: 'mcp', connection_name: 'c1', server_name: 'Docs server', agent: 'architect' },
      { type: 'mcp', connection_name: 'c2', server_name: 'Stats server' },
    ]);

    expect(suffix(' · Architect')).toBeInTheDocument();
    expect(suffix(' · Data analyst')).toBeInTheDocument();
    // The suffix is separate from the label, so the remove button still names the bare server.
    expect(screen.getByLabelText('Remove Docs server')).toBeTruthy();
    expect(screen.getByLabelText('Remove Stats server')).toBeTruthy();
    expect(screen.getAllByTestId('tool-chip-label').map((b) => b.textContent)).toEqual([
      'Docs server',
      'Stats server',
    ]);
  });

  it.each([
    ['vector_index', { type: 'vector_index', endpoint_name: 'ep', index_name: 'cat.s.idx' }, 'Remove ep'],
    ['agent_bricks', { type: 'agent_bricks', endpoint_name: 'brick_ep' }, 'Remove brick_ep'],
    ['model_endpoint', { type: 'model_endpoint', endpoint_name: 'model_ep' }, 'Remove model_ep'],
  ])('a %s chip on an agent deck says not used in agent mode', (_t, tool, removeLabel) => {
    renderBar([tool as ToolEntry]);
    expect(suffix(' · not used in agent mode')).toBeInTheDocument();
    expect(screen.getByTitle('Not used in agent mode')).toBeTruthy();
    expect(screen.getByLabelText(removeLabel)).toBeTruthy();
  });

  it('a chip on a locked agent deck says it even while the picker says legacy', () => {
    sessionState.storedDeckMode = 'agent';
    sessionState.selectedDeckMode = 'legacy';
    renderBar([{ type: 'vector_index', endpoint_name: 'ep', index_name: 'cat.s.idx' }]);
    expect(suffix(' · not used in agent mode')).toBeInTheDocument();
  });

  it('the same chip on a legacy deck has no suffix', () => {
    sessionState.storedDeckMode = 'legacy';
    renderBar([{ type: 'vector_index', endpoint_name: 'ep', index_name: 'cat.s.idx' }]);
    expect(screen.queryByText(/not used in agent mode/)).toBeNull();
    expect(screen.queryByTitle('Not used in agent mode')).toBeNull();
  });

  it('an mcp chip and a genie chip never say not used in agent mode', () => {
    renderBar([
      { type: 'mcp', connection_name: 'c1', server_name: 'Docs server' },
      { type: 'genie', space_id: 's1', space_name: 'Sales' },
    ]);
    expect(screen.queryByText(/not used in agent mode/)).toBeNull();
  });
});
