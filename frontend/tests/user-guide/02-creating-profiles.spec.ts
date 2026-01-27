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

    // Step 01: Navigate to Profiles
    await page.goto('/');
    await page.getByRole('navigation').getByRole('button', { name: 'Profiles' }).click();
    await expect(page.getByRole('heading', { name: 'Configuration Profiles' })).toBeVisible();
    await capture.capture({
      step: '01',
      name: 'profiles-page',
      description: 'Navigate to Profiles from the navigation bar',
      highlightSelector: 'nav button:has-text("Profiles")',
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
      highlightSelector: 'button:has-text("Create Profile")',
    });

    // Step 04: Open the creation wizard
    await page.getByRole('button', { name: '+ Create Profile' }).click();
    await page.waitForTimeout(300);
    
    // Check if wizard modal appears
    const wizardHeading = page.getByRole('heading', { name: /Create.*Profile|New Profile/i });
    if (await wizardHeading.isVisible()) {
      await capture.capture({
        step: '04',
        name: 'wizard-step1-basics',
        description: 'Step 1: Enter profile name and description',
      });
    }

    // Step 05: Fill in profile basics
    const nameInput = page.getByRole('textbox', { name: /name/i }).first();
    if (await nameInput.isVisible()) {
      await nameInput.fill('My Custom Profile');
      
      const descInput = page.getByRole('textbox', { name: /description/i });
      if (await descInput.isVisible()) {
        await descInput.fill('A profile for quarterly reports using sales data');
      }

      await capture.capture({
        step: '05',
        name: 'wizard-step1-filled',
        description: 'Enter a descriptive name and description for your profile',
      });
    }

    // Step 06: Look for Next button or Genie room selection
    const nextButton = page.getByRole('button', { name: /next/i });
    if (await nextButton.isVisible()) {
      await nextButton.click();
      await page.waitForTimeout(300);
      
      await capture.capture({
        step: '06',
        name: 'wizard-step2-genie',
        description: 'Step 2: Search and select a Genie room for data access',
      });
    }

    // Step 07: Genie room search (if visible)
    const genieSearch = page.getByRole('textbox', { name: /search.*genie|genie.*room/i });
    if (await genieSearch.isVisible()) {
      await genieSearch.fill('sales');
      await page.waitForTimeout(500);
      
      await capture.capture({
        step: '07',
        name: 'wizard-genie-search',
        description: 'Search for Genie rooms by name - matching rooms will appear in a dropdown',
      });
    }

    // Step 08: Look for ID tab option
    const idTab = page.getByRole('tab', { name: /enter.*id|id/i });
    if (await idTab.isVisible()) {
      await idTab.click();
      await page.waitForTimeout(200);
      
      await capture.capture({
        step: '08',
        name: 'wizard-genie-id-tab',
        description: 'Alternatively, switch to the ID tab and paste a Genie room ID directly',
      });
    }

    // Step 09: Style selection step
    const styleStep = page.getByText(/slide style|select.*style/i);
    if (await styleStep.isVisible()) {
      await capture.capture({
        step: '09',
        name: 'wizard-step3-style',
        description: 'Step 3: Select a slide style for your presentations',
      });
    }

    // Step 10: Prompt selection step
    const promptStep = page.getByText(/deck prompt|select.*prompt/i);
    if (await promptStep.isVisible()) {
      await capture.capture({
        step: '10',
        name: 'wizard-step4-prompt',
        description: 'Step 4: Choose a deck prompt template (optional)',
      });
    }

    // Step 11: Cancel button demonstration
    const cancelButton = page.getByRole('button', { name: /cancel/i });
    if (await cancelButton.isVisible()) {
      await capture.capture({
        step: '11',
        name: 'wizard-cancel',
        description: 'Click Cancel to exit without saving, or complete the wizard to create the profile',
        highlightSelector: 'button:has-text("Cancel")',
      });
    }

    // Close the wizard
    if (await cancelButton.isVisible()) {
      await cancelButton.click();
    }

    console.log('\n=== Generated Markdown for Creating Profiles ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture profile editing workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    await goToProfiles(page);

    // Step 12: Click on an existing profile
    const profileCard = page.locator('text=KPMG UK Consumption').first();
    if (await profileCard.isVisible()) {
      await capture.capture({
        step: '12',
        name: 'profile-card',
        description: 'Click on a profile card to view its details',
        highlightSelector: 'text=KPMG UK Consumption',
      });

      await profileCard.click();
      await page.waitForTimeout(300);

      await capture.capture({
        step: '13',
        name: 'profile-details',
        description: 'View profile details including connected Genie room, style, and prompt',
      });
    }

    // Step 14: Edit button
    const editButton = page.getByRole('button', { name: /edit/i });
    if (await editButton.isVisible()) {
      await capture.capture({
        step: '14',
        name: 'profile-edit-button',
        description: 'Click Edit to modify the profile settings',
        highlightSelector: 'button:has-text("Edit")',
      });
    }

    console.log('\n=== Generated Markdown for Profile Editing ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
