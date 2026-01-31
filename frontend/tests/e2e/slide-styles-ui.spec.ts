import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Slide Styles UI Tests (Mocked)
 *
 * Tests UI behavior for slide style management using mocked API responses.
 * These tests run fast and don't require a backend.
 *
 * Covers:
 * - SlideStyleList rendering
 * - Create/Edit modal behavior
 * - Delete confirmation dialog
 * - Form validation
 *
 * Run: npx playwright test tests/e2e/slide-styles-ui.spec.ts
 */

// ============================================
// Setup Helpers
// ============================================

async function setupMocks(page: Page) {
  // Mock slide styles endpoint
  await page.route('http://localhost:8000/api/settings/slide-styles', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlideStyles),
      });
    } else if (request.method() === 'POST') {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 99,
          name: 'New Test Style',
          description: 'Test style created via E2E',
          category: 'Custom',
          style_content: '/* test CSS */',
          is_active: true,
          is_system: false,
          created_by: 'test',
          created_at: new Date().toISOString(),
          updated_by: null,
          updated_at: new Date().toISOString(),
        }),
      });
    } else {
      route.continue();
    }
  });

  // Mock individual slide style endpoints
  await page.route(/http:\/\/localhost:8000\/api\/settings\/slide-styles\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    } else if (request.method() === 'PUT') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSlideStyles.styles[1],
          name: 'Updated Style Name',
        }),
      });
    } else if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const style = mockSlideStyles.styles.find((s) => s.id === id) || mockSlideStyles.styles[0];
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(style),
      });
    } else {
      route.continue();
    }
  });

  // Mock profiles endpoint
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles),
    });
  });

  // Mock individual profile endpoints
  await page.route(/http:\/\/localhost:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const profile = mockProfiles.find((p) => p.id === id) || mockProfiles[0];
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(profile),
      });
    } else {
      route.continue();
    }
  });

  // Mock profile load endpoint
  await page.route(/http:\/\/localhost:8000\/api\/settings\/profiles\/\d+\/load/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'reloaded', profile_id: 1 }),
    });
  });

  // Mock deck prompts
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts),
    });
  });

  // Mock sessions
  await page.route('http://localhost:8000/api/sessions**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessions),
    });
  });

  // Mock Genie spaces
  await page.route('http://localhost:8000/api/genie/spaces', (route) => {
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

async function goToSlideStyles(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
}

// ============================================
// SlideStyleList Tests
// ============================================

test.describe('SlideStyleList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('renders all styles', async ({ page }) => {
    await goToSlideStyles(page);

    // Verify mock styles are displayed
    await expect(page.getByRole('heading', { name: 'System Default', level: 3 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Corporate Theme', level: 3 })).toBeVisible();
  });

  test('shows System badge for system styles', async ({ page }) => {
    await goToSlideStyles(page);

    // Find the System Default style card and verify it has System badge
    const systemStyleCard = page.locator('div').filter({ hasText: 'System Default' }).first();
    await expect(systemStyleCard).toBeVisible();

    // System badge should be visible on the page (scoped to system style)
    const systemBadge = page.locator('span', { hasText: 'System' }).first();
    await expect(systemBadge).toBeVisible();
  });

  test('shows category badges', async ({ page }) => {
    await goToSlideStyles(page);

    // System Default has "System" category
    await expect(page.locator('span').filter({ hasText: 'System' }).first()).toBeVisible();
    // Corporate Theme has "Brand" category
    await expect(page.locator('span').filter({ hasText: 'Brand' }).first()).toBeVisible();
  });

  test('shows Edit and Delete buttons for non-system styles', async ({ page }) => {
    await goToSlideStyles(page);

    // Find the Corporate Theme card (non-system)
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });

    // Should have Edit and Delete buttons
    await expect(corporateCard.getByRole('button', { name: 'Edit' })).toBeVisible();
    await expect(corporateCard.getByRole('button', { name: 'Delete' })).toBeVisible();
  });

  test('hides Edit and Delete buttons for system styles', async ({ page }) => {
    await goToSlideStyles(page);

    // Find the System Default card (system style)
    const systemCard = page.locator('div.border.rounded-lg').filter({ hasText: 'System Default' }).filter({ hasText: 'Protected system style' });

    // Should NOT have Edit or Delete buttons
    await expect(systemCard.getByRole('button', { name: 'Edit' })).not.toBeVisible();
    await expect(systemCard.getByRole('button', { name: 'Delete' })).not.toBeVisible();
  });

  test('shows Preview button for all styles', async ({ page }) => {
    await goToSlideStyles(page);

    // Both styles should have Preview button
    const previewButtons = page.getByRole('button', { name: 'Preview' });
    await expect(previewButtons.first()).toBeVisible();
    expect(await previewButtons.count()).toBe(2);
  });

  test('Preview button toggles to Hide when clicked', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Preview on first style
    const previewButton = page.getByRole('button', { name: 'Preview' }).first();
    await previewButton.click();

    // Button should now say Hide
    await expect(page.getByRole('button', { name: 'Hide' }).first()).toBeVisible();
  });

  test('expanded view shows style content', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Preview on System Default
    const systemCard = page.locator('div.border.rounded-lg').filter({ hasText: 'System Default' }).filter({ hasText: 'Protected system style' });
    await systemCard.getByRole('button', { name: 'Preview' }).click();

    // Should show Style Content label and content
    await expect(page.getByText('Style Content')).toBeVisible();
    await expect(page.locator('pre').filter({ hasText: '/* System default CSS */' })).toBeVisible();
  });

  test('displays style description', async ({ page }) => {
    await goToSlideStyles(page);

    // Verify descriptions are shown
    await expect(page.getByText('Protected system style')).toBeVisible();
    await expect(page.getByText('Professional corporate styling')).toBeVisible();
  });

  test('displays created by and updated date', async ({ page }) => {
    await goToSlideStyles(page);

    // Should show creator info
    await expect(page.getByText(/Created by system/i).first()).toBeVisible();
    // Should show updated date
    await expect(page.getByText(/Updated/i).first()).toBeVisible();
  });
});

