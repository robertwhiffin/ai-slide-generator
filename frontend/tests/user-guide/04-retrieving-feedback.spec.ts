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

    // Step 01: Navigate to Admin page and open the Feedback tab.
    //
    // The Feedback tab used to be the default. The Usage tab (#214) now is
    // (`AdminPage.tsx`: useState<TabId>('usage')), so the guide has to select
    // Feedback explicitly — the comment here claimed a default that no longer
    // existed, and the capture below documents the Feedback dashboard.
    await page.goto('/admin');
    await page.getByRole('tab', { name: 'Feedback' }).click();
    await expect(page.getByRole('heading', { name: 'Feedback Dashboard' })).toBeVisible();
    // Wait for stats to load
    await page.waitForTimeout(500);
    await capture.capture({
      step: '01',
      name: 'admin-feedback-tab',
      // The generated prose must describe what the step ACTUALLY does. This claimed
      // the Feedback tab was selected by default; #214 made Usage the default
      // (`AdminPage.tsx`: useState<TabId>('usage')) and the step above now clicks
      // Feedback explicitly, so the sentence documented a behaviour the reader would
      // not see. ``description`` is the single source for both the ``### Step`` heading
      // and the image alt text in `shared.ts: generateMarkdown`.
      description: 'Open the Admin page and select the Feedback tab',
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

    // Step 04: AI Summary.
    //
    // #214 renamed this section to "AI Summary (optional)" and made it
    // collapsed-by-default (`FeedbackDashboard.tsx`: summaryOpen starts false),
    // so the guide must EXPAND it before capturing — under the old name it was
    // never found and the capture never happened.
    const summaryHeading = page.getByRole('heading', { name: 'AI Summary (optional)' });
    await summaryHeading.scrollIntoViewIfNeeded();
    await summaryHeading.click();
    await page.waitForTimeout(300);
    await capture.capture({
      step: '04',
      name: 'ai-summary',
      description: 'The optional AI Summary analyses recent feedback and highlights top themes and category breakdown',
      highlightSelector: 'text=AI Summary (optional)',
    });

    console.log('\n=== Generated Markdown for Retrieving Feedback ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
