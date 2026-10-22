/**
 * #314 Task 8: after an ERRORED turn the chat panel refetches the deck, so the viewer does not keep a
 * stale mid-turn view (synthetic `build-N` slides) and the next diff is against the server deck (plan
 * D10, AC10; review m6; correction C17).
 *
 * C17's rules, each a test below:
 *   - The refetched deck goes to a NEW optional prop, `onDeckRefetched(deck)`, never to
 *     `onSlidesGenerated`: that is the success path (AppLayout runs the survey trigger, "Saved just now",
 *     a sessions-list refresh and a versions reload from it). AppLayout wires the new prop to
 *     `setSlideDeckGated(deck, deck.version)` and nothing else (the source pin at the bottom).
 *   - BOTH failure paths refetch: an SSE `error` event, and the `onError` callback handed to
 *     `api.sendChatMessage`. Polling (production) never emits an `error` event: a failed job calls
 *     `onError(new Error(response.error))` (api.ts startPolling), and SSE transport failures do too.
 *   - Target: `api.getCurrentSessionId() ?? <the session the turn was sent to>`.
 *   - Dropped when a newer send started or the session switched before the refetch landed; nothing on
 *     `slide_deck: null`; a rejected refetch is swallowed (no unhandled rejection) and changes nothing.
 * Each absence is paired with a positive in the same test (the refetch WAS asked for, or a later one
 * is handed up), so no "not called" passes for a harness reason.
 *
 * Harness: as ChatPanel.deleteMessage.test.tsx / ChatPanel.turnProgress.test.tsx. The real ChatPanel;
 * `api.sendChatMessage` is mocked and hands each turn's onEvent/onError to the test; `setIsGenerating`
 * and `refreshConfig` are stable identities (a new identity per render re-runs ChatPanel's session-change
 * cleanup and ends every turn).
 *
 * SABOTAGE (run against a throwaway implementation in /tmp/issue314-ui-t8, then reverted):
 *   - the refetch routed through onSlidesGenerated            -> the SSE and polling tests RED.
 *   - the refetch only in `case 'error':`                      -> the polling (onError) test RED.
 *   - the refetch only in the onError callback                 -> the SSE test RED.
 *   - no `.catch` on the refetch                               -> "rejected" RED (unhandled rejection).
 *   - no sendSeq guard                                         -> "newer send" RED.
 *   - no session-switch guard                                  -> "session switch" RED.
 *   - a null slide_deck handed up                              -> "slide_deck null" RED.
 *   - target always the sent-to session                        -> "targets api.getCurrentSessionId()" RED.
 *   - target always api.getCurrentSessionId() (no fallback)    -> "falls back" RED.
 *   - the switch guard compares the TARGET, not the sent-to
 *     session (the refreshMessageIds guard compares sent-to)   -> "targets api.getCurrentSessionId()" RED.
 *   - (reviewer, on the real implementation) the target computed synchronously, outside the promise
 *     chain                                                    -> "inside the promise chain" RED.
 *
 * HARNESS NOTE for the implementer: ChatPanel.deleteMessage.test.tsx's api mock has no
 * getCurrentSessionId. Calling it synchronously in the error handler throws there and reddens three of
 * its tests; compute the target inside the promise chain (as refreshMessageIds does with
 * `Promise.resolve().then(…)`) so the `.catch` covers it. Measured: that keeps all 38 green.
 *   - AppLayout's onDeckRefetched also calls onGenerationComplete / setLastSavedTime / loadVersions, or
 *     passes `force`                                           -> the AppLayout pin RED.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ts from 'typescript';
import appLayoutSource from '../Layout/AppLayout.tsx?raw';
import type { StreamEvent } from '../../services/api';
import type { SlideDeck } from '../../types/slide';

type OnEvent = (event: StreamEvent) => void;
type OnError = (error: Error) => void;
interface Turn { sentTo: string; onEvent: OnEvent; onError: OnError }

const h = vi.hoisted(() => {
  const setIsGenerating = vi.fn();
  const refreshConfig = vi.fn();
  return {
    setIsGenerating,
    refreshConfig,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
    agentConfig: { agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false },
    generation: { setIsGenerating },
    /** The session the panel is on (useSession().sessionId). */
    sessionId: 'sess-1',
    /** What api.getCurrentSessionId() answers. */
    apiSessionId: 'sess-1' as string | null,
    /** When true, api.getCurrentSessionId() throws (a harness or api without it, e.g. a partial mock). */
    currentSessionIdThrows: false,
    getSession: vi.fn(),
    getSlides: vi.fn(),
    sendChatMessage: vi.fn(),
    listMessages: vi.fn(),
  };
});

