/**
 * #319 — ChatPanel feeds the graph turn's stage summary into the chat placeholder.
 *
 * The real ChatPanel and the real MessageList are mounted.  `api.sendChatMessage` is
 * mocked: it captures `onEvent` / `onError`, so each test drives a turn event by event.
 * Both transports (SSE `streamChat` and polling `startPolling`) hand ChatPanel the same
 * `{type: 'turn_progress', turn_progress}` event through `onEvent`, and polling's
 * `status=error` arrives through `onError`.  These tests therefore cover the placeholder
 * on both transports; each transport's own forwarding is tested in src/services/.
 *
 * Harness rule (plan Task 8): `setIsGenerating` and `refreshConfig` are hoisted, stable
 * identities, and every context mock returns the same object on every render.  ChatPanel's
 * effects keyed on `[sessionId, setIsGenerating]` and `[setIsGenerating]` end loading in
 * their cleanup, so a fresh `vi.fn()` per render (as in ChatPanel.tourRefresh.test.tsx)
 * would hide the placeholder right after send, for a harness reason.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { StreamEvent } from '../../services/api';
import type { TurnPhase, TurnProgress, TurnProgressSlides } from '../../types/turnProgress';

const h = vi.hoisted(() => {
  const setIsGenerating = vi.fn();
  const refreshConfig = vi.fn();
  return {
    setIsGenerating,
    refreshConfig,
    session: {
      sessionId: 'session-319',
      isSessionPersisted: true,
      isInitializing: false,
      error: null,
      setExperimentUrl: vi.fn(),
      setSessionTitle: vi.fn(),
      // Deck Mode (Task 7): the four SessionContext members ChatPanel reads.
      storedDeckMode: null,
      selectedDeckMode: 'agent' as const,
      setSelectedDeckMode: vi.fn(),
      setStoredDeckMode: vi.fn(),
    },
    agentConfig: { agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false },
    generation: { setIsGenerating },
    getSession: vi.fn(),
    sendChatMessage: vi.fn(),
  };
});

vi.mock('../../services/api', () => ({
  api: {
    getSession: (...a: unknown[]) => h.getSession(...a),
    sendChatMessage: (...a: unknown[]) => h.sendChatMessage(...a),
    getSlides: vi.fn(async () => ({ slide_deck: null })),
    getCurrentSessionId: vi.fn(() => 'session-319'),
    setCurrentSessionId: vi.fn(),
  },
}));
vi.mock('../../contexts/SessionContext', () => ({ useSession: () => h.session }));
vi.mock('../../contexts/AgentConfigContext', () => ({ useAgentConfig: () => h.agentConfig }));
vi.mock('../../contexts/GenerationContext', () => ({ useGeneration: () => h.generation }));
vi.mock('./ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (message: string) => void; disabled: boolean }) => (
    <button type="button" disabled={disabled} onClick={() => { onSend('build me a deck'); }}>
      send
    </button>
  ),
}));

import { ChatPanel } from './ChatPanel';

let onEvent: (event: StreamEvent) => void = () => {};
let onError: (error: Error) => void = () => {};

beforeEach(() => {
  vi.clearAllMocks();
  h.getSession.mockResolvedValue({ messages: [] });
  h.sendChatMessage.mockImplementation(
    (_sessionId: string, _message: string, _ctx: unknown, ev: typeof onEvent, err: typeof onError) => {
      onEvent = ev;
      onError = err;
      return () => {};
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
});

/** A well-formed snapshot; slide lists default to empty. */
function tp(seq: number, phase: TurnPhase, slides: Partial<TurnProgressSlides> = {}): TurnProgress {
  return {
    seq,
    phase,
    slides: { total: 0, building: [], reviewing: [], fixing: [], done: [], ...slides },
  };
}

const onSlidesGenerated = vi.fn();
const ensureGraphCapableRoot = async () => true;

function panel() {
  return (
    <MemoryRouter>
      <ChatPanel rawHtml={null} onSlidesGenerated={onSlidesGenerated} ensureGraphCapableRoot={ensureGraphCapableRoot} />
    </MemoryRouter>
  );
}

async function mount() {
  const view = render(panel());
  // Let the mount-time history load settle, so it cannot clear the chat mid-test.
  await act(async () => {});
  expect(h.getSession).toHaveBeenCalledWith('session-319');
  return view;
}

function send() {
  fireEvent.click(screen.getByRole('button', { name: 'send' }));
}

function emit(event: StreamEvent) {
  act(() => { onEvent(event); });
}

function progress(snapshot: TurnProgress) {
  emit({ type: 'turn_progress', turn_progress: snapshot });
}

/** A snapshot whose `seq` is a string: otherwise well formed, so only validation rejects it. */
function stringSeq(seq: number, phase: TurnPhase): TurnProgress {
  return { ...tp(seq, phase), seq: String(seq) } as unknown as TurnProgress;
}

const placeholder = () => screen.getByTestId('chat-turn-progress');

function expectLabel(text: string) {
  expect(placeholder().textContent?.trim()).toBe(text);
}

