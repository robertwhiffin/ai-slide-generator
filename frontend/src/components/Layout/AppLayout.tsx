import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel, type ChatPanelHandle } from '../ChatPanel/ChatPanel';
import { SlidePanel, type SlidePanelHandle } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';
import { ProfileSelector } from '../config/ProfileSelector';
import { ProfileList } from '../config/ProfileList';
import { DeckPromptList } from '../config/DeckPromptList';
import { SlideStyleList } from '../config/SlideStyleList';
import { SessionHistory } from '../History/SessionHistory';
import { SaveAsDialog } from '../History/SaveAsDialog';
import { NotificationsPanel } from '../Notifications/NotificationsPanel';
import { ImageLibrary } from '../ImageLibrary/ImageLibrary';
import { HelpPage } from '../Help';
import { UpdateBanner } from '../UpdateBanner';
import { SavePointDropdown, PreviewBanner, RevertConfirmModal } from '../SavePoints';
import type { SavePointVersion } from '../SavePoints';
import { FeedbackButton } from '../Feedback/FeedbackButton';
import { SurveyModal } from '../Feedback/SurveyModal';
import { useSurveyTrigger } from '../../hooks/useSurveyTrigger';
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';
import { useProfiles } from '../../contexts/ProfileContext';
import { useVersionCheck } from '../../hooks/useVersionCheck';
import { useToast } from '../../contexts/ToastContext';
import { api } from '../../services/api';
import { SidebarProvider, SidebarInset } from '@/ui/sidebar';
import { AppSidebar } from './app-sidebar';
import { PageHeader } from './page-header';
import { SimplePageHeader } from './simple-page-header';

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'notifications' | 'help';

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
  const [showRevertModal, setShowRevertModal] = useState(false);
  const [revertTargetVersion, setRevertTargetVersion] = useState<number | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const slidePanelRef = useRef<SlidePanelHandle>(null);
  const slideDeckRef = useRef(slideDeck);
  slideDeckRef.current = slideDeck;
  const { sessionTitle, sessionId, createNewSession, switchSession, renameSession } = useSession();
  const { isGenerating } = useGeneration();
  const { currentProfile, loadProfile } = useProfiles();
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const currentProfileRef = useRef(currentProfile);
  currentProfileRef.current = currentProfile;
  const loadProfileRef = useRef(loadProfile);
  loadProfileRef.current = loadProfile;
  const { updateAvailable, latestVersion, updateType, dismissed, dismiss } = useVersionCheck();
  const { showToast } = useToast();
  const { showSurvey, closeSurvey, onGenerationComplete, onGenerationStart } = useSurveyTrigger();

  // Permission level for the current session (null until loaded from server)
  const [sessionPermission, setSessionPermission] = useState<'CAN_VIEW' | 'CAN_EDIT' | 'CAN_MANAGE' | null>(null);

  // Non-null when viewing a session whose profile has been deleted
  const [deletedProfileName, setDeletedProfileName] = useState<string | null>(null);

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

  // Main lock lifecycle: acquire on open, heartbeat, idle release, poll status
  useEffect(() => {
    if (!sessionId || initialView !== 'main' || sessionPermission === null) return;
    const isViewer = sessionPermission === 'CAN_VIEW';
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

    tryAcquire();

    const pollTimer = setInterval(async () => {
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
        const [status, slideResult] = await Promise.all([
          api.getEditingLockStatus(sessionId),
          api.getSlides(sessionId),
        ]);
        if (cancelled) return;

        if (slideResult.slide_deck && !isSelf(status)) {
          setSlideDeck(slideResult.slide_deck as SlideDeck);
        }

        applyStatus(status);

        if (!isViewer && !status.locked && lockSessionRef.current !== sessionId) {
          const idleMs = Date.now() - lastActivityRef.current;
          if (idleMs < IDLE_TIMEOUT_MS) {
            await tryAcquire();
          }
        }
      } catch { /* ignore */ }
    }, 10_000);

    return () => {
      cancelled = true;
      clearInterval(pollTimer);
      if (lockSessionRef.current === sessionId) {
        api.releaseEditingLock(sessionId);
        lockSessionRef.current = null;
      }
    };
  }, [sessionId, initialView, sessionPermission]);

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

  // When URL has sessionId, restore that session
  useEffect(() => {
    if (!urlSessionId) return;
    if (urlSessionId === sessionIdRef.current && slideDeckRef.current != null) return;
    let cancelled = false;
    (async () => {
      try {
        const sessionInfo = await api.getSession(urlSessionId);
        if (cancelled) return;

        // Store permission level from session info
        setSessionPermission(sessionInfo.my_permission || 'CAN_MANAGE');

        if (sessionInfo.profile_deleted) {
          setDeletedProfileName(
            sessionInfo.profile_name || `Profile ${sessionInfo.profile_id}`,
          );
        } else if (sessionInfo.profile_id && currentProfileRef.current && sessionInfo.profile_id !== currentProfileRef.current.id) {
          try {
            await loadProfileRef.current(sessionInfo.profile_id);
          } catch {
            // Profile may have been deleted; continue with current profile
          }
        }
        if (cancelled) return;

        const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(
          urlSessionId,
          { title: sessionInfo.title, has_slide_deck: sessionInfo.has_slide_deck },
          () => cancelled,
        );
        if (!cancelled) {
          setSlideDeck(restoredDeck);
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

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  // Clear preview when leaving session or switching deck
  useEffect(() => {
    setPreviewVersion(null);
    setPreviewDeck(null);
    setPreviewDescription('');
  }, [sessionId]);

  const handleSlideNavigate = useCallback((index: number) => {
    setScrollTarget(prev => ({ index, key: (prev?.key ?? 0) + 1 }));
  }, []);

  const handleSendMessage = useCallback((content: string, slideContext?: { indices: number[]; slide_htmls: string[] }) => {
    chatPanelRef.current?.sendMessage(content, slideContext);
  }, []);

  const handleProfileChange = useCallback(() => {
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    setDeletedProfileName(null);
    setSessionPermission('CAN_MANAGE');
    createNewSession();
  }, [createNewSession]);

  const handleSessionRestore = useCallback(
    (restoredSessionId: string) => {
      navigate(`/sessions/${restoredSessionId}/edit`);
    },
    [navigate],
  );

  const autoSaveSession = useCallback(async (deck: SlideDeck) => {
    if (!sessionId) return;

    try {
      const title = deck.title?.trim();
      const count = deck.slide_count ?? deck.slides?.length;
      if (title) {
        await renameSession(title, count);
      } else if (count != null) {
        await api.updateSession(sessionId, { slide_count: count });
      } else {
        return;
      }
      setLastSavedTime(new Date());
      setSessionsRefreshKey((prev) => prev + 1);
    } catch (err) {
      console.error('Failed to save session after generation:', err);
    }
  }, [sessionId, renameSession]);

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
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    setDeletedProfileName(null);
    setSessionPermission('CAN_MANAGE');
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
  }, []);

  const handleRevertConfirm = useCallback(async () => {
    if (!sessionId || revertTargetVersion == null || !isLockHolder) return;

    try {
      const result = await api.restoreVersion(sessionId, revertTargetVersion);
      setSlideDeck(result.deck);
      setPreviewVersion(null);
      setPreviewDeck(null);
      setPreviewDescription('');
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

  const effectiveReadOnly = !!previewVersion || viewOnly || !!deletedProfileName || sessionPermission === 'CAN_VIEW' || !isLockHolder;
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

  const getSubtitle = () => {
    if (!slideDeck) return undefined;
    const parts = [`${slideDeck.slide_count} slide${slideDeck.slide_count !== 1 ? 's' : ''}`];

    if (lastSavedTime) {
      parts.push(`Saved ${getTimeAgo(lastSavedTime)}`);
    }

    if (isGenerating) parts.push('Generating...');

    return parts.join(' • ');
  };

  const displayDeck = previewVersion != null && previewDeck ? previewDeck : slideDeck;

  const handleExportPPTX = useCallback(() => {
    slidePanelRef.current?.exportPPTX();
  }, []);

  const handleExportPDF = useCallback(() => {
    slidePanelRef.current?.exportPDF();
  }, []);

  const handleExportGoogleSlides = useCallback(async () => {
    if (!sessionId || !slideDeck) return;
    try {
      setExportStatus('Exporting to Google Slides…');
      const { presentation_url } = await api.exportToGoogleSlides(
        sessionId,
        slideDeck,
        (_progress, _total, status) => setExportStatus(status || 'Exporting…')
      );
      setExportStatus(null);
      showToast('Export complete', 'success');
      if (presentation_url) {
        window.open(presentation_url, '_blank');
      }
    } catch (err) {
      console.error('Google Slides export failed:', err);
      setExportStatus(null);
      showToast('Export to Google Slides failed', 'error');
    }
  }, [sessionId, slideDeck, showToast]);

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
      else if (view === 'notifications') navigate('/notifications');
    },
    [navigate]
  );

  const viewOnlyReason =
    !isLockHolder && editingLockHolder
      ? `${editingLockHolder} is currently editing this session`
      : sessionPermission === 'CAN_VIEW'
      ? 'You have view-only access to this session'
      : deletedProfileName
      ? `Profile "${deletedProfileName}" was deleted — session is read-only`
      : undefined;

  return (
    <SidebarProvider className="h-svh max-h-svh">
      <AppSidebar
        currentView={viewMode}
        onViewChange={handleViewChange}
        onSessionSelect={handleSessionRestore}
        onNewSession={handleNewSession}
        currentSessionId={sessionId}
        profileName={currentProfile?.name}
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
                onExportPPTX={slideDeck ? handleExportPPTX : undefined}
                onExportPDF={slideDeck ? handleExportPDF : undefined}
                onExportGoogleSlides={slideDeck ? handleExportGoogleSlides : undefined}
                onPresent={slideDeck ? handlePresent : undefined}
                isGenerating={isGenerating}
                viewOnly={viewOnly}
                exportStatus={exportStatus}
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
                profileSelector={
                  <ProfileSelector
                    onManageClick={() => setViewMode('profiles')}
                    onProfileChange={handleProfileChange}
                    disabled={isGenerating}
                  />
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

              {deletedProfileName && (
                <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-sm text-amber-800 flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                  </svg>
                  <span>
                    This session was created with profile &ldquo;{deletedProfileName}&rdquo; which has been deleted.
                    The session is read-only and cannot continue.
                  </span>
                </div>
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
                <div className="w-[32%] min-w-[260px] border-r border-border bg-card">
                  <ChatPanel
                    key="chat-panel"
                    ref={chatPanelRef}
                    rawHtml={rawHtml}
                    disabled={isReadOnly}
                    onGenerationStart={onGenerationStart}
                    onSlidesGenerated={async (deck, raw) => {
                      onGenerationComplete();
                      setSlideDeck(deck);
                      setRawHtml(raw);
                      autoSaveSession(deck);
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

                <SelectionRibbon
                  slideDeck={displayDeck}
                  onSlideNavigate={handleSlideNavigate}
                  versionKey={versionKey}
                />

                <div className="flex-1 bg-background">
                  <SlidePanel
                    ref={slidePanelRef}
                    slideDeck={displayDeck}
                    rawHtml={rawHtml}
                    onSlideChange={isReadOnly ? undefined : setSlideDeck}
                    scrollToSlide={scrollTarget}
                    onSendMessage={isReadOnly ? undefined : handleSendMessage}
                    onExportStatusChange={setExportStatus}
                    versionKey={versionKey}
                    readOnly={isReadOnly}
                    canManage={sessionPermission === 'CAN_MANAGE'}
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
                  activeProfileId={currentProfile?.id}
                />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'profiles' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="Agent Profiles" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <ProfileList onProfileChange={handleProfileChange} />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'notifications' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="Notifications" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <NotificationsPanel />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'deck_prompts' && (
          <div className="flex h-full flex-col">
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
          <div className="flex h-full flex-col">
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
          <div className="flex h-full flex-col">
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
          <div className="flex h-full flex-col">
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

      <FeedbackButton />
      <SurveyModal isOpen={showSurvey} onClose={closeSurvey} />
    </SidebarProvider>
  );
};
