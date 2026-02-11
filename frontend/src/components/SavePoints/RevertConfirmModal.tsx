import React from 'react';

interface RevertConfirmModalProps {
  isOpen: boolean;
  versionNumber: number;
  description: string;
  currentVersion: number;
  onConfirm: () => void;
  onCancel: () => void;
}

export const RevertConfirmModal: React.FC<RevertConfirmModalProps> = ({
  isOpen,
  versionNumber,
  description,
  currentVersion,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  const versionsToDelete = currentVersion - versionNumber;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/50" 
        onClick={onCancel}
      />
      
      {/* Modal */}
      <div className="relative bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 overflow-hidden">
        {/* Header - Indigo theme to match preview */}
        <div className="bg-indigo-50 dark:bg-indigo-900/30 px-6 py-4 border-b border-indigo-200 dark:border-indigo-700">
          <div className="flex items-center gap-3">
            <div className="flex-shrink-0">
              <svg className="w-6 h-6 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0019 16V8a1 1 0 00-1.6-.8l-5.333 4zM4.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0011 16V8a1 1 0 00-1.6-.8l-5.334 4z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Revert to Previous Version
            </h3>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-4">
          <p className="text-gray-700 dark:text-gray-300 mb-4">
            You are about to revert your project to <strong>version {versionNumber}</strong>:
          </p>
          <div className="bg-gray-100 dark:bg-gray-700 rounded-md px-3 py-2 mb-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">{description}</p>
          </div>
          
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-3 mb-4">
            <div className="flex items-start gap-2">
              <svg className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-red-800 dark:text-red-200">
                  Warning: This action cannot be undone
                </p>
                <p className="text-sm text-red-700 dark:text-red-300 mt-1">
                  {versionsToDelete > 0 
                    ? `${versionsToDelete} newer version${versionsToDelete > 1 ? 's' : ''} will be permanently deleted.`
                    : 'All changes made after this version will be lost.'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50 flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 active:bg-gray-300 dark:hover:bg-gray-700 dark:active:bg-gray-600 rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 active:bg-red-800 rounded-md transition-colors"
          >
            Yes, Revert
          </button>
        </div>
      </div>
    </div>
  );
};

export default RevertConfirmModal;
