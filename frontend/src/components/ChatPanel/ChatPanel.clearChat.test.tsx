/**
 * #323 Clear chat: the chat-panel header action that deletes THIS session's conversation and keeps
 * the deck, its Spec and save points (plan Task 5; Decisions D4, D7, D8; review F2, F12, F19, F23).
 *
 * Mock scaffold copied from ChatPanel.tourRefresh.test.tsx, plus the conversation API, a list that
 * renders one <li> per message, and a one-button ChatInput. The permission helper is real.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createRef, type Ref } from 'react';
import { render, screen, waitFor, act, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { Message } from '../../types/message';

const getSession = vi.fn();
const getSlides = vi.fn();
const sendChatMessage = vi.fn<(...args: unknown[]) => () => void>();
const clearChat = vi.fn();
const refreshConfig = vi.fn();
// One function for the whole file, not a fresh vi.fn() per render: ChatPanel's session-change
// cleanup effect lists setIsGenerating as a dependency, so a new identity on every render re-runs
// that cleanup (setIsLoading(false)) and a turn could never be seen in flight.
const setIsGenerating = vi.fn();
let currentSessionId = 'sess-1';
let currentPersisted = true;

vi.mock('../../services/api', () => ({
  api: {
    getSession: (...a: unknown[]) => getSession(...a),
    getSlides: (...a: unknown[]) => getSlides(...a),
    sendChatMessage: (...a: unknown[]) => sendChatMessage(...a),
  },
}));
vi.mock('../../api/conversation', () => ({
  conversationApi: { clearChat: (...a: unknown[]) => clearChat(...a) },
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
vi.mock('./MessageList', () => ({
  MessageList: ({ messages }: { messages: { content: string }[] }) => (
    <ul data-testid="message-list">{messages.map((m, i) => <li key={i}>{m.content}</li>)}</ul>
  ),
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
  CLEAR_CHAT_LABEL,
  CLEAR_CHAT_DIALOG_TITLE,
  CLEAR_CHAT_DIALOG_MESSAGE,
  CLEAR_CHAT_TOOLTIP,
  CLEAR_CHAT_BUSY,
  CLEAR_CHAT_FORBIDDEN,
  CLEAR_CHAT_FAILED,
} from './clearChatCopy';

const msg = (content: string) => ({ role: 'assistant', content, created_at: 't', metadata: null });
const TWO = [msg('message A'), msg('message B')];
const CLEARED = { status: 'cleared', session_id: 'sess-1', deleted_messages: 2, preserved_message_id: 1 };

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

function panel(props: PanelProps, ref?: Ref<ChatPanelHandle>) {
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

function mount(props: PanelProps = { hasDeckSpec: true }, ref?: Ref<ChatPanelHandle>) {
  return render(panel(props, ref));
}

/** Let pending promise callbacks and effects run, so a "nothing happened" check is meaningful. */
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 30)); });
const listItems = () => within(screen.getByTestId('message-list')).queryAllByRole('listitem');
const clearButton = () => screen.getByTestId('clear-chat-button');
const clearButtonCount = () => screen.queryAllByTestId('clear-chat-button').length;
/** The header button and the dialog's confirm share the name "Clear chat" (F19): scope to the dialog. */
const confirmInDialog = () =>
  within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Clear chat' });

async function enabledClearButton() {
  await waitFor(() => expect(clearButton()).toBeEnabled());
  return clearButton();
}

async function confirmClear() {
  fireEvent.click(await enabledClearButton());
  await act(async () => { fireEvent.click(confirmInDialog()); });
}

