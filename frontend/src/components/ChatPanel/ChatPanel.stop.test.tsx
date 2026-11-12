/**
 * Interrupt generation, Task 10: the ChatPanel stop flow, through the REAL ChatPanel, ChatInput,
 * MessageList and ConfirmDialog.
 *
 * Contract: task-10-brief.md ("Behaviour"), PLAN-CORRECTIONS C15 + C16, and the spec's "What the user
 * sees" (docs/superpowers/specs/2026-11-12-interrupt-generation-design.md). Copy is asserted as literals,
 * so a wrong constant cannot pass.
 *
 *   Which stop: `stopNeedsConfirmation(progress)` (stopGenerationCopy.ts) is true for phase `building`
 *   and `reviewing_deck`. Otherwise (queued, no phase yet, planning, gathering_data, checking_slides) a
 *   stop is instant: `api.cancelChat(requestId)`. Confirm first: ConfirmDialog, initialFocus "cancel"
 *   ("Keep generating" focused), variant danger, `stopDialogMessage(done.length, total)`.
 *   Escape (useEscapeToStop) does exactly what the stop button does.
 *   Only on an Agent deck with the polling transport (`isPollingMode()`); Legacy and SSE keep Send.
 *
 *   Before `request_accepted` there is no request id: the stop is queued in pendingStopRef for THAT
 *   send's seq and sent on its `request_accepted`; never a local cancel first (C16). A send that fails
 *   drops it, so it can never stop a later send.
 *
 *   Outcomes:
 *     cancelChat `cancelled`, a polled `cancelled` (rollback rolled_back / null), or
 *     ChatTurnError rollback `rolled_back` -> finishAfterRollback: polling stopped, loading cleared,
 *       messages REPLACED by conversationApi.listMessages(sentTo), the draft back in the box (focused),
 *       the session's deck mode re-read, api.getSlides(sentTo) -> onDeckRestored(slide_deck ?? null),
 *       and a neutral, dismissible notice ("Generation cancelled. Nothing was changed." / "Generation
 *       failed. Nothing was changed.") that clears on the next send.
 *     `already_finished` (any status, incl. `running`, C15) -> close the dialog; nothing else; polling
 *       goes on and delivers the turn.
 *     `refused_foreign_change` -> the refused notice; the generation goes on.
 *     ChatTurnError `kept_foreign_change` -> today's error path (ErrorDisplay, onDeckRefetched, mode
 *       reconcile) with the failed-but-kept copy.
 *     `restore_failed` (polled `cancelled` C16, ChatTurnError, or the poll after a failed cancelChat)
 *       -> ErrorDisplay with the restore-pending copy, messages + deck refreshed, no notice.
 *     ChatTurnError rollback null -> today's error path, unchanged.
 *     cancelChat network error / 5xx -> one api.pollChat(requestId): terminal restore_failed -> the
 *       restore_failed rule; terminal rolled_back -> finishAfterRollback('cancelled'); still live ->
 *       ErrorDisplay "Couldn't stop the generation. It is still running." and the generation goes on.
 *   The dialog closes itself when the turn completes, errors or is cancelled while it is open.
 *
 * Harness: as ChatPanel.errorRefetch.test.tsx (vi.hoisted + vi.mock('../../services/api')), but the
 * api mock spreads the actual module (ApiError, ChatTurnError) and the REAL ChatInput is rendered.
 * `isPollingMode` is mocked both as a named export and as `api.isPollingMode`, so either wiring works.
 * The transport mock is faithful to startPolling: once the panel calls the cancel function it returned,
 * that turn's onEvent/onError are never called again (a local cancel before submit resolves
 * suppresses `request_accepted`, C16).
 *
 * SABOTAGE (measured by the test author against a throwaway reference implementation, since deleted):
 *   - reviewing_deck left instant                           -> test_stopNeedsConfirmation_by_phase + reviewing_deck case RED.
 *   - initialFocus left at "confirm"                         -> 4 RED (keep-focused x2, both dialog Escape tests).
 *   - a local cancel before request_accepted (C16)           -> Review Focus 1 + 3 more RED.
 *   - a stop before request_accepted dropped                 -> Review Focus 1 + finished-turn test RED.
 *   - requestIdRef not cleared when a send starts            -> test_stop_after_a_session_switch_... RED.
 *   - pendingStopRef: no clear on send AND no seq check      -> test_pending_stop_dropped_by_a_session_switch_... RED.
 *   - pendingStopRef: no clear on fail, on send, no seq check -> test_pending_stop_from_failed_send_... RED.
 *     (Any ONE of those three alone survives: the other two cover the same path. Equivalent mutants.)
 *   - messages not replaced / no onDeckRestored              -> 20 RED each.
 *   - no restoreDraftKey bump                                -> 6 RED.
 *   - the cancelled notice rendered through ErrorDisplay     -> 4 RED.
 *   - notice not cleared on send                             -> test_notice_is_dismissible_and_clears_on_next_send RED.
 *   - already_finished treated as cancelled, or ending polling -> the 3 already_finished tests RED.
 *   - a polled restore_failed handled as a plain cancel      -> the C16 test RED.
 *   - restore_failed leaving the turn loading                -> the 5 restore_failed tests RED.
 *   - 5xx / network error not followed by one poll           -> the 5 cancel-failure tests RED.
 *   - dialog not closed on complete                          -> test_dialog_closes_when_turn_completes (completes) RED.
 *   - rolled_back failure on today's path / kept with the server text -> its test RED.
 *   - refused outcome not shown                              -> test_refused_shows_notice_and_keeps_generating RED.
 *   - onStop on a Legacy deck / in SSE mode                  -> the legacy tests / test_no_stop_in_sse_mode RED.
 *   - useEscapeToStop without its dialog check               -> RED in useEscapeToStop.test.tsx, not here: in ChatPanel
 *     the hook's listener runs before ConfirmDialog's, and a stop while the dialog is open re-sets `open`
 *     to true, which ConfirmDialog's own Escape then closes. Nothing is visible here, so the hook tests pin it.
 */
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { StreamEvent } from '../../services/api';
import type { SlideDeck } from '../../types/slide';
import type { TurnPhase, TurnProgress } from '../../types/turnProgress';

