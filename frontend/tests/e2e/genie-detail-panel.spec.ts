/**
 * E2E tests for the Genie Detail Panel.
 *
 * Tests the two entry points:
 *  1. Adding a new Genie space via ToolPicker → detail panel
 *  2. Editing an existing Genie space by clicking its chip
 *
 * Also covers: cancel flows, escape key, description editing.
 */

import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import { mockAvailableTools } from '../fixtures/mocks';

// Helper: navigate to session edit page and expand the agent config bar
async function openAgentConfig(page: import('@playwright/test').Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  // Wait for session to load
  await expect(page.getByTestId('agent-config-bar')).toBeVisible();
  // Expand the config bar
  await page.getByTestId('agent-config-toggle').click();
  // Wait for expanded content
  await expect(page.getByTestId('add-tool-genie')).toBeVisible();
}

// Helper: mock agent-config with an existing Genie tool
async function mockAgentConfigWithGenie(page: import('@playwright/test').Page) {
  await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tools: [{
            type: 'genie',
            space_id: '01JGKX5N2PWQV8ABC123DEF456',
            space_name: 'Sales Data Space',
            description: 'Contains sales and revenue data',
          }],
          slide_style_id: 1,
          deck_prompt_id: null,
          system_prompt: null,
          slide_editing_instructions: null,
        }),
      });
    } else {
      // PUT — return whatever was sent
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: route.request().postData() ?? '{}',
      });
    }
  });
}

