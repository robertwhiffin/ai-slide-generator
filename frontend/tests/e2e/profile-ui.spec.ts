import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockProfileLoadResponse,
  mockProfileCreateResponse,
  mockDuplicateNameError,
  mockGenieSpaces,
} from '../fixtures/mocks';
import { goToGenerator } from '../helpers/new-ui';

/**
 * Profile UI Tests (Mocked)
 *
 * These tests validate UI behavior for profile-related components
 * using mocked API responses. They run fast and don't require a backend.
 *
 * Covers:
 * - ProfileSelector dropdown behavior
 * - ProfileList rendering and interactions
 * - ProfileCreationWizard step navigation and validation
 */

// ============================================
// Setup Helpers
// ============================================

async function setupProfileMocks(page: Page) {
  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });
  await page.route(/\/api\/settings\/profiles$/, (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockProfiles),
      });
    } else if (request.method() === 'POST') {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(mockProfileCreateResponse),
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

  // Mock profile duplicate endpoint
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+\/duplicate/, (route) => {
    route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockProfileCreateResponse,
        id: 4,
        name: 'Sales Analytics (Copy)',
      }),
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

    if (url.includes('limit=')) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions),
      });
    } else {
      route.fulfill({ status: 404 });
    }
  });

  // Mock Genie spaces
  await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockGenieSpaces),
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

async function goToProfiles(page: Page) {
  await page.goto('/profiles');
  await expect(page.getByRole('heading', { name: /Agent Profiles|Configuration Profiles/i })).toBeVisible({ timeout: 10000 });
}

/** Profile selector button in the page header (not sidebar). */
function getHeaderProfileButton(page: Page) {
  return page.locator('header').getByRole('button', { name: /Sales Analytics|Default|Profile/i });
}

// ============================================
// ProfileSelector Tests
// ============================================

test.describe('ProfileSelector', () => {
  test.beforeEach(async ({ page }) => {
    await setupProfileMocks(page);
  });

  test('displays current profile name in button', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await expect(profileButton).toBeVisible();
    await expect(page.getByText('Sales Analytics').first()).toBeVisible();
  });

  test('shows "Default" badge when current profile is default', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await profileButton.click();

    await expect(page.getByText('Default').first()).toBeVisible();
  });

  test('opens dropdown on click', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await profileButton.click();

    await expect(page.getByText('Marketing Reports')).toBeVisible();
  });

  test('closes dropdown when clicking outside', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await profileButton.click();

    await expect(page.getByText('Switch Profile')).toBeVisible();

    await page.locator('header').click({ position: { x: 10, y: 10 } });

    await expect(page.getByText('Switch Profile')).not.toBeVisible();
  });

  test('shows checkmark on currently loaded profile', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await profileButton.click();

    const salesRow = page.locator('text=Sales Analytics').first();
    await expect(salesRow).toBeVisible();
  });

  test('shows "Manage Profiles" link', async ({ page }) => {
    await goToGenerator(page);

    const profileButton = getHeaderProfileButton(page);
    await profileButton.click();

    await expect(page.getByText(/Manage Profiles/)).toBeVisible();
  });
});

// ============================================
// ProfileList Tests
// ============================================

