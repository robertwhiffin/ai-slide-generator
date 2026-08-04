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

    // Wait for content to load — SlidePanel was replaced by SlideViewer.
    await expect(page.locator('[data-testid="slide-viewer"]')).toBeVisible();

    // New and Save As buttons should not be visible
    await expect(page.locator('button:text-is("New")')).toBeHidden();
    await expect(page.locator('button:has-text("Save As")')).toBeHidden();
  });

  test('view mode loads slides', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Slides should be visible — the flip-through viewer renders slide-viewer when
    // the deck is loaded.  (The old test checked for "Benefits of Cloud Computing"
    // which only appeared transiently in the header before the session title loaded;
    // use the stable slide-viewer testid instead.)
    await expect(page.locator('[data-testid="slide-viewer"]')).toBeVisible();
  });

  test('view mode shows chat history', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);

    // Chat panel should be visible with history
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  });

  test('view mode keeps the verification badge but hides mutating controls', async ({ page }) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/view`);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();

    // The stage toolbar must render for read-only viewers so verification
    // ratings stay visible on the share-link route. The pre-viewer SlideTile
    // kept its badge outside the readOnly gate; gating the whole toolbar
    // silently removed RAG visibility for anyone on /view.
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();
    await expect(page.getByTestId('stage-verification-badge')).toBeVisible();

    // ...but nothing that mutates the deck may be reachable.
    await expect(page.getByTestId('stage-edit-slide')).toHaveCount(0);
    await expect(page.getByTestId('stage-delete-slide')).toHaveCount(0);
    await expect(page.getByTestId('stage-optimize-layout')).toHaveCount(0);
  });
});