describe('ChatPanel turn-progress placeholder (#319)', () => {
  it('shows the generic text until the first stage arrives', async () => {
    await mount();
    send();
    // Harness check: the turn is loading and stayed loading (stable setIsGenerating).
    expect(h.sendChatMessage).toHaveBeenCalledTimes(1);
    expect(h.setIsGenerating).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('Generating slides...')).toBeInTheDocument();

    expectLabel('Generating slides...');
    emit({ type: 'assistant', content: 'On it.' });
    expectLabel('Generating slides...');

    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');
    expect(screen.queryByText('Generating slides...')).toBeNull();
  });

  it('shows each stage as it arrives', async () => {
    await mount();
    send();
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');
    progress(tp(2, 'building', { total: 3, building: [0, 1, 2] }));
    expectLabel('Building 3 slides…');
    progress(tp(3, 'building', { total: 3, building: [1, 2], reviewing: [0] }));
    expectLabel('Building 2 slides, reviewing slide 1…');
    progress(tp(4, 'reviewing_deck', { total: 3, done: [0, 1, 2] }));
    expectLabel('Reviewing the narrative…');
  });

  it('ignores an older or repeated snapshot', async () => {
    await mount();
    send();
    progress(tp(5, 'building', { total: 3, reviewing: [2], done: [0, 1] }));
    expectLabel('Reviewing slide 3… (2 of 3 done)');

    progress(tp(4, 'planning'));
    expectLabel('Reviewing slide 3… (2 of 3 done)');

    progress(tp(5, 'reviewing_deck'));
    expectLabel('Reviewing slide 3… (2 of 3 done)');

    // Non-vacuous: a newer snapshot still lands.
    progress(tp(6, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');
  });

  it('ignores a malformed turn_progress event', async () => {
    await mount();
    send();
    emit({ type: 'turn_progress' });
    emit({ type: 'turn_progress', turn_progress: stringSeq(7, 'reviewing_deck') });
    expectLabel('Generating slides...');

    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');

    // Neither kind of malformed event moves a held stage (backwards or forwards).
    emit({ type: 'turn_progress' });
    emit({ type: 'turn_progress', turn_progress: stringSeq(8, 'reviewing_deck') });
    expectLabel('Planning the deck…');
  });

  it('the label is not timer-driven', async () => {
    await mount();
    vi.useFakeTimers();
    send();
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');

    act(() => { vi.advanceTimersByTime(3_000); });
    expectLabel('Planning the deck…');
    act(() => { vi.advanceTimersByTime(57_000); });
    expectLabel('Planning the deck…');
  });

  it('a stage never becomes a chat message', async () => {
    await mount();
    send();
    progress(tp(1, 'planning'));
    progress(tp(2, 'gathering_data'));
    progress(tp(3, 'planning'));

    const matches = screen.getAllByText(/Planning the deck/);
    expect(matches).toHaveLength(1);
    expect(placeholder()).toContainElement(matches[0]);
    expect(screen.queryByText(/Gathering the data/)).toBeNull();

    // Once the turn ends the placeholder goes, and no stage is left in the transcript.
    emit({ type: 'complete' });
    expect(screen.queryByText(/Planning the deck/)).toBeNull();
    expect(screen.queryByText(/Gathering the data/)).toBeNull();
    expect(screen.getByText('build me a deck')).toBeInTheDocument();
  });

  it('hides on complete and on error', async () => {
    await mount();

    send();
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');
    emit({ type: 'complete' });
    expect(screen.queryByTestId('chat-turn-progress')).toBeNull();
    expect(screen.queryByText('Planning the deck…')).toBeNull();

    // SSE: an `error` event ends the turn.
    send();
    progress(tp(2, 'gathering_data'));
    expectLabel('Gathering the data…');
    emit({ type: 'error', error: 'The turn failed' });
    expect(screen.queryByTestId('chat-turn-progress')).toBeNull();
    expect(screen.queryByText('Gathering the data…')).toBeNull();

    // Polling: `status=error` reaches ChatPanel through onError.
    send();
    progress(tp(3, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');
    act(() => { onError(new Error('poll failed')); });
    expect(screen.queryByTestId('chat-turn-progress')).toBeNull();
    expect(screen.queryByText('Reviewing the narrative…')).toBeNull();
  });

  it('the next turn starts fresh even though its seq restarts at 1', async () => {
    await mount();
    send();
    progress(tp(9, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');
    emit({ type: 'complete' });

    send();
    expect(h.sendChatMessage).toHaveBeenCalledTimes(2);
    expectLabel('Generating slides...');
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');
  });

  // The reset sits at send, not at `complete` (D14), so a turn that ends any other way
  // leaves nothing behind either.  Sabotage: reset on `complete` instead of at send -> red.
  it('the next turn starts fresh after a turn that failed', async () => {
    await mount();

    // SSE: the turn ends with an `error` event.
    send();
    progress(tp(9, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');
    emit({ type: 'error', error: 'The turn failed' });
    send();
    expect(h.sendChatMessage).toHaveBeenCalledTimes(2);
    expectLabel('Generating slides...');
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');

    // Polling: `status=error` ends the turn through onError.
    progress(tp(9, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');
    act(() => { onError(new Error('poll failed')); });
    send();
    expect(h.sendChatMessage).toHaveBeenCalledTimes(3);
    expectLabel('Generating slides...');
    progress(tp(1, 'planning'));
    expectLabel('Planning the deck…');
  });

  // Sabotage: reset in every terminal handler (complete, error, onError) instead of at
  // send -> red, because a session switch ends the turn without any of them.
  it('the next turn starts fresh after a session switch cut the last one short', async () => {
    const view = await mount();
    send();
    progress(tp(9, 'reviewing_deck'));
    expectLabel('Reviewing the narrative…');

    const original = h.session;
    h.session = { ...original, sessionId: 'session-319-b' };
    try {
      view.rerender(panel());
      await act(async () => {});
      // The switch cancelled the turn and ended loading.
      expect(h.getSession).toHaveBeenCalledWith('session-319-b');
      expect(screen.queryByTestId('chat-turn-progress')).toBeNull();

      send();
      expect(h.sendChatMessage).toHaveBeenCalledTimes(2);
      expect(h.sendChatMessage.mock.calls[1][0]).toBe('session-319-b');
      expectLabel('Generating slides...');
      progress(tp(1, 'planning'));
      expectLabel('Planning the deck…');
    } finally {
      h.session = original;
    }
  });
});