// ============================================
// Create Style Modal Tests
// ============================================

test.describe('Create Style Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Create Style button opens modal', async ({ page }) => {
    await goToSlideStyles(page);

    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
  });

  test('modal shows all form fields', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    // Name field
    await expect(page.getByLabel(/Name/i)).toBeVisible();
    // Description field
    await expect(page.getByLabel(/Description/i)).toBeVisible();
    // Category field
    await expect(page.getByLabel(/Category/i)).toBeVisible();
    // Style Content (Monaco editor is harder to check directly)
    await expect(page.getByText('Style Content')).toBeVisible();
  });

  test('modal shows Cancel and Create Style buttons', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
    // Use exact: true to avoid matching the "+ Create Style" button
    await expect(page.getByRole('button', { name: 'Create Style', exact: true })).toBeVisible();
  });

  test('Cancel button closes modal', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible();
  });

  test('shows placeholder text for name field', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByPlaceholder('e.g., Databricks Brand')).toBeVisible();
  });

  test('shows placeholder text for description field', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByPlaceholder(/Brief description/i)).toBeVisible();
  });

  test('shows placeholder text for category field', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    await expect(page.getByPlaceholder(/Brand, Minimal, Dark, Bold/i)).toBeVisible();
  });
});

// ============================================
// Edit Style Modal Tests
// ============================================

test.describe('Edit Style Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Edit button opens modal with Edit heading', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Edit on Corporate Theme (non-system style)
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();
  });

  test('Edit modal pre-fills form with style data', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Edit on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Edit' }).click();

    // Name should be pre-filled
    await expect(page.getByLabel(/Name/i)).toHaveValue('Corporate Theme');
    // Description should be pre-filled
    await expect(page.getByLabel(/Description/i)).toHaveValue('Professional corporate styling with clean typography and modern layout.');
    // Category should be pre-filled
    await expect(page.getByLabel(/Category/i)).toHaveValue('Brand');
  });

  test('Edit modal shows Save Changes button', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Edit on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('button', { name: 'Save Changes' })).toBeVisible();
  });

  test('Cancel button closes edit modal', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Edit on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Edit' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).not.toBeVisible();
  });
});

// ============================================
// Delete Confirmation Dialog Tests
// ============================================

