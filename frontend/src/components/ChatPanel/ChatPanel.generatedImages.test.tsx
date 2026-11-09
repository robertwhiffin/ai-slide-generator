/**
 * Chat image generation, Unit I (Tasks 6, 7, 8) through the real ChatPanel.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md ("Shared metadata
 * shape", "Unit I interface"). What this file pins, end to end through ChatPanel -> MessageList ->
 * Message -> GeneratedImagesCard, and ChatPanel -> ChatInput -> GenerateImageRequestDialog (all REAL):
 *
 *   Plumbing (Task 6)
 *   - A reloaded row (`GET /api/sessions/{id}` -> messages[].metadata.generated_images) and an SSE/poll
 *     `assistant` event (`event.metadata.generated_images`) both become `Message.generated_images`
 *     via readGeneratedImages, and the card renders under that reply. Malformed metadata: no card.
 *   - A `tool_call` with tool_name "image_generation" and tool_input {kind, count} reads
 *     "Image generation · 3 illustrations" in the activity bar, live and reloaded; the live label is
 *     "Generating 3 images…" (U+2026).
 *
 *   Actions (Task 7)
 *   - "Use this" on option 2 = handleSendMessage(pickImageMessage(img), [img.token]):
 *     api.sendChatMessage(sessionId, message, slideContext, onEvent, onError, imageIds, agentConfig, deckMode)
 *     gets message (index 1) "Use option 2 on slide 3.", slideContext (index 2) undefined, imageIds
 *     (index 5) ["tok2"].
 *   - "Regenerate" = handleSendMessage(regenerateMessage(images)): imageIds (index 5) undefined.
 *   - Disabled while a turn runs (enabled again after `complete`); hidden in save-point preview
 *     (`previewMessages`), where the card itself still shows.
 *   - Choice pinned here (CORRECTIONS is silent): on a read-only panel (`disabled`) no action is
 *     enabled and nothing is sent.
 *
 *   Entry point gating (Task 8)
 *   - ChatPanel passes ChatInput `imageRequest={{ slideCount }}` only when useImageGenerationOptions()
 *     says `available` AND the deck mode (`storedDeckMode ?? selectedDeckMode`, from useSession) is not
 *     'legacy'.
 *   - Choice pinned here: ChatPanel gets the slide count as a NEW prop `slideCount?: number`
 *     (AppLayout passes the live deck's `slides.length`); it is what the dialog's For-slide select lists.
 *
 * Harness: as ChatPanel.gatewayChat.test.tsx. The api module is mocked; useSession is a static mock read
 * from `h.session` at render time, so a rerender changes the deck mode. The options cache is reset
 * before every test.
 */
import { createRef, type ComponentProps, type RefObject } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ImageAsset, ImageGenerationOptions } from '../../types/image';
import type { Message } from '../../types/message';
import type { StreamEvent } from '../../services/api';
import { __resetImageGenerationOptionsCacheForTests } from '../../hooks/useImageGenerationOptions';

type OnEvent = (event: StreamEvent) => void;
interface Turn {
  args: unknown[];
  onEvent: OnEvent;
}

const h = vi.hoisted(() => ({
  getSession: vi.fn(),
  sendChatMessage: vi.fn(),
  getImage: vi.fn(),
  imageGenerationOptions: vi.fn(),
  getSlides: vi.fn(),
  listMessages: vi.fn(),
  // Stable across renders: ChatPanel's session effect depends on it.
  setIsGenerating: vi.fn(),
  setStoredDeckMode: vi.fn(),
  setSelectedDeckMode: vi.fn(),
  refreshConfig: vi.fn(),
  session: {
    storedDeckMode: null as 'agent' | 'legacy' | null,
    selectedDeckMode: 'agent' as 'agent' | 'legacy',
  },
  turns: [] as Array<{ args: unknown[]; onEvent: (event: unknown) => void }>,
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getSession: (...a: unknown[]) => h.getSession(...a),
      sendChatMessage: (...a: unknown[]) => h.sendChatMessage(...a),
      getImage: (...a: unknown[]) => h.getImage(...a),
      imageGenerationOptions: (...a: unknown[]) => h.imageGenerationOptions(...a),
      getSlides: (...a: unknown[]) => h.getSlides(...a),
      uploadImage: vi.fn(),
      getCurrentSessionId: () => 'img-session',
      setCurrentSessionId: vi.fn(),
    },
  };
});
vi.mock('../../api/conversation', () => ({
  conversationApi: {
    listMessages: (...a: unknown[]) => h.listMessages(...a),
    clearChat: vi.fn(),
    deleteMessage: vi.fn(),
  },
}));
vi.mock('../../contexts/SessionContext', () => ({
  useSession: () => ({
    sessionId: 'img-session',
    isSessionPersisted: true,
    isInitializing: false,
    error: null,
    setExperimentUrl: vi.fn(),
    setSessionTitle: vi.fn(),
    storedDeckMode: h.session.storedDeckMode,
    selectedDeckMode: h.session.selectedDeckMode,
    setStoredDeckMode: h.setStoredDeckMode,
    setSelectedDeckMode: h.setSelectedDeckMode,
  }),
}));
vi.mock('../../contexts/AgentConfigContext', () => ({
  useAgentConfig: () => ({
    agentConfig: null,
    refreshConfig: h.refreshConfig,
    configOwnerSessionId: null,
    isPreSession: false,
  }),
}));
vi.mock('../../contexts/GenerationContext', () => ({
  useGeneration: () => ({ setIsGenerating: h.setIsGenerating }),
}));

