import type { ChatResponse } from '../types/message';
import type { SlideDeck, Slide, SlideContext, ReplacementInfo } from '../types/slide';
import type { VerificationResult } from '../types/verification';

// Use relative URLs in production, localhost in development
const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
);

// Polling interval in milliseconds
const POLL_INTERVAL_MS = 2000;

export class ApiError extends Error {
  status: number;
  
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

/**
 * Detect if we should use polling instead of SSE streaming.
 * 
 * Databricks Apps runs behind a reverse proxy with a 60-second
 * connection timeout, which breaks SSE for long-running requests.
 * 
 * In production mode, we always use polling to be safe.
 * In development, we use SSE for faster feedback.
 */
const isPollingMode = (): boolean => {
  // Explicit override via environment variable
  if (import.meta.env.VITE_USE_POLLING === 'true') {
    return true;
  }
  
  // In production mode, always use polling (Databricks Apps has proxy timeouts)
  if (import.meta.env.MODE === 'production') {
    return true;
  }
  
  // Auto-detect Databricks Apps environment (for dev builds deployed to Databricks)
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    if (
      hostname.includes('.cloud.databricks.com') ||
      hostname.includes('.databricks.com') ||
      hostname.includes('.azuredatabricks.net')
    ) {
      return true;
    }
  }
  
  return false;
};

// Streaming event types matching backend StreamEventType
export type StreamEventType = 'assistant' | 'tool_call' | 'tool_result' | 'error' | 'complete';

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  tool_name?: string;
  tool_input?: Record<string, any>;
  tool_output?: string;
  slides?: SlideDeck;
  error?: string;
  message_id?: number;
  raw_html?: string;
  replacement_info?: ReplacementInfo;
  metadata?: Record<string, any>;
}

export interface SessionMessage {
  id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  message_type?: string;
  created_at: string;
  metadata?: Record<string, any>;
}

export interface Session {
  session_id: string;
  user_id: string | null;
  title: string;
  created_at: string;
  last_activity?: string;
  message_count?: number;
  has_slide_deck?: boolean;
  messages?: SessionMessage[];
  slide_deck?: SlideDeck | null;
  profile_id?: number | null;
  profile_name?: string | null;
}

interface SendMessageParams {
  message: string;
  sessionId: string;
  slideContext?: SlideContext;
}

/**
 * Response from the poll endpoint
 */
interface PollResponse {
  status: 'pending' | 'running' | 'completed' | 'error';
  events: StreamEvent[];
  last_message_id: number;
  result?: {
    slides?: SlideDeck;
    raw_html?: string;
    replacement_info?: ReplacementInfo;
  };
  error?: string;
}

// Session management
let currentSessionId: string | null = null;

