import React, { useEffect, useRef, useState } from 'react';
import type { SlideDeck } from '../../types/slide';
import { useSelection } from '../../contexts/SelectionContext';
import { SlideSelection } from './SlideSelection';

interface SelectionRibbonProps {
  slideDeck: SlideDeck | null;
  onSlideNavigate?: (index: number) => void;
  versionKey?: string;  // Used to force re-render when switching save point versions
}

export const SelectionRibbon: React.FC<SelectionRibbonProps> = ({
  slideDeck,
  onSlideNavigate,
  versionKey,
}) => {
  const { selectedIndices, setSelection, clearSelection } = useSelection();
  const [warning, setWarning] = useState<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    },
    [],
  );

  const handleSelectionChange = (indices: number[]) => {
    if (!slideDeck) {
      return;
    }
    const slides = indices
      .map(index => slideDeck.slides[index])
      .filter((slide): slide is NonNullable<typeof slide> => Boolean(slide));

    setSelection(indices, slides);
    setWarning(null);
  };

  const handleNonContiguousSelection = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setWarning('Selections must be consecutive. Please adjust your selection.');
    timeoutRef.current = setTimeout(() => setWarning(null), 4000);
  };

  const renderBody = () => {
    if (!slideDeck || !slideDeck.slides || slideDeck.slides.length === 0) {
      return (
        <div className="p-4 text-sm text-gray-500">
          Generate slides to enable selection.
        </div>
      );
    }

    return (
      <SlideSelection
        slides={slideDeck.slides}
        slideDeck={slideDeck}
        selectedIndices={selectedIndices}
        onSelectionChange={handleSelectionChange}
        onNonContiguousSelection={handleNonContiguousSelection}
        onSlideNavigate={onSlideNavigate}
        versionKey={versionKey}
      />
    );
  };

  return (
    <div className="w-64 border-r bg-slate-50 flex flex-col">
      <div className="p-4 border-b bg-white">
        <p className="text-sm font-semibold text-gray-900">Select slides</p>
        <p className="text-xs text-gray-500">
          Use the checkboxes to pick consecutive slides.
        </p>
        {warning && (
          <div className="mt-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
            {warning}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">{renderBody()}</div>

      {selectedIndices.length > 0 && (
        <div className="p-3 border-t bg-white">
          <p className="text-xs text-gray-600 mb-2">
            {selectedIndices.length} slide
            {selectedIndices.length === 1 ? '' : 's'} selected
          </p>
          <button
            type="button"
            onClick={clearSelection}
            className="w-full px-3 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 bg-blue-50 rounded hover:bg-blue-100 transition"
          >
            Clear selection
          </button>
        </div>
      )}
    </div>
  );
};