vi.mock('../../services/api', () => ({
  api: {
    getSession: (...a: unknown[]) => h.getSession(...a),
    getSlides: (...a: unknown[]) => h.getSlides(...a),
    sendChatMessage: (...a: unknown[]) => h.sendChatMessage(...a),
    getCurrentSessionId: () => {
      if (h.currentSessionIdThrows) throw new Error('getCurrentSessionId unavailable');
      return h.apiSessionId;
    },
    setCurrentSessionId: vi.fn(),
  },
}));
vi.mock('../../api/conversation', () => ({
  conversationApi: { listMessages: (...a: unknown[]) => h.listMessages(...a) },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: h.sessionId,
    isSessionPersisted: true,
    isInitializing: false,
    error: null,
    setExperimentUrl: h.setExperimentUrl,
    setSessionTitle: h.setSessionTitle,
  }),
}));
vi.mock('../../contexts/AgentConfigContext', () => ({ useAgentConfig: () => h.agentConfig }));
vi.mock('../../contexts/GenerationContext', () => ({ useGeneration: () => h.generation }));
vi.mock('./ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (message: string) => void; disabled: boolean }) => (
    <button type="button" data-testid="mock-send" disabled={disabled} onClick={() => onSend('Add a slide after 2')}>
      send
    </button>
  ),
}));

import { ChatPanel } from './ChatPanel';

// ── fixtures ──────────────────────────────────────────────────────────────────

function deckOf(ids: string[], version: number): SlideDeck {
  return {
    title: 'Deck',
    slide_count: ids.length,
    css: '',
    external_scripts: [],
    scripts: '',
    version,
    slides: ids.map((id, index) => ({ index, slide_id: id, html: `<div class="slide">${id}</div>`, scripts: '' })),
  };
}

const SERVER_DECK = deckOf(['A', 'B', 'C'], 7);
const LATER_DECK = deckOf(['A', 'B', 'C', 'D'], 8);

interface Deferred<T> { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void }
function deferred<T>(): Deferred<T> {
  let resolve: (v: T) => void = () => {};
  let reject: (e: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

// ── harness ───────────────────────────────────────────────────────────────────

const onSlidesGenerated = vi.fn();
const onDeckRefetched = vi.fn();
const ensureGraphCapableRoot = async () => true;
let turns: Turn[] = [];

function panel() {
  return (
    <MemoryRouter>
      <ChatPanel
        rawHtml={null}
        onSlidesGenerated={onSlidesGenerated}
        onDeckRefetched={onDeckRefetched}
        ensureGraphCapableRoot={ensureGraphCapableRoot}
      />
    </MemoryRouter>
  );
}

async function mount() {
  const view = render(panel());
  await settle(); // the mount-time history load
  return view;
}

/** Let promise callbacks and effects run, so a "nothing happened" check is meaningful. */
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });

async function send() {
  await act(async () => { fireEvent.click(screen.getByTestId('mock-send')); });
  expect(turns.length).toBeGreaterThan(0);
}

const lastTurn = () => turns[turns.length - 1];
/** An SSE `error` event on the turn sent last. */
const emitError = (message = 'The turn failed') =>
  act(async () => { lastTurn().onEvent({ type: 'error', error: message }); });
/** The transport's failure callback on the turn sent last (polling's status=error, an SSE network failure). */
const failTransport = (message = 'Request failed') =>
  act(async () => { lastTurn().onError(new Error(message)); });

const errorShown = () => screen.queryByRole('button', { name: 'Dismiss error' }) !== null;

const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => { unhandled.push(reason); };