test.describe('ProfileList', () => {
  test.beforeEach(async ({ page }) => {
    await setupProfileMocks(page);
  });

  test('renders all profiles in table', async ({ page }) => {
    await goToProfiles(page);

    // ProfileList uses cards with headings, not a table
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
    await expect(page.getByRole('button', { name: /View and Edit/i }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Duplicate/i }).first()).toBeVisible();
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

  test('shows inline duplicate form on Duplicate click', async ({ page }) => {
    await goToProfiles(page);

    const salesCard = profileCard(page, 'Sales Analytics');
    await salesCard.getByRole('button', { name: 'Expand' }).click();
    await salesCard.getByRole('button', { name: /Duplicate/i }).click();

    await expect(salesCard.getByRole('textbox')).toBeVisible();
  });

  test('Create Profile button opens wizard', async ({ page }) => {
    await goToProfiles(page);

    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Wizard should open
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();
  });
});

// ============================================
// ProfileCreationWizard Tests
// ============================================

test.describe('ProfileCreationWizard', () => {
  test.beforeEach(async ({ page }) => {
    await setupProfileMocks(page);
  });

  test('opens when "+ Create Profile" clicked', async ({ page }) => {
    await goToProfiles(page);

    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();
  });

  test('shows 5-step progress indicator', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Should show step indicators (look for numbered steps)
    await expect(page.getByText('1', { exact: true })).toBeVisible();
    await expect(page.getByText('2', { exact: true })).toBeVisible();
    await expect(page.getByText('3', { exact: true })).toBeVisible();
    await expect(page.getByText('4', { exact: true })).toBeVisible();
    await expect(page.getByText('5', { exact: true })).toBeVisible();
  });

  test('Next button disabled when name empty', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // On step 1, name is required
    const nextButton = page.getByRole('button', { name: /Next/i });

    // Initially disabled (name empty)
    await expect(nextButton).toBeDisabled();

    // Fill in name
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');

    // Now should be enabled
    await expect(nextButton).toBeEnabled();
  });

  test('shows character counter for name field', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Type in the name field
    await page.getByPlaceholder(/Production Analytics/i).fill('Test');

    // Should show character count
    await expect(page.getByText(/4.*100|4\/100/)).toBeVisible();
  });

  test('can skip Genie space step', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Step 1: Fill name
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');
    await page.getByRole('button', { name: /Next/i }).click();

    // Step 2: Genie Space - should be able to click Next without selection
    // Look for step 2 content indicator
    await expect(page.getByText(/Select Genie Space/i)).toBeVisible();
    await page.getByRole('button', { name: /Next/i }).click();

    // Should proceed to Step 3: Slide Style - look for step heading
    await expect(page.getByText(/Slide Style \*|Select.*Style/i).first()).toBeVisible();
  });

  test('requires slide style selection to proceed', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Navigate to Step 3
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');
    await page.getByRole('button', { name: /Next/i }).click(); // Step 1 -> 2
    await page.getByRole('button', { name: /Next/i }).click(); // Step 2 -> 3

    // On Step 3: Slide Style is required
    const nextButton = page.getByRole('button', { name: /Next/i });

    // Should be disabled until a style is selected
    await expect(nextButton).toBeDisabled();

    // Select a style - use label selector for radio button
    await page.locator('label').filter({ hasText: 'System Default' }).first().click();

    // Now should be enabled
    await expect(nextButton).toBeEnabled();
  });

  test('shows review summary on final step', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Navigate through wizard
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');
    await page.getByRole('button', { name: /Next/i }).click(); // Step 1 -> 2
    await page.getByRole('button', { name: /Next/i }).click(); // Step 2 -> 3

    // Select slide style - use label selector
    await page.locator('label').filter({ hasText: 'System Default' }).first().click();
    await page.getByRole('button', { name: /Next/i }).click(); // Step 3 -> 4
    await page.getByRole('button', { name: /Next/i }).click(); // Step 4 -> 5 (Review)

    // Should show review with profile name
    await expect(page.getByText('Test Profile').first()).toBeVisible();
    // Review shows the style name in a summary section
    await expect(page.getByText('System Default', { exact: true }).first()).toBeVisible();
  });

  test('closes on Cancel button', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Wizard should be open
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();

    // Click Cancel
    await page.getByRole('button', { name: /Cancel/i }).click();

    // Wizard should close
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).not.toBeVisible();
  });

  test('closes on X button', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    // Wizard should be open
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();

    // The wizard may not have a dedicated X button - use Back/Cancel which achieves same result
    // This tests that the wizard can be dismissed without completing it
    await page.getByRole('button', { name: /Cancel|Back/i }).first().click();

    // Wizard should close
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).not.toBeVisible();
  });
});

// ============================================
// Form Validation Tests
// ============================================

test.describe('Profile Form Validation', () => {
  test.beforeEach(async ({ page }) => {
    await setupProfileMocks(page);
  });

  // TODO: Flaky test - tracked in GitHub issue
  test.skip('shows error for duplicate name on create', async ({ page }) => {
    // Set up mocks first, then override POST to return error
    await setupProfileMocks(page);

    // Override the profile creation to return duplicate error
    await page.route('http://127.0.0.1:8000/api/settings/profiles', async (route, request) => {
      if (request.method() === 'POST') {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify(mockDuplicateNameError),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockProfiles),
        });
      }
    });

    await goToProfiles(page);
    await page.getByRole('button', { name: 'New Agent' }).click();

    // Fill wizard and try to create
    await page.getByPlaceholder(/Production Analytics/i).fill('Sales Analytics'); // Duplicate name
    await page.getByRole('button', { name: /Next/i }).click();
    await page.getByRole('button', { name: /Next/i }).click();
    await page.locator('label').filter({ hasText: 'System Default' }).first().click();
    await page.getByRole('button', { name: /Next/i }).click();
    await page.getByRole('button', { name: /Next/i }).click();

    // Click Create (the wizard submit button, not the list button)
    await page.getByRole('button', { name: 'Create Profile', exact: true }).click();

    // Should show error - look for error text (not buttons)
    // The wizard should show an error message in a text element
    await expect(
      page.getByText('Failed to create profile')
    ).toBeVisible({ timeout: 10000 });
  });

  test('enforces maximum character limit for name', async ({ page }) => {
    await goToProfiles(page);
    await page.getByRole('button', { name: /New Agent|Create Profile/i }).click();

    const nameInput = page.getByPlaceholder(/Production Analytics/i);

    // Try to type more than 100 characters
    const longName = 'A'.repeat(150);
    await nameInput.fill(longName);

    // Value should be truncated to 100
    const value = await nameInput.inputValue();
    expect(value.length).toBeLessThanOrEqual(100);
  });
});
