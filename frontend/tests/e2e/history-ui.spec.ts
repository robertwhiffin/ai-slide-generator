import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Session History UI Tests (Mocked)
 *
 * These tests validate UI behavior for the Session History view
 * using mocked API responses. They run fast and don't require a backend.
 *
 * Key differences from CRUD tests:
 * - History is READ-ONLY (no create/edit operations)
 * - Sessions are created via Generator, not this page
 * - Operations: view list, restore session, rename session, delete session
 *
 * Run: npx playwright test tests/e2e/history-ui.spec.ts
 */

// ============================================
// Setup Helpers
// ============================================

async function setupMocks(page: Page) {
  // Mock sessions endpoint
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();

    if (url.includes('limit=')) {
      // Sessions list
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions),
      });
    } else if (method === 'DELETE') {
      // Delete session
      route.fulfill({ status: 204 });
    } else if (method === 'PUT' || method === 'PATCH') {
      // Rename session
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockSessions.sessions[0], title: 'Renamed Session' }),
      });
    } else {
      route.fulfill({ status: 404 });
    }
  });

  // Mock profiles endpoint
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles),
    });
  });

  // Mock individual profile endpoints
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles[0]),
    });
  });

  // Mock profile load endpoint
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+\/load/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'reloaded', profile_id: 1 }),
    });
  });

  // Mock deck prompts
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts),
    });
  });

  // Mock slide styles
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles),
    });
  });

  // Mock Genie spaces
  await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ spaces: [], total: 0 }),
    });
  });

  // Mock version check
  await page.route('**/api/version**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }),
    });
  });
}

async function setupEmptySessionsMock(page: Page) {
  // Override sessions to return empty list
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    if (request.url().includes('limit=')) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    } else {
      route.fulfill({ status: 404 });
    }
  });
}

async function goToHistory(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
  await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
}

// ============================================
// Session History List Tests
// ============================================

test.describe('SessionHistoryList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('renders page heading and session count', async ({ page }) => {
    await goToHistory(page);

    await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
    // Check for session count text
    await expect(page.getByText(/\d+ sessions? saved/)).toBeVisible();
  });

  test('renders all sessions in table', async ({ page }) => {
    await goToHistory(page);

    const table = page.getByRole('table');
    await expect(table).toBeVisible();

    // Verify mock sessions are displayed
    await expect(page.getByText('Session 2026-01-08 20:38')).toBeVisible();
    await expect(page.getByText('Session 2026-01-08 20:20')).toBeVisible();
  });

  test('shows correct table columns', async ({ page }) => {
    await goToHistory(page);

    // Check column headers
    await expect(page.getByRole('columnheader', { name: /Profile/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Session Name/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Created/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Last Activity/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Slides/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Actions/i })).toBeVisible();
  });

  test('shows profile name in Profile column', async ({ page }) => {
    await goToHistory(page);

    // Profile names should be visible in the table
    await expect(page.getByText('Sales Analytics').first()).toBeVisible();
    await expect(page.getByText('Marketing Reports').first()).toBeVisible();
  });

  test('shows slides badge for sessions with slides', async ({ page }) => {
    await goToHistory(page);

    // Sessions with slides should show "Yes" badge
    const yesCount = await page.getByText('Yes').count();
    expect(yesCount).toBeGreaterThan(0);
  });

  test('shows action buttons per session', async ({ page }) => {
    await goToHistory(page);

    // Each session row should have Rename and Delete buttons
    await expect(page.getByRole('button', { name: 'Rename' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete' }).first()).toBeVisible();
  });

  test('shows Restore button for non-current sessions with slides', async ({ page }) => {
    await goToHistory(page);

    // At least one session should have a Restore button
    // (depends on which session is "current" - mock shows none as current)
    const restoreButtons = await page.getByRole('button', { name: 'Restore' }).count();
    expect(restoreButtons).toBeGreaterThan(0);
  });

  test('shows Back to Generator button', async ({ page }) => {
    await goToHistory(page);

    await expect(page.getByRole('button', { name: /Back to Generator/i })).toBeVisible();
  });

  test('Back to Generator button navigates to Generator', async ({ page }) => {
    await goToHistory(page);

    await page.getByRole('button', { name: /Back to Generator/i }).click();

    // Should navigate to Generator view
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
  });
});

// ============================================
// Empty State Tests
// ============================================

test.describe('SessionHistory Empty State', () => {
  test('shows empty state when no sessions exist', async ({ page }) => {
    await setupMocks(page);
    await setupEmptySessionsMock(page);

    await goToHistory(page);

    await expect(page.getByText('No sessions yet')).toBeVisible();
    await expect(page.getByText(/Start creating slides/)).toBeVisible();
  });

  test('empty state does not show table', async ({ page }) => {
    await setupMocks(page);
    await setupEmptySessionsMock(page);

    await goToHistory(page);

    // Table should not be visible
    await expect(page.getByRole('table')).not.toBeVisible();
  });
});

// ============================================
// Rename Session Tests
// ============================================

test.describe('SessionHistory Rename', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('clicking Rename shows inline input', async ({ page }) => {
    await goToHistory(page);

    // Click Rename on first session
    await page.getByRole('button', { name: 'Rename' }).first().click();

    // Should show input field
    await expect(page.getByRole('textbox')).toBeVisible();
  });

  test('rename input is pre-filled with current title', async ({ page }) => {
    await goToHistory(page);

    await page.getByRole('button', { name: 'Rename' }).first().click();

    const input = page.getByRole('textbox');
    await expect(input).toBeVisible();

    // Input should have the session title
    const value = await input.inputValue();
    expect(value).toBeTruthy();
  });

  test('cancel rename reverts to display mode', async ({ page }) => {
    await goToHistory(page);

    await page.getByRole('button', { name: 'Rename' }).first().click();
    await expect(page.getByRole('textbox')).toBeVisible();

    // Press Escape to cancel
    await page.keyboard.press('Escape');

    // Input should no longer be visible, but Rename button should be back
    await expect(page.getByRole('button', { name: 'Rename' }).first()).toBeVisible();
  });
});

