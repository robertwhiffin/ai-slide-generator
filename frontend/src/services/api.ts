import type { ChatResponse } from '../types/message';
import type { SlideDeck, Slide, SlideContext } from '../types/slide';

// Use relative URLs in production, localhost in development
const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
);

export class ApiError extends Error {
  status: number;
  
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

interface Session {
  session_id: string;
  user_id: string | null;
  title: string;
  created_at: string;
}

interface SendMessageParams {
  message: string;
  sessionId: string;
  slideContext?: SlideContext;
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
