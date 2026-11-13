/**
 * Interrupt generation, Task 10: AppLayout's new ChatPanel prop `onDeckRestored(deck: SlideDeck | null)`,
 * the deck the server holds after a stop or a rolled-back failure.
 *
 * Contract (task-10-brief.md, AppLayout bullet):
 *   - with a deck: `setSlideDeckGated(deck, deck.version, true)`: shown even below the version on
 *     screen, and the mid-turn view (synthetic `build-N` slides from slide_ready) is replaced;
 *   - with `null`: `deckVersionRef.current = 0` AND `setSlideDeck(null)`, mirroring handleNewSession.
 *     Without the reset, the version guard (setSlideDeckGated) rejects the next first generation's
 *     version-1 deck and the viewer stays empty.
 *   - it is not the success path: onGenerationComplete (the survey trigger) does not run.
 *
 * This file renders the REAL AppLayout. Its children are stubs: ChatPanel records the props it is
 * given (so the test calls `onDeckRestored` / `onSlidesGenerated` / `onSlideReady` exactly as ChatPanel
 * would), and SlideViewer prints the slide ids of the deck it is handed (what the user sees). It lives in
 * its own file because ChatPanel.stop.test.tsx needs the real ChatPanel, and vi.mock is per file.
 *
 * SABOTAGE (for the reviewer):
 *   - onDeckRestored not passed to ChatPanel                 -> every test but the control RED.
 *   - null: setSlideDeck(null) without the version reset     -> test_first_generation_after_empty_rollback_renders RED.
 *   - null: only the version reset (deck kept)               -> same test RED (the viewer still shows the deck).
 *   - deck: setSlideDeckGated(deck, deck.version) (no force) -> test_restored_deck_replaces_the_mid_turn_view RED.
 *   - onDeckRestored routed through onSlidesGenerated's body -> both tests RED (onGenerationComplete runs).
 */
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';

type Props = Record<string, unknown>;

const h = vi.hoisted(() => ({
  /** The props AppLayout last rendered ChatPanel with. */
  chat: null as Record<string, unknown> | null,
  onGenerationComplete: vi.fn(),
  onGenerationStart: vi.fn(),
  closeSurvey: vi.fn(),
  showToast: vi.fn(),
  openOAuthPopup: vi.fn(),
  dismiss: vi.fn(),
  listVersions: vi.fn(),
  session: {
    sessionTitle: 'Otters',
    sessionId: 'sess-1',
    experimentUrl: null,
    graphVersion: 1,
    activeGraphVersion: 1,
    isGraphVersionOlder: false,
    collaborationHistory: [],
    collaborationHistoryFailed: false,
    isSessionPersisted: true,
    createNewSession: vi.fn(),
    markSessionPersisted: vi.fn(),
    switchSession: vi.fn(),
    renameSession: vi.fn(),
    setConversationGraphVersion: vi.fn(),
    storedDeckMode: 'agent',
    selectedDeckMode: 'agent',
  },
  generation: { isGenerating: false, setIsGenerating: vi.fn() },
}));

// ── the two children that matter ─────────────────────────────────────────────
vi.mock('../ChatPanel/ChatPanel', () => ({
  ChatPanel: (props: Record<string, unknown>) => {
    h.chat = props;
    return <div data-testid="chat-stub" />;
  },
}));
vi.mock('../SlideViewer/SlideViewer', () => ({
  SlideViewer: ({ slideDeck }: { slideDeck: SlideDeck | null }) => (
    <div data-testid="viewer">{slideDeck ? slideDeck.slides.map((s) => s.slide_id).join(',') : 'no deck'}</div>
  ),
}));

// ── everything else AppLayout renders or calls: inert ──────────────────────────
vi.mock('../SpecView/SpecView', () => ({ SpecView: () => null }));
vi.mock('../AgentConfigBar/AgentConfigBar', () => ({ AgentConfigBar: () => null }));
vi.mock('../config/ProfileList', () => ({ ProfileList: () => null }));
vi.mock('../config/DeckPromptList', () => ({ DeckPromptList: () => null }));
vi.mock('../config/SlideStyleList', () => ({ SlideStyleList: () => null }));
vi.mock('../config/DesignSystemLibrary', () => ({ DesignSystemLibrary: () => null }));
vi.mock('../config/SettingsPage', () => ({ SettingsPage: () => null }));
vi.mock('../History/SessionHistory', () => ({ SessionHistory: () => null }));
vi.mock('../History/SaveAsDialog', () => ({ SaveAsDialog: () => null }));
vi.mock('../ImageLibrary/ImageLibrary', () => ({ ImageLibrary: () => null }));
vi.mock('../Help', () => ({ HelpPage: () => null }));
vi.mock('../UpdateBanner', () => ({ UpdateBanner: () => null }));
vi.mock('../SavePoints', () => ({ SavePointDropdown: () => null, PreviewBanner: () => null, RevertConfirmModal: () => null }));
vi.mock('../DeckContributorsManager', () => ({ DeckContributorsManager: () => null }));
vi.mock('../Feedback/FeedbackButton', () => ({ FeedbackButton: () => null }));
vi.mock('../Feedback/SurveyModal', () => ({ SurveyModal: () => null }));
vi.mock('../Conversation/GraphVersionStatus', () => ({ GraphVersionStatus: () => null }));
vi.mock('../Conversation/MixedReleaseWarning', () => ({ MixedReleaseWarning: () => null }));
vi.mock('./app-sidebar', () => ({ AppSidebar: () => null }));
vi.mock('./page-header', () => ({ PageHeader: () => null }));
vi.mock('./simple-page-header', () => ({ SimplePageHeader: () => null }));
vi.mock('./GenieDataButton', () => ({ GenieDataButton: () => null }));
vi.mock('@/ui/sidebar', () => ({
  SidebarProvider: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  SidebarInset: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));
vi.mock('../../contexts/ProfileContext', () => ({
  ProfileProvider: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));
vi.mock('../../contexts/SessionContext', () => ({ useSession: () => h.session }));
vi.mock('../../contexts/GenerationContext', () => ({ useGeneration: () => h.generation }));
vi.mock('../../contexts/ToastContext', () => ({ useToast: () => ({ showToast: h.showToast }) }));
vi.mock('../../hooks/useVersionCheck', () => ({
  useVersionCheck: () => ({ updateAvailable: false, latestVersion: null, updateType: null, dismissed: false, dismiss: h.dismiss }),
}));
vi.mock('../../hooks/useGoogleOAuthPopup', () => ({ useGoogleOAuthPopup: () => ({ openOAuthPopup: h.openOAuthPopup }) }));
vi.mock('../../hooks/useSurveyTrigger', () => ({
  useSurveyTrigger: () => ({
    showSurvey: false,
    closeSurvey: h.closeSurvey,
    onGenerationComplete: h.onGenerationComplete,
    onGenerationStart: h.onGenerationStart,
  }),
}));
vi.mock('../../hooks/useDeckExport', () => ({
  useDeckExport: () => ({ handleExportPDF: () => {}, handleExportPPTX: () => {}, handleSaveAsHTML: () => {} }),
}));
vi.mock('../../hooks/useImageGenerationOptions', () => ({ useImageGenerationOptions: () => null }));
vi.mock('../../api/config', () => ({ configApi: { listDeckContributors: () => Promise.resolve({ contributors: [] }) } }));
vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      listVersions: (...a: unknown[]) => h.listVersions(...a),
      getCurrentSessionId: () => 'sess-1',
      releaseEditingLock: () => Promise.resolve(),
      acquireEditingLock: () => Promise.resolve({ acquired: true, locked_by: null }),
    },
  };
});