type OnEvent = (event: StreamEvent) => void;
type OnError = (error: Error) => void;
interface Turn {
  sentTo: string;
  message: string;
  onEvent: OnEvent;
  onError: OnError;
  /** The cancel function the transport handed back (ChatPanel's cancelStreamRef). */
  cancel: ReturnType<typeof vi.fn>;
  cancelled: boolean;
}

const h = vi.hoisted(() => {
  const setIsGenerating = vi.fn();
  const refreshConfig = vi.fn();
  return {
    setIsGenerating,
    refreshConfig,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
    setSelectedDeckMode: vi.fn(),
    setStoredDeckMode: vi.fn(),
    agentConfig: { agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false },
    generation: { setIsGenerating },
    session: {
      sessionId: 'sess-1',
      storedDeckMode: 'agent' as 'agent' | 'legacy' | null,
      selectedDeckMode: 'agent' as 'agent' | 'legacy',
    },
    /** What isPollingMode() answers: the production transport is polling. */
    polling: true,
    getSession: vi.fn(),
    getSlides: vi.fn(),
    sendChatMessage: vi.fn(),
    cancelChat: vi.fn(),
    pollChat: vi.fn(),
    listMessages: vi.fn(),
  };
});

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    isPollingMode: () => h.polling,
    api: {
      getSession: (...a: unknown[]) => h.getSession(...a),
      getSlides: (...a: unknown[]) => h.getSlides(...a),
      sendChatMessage: (...a: unknown[]) => h.sendChatMessage(...a),
      cancelChat: (...a: unknown[]) => h.cancelChat(...a),
      pollChat: (...a: unknown[]) => h.pollChat(...a),
      isPollingMode: () => h.polling,
      getCurrentSessionId: () => h.session.sessionId,
      setCurrentSessionId: () => {},
      imageGenerationOptions: () =>
        Promise.resolve({ available: false, max_prompt_chars: 0, default_preset: null, presets: [], edit: null }),
      uploadImage: () => Promise.reject(new Error('not used')),
    },
  };
});
vi.mock('../../api/conversation', () => ({
  conversationApi: {
    listMessages: (...a: unknown[]) => h.listMessages(...a),
    clearChat: () => Promise.reject(new Error('not used')),
    deleteMessage: () => Promise.reject(new Error('not used')),
  },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: h.session.sessionId,
    isSessionPersisted: true,
    isInitializing: false,
    error: null,
    setExperimentUrl: h.setExperimentUrl,
    setSessionTitle: h.setSessionTitle,
    storedDeckMode: h.session.storedDeckMode,
    selectedDeckMode: h.session.selectedDeckMode,
    setSelectedDeckMode: h.setSelectedDeckMode,
    setStoredDeckMode: h.setStoredDeckMode,
  }),
}));
vi.mock('../../contexts/AgentConfigContext', () => ({ useAgentConfig: () => h.agentConfig }));
vi.mock('../../contexts/GenerationContext', () => ({ useGeneration: () => h.generation }));

import { ChatPanel } from './ChatPanel';
import { ApiError, ChatTurnError } from '../../services/api';
import { stopNeedsConfirmation } from './stopGenerationCopy';

// ── copy (literals) ───────────────────────────────────────────────────────────

const STOP_NAME = 'Stop generating';
const DIALOG_TITLE = 'Stop generating?';
const KEEP = 'Keep generating';
const DISCARD = 'Stop and discard';
const CANCELLED = 'Generation cancelled. Nothing was changed.';
const FAILED = 'Generation failed. Nothing was changed.';
const REFUSED = "Someone else has edited this deck since you sent this, so it can't be rolled back.";
const FAILED_KEPT =
  "Generation failed, and it couldn't be undone because someone else has edited this deck since you sent your message.";
const RESTORE_PENDING = 'This deck is still being restored after a failed generation. Try again in a minute.';
const STOP_FAILED = "Couldn't stop the generation. It is still running.";
const HINT = 'Enter to send · Shift+Enter new line';
const GENERATING_HINT = 'Esc to cancel · Enter to send · Shift+Enter new line';
const dialogMessage = (done: number, total: number) =>
  `Your slides are being built (${done} of ${total} done). If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.`;

// ── fixtures ──────────────────────────────────────────────────────────────────

function deckOf(ids: string[], version: number): SlideDeck {
  return {
    title: 'Otters',
    slide_count: ids.length,
    css: '',
    external_scripts: [],
    scripts: '',
    version,
    slides: ids.map((id, index) => ({ index, slide_id: id, html: `<div class="slide">${id}</div>`, scripts: '' })),
  };
}

const TS = '2026-11-12T10:00:00Z';
const HISTORY = [
  { id: 11, role: 'user', content: 'Make a deck about otters', created_at: TS, metadata: {} },
  { id: 12, role: 'assistant', content: 'Here is your otter deck.', created_at: TS, metadata: {} },
];
const DRAFT = 'Add a slide about what otters eat';
const STREAMED = 'Planning a slide on otter diets.';
/** The deck as it was before Enter: what the server holds after a rollback. */
const PRE_TURN_DECK = deckOf(['A', 'B', 'C'], 3);
const FINISHED_DECK = deckOf(['A', 'B', 'C', 'D'], 4);

const slidesOf = (total: number, done: number[], building: number[] = []): TurnProgress['slides'] => ({
  total,
  building,
  reviewing: [],
  fixing: [],
  done,
});

let progressSeq = 0;
function progressEvent(phase: TurnPhase, slides = slidesOf(0, [])): StreamEvent {
  progressSeq += 1;
  return { type: 'turn_progress', turn_progress: { seq: progressSeq, phase, slides } };
}
/** Building, 2 of 5 done. */
const building = () => progressEvent('building', slidesOf(5, [0, 1], [2]));
/** Reviewing the deck, 5 of 5 done. */
const reviewing = () => progressEvent('reviewing_deck', slidesOf(5, [0, 1, 2, 3, 4]));

