import React, { useState, useCallback } from 'react';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';
import { ProfileSelector } from '../config/ProfileSelector';
import { ProfileList } from '../config/ProfileList';

type ViewMode = 'main' | 'profiles';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('main');
  // Key to force remount ChatPanel when profile changes
  const [chatKey, setChatKey] = useState<number>(0);

  // Reset chat state when profile changes
  const handleProfileChange = useCallback(() => {
    setSlideDeck(null);
    setRawHtml(null);
    setChatKey(prev => prev + 1);
  }, []);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">AI Slide Generator</h1>
            <p className="text-sm text-blue-100">
              Slide Editing Mode • Single Session
            </p>
          </div>
          
          <div className="flex items-center gap-4">
            {/* Navigation */}
            <nav className="flex gap-2">
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
                onClick={() => setViewMode('profiles')}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === 'profiles'
                    ? 'bg-blue-700 text-white'
                    : 'bg-blue-500 hover:bg-blue-700 text-blue-100'
                }`}
              >
                Settings
              </button>
            </nav>

            {/* Profile Selector */}
            <ProfileSelector 
              onManageClick={() => setViewMode('profiles')}
              onProfileChange={handleProfileChange}
            />
          </div>
        </div>
      </header>

      {/* Main Content */}
      {viewMode === 'main' ? (
        <div className="flex-1 flex overflow-hidden">
          {/* Chat Panel */}
          <div className="w-[32%] min-w-[260px] border-r">
            <ChatPanel
              key={chatKey}
              rawHtml={rawHtml}
              onSlidesGenerated={(deck, raw) => {
                setSlideDeck(deck);
                setRawHtml(raw);
              }}
            />
          </div>

          {/* Selection Ribbon */}
          <SelectionRibbon slideDeck={slideDeck} />

          {/* Slide Panel */}
          <div className="flex-1">
            <SlidePanel
              slideDeck={slideDeck}
              rawHtml={rawHtml}
              onSlideChange={setSlideDeck}
            />
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto bg-gray-50">
          <div className="max-w-7xl mx-auto p-6">
            <ProfileList onProfileChange={handleProfileChange} />
          </div>
        </div>
      )}
    </div>
  );
};
