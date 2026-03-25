# Agent Config E2E Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two Playwright integration test files (19 tests total) covering agent config workflows against a real backend + Postgres, plus CI matrix updates.

**Architecture:** Shared helpers in `integration-helpers.ts` provide API-driven test data setup/teardown and page-level mocks for chat stream, tool discovery, and setup status. Two test files — `agent-config-integration.spec.ts` (session config flows) and `profiles-integration.spec.ts` (profile page CRUD) — both hit the real backend for all database operations. Only `/api/chat/stream`, `/api/tools/available`, and `/api/setup/status` are mocked at the Playwright route level.

**Tech Stack:** Playwright, TypeScript, FastAPI backend, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-21-agent-config-e2e-tests-design.md`

---

### Task 1: Create `integration-helpers.ts` — page-level mocks

**Files:**
- Create: `frontend/tests/helpers/integration-helpers.ts`

- [ ] **Step 1: Write the mock helpers file**

```typescript
/**
 * Integration test helpers — shared by agent-config and profiles integration tests.
 *
 * Page-level mocks intercept only endpoints that require external services
 * (LLM, Databricks SDK). Everything else hits the real backend + Postgres.
 */
import type { Page, APIRequestContext } from '@playwright/test';
import { mockAvailableTools } from '../fixtures/mocks';

// Base URL for direct API calls (bypassing the browser)
export const API_BASE = 'http://127.0.0.1:8000/api';

// ── Slide deck for SSE mock ───────────────────────────────────────────

const mockSlideDeck = {
  title: 'Test Deck',
  slide_count: 1,
  css: '',
  scripts: '',
  external_scripts: [],
  slides: [
    {
      slide_id: 'slide-0',
      title: 'Test Slide',
      html: '<div class="slide-container"><h1>Test Slide</h1></div>',
      content_hash: 'abc123',
      scripts: '',
      verification: null,
    },
  ],
};

/**
 * Create a structured SSE response with start → progress → complete events
 * and a full slide deck payload. This is the "with deck" variant used by
 * integration tests. The simpler `createStreamingResponse` in mocks.ts is
 * for unit-like E2E tests that don't need slide content.
 */
export function createStreamingResponseWithDeck(): string {
  const events: string[] = [];
  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');
  events.push('data: {"type": "progress", "message": "Generating slides..."}\n\n');
  events.push(`data: {"type": "complete", "message": "Generation complete", "slides": ${JSON.stringify(mockSlideDeck)}}\n\n`);
  return events.join('');
}

// ── Page-level mocks ──────────────────────────────────────────────────

/** Mock /api/setup/status to bypass the welcome screen. */
export async function mockSetupStatus(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ configured: true }),
    });
  });
}

/**
 * Mock /api/tools/available — returns the fixed tool list from mocks.ts.
 * Tests reference the same space_id values for assertions.
 */
export async function mockAvailableToolsEndpoint(page: Page) {
  await page.route('**/api/tools/available', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAvailableTools),
    });
  });
}

/** Mock /api/chat/stream — returns a structured SSE slide deck response. */
export async function mockChatStream(page: Page) {
  await page.route('**/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponseWithDeck(),
    });
  });
}

/** Apply all three page-level mocks needed for integration tests. */
export async function setupIntegrationMocks(page: Page) {
  await mockSetupStatus(page);
  await mockAvailableToolsEndpoint(page);
  await mockChatStream(page);
}
```

- [ ] **Step 2: Verify the file compiles**

Run: `cd frontend && npx tsc --noEmit tests/helpers/integration-helpers.ts 2>&1 || echo "Checking imports only"`

If tsc doesn't pick up test files directly, just verify no red squiggles by running the full build: `cd frontend && npx tsc -b`

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/helpers/integration-helpers.ts
git commit -m "test: add integration-helpers.ts with page-level mocks for E2E integration tests"
```

---

### Task 2: Add API helpers to `integration-helpers.ts`

**Files:**
- Modify: `frontend/tests/helpers/integration-helpers.ts`

- [ ] **Step 1: Add API helper functions**

Append the following to `integration-helpers.ts`:

```typescript
// ── API helpers (use Playwright `request` fixture) ────────────────────

/** Create a session via API. Returns the session_id. */
export async function createTestSession(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${API_BASE}/sessions`, {
    data: { title: `E2E Test ${Date.now()}` },
  });
  if (!response.ok()) {
    throw new Error(`Failed to create session: ${response.status()} ${await response.text()}`);
  }
  const data = await response.json();
  return data.session_id;
}

/** Get the agent config for a session. */
export async function getSessionConfig(request: APIRequestContext, sessionId: string) {
  const response = await request.get(`${API_BASE}/sessions/${sessionId}/agent-config`);
  if (!response.ok()) {
    throw new Error(`Failed to get config: ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/** PUT a full agent config onto a session. */
export async function putSessionConfig(
  request: APIRequestContext,
  sessionId: string,
  config: Record<string, unknown>,
) {
  const response = await request.put(`${API_BASE}/sessions/${sessionId}/agent-config`, {
    data: config,
  });
  if (!response.ok()) {
    throw new Error(`Failed to put config: ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/**
 * Create a profile via the save-from-session flow.
 *
 * Multi-step: (1) create throwaway session, (2) PUT config, (3) save-from-session,
 * (4) delete throwaway session. The throwaway is always cleaned up via try/finally.
 */
export async function createTestProfile(
  request: APIRequestContext,
  opts: {
    name: string;
    description?: string;
    tools?: Array<Record<string, unknown>>;
    styleId?: number | null;
    promptId?: number | null;
  },
) {
  const throwawaySessionId = await createTestSession(request);
  try {
    // PUT the desired config onto the throwaway session
    await putSessionConfig(request, throwawaySessionId, {
      tools: opts.tools ?? [],
      slide_style_id: opts.styleId ?? null,
      deck_prompt_id: opts.promptId ?? null,
      system_prompt: null,
      slide_editing_instructions: null,
    });

    // Save as profile
    const response = await request.post(
      `${API_BASE}/profiles/save-from-session/${throwawaySessionId}`,
      { data: { name: opts.name, description: opts.description ?? null } },
    );
    if (!response.ok()) {
      throw new Error(`Failed to save profile: ${response.status()} ${await response.text()}`);
    }
    return response.json();
  } finally {
    // Always clean up throwaway session
    await request.delete(`${API_BASE}/sessions/${throwawaySessionId}`).catch(() => {});
  }
}

/** Create a slide style via API. Returns the created style. */
export async function createTestStyle(
  request: APIRequestContext,
  name: string,
) {
  const response = await request.post(`${API_BASE}/settings/slide-styles`, {
    data: {
      name,
      description: `E2E test style ${Date.now()}`,
      category: 'Test',
      style_content: '/* test CSS */',
    },
  });
  if (!response.ok()) {
    throw new Error(`Failed to create style: ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/** Create a deck prompt via API. Returns the created prompt. */
export async function createTestDeckPrompt(
  request: APIRequestContext,
  name: string,
) {
  const response = await request.post(`${API_BASE}/settings/deck-prompts`, {
    data: {
      name,
      description: `E2E test prompt ${Date.now()}`,
      category: 'Test',
      prompt_content: 'Test prompt content for E2E.',
    },
  });
  if (!response.ok()) {
    throw new Error(`Failed to create prompt: ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/** Delete a session via API. Ignores 404 (already deleted). */
export async function cleanupSession(request: APIRequestContext, sessionId: string) {
  const response = await request.delete(`${API_BASE}/sessions/${sessionId}`);
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete session ${sessionId}: ${response.status()}`);
  }
}

/** Soft-delete a profile via API. Ignores 404 (already deleted). */
export async function cleanupProfile(request: APIRequestContext, profileId: number) {
  const response = await request.delete(`${API_BASE}/profiles/${profileId}`);
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete profile ${profileId}: ${response.status()}`);
  }
}

/** List all profiles. Used for cleanup in empty-state tests. */
export async function listProfiles(request: APIRequestContext) {
  const response = await request.get(`${API_BASE}/profiles`);
  if (!response.ok()) {
    throw new Error(`Failed to list profiles: ${response.status()}`);
  }
  return response.json();
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc -b`

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/helpers/integration-helpers.ts
git commit -m "test: add API helpers (session, profile, style, prompt CRUD) to integration-helpers.ts"
```

---

### Task 3: Create `agent-config-integration.spec.ts` — scaffolding and pre-session tests

**Files:**
- Create: `frontend/tests/e2e/agent-config-integration.spec.ts`

- [ ] **Step 1: Write the test file scaffolding + pre-session describe block**

```typescript
import { test, expect } from '@playwright/test';
import { mockAvailableTools as mockToolsPayload } from '../fixtures/mocks';
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  getSessionConfig,
  cleanupSession,
  API_BASE,
} from '../helpers/integration-helpers';

/**
 * Agent Config Integration Tests
 *
 * These tests hit the real backend + Postgres for all database operations.
 * Only /api/chat/stream, /api/tools/available, and /api/setup/status are mocked.
 *
 * Prerequisites:
 * - Backend running at http://127.0.0.1:8000
 * - Database accessible and seeded
 *
 * Run: cd frontend && npx playwright test tests/e2e/agent-config-integration.spec.ts
 */

// ── Shared test data ─────────────────────────────────────────────────
// Created once in beforeAll — read-only reference data that no test mutates.
// This diverges from existing integration tests (which use beforeEach) because
// library data is never modified by tests, just referenced via dropdowns.

let testStyle: { id: number; name: string };
let testPrompt: { id: number; name: string };

test.beforeAll(async ({ request }) => {
  testStyle = await createTestStyle(request, `E2E Style ${Date.now()}`);
  testPrompt = await createTestDeckPrompt(request, `E2E Prompt ${Date.now()}`);
});

test.afterAll(async ({ request }) => {
  // Clean up library data — best-effort
  await request.delete(`${API_BASE}/settings/slide-styles/${testStyle?.id}`).catch(() => {});
  await request.delete(`${API_BASE}/settings/deck-prompts/${testPrompt?.id}`).catch(() => {});
});

// ── Per-test setup ───────────────────────────────────────────────────

// Track sessions created during tests for cleanup
let testSessionIds: string[] = [];

test.beforeEach(async ({ page }) => {
  testSessionIds = [];
  await setupIntegrationMocks(page);

  // Clear localStorage to prevent pre-session state leaking between tests
  await page.addInitScript(() => {
    localStorage.removeItem('pendingAgentConfig');
  });
});

test.afterEach(async ({ request }) => {
  for (const id of testSessionIds) {
    await cleanupSession(request, id);
  }
});

// ── Helpers ──────────────────────────────────────────────────────────

/** Extract session ID from the URL after session creation. */
async function getSessionIdFromUrl(page: import('@playwright/test').Page): Promise<string> {
  await page.waitForURL(/\/sessions\/[^/]+\/edit/, { timeout: 15000 });
  const match = page.url().match(/\/sessions\/([^/]+)\/edit/);
  if (!match) throw new Error(`Could not extract session ID from URL: ${page.url()}`);
  const sessionId = match[1];
  testSessionIds.push(sessionId);
  return sessionId;
}

/** Send a chat message and wait for generation to complete. */
async function sendMessage(page: import('@playwright/test').Page, message: string) {
  const input = page.getByRole('textbox');
  await input.fill(message);
  await page.getByRole('button', { name: 'Send' }).click();
  // Wait for the streaming response to complete (slide appears)
  await page.waitForSelector('.slide-container', { timeout: 15000 });
}

/** Expand the AgentConfigBar to access dropdowns and tools. */
async function expandConfigBar(page: import('@playwright/test').Page) {
  const toggle = page.getByTestId('agent-config-toggle');
  await toggle.click();
  await page.getByTestId('add-tool-button').waitFor({ state: 'visible', timeout: 5000 });
}

/** Add a Genie space by name via the ToolPicker UI. */
async function addGenieSpace(page: import('@playwright/test').Page, spaceName: string) {
  await page.getByTestId('add-tool-button').click();
  await page.getByTestId('tool-picker').waitFor({ state: 'visible' });
  await page.getByTestId('tool-picker').getByText(spaceName).click();
  // GenieDetailPanel appears — click Save & Add
  await page.getByTestId('genie-detail-panel').waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'Save & Add' }).click();
  await page.getByTestId('genie-detail-panel').waitFor({ state: 'hidden', timeout: 5000 });
}

// ── Pre-session configuration ────────────────────────────────────────

test.describe('Pre-session configuration', () => {
  test('configure Genie tool before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');

    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);
    expect(config.tools[0].type).toBe('genie');
    expect(config.tools[0].space_id).toBe(mockToolsPayload[0].space_id);
  });

  test('configure deck prompt before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);

    // Select test prompt from dropdown
    const promptSelector = page.getByTestId('deck-prompt-selector');
    await promptSelector.selectOption({ label: testPrompt.name });

    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('configure slide style before first message', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);

    // Select test style from dropdown
    const styleSelector = page.getByTestId('style-selector');
    await styleSelector.selectOption({ label: testStyle.name });

    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).toBe(testStyle.id);
  });

  test('configure Genie + deck prompt together', async ({ page, request }) => {
    await page.goto('/');
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');

    const promptSelector = page.getByTestId('deck-prompt-selector');
    await promptSelector.selectOption({ label: testPrompt.name });

    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);
    expect(config.tools[0].space_id).toBe(mockToolsPayload[0].space_id);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('send message with no configuration uses defaults', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(0);
    expect(config.deck_prompt_id).toBeNull();
    // slide_style_id may or may not be null depending on defaults
  });

  test.fail('new session gets default slide style', async ({ page, request }) => {
    // TDD: This test documents desired behavior — new sessions should
    // automatically get a default slide style even when the user doesn't pick one.
    // Fails because there is no concept of "default style" yet.
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    const config = await getSessionConfig(request, sessionId);
    // The session should have a style assigned even without user picking one
    expect(config.slide_style_id).not.toBeNull();
    // When implemented, also verify: the ID matches a style marked as default in the library
  });
});
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc -b`

- [ ] **Step 3: Run the pre-session tests against the local backend (expect passes for 5, fail for 1)**

Run: `cd frontend && npx playwright test tests/e2e/agent-config-integration.spec.ts --grep "Pre-session" --project=chromium --workers=1`

Note: The backend must be running locally. If not, skip this step — these will be validated in CI.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e/agent-config-integration.spec.ts
git commit -m "test: add agent-config-integration.spec.ts with pre-session config tests"
```

---

### Task 4: Add mid-session configuration tests

**Files:**
- Modify: `frontend/tests/e2e/agent-config-integration.spec.ts`

- [ ] **Step 1: Add the mid-session describe block**

Append before the closing of the file:

```typescript
// ── Mid-session configuration ────────────────────────────────────────

test.describe('Mid-session configuration', () => {
  test('add Genie tool mid-session', async ({ page, request }) => {
    // Create session first by sending a message
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    // Now add a tool in the active session
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');

    // Wait for config to persist (optimistic update + PUT)
    await page.waitForTimeout(1000);

    const config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);
    expect(config.tools[0].type).toBe('genie');
    expect(config.tools[0].space_id).toBe(mockToolsPayload[0].space_id);
  });

  test('remove tool mid-session', async ({ page, request }) => {
    // Create session and add a tool
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await page.waitForTimeout(500);

    // Verify tool was added
    let config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);

    // Remove via the X button on the chip
    await page.getByRole('button', { name: 'Remove Sales Data Space' }).click();
    await page.waitForTimeout(1000);

    config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(0);
  });

  test('change deck prompt mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    await expandConfigBar(page);
    const promptSelector = page.getByTestId('deck-prompt-selector');
    await promptSelector.selectOption({ label: testPrompt.name });
    await page.waitForTimeout(1000);

    const config = await getSessionConfig(request, sessionId);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
  });

  test('change slide style mid-session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    await expandConfigBar(page);
    const styleSelector = page.getByTestId('style-selector');
    await styleSelector.selectOption({ label: testStyle.name });
    await page.waitForTimeout(1000);

    const config = await getSessionConfig(request, sessionId);
    expect(config.slide_style_id).toBe(testStyle.id);
  });
});
```

- [ ] **Step 2: Run mid-session tests**

Run: `cd frontend && npx playwright test tests/e2e/agent-config-integration.spec.ts --grep "Mid-session" --project=chromium --workers=1`

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/agent-config-integration.spec.ts
git commit -m "test: add mid-session configuration tests to agent-config-integration"
```

---

### Task 5: Add load-profile-into-session tests

**Files:**
- Modify: `frontend/tests/e2e/agent-config-integration.spec.ts`

- [ ] **Step 1: Add the load-profile describe block**

Append before the closing of the file:

```typescript
// ── Load profile into session ────────────────────────────────────────

test.describe('Load profile into session', () => {
  let profileA: { id: number; name: string };
  let profileB: { id: number; name: string };

  test.beforeAll(async ({ request }) => {
    // Create two profiles with distinct configs for testing
    profileA = await createTestProfile(request, {
      name: `E2E Profile A ${Date.now()}`,
      description: 'Profile A for load testing',
      tools: [{
        type: 'genie',
        space_id: mockToolsPayload[0].space_id,
        space_name: mockToolsPayload[0].space_name,
      }],
      styleId: testStyle.id,
    });
    profileB = await createTestProfile(request, {
      name: `E2E Profile B ${Date.now()}`,
      description: 'Profile B for replacement testing',
      tools: [{
        type: 'genie',
        space_id: mockToolsPayload[1].space_id,
        space_name: mockToolsPayload[1].space_name,
      }],
      promptId: testPrompt.id,
    });
  });

  test.afterAll(async ({ request }) => {
    await cleanupProfile(request, profileA?.id);
    await cleanupProfile(request, profileB?.id);
  });

  test('load profile into new session', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    // Open config bar and load profile A
    await expandConfigBar(page);
    await page.getByTestId('load-profile-button').click();
    await page.getByText(profileA.name).click();
    await page.waitForTimeout(1000);

    const config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);
    expect(config.tools[0].space_id).toBe(mockToolsPayload[0].space_id);
    expect(config.slide_style_id).toBe(testStyle.id);
  });

  test.fail('load profile mid-session shows confirmation', async ({ page, request }) => {
    // TDD: Loading a profile into a session that already has config should
    // show a window.confirm() dialog before overwriting. Matches the existing
    // destructive action pattern (e.g., session delete in history-integration).
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    await getSessionIdFromUrl(page);

    // Add a tool to establish existing config
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await page.waitForTimeout(500);

    // Set up dialog listener BEFORE triggering load
    let dialogAppeared = false;
    page.on('dialog', async (dialog) => {
      dialogAppeared = true;
      await dialog.accept();
    });

    // Try to load a different profile
    await page.getByTestId('load-profile-button').click();
    await page.getByText(profileB.name).click();
    await page.waitForTimeout(1000);

    // The confirm dialog should have appeared
    expect(dialogAppeared).toBe(true);
  });

  test('load profile replaces config entirely', async ({ page, request }) => {
    await page.goto('/');
    await sendMessage(page, 'Create test slides');
    const sessionId = await getSessionIdFromUrl(page);

    // First load profile A (has tool A + style)
    await expandConfigBar(page);
    await page.getByTestId('load-profile-button').click();
    await page.getByText(profileA.name).click();
    await page.waitForTimeout(1000);

    let config = await getSessionConfig(request, sessionId);
    expect(config.tools[0].space_id).toBe(mockToolsPayload[0].space_id);

    // Now load profile B (has tool B + prompt) — should replace, not merge
    await page.getByTestId('load-profile-button').click();
    await page.getByText(profileB.name).click();
    await page.waitForTimeout(1000);

    config = await getSessionConfig(request, sessionId);
    expect(config.tools).toHaveLength(1);
    expect(config.tools[0].space_id).toBe(mockToolsPayload[1].space_id);
    expect(config.deck_prompt_id).toBe(testPrompt.id);
    // Profile A's style should be gone — replaced by profile B's config
    expect(config.slide_style_id).toBeNull();
  });
});
```

Note: Also add `createTestProfile` and `cleanupProfile` to the imports at the top of the file:

```typescript
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  createTestProfile,
  getSessionConfig,
  cleanupSession,
  cleanupProfile,
  API_BASE,
} from '../helpers/integration-helpers';
```

- [ ] **Step 2: Run load-profile tests**

Run: `cd frontend && npx playwright test tests/e2e/agent-config-integration.spec.ts --grep "Load profile" --project=chromium --workers=1`

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/agent-config-integration.spec.ts
git commit -m "test: add load-profile-into-session tests (including TDD confirmation dialog)"
```

---

### Task 6: Create `profiles-integration.spec.ts`

**Files:**
- Create: `frontend/tests/e2e/profiles-integration.spec.ts`

- [ ] **Step 1: Write the full profiles integration test file**

```typescript
import { test, expect } from '@playwright/test';
import { mockAvailableTools as mockToolsPayload } from '../fixtures/mocks';
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  createTestProfile,
  createTestSession,
  putSessionConfig,
  getSessionConfig,
  cleanupSession,
  cleanupProfile,
  listProfiles,
  API_BASE,
} from '../helpers/integration-helpers';