import { AppLayout } from './AppLayout';

// ── fixtures and harness ───────────────────────────────────────────────────────

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

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });
const viewer = () => screen.getByTestId('viewer').textContent;

function chat(): Props {
  expect(h.chat, 'AppLayout did not render ChatPanel').not.toBeNull();
  return h.chat as Props;
}
function prop<T>(name: string): T {
  const value = chat()[name];
  expect(value, `AppLayout does not pass ${name} to ChatPanel`).toBeTypeOf('function');
  return value as T;
}
type OnSlidesGenerated = (deck: SlideDeck, rawHtml: string | null) => Promise<void> | void;
type OnDeckRestored = (deck: SlideDeck | null) => void;
type OnSlideReady = (position: number, html: string, scripts: string) => void;

/** ChatPanel's success path: a turn completed with this deck. */
const generated = (deck: SlideDeck) =>
  act(async () => { await prop<OnSlidesGenerated>('onSlidesGenerated')(deck, null); });
const restored = (deck: SlideDeck | null) => act(async () => { prop<OnDeckRestored>('onDeckRestored')(deck); });
const slideReady = (position: number, html: string) =>
  act(async () => { prop<OnSlideReady>('onSlideReady')(position, html, ''); });

async function mount() {
  render(
    <MemoryRouter>
      <AppLayout initialView="main" />
    </MemoryRouter>,
  );
  await settle();
}

beforeEach(() => {
  vi.clearAllMocks();
  h.chat = null;
  h.listVersions.mockResolvedValue({ versions: [], current_version: null });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ json: () => Promise.resolve({ username: 'me@example.com' }) })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AppLayout's ChatPanel onDeckRestored", () => {
  it('control: the version guard is live in this harness (an older deck is rejected without a rollback)', async () => {
    await mount();
    await generated(deckOf(['A', 'B', 'C'], 3));
    expect(viewer()).toBe('A,B,C');

    await generated(deckOf(['X'], 1));
    expect(viewer()).toBe('A,B,C');
  });

  it('test_first_generation_after_empty_rollback_renders', async () => {
    await mount();
    expect(viewer()).toBe('no deck');
    await generated(deckOf(['A', 'B', 'C'], 3));
    expect(viewer()).toBe('A,B,C');
    const surveyCalls = h.onGenerationComplete.mock.calls.length;

    // The stop rolled the deck back to nothing.
    await restored(null);
    expect(viewer()).toBe('no deck');
    expect(h.onGenerationComplete.mock.calls.length, 'a rollback ran the success path').toBe(surveyCalls);

    // The next first generation's deck is version 1, and it must show.
    await generated(deckOf(['X', 'Y'], 1));
    expect(viewer()).toBe('X,Y');
  });

  it('test_restored_deck_replaces_the_mid_turn_view_even_below_the_shown_version', async () => {
    await mount();
    await generated(deckOf(['A', 'B', 'C'], 5));
    // Mid-turn slides arrive one at a time.
    await slideReady(3, '<div class="slide">D</div>');
    expect(viewer()).toBe('A,B,C,build-3');
    const surveyCalls = h.onGenerationComplete.mock.calls.length;

    // The server's deck after the rollback, at a version below the one on screen: it still shows.
    await restored(deckOf(['A', 'B', 'C'], 4));
    expect(viewer()).toBe('A,B,C');
    expect(h.onGenerationComplete.mock.calls.length, 'a rollback ran the success path').toBe(surveyCalls);

    // And the restored version is the new floor: the next turn's deck shows.
    await generated(deckOf(['A', 'B', 'C', 'E'], 5));
    expect(viewer()).toBe('A,B,C,E');
  });
});
