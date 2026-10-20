/**
 * #317 Delete a message: the per-message action in the chat panel that deletes one of the user's
 * messages and the replies to it (plan Task 7; Decisions D12, D13, D14; review F1; corrections C15).
 *
 * Mock scaffold from ChatPanel.clearChat.test.tsx (#323), except that the real MessageList and the
 * real Message render, the conversation API also has deleteMessage and listMessages, and the
 * mocked transport hands each turn's onEvent/onError to the test so it can end the turn.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createRef, type Ref } from 'react';
import { render, screen, waitFor, act, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { Message } from '../../types/message';
import type { SessionMessage, StreamEvent } from '../../services/api';

type OnEvent = (event: StreamEvent) => void;
type OnError = (error: Error) => void;
interface Turn { onEvent: OnEvent; onError: OnError }

const getSession = vi.fn<(id: string) => Promise<unknown>>();
const getSlides = vi.fn<(id: string) => Promise<unknown>>();
const sendChatMessage = vi.fn<
  (sessionId: string, message: string, slideContext: unknown, onEvent: OnEvent, onError: OnError) => () => void
>();
const clearChat = vi.fn<(sessionId: string) => Promise<unknown>>();
const deleteMessage = vi.fn<(sessionId: string, messageId: number) => Promise<unknown>>();
const listMessages = vi.fn<(sessionId: string, limit?: number) => Promise<unknown>>();
const refreshConfig = vi.fn();
// One function for the whole file (see ChatPanel.clearChat.test.tsx): a new identity per render
// would re-run the session-change cleanup and end every turn at once.
const setIsGenerating = vi.fn();
let currentSessionId = 'sess-1';
let currentPersisted = true;
let turn: Turn | null = null;

vi.mock('../../services/api', () => ({
  api: {
    getSession: (...a: Parameters<typeof getSession>) => getSession(...a),
    getSlides: (...a: Parameters<typeof getSlides>) => getSlides(...a),
    sendChatMessage: (...a: Parameters<typeof sendChatMessage>) => sendChatMessage(...a),
  },
}));
vi.mock('../../api/conversation', () => ({
  conversationApi: {
    clearChat: (...a: Parameters<typeof clearChat>) => clearChat(...a),
    deleteMessage: (...a: Parameters<typeof deleteMessage>) => deleteMessage(...a),
    listMessages: (...a: Parameters<typeof listMessages>) => listMessages(...a),
  },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: currentSessionId,
    isSessionPersisted: currentPersisted,
    isInitializing: false,
    error: null,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
  }),
}));
vi.mock('../../contexts/AgentConfigContext', () => ({
  useAgentConfig: () => ({
    agentConfig: null,
    refreshConfig: (...a: unknown[]) => refreshConfig(...a),
    configOwnerSessionId: null,
    isPreSession: false,
  }),
}));
vi.mock('../../contexts/GenerationContext', () => ({
  useGeneration: () => ({ setIsGenerating }),
}));
vi.mock('./ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (message: string) => void; disabled: boolean }) => (
    <button data-testid="mock-send" disabled={disabled} onClick={() => onSend('Make slide 3 shorter')}>
      send
    </button>
  ),
}));

import { ChatPanel, type ChatPanelHandle } from './ChatPanel';
import {
  DELETE_MESSAGE_TOOLTIP,
  DELETE_MESSAGE_DIALOG_TITLE,
  DELETE_MESSAGE_DIALOG_MESSAGE,
  DELETE_MESSAGE_BUSY,
  DELETE_MESSAGE_FORBIDDEN,
  DELETE_MESSAGE_GONE,
  DELETE_MESSAGE_FAILED,
} from './deleteMessageCopy';
import { CLEAR_CHAT_DIALOG_MESSAGE } from './clearChatCopy';

const U = (id: number, content: string): SessionMessage => ({ id, role: 'user', content, created_at: 't' });
const A = (id: number, content: string): SessionMessage => ({ id, role: 'assistant', content, created_at: 't' });

/** What the mocked ChatInput sends, every time. */
const SENT = 'Make slide 3 shorter';
const FOUR = [U(1, 'Build a deck'), A(2, 'Built 3 slides.'), U(3, 'Make the title punchier'), A(4, 'Edited slide 1.')];
const FOUR_TEXTS = FOUR.map(m => m.content);
const EDITOR_SESSION = { messages: FOUR, my_permission: 'CAN_MANAGE' };
const OTHER = [U(21, 'Another deck'), A(22, 'Another reply')];
const rowsRead = (messages: unknown[]) => ({ session_id: 'sess-1', messages, count: messages.length });

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

