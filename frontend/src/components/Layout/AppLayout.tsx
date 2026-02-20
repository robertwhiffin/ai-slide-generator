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
  const [lastSavedTime, setLastSavedTime] = useState<Date | null>(null);
  // Key to trigger session list refresh in sidebar and history
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState<number>(0);
  // Key to force remount ChatPanel when profile/session changes
  const [chatKey, setChatKey] = useState<number>(0);
  // Track which slide to scroll to in the main panel (uses key to allow re-scroll to same index)
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
  const { sessionTitle, sessionId, createNewSession, switchSession, renameSession } = useSession();
  const { isGenerating } = useGeneration();
  const { currentProfile, loadProfile } = useProfiles();
  const { updateAvailable, latestVersion, updateType, dismissed, dismiss } = useVersionCheck();
  const { showToast } = useToast();
  const { showSurvey, closeSurvey, onGenerationComplete, onGenerationStart } = useSurveyTrigger();

  // Sync viewMode when initialView changes (e.g. route change)
  useEffect(() => {
    setViewMode(initialView);
  }, [initialView]);

  // When URL has sessionId, restore that session
  useEffect(() => {
    if (!urlSessionId) return;
    if (urlSessionId === sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(urlSessionId);
        if (!cancelled) {
          setSlideDeck(restoredDeck);
          setRawHtml(restoredRawHtml);
          setLastSavedTime(new Date());
          setChatKey((k) => k + 1);
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
  }, [urlSessionId, showToast, navigate]); // eslint-disable-line react-hooks/exhaustive-deps -- only run when URL segment changes

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

  // Handle navigation from ribbon to main slide panel
  const handleSlideNavigate = useCallback((index: number) => {
    setScrollTarget(prev => ({ index, key: (prev?.key ?? 0) + 1 }));
  }, []);

  // Send a message through the chat panel (used by SlidePanel for optimize layout)
  const handleSendMessage = useCallback((content: string, slideContext?: { indices: number[]; slide_htmls: string[] }) => {
    chatPanelRef.current?.sendMessage(content, slideContext);
  }, []);

  // Reset chat state and create new session when profile changes
  const handleProfileChange = useCallback(() => {
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    setChatKey(prev => prev + 1);
    // Create new session for the new profile
    createNewSession();
  }, [createNewSession]);

  // Handle restoring a session from history
  // Auto-switches profile if the session belongs to a different profile
  const handleSessionRestore = useCallback(async (restoredSessionId: string) => {
    try {
      // First, get the session info to check its profile
      const sessionInfo = await api.getSession(restoredSessionId);

      // If session has a profile_id and it's different from current, switch profiles first
      if (sessionInfo.profile_id && currentProfile && sessionInfo.profile_id !== currentProfile.id) {
        await loadProfile(sessionInfo.profile_id);
      }

      const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(restoredSessionId);
      setSlideDeck(restoredDeck);
      setRawHtml(restoredRawHtml);
      setLastSavedTime(new Date());
      setChatKey((k) => k + 1);
      setViewMode('main');
      navigate(`/sessions/${restoredSessionId}/edit`);
    } catch (err) {
      console.error('Failed to restore session:', err);
    }
  }, [switchSession, currentProfile, loadProfile, navigate]);

  // After generation: save deck name + slide count so sidebar/list show correct name and count
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

  // Handle title change from header
  const handleTitleChange = useCallback(async (newTitle: string) => {
    try {
      await renameSession(newTitle);
      setLastSavedTime(new Date());
      // Update slide deck title if it exists
      if (slideDeck) {
        setSlideDeck({ ...slideDeck, title: newTitle });
      }
      // Trigger session list refresh in sidebar and history
      setSessionsRefreshKey(prev => prev + 1);
    } catch (err) {
      console.error('Failed to update title:', err);
      alert('Failed to update title');
    }
  }, [renameSession, slideDeck]);

  // Start a new session and persist + navigate to edit URL
  const handleNewSession = useCallback(async () => {
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    setChatKey((k) => k + 1);
    const newId = createNewSession();
    setViewMode('main');
    try {
      await api.createSession({ sessionId: newId });
      navigate(`/sessions/${newId}/edit`);
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }, [createNewSession, navigate]);

  // Save As: rename session with custom title
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

  // Share: copy view-only link to clipboard
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

  // Save Points: open revert modal (from PreviewBanner)
  const handleRevertClick = useCallback(() => {
    if (previewVersion == null) return;
    setRevertTargetVersion(previewVersion);
    setShowRevertModal(true);
  }, [previewVersion]);

  // Save Points: cancel preview
  const handlePreviewCancel = useCallback(() => {
    setPreviewVersion(null);
    setPreviewDeck(null);
    setPreviewDescription('');
  }, []);

  // Save Points: confirm revert
  const handleRevertConfirm = useCallback(async () => {
    if (!sessionId || revertTargetVersion == null) return;
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
  }, [sessionId, revertTargetVersion, loadVersions]);

  // Version key and read-only for preview/view mode
  const versionKey = previewVersion != null
    ? `preview-v${previewVersion}`
    : `current-v${currentVersion ?? 0}`;
  const isReadOnly = !!previewVersion || viewOnly;

  // Format time ago string
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
  const getSubtitle = () => {
    if (!slideDeck) return undefined;
    const parts = [`${slideDeck.slide_count} slide${slideDeck.slide_count !== 1 ? 's' : ''}`];

    // Add last saved time
    if (lastSavedTime) {
      parts.push(`Saved ${getTimeAgo(lastSavedTime)}`);
    }

    // Add status indicators (export status shown next to Export button in header)
    if (isGenerating) parts.push('Generating...');

    return parts.join(' • ');
  };

  // Deck to show: preview snapshot or live (use preview only when we have the deck)
  const displayDeck = previewVersion != null && previewDeck ? previewDeck : slideDeck;

  // Handle export and present via SlidePanel ref
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
      // 'main' is handled by New Deck button -> handleNewSession
    },
    [navigate]
  );

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
                title={slideDeck?.title || sessionTitle || 'Untitled session'}
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
                      disabled={isGenerating}
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
                  onRevert={handleRevertClick}
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
                <div className="w-[32%] min-w-[260px] border-r border-border bg-card">
                  <ChatPanel
                    key={chatKey}
                    ref={chatPanelRef}
                    rawHtml={rawHtml}
                    disabled={isReadOnly}
                    onGenerationStart={onGenerationStart}
                    onSlidesGenerated={async (deck, raw, actionDescription) => {
                      onGenerationComplete();
                      setSlideDeck(deck);
                      setRawHtml(raw);
                      autoSaveSession(deck);
                      if (sessionId && actionDescription) {
                        try {
                          await api.createSavePoint(sessionId, actionDescription);
                          await loadVersions();
                        } catch (e) {
                          console.warn('Create save point failed:', e);
                        }
                      }
                    }}
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
                    onSlideChange={setSlideDeck}
                    scrollToSlide={scrollTarget}
                    onSendMessage={handleSendMessage}
                    onExportStatusChange={setExportStatus}
                    versionKey={versionKey}
                    readOnly={isReadOnly}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'history' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="All Decks" />
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
        currentTitle={slideDeck?.title || sessionTitle || 'Untitled session'}
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
