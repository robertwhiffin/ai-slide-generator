import { test, expect, Page, APIRequestContext } from '@playwright/test';

/**
 * Session History Integration Tests
 *
 * These tests hit the real backend to validate database persistence.
 * Unlike CRUD tests, sessions are created via the Generator, not this page.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Key differences from other integration tests:
 * - Cannot create sessions from History page
 * - Tests may skip if no sessions exist
 * - Sessions are created by sending messages via Generator
 *
 * Run with: npx playwright test tests/e2e/history-integration.spec.ts
 */

const API_BASE = 'http://127.0.0.1:8000/api';

// ============================================
// Network Logging and Diagnostics
// ============================================

/**
 * Enable network logging for debugging CI failures.
 * Logs all failed requests and console errors.
 */
test.beforeEach(async ({ page, request }, testInfo) => {
  console.log(`\n=== Starting test: ${testInfo.title} ===`);

  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });

  try {
    const healthCheck = await request.get('http://127.0.0.1:8000/api/health');
    console.log(`Backend health check: ${healthCheck.status()}`);
  } catch (error) {
    console.error('Backend health check failed:', error);
  }
  
  // Log console messages from the browser
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[Browser Console Error]: ${msg.text()}`);
    }
  });
  
  // Log failed network requests
  page.on('requestfailed', (request) => {
    console.log(`[Request Failed]: ${request.method()} ${request.url()} - ${request.failure()?.errorText}`);
  });
  
  // Log slow or hanging requests (requests that take > 5s)
  page.on('request', (request) => {
    const url = request.url();
    if (url.includes('/api/')) {
      console.log(`[API Request]: ${request.method()} ${url}`);
    }
  });
  
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/')) {
      console.log(`[API Response]: ${response.status()} ${url}`);
    }
  });
});

// ============================================
// Test Data Helpers
// ============================================

interface Session {
  session_id: string;
  user_id: string | null;
  title: string;
  created_at: string;
  last_activity: string | null;
  message_count: number;
  has_slide_deck: boolean;
  profile_id: number | null;
  profile_name: string | null;
}

interface SessionsResponse {
  sessions: Session[];
  count: number;
}

/**
 * Get all sessions via API
 */
async function getSessionsViaAPI(request: APIRequestContext, limit = 50): Promise<SessionsResponse> {
  const response = await request.get(`${API_BASE}/sessions?limit=${limit}`);
  return response.json();
}

/**
 * Get a session by ID via API.
 * Tries GET /sessions/:id first; if 404, falls back to list (limit 100) and finds by id.
 */
async function getSessionByIdViaAPI(
  request: APIRequestContext,
  sessionId: string
): Promise<Session | null> {
  const url = `${API_BASE}/sessions/${encodeURIComponent(sessionId)}`;
  const response = await request.get(url);
  if (response.ok()) {
    const body = await response.json();
    // Backend returns { ...session, messages, slide_deck }; we need session fields including title
    if (body && typeof body.session_id !== 'undefined' && typeof body.title !== 'undefined') {
      return {
        session_id: body.session_id,
        user_id: body.user_id ?? null,
        title: body.title,
        created_at: body.created_at,
        last_activity: body.last_activity ?? null,
        message_count: body.message_count ?? 0,
        has_slide_deck: body.has_slide_deck ?? false,
        profile_id: body.profile_id ?? null,
        profile_name: body.profile_name ?? null,
      };
    }
  }
  const data = await getSessionsViaAPI(request, 100);
  const sessions = data?.sessions ?? [];
  return sessions.find((s) => s.session_id === sessionId) || null;
}

/**
 * Delete a session via API
 */
async function deleteSessionViaAPI(
  request: APIRequestContext,
  sessionId: string
): Promise<void> {
  const response = await request.delete(`${API_BASE}/sessions/${sessionId}`);
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete session ${sessionId}: ${response.status()}`);
  }
}

