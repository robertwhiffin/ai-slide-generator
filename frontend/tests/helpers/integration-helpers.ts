/**
 * Integration test helpers — page-level mocks and real-API helpers.
 *
 * Page-level mocks (Task 1): lightweight route intercepts for tests that
 * render the UI but don't need the full setupMocks() kitchen sink.
 *
 * API helpers (Task 2): thin wrappers around Playwright's APIRequestContext
 * that hit the *real* backend so integration tests can create/cleanup
 * sessions, profiles, styles, and prompts.
 */
import type { Page, APIRequestContext } from '@playwright/test';
import { mockAvailableTools } from '../fixtures/mocks';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const API_BASE = 'http://127.0.0.1:8000/api';

// ---------------------------------------------------------------------------
// Minimal slide deck for SSE responses
// ---------------------------------------------------------------------------

export const mockSlideDeck = {
  title: 'Integration Test Deck',
  slide_count: 1,
  css: '',
  external_scripts: [],
  scripts: '',
  slides: [
    {
      index: 0,
      slide_id: 'slide-0',
      html: '<div class="slide-container"><h1>Test Slide</h1></div>',
      scripts: '',
      content_hash: 'abc123',
    },
  ],
  html_content: '<div class="slide-container"><h1>Test Slide</h1></div>',
};

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

/**
 * Build an SSE string containing start → progress → complete events that
 * carry `mockSlideDeck` in the completion payload.
 */
export function createStreamingResponseWithDeck(): string {
  const events: string[] = [];

  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');
  events.push('data: {"type": "progress", "message": "Generating slides..."}\n\n');
  events.push(
    `data: ${JSON.stringify({ type: 'complete', message: 'Generation complete', slide_deck: mockSlideDeck })}\n\n`,
  );

  return events.join('');
}

// ---------------------------------------------------------------------------
// Page-level mocks (Task 1)
// ---------------------------------------------------------------------------

/** Route-intercept GET /api/setup/status returning `{ configured: true }`. */
export async function mockSetupStatus(page: Page): Promise<void> {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ configured: true }),
    });
  });
}

/** Route-intercept GET /api/tools/available using shared mock data. */
export async function mockAvailableToolsEndpoint(page: Page): Promise<void> {
  await page.route('**/api/tools/available', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAvailableTools),
    });
  });
}

/** Route-intercept POST /api/chat/stream with an SSE response. */
export async function mockChatStream(page: Page): Promise<void> {
  await page.route('**/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponseWithDeck(),
    });
  });
}

/**
 * Convenience wrapper — sets up the three lightweight mocks that most
 * integration tests need before navigating.
 */
export async function setupIntegrationMocks(page: Page): Promise<void> {
  await mockSetupStatus(page);
  await mockAvailableToolsEndpoint(page);
  await mockChatStream(page);
}

// ---------------------------------------------------------------------------
// Shared UI helpers
// ---------------------------------------------------------------------------

/** Expand the agent config bar by clicking its toggle. */
export async function expandConfigBar(page: Page): Promise<void> {
  await page.locator('[data-testid="agent-config-toggle"]').click();
  await page.locator('[data-testid="add-tool-button"]').waitFor({ state: 'visible', timeout: 10000 });
}

/**
 * Add a Genie space via the tool picker flow:
 *   1. Click add-tool-button → tool-picker appears
 *   2. Click the space name → genie-detail-panel appears
 *   3. Click "Save & Add" → panel hides
 */
export async function addGenieSpace(page: Page, spaceName: string): Promise<void> {
  await page.locator('[data-testid="add-tool-button"]').click();
  await page.locator('[data-testid="tool-picker"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByText(spaceName).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByRole('button', { name: 'Save & Add' }).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'hidden', timeout: 10000 });
}

// ---------------------------------------------------------------------------
// API helpers (Task 2) — real backend calls via APIRequestContext
// ---------------------------------------------------------------------------

/** POST `/api/sessions` → returns the new session_id. */
export async function createTestSession(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API_BASE}/sessions`);
  if (!res.ok()) throw new Error(`POST /sessions failed: ${res.status()} ${await res.text()}`);
  const body = await res.json();
  return body.session_id as string;
}

/** GET `/api/sessions/{id}/agent-config` → returns the config object. */
export async function getSessionConfig(
  request: APIRequestContext,
  sessionId: string,
): Promise<Record<string, unknown>> {
  const res = await request.get(`${API_BASE}/sessions/${sessionId}/agent-config`);
  if (!res.ok()) throw new Error(`GET /sessions/${sessionId}/agent-config failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as Record<string, unknown>;
}

