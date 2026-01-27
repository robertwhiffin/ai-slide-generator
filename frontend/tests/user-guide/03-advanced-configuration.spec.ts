/**
 * User Guide: Advanced Configuration
 * 
 * This Playwright spec captures screenshots for the "Advanced Configuration" workflow.
 * Run with: npx playwright test user-guide/03-advanced-configuration.spec.ts
 * 
 * The workflow covers:
 * 1. Creating and managing Deck Prompts
 * 2. Creating and managing Slide Styles
 * 3. Understanding system vs custom items
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToDeckPrompts,
  goToSlideStyles 
} from './shared';

test.describe('User Guide: Advanced Configuration', () => {
  
  test.describe('Deck Prompts', () => {
    test('capture deck prompts workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      const capture = new UserGuideCapture(page, '03-advanced-configuration');

      // Step 01: Navigate to Deck Prompts
      await page.goto('/');
      await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
      await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
      await capture.capture({
        step: '01',
        name: 'deck-prompts-page',
        description: 'Navigate to Deck Prompts from the navigation bar',
        highlightSelector: 'nav button:has-text("Deck Prompts")',
      });

      // Step 02: View prompt library
      await capture.capture({
        step: '02',
        name: 'deck-prompts-list',
        description: 'The Deck Prompt Library shows all available prompt templates',
      });

      // Step 03: Create Prompt button
      await capture.capture({
        step: '03',
        name: 'create-prompt-button',
        description: 'Click "+ Create Prompt" to create a new deck prompt template',
        highlightSelector: 'button:has-text("Create Prompt")',
      });

      // Step 04: Open creation modal
      await page.getByRole('button', { name: '+ Create Prompt' }).click();
      await expect(page.getByRole('heading', { name: 'Create Deck Prompt' })).toBeVisible();
      await capture.capture({
        step: '04',
        name: 'create-prompt-modal',
        description: 'The creation form appears - enter name, description, category, and prompt content',
      });

      // Step 05: Fill in prompt details
      await page.getByRole('textbox', { name: 'Name *' }).fill('Monthly Status Report');
      await page.getByRole('textbox', { name: 'Description' }).fill('Template for monthly team status updates');
      await page.getByRole('textbox', { name: 'Category' }).fill('Report');
      
      await capture.capture({
        step: '05',
        name: 'create-prompt-filled',
        description: 'Fill in the prompt details - name is required, category helps organize your prompts',
      });

      // Step 06: Prompt content editor
      const contentEditor = page.getByRole('textbox', { name: /content|prompt/i });
      if (await contentEditor.isVisible()) {
        await contentEditor.fill('Create a monthly status report presentation that includes: team achievements, key metrics, blockers, and next month priorities.');
        await capture.capture({
          step: '06',
          name: 'prompt-content-editor',
          description: 'Enter the prompt content - this is the instruction that guides slide generation',
        });
      }

      // Close modal
      await page.getByRole('button', { name: 'Cancel' }).click();
      await page.waitForTimeout(200);

      // Step 07: View an existing prompt
      const promptCard = page.getByRole('heading', { name: 'Monthly Review' }).first();
      if (await promptCard.isVisible()) {
        await promptCard.click();
        await page.waitForTimeout(300);
        
        await capture.capture({
          step: '07',
          name: 'prompt-details',
          description: 'Click a prompt to view its details and content',
        });
      }

      // Step 08: System prompt badge
      await capture.capture({
        step: '08',
        name: 'system-prompt-indicator',
        description: 'System prompts are protected and cannot be edited - duplicate them to customize',
      });

      console.log('\n=== Generated Markdown for Deck Prompts ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });

  test.describe('Slide Styles', () => {
    test('capture slide styles workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      const capture = new UserGuideCapture(page, '03-advanced-configuration');

      // Step 09: Navigate to Slide Styles
      await page.goto('/');
      await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
      await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
      await capture.capture({
        step: '09',
        name: 'slide-styles-page',
        description: 'Navigate to Slide Styles from the navigation bar',
        highlightSelector: 'nav button:has-text("Slide Styles")',
      });

      // Step 10: View style library
      await capture.capture({
        step: '10',
        name: 'slide-styles-list',
        description: 'The Slide Style Library shows all available CSS styles for presentations',
      });

      // Step 11: Create Style button
      await capture.capture({
        step: '11',
        name: 'create-style-button',
        description: 'Click "+ Create Style" to create a custom slide style',
        highlightSelector: 'button:has-text("Create Style")',
      });

      // Step 12: Open creation modal
      await page.getByRole('button', { name: '+ Create Style' }).click();
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
      await capture.capture({
        step: '12',
        name: 'create-style-modal',
        description: 'Enter name, description, and CSS content for your custom style',
      });

      // Step 13: Style form fields
      await page.getByRole('textbox', { name: 'Name *' }).fill('Corporate Blue');
      await page.getByRole('textbox', { name: 'Description' }).fill('Professional blue theme with clean typography');
      await page.getByRole('textbox', { name: 'Category' }).fill('Corporate');
      
      await capture.capture({
        step: '13',
        name: 'create-style-filled',
        description: 'Provide a descriptive name and category for easy identification',
      });

      // Close modal
      await page.getByRole('button', { name: 'Cancel' }).click();
      await page.waitForTimeout(200);

      // Step 14: View system style
      const systemStyle = page.getByRole('heading', { name: 'System Default' }).first();
      if (await systemStyle.isVisible()) {
        await systemStyle.click();
        await page.waitForTimeout(300);
        
        await capture.capture({
          step: '14',
          name: 'system-style-details',
          description: 'System styles cannot be edited - use as reference when creating custom styles',
        });
      }

      // Step 15: Corporate Theme style
      const brandStyle = page.getByRole('heading', { name: 'Corporate Theme' }).first();
      if (await brandStyle.isVisible()) {
        await brandStyle.click();
        await page.waitForTimeout(300);
        
        await capture.capture({
          step: '15',
          name: 'brand-style-details',
          description: 'The Corporate Theme style applies official colors and typography',
        });
      }

      console.log('\n=== Generated Markdown for Slide Styles ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });

  test('capture combined configuration overview', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '03-advanced-configuration');

    // Overview screenshot of navigation
    await page.goto('/');
    await capture.capture({
      step: '16',
      name: 'configuration-navigation',
      description: 'Access configuration pages from the main navigation: Profiles, Deck Prompts, and Slide Styles',
    });

    console.log('\n=== Generated Markdown for Configuration Overview ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
