/**
 * Architect stage awareness, Task 1: ChatPanel captures the staged slide and sends it on Agent turns.
 *
 * Contract (task brief + PLAN-CORRECTIONS C3, global constraints):
 *   - ChatPanel takes an optional `getStageSlide?: () => StageSlideContext | undefined` prop.
 *   - An Agent-mode send (`storedDeckMode ?? selectedDeckMode` === 'agent') passes the captured stage as
 *     the argument APPENDED after deckMode on api.sendChatMessage (index 8). Legacy sends omit it and
 *     keep their slide_context exactly as before.
 *   - The stage is captured SYNCHRONOUSLY and COPIED before ensureGraphCapableRoot() or any other
 *     await: paging during a pending persistence, or a mutation of the object the getter returned,
 *     cannot retarget the send.
 *   - The visible user message is unchanged.
 *
 * Harness (as ChatPanel.deckMode.test.tsx): the REAL SessionProvider (so mode state is real), api
 * mocked, ChatInput mocked to a send button. Assertions read what reached api.sendChatMessage, the
 * transport boundary; api.stageContext.test.ts covers what the transport then POSTs.
 *
 * Mutations each guards:
 *   - stage not passed / passed in another slot                   -> "an Agent send carries the stage".
 *   - stage sent regardless of mode (Legacy too)                  -> the Legacy rows + "Legacy optimize".
 *   - mode read from the selection instead of stored ?? selection -> the locked-deck rows.
 *   - getter called after `await ensureGraphCapableRoot()`        -> "paging during persistence".
 *   - captured by reference, not copied                           -> "mutating the returned object".
 *   - Legacy slide_context dropped or replaced by the stage       -> "Legacy optimize".
 */
import type { ComponentProps } from 'react';
import { createRef } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DeckMode } from '../../services/api';
import { SessionProvider, useSession, type OptionalSessionInfo } from '../../contexts/SessionContext';

/** Structural mirror of the StageSlideContext the task adds to types/slide.ts. */
interface StageSlide { slide_number: number; slide_id?: string }

const h = vi.hoisted(() => {
  const setIsGenerating = vi.fn();
  const refreshConfig = vi.fn();
  return {
    agentConfig: { agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false },
    generation: { setIsGenerating },
    apiSessionId: null as string | null,
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
    <button type="button" data-testid="mock-send" disabled={disabled} onClick={() => onSend('Make the title bigger')}>
      send
    </button>
  ),
}));

import { ChatPanel, type ChatPanelHandle } from './ChatPanel';

// ── harness ───────────────────────────────────────────────────────────────────

type Ctx = ReturnType<typeof useSession>;
let ctx: Ctx;
function Probe() {
  ctx = useSession();
  return null;
}

type PanelProps = Partial<ComponentProps<typeof ChatPanel>>;
/** The prop the task adds; passed through a cast so this file compiles before and after the change. */
const withGetter = (getStageSlide: () => StageSlide | undefined) => ({ getStageSlide }) as unknown as PanelProps;

let ensureGraphCapableRoot = vi.fn(async () => true);
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });

async function mount(extra: PanelProps = {}) {
  const ref = createRef<ChatPanelHandle>();
  render(
    <MemoryRouter>
      <SessionProvider>
        <Probe />
        <ChatPanel ref={ref} rawHtml={null} onSlidesGenerated={vi.fn()} ensureGraphCapableRoot={ensureGraphCapableRoot} {...extra} />
      </SessionProvider>
    </MemoryRouter>,
  );
  await settle();
  return ref;
}

/** Open a saved deck (persisted), as AppLayout's URL restore does. */
async function restore(id: string, deck_mode: DeckMode | null) {
  const info: OptionalSessionInfo = { title: 'Deck', has_slide_deck: true, deck_mode };
  await act(async () => { await ctx.switchSession(id, info); });
  await settle();
}

async function select(mode: DeckMode) {
  await act(async () => { ctx.setSelectedDeckMode(mode); });
}