beforeEach(() => {
  vi.clearAllMocks();
  h.sessionId = 'sess-1';
  h.apiSessionId = 'sess-1';
  h.currentSessionIdThrows = false;
  turns = [];
  unhandled.length = 0;
  h.getSession.mockResolvedValue({ messages: [], my_permission: 'CAN_EDIT' });
  h.listMessages.mockResolvedValue({ session_id: 'sess-1', messages: [], count: 0 });
  h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: SERVER_DECK });
  h.sendChatMessage.mockImplementation((sentTo: string, _m: string, _c: unknown, onEvent: OnEvent, onError: OnError) => {
    turns.push({ sentTo, onEvent, onError });
    return () => {};
  });
  process.on('unhandledRejection', onUnhandled);
});

afterEach(() => {
  process.off('unhandledRejection', onUnhandled);
});

// ── both failure paths refetch, and only onDeckRefetched hears about it ──────

describe('an errored turn refetches the deck (C17)', () => {
  it('an SSE error event: getSlides(session) -> onDeckRefetched(deck); onSlidesGenerated is not called', async () => {
    await mount();
    await send();
    expect(h.getSlides).not.toHaveBeenCalled();

    await emitError('The turn failed');
    await settle();

    expect(h.getSlides).toHaveBeenCalledTimes(1);
    expect(h.getSlides).toHaveBeenCalledWith('sess-1');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(SERVER_DECK);
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    // The failure is still reported as before.
    expect(screen.getByText('The turn failed')).toBeInTheDocument();
  });

  it('a per-slide error notice (metadata.position, emitted mid-turn) does not refetch; a turn-ending error does', async () => {
    await mount();
    await send();

    // _placehold_failed_position's notice: one slide failed, the turn carries on.
    await act(async () => {
      lastTurn().onEvent({ type: 'error', error: 'Slide 2 could not be built', metadata: { node: 'builder', position: 1 } });
    });
    await settle();
    expect(h.getSlides).not.toHaveBeenCalled();
    expect(onDeckRefetched).not.toHaveBeenCalled();

    // Positive half, same turn: an error with no position ends the turn and refetches.
    await emitError('The turn failed');
    await settle();
    expect(h.getSlides).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onSlidesGenerated).not.toHaveBeenCalled();
  });

  it("polling's failure (onError, no error event): getSlides -> onDeckRefetched(deck); onSlidesGenerated is not called", async () => {
    await mount();
    await send();

    await failTransport('Request failed');
    await settle();

    expect(h.getSlides).toHaveBeenCalledTimes(1);
    expect(h.getSlides).toHaveBeenCalledWith('sess-1');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(SERVER_DECK);
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    expect(screen.getByText('Request failed')).toBeInTheDocument();
  });

  it('control: a completed turn still hands its refetch to onSlidesGenerated (the harness can see it)', async () => {
    await mount();
    await send();

    await act(async () => {
      lastTurn().onEvent({ type: 'complete', slides: SERVER_DECK } as StreamEvent);
    });
    await settle();

    expect(onSlidesGenerated).toHaveBeenCalledTimes(1);
    expect(onSlidesGenerated.mock.calls[0][0]).toBe(SERVER_DECK);
  });

  it("targets api.getCurrentSessionId() when it is set (it follows session_created), as `complete` does", async () => {
    // session_created moved the api's current session before the panel's own sessionId caught up. The
    // panel has not switched sessions (it is still on the one the turn was sent to), so this is no switch.
    await mount();
    await send();
    expect(lastTurn().sentTo).toBe('sess-1');
    h.apiSessionId = 'sess-created';
    h.getSlides.mockResolvedValue({ session_id: 'sess-created', slide_deck: LATER_DECK });

    await emitError();
    await settle();

    expect(h.getSlides).toHaveBeenCalledTimes(1);
    expect(h.getSlides).toHaveBeenCalledWith('sess-created');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(LATER_DECK);
  });

  it('falls back to the session the turn was sent to when api.getCurrentSessionId() is null', async () => {
    h.apiSessionId = null;
    await mount();
    await send();
    expect(lastTurn().sentTo).toBe('sess-1');

    await failTransport();
    await settle();

    expect(h.getSlides).toHaveBeenCalledWith('sess-1');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(SERVER_DECK);
  });
});

// ── guards ─────────────────────────────────────────────────────────────────────