interface PanelProps {
  hasDeckSpec?: boolean;
  disabled?: boolean;
  previewMessages?: Message[] | null;
}

const onSlidesGenerated = vi.fn();
const ensureGraphCapableRoot = vi.fn(async () => true);

function panel(props: PanelProps = {}, ref?: Ref<ChatPanelHandle>) {
  return (
    <MemoryRouter>
      <ChatPanel
        ref={ref}
        rawHtml={null}
        onSlidesGenerated={onSlidesGenerated}
        ensureGraphCapableRoot={ensureGraphCapableRoot}
        {...props}
      />
    </MemoryRouter>
  );
}

// No hasDeckSpec by default: the delete action is offered with or without a Spec (D11).
function mount(props: PanelProps = {}, ref?: Ref<ChatPanelHandle>) {
  return render(panel(props, ref));
}

/** Let pending promise callbacks and effects run, so a "nothing happened" check is meaningful. */
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 30)); });
const deleteButtons = () => screen.queryAllByTestId('delete-message-button');
const rows = () => screen.queryAllByTestId('chat-message-row');
const rowTexts = () => rows().map(r => r.textContent);
const rowsWith = (text: string) => rows().filter(r => within(r).queryByText(text) !== null);
function rowWith(text: string) {
  const found = rowsWith(text);
  expect(found).toHaveLength(1);
  return found[0];
}
const deleteButtonIn = (row: HTMLElement) => within(row).queryByTestId('delete-message-button');
const sendButton = () => screen.getByTestId('mock-send');
const errorShown = () => screen.queryByRole('button', { name: 'Dismiss error' }) !== null;
/** The row buttons are named after the tooltip; the dialog's own confirm is "Delete". Scope to it. */
const confirmInDialog = () =>
  within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Delete' });

/** The load has landed and its two user messages offer delete. */
async function loaded(count = 2) {
  await waitFor(() => expect(deleteButtons()).toHaveLength(count));
}

function openDelete(row: HTMLElement) {
  const button = deleteButtonIn(row);
  if (!button) throw new Error(`no delete button on the row "${row.textContent}"`);
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
}

async function deleteRow(row: HTMLElement) {
  openDelete(row);
  await act(async () => { fireEvent.click(confirmInDialog()); });
}

async function send() {
  await act(async () => { fireEvent.click(sendButton()); });
}

function currentTurn(): Turn {
  if (!turn) throw new Error('no turn has been sent');
  return turn;
}
/** Delivers one transport event to the turn sent last. */
const emit = (event: StreamEvent) => act(async () => { currentTurn().onEvent(event); });
/** The transport's own failure callback for the turn sent last. */
const failTransport = (error: Error) => act(async () => { currentTurn().onError(error); });

