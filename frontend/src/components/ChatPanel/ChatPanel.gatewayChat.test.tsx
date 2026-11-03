/**
 * Gateway MCP final review.
 *
 * I1: the backend marks a sign-in notice row with `metadata.sign_in_url`, on the reloaded row
 * (`GET /api/sessions/{id}` -> `messages[].metadata.sign_in_url`) and on the polled `assistant`
 * event (`event.metadata.sign_in_url`). ChatPanel must carry it onto the UI message on BOTH paths,
 * so the real Message links that URL; an unmarked message with a URL renders no link.
 *
 * m6 (T7-b): a Gateway tool call's live label reads "{connection} · {tool}", not
 * "Querying gateway_mcp...". Other tools keep their label.
 */
import { createRef, type Ref } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const getSession = vi.fn();
const sendChatMessage = vi.fn();
// Stable across renders: ChatPanel's session effect depends on it, and a new function per render
// would re-run its cleanup (which clears the live label) on every render.
const setIsGenerating = vi.fn();
const deckModeSession = {
  storedDeckMode: null,
  selectedDeckMode: 'agent' as const,
  setSelectedDeckMode: vi.fn(),
  setStoredDeckMode: vi.fn(),
};

vi.mock('../../services/api', () => ({
  api: {
    getSession: (...a: unknown[]) => getSession(...a),
    sendChatMessage: (...a: unknown[]) => sendChatMessage(...a),
  },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: 'gateway-session',
    isSessionPersisted: true,
    isInitializing: false,
    error: null,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
    ...deckModeSession,
  }),
}));
vi.mock('../../contexts/AgentConfigContext', () => ({
  useAgentConfig: () => ({
    agentConfig: null,
    refreshConfig: vi.fn(),
    configOwnerSessionId: null,
    isPreSession: false,
  }),
}));
vi.mock('../../contexts/GenerationContext', () => ({
  useGeneration: () => ({ setIsGenerating }),
}));
// MessageList and Message are REAL: the link must reach the DOM through them.
vi.mock('./ChatInput', () => ({ ChatInput: () => null }));

import { ChatPanel, type ChatPanelHandle } from './ChatPanel';

const SIGN_IN_URL =
  'https://fevm-db-tellr-dev-workspace.cloud.databricks.com/mcp-service-login?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749';
const SIGN_IN = `To use LakeDraw, sign in here: ${SIGN_IN_URL} — then ask again.`;
const UNMARKED = 'The deck cites https://docs.example.com/page for the numbers.';

const row = (id: number, content: string, metadata: unknown) => ({
  id,
  role: 'assistant',
  content,
  message_type: 'info',
  created_at: '2026-11-03T00:00:00Z',
  metadata,
});

function mount(ref?: Ref<ChatPanelHandle>) {
  return render(
    <MemoryRouter>
      <ChatPanel
        ref={ref}
        rawHtml={null}
        onSlidesGenerated={vi.fn()}
        ensureGraphCapableRoot={async () => true}
      />
    </MemoryRouter>,
  );
}

async function sendWith(events: unknown[]) {
  getSession.mockResolvedValue({
    session_id: 'gateway-session',
    messages: [row(1, 'earlier line', null)],
  });
  sendChatMessage.mockImplementation(
    (_sessionId: string, _message: string, _ctx: unknown, onEvent: (e: unknown) => void) => {
      for (const event of events) onEvent(event);
      return () => {};
    },
  );
  const ref = createRef<ChatPanelHandle>();
  mount(ref);
  // Let the history load settle first, so its setMessages cannot overwrite the streamed rows.
  await screen.findByText('earlier line');
  await act(async () => {
    ref.current!.sendMessage('hi');
  });
}

describe('ChatPanel links only the server-marked sign-in notice', () => {
  beforeEach(() => {
    getSession.mockReset();
    sendChatMessage.mockReset();
  });

  it('reload: the row with metadata.sign_in_url renders one link; an unmarked URL renders none', async () => {
    getSession.mockResolvedValue({
      session_id: 'gateway-session',
      messages: [row(1, UNMARKED, null), row(2, SIGN_IN, { sign_in_url: SIGN_IN_URL })],
    });

    mount();

    await screen.findByText(UNMARKED);
    const links = await screen.findAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe(SIGN_IN_URL);
    expect(links[0].getAttribute('target')).toBe('_blank');
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('poll/stream: an assistant event with metadata.sign_in_url renders one link; one without none', async () => {
    await sendWith([
      { type: 'assistant', content: UNMARKED },
      { type: 'assistant', content: SIGN_IN, metadata: { sign_in_url: SIGN_IN_URL } },
    ]);

    await screen.findByText(UNMARKED);
    const links = await screen.findAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe(SIGN_IN_URL);
  });
});

describe('ChatPanel live label for a Gateway tool call', () => {
  beforeEach(() => {
    getSession.mockReset();
    sendChatMessage.mockReset();
  });

  it('a gateway_mcp tool call shows "{connection} · {tool}"', async () => {
    await sendWith([
      {
        type: 'tool_call',
        content: 'LakeDraw · lakedraw_create_from_spec',
        tool_name: 'gateway_mcp',
        tool_input: { connection: 'LakeDraw', tool: 'lakedraw_create_from_spec' },
      },
    ]);

    expect(await screen.findByText('LakeDraw · lakedraw_create_from_spec')).toBeInTheDocument();
    expect(screen.queryByText(/Querying gateway_mcp/)).toBeNull();
  });

  it('a gateway_mcp tool call without a connection keeps the generic label', async () => {
    await sendWith([{ type: 'tool_call', tool_name: 'gateway_mcp', tool_input: {} }]);

    expect(await screen.findByText('Querying gateway_mcp...')).toBeInTheDocument();
  });

  it('another tool keeps its "Querying <tool>..." label', async () => {
    await sendWith([
      { type: 'tool_call', tool_name: 'genie_one', tool_input: { question: 'How many trips?' } },
    ]);

    expect(await screen.findByText('Querying genie_one...')).toBeInTheDocument();
  });
});
