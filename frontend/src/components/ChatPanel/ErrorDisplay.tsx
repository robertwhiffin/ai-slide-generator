import React from 'react';

interface ErrorDisplayProps {
  error: string;
  onDismiss: () => void;
}

export const ErrorDisplay: React.FC<ErrorDisplayProps> = ({
  error,
  onDismiss,
}) => (
  <div className="px-4 py-3 bg-red-50 border-t border-red-200 flex items-center justify-between text-sm text-red-700">
    <div className="flex items-center gap-2">
      <span role="img" aria-hidden="true">
        ⚠️
      </span>
      <span>{error}</span>
    </div>
    <button
      type="button"
      onClick={onDismiss}
      className="text-red-700 font-semibold hover:underline"
      aria-label="Dismiss error"
    >
      Dismiss
    </button>
  </div>
);