describe('ChatPanel delete a message (#317)', () => {
  beforeEach(() => {
    getSession.mockReset();
    getSlides.mockReset();
    sendChatMessage.mockReset();
    clearChat.mockReset();
    deleteMessage.mockReset();
    listMessages.mockReset();
    refreshConfig.mockReset();
    setIsGenerating.mockReset();
    onSlidesGenerated.mockReset();
    ensureGraphCapableRoot.mockReset();
    currentSessionId = 'sess-1';
    currentPersisted = true;
    turn = null;
    getSession.mockResolvedValue(EDITOR_SESSION);
    getSlides.mockResolvedValue({ slide_deck: null });
    sendChatMessage.mockImplementation((_s, _m, _c, onEvent, onError) => {
      turn = { onEvent, onError };
      return () => {};
    });
    clearChat.mockResolvedValue({ status: 'cleared', session_id: 'sess-1', deleted_messages: 4, preserved_message_id: 1 });
    deleteMessage.mockImplementation(async (sessionId, messageId) => ({
      status: 'deleted', session_id: sessionId, message_id: messageId, deleted_messages: 2, hidden_message_id: null,
    }));
    listMessages.mockResolvedValue(rowsRead(FOUR));
    ensureGraphCapableRoot.mockResolvedValue(true);
  });

  // ---- 1-2: who sees the action -------------------------------------------------------------

  it.each(['CAN_EDIT', 'CAN_MANAGE'])(
    "offers delete on each of the user's persisted messages to an editor (%s)",
    async (permission) => {
      getSession.mockResolvedValue({ messages: FOUR, my_permission: permission });
      mount();
      await loaded();
      expect(rowTexts()).toEqual(FOUR_TEXTS);
      for (const text of ['Build a deck', 'Make the title punchier']) {
        const button = deleteButtonIn(rowWith(text));
        expect(button).toBeEnabled();
        expect(button).toHaveAccessibleName(DELETE_MESSAGE_TOOLTIP);
        expect(button).toHaveAttribute('title', DELETE_MESSAGE_TOOLTIP);
      }
      expect(deleteButtonIn(rowWith('Built 3 slides.'))).toBeNull();
      expect(deleteButtonIn(rowWith('Edited slide 1.'))).toBeNull();
      expect(getSession).toHaveBeenCalledWith('sess-1');
    },
  );

  // Same setup as the test above except for the one condition named; each must show no action.
  it.each([
    { label: 'to a viewer (CAN_VIEW)', permission: 'CAN_VIEW', persisted: true, shown: 'Make the title punchier', props: {} },
    { label: 'without a permission', permission: undefined, persisted: true, shown: 'Make the title punchier', props: {} },
    { label: 'before the session is persisted', permission: 'CAN_MANAGE', persisted: false, shown: 'Make the title punchier', props: {} },
    {
      label: 'in a save-point preview',
      permission: 'CAN_MANAGE',
      persisted: true,
      shown: 'Saved prompt',
      // The saved chat carries row ids (a save point captures them), so only the preview gate can hide the action.
      props: {
        previewMessages: [
          { id: 1, role: 'user' as const, content: 'Saved prompt', timestamp: 't' },
          { id: 2, role: 'assistant' as const, content: 'Saved reply', timestamp: 't' },
        ],
      },
    },
  ])('does not offer delete $label', async ({ permission, persisted, shown, props }) => {
    currentPersisted = persisted;
    getSession.mockResolvedValue({ messages: FOUR, my_permission: permission });
    const view = mount(props);
    await waitFor(() => expect(getSession).toHaveBeenCalledWith('sess-1'));
    await settle(); // the load, and the my_permission it carries, has landed
    expect(screen.getByText(shown)).toBeInTheDocument(); // a user message with an id is on screen
    expect(deleteButtons()).toHaveLength(0);

    // Control: the same deck, for an editor, on a persisted session, outside a preview, offers it.
    view.unmount();
    currentPersisted = true;
    getSession.mockResolvedValue(EDITOR_SESSION);
    mount();
    await loaded();
  });

  // ---- 3: when the action is unavailable -----------------------------------------------------

  it('disables delete while a turn runs', async () => {
    mount();
    await loaded();
    expect(deleteButtons().every(b => !(b as HTMLButtonElement).disabled)).toBe(true); // control
    await send();
    expect(sendChatMessage).toHaveBeenCalledTimes(1);
    expect(deleteButtons()).toHaveLength(2);
    for (const button of deleteButtons()) expect(button).toBeDisabled();
    fireEvent.click(deleteButtons()[1]);
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();

    // The turn ends: the action is back.
    await emit({ type: 'complete' });
    await waitFor(() => {
      for (const button of deleteButtons()) expect(button).toBeEnabled();
    });
    expect(deleteButtons()).toHaveLength(2);
  });

  it('disables delete while the panel is read-only', async () => {
    const view = mount({ disabled: true });
    await loaded();
    for (const button of deleteButtons()) expect(button).toBeDisabled();
    view.rerender(panel({}));
    await waitFor(() => {
      for (const button of deleteButtons()) expect(button).toBeEnabled();
    });
    expect(deleteButtons()).toHaveLength(2);
  });

  it('disables delete while a clear runs', async () => {
    const pending = deferred<unknown>();
    clearChat.mockReturnValueOnce(pending.promise);
    mount({ hasDeckSpec: true });
    await loaded();
    const clear = screen.getByTestId('clear-chat-button');
    await waitFor(() => expect(clear).toBeEnabled());
    fireEvent.click(clear);
    await act(async () => {
      fireEvent.click(within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Clear chat' }));
    });
    expect(clearChat).toHaveBeenCalledWith('sess-1');
    expect(deleteButtons()).toHaveLength(2);
    for (const button of deleteButtons()) expect(button).toBeDisabled();

    // The clear fails, so the conversation stays: the action comes back with it.
    await act(async () => { pending.reject({ status: 500 }); });
    await waitFor(() => {
      for (const button of deleteButtons()) expect(button).toBeEnabled();
    });
    expect(rowTexts()).toEqual(FOUR_TEXTS);
    expect(deleteMessage).not.toHaveBeenCalled();
  });

  // ---- 4-5: the confirmation ------------------------------------------------------------------

  it('cancelling the confirmation deletes nothing', async () => {
    mount();
    await loaded();
    openDelete(rowWith('Make the title punchier'));
    fireEvent.click(within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    await settle();
    expect(deleteMessage).not.toHaveBeenCalled();
    expect(rowTexts()).toEqual(FOUR_TEXTS);
    expect(deleteButtons()).toHaveLength(2);
  });

  it('the confirmation says the deck is not rolled back', async () => {
    mount();
    await loaded();
    openDelete(rowWith('Make the title punchier'));
    const dialog = screen.getByTestId('confirm-dialog');
    expect(within(dialog).getByText(DELETE_MESSAGE_DIALOG_TITLE)).toBeInTheDocument();
    expect(within(dialog).getByText(DELETE_MESSAGE_DIALOG_MESSAGE)).toBeInTheDocument();
    expect(within(dialog).getByText(/it is not rolled back/)).toBeInTheDocument();
    expect(within(dialog).queryByText(CLEAR_CHAT_DIALOG_MESSAGE)).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(deleteMessage).not.toHaveBeenCalled(); // opening is not deleting
  });

  // ---- 6-10: confirming ------------------------------------------------------------------------

  it('confirming deletes that message and its replies for this session only, without refetching the deck', async () => {
    mount();
    await loaded();
    await deleteRow(rowWith('Make the title punchier'));
    await waitFor(() => expect(rowTexts()).toEqual(['Build a deck', 'Built 3 slides.']));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    expect(deleteMessage).toHaveBeenCalledTimes(1);
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 3);
    await settle();
    // No refetch: the slides, the Spec and the session are deliberately left as they are (D9, D13).
    expect(getSlides).not.toHaveBeenCalled();
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    expect(getSession).toHaveBeenCalledTimes(1);
    expect(refreshConfig).not.toHaveBeenCalled();
    expect(listMessages).not.toHaveBeenCalled();
    expect(sendChatMessage).not.toHaveBeenCalled();
    expect(errorShown()).toBe(false);
    // The user carries on: the input works and the remaining message still offers delete.
    expect(sendButton()).toBeEnabled();
    expect(deleteButtons()).toHaveLength(1);
    expect(deleteButtonIn(rowWith('Build a deck'))).toBeEnabled();
  });

  it('deleting the first message removes its turn and keeps the rest', async () => {
    mount();
    await loaded();
    await deleteRow(rowWith('Build a deck'));
    await waitFor(() => expect(rowTexts()).toEqual(['Make the title punchier', 'Edited slide 1.']));
    expect(deleteMessage).toHaveBeenCalledTimes(1);
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 1);
    expect(deleteButtons()).toHaveLength(1);
    expect(deleteButtonIn(rowWith('Make the title punchier'))).toBeEnabled();
  });

  it("deleting a turn clears the slide feedback that turn left under the input", async () => {
    const feedback = 'The deck could not be synced.';
    listMessages.mockResolvedValue(rowsRead([...FOUR, U(5, SENT)]));
    mount();
    await loaded();
    await send();
    await emit({ type: 'complete', metadata: { sync_error: feedback } });
    expect(await screen.findByText(feedback)).toBeInTheDocument(); // control: the turn left feedback
    await loaded(3);

    await deleteRow(rowWith(SENT));
    await waitFor(() => expect(rowTexts()).toEqual(FOUR_TEXTS));
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 5);
    expect(screen.queryByText(feedback)).toBeNull();
  });

  it.each([
    { label: '409', err: { status: 409, message: 'server busy detail' }, shown: DELETE_MESSAGE_BUSY },
    { label: '403', err: { status: 403, message: 'server forbidden detail' }, shown: DELETE_MESSAGE_FORBIDDEN },
    { label: '404', err: { status: 404, message: 'server not found detail' }, shown: DELETE_MESSAGE_GONE },
    { label: '500', err: { status: 500, message: 'server error detail' }, shown: DELETE_MESSAGE_FAILED },
    { label: 'a network error', err: new TypeError('network error detail'), shown: DELETE_MESSAGE_FAILED },
  ])('a failed delete ($label) keeps the conversation and says why', async ({ err, shown }) => {
    deleteMessage.mockRejectedValueOnce(err);
    mount();
    await loaded();
    await deleteRow(rowWith('Make the title punchier'));
    expect(await screen.findByText(shown)).toBeInTheDocument();
    expect(screen.queryByText(err.message)).toBeNull(); // mapped by status, never the server's detail
    expect(rowTexts()).toEqual(FOUR_TEXTS);
    await waitFor(() => {
      for (const button of deleteButtons()) expect(button).toBeEnabled();
    });
    expect(deleteButtons()).toHaveLength(2);
    expect(sendButton()).toBeEnabled();

    // A retry works and clears the message.
    await deleteRow(rowWith('Make the title punchier'));
    await waitFor(() => expect(rowTexts()).toEqual(['Build a deck', 'Built 3 slides.']));
    expect(deleteMessage).toHaveBeenCalledTimes(2);
    expect(deleteMessage).toHaveBeenNthCalledWith(2, 'sess-1', 3);
    expect(screen.queryByText(shown)).toBeNull();
  });

  it('the input is disabled and nothing can double-submit while a delete runs', async () => {
    const pending = deferred<unknown>();
    deleteMessage.mockReturnValueOnce(pending.promise);
    const ref = createRef<ChatPanelHandle>();
    mount({ hasDeckSpec: true }, ref);
    await loaded();
    expect(sendButton()).toBeEnabled(); // control
    expect(screen.getByTestId('clear-chat-button')).toBeEnabled(); // control
    await deleteRow(rowWith('Make the title punchier'));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();

    expect(sendButton()).toBeDisabled();
    expect(screen.getByTestId('clear-chat-button')).toBeDisabled();
    expect(deleteButtonIn(rowWith('Build a deck'))).toBeDisabled();
    expect(deleteButtonIn(rowWith('Make the title punchier'))).toBeDisabled();
    fireEvent.click(rowWith('Build a deck').querySelector('[data-testid="delete-message-button"]') as HTMLElement);
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    // A send from elsewhere in the app (the imperative handle) is refused while the delete runs.
    expect(ref.current).not.toBeNull();
    act(() => { ref.current?.sendMessage(SENT); });
    await settle();
    expect(sendChatMessage).not.toHaveBeenCalled();
    expect(deleteMessage).toHaveBeenCalledTimes(1);
    expect(rowTexts()).toEqual(FOUR_TEXTS);

    await act(async () => { pending.resolve({ status: 'deleted' }); });
    await waitFor(() => expect(rowTexts()).toEqual(['Build a deck', 'Built 3 slides.']));
    expect(sendButton()).toBeEnabled();
    expect(deleteButtonIn(rowWith('Build a deck'))).toBeEnabled();
  });

  it.each([
    { outcome: 'succeeds', land: (d: Deferred<unknown>) => d.resolve({ status: 'deleted' }) },
    { outcome: 'fails', land: (d: Deferred<unknown>) => d.reject({ status: 500 }) },
  ])('a delete that lands after the session changed leaves the new session alone ($outcome)', async ({ land }) => {
    // The new session's rows carry the same ids on purpose, so a late result applied to it would show.
    const sameIds = [U(3, 'Another deck'), A(4, 'Another reply')];
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: sameIds, my_permission: 'CAN_MANAGE' }
      : EDITOR_SESSION));
    const pending = deferred<unknown>();
    deleteMessage.mockReturnValueOnce(pending.promise);
    const view = mount();
    await loaded();
    await deleteRow(rowWith('Make the title punchier'));
    expect(sendButton()).toBeDisabled();

    currentSessionId = 'sess-2';
    view.rerender(panel({}));
    await waitFor(() => expect(rowTexts()).toEqual(['Another deck', 'Another reply']));
    // The new session is usable before the old session's delete settles.
    await loaded(1);
    expect(deleteButtonIn(rowWith('Another deck'))).toBeEnabled();
    expect(sendButton()).toBeEnabled();

    await act(async () => { land(pending); });
    await settle();
    expect(rowTexts()).toEqual(['Another deck', 'Another reply']);
    expect(screen.queryByText(DELETE_MESSAGE_FAILED)).toBeNull();
    expect(errorShown()).toBe(false);
    expect(deleteButtonIn(rowWith('Another deck'))).toBeEnabled();
    expect(sendButton()).toBeEnabled();
    expect(deleteMessage).toHaveBeenCalledTimes(1);
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 3);
  });

  it("a late delete for the previous session does not unlock the new session's own running delete", async () => {
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: OTHER, my_permission: 'CAN_MANAGE' }
      : EDITOR_SESSION));
    const pendingA = deferred<unknown>();
    const pendingB = deferred<unknown>();
    deleteMessage.mockReturnValueOnce(pendingA.promise).mockReturnValueOnce(pendingB.promise);
    const view = mount();
    await loaded();
    await deleteRow(rowWith('Make the title punchier'));

    currentSessionId = 'sess-2';
    view.rerender(panel({}));
    await loaded(1);
    await deleteRow(rowWith('Another deck'));
    expect(sendButton()).toBeDisabled();
    expect(deleteButtonIn(rowWith('Another deck'))).toBeDisabled();

    await act(async () => { pendingA.resolve({ status: 'deleted' }); });
    await settle();
    // B's delete is still running: its input and its action stay locked.
    expect(sendButton()).toBeDisabled();
    expect(deleteButtonIn(rowWith('Another deck'))).toBeDisabled();
    expect(rowTexts()).toEqual(['Another deck', 'Another reply']);

    await act(async () => { pendingB.resolve({ status: 'deleted' }); });
    await waitFor(() => expect(rows()).toHaveLength(0));
    expect(sendButton()).toBeEnabled();
    expect(deleteMessage.mock.calls).toEqual([['sess-1', 3], ['sess-2', 21]]);
  });

  it('switching session closes an open delete confirmation', async () => {
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: OTHER, my_permission: 'CAN_MANAGE' }
      : EDITOR_SESSION));
    const view = mount();
    await loaded();
    openDelete(rowWith('Make the title punchier'));

    currentSessionId = 'sess-2';
    view.rerender(panel({}));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    await loaded(1);
    await settle();
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    expect(deleteMessage).not.toHaveBeenCalled();
    expect(rowTexts()).toEqual(['Another deck', 'Another reply']);
  });

  // ---- 11-17: ids for messages sent in this panel ----------------------------------------------

  it('after an SSE-shaped turn, the new message gets its id and can be deleted without a reload', async () => {
    const read = deferred<unknown>();
    listMessages.mockReturnValueOnce(read.promise);
    mount();
    await loaded();
    await send();
    expect(listMessages).not.toHaveBeenCalled(); // the read runs at turn end, never on the click (C15)
    expect(deleteButtonIn(rowWith(SENT))).toBeNull(); // shown before it is stored: no id yet

    await emit({ type: 'assistant', content: 'Editing slide 3.' });
    // SSE also shows progress lines that are never stored; the read must not drop them.
    await emit({ type: 'assistant', content: 'Slide 3 reviewed: shorter now.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(1));
    expect(listMessages).toHaveBeenCalledWith('sess-1', 200);
    expect(deleteButtonIn(rowWith(SENT))).toBeNull(); // still no id until the read lands

    await act(async () => { read.resolve(rowsRead([...FOUR, U(5, SENT), A(6, 'Editing slide 3.')])); });
    await loaded(3);
    expect(deleteButtonIn(rowWith(SENT))).toBeEnabled();
    expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.', 'Slide 3 reviewed: shorter now.']);

    await deleteRow(rowWith(SENT));
    await waitFor(() => expect(rowTexts()).toEqual(FOUR_TEXTS));
    expect(deleteMessage).toHaveBeenCalledTimes(1);
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 5);
    expect(getSession).toHaveBeenCalledTimes(1); // no reload
  });

  it('after a polling-shaped turn (assistant events carry message_id, the user row is not echoed), the new message gets its id', async () => {
    const read = deferred<unknown>();
    listMessages.mockReturnValueOnce(read.promise);
    mount();
    await loaded();
    await send();
    expect(listMessages).not.toHaveBeenCalled();

    await emit({ type: 'assistant', content: 'Editing slide 3.', message_id: 6 });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(1));
    expect(listMessages).toHaveBeenCalledWith('sess-1', 200);

    await act(async () => { read.resolve(rowsRead([...FOUR, U(5, SENT), A(6, 'Editing slide 3.')])); });
    await loaded(3);
    expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.']);
    expect(deleteButtonIn(rowWith('Editing slide 3.'))).toBeNull(); // replies never offer it

    await deleteRow(rowWith(SENT));
    await waitFor(() => expect(rowTexts()).toEqual(FOUR_TEXTS));
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 5);
    expect(getSession).toHaveBeenCalledTimes(1);
  });

  it.each([
    { label: 'an error event', end: () => emit({ type: 'error', error: 'The turn failed' }) },
    { label: 'the transport failing (onError)', end: () => failTransport(new Error('The turn failed')) },
  ])('a turn that ends in an error still gets its id ($label)', async ({ end }) => {
    // A failed turn is exactly what a user wants to delete, and it sends no `complete`.
    listMessages.mockResolvedValue(rowsRead([...FOUR, U(5, SENT)]));
    mount();
    await loaded();
    await send();
    await end();
    expect(await screen.findByText('The turn failed')).toBeInTheDocument();
    await waitFor(() => expect(listMessages).toHaveBeenCalledWith('sess-1', 200));
    await loaded(3);
    expect(deleteButtonIn(rowWith(SENT))).toBeEnabled();
    expect(screen.getByText('The turn failed')).toBeInTheDocument(); // the read does not hide the failure

    await deleteRow(rowWith(SENT));
    await waitFor(() => expect(rowTexts()).toEqual(FOUR_TEXTS));
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 5);
  });

  it.each([
    { label: 'the read is refused', arrange: () => listMessages.mockRejectedValue({ status: 403, message: 'Failed to load the conversation' }) },
    { label: 'the body has no messages', arrange: () => listMessages.mockResolvedValue({}) },
    { label: 'messages is null', arrange: () => listMessages.mockResolvedValue({ messages: null }) },
    // setupMocks answers any URL with `limit=` with the sessions list (C19).
    { label: 'the body is the sessions list', arrange: () => listMessages.mockResolvedValue({ sessions: [{ session_id: 'sess-1' }] }) },
    // setupMocks' canned /messages rows carry no ids (Context 18).
    {
      label: 'the rows carry no ids',
      arrange: () => listMessages.mockResolvedValue({
        messages: [
          { role: 'user', content: SENT, created_at: 't' },
          { role: 'assistant', content: 'Editing slide 3.', created_at: 't' },
        ],
      }),
    },
  ])('a failed or malformed id read changes nothing ($label)', async ({ arrange }) => {
    arrange();
    mount();
    await loaded();
    await send();
    await emit({ type: 'assistant', content: 'Editing slide 3.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledWith('sess-1', 200));
    await settle();
    expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.']);
    expect(deleteButtons()).toHaveLength(2);
    expect(deleteButtonIn(rowWith(SENT))).toBeNull();
    expect(errorShown()).toBe(false);
    expect(screen.queryByText('Failed to load the conversation')).toBeNull();
    expect(sendButton()).toBeEnabled();
  });

  it('the id read never rewrites the conversation', async () => {
    // SSE stores a prompt with images with the image context injected, so its row's text differs.
    listMessages.mockResolvedValue(rowsRead([
      ...FOUR,
      U(5, `${SENT}\n\n[Image context: chart.png, a bar chart of revenue]`),
      A(6, 'Editing slide 3 (as stored).'),
    ]));
    mount();
    await loaded();
    await send();
    await emit({ type: 'assistant', content: 'Editing slide 3.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledWith('sess-1', 200));
    await settle();
    expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.']);
    expect(screen.queryByText(/Image context/)).toBeNull();
    expect(screen.queryByText('Editing slide 3 (as stored).')).toBeNull();
    expect(deleteButtons()).toHaveLength(2);
    expect(deleteButtonIn(rowWith(SENT))).toBeNull();
  });

  it('an id read that lands after a session switch is dropped', async () => {
    // The new session shows a message the panel holds without an id (as setupMocks' rows have none),
    // with the same text, so a late read for the old session would pin the old session's row on it.
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: [{ role: 'user', content: SENT, created_at: 't' }, A(22, 'Another reply')], my_permission: 'CAN_MANAGE' }
      : EDITOR_SESSION));
    const read = deferred<unknown>();
    listMessages.mockReturnValueOnce(read.promise);
    const view = mount();
    await loaded();
    await send();
    await emit({ type: 'assistant', content: 'Editing slide 3.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledWith('sess-1', 200));

    currentSessionId = 'sess-2';
    view.rerender(panel({}));
    await waitFor(() => expect(rowTexts()).toEqual([SENT, 'Another reply']));
    expect(deleteButtons()).toHaveLength(0); // control: nothing in the new session has an id yet

    await act(async () => { read.resolve(rowsRead([...FOUR, U(5, SENT), A(6, 'Editing slide 3.')])); });
    await settle();
    expect(rowTexts()).toEqual([SENT, 'Another reply']);
    expect(deleteButtons()).toHaveLength(0);
    expect(listMessages).toHaveBeenCalledTimes(1);
    expect(deleteMessage).not.toHaveBeenCalled();
  });

  it('an id read that lands after the next send started is dropped', async () => {
    // Review F1: the mocked input always sends the same text, so this is the identical-prompt case
    // ("yes", "try again"). A stale read would give turn 1's row to turn 2's message, and a delete
    // of turn 2 would then remove turn 1 on the server.
    const firstRead = deferred<unknown>();
    const secondRead = deferred<unknown>();
    listMessages.mockReturnValueOnce(firstRead.promise).mockReturnValueOnce(secondRead.promise);
    mount();
    await loaded();

    // Turn 1 ends; its id read is still in flight.
    await send();
    await emit({ type: 'assistant', content: 'Editing slide 3.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    // Turn 2 starts with the same text before turn 1's read lands.
    await send();
    expect(sendChatMessage).toHaveBeenCalledTimes(2);
    expect(rowsWith(SENT)).toHaveLength(2);

    await act(async () => { firstRead.resolve(rowsRead([...FOUR, U(5, SENT), A(6, 'Editing slide 3.')])); });
    await settle();
    expect(rowsWith(SENT).map(deleteButtonIn)).toEqual([null, null]);
    expect(deleteButtons()).toHaveLength(2);

    // Turn 2 ends; its read pairs both.
    await emit({ type: 'assistant', content: 'Shortened slide 3 again.' });
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(2));
    expect(listMessages).toHaveBeenNthCalledWith(2, 'sess-1', 200);
    await act(async () => {
      secondRead.resolve(rowsRead([
        ...FOUR, U(5, SENT), A(6, 'Editing slide 3.'), U(8, SENT), A(9, 'Shortened slide 3 again.'),
      ]));
    });
    await loaded(4);
    expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.', SENT, 'Shortened slide 3 again.']);

    // The newest message is turn 2's row (8), and the older one is turn 1's (5).
    await deleteRow(rowsWith(SENT)[1]);
    await waitFor(() => expect(rowTexts()).toEqual([...FOUR_TEXTS, SENT, 'Editing slide 3.']));
    expect(deleteMessage).toHaveBeenLastCalledWith('sess-1', 8);
    await deleteRow(rowWith(SENT));
    await waitFor(() => expect(rowTexts()).toEqual(FOUR_TEXTS));
    expect(deleteMessage).toHaveBeenLastCalledWith('sess-1', 5);
    expect(deleteMessage).toHaveBeenCalledTimes(2);
  });

  it('a refused duplicate send never takes the stored send\'s id: neither copy offers delete (W1)', async () => {
    // A double-click on a finding's Apply: AppLayout sends the same fixed text twice through the
    // imperative handle. Send 1 is stored as row 10; send 2 is refused (409) before anything is stored.
    // Send 2's onError read sees row 10 and is the newest read, so it lands; send 1's read is dropped
    // (its seq is stale). The panel cannot tell which copy row 10 is, so neither may offer delete.
    const APPLY = 'Please apply this review suggestion for slide 2: Shorten the title';
    const turns: Turn[] = [];
    sendChatMessage.mockImplementation((_s, _m, _c, onEvent, onError) => {
      turns.push({ onEvent, onError });
      return () => {};
    });
    listMessages.mockResolvedValue(rowsRead([...FOUR, U(10, APPLY), A(11, 'Applied.')]));
    const ref = createRef<ChatPanelHandle>();
    mount({}, ref);
    await loaded();

    act(() => { ref.current?.sendMessage(APPLY); });
    await settle();
    act(() => { ref.current?.sendMessage(APPLY); });
    await settle();
    expect(sendChatMessage).toHaveBeenCalledTimes(2);
    expect(rowsWith(APPLY)).toHaveLength(2);

    // Send 2 is refused: its read runs and lands (control: it is the read the old pairing misused).
    await act(async () => { turns[1].onError(new Error('Session is already processing a request')); });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(1));
    await settle();
    // Send 1 completes; its own read is dropped by the send-seq guard.
    await act(async () => { turns[0].onEvent({ type: 'assistant', content: 'Applied.' }); });
    await act(async () => { turns[0].onEvent({ type: 'complete' }); });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(2));
    await settle();

    expect(rowTexts()).toEqual([...FOUR_TEXTS, APPLY, APPLY, 'Applied.']);
    expect(rowsWith(APPLY).map(deleteButtonIn)).toEqual([null, null]);
    // The loaded messages still offer delete, so the read did land and nothing else changed.
    expect(deleteButtons()).toHaveLength(2);
    expect(deleteButtonIn(rowWith('Build a deck'))).toBeEnabled();
    expect(deleteButtonIn(rowWith('Make the title punchier'))).toBeEnabled();
    expect(deleteMessage).not.toHaveBeenCalled();
  });

  it('an id read that lands while a delete runs is kept when the delete lands', async () => {
    // The delete must apply to the messages as they are when it lands, not as they were when it was
    // confirmed: otherwise the ids the read added meanwhile are lost.
    const read = deferred<unknown>();
    listMessages.mockReturnValueOnce(read.promise);
    const pending = deferred<unknown>();
    deleteMessage.mockReturnValueOnce(pending.promise);
    mount();
    await loaded();
    await send();
    await emit({ type: 'complete' });
    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(1));

    await deleteRow(rowWith('Build a deck'));
    await act(async () => { read.resolve(rowsRead([...FOUR, U(5, SENT)])); });
    await loaded(3); // control: the read landed while the delete runs
    await act(async () => { pending.resolve({ status: 'deleted' }); });
    await waitFor(() => expect(rowTexts()).toEqual(['Make the title punchier', 'Edited slide 1.', SENT]));
    expect(deleteButtons()).toHaveLength(2);
    expect(deleteButtonIn(rowWith(SENT))).toBeEnabled();
    expect(deleteMessage).toHaveBeenCalledWith('sess-1', 1);
  });
});