describe('the error refetch hands nothing up when it should not', () => {
  it('a rejected getSlides: no onDeckRefetched, no unhandled rejection, the error still shows', async () => {
    h.getSlides.mockRejectedValue(new Error('network down'));
    await mount();
    await send();

    await emitError('The turn failed');
    await settle();

    expect(h.getSlides).toHaveBeenCalledWith('sess-1'); // it was asked for
    expect(onDeckRefetched).not.toHaveBeenCalled();
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
    expect(errorShown()).toBe(true);
    expect(screen.getByText('The turn failed')).toBeInTheDocument();
  });

  it('the target is computed inside the promise chain: a throwing getCurrentSessionId is swallowed on both paths', async () => {
    // Reviewer addition (supervisor ruling). Computed synchronously, the throw would escape the SSE event
    // handler (the turn's own state updates after it would never run) and the transport's onError callback.
    h.currentSessionIdThrows = true;
    await mount();

    await send();
    await emitError('The turn failed');
    await settle();
    expect(screen.getByText('The turn failed')).toBeInTheDocument();
    expect(screen.getByTestId('mock-send')).not.toBeDisabled(); // the turn ended: isLoading is false

    await send();
    await failTransport('Request failed');
    await settle();
    expect(screen.getByText('Request failed')).toBeInTheDocument();
    expect(screen.getByTestId('mock-send')).not.toBeDisabled();

    expect(h.getSlides).not.toHaveBeenCalled();
    expect(onDeckRefetched).not.toHaveBeenCalled();
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);

    // Positive in the same test: once the target can be computed, the next failure is refetched.
    h.currentSessionIdThrows = false;
    await send();
    await failTransport();
    await settle();
    expect(h.getSlides).toHaveBeenCalledWith('sess-1');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(SERVER_DECK);
  });

  it('slide_deck: null: no onDeckRefetched (and nothing else stands in for it)', async () => {
    h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: null });
    await mount();
    await send();

    await failTransport();
    await settle();

    expect(h.getSlides).toHaveBeenCalledWith('sess-1'); // it was asked for
    expect(onDeckRefetched).not.toHaveBeenCalled();
    expect(onSlidesGenerated).not.toHaveBeenCalled();
  });

  it("a newer send before the refetch lands drops it; the newer turn's own refetch is handed up", async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    h.getSlides.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await mount();

    await send();
    await emitError('first failed');
    expect(h.getSlides).toHaveBeenCalledTimes(1);

    // The user sends again while the first refetch is still in flight: that turn is now running, and an
    // old deck landing on it would overwrite its mid-turn view.
    await send();
    expect(turns).toHaveLength(2);
    await act(async () => { first.resolve({ session_id: 'sess-1', slide_deck: SERVER_DECK }); });
    await settle();
    expect(onDeckRefetched).not.toHaveBeenCalled();

    // Positive in the same test: the second turn fails too, and ITS refetch is handed up.
    await failTransport('second failed');
    await act(async () => { second.resolve({ session_id: 'sess-1', slide_deck: LATER_DECK }); });
    await settle();
    expect(h.getSlides).toHaveBeenCalledTimes(2);
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(LATER_DECK);
    expect(onSlidesGenerated).not.toHaveBeenCalled();
  });

  it('a session switch before the refetch lands drops it; a failure in the new session is handed up', async () => {
    const first = deferred<unknown>();
    h.getSlides.mockReturnValueOnce(first.promise);
    const view = await mount();

    await send();
    await failTransport();
    expect(h.getSlides).toHaveBeenCalledWith('sess-1'); // it was asked for

    // The user opens another deck before the refetch answers.
    h.sessionId = 'sess-2';
    h.apiSessionId = 'sess-2';
    view.rerender(panel());
    await settle();
    await act(async () => { first.resolve({ session_id: 'sess-1', slide_deck: SERVER_DECK }); });
    await settle();
    expect(onDeckRefetched).not.toHaveBeenCalled();

    // Positive in the same test: in the new session an errored turn refetches THAT session's deck.
    h.getSlides.mockResolvedValue({ session_id: 'sess-2', slide_deck: LATER_DECK });
    await send();
    expect(lastTurn().sentTo).toBe('sess-2');
    await emitError();
    await settle();
    expect(h.getSlides).toHaveBeenLastCalledWith('sess-2');
    expect(onDeckRefetched).toHaveBeenCalledTimes(1);
    expect(onDeckRefetched.mock.calls[0][0]).toBe(LATER_DECK);
  });
});

