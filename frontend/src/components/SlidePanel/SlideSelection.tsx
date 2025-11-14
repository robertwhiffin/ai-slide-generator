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
}

export const SlideSelection: React.FC<SlideSelectionProps> = ({
  slides,
  slideDeck,
  selectedIndices,
  onSelectionChange,
  onNonContiguousSelection,
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
        ?.map(src => `<link rel="preload" as="script" href="${src}">`)
        .join('\n    ') ?? '';

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
        background: #0f172a;
        display: flex;
        align-items: flex-start;
        justify-content: flex-start;
        padding: 0;
        font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
      }
      .preview-wrapper {
        width: 1280px;
        height: 720px;
        transform: scale(0.18);
        transform-origin: top left;
        border-radius: 8px;
        overflow: hidden;
        background: #ffffff;
      }
    </style>
  </head>
  <body>
    <div class="preview-wrapper">
      ${slideHtml}
    </div>
  </body>
</html>`;
  }, [slideDeck?.css, slideDeck?.external_scripts]);

  const handleCardClick = (index: number) => {
    toggleSelection(index);
  };

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
                sandbox="allow-same-origin"
                scrolling="no"
              />
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