import { ChatPanel, type ChatPanelHandle } from './ChatPanel';

// ── fixtures ──────────────────────────────────────────────────────────────────

const TS = '2026-11-09T10:00:00Z';
const PROMPT = 'A calm lake at dawn';
const IMAGES = [1, 2, 3].map((option) => ({
  token: `tok${option}`,
  kind: 'illustration' as const,
  option,
  prompt: PROMPT,
  for_slide: 3,
  slides: [] as number[],
}));
const REPLY = 'Here are three illustrations for slide 3. Pick one, or ask for new ones.';
const ASKED = 'Make me a picture to get slide 3 across';

const thumb = (token: string) => `data:image/png;base64,THUMB_${token}`;
const asset = (token: string): ImageAsset => ({
  id: token,
  filename: `${token}.png`,
  original_filename: `${token}.png`,
  mime_type: 'image/png',
  size_bytes: 1024,
  thumbnail_base64: thumb(token),
  tags: ['ai_generated', 'chat', 'chat_option'],
  description: null,
  category: 'content',
  uploaded_by: 'alice@example.com',
  is_active: true,
  created_at: TS,
  updated_at: TS,
});

const OPTIONS = (available: boolean): ImageGenerationOptions => ({
  available,
  max_prompt_chars: available ? 2000 : 0,
  default_preset: available ? 'illustration' : null,
  presets: [],
  edit: null,
});

const row = (id: number, role: 'user' | 'assistant', content: string, metadata: unknown, message_type = 'llm_response') => ({
  id,
  role,
  content,
  message_type,
  created_at: TS,
  metadata,
});
const userRow = (id: number, content = ASKED) => row(id, 'user', content, null, 'user_input');
const replyRow = (id: number, metadata: unknown, content = REPLY) => row(id, 'assistant', content, metadata);
const architect = (generated_images: unknown) => ({ node: 'architect', intent: 'discuss', generated_images });

// ── harness ───────────────────────────────────────────────────────────────────

type PanelProps = Partial<ComponentProps<typeof ChatPanel>> & { slideCount?: number };

function mount(props: PanelProps = {}) {
  const ref = createRef<ChatPanelHandle>();
  const ui = (p: PanelProps) => (
    <MemoryRouter>
      <ChatPanel
        ref={ref}
        rawHtml={null}
        onSlidesGenerated={vi.fn()}
        ensureGraphCapableRoot={async () => true}
        slideCount={4}
        {...p}
      />
    </MemoryRouter>
  );
  const view = render(ui(props));
  return { ref, rerenderPanel: (p: PanelProps) => view.rerender(ui(p)) };
}

/** Let pending promise callbacks and zero-delay timers run, inside act. */
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function startTurn(ref: RefObject<ChatPanelHandle | null>, text = ASKED): Promise<Turn> {
  const before = h.turns.length;
  await act(async () => {
    ref.current!.sendMessage(text);
  });
  await waitFor(() => expect(h.turns.length).toBe(before + 1));
  return h.turns[before] as Turn;
}

async function emit(turn: Turn, ...events: StreamEvent[]) {
  await act(async () => {
    for (const e of events) turn.onEvent(e);
  });
}

// ── queries ───────────────────────────────────────────────────────────────────

const CAPTION = 'Saved to your Image Library';

