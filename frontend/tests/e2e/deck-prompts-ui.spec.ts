import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
} from '../fixtures/mocks';

/**
 * Deck Prompts UI Tests (Mocked)
 *
 * These tests validate UI behavior for deck prompt-related components
 * using mocked API responses. They run fast and don't require a backend.
 *
 * Covers:
 * - DeckPromptList rendering and interactions
 * - DeckPromptForm modal for create/edit
 * - Delete confirmation dialog
 * - Form validation
 */

// ============================================
// Setup Helpers
// ============================================

async function setupMocks(page: Page) {
  // Mock deck prompts endpoint
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDeckPrompts),
      });
    } else if (request.method() === 'POST') {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 99,
          name: 'New Test Prompt',
          description: 'Test description',
          category: 'Test',
          prompt_content: 'Test prompt content',
          is_active: true,
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

  // Mock individual prompt endpoints
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/deck-prompts\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    } else if (request.method() === 'PUT') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDeckPrompts.prompts[0]),
      });
    } else if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDeckPrompts.prompts[0]),
      });
    } else {
      route.continue();
    }
  });

  // Mock profiles
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles),
    });
  });

  // Mock individual profile endpoints
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles[0]),
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
  await page.route('http://127.0.0.1:8000/api/sessions**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessions),
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

async function goToDeckPrompts(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
  await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
}

// ============================================
// DeckPromptList Tests
// ============================================

test.describe('DeckPromptList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('renders all prompts', async ({ page }) => {
    await goToDeckPrompts(page);

    // Verify mock prompts are displayed
    await expect(page.getByRole('heading', { name: 'Monthly Review', level: 3 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Executive Summary', level: 3 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Quarterly Business Review', level: 3 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Use Case Analysis', level: 3 })).toBeVisible();
  });

  test('shows category badges for prompts', async ({ page }) => {
    await goToDeckPrompts(page);

    // Category badges should be visible
    await expect(page.getByText('Review').first()).toBeVisible();
    await expect(page.getByText('Summary').first()).toBeVisible();
    await expect(page.getByText('Report').first()).toBeVisible();
    await expect(page.getByText('Analysis').first()).toBeVisible();
  });

  test('shows action buttons per prompt', async ({ page }) => {
    await goToDeckPrompts(page);

    // Each prompt should have action buttons
    await expect(page.getByRole('button', { name: 'Preview' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete' }).first()).toBeVisible();
  });

  test('Create Prompt button opens modal', async ({ page }) => {
    await goToDeckPrompts(page);

    await page.getByRole('button', { name: '+ Create Prompt' }).click();
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();
  });

  test('modal closes on Cancel', async ({ page }) => {
    await goToDeckPrompts(page);

    await page.getByRole('button', { name: '+ Create Prompt' }).click();
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible();
  });

  test('Preview button toggles prompt content visibility', async ({ page }) => {
    await goToDeckPrompts(page);

    // Initially prompt content should not be visible
    await expect(page.getByText('Prompt Content').first()).not.toBeVisible();

    // Click Preview on first prompt
    await page.getByRole('button', { name: 'Preview' }).first().click();

    // Now should show prompt content section
    await expect(page.getByText('Prompt Content').first()).toBeVisible();

    // Button should now say "Hide"
    await expect(page.getByRole('button', { name: 'Hide' }).first()).toBeVisible();

    // Click Hide to collapse
    await page.getByRole('button', { name: 'Hide' }).first().click();
    await expect(page.getByText('Prompt Content').first()).not.toBeVisible();
  });

  test('Edit button opens modal with prompt data', async ({ page }) => {
    await goToDeckPrompts(page);

    // Click Edit on first prompt (Monthly Review)
    await page.getByRole('button', { name: 'Edit' }).first().click();

    // Modal should open with Edit title
    await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();

    // Name field should be populated
    const nameInput = page.locator('#prompt-name');
    await expect(nameInput).toHaveValue('Monthly Review');
  });

  test('Delete button opens confirm dialog', async ({ page }) => {
    await goToDeckPrompts(page);

    // Click Delete on first prompt
    await page.getByRole('button', { name: 'Delete' }).first().click();

    // Confirm dialog should appear
    await expect(page.getByRole('heading', { name: 'Delete Deck Prompt' })).toBeVisible();
    await expect(page.getByText(/Are you sure you want to delete/)).toBeVisible();
  });

  test('confirm dialog has Cancel and Confirm buttons', async ({ page }) => {
    await goToDeckPrompts(page);

    await page.getByRole('button', { name: 'Delete' }).first().click();

    await expect(page.getByRole('heading', { name: 'Delete Deck Prompt' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirm' })).toBeVisible();
  });

  test('confirm dialog closes on Cancel', async ({ page }) => {
    await goToDeckPrompts(page);

    await page.getByRole('button', { name: 'Delete' }).first().click();
    await expect(page.getByRole('heading', { name: 'Delete Deck Prompt' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: 'Delete Deck Prompt' })).not.toBeVisible();
  });

  test('shows description for prompts', async ({ page }) => {
    await goToDeckPrompts(page);

    // Descriptions should be visible
    await expect(page.getByText(/Template for consumption review meetings/)).toBeVisible();
    await expect(page.getByText(/High-level overview format for executive audiences/)).toBeVisible();
  });

  test('shows created by and updated date', async ({ page }) => {
    await goToDeckPrompts(page);

    // Should show creator and date info
    await expect(page.getByText(/Created by system/).first()).toBeVisible();
  });
});

// ============================================
// DeckPromptForm Tests
// ============================================

test.describe('DeckPromptForm', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('shows required fields with asterisks', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Name and Prompt Content are required
    await expect(page.getByText('Name *')).toBeVisible();
    await expect(page.getByText('Prompt Content *')).toBeVisible();
  });

  test('shows optional fields without asterisks', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Description and Category are optional
    const descLabel = page.locator('label', { hasText: 'Description' });
    await expect(descLabel).toBeVisible();
    await expect(descLabel).not.toContainText('*');

    const catLabel = page.locator('label', { hasText: 'Category' });
    await expect(catLabel).toBeVisible();
    await expect(catLabel).not.toContainText('*');
  });

  test('shows validation error for empty name', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Try to submit without name - use exact match to avoid matching the header button
    await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Name is required')).toBeVisible();
  });

  test('shows validation error for empty prompt content', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Fill name but not prompt content
    await page.locator('#prompt-name').fill('Test Name');
    await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Prompt content is required')).toBeVisible();
  });

  test('form has placeholder text', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Check placeholders
    await expect(page.getByPlaceholder('e.g., Quarterly Business Review')).toBeVisible();
    await expect(page.getByPlaceholder(/Brief description of what this prompt is for/)).toBeVisible();
    await expect(page.getByPlaceholder('e.g., Review, Report, Summary, Analysis')).toBeVisible();
  });

  test('Create Prompt modal shows correct title', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();
    // Use exact match to find the submit button in the modal
    await expect(page.getByRole('button', { name: 'Create Prompt', exact: true })).toBeVisible();
  });

  test('Edit modal shows correct title and button', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: 'Edit' }).first().click();

    await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save Changes' })).toBeVisible();
  });

  test('edit form is pre-populated with prompt data', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: 'Edit' }).first().click();

    // Fields should be pre-populated
    await expect(page.locator('#prompt-name')).toHaveValue('Monthly Review');
    await expect(page.locator('#prompt-description')).toHaveValue(
      'Template for consumption review meetings. Analyzes usage trends, identifies key drivers, and highlights areas for optimization.'
    );
    await expect(page.locator('#prompt-category')).toHaveValue('Review');
  });
});

