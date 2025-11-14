import React from 'react';

interface LoadingIndicatorProps {
  message?: string;
}

export const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  message = 'Processing slide edits...',
}) => (
  <div className="px-4 py-3 bg-blue-50 border-t border-blue-200">
    <div className="flex items-center space-x-3 text-blue-800 text-sm">
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
  </div>
);