describe('ChatPanel Clear chat (#323)', () => {
  beforeEach(() => {
    getSession.mockReset();
    getSlides.mockReset();
    sendChatMessage.mockReset();
    clearChat.mockReset();
    refreshConfig.mockReset();
    setIsGenerating.mockReset();
    onSlidesGenerated.mockReset();
    ensureGraphCapableRoot.mockReset();
    currentSessionId = 'sess-1';
    currentPersisted = true;
    getSession.mockResolvedValue({ messages: TWO, my_permission: 'CAN_MANAGE' });
    getSlides.mockResolvedValue({ slide_deck: null });
    sendChatMessage.mockImplementation(() => () => {});
    clearChat.mockResolvedValue(CLEARED);
    ensureGraphCapableRoot.mockResolvedValue(true);
  });

  it('uses the agreed copy (D8, F23)', () => {
    expect(CLEAR_CHAT_LABEL).toBe('Clear chat');
    expect(CLEAR_CHAT_DIALOG_TITLE).toBe('Clear chat?');
    expect(CLEAR_CHAT_DIALOG_MESSAGE).toBe(
      'This deletes your conversation on this deck. Your slides, the Spec and save points stay as they '
      + "are, and the assistant carries on from the Spec and the current slides. This can't be undone.",
    );
    expect(CLEAR_CHAT_TOOLTIP).toBe('Delete this conversation and keep the deck, its Spec and save points');
    expect(CLEAR_CHAT_BUSY).toBe(
      'Something is still running on this deck. Wait for it to finish, then clear the chat.',
    );
    expect(CLEAR_CHAT_FORBIDDEN).toBe('Only editors can clear the chat, and only their own conversation.');
    expect(CLEAR_CHAT_FAILED).toBe(
      "Couldn't clear the chat. Reload the page to see its current state, then try again.",
    );
  });

  it.each(['CAN_EDIT', 'CAN_MANAGE'])('offers Clear chat to an editor (%s) on a deck with a Spec', async (permission) => {
    getSession.mockResolvedValue({ messages: TWO, my_permission: permission });
    mount({ hasDeckSpec: true });
    const button = await enabledClearButton();
    expect(button).toHaveTextContent('Clear chat');
    expect(button).toHaveAttribute('title', CLEAR_CHAT_TOOLTIP);
    expect(getSession).toHaveBeenCalledWith('sess-1');
  });

  // Same setup as the test above except for the one condition named; each must hide the button.
  it.each([
    { label: 'to a viewer (CAN_VIEW)', permission: 'CAN_VIEW', hasDeckSpec: true, persisted: true },
    { label: 'without a permission', permission: undefined, hasDeckSpec: true, persisted: true },
    { label: 'without a Spec (hasDeckSpec false)', permission: 'CAN_MANAGE', hasDeckSpec: false, persisted: true },
    { label: 'without a Spec (hasDeckSpec omitted)', permission: 'CAN_MANAGE', hasDeckSpec: undefined, persisted: true },
    { label: 'before the session is persisted', permission: 'CAN_MANAGE', hasDeckSpec: true, persisted: false },
  ])('does not offer Clear chat $label', async ({ permission, hasDeckSpec, persisted }) => {
    currentPersisted = persisted;
    getSession.mockResolvedValue({ messages: TWO, my_permission: permission });
    mount(hasDeckSpec === undefined ? {} : { hasDeckSpec });
    await screen.findByText('message B'); // the load, and the my_permission it carries, has landed
    await settle();
    expect(clearButtonCount()).toBe(0);
  });

  it('disables Clear chat when there is nothing to clear', async () => {
    getSession.mockResolvedValue({ messages: [], my_permission: 'CAN_MANAGE' });
    mount();
    await screen.findByTestId('clear-chat-button');
    await settle();
    expect(listItems()).toHaveLength(0);
    expect(clearButton()).toBeDisabled();
    fireEvent.click(clearButton());
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
  });

  it('disables Clear chat while a turn is in flight', async () => {
    mount();
    await screen.findByText('message B');
    await enabledClearButton(); // control: enabled before the turn
    fireEvent.click(screen.getByTestId('mock-send'));
    await waitFor(() => expect(sendChatMessage).toHaveBeenCalledTimes(1));
    expect(clearButton()).toBeDisabled();
  });

  it.each([
    { label: 'read-only', props: { disabled: true } },
    {
      label: 'previewing a save point',
      props: { previewMessages: [{ role: 'assistant' as const, content: 'saved line', timestamp: 't' }] },
    },
  ])('disables Clear chat in a read-only or preview panel ($label)', async ({ props }) => {
    const view = mount({ hasDeckSpec: true, ...props });
    await waitFor(() => expect(getSession).toHaveBeenCalledWith('sess-1'));
    await screen.findByTestId('clear-chat-button');
    await settle();
    expect(clearButton()).toBeDisabled();
    // Control: the same panel, with the live conversation loaded, is enabled once that prop goes.
    view.rerender(panel({ hasDeckSpec: true }));
    await enabledClearButton();
  });

  it('cancelling the confirmation clears nothing', async () => {
    mount();
    await screen.findByText('message B');
    fireEvent.click(await enabledClearButton());
    const dialog = screen.getByTestId('confirm-dialog');
    expect(within(dialog).getByText(CLEAR_CHAT_DIALOG_TITLE)).toBeInTheDocument();
    expect(within(dialog).getByText(CLEAR_CHAT_DIALOG_MESSAGE)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Clear chat' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    await settle();
    expect(clearChat).not.toHaveBeenCalled();
    expect(listItems()).toHaveLength(2);
  });

  it('confirming clears the panel through the API for this session only', async () => {
    mount();
    await screen.findByText('message B');
    await confirmClear();
    await waitFor(() => expect(listItems()).toHaveLength(0));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    expect(clearChat).toHaveBeenCalledTimes(1);
    expect(clearChat).toHaveBeenCalledWith('sess-1');
    await settle();
    // No refetch: the deck, the slides and the Spec are deliberately left as they are.
    expect(getSession).toHaveBeenCalledTimes(1);
    expect(getSlides).not.toHaveBeenCalled();
    expect(onSlidesGenerated).not.toHaveBeenCalled();
    expect(refreshConfig).not.toHaveBeenCalled();
    expect(sendChatMessage).not.toHaveBeenCalled();
    // The user carries on: the input is usable; the action stays offered but has nothing left to clear.
    expect(screen.getByTestId('mock-send')).toBeEnabled();
    expect(clearButton()).toBeDisabled();
  });

  it('a busy session keeps the conversation and says why', async () => {
    clearChat.mockRejectedValueOnce({ status: 409, message: 'server busy detail' });
    mount();
    await screen.findByText('message B');
    await confirmClear();
    expect(await screen.findByText(CLEAR_CHAT_BUSY)).toBeInTheDocument();
    expect(screen.queryByText('server busy detail')).toBeNull(); // mapped by status, not the detail
    expect(listItems()).toHaveLength(2);
    await enabledClearButton();
    expect(screen.getByTestId('mock-send')).toBeEnabled();
  });

  it('a refused clear (403) keeps the conversation and says who may clear', async () => {
    clearChat.mockRejectedValueOnce({ status: 403, message: 'server forbidden detail' });
    mount();
    await screen.findByText('message B');
    await confirmClear();
    expect(await screen.findByText(CLEAR_CHAT_FORBIDDEN)).toBeInTheDocument();
    expect(screen.queryByText('server forbidden detail')).toBeNull();
    expect(listItems()).toHaveLength(2);
  });

  it.each([
    { label: '500', err: { status: 500, message: 'server error detail' } },
    { label: '404', err: { status: 404, message: 'server not found detail' } },
    { label: 'network error', err: new TypeError('network error detail') },
  ])('any other failure ($label) keeps the conversation and a retry works', async ({ err }) => {
    clearChat.mockRejectedValueOnce(err);
    mount();
    await screen.findByText('message B');
    await confirmClear();
    expect(await screen.findByText(CLEAR_CHAT_FAILED)).toBeInTheDocument();
    expect(screen.queryByText(err.message)).toBeNull();
    expect(listItems()).toHaveLength(2);
    await confirmClear();
    await waitFor(() => expect(listItems()).toHaveLength(0));
    expect(clearChat).toHaveBeenCalledTimes(2);
    expect(clearChat).toHaveBeenNthCalledWith(2, 'sess-1');
    expect(screen.queryByText(CLEAR_CHAT_FAILED)).toBeNull();
  });

  it('input is disabled and the clear cannot double-submit while it runs', async () => {
    const pending = deferred<typeof CLEARED>();
    clearChat.mockReturnValueOnce(pending.promise);
    const ref = createRef<ChatPanelHandle>();
    mount({ hasDeckSpec: true }, ref);
    await screen.findByText('message B');
    expect(screen.getByTestId('mock-send')).toBeEnabled(); // control
    await confirmClear();
    expect(screen.getByTestId('mock-send')).toBeDisabled();
    expect(clearButton()).toBeDisabled();
    fireEvent.click(clearButton());
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    // A send from elsewhere in the app (the imperative handle) is refused while the clear runs.
    expect(ref.current).not.toBeNull();
    act(() => { ref.current?.sendMessage('Make slide 3 shorter'); });
    await settle();
    expect(sendChatMessage).not.toHaveBeenCalled();
    expect(clearChat).toHaveBeenCalledTimes(1);
    expect(listItems()).toHaveLength(2);
    await act(async () => { pending.resolve(CLEARED); });
    await waitFor(() => expect(listItems()).toHaveLength(0));
    expect(screen.getByTestId('mock-send')).toBeEnabled();
  });

  it.each([
    { outcome: 'succeeds', land: (d: Deferred<typeof CLEARED>) => d.resolve(CLEARED) },
    { outcome: 'fails', land: (d: Deferred<typeof CLEARED>) => d.reject({ status: 500 }) },
  ])('a clear that lands after the session changed leaves the new session alone ($outcome)', async ({ land }) => {
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: [msg('message C')], my_permission: 'CAN_MANAGE' }
      : { messages: TWO, my_permission: 'CAN_MANAGE' }));
    const pending = deferred<typeof CLEARED>();
    clearChat.mockReturnValueOnce(pending.promise);
    const view = mount();
    await screen.findByText('message B');
    await confirmClear();
    expect(screen.getByTestId('mock-send')).toBeDisabled();

    currentSessionId = 'sess-2';
    view.rerender(panel({ hasDeckSpec: true }));
    await screen.findByText('message C');
    // F12: the new session is usable before the old session's clear settles.
    expect(screen.getByTestId('mock-send')).toBeEnabled();

    await act(async () => { land(pending); });
    await settle();
    expect(listItems()).toHaveLength(1);
    expect(screen.getByText('message C')).toBeInTheDocument();
    expect(screen.queryByText(CLEAR_CHAT_FAILED)).toBeNull();
    expect(clearChat).toHaveBeenCalledTimes(1);
    expect(clearChat).toHaveBeenCalledWith('sess-1');
    expect(screen.getByTestId('mock-send')).toBeEnabled();
  });

  it("a late clear for the previous session does not unlock the new session's own running clear", async () => {
    // Whole-branch review W6: A's clear is in flight, the user switches to B and
    // starts a clear there; A's response landing must not flip B's isClearing off.
    getSession.mockImplementation(async (id: string) => (id === 'sess-2'
      ? { messages: [msg('message C')], my_permission: 'CAN_MANAGE' }
      : { messages: TWO, my_permission: 'CAN_MANAGE' }));
    const pendingA = deferred<typeof CLEARED>();
    const pendingB = deferred<typeof CLEARED>();
    clearChat.mockReturnValueOnce(pendingA.promise).mockReturnValueOnce(pendingB.promise);
    const view = mount();
    await screen.findByText('message B');
    await confirmClear();

    currentSessionId = 'sess-2';
    view.rerender(panel({ hasDeckSpec: true }));
    await screen.findByText('message C');
    await confirmClear();
    expect(screen.getByTestId('mock-send')).toBeDisabled();
    expect(clearButton()).toBeDisabled();

    await act(async () => { pendingA.resolve(CLEARED); });
    await settle();
    // B's clear is still running: its input and button stay locked.
    expect(screen.getByTestId('mock-send')).toBeDisabled();
    expect(clearButton()).toBeDisabled();
    expect(screen.getByText('message C')).toBeInTheDocument();

    await act(async () => { pendingB.resolve({ ...CLEARED, session_id: 'sess-2' }); });
    await waitFor(() => expect(listItems()).toHaveLength(0));
    expect(screen.getByTestId('mock-send')).toBeEnabled();
    expect(clearChat.mock.calls).toEqual([['sess-1'], ['sess-2']]);
  });

  it('a deck built in this panel offers Clear chat without a reload', async () => {
    // A new deck: a browser-local id the backend does not know yet.
    currentSessionId = 'local-1';
    currentPersisted = false;
    getSession.mockRejectedValueOnce({ status: 404, message: 'Session not found' });
    const view = mount({ hasDeckSpec: false });
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    await settle();
    expect(clearButtonCount()).toBe(0);

    // ensureGraphCapableRoot persisted the SAME id and AppLayout marked it persisted; the build gave
    // the deck a Spec. sessionId does not change, so only the became-persisted re-read can help.
    getSession.mockResolvedValue({ messages: [], my_permission: 'CAN_MANAGE' });
    currentPersisted = true;
    view.rerender(panel({ hasDeckSpec: true }));
    expect(await screen.findByTestId('clear-chat-button')).toBeInTheDocument();
    expect(getSession).toHaveBeenCalledTimes(2);
    expect(getSession).toHaveBeenNthCalledWith(2, 'local-1');
  });

  it('re-reading the permission when the deck becomes persisted leaves the conversation in the panel alone', async () => {
    currentSessionId = 'local-1';
    currentPersisted = false;
    getSession.mockRejectedValueOnce({ status: 404, message: 'Session not found' });
    const view = mount({ hasDeckSpec: false });
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    await settle();
    // The first turn on the new deck: its user line is shown before the server has written any row.
    await act(async () => { fireEvent.click(screen.getByTestId('mock-send')); });
    await screen.findByText('Make slide 3 shorter');
    expect(ensureGraphCapableRoot).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(sendChatMessage).toHaveBeenCalledTimes(1));

    getSession.mockResolvedValue({ messages: [], my_permission: 'CAN_MANAGE' });
    currentPersisted = true;
    view.rerender(panel({ hasDeckSpec: true }));
    await screen.findByTestId('clear-chat-button');
    await settle();
    expect(listItems()).toHaveLength(1);
    expect(screen.getByText('Make slide 3 shorter')).toBeInTheDocument();
  });

  it('opening a saved deck from a browser-local session loads it once', async () => {
    currentSessionId = 'local-1';
    currentPersisted = false;
    getSession.mockRejectedValueOnce({ status: 404, message: 'Session not found' });
    const view = mount({ hasDeckSpec: false });
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    await settle();

    // A page load on /sessions/sess-2/edit, or a deck opened from history: switchSession commits the
    // new id and isSessionPersisted=true in one render. The session-change load reads the permission,
    // so the became-persisted re-read must not fetch the whole session a second time.
    getSession.mockResolvedValue({ messages: TWO, my_permission: 'CAN_MANAGE' });
    currentSessionId = 'sess-2';
    currentPersisted = true;
    view.rerender(panel({ hasDeckSpec: true }));
    await enabledClearButton();
    await settle();
    expect(getSession.mock.calls.filter(([id]) => id === 'sess-2')).toHaveLength(1);
  });

  it("switching session closes the dialog and hides Clear chat until the new session's permission arrives", async () => {
    const sess2 = deferred<unknown>();
    getSession.mockImplementation((id: string) => (id === 'sess-2'
      ? sess2.promise
      : Promise.resolve({ messages: TWO, my_permission: 'CAN_MANAGE' })));
    const view = mount();
    await screen.findByText('message B');
    fireEvent.click(await enabledClearButton());
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();

    currentSessionId = 'sess-2';
    view.rerender(panel({ hasDeckSpec: true }));
    expect(screen.queryByTestId('confirm-dialog')).toBeNull();
    expect(clearButtonCount()).toBe(0);

    await act(async () => { sess2.resolve({ messages: [msg('message C')], my_permission: 'CAN_EDIT' }); });
    await screen.findByText('message C');
    await enabledClearButton();
    expect(clearChat).not.toHaveBeenCalled();
  });

  it('a slow load for the previous session sets neither its conversation nor its permission on the new one', async () => {
    const sess1 = deferred<unknown>();
    getSession.mockImplementation((id: string) => (id === 'sess-1'
      ? sess1.promise
      : Promise.resolve({ messages: [], my_permission: 'CAN_VIEW' })));
    const view = mount();
    currentSessionId = 'sess-2';
    view.rerender(panel({ hasDeckSpec: true }));
    await waitFor(() => expect(getSession).toHaveBeenCalledWith('sess-2'));
    await settle();

    await act(async () => { sess1.resolve({ messages: TWO, my_permission: 'CAN_MANAGE' }); });
    await settle();
    expect(screen.queryByText('message A')).toBeNull();
    expect(listItems()).toHaveLength(0);
    expect(clearButtonCount()).toBe(0);
  });
});