/**
 * Profiles Integration Tests
 *
 * Tests the /profiles page (Saved Configurations) against a real backend + Postgres.
 * Covers: listing, expanded config display, empty state, delete, rename, save-from-session.
 *
 * Prerequisites:
 * - Backend running at http://127.0.0.1:8000
 * - Database accessible and seeded
 *
 * Run: cd frontend && npx playwright test tests/e2e/profiles-integration.spec.ts
 */

// ── Shared reference data ────────────────────────────────────────────
// Read-only library data created once. See agent-config-integration.spec.ts
// for rationale on using beforeAll vs beforeEach.

let testStyle: { id: number; name: string };
let testPrompt: { id: number; name: string };

test.beforeAll(async ({ request }) => {
  testStyle = await createTestStyle(request, `E2E ProfStyle ${Date.now()}`);
  testPrompt = await createTestDeckPrompt(request, `E2E ProfPrompt ${Date.now()}`);
});

test.afterAll(async ({ request }) => {
  await request.delete(`${API_BASE}/settings/slide-styles/${testStyle?.id}`).catch(() => {});
  await request.delete(`${API_BASE}/settings/deck-prompts/${testPrompt?.id}`).catch(() => {});
});

// ── Per-test setup ───────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await setupIntegrationMocks(page);
});

