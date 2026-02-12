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
 * Create a profile via API for faster test setup
 */
async function createTestProfileViaAPI(
  request: APIRequestContext,
  name: string,
  description?: string
): Promise<Profile> {
  // First, get available slide styles (required for profile creation)
  const stylesResponse = await request.get(`${API_BASE}/slide-styles`);
  const styles = await stylesResponse.json();
  const styleId = styles.styles?.[0]?.id || 1;

  // Create profile with minimal required data
  const response = await request.post(`${API_BASE}/profiles`, {
    data: {
      name,
      description: description || 'E2E test profile',
      slide_style_id: styleId,
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
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Profiles' }).click();
  await expect(page.getByRole('heading', { name: 'Configuration Profiles' })).toBeVisible();
}

async function goToGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'New Session' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

async function goToHistory(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
  await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();
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
    await page.getByRole('button', { name: '+ Create Profile' }).click();
    await expect(page.getByRole('heading', { name: /Create New Profile/i })).toBeVisible();

    // Complete wizard
    await completeWizardStep1(page, profileName, 'Created via E2E test');
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
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

      // Click View and Edit
      const row = page.locator('tr', { hasText: profileName });
      await row.getByRole('button', { name: /View and Edit/i }).click();

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

      // Click View and Edit
      const row = page.locator('tr', { hasText: profileName });
      await row.getByRole('button', { name: /View and Edit/i }).click();

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

    // Click Delete
    const row = page.locator('tr', { hasText: profileName });
    await row.getByRole('button', { name: /Delete/i }).click();

    // Confirm deletion
    await page.getByRole('button', { name: /Confirm|Delete/i }).last().click();

    // Wait for deletion - use table cell selector to avoid matching confirmation dialog
    await expect(page.getByRole('cell', { name: profileName })).not.toBeVisible({ timeout: 5000 });

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

      // Wait for profile row to be visible
      const row = page.locator('tr', { hasText: profileName });
      await expect(row).toBeVisible();

      // Click Duplicate button in this specific row
      await row.getByRole('button', { name: /Duplicate/i }).click();

      // Wait for the duplicate input with the expected default value
      // The input should appear with "(Profile Name) (Copy)" pre-filled
      const defaultCopyName = `${profileName} (Copy)`;
      const nameInput = page.getByPlaceholder('Enter new profile name');
      await expect(nameInput).toHaveValue(defaultCopyName);

      // Clear and fill with our copy name (same in this case but good practice)
      await nameInput.clear();
      await nameInput.fill(copyName);

      // Click the Create button that's in the same row as the input
      // Find the input's parent row and click Create within it
      const inputRow = page.locator('tr').filter({ has: nameInput });
      await inputRow.getByRole('button', { name: 'Create' }).click();

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
      await page.getByRole('button', { name: '+ Create Profile' }).click();

      await completeWizardStep1(page, profileName);
      await skipWizardStep2(page);
      await completeWizardStep3(page);
      await skipWizardStep4(page);
      await submitWizard(page);

      // Should show error - use more specific selector to avoid matching "Duplicate" buttons
      await expect(
        page.getByText(/already exists/i).or(page.locator('.text-red-500, .text-red-600, [role="alert"]'))
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

      // Try to rename profile2 to profile1's name
      const row = page.locator('tr', { hasText: profileName2 });
      await row.getByRole('button', { name: /View and Edit/i }).click();

      // Use exact match to avoid matching "View and Edit" buttons
      await page.getByRole('button', { name: 'Edit', exact: true }).click();

      const nameInput = page.locator('input').first();
      await nameInput.clear();
      await nameInput.fill(profileName1);

      // Save - use exact text to avoid matching "Save Genie Configuration"
      await page.getByRole('button', { name: 'Save Profile Info' }).click();

      // Should show error - use more specific selector to avoid matching "Duplicate" buttons
      await expect(
        page.getByText(/already exists/i).or(page.locator('.text-red-500, .text-red-600, [role="alert"]'))
      ).toBeVisible({ timeout: 5000 });
    } finally {
      await deleteTestProfileViaAPI(request, profile1.id);
      await deleteTestProfileViaAPI(request, profile2.id);
    }
  });

  test('wizard requires name to proceed past step 1', async ({ page }) => {
    await goToProfiles(page);

    await page.getByRole('button', { name: '+ Create Profile' }).click();

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

    await page.getByRole('button', { name: '+ Create Profile' }).click();

    // Navigate to step 3
    await page.getByPlaceholder(/Production Analytics/i).fill('Test Profile');
    await page.getByRole('button', { name: /Next/i }).click();
    await page.getByRole('button', { name: /Next/i }).click();

    // Next button should be disabled without style selection
    const nextButton = page.getByRole('button', { name: /Next/i });
    await expect(nextButton).toBeDisabled();
  });
});

