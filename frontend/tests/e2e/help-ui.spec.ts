import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Help Page UI Tests
 *
 * Tests help page navigation, tab switching, and content display.
 * Run: cd frontend && npx playwright test tests/e2e/help-ui.spec.ts
 */

// ============================================
// Setup Helpers
// ============================================

async function setupMocks(page: Page) {
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
  });
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://localhost:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
  await page.route('http://localhost:8000/api/sessions**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) });
  });
}

async function goToHelp(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();
  await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
}

// ============================================
// Help Navigation Tests
// ============================================

test.describe('HelpNavigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Help button navigates to help page', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('navigation').getByRole('button', { name: 'Help' }).click();

    await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).toBeVisible();
  });

  test('Back button returns to main view', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: 'Back' }).click();

    // Should return to main view
    await expect(page.getByRole('heading', { name: 'How to Use databricks tellr' })).not.toBeVisible();
  });

  test('shows Overview tab by default', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('heading', { name: 'What is databricks tellr?' })).toBeVisible();
  });
});

// ============================================
// Help Tabs Tests
// ============================================

test.describe('HelpTabs', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Helper to get tab buttons within the help page (not the navigation or quick links)
  // Tab buttons have rounded-full and px-4 py-2 styling, distinct from nav buttons and quick links
  const getHelpTabButton = (page: Page, name: string) => {
    return page.locator('button.rounded-full').filter({ hasText: new RegExp(`^${name}$`) }).first();
  };

  test('all tabs are visible', async ({ page }) => {
    await goToHelp(page);

    await expect(getHelpTabButton(page, 'Overview')).toBeVisible();
    await expect(getHelpTabButton(page, 'Generator')).toBeVisible();
    await expect(getHelpTabButton(page, 'Verification')).toBeVisible();
    await expect(getHelpTabButton(page, 'History')).toBeVisible();
    await expect(getHelpTabButton(page, 'Profiles')).toBeVisible();
    await expect(getHelpTabButton(page, 'Deck Prompts')).toBeVisible();
    await expect(getHelpTabButton(page, 'Slide Styles')).toBeVisible();
  });

  test('clicking Generator tab shows generator content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'Generator').click();

    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });

  test('clicking Verification tab shows verification content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'Verification').click();

    await expect(page.getByRole('heading', { name: 'What is Slide Verification?' })).toBeVisible();
  });

  test('clicking History tab shows history content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'History').click();

    await expect(page.getByRole('heading', { name: 'Session List' })).toBeVisible();
  });

  test('clicking Profiles tab shows profiles content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'Profiles').click();

    await expect(page.getByRole('heading', { name: 'What are Profiles?' })).toBeVisible();
  });

  test('clicking Deck Prompts tab shows deck prompts content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'Deck Prompts').click();

    await expect(page.getByRole('heading', { name: 'What are Deck Prompts?' })).toBeVisible();
  });

  test('clicking Slide Styles tab shows slide styles content', async ({ page }) => {
    await goToHelp(page);

    await getHelpTabButton(page, 'Slide Styles').click();

    await expect(page.getByRole('heading', { name: 'What are Slide Styles?' })).toBeVisible();
  });
});

// ============================================
// Quick Links Tests
// ============================================

test.describe('QuickLinks', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('quick links visible in overview tab', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('button', { name: /Learn about Generator/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Learn about Verification/i })).toBeVisible();
  });

  test('clicking quick link navigates to corresponding tab', async ({ page }) => {
    await goToHelp(page);

    await page.getByRole('button', { name: /Learn about Generator/i }).click();

    await expect(page.getByRole('heading', { name: 'Chat Panel (Left)' })).toBeVisible();
  });
});