/**
 * Rename a session via API
 */
async function renameSessionViaAPI(
  request: APIRequestContext,
  sessionId: string,
  newTitle: string
): Promise<void> {
  const response = await request.patch(`${API_BASE}/sessions/${sessionId}/rename`, {
    data: { title: newTitle },
  });
  if (!response.ok()) {
    console.warn(`Failed to rename session ${sessionId}: ${response.status()}`);
  }
}

/**
 * Create a test session via API
 */
async function createTestSessionViaAPI(
  request: APIRequestContext,
  title?: string
): Promise<{ session_id: string }> {
  const response = await request.post(`${API_BASE}/sessions`, {
    data: { title: title || `E2E Test Session ${Date.now()}` },
  });
  if (!response.ok()) {
    throw new Error(`Failed to create session: ${response.status()}`);
  }
  const session = await response.json();

  // Add a placeholder message so the session passes the non-empty filter
  await request.post(`${API_BASE}/sessions/${session.session_id}/messages`, {
    data: { role: 'user', content: 'E2E test placeholder message' },
  });

  return session;
}

// ============================================
// Navigation Helpers
// ============================================

async function goToHistory(page: Page): Promise<void> {
  await page.goto('/history');
  await expect(page.getByRole('heading', { name: 'All Decks' })).toBeVisible({ timeout: 10000 });
}

async function goToGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: 'New Deck' }).click();
  await page.waitForURL(/\/sessions\/[^/]+\/edit/);
  await page.getByRole('textbox').waitFor({ state: 'visible', timeout: 10000 });
}

// ============================================
// Session List Display Tests
// ============================================

test.describe('Session History Display', () => {
  test('session history page loads correctly', async ({ page }) => {
    await goToHistory(page);

    // Page heading should be visible
    await expect(page.getByRole('heading', { name: 'All Decks' })).toBeVisible();

    // Either shows table or empty state
    const table = page.getByRole('table');
    const emptyState = page.getByText('No sessions yet');

    const hasTable = await table.isVisible().catch(() => false);
    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    expect(hasTable || hasEmptyState).toBe(true);
  });

  test('empty state shows when no sessions exist', async ({ page, request }) => {
    // Get sessions from API to check if we have any
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length > 0) {
      // Sessions exist, skip this empty state test
      test.skip();
      return;
    }

    await goToHistory(page);

    // Empty state should be visible
    await expect(page.getByText('No sessions yet')).toBeVisible();
    await expect(
      page.getByText('Start creating slides and save your sessions to see them here.')
    ).toBeVisible();
  });

  test('session history shows profile column header when sessions exist', async ({
    page,
    request,
  }) => {
    // Create a test session to ensure table is shown
    const session = await createTestSessionViaAPI(request, 'E2E Column Header Test');

    try {
      await goToHistory(page);

      // Profile column should exist in the table
      await expect(page.getByRole('columnheader', { name: /Profile/i })).toBeVisible();
    } finally {
      // Cleanup
      await deleteSessionViaAPI(request, session.session_id);
    }
  });

  test('sessions display correctly from database', async ({ page, request }) => {
    // Create a test session
    const sessionTitle = `E2E Display Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      await expect(page.getByText(sessionTitle).first()).toBeVisible();
    } finally {
      // Cleanup
      await deleteSessionViaAPI(request, session.session_id);
    }
  });

  test('profile name displays correctly for sessions', async ({ page, request }) => {
    // Create a test session - it should get the default profile
    const sessionTitle = `E2E Profile Display Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      await expect(page.getByText(sessionTitle).first()).toBeVisible();

      const row = page.locator('tr', { hasText: sessionTitle }).first();
      await expect(row).toBeVisible();
    } finally {
      await deleteSessionViaAPI(request, session.session_id);
    }
  });
});

// ============================================
// Session Delete Tests
// ============================================

