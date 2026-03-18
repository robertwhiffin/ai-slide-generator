import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockProfileSummaries,
  mockDefaultAgentConfig,
  mockAvailableTools,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockProfileLoadResponse,
} from '../fixtures/mocks';

/**
 * Saved Configurations UI Tests (Mocked)
 *
 * These tests validate UI behavior for the Saved Configurations page
 * using mocked API responses. They run fast and don't require a backend.
 *
 * Covers:
 * - ProfileList rendering and interactions (rename, delete, load, set default)
 */

// ============================================
// Setup Helpers
// ============================================

async function setupProfileMocks(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });

  // New profiles API (GET /api/profiles) — used by AgentConfigContext
  await page.route(/\/api\/profiles$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfileSummaries) });
  });

  // Available tools
  await page.route('**/api/tools/available', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAvailableTools) });
  });

  // Legacy profiles endpoint (used by ProfileList on /profiles page)
  await page.route(/\/api\/settings\/profiles$/, (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockProfiles),
      });
    } else {
      route.continue();
    }
  });

  // Mock individual profile endpoints
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const profile = mockProfiles.find((p) => p.id === id) || mockProfiles[0];
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(profile),
      });
    } else if (request.method() === 'PUT') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockProfiles[0], name: 'Updated Profile' }),
      });
    } else if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    } else {
      route.continue();
    }
  });

  // Mock profile load endpoint
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+\/load/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfileLoadResponse),
    });
  });

  // Mock profile set-default endpoint
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+\/set-default/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...mockProfiles[1], is_default: true }),
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

  // Mock sessions
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();

    // Handle session creation/deletion
    if (method === 'POST' || method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }

    // Handle agent-config endpoint
    if (url.includes('/agent-config')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
      return;
    }

    // Handle load-profile endpoint
    if (url.includes('/load-profile/')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'loaded', agent_config: mockDefaultAgentConfig }) });
      return;
    }

    if (url.includes('limit=')) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions),
      });
    } else if (url.includes('/slides')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', slide_deck: null }) });
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', title: null, has_slide_deck: false, messages: [] }) });
    }
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

async function goToProfiles(page: Page) {
  await page.goto('/profiles');
  await expect(page.getByRole('heading', { name: /Saved Configurations/i })).toBeVisible({ timeout: 10000 });
}

// ============================================
// ProfileList Tests
// ============================================

test.describe('ProfileList', () => {
  test.beforeEach(async ({ page }) => {
    await setupProfileMocks(page);
  });

  test('renders all profiles as cards', async ({ page }) => {
    await goToProfiles(page);

    await expect(page.getByRole('heading', { name: 'Sales Analytics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Marketing Reports' })).toBeVisible();
  });

  test('shows correct status badges', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = page.getByTestId('profile-card').filter({ hasText: 'Sales Analytics' }).first();
    await expect(salesCard.getByText('Default')).toBeVisible();
  });

  function profileCard(page: Page, name: string) {
    return page.getByTestId('profile-card').filter({ hasText: name }).first();
  }

  test('shows action buttons per profile', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = profileCard(page, 'Sales Analytics');
    await salesCard.getByRole('button', { name: 'Expand' }).click();
    await expect(salesCard.getByRole('button', { name: /Rename/i })).toBeVisible();
  });

  test('hides "Set Default" for default profile', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = profileCard(page, 'Sales Analytics');
    await salesCard.getByRole('button', { name: 'Expand' }).click();
    await expect(salesCard.getByRole('button', { name: /Set as Default/i })).not.toBeVisible();

    const marketingCard = profileCard(page, 'Marketing Reports');
    await marketingCard.getByRole('button', { name: 'Expand' }).click();
    await expect(marketingCard.getByRole('button', { name: /Set as Default/i })).toBeVisible();
  });

  test('hides "Load" for currently loaded profile', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = profileCard(page, 'Sales Analytics');
    await salesCard.getByRole('button', { name: 'Expand' }).click();
    await expect(salesCard.getByRole('button', { name: 'Load' })).not.toBeVisible();

    const marketingCard = profileCard(page, 'Marketing Reports');
    await marketingCard.getByRole('button', { name: 'Expand' }).click();
    await expect(marketingCard.getByRole('button', { name: 'Load' })).toBeVisible();
  });

  test('opens confirm dialog on Delete click', async ({ page }) => {
    await goToProfiles(page);

    const marketingCard = profileCard(page, 'Marketing Reports');
    await marketingCard.getByRole('button', { name: 'Delete' }).click();

    await expect(page.getByRole('heading', { name: /Delete Profile/i })).toBeVisible();
    const dialog = page.locator('[role="dialog"], .fixed.inset-0').last();
    await expect(dialog.getByRole('button', { name: /Cancel/i })).toBeVisible();
  });

  test('opens confirm dialog on Set Default click', async ({ page }) => {
    await goToProfiles(page);

    const marketingCard = profileCard(page, 'Marketing Reports');
    await marketingCard.getByRole('button', { name: 'Expand' }).click();
    await marketingCard.getByRole('button', { name: /Set as Default/i }).click();

    await expect(page.getByRole('heading', { name: /Set Default Profile/i })).toBeVisible();
  });

  test('shows inline rename form on Rename click', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = profileCard(page, 'Sales Analytics');
    await salesCard.getByRole('button', { name: 'Expand' }).click();
    await salesCard.getByRole('button', { name: /Rename/i }).click();

    await expect(salesCard.getByRole('textbox')).toBeVisible();
  });

  test('does not show create profile button', async ({ page }) => {
    await goToProfiles(page);

    // The simplified page should not have a create/new button
    await expect(page.getByRole('button', { name: /New Agent|Create Profile/i })).not.toBeVisible();
  });
});
