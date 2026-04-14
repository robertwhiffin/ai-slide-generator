import React from 'react';
import type { ReplacementInfo } from '../../types/slide';
import './ReplacementFeedback.css';

interface ReplacementFeedbackProps {
  replacementInfo: ReplacementInfo;
}

const buildMessage = (info: ReplacementInfo): string => {
  const originalCount = info.original_count ?? info.original_indices?.length ?? 0;
  const replacementCount = info.replacement_count ?? 0;
  const netChange =
    info.net_change ?? replacementCount - originalCount;

  if (netChange === 0) {
    return `✓ Replaced ${originalCount} slide${originalCount === 1 ? '' : 's'}`;
  }

  if (netChange > 0) {
    return `✓ Expanded ${originalCount} slide${originalCount === 1 ? '' : 's'} into ${replacementCount} (+${netChange})`;
  }

  return `✓ Condensed ${originalCount} slide${originalCount === 1 ? '' : 's'} into ${replacementCount} (${netChange})`;
};

export const ReplacementFeedback: React.FC<ReplacementFeedbackProps> = ({
  replacementInfo,
}) => {
  // RC14: If only sync_error, show error without success message
  if (replacementInfo.sync_error && !replacementInfo.original_count) {
    return (
      <div className="replacement-feedback-container">
        <div className="replacement-feedback sync-error">
          {replacementInfo.sync_error}
        </div>
      </div>
    );
  }

  return (
    <div className="replacement-feedback-container">
      <div className="replacement-feedback success">
        {buildMessage(replacementInfo)}
      </div>
      {replacementInfo.conflict_note && (
        <div className="replacement-feedback conflict-note">
          {replacementInfo.conflict_note}
        </div>
      )}
    </div>
  );
};