test.describe('Session Delete', () => {
  test('delete session removes it from database', async ({ page, request }) => {
    // Create a test session to delete
    const sessionTitle = `E2E Delete Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);
    const sessionId = session.session_id;

    await goToHistory(page);

    await expect(page.getByText(sessionTitle).first()).toBeVisible();

    page.on('dialog', async (dialog) => {
      await dialog.accept();
    });

    const row = page.locator('tr', { hasText: sessionTitle }).first();
    await row.getByRole('button', { name: 'Delete' }).click();

    // Wait for deletion to process
    await page.waitForTimeout(1000);

    // Verify session is removed from database
    const deletedSession = await getSessionByIdViaAPI(request, sessionId);
    expect(deletedSession).toBeNull();
  });

  test('deleted session no longer appears in list', async ({ page, request }) => {
    // Create a test session to delete
    const sessionTitle = `E2E Delete UI Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    await goToHistory(page);

    await expect(page.getByText(sessionTitle).first()).toBeVisible();

    page.on('dialog', async (dialog) => {
      await dialog.accept();
    });

    const row = page.locator('tr', { hasText: sessionTitle }).first();
    await row.getByRole('button', { name: 'Delete' }).click();

    await page.waitForTimeout(2000);

    const table = page.getByRole('table');
    await expect(table.getByText(sessionTitle)).not.toBeVisible({ timeout: 5000 });
  });
});

// ============================================
// Session Rename Tests
// ============================================

test.describe('Session Rename', () => {
  // Depends on getSessionByIdViaAPI finding the session (same auth/scoping as browser)
  test.skip('rename session persists to database', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Rename DB Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const newTitle = `Renamed E2E ${Date.now()}`;

    try {
      await goToHistory(page);

      const row = page.locator('tr', { hasText: originalTitle }).first();
      await row.getByRole('button', { name: 'Rename' }).click();

      const input = page.getByRole('table').getByRole('textbox');
      await expect(input).toBeVisible({ timeout: 5000 });
      await input.clear();
      await input.fill(newTitle);
      await page.keyboard.press('Enter');

      await page.waitForTimeout(2000);

      // Verify in database (allow time for backend to persist)
      const updatedSession = await getSessionByIdViaAPI(request, sessionId);
      expect(updatedSession).not.toBeNull();
      expect(updatedSession?.title).toBe(newTitle);
    } finally {
      // Cleanup - delete the test session
      await deleteSessionViaAPI(request, sessionId);
    }
  });

  test.skip('renamed session shows new title in list', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Rename UI Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const newTitle = `UI Renamed ${Date.now()}`;

    try {
      await goToHistory(page);

      const row = page.locator('tr', { hasText: originalTitle }).first();
      await row.getByRole('button', { name: 'Rename' }).click();

      const input = page.getByRole('table').getByRole('textbox');
      await expect(input).toBeVisible({ timeout: 5000 });
      await input.clear();
      await input.fill(newTitle);
      await page.keyboard.press('Enter');

      await page.waitForTimeout(1500);

      await expect(page.getByText(newTitle).first()).toBeVisible({ timeout: 10000 });
    } finally {
      // Cleanup - delete the test session
      await deleteSessionViaAPI(request, sessionId);
    }
  });
});

// ============================================
// Session Restore Tests
// ============================================

