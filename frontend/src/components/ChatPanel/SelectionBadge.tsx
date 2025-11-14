import React from 'react';
import './SelectionBadge.css';

interface SelectionBadgeProps {
  selectedIndices: number[];
  onClear: () => void;
}

export const SelectionBadge: React.FC<SelectionBadgeProps> = ({
  selectedIndices,
  onClear,
}) => {
  if (selectedIndices.length === 0) {
    return null;
  }

  const sorted = [...selectedIndices].sort((a, b) => a - b);
  const first = sorted[0] + 1;
  const last = sorted[sorted.length - 1] + 1;
  const rangeText =
    sorted.length === 1 ? `Slide ${first}` : `Slides ${first}-${last}`;

  return (
    <div className="selection-badge" role="status" aria-live="polite">
      <span className="badge-icon" aria-hidden="true">
        📎
      </span>
      <span className="badge-text">{rangeText}</span>
      <button
        className="badge-clear"
        onClick={onClear}
        aria-label="Clear selection"
        type="button"
      >
        ×
      </button>
    </div>
  );
};

