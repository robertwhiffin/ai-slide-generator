/**
 * User Guide: Creating Profiles
 * 
 * This Playwright spec captures screenshots for the "Creating Profiles" workflow.
 * Run with: npx playwright test user-guide/02-creating-profiles.spec.ts
 * 
 * The workflow covers:
 * 1. Navigating to the Profiles page
 * 2. Clicking "Create Profile"
 * 3. Entering profile name and description
 * 4. Searching and selecting a Genie room
 * 5. Selecting slide style and deck prompt
 * 6. Completing the wizard
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToProfiles 
} from './shared';

test.describe('User Guide: Creating Profiles', () => {
  test('capture profile creation workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    // Step 01: Navigate to Profiles (shared helper uses direct URL)
    await goToProfiles(page);
    await capture.capture({
      step: '01',
      name: 'profiles-page',
      description: 'Navigate to Profiles from the sidebar or URL',
      highlightSelector: 'button:has-text("Agent profiles")',
    });

    // Step 02: View existing profiles
    await capture.capture({
      step: '02',
      name: 'profiles-list',
      description: 'The Profiles page shows all your configuration profiles',
    });

    // Step 03: Click Create Profile button
    await capture.capture({
      step: '03',
      name: 'create-profile-button',
      description: 'Click "+ Create Profile" to start the profile creation wizard',
      highlightSelector: 'button:has-text("New Agent")',
    });

    // Step 04: Open the creation wizard
    await page.getByRole('button', { name: 'New Agent' }).click();
    await page.waitForTimeout(500);
    
    // Wizard Step 1: Basic Info
    await expect(page.getByRole('heading', { name: 'Create New Profile' })).toBeVisible();
    await capture.capture({
      step: '04',
      name: 'wizard-step1-basics',
      description: 'Step 1: Enter profile name and description',
    });

    // Fill in profile name (required)
    const nameInput = page.locator('input[placeholder*="Production Analytics"]');
    await nameInput.fill('My Custom Profile');
    
    // Fill description (optional)
    const descInput = page.locator('textarea[placeholder*="Optional description"]');
    await descInput.fill('A profile for quarterly reports using sales data');
    
    await capture.capture({
      step: '05',
      name: 'wizard-step1-filled',
      description: 'Enter a descriptive name and description for your profile',
    });

    // Click Next to go to Step 2 (Genie Space)
    await page.getByRole('button', { name: /next/i }).click();
    await page.waitForTimeout(300);
    
    // Wizard Step 2: Genie Space (optional)
    await capture.capture({
      step: '06',
      name: 'wizard-step2-genie',
      description: 'Step 2: Genie Space is optional - skip to create a prompt-only profile',
    });

    // Click Next to skip Genie and go to Step 3 (Slide Style)
    await page.getByRole('button', { name: /next/i }).click();
    await page.waitForTimeout(300);
    
    // Wizard Step 3: Slide Style (required)
    await capture.capture({
      step: '07',
      name: 'wizard-step3-style',
      description: 'Step 3: Select a slide style (required)',
    });

    // Select a slide style (required to proceed)
    const styleOption = page.locator('label').filter({ hasText: 'System Default' }).first();
    if (await styleOption.isVisible()) {
      await styleOption.click();
      await page.waitForTimeout(200);
      
      await capture.capture({
        step: '08',
        name: 'wizard-step3-style-selected',
        description: 'Select a style to define the visual appearance of your slides',
      });
    }

    // Click Next to go to Step 4 (Deck Prompt)
    await page.getByRole('button', { name: /next/i }).click();
    await page.waitForTimeout(300);
    
    // Wizard Step 4: Deck Prompt (optional)
    await capture.capture({
      step: '09',
      name: 'wizard-step4-prompt',
      description: 'Step 4: Optionally select a deck prompt template',
    });

    // Click Next to go to Step 5 (Review)
    await page.getByRole('button', { name: /next/i }).click();
    await page.waitForTimeout(300);
    
    // Wizard Step 5: Review
    await capture.capture({
      step: '10',
      name: 'wizard-step5-review',
      description: 'Step 5: Review your settings and create the profile',
    });

    // Close the wizard without creating (click Cancel/Back or X)
    await page.locator('button:has-text("Cancel"), button:has-text("Back")').first().click()

    console.log('\n=== Generated Markdown for Creating Profiles ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture profile editing workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    await goToProfiles(page);

    // Step 12: Click on an existing profile
    const profileCard = page.locator('text=Sales Analytics').first();
    if (await profileCard.isVisible()) {
      await capture.capture({
        step: '12',
        name: 'profile-card',
        description: 'Click on a profile card to view its details',
        highlightSelector: 'text=Sales Analytics',
      });

      await profileCard.click();
      await page.waitForTimeout(300);

      await capture.capture({
        step: '13',
        name: 'profile-details',
        description: 'View profile details including connected Genie room, style, and prompt',
      });
    }

    // Step 14: Edit button (use first() since multiple may exist)
    const editButton = page.getByRole('button', { name: /edit/i }).first();
    if (await editButton.isVisible()) {
      await capture.capture({
        step: '14',
        name: 'profile-edit-button',
        description: 'Click Edit to modify the profile settings',
        highlightSelector: 'button:has-text("View and Edit")',
      });
    }

    console.log('\n=== Generated Markdown for Profile Editing ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
