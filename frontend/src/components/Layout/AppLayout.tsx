import React, { useState } from 'react';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <h1 className="text-xl font-bold">AI Slide Generator</h1>
        <p className="text-sm text-blue-100">
          Phase 2 - Drag & Drop, Edit • Single Session
        </p>
      </header>

      {/* Main Content: Two Panel Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel - Left 30% */}
        <div className="w-[30%] border-r">
          <ChatPanel onSlidesGenerated={setSlideDeck} />
        </div>

        {/* Slide Panel - Right 70% */}
        <div className="flex-1">
          <SlidePanel 
            slideDeck={slideDeck} 
            onSlideChange={setSlideDeck}
          />
        </div>
      </div>
    </div>
  );
};
