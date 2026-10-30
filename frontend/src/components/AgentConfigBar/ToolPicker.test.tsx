/**
 * ToolPicker: the one-click "+ Genie One" button (Genie One in agent mode, Task 3),
 * and the AgentConfigBar chip it produces.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ToolEntry } from '../../types/agentConfig';

const sessionState = vi.hoisted(() => ({
  storedDeckMode: null as 'agent' | 'legacy' | null,
  selectedDeckMode: 'agent' as 'agent' | 'legacy',
}));
const configState = vi.hoisted(() => ({ tools: [] as unknown[] }));

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
    addTool: vi.fn(),
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

describe('ToolPicker: + Genie One', () => {
  it('renders "+ Genie One" as the FIRST button, with the other buttons unchanged after it', () => {
    renderPicker();
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual([
      '+ Genie One',
      '+ Genie Agent',
      '+ Agent Bricks',
      '+ Vector Index',
      '+ MCP Server',
      '+ Model Endpoint',
    ]);
    expect(buttons[0]).toBe(screen.getByTestId('add-tool-genie_one'));
  });

  it('clicking it calls onSelect with {type: genie_one} and opens no discovery panel', () => {
    const { onSelect } = renderPicker();
    fireEvent.click(screen.getByTestId('add-tool-genie_one'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith({ type: 'genie_one' });
    // Still just the six category buttons: no discovery panel mounted.
    expect(screen.getAllByRole('button')).toHaveLength(6);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('searchbox')).toBeNull();
  });

  it('is absent once existingTools already holds a genie_one entry', () => {
    renderPicker([GENIE_ONE]);
    expect(screen.queryByTestId('add-tool-genie_one')).toBeNull();
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual([
      '+ Genie Agent',
      '+ Agent Bricks',
      '+ Vector Index',
      '+ MCP Server',
      '+ Model Endpoint',
    ]);
  });
});

describe('AgentConfigBar: Genie One chip', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
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