async function clickSend() {
  await act(async () => { fireEvent.click(screen.getByTestId('mock-send')); });
}

/** The arguments of the one sendChatMessage call so far. */
function sent() {
  expect(h.sendChatMessage).toHaveBeenCalledTimes(1);
  const a = h.sendChatMessage.mock.calls[0];
  return { sessionId: a[0], content: a[1], slideContext: a[2], deckMode: a[7], stage: a[8] };
}

interface Deferred<T> { promise: Promise<T>; resolve: (v: T) => void }
function deferred<T>(): Deferred<T> {
  let resolve: (v: T) => void = () => {};
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  h.apiSessionId = null;
  ensureGraphCapableRoot = vi.fn(async () => {
    ctx.markSessionPersisted();
    return true;
  });
  h.getSession.mockImplementation(async (id: string) => ({
    session_id: id, title: 'Deck', messages: [], my_permission: 'CAN_EDIT', has_slide_deck: true,
    graph_version: 1, active_graph_version: 1, is_older_than_active: false, deck_mode: null,
  }));
  h.getSlides.mockImplementation(async (id: string) => ({ session_id: id, slide_deck: null }));
  h.getCollaborationHistory.mockResolvedValue({ mixed_release_warning: false, has_legacy_evidence: false, groups: [] });
  h.listMessages.mockResolvedValue({ messages: [], count: 0 });
  h.sendChatMessage.mockImplementation(() => () => {});
});

// ── which sends carry the stage ───────────────────────────────────────────────

describe('the stage an Agent send carries', () => {
  it('an Agent send carries the captured stage after deckMode, with no slide_context; the user message shows', async () => {
    await mount(withGetter(() => ({ slide_number: 2, slide_id: 's-two' })));
    await restore('sess-1', null);

    await clickSend();

    const s = sent();
    expect(s.sessionId).toBe('sess-1');
    expect(s.deckMode).toBe('agent');
    expect(s.stage).toEqual({ slide_number: 2, slide_id: 's-two' });
    expect(s.slideContext).toBeUndefined();
    expect(screen.getByText('Make the title bigger')).toBeInTheDocument();
  });

  it.each<{ label: string; stored: DeckMode | null; selection: DeckMode; mode: DeckMode; carries: boolean }>([
    { label: 'unlocked, Agent selected', stored: null, selection: 'agent', mode: 'agent', carries: true },
    { label: 'locked Agent, Legacy selected', stored: 'agent', selection: 'legacy', mode: 'agent', carries: true },
    { label: 'unlocked, Legacy selected', stored: null, selection: 'legacy', mode: 'legacy', carries: false },
    { label: 'locked Legacy, Agent selected', stored: 'legacy', selection: 'agent', mode: 'legacy', carries: false },
  ])('$label: the stage is sent only on an Agent turn', async ({ stored, selection, mode, carries }) => {
    await mount(withGetter(() => ({ slide_number: 3, slide_id: 's-three' })));
    await restore('sess-1', stored);
    await select(selection);

    await clickSend();

    const s = sent();
    expect(s.deckMode).toBe(mode);
    if (carries) expect(s.stage).toEqual({ slide_number: 3, slide_id: 's-three' });
    else expect(s.stage).toBeUndefined();
    expect(screen.getByText('Make the title bigger')).toBeInTheDocument();
  });

  it('an id-less stage is forwarded as just its number', async () => {
    await mount(withGetter(() => ({ slide_number: 1 })));
    await restore('sess-1', 'agent');

    await clickSend();

    expect(sent().stage).toEqual({ slide_number: 1 });
  });

  it('no stage on view (the getter answers undefined): nothing is sent for it (control)', async () => {
    await mount(withGetter(() => undefined));
    await restore('sess-1', 'agent');
    await clickSend();
    expect(sent().stage).toBeUndefined();
  });

  it('a panel mounted without the prop still sends Agent turns (control)', async () => {
    await mount();
    await restore('sess-1', 'agent');
    await clickSend();
    const s = sent();
    expect(s.deckMode).toBe('agent');
    expect(s.stage).toBeUndefined();
  });
});

