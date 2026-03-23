import { test, expect, Page, APIRequestContext } from '@playwright/test';
import {
  setupIntegrationMocks,
  createTestStyle,
  createTestDeckPrompt,
  createTestProfile,
  createTestSession,
  putSessionConfig,
  cleanupSession,
  cleanupProfile,
  listProfiles,
  API_BASE,
} from '../helpers/integration-helpers';
import { mockAvailableTools } from '../fixtures/mocks';

/**
 * Profile Integration Tests
 *
 * These tests hit the REAL backend + Postgres. Only chat stream, tools
 * available, and setup status are mocked (via setupIntegrationMocks).
 *
 * They verify profile CRUD operations: listing, displaying config details,
 * empty state, delete, rename, and saving from a session.
 *
 * Prerequisites:
 * - Backend must be running at http://127.0.0.1:8000
 * - Database must be accessible
 *
 * Run with: npx playwright test tests/e2e/profiles-integration.spec.ts
 */

// ---------------------------------------------------------------------------
// Shared test data created once for the entire file
// ---------------------------------------------------------------------------

let testStyle: Record<string, unknown>;
let testPrompt: Record<string, unknown>;

// beforeAll creates library data (style + prompt) shared read-only across all
// tests. We use beforeAll rather than beforeEach because these items are never
// mutated by the tests — only referenced by ID when building profile configs.
test.beforeAll(async ({ request }) => {
  testStyle = await createTestStyle(request, `E2E Style ${Date.now()}`);
  testPrompt = await createTestDeckPrompt(request, `E2E Prompt ${Date.now()}`);
});

test.afterAll(async ({ request }) => {
  try {
    if (testStyle?.id) {
      await request.delete(`${API_BASE}/settings/slide-styles/${testStyle.id}`);
    }
  } catch {
    // ignore
  }
  try {
    if (testPrompt?.id) {
      await request.delete(`${API_BASE}/settings/deck-prompts/${testPrompt.id}`);
    }
  } catch {
    // ignore
  }
});

test.beforeEach(async ({ page }) => {
  await setupIntegrationMocks(page);
});

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

async function goToProfiles(page: Page): Promise<void> {
  await page.goto('/profiles');
  await expect(page.getByRole('heading', { name: /Agent Profiles/i })).toBeVisible({ timeout: 10000 });
}

async function expandConfigBar(page: Page): Promise<void> {
  await page.locator('[data-testid="agent-config-toggle"]').click();
  await page.locator('[data-testid="add-tool-button"]').waitFor({ state: 'visible', timeout: 10000 });
}

