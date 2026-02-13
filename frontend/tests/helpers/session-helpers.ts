/**
 * Test helpers for session-related mocks.
 * Provides deterministic session IDs and mock setup for session loading tests.
 */
import type { Page } from '@playwright/test';
import { mockSlides } from '../fixtures/mocks';

// Fixed session IDs for deterministic test URLs
export const TEST_SESSION_ID = 'b1b4d8e3-6cf6-47cb-ad58-9fdc6ad205cc';

// Mock session detail data
export const mockSessionDetail = {
  session_id: TEST_SESSION_ID,
  user_id: null,
  created_by: 'dev@local.dev',
  title: 'Test Session With Slides',
  has_slide_deck: true,
  profile_id: 1,
  profile_name: 'Sales Analytics',
  created_at: '2026-01-08T20:38:56.749592',
  last_activity: '2026-01-08T20:42:11.058737',
  message_count: 3,
};

// Mock slides response in the format api.getSlides() returns
export const mockSlidesResponse = {
  session_id: TEST_SESSION_ID,
  slide_deck: {
    title: 'Benefits of Cloud Computing',
    slide_count: 3,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: mockSlides.map((s, i) => ({
      index: i,
      slide_id: `slide-${i}`,
      html: s.html_content,
      scripts: '',
      content_hash: s.hash,
    })),
    html_content: mockSlides.map(s => s.html_content).join('\n'),
  },
};

/**
 * Set up route mocks for a specific session that has slides.
 * Call this AFTER setupMocks() — Playwright uses LIFO ordering,
 * so this more specific route takes precedence over the generic sessions** handler.
 */
export async function mockSessionWithSlides(page: Page, sessionId: string = TEST_SESSION_ID) {
  // Mock session detail endpoint (exact URL match, no sub-paths)
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, (route) => {
    const url = route.request().url();
    // Only handle exact session detail URL, not sub-paths like /slides, /versions
    if (url.endsWith(sessionId)) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockSessionDetail, session_id: sessionId }),
      });
    } else {
      route.fallback();
    }
  });

  // Mock slides endpoint for this specific session
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/slides`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...mockSlidesResponse, session_id: sessionId }),
    });
  });

  // Mock versions endpoint for this specific session
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/versions`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ versions: [], current_version: null }),
    });
  });

  // Mock messages endpoint for this specific session
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/messages`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        messages: [
          { role: 'user', content: 'Create slides about cloud computing', created_at: '2026-01-08T20:39:00' },
          { role: 'assistant', content: "I'll create slides about cloud computing benefits.", created_at: '2026-01-08T20:39:30' },
        ],
      }),
    });
  });
}

/**
 * Mock a session that returns 404 (doesn't exist).
 */
export async function mockSessionNotFound(page: Page, sessionId: string) {
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, (route) => {
    const url = route.request().url();
    if (url.endsWith(sessionId)) {
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Session not found' }),
      });
    } else {
      route.fallback();
    }
  });
}
