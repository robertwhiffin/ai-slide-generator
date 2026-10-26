/**
 * Deck Mode toggle, Task 7: ChatPanel sends the deck's mode, locks it optimistically, and reconciles
 * with the server after a failed send.
 *
 * Rules (task brief + PLAN-CORRECTIONS Task 7), each a test below:
 *   - The mode sent is `storedDeckMode ?? selectedDeckMode`, as the 8th argument of api.sendChatMessage.
 *   - On an unlocked deck the send locks optimistically: storedDeckMode becomes the sent mode while the
 *     request is still in flight, so the next send carries it whatever the selection says. A send that
 *     never goes out (persistence failed) locks nothing.
 *   - After a failed send, on BOTH failure paths (the transport's onError, the production polling path;
 *     and an SSE `error` event that ends the turn), the panel re-reads the session it sent to and sets
 *     storedDeckMode to the server's `deck_mode ?? null`. A per-slide error notice (metadata.position)
 *     is mid-turn and re-reads nothing. A failed re-read changes nothing (the optimistic lock stays).
 *   - The re-read is dropped after a newer send or a session switch (the refreshMessageIds guard).
 *   - The landing deck's first send survives the same-id re-restore that ensureGraphCapableRoot's
 *     navigate triggers (C2).
 *
 * Harness: the REAL SessionProvider with a probe beside the panel (a static useSession mock cannot hold
 * state), so "storedDeckMode becomes X" is read from the provider, not inferred from a spy. The api is
 * mocked; sendChatMessage hands each turn's onEvent/onError to the test. No `onDeckRefetched` prop is
 * passed: the reconcile must not share refetchDeckAfterError's `if (!onDeckRefetched) return` guard.
 * ChatPanel calls getSession on mount and on every session change, so the re-read is pinned as the call
 * COUNT rising by one after the failure, plus the server's value reaching storedDeckMode.
 *
 * SABOTAGE (measured against a throwaway implementation outside the worktree; each turned at least one
 * test red):
 *   - deckMode not passed to sendChatMessage (or always the selection / always `stored ?? 'agent'`)
 *                                                                   -> the "sends" tests.
 *   - no optimistic lock                                            -> "locks optimistically" and the re-read tests.
 *   - the lock set before ensureGraphCapableRoot                    -> "a send that never goes out".
 *   - the reconcile only in the onError callback (or only in the SSE `error` case) -> the other path.
 *   - the reconcile outside the `metadata.position == null` guard  -> "a per-slide error notice".
 *   - the reconcile copies `if (!onDeckRefetched) return`          -> every re-read test.
 *   - a setStoredDeckMode that refuses null                        -> "unlocked again".
 *   - a failed re-read resets the lock, or has no `.catch`         -> "keeps the optimistic lock".
 *   - no sendSeq guard / no session guard on the re-read           -> the matching guard test.
 *   - switchSession resets the stored mode or the selection on a same-id re-restore
 *                                                                   -> "the landing deck's first send".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DeckMode, StreamEvent } from '../../services/api';
import { SessionProvider, useSession, type OptionalSessionInfo } from '../../contexts/SessionContext';

type OnEvent = (event: StreamEvent) => void;
type OnError = (error: Error) => void;
interface Turn { sentTo: string; mode: unknown; onEvent: OnEvent; onError: OnError }

const h = vi.hoisted(() => {
  const setIsGenerating = vi.fn();
  const refreshConfig = vi.fn();
  return {
    setIsGenerating,
    refreshConfig,
    agentConfig: { agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false },
    generation: { setIsGenerating },
    /** api.getCurrentSessionId / setCurrentSessionId, a plain variable as in the real module. */
    apiSessionId: null as string | null,
    /** What GET /api/sessions/{id} answers for deck_mode. */
    serverDeckMode: null as 'agent' | 'legacy' | null,
    /** When true, getSession rejects (the re-read fails). */
    getSessionFails: false,
    getSession: vi.fn(),
    getSlides: vi.fn(),
    sendChatMessage: vi.fn(),
    getCollaborationHistory: vi.fn(),
    listMessages: vi.fn(),
  };
});

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getSession: (...a: unknown[]) => h.getSession(...a),
      getSlides: (...a: unknown[]) => h.getSlides(...a),
      sendChatMessage: (...a: unknown[]) => h.sendChatMessage(...a),
      getCollaborationHistory: (...a: unknown[]) => h.getCollaborationHistory(...a),
      getCurrentSessionId: () => h.apiSessionId,
      setCurrentSessionId: (id: string | null) => { h.apiSessionId = id; },
    },
  };
});
vi.mock('../../api/conversation', () => ({
  conversationApi: { listMessages: (...a: unknown[]) => h.listMessages(...a) },
}));
vi.mock('../../contexts/AgentConfigContext', () => ({ useAgentConfig: () => h.agentConfig }));
vi.mock('../../contexts/GenerationContext', () => ({ useGeneration: () => h.generation }));
vi.mock('./ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (message: string) => void; disabled: boolean }) => (
    <button type="button" data-testid="mock-send" disabled={disabled} onClick={() => onSend('Build me a deck')}>
      send
    </button>
  ),
}));

