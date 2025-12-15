import React, { useState } from 'react';
import { FaGavel } from 'react-icons/fa';
import { FiThumbsUp, FiThumbsDown, FiX, FiExternalLink } from 'react-icons/fi';
import type { VerificationResult } from '../../types/verification';
import { getRatingColor, getRatingText, getRatingIcon } from '../../types/verification';
import { api } from '../../services/api';

interface VerificationBadgeProps {
  slideIndex: number;
  sessionId: string;
  verificationResult?: VerificationResult;
  isVerifying: boolean;
  onVerify: () => void;
  isStale?: boolean;  // True if slide was edited after verification
}

export const VerificationBadge: React.FC<VerificationBadgeProps> = ({
  slideIndex,
  sessionId,
  verificationResult,
  isVerifying,
  onVerify,
  isStale,
}) => {
  const [showDetails, setShowDetails] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackRationale, setFeedbackRationale] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

  const handleFeedback = async (isPositive: boolean) => {
    if (!isPositive && !feedbackRationale.trim()) {
      // For negative feedback, require rationale
      setShowFeedback(true);
      return;
    }

    try {
      await api.submitVerificationFeedback(
        sessionId,
        slideIndex,
        isPositive,
        isPositive ? undefined : feedbackRationale
      );
      setFeedbackSubmitted(true);
      setShowFeedback(false);
      setTimeout(() => setFeedbackSubmitted(false), 3000);
    } catch (error) {
      console.error('Failed to submit feedback:', error);
    }
  };

  // No result yet - show verify button
  if (!verificationResult && !isVerifying) {
    return (
      <button
        onClick={onVerify}
        className="p-1 text-amber-600 hover:bg-amber-50 rounded"
        title="Verify slide accuracy"
      >
        <FaGavel size={16} />
      </button>
    );
  }

  // Currently verifying
  if (isVerifying) {
    return (
      <div className="flex items-center space-x-1 px-2 py-0.5 bg-blue-50 rounded text-blue-700 text-xs">
        <span className="animate-spin">⚙</span>
        <span>Verifying...</span>
      </div>
    );
  }

  // Has result
  if (!verificationResult) return null;

  const badgeColor = getRatingColor(verificationResult.rating);
  const badgeIcon = getRatingIcon(verificationResult.rating);

  return (
    <div className="relative">
      {/* Badge */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className={`flex items-center space-x-1 px-2 py-0.5 text-xs font-medium rounded border ${badgeColor} ${
          isStale ? 'opacity-60' : ''
        }`}
        title={isStale ? 'Verification may be outdated - slide was edited' : 'Click for details'}
      >
        <span>{badgeIcon}</span>
        <span>{verificationResult.score}%</span>
        {isStale && <span className="text-orange-500">⚠</span>}
      </button>

      {/* Details Popup */}
      {showDetails && (
        <div className="absolute right-0 top-8 z-50 w-80 bg-white rounded-lg shadow-xl border border-gray-200 p-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h4 className="font-semibold text-gray-800">
              {getRatingText(verificationResult.rating)}
            </h4>
            <button
              onClick={() => setShowDetails(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              <FiX size={18} />
            </button>
          </div>

          {/* Score */}
          <div className="mb-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600">Accuracy Score</span>
              <span className={`font-bold ${
                verificationResult.score >= 70 ? 'text-green-600' : 
                verificationResult.score >= 50 ? 'text-yellow-600' : 'text-red-600'
              }`}>
                {verificationResult.score}%
              </span>
            </div>
            <div className="mt-1 h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full ${
                  verificationResult.score >= 70 ? 'bg-green-500' : 
                  verificationResult.score >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${verificationResult.score}%` }}
              />
            </div>
          </div>

          {/* Explanation */}
          <div className="mb-3">
            <p className="text-sm text-gray-700">{verificationResult.explanation}</p>
          </div>

          {/* Issues */}
          {verificationResult.issues.length > 0 && (
            <div className="mb-3">
              <h5 className="text-xs font-medium text-gray-500 uppercase mb-1">Issues</h5>
              <ul className="text-sm text-red-700 space-y-1">
                {verificationResult.issues.map((issue, i) => (
                  <li key={i} className="flex items-start">
                    <span className="mr-1">•</span>
                    <span>{issue.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Stale Warning */}
          {isStale && (
            <div className="mb-3 p-2 bg-orange-50 rounded text-xs text-orange-700">
              ⚠️ Slide was edited after verification. Results may be outdated.
              <button
                onClick={() => {
                  setShowDetails(false);
                  onVerify();
                }}
                className="ml-2 underline hover:no-underline"
              >
                Re-verify
              </button>
            </div>
          )}

          {/* Genie Link */}
          {verificationResult.genie_conversation_id && (
            <button
              onClick={async () => {
                try {
                  const link = await api.getGenieLink(sessionId);
                  if (link.url) {
                    window.open(link.url, '_blank');
                  }
                } catch (error) {
                  console.error('Failed to get Genie link:', error);
                }
              }}
              className="flex items-center space-x-1 text-xs text-blue-600 hover:text-blue-800 mb-3"
            >
              <FiExternalLink size={12} />
              <span>View Source Data in Genie</span>
            </button>
          )}

          {/* Feedback */}
          {!feedbackSubmitted && !showFeedback && (
            <div className="flex items-center justify-between pt-3 border-t">
              <span className="text-xs text-gray-500">Is this accurate?</span>
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => handleFeedback(true)}
                  className="p-1.5 text-green-600 hover:bg-green-50 rounded"
                  title="Yes, accurate"
                >
                  <FiThumbsUp size={16} />
                </button>
                <button
                  onClick={() => handleFeedback(false)}
                  className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                  title="No, issues found"
                >
                  <FiThumbsDown size={16} />
                </button>
              </div>
            </div>
          )}

          {/* Feedback Form */}
          {showFeedback && (
            <div className="pt-3 border-t">
              <label className="text-xs text-gray-600 block mb-1">
                What's wrong with this assessment?
              </label>
              <textarea
                value={feedbackRationale}
                onChange={(e) => setFeedbackRationale(e.target.value)}
                className="w-full text-sm border rounded p-2 h-16 resize-none"
                placeholder="Please describe the issue..."
              />
              <div className="flex justify-end space-x-2 mt-2">
                <button
                  onClick={() => setShowFeedback(false)}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleFeedback(false)}
                  disabled={!feedbackRationale.trim()}
                  className="text-xs bg-red-500 text-white px-3 py-1 rounded hover:bg-red-600 disabled:opacity-50"
                >
                  Submit
                </button>
              </div>
            </div>
          )}

          {/* Feedback Submitted */}
          {feedbackSubmitted && (
            <div className="pt-3 border-t text-center text-xs text-green-600">
              ✓ Feedback submitted. Thank you!
            </div>
          )}

          {/* Meta Info */}
          <div className="mt-3 pt-2 border-t text-xs text-gray-400 flex justify-between">
            <span>Duration: {verificationResult.duration_ms}ms</span>
            {verificationResult.trace_id && (
              <span className="font-mono">{verificationResult.trace_id.substring(0, 12)}...</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

