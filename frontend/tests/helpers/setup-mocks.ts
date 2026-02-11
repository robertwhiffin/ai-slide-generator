/**
 * Shared mock setup for E2E tests.
 * Extracted from slide-generator.spec.ts for reuse across test files.
 */
import type { Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
  mockVerificationResponse,
  createStreamingResponse
} from '../fixtures/mocks';

/**
 * Set up API mocks for all common endpoints (profiles, styles, sessions list, etc.).
 * Call this in beforeEach for any test that loads the app.
 */
export async function setupMocks(page: Page) {
  // Mock profiles endpoint
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles)
    });
  });

  // Mock deck prompts endpoint
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts)
    });
  });

  // Mock slide styles endpoint
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles)
    });
  });

  // Mock sessions endpoints
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();

    if (url.includes('limit=')) {
      // Sessions list
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions)
      });
    } else if (url.includes('/slides')) {
      // Slides for a session
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlides)
      });
    } else if (url.includes('/versions')) {
      // Versions for save points
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ versions: [], current_version: null })
      });
    } else if (url.includes('/messages')) {
      // Chat messages
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          messages: [
            { role: 'user', content: 'Create slides about cloud computing', created_at: '2026-01-08T20:39:00' },
            { role: 'assistant', content: 'I\'ll create slides about cloud computing benefits.', created_at: '2026-01-08T20:39:30' },
          ]
        })
      });
    } else {
      // Session details - return 404 for new/unknown sessions
      route.fulfill({ status: 404 });
    }
  });

  // Mock images endpoint
  await page.route('http://127.0.0.1:8000/api/images**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ images: [], total: 0 })
    });
  });

  // Mock verification endpoint
  await page.route('http://127.0.0.1:8000/api/verification/**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVerificationResponse)
    });
  });

  // Mock chat stream endpoint
  await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides)
    });
  });

  // Mock version check endpoint
  await page.route('http://127.0.0.1:8000/api/version', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: '1.0.0' })
    });
  });
}