import { ChatPanel } from './ChatPanel';

// ── harness ───────────────────────────────────────────────────────────────────

type Ctx = ReturnType<typeof useSession>;
let ctx: Ctx;

function Probe() {
  ctx = useSession();
  return (
    <>
      <output data-testid="stored-mode">{String(ctx.storedDeckMode)}</output>
      <output data-testid="selected-mode">{String(ctx.selectedDeckMode)}</output>
    </>
  );
}

const stored = () => screen.getByTestId('stored-mode').textContent;
const selected = () => screen.getByTestId('selected-mode').textContent;

interface Deferred<T> { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void }
function deferred<T>(): Deferred<T> {
  let resolve: (v: T) => void = () => {};
  let reject: (e: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const onSlidesGenerated = vi.fn();
/** Production: persists the browser-local id (markSessionPersisted), then navigates to the same id. */
let persistOk = true;
const ensureGraphCapableRoot = vi.fn(async () => {
  if (!persistOk) return false;
  ctx.markSessionPersisted();
  return true;
});
let turns: Turn[] = [];

/** Let promise callbacks and effects run, so a "nothing happened" check is meaningful. */
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });

async function mount() {
  const view = render(
    <MemoryRouter>
      <SessionProvider>
        <Probe />
        <ChatPanel rawHtml={null} onSlidesGenerated={onSlidesGenerated} ensureGraphCapableRoot={ensureGraphCapableRoot} />
      </SessionProvider>
    </MemoryRouter>,
  );
  await settle(); // the mount-time history load
  return view;
}

/** Open a saved deck, as AppLayout's URL restore does (existingSessionInfo). */
async function restore(id: string, deck_mode: DeckMode | null) {
  const sessionInfo: OptionalSessionInfo = { title: 'Deck', has_slide_deck: false, deck_mode };
  await act(async () => { await ctx.switchSession(id, sessionInfo); });
  await settle();
}

async function select(mode: DeckMode) {
  expect(typeof ctx.setSelectedDeckMode, 'SessionContext has no setSelectedDeckMode').toBe('function');
  await act(async () => { ctx.setSelectedDeckMode(mode); });
  expect(selected()).toBe(mode);
}

async function send() {
  const before = turns.length;
  await act(async () => { fireEvent.click(screen.getByTestId('mock-send')); });
  expect(turns.length).toBe(before + 1);
}

const lastTurn = () => turns[turns.length - 1];
/** An SSE `error` event that ends the turn sent last. */
const emitError = (message = 'The turn failed') =>
  act(async () => { lastTurn().onEvent({ type: 'error', error: message }); });
/** The transport's failure callback (polling's status=error, a 409, an SSE network failure). */
const failTransport = (message = 'Request failed') =>
  act(async () => { lastTurn().onError(new Error(message)); });

const getSessionCalls = () => h.getSession.mock.calls.length;

const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => { unhandled.push(reason); };

beforeEach(() => {
  vi.clearAllMocks();
  h.apiSessionId = null;
  h.serverDeckMode = null;
  h.getSessionFails = false;
  persistOk = true;
  turns = [];
  unhandled.length = 0;
  h.getSession.mockImplementation(async (id: string) => {
    if (h.getSessionFails) throw new Error('network down');
    return {
      session_id: id,
      title: 'Deck',
      messages: [],
      my_permission: 'CAN_EDIT',
      has_slide_deck: false,
      graph_version: 1,
      active_graph_version: 1,
      is_older_than_active: false,
      deck_mode: h.serverDeckMode,
    };
  });
  h.getSlides.mockImplementation(async (id: string) => ({ session_id: id, slide_deck: null }));
  h.getCollaborationHistory.mockResolvedValue({ mixed_release_warning: false, has_legacy_evidence: false, groups: [] });
  h.listMessages.mockResolvedValue({ messages: [], count: 0 });
  h.sendChatMessage.mockImplementation((sentTo: string, ...rest: unknown[]) => {
    turns.push({ sentTo, mode: rest[6], onEvent: rest[2] as OnEvent, onError: rest[3] as OnError });
    return () => {};
  });
  process.on('unhandledRejection', onUnhandled);
});

