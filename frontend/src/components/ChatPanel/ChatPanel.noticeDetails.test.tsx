/**
 * The backend puts a failure notice's technical detail on `metadata.details`: on the reloaded
 * row (`GET /api/sessions/{id}` -> `messages[].metadata.details`) and on the polled `assistant`
 * event (`event.metadata.details`). ChatPanel must carry it onto the UI message on BOTH paths so
 * the real Message renders its Details disclosure; rows and events without details render none.
 */
import { createRef, type Ref } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const getSession = vi.fn();
const sendChatMessage = vi.fn();
// Deck Mode (Task 7): the four SessionContext members ChatPanel reads; stable identities.
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
    sessionId: 'notice-session',
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
  useGeneration: () => ({ setIsGenerating: vi.fn() }),
}));
// MessageList and Message are REAL: the disclosure must reach the DOM through them.
vi.mock('./ChatInput', () => ({ ChatInput: () => null }));

import { ChatPanel, type ChatPanelHandle } from './ChatPanel';

const row = (content: string, metadata: unknown) => ({
  id: 1,
  role: 'assistant',
  content,
  message_type: 'info',
  created_at: '2026-10-19T00:00:00Z',
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

/** The bubble a message's content sits in (Message renders the content div inside it). */
function bubbleOf(text: string): HTMLElement {
  const content = screen.getByText(text);
  expect(content.parentElement).not.toBeNull();
  return content.parentElement!;
}

describe('ChatPanel carries notice details onto chat messages', () => {
  beforeEach(() => {
    getSession.mockReset();
    sendChatMessage.mockReset();
  });

  it('reload: only the row with metadata.details shows a disclosure, inside its own bubble', async () => {
    getSession.mockResolvedValue({
      session_id: 'notice-session',
      messages: [
        row('old notice', null),
        row('tool row', { tool_name: 'q', tool_input: {} }),
        // A tour row's metadata is all strings, so reading the whole metadata as details would show one.
        row('tour reply', { tour_stage: 'prompt', node: 'architect' }),
        row('new notice', {
          details: { stage: 'builder', error: 'RuntimeError', request_id: 'req-1' },
        }),
      ],
    });

    mount();

    // All four rows render (the tool row as its collapsed tool-call header).
    await screen.findByText('new notice');
    expect(screen.getByText('old notice')).toBeInTheDocument();
    expect(screen.getByText('Tool call: q')).toBeInTheDocument();
    expect(screen.getByText('tour reply')).toBeInTheDocument();
    expect(getSession).toHaveBeenCalledWith('notice-session');

    const disclosures = screen.getAllByTestId('message-details');
    expect(disclosures).toHaveLength(1);
    expect(within(bubbleOf('new notice')).getByTestId('message-details')).toBe(disclosures[0]);
    expect(within(bubbleOf('old notice')).queryByTestId('message-details')).toBeNull();
    expect(within(bubbleOf('tour reply')).queryByTestId('message-details')).toBeNull();

    // The disclosure shows the row's own detail values.
    const details = within(disclosures[0]);
    expect(details.getByText('builder')).toBeInTheDocument();
    expect(details.getByText('RuntimeError')).toBeInTheDocument();
    expect(details.getByText('req-1')).toBeInTheDocument();
  });

  it('stream: an assistant event with metadata.details shows a disclosure; one without does not', async () => {
    getSession.mockResolvedValue({
      session_id: 'notice-session',
      messages: [row('earlier line', null)],
    });
    sendChatMessage.mockImplementation(
      (_sessionId: string, _message: string, _ctx: unknown, onEvent: (e: unknown) => void) => {
        onEvent({ type: 'assistant', content: 'plain reply' });
        // An SSE progress line: string-valued metadata that is NOT details must not
        // grow a disclosure (guards a `metadata?.details ?? metadata` fallback).
        onEvent({
          type: 'assistant',
          content: 'progress line',
          metadata: { node: 'build_reviewer', verdict: 'clean' },
        });
        onEvent({
          type: 'assistant',
          content: 'streamed notice',
          metadata: { details: { stage: 'foreman' } },
        });
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

    await screen.findByText('streamed notice');
    expect(sendChatMessage).toHaveBeenCalledTimes(1);
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('plain reply')).toBeInTheDocument();

    const disclosures = screen.getAllByTestId('message-details');
    expect(disclosures).toHaveLength(1);
    expect(within(bubbleOf('streamed notice')).getByTestId('message-details')).toBe(disclosures[0]);
    expect(within(bubbleOf('plain reply')).queryByTestId('message-details')).toBeNull();
    expect(within(bubbleOf('progress line')).queryByTestId('message-details')).toBeNull();
    expect(within(disclosures[0]).getByText('foreman')).toBeInTheDocument();
  });
});

describe('ChatPanel carries the data analyst tag onto chat messages', () => {
  const REPORT = 'Trips rose 4% in 10001. | zip | trips |\n| 10001 | 1227 |';

  beforeEach(() => {
    getSession.mockReset();
    sendChatMessage.mockReset();
  });

  it('reload: a history row with metadata.agent renders the analyst card; others do not', async () => {
    getSession.mockResolvedValue({
      session_id: 'notice-session',
      messages: [
        row('architect reply', { node: 'architect' }),
        row(REPORT, { agent: 'data_analyst' }),
      ],
    });

    mount();

    await screen.findByText('Data analyst');
    const cards = screen.getAllByTestId('analyst-report');
    expect(cards).toHaveLength(1);
    expect(screen.getByText('architect reply')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Data analyst')).toBeInTheDocument();
  });

  it('poll/stream: an assistant event with agent data_analyst renders the card; one without does not', async () => {
    getSession.mockResolvedValue({
      session_id: 'notice-session',
      messages: [row('earlier line', null)],
    });
    sendChatMessage.mockImplementation(
      (_sessionId: string, _message: string, _ctx: unknown, onEvent: (e: unknown) => void) => {
        onEvent({ type: 'assistant', content: 'plain reply' });
        onEvent({ type: 'assistant', content: REPORT, agent: 'data_analyst' });
        return () => {};
      },
    );

    const ref = createRef<ChatPanelHandle>();
    mount(ref);
    await screen.findByText('earlier line');

    await act(async () => {
      ref.current!.sendMessage('hi');
    });

    await screen.findByText('Data analyst');
    expect(screen.getAllByTestId('analyst-report')).toHaveLength(1);
    expect(screen.getByText('plain reply')).toBeInTheDocument();
  });
});