// ── Helpers ──────────────────────────────────────────────────────────

async function goToProfiles(page: import('@playwright/test').Page) {
  await page.goto('/profiles');
  await expect(page.getByRole('heading', { name: /Agent Profiles/i })).toBeVisible({ timeout: 15000 });
}

// ── Profile list and display ─────────────────────────────────────────

test.describe('Profile list and display', () => {
  let createdProfiles: Array<{ id: number; name: string }> = [];

  test.beforeEach(async ({ request }) => {
    createdProfiles = [];
  });

  test.afterEach(async ({ request }) => {
    for (const p of createdProfiles) {
      await cleanupProfile(request, p.id);
    }
  });

  test('list profiles from database', async ({ page, request }) => {
    // Create 3 profiles with unique configs
    const p1 = await createTestProfile(request, {
      name: `E2E List 1 ${Date.now()}`,
      styleId: testStyle.id,
    });
    const p2 = await createTestProfile(request, {
      name: `E2E List 2 ${Date.now()}`,
      promptId: testPrompt.id,
    });
    const p3 = await createTestProfile(request, {
      name: `E2E List 3 ${Date.now()}`,
      tools: [{ type: 'genie', space_id: mockToolsPayload[0].space_id, space_name: mockToolsPayload[0].space_name }],
    });
    createdProfiles.push(p1, p2, p3);

    await goToProfiles(page);

    await expect(page.getByText(p1.name)).toBeVisible();
    await expect(page.getByText(p2.name)).toBeVisible();
    await expect(page.getByText(p3.name)).toBeVisible();
  });

  test('expanded profile shows agent config details', async ({ page, request }) => {
    const profile = await createTestProfile(request, {
      name: `E2E Expanded ${Date.now()}`,
      tools: [{ type: 'genie', space_id: mockToolsPayload[0].space_id, space_name: 'Sales Data Space' }],
      styleId: testStyle.id,
      promptId: testPrompt.id,
    });
    createdProfiles.push(profile);

    await goToProfiles(page);

    // Expand the profile card
    const card = page.getByTestId('profile-card').filter({ hasText: profile.name }).first();
    await card.getByRole('button', { name: 'Expand' }).click();

    // Verify config details are shown (whatever the current UI renders)
    await expect(card.getByText('Sales Data Space')).toBeVisible();
    await expect(card.getByText(testStyle.name)).toBeVisible();
    await expect(card.getByText(testPrompt.name)).toBeVisible();
  });

  test('empty state when no profiles exist', async ({ page, request }) => {
    // Delete all existing profiles for this test
    const existing = await listProfiles(request);
    for (const p of existing) {
      await cleanupProfile(request, p.id);
    }

    await goToProfiles(page);

    await expect(page.getByText(/No saved configurations found/i)).toBeVisible();
  });
});

