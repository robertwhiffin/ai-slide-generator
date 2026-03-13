import React from 'react';

interface LoadingIndicatorProps {
  message?: string;
  onCancel?: () => void;
}

export const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  message = 'Processing slide edits...',
  onCancel,
}) => (
  <div className="px-4 py-3 bg-blue-50 border-t border-blue-200">
    <div className="flex items-center justify-between text-blue-800 text-sm">
      <div className="flex items-center space-x-3">
        <div className="flex space-x-1" aria-hidden="true">
          <div
            className="w-2 h-2 bg-blue-600 rounded-full animate-bounce"
            style={{ animationDelay: '0ms' }}
          ></div>
          <div
            className="w-2 h-2 bg-blue-600 rounded-full animate-bounce"
            style={{ animationDelay: '150ms' }}
          ></div>
          <div
            className="w-2 h-2 bg-blue-600 rounded-full animate-bounce"
            style={{ animationDelay: '300ms' }}
          ></div>
        </div>
        <span className="font-medium italic">{message}</span>
      </div>
      {onCancel && (
        <button
          onClick={onCancel}
          className="ml-3 px-3 py-1 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded hover:bg-red-100 transition-colors"
        >
          Stop
        </button>
      )}
    </div>
  </div>
);

