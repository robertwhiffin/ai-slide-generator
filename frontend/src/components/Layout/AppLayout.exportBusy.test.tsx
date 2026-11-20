/**
 * A busy worker's 429 on the Google Slides export: AppLayout's handleExportGoogleSlides ->
 * api.exportToGoogleSlides -> POST /api/export/google-slides/from-huashu.
 *
 * Contract: when the worker has no room for another export,
 * both Chrome export routes answer 429 with `Retry-After: 60` and
 * `{"detail": "Exports are busy right now. Please try again in a minute."}`. AppLayout shows that
 * detail as it is, in an error toast, and the export does NOT fall back to the records pipeline: the
 * client falls back only on a 503 (not installed here), and running it on a 429 would hide the
 * message behind a slower, different export.
 *
 * This file mounts the REAL AppLayout inside the real SessionProvider, GenerationProvider and
 * ToastProvider, and runs the REAL api.exportToGoogleSlides over a stubbed `fetch` that records every
 * request. Mocked as in AppLayout.stageContext.test.tsx: the rest of the api module, configApi, and
 * the leaf UI AppLayout hosts. The PageHeader stub exposes AppLayout's own onExportGoogleSlides as a
 * button and records every exportStatus it is shown. domWalker (the records pipeline's in-browser
 * extraction) is stubbed so a fallback, if one ran, would reach the records route instead of
 * rendering slides in jsdom.
 *
 * SABOTAGE (for the reviewer):
 *   - the client falling back on a 429 (`status === 503 || status === 429`) -> both tests RED.
 *   - a generic toast instead of the error's message                     -> "shows the detail" RED.
 */
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';

const BUSY = 'Exports are busy right now. Please try again in a minute.';
const HUASHU_ROUTE = '/api/export/google-slides/from-huashu';
const FALLBACK_STATUS = 'Falling back to records pipeline (slower)…';

const DECK = {
  title: 'Deck',
  slide_count: 1,
  css: '',
  external_scripts: [],
  scripts: '',
  version: 1,
  findings: [],
  slides: [{ index: 0, slide_id: 's1', html: '<div class="slide"><h1>One</h1></div>', scripts: '' }],
} as unknown as SlideDeck;

const h = vi.hoisted(() => ({
  apiSessionId: null as string | null,
  deck: null as SlideDeck | null,
  /** Every exportStatus the page header was rendered with. */
  exportStatuses: [] as Array<string | null | undefined>,
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
        session_id: id, title: 'Deck', messages: [], my_permission: 'CAN_EDIT',
        has_slide_deck: true, experiment_url: null,
        graph_version: 1, active_graph_version: 1, is_older_than_active: false, deck_mode: null,
      })),
      getSlides: fn(async (id: string) => ({ session_id: id, slide_deck: h.deck })),
      getCollaborationHistory: fn(async () => ({ mixed_release_warning: false, has_legacy_evidence: false, groups: [] })),
      listVersions: fn(async () => ({ versions: [], current_version: 1 })),
      createSession: fn(async ({ sessionId }: { sessionId?: string }) => ({
        session_id: sessionId ?? 'created', graph_version: 1, active_graph_version: 1, is_older_than_active: false,
      })),
      acquireEditingLock: fn(async () => ({ acquired: true, locked_by: null })),
      releaseEditingLock: fn(async () => undefined),
      heartbeatEditingLock: fn(async () => undefined),
      getEditingLockStatus: fn(async () => ({ locked: false, locked_by: null })),
      verifySlide: fn(async () => ({})),
      syncVersionVerification: fn(async () => undefined),
      checkGoogleSlidesAuth: fn(async () => ({ authorized: true, has_credentials: true })),
      // The real client: its 503-only fallback is what this file pins.
      exportToGoogleSlides: (...args: Parameters<typeof actual.api.exportToGoogleSlides>) =>
        actual.api.exportToGoogleSlides(...args),
    },
  };
});
vi.mock('../../services/domWalker', () => ({ extractSlideRecordsForExport: vi.fn(async () => []) }));
vi.mock('../../api/config', () => ({
  configApi: { listDeckContributors: vi.fn(async () => ({ contributors: [] })) },
}));

