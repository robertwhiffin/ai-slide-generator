/**
 * User Guide: Creating Profiles
 *
 * This Playwright spec captures screenshots for the "Creating Profiles" workflow.
 * Run with: npx playwright test user-guide/02-creating-profiles.spec.ts
 *
 * The workflow covers:
 * 1. Viewing the AgentConfigBar with tools configured
 * 2. Saving a session config as a profile
 * 3. Browsing saved profiles on the Profiles page
 * 4. Loading a profile into a session
 */

import { test, expect } from '@playwright/test';
import {
  UserGuideCapture,
  setupUserGuideMocks,
  goToGenerator,
  goToPreSessionGenerator,
  goToProfiles
} from './shared';

test.describe('User Guide: Creating Profiles', () => {
  test('capture save-from-session workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    // Step 01: Show pre-session generator with config bar
    // Note: "Save as Profile" is disabled in pre-session mode
    await goToPreSessionGenerator(page);
    await capture.capture({
      step: '01',
      name: 'pre-session-config-bar',
      description: 'The config bar shows your current tools, style, and prompt — configure before or during a session',
    });

    // Step 02: Navigate to active session to show AgentConfigBar in session mode
    await goToGenerator(page);
    await capture.capture({
      step: '02',
      name: 'session-config-bar',
      description: 'In an active session, the config bar syncs changes to the backend',
    });

    // Step 03: Highlight Save as Profile button (enabled in session mode)
    await capture.capture({
      step: '03',
      name: 'save-as-profile-button',
      description: 'Click "Save as Profile" to save your current configuration as a reusable profile',
      highlightSelector: 'button:has-text("Save as Profile")',
    });

    // Step 04: Click Save as Profile to open dialog
    await page.getByRole('button', { name: 'Save as Profile' }).click();
    await page.waitForTimeout(500);
    await capture.capture({
      step: '04',
      name: 'save-profile-dialog',
      description: 'Enter a name and description for your profile',
    });

    // Step 05: Fill in profile name and description
    const nameInput = page.getByPlaceholder(/name/i).first();
    if (await nameInput.isVisible({ timeout: 2000 })) {
      await nameInput.fill('Quarterly Reports');
      const descInput = page.getByPlaceholder(/description/i).first();
      if (await descInput.isVisible()) {
        await descInput.fill('Sales data with executive summary template');
      }
      await capture.capture({
        step: '05',
        name: 'save-profile-filled',
        description: 'Give your profile a descriptive name — it captures the current tools, style, and prompt',
      });
    }

    // Close dialog without saving (no mock for the save endpoint)
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    console.log('\n=== Generated Markdown for Save Profile Workflow ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture load-profile workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    await goToGenerator(page);

    // Step 06: Highlight Load Profile button
    await capture.capture({
      step: '06',
      name: 'load-profile-button',
      description: 'Click "Load Profile" to apply a saved configuration to your session',
      highlightSelector: '[data-testid="load-profile-button"]',
    });

    // Step 07: Click Load Profile to open picker
    await page.getByTestId('load-profile-button').click();
    await page.waitForTimeout(500);
    await capture.capture({
      step: '07',
      name: 'load-profile-picker',
      description: 'Select from your saved profiles — the config is copied into your current session',
    });

    // Close picker
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    console.log('\n=== Generated Markdown for Load Profile Workflow ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture profile management page', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    // Step 08: Navigate to Profiles page
    await goToProfiles(page);
    await capture.capture({
      step: '08',
      name: 'profiles-page',
      description: 'The Profiles page lists all saved configurations',
    });

    // Step 09: Highlight a profile card
    const profileCard = page.locator('text=Sales Analytics').first();
    if (await profileCard.isVisible({ timeout: 2000 })) {
      await capture.capture({
        step: '09',
        name: 'profile-card',
        description: 'Click a profile to view its details — tools, style, and prompt',
        highlightSelector: 'text=Sales Analytics',
      });

      // Step 10: Click to view details
      await profileCard.click();
      await page.waitForTimeout(300);
      await capture.capture({
        step: '10',
        name: 'profile-details',
        description: 'View and edit profile name, description, or delete the profile',
      });
    }

    console.log('\n=== Generated Markdown for Profile Management ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
