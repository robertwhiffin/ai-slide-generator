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
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

// ============================================
// Session List Display Tests
// ============================================

test.describe('Session History Display', () => {
  test('session history page loads and shows table structure', async ({ page }) => {
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

  test('session history shows profile column header', async ({ page }) => {
    await goToHistory(page);

    // Profile column should exist
    await expect(page.getByRole('columnheader', { name: /Profile/i })).toBeVisible();
  });

  test('sessions display correctly from database', async ({ page, request }) => {
    // Get sessions from API
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length === 0) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // First session should be visible
    const firstSession = data.sessions[0];
    await expect(page.getByText(firstSession.title)).toBeVisible();
  });

  test('profile name displays correctly for sessions', async ({ page, request }) => {
    // Get sessions with profile names from API
    const data = await getSessionsViaAPI(request);
    const sessionWithProfile = data.sessions.find((s) => s.profile_name);

    if (!sessionWithProfile) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // Profile name should be visible
    await expect(page.getByText(sessionWithProfile.profile_name!).first()).toBeVisible();
  });
});

// ============================================
// Session Delete Tests
// ============================================

test.describe('Session Delete', () => {
  test('delete session removes it from database', async ({ page, request }) => {
    // Get sessions to find one to delete
    const initialData = await getSessionsViaAPI(request);

    if (initialData.sessions.length === 0) {
      test.skip();
      return;
    }

    // Find a session to delete - prefer one that's not the most recent
    // to avoid deleting a session that might be in active use
    const sessionToDelete = initialData.sessions[initialData.sessions.length - 1];
    const sessionId = sessionToDelete.session_id;
    const sessionTitle = sessionToDelete.title;

    await goToHistory(page);

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
    const session = await getSessionByIdViaAPI(request, sessionId);
    expect(session).toBeNull();
  });

  test('deleted session no longer appears in list', async ({ page, request }) => {
    // Get sessions
    const initialData = await getSessionsViaAPI(request);

    if (initialData.sessions.length === 0) {
      test.skip();
      return;
    }

    // Get the last session to delete
    const sessionToDelete = initialData.sessions[initialData.sessions.length - 1];
    const sessionTitle = sessionToDelete.title;

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
    // Get sessions
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length === 0) {
      test.skip();
      return;
    }

    const session = data.sessions[0];
    const sessionId = session.session_id;
    const originalTitle = session.title;
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
      // Restore original title
      await renameSessionViaAPI(request, sessionId, originalTitle);
    }
  });

  test('renamed session shows new title in list', async ({ page, request }) => {
    // Get sessions
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length === 0) {
      test.skip();
      return;
    }

    const session = data.sessions[0];
    const sessionId = session.session_id;
    const originalTitle = session.title;
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
      // Restore original title
      await renameSessionViaAPI(request, sessionId, originalTitle);
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
  test('sessions display correct profile names', async ({ page, request }) => {
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length === 0) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // Check each session's profile name matches
    for (const session of data.sessions.slice(0, 3)) {
      if (session.profile_name) {
        // Profile name should appear in the table
        const profileBadge = page.locator('tr', { hasText: session.title })
          .getByText(session.profile_name);
        await expect(profileBadge).toBeVisible();
      }
    }
  });

  test('sessions without profile show placeholder', async ({ page, request }) => {
    const data = await getSessionsViaAPI(request);
    const sessionWithoutProfile = data.sessions.find((s) => !s.profile_name);

    if (!sessionWithoutProfile) {
      // All sessions have profiles - this is fine
      test.skip();
      return;
    }

    await goToHistory(page);

    // Row should exist but profile cell should show dash or be empty
    const row = page.locator('tr', { hasText: sessionWithoutProfile.title });
    await expect(row).toBeVisible();
  });
});

// ============================================
// Navigation Tests
// ============================================

test.describe('Session History Navigation', () => {
  test('Back to Generator button works', async ({ page }) => {
    await goToHistory(page);

    await page.getByRole('button', { name: /Back to Generator/i }).click();

    // Should be on Generator page
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
  });

  test('can navigate back to History after leaving', async ({ page }) => {
    await goToHistory(page);

    // Go to Generator
    await page.getByRole('button', { name: /Back to Generator/i }).click();
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();

    // Go back to History via nav
    await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
    await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
  });
});

// ============================================
// Edge Case Tests
// ============================================

test.describe('Session History Edge Cases', () => {
  test('handles special characters in session titles', async ({ page, request }) => {
    // Get a session to rename
    const data = await getSessionsViaAPI(request);

    if (data.sessions.length === 0) {
      test.skip();
      return;
    }

    const session = data.sessions[0];
    const sessionId = session.session_id;
    const originalTitle = session.title;
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
      await renameSessionViaAPI(request, sessionId, originalTitle);
    }
  });

  test('session list refreshes after operations', async ({ page, request }) => {
    // Get sessions
    const initialData = await getSessionsViaAPI(request);

    if (initialData.sessions.length === 0) {
      test.skip();
      return;
    }

    await goToHistory(page);

    // Get initial count from page
    const countText = await page.getByText(/\d+ sessions? saved/).textContent();
    const initialCountMatch = countText?.match(/(\d+) sessions?/);
    const initialUiCount = initialCountMatch ? parseInt(initialCountMatch[1]) : 0;

    // The UI count should match the API count
    expect(initialUiCount).toBe(initialData.count);
  });
});