interface Deferred<T> { promise: Promise<T>; resolve: (v: T) => void }
function deferred<T>(): Deferred<T> {
  let resolve: (v: T) => void = () => {};
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

const running = (rollback: string | null = null) => ({
  status: 'running', events: [], last_message_id: 0, rollback, error: null,
});

// ── harness ───────────────────────────────────────────────────────────────────

const onSlidesGenerated = vi.fn();
const onDeckRefetched = vi.fn();
const onDeckRestored = vi.fn();
const ensureGraphCapableRoot = async () => true;
let turns: Turn[] = [];

type PanelProps = ComponentProps<typeof ChatPanel>;
function panel() {
  // `onDeckRestored` is the new prop; cast so this file reads the same before and after it lands.
  const props = {
    rawHtml: null,
    onSlidesGenerated,
    onDeckRefetched,
    onDeckRestored,
    ensureGraphCapableRoot,
  } as unknown as PanelProps;
  return (
    <MemoryRouter>
      <ChatPanel {...props} />
    </MemoryRouter>
  );
}

/** Let promise callbacks and effects run, so a "nothing happened" check is meaningful. */
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });

let currentView: ReturnType<typeof render> | null = null;
async function mount() {
  const view = render(panel());
  currentView = view;
  await settle(); // the mount-time history load
  return view;
}
/** A parent re-render of the mounted panel, with fresh props. */
const rerenderPanel = () => act(async () => { currentView?.rerender(panel()); });

const textarea = () => screen.getByTestId('chat-input') as HTMLTextAreaElement;
const stopButton = () => screen.getByRole('button', { name: STOP_NAME });
const queryStopButton = () => screen.queryByRole('button', { name: STOP_NAME });
const sendButton = () => screen.getByRole('button', { name: 'Send' });
const queryDialog = () => screen.queryByRole('dialog');
const errorShown = () => screen.queryByRole('button', { name: 'Dismiss error' }) !== null;
/** The chat's message rows, as text, in order. */
const rows = () => screen.queryAllByTestId('chat-message-row').map((r) => r.textContent ?? '');
const progressPlaceholder = () => screen.queryByTestId('chat-turn-progress');

/** Type into the real ChatInput and press Enter. */
async function send(text = DRAFT): Promise<Turn> {
  const before = turns.length;
  fireEvent.change(textarea(), { target: { value: text } });
  await act(async () => { fireEvent.keyDown(textarea(), { key: 'Enter' }); });
  expect(turns.length, 'the message was not sent').toBe(before + 1);
  return turns[turns.length - 1];
}

/** Deliver a transport event, unless the panel has cancelled that turn's polling (as startPolling does). */
const emit = (turn: Turn, event: StreamEvent) =>
  act(async () => { if (!turn.cancelled) turn.onEvent(event); });
const accept = (turn: Turn, requestId = 'req-1') => emit(turn, { type: 'request_accepted', request_id: requestId });
const fail = (turn: Turn, error: Error) => act(async () => { if (!turn.cancelled) turn.onError(error); });
const complete = (turn: Turn) => emit(turn, { type: 'complete', slides: FINISHED_DECK });

const clickStop = () => act(async () => { fireEvent.click(stopButton()); });
const pressEscape = (target: Element = document.body) =>
  act(async () => { fireEvent.keyDown(target, { key: 'Escape', code: 'Escape' }); });

/** A sent, accepted turn in `phaseEvent`'s phase. */
async function runningTurn(phaseEvent: StreamEvent | null = progressEvent('planning'), requestId = 'req-1') {
  await mount();
  const turn = await send();
  await accept(turn, requestId);
  if (phaseEvent) await emit(turn, phaseEvent);
  return turn;
}

/** Open the confirmation for a turn in the building phase. */
async function openConfirmation() {
  const turn = await runningTurn(building());
  await clickStop();
  const dialog = screen.getByRole('dialog');
  return { turn, dialog };
}

/** The single button beside a notice's text: the smallest ancestor holding exactly one button. */
function dismissButtonFor(text: string): HTMLElement {
  let el: HTMLElement | null = screen.getByText(text);
  while (el && el.getAttribute('data-testid') !== 'chat-panel') {
    const buttons = within(el).queryAllByRole('button');
    if (buttons.length === 1) return buttons[0];
    if (buttons.length > 1) break;
    el = el.parentElement;
  }
  throw new Error(`no single dismiss button beside "${text}"`);
}

/** What a finished rollback looks like (finishAfterRollback): the server's truth everywhere. */
async function expectRolledBack(turn: Turn, deck: SlideDeck | null = PRE_TURN_DECK) {
  // Polling stopped, the turn is over and the input is usable at once.
  await waitFor(() => expect(turn.cancel).toHaveBeenCalled());
  await waitFor(() => expect(queryStopButton()).toBeNull());
  expect(progressPlaceholder()).toBeNull();
  expect(screen.getByText(HINT)).toBeInTheDocument();
  expect(textarea()).not.toBeDisabled();
  expect(h.setIsGenerating).toHaveBeenLastCalledWith(false);
  // The user's message (and anything streamed) is gone: the list is the server's.
  await waitFor(() => expect(rows()).toHaveLength(2));
  expect(rows()[0]).toContain('Make a deck about otters');
  expect(rows()[1]).toContain('Here is your otter deck.');
  expect(h.listMessages).toHaveBeenCalled();
  expect(h.listMessages.mock.calls[0][0]).toBe('sess-1');
  // The deck the server holds goes to onDeckRestored, and only there.
  await waitFor(() => expect(onDeckRestored).toHaveBeenCalledTimes(1));
  expect(onDeckRestored.mock.calls[0][0]).toBe(deck);
  expect(h.getSlides).toHaveBeenCalledWith('sess-1');
  expect(onSlidesGenerated).not.toHaveBeenCalled();
  expect(onDeckRefetched).not.toHaveBeenCalled();
}

/** What the restore_failed rule looks like: ErrorDisplay + refreshed messages and deck, no notice. */
async function expectRestorePending() {
  await waitFor(() => expect(screen.getByText(RESTORE_PENDING)).toBeInTheDocument());
  expect(errorShown()).toBe(true);
  expect(screen.queryByText(CANCELLED)).toBeNull();
  expect(screen.queryByText(FAILED)).toBeNull();
  await waitFor(() => expect(rows()).toHaveLength(2));
  expect(h.listMessages.mock.calls[0][0]).toBe('sess-1');
  await waitFor(() => expect(onDeckRestored).toHaveBeenCalledTimes(1));
  expect(onDeckRestored.mock.calls[0][0]).toBe(PRE_TURN_DECK);
  expect(h.getSlides).toHaveBeenCalledWith('sess-1');
  await waitFor(() => expect(queryStopButton()).toBeNull());
  expect(progressPlaceholder()).toBeNull();
}

