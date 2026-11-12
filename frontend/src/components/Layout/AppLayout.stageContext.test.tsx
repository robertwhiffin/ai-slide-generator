/**
 * Architect stage awareness, Task 1: AppLayout wires the viewer's stage into the chat panel, at RUNTIME.
 *
 * Contract (task brief + PLAN-CORRECTIONS C4; plan Review Focus 2):
 *   - AppLayout passes ChatPanel a `getStageSlide` prop that answers the REAL SlideViewer's displayed
 *     slide, `{ slide_number (1-based), slide_id }`, at the moment it is called.
 *   - Spec view (slides pane hidden, never unmounted) and a historical save-point preview supply NO
 *     stage (undefined), and leaving them supplies the live stage again.
 *   - A session switch never supplies the previous session's slide; a new, empty session supplies none.
 *
 * AppLayoutSpecToggle.test.ts is source-text only. This file mounts AppLayout for real, inside the real
 * SessionProvider, GenerationProvider, ToastProvider and a MemoryRouter, with the REAL SlideViewer.
 * Mocked: the api module and configApi (network), ChatPanel (replaced by a stub that only records its
 * props; the assertions call AppLayout's getter, never the stub), and leaf UI/hooks AppLayout merely
 * hosts (sidebar, header, save-point controls, config bar, other views). The sidebar/header/save-point
 * stubs expose buttons that drive AppLayout's own handlers (onSessionSelect, onNewSession, onPreview,
 * onCancel) so the session switch and preview paths are AppLayout's real ones.
 *
 * Mutations each guards:
 *   - no getStageSlide prop passed to ChatPanel / not wired to the viewer ref -> "wires the viewer".
 *   - getter not gated by showSpec                                            -> "Spec view supplies no stage".
 *   - getter not gated by previewVersion (would answer the preview deck)      -> "a save-point preview".
 *   - a gate that sticks after leaving Spec/preview                           -> the positive halves.
 *   - stage cached in AppLayout (state/ref set on navigation) and not reset   -> "a session switch".
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';

/** Structural mirror of the StageSlideContext the task adds to types/slide.ts. */
interface StageSlide { slide_number: number; slide_id?: string }

function deckOf(ids: string[]): SlideDeck {
  return {
    title: 'Deck',
    slide_count: ids.length,
    css: '',
    external_scripts: [],
    scripts: '',
    version: 1,
    findings: [],
    slides: ids.map((slide_id, index) => ({
      index,
      slide_id,
      html: `<div class="slide"><h1>${slide_id}</h1></div>`,
      scripts: '',
    })),
  } as SlideDeck;
}