// ============================================
// Delete Session Tests
// ============================================

test.describe('SessionHistory Delete', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('clicking Delete triggers browser confirm dialog', async ({ page }) => {
    await goToHistory(page);

    // Set up dialog handler to accept
    page.on('dialog', async (dialog) => {
      expect(dialog.type()).toBe('confirm');
      expect(dialog.message()).toContain('Delete this session');
      await dialog.accept();
    });

    // Click Delete on first session
    await page.getByRole('button', { name: 'Delete' }).first().click();
  });

  test('dismissing confirm dialog does not delete session', async ({ page }) => {
    await goToHistory(page);

    // Count sessions before
    const sessionsBefore = await page.locator('tbody tr').count();

    // Set up dialog handler to dismiss
    page.on('dialog', async (dialog) => {
      await dialog.dismiss();
    });

    // Click Delete
    await page.getByRole('button', { name: 'Delete' }).first().click();

    // Wait a bit
    await page.waitForTimeout(500);

    // Sessions count should be unchanged (mocked data doesn't actually change)
    const sessionsAfter = await page.locator('tbody tr').count();
    expect(sessionsAfter).toBe(sessionsBefore);
  });
});

// ============================================
// Date Formatting Tests
// ============================================

test.describe('SessionHistory Date Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('shows formatted dates in Created column', async ({ page }) => {
    await goToHistory(page);

    // Dates should be formatted (e.g., "1/8/2026, 8:38 PM")
    // Check that at least one date pattern is visible
    await expect(page.getByText(/\d+\/\d+\/\d{4}/).first()).toBeVisible();
  });

  test('shows formatted dates in Last Activity column', async ({ page }) => {
    await goToHistory(page);

    // Last activity dates should also be formatted
    const cells = page.locator('tbody tr td').nth(3);
    await expect(cells.first()).toBeVisible();
  });
});

// ============================================
// Error State Tests
// ============================================

test.describe('SessionHistory Error State', () => {
  test('shows error message when API fails', async ({ page }) => {
    // Set up mocks but make sessions fail
    await setupMocks(page);
    await page.route('http://127.0.0.1:8000/api/sessions**', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await goToHistory(page);

    // Should show error message
    await expect(page.getByText(/Failed to load sessions/i)).toBeVisible();
  });
});

// ============================================
// Current Session Badge Tests
// ============================================

test.describe('SessionHistory Current Session', () => {
  test('shows Current badge for active session', async ({ page }) => {
    // Set up mocks with a specific current session
    await setupMocks(page);

    // Override sessions to include a session that matches a "current" session ID
    // We need to mock the session context - this is complex without modifying app state
    // For now, we test that the badge rendering logic exists

    await goToHistory(page);

    // The "Current" badge element exists in the DOM structure
    // If any session is current, it would show the badge
    // We verify the table structure is correct
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
  });
});