// ============================================
// Profile Switching Tests
// ============================================

test.describe('Profile Switching', () => {
  test('loading profile updates ProfileSelector display', async ({ page, request }) => {
    const profileName = testProfileName('Switch');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await page.goto('/');

      // Get current profile from selector
      const profileButton = page.getByRole('button', { name: /Profile:/ });
      const initialText = await profileButton.textContent();

      // Open selector and load the new profile
      await profileButton.click();

      // Click on the new profile
      await page.getByText(profileName).click();

      // Wait for load
      await page.waitForTimeout(1000);

      // Verify selector shows new profile
      await expect(profileButton).toContainText(profileName);
      expect(await profileButton.textContent()).not.toBe(initialText);
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('loading profile shows "Loaded" badge in list', async ({ page, request }) => {
    const profileName = testProfileName('LoadBadge');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await goToProfiles(page);

      // Load the profile
      const row = page.locator('tr', { hasText: profileName });
      await row.getByRole('button', { name: 'Load' }).click();



      // Confirm if dialog appears
      const confirmButton = page.getByRole('button', { name: /Confirm|Load/i }).last();
      if (await confirmButton.isVisible()) {
        await confirmButton.click();
      }

      // Wait for load to complete and redirect to generator page
      await page.waitForURL(/\/sessions\/.*\/edit/, { timeout: 10000 });

      // loading a profile takes you to the generator page - go back
      await goToProfiles(page);
      await page.waitForTimeout(1000);

      // Row should now show Loaded badge
      const updatedRow = page.locator('tr', { hasText: profileName });
      await expect(updatedRow.getByText('Loaded', { exact: true })).toBeVisible();
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('set default profile updates "Default" badge', async ({ page, request }) => {
    const profileName = testProfileName('SetDefault');

    // Create profile via API
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      await goToProfiles(page);

      // Set as default
      const row = page.locator('tr', { hasText: profileName });
      await row.getByRole('button', { name: /Set Default/i }).click();

      // Confirm
      await page.getByRole('button', { name: /Confirm/i }).click();

      // Wait for update
      await page.waitForTimeout(1000);


      // Row should now show Default badge
      const updatedRow = page.locator('tr', { hasText: profileName });
      await expect(updatedRow.getByText('Default', { exact: true })).toBeVisible();
    } finally {
      // Note: We need to set another profile as default before deleting
      // or the delete might fail
      const profiles = await getProfilesViaAPI(request);
      const otherProfile = profiles.find((p) => p.id !== profile.id);
      if (otherProfile) {
        await request.post(`${API_BASE}/profiles/${otherProfile.id}/set-default`);
      }
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('switching profiles preserves other profile data', async ({ page, request }) => {
    const profileName1 = testProfileName('Preserve1');
    const profileName2 = testProfileName('Preserve2');

    // Create two profiles
    const profile1 = await createTestProfileViaAPI(request, profileName1, 'Description 1');
    const profile2 = await createTestProfileViaAPI(request, profileName2, 'Description 2');

    try {
      await page.goto('/');

      // Load profile1
      const profileButton = page.getByRole('button', { name: /Profile:/ });
      await profileButton.click();
      await page.getByText(profileName1).click();
      await page.waitForTimeout(500);

      // Load profile2
      await profileButton.click();
      await page.getByText(profileName2).click();
      await page.waitForTimeout(500);

      // Verify both profiles still exist with correct data
      const p1 = await getProfileByName(request, profileName1);
      const p2 = await getProfileByName(request, profileName2);

      expect(p1?.description).toBe('Description 1');
      expect(p2?.description).toBe('Description 2');
    } finally {
      await deleteTestProfileViaAPI(request, profile1.id);
      await deleteTestProfileViaAPI(request, profile2.id);
    }
  });
});

// ============================================
// Session-Profile Association Tests
// ============================================

test.describe('Session-Profile Association', () => {
  test('session history shows profile name column', async ({ page }) => {
    await goToHistory(page);

    // Should see Profile column header
    await expect(page.getByRole('columnheader', { name: /Profile/i })).toBeVisible();
  });

  test('new session is associated with current profile', async ({ page, request }) => {
    const profileName = testProfileName('SessionAssoc');

    // Create and load a profile
    const profile = await createTestProfileViaAPI(request, profileName);

    try {
      // Mock the chat stream endpoint to return a simple presentation
      const mockSlideDeck = {
        title: 'Test Presentation',
        slide_count: 1,
        css: '',
        scripts: '',
        external_scripts: [],
        slides: [
          {
            slide_id: 'slide-0',
            title: 'Test Slide',
            html: '<div class="slide"><h1>Test Slide</h1><p>This is a test presentation.</p></div>',
            content_hash: 'abc123',
            scripts: '',
            verification: null,
          },
        ],
      };
      const streamResponse = [
        'data: {"type": "start", "message": "Starting..."}\n\n',
        'data: {"type": "progress", "message": "Generating..."}\n\n',
        `data: {"type": "complete", "message": "Done", "slides": ${JSON.stringify(mockSlideDeck)}}\n\n`,
      ].join('');

      await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: streamResponse,
        });
      });

      await page.goto('/');

      // Load the profile
      const profileButton = page.getByRole('button', { name: /Profile:/ });
      await profileButton.click();
      await page.getByText(profileName).click();
      await page.waitForTimeout(1000);

      // Navigate to Generator and send a message to create a session
      await page.getByRole('navigation').getByRole('button', { name: 'New Session' }).click();
      await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();

      // Type a message
      const chatInput = page.getByRole('textbox', { name: /Ask to generate/i });
      await chatInput.fill('Create a test presentation');
      await page.getByRole('button', { name: 'Send' }).click();

      // Wait for session to be created
      await page.waitForTimeout(2000);

      // Go to History
      await page.getByRole('navigation').getByRole('button', { name: 'History' }).click();
      await expect(page.getByRole('heading', { name: 'Session History' })).toBeVisible();

      // The most recent session should show the profile name
      await expect(page.getByText(profileName).first()).toBeVisible();
    } finally {
      await deleteTestProfileViaAPI(request, profile.id);
    }
  });

  test('restoring session from different profile triggers auto-switch', async ({
    page,
    request,
  }) => {
    // This test requires pre-existing sessions with different profiles
    // Skip if no sessions exist
    const sessionsResponse = await request.get('http://127.0.0.1:8000/api/sessions?limit=10');
    const sessionsData = await sessionsResponse.json();

    if (!sessionsData.sessions || sessionsData.sessions.length < 2) {
      test.skip();
      return;
    }

    // Find two sessions with different profiles
    const sessions = sessionsData.sessions;
    const session1 = sessions[0];
    const session2 = sessions.find(
      (s: { profile_id: number }) => s.profile_id !== session1.profile_id
    );

    if (!session2) {
      test.skip();
      return;
    }

    await page.goto('/');

    // Load session1's profile first
    const profileButton = page.getByRole('button', { name: /Profile:/ });
    await profileButton.click();
    if (session1.profile_name) {
      const profile1Option = page.getByText(session1.profile_name);
      if (await profile1Option.isVisible()) {
        await profile1Option.click();
        await page.waitForTimeout(500);
      }
    }

    // Go to History and restore session2
    await goToHistory(page);

    // Click on session2 to restore it - use session_id for unique matching
    const sessionRow = page.locator('tr').filter({ has: page.getByText(session2.session_id) }).first();
    await sessionRow.getByRole('button', { name: 'Restore' }).click();

    // Wait for potential profile switch
    await page.waitForTimeout(1000);

    // Verify profile switched to session2's profile
    await expect(page.getByRole('button', { name: /Profile:/ })).toContainText(
      session2.profile_name || ''
    );
  });
});

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

      const row = page.locator('tr', { hasText: profiles[0].name });
      const deleteButton = row.getByRole('button', { name: /Delete/i });

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
    await page.getByRole('button', { name: '+ Create Profile' }).click();

    // Complete wizard with special characters
    await completeWizardStep1(page, profileName);
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
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
    await page.getByRole('button', { name: '+ Create Profile' }).click();

    // Complete wizard with unicode characters
    await completeWizardStep1(page, profileName);
    await skipWizardStep2(page);
    await completeWizardStep3(page);
    await skipWizardStep4(page);
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
