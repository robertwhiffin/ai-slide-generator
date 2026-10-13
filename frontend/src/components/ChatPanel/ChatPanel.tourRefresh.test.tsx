/**
 * The tour writes chat lines server-side for the session already on screen, so sessionId never
 * changes. ChatPanel must reload its history when `tour:refresh-session` targets its session.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const getSession = vi.fn();

vi.mock('../../services/api', () => ({
  api: { getSession: (...a: unknown[]) => getSession(...a) },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: 'tour-demo',
    isSessionPersisted: true,
    isInitializing: false,
    error: null,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
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
vi.mock('./MessageList', () => ({
  MessageList: ({ messages }: { messages: { content: string }[] }) => (
    <ul>{messages.map((m, i) => <li key={i}>{m.content}</li>)}</ul>
  ),
}));
vi.mock('./ChatInput', () => ({ ChatInput: () => null }));

import { ChatPanel } from './ChatPanel';

const msg = (content: string) => ({ role: 'assistant', content, created_at: 't', metadata: null });

function refresh(sessionId: string) {
  act(() => {
    window.dispatchEvent(new CustomEvent('tour:refresh-session', { detail: { sessionId } }));
  });
}

describe('ChatPanel tour:refresh-session', () => {
  beforeEach(() => {
    getSession.mockReset();
    getSession.mockResolvedValue({ messages: [msg('message A')] });
  });

  function mount() {
    return render(
      <MemoryRouter>
        <ChatPanel rawHtml={null} onSlidesGenerated={vi.fn()} ensureGraphCapableRoot={async () => true} />
      </MemoryRouter>,
    );
  }

  it('reloads history for its own session so newly written lines appear', async () => {
    mount();
    await screen.findByText('message A');
    getSession.mockResolvedValue({ messages: [msg('message A'), msg('message B')] });
    refresh('tour-demo');
    await screen.findByText('message B');
    expect(getSession).toHaveBeenCalledTimes(2);
  });

  it('ignores a refresh for a different session', async () => {
    mount();
    await screen.findByText('message A');
    getSession.mockResolvedValue({ messages: [msg('message A'), msg('message B')] });
    refresh('someone-else');
    await new Promise(r => setTimeout(r, 30));
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('message B')).toBeNull();
  });
});