/** PUT `/api/sessions/{id}/agent-config` → returns the updated config. */
export async function putSessionConfig(
  request: APIRequestContext,
  sessionId: string,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const res = await request.put(`${API_BASE}/sessions/${sessionId}/agent-config`, {
    data: config,
  });
  if (!res.ok()) throw new Error(`PUT /sessions/${sessionId}/agent-config failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as Record<string, unknown>;
}

/**
 * Create a profile the hard way:
 *   1. Create a throwaway session
 *   2. PUT the desired agent-config onto it
 *   3. POST /api/profiles/save-from-session/{sessionId}
 *   4. DELETE the throwaway session (in finally)
 *
 * Returns the newly created profile dict.
 */
export async function createTestProfile(
  request: APIRequestContext,
  opts: {
    name: string;
    description?: string;
    agentConfig?: Record<string, unknown>;
  },
): Promise<Record<string, unknown>> {
  const throwawaySessionId = await createTestSession(request);
  try {
    // Apply config if provided
    if (opts.agentConfig) {
      await putSessionConfig(request, throwawaySessionId, opts.agentConfig);
    }

    const res = await request.post(
      `${API_BASE}/profiles/save-from-session/${throwawaySessionId}`,
      {
        data: {
          name: opts.name,
          description: opts.description ?? `Integration test profile: ${opts.name}`,
        },
      },
    );
    if (!res.ok()) throw new Error(`POST /profiles/save-from-session/${throwawaySessionId} failed: ${res.status()} ${await res.text()}`);
    return (await res.json()) as Record<string, unknown>;
  } finally {
    await cleanupSession(request, throwawaySessionId);
  }
}

/** POST `/api/settings/slide-styles` → returns the created style. */
export async function createTestStyle(
  request: APIRequestContext,
  name: string,
): Promise<Record<string, unknown>> {
  const res = await request.post(`${API_BASE}/settings/slide-styles`, {
    data: {
      name,
      description: `Integration test style: ${name}`,
      category: 'Test',
      style_content: '/* test */',
    },
  });
  if (!res.ok()) throw new Error(`POST /settings/slide-styles failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as Record<string, unknown>;
}

/** POST `/api/settings/deck-prompts` → returns the created prompt. */
export async function createTestDeckPrompt(
  request: APIRequestContext,
  name: string,
): Promise<Record<string, unknown>> {
  const res = await request.post(`${API_BASE}/settings/deck-prompts`, {
    data: {
      name,
      description: `Integration test prompt: ${name}`,
      category: 'Test',
      prompt_content: 'Test prompt content.',
    },
  });
  if (!res.ok()) throw new Error(`POST /settings/deck-prompts failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as Record<string, unknown>;
}

/** DELETE `/api/sessions/{id}` — ignores 404. */
export async function cleanupSession(
  request: APIRequestContext,
  id: string,
): Promise<void> {
  try {
    await request.delete(`${API_BASE}/sessions/${id}`);
  } catch {
    // ignore — session may already be gone
  }
}

/** DELETE `/api/profiles/{id}` — ignores 404. */
export async function cleanupProfile(
  request: APIRequestContext,
  id: number | string,
): Promise<void> {
  try {
    await request.delete(`${API_BASE}/profiles/${id}`);
  } catch {
    // ignore — profile may already be gone
  }
}

/** DELETE `/api/settings/slide-styles/{id}` — ignores errors. */
export async function cleanupStyle(
  request: APIRequestContext,
  id: number | string,
): Promise<void> {
  try {
    await request.delete(`${API_BASE}/settings/slide-styles/${id}`);
  } catch {
    // ignore — style may already be gone
  }
}

/** DELETE `/api/settings/deck-prompts/{id}` — ignores errors. */
export async function cleanupDeckPrompt(
  request: APIRequestContext,
  id: number | string,
): Promise<void> {
  try {
    await request.delete(`${API_BASE}/settings/deck-prompts/${id}`);
  } catch {
    // ignore — prompt may already be gone
  }
}

/** GET `/api/profiles` → returns the array of profile dicts. */
export async function listProfiles(
  request: APIRequestContext,
): Promise<Record<string, unknown>[]> {
  const res = await request.get(`${API_BASE}/profiles`);
  if (!res.ok()) throw new Error(`GET /profiles failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as Record<string, unknown>[];
}
