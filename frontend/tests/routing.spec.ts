import { test, expect } from './fixtures/base-test';
import { setupMocks } from './helpers/setup-mocks';
import { mockSessionWithSlides } from './helpers/session-helpers';

test.describe('URL Routing', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('root path shows help page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/ })).toBeVisible();
  });

  test('/help shows help page', async ({ page }) => {
    await page.goto('/help');
    await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/ })).toBeVisible();
  });

  test('/profiles shows profiles page', async ({ page }) => {
    await page.goto('/profiles');
    await expect(page.getByRole('heading', { name: /Agent Profiles|Configuration Profiles/i })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('heading', { name: 'Sales Analytics' })).toBeVisible();
  });

  test('/deck-prompts shows deck prompts page', async ({ page }) => {
    await page.goto('/deck-prompts');
    await expect(page.locator('text=Monthly Review')).toBeVisible();
  });

  test('/slide-styles shows slide styles page', async ({ page }) => {
    await page.goto('/slide-styles');
    await expect(page.locator('text=System Default')).toBeVisible();
  });

  test('/images shows images page', async ({ page }) => {
    await page.goto('/images');
    await expect(page.locator('[data-testid="image-library"]')).toBeVisible();
  });

  test('/history shows session history page', async ({ page }) => {
    await page.goto('/history');
    await expect(page.getByRole('heading', { name: 'All Decks' })).toBeVisible();
    // Mock sessions list includes "Session 2026-01-08 20:38" when API is mocked
    await expect(page.getByText(/Session|sessions? saved/i).first()).toBeVisible({ timeout: 10000 });
  });

  test('session edit URL loads generator', async ({ page }) => {
    await mockSessionWithSlides(page, 'test-session-id');
    await page.goto('/sessions/test-session-id/edit');
    await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
    await expect(page.locator('[data-testid="slide-panel"]')).toBeVisible();
  });

  test('session view URL loads read-only viewer', async ({ page }) => {
    await mockSessionWithSlides(page, 'test-session-id');
    await page.goto('/sessions/test-session-id/view');
    await expect(page.locator('[data-testid="slide-panel"]')).toBeVisible();
  });

  test('unknown path redirects to help page', async ({ page }) => {
    await page.goto('/this-does-not-exist');
    await expect(page).toHaveURL(/\/help$/);
    await expect(page.getByRole('heading', { name: /How to Use.*[Tt]ellr/ })).toBeVisible();
  });
});