afterEach(() => {
  process.off('unhandledRejection', onUnhandled);
});

// ── what is sent ──────────────────────────────────────────────────────────────

describe('the mode a send carries', () => {
  it('sends deck_mode "legacy" when Legacy mode is selected on an unlocked deck', async () => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');

    await send();

    expect(h.sendChatMessage).toHaveBeenCalledTimes(1);
    expect(h.sendChatMessage.mock.calls[0][0]).toBe('sess-1');
    expect(h.sendChatMessage.mock.calls[0][7]).toBe('legacy');
  });

  it('sends deck_mode "agent" on an unlocked deck left on the default selection', async () => {
    await mount();
    await restore('sess-1', null);
    expect(selected()).toBe('agent');

    await send();

    expect(h.sendChatMessage.mock.calls[0][7]).toBe('agent');
  });

  it.each<{ storedMode: DeckMode; selection: DeckMode }>([
    { storedMode: 'legacy', selection: 'agent' },
    { storedMode: 'agent', selection: 'legacy' },
  ])('sends the stored mode, not the selection, on a locked deck (stored $storedMode, selected $selection)', async ({ storedMode, selection }) => {
    await mount();
    await restore('sess-1', storedMode);
    expect(stored()).toBe(storedMode);
    await select(selection);

    await send();

    expect(h.sendChatMessage.mock.calls[0][7]).toBe(storedMode);
    expect(stored()).toBe(storedMode); // a locked deck is not re-locked to the selection
  });
});

// ── the optimistic lock ───────────────────────────────────────────────────────

describe('locking on send', () => {
  it('locks optimistically on send: storedDeckMode is the sent mode while the request is in flight', async () => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    expect(stored()).toBe('null');

    await send();
    await settle(); // no event has arrived: the turn is still in flight

    expect(stored()).toBe('legacy');

    // The lock is real state: the next send carries it even if the selection moves.
    await act(async () => { lastTurn().onEvent({ type: 'complete' } as StreamEvent); });
    await settle();
    await select('agent');
    await send();
    expect(h.sendChatMessage.mock.calls[1][7]).toBe('legacy');
    expect(stored()).toBe('legacy');
  });

  it("the landing deck's first send locks, and the same-id re-restore its navigate triggers keeps the lock (C2)", async () => {
    await mount();
    const landingId = ctx.sessionId!;
    expect(ctx.isSessionPersisted).toBe(false);
    await select('legacy');

    await send();
    expect(ensureGraphCapableRoot).toHaveBeenCalledTimes(1);
    expect(lastTurn().sentTo).toBe(landingId);
    expect(h.sendChatMessage.mock.calls[0][7]).toBe('legacy');
    expect(stored()).toBe('legacy');

    // loadSessionFromServer re-restores the same id mid-turn; the server has not committed the lock.
    await act(async () => {
      await ctx.switchSession(landingId, { title: null, has_slide_deck: false, deck_mode: null });
    });
    await settle();

    expect(ctx.sessionId).toBe(landingId);
    expect(stored()).toBe('legacy');
    expect(selected()).toBe('legacy');
  });

  it('a send that never goes out (persistence failed) locks nothing; once persistence works it does', async () => {
    persistOk = false;
    await mount();
    await select('legacy');

    await act(async () => { fireEvent.click(screen.getByTestId('mock-send')); });
    await settle();
    expect(ensureGraphCapableRoot).toHaveBeenCalledTimes(1);
    expect(h.sendChatMessage).not.toHaveBeenCalled();
    expect(stored()).toBe('null');
    expect(selected()).toBe('legacy');

    // Positive half: persistence succeeds, the send goes out and locks.
    persistOk = true;
    await send();
    expect(h.sendChatMessage.mock.calls[0][7]).toBe('legacy');
    expect(stored()).toBe('legacy');
  });
});

// ── reconcile after a failed send ─────────────────────────────────────────────