beforeEach(() => {
  vi.resetAllMocks();
  h.session.sessionId = 'sess-1';
  h.session.storedDeckMode = 'agent';
  h.session.selectedDeckMode = 'agent';
  h.polling = true;
  turns = [];
  progressSeq = 0;
  h.getSession.mockResolvedValue({ messages: HISTORY, my_permission: 'CAN_EDIT', deck_mode: 'agent' });
  h.listMessages.mockResolvedValue({ session_id: 'sess-1', messages: HISTORY, count: HISTORY.length });
  h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: PRE_TURN_DECK });
  h.cancelChat.mockResolvedValue({ outcome: 'cancelled', status: 'cancelled' });
  h.pollChat.mockResolvedValue(running());
  h.sendChatMessage.mockImplementation(
    (sentTo: string, message: string, _ctx: unknown, onEvent: OnEvent, onError: OnError) => {
      const turn: Turn = { sentTo, message, onEvent, onError, cancel: vi.fn(), cancelled: false };
      turn.cancel.mockImplementation(() => { turn.cancelled = true; });
      turns.push(turn);
      return turn.cancel;
    },
  );
});

afterEach(() => {
  cleanup();
  currentView = null;
});

// ── which stop applies ─────────────────────────────────────────────────────────

describe('which stop applies (the spec table)', () => {
  it('test_stopNeedsConfirmation_by_phase', () => {
    const at = (phase: TurnPhase): TurnProgress => ({ seq: 1, phase, slides: slidesOf(3, [0]) });
    expect(stopNeedsConfirmation(null)).toBe(false);
    expect(stopNeedsConfirmation(at('planning'))).toBe(false);
    expect(stopNeedsConfirmation(at('gathering_data'))).toBe(false);
    expect(stopNeedsConfirmation(at('checking_slides'))).toBe(false);
    expect(stopNeedsConfirmation(at('building'))).toBe(true);
    expect(stopNeedsConfirmation(at('reviewing_deck'))).toBe(true);
  });

  describe('test_stop_during_planning_is_instant', () => {
    it.each<[string, () => StreamEvent | null]>([
      ['planning', () => progressEvent('planning')],
      ['gathering_data', () => progressEvent('gathering_data')],
      ['checking_slides', () => progressEvent('checking_slides')],
      ['no phase yet', () => null],
      ['queued for a runner', () => ({ type: 'queued', queued: true })],
    ])('%s: the stop sign replaces Send; a click stops at once with no dialog', async (_state, state) => {
      const turn = await runningTurn(state(), 'req-7');

      expect(stopButton()).toHaveAttribute('title', 'Stop generating (Esc)');
      expect(screen.queryByRole('button', { name: 'Send' })).toBeNull();
      expect(screen.getByText(GENERATING_HINT)).toBeInTheDocument();

      await clickStop();

      expect(queryDialog()).toBeNull();
      expect(h.cancelChat).toHaveBeenCalledTimes(1);
      expect(h.cancelChat).toHaveBeenCalledWith('req-7');
      await expectRolledBack(turn);
    });
  });

  describe('test_stop_during_building_asks_first_with_keep_focused', () => {
    it.each<[string, () => StreamEvent, number, number]>([
      ['building', building, 2, 5],
      ['reviewing_deck', reviewing, 5, 5],
    ])('%s: the confirmation, Keep generating focused, nothing stopped yet', async (_phase, phaseEvent, done, total) => {
      const turn = await runningTurn(phaseEvent());

      await clickStop();

      const dialog = screen.getByRole('dialog');
      expect(within(dialog).getByText(DIALOG_TITLE)).toBeInTheDocument();
      expect(within(dialog).getByText(dialogMessage(done, total))).toBeInTheDocument();
      const keep = within(dialog).getByRole('button', { name: KEEP });
      const discard = within(dialog).getByRole('button', { name: DISCARD });
      await waitFor(() => expect(keep).toHaveFocus());
      expect(discard).not.toHaveFocus();
      expect(discard).toHaveClass('bg-red-600'); // variant="danger"

      // The generation carries on while the dialog is open.
      await settle();
      expect(h.cancelChat).not.toHaveBeenCalled();
      expect(turn.cancel).not.toHaveBeenCalled();
      expect(progressPlaceholder()).not.toBeNull();
    });
  });

  it('test_keep_generating_closes_dialog_without_cancel', async () => {
    const { turn, dialog } = await openConfirmation();

    await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: KEEP })); });
    await settle();

    expect(queryDialog()).toBeNull();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(turn.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();
    expect(rows().some((r) => r.includes(DRAFT))).toBe(true);

    // The generation finishes normally and its deck is handed up.
    h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: FINISHED_DECK });
    await complete(turn);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));
    expect(onSlidesGenerated.mock.calls[0][0]).toBe(FINISHED_DECK);
    expect(onDeckRestored).not.toHaveBeenCalled();
  });

  it('test_stop_and_discard_cancels', async () => {
    const { turn, dialog } = await openConfirmation();

    await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: DISCARD })); });

    expect(queryDialog()).toBeNull();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(h.cancelChat).toHaveBeenCalledWith('req-1');
    await expectRolledBack(turn);
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
  });
});

// ── Escape ───────────────────────────────────────────────────────────────────

