import { test, expect, Page, APIRequestContext } from '@playwright/test';

/**
 * Slide Styles Integration Tests
 *
 * Tests real backend persistence for slide style operations.
 * Each test creates its own test data and cleans up after itself.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Run with: npx playwright test tests/e2e/slide-styles-integration.spec.ts
 */

const API_BASE = 'http://127.0.0.1:8000/api/settings';

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
// Type Definitions
// ============================================

interface SlideStyle {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  style_content: string;
  is_active: boolean;
  is_system: boolean;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
}

interface SlideStylesResponse {
  styles: SlideStyle[];
  total: number;
}

// ============================================
// Test Data Helpers
// ============================================

/**
 * Generate a unique test style name
 */
function testStyleName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

/**
 * Create a slide style via API for faster test setup
 */
async function createTestStyleViaAPI(
  request: APIRequestContext,
  name: string,
  description?: string
): Promise<SlideStyle> {
  const response = await request.post(`${API_BASE}/slide-styles`, {
    data: {
      name,
      description: description || 'E2E test style',
      category: 'E2E Test',
      style_content: '/* E2E test CSS content */\n.slide { color: #333; }',
    },
  });

  if (!response.ok()) {
    const error = await response.text();
    throw new Error(`Failed to create style: ${error}`);
  }

  return response.json();
}

/**
 * Delete a slide style via API for cleanup
 */
