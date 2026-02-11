import React from 'react';

interface PreviewBannerProps {
  versionNumber: number;
  description: string;
  onRevert: () => void;
  onCancel: () => void;
}

export const PreviewBanner: React.FC<PreviewBannerProps> = ({
  versionNumber,
  description,
  onRevert,
  onCancel,
}) => {
  return (
    <div className="bg-indigo-50 dark:bg-indigo-900/40 border-b border-indigo-200 dark:border-indigo-700 px-4 py-2 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <svg className="w-5 h-5 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg>
        <span className="text-sm text-indigo-800 dark:text-indigo-200">
          <strong>Previewing v{versionNumber}:</strong> {description}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onRevert}
          className="px-3 py-1 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 rounded-md transition-colors"
        >
          Revert to This Version
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-800 active:bg-indigo-200 dark:active:bg-indigo-700 rounded-md transition-colors"
        >
          Cancel Preview
        </button>
      </div>
    </div>
  );
};

export default PreviewBanner;