describe('Escape', () => {
  it('test_escape_triggers_same_stop (instant phase: stops at once)', async () => {
    const turn = await runningTurn(progressEvent('planning'));

    await pressEscape(document.body);

    expect(queryDialog()).toBeNull();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(h.cancelChat).toHaveBeenCalledWith('req-1');
    await expectRolledBack(turn);
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();

    // No generation running: Escape does nothing.
    await pressEscape(document.body);
    await settle();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(queryDialog()).toBeNull();
  });

  it('test_escape_triggers_same_stop (confirm phase: opens the same dialog)', async () => {
    await runningTurn(building());

    await pressEscape(document.body);

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(DIALOG_TITLE)).toBeInTheDocument();
    expect(within(dialog).getByText(dialogMessage(2, 5))).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole('button', { name: KEEP })).toHaveFocus());
    expect(h.cancelChat).not.toHaveBeenCalled();
  });

  it('test_escape_with_dialog_open_does_not_stop (Review Focus 5: real ConfirmDialog + hook, re-rendered while open)', async () => {
    const turn = await runningTurn(building());
    // Open it with the hook itself.
    await pressEscape(document.body);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Re-render ChatPanel while the dialog is open: a poll (new state) and a parent re-render.
    await emit(turn, progressEvent('building', slidesOf(5, [0, 1, 2], [3])));
    await rerenderPanel();
    await rerenderPanel();
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Escape where the focus is (Keep generating): the dialog closes, nothing is stopped.
    const keep = screen.getByRole('button', { name: KEEP });
    await waitFor(() => expect(keep).toHaveFocus());
    await pressEscape(keep);
    expect(queryDialog()).toBeNull();
    await settle();
    expect(queryDialog(), 'the dialog reopened').toBeNull();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(turn.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();

    // Positive in the same test: the stop still works.
    await clickStop();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: DISCARD })); });
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(h.cancelChat).toHaveBeenCalledWith('req-1');
  });
});

// ── a stop before the request id exists ────────────────────────────────────────

describe('a stop before request_accepted', () => {
  it('test_stop_before_request_accepted_is_sent_once_accepted (Review Focus 1)', async () => {
    await mount();
    const turn = await send();

    // No request id yet (the submit has not answered): the stop sign is already there.
    await clickStop();
    const again = queryStopButton();
    if (again) await act(async () => { fireEvent.click(again); }); // a second press must not send twice
    await settle();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(turn.cancel, 'C16: a local cancel before submit resolves suppresses request_accepted').not.toHaveBeenCalled();
    expect(queryDialog()).toBeNull();

    await accept(turn, 'req-9');

    await waitFor(() => expect(h.cancelChat).toHaveBeenCalledTimes(1));
    expect(h.cancelChat).toHaveBeenCalledWith('req-9');
    await expectRolledBack(turn);
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
    await settle();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
  });

  it('test_pending_stop_from_failed_send_does_not_cancel_next_send', async () => {
    await mount();
    const first = await send('First try');
    await clickStop(); // queued: no request id yet
    // The submit fails: there is never a request_accepted for this send.
    await fail(first, new Error('Failed to start chat'));
    await settle();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(screen.getByText('Failed to start chat')).toBeInTheDocument(); // today's error path

    const second = await send('Second try');
    await accept(second, 'req-2');
    await emit(second, progressEvent('planning'));
    await settle();
    expect(h.cancelChat, "the failed send's pending stop stopped the next send").not.toHaveBeenCalled();
    expect(second.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();

    // Positive in the same test: a stop on the new send goes to the new request.
    await clickStop();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(h.cancelChat).toHaveBeenCalledWith('req-2');
  });

  it('test_stop_after_a_finished_turn_waits_for_the_new_request_id', async () => {
    await mount();
    const first = await send('First try');
    await accept(first, 'req-1');
    await complete(first);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));

    const second = await send('Second try');
    await clickStop(); // the new send has no id yet; req-1 is finished and must not be used
    await settle();
    expect(h.cancelChat).not.toHaveBeenCalled();

    await accept(second, 'req-2');
    await waitFor(() => expect(h.cancelChat).toHaveBeenCalledTimes(1));
    expect(h.cancelChat).toHaveBeenCalledWith('req-2');
  });

  it('test_stop_after_a_session_switch_never_targets_the_old_request (requestIdRef cleared when a send starts)', async () => {
    await mount();
    const first = await send('In the first deck');
    await accept(first, 'req-old');
    await emit(first, progressEvent('planning'));

    // The user opens another deck mid-turn: today's cleanup ends the old turn's polling locally.
    h.session.sessionId = 'sess-2';
    await rerenderPanel();
    await settle();
    expect(first.cancel).toHaveBeenCalled();

    const second = await send('In the second deck');
    expect(second.sentTo).toBe('sess-2');
    await clickStop(); // the new send has no id yet
    await settle();
    expect(h.cancelChat, "a stop in the new deck went to the old deck's request").not.toHaveBeenCalled();

    await accept(second, 'req-new');
    await waitFor(() => expect(h.cancelChat).toHaveBeenCalledTimes(1));
    expect(h.cancelChat).toHaveBeenCalledWith('req-new');
  });

  it('test_pending_stop_dropped_by_a_session_switch_does_not_stop_the_next_send (pendingStopRef cleared when a send starts)', async () => {
    await mount();
    await send('In the first deck');
    await clickStop(); // queued for this send's request_accepted, which never comes: the user leaves
    h.session.sessionId = 'sess-2';
    await rerenderPanel();
    await settle();

    const second = await send('In the second deck');
    await accept(second, 'req-2');
    await emit(second, progressEvent('planning'));
    await settle();
    expect(h.cancelChat, "the old send's pending stop stopped the next send").not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();

    // Positive in the same test: a stop on the new send goes to the new request.
    await clickStop();
    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(h.cancelChat).toHaveBeenCalledWith('req-2');
  });
});

// ── what the user sees after a stop ────────────────────────────────────────────

