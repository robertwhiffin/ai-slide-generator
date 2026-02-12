/**
 * User Guide: Generating Slides
 * 
 * This Playwright spec captures screenshots for the "Generating Slides" workflow.
 * Run with: npx playwright test user-guide/01-generating-slides.spec.ts
 * 
 * The workflow covers:
 * 1. Opening the app / logging in
 * 2. Navigating to the Generator page
 * 3. Selecting a profile
 * 4. Entering a prompt and generating slides
 * 5. Viewing and interacting with generated slides
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToGenerator 
} from './shared';

test.describe('User Guide: Generating Slides', () => {
  test('capture workflow screenshots', async ({ page }) => {
    // Set up mocks for predictable screenshots
    await setupUserGuideMocks(page);
    
    const capture = new UserGuideCapture(page, '01-generating-slides');

    // Step 01: App Landing / Home Page
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'databricks tellr', exact: true })).toBeVisible();
    await capture.capture({
      step: '01',
      name: 'app-landing',
      description: 'Open the app - you\'ll see the main navigation and Help page by default',
    });

    // Step 02: Navigate to Generator
    await page.getByRole('navigation').getByRole('button', { name: 'New Session' }).click();
    await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
    await capture.capture({
      step: '02',
      name: 'generator-view',
      description: 'Navigate to the New Session view using the navigation bar',
      highlightSelector: 'nav button:has-text("New Session")',
    });

    // Step 03: Profile Selector
    await capture.capture({
      step: '03',
      name: 'profile-selector',
      description: 'The current profile is shown in the header - click to change profiles',
      highlightSelector: 'button:has-text("Profile:")',
    });

    // Step 04: Open Profile Dropdown
    await page.getByRole('button', { name: /Profile:/ }).click();
    // Wait for dropdown to appear
    await page.waitForTimeout(300);
    await capture.capture({
      step: '04',
      name: 'profile-dropdown',
      description: 'Select the profile that matches your data source and presentation style',
    });

    // Close dropdown by clicking elsewhere
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    // Step 05: Chat Input
    const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
    await chatInput.click();
    await capture.capture({
      step: '05',
      name: 'chat-input-empty',
      description: 'The chat input is where you enter prompts to generate or modify slides',
      highlightSelector: 'textarea',
    });

    // Step 06: Enter a Prompt
    await chatInput.fill('Create a presentation about cloud computing benefits with 3 slides');
    await capture.capture({
      step: '06',
      name: 'chat-input-with-prompt',
      description: 'Type your request - be specific about the topic and number of slides',
    });

    // Step 07: Send Button Enabled
    await capture.capture({
      step: '07',
      name: 'send-button-enabled',
      description: 'Click Send or press Enter to start generating slides',
      highlightSelector: 'button:has-text("Send")',
    });

    // Step 08: Simulate slide generation (click send, mocks will respond)
    await page.getByRole('button', { name: 'Send' }).click();
    
    // Wait for slides to appear (mocked response)
    await page.waitForTimeout(1000);
    
    // Check if slides appeared
    const slidePanel = page.locator('[class*="slide"]').first();
    if (await slidePanel.isVisible()) {
      await capture.capture({
        step: '08',
        name: 'slides-generated',
        description: 'Slides appear in the right panel as they are generated',
      });
    }

    // Step 09: Slide Actions (if slides are visible)
    const slides = page.locator('.slide-tile, [data-testid*="slide"]');
    if (await slides.count() > 0) {
      await capture.capture({
        step: '09',
        name: 'slide-actions',
        description: 'Each slide has actions for editing, verification, and more',
      });
    }

    // Output markdown for documentation
    console.log('\n=== Generated Markdown for User Guide ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture slide editing workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '01-generating-slides');

    // This test captures the iterative editing workflow
    await goToGenerator(page);

    // Capture empty state
    await capture.capture({
      step: '10',
      name: 'empty-state',
      description: 'Before generating, you\'ll see an empty slide panel',
    });

    // Additional editing steps would go here after slides are generated
    // For now, we document what the empty state looks like
  });
});
