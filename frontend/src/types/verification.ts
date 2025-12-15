/**
 * Types for slide verification using LLM as Judge
 */

export type VerificationRating = 'excellent' | 'good' | 'moderate' | 'poor' | 'failing' | 'error' | 'unknown';

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
 * Get badge color based on rating
 */
export const getRatingColor = (rating: VerificationRating): string => {
  switch (rating) {
    case 'excellent':
      return 'bg-green-100 text-green-800 border-green-300';
    case 'good':
      return 'bg-emerald-100 text-emerald-700 border-emerald-300';
    case 'moderate':
      return 'bg-yellow-100 text-yellow-800 border-yellow-300';
    case 'poor':
      return 'bg-orange-100 text-orange-800 border-orange-300';
    case 'failing':
      return 'bg-red-100 text-red-800 border-red-300';
    case 'error':
      return 'bg-gray-100 text-gray-600 border-gray-300';
    default:
      return 'bg-gray-100 text-gray-600 border-gray-300';
  }
};

/**
 * Get badge icon based on rating
 */
export const getRatingIcon = (rating: VerificationRating): string => {
  switch (rating) {
    case 'excellent':
    case 'good':
      return '✓';
    case 'moderate':
      return '~';
    case 'poor':
    case 'failing':
      return '✗';
    case 'error':
      return '!';
    default:
      return '?';
  }
};

/**
 * Get human-readable rating text
 */
export const getRatingText = (rating: VerificationRating): string => {
  switch (rating) {
    case 'excellent':
      return 'Verified - Excellent';
    case 'good':
      return 'Verified - Good';
    case 'moderate':
      return 'Verified - Moderate';
    case 'poor':
      return 'Issues Found';
    case 'failing':
      return 'Verification Failed';
    case 'error':
      return 'Error';
    default:
      return 'Unknown';
  }
};

