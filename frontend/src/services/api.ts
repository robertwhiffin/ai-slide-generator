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

interface SendMessageParams {
  message: string;
  maxSlides?: number;
  slideContext?: SlideContext;
}

export const api = {
  /**
   * Send a message to the chat API
   * 
   * Phase 1: No session_id parameter
   * Phase 4: Add session_id parameter
   */
  async sendMessage({
    message,
    maxSlides = 10,
    slideContext,
  }: SendMessageParams): Promise<ChatResponse> {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        max_slides: maxSlides,
        slide_context: slideContext,
        // session_id: sessionId  // For Phase 4
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
   * Get current slide deck
   * Phase 4: Add sessionId parameter
   */
  async getSlides(/* sessionId?: string */): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides`);
    
    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to fetch slides');
    }
    
    return response.json();
  },

  /**
   * Reorder slides
   * Phase 4: Add sessionId parameter
   */
  async reorderSlides(
    newOrder: number[]
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/reorder`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_order: newOrder }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to reorder slides');
    }

    return response.json();
  },

  /**
   * Update a single slide
   * Phase 4: Add sessionId parameter
   */
  async updateSlide(
    index: number,
    html: string
    /* sessionId?: string */
  ): Promise<Slide> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ html }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to update slide');
    }

    return response.json();
  },

  /**
   * Duplicate a slide
   * Phase 4: Add sessionId parameter
   */
  async duplicateSlide(
    index: number
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}/duplicate`, {
      method: 'POST',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to duplicate slide');
    }

    return response.json();
  },

  /**
   * Delete a slide
   * Phase 4: Add sessionId parameter
   */
  async deleteSlide(
    index: number
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to delete slide');
    }

    return response.json();
  },
};