// ── Profile operations ───────────────────────────────────────────────

test.describe('Profile operations', () => {
  let createdProfiles: Array<{ id: number; name: string }> = [];
  let createdSessions: string[] = [];

  test.beforeEach(async () => {
    createdProfiles = [];
    createdSessions = [];
  });

  test.afterEach(async ({ request }) => {
    for (const p of createdProfiles) {
      await cleanupProfile(request, p.id);
    }
    for (const s of createdSessions) {
      await cleanupSession(request, s);
    }
  });

  test('delete a profile', async ({ page, request }) => {
    // Create two profiles so delete button is visible (hidden when only 1 profile)
    const toKeep = await createTestProfile(request, {
      name: `E2E Keep ${Date.now()}`,
      styleId: testStyle.id,
    });
    const toDelete = await createTestProfile(request, {
      name: `E2E Delete ${Date.now()}`,
      promptId: testPrompt.id,
    });
    createdProfiles.push(toKeep, toDelete);

    await goToProfiles(page);

    // Click delete on the target profile
    const card = page.getByTestId('profile-card').filter({ hasText: toDelete.name }).first();
    await card.getByRole('button', { name: 'Delete' }).click();

    // Confirm in the dialog
    await expect(page.getByRole('heading', { name: /Delete Profile/i })).toBeVisible();
    await page.getByRole('button', { name: /Confirm|Delete/i }).click();

    // Profile should disappear from the list
    await expect(page.getByText(toDelete.name)).not.toBeVisible({ timeout: 5000 });

    // Verify via API — should be soft-deleted (404 on direct fetch)
    const resp = await request.get(`${API_BASE}/profiles`);
    const profiles = await resp.json();
    const found = profiles.find((p: { id: number }) => p.id === toDelete.id);
    expect(found).toBeUndefined();
  });

  test('rename a profile', async ({ page, request }) => {
    const profile = await createTestProfile(request, {
      name: `E2E Rename ${Date.now()}`,
      tools: [{ type: 'genie', space_id: mockToolsPayload[0].space_id, space_name: 'Sales Data Space' }],
    });
    createdProfiles.push(profile);
    const newName = `Renamed ${Date.now()}`;

    await goToProfiles(page);

    // Expand the card, then click Rename
    const card = page.getByTestId('profile-card').filter({ hasText: profile.name }).first();
    await card.getByRole('button', { name: 'Expand' }).click();
    await card.getByRole('button', { name: /Rename/i }).click();

    // Fill in the new name and submit
    const input = card.getByRole('textbox');
    await input.clear();
    await input.fill(newName);
    await card.getByRole('button', { name: 'Save' }).click();

    // Verify new name appears in the UI
    await expect(page.getByText(newName)).toBeVisible({ timeout: 5000 });

    // Verify via API
    const resp = await request.get(`${API_BASE}/profiles`);
    const profiles = await resp.json();
    const updated = profiles.find((p: { id: number }) => p.id === profile.id);
    expect(updated?.name).toBe(newName);
  });

  test('save current session as profile', async ({ page, request }) => {
    // Create a session with tools configured
    await page.goto('/');

    // Send a message to create the session
    const input = page.getByRole('textbox');
    await input.fill('Create test slides');
    await page.getByRole('button', { name: 'Send' }).click();
    await page.waitForSelector('.slide-container', { timeout: 15000 });

    await page.waitForURL(/\/sessions\/[^/]+\/edit/, { timeout: 15000 });
    const match = page.url().match(/\/sessions\/([^/]+)\/edit/);
    const sessionId = match![1];
    createdSessions.push(sessionId);

    // Expand config bar and add a tool
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    await page.waitForTimeout(1000);

    // Click Save as Profile
    await page.getByTestId('save-profile-button').click();
    const profileName = `E2E Saved ${Date.now()}`;
    await page.getByPlaceholder('Profile name').fill(profileName);
    await page.getByPlaceholder('Description (optional)').fill('Saved from E2E test');
    await page.getByRole('button', { name: 'Save' }).click();

    // Wait for dialog to close
    await expect(page.getByText('Save as Profile').locator('visible=true')).not.toBeVisible({ timeout: 5000 });

    // Navigate to profiles page and verify
    await goToProfiles(page);
    await expect(page.getByText(profileName)).toBeVisible();

    // Track for cleanup
    const profiles = await listProfiles(request);
    const created = profiles.find((p: { name: string }) => p.name === profileName);
    if (created) createdProfiles.push(created);
  });
});
```

Note: Also add `expandConfigBar` and `addGenieSpace` either as imports from a shared helper or duplicate them here. Since these are private to the test file, the cleanest approach is to extract them into `integration-helpers.ts` as shared UI interaction helpers, or duplicate them in this file. For simplicity, duplicate them:

Add these at the top of the file after imports:

```typescript
/** Expand the AgentConfigBar to access dropdowns and tools. */
async function expandConfigBar(page: import('@playwright/test').Page) {
  const toggle = page.getByTestId('agent-config-toggle');
  await toggle.click();
  await page.getByTestId('add-tool-button').waitFor({ state: 'visible', timeout: 5000 });
}