test.describe('Genie Detail Panel', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
  });

  // -----------------------------------------------------------------------
  // Add flow
  // -----------------------------------------------------------------------

  test.describe('Add flow (via ToolPicker)', () => {
    test('clicking a Genie space in ToolPicker opens the detail panel', async ({ page }) => {
      await openAgentConfig(page);

      // Open tool picker
      await page.getByTestId('add-tool-genie').click();
      await expect(page.getByTestId('tool-picker')).toBeVisible();

      // Click a Genie space — should open detail panel, not add immediately
      await page.getByText('Sales Data Space').click();

      // Detail panel should be visible
      await expect(page.getByTestId('genie-detail-panel')).toBeVisible();
      // Tool picker should be closed
      await expect(page.getByTestId('tool-picker')).not.toBeVisible();
    });

    test('detail panel shows full description and space ID', async ({ page }) => {
      await openAgentConfig(page);

      await page.getByTestId('add-tool-genie').click();
      await page.getByText('Sales Data Space').click();

      const panel = page.getByTestId('genie-detail-panel');
      // Space name visible
      await expect(panel.getByText('Sales Data Space')).toBeVisible();
      // Space ID visible
      await expect(panel.getByText('01JGKX5N2PWQV8ABC123DEF456')).toBeVisible();
      // Full description in textarea
      const textarea = panel.getByRole('textbox');
      await expect(textarea).toHaveValue('Contains sales and revenue data');
    });

    test('Save & Add button adds the tool with edited description', async ({ page }) => {
      // Mock the PUT to capture what gets sent
      let capturedConfig: any = null;
      await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route) => {
        if (route.request().method() === 'PUT') {
          capturedConfig = JSON.parse(route.request().postData() ?? '{}');
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: route.request().postData() ?? '{}',
          });
        } else {
          route.fallback();
        }
      });

      await openAgentConfig(page);
      await page.getByTestId('add-tool-genie').click();
      await page.getByText('Sales Data Space').click();

      const panel = page.getByTestId('genie-detail-panel');
      const textarea = panel.getByRole('textbox');

      // Edit the description
      await textarea.clear();
      await textarea.fill('Custom description for agent tool selection');

      // Click Save & Add
      await panel.getByRole('button', { name: /save.*add/i }).click();

      // Panel should close
      await expect(page.getByTestId('genie-detail-panel')).not.toBeVisible();

      // Tool chip should appear
      await expect(page.getByText('Sales Data Space')).toBeVisible();

      // Verify the PUT contained the edited description
      expect(capturedConfig).not.toBeNull();
      const genieTool = capturedConfig.tools.find((t: any) => t.type === 'genie');
      expect(genieTool.description).toBe('Custom description for agent tool selection');
    });

    test('Cancel does not add the tool', async ({ page }) => {
      await openAgentConfig(page);
      await page.getByTestId('add-tool-genie').click();
      await page.getByText('Sales Data Space').click();

      const panel = page.getByTestId('genie-detail-panel');
      await panel.getByRole('button', { name: 'Cancel' }).click();

      // Panel should close
      await expect(page.getByTestId('genie-detail-panel')).not.toBeVisible();
      // No tool chip should appear (config starts empty)
      await expect(page.locator('[data-testid="agent-config-bar"]').getByText('Sales Data Space')).not.toBeVisible();
    });

    test('Escape key closes the detail panel without adding', async ({ page }) => {
      await openAgentConfig(page);
      await page.getByTestId('add-tool-genie').click();
      await page.getByText('Sales Data Space').click();

      await expect(page.getByTestId('genie-detail-panel')).toBeVisible();

      // Press Escape
      await page.keyboard.press('Escape');

      // Panel should close
      await expect(page.getByTestId('genie-detail-panel')).not.toBeVisible();
    });
  });

  // -----------------------------------------------------------------------
  // Edit flow
  // -----------------------------------------------------------------------

  test.describe('Edit flow (via ToolChip)', () => {
    test.beforeEach(async ({ page }) => {
      // Override the agent-config mock to include a Genie tool
      await mockAgentConfigWithGenie(page);
    });

    test('clicking a Genie chip label opens the detail panel in edit mode', async ({ page }) => {
      await openAgentConfig(page);

      // Click the chip label (not the X button)
      await page.getByTestId('tool-chip-label').first().click();

      // Detail panel should open
      const panel = page.getByTestId('genie-detail-panel');
      await expect(panel).toBeVisible();

      // Should show "Save" not "Save & Add"
      await expect(panel.getByRole('button', { name: 'Save' })).toBeVisible();
      await expect(panel.getByRole('button', { name: /save.*add/i })).not.toBeVisible();
    });

    test('editing description and saving updates the tool', async ({ page }) => {
      let capturedConfig: any = null;
      await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route) => {
        if (route.request().method() === 'PUT') {
          capturedConfig = JSON.parse(route.request().postData() ?? '{}');
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: route.request().postData() ?? '{}',
          });
        } else {
          route.fallback();
        }
      });

      await openAgentConfig(page);
      await page.getByTestId('tool-chip-label').first().click();

      const panel = page.getByTestId('genie-detail-panel');
      const textarea = panel.getByRole('textbox');

      // Should show current description
      await expect(textarea).toHaveValue('Contains sales and revenue data');

      // Edit
      await textarea.clear();
      await textarea.fill('Updated description for better agent routing');

      // Save
      await panel.getByRole('button', { name: 'Save' }).click();

      // Panel should close
      await expect(page.getByTestId('genie-detail-panel')).not.toBeVisible();

      // Verify PUT had updated description
      expect(capturedConfig).not.toBeNull();
      const genieTool = capturedConfig.tools.find((t: any) => t.type === 'genie');
      expect(genieTool.description).toBe('Updated description for better agent routing');
    });

    test('cancel on edit reverts description', async ({ page }) => {
      await openAgentConfig(page);
      await page.getByTestId('tool-chip-label').first().click();

      const panel = page.getByTestId('genie-detail-panel');
      const textarea = panel.getByRole('textbox');

      // Edit the description
      await textarea.clear();
      await textarea.fill('This should be reverted');

      // Cancel
      await panel.getByRole('button', { name: 'Cancel' }).click();

      // Panel should close
      await expect(page.getByTestId('genie-detail-panel')).not.toBeVisible();

      // Re-open and verify original description is back
      await page.getByTestId('tool-chip-label').first().click();
      await expect(page.getByTestId('genie-detail-panel').getByRole('textbox'))
        .toHaveValue('Contains sales and revenue data');
    });
  });

  // -----------------------------------------------------------------------
  // Edge cases
  // -----------------------------------------------------------------------

  test.describe('Edge cases', () => {
    test('empty description shows placeholder', async ({ page }) => {
      // Override tools to return a space with no description
      await page.route('**/api/tools/available', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{
            type: 'genie',
            space_id: 'no-desc-space',
            space_name: 'No Description Space',
            description: null,
          }]),
        });
      });

      await openAgentConfig(page);
      await page.getByTestId('add-tool-genie').click();
      await page.getByText('No Description Space').click();

      const panel = page.getByTestId('genie-detail-panel');
      const textarea = panel.getByRole('textbox');
      await expect(textarea).toHaveValue('');
      await expect(textarea).toHaveAttribute('placeholder', /describe when/i);
    });

    test('textarea auto-focuses on panel open', async ({ page }) => {
      await openAgentConfig(page);
      await page.getByTestId('add-tool-genie').click();
      await page.getByText('Sales Data Space').click();

      const textarea = page.getByTestId('genie-detail-panel').getByRole('textbox');
      await expect(textarea).toBeFocused();
    });
  });
});
