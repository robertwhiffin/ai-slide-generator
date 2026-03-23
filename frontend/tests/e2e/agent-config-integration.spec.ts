import { test, expect, Page } from '@playwright/test';
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  getSessionConfig,
  cleanupSession,
  cleanupStyle,
  cleanupDeckPrompt,
  createTestProfile,
  cleanupProfile,
  expandConfigBar,
  addGenieSpace,
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
  if (testStyle?.id) {
    await cleanupStyle(request, testStyle.id as number);
  }
  if (testPrompt?.id) {
    await cleanupDeckPrompt(request, testPrompt.id as number);
  }
});

test.beforeEach(async ({ page }) => {
  await setupIntegrationMocks(page);

  // Clear any pending agent config from localStorage before each test.
  // addInitScript runs before page JS so the slate is clean.
  await page.addInitScript(() => {
    localStorage.removeItem('pendingAgentConfig');
  });
});

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

/**
 * Extract the session ID from the current URL (pattern: /sessions/{uuid}/edit)
 * and track it for cleanup.
 */
function getSessionIdFromUrl(page: Page, trackingArray: string[]): string {
  const url = page.url();
  const match = url.match(/\/sessions\/([^/]+)\/edit/);
  if (!match) {
    throw new Error(`Could not extract session ID from URL: ${url}`);
  }
  const sessionId = match[1];
  trackingArray.push(sessionId);
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

// ---------------------------------------------------------------------------
// Pre-session configuration tests
// ---------------------------------------------------------------------------

test.describe('Pre-session configuration', () => {
  const testSessionIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of testSessionIds) {
      await cleanupSession(request, id);
    }
    testSessionIds.length = 0;
  });

  test('configure Genie tool before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await sendMessage(page, 'Create a sales report');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

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
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

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
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

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
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('send message with no configuration uses defaults', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create a presentation with defaults');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

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
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Mid-session configuration tests
// ---------------------------------------------------------------------------

test.describe('Mid-session configuration', () => {
  const testSessionIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of testSessionIds) {
      await cleanupSession(request, id);
    }
    testSessionIds.length = 0;
  });

  test('add Genie tool mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const toolResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await addGenieSpace(page, 'Sales Data Space');
    await toolResponse;

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].type).toBe('genie');
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);
  });

  test('remove tool mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const addToolResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await addGenieSpace(page, 'Sales Data Space');
    await addToolResponse;

    // Verify tool was added
    let config = await getSessionConfig(request, sessionId);
    let tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);

    // Remove the tool
    const removeToolResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await page.getByRole('button', { name: 'Remove Sales Data Space' }).click();
    await removeToolResponse;

    config = await getSessionConfig(request, sessionId);
    tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(0);
  });

  test('change deck prompt mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const configResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await page.locator('[data-testid="deck-prompt-selector"]').selectOption({
      label: testPrompt.name as string,
    });
    await configResponse;

    const config = await getSessionConfig(request, sessionId);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('change slide style mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const configResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await page.locator('[data-testid="style-selector"]').selectOption({
      label: testStyle.name as string,
    });
    await configResponse;

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).toBe(testStyle.id);
  });
});

// ---------------------------------------------------------------------------
// Load profile into session tests
// ---------------------------------------------------------------------------

test.describe('Load profile into session', () => {
  const testSessionIds: string[] = [];
  let profileA: Record<string, unknown>;
  let profileB: Record<string, unknown>;

  test.beforeAll(async ({ request }) => {
    profileA = await createTestProfile(request, {
      name: `E2E Profile A ${Date.now()}`,
      agentConfig: {
        tools: [
          {
            type: 'genie',
            space_id: mockAvailableTools[0].space_id,
            space_name: mockAvailableTools[0].space_name,
            description: mockAvailableTools[0].description,
            conversation_id: null,
          },
        ],
        slide_style_id: testStyle.id,
        deck_prompt_id: null,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });

    profileB = await createTestProfile(request, {
      name: `E2E Profile B ${Date.now()}`,
      agentConfig: {
        tools: [
          {
            type: 'genie',
            space_id: mockAvailableTools[1].space_id,
            space_name: mockAvailableTools[1].space_name,
            description: mockAvailableTools[1].description,
            conversation_id: null,
          },
        ],
        slide_style_id: null,
        deck_prompt_id: testPrompt.id,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });
  });

  test.afterEach(async ({ request }) => {
    for (const id of testSessionIds) {
      await cleanupSession(request, id);
    }
    testSessionIds.length = 0;
  });

  test.afterAll(async ({ request }) => {
    if (profileA?.id) {
      await cleanupProfile(request, profileA.id as number);
    }
    if (profileB?.id) {
      await cleanupProfile(request, profileB.id as number);
    }
  });

  test('load profile into new session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const loadResponse = page.waitForResponse(resp => resp.url().includes('/load-profile/') && resp.ok());
    await page.locator('[data-testid="load-profile-button"]').click();
    await page.getByText(profileA.name as string).click();
    await loadResponse;

    const config = await getSessionConfig(request, sessionId);
    const tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);
    expect(config.slide_style_id).toBe(testStyle.id);
  });

  // TDD test — fails because confirmation dialog is not implemented yet.
  test.fail('load profile mid-session shows confirmation', async ({ page }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    getSessionIdFromUrl(page, testSessionIds);

    await expandConfigBar(page);
    const toolResponse = page.waitForResponse(resp => resp.url().includes('/agent-config') && resp.ok());
    await addGenieSpace(page, 'Sales Data Space');
    await toolResponse;

    let dialogAppeared = false;
    page.on('dialog', async (dialog) => {
      dialogAppeared = true;
      await dialog.accept();
    });

    await page.locator('[data-testid="load-profile-button"]').click();
    const loadResponse = page.waitForResponse(resp => resp.url().includes('/load-profile/') && resp.ok());
    await page.getByText(profileB.name as string).click();
    await loadResponse;

    // Fails because confirmation dialog not implemented yet
    expect(dialogAppeared).toBe(true);
  });

  test('load profile replaces config entirely', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Start a session');
    const sessionId = getSessionIdFromUrl(page, testSessionIds);

    // Load profile A
    await expandConfigBar(page);
    await page.locator('[data-testid="load-profile-button"]').click();
    const loadResponseA = page.waitForResponse(resp => resp.url().includes('/load-profile/') && resp.ok());
    await page.getByText(profileA.name as string).click();
    await loadResponseA;

    let config = await getSessionConfig(request, sessionId);
    let tools = config.tools as Array<Record<string, unknown>>;
    expect(tools[0].space_id).toBe(mockAvailableTools[0].space_id);

    // Load profile B — should fully replace config
    await page.locator('[data-testid="load-profile-button"]').click();
    const loadResponseB = page.waitForResponse(resp => resp.url().includes('/load-profile/') && resp.ok());
    await page.getByText(profileB.name as string).click();
    await loadResponseB;

    config = await getSessionConfig(request, sessionId);
    tools = config.tools as Array<Record<string, unknown>>;
    expect(tools).toHaveLength(1);
    expect(tools[0].space_id).toBe(mockAvailableTools[1].space_id);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
    expect(config.slide_style_id).toBeNull();
  });
});
