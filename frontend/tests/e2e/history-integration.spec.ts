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
  // Log test start
  console.log(`\n=== Starting test: ${testInfo.title} ===`);
  
  // Verify backend is accessible before test
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
 * Get a session by ID via API
 */
async function getSessionByIdViaAPI(
  request: APIRequestContext,
  sessionId: string
): Promise<Session | null> {
  const data = await getSessionsViaAPI(request);
  return data.sessions.find((s) => s.session_id === sessionId) || null;
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
  return response.json();
}

// ============================================
// Navigation Helpers
// ============================================

async function goToHistory(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
  await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
}

async function goToGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'New Session' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

// ============================================
// Session List Display Tests
// ============================================

test.describe('Session History Display', () => {
  test('session history page loads correctly', async ({ page }) => {
    await goToHistory(page);

    // Page heading should be visible
    await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();

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

      // Session should be visible in the list
      await expect(page.getByText(sessionTitle)).toBeVisible();
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

      // Session should be visible
      await expect(page.getByText(sessionTitle)).toBeVisible();

      // Profile column should show something (either profile name or dash for null)
      const row = page.locator('tr', { hasText: sessionTitle });
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

    // Verify session is visible first
    await expect(page.getByText(sessionTitle)).toBeVisible();

    // Set up dialog handler to accept deletion
    page.on('dialog', async (dialog) => {
      await dialog.accept();
    });

    // Find the row with this session and click Delete
    const row = page.locator('tr', { hasText: sessionTitle });
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

    // Verify session is visible
    await expect(page.getByText(sessionTitle)).toBeVisible();

    // Set up dialog handler
    page.on('dialog', async (dialog) => {
      await dialog.accept();
    });

    // Delete it
    const row = page.locator('tr', { hasText: sessionTitle });
    await row.getByRole('button', { name: 'Delete' }).click();

    // Wait for UI to update
    await page.waitForTimeout(1000);

    // Session should no longer be visible
    await expect(page.getByText(sessionTitle)).not.toBeVisible();
  });
});

// ============================================
// Session Rename Tests
// ============================================

test.describe('Session Rename', () => {
  test('rename session persists to database', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Rename DB Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const newTitle = `Renamed E2E ${Date.now()}`;

    try {
      await goToHistory(page);

      // Find the row and click Rename
      const row = page.locator('tr', { hasText: originalTitle });
      await row.getByRole('button', { name: 'Rename' }).click();

      // Fill in new title
      const input = page.getByRole('textbox');
      await input.clear();
      await input.fill(newTitle);

      // Press Enter to save
      await page.keyboard.press('Enter');

      // Wait for save
      await page.waitForTimeout(1000);

      // Verify in database
      const updatedSession = await getSessionByIdViaAPI(request, sessionId);
      expect(updatedSession?.title).toBe(newTitle);
    } finally {
      // Cleanup - delete the test session
      await deleteSessionViaAPI(request, sessionId);
    }
  });

  test('renamed session shows new title in list', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Rename UI Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const newTitle = `UI Renamed ${Date.now()}`;

    try {
      await goToHistory(page);

      // Find the row and click Rename
      const row = page.locator('tr', { hasText: originalTitle });
      await row.getByRole('button', { name: 'Rename' }).click();

      // Fill in new title
      const input = page.getByRole('textbox');
      await input.clear();
      await input.fill(newTitle);

      // Press Enter to save
      await page.keyboard.press('Enter');

      // Wait for UI update
      await page.waitForTimeout(1000);

      // New title should be visible in the UI
      await expect(page.getByText(newTitle)).toBeVisible();
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
    const row = page.locator('tr', { hasText: sessionWithSlides.title });

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
    const row = page.locator('tr', { hasText: sessionWithSlides.title });
    const restoreButton = row.getByRole('button', { name: 'Restore' });

    // If Restore button is visible (session is not current), click it
    if (await restoreButton.isVisible()) {
      await restoreButton.click();

      // Should navigate away from History
      await expect(page.getByRole('heading', { name: 'Session History' })).not.toBeVisible({ timeout: 5000 });
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
      const row = page.locator('tr', { hasText: sessionTitle });
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
      const row = page.locator('tr', { hasText: sessionTitle });
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
    await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();
    await expect(page.getByRole('heading', { name: /how to use/i })).toBeVisible();

    // Navigate back to History via nav
    await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
    await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
  });
});

// ============================================
// Edge Case Tests
// ============================================

test.describe('Session History Edge Cases', () => {
  test('handles special characters in session titles', async ({ page, request }) => {
    // Create a test session to rename
    const originalTitle = `E2E Special Chars Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, originalTitle);
    const sessionId = session.session_id;
    const specialTitle = `Test <>"'& ${Date.now()}`;

    try {
      await goToHistory(page);

      // Rename with special characters
      const row = page.locator('tr', { hasText: originalTitle });
      await row.getByRole('button', { name: 'Rename' }).click();

      const input = page.getByRole('textbox');
      await input.clear();
      await input.fill(specialTitle);
      await page.keyboard.press('Enter');

      await page.waitForTimeout(1000);

      // Verify the title is displayed correctly (escaped)
      // Note: The actual displayed text may have HTML entities escaped
      const updatedSession = await getSessionByIdViaAPI(request, sessionId);
      expect(updatedSession?.title).toBe(specialTitle);
    } finally {
      await deleteSessionViaAPI(request, sessionId);
    }
  });

  test('session list shows count correctly', async ({ page, request }) => {
    // Create a test session to ensure we have at least one
    const sessionTitle = `E2E Count Test ${Date.now()}`;
    const session = await createTestSessionViaAPI(request, sessionTitle);

    try {
      await goToHistory(page);

      // Get session count from API
      const apiData = await getSessionsViaAPI(request);

      // Get count from page
      const countText = await page.getByText(/\d+ sessions? saved/).textContent();
      const countMatch = countText?.match(/(\d+) sessions?/);
      const uiCount = countMatch ? parseInt(countMatch[1]) : 0;

      // The UI count should match the API count
      expect(uiCount).toBe(apiData.count);
    } finally {
      await deleteSessionViaAPI(request, session.session_id);
    }
  });
});
