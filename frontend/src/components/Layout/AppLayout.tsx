import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { SlideDeck } from '../../types/slide';
import type { Message } from '../../types/message';
import { ChatPanel, type ChatPanelHandle } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';
import { ProfileSelector } from '../config/ProfileSelector';
import { ProfileList } from '../config/ProfileList';
import { DeckPromptList } from '../config/DeckPromptList';
import { SlideStyleList } from '../config/SlideStyleList';
import { SessionHistory } from '../History/SessionHistory';
import { SaveAsDialog } from '../History/SaveAsDialog';
import { HelpPage } from '../Help';
import { ImageLibrary } from '../ImageLibrary/ImageLibrary';
import { UpdateBanner } from '../UpdateBanner';
import { SavePointDropdown, PreviewBanner, RevertConfirmModal, type SavePointVersion } from '../SavePoints';
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';
import { useProfiles } from '../../contexts/ProfileContext';
import { useToast } from '../../contexts/ToastContext';
import { useVersionCheck } from '../../hooks/useVersionCheck';
import { api } from '../../services/api';

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'help';

interface AppLayoutProps {
  initialView?: ViewMode;
  viewOnly?: boolean;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ initialView = 'help', viewOnly = false }) => {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(initialView);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  // Key to force remount ChatPanel when profile/session changes
  const [chatKey, setChatKey] = useState<number>(0);
  // Track which slide to scroll to in the main panel (uses key to allow re-scroll to same index)
  const [scrollTarget, setScrollTarget] = useState<{ index: number; key: number } | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const { sessionId, sessionTitle, experimentUrl, createNewSession, switchSession, renameSession, lastWorkingSessionId, setLastWorkingSessionId } = useSession();
  const { isGenerating } = useGeneration();
  const { currentProfile, loadProfile } = useProfiles();
  const { updateAvailable, latestVersion, updateType, dismissed, dismiss } = useVersionCheck();

  // Save Points / Versioning state
  const [versions, setVersions] = useState<SavePointVersion[]>([]);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [previewDeck, setPreviewDeck] = useState<SlideDeck | null>(null);
  const [previewDescription, setPreviewDescription] = useState<string>('');
  const [previewMessages, setPreviewMessages] = useState<Message[] | null>(null);
  const [showRevertModal, setShowRevertModal] = useState(false);
  const [revertTargetVersion, setRevertTargetVersion] = useState<number | null>(null);
  // Pending save point - created after verification completes
  const [pendingSavePointDescription, setPendingSavePointDescription] = useState<string | null>(null);

  // Track last working session ID when on a session edit route
  useEffect(() => {
    if (urlSessionId && initialView === 'main' && !viewOnly) {
      setLastWorkingSessionId(urlSessionId);
    }
  }, [urlSessionId, initialView, viewOnly, setLastWorkingSessionId]);

  // Load session from URL parameter when on a session route
  // Skip if URL session ID matches current context (newly created session, not yet in DB)
  useEffect(() => {
    if (!urlSessionId || initialView !== 'main') return;
    if (urlSessionId === sessionId) return;

    const loadSession = async () => {
      try {
        // Get session info to check profile
        const sessionInfo = await api.getSession(urlSessionId);

        // Auto-switch profile if needed
        if (sessionInfo.profile_id && currentProfile && sessionInfo.profile_id !== currentProfile.id) {
          await loadProfile(sessionInfo.profile_id);
        }

        // Load session data
        const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(urlSessionId);
        setSlideDeck(restoredDeck);
        setRawHtml(restoredRawHtml);
        setChatKey(prev => prev + 1);
      } catch {
        navigate('/help');
        showToast('Session not found', 'error');
      }
    };

    loadSession();
  }, [urlSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

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
        console.log(`Session belongs to profile ${sessionInfo.profile_name}, switching from ${currentProfile.name}`);
        await loadProfile(sessionInfo.profile_id);
      }
      
      // Now restore the session
      const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(restoredSessionId);
      setSlideDeck(restoredDeck);
      setRawHtml(restoredRawHtml);
      setChatKey(prev => prev + 1);
      setViewMode('main');
    } catch (err) {
      console.error('Failed to restore session:', err);
    }
  }, [switchSession, currentProfile, loadProfile]);

  // Handle saving session with a custom name
  const handleSaveAs = useCallback(async (title: string) => {
    try {
      await renameSession(title);
      setShowSaveDialog(false);
    } catch (err) {
      console.error('Failed to save session:', err);
      alert('Failed to save session name');
    }
  }, [renameSession]);

  // Start a new session
  const handleNewSession = useCallback(() => {
    setSlideDeck(null);
    setRawHtml(null);
    setChatKey(prev => prev + 1);
    setVersions([]);
    setCurrentVersion(null);
    setPreviewVersion(null);
    setPreviewDeck(null);
    const newId = createNewSession();
    navigate(`/sessions/${newId}/edit`);
  }, [createNewSession, navigate]);

  // Load versions when session or slideDeck changes
  useEffect(() => {
    const loadVersions = async () => {
      if (!sessionId) {
        setVersions([]);
        setCurrentVersion(null);
        return;
      }

      try {
        const { versions: loadedVersions, current_version } = await api.listVersions(sessionId);
        setVersions(loadedVersions);
        setCurrentVersion(current_version);
      } catch (err) {
        console.error('Failed to load versions:', err);
      }
    };

    loadVersions();
  }, [sessionId, slideDeck]); // Reload when slideDeck changes (new save point created)

  // Handle previewing a version
  const handlePreviewVersion = useCallback(async (versionNumber: number) => {
    if (!sessionId) return;

    try {
      const { deck, description, chat_history } = await api.previewVersion(sessionId, versionNumber);
      setPreviewVersion(versionNumber);
      setPreviewDeck(deck as SlideDeck);
      setPreviewDescription(description);
      
      // Convert chat history to Message format for preview
      if (chat_history && Array.isArray(chat_history)) {
        const previewMsgs: Message[] = chat_history.map((msg: Record<string, unknown>) => ({
          role: msg.role as 'user' | 'assistant' | 'tool',
          content: msg.content as string,
          timestamp: msg.created_at as string,
          tool_call: (msg as { metadata?: { tool_name?: string; tool_input?: Record<string, unknown> } }).metadata?.tool_name ? {
            name: (msg as { metadata: { tool_name: string } }).metadata.tool_name,
            arguments: (msg as { metadata: { tool_input?: Record<string, unknown> } }).metadata?.tool_input || {},
          } : undefined,
          tool_result: msg.message_type === 'tool_result' ? {
            name: (msg as { metadata?: { tool_name?: string } }).metadata?.tool_name || 'tool',
            content: msg.content as string,
          } : undefined,
        }));
        setPreviewMessages(previewMsgs);
      } else {
        setPreviewMessages([]);
      }
    } catch (err) {
      console.error('Failed to preview version:', err);
    }
  }, [sessionId]);

  // Cancel preview - return to current version
  const handleCancelPreview = useCallback(() => {
    setPreviewVersion(null);
    setPreviewDeck(null);
    setPreviewDescription('');
    setPreviewMessages(null);
  }, []);

  // Open revert confirmation modal
  const handleRevertClick = useCallback((versionNumber?: number) => {
    const targetVersion = versionNumber ?? previewVersion;
    if (targetVersion) {
      setRevertTargetVersion(targetVersion);
      setShowRevertModal(true);
    }
  }, [previewVersion]);

  // Confirm and execute revert
  const handleRevertConfirm = useCallback(async () => {
    if (!sessionId || !revertTargetVersion) return;

    try {
      const { deck } = await api.restoreVersion(sessionId, revertTargetVersion);
      setSlideDeck(deck as SlideDeck);
      setPreviewVersion(null);
      setPreviewDeck(null);
      setPreviewDescription('');
      setPreviewMessages(null);
      setShowRevertModal(false);
      setRevertTargetVersion(null);
      
      // Reload versions to reflect the changes
      const { versions: loadedVersions, current_version } = await api.listVersions(sessionId);
      setVersions(loadedVersions);
      setCurrentVersion(current_version);
      
      // Force ChatPanel to remount and reload messages (which are now restored)
      setChatKey(prev => prev + 1);
    } catch (err) {
      console.error('Failed to restore version:', err);
      alert('Failed to restore version');
    }
  }, [sessionId, revertTargetVersion]);

  // Handle verification complete - create save point with captured verification
  const handleVerificationComplete = useCallback(async (panelEditDescription?: string) => {
    // Use panel edit description if provided, otherwise use pending description from chat
    const description = panelEditDescription || pendingSavePointDescription;
    
    if (!sessionId || !description) return;

    try {
      console.log(`[SavePoint] Creating save point after verification: "${description}"`);
      await api.createSavePoint(sessionId, description);
      
      // Clear pending description
      setPendingSavePointDescription(null);
      
      // Reload versions to show the new save point
      const { versions: loadedVersions, current_version } = await api.listVersions(sessionId);
      setVersions(loadedVersions);
      setCurrentVersion(current_version);
      
      console.log(`[SavePoint] Created save point v${current_version}`);
    } catch (err) {
      console.error('Failed to create save point:', err);
      // Clear pending to prevent retry loops
      setPendingSavePointDescription(null);
    }
  }, [sessionId, pendingSavePointDescription]);

  // Determine which deck to display
  const displayDeck = previewVersion ? previewDeck : slideDeck;
  
  // Version key for forcing re-render when switching save point versions
  // This prevents React from reusing DOM elements with identical slide_id keys
  const versionKey = previewVersion ? `preview-v${previewVersion}` : `current-v${currentVersion || 'live'}`;

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">databricks tellr</h1>
            <p className="text-sm text-blue-100 flex items-center gap-2">
              {sessionTitle && (
                <>
                  <span className="truncate max-w-[200px]" title={sessionTitle}>
                    {sessionTitle}
                  </span>
                  <span className="text-blue-300">•</span>
                </>
              )}
              {slideDeck ? `${slideDeck.slide_count} slides` : 'No slides'}
              {experimentUrl && (
                <>
                  <span className="text-blue-300">•</span>
                  <a
                    href={experimentUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-white underline"
                    title="View MLflow experiment traces"
                  >
                    Run Details
                  </a>
                </>
              )}
            </p>
          </div>
          
          <div className="flex items-center gap-4">
            {/* Session Actions (hidden in view-only mode) */}
            {viewMode === 'main' && !viewOnly && (
              <div className="flex items-center gap-2">
                {/* Save Points Dropdown */}
                {versions.length > 0 && (
                  <SavePointDropdown
                    versions={versions}
                    currentVersion={currentVersion}
                    previewVersion={previewVersion}
                    onPreview={handlePreviewVersion}
                    onRevert={handleRevertClick}
                    disabled={isGenerating}
                  />
                )}
                <button
                  onClick={() => setShowSaveDialog(true)}
                  disabled={isGenerating || !!previewVersion}
                  className={`px-3 py-1.5 rounded text-sm transition-colors ${
                    isGenerating || previewVersion
                      ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                      : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                  }`}
                  title={isGenerating ? 'Disabled during generation' : previewVersion ? 'Exit preview to save' : 'Save session with a custom name'}
                >
                  Save As
                </button>
                <button
                  onClick={handleNewSession}
                  disabled={isGenerating || !!previewVersion}
                  className={`px-3 py-1.5 rounded text-sm transition-colors ${
                    isGenerating || previewVersion
                      ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                      : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                  }`}
                  title={isGenerating ? 'Disabled during generation' : previewVersion ? 'Exit preview first' : 'Start a new session'}
                >
                  New
                </button>
                {urlSessionId && (
                  <button
                    onClick={async () => {
                      const viewUrl = `${window.location.origin}/sessions/${urlSessionId}/view`;
                      await navigator.clipboard.writeText(viewUrl);
                      showToast('Link copied to clipboard', 'success');
                    }}
                    className="px-3 py-1.5 rounded text-sm transition-colors bg-blue-500 hover:bg-blue-700 text-blue-100"
                    title="Copy shareable view link"
                  >
                    Share
                  </button>
                )}
              </div>
            )}

            {/* Navigation */}
            <nav className="flex gap-2 border-l border-blue-500 pl-4">
              <button
                onClick={() => {
                  if (lastWorkingSessionId) {
                    navigate(`/sessions/${lastWorkingSessionId}/edit`);
                  } else {
                    const newId = createNewSession();
                    navigate(`/sessions/${newId}/edit`);
                  }
                }}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'main'
                    ? 'bg-blue-700 text-white'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
              >
                Generator
              </button>
              <button
                onClick={() => navigate('/history')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'history'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                History
              </button>
              <button
                onClick={() => navigate('/profiles')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'profiles'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                Profiles
              </button>
              <button
                onClick={() => navigate('/deck-prompts')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'deck_prompts'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                Deck Prompts
              </button>
              <button
                onClick={() => navigate('/slide-styles')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'slide_styles'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                Slide Styles
              </button>
              <button
                onClick={() => navigate('/images')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'images'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                Images
              </button>
              <button
                onClick={() => navigate('/help')}
                disabled={isGenerating}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'help'
                    ? 'bg-blue-700 text-white'
                    : isGenerating
                    ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
                title={isGenerating ? 'Navigation disabled during generation' : undefined}
              >
                Help
              </button>
              {isGenerating && (
                <span className="px-2 py-1.5 text-xs text-yellow-200 bg-yellow-600 rounded animate-pulse">
                  Generating...
                </span>
              )}
            </nav>

            {/* Profile Selector */}
            <ProfileSelector
              onManageClick={() => navigate('/profiles')}
              onProfileChange={handleProfileChange}
              disabled={isGenerating}
            />
          </div>
        </div>
      </header>

      {/* Update Banner */}
      {updateAvailable && !dismissed && latestVersion && updateType && (
        <UpdateBanner
          latestVersion={latestVersion}
          updateType={updateType}
          onDismiss={dismiss}
        />
      )}

      {/* Preview Banner */}
      {previewVersion && (
        <PreviewBanner
          versionNumber={previewVersion}
          description={previewDescription}
          onRevert={() => handleRevertClick()}
          onCancel={handleCancelPreview}
        />
      )}

      {/* Main Content */}
      {viewMode === 'main' && (
        <div className="flex-1 flex overflow-hidden">
          {/* Chat Panel */}
          <div className="w-[32%] min-w-[260px] border-r" data-testid="chat-panel">
            <ChatPanel
              key={chatKey}
              ref={chatPanelRef}
              rawHtml={rawHtml}
              onSlidesGenerated={(deck, raw, actionDescription) => {
                setSlideDeck(deck);
                setRawHtml(raw);
                // Set pending save point description - will be created after verification
                if (actionDescription) {
                  setPendingSavePointDescription(actionDescription);
                }
              }}
              disabled={viewOnly || !!previewVersion}
              previewMessages={previewMessages}
            />
          </div>

          {/* Selection Ribbon */}
          <SelectionRibbon slideDeck={displayDeck} onSlideNavigate={handleSlideNavigate} versionKey={versionKey} />

          {/* Slide Panel */}
          <div className="flex-1" data-testid="slide-panel">
            <SlidePanel
              slideDeck={displayDeck}
              rawHtml={rawHtml}
              onSlideChange={viewOnly || previewVersion ? undefined : setSlideDeck}
              scrollToSlide={scrollTarget}
              onSendMessage={viewOnly || previewVersion ? undefined : handleSendMessage}
              readOnly={viewOnly || !!previewVersion}
              onVerificationComplete={handleVerificationComplete}
              versionKey={versionKey}
            />
          </div>
        </div>
      )}

      {viewMode === 'history' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="p-6">
            <SessionHistory
              onSessionSelect={(id) => navigate(`/sessions/${id}/edit`)}
              onBack={() => {
                if (lastWorkingSessionId) {
                  navigate(`/sessions/${lastWorkingSessionId}/edit`);
                } else {
                  navigate('/help');
                }
              }}
            />
          </div>
        </div>
      )}

      {viewMode === 'profiles' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="max-w-7xl mx-auto p-6">
            <ProfileList onProfileChange={handleProfileChange} />
          </div>
        </div>
      )}

      {viewMode === 'deck_prompts' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="max-w-7xl mx-auto p-6">
            <DeckPromptList />
          </div>
        </div>
      )}

      {viewMode === 'slide_styles' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="max-w-7xl mx-auto p-6">
            <SlideStyleList />
          </div>
        </div>
      )}

      {viewMode === 'images' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="max-w-7xl mx-auto p-6">
            <ImageLibrary />
          </div>
        </div>
      )}

      {viewMode === 'help' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="p-6">
            <HelpPage onBack={() => {
              if (lastWorkingSessionId) {
                navigate(`/sessions/${lastWorkingSessionId}/edit`);
              } else {
                const newId = createNewSession();
                navigate(`/sessions/${newId}/edit`);
              }
            }} />
          </div>
        </div>
      )}

      {/* Save As Dialog */}
      <SaveAsDialog
        isOpen={showSaveDialog}
        currentTitle={sessionTitle || ''}
        onSave={handleSaveAs}
        onCancel={() => setShowSaveDialog(false)}
      />

      {/* Revert Confirmation Modal */}
      <RevertConfirmModal
        isOpen={showRevertModal}
        versionNumber={revertTargetVersion || 0}
        description={versions.find(v => v.version_number === revertTargetVersion)?.description || ''}
        currentVersion={currentVersion || 0}
        onConfirm={handleRevertConfirm}
        onCancel={() => {
          setShowRevertModal(false);
          setRevertTargetVersion(null);
        }}
      />
    </div>
  );
};