async function deleteTestStyleViaAPI(
  request: APIRequestContext,
  styleId: number
): Promise<void> {
  const response = await request.delete(`${API_BASE}/slide-styles/${styleId}`);
  // 204 No Content is success, 404 means already deleted
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete style ${styleId}: ${response.status()}`);
  }
}

/**
 * Get all slide styles via API
 */
async function getStylesViaAPI(request: APIRequestContext): Promise<SlideStyle[]> {
  const response = await request.get(`${API_BASE}/slide-styles`);
  const data: SlideStylesResponse = await response.json();
  return data.styles || [];
}

/**
 * Get a slide style by name via API
 */
async function getStyleByName(
  request: APIRequestContext,
  name: string
): Promise<SlideStyle | null> {
  const styles = await getStylesViaAPI(request);
  return styles.find((s) => s.name === name) || null;
}

/**
 * Get a slide style by ID via API
 */
async function getStyleById(
  request: APIRequestContext,
  id: number
): Promise<SlideStyle | null> {
  const response = await request.get(`${API_BASE}/slide-styles/${id}`);
  if (!response.ok()) {
    return null;
  }
  return response.json();
}

// ============================================
// Monaco Editor Helper
// ============================================

/**
 * Fill content into Monaco editor reliably.
 * Uses JavaScript evaluation to set the value directly, avoiding keyboard timing issues.
 */
async function fillMonacoEditor(page: Page, content: string): Promise<void> {
  // Wait for Monaco to be fully loaded
  await page.waitForSelector('.monaco-editor', { state: 'visible' });
  
  // Click to focus the editor
  await page.locator('.monaco-editor').first().click();
  
  // Use evaluate to set the value directly via Monaco's API
  await page.evaluate((text) => {
    // Monaco editors are stored in a global registry
    const monacoWindow = window as typeof window & { monaco?: { editor: { getEditors: () => Array<{ setValue: (value: string) => void; getValue: () => string }> } } };
    if (monacoWindow.monaco?.editor) {
      const editors = monacoWindow.monaco.editor.getEditors();
      if (editors.length > 0) {
        editors[0].setValue(text);
      }
    }
  }, content);
  
  // Small wait to ensure React state updates
  await page.waitForTimeout(100);
}

// ============================================
// Navigation Helpers
// ============================================

async function goToSlideStyles(page: Page): Promise<void> {
  await page.goto('/slide-styles');
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
}

// ============================================
// Style CRUD Operations
// ============================================

test.describe('Slide Style CRUD Operations', () => {
  test('create style via UI saves to database', async ({ page, request }) => {
    const styleName = testStyleName('Create');
    let createdStyle: SlideStyle | null = null;

    try {
      await goToSlideStyles(page);

      // Open create modal
      await page.getByRole('button', { name: 'New Style' }).click();
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();

      // Fill form
      await page.getByLabel(/Name/i).fill(styleName);
      await page.getByLabel(/Description/i).fill('Created via E2E test');
      await page.getByLabel(/Category/i).fill('E2E Test');

      // Fill Monaco editor using reliable helper
      await fillMonacoEditor(page, '/* E2E Test CSS */\n.slide { background: #fff; }');

      // Submit
      await page.getByRole('button', { name: 'Create Style', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify style appears in list
      await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible();

      // Verify in database
      createdStyle = await getStyleByName(request, styleName);
      expect(createdStyle).not.toBeNull();
      expect(createdStyle?.name).toBe(styleName);
      expect(createdStyle?.description).toBe('Created via E2E test');
      expect(createdStyle?.category).toBe('E2E Test');
      expect(createdStyle?.is_system).toBe(false);
    } finally {
      // Cleanup
      if (createdStyle) {
        await deleteTestStyleViaAPI(request, createdStyle.id);
      } else {
        // Try to find and delete by name if creation partially succeeded
        const style = await getStyleByName(request, styleName);
        if (style) {
          await deleteTestStyleViaAPI(request, style.id);
        }
      }
    }
  });

  test('created style appears in style list', async ({ page, request }) => {
    const styleName = testStyleName('List');

    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible({ timeout: 10000 });
      await expect(page.getByText('E2E test style').first()).toBeVisible();
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('edit style name persists to database', async ({ page, request }) => {
    const styleName = testStyleName('EditName');
    const updatedName = testStyleName('EditedName');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      // Click Edit on the style (use .first() to avoid matching nested divs)
      const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();
      await styleCard.getByRole('button', { name: 'Edit' }).first().click();

      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();

      // Update name
      const nameInput = page.getByLabel(/Name/i);
      await nameInput.clear();
      await nameInput.fill(updatedName);

      // Save
      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in UI
      await expect(page.getByRole('heading', { name: updatedName, level: 3 })).toBeVisible();

      // Verify in database
      const updated = await getStyleById(request, style.id);
      expect(updated).not.toBeNull();
      expect(updated?.name).toBe(updatedName);
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('edit style description persists to database', async ({ page, request }) => {
    const styleName = testStyleName('EditDesc');
    const updatedDescription = 'Updated description via E2E test';

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName, 'Original description');

    try {
      await goToSlideStyles(page);

      // Click Edit on the style (use .first() to avoid matching nested divs)
      const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();
      await styleCard.getByRole('button', { name: 'Edit' }).first().click();

      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();

      // Update description
      const descInput = page.getByLabel(/Description/i);
      await descInput.clear();
      await descInput.fill(updatedDescription);

      // Save
      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      const updated = await getStyleById(request, style.id);
      expect(updated?.description).toBe(updatedDescription);
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('edit style category persists to database', async ({ page, request }) => {
    const styleName = testStyleName('EditCategory');
    const updatedCategory = 'Updated Category';

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      // Click Edit on the style (use .first() to avoid matching nested divs)
      const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();
      await styleCard.getByRole('button', { name: 'Edit' }).first().click();

      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();

      // Update category
      const categoryInput = page.getByLabel(/Category/i);
      await categoryInput.clear();
      await categoryInput.fill(updatedCategory);

      // Save
      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      const updated = await getStyleById(request, style.id);
      expect(updated?.category).toBe(updatedCategory);
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('delete style removes from database', async ({ page, request }) => {
    const styleName = testStyleName('Delete');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    await goToSlideStyles(page);

    // Verify visible
    await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible();

    // Click Delete (use .first() to avoid matching nested divs)
    const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();
    await styleCard.getByRole('button', { name: 'Delete' }).first().click();

    // Confirm deletion
    await expect(page.getByRole('heading', { name: 'Delete Slide Style' })).toBeVisible();
    const dialog = page.locator('.fixed.inset-0').last();
    await dialog.getByRole('button', { name: 'Confirm' }).click();

    // Wait for deletion
    await expect(page.getByRole('heading', { name: styleName, level: 3 })).not.toBeVisible({
      timeout: 5000,
    });

    // Verify removed from database
    const deleted = await getStyleByName(request, styleName);
    expect(deleted).toBeNull();
  });

  test('deleted style no longer appears in list after refresh', async ({ page, request }) => {
    const styleName = testStyleName('DeleteRefresh');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    await goToSlideStyles(page);

    // Verify visible
    await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible();

    // Delete via API
    await deleteTestStyleViaAPI(request, style.id);

    // Reload and navigate back to slide styles to get fresh data
    await page.reload();
    await goToSlideStyles(page);

    // Should no longer be visible
    await expect(page.getByRole('heading', { name: styleName, level: 3 })).not.toBeVisible();
  });
});

// ============================================
// System Style Protection Tests
// ============================================

test.describe('System Style Protection', () => {
  test('cannot delete system style via UI', async ({ page, request }) => {
    await goToSlideStyles(page);

    // Find the System Default style card
    const systemCard = page.locator('div.border.rounded-lg').filter({ hasText: 'System Default' }).filter({ hasText: 'Protected system style' });

    // Verify it exists
    await expect(systemCard).toBeVisible();

    // Verify Delete button is NOT present
    await expect(systemCard.getByRole('button', { name: 'Delete' })).not.toBeVisible();
  });

  test('cannot edit system style via UI', async ({ page, request }) => {
    await goToSlideStyles(page);

    // Find the System Default style card
    const systemCard = page.locator('div.border.rounded-lg').filter({ hasText: 'System Default' }).filter({ hasText: 'Protected system style' });

    // Verify it exists
    await expect(systemCard).toBeVisible();

    // Verify Edit button is NOT present
    await expect(systemCard.getByRole('button', { name: 'Edit' })).not.toBeVisible();
  });

  test('system style has System badge', async ({ page }) => {
    await goToSlideStyles(page);

    const systemCard = page.locator('div.rounded-lg').filter({ hasText: 'System Default' }).first();
    await expect(systemCard.getByText('System').first()).toBeVisible();
  });
});

// ============================================
// Validation Tests
// ============================================

test.describe('Slide Style Validation', () => {
  test('cannot create style with duplicate name', async ({ page, request }) => {
    const styleName = testStyleName('DupName');

    // Create style via API first
    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      // Try to create another with same name
      await page.getByRole('button', { name: 'New Style' }).click();

      // Fill form with duplicate name
      await page.getByLabel(/Name/i).fill(styleName);
      await page.getByLabel(/Description/i).fill('Duplicate test');

      // Fill Monaco editor using reliable helper
      await fillMonacoEditor(page, '/* duplicate test */');

      // Submit
      await page.getByRole('button', { name: 'Create Style', exact: true }).click();

      // Should show error (API returns 409 for duplicate)
      await expect(page.getByText(/already exists|duplicate|failed/i).first()).toBeVisible({
        timeout: 5000,
      });
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('cannot rename style to existing name', async ({ page, request }) => {
    const styleName1 = testStyleName('Rename1');
    const styleName2 = testStyleName('Rename2');

    // Create two styles
    const style1 = await createTestStyleViaAPI(request, styleName1);
    const style2 = await createTestStyleViaAPI(request, styleName2);

    try {
      await goToSlideStyles(page);

      // Try to rename style2 to style1's name
      const style2Card = page.locator('div.border.rounded-lg').filter({ hasText: styleName2 });
      await style2Card.getByRole('button', { name: 'Edit' }).click();

      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).toBeVisible();

      const nameInput = page.getByLabel(/Name/i);
      await nameInput.clear();
      await nameInput.fill(styleName1);

      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Should show error
      await expect(page.getByText(/already exists|duplicate|failed/i).first()).toBeVisible({
        timeout: 5000,
      });
    } finally {
      await deleteTestStyleViaAPI(request, style1.id);
      await deleteTestStyleViaAPI(request, style2.id);
    }
  });

  test('form requires name field', async ({ page }) => {
    await goToSlideStyles(page);

    await page.getByRole('button', { name: 'New Style' }).click();

    // Try to submit without name
    await page.getByRole('button', { name: 'Create Style', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Name is required')).toBeVisible();
  });

  test('form requires style content field', async ({ page }) => {
    await goToSlideStyles(page);

    await page.getByRole('button', { name: 'New Style' }).click();

    // Fill only name
    await page.getByLabel(/Name/i).fill('Test Style');

    // Submit without style content
    await page.getByRole('button', { name: 'Create Style', exact: true }).click();

    // Should show validation error
    await expect(page.getByText('Style content is required')).toBeVisible();
  });
});

// ============================================
// Edge Case Tests
// ============================================

test.describe('Slide Style Edge Cases', () => {
  test('special characters in style name are handled correctly', async ({ page, request }) => {
    const styleName = `E2E Test Special Chars ${Date.now()} <>"'&`;
    let createdStyle: SlideStyle | null = null;

    try {
      await goToSlideStyles(page);

      await page.getByRole('button', { name: 'New Style' }).click();

      // Fill form with special characters
      await page.getByLabel(/Name/i).fill(styleName);
      await page.getByLabel(/Description/i).fill('Test with special chars <>&"\'');

      // Fill Monaco editor using reliable helper
      await fillMonacoEditor(page, '/* special chars test <>&"\' */');

      await page.getByRole('button', { name: 'Create Style', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      createdStyle = await getStyleByName(request, styleName);
      expect(createdStyle).not.toBeNull();
      expect(createdStyle?.name).toBe(styleName);
    } finally {
      if (createdStyle) {
        await deleteTestStyleViaAPI(request, createdStyle.id);
      }
    }
  });

  test('unicode characters in style name are handled correctly', async ({ page, request }) => {
    const styleName = `E2E Test Unicode ${Date.now()} Test`;
    let createdStyle: SlideStyle | null = null;

    try {
      await goToSlideStyles(page);

      await page.getByRole('button', { name: 'New Style' }).click();

      // Fill form with unicode
      await page.getByLabel(/Name/i).fill(styleName);
      await page.getByLabel(/Description/i).fill('Description with unicode test');

      // Fill Monaco editor using reliable helper
      await fillMonacoEditor(page, '/* unicode test */');

      await page.getByRole('button', { name: 'Create Style', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      createdStyle = await getStyleByName(request, styleName);
      expect(createdStyle).not.toBeNull();
      expect(createdStyle?.name).toBe(styleName);
    } finally {
      if (createdStyle) {
        await deleteTestStyleViaAPI(request, createdStyle.id);
      }
    }
  });

  test('long description is handled correctly', async ({ page, request }) => {
    const styleName = testStyleName('LongDesc');
    const longDescription = 'A'.repeat(500);
    let createdStyle: SlideStyle | null = null;

    try {
      await goToSlideStyles(page);

      await page.getByRole('button', { name: 'New Style' }).click();

      await page.getByLabel(/Name/i).fill(styleName);
      await page.getByLabel(/Description/i).fill(longDescription);

      // Fill Monaco editor using reliable helper
      await fillMonacoEditor(page, '/* long description test */');

      await page.getByRole('button', { name: 'Create Style', exact: true }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Verify in database
      createdStyle = await getStyleByName(request, styleName);
      expect(createdStyle).not.toBeNull();
    } finally {
      if (createdStyle) {
        await deleteTestStyleViaAPI(request, createdStyle.id);
      }
    }
  });

  test('Preview toggle works correctly', async ({ page, request }) => {
    const styleName = testStyleName('Preview');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      // Find the style card (use .first() to avoid matching nested divs)
      const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();

      // Click Preview
      await styleCard.getByRole('button', { name: 'Preview' }).first().click();

      // Should show content
      await expect(page.getByText('Style Content').first()).toBeVisible();
      await expect(page.locator('pre').filter({ hasText: 'E2E test CSS' })).toBeVisible();

      // Button should now say Hide
      await expect(styleCard.getByRole('button', { name: 'Hide' }).first()).toBeVisible();

      // Click Hide
      await styleCard.getByRole('button', { name: 'Hide' }).first().click();

      // Content should be hidden, button back to Preview
      await expect(styleCard.getByRole('button', { name: 'Preview' }).first()).toBeVisible();
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });
});

// ============================================
// Data Persistence Tests
// ============================================

test.describe('Slide Style Data Persistence', () => {
  test('style persists after page reload', async ({ page, request }) => {
    const styleName = testStyleName('Persist');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName, 'Persistence test');

    try {
      await goToSlideStyles(page);

      // Verify visible
      await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible();

      // Reload and navigate back to slide styles to verify persistence
      await page.reload();
      await goToSlideStyles(page);

      // Should still be visible
      await expect(page.getByRole('heading', { name: styleName, level: 3 })).toBeVisible();
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });

  test('edited style shows updated values after reload', async ({ page, request }) => {
    const styleName = testStyleName('EditReload');
    const updatedName = testStyleName('EditedReload');

    // Create style via API
    const style = await createTestStyleViaAPI(request, styleName);

    try {
      await goToSlideStyles(page);

      // Edit the style (use .first() to avoid matching nested divs)
      const styleCard = page.locator('div.border.rounded-lg').filter({ hasText: styleName }).first();
      await styleCard.getByRole('button', { name: 'Edit' }).first().click();

      const nameInput = page.getByLabel(/Name/i);
      await nameInput.clear();
      await nameInput.fill(updatedName);

      await page.getByRole('button', { name: 'Save Changes' }).click();

      // Wait for modal to close
      await expect(page.getByRole('heading', { name: 'Edit Slide Style' })).not.toBeVisible({
        timeout: 10000,
      });

      // Reload and navigate back to slide styles to verify persistence
      await page.reload();
      await goToSlideStyles(page);

      // Should show updated name
      await expect(page.getByRole('heading', { name: updatedName, level: 3 })).toBeVisible();
      await expect(page.getByRole('heading', { name: styleName, level: 3 })).not.toBeVisible();
    } finally {
      await deleteTestStyleViaAPI(request, style.id);
    }
  });
});