const h = vi.hoisted(() => ({
  /** The props of ChatPanel's latest render. */
  chatProps: null as null | Record<string, unknown>,
  /** Server decks by session id (null: the session has no deck). */
  decks: {} as Record<string, SlideDeck | null>,
  previewDeck: null as SlideDeck | null,
  apiSessionId: null as string | null,
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  const fn = vi.fn;
  return {
    ...actual,
    api: {
      getCurrentSessionId: () => h.apiSessionId,
      setCurrentSessionId: (id: string | null) => { h.apiSessionId = id; },
      getSession: fn(async (id: string) => ({
        session_id: id, title: `Deck ${id}`, messages: [], my_permission: 'CAN_EDIT',
        has_slide_deck: h.decks[id] != null, experiment_url: null,
        graph_version: 1, active_graph_version: 1, is_older_than_active: false, deck_mode: null,
      })),
      getSlides: fn(async (id: string) => ({ session_id: id, slide_deck: h.decks[id] ?? null })),
      getCollaborationHistory: fn(async () => ({ mixed_release_warning: false, has_legacy_evidence: false, groups: [] })),
      listVersions: fn(async () => ({
        versions: [{ version_number: 1, description: 'First draft', created_at: '2026-11-12T00:00:00Z', slide_count: 2 }],
        current_version: 2,
      })),
      previewVersion: fn(async (_id: string, v: number) => ({
        version_number: v, deck: h.previewDeck, description: 'First draft', chat_history: [],
      })),
      createSession: fn(async ({ sessionId }: { sessionId?: string }) => ({
        session_id: sessionId ?? 'created', graph_version: 1, active_graph_version: 1, is_older_than_active: false,
      })),
      acquireEditingLock: fn(async () => ({ acquired: true, locked_by: null })),
      releaseEditingLock: fn(async () => undefined),
      heartbeatEditingLock: fn(async () => undefined),
      getEditingLockStatus: fn(async () => ({ locked: false, locked_by: null })),
      verifySlide: fn(async () => ({})),
      syncVersionVerification: fn(async () => undefined),
    },
  };
});
vi.mock('../../api/config', () => ({
  configApi: { listDeckContributors: vi.fn(async () => ({ contributors: [] })) },
}));

// ChatPanel: records its props only. The getter it receives is AppLayout's, and that is what is called.
vi.mock('../ChatPanel/ChatPanel', () => ({
  ChatPanel: (props: Record<string, unknown>) => {
    h.chatProps = props;
    return <div data-testid="chat-panel-stub" />;
  },
}));

// Leaf UI AppLayout hosts. Stubs that expose AppLayout's own callbacks as buttons.
vi.mock('./app-sidebar', () => ({
  AppSidebar: ({ onSessionSelect, onNewSession }: { onSessionSelect: (id: string) => void; onNewSession: () => void }) => (
    <nav>
      <button type="button" data-testid="open-sess-b" onClick={() => onSessionSelect('sess-b')}>open B</button>
      <button type="button" data-testid="new-session" onClick={() => onNewSession()}>new</button>
    </nav>
  ),
}));
vi.mock('./page-header', () => ({
  PageHeader: ({ savePointDropdown }: { savePointDropdown?: ReactNode }) => <header>{savePointDropdown}</header>,
}));
vi.mock('../SavePoints', () => ({
  SavePointDropdown: ({ onPreview }: { onPreview: (v: number) => void }) => (
    <button type="button" data-testid="preview-v1" onClick={() => onPreview(1)}>preview v1</button>
  ),
  PreviewBanner: ({ onCancel }: { onCancel: () => void }) => (
    <button type="button" data-testid="preview-cancel" onClick={onCancel}>back to latest</button>
  ),
  RevertConfirmModal: () => null,
}));
vi.mock('@/ui/sidebar', () => ({
  SidebarProvider: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SidebarInset: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock('./simple-page-header', () => ({ SimplePageHeader: () => null }));
vi.mock('./GenieDataButton', () => ({ GenieDataButton: () => null }));
vi.mock('../SpecView/SpecView', () => ({ SpecView: () => <div data-testid="spec-view-stub" /> }));
vi.mock('../AgentConfigBar/AgentConfigBar', () => ({ AgentConfigBar: () => null }));
vi.mock('../Conversation/GraphVersionStatus', () => ({ GraphVersionStatus: () => null }));
vi.mock('../Conversation/MixedReleaseWarning', () => ({ MixedReleaseWarning: () => null }));
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
vi.mock('../DeckContributorsManager', () => ({ DeckContributorsManager: () => null }));
vi.mock('../Feedback/FeedbackButton', () => ({ FeedbackButton: () => null }));
vi.mock('../Feedback/SurveyModal', () => ({ SurveyModal: () => null }));
vi.mock('../../hooks/useVersionCheck', () => ({
  useVersionCheck: () => ({ updateAvailable: false, latestVersion: null, updateType: null, dismissed: false, dismiss: () => {} }),
}));
vi.mock('../../hooks/useSurveyTrigger', () => ({
  useSurveyTrigger: () => ({ showSurvey: false, closeSurvey: () => {}, onGenerationComplete: () => {}, onGenerationStart: () => {} }),
}));
vi.mock('../../hooks/useGoogleOAuthPopup', () => ({ useGoogleOAuthPopup: () => ({ openOAuthPopup: async () => false }) }));
vi.mock('../../hooks/useImageGenerationOptions', () => ({ useImageGenerationOptions: () => null }));
vi.mock('../../hooks/useDeckExport', () => ({
  useDeckExport: () => ({
    isExportingPDF: false, isExportingPPTX: false,
    handleExportPDF: async () => {}, handleExportPPTX: async () => {}, handleSaveAsHTML: () => {},
  }),
}));

import { AppLayout } from './AppLayout';
import { SessionProvider } from '../../contexts/SessionContext';
import { GenerationProvider } from '../../contexts/GenerationContext';
import { ToastProvider } from '../../contexts/ToastContext';

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });

/** Call AppLayout's getter as ChatPanel would at send time. No prop -> undefined (a red assertion). */
const stage = (): StageSlide | undefined => {
  const getter = h.chatProps?.getStageSlide as undefined | (() => StageSlide | undefined);
  return getter?.();
};

async function mountAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <SessionProvider>
          <GenerationProvider>
            <Routes>
              <Route path="/" element={<AppLayout key="app-layout" initialView="main" />} />
              <Route path="/sessions/:sessionId/edit" element={<AppLayout key="app-layout" initialView="main" />} />
            </Routes>
          </GenerationProvider>
        </SessionProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  await settle();
  await settle();
}

const position = () => screen.getByTestId('stage-position').textContent?.replace(/\s+/g, ' ').trim();

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
  // AppLayout's one direct fetch: the current user, for lock comparison.
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ username: 'me@example.com' }), { status: 200 })));
  h.chatProps = null;
  h.apiSessionId = null;
  h.decks = {
    'sess-a': deckOf(['a-one', 'a-two', 'a-three']),
    'sess-b': deckOf(['b-only']),
  };
  h.previewDeck = deckOf(['p-one', 'p-two']);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('AppLayout hands ChatPanel the stage of the real SlideViewer', () => {
  it('wires the viewer: the getter answers the displayed slide as the user pages', async () => {
    await mountAt('/sessions/sess-a/edit');
    expect(position()).toBe('1 / 3');
    expect(stage()).toEqual({ slide_number: 1, slide_id: 'a-one' });

    fireEvent.click(screen.getByTestId('stage-next'));
    fireEvent.click(screen.getByTestId('stage-next'));
    expect(position()).toBe('3 / 3');
    expect(stage()).toEqual({ slide_number: 3, slide_id: 'a-three' });

    fireEvent.click(screen.getByTestId('ribbon-thumb-1'));
    expect(stage()).toEqual({ slide_number: 2, slide_id: 'a-two' });
  });

  it('Spec view supplies no stage; back on Slides the live stage returns', async () => {
    await mountAt('/sessions/sess-a/edit');
    fireEvent.click(screen.getByTestId('ribbon-thumb-1'));
    expect(stage()).toEqual({ slide_number: 2, slide_id: 'a-two' });

    fireEvent.click(screen.getByTestId('view-toggle-spec'));
    // The slides pane is hidden, not unmounted: the viewer still holds slide 2 behind it.
    expect(screen.getByTestId('slide-viewer-pane')).toHaveClass('hidden');
    expect(position()).toBe('2 / 3');
    expect(stage()).toBeUndefined();

    fireEvent.click(screen.getByTestId('view-toggle-slides'));
    expect(stage()).toEqual({ slide_number: 2, slide_id: 'a-two' });
  });

  it('a save-point preview supplies no stage (not the preview deck\'s slide); leaving it supplies the live deck again', async () => {
    await mountAt('/sessions/sess-a/edit');
    fireEvent.click(screen.getByTestId('ribbon-thumb-2'));
    expect(stage()).toEqual({ slide_number: 3, slide_id: 'a-three' });

    await act(async () => { fireEvent.click(screen.getByTestId('preview-v1')); });
    await settle();
    // The viewer now shows the historical (2-slide) deck.
    expect(position()).toBe('1 / 2');
    expect(stage()).toBeUndefined();

    await act(async () => { fireEvent.click(screen.getByTestId('preview-cancel')); });
    await settle();
    expect(position()).toBe('1 / 3');
    expect(stage()).toEqual({ slide_number: 1, slide_id: 'a-one' });
  });

  it('a session switch supplies the new deck\'s displayed slide, never the old one; a new empty session supplies none', async () => {
    await mountAt('/sessions/sess-a/edit');
    fireEvent.click(screen.getByTestId('ribbon-thumb-2'));
    expect(stage()).toEqual({ slide_number: 3, slide_id: 'a-three' });

    await act(async () => { fireEvent.click(screen.getByTestId('open-sess-b')); });
    await settle();
    await settle();
    expect(position()).toBe('1 / 1');
    expect(stage()).toEqual({ slide_number: 1, slide_id: 'b-only' });

    await act(async () => { fireEvent.click(screen.getByTestId('new-session')); });
    await settle();
    await settle();
    expect(screen.getByTestId('slide-viewer-empty')).toBeInTheDocument();
    expect(stage()).toBeUndefined();
  });
});
