import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from './helpers/session-helpers';

test.describe('Read-only Viewer', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
  });

  test('view mode disables chat input', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Chat input textarea should be disabled
    await expect(page.locator('[data-testid="chat-input"]')).toBeDisabled();
  });

  test('view mode hides session action buttons', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Wait for content to load
    await expect(page.locator('[data-testid="slide-panel"]')).toBeVisible();

    // New and Save As buttons should not be visible
    await expect(page.locator('button:has-text("New")')).toBeHidden();
    await expect(page.locator('button:has-text("Save As")')).toBeHidden();
  });

  test('view mode loads slides', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Slides should be visible
    await expect(page.locator('text=Benefits of Cloud Computing').first()).toBeVisible();
  });

  test('view mode shows chat history', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Chat panel should be visible with history
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });
});