describe('the imperative send path (stage toolbar actions) keeps Legacy slide_context', () => {
  const OPTIMIZE_CONTEXT = { indices: [1], slide_htmls: ['<div class="slide">two</div>'] };

  it('Legacy: slide_context is sent exactly as before and no stage is added', async () => {
    const ref = await mount(withGetter(() => ({ slide_number: 2, slide_id: 's-two' })));
    await restore('sess-1', 'legacy');

    await act(async () => { ref.current!.sendMessage('Optimize the layout', OPTIMIZE_CONTEXT); });

    const s = sent();
    expect(s.deckMode).toBe('legacy');
    expect(s.slideContext).toEqual({ indices: [1], slide_htmls: ['<div class="slide">two</div>'] });
    expect(s.stage).toBeUndefined();
  });

  it('Agent: the same call keeps its slide_context and also carries the stage', async () => {
    const ref = await mount(withGetter(() => ({ slide_number: 2, slide_id: 's-two' })));
    await restore('sess-1', 'agent');

    await act(async () => { ref.current!.sendMessage('Optimize the layout', OPTIMIZE_CONTEXT); });

    const s = sent();
    expect(s.slideContext).toEqual({ indices: [1], slide_htmls: ['<div class="slide">two</div>'] });
    expect(s.stage).toEqual({ slide_number: 2, slide_id: 's-two' });
  });
});

// ── captured before the first await ───────────────────────────────────────────

describe('the stage is captured before ensureGraphCapableRoot resolves', () => {
  /** A landing deck (browser-local id): the send awaits persistence first. */
  async function mountLandingWithPendingPersistence(getter: () => StageSlide | undefined) {
    const persisted = deferred<boolean>();
    ensureGraphCapableRoot = vi.fn(async () => {
      const ok = await persisted.promise;
      if (ok) ctx.markSessionPersisted();
      return ok;
    });
    await mount(withGetter(getter));
    expect(ctx.isSessionPersisted).toBe(false);
    return persisted;
  }

  it('paging during the pending persistence does not retarget the send', async () => {
    let onStage: StageSlide = { slide_number: 2, slide_id: 's-two' };
    const persisted = await mountLandingWithPendingPersistence(() => onStage);
    const landingId = ctx.sessionId;

    await clickSend();
    expect(ensureGraphCapableRoot).toHaveBeenCalledTimes(1);
    expect(h.sendChatMessage).not.toHaveBeenCalled();

    // The user pages to slide 4 while the root is being persisted.
    onStage = { slide_number: 4, slide_id: 's-four' };
    await act(async () => { persisted.resolve(true); });
    await settle();

    const s = sent();
    expect(s.sessionId).toBe(landingId);
    expect(s.deckMode).toBe('agent');
    expect(s.stage).toEqual({ slide_number: 2, slide_id: 's-two' });
    expect(screen.getByText('Make the title bigger')).toBeInTheDocument();
  });

  it('mutating the object the getter returned, during the pending persistence, does not retarget the send', async () => {
    const staged: StageSlide = { slide_number: 2, slide_id: 's-two' };
    const persisted = await mountLandingWithPendingPersistence(() => staged);

    await clickSend();
    staged.slide_number = 4;
    staged.slide_id = 's-four';
    await act(async () => { persisted.resolve(true); });
    await settle();

    expect(sent().stage).toEqual({ slide_number: 2, slide_id: 's-two' });
  });

  it('a send whose persistence fails sends nothing (control)', async () => {
    const persisted = await mountLandingWithPendingPersistence(() => ({ slide_number: 2, slide_id: 's-two' }));

    await clickSend();
    await act(async () => { persisted.resolve(false); });
    await settle();

    expect(h.sendChatMessage).not.toHaveBeenCalled();
  });
});