/** Add a Genie space by name via the ToolPicker UI. */
async function addGenieSpace(page: import('@playwright/test').Page, spaceName: string) {
  await page.getByTestId('add-tool-button').click();
  await page.getByTestId('tool-picker').waitFor({ state: 'visible' });
  await page.getByTestId('tool-picker').getByText(spaceName).click();
  await page.getByTestId('genie-detail-panel').waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'Save & Add' }).click();
  await page.getByTestId('genie-detail-panel').waitFor({ state: 'hidden', timeout: 5000 });
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc -b`

- [ ] **Step 3: Run profiles tests**

Run: `cd frontend && npx playwright test tests/e2e/profiles-integration.spec.ts --project=chromium --workers=1`

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e/profiles-integration.spec.ts
git commit -m "test: add profiles-integration.spec.ts with list, display, delete, rename, save tests"
```

---

### Task 7: Update CI workflow — matrix entries

**Files:**
- Modify: `.github/workflows/test.yml:476-491`

- [ ] **Step 1: Update the matrix**

In `.github/workflows/test.yml`, replace the `profile-integration` entry and add `agent-config-integration`:

Find:
```yaml
          - profile-integration
```

Replace with:
```yaml
          - agent-config-integration
          - profiles-integration
```

The final matrix should look like:
```yaml
        test:
          - chat-ui
          - deck-integrity
          - deck-prompts-integration
          - deck-prompts-ui
          - export-ui
          - help-ui
          - history-integration
          - history-ui
          - agent-config-integration
          - profiles-integration
          - profile-ui
          - slide-operations-ui
          - slide-styles-integration
          - slide-styles-ui
```

- [ ] **Step 2: Verify the YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add agent-config-integration and profiles-integration to E2E matrix, remove broken profile-integration"
```

---

### Task 8: Local smoke test — full suite

**Files:** (none — verification only)

- [ ] **Step 1: Run both integration test files**

Run: `cd frontend && npx playwright test tests/e2e/agent-config-integration.spec.ts tests/e2e/profiles-integration.spec.ts --project=chromium --workers=1`

- [ ] **Step 2: Verify expected results**

Expected:
- 17 tests pass
- 2 tests marked as `test.fail` (default style + confirmation dialog) — these are expected failures and count as "passing" in Playwright's output

If any tests fail unexpectedly, fix them before proceeding.

- [ ] **Step 3: Run the full E2E suite to check for regressions**

Run: `cd frontend && npx playwright test --project=chromium --workers=1`

No existing tests should break.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "test: fix integration test issues found during local smoke test"
```
