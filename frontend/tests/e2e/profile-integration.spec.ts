import { test, expect, Page, APIRequestContext } from '@playwright/test';

/**
 * Profile Integration Tests
 *
 * These tests hit the real backend to validate database persistence.
 * Each test creates its own test data and cleans up after itself.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Run with: npx playwright test e2e/profile-integration.spec.ts
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
  console.log(`\n=== Starting test: ${testInfo.title} ===`);

  await page.route('**/api/setup/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) });
  });

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
// Test Data Helpers
// ============================================

interface Profile {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  created_by: string | null;
  updated_at: string;
  updated_by: string | null;
}

interface SlideStyle {
  id: number;
  name: string;
  category: string;
}

/**
 * Generate a unique test profile name
 */
function testProfileName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

/**
 * Create a profile via API for faster test setup.
 * Uses the with-config endpoint so that the profile has full configuration
 * and can be loaded via /load (which triggers reload_agent).
 */
async function createTestProfileViaAPI(
  request: APIRequestContext,
  name: string,
  description?: string
): Promise<Profile> {
  const stylesResponse = await request.get(`${API_BASE}/slide-styles`);
  const styles = await stylesResponse.json();
  const styleId = styles.styles?.[0]?.id || 1;

  const response = await request.post(`${API_BASE}/profiles/with-config`, {
    data: {
      name,
      description: description || 'E2E test profile',
      prompts: {
        selected_slide_style_id: styleId,
      },
    },
  });

  if (!response.ok()) {
    const error = await response.text();
    throw new Error(`Failed to create profile: ${error}`);
  }

  return response.json();
}

/**
 * Delete a profile via API for cleanup
 */
async function deleteTestProfileViaAPI(
  request: APIRequestContext,
  profileId: number
): Promise<void> {
  const response = await request.delete(`${API_BASE}/profiles/${profileId}`);
  // 204 No Content is success, 404 means already deleted
  if (!response.ok() && response.status() !== 404) {
    console.warn(`Failed to delete profile ${profileId}: ${response.status()}`);
  }
}

/**
 * Get all profiles via API
 */
async function getProfilesViaAPI(request: APIRequestContext): Promise<Profile[]> {
  const response = await request.get(`${API_BASE}/profiles`);
  return response.json();
}

/**
 * Get a profile by name via API
 */
async function getProfileByName(
  request: APIRequestContext,
  name: string
): Promise<Profile | null> {
  const profiles = await getProfilesViaAPI(request);
  return profiles.find((p) => p.name === name) || null;
}

/**
 * Get available slide styles
 */
async function getSlideStyles(request: APIRequestContext): Promise<SlideStyle[]> {
  const response = await request.get(`${API_BASE}/slide-styles`);
  const data = await response.json();
  return data.styles || [];
}

// ============================================
// Navigation Helpers
// ============================================

async function goToProfiles(page: Page): Promise<void> {
  await page.goto('/profiles');
  await expect(page.getByRole('heading', { name: /Agent Profiles|Configuration Profiles/i })).toBeVisible();
}

async function goToGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: 'New Deck' }).click();
  await page.waitForURL(/\/sessions\/[^/]+\/edit/);
  await page.getByRole('textbox').waitFor({ state: 'visible', timeout: 10000 });
}

function profileCard(page: Page, name: string) {
  return page.getByTestId('profile-card').filter({ hasText: name }).first();
}

// ============================================
// Wizard Helpers
// ============================================

async function completeWizardStep1(
  page: Page,
  name: string,
  description?: string
): Promise<void> {
  await page.getByPlaceholder(/Production Analytics/i).fill(name);
  if (description) {
    await page.getByPlaceholder(/Optional description/i).fill(description);
  }
  await page.getByRole('button', { name: /Next/i }).click();
}

async function skipWizardStep2(page: Page): Promise<void> {
  // Step 2: Genie Space - skip by clicking Next
  await page.getByRole('button', { name: /Next/i }).click();
}

