/**
 * Banner component for displaying app update notifications.
 * 
 * Shows different messages based on update type:
 * - Patch updates: Just redeploy the app
 * - Major updates: Run tellr.update() from databricks-tellr
 */

import React from 'react';

interface UpdateBannerProps {
  latestVersion: string;
  updateType: 'patch' | 'major';
  onDismiss: () => void;
  /** Optional custom message to override the default update text */
  customMessage?: string;
}

export const UpdateBanner: React.FC<UpdateBannerProps> = ({
  latestVersion,
  updateType,
  onDismiss,
  customMessage,
}) => {
  const isPatch = updateType === 'patch';

  // Different styling for patch vs major updates
  const bgColor = isPatch ? 'bg-blue-50' : 'bg-amber-50';
  const borderColor = isPatch ? 'border-blue-200' : 'border-amber-200';
  const textColor = isPatch ? 'text-blue-800' : 'text-amber-800';
  const iconColor = isPatch ? 'text-blue-500' : 'text-amber-500';
  const buttonColor = isPatch
    ? 'text-blue-600 hover:text-blue-800'
    : 'text-amber-600 hover:text-amber-800';

  const message = customMessage
    ? customMessage
    : isPatch
      ? `A new version (v${latestVersion}) is available. Redeploy the app to update.`
      : `A new version (v${latestVersion}) is available. This update requires running the update command from databricks-tellr.`;

  return (
    <div className={`${bgColor} ${borderColor} border-b px-4 py-2`}>
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <div className="flex items-center gap-3">
          {/* Icon */}
          <svg
            className={`w-5 h-5 ${iconColor} flex-shrink-0`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            {isPatch ? (
              // Info icon for patch updates
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            ) : (
              // Warning icon for major updates
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            )}
          </svg>

          {/* Message */}
          <span className={`text-sm ${textColor}`}>
            {message}
            {!isPatch && (
              <code className="ml-1 px-1.5 py-0.5 bg-amber-100 rounded text-xs font-mono">
                tellr.update()
              </code>
            )}
          </span>
        </div>

        {/* Dismiss button */}
        <button
          onClick={onDismiss}
          className={`${buttonColor} p-1 rounded hover:bg-opacity-20 transition-colors`}
          title="Dismiss"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>
  );
};
