import React, { useEffect, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import { Button } from '@/ui/button';
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
        <div className="flex flex-col items-center justify-center h-32 text-center px-4">
          <Layers className="size-8 text-muted-foreground/50 mb-2" />
          <p className="text-sm text-muted-foreground">
            Generate slides to enable selection
          </p>
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
    <div className="flex h-full w-64 flex-col border-r border-border bg-card">
      <div className="flex items-center gap-3 border-b border-border bg-card px-4 py-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
          <Layers className="size-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-medium text-foreground">Thumbnails</h2>
          <p className="text-xs text-muted-foreground">
            Select consecutive slides
          </p>
        </div>
      </div>

      {warning && (
        <div className="mx-3 mt-3 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {warning}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3">{renderBody()}</div>

      {selectedIndices.length > 0 && (
        <div className="border-t border-border bg-card p-3">
          <p className="text-xs text-muted-foreground mb-2">
            {selectedIndices.length} slide{selectedIndices.length === 1 ? '' : 's'} selected
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={clearSelection}
            className="w-full"
          >
            Clear selection
          </Button>
        </div>
      )}
    </div>
  );
};

