import React, { useState, useRef, useEffect } from 'react';
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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  // Click-away to close popup
  useEffect(() => {
    if (!showDetails) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(event.target as Node)) {
        setShowDetails(false);
      }
    };

    // Delay to prevent immediate close on badge click
    const timeoutId = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showDetails]);

  const handleFeedback = async (isPositive: boolean) => {
    if (!isPositive && !feedbackRationale.trim()) {
      // For negative feedback, require rationale
      setShowFeedback(true);
      return;
    }

    if (isSubmitting) return;
    setIsSubmitting(true);

    try {
      // Pass trace_id to link feedback to the original verification trace in MLflow
      // This enables labeling sessions where reviewers can see feedback
      await api.submitVerificationFeedback(
        sessionId,
        slideIndex,
        isPositive,
        isPositive ? undefined : feedbackRationale,
        verificationResult?.trace_id  // Links feedback to verification trace
      );
      setFeedbackSubmitted(true);
      setShowFeedback(false);
      setFeedbackRationale('');
      // Don't reset feedbackSubmitted - keep it permanent until re-verification
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      setIsSubmitting(false);  // Allow retry on error
    }
  };

  // Handle Enter key in textarea
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && feedbackRationale.trim()) {
      e.preventDefault();
      handleFeedback(false);
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

      {/* Click-away overlay */}
      {showDetails && (
        <div 
          className="fixed inset-0 z-40"
          onClick={() => setShowDetails(false)}
        />
      )}

      {/* Details Popup */}
      {showDetails && (
        <div 
          ref={popupRef}
          className="absolute right-0 top-8 z-50 w-80 bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col max-h-[500px]"
        >
          {/* Fixed Header */}
          <div className="p-4 pb-0 flex-shrink-0">
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
          </div>

          {/* Scrollable Content Area - Explanation & Issues */}
          <div className="px-4 overflow-y-auto flex-1 min-h-0">
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
          </div>

          {/* Fixed Footer */}
          <div className="p-4 pt-3 flex-shrink-0 border-t bg-gray-50 rounded-b-lg">
            {/* MLflow Trace ID */}
            {verificationResult.trace_id && (
              <div className="mb-3 p-2 bg-white rounded border">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">MLflow Trace ID:</span>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(verificationResult.trace_id || '');
                      alert('Trace ID copied!');
                    }}
                    className="text-xs text-blue-600 hover:underline"
                    title="Copy trace ID"
                  >
                    Copy
                  </button>
                </div>
                <code className="text-xs text-gray-700 break-all">{verificationResult.trace_id}</code>
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

            {/* Feedback - only show if not already submitted */}
            {!feedbackSubmitted && !showFeedback && (
              <div className="flex items-center justify-between pt-2 border-t">
                <span className="text-xs text-gray-500">Is this accurate?</span>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => handleFeedback(true)}
                    disabled={isSubmitting}
                    className="p-1.5 text-green-600 hover:bg-green-50 rounded disabled:opacity-50"
                    title="Yes, accurate"
                  >
                    <FiThumbsUp size={16} />
                  </button>
                  <button
                    onClick={() => handleFeedback(false)}
                    disabled={isSubmitting}
                    className="p-1.5 text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                    title="No, issues found"
                  >
                    <FiThumbsDown size={16} />
                  </button>
                </div>
              </div>
            )}

            {/* Feedback Form */}
            {showFeedback && !feedbackSubmitted && (
              <div className="pt-2 border-t">
                <label className="text-xs text-gray-600 block mb-1">
                  What's wrong with this assessment?
                </label>
                <textarea
                  value={feedbackRationale}
                  onChange={(e) => setFeedbackRationale(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="w-full text-sm border rounded p-2 h-16 resize-none"
                  placeholder="Please describe the issue... (Enter to submit)"
                  disabled={isSubmitting}
                  autoFocus
                />
                <div className="flex justify-end space-x-2 mt-2">
                  <button
                    onClick={() => {
                      setShowFeedback(false);
                      setFeedbackRationale('');
                    }}
                    className="text-xs text-gray-500 hover:text-gray-700"
                    disabled={isSubmitting}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => handleFeedback(false)}
                    disabled={!feedbackRationale.trim() || isSubmitting}
                    className="text-xs bg-red-500 text-white px-3 py-1 rounded hover:bg-red-600 disabled:opacity-50"
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit'}
                  </button>
                </div>
              </div>
            )}

            {/* Feedback Submitted */}
            {feedbackSubmitted && (
              <div className="pt-2 border-t text-center text-xs text-green-600">
                ✓ Feedback submitted. Thank you!
              </div>
            )}

            {/* Meta Info */}
            <div className="mt-2 pt-2 border-t text-xs text-gray-400 flex justify-between">
              <span>Duration: {verificationResult.duration_ms}ms</span>
              {verificationResult.trace_id && (
                <span className="font-mono">{verificationResult.trace_id.substring(0, 12)}...</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

