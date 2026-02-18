/**
 * User Guide: Retrieving User Feedback
 * 
 * This Playwright spec captures screenshots for the "Retrieving Feedback" workflow.
 * Run with: npx playwright test user-guide/04-retrieving-feedback.spec.ts
 * 
 * The workflow covers:
 * 1. The Feedback Dashboard on the Admin page
 * 2. Summary metric cards
 * 3. Weekly Survey Stats table
 * 4. AI Feedback Summary section
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToAdmin
} from './shared';

async function setupFeedbackMocks(page: import('@playwright/test').Page): Promise<void> {
  const { mockFeedbackStats, mockFeedbackSummary } = await import('../fixtures/mocks');

  await page.route('http://127.0.0.1:8000/api/feedback/report/stats**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockFeedbackStats),
    });
  });

  await page.route('http://127.0.0.1:8000/api/feedback/report/summary**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockFeedbackSummary),
    });
  });

  await page.route('http://127.0.0.1:8000/api/feedback/conversations**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [], total: 0 }),
    });
  });

  // Mock Google credentials status so the admin page doesn't error on the other tab
  await page.route('http://127.0.0.1:8000/api/admin/google-credentials/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ has_credentials: false }),
    });
  });

  await page.route('http://127.0.0.1:8000/api/export/google-slides/auth/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ authorized: false }),
    });
  });
}

test.describe('User Guide: Retrieving Feedback', () => {

  test('capture feedback dashboard workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    await setupFeedbackMocks(page);
    const capture = new UserGuideCapture(page, '04-retrieving-feedback');

    // Step 01: Navigate to Admin page (Feedback tab is default)
    await page.goto('/admin');
    await expect(page.getByRole('heading', { name: 'Feedback Dashboard' })).toBeVisible();
    // Wait for stats to load
    await page.waitForTimeout(500);
    await capture.capture({
      step: '01',
      name: 'admin-feedback-tab',
      description: 'Open the Admin page — the Feedback tab is selected by default',
      highlightSelector: '#feedback-tab',
    });

    // Step 02: Summary metric cards
    await capture.capture({
      step: '02',
      name: 'summary-cards',
      description: 'Summary cards show key metrics: users, sessions, survey responses, ratings, and time saved',
      highlightSelector: 'text=Distinct Users',
    });

    // Step 03: Weekly Survey Stats table
    await capture.capture({
      step: '03',
      name: 'weekly-stats',
      description: 'The Weekly Survey Stats table breaks down responses by week with star ratings, NPS, and time saved',
      highlightSelector: 'text=Weekly Survey Stats',
    });

    // Step 04: AI Feedback Summary
    // Scroll down to make the summary visible
    const summaryHeading = page.getByRole('heading', { name: 'AI Feedback Summary' });
    await summaryHeading.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await capture.capture({
      step: '04',
      name: 'ai-summary',
      description: 'The AI Feedback Summary analyses recent feedback and highlights top themes and category breakdown',
      highlightSelector: 'text=AI Feedback Summary',
    });

    console.log('\n=== Generated Markdown for Retrieving Feedback ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
