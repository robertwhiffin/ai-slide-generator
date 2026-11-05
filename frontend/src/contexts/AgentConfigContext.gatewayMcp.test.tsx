/**
 * Gateway MCP Task 7 (PLAN-CORRECTIONS T7.1): removeTool's filter ends with `return true`, so a
 * `gateway_mcp` entry without its own branch could never be removed. Entries are keyed by
 * `service_name`; removing one must leave every other entry (Gateway or not) in place.
 * updateToolEntry likewise needs a `gateway_mcp` case keyed by `service_name`.
 *
 * Harness (copied from AgentConfigContext.genieOne.test.tsx): the real AgentConfigProvider on a
 * pre-session route ("/"), seeded from the localStorage mirror. Pre-session updateConfig is
 * local-only, so no backend is involved; any stray network call is mocked out.
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
    // The admin "Add Genie One to new decks" setting, off (the real call never rejects).
    getGenieOneDefault: vi.fn().mockResolvedValue(false),
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

const LAKEDRAW = {
  type: 'gateway_mcp',
  service_name: 'db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw',
  display_name: 'LakeDraw',
} as unknown as ToolEntry;
const WEB_SEARCH = {
  type: 'gateway_mcp',
  service_name: 'system.ai.web_search',
  display_name: 'Web Search',
} as unknown as ToolEntry;
const GENIE = { type: 'genie', space_id: 'g1', space_name: 'Sales' } as unknown as ToolEntry;
const MCP = { type: 'mcp', connection_name: 'sales_http', server_name: 'sales_http' } as unknown as ToolEntry;

/** "gateway_mcp:<service>:<display>" for Gateway entries, the bare type for anything else. */
function describeTool(t: ToolEntry): string {
  const r = t as unknown as Record<string, unknown>;
  return r.type === 'gateway_mcp' ? `gateway_mcp:${r.service_name}:${r.display_name}` : String(r.type);
}

const Probe: React.FC<{ remove?: ToolEntry; update?: ToolEntry }> = ({ remove, update }) => {
  const { agentConfig, removeTool, updateToolEntry } = useAgentConfig();
  return (
    <div>
      <div data-testid="tools">{agentConfig.tools.map(describeTool).join(',')}</div>
      {remove && <button onClick={() => void removeTool(remove)}>remove</button>}
      {update && <button onClick={() => void updateToolEntry(update)}>update</button>}
    </div>
  );
};

function renderWith(stored: ToolEntry[], props: { remove?: ToolEntry; update?: ToolEntry }) {
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
        <Probe {...props} />
      </AgentConfigProvider>
    </MemoryRouter>,
  );
}

const tools = () => screen.getByTestId('tools').textContent;

describe('AgentConfigContext: gateway_mcp entries (T7.1)', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage());
  });

  it('removeTool removes ONLY the matching gateway entry, by service_name, when two exist', async () => {
    renderWith([LAKEDRAW, WEB_SEARCH], { remove: LAKEDRAW });
    expect(tools()).toBe(
      'gateway_mcp:db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw:LakeDraw,'
      + 'gateway_mcp:system.ai.web_search:Web Search',
    );

    fireEvent.click(screen.getByText('remove'));

    await waitFor(() => expect(tools()).toBe('gateway_mcp:system.ai.web_search:Web Search'));
  });

  it('removeTool matches by service_name even when the display name differs', async () => {
    const renamed = { ...(WEB_SEARCH as object), display_name: 'Search (renamed)' } as unknown as ToolEntry;
    renderWith([LAKEDRAW, WEB_SEARCH], { remove: renamed });

    fireEvent.click(screen.getByText('remove'));

    await waitFor(() =>
      expect(tools()).toBe('gateway_mcp:db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw:LakeDraw'),
    );
  });

  it('removeTool of a gateway entry leaves other tool types in place', async () => {
    renderWith([GENIE, LAKEDRAW, MCP], { remove: LAKEDRAW });

    fireEvent.click(screen.getByText('remove'));

    await waitFor(() => expect(tools()).toBe('genie,mcp'));
  });

  it('updateToolEntry replaces only the gateway entry with the same service_name', async () => {
    const updated = { ...(LAKEDRAW as object), display_name: 'LakeDraw v2' } as unknown as ToolEntry;
    renderWith([LAKEDRAW, WEB_SEARCH], { update: updated });

    fireEvent.click(screen.getByText('update'));

    await waitFor(() =>
      expect(tools()).toBe(
        'gateway_mcp:db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw:LakeDraw v2,'
        + 'gateway_mcp:system.ai.web_search:Web Search',
      ),
    );
  });
});
