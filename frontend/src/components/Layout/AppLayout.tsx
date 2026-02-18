import React, { useState, useCallback, useRef } from 'react';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel, type ChatPanelHandle } from '../ChatPanel/ChatPanel';
import { SlidePanel, type SlidePanelHandle } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';
import { ProfileSelector } from '../config/ProfileSelector';
import { ProfileList } from '../config/ProfileList';
import { DeckPromptList } from '../config/DeckPromptList';
import { SlideStyleList } from '../config/SlideStyleList';
import { SessionHistory } from '../History/SessionHistory';
import { HelpPage } from '../Help';
import { UpdateBanner } from '../UpdateBanner';
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';
import { useProfiles } from '../../contexts/ProfileContext';
import { useVersionCheck } from '../../hooks/useVersionCheck';
import { api } from '../../services/api';
import { SidebarProvider, SidebarInset } from '@/ui/sidebar';
import { AppSidebar } from './app-sidebar';
import { PageHeader } from './page-header';
import { SimplePageHeader } from './simple-page-header';

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'history' | 'help';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('help');
  const [lastSavedTime, setLastSavedTime] = useState<Date | null>(null);
  // Key to force remount ChatPanel when profile/session changes
  const [chatKey, setChatKey] = useState<number>(0);
  // Track which slide to scroll to in the main panel (uses key to allow re-scroll to same index)
  const [scrollTarget, setScrollTarget] = useState<{ index: number; key: number } | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const slidePanelRef = useRef<SlidePanelHandle>(null);
  const { sessionTitle, sessionId, createNewSession, switchSession, renameSession } = useSession();
  const { isGenerating } = useGeneration();
  const { currentProfile, loadProfile } = useProfiles();
  const { updateAvailable, latestVersion, updateType, dismissed, dismiss } = useVersionCheck();

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
        console.log(`Session belongs to profile ${sessionInfo.profile_name}, switching from ${currentProfile.name}`);
        await loadProfile(sessionInfo.profile_id);
      }

      // Now restore the session
      const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(restoredSessionId);
      setSlideDeck(restoredDeck);
      setRawHtml(restoredRawHtml);
      setLastSavedTime(new Date()); // Set as "just restored"
      setChatKey(prev => prev + 1);
      setViewMode('main');
    } catch (err) {
      console.error('Failed to restore session:', err);
    }
  }, [switchSession, currentProfile, loadProfile]);

  // Auto-save session with slide deck title
  const autoSaveSession = useCallback(async (deck: SlideDeck) => {
    if (!sessionId || !deck.title) return;

    try {
      await renameSession(deck.title);
      setLastSavedTime(new Date());
    } catch (err) {
      console.error('Failed to auto-save session:', err);
    }
  }, [sessionId, renameSession]);

  // Start a new session
  const handleNewSession = useCallback(() => {
    setSlideDeck(null);
    setRawHtml(null);
    setLastSavedTime(null);
    setChatKey(prev => prev + 1);
    createNewSession();
    setViewMode('main');
  }, [createNewSession]);

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

    // Add status indicators
    if (isGenerating) parts.push('Generating...');
    if (exportStatus) parts.push(exportStatus);

    return parts.join(' • ');
  };

  // Handle export and present via SlidePanel ref
  const handleExport = useCallback(() => {
    slidePanelRef.current?.exportPPTX();
  }, []);

  const handlePresent = useCallback(() => {
    slidePanelRef.current?.openPresentationMode();
  }, []);

  return (
    <SidebarProvider className="h-svh max-h-svh">
      <AppSidebar
        currentView={viewMode}
        onViewChange={setViewMode}
        onSessionSelect={handleSessionRestore}
        onNewSession={handleNewSession}
        currentSessionId={sessionId}
        profileName={currentProfile?.name}
      />
      <SidebarInset className="h-full overflow-hidden">
        {viewMode === 'main' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <PageHeader
                title={slideDeck?.title || sessionTitle || 'Untitled session'}
                subtitle={getSubtitle()}
                onExport={slideDeck ? handleExport : undefined}
                onPresent={slideDeck ? handlePresent : undefined}
                isGenerating={isGenerating}
                profileSelector={
                  <ProfileSelector
                    onManageClick={() => setViewMode('profiles')}
                    onProfileChange={handleProfileChange}
                    disabled={isGenerating}
                  />
                }
              />

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
                    onSlidesGenerated={(deck, raw) => {
                      setSlideDeck(deck);
                      setRawHtml(raw);
                      autoSaveSession(deck);
                    }}
                  />
                </div>

                <SelectionRibbon slideDeck={slideDeck} onSlideNavigate={handleSlideNavigate} />

                <div className="flex-1 bg-background">
                  <SlidePanel
                    ref={slidePanelRef}
                    slideDeck={slideDeck}
                    rawHtml={rawHtml}
                    onSlideChange={setSlideDeck}
                    scrollToSlide={scrollTarget}
                    onSendMessage={handleSendMessage}
                    onExportStatusChange={setExportStatus}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'history' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="History" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <SessionHistory
                  onSessionSelect={handleSessionRestore}
                  onBack={() => setViewMode('main')}
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

        {viewMode === 'help' && (
          <div className="flex h-full flex-col">
            <div className="shrink-0">
              <SimplePageHeader title="Help" />
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-4xl px-4 py-8">
                <HelpPage onBack={() => setViewMode('main')} />
              </div>
            </div>
          </div>
        )}
      </SidebarInset>
    </SidebarProvider>
  );
};
