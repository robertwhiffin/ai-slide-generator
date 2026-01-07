/**
 * Types for slide verification using LLM as Judge
 * 
 * RAG (Red/Amber/Green) rating system:
 * - green: ≥80% - No issues detected
 * - amber: 50-79% - Review suggested
 * - red: <50% - Review required
 * - unknown: No source data available (title slides, etc.)
 * - error: Verification failed
 */

export type VerificationRating = 'green' | 'amber' | 'red' | 'error' | 'unknown';

export interface VerificationResult {
  score: number;
  rating: VerificationRating;
  explanation: string;
  issues: Array<{ type: string; detail: string }>;
  duration_ms: number;
  trace_id?: string;
  genie_conversation_id?: string;
  error: boolean;
  error_message?: string;
  timestamp?: string;  // ISO string for when verification was done
}

export interface VerificationState {
  [slideIndex: number]: {
    result: VerificationResult;
    isLoading: boolean;
    lastVerifiedAt: string;
    lastEditedAt?: string;  // If edited after verification, show as stale
  };
}

/**
 * Get badge color based on RAG rating
 */
export const getRatingColor = (rating: VerificationRating): string => {
  switch (rating) {
    case 'green':
      return 'bg-green-100 text-green-800 border-green-300';
    case 'amber':
      return 'bg-amber-100 text-amber-800 border-amber-300';
    case 'red':
      return 'bg-red-100 text-red-800 border-red-300';
    case 'error':
    case 'unknown':
    default:
      return 'bg-gray-100 text-gray-600 border-gray-300';
  }
};

/**
 * Get badge icon based on RAG rating
 */
export const getRatingIcon = (rating: VerificationRating): string => {
  switch (rating) {
    case 'green':
      return '●';  // Solid circle for RAG indicator
    case 'amber':
      return '●';
    case 'red':
      return '●';
    case 'error':
      return '!';
    case 'unknown':
    default:
      return '○';  // Empty circle for unknown
  }
};

/**
 * Get human-readable rating text for popup header
 */
export const getRatingText = (rating: VerificationRating): string => {
  switch (rating) {
    case 'green':
      return 'No Issues Detected';
    case 'amber':
      return 'Review Suggested';
    case 'red':
      return 'Review Required';
    case 'error':
      return 'Verification Error';
    case 'unknown':
    default:
      return 'Unable to Verify';
  }
};

/**
 * Get short label for badge display
 */
export const getRatingLabel = (rating: VerificationRating): string => {
  switch (rating) {
    case 'green':
      return 'No issues';
    case 'amber':
      return 'Review suggested';
    case 'red':
      return 'Review required';
    case 'error':
      return 'Error';
    case 'unknown':
    default:
      return 'Unable to verify';
  }
};