// The page header: AppLayout's own Google Slides export as a button, and the status it shows.
vi.mock('./page-header', () => ({
  PageHeader: ({ onExportGoogleSlides, exportStatus }: { onExportGoogleSlides?: () => void; exportStatus?: string | null }) => {
    h.exportStatuses.push(exportStatus);
    return (
      <header>
        {onExportGoogleSlides && (
          <button type="button" data-testid="export-google-slides" onClick={onExportGoogleSlides}>
            Google Slides
          </button>
        )}
      </header>
    );
  },
}));

// Leaf UI AppLayout hosts: inert.
vi.mock('../ChatPanel/ChatPanel', () => ({ ChatPanel: () => <div data-testid="chat-panel-stub" /> }));
vi.mock('../SlideViewer/SlideViewer', () => ({ SlideViewer: () => <div data-testid="viewer-stub" /> }));
vi.mock('./app-sidebar', () => ({ AppSidebar: () => <nav /> }));
vi.mock('../SavePoints', () => ({
  SavePointDropdown: () => null,
  PreviewBanner: () => null,
  RevertConfirmModal: () => null,
}));
vi.mock('@/ui/sidebar', () => ({
  SidebarProvider: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SidebarInset: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock('./simple-page-header', () => ({ SimplePageHeader: () => null }));
vi.mock('./GenieDataButton', () => ({ GenieDataButton: () => null }));
vi.mock('../SpecView/SpecView', () => ({ SpecView: () => null }));
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

type Call = { method: string; path: string };

/**
 * The server: the Google Slides Chrome route answers the busy 429; the records route (a fallback)
 * a presentation; anything else (AppLayout's current-user read) a user. Every request is recorded.
 */
function busyServer() {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname;
      calls.push({ method: (init?.method ?? 'GET').toUpperCase(), path });
      if (path === HUASHU_ROUTE) {
        return new Response(JSON.stringify({ detail: BUSY }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '60' },
        });
      }
      if (path === '/api/export/google-slides/from-records') {
        return new Response(
          JSON.stringify({ presentation_id: 'p1', presentation_url: 'https://docs.google.com/presentation/d/p1' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ username: 'me@example.com' }), { status: 200 });
    }),
  );
  return calls;
}

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });

/** Mount AppLayout on the deck's session and export it to Google Slides while the worker is busy. */
async function exportWhileBusy() {
  const calls = busyServer();
  render(
    <MemoryRouter initialEntries={['/sessions/sess-a/edit']}>
      <ToastProvider>
        <SessionProvider>
          <GenerationProvider>
            <Routes>
              <Route path="/sessions/:sessionId/edit" element={<AppLayout key="app-layout" initialView="main" />} />
            </Routes>
          </GenerationProvider>
        </SessionProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  await settle();
  await settle();
  await act(async () => { fireEvent.click(screen.getByTestId('export-google-slides')); });
  await settle();
  return { exportPosts: calls.filter((call) => call.method === 'POST').map((call) => call.path) };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  vi.spyOn(console, 'error').mockImplementation(() => {}); // AppLayout logs the failed export
  vi.spyOn(window, 'open').mockImplementation(() => null);
  h.apiSessionId = null;
  h.deck = DECK;
  h.exportStatuses = [];
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the Google Slides export while the worker is busy (429)', () => {
  it('shows the busy detail as it is, in an error toast', async () => {
    await exportWhileBusy();

    const toasts = screen.getAllByTestId('toast');
    expect(toasts).toHaveLength(1);
    expect(within(toasts[0]).getByText(BUSY)).toBeInTheDocument();
    expect(toasts[0]).toHaveClass('bg-red-600');
  });

  it('does not fall back to the records pipeline', async () => {
    const { exportPosts } = await exportWhileBusy();

    expect(exportPosts).toEqual([HUASHU_ROUTE]);
    expect(h.exportStatuses).not.toContain(FALLBACK_STATUS);
  });
});
