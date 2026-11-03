/**
 * The admin "Add Genie One to new decks" setting: a genuinely NEW pre-session surface (no
 * localStorage mirror) starts with the Genie One pill when the setting is on. A stored config is
 * the user's own state and is never seeded over.
 *
 * Harness: the real AgentConfigProvider on a pre-session route ("/"), as in
 * AgentConfigContext.genieOne.test.tsx, with `api.getGenieOneDefault` standing in for the setting.
 *
 * SABOTAGE (each should turn the named test RED):
 *   - skip the setting in the default load            -> "adds Genie One to a new deck ..."
 *   - add Genie One without checking the setting      -> "leaves a new deck without tools ..."
 *   - replace the profile's tools instead of adding   -> "keeps the default profile's tools ..."
 *   - seed the stored-config branch too               -> "does not touch a stored config ..."
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ToolEntry } from '../types/agentConfig';

const listProfiles = vi.fn();
const getGenieOneDefault = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    listProfiles: (...args: unknown[]) => listProfiles(...args),
    getGenieOneDefault: (...args: unknown[]) => getGenieOneDefault(...args),
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

const GENIE = { type: 'genie', space_id: 'g1', space_name: 'Sales' } as unknown as ToolEntry;

const Probe: React.FC = () => {
  const { agentConfig } = useAgentConfig();
  return <div data-testid="types">{agentConfig.tools.map((t) => t.type).join(',')}</div>;
};

function renderNewDeck() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <AgentConfigProvider>
        <Probe />
      </AgentConfigProvider>
    </MemoryRouter>,
  );
}

const defaultProfile = (tools: ToolEntry[]) => ({
  id: 1,
  name: 'Default',
  is_default: true,
  created_by: 'someone@example.com',
  agent_config: {
    tools,
    slide_style_id: null,
    design_system_id: null,
    template_id: null,
    deck_prompt_id: null,
  },
});

describe('AgentConfigContext: the Genie One new-deck default', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
    listProfiles.mockReset().mockResolvedValue([]);
    getGenieOneDefault.mockReset();
  });

  it('adds Genie One to a new deck when the admin setting is on', async () => {
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie_one'));
  });

  it('leaves a new deck without tools when the admin setting is off', async () => {
    getGenieOneDefault.mockResolvedValue(false);
    renderNewDeck();
    await waitFor(() => expect(getGenieOneDefault).toHaveBeenCalled());
    await waitFor(() => expect(localStorage.getItem('pendingAgentConfig')).not.toBeNull());
    expect(screen.getByTestId('types').textContent).toBe('');
  });

  it("keeps the default profile's tools and adds Genie One after them", async () => {
    listProfiles.mockResolvedValue([defaultProfile([GENIE])]);
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie,genie_one'));
  });

  it('does not add a second Genie One when the default profile already has it', async () => {
    listProfiles.mockResolvedValue([
      defaultProfile([{ type: 'genie_one' } as unknown as ToolEntry]),
    ]);
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    await waitFor(() => expect(localStorage.getItem('pendingAgentConfig')).not.toBeNull());
    expect(screen.getByTestId('types').textContent).toBe('genie_one');
  });

  it('does not touch a stored config (the user removed the pill earlier)', async () => {
    localStorage.setItem(
      'pendingAgentConfig',
      JSON.stringify({
        tools: [],
        slide_style_id: null,
        design_system_id: null,
        template_id: null,
        deck_prompt_id: null,
        style_source: 'user',
      }),
    );
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    // Let any async default load settle before asserting nothing changed.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByTestId('types').textContent).toBe('');
  });
});