// ============================================
// Form Submission Tests (Mocked)
// ============================================

test.describe('Form Submission', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('successful create closes modal', async ({ page }) => {
    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Fill required fields
    await page.locator('#prompt-name').fill('New Test Prompt');

    // Fill the Monaco editor - need to interact with the editor container
    const editor = page.locator('.monaco-editor').first();
    await editor.click();
    await page.keyboard.type('Test prompt content for the AI');

    // Submit - use exact match to find the submit button in the modal
    await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

    // Modal should close after successful submission
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible({ timeout: 10000 });
  });

  test('shows error message on API failure', async ({ page }) => {
    // Override the POST mock to return an error
    await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', async (route, request) => {
      if (request.method() === 'POST') {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Prompt with this name already exists' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDeckPrompts),
        });
      }
    });

    // Also set up other mocks
    await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
    });
    await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles[0]) });
    });
    await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
    });
    await page.route('http://127.0.0.1:8000/api/sessions**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
    });
    await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) });
    });
    await page.route('**/api/version**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21' }) });
    });

    await goToDeckPrompts(page);
    await page.getByRole('button', { name: '+ Create Prompt' }).click();

    // Fill form
    await page.locator('#prompt-name').fill('Duplicate Name');
    const editor = page.locator('.monaco-editor').first();
    await editor.click();
    await page.keyboard.type('Test content');

    // Submit - use exact match to find the submit button in the modal
    await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

    // Should show error message
    await expect(page.getByText(/already exists|Failed to save/i)).toBeVisible({ timeout: 10000 });
  });
});

// ============================================
// Empty State Tests
// ============================================

test.describe('Empty State', () => {
  test('shows empty state message when no prompts', async ({ page }) => {
    // Override to return empty prompts
    await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ prompts: [], total: 0 }),
      });
    });

    // Set up other mocks
    await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
    });
    await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles[0]) });
    });
    await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
    });
    await page.route('http://127.0.0.1:8000/api/sessions**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
    });
    await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) });
    });
    await page.route('**/api/version**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21' }) });
    });

    await goToDeckPrompts(page);

    // Should show empty state message
    await expect(page.getByText(/No deck prompts found/)).toBeVisible();
  });
});