export const api = {
  /**
   * Create a new session
   */
  async createSession(title?: string): Promise<Session> {
    const response = await fetch(`${API_BASE_URL}/api/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ title }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        error.detail || 'Failed to create session'
      );
    }

    const session = await response.json();
    currentSessionId = session.session_id;
    return session;
  },

  /**
   * Get or create the current session
   */
  async getOrCreateSession(): Promise<string> {
    if (currentSessionId) {
      return currentSessionId;
    }
    const session = await this.createSession();
    return session.session_id;
  },

  /**
   * Get current session ID (may be null if not initialized)
   */
  getCurrentSessionId(): string | null {
    return currentSessionId;
  },

  /**
   * Set the current session ID (for restoring sessions)
   */
  setCurrentSessionId(sessionId: string | null): void {
    currentSessionId = sessionId;
  },

  /**
   * List all sessions
   */
  async listSessions(limit = 50): Promise<{ sessions: Session[]; count: number }> {
    const response = await fetch(`${API_BASE_URL}/api/sessions?limit=${limit}`);

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to list sessions');
    }

    return response.json();
  },

  /**
   * Get a specific session
   */
  async getSession(sessionId: string): Promise<Session> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`);

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to get session');
    }

    return response.json();
  },

  /**
   * Rename a session
   */
  async renameSession(sessionId: string, title: string): Promise<Session> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}?title=${encodeURIComponent(title)}`, {
      method: 'PATCH',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to rename session');
    }

    return response.json();
  },

  /**
   * Delete a session
   */
  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to delete session');
    }

    if (currentSessionId === sessionId) {
      currentSessionId = null;
    }
  },

  /**
   * Send a message to the chat API
   */
  async sendMessage({
    message,
    sessionId,
    slideContext,
  }: SendMessageParams): Promise<ChatResponse> {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        slide_context: slideContext,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        error.detail || 'Failed to send message'
      );
    }

    return response.json();
  },

  async healthCheck(): Promise<{ status: string }> {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (!response.ok) {
      throw new ApiError(response.status, 'Health check failed');
    }
    return response.json();
  },

  /**
   * Get slide deck for a session
   */
  async getSlides(sessionId: string): Promise<{ session_id: string; slide_deck: SlideDeck | null }> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/slides`);
    
    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to fetch slides');
    }
    
    return response.json();
  },

  /**
   * Reorder slides
   */
  async reorderSlides(
    newOrder: number[],
    sessionId: string
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/reorder`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_order: newOrder, session_id: sessionId }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to reorder slides');
    }

    return response.json();
  },

  /**
   * Update a single slide
   */
  async updateSlide(
    index: number,
    html: string,
    sessionId: string
  ): Promise<Slide> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ html, session_id: sessionId }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to update slide');
    }

    return response.json();
  },

  /**
   * Duplicate a slide
   */
  async duplicateSlide(
    index: number,
    sessionId: string
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to duplicate slide');
    }

    return response.json();
  },

  /**
   * Delete a slide
   */
  async deleteSlide(
    index: number,
    sessionId: string
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}?session_id=${sessionId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to delete slide');
    }

    return response.json();
  },

  /**
   * Update a slide's verification result
   * Persists verification with the session so it survives refresh/restore
   */
  async updateSlideVerification(
    index: number,
    sessionId: string,
    verification: VerificationResult | null
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}/verification`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, verification }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to update slide verification');
    }

    return response.json();
  },

  /**
   * Stream chat messages via Server-Sent Events
   * 
   * @param sessionId - Session ID
   * @param message - User message
   * @param slideContext - Optional slide context for editing
   * @param onEvent - Callback for each streaming event
   * @param onError - Callback for errors
   * @returns Function to cancel the stream
   */
  streamChat(
    sessionId: string,
    message: string,
    slideContext: SlideContext | undefined,
    onEvent: (event: StreamEvent) => void,
    onError: (error: Error) => void,
  ): () => void {
    const controller = new AbortController();

    const runStream = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            session_id: sessionId,
            message,
            slide_context: slideContext,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new ApiError(
            response.status,
            error.detail || 'Failed to start streaming'
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE events
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer
          
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              // Event type is embedded in the JSON data, skip this line
              continue;
            } else if (line.startsWith('data: ')) {
              const data = line.slice(6);
              try {
                const event = JSON.parse(data) as StreamEvent;
                onEvent(event);
              } catch (e) {
                console.warn('Failed to parse SSE data:', data, e);
              }
            }
          }
        }
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          // Stream was cancelled, don't report as error
          return;
        }
        onError(error instanceof Error ? error : new Error(String(error)));
      }
    };

    runStream();

    // Return cancel function
    return () => {
      controller.abort();
    };
  },

  /**
   * Submit a chat request for async processing (polling-based)
   * 
   * @param sessionId - Session ID
   * @param message - User message
   * @param slideContext - Optional slide context for editing
   * @returns Promise with request_id
   */
  async submitChatAsync(
    sessionId: string,
    message: string,
    slideContext?: SlideContext,
  ): Promise<{ request_id: string }> {
    const response = await fetch(`${API_BASE_URL}/api/chat/async`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        slide_context: slideContext,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to submit chat');
    }

    return response.json();
  },

  /**
   * Poll for chat request status and new messages
   * 
   * @param requestId - Request ID from submitChatAsync
   * @param afterMessageId - Return messages after this ID
   * @returns Promise with poll response
   */
  async pollChat(requestId: string, afterMessageId: number = 0): Promise<PollResponse> {
    const response = await fetch(
      `${API_BASE_URL}/api/chat/poll/${requestId}?after_message_id=${afterMessageId}`,
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to poll chat');
    }

    return response.json();
  },

  /**
   * Start polling for chat messages
   * 
   * @param sessionId - Session ID
   * @param message - User message
   * @param slideContext - Optional slide context
   * @param onEvent - Callback for each event
   * @param onError - Callback for errors
   * @returns Function to cancel polling
   */
  startPolling(
    sessionId: string,
    message: string,
    slideContext: SlideContext | undefined,
    onEvent: (event: StreamEvent) => void,
    onError: (error: Error) => void,
  ): () => void {
    let cancelled = false;
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    (async () => {
      try {
        const { request_id } = await this.submitChatAsync(sessionId, message, slideContext);

        let lastMessageId = 0;

        pollInterval = setInterval(async () => {
          if (cancelled) {
            if (pollInterval) clearInterval(pollInterval);
            return;
          }

          try {
            const response = await this.pollChat(request_id, lastMessageId);

            // Process new events
            for (const event of response.events) {
              onEvent(event);
            }
            lastMessageId = response.last_message_id;

            // Stop polling on completion
            if (response.status === 'completed' || response.status === 'error') {
              if (pollInterval) clearInterval(pollInterval);

              if (response.status === 'error') {
                onError(new Error(response.error || 'Request failed'));
              } else if (response.result) {
                // Emit complete event
                onEvent({
                  type: 'complete',
                  slides: response.result.slides,
                  raw_html: response.result.raw_html,
                  replacement_info: response.result.replacement_info,
                });
              }
            }
          } catch (err) {
            console.error('Poll error:', err);
            // Don't stop polling on transient errors
          }
        }, POLL_INTERVAL_MS);

      } catch (err) {
        onError(err instanceof Error ? err : new Error('Failed to start chat'));
      }
    })();

    // Return cancel function
    return () => {
      cancelled = true;
      if (pollInterval) clearInterval(pollInterval);
    };
  },

  /**
   * Send a chat message using the appropriate method (SSE or polling)
   * 
   * Automatically detects the environment and uses:
   * - SSE streaming for local development
   * - Polling for Databricks Apps (due to 60s proxy timeout)
   * 
   * @param sessionId - Session ID
   * @param message - User message
   * @param slideContext - Optional slide context
   * @param onEvent - Callback for each event
   * @param onError - Callback for errors
   * @returns Function to cancel the request
   */
  sendChatMessage(
    sessionId: string,
    message: string,
    slideContext: SlideContext | undefined,
    onEvent: (event: StreamEvent) => void,
    onError: (error: Error) => void,
  ): () => void {
    if (isPollingMode()) {
      return this.startPolling(sessionId, message, slideContext, onEvent, onError);
    } else {
      return this.streamChat(sessionId, message, slideContext, onEvent, onError);
    }
  },

  // ============ Verification API ============

  /**
   * Verify a slide's numerical accuracy against source data
   */
  async verifySlide(
    sessionId: string,
    slideIndex: number
  ): Promise<{
    score: number;
    rating: string;
    explanation: string;
    issues: Array<{ type: string; detail: string }>;
    duration_ms: number;
    trace_id?: string;
    genie_conversation_id?: string;
    error: boolean;
    error_message?: string;
  }> {
    const response = await fetch(`${API_BASE_URL}/api/verification/${slideIndex}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to verify slide');
    }

    return response.json();
  },

  /**
   * Submit feedback on a verification result
   * Feedback is linked to the original verification trace for labeling/review
   */
  async submitVerificationFeedback(
    sessionId: string,
    slideIndex: number,
    isPositive: boolean,
    rationale?: string,
    traceId?: string  // Links feedback to the verification trace in MLflow
  ): Promise<{ status: string; message: string; linked_to_trace: boolean }> {
    const response = await fetch(`${API_BASE_URL}/api/verification/${slideIndex}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        slide_index: slideIndex,
        is_positive: isPositive,
        rationale,
        trace_id: traceId,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to submit feedback');
    }

    return response.json();
  },

  /**
   * Get the Genie conversation link for viewing source data
   */
  async getGenieLink(sessionId: string): Promise<{
    has_genie_conversation: boolean;
    conversation_id?: string;
    url?: string;
    message: string;
  }> {
    const response = await fetch(
      `${API_BASE_URL}/api/verification/genie-link?session_id=${encodeURIComponent(sessionId)}`
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to get Genie link');
    }

    return response.json();
  },

  /**
   * Export slides to PowerPoint format
   * 
   * @param sessionId - Session ID
   * @param useScreenshot - Whether to use screenshots for chart rendering
   * @returns Promise with PPTX file as Blob
   */
  async exportToPPTX(sessionId: string, useScreenshot: boolean = true): Promise<Blob> {
    const response = await fetch(`${API_BASE_URL}/api/export/pptx`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        use_screenshot: useScreenshot,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        error.detail || 'Failed to export PPTX'
      );
    }

    return response.blob();
  },
};