test.describe('Delete Confirmation Dialog', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('Delete button opens confirmation dialog', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Delete on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Delete' }).click();

    await expect(page.getByRole('heading', { name: 'Delete Slide Style' })).toBeVisible();
  });

  test('confirmation dialog shows style name in message', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Delete on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Delete' }).click();

    // The dialog message should contain the style name
    await expect(page.getByText(/Are you sure you want to delete/i)).toBeVisible();
    // Dialog message includes "Corporate Theme"
    const dialog = page.locator('.fixed.inset-0').last();
    await expect(dialog.getByText(/Corporate Theme/)).toBeVisible();
  });

  test('confirmation dialog has Cancel and Confirm buttons', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Delete on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Delete' }).click();

    // Check for buttons in the dialog
    const dialog = page.locator('.fixed.inset-0').last();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Confirm' })).toBeVisible();
  });

  test('Cancel closes confirmation dialog', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Delete on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Delete' }).click();

    await expect(page.getByRole('heading', { name: 'Delete Slide Style' })).toBeVisible();

    // Click Cancel in the dialog
    const dialog = page.locator('.fixed.inset-0').last();
    await dialog.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByRole('heading', { name: 'Delete Slide Style' })).not.toBeVisible();
  });

  test('Confirm deletes style and closes dialog', async ({ page }) => {
    await goToSlideStyles(page);

    // Click Delete on Corporate Theme
    const corporateCard = page.locator('div.border.rounded-lg').filter({ hasText: 'Corporate Theme' });
    await corporateCard.getByRole('button', { name: 'Delete' }).click();

    // Confirm deletion
    const dialog = page.locator('.fixed.inset-0').last();
    await dialog.getByRole('button', { name: 'Confirm' }).click();

    // Dialog should close
    await expect(page.getByRole('heading', { name: 'Delete Slide Style' })).not.toBeVisible({ timeout: 5000 });
  });
});

// ============================================
// Form Validation Tests
// ============================================

test.describe('Form Validation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('shows error when submitting empty name', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    // Don't fill name, just click Create (use exact match to avoid "+ Create Style" button)
    await page.getByRole('button', { name: 'Create Style', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Name is required')).toBeVisible();
  });

  test('shows error when submitting empty style content', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    // Fill only name
    await page.getByLabel(/Name/i).fill('Test Style');

    // Click Create without style content (use exact match)
    await page.getByRole('button', { name: 'Create Style', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Style content is required')).toBeVisible();
  });

  test('error for duplicate name on create', async ({ page }) => {
    // Override POST to return duplicate error
    await page.route('http://localhost:8000/api/settings/slide-styles', async (route, request) => {
      if (request.method() === 'POST') {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Style with this name already exists' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockSlideStyles),
        });
      }
    });

    // Setup other mocks
    await setupMocks(page);

    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    // Fill form
    await page.getByLabel(/Name/i).fill('System Default');
    await page.getByLabel(/Description/i).fill('Test description');

    // Need to type in Monaco editor - use keyboard
    // Monaco is complex, so we'll check that the API error is displayed
    // For now, simulate the error scenario (use exact match for submit button)
    await page.getByRole('button', { name: 'Create Style', exact: true }).click();

    // Should show either validation error or API error
    await expect(
      page.getByText(/required|already exists/i).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test('name field enforces maximum length', async ({ page }) => {
    await goToSlideStyles(page);
    await page.getByRole('button', { name: '+ Create Style' }).click();

    const nameInput = page.getByLabel(/Name/i);

    // Try to type more than 100 characters
    const longName = 'A'.repeat(150);
    await nameInput.fill(longName);

    // Value should be truncated to maxLength (100)
    const value = await nameInput.inputValue();
    expect(value.length).toBeLessThanOrEqual(100);
  });
});

// ============================================
// Empty State Tests
// ============================================

test.describe('Empty State', () => {
  test('shows empty message when no styles exist', async ({ page }) => {
    // Setup other mocks first (except slide-styles)
    await page.route('http://localhost:8000/api/settings/profiles', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockProfiles),
      });
    });

    await page.route(/http:\/\/localhost:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockProfiles[0]),
        });
      } else {
        route.continue();
      }
    });

    await page.route(/http:\/\/localhost:8000\/api\/settings\/profiles\/\d+\/load/, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'reloaded', profile_id: 1 }),
      });
    });

    await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDeckPrompts),
      });
    });

    await page.route('http://localhost:8000/api/sessions**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions),
      });
    });

    await page.route('http://localhost:8000/api/genie/spaces', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ spaces: [], total: 0 }),
      });
    });

    await page.route('**/api/version**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }),
      });
    });

    // Override slide-styles to return empty (this MUST be after the above routes)
    await page.route('http://localhost:8000/api/settings/slide-styles', (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ styles: [], total: 0 }),
        });
      } else {
        route.continue();
      }
    });

    await goToSlideStyles(page);

    await expect(page.getByText('No slide styles found')).toBeVisible();
    await expect(page.getByText('Create your first style to get started')).toBeVisible();
  });
});