async function addGenieSpace(page: Page, spaceName: string): Promise<void> {
  await page.locator('[data-testid="add-tool-button"]').click();
  await page.locator('[data-testid="tool-picker"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByText(spaceName).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'visible', timeout: 10000 });
  await page.getByRole('button', { name: 'Save & Add' }).click();
  await page.locator('[data-testid="genie-detail-panel"]').waitFor({ state: 'hidden', timeout: 10000 });
}

function profileCard(page: Page, name: string) {
  return page.getByTestId('profile-card').filter({ hasText: name }).first();
}

// ---------------------------------------------------------------------------
// Profile list and display
// ---------------------------------------------------------------------------

test.describe('Profile list and display', () => {
  let createdProfileIds: (number | string)[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdProfileIds) {
      await cleanupProfile(request, id);
    }
    createdProfileIds = [];
  });

  test('list profiles from database', async ({ page, request }) => {
    const ts = Date.now();

    const p1 = await createTestProfile(request, {
      name: `Profile-Style-${ts}`,
      agentConfig: {
        tools: [],
        slide_style_id: testStyle.id,
        deck_prompt_id: null,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });

    const p2 = await createTestProfile(request, {
      name: `Profile-Prompt-${ts}`,
      agentConfig: {
        tools: [],
        slide_style_id: null,
        deck_prompt_id: testPrompt.id,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });

    const p3 = await createTestProfile(request, {
      name: `Profile-Genie-${ts}`,
      agentConfig: {
        tools: [
          {
            type: 'genie',
            space_id: mockAvailableTools[0].space_id,
            space_name: mockAvailableTools[0].space_name,
            description: mockAvailableTools[0].description,
            conversation_id: null,
          },
        ],
        slide_style_id: null,
        deck_prompt_id: null,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });

    createdProfileIds.push(p1.id as number, p2.id as number, p3.id as number);

    await goToProfiles(page);

    await expect(page.getByText(`Profile-Style-${ts}`)).toBeVisible();
    await expect(page.getByText(`Profile-Prompt-${ts}`)).toBeVisible();
    await expect(page.getByText(`Profile-Genie-${ts}`)).toBeVisible();
  });

  test('expanded profile shows agent config details', async ({ page, request }) => {
    const ts = Date.now();

    const profile = await createTestProfile(request, {
      name: `Profile-Details-${ts}`,
      agentConfig: {
        tools: [
          {
            type: 'genie',
            space_id: mockAvailableTools[0].space_id,
            space_name: mockAvailableTools[0].space_name,
            description: mockAvailableTools[0].description,
            conversation_id: null,
          },
        ],
        slide_style_id: testStyle.id,
        deck_prompt_id: testPrompt.id,
        system_prompt: null,
        slide_editing_instructions: null,
      },
    });

    createdProfileIds.push(profile.id as number);

    await goToProfiles(page);

    const card = profileCard(page, `Profile-Details-${ts}`);
    await card.getByRole('button', { name: 'Expand' }).click();

    // Verify Genie space name, style name, and prompt name are visible
    await expect(card.getByText('Sales Data Space')).toBeVisible();
    await expect(card.getByText(testStyle.name as string)).toBeVisible();
    await expect(card.getByText(testPrompt.name as string)).toBeVisible();
  });

  test('empty state when no profiles exist', async ({ page, request }) => {
    // Delete ALL profiles via API first
    const allProfiles = await listProfiles(request);
    for (const p of allProfiles) {
      await cleanupProfile(request, p.id as number);
    }

    await goToProfiles(page);

    await expect(page.getByText('No saved configurations found')).toBeVisible();

    // Re-create at least one profile so other tests in the suite aren't affected
    const restored = await createTestProfile(request, {
      name: `Restored-${Date.now()}`,
    });
    createdProfileIds.push(restored.id as number);
  });
});

// ---------------------------------------------------------------------------
// Profile operations
// ---------------------------------------------------------------------------

test.describe('Profile operations', () => {
  let createdProfileIds: (number | string)[] = [];
  let createdSessionIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdProfileIds) {
      await cleanupProfile(request, id);
    }
    createdProfileIds = [];

    for (const id of createdSessionIds) {
      await cleanupSession(request, id);
    }
    createdSessionIds = [];
  });

  test('delete a profile', async ({ page, request }) => {
    const ts = Date.now();

    // Create TWO profiles so delete button is visible (hidden when only 1)
    const keeper = await createTestProfile(request, {
      name: `Keeper-${ts}`,
    });
    const target = await createTestProfile(request, {
      name: `ToDelete-${ts}`,
    });
    createdProfileIds.push(keeper.id as number, target.id as number);

    await goToProfiles(page);

    const card = profileCard(page, `ToDelete-${ts}`);
    await card.getByRole('button', { name: 'Delete' }).click();

    // Confirm in the dialog
    await expect(page.getByRole('heading', { name: /Delete Profile/i })).toBeVisible();
    await page.getByRole('button', { name: 'Confirm' }).click();

    // Verify the profile name disappears from the page
    await expect(page.getByText(`ToDelete-${ts}`)).not.toBeVisible({ timeout: 10000 });

    // Verify via API
    const remaining = await listProfiles(request);
    const deletedStillExists = remaining.some(p => p.id === target.id);
    expect(deletedStillExists).toBe(false);

    // Remove deleted ID from cleanup list (already gone)
    createdProfileIds = createdProfileIds.filter(id => id !== target.id);
  });

  test('rename a profile', async ({ page, request }) => {
    const ts = Date.now();

    const profile = await createTestProfile(request, {
      name: `OriginalName-${ts}`,
    });
    createdProfileIds.push(profile.id as number);

    await goToProfiles(page);

    const card = profileCard(page, `OriginalName-${ts}`);
    await card.getByRole('button', { name: 'Expand' }).click();
    await card.getByRole('button', { name: /Rename/i }).click();

    // Clear and type new name
    const textbox = card.getByRole('textbox');
    await textbox.clear();
    const newName = `Renamed-${ts}`;
    await textbox.fill(newName);
    await card.getByRole('button', { name: 'Save' }).click();

    // Verify new name visible on page
    await expect(page.getByText(newName)).toBeVisible({ timeout: 10000 });

    // Verify via API
    const all = await listProfiles(request);
    const updated = all.find(p => p.id === profile.id);
    expect(updated).toBeTruthy();
    expect(updated!.name).toBe(newName);
  });

  test('save current session as profile', async ({ page, request }) => {
    // Navigate to home, send a message to create a session
    await page.goto('/');
    await page.getByRole('textbox').fill('Create a test presentation');
    await page.getByRole('button', { name: 'Send' }).click();
    await page.locator('.slide-container').waitFor({ state: 'visible', timeout: 15000 });

    // Extract session ID for cleanup
    const url = page.url();
    const match = url.match(/\/sessions\/([^/]+)\/edit/);
    if (match) {
      createdSessionIds.push(match[1]);
    }

    // Add a Genie space to the config
    await expandConfigBar(page);
    await addGenieSpace(page, 'Sales Data Space');
    // Wait for config to persist
    await page.waitForTimeout(1000);

    // Save as profile
    const profileName = `SavedProfile-${Date.now()}`;
    await page.locator('[data-testid="save-profile-button"]').click();
    await page.getByPlaceholder('Profile name').fill(profileName);
    await page.getByPlaceholder('Description (optional)').fill('Integration test profile');
    await page.getByRole('button', { name: 'Save' }).click();

    // Wait for dialog to close
    await expect(page.getByText('Save as Profile')).not.toBeVisible({ timeout: 10000 });

    // Navigate to profiles page and verify the new profile appears
    await goToProfiles(page);
    await expect(page.getByText(profileName)).toBeVisible({ timeout: 10000 });

    // Look up the profile for cleanup
    const all = await listProfiles(request);
    const saved = all.find(p => p.name === profileName);
    if (saved) {
      createdProfileIds.push(saved.id as number);
    }
  });
});
