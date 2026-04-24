import { test, expect, Page } from '@playwright/test';
import {
  mockProfileSummaries,
  mockDefaultAgentConfig,
  mockAvailableTools,
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
  // New profiles API (GET /api/profiles)
  await page.route(/\/api\/profiles$/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfileSummaries) });
  });
  // Available tools
  await page.route('**/api/tools/available', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAvailableTools) });
  });
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
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

    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) });
  });
}

async function goToHelp(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Help' }).click();
  await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/ })).toBeVisible();
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

    await page.getByRole('button', { name: 'Help' }).click();

    await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/ })).toBeVisible();
  });

  test('shows Overview tab by default', async ({ page }) => {
    await goToHelp(page);

    await expect(page.getByRole('heading', { name: /What is .*[Tt]ellr\?/ })).toBeVisible();
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
    await expect(getHelpTabButton(page, 'My Sessions')).toBeVisible();
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

    await getHelpTabButton(page, 'My Sessions').click();

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

  test('MCP tab renders in the tab strip', async ({ page }) => {
    await goToHelp(page);
    await expect(getHelpTabButton(page, 'MCP')).toBeVisible();
  });

  test('MCP tab shows What is MCP and Who is this for sections', async ({ page }) => {
    await goToHelp(page);
    await getHelpTabButton(page, 'MCP').click();
    await expect(page.getByRole('heading', { name: 'What is MCP?' })).toBeVisible();
    await expect(page.getByRole('heading', { name: "Who's this for?" })).toBeVisible();
  });

  test('MCP tab shows the live endpoint URL ending in /mcp/', async ({ page }) => {
    await goToHelp(page);
    await getHelpTabButton(page, 'MCP').click();

    const endpointBlock = page.getByTestId('mcp-endpoint-url');
    await expect(endpointBlock).toBeVisible();
    await expect(endpointBlock).toContainText('/mcp/');
  });

  test('MCP tab has a copy endpoint button', async ({ page }) => {
    await goToHelp(page);
    await getHelpTabButton(page, 'MCP').click();
    await expect(
      page.getByRole('button', { name: /copy endpoint/i }),
    ).toBeVisible();
  });

  test('MCP tab shows prerequisites', async ({ page }) => {
    await goToHelp(page);
    await getHelpTabButton(page, 'MCP').click();
    await expect(page.getByRole('heading', { name: 'Prerequisites' })).toBeVisible();
    await expect(page.getByText(/Databricks user token/i)).toBeVisible();
  });

  test('MCP tab links to the integration guide', async ({ page }) => {
    await goToHelp(page);
    await getHelpTabButton(page, 'MCP').click();

    const link = page.getByRole('link', { name: /MCP Integration Guide/i });
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href).toContain('/technical/mcp-integration-guide');
  });

  test('Overview tab shows MCP as a headline capability', async ({ page }) => {
    await goToHelp(page);
    // Default tab is Overview.
    await expect(page.getByText(/Programmatic API via MCP/)).toBeVisible();
  });

  test('Overview Quick Link navigates to the MCP tab', async ({ page }) => {
    await goToHelp(page);
    await page.getByRole('button', { name: /Learn about MCP/ }).click();
    await expect(page.getByRole('heading', { name: 'What is MCP?' })).toBeVisible();
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
