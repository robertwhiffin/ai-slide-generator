import React, { useMemo } from 'react';
import type { Slide, SlideDeck } from '../../types/slide';
import { isContiguous } from '../../utils/slideReplacements';
import './SlideSelection.css';

interface SlideSelectionProps {
  slides: Slide[];
  slideDeck?: SlideDeck | null;
  selectedIndices: number[];
  onSelectionChange: (indices: number[]) => void;
  onNonContiguousSelection?: (attemptedIndices: number[]) => void;
  onSlideNavigate?: (index: number) => void;
}

export const SlideSelection: React.FC<SlideSelectionProps> = ({
  slides,
  slideDeck,
  selectedIndices,
  onSelectionChange,
  onNonContiguousSelection,
  onSlideNavigate,
}) => {
  const toggleSelection = (index: number) => {
    const isSelected = selectedIndices.includes(index);
    const nextSelection = isSelected
      ? selectedIndices.filter(i => i !== index)
      : [...selectedIndices, index].sort((a, b) => a - b);

    if (!isContiguous(nextSelection)) {
      onNonContiguousSelection?.(nextSelection);
      return;
    }

    onSelectionChange(nextSelection);
  };

  const getPreviewDocument = useMemo(() => {
    const cssBlock = slideDeck?.css ? `<style>${slideDeck.css}</style>` : '';
    const externalScripts =
      slideDeck?.external_scripts
        ?.map(src => `<script src="${src}"></script>`)
        .join('\n    ') ?? '';

    const inlineScripts = slideDeck?.scripts ? `
    <script>
      try {
        ${slideDeck.scripts}
      } catch (error) {
        console.debug('Chart initialization skipped for missing canvas:', error.message);
      }
    </script>` : '';

    return (slideHtml: string) => `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    ${cssBlock}
    ${externalScripts}
    <style>
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        width: 1280px;
        height: 720px;
        background: #ffffff;
        font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
      }
    </style>
  </head>
  <body>
    ${slideHtml}
    ${inlineScripts}
  </body>
</html>`;
  }, [slideDeck?.css, slideDeck?.external_scripts, slideDeck?.scripts]);

  const handleCardClick = (index: number) => {
    onSlideNavigate?.(index);
  };

  if (!slides || slides.length === 0) {
    return <div className="text-sm text-gray-500">No slides available</div>;
  }

  return (
    <div className="slide-selection">
      {slides.map((slide, index) => {
        const isSelected = selectedIndices.includes(index);
        return (
          <div
            key={slide.slide_id}
            className={`slide-thumbnail ${isSelected ? 'selected' : ''}`}
            onClick={() => handleCardClick(index)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                handleCardClick(index);
              }
            }}
          >
            <div className="slide-checkbox-row">
              <label className="slide-checkbox-label">
                <input
                  type="checkbox"
                  className="slide-checkbox-input"
                  checked={isSelected}
                  onChange={(event) => {
                    event.stopPropagation();
                    toggleSelection(index);
                  }}
                  onClick={(event) => event.stopPropagation()}
                  aria-label={`Select slide ${index + 1}`}
                />
                <span>Slide {index + 1}</span>
              </label>
            </div>
            <div className="slide-preview">
              <iframe
                title={`Slide ${index + 1} preview`}
                srcDoc={getPreviewDocument(slide.html)}
                className="slide-preview-frame"
                scrolling="no"
              />
              <div className="slide-preview-overlay" aria-hidden="true" />
            </div>
            {isSelected && (
              <div className="selection-indicator" aria-hidden="true">
                ✓
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

