import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel, type ChatPanelHandle } from '../ChatPanel/ChatPanel';
import { SlidePanel, type SlidePanelHandle } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';
import { AgentConfigBar } from '../AgentConfigBar/AgentConfigBar';
import { ProfileList } from '../config/ProfileList';
import { DeckPromptList } from '../config/DeckPromptList';
import { SlideStyleList } from '../config/SlideStyleList';
import { SessionHistory } from '../History/SessionHistory';
import { SaveAsDialog } from '../History/SaveAsDialog';
import { ImageLibrary } from '../ImageLibrary/ImageLibrary';
import { HelpPage } from '../Help';
import { UpdateBanner } from '../UpdateBanner';
import { SavePointDropdown, PreviewBanner, RevertConfirmModal } from '../SavePoints';
import type { SavePointVersion } from '../SavePoints';
import { DeckContributorsManager } from '../DeckContributorsManager';
import { FeedbackButton } from '../Feedback/FeedbackButton';
import { SurveyModal } from '../Feedback/SurveyModal';
import { useSurveyTrigger } from '../../hooks/useSurveyTrigger';
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';
import { ProfileProvider } from '../../contexts/ProfileContext';
import { useVersionCheck } from '../../hooks/useVersionCheck';
import { useToast } from '../../contexts/ToastContext';
import { useGoogleOAuthPopup } from '../../hooks/useGoogleOAuthPopup';
import { api } from '../../services/api';
import { configApi } from '../../api/config';
import { SidebarProvider, SidebarInset } from '@/ui/sidebar';
import { AppSidebar } from './app-sidebar';
import { PageHeader } from './page-header';
import { SimplePageHeader } from './simple-page-header';
import { GenieDataButton } from './GenieDataButton';

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'help';

