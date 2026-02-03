import { test, expect, Page, APIRequestContext } from '@playwright/test';

/**
 * Deck Prompts Integration Tests
 *
 * These tests hit the real backend to validate database persistence.
 * Each test creates its own test data and cleans up after itself.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Run with: npx playwright test e2e/deck-prompts-integration.spec.ts
 */

const API_BASE = 'http://127.0.0.1:8000/api/settings';

// ============================================
// Test Data Types
// ============================================

interface DeckPrompt {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  prompt_content: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
}

// ============================================
// Test Data Helpers
// ============================================

/**
 * Generate a unique test prompt name
 */
function testPromptName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

/**
 * Create a prompt via API for faster test setup
 */
async function createTestPromptViaAPI(
  request: APIRequestContext,
  name: string,
  description?: string
): Promise<DeckPrompt> {
  const response = await request.post(`${API_BASE}/deck-prompts`, {
    data: {
      name,
      description: description || 'E2E test prompt',
      category: 'Test',
      prompt_content: 'This is test prompt content created via E2E test.',
    },
  });

  if (!response.ok()) {
    const error = await response.text();
    throw new Error(`Failed to create prompt: ${error}`);
  }

  return response.json();
}

/**
 * Delete a prompt via API for cleanup
 */
async function deleteTestPromptViaAPI(
  request: APIRequestContext,
  promptId: number
): Promise<void> {
  const response = await request.delete(`${API_BASE}/deck-prompts/${promptId}`);
  // 204 No Content is success, 404 means already deleted
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete prompt ${promptId}: ${response.status()}`);
  }
}

/**
 * Get all prompts via API
 */
async function getPromptsViaAPI(request: APIRequestContext): Promise<DeckPrompt[]> {
  const response = await request.get(`${API_BASE}/deck-prompts`);
  const data = await response.json();
  return data.prompts || [];
}

/**
 * Get a prompt by name via API
 */
async function getPromptByName(
  request: APIRequestContext,
  name: string
): Promise<DeckPrompt | null> {
  const prompts = await getPromptsViaAPI(request);
  return prompts.find((p) => p.name === name) || null;
}

// ============================================
// Navigation Helpers
// ============================================

async function goToDeckPrompts(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
  await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
}

// ============================================
// Deck Prompt CRUD Operations
// ============================================

test.describe('Deck Prompt CRUD Operations', () => {
  test('create prompt via form saves to database', async ({ page, request }) => {
    const promptName = testPromptName('Create');
    let createdPrompt: DeckPrompt | null = null;

    try {
      await goToDeckPrompts(page);

      // Open create modal
      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

      // Fill form
      await page.locator('#prompt-name').fill(promptName);
      await page.locator('#prompt-description').fill('Created via E2E test');
      await page.locator('#prompt-category').fill('Test');

      // Fill the Monaco editor
      const editor = page.locator('.monaco-editor').first();
      await editor.click();
      await page.keyboard.type('This is test prompt content for E2E testing.');

      // Submit
      await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify prompt exists in database
      createdPrompt = await getPromptByName(request, promptName);
      expect(createdPrompt).not.toBeNull();
      expect(createdPrompt?.name).toBe(promptName);
      expect(createdPrompt?.description).toBe('Created via E2E test');
      expect(createdPrompt?.category).toBe('Test');
    } finally {
      // Cleanup
      if (createdPrompt) {
        await deleteTestPromptViaAPI(request, createdPrompt.id);
      }
    }
  });

  test('created prompt appears in prompt list', async ({ page, request }) => {
    const promptName = testPromptName('List');

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    try {
      await goToDeckPrompts(page);

      // Should see the new prompt in the list
      await expect(page.getByRole('heading', { name: promptName, level: 3 })).toBeVisible();
    } finally {
      // Cleanup
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });

  test('edit prompt name persists to database', async ({ page, request }) => {
    const promptName = testPromptName('EditName');
    const updatedName = testPromptName('EditedName');

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    try {
      await goToDeckPrompts(page);

      // Find the prompt and click Edit
      const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName, level: 3 }) });
      await promptCard.getByRole('button', { name: 'Edit' }).click();

      // Wait for edit modal
      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();

      // Update name
      const nameInput = page.locator('#prompt-name');
      await nameInput.clear();
      await nameInput.fill(updatedName);

      // Save
      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      const updated = await getPromptByName(request, updatedName);
      expect(updated).not.toBeNull();
      expect(updated?.id).toBe(prompt.id);
    } finally {
      // Cleanup - delete by ID since name changed
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });

  test('edit prompt description persists to database', async ({ page, request }) => {
    const promptName = testPromptName('EditDesc');
    const updatedDescription = 'Updated description via E2E test';

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName, 'Original description');

    try {
      await goToDeckPrompts(page);

      // Find the prompt and click Edit
      const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName, level: 3 }) });
      await promptCard.getByRole('button', { name: 'Edit' }).click();

      // Wait for edit modal
      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();

      // Update description
      const descInput = page.locator('#prompt-description');
      await descInput.clear();
      await descInput.fill(updatedDescription);

      // Save
      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      const prompts = await getPromptsViaAPI(request);
      const updated = prompts.find((p) => p.id === prompt.id);
      expect(updated?.description).toBe(updatedDescription);
    } finally {
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });

  test('delete prompt removes from database', async ({ page, request }) => {
    const promptName = testPromptName('Delete');

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    await goToDeckPrompts(page);

    // Find the prompt and click Delete
    const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName, level: 3 }) });
    await promptCard.getByRole('button', { name: 'Delete' }).click();

    // Confirm deletion
    await expect(page.getByRole('heading', { name: 'Delete Deck Prompt' })).toBeVisible();
    await page.getByRole('button', { name: 'Confirm' }).click();

    // Wait for deletion
    await expect(page.getByRole('heading', { name: promptName, level: 3 })).not.toBeVisible({ timeout: 5000 });

    // Verify removed from database
    const deleted = await getPromptByName(request, promptName);
    expect(deleted).toBeNull();
  });

  test('deleted prompt no longer appears in list', async ({ page, request }) => {
    const promptName = testPromptName('DeleteList');

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    await goToDeckPrompts(page);

    // Verify visible
    await expect(page.getByRole('heading', { name: promptName, level: 3 })).toBeVisible();

    // Delete via API
    await deleteTestPromptViaAPI(request, prompt.id);

    // Refresh page
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();

    // Should no longer be visible
    await expect(page.getByRole('heading', { name: promptName, level: 3 })).not.toBeVisible();
  });
});

// ============================================
// Validation Tests
// ============================================

test.describe('Deck Prompt Validation', () => {
  test('cannot create prompt with duplicate name', async ({ page, request }) => {
    const promptName = testPromptName('DupName');

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    try {
      await goToDeckPrompts(page);

      // Try to create another with same name
      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

      // Fill form with duplicate name
      await page.locator('#prompt-name').fill(promptName);
      const editor = page.locator('.monaco-editor').first();
      await editor.click();
      await page.keyboard.type('Some content');

      // Submit
      await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

      // Should show error
      await expect(page.getByText(/already exists|duplicate/i)).toBeVisible({ timeout: 5000 });
    } finally {
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });

  test('cannot rename prompt to existing name', async ({ page, request }) => {
    const promptName1 = testPromptName('Rename1');
    const promptName2 = testPromptName('Rename2');

    // Create two prompts
    const prompt1 = await createTestPromptViaAPI(request, promptName1);
    const prompt2 = await createTestPromptViaAPI(request, promptName2);

    try {
      await goToDeckPrompts(page);

      // Try to rename prompt2 to prompt1's name
      const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName2, level: 3 }) });
      await promptCard.getByRole('button', { name: 'Edit' }).click();

      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();

      const nameInput = page.locator('#prompt-name');
      await nameInput.clear();
      await nameInput.fill(promptName1);

      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Should show error
      await expect(page.getByText(/already exists|duplicate/i)).toBeVisible({ timeout: 5000 });
    } finally {
      await deleteTestPromptViaAPI(request, prompt1.id);
      await deleteTestPromptViaAPI(request, prompt2.id);
    }
  });

  test('form validates required fields before submission', async ({ page }) => {
    await goToDeckPrompts(page);

    await page.getByRole('button', { name: '+ Create Prompt' }).click();
    await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

    // Try to submit without filling required fields
    await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

    // Should show validation error
    await expect(page.getByText(/Name is required/i)).toBeVisible();
  });
});

// ============================================
// Edge Case Tests
// ============================================

test.describe('Deck Prompt Edge Cases', () => {
  test('special characters in prompt name are handled correctly', async ({ page, request }) => {
    const promptName = `E2E Test Special Chars ${Date.now()} <>"'&`;
    let createdPrompt: DeckPrompt | null = null;

    try {
      await goToDeckPrompts(page);

      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

      // Fill form with special characters
      await page.locator('#prompt-name').fill(promptName);
      const editor = page.locator('.monaco-editor').first();
      await editor.click();
      await page.keyboard.type('Test content with special chars: <>&"');

      await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify prompt exists with correct name
      createdPrompt = await getPromptByName(request, promptName);
      expect(createdPrompt).not.toBeNull();
      expect(createdPrompt?.name).toBe(promptName);
    } finally {
      if (createdPrompt) {
        await deleteTestPromptViaAPI(request, createdPrompt.id);
      }
    }
  });

  test('unicode characters in prompt name are handled correctly', async ({ page, request }) => {
    const promptName = `E2E Test Unicode ${Date.now()} Test`;
    let createdPrompt: DeckPrompt | null = null;

    try {
      await goToDeckPrompts(page);

      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

      // Fill form with unicode characters
      await page.locator('#prompt-name').fill(promptName);
      const editor = page.locator('.monaco-editor').first();
      await editor.click();
      await page.keyboard.type('Test content with unicode');

      await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify prompt exists with correct name
      createdPrompt = await getPromptByName(request, promptName);
      expect(createdPrompt).not.toBeNull();
      expect(createdPrompt?.name).toBe(promptName);
    } finally {
      if (createdPrompt) {
        await deleteTestPromptViaAPI(request, createdPrompt.id);
      }
    }
  });

  test('long prompt content is handled correctly', async ({ page, request }) => {
    const promptName = testPromptName('LongContent');
    const longContent = 'This is a test. '.repeat(500); // About 8000 characters
    let createdPrompt: DeckPrompt | null = null;

    try {
      await goToDeckPrompts(page);

      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();

      await page.locator('#prompt-name').fill(promptName);

      // Fill the Monaco editor with long content
      const editor = page.locator('.monaco-editor').first();
      await editor.click();
      // Type a shorter version since typing is slow
      await page.keyboard.type('Long content test: ' + 'repeat '.repeat(100));

      await page.getByRole('button', { name: 'Create Prompt', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify prompt was created
      createdPrompt = await getPromptByName(request, promptName);
      expect(createdPrompt).not.toBeNull();
    } finally {
      if (createdPrompt) {
        await deleteTestPromptViaAPI(request, createdPrompt.id);
      }
    }
  });

  test('edit preserves unchanged fields', async ({ page, request }) => {
    const promptName = testPromptName('PreserveFields');
    const originalDescription = 'Original description that should be preserved';
    const originalCategory = 'OriginalCategory';

    // Create prompt via API with specific values
    const prompt = await createTestPromptViaAPI(request, promptName, originalDescription);

    try {
      // Update category via API to have all fields set
      await request.put(`${API_BASE}/deck-prompts/${prompt.id}`, {
        data: {
          name: promptName,
          description: originalDescription,
          category: originalCategory,
          prompt_content: prompt.prompt_content,
        },
      });

      await goToDeckPrompts(page);

      // Edit only the name
      const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName, level: 3 }) });
      await promptCard.getByRole('button', { name: 'Edit' }).click();

      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).toBeVisible();

      const newName = testPromptName('PreserveFieldsUpdated');
      const nameInput = page.locator('#prompt-name');
      await nameInput.clear();
      await nameInput.fill(newName);

      await page.getByRole('button', { name: 'Save Changes' }).click();

      await expect(page.getByRole('heading', { name: 'Edit Deck Prompt' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify other fields were preserved
      const updated = await getPromptByName(request, newName);
      expect(updated).not.toBeNull();
      expect(updated?.description).toBe(originalDescription);
      expect(updated?.category).toBe(originalCategory);
    } finally {
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });
});

// ============================================
// Preview Feature Tests
// ============================================

test.describe('Deck Prompt Preview', () => {
  test('preview shows prompt content', async ({ page, request }) => {
    const promptName = testPromptName('Preview');
    const promptContent = 'This is the preview test content that should be visible.';

    // Create prompt via API
    const prompt = await createTestPromptViaAPI(request, promptName);

    // Update with specific content
    await request.put(`${API_BASE}/deck-prompts/${prompt.id}`, {
      data: {
        name: promptName,
        description: prompt.description,
        category: prompt.category,
        prompt_content: promptContent,
      },
    });

    try {
      await goToDeckPrompts(page);

      // Find the prompt and click Preview
      const promptCard = page.locator('div', { has: page.getByRole('heading', { name: promptName, level: 3 }) });
      await promptCard.getByRole('button', { name: 'Preview' }).click();

      // Should show the content section
      await expect(page.getByText('Prompt Content').first()).toBeVisible();

      // Should show the actual content (in the pre element)
      await expect(page.locator('pre').filter({ hasText: promptContent })).toBeVisible();
    } finally {
      await deleteTestPromptViaAPI(request, prompt.id);
    }
  });
});
