/**
 * The admin "Add Genie One to new decks" setting. A new deck starts with the Genie One pill when
 * the setting is on, however it was started:
 *   - the pre-session surface ("/") with no localStorage mirror (opening the app);
 *   - "New Deck", which creates the session first and lands on a session that has no stored
 *     config yet (`is_configured: false`);
 *   - a reload of "/" whose mirror lacks the pill. A reload is a reset: the mirror's other choices
 *     are kept, but a pill the user removed comes back.
 * A session that HAS a stored config is the user's own deck and is never seeded.
 *
 * Harness: the real AgentConfigProvider on a pre-session route ("/") or a session route, as in
 * AgentConfigContext.genieOne.test.tsx, with `api.getGenieOneDefault` standing in for the setting.
 *
 * SABOTAGE (each should turn the named test RED):
 *   - skip the setting in the default load             -> "adds Genie One to a new deck ..."
 *   - add Genie One without checking the setting       -> "leaves a new deck without tools ..."
 *   - replace the profile's tools instead of adding    -> "keeps the default profile's tools ..."
 *   - skip the setting on the unconfigured-session GET -> "adds Genie One to a deck started with New Deck ..."
 *   - seed every session GET, configured or not        -> "does not add Genie One to an existing deck ..."
 *   - skip the setting in the stored-config branch     -> "re-adds Genie One on a reload ..."
 *   - replace the stored config instead of adding      -> "keeps the rest of a stored config ..."
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ToolEntry } from '../types/agentConfig';

const listProfiles = vi.fn();
const getGenieOneDefault = vi.fn();
const getAgentConfig = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    listProfiles: (...args: unknown[]) => listProfiles(...args),
    getGenieOneDefault: (...args: unknown[]) => getGenieOneDefault(...args),
    getAgentConfig: (...args: unknown[]) => getAgentConfig(...args),
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
  return (
    <>
      <div data-testid="types">{agentConfig.tools.map((t) => t.type).join(',')}</div>
      <div data-testid="design-system">{String(agentConfig.design_system_id)}</div>
    </>
  );
};

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AgentConfigProvider>
        <Probe />
      </AgentConfigProvider>
    </MemoryRouter>,
  );
}

function renderNewDeck() {
  renderAt('/');
}

/** "New Deck" creates the session first, so the deck opens on its session route. */
function renderSession(sessionId: string) {
  renderAt(`/sessions/${sessionId}/edit`);
}

const EMPTY_CONFIG = {
  tools: [] as ToolEntry[],
  slide_style_id: null,
  design_system_id: null,
  template_id: null,
  deck_prompt_id: null,
};

function storeMirror(config: Record<string, unknown>) {
  localStorage.setItem('pendingAgentConfig', JSON.stringify({ ...EMPTY_CONFIG, ...config }));
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
    getAgentConfig.mockReset().mockResolvedValue({ ...EMPTY_CONFIG, is_configured: true });
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

  it('adds Genie One to a deck started with New Deck (a session with no stored config)', async () => {
    getAgentConfig.mockResolvedValue({ ...EMPTY_CONFIG, is_configured: false });
    getGenieOneDefault.mockResolvedValue(true);
    renderSession('new-deck');
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie_one'));
  });

  it('leaves a deck started with New Deck without Genie One when the admin setting is off', async () => {
    getAgentConfig.mockResolvedValue({ ...EMPTY_CONFIG, is_configured: false });
    getGenieOneDefault.mockResolvedValue(false);
    listProfiles.mockResolvedValue([defaultProfile([GENIE])]);
    renderSession('new-deck');
    // The profile's tool landing proves the load settled.
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie'));
  });

  it('does not add Genie One to an existing deck (the user removed it there)', async () => {
    getAgentConfig.mockResolvedValue({ ...EMPTY_CONFIG, tools: [GENIE], is_configured: true });
    getGenieOneDefault.mockResolvedValue(true);
    renderSession('existing-deck');
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie'));
    // Let any async seeding settle before asserting nothing was added.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByTestId('types').textContent).toBe('genie');
  });

  it('re-adds Genie One on a reload even though the user removed it before (a reset)', async () => {
    storeMirror({ style_source: 'user' });
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie_one'));
  });

  it('keeps the rest of a stored config on a reload and adds Genie One after its tools', async () => {
    // Design system and deck prompt both set: the stored-config path that needs no style resolve.
    storeMirror({ tools: [GENIE], design_system_id: 7, deck_prompt_id: 3, style_source: 'user' });
    getGenieOneDefault.mockResolvedValue(true);
    renderNewDeck();
    await waitFor(() => expect(screen.getByTestId('types').textContent).toBe('genie,genie_one'));
    expect(screen.getByTestId('design-system').textContent).toBe('7');
  });

  it('leaves a stored config without Genie One on a reload when the admin setting is off', async () => {
    storeMirror({ style_source: 'user' });
    getGenieOneDefault.mockResolvedValue(false);
    renderNewDeck();
    // Let the reload's async load settle before asserting nothing was added.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByTestId('types').textContent).toBe('');
  });
});