interface AppLayoutProps {
  initialView?: ViewMode;
  viewOnly?: boolean;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ initialView = 'help', viewOnly = false }) => {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(initialView);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showShareDialog, setShowShareDialog] = useState(false);
  const [lastSavedTime, setLastSavedTime] = useState<Date | null>(null);
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState<number>(0);
  const [scrollTarget, setScrollTarget] = useState<{ index: number; key: number } | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);
  // Save Points / versioning
  const [versions, setVersions] = useState<SavePointVersion[]>([]);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [previewDeck, setPreviewDeck] = useState<SlideDeck | null>(null);
  const [previewDescription, setPreviewDescription] = useState<string>('');
  const [previewMessages, setPreviewMessages] = useState<import('../../types/message').Message[] | null>(null);
  const [showRevertModal, setShowRevertModal] = useState(false);
  const [revertTargetVersion, setRevertTargetVersion] = useState<number | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const slidePanelRef = useRef<SlidePanelHandle>(null);
  const slideDeckRef = useRef(slideDeck);
  slideDeckRef.current = slideDeck;
  const deckVersionRef = useRef<number>(0);

  const loadVersionsRef = useRef<(() => Promise<void>) | null>(null);

  const setSlideDeckGated = useCallback((newDeck: SlideDeck, serverVersion?: number, force = false) => {
    if (!force && serverVersion != null && serverVersion < deckVersionRef.current) {
      console.log(`[deckVersionGuard] Rejected stale deck: server v${serverVersion} < local v${deckVersionRef.current}`);
      return;
    }
    const versionBumped = serverVersion != null && serverVersion > deckVersionRef.current;
    if (serverVersion != null) {
      deckVersionRef.current = serverVersion;
    }
    setSlideDeck(newDeck);
    // Refresh version list whenever deck version bumps (covers reorder, delete, duplicate)
    if (versionBumped || force) {
      loadVersionsRef.current?.();
    }
  }, []);
  const { sessionTitle, sessionId, experimentUrl, createNewSession, switchSession, renameSession } = useSession();
  const { isGenerating } = useGeneration();
  /** Ref-tracked sessionId so the URL effect guard doesn't need sessionId as a dep (which would cause it to re-fire when switchSession internally calls setSessionId). */
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const { updateAvailable, latestVersion, updateType, dismissed, dismiss } = useVersionCheck();
  const { showToast } = useToast();
  const { openOAuthPopup } = useGoogleOAuthPopup();
  const { showSurvey, closeSurvey, onGenerationComplete, onGenerationStart } = useSurveyTrigger();

  // Editing lock state (default false until acquire succeeds)
  const [editingLockHolder, setEditingLockHolder] = useState<string | null>(null);
  const [isLockHolder, setIsLockHolder] = useState(false);
  const lockSessionRef = useRef<string | null>(null);
  const currentUserEmailRef = useRef<string | null>(null);
  const lastActivityRef = useRef<number>(Date.now());
  const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

  // Fetch current user email once for lock comparison
  useEffect(() => {
    fetch('/api/user/current').then(r => r.json()).then(data => {
      currentUserEmailRef.current = data.username || null;
    }).catch(() => {});
  }, []);

  // Track user activity (mouse, keyboard, scroll) to detect idle
  useEffect(() => {
    const markActive = () => { lastActivityRef.current = Date.now(); };
    window.addEventListener('mousemove', markActive);
    window.addEventListener('keydown', markActive);
    window.addEventListener('scroll', markActive, true);
    return () => {
      window.removeEventListener('mousemove', markActive);
      window.removeEventListener('keydown', markActive);
      window.removeEventListener('scroll', markActive, true);
    };
  }, []);

  // Main lock lifecycle: acquire on open, heartbeat, idle release, poll status.
  // Skipped entirely for unshared sessions (no contributors) to avoid idle API traffic.
  useEffect(() => {
    if (!sessionId || initialView !== 'main') return;

    // New session (no URL session ID) — not persisted to DB yet, so no lock needed.
    if (!urlSessionId) {
      setIsLockHolder(true);
      setEditingLockHolder(null);
      return;
    }

    const isViewer = false;
    let cancelled = false;

    const isSelf = (status: { locked_by_email?: string | null }) =>
      lockSessionRef.current === sessionId ||
      (currentUserEmailRef.current != null && status.locked_by_email === currentUserEmailRef.current);

    const applyStatus = (status: { locked: boolean; locked_by: string | null; locked_by_email?: string | null }) => {
      if (!status.locked) {
        if (lockSessionRef.current === sessionId) lockSessionRef.current = null;
        setIsLockHolder(!isViewer);
        setEditingLockHolder(null);
      } else if (isSelf(status)) {
        lockSessionRef.current = sessionId;
        setIsLockHolder(true);
        setEditingLockHolder(null);
      } else {
        setIsLockHolder(false);
        setEditingLockHolder(isViewer ? null : status.locked_by);
      }
    };

    const tryAcquire = async () => {
      if (isViewer) return;
      try {
        const result = await api.acquireEditingLock(sessionId);
        if (!cancelled) {
          if (result.acquired) {
            lockSessionRef.current = sessionId;
            setIsLockHolder(true);
            setEditingLockHolder(null);
          } else {
            setIsLockHolder(false);
            setEditingLockHolder(result.locked_by);
          }
        }
      } catch { /* ignore */ }
    };

    const timers: ReturnType<typeof setInterval>[] = [];

    // Check if session is shared before starting lock polling
    configApi.listDeckContributors(sessionId).then(({ contributors }) => {
      if (cancelled) return;

      if (contributors.length === 0) {
        // Unshared session — no contention possible, grant lock immediately
        setIsLockHolder(true);
        setEditingLockHolder(null);
        return;
      }

      // Shared session — full lock lifecycle
      tryAcquire();

      timers.push(setInterval(async () => {
        if (cancelled) return;

        if (!isViewer && lockSessionRef.current === sessionId) {
          const idleMs = Date.now() - lastActivityRef.current;
          if (idleMs >= IDLE_TIMEOUT_MS) {
            try { await api.releaseEditingLock(sessionId); } catch { /* ignore */ }
            lockSessionRef.current = null;
            setIsLockHolder(true);
            setEditingLockHolder(null);
            return;
          }
          try { await api.heartbeatEditingLock(sessionId); } catch { /* ignore */ }
        }

        try {
          const status = await api.getEditingLockStatus(sessionId);
          if (cancelled) return;

          applyStatus(status);

          if (!isViewer && !status.locked && lockSessionRef.current !== sessionId) {
            const idleMs = Date.now() - lastActivityRef.current;
            if (idleMs < IDLE_TIMEOUT_MS) {
              await tryAcquire();
            }
          }
        } catch { /* ignore */ }
      }, 10_000));

    }).catch(() => {
      // If contributor check fails, fall back to full lock lifecycle for safety
      if (cancelled) return;
      tryAcquire();

      timers.push(setInterval(async () => {
        if (cancelled) return;

        if (!isViewer && lockSessionRef.current === sessionId) {
          const idleMs = Date.now() - lastActivityRef.current;
          if (idleMs >= IDLE_TIMEOUT_MS) {
            try { await api.releaseEditingLock(sessionId); } catch { /* ignore */ }
            lockSessionRef.current = null;
            setIsLockHolder(true);
            setEditingLockHolder(null);
            return;
          }
          try { await api.heartbeatEditingLock(sessionId); } catch { /* ignore */ }
        }

        try {
          const status = await api.getEditingLockStatus(sessionId);
          if (cancelled) return;
          applyStatus(status);

          if (!isViewer && !status.locked && lockSessionRef.current !== sessionId) {
            const idleMs = Date.now() - lastActivityRef.current;
            if (idleMs < IDLE_TIMEOUT_MS) {
              await tryAcquire();
            }
          }
        } catch { /* ignore */ }
      }, 10_000));
    });

    return () => {
      cancelled = true;
      timers.forEach(t => clearInterval(t));
      if (lockSessionRef.current === sessionId) {
        api.releaseEditingLock(sessionId);
        lockSessionRef.current = null;
      }
    };
  }, [sessionId, initialView, urlSessionId]);

  // Release lock on page unload (tab close, refresh)
  useEffect(() => {
    const handleUnload = () => {
      if (lockSessionRef.current) {
        api.releaseEditingLock(lockSessionRef.current);
        lockSessionRef.current = null;
      }
    };
    window.addEventListener('beforeunload', handleUnload);
    return () => window.removeEventListener('beforeunload', handleUnload);
  }, []);

  // Sync viewMode when initialView changes (e.g. route change)
  useEffect(() => {
    setViewMode(initialView);
  }, [initialView]);

  // Allow the app tour to navigate back to the main view via a custom DOM event
  useEffect(() => {
    const handler = () => {
      setViewMode('main');
      navigate('/');
    };
    window.addEventListener('tour:navigate-main', handler);
    return () => window.removeEventListener('tour:navigate-main', handler);
  }, [navigate]);

  // Allow the app tour to load a pre-built demo deck via a custom DOM event
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId } = (e as CustomEvent).detail;
      if (sessionId) {
        setViewMode('main');
        navigate(`/sessions/${sessionId}/edit`);
      }
    };
    window.addEventListener('tour:load-demo-deck', handler);
    return () => window.removeEventListener('tour:load-demo-deck', handler);
  }, [navigate]);

  // After tour phase 2 adds slides+messages, re-navigate to reload everything
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId: sid } = (e as CustomEvent).detail;
      if (!sid) return;
      navigate('/', { replace: true });
      setTimeout(() => navigate(`/sessions/${sid}/edit`, { replace: true }), 50);
    };
    window.addEventListener('tour:refresh-session', handler);
    return () => window.removeEventListener('tour:refresh-session', handler);
  }, [navigate]);

  // Tour finished: leave the demo session in the UI, then the tour deletes it in the background
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId: deletedId } = (e as CustomEvent<{ sessionId: string }>).detail;
      if (!deletedId) return;

      const viewingDeleted = urlSessionId === deletedId || sessionId === deletedId;
      if (viewingDeleted) {
        api.releaseEditingLock(deletedId);
        if (urlSessionId === deletedId) {
          navigate('/', { replace: true });
        }
        createNewSession();
        setSlideDeck(null);
        setRawHtml(null);
        setLastSavedTime(null);
        deckVersionRef.current = 0;
      }
      setSessionsRefreshKey(k => k + 1);
    };
    window.addEventListener('tour:demo-session-deleted', handler);
    return () => window.removeEventListener('tour:demo-session-deleted', handler);
  }, [navigate, createNewSession, urlSessionId, sessionId]);

  // When URL has sessionId, restore that session (load deck if we don't have it yet).
  // sessionId is intentionally NOT in deps — we use sessionIdRef.current in the guard instead.
  // This prevents the effect from re-firing when switchSession internally calls setSessionId,
  // which would cancel the in-flight load and trigger another one, causing chat to reload 3×.
  useEffect(() => {
    if (!urlSessionId) return;
    if (urlSessionId === sessionIdRef.current && slideDeckRef.current != null) return;
    let cancelled = false;
    (async () => {
      try {
        // Fetch session info first so we can pass it to switchSession as existingSessionInfo
        // to avoid a second getSession call.
        const sessionInfo = await api.getSession(urlSessionId);
        if (cancelled) return;

        const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(
          urlSessionId,
          { title: sessionInfo.title, has_slide_deck: sessionInfo.has_slide_deck, experiment_url: sessionInfo.experiment_url },
          () => cancelled,
        );
        if (!cancelled) {
          if (restoredDeck) {
            setSlideDeckGated(restoredDeck, (restoredDeck as SlideDeck)?.version, true);
          } else {
            setSlideDeck(null);
          }
          setRawHtml(restoredRawHtml);
          setLastSavedTime(new Date());
          setViewMode('main');
        }
      } catch (err: unknown) {
        if (!cancelled && err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 404) {
          showToast('Session not found', 'error');
          navigate('/help');
          return;
        }
        console.error('Failed to restore session from URL:', err);
      }
    })();
    return () => { cancelled = true; };
  }, [urlSessionId, showToast, navigate, switchSession]);

  // Load save point versions when session or deck changes
  const loadVersions = useCallback(async () => {
    if (!sessionId) {
      setVersions([]);
      setCurrentVersion(null);
      return;
    }
    try {
      const { versions: v, current_version: cv } = await api.listVersions(sessionId);
      setVersions(v);
      setCurrentVersion(cv);
    } catch (err) {
      console.warn('Failed to list versions:', err);
      setVersions([]);
      setCurrentVersion(null);
    }
  }, [sessionId]);
  loadVersionsRef.current = loadVersions;

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  // Clear preview when leaving session or switching deck
  useEffect(() => {
    setPreviewVersion(null);
    setPreviewDeck(null);
    setPreviewDescription('');
    deckVersionRef.current = 0;
  }, [sessionId]);

  const handleSlideNavigate = useCallback((index: number) => {
    setScrollTarget(prev => ({ index, key: (prev?.key ?? 0) + 1 }));
  }, []);

  const handleSendMessage = useCallback((content: string, slideContext?: { indices: number[]; slide_htmls: string[] }) => {
    chatPanelRef.current?.sendMessage(content, slideContext);
  }, []);

  const handleSessionRestore = useCallback(
    (restoredSessionId: string) => {
      navigate(`/sessions/${restoredSessionId}/edit`);
    },
    [navigate],
  );

  // Handle title change from header
  const handleTitleChange = useCallback(async (newTitle: string) => {
    try {
      await renameSession(newTitle);
      setLastSavedTime(new Date());
      if (slideDeck) {
        setSlideDeck({ ...slideDeck, title: newTitle });
      }
      setSessionsRefreshKey(prev => prev + 1);
    } catch (err) {
      console.error('Failed to update title:', err);
      alert('Failed to update title');
    }
  }, [renameSession, slideDeck]);

  const handleNewSession = useCallback(async () => {
    deckVersionRef.current = 0;
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    const newId = createNewSession();
    setViewMode('main');
    try {
      await api.createSession({ sessionId: newId });
      setSessionsRefreshKey(prev => prev + 1);
      navigate(`/sessions/${newId}/edit`);
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }, [createNewSession, navigate]);

  const handleSaveAs = useCallback(async (title: string) => {
    try {
      await renameSession(title);
      setShowSaveDialog(false);
      setLastSavedTime(new Date());
      setSessionsRefreshKey((k) => k + 1);
    } catch (err) {
      console.error('Failed to save session:', err);
      alert('Failed to save session name');
    }
  }, [renameSession]);

  const handleShare = useCallback(() => {
    if (!sessionId) return;
    setShowShareDialog(true);
  }, [sessionId]);

  const handleCopyLink = useCallback(() => {
    if (!sessionId) return;
    const viewUrl = `${window.location.origin}/sessions/${sessionId}/view`;
    navigator.clipboard.writeText(viewUrl).then(
      () => showToast('Link copied to clipboard', 'success'),
      () => showToast('Failed to copy link', 'error')
    );
  }, [sessionId, showToast]);

  // Save Points: preview a version
  const handlePreviewVersion = useCallback(async (versionNumber: number) => {
    if (!sessionId) return;
    try {
      const result = await api.previewVersion(sessionId, versionNumber);
      setPreviewVersion(result.version_number);
      setPreviewDeck(result.deck);
      setPreviewDescription(result.description || '');
      // Map backend chat_history to Message[] for preview
      const chatHistory = result.chat_history;
      if (Array.isArray(chatHistory) && chatHistory.length > 0) {
        setPreviewMessages(chatHistory.map((m: any) => ({
          role: m.role || 'assistant',
          content: m.content || '',
          timestamp: m.created_at || new Date().toISOString(),
        })));
      } else {
        setPreviewMessages(null);
      }
    } catch (err) {
      console.error('Failed to preview version:', err);
      showToast('Failed to load version', 'error');
    }
  }, [sessionId, showToast]);

  const handleRevertClick = useCallback(() => {
    if (previewVersion == null) return;
    setRevertTargetVersion(previewVersion);
    setShowRevertModal(true);
  }, [previewVersion]);

  const handlePreviewCancel = useCallback(() => {
    setPreviewVersion(null);
    setPreviewDeck(null);
    setPreviewDescription('');
    setPreviewMessages(null);
  }, []);

  const handleRevertConfirm = useCallback(async () => {
    if (!sessionId || revertTargetVersion == null || !isLockHolder) return;

    try {
      const result = await api.restoreVersion(sessionId, revertTargetVersion);
      setSlideDeckGated(result.deck, undefined, true);
      setPreviewVersion(null);
      setPreviewDeck(null);
      setPreviewDescription('');
      setPreviewMessages(null);
      setShowRevertModal(false);
      setRevertTargetVersion(null);
      setLastSavedTime(new Date());
      setSessionsRefreshKey((k) => k + 1);
      await loadVersions();
    } catch (err) {
      console.error('Failed to revert:', err);
      showToast('Failed to revert to version', 'error');
    }
  }, [sessionId, revertTargetVersion, isLockHolder, loadVersions, showToast]);

  const handleVerificationComplete = useCallback(async () => {
    if (!sessionId) return;
    try {
      await api.syncVersionVerification(sessionId);
      const { versions: v, current_version: cv } = await api.listVersions(sessionId);
      setVersions(v);
      setCurrentVersion(cv);
    } catch (err) {
      console.error('Failed to sync verification to save point:', err);
    }
  }, [sessionId]);

  const versionKey = previewVersion != null
    ? `preview-v${previewVersion}`
    : 'current';

  const effectiveReadOnly = !!previewVersion || viewOnly || !isLockHolder;
  const isReadOnly = effectiveReadOnly;

  const getTimeAgo = (date: Date) => {
    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);
    if (seconds < 60) return 'Just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  };

  // Generate subtitle for page header with status
  const getSubtitle = (): React.ReactNode | undefined => {
    if (!slideDeck) return undefined;
    const slideCount = `${slideDeck.slide_count} slide${slideDeck.slide_count !== 1 ? 's' : ''}`;
    const saved = lastSavedTime ? `Saved ${getTimeAgo(lastSavedTime)}` : null;

    return (
      <>
        {slideCount}
        {experimentUrl && (
          <>
            {' \u2022 '}
            <a href={experimentUrl} target="_blank" rel="noopener noreferrer" className="hover:underline text-primary">
              Agent Trace
            </a>
          </>
        )}
        {saved && ` \u2022 ${saved}`}
        {isGenerating && ' \u2022 Generating...'}
      </>
    );
  };

  const displayDeck = previewVersion != null && previewDeck ? previewDeck : slideDeck;

  const handleExportPPTX = useCallback(() => {
    slidePanelRef.current?.exportPPTX();
  }, []);

  const handleExportPDF = useCallback(() => {
    slidePanelRef.current?.exportPDF();
  }, []);

  const handleExportHTML = useCallback(() => {
    slidePanelRef.current?.exportHTML();
  }, []);

  const handleExportGoogleSlides = useCallback(async () => {
    if (!sessionId || !slideDeck) return;
    try {
      // Check auth first
      const { authorized } = await api.checkGoogleSlidesAuth();

      if (!authorized) {
        setExportStatus('Waiting for Google authorization...');
        const authResult = await openOAuthPopup();
        if (!authResult) {
          setExportStatus(null);
          showToast('Google authorization was not completed. Please try again.', 'error');
          return;
        }
      }

      setExportStatus('Exporting to Google Slides…');
      const { presentation_url, alreadyOpened } = await api.exportToGoogleSlides(
        sessionId,
        slideDeck,
        (_progress, _total, status) => setExportStatus(status || 'Exporting…')
      );
      setExportStatus(null);
      showToast('Export complete', 'success');
      if (presentation_url && !alreadyOpened) {
        window.open(presentation_url, '_blank');
      }
    } catch (err) {
      console.error('Google Slides export failed:', err);
      setExportStatus(null);
      showToast('Export to Google Slides failed', 'error');
    }
  }, [sessionId, slideDeck, showToast, openOAuthPopup]);

  const handlePresent = useCallback(() => {
    slidePanelRef.current?.openPresentationMode();
  }, []);

  const handleViewChange = useCallback(
    (view: ViewMode) => {
      setViewMode(view);
      if (view === 'help') navigate('/help');
      else if (view === 'profiles') navigate('/profiles');
      else if (view === 'deck_prompts') navigate('/deck-prompts');
      else if (view === 'slide_styles') navigate('/slide-styles');
      else if (view === 'images') navigate('/images');
      else if (view === 'history') navigate('/history');
    },
    [navigate]
  );

  const viewOnlyReason =
    !isLockHolder && editingLockHolder
      ? `${editingLockHolder} is currently editing this session`
      : undefined;

  return (
    <SidebarProvider className="h-svh max-h-svh">
      <AppSidebar
        currentView={viewMode}
        onViewChange={handleViewChange}
        onSessionSelect={handleSessionRestore}
        onNewSession={handleNewSession}
        currentSessionId={sessionId}
        sessionsRefreshKey={sessionsRefreshKey}
      />
      <SidebarInset className="h-full overflow-hidden">
        {viewMode === 'main' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <PageHeader
                title={sessionTitle || slideDeck?.title || 'Untitled session'}
                subtitle={getSubtitle()}
                onTitleChange={handleTitleChange}
                onSave={() => setShowSaveDialog(true)}
                onShare={!viewOnly && sessionId ? handleShare : undefined}
                onCopyLink={!viewOnly && sessionId ? handleCopyLink : undefined}
                onExportPPTX={slideDeck ? handleExportPPTX : undefined}
                onExportPDF={slideDeck ? handleExportPDF : undefined}
                onExportHTML={slideDeck ? handleExportHTML : undefined}
                onExportGoogleSlides={slideDeck ? handleExportGoogleSlides : undefined}
                onPresent={slideDeck ? handlePresent : undefined}
                isGenerating={isGenerating}
                viewOnly={viewOnly}
                exportStatus={exportStatus}
                centerSlot={<GenieDataButton />}
                savePointDropdown={
                  sessionId && slideDeck && versions.length > 0 ? (
                    <SavePointDropdown
                      versions={versions}
                      currentVersion={currentVersion}
                      previewVersion={previewVersion}
                      onPreview={handlePreviewVersion}
                      onRevert={handleRevertClick}
                      disabled={isGenerating || !isLockHolder}
                      minimal
                    />
                  ) : undefined
                }
              />

              {previewVersion != null && (
                <PreviewBanner
                  versionNumber={previewVersion}
                  description={previewDescription}
                  onRevert={isLockHolder ? handleRevertClick : () => {}}
                  onCancel={handlePreviewCancel}
                />
              )}

              {updateAvailable && !dismissed && latestVersion && updateType && (
                <UpdateBanner
                  latestVersion={latestVersion}
                  updateType={updateType}
                  onDismiss={dismiss}
                />
              )}
            </div>

            <div className="relative flex-1 overflow-hidden">
              <div className="absolute inset-0 flex">
                <div className="w-[32%] min-w-[260px] border-r border-border bg-card flex flex-col" data-tour="chat-panel">
                  <div className="shrink-0 relative z-10 overflow-visible" data-tour="agent-config">
                    <AgentConfigBar />
                  </div>
                  <ChatPanel
                    key="chat-panel"
                    ref={chatPanelRef}
                    rawHtml={rawHtml}
                    disabled={isReadOnly}
                    onGenerationStart={onGenerationStart}
                    previewMessages={previewVersion != null ? previewMessages : null}
                    onSlidesGenerated={async (deck, raw) => {
                      onGenerationComplete();
                      setSlideDeckGated(deck, deck.version);
                      setRawHtml(raw);
                      setLastSavedTime(new Date());
                      setSessionsRefreshKey((prev) => prev + 1);
                      if (sessionId) {
                        try {
                          await loadVersions();
                        } catch (e) {
                          console.warn('Failed to refresh versions:', e);
                        }
                      }
                    }}
                    viewOnlyReason={viewOnlyReason}
                  />
                </div>

                <div data-tour="selection-ribbon">
                  <SelectionRibbon
                    key={versionKey}
                    slideDeck={displayDeck}
                    onSlideNavigate={handleSlideNavigate}
                    versionKey={versionKey}
                  />
                </div>

                <div className="flex-1 bg-background" data-tour="slide-panel">
                  <SlidePanel
                    key={versionKey}
                    ref={slidePanelRef}
                    slideDeck={displayDeck}
                    rawHtml={rawHtml}
                    onSlideChange={isReadOnly ? undefined : (deck: SlideDeck) => {
                      setSlideDeckGated(deck, deck.version);
                    }}
                    scrollToSlide={scrollTarget}
                    onSendMessage={isReadOnly ? undefined : handleSendMessage}
                    onExportStatusChange={setExportStatus}
                    versionKey={versionKey}
                    readOnly={isReadOnly}
                    lockedBy={!isLockHolder ? editingLockHolder : null}
                    onVerificationComplete={handleVerificationComplete}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'history' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="Sessions" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <SessionHistory
                  onSessionSelect={handleSessionRestore}
                  onBack={() => setViewMode('main')}
                  refreshKey={sessionsRefreshKey}
                />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'profiles' && (
          <div className="flex h-full flex-col" data-tour="page-profiles">
            <div className="shrink-0">
              <SimplePageHeader title="Agent Profiles" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <ProfileProvider>
                  <ProfileList />
                </ProfileProvider>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'deck_prompts' && (
          <div className="flex h-full flex-col" data-tour="page-deck-prompts">
            <div className="shrink-0">
              <SimplePageHeader title="Deck Prompts" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <DeckPromptList />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'slide_styles' && (
          <div className="flex h-full flex-col" data-tour="page-slide-styles">
            <div className="shrink-0">
              <SimplePageHeader title="Slide Styles" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <SlideStyleList />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'images' && (
          <div className="flex h-full flex-col" data-tour="page-images">
            <div className="shrink-0">
              <SimplePageHeader title="Image library" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <ImageLibrary />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'help' && (
          <div className="flex h-full flex-col" data-tour="page-help">
            <div className="shrink-0">
              <SimplePageHeader title="Help" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <HelpPage />
              </div>
            </div>
          </div>
        )}
      </SidebarInset>

      <SaveAsDialog
        isOpen={showSaveDialog}
        currentTitle={sessionTitle || slideDeck?.title || 'Untitled session'}
        onSave={handleSaveAs}
        onCancel={() => setShowSaveDialog(false)}
      />

      <RevertConfirmModal
        isOpen={showRevertModal}
        versionNumber={revertTargetVersion ?? 0}
        description={previewDescription}
        currentVersion={currentVersion ?? 0}
        onConfirm={handleRevertConfirm}
        onCancel={() => {
          setShowRevertModal(false);
          setRevertTargetVersion(null);
        }}
      />

      {/* Share Deck Dialog */}
      {showShareDialog && sessionId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-lg mx-4 rounded-lg border border-border bg-card shadow-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <h2 className="text-lg font-semibold text-foreground">Share Deck</h2>
              <button
                onClick={() => setShowShareDialog(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <DeckContributorsManager sessionId={sessionId} />
            </div>
          </div>
        </div>
      )}

      <FeedbackButton />
      <SurveyModal isOpen={showSurvey} onClose={closeSurvey} />
    </SidebarProvider>
  );
};