/** The list item holding the visible label "Option N". */
function tile(n: number): HTMLElement {
  const li = screen.getByText(`Option ${n}`, { exact: true }).closest('li');
  expect(li, `"Option ${n}" sits in a list item`).not.toBeNull();
  return li as HTMLElement;
}
const useButtons = () => screen.queryAllByRole('button', { name: 'Use this' });
const regenerateButtons = () => screen.queryAllByRole('button', { name: 'Regenerate' });
const generateImageButton = () => screen.queryByRole('button', { name: 'Generate image' });

async function expectCard(tokens: string[]) {
  expect(await screen.findByText(CAPTION)).toBeInTheDocument();
  for (const [i, token] of tokens.entries()) {
    const img = await within(tile(i + 1)).findByRole('img');
    expect(img).toHaveAttribute('src', thumb(token));
  }
  expect(screen.queryByText(`Option ${tokens.length + 1}`, { exact: true })).toBeNull();
}

// ── setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  __resetImageGenerationOptionsCacheForTests();
  for (const fn of [h.getSession, h.sendChatMessage, h.getImage, h.imageGenerationOptions, h.getSlides, h.listMessages]) {
    fn.mockReset();
  }
  h.turns.length = 0;
  h.session.storedDeckMode = null;
  h.session.selectedDeckMode = 'agent';
  h.getSession.mockResolvedValue({ session_id: 'img-session', messages: [], my_permission: 'CAN_MANAGE' });
  h.getImage.mockImplementation(async (token: string) => asset(token));
  h.imageGenerationOptions.mockResolvedValue(OPTIONS(true));
  h.getSlides.mockResolvedValue({ slide_deck: null });
  h.listMessages.mockResolvedValue({ messages: [] });
  h.sendChatMessage.mockImplementation((...args: unknown[]) => {
    h.turns.push({ args, onEvent: args[3] as (event: unknown) => void });
    return () => {};
  });
});
afterEach(() => cleanup());

// ── Task 6: the card reaches the chat ─────────────────────────────────────────

describe('ChatPanel shows the options card', () => {
  it('reload: a row with metadata.generated_images renders the card under that reply', async () => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [userRow(1), replyRow(2, architect(IMAGES))],
    });
    mount();

    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    await expectCard(['tok1', 'tok2', 'tok3']);
    expect(h.getImage.mock.calls.map((c) => c[0]).sort()).toEqual(['tok1', 'tok2', 'tok3']);
  });

  it('reload: the card sits under the reply that carried it, not under an earlier one', async () => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [replyRow(1, null, 'An earlier reply.'), userRow(2), replyRow(3, architect(IMAGES))],
    });
    mount();

    const caption = await screen.findByText(CAPTION);
    const rows = screen.getAllByTestId('chat-message-row');
    const owner = rows.find((r) => r.contains(caption));
    expect(owner).toBeDefined();
    expect(owner!.textContent).toContain(REPLY);
    expect(owner!.textContent).not.toContain('An earlier reply.');
  });

  it('stream/poll: an assistant event with metadata.generated_images renders the card', async () => {
    const { ref } = mount();
    await flush();
    const turn = await startTurn(ref);
    await emit(turn, { type: 'assistant', content: REPLY, metadata: architect(IMAGES) }, { type: 'complete' });

    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    await expectCard(['tok1', 'tok2', 'tok3']);
  });

  it.each([
    ['a string', 'tok1,tok2'],
    ['an object', { tok1: true }],
    ['entries with a bad token, an unknown kind and no option', [
      { token: 'bad token', kind: 'illustration', option: 1, slides: [] },
      { token: 'tok2', kind: 'photo', option: 2, slides: [] },
      { token: 'tok3', kind: 'icon', slides: [] },
    ]],
    ['an empty list', []],
  ])('reload: malformed generated_images (%s) renders the reply and no card', async (_label, junk) => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [userRow(1), replyRow(2, architect(junk))],
    });
    mount();

    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    await flush();
    expect(screen.queryByText(CAPTION)).toBeNull();
    expect(screen.queryByText(/^Option \d$/)).toBeNull();
    expect(h.getImage).not.toHaveBeenCalled();
  });

  it('stream/poll: malformed generated_images renders the reply and no card', async () => {
    const { ref } = mount();
    await flush();
    const turn = await startTurn(ref);
    await emit(
      turn,
      { type: 'assistant', content: REPLY, metadata: architect([{ token: '../etc', kind: 'icon', option: 1 }]) },
      { type: 'complete' },
    );

    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    await flush();
    expect(screen.queryByText(CAPTION)).toBeNull();
    expect(h.getImage).not.toHaveBeenCalled();
  });

  it('reload: only the valid entries of a mixed list reach the card', async () => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [userRow(1), replyRow(2, architect([IMAGES[0], { token: 'x y', kind: 'icon', option: 2 }, null]))],
    });
    mount();

    await expectCard(['tok1']);
    expect(h.getImage.mock.calls.map((c) => c[0])).toEqual(['tok1']);
  });
});