describe('after a stop', () => {
  it('test_after_cancel_messages_replaced_draft_restored_deck_restored_notice_shown', async () => {
    await mount();
    expect(rows()).toHaveLength(2);
    const turn = await send(DRAFT);
    await accept(turn, 'req-1');
    await emit(turn, { type: 'assistant', content: STREAMED });
    await emit(turn, progressEvent('planning'));
    expect(rows()).toHaveLength(4);
    expect(rows()[2]).toContain(DRAFT);
    expect(rows()[3]).toContain(STREAMED);
    expect(textarea().value).toBe('');
    expect(h.listMessages).not.toHaveBeenCalled();
    expect(h.setStoredDeckMode).not.toHaveBeenCalled();

    await clickStop();

    expect(h.cancelChat).toHaveBeenCalledWith('req-1');
    await expectRolledBack(turn);
    // The text they sent is back in the box, focused, cursor at the end, ready to resend.
    await waitFor(() => expect(textarea().value).toBe(DRAFT));
    await waitFor(() => expect(textarea()).toHaveFocus());
    expect(textarea().selectionStart).toBe(DRAFT.length);
    expect(sendButton()).not.toBeDisabled();
    // The deck mode is re-read from the server (reconcileDeckModeAfterError).
    await waitFor(() => expect(h.setStoredDeckMode).toHaveBeenCalledWith('agent'));
    expect(h.getSession.mock.calls.at(-1)?.[0]).toBe('sess-1');
    // A neutral notice, not an error.
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
    expect(errorShown()).toBe(false);
    expect(screen.queryByText(FAILED)).toBeNull();
  });

  it('test_rollback_to_empty_deck_hands_up_null (a first turn on a new deck)', async () => {
    h.session.storedDeckMode = null; // a new deck: the mode locks optimistically on send
    h.getSession.mockResolvedValue({ messages: [], my_permission: 'CAN_EDIT', deck_mode: null });
    h.listMessages.mockResolvedValue({ session_id: 'sess-1', messages: [], count: 0 });
    h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: null });
    await mount();
    const turn = await send();
    expect(h.setStoredDeckMode).toHaveBeenLastCalledWith('agent');
    await accept(turn);
    await emit(turn, progressEvent('planning'));

    await clickStop();

    await waitFor(() => expect(onDeckRestored).toHaveBeenCalledTimes(1));
    expect(onDeckRestored.mock.calls[0][0]).toBeNull();
    await waitFor(() => expect(rows()).toHaveLength(0));
    // The server unlocked the mode with the rolled-back first message.
    await waitFor(() => expect(h.setStoredDeckMode).toHaveBeenLastCalledWith(null));
    await waitFor(() => expect(textarea().value).toBe(DRAFT));
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
  });

  it('test_rollback_refresh_landing_after_a_newer_send_is_dropped (coordinator ruling: the sendSeqRef guard)', async () => {
    const staleMessages = deferred<unknown>();
    const staleSlides = deferred<unknown>();
    h.listMessages.mockReturnValueOnce(staleMessages.promise);
    h.getSlides.mockReturnValueOnce(staleSlides.promise);
    await runningTurn(progressEvent('planning'));

    await clickStop();
    // cancelChat answered `cancelled`: the refresh is asked for, and the input is usable at once.
    await waitFor(() => expect(h.listMessages).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(h.getSlides).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(textarea().value).toBe(DRAFT));

    // The user sends again BEFORE the refresh lands.
    const second = await send('Something new');
    expect(rows().some((r) => r.includes('Something new'))).toBe(true);

    // Now the stopped turn's refresh lands: it belongs to an older send and must be dropped.
    await act(async () => {
      staleMessages.resolve({ session_id: 'sess-1', messages: HISTORY, count: HISTORY.length });
      staleSlides.resolve({ session_id: 'sess-1', slide_deck: PRE_TURN_DECK });
    });
    await settle();
    expect(rows().some((r) => r.includes('Something new')), 'the late refresh wiped the new message').toBe(true);
    expect(onDeckRestored, 'the late refresh handed up the stale deck').not.toHaveBeenCalled();

    // Positive in the same test: the new turn's own rollback refresh is handed up.
    h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: FINISHED_DECK });
    await accept(second, 'req-2');
    await clickStop();
    await waitFor(() => expect(onDeckRestored).toHaveBeenCalledTimes(1));
    expect(onDeckRestored.mock.calls[0][0]).toBe(FINISHED_DECK);
  });

  it('test_notice_is_dismissible_and_clears_on_next_send', async () => {
    const turn = await runningTurn(progressEvent('planning'));
    await clickStop();
    await expectRolledBack(turn);
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();

    await act(async () => { fireEvent.click(dismissButtonFor(CANCELLED)); });
    expect(screen.queryByText(CANCELLED)).toBeNull();

    // A second stop shows it again; the next send clears it.
    const second = await send('Try again');
    await accept(second, 'req-2');
    await clickStop();
    await waitFor(() => expect(screen.getByText(CANCELLED)).toBeInTheDocument());
    await send('And again');
    expect(screen.queryByText(CANCELLED)).toBeNull();
  });
});

// ── the dialog follows the turn ──────────────────────────────────────────────

describe('the dialog closes itself when the turn ends', () => {
  it.each<[string, (turn: Turn) => Promise<void>, () => void]>([
    [
      'completes',
      (turn) => complete(turn),
      () => expect(onSlidesGenerated).toHaveBeenCalledTimes(1),
    ],
    [
      'errors',
      (turn) => fail(turn, new ChatTurnError('The turn failed', null)),
      () => expect(screen.getByText('The turn failed')).toBeInTheDocument(),
    ],
    [
      'is cancelled from another tab',
      (turn) => emit(turn, { type: 'cancelled', rollback: 'rolled_back' }),
      () => expect(screen.getByText(CANCELLED)).toBeInTheDocument(),
    ],
  ])('test_dialog_closes_when_turn_completes (%s)', async (_how, end, outcome) => {
    const { turn } = await openConfirmation();

    await end(turn);

    await waitFor(() => expect(queryDialog()).toBeNull());
    await waitFor(outcome);
    expect(h.cancelChat).not.toHaveBeenCalled();
    await waitFor(() => expect(queryStopButton()).toBeNull());

    // Nothing is running: Escape opens nothing and stops nothing.
    await pressEscape(document.body);
    await settle();
    expect(queryDialog()).toBeNull();
    expect(h.cancelChat).not.toHaveBeenCalled();
  });
});

// ── cancelChat outcomes ───────────────────────────────────────────────────────

