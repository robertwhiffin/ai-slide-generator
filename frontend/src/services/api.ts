import type { ChatResponse } from '../types/message';
import type { SlideDeck, Slide, SlideContext, ReplacementInfo } from '../types/slide';

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
};