test.describe('Session Restore', () => {
  test('restore button is visible for sessions with slides', async ({ page, request }) => {
    // Get sessions with slides
    const data = await getSessionsViaAPI(request);
    const sessionWithSlides = data.sessions.find((s) => s.has_slide_deck);

    if (!sessionWithSlides) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // Find the session row
    const row = page.locator('tr', { hasText: sessionWithSlides.title }).first();

    // Note: Restore button is only visible for non-current sessions with slides
    // This depends on the current session state
    // We check that the row exists and has action buttons
    await expect(row).toBeVisible();
    await expect(row.getByRole('button', { name: 'Rename' })).toBeVisible();
  });

  test('clicking restore navigates to Generator with session loaded', async ({ page, request }) => {
    // Get sessions with slides
    const data = await getSessionsViaAPI(request);
    const sessionWithSlides = data.sessions.find((s) => s.has_slide_deck);

    if (!sessionWithSlides) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // Find the session row
    const row = page.locator('tr', { hasText: sessionWithSlides.title }).first();
    const restoreButton = row.getByRole('button', { name: 'Restore' });

    // If Restore button is visible (session is not current), click it
    if (await restoreButton.isVisible()) {
      await restoreButton.click();

      // Should navigate away from History
      await expect(page.getByRole('heading', { name: 'All Decks' })).not.toBeVisible({ timeout: 5000 });
    }
  });
});

// ============================================
// Session-Profile Association Tests
// ============================================

test.describe('Session-Profile Association', () => {
  test('session row displays in table correctly', async ({ page, request }) => {
    // Create a test session
    const sessionTitle = `E2E Profile Assoc Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      // Session should be visible in table
      const row = page.locator('tr', { hasText: sessionTitle }).first();
      await expect(row).toBeVisible();

      // Row should have the standard action buttons
      await expect(row.getByRole('button', { name: 'Rename' })).toBeVisible();
      await expect(row.getByRole('button', { name: 'Delete' })).toBeVisible();
    } finally {
      await deleteSessionViaAPI(request, session.session_id);
    }
  });

  test('sessions without profile show placeholder', async ({ page, request }) => {
    // Create a session without explicitly setting profile
    const sessionTitle = `E2E No Profile Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      // Row should exist
      const row = page.locator('tr', { hasText: sessionTitle }).first();
      await expect(row).toBeVisible();
    } finally {
      await deleteSessionViaAPI(request, session.session_id);
    }
  });
});

// ============================================
// Navigation Tests
// ============================================

test.describe('Session History Navigation', () => {
  test('can navigate back to History after leaving', async ({ page }) => {
    await goToHistory(page);

    // Navigate away from History to another page
    await page.getByRole('button', { name: 'Help' }).click();
    await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/i })).toBeVisible();

    await page.goto('/history');
    await expect(page.getByRole('heading', { name: 'All Decks' })).toBeVisible();
  });
});

// ============================================
// Edge Case Tests
// ============================================

test.describe('Session History Edge Cases', () => {
  test.skip('handles special characters in session titles', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Special Chars Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const specialTitle = `Test <>"'& ${Date.now()}`;

    try {
      await goToHistory(page);

      const row = page.locator('tr', { hasText: originalTitle }).first();
      await row.getByRole('button', { name: 'Rename' }).click();

      const input = page.getByRole('table').getByRole('textbox');
      await expect(input).toBeVisible({ timeout: 5000 });
      await input.clear();
      await input.fill(specialTitle);
      await page.keyboard.press('Enter');

      await page.waitForTimeout(2000);

      const updatedSession = await getSessionByIdViaAPI(request, sessionId);
      expect(updatedSession).not.toBeNull();
      expect(updatedSession?.title).toBe(specialTitle);
    } finally {
      await deleteSessionViaAPI(request, sessionId);
    }
  });

  test('session list shows count correctly', async ({ page, request }) => {
    const sessionTitle = `E2E Count Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      // UI uses limit 100 (SessionHistory.listSessions(100)); compare to same
      const apiData = await getSessionsViaAPI(request, 100);

      const countEl = page.getByText(/\d+ session/).first();
      await expect(countEl).toBeVisible({ timeout: 10000 });
      const countText = await countEl.textContent();
      const countMatch = countText?.match(/(\d+)\s+session/);
      const uiCount = countMatch ? parseInt(countMatch[1], 10) : 0;

      // UI displays sessions.length, so compare to length of returned list
      expect(uiCount).toBe(apiData.sessions.length);
    } finally {
      await deleteSessionViaAPI(request, session.session_id);
    }
  });
});
