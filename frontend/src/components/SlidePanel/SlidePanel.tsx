import React from 'react';
import { SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
}

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck }) => {
  if (!slideDeck) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center text-gray-500">
          <p className="text-lg font-medium">No slides yet</p>
          <p className="text-sm mt-2">Send a message to generate slides</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="sticky top-0 z-10 p-4 bg-white border-b">
        <h2 className="text-lg font-semibold">{slideDeck.title}</h2>
        <p className="text-sm text-gray-500">
          {slideDeck.slide_count} slide{slideDeck.slide_count !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Slide Tiles */}
      <div className="p-4 space-y-4">
        {slideDeck.slides.map((slide, index) => (
          <SlideTile
            key={slide.slide_id}
            slide={slide}
            slideDeck={slideDeck}
            index={index}
          />
        ))}
      </div>
    </div>
  );
};

