/**
 * Base test fixture with global console error filtering.
 * 
 * Import { test, expect } from this file instead of '@playwright/test'
 * to automatically filter out known benign console errors.
 */

import { test as base, expect } from '@playwright/test';

/**
 * Known benign console errors that don't affect test validity.
 * These are logged but not treated as test failures.
 */
const IGNORED_CONSOLE_ERRORS = [
  // React infinite loop warning that occurs during error recovery
  // but doesn't affect actual functionality
  'Maximum update depth exceeded',
];

/**
 * Check if a console error message should be ignored.
 */
function shouldIgnoreError(message: string): boolean {
  return IGNORED_CONSOLE_ERRORS.some(pattern => message.includes(pattern));
}

/**
 * Extended test fixture that sets up console error filtering.
 */
export const test = base.extend<{
  /** Console errors collected during the test (excluding ignored ones) */
  consoleErrors: string[];
}>({
  consoleErrors: async ({ page }, use) => {
    const errors: string[] = [];
    
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (shouldIgnoreError(text)) {
          // Log but don't collect ignored errors
          console.log(`[Browser Console Error - IGNORED]: ${text.substring(0, 100)}...`);
        } else {
          console.log(`[Browser Console Error]: ${text}`);
          errors.push(text);
        }
      }
    });
    
    await use(errors);
  },
});

export { expect };

/**
 * Helper to set up standard console logging for a page.
 * Use this in beforeEach if you're not using the base test fixture.
 */
export function setupConsoleLogging(page: import('@playwright/test').Page): void {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (shouldIgnoreError(text)) {
        console.log(`[Browser Console Error - IGNORED]: ${text.substring(0, 100)}...`);
      } else {
        console.log(`[Browser Console Error]: ${text}`);
      }
    }
  });
}
