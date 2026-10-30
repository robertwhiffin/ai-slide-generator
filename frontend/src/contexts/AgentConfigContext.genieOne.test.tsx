/**
 * PLAN-CORRECTIONS C1: removeTool's filter ends with `return true`, so a
 * `genie_one` entry (no identifying key) would never be removable without its
 * own branch.
 *
 * Harness: the real AgentConfigProvider on a pre-session route ("/"), seeded from
 * the localStorage mirror. Pre-session updateConfig is local-only, so no backend
 * is involved; any stray network call is mocked out.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ToolEntry } from '../types/agentConfig';

vi.mock('../services/api', () => ({
  api: {
    listProfiles: vi.fn().mockResolvedValue({ profiles: [] }),
    getAgentConfig: vi.fn().mockResolvedValue({ tools: [] }),
    updateAgentConfig: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../api/config', () => ({
  configApi: {
    listSlideStyles: vi.fn().mockResolvedValue({ styles: [] }),
    listDesignSystems: vi.fn().mockResolvedValue({ design_systems: [] }),
    listDeckPrompts: vi.fn().mockResolvedValue({ prompts: [] }),
    listDesignSystemTemplates: vi.fn().mockResolvedValue({ templates: [] }),
  },
}));

vi.mock('./ToastContext', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

import { AgentConfigProvider, useAgentConfig } from './AgentConfigContext';


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

const GENIE_ONE = { type: 'genie_one' } as unknown as ToolEntry;
const GENIE = { type: 'genie', space_id: 'g1', space_name: 'Sales' } as unknown as ToolEntry;

const Probe: React.FC<{ remove: ToolEntry }> = ({ remove }) => {
  const { agentConfig, removeTool } = useAgentConfig();
  return (
    <div>
      <div data-testid="types">{agentConfig.tools.map((t) => t.type).join(',')}</div>
      <button onClick={() => void removeTool(remove)}>remove</button>
    </div>
  );
};

function renderWith(stored: ToolEntry[], remove: ToolEntry) {
  localStorage.setItem(
    'pendingAgentConfig',
    JSON.stringify({
      tools: stored,
      slide_style_id: null,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
      style_source: 'user',
    }),
  );
  render(
    <MemoryRouter initialEntries={['/']}>
      <AgentConfigProvider>
        <Probe remove={remove} />
      </AgentConfigProvider>
    </MemoryRouter>,
  );
}

describe('AgentConfigContext.removeTool: genie_one (C1)', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
  });

  it('removes a genie_one entry', async () => {
    renderWith([GENIE_ONE], GENIE_ONE);
    expect(screen.getByTestId('types').textContent).toBe('genie_one');
    fireEvent.click(screen.getByText('remove'));
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe(''));
  });

  it('removes only genie_one and leaves other tools in place', async () => {
    renderWith([GENIE, GENIE_ONE], GENIE_ONE);
    expect(screen.getByTestId('types').textContent).toBe('genie,genie_one');
    fireEvent.click(screen.getByText('remove'));
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie'));
  });
});