describe('what cancelChat answers', () => {
  it('test_already_finished_keeps_result', async () => {
    h.cancelChat.mockResolvedValue({ outcome: 'already_finished', status: 'completed' });
    const { turn, dialog } = await openConfirmation();

    await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: DISCARD })); });
    await settle();

    expect(h.cancelChat).toHaveBeenCalledWith('req-1');
    expect(queryDialog()).toBeNull();
    // Nothing else: no rollback refresh, no notice, no error, the draft stays sent.
    expect(turn.cancel, 'polling must go on to deliver the finished turn').not.toHaveBeenCalled();
    expect(h.listMessages).not.toHaveBeenCalled();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(screen.queryByText(CANCELLED)).toBeNull();
    expect(errorShown()).toBe(false);
    expect(textarea().value).toBe('');
    expect(rows().some((r) => r.includes(DRAFT))).toBe(true);

    // Polling delivers the finished turn; its deck stays.
    h.getSlides.mockResolvedValue({ session_id: 'sess-1', slide_deck: FINISHED_DECK });
    await complete(turn);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));
    expect(onSlidesGenerated.mock.calls[0][0]).toBe(FINISHED_DECK);
    expect(onDeckRestored).not.toHaveBeenCalled();
    await waitFor(() => expect(queryStopButton()).toBeNull());
  });

  it.each<[string, () => StreamEvent]>([
    ['instant stop', () => progressEvent('planning')],
    ['confirmed stop', building],
  ])('test_already_finished_while_running_keeps_polling (C15, %s)', async (kind, phaseEvent) => {
    h.cancelChat.mockResolvedValue({ outcome: 'already_finished', status: 'running' });
    const turn = await runningTurn(phaseEvent());

    await clickStop();
    if (kind === 'confirmed stop') {
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: DISCARD })); });
    }
    await settle();

    expect(h.cancelChat).toHaveBeenCalledTimes(1);
    expect(queryDialog()).toBeNull();
    // `running` is not final: the turn is still shown as running and polling goes on.
    expect(turn.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();
    expect(progressPlaceholder()).not.toBeNull();
    expect(h.listMessages).not.toHaveBeenCalled();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(screen.queryByText(CANCELLED)).toBeNull();
    expect(errorShown()).toBe(false);

    await complete(turn);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(queryStopButton()).toBeNull());
  });

  it('test_refused_shows_notice_and_keeps_generating', async () => {
    h.cancelChat.mockResolvedValue({ outcome: 'refused_foreign_change', detail: REFUSED });
    const { turn, dialog } = await openConfirmation();

    await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: DISCARD })); });

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    expect(queryDialog()).toBeNull();
    // The generation carries on.
    await settle();
    expect(turn.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();
    expect(progressPlaceholder()).not.toBeNull();
    expect(h.listMessages).not.toHaveBeenCalled();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(rows().some((r) => r.includes(DRAFT))).toBe(true);
    expect(textarea().value).toBe('');

    await complete(turn);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));
  });

  it.each<[string, Error]>([
    ['a 500', new ApiError(500, 'Internal server error')],
    ['a network error', new TypeError('Failed to fetch')],
  ])('test_cancel_500_then_poll_restore_failed_shows_restore_pending (%s)', async (_kind, failure) => {
    h.cancelChat.mockRejectedValue(failure);
    // C16: a stop whose restore failed is `cancelled` + restore_failed, and the poll's error is null.
    h.pollChat.mockResolvedValue({ status: 'cancelled', rollback: 'restore_failed', error: null, events: [], last_message_id: 0 });
    await runningTurn(progressEvent('planning'), 'req-5');

    await clickStop();

    await waitFor(() => expect(h.pollChat).toHaveBeenCalledTimes(1));
    expect(h.pollChat.mock.calls[0][0]).toBe('req-5');
    await expectRestorePending();
    expect(screen.queryByText(STOP_FAILED)).toBeNull();
    await settle();
    expect(h.pollChat).toHaveBeenCalledTimes(1);
  });

  it('test_cancel_500_then_poll_error_restore_failed_shows_the_servers_message', async () => {
    h.cancelChat.mockRejectedValue(new ApiError(503, 'Service unavailable'));
    h.pollChat.mockResolvedValue({
      status: 'error', rollback: 'restore_failed', error: RESTORE_PENDING, events: [], last_message_id: 0,
    });
    await runningTurn(progressEvent('planning'));

    await clickStop();

    await waitFor(() => expect(h.pollChat).toHaveBeenCalledTimes(1));
    await expectRestorePending();
  });

  it('test_cancel_network_error_then_poll_rolled_back_finishes_as_cancelled', async () => {
    h.cancelChat.mockRejectedValue(new TypeError('Failed to fetch'));
    h.pollChat.mockResolvedValue({ status: 'cancelled', rollback: 'rolled_back', error: null, events: [], last_message_id: 0 });
    const turn = await runningTurn(progressEvent('planning'), 'req-3');

    await clickStop();

    await waitFor(() => expect(h.pollChat).toHaveBeenCalledTimes(1));
    expect(h.pollChat.mock.calls[0][0]).toBe('req-3');
    await expectRolledBack(turn);
    await waitFor(() => expect(textarea().value).toBe(DRAFT));
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
    expect(errorShown()).toBe(false);
  });

  it('test_cancel_500_then_poll_still_running_shows_stop_failed', async () => {
    h.cancelChat.mockRejectedValue(new ApiError(500, 'Internal server error'));
    h.pollChat.mockResolvedValue(running());
    const turn = await runningTurn(progressEvent('planning'));

    await clickStop();

    await waitFor(() => expect(h.pollChat).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(STOP_FAILED)).toBeInTheDocument());
    expect(errorShown()).toBe(true);
    // The generation carries on.
    expect(turn.cancel).not.toHaveBeenCalled();
    expect(stopButton()).toBeInTheDocument();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(screen.queryByText(CANCELLED)).toBeNull();

    await complete(turn);
    await waitFor(() => expect(onSlidesGenerated).toHaveBeenCalledTimes(1));
  });
});

// ── a polled `cancelled` (the stop came from another tab) ─────────────────────