// ── Task 7: Use this / Regenerate ─────────────────────────────────────────────

describe('ChatPanel card actions', () => {
  async function mountWithCard(props: PanelProps = {}) {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [userRow(1), replyRow(2, architect(IMAGES))],
    });
    const mounted = mount(props);
    await expectCard(['tok1', 'tok2', 'tok3']);
    return mounted;
  }

  it('"Use this" on option 2 sends "Use option 2 on slide 3." with image_ids ["tok2"]', async () => {
    await mountWithCard();

    fireEvent.click(within(tile(2)).getByRole('button', { name: 'Use this' }));

    await waitFor(() => expect(h.sendChatMessage).toHaveBeenCalledTimes(1));
    const args = h.sendChatMessage.mock.calls[0];
    expect(args[0]).toBe('img-session');
    expect(args[1]).toBe('Use option 2 on slide 3.');
    expect(args[2]).toBeUndefined();
    expect(args[5]).toEqual(['tok2']);
    expect(args[7]).toBe('agent');
    // The user's own bubble reads the same sentence.
    expect(await screen.findByText('Use option 2 on slide 3.')).toBeInTheDocument();
  });

  it('"Use this" on an image made for no slide asks for the best fit', async () => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [userRow(1), replyRow(2, architect(IMAGES.map((i) => ({ ...i, for_slide: null }))))],
    });
    mount();
    await expectCard(['tok1', 'tok2', 'tok3']);

    fireEvent.click(within(tile(1)).getByRole('button', { name: 'Use this' }));

    await waitFor(() => expect(h.sendChatMessage).toHaveBeenCalledTimes(1));
    expect(h.sendChatMessage.mock.calls[0][1]).toBe('Use option 1 where it fits best.');
    expect(h.sendChatMessage.mock.calls[0][5]).toEqual(['tok1']);
  });

  it('"Regenerate" sends the regenerate message with no image ids', async () => {
    await mountWithCard();

    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));

    await waitFor(() => expect(h.sendChatMessage).toHaveBeenCalledTimes(1));
    const args = h.sendChatMessage.mock.calls[0];
    expect(args[1]).toBe('Generate 3 new illustration options for slide 3.');
    expect(args[5]).toBeUndefined();
  });

  it('the actions are disabled while a turn runs and enabled again after it completes', async () => {
    await mountWithCard();
    for (const b of [...useButtons(), ...regenerateButtons()]) expect(b).toBeEnabled();

    fireEvent.click(within(tile(2)).getByRole('button', { name: 'Use this' }));
    await waitFor(() => expect(h.turns).toHaveLength(1));

    expect(useButtons()).toHaveLength(3);
    for (const b of [...useButtons(), ...regenerateButtons()]) expect(b).toBeDisabled();
    fireEvent.click(within(tile(3)).getByRole('button', { name: 'Use this' }));
    expect(h.sendChatMessage).toHaveBeenCalledTimes(1);

    await emit(h.turns[0] as Turn, { type: 'complete' });
    await waitFor(() => {
      for (const b of [...useButtons(), ...regenerateButtons()]) expect(b).toBeEnabled();
    });
  });

  // AppLayout's preview is also read-only (disabled); the preview alone must hide the actions too.
  it.each([true, false])('save-point preview shows the card with no actions (disabled=%s)', async (disabled) => {
    const preview: Message[] = [
      { role: 'user', content: ASKED, timestamp: TS },
      { role: 'assistant', content: REPLY, timestamp: TS, generated_images: IMAGES } as Message,
    ];
    mount({ previewMessages: preview, disabled });

    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    await expectCard(['tok1', 'tok2', 'tok3']);
    expect(useButtons()).toHaveLength(0);
    expect(regenerateButtons()).toHaveLength(0);
  });

  it('a read-only panel offers no enabled action and sends nothing', async () => {
    await mountWithCard({ disabled: true });

    const actions = [...useButtons(), ...regenerateButtons()];
    for (const b of actions) {
      expect(b).toBeDisabled();
      fireEvent.click(b);
    }
    await flush();
    expect(h.sendChatMessage).not.toHaveBeenCalled();
  });
});

// ── Task 6: activity label ────────────────────────────────────────────────────

