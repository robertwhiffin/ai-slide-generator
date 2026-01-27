/**
 * Shared utilities for user guide screenshot generation.
 * 
 * These utilities help capture consistent, annotated screenshots
 * for documentation purposes.
 */

import { Page, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

// ESM-compatible __dirname equivalent
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Base path for user guide images (relative to project root)
const DOCS_IMAGE_BASE = path.join(__dirname, '..', '..', '..', 'docs', 'user-guide', 'images');

export interface ScreenshotOptions {
  /** Step number for ordering (e.g., "01", "02") */
  step: string;
  /** Short descriptive name (e.g., "login-page", "profile-selector") */
  name: string;
  /** Optional description for the markdown alt text */
  description?: string;
  /** Whether to capture full page or just viewport */
  fullPage?: boolean;
  /** Element to highlight before screenshot (optional) */
  highlightSelector?: string;
}

export interface WorkflowStep {
  step: string;
  name: string;
  description: string;
  imagePath: string;
}

/**
 * Screenshot helper that captures and saves images to the docs folder.
 */
export class UserGuideCapture {
  private page: Page;
  private workflow: string;
  private steps: WorkflowStep[] = [];

  constructor(page: Page, workflow: '01-generating-slides' | '02-creating-profiles' | '03-advanced-configuration') {
    this.page = page;
    this.workflow = workflow;
  }

  /**
   * Capture a screenshot for the user guide.
   */
  async capture(options: ScreenshotOptions): Promise<void> {
    const filename = `${options.step}-${options.name}.png`;
    const imagePath = path.join(DOCS_IMAGE_BASE, this.workflow, filename);
    
    // Ensure directory exists
    const dir = path.dirname(imagePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Optional: highlight an element before capturing
    if (options.highlightSelector) {
      await this.highlightElement(options.highlightSelector);
    }

    // Capture the screenshot
    await this.page.screenshot({
      path: imagePath,
      fullPage: options.fullPage ?? false,
    });

    // Remove highlight if added
    if (options.highlightSelector) {
      await this.removeHighlight();
    }

    // Track the step for markdown generation
    this.steps.push({
      step: options.step,
      name: options.name,
      description: options.description || options.name.replace(/-/g, ' '),
      imagePath: `images/${this.workflow}/${filename}`,
    });
  }

  /**
   * Add a visual highlight to an element (red border).
   * Accepts Playwright-style selectors (text=, :has-text(), etc.)
   */
  private async highlightElement(selector: string): Promise<void> {
    try {
      // Use Playwright's locator to find the element
      const locator = this.page.locator(selector).first();
      
      // Check if element exists and is visible
      if (await locator.isVisible({ timeout: 2000 })) {
        // Add highlight via evaluate on the specific element
        await locator.evaluate((el) => {
          (el as HTMLElement).style.outline = '3px solid #FF3621';
          (el as HTMLElement).style.outlineOffset = '2px';
        });
      }
    } catch {
      // If element not found, continue without highlight
      console.log(`Could not highlight element: ${selector}`);
    }
    // Brief pause for render
    await this.page.waitForTimeout(100);
  }

  /**
   * Remove all highlights from the page.
   */
  private async removeHighlight(): Promise<void> {
    await this.page.evaluate(() => {
      document.querySelectorAll('[style*="outline"]').forEach((el) => {
        (el as HTMLElement).style.outline = '';
        (el as HTMLElement).style.outlineOffset = '';
      });
    });
  }

  /**
   * Get the captured steps for markdown generation.
   */
  getSteps(): WorkflowStep[] {
    return [...this.steps];
  }

  /**
   * Generate a markdown snippet for the captured steps.
   */
  generateMarkdown(): string {
    const lines: string[] = [];
    for (const step of this.steps) {
      lines.push(`### Step ${step.step}: ${step.description}`);
      lines.push('');
      lines.push(`![${step.description}](${step.imagePath})`);
      lines.push('');
    }
    return lines.join('\n');
  }

  /**
   * Write the generated markdown to a file.
   */
  async writeMarkdown(filename: string): Promise<void> {
    const markdownPath = path.join(DOCS_IMAGE_BASE, '..', filename);
    const content = this.generateMarkdown();
    fs.writeFileSync(markdownPath, content);
  }
}

/**
 * Set up API mocks for user guide scenarios.
 * Uses live backend by default but can use mocks for predictable screenshots.
 */
export async function setupUserGuideMocks(page: Page): Promise<void> {
  // Import mocks from the fixtures
  const { 
    mockProfiles, 
    mockDeckPrompts, 
    mockSlideStyles, 
    mockSessions 
  } = await import('../fixtures/mocks');

  // Mock profiles
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles)
    });
  });

  // Mock deck prompts
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDeckPrompts)
    });
  });

  // Mock slide styles
  await page.route('http://localhost:8000/api/settings/slide-styles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlideStyles)
    });
  });

  // Mock sessions
  await page.route('http://localhost:8000/api/sessions**', (route, request) => {
    const url = request.url();
    if (url.includes('limit=')) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessions)
      });
    } else {
      route.fulfill({ status: 404 });
    }
  });
}

/**
 * Navigate to the Generator page.
 */
export async function goToGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

/**
 * Navigate to the Profiles page.
 */
export async function goToProfiles(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Profiles' }).click();
  await expect(page.getByRole('heading', { name: 'Configuration Profiles' })).toBeVisible();
}

/**
 * Navigate to Deck Prompts page.
 */
export async function goToDeckPrompts(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Deck Prompts' }).click();
  await expect(page.getByRole('heading', { name: 'Deck Prompt Library' })).toBeVisible();
}

/**
 * Navigate to Slide Styles page.
 */
export async function goToSlideStyles(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Slide Styles' }).click();
  await expect(page.getByRole('heading', { name: 'Slide Style Library' })).toBeVisible();
}
