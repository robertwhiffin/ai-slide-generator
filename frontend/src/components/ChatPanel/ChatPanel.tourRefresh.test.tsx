/**
 * The tour writes chat lines server-side for the session already on screen, so sessionId never
 * changes. ChatPanel must reload its history when `tour:refresh-session` targets its session.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const getSession = vi.fn();
let currentSessionId = 'tour-demo';
// Deck Mode (Task 7): the four SessionContext members ChatPanel reads; stable identities.
const deckModeSession = {
  storedDeckMode: null,
  selectedDeckMode: 'agent' as const,
  setSelectedDeckMode: vi.fn(),
  setStoredDeckMode: vi.fn(),
};

vi.mock('../../services/api', () => ({
  api: { getSession: (...a: unknown[]) => getSession(...a) },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: currentSessionId,
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
    currentSessionId = 'tour-demo';
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

  it('drops a refresh response that lands after the session changed (tour ended mid-load)', async () => {
    const view = mount();
    await screen.findByText('message A');
    let resolveLate: (v: unknown) => void = () => {};
    getSession.mockImplementationOnce(() => new Promise(r => { resolveLate = r; }));
    refresh('tour-demo');
    // endDemo -> createNewSession: the workspace moves to a fresh session before the refresh lands.
    getSession.mockResolvedValue({ messages: [] });
    currentSessionId = 'fresh-session';
    view.rerender(
      <MemoryRouter>
        <ChatPanel rawHtml={null} onSlidesGenerated={vi.fn()} ensureGraphCapableRoot={async () => true} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getSession).toHaveBeenCalledWith('fresh-session'));
    await act(async () => { resolveLate({ messages: [msg('demo line')] }); });
    await new Promise(r => setTimeout(r, 30));
    expect(screen.queryByText('demo line')).toBeNull();
  });
});
