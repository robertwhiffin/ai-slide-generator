import React, { useState, useCallback, useRef } from 'react';
import type { SlideDeck } from '../../types/slide';
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
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'history' | 'help';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('help');
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  // Key to force remount ChatPanel when profile/session changes
  const [chatKey, setChatKey] = useState<number>(0);
  // Track which slide to scroll to in the main panel (uses key to allow re-scroll to same index)
  const [scrollTarget, setScrollTarget] = useState<{ index: number; key: number } | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const { sessionTitle, createNewSession, switchSession, renameSession } = useSession();
  const { isGenerating } = useGeneration();

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
  const handleSessionRestore = useCallback(async (restoredSessionId: string) => {
    const { slideDeck: restoredDeck, rawHtml: restoredRawHtml } = await switchSession(restoredSessionId);
    setSlideDeck(restoredDeck);
    setRawHtml(restoredRawHtml);
    setChatKey(prev => prev + 1);
    setViewMode('main');
  }, [switchSession]);

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
    createNewSession();
  }, [createNewSession]);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">Databricks Storyteller</h1>
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
            </p>
          </div>
          
          <div className="flex items-center gap-4">
            {/* Session Actions */}
            {viewMode === 'main' && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowSaveDialog(true)}
                  disabled={isGenerating}
                  className={`px-3 py-1.5 rounded text-sm transition-colors ${
                    isGenerating
                      ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                      : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                  }`}
                  title={isGenerating ? 'Disabled during generation' : 'Save session with a custom name'}
                >
                  Save As
                </button>
                <button
                  onClick={handleNewSession}
                  disabled={isGenerating}
                  className={`px-3 py-1.5 rounded text-sm transition-colors ${
                    isGenerating
                      ? 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50'
                      : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                  }`}
                  title={isGenerating ? 'Disabled during generation' : 'Start a new session'}
                >
                  New
                </button>
              </div>
            )}

            {/* Navigation */}
            <nav className="flex gap-2 border-l border-blue-500 pl-4">
              <button
                onClick={() => setViewMode('main')}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'main'
                    ? 'bg-blue-700 text-white'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
              >
                Generator
              </button>
              <button
                onClick={() => setViewMode('history')}
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
                onClick={() => setViewMode('profiles')}
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
                onClick={() => setViewMode('deck_prompts')}
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
                onClick={() => setViewMode('slide_styles')}
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
                onClick={() => setViewMode('help')}
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
              onManageClick={() => setViewMode('profiles')}
              onProfileChange={handleProfileChange}
              disabled={isGenerating}
            />
          </div>
        </div>
      </header>

      {/* Main Content */}
      {viewMode === 'main' && (
        <div className="flex-1 flex overflow-hidden">
          {/* Chat Panel */}
          <div className="w-[32%] min-w-[260px] border-r">
            <ChatPanel
              key={chatKey}
              ref={chatPanelRef}
              rawHtml={rawHtml}
              onSlidesGenerated={(deck, raw) => {
                setSlideDeck(deck);
                setRawHtml(raw);
              }}
            />
          </div>

          {/* Selection Ribbon */}
          <SelectionRibbon slideDeck={slideDeck} onSlideNavigate={handleSlideNavigate} />

          {/* Slide Panel */}
          <div className="flex-1">
            <SlidePanel
              slideDeck={slideDeck}
              rawHtml={rawHtml}
              onSlideChange={setSlideDeck}
              scrollToSlide={scrollTarget}
              onSendMessage={handleSendMessage}
            />
          </div>
        </div>
      )}

      {viewMode === 'history' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="p-6">
            <SessionHistory
              onSessionSelect={handleSessionRestore}
              onBack={() => setViewMode('main')}
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

      {viewMode === 'help' && (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="p-6">
            <HelpPage onBack={() => setViewMode('main')} />
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
    </div>
  );
};
