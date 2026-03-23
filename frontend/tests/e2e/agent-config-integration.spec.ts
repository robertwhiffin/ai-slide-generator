import { test, expect, Page, APIRequestContext } from '@playwright/test';
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  getSessionConfig,
  cleanupSession,
  API_BASE,
} from '../helpers/integration-helpers';
import { mockAvailableTools } from '../fixtures/mocks';

/**
 * Agent Config Integration Tests
 *
 * These tests hit the REAL backend + Postgres. Only chat stream, tools
 * available, and setup status are mocked (via setupIntegrationMocks).
 *
 * They verify that pre-session configuration (Genie tools, deck prompts,
 * slide styles) is correctly persisted to the session's agent-config when
 * the first message is sent.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Run with: npx playwright test tests/e2e/agent-config-integration.spec.ts
 */

// ---------------------------------------------------------------------------
// Shared test data created once for the entire file
// ---------------------------------------------------------------------------

let testStyle: Record<string, unknown>;
let testPrompt: Record<string, unknown>;

// beforeAll uses `request` (APIRequestContext) to create library data that is
// shared read-only across every test in this file. We use beforeAll instead of
// beforeEach because styles and prompts are expensive to create and these tests
// only read them — they never mutate the library items themselves.
test.beforeAll(async ({ request }) => {
  testStyle = await createTestStyle(request, `E2E Style ${Date.now()}`);
  testPrompt = await createTestDeckPrompt(request, `E2E Prompt ${Date.now()}`);
});

test.afterAll(async ({ request }) => {
  // Clean up library data created in beforeAll
  try {
    if (testStyle?.id) {
      await request.delete(`${API_BASE}/settings/slide-styles/${testStyle.id}`);
    }
  } catch {
    // ignore — may already be gone
  }
  try {
    if (testPrompt?.id) {
      await request.delete(`${API_BASE}/settings/deck-prompts/${testPrompt.id}`);
    }
  } catch {
    // ignore — may already be gone
  }
});

// ---------------------------------------------------------------------------
// Per-test session tracking and cleanup
// ---------------------------------------------------------------------------

const testSessionIds: string[] = [];

test.beforeEach(async ({ page }) => {
  await setupIntegrationMocks(page);

  // Clear any pending agent config from localStorage before each test.
  // addInitScript runs before page JS so the slate is clean.
  await page.addInitScript(() => {
    localStorage.removeItem('pendingAgentConfig');
  });
});

test.afterEach(async ({ request }) => {
  // Clean up every session created during the test
  for (const id of testSessionIds) {
    await cleanupSession(request, id);
  }
  testSessionIds.length = 0;
});

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

/**
 * Extract the session ID from the current URL (pattern: /sessions/{uuid}/edit)
 * and track it for cleanup.
 */
async function getSessionIdFromUrl(page: Page): Promise<string> {
  const url = page.url();
  const match = url.match(/\/sessions\/([^/]+)\/edit/);
  if (!match) {
    throw new Error(`Could not extract session ID from URL: ${url}`);
  }
  const sessionId = match[1];
  testSessionIds.push(sessionId);
  return sessionId;
}

/**
 * Type a message and send it, then wait for the slide container to appear
 * (indicating the mocked SSE response was processed).
 */
async function sendMessage(page: Page, message: string): Promise<void> {
  await page.getByRole('textbox').fill(message);
  await page.getByRole('button', { name: 'Send' }).click();
  await page.locator('.slide-container').waitFor({ state: 'visible', timeout: 15000 });
}

/** Expand the agent config bar by clicking its toggle. */
async function expandConfigBar(page: Page): Promise<void> {
  await page.locator('[data-testid="agent-config-toggle"]').click();
  await page.locator('[data-testid="add-tool-button"]').waitFor({ state: 'visible', timeout: 10000 });
}

/**
 * Add a Genie space via the tool picker flow:
 *   1. Click add-tool-button → tool-picker appears
 *   2. Click the space name → genie-detail-panel appears
 *   3. Click "Save & Add" → panel hides
 */
async function addGenieSpace(page: Page, spaceName: string): Promise<void> {
  await page.locator('[data-testid="add-tool-button"]').click();
  await page.locator('[data-testid="tool-picker"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByText(spaceName).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByRole('button', { name: 'Save & Add' }).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'hidden', timeout: 10000 });
}

// ---------------------------------------------------------------------------
// Pre-session configuration tests
// ---------------------------------------------------------------------------

test.describe('Pre-session configuration', () => {
  test('configure Genie tool before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await sendMessage(page, 'Create a sales report');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].type).toBe('genie');
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);
  });

  test('configure deck prompt before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await page.locator('[data-testid="deck-prompt-selector"]').selectOption({
      label: testPrompt.name as string,
    });
    await sendMessage(page, 'Create a presentation');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('configure slide style before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await page.locator('[data-testid="style-selector"]').selectOption({
      label: testStyle.name as string,
    });
    await sendMessage(page, 'Create a presentation');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).toBe(testStyle.id);
  });

  test('configure Genie + deck prompt together', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await page.locator('[data-testid="deck-prompt-selector"]').selectOption({
      label: testPrompt.name as string,
    });
    await sendMessage(page, 'Create a combined report');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('send message with no configuration uses defaults', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create a presentation with defaults');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(0);
    expect(config.deck_prompt_id).toBeNull();
  });

  // TDD placeholder — this test is expected to fail until default styles are implemented.
  // Fails because there is no concept of default styles yet.
  test.fail('new session gets default slide style', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create a presentation');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).not.toBeNull();
  });
});