const FAILURE_PATHS = [
  { label: 'the transport fails (onError: polling status=error, a 409)', fail: () => failTransport('Request failed'), shown: 'Request failed' },
  { label: 'an SSE error event ends the turn', fail: () => emitError('The turn failed'), shown: 'The turn failed' },
];

describe('re-reading the session after a failed send', () => {
  it.each(FAILURE_PATHS)("re-reads the session and shows the server's mode when $label", async ({ fail, shown }) => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();
    expect(stored()).toBe('legacy'); // optimistic

    h.serverDeckMode = 'agent'; // e.g. another tab locked the deck first: the server says Agent mode
    const before = getSessionCalls();
    await fail();
    await settle();

    expect(getSessionCalls()).toBe(before + 1);
    expect(h.getSession).toHaveBeenLastCalledWith('sess-1');
    expect(stored()).toBe('agent');
    expect(screen.getByText(shown)).toBeInTheDocument(); // the turn's error still shows
  });

  it.each(FAILURE_PATHS)('a server null after the failure unlocks the deck again when $label', async ({ fail }) => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();
    expect(stored()).toBe('legacy');

    h.serverDeckMode = null; // the failed first message never committed the lock
    const before = getSessionCalls();
    await fail();
    await settle();

    expect(getSessionCalls()).toBe(before + 1);
    expect(stored()).toBe('null');
    expect(selected()).toBe('legacy'); // the user's pick is still there for the retry
  });

  it.each(FAILURE_PATHS)('keeps the optimistic lock when the re-read fails ($label)', async ({ fail, shown }) => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();

    h.getSessionFails = true;
    const before = getSessionCalls();
    await fail();
    await settle();

    expect(getSessionCalls()).toBe(before + 1); // it was asked for
    expect(stored()).toBe('legacy');
    expect(unhandled).toEqual([]);
    expect(screen.getByText(shown)).toBeInTheDocument();
  });

  it('a per-slide error notice (metadata.position, mid-turn) re-reads nothing; the turn-ending error does', async () => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();
    h.serverDeckMode = 'agent';
    const before = getSessionCalls();

    await act(async () => {
      lastTurn().onEvent({ type: 'error', error: 'Slide 2 could not be built', metadata: { node: 'builder', position: 1 } });
    });
    await settle();
    expect(getSessionCalls()).toBe(before);
    expect(stored()).toBe('legacy');

    // Positive half, same turn.
    await emitError('The turn failed');
    await settle();
    expect(getSessionCalls()).toBe(before + 1);
    expect(stored()).toBe('agent');
  });
});

describe('the re-read is dropped when it no longer belongs to the panel', () => {
  it("a newer send before the re-read lands drops it; the newer turn's own re-read lands", async () => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();

    const first = deferred<unknown>();
    const second = deferred<unknown>();
    h.getSession.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    await failTransport('first failed');
    await settle();
    await send(); // the user retries while the first re-read is in flight
    await act(async () => { first.resolve({ session_id: 'sess-1', messages: [], deck_mode: null }); });
    await settle();
    expect(stored()).toBe('legacy'); // the stale null did not unlock the deck under the running turn

    // Positive half: the second turn fails too, and ITS re-read lands.
    await failTransport('second failed');
    await act(async () => { second.resolve({ session_id: 'sess-1', messages: [], deck_mode: 'agent' }); });
    await settle();
    expect(stored()).toBe('agent');
  });

  it("a session switch before the re-read lands drops it; a failure in the new session reconciles that session", async () => {
    await mount();
    await restore('sess-1', null);
    await select('legacy');
    await send();
    await settle();

    const first = deferred<unknown>();
    h.getSession.mockReturnValueOnce(first.promise);
    await failTransport();
    await settle();

    // The user opens another deck, locked as Agent mode, before the re-read answers.
    await restore('sess-2', 'agent');
    expect(stored()).toBe('agent');
    await act(async () => { first.resolve({ session_id: 'sess-1', messages: [], deck_mode: null }); });
    await settle();
    expect(stored()).toBe('agent'); // sess-1's answer did not land on sess-2

    // Positive half: a failure on sess-2 re-reads sess-2 and lands.
    h.serverDeckMode = 'legacy';
    await send();
    expect(lastTurn().sentTo).toBe('sess-2');
    const before = getSessionCalls();
    await emitError();
    await settle();
    expect(getSessionCalls()).toBe(before + 1);
    expect(h.getSession).toHaveBeenLastCalledWith('sess-2');
    expect(stored()).toBe('legacy');
  });
});