describe('ChatPanel image generation activity', () => {
  const openBar = () => {
    const bar = screen.getByTestId('tool-activity-bar');
    fireEvent.click(within(bar).getByRole('button'));
    return bar;
  };

  it('a live image_generation tool_call reads "Image generation · 3 illustrations"; the live label "Generating 3 images…"', async () => {
    const { ref } = mount();
    await flush();
    const turn = await startTurn(ref);
    await emit(turn, {
      type: 'tool_call',
      content: 'Generating 3 illustrations',
      tool_name: 'image_generation',
      tool_input: { kind: 'illustration', count: 3 },
      metadata: { node: 'architect' },
    });

    expect(await screen.findByText('Generating 3 images…')).toBeInTheDocument();
    expect(screen.queryByText(/Querying image_generation/)).toBeNull();
    const bar = openBar();
    expect(bar.textContent).toContain('1 tool call · Image generation');
    const items = screen.getAllByTestId('tool-activity-item');
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toBe('Image generation · 3 illustrations');
  });

  it('a reloaded image_generation tool_call row reads the same', async () => {
    h.getSession.mockResolvedValue({
      session_id: 'img-session',
      messages: [
        userRow(1),
        row(2, 'assistant', 'Generating 3 illustrations', {
          tool_name: 'image_generation',
          tool_input: { kind: 'illustration', count: 3 },
        }, 'tool_call'),
        replyRow(3, architect(IMAGES)),
      ],
    });
    mount();
    await screen.findByText(REPLY);

    openBar();
    expect(screen.getByTestId('tool-activity-item').textContent).toBe('Image generation · 3 illustrations');
  });
});

// ── Task 8: the Generate image entry point ────────────────────────────────────

describe('ChatPanel "Generate image" gating', () => {
  it('shows the button in agent mode when generation is available, with the deck’s slides in the dialog', async () => {
    mount({ slideCount: 4 });

    const button = await screen.findByRole('button', { name: 'Generate image' });
    fireEvent.click(button);
    const select = within(screen.getByRole('dialog')).getByRole('combobox', { name: 'For slide' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['None', '1', '2', '3', '4']);
  });

  it('the dialog sends its message through the chat', async () => {
    mount({ slideCount: 4 });
    fireEvent.click(await screen.findByRole('button', { name: 'Generate image' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Describe the image' }), {
      target: { value: 'A lighthouse at dusk' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Send to chat' }));

    await waitFor(() => expect(h.sendChatMessage).toHaveBeenCalledTimes(1));
    expect(h.sendChatMessage.mock.calls[0][1]).toBe('Generate 3 illustration options: A lighthouse at dusk');
    expect(h.sendChatMessage.mock.calls[0][5]).toBeUndefined();
  });

  it('hides the button when the options say unavailable', async () => {
    h.imageGenerationOptions.mockResolvedValue(OPTIONS(false));
    mount();

    await waitFor(() => expect(h.imageGenerationOptions).toHaveBeenCalled());
    await flush();
    await flush();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(generateImageButton()).toBeNull();
  });

  it('hides the button when the probe fails', async () => {
    h.imageGenerationOptions.mockRejectedValue(new TypeError('Failed to fetch'));
    mount();

    await waitFor(() => expect(h.imageGenerationOptions).toHaveBeenCalled());
    await flush();
    await flush();
    expect(generateImageButton()).toBeNull();
  });

  it('hides the button on a legacy deck (stored mode), and shows it once the mode is agent', async () => {
    h.session.storedDeckMode = 'legacy';
    h.session.selectedDeckMode = 'agent';
    const { rerenderPanel } = mount();
    await flush();
    await flush();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(generateImageButton()).toBeNull();

    h.session.storedDeckMode = 'agent';
    rerenderPanel({});
    expect(await screen.findByRole('button', { name: 'Generate image' })).toBeInTheDocument();
  });

  it('hides the button on an unlocked deck with Legacy selected', async () => {
    h.session.storedDeckMode = null;
    h.session.selectedDeckMode = 'legacy';
    const { rerenderPanel } = mount();
    await flush();
    await flush();
    expect(generateImageButton()).toBeNull();

    h.session.selectedDeckMode = 'agent';
    rerenderPanel({});
    expect(await screen.findByRole('button', { name: 'Generate image' })).toBeInTheDocument();
  });

  it('the stored mode wins: agent stored with Legacy selected shows the button', async () => {
    h.session.storedDeckMode = 'agent';
    h.session.selectedDeckMode = 'legacy';
    mount();
    expect(await screen.findByRole('button', { name: 'Generate image' })).toBeInTheDocument();
  });
});