async function completeWizardStep3(page: Page): Promise<void> {
  // Step 3: Slide Style - select first available
  await page.locator('label').filter({ hasText: /Default|Corporate/i }).first().click();
  await page.getByRole('button', { name: /Next/i }).click();
}

async function skipWizardStep4(page: Page): Promise<void> {
  // Step 4: Deck Prompt - skip by clicking Next
  await page.getByRole('button', { name: /Next/i }).click();
}

async function skipWizardStep5(page: Page): Promise<void> {
  // Step 5: Share (contributors) - skip by clicking Next
  await page.getByRole('button', { name: /Next/i }).click();
}

async function submitWizard(page: Page): Promise<void> {
  // Step 5: Review - click Create Profile (exact match to avoid matching "+ Create Profile" button)
  await page.getByRole('button', { name: 'Create Profile', exact: true }).click();
}

// ============================================
// Profile CRUD Operations
// ============================================

test.describe('Profile CRUD Operations', () => {
  test('create profile via wizard saves to database', async ({ page, request }) => {
    const profileName = testProfileName('Create');

    await goToProfiles(page);

    // Open wizard (use specific button text to avoid matching wizard submit button)
    await page.getByRole('button', { name: 'New Agent' }).click();
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();

    // Complete wizard
    await completeWizardStep1(page, profileName, 'Created via E2E test');
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
    await skipWizardStep5(page);
    await submitWizard(page);

    // Wait for wizard to close
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).not.toBeVisible({
      timeout: 10000,
    });

    // Verify profile exists in database
    const profile = await getProfileByName(request, profileName);
    expect(profile).not.toBeNull();
    expect(profile?.name).toBe(profileName);
    expect(profile?.description).toBe('Created via E2E test');

    // Cleanup
    if (profile) {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('created profile appears in profile list', async ({ page, request }) => {
    const profileName = testProfileName('List');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await goToProfiles(page);

      // Should see the new profile in the list
      await expect(page.getByText(profileName)).toBeVisible();
    } finally {
      // Cleanup
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('edit profile name persists to database', async ({ page, request }) => {
    const profileName = testProfileName('EditName');
    const updatedName = testProfileName('EditedName');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await goToProfiles(page);

      const card = profileCard(page, profileName);
      await card.getByRole('button', { name: 'Expand' }).click();
      await card.getByRole('button', { name: /View and Edit/i }).click();

      // Switch to Edit mode (use exact match to avoid matching "View and Edit" buttons)
      await page.getByRole('button', { name: 'Edit', exact: true }).click();

      // Update name
      const nameInput = page.locator('input').first();
      await nameInput.clear();
      await nameInput.fill(updatedName);

      // Save - use exact text to avoid matching "Save Genie Configuration"
      await page.getByRole('button', { name: 'Save Profile Info' }).click();

      // Wait for save
      await page.waitForTimeout(1000);

      // Verify in database
      const updated = await getProfileByName(request, updatedName);
      expect(updated).not.toBeNull();
      expect(updated?.id).toBe(profile.id);

      // Cleanup with updated profile
      await deleteTestProfileViaAPI(request, profile.id);
    } catch (error) {
      // Cleanup on failure
      await deleteTestProfileViaAPI(request, profile.id);
      throw error;
    }
  });

  test('edit profile description persists to database', async ({ page, request }) => {
    const profileName = testProfileName('EditDesc');
    const updatedDescription = 'Updated description via E2E test';

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName, 'Original description');

    try {
      await goToProfiles(page);

      const card = profileCard(page, profileName);
      await card.getByRole('button', { name: 'Expand' }).click();
      await card.getByRole('button', { name: /View and Edit/i }).click();

      // Switch to Edit mode (use exact match to avoid matching "View and Edit" buttons)
      await page.getByRole('button', { name: 'Edit', exact: true }).click();

      // Update description
      const descInput = page.locator('textarea').first();
      await descInput.clear();
      await descInput.fill(updatedDescription);

      // Save - use exact text to avoid matching "Save Genie Configuration"
      await page.getByRole('button', { name: 'Save Profile Info' }).click();

      // Wait for save
      await page.waitForTimeout(1000);

      // Verify in database
      const profiles = await getProfilesViaAPI(request);
      const updated = profiles.find((p) => p.id === profile.id);
      expect(updated?.description).toBe(updatedDescription);
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('delete profile removes from database', async ({ page, request }) => {
    const profileName = testProfileName('Delete');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    await goToProfiles(page);

    const card = profileCard(page, profileName);
    await card.getByRole('button', { name: 'Delete' }).click();

    // Confirm deletion
    await page.getByRole('button', { name: /Confirm|Delete/i }).last().click();

    await expect(profileCard(page, profileName)).not.toBeVisible({ timeout: 5000 });

    // Verify removed from database
    const deleted = await getProfileByName(request, profileName);
    expect(deleted).toBeNull();
  });

  test('deleted profile no longer appears in list', async ({ page, request }) => {
    const profileName = testProfileName('DeleteList');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    await goToProfiles(page);

    // Verify visible
    await expect(page.getByText(profileName)).toBeVisible();

    // Delete via API
    await deleteTestProfileViaAPI(request, profile.id);

    // Reload and navigate back to profiles to get fresh data
    await page.reload();
    await goToProfiles(page);

    // Should no longer be visible
    await expect(page.getByText(profileName)).not.toBeVisible();
  });

  test('duplicate profile creates copy with new name', async ({ page, request }) => {
    const profileName = testProfileName('Duplicate');
    const copyName = `${profileName} (Copy)`;

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);
    let copyProfile: Profile | null = null;

    try {
      await goToProfiles(page);

      const card = profileCard(page, profileName);
      await expect(card).toBeVisible();
      await card.getByRole('button', { name: 'Expand' }).click();
      await card.getByRole('button', { name: /Duplicate/i }).click();

      const defaultCopyName = `${profileName} (Copy)`;
      const nameInput = card.getByRole('textbox');
      await expect(nameInput).toHaveValue(defaultCopyName);

      await nameInput.clear();
      await nameInput.fill(copyName);

      await card.getByRole('button', { name: 'Create' }).click();

      // Wait for creation
      await page.waitForTimeout(1000);

      // Verify copy exists in database
      copyProfile = await getProfileByName(request, copyName);
      expect(copyProfile).not.toBeNull();
      expect(copyProfile?.id).not.toBe(profile.id);
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
      if (copyProfile) {
        await deleteTestProfileViaAPI(request, copyProfile.id);
      }
    }
  });
});

// ============================================
// Validation Tests
// ============================================

test.describe('Profile Validation', () => {
  test('cannot create profile with duplicate name', async ({ page, request }) => {
    const profileName = testProfileName('DupName');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await goToProfiles(page);

      // Try to create another with same name
      await page.getByRole('button', { name: 'New Agent' }).click();

      await completeWizardStep1(page, profileName);
      await skipWizardStep2(page);
      await completeWizardStep3(page);
      await skipWizardStep4(page);
    await skipWizardStep5(page);
      await submitWizard(page);

      // Should show error - use more specific selector to avoid matching "Duplicate" buttons
      await expect(
        page.getByText(/already exists/i).or(page.locator('.text-red-600, [role="alert"]'))
      ).toBeVisible({ timeout: 5000 });
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('cannot rename profile to existing name', async ({ page, request }) => {
    const profileName1 = testProfileName('Rename1');
    const profileName2 = testProfileName('Rename2');

    // Create two profiles
    const profile1 = await createTestProfileViaAPI(request, profileName1);
    const profile2 = await createTestProfileViaAPI(request, profileName2);

    try {
      await goToProfiles(page);

      const card = profileCard(page, profileName2);
      await card.getByRole('button', { name: 'Expand' }).click();
      await card.getByRole('button', { name: /View and Edit/i }).click();

      await page.getByRole('button', { name: 'Edit', exact: true }).click();

      const nameInput = page.locator('input').first();
      await nameInput.clear();
      await nameInput.fill(profileName1);

      // Save - use exact text to avoid matching "Save Genie Configuration"
      await page.getByRole('button', { name: 'Save Profile Info' }).click();

      // Should show error - use more specific selector to avoid matching "Duplicate" buttons
      await expect(
        page.getByText(/already exists/i).or(page.locator('.text-red-600, [role="alert"]'))
      ).toBeVisible({ timeout: 5000 });
    } finally {
      await deleteTestProfileViaAPI(request, profile1.id);
      await deleteTestProfileViaAPI(request, profile2.id);
    }
  });

  test('wizard requires name to proceed past step 1', async ({ page }) => {
    await goToProfiles(page);

    await page.getByRole('button', { name: 'New Agent' }).click();

    // Next button should be disabled with empty name
    const nextButton = page.getByRole('button', { name: /Next/i });
    await expect(nextButton).toBeDisabled();

    // Clear any existing text and verify still disabled
    const nameInput = page.getByPlaceholder(/Production Analytics/i);
    await nameInput.fill('');
    await expect(nextButton).toBeDisabled();
  });

  test('wizard requires slide style selection', async ({ page }) => {
    await goToProfiles(page);

    await page.getByRole('button', { name: 'New Agent' }).click();

    // Navigate to step 3
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');
    await page.getByRole('button', { name: /Next/i }).click();
    await page.getByRole('button', { name: /Next/i }).click();

    // Next button should be disabled without style selection
    const nextButton = page.getByRole('button', { name: /Next/i });
    await expect(nextButton).toBeDisabled();
  });
});

// NOTE: Profile Switching tests removed — the header ProfileSelector dropdown
// was replaced by the AgentConfigBar. Profile loading is now done via the
// AgentConfigBar "Load Profile" control within the generator view, not the
// header dropdown. These tests will be rewritten in Task 21.

// NOTE: Session-Profile Association tests removed — the header ProfileSelector
// and session-profile auto-switching were removed in the profile rebuild.
// Session history still shows a profile_name column but it's a legacy field.
// New tests for AgentConfig-based profile loading will be added in Task 21.

// ============================================
// Edge Case Tests
// ============================================

test.describe('Profile Edge Cases', () => {
  test('cannot delete the only remaining profile', async ({ page, request }) => {
    // Get all profiles
    const profiles = await getProfilesViaAPI(request);

    // If there's only one profile, the delete button should be hidden or disabled
    if (profiles.length === 1) {
      await goToProfiles(page);

      const card = profileCard(page, profiles[0].name);
      const deleteButton = card.getByRole('button', { name: 'Delete' });

      // Delete button should not be visible or should be disabled
      const isVisible = await deleteButton.isVisible();
      if (isVisible) {
        await expect(deleteButton).toBeDisabled();
      }
    } else {
      // Create a scenario where only one profile exists
      test.skip();
    }
  });

  test('special characters in profile name are handled correctly', async ({ page, request }) => {
    const profileName = `E2E Test Special Chars ${Date.now()} <>"'&`;

    await goToProfiles(page);

    // Open wizard
    await page.getByRole('button', { name: 'New Agent' }).click();

    // Complete wizard with special characters
    await completeWizardStep1(page, profileName);
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
    await skipWizardStep5(page);
    await submitWizard(page);

    // Wait for wizard to close
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).not.toBeVisible({
      timeout: 10000,
    });

    // Verify profile exists
    const profile = await getProfileByName(request, profileName);
    expect(profile).not.toBeNull();

    // Cleanup
    if (profile) {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('unicode characters in profile name are handled correctly', async ({ page, request }) => {
    const profileName = `E2E Test Unicode ${Date.now()} 日本語 émojis 🎨`;

    await goToProfiles(page);

    // Open wizard
    await page.getByRole('button', { name: 'New Agent' }).click();

    // Complete wizard with unicode characters
    await completeWizardStep1(page, profileName);
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
    await skipWizardStep5(page);
    await submitWizard(page);

    // Wait for wizard to close
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).not.toBeVisible({
      timeout: 10000,
    });

    // Verify profile exists with correct name
    const profile = await getProfileByName(request, profileName);
    expect(profile).not.toBeNull();
    expect(profile?.name).toBe(profileName);

    // Cleanup
    if (profile) {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });
});