// ── AppLayout wires the prop to setSlideDeckGated only (source pin) ─────────
//
// Rendering AppLayout needs the whole app shell (see AppLayoutSpecToggle.test.ts); the wiring is read
// through the TypeScript parser, so a comment cannot satisfy it.

const appLayout = ts.createSourceFile('AppLayout.tsx', appLayoutSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function findAll<T extends ts.Node>(root: ts.Node, test: (n: ts.Node) => n is T): T[] {
  const out: T[] = [];
  const visit = (n: ts.Node) => {
    if (test(n)) out.push(n);
    ts.forEachChild(n, visit);
  };
  visit(root);
  return out;
}

/** The function an attribute expression names: inline, a const, or a const = useCallback(fn, deps). */
function resolveFunction(expr: ts.Expression): ts.ArrowFunction | ts.FunctionExpression | null {
  if (ts.isArrowFunction(expr) || ts.isFunctionExpression(expr)) return expr;
  if (ts.isCallExpression(expr) && expr.expression.getText(appLayout) === 'useCallback' && expr.arguments[0]) {
    return resolveFunction(expr.arguments[0]);
  }
  if (ts.isIdentifier(expr)) {
    const decl = findAll(appLayout, ts.isVariableDeclaration).find(
      (d) => ts.isIdentifier(d.name) && d.name.text === expr.text,
    );
    return decl?.initializer ? resolveFunction(decl.initializer) : null;
  }
  return null;
}

/** Every call in a function body, as `callee(args)` text. */
function callsIn(fn: ts.ArrowFunction | ts.FunctionExpression): string[] {
  return findAll(fn.body, ts.isCallExpression).map((c) => c.getText(appLayout).replace(/\s+/g, ''));
}

describe("AppLayout's ChatPanel onDeckRefetched", () => {
  it('is wired, and does exactly setSlideDeckGated(deck, deck.version)', () => {
    const chatPanels = findAll(appLayout, (n): n is ts.JsxSelfClosingElement | ts.JsxOpeningElement =>
      (ts.isJsxSelfClosingElement(n) || ts.isJsxOpeningElement(n)) && n.tagName.getText(appLayout) === 'ChatPanel',
    );
    expect(chatPanels, '<ChatPanel> not found in AppLayout.tsx').toHaveLength(1);

    const attr = chatPanels[0].attributes.properties.find(
      (p): p is ts.JsxAttribute => ts.isJsxAttribute(p) && p.name.getText(appLayout) === 'onDeckRefetched',
    );
    expect(attr, 'AppLayout does not pass onDeckRefetched to ChatPanel').toBeDefined();
    const init = attr!.initializer;
    expect(init && ts.isJsxExpression(init) && init.expression).toBeTruthy();
    const fn = resolveFunction((init as ts.JsxExpression).expression!);
    expect(fn, 'onDeckRefetched is not a function AppLayout defines').not.toBeNull();

    expect(fn!.parameters).toHaveLength(1);
    const param = fn!.parameters[0].name.getText(appLayout);
    // One call, and only that call: none of the success path (onGenerationComplete — the survey trigger —,
    // setLastSavedTime, setSessionsRefreshKey, setRawHtml, loadVersions), and no `force`.
    expect(callsIn(fn!)).toEqual([`setSlideDeckGated(${param},${param}.version)`]);
  });

  it("the success path's onSlidesGenerated is still the one that runs onGenerationComplete (vacuity guard)", () => {
    const attr = findAll(appLayout, ts.isJsxAttribute).find((a) => a.name.getText(appLayout) === 'onSlidesGenerated');
    expect(attr).toBeDefined();
    const fn = resolveFunction((attr!.initializer as ts.JsxExpression).expression!);
    expect(fn).not.toBeNull();
    expect(callsIn(fn!)).toContain('onGenerationComplete()');
  });
});