describe('a cancelled event from polling', () => {
  it.each<[string, 'rolled_back' | null]>([
    ['rolled_back', 'rolled_back'],
    ['no rollback reported', null],
  ])('test_polled_cancelled_from_another_tab_finishes_as_stop (%s)', async (_kind, rollback) => {
    const turn = await runningTurn(building());

    await emit(turn, { type: 'cancelled', rollback });

    await expectRolledBack(turn);
    await waitFor(() => expect(textarea().value).toBe(DRAFT));
    expect(screen.getByText(CANCELLED)).toBeInTheDocument();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(errorShown()).toBe(false);
  });

  it('test_polled_cancelled_restore_failed_shows_restore_pending (C16)', async () => {
    const turn = await runningTurn(building());

    await emit(turn, { type: 'cancelled', rollback: 'restore_failed' });

    await expectRestorePending();
    expect(h.cancelChat).not.toHaveBeenCalled();
  });
});

// ── failures ──────────────────────────────────────────────────────────────────

describe('a failed turn', () => {
  it('test_failure_rolled_back_behaves_like_stop_with_failed_notice', async () => {
    const turn = await runningTurn(building());

    await fail(turn, new ChatTurnError('Graph turn failed: 403 from the model', 'rolled_back'));

    await waitFor(() => expect(screen.getByText(FAILED)).toBeInTheDocument());
    expect(screen.queryByText(CANCELLED)).toBeNull();
    expect(errorShown()).toBe(false);
    await waitFor(() => expect(rows()).toHaveLength(2));
    await waitFor(() => expect(textarea().value).toBe(DRAFT)); // retrying is one keypress
    await waitFor(() => expect(onDeckRestored).toHaveBeenCalledTimes(1));
    expect(onDeckRestored.mock.calls[0][0]).toBe(PRE_TURN_DECK);
    expect(h.listMessages.mock.calls[0][0]).toBe('sess-1');
    expect(h.getSlides).toHaveBeenCalledWith('sess-1');
    expect(onDeckRefetched).not.toHaveBeenCalled();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(queryStopButton()).toBeNull();
    await waitFor(() => expect(h.setStoredDeckMode).toHaveBeenCalledWith('agent'));

    await act(async () => { fireEvent.click(dismissButtonFor(FAILED)); });
    expect(screen.queryByText(FAILED)).toBeNull();
  });

  it('test_failure_kept_foreign_change_uses_error_display', async () => {
    const turn = await runningTurn(building());

    await fail(turn, new ChatTurnError('Graph turn failed', 'kept_foreign_change'));

    await waitFor(() => expect(screen.getByText(FAILED_KEPT)).toBeInTheDocument());
    expect(errorShown()).toBe(true);
    // Today's error path: refetch to onDeckRefetched, re-read the mode; the turn's message stays.
    await waitFor(() => expect(onDeckRefetched).toHaveBeenCalledTimes(1));
    expect(onDeckRefetched.mock.calls[0][0]).toBe(PRE_TURN_DECK);
    await waitFor(() => expect(h.setStoredDeckMode).toHaveBeenCalledWith('agent'));
    await settle();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(screen.queryByText(FAILED)).toBeNull();
    expect(screen.queryByText(CANCELLED)).toBeNull();
    expect(rows().some((r) => r.includes(DRAFT))).toBe(true);
    expect(textarea().value).toBe('');
    expect(queryStopButton()).toBeNull();
  });

  it('test_failure_restore_failed_shows_restore_pending', async () => {
    const turn = await runningTurn(building());

    await fail(turn, new ChatTurnError(RESTORE_PENDING, 'restore_failed'));

    await expectRestorePending();
  });

  it('test_failure_without_rollback_keeps_todays_error_path', async () => {
    const turn = await runningTurn(building());
    expect(stopButton()).toBeInTheDocument();

    await fail(turn, new ChatTurnError('The turn failed', null));

    await waitFor(() => expect(screen.getByText('The turn failed')).toBeInTheDocument());
    expect(errorShown()).toBe(true);
    await waitFor(() => expect(onDeckRefetched).toHaveBeenCalledTimes(1));
    expect(onDeckRefetched.mock.calls[0][0]).toBe(PRE_TURN_DECK);
    await settle();
    expect(onDeckRestored).not.toHaveBeenCalled();
    expect(screen.queryByText(FAILED)).toBeNull();
    expect(screen.queryByText(CANCELLED)).toBeNull();
    expect(rows().some((r) => r.includes(DRAFT))).toBe(true);
    expect(textarea().value).toBe('');
    expect(queryStopButton()).toBeNull();
  });
});

// ── where there is no stop ────────────────────────────────────────────────────

describe('no stop where the turn cannot be stopped', () => {
  /** The same flow on an Agent deck with polling: the stop sign shows (the harness can see one). */
  async function expectStopShownOnAnAgentDeck() {
    const turn = await runningTurn(progressEvent('planning'));
    expect(stopButton()).toBeInTheDocument();
    expect(screen.getByText(GENERATING_HINT)).toBeInTheDocument();
    await emit(turn, { type: 'queued', queued: false });
    cleanup();
    turns = [];
    vi.clearAllMocks();
  }

  async function expectSendKept() {
    await mount();
    const turn = await send();
    await accept(turn, 'req-1');
    await emit(turn, building());

    expect(queryStopButton()).toBeNull();
    expect(sendButton()).toBeDisabled();
    expect(screen.getByText(HINT)).toBeInTheDocument();
    expect(screen.queryByText(GENERATING_HINT)).toBeNull();
    expect(progressPlaceholder()).not.toBeNull(); // the turn is running

    await pressEscape(document.body);
    await settle();
    expect(queryDialog()).toBeNull();
    expect(h.cancelChat).not.toHaveBeenCalled();
    expect(turn.cancel).not.toHaveBeenCalled();
  }

  it('test_no_stop_on_legacy_deck', async () => {
    await expectStopShownOnAnAgentDeck();

    h.session.storedDeckMode = 'legacy';
    h.session.selectedDeckMode = 'legacy';
    await expectSendKept();
  });

  it('test_no_stop_on_a_new_deck_set_to_legacy', async () => {
    await expectStopShownOnAnAgentDeck();

    h.session.storedDeckMode = null;
    h.session.selectedDeckMode = 'legacy';
    await expectSendKept();
  });

  it('test_no_stop_in_sse_mode', async () => {
    await expectStopShownOnAnAgentDeck();

    h.polling = false; // the SSE transport has no request id to stop
    await expectSendKept();
  });
});
