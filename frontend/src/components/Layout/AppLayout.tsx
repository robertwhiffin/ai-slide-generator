import React, { useState } from 'react';
import type { SlideDeck } from '../../types/slide';
import { ChatPanel } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';
import { SelectionRibbon } from '../SlidePanel/SelectionRibbon';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  const [rawHtml, setRawHtml] = useState<string | null>(null);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <h1 className="text-xl font-bold">AI Slide Generator</h1>
        <p className="text-sm text-blue-100">
          Slide Editing Mode • Single Session
        </p>
      </header>

      {/* Main Content: Two Panel Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel */}
        <div className="w-[32%] min-w-[260px] border-r">
          <ChatPanel
            slideDeck={slideDeck}
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
    </div>
  );
};
