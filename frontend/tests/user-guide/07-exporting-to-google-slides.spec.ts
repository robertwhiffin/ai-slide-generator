/**
 * User Guide: Exporting to Google Slides
 * 
 * This Playwright spec captures screenshots for the "Exporting to Google Slides" workflow.
 * Run with: npx playwright test user-guide/07-exporting-to-google-slides.spec.ts
 * 
 * The workflow covers:
 * 1. Admin page — uploading Google OAuth credentials
 * 2. Per-user authorization — authorizing with Google
 * 3. Exporting a deck — using the export dropdown in the slide panel
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToAdmin,
  goToGenerator
} from './shared';

async function setupGoogleSlidesMocks(
  page: import('@playwright/test').Page,
  options: { credentialsConfigured: boolean; authorized: boolean } = { credentialsConfigured: false, authorized: false }
): Promise<void> {
  const {
    mockGoogleCredentialsStatusConfigured,
    mockGoogleCredentialsStatusEmpty,
    mockGoogleAuthStatusAuthorized,
    mockGoogleAuthStatusUnauthorized,
    mockGoogleSlidesExportResponse,
  } = await import('../fixtures/mocks');

  await page.route('http://127.0.0.1:8000/api/admin/google-credentials/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        options.credentialsConfigured
          ? mockGoogleCredentialsStatusConfigured
          : mockGoogleCredentialsStatusEmpty
      ),
    });
  });

  await page.route('http://127.0.0.1:8000/api/admin/google-credentials', (route, request) => {
    if (request.method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
    } else if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    } else {
      route.continue();
    }
  });

  await page.route('http://127.0.0.1:8000/api/export/google-slides/auth/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        options.authorized
          ? mockGoogleAuthStatusAuthorized
          : mockGoogleAuthStatusUnauthorized
      ),
    });
  });

  await page.route('http://127.0.0.1:8000/api/export/google-slides/auth/url', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ url: 'https://accounts.google.com/o/oauth2/v2/auth?...' }),
    });
  });

  await page.route('http://127.0.0.1:8000/api/export/google-slides', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockGoogleSlidesExportResponse),
    });
  });

  // Mock feedback stats for the admin page Feedback tab
  await page.route('http://127.0.0.1:8000/api/feedback/report/stats**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ weeks: [], totals: { avg_star_rating: 0, avg_nps_score: 0, total_time_saved_minutes: 0, total_surveys: 0, total_feedback: 0 } }),
    });
  });

  await page.route('http://127.0.0.1:8000/api/feedback/conversations**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [], total: 0 }),
    });
  });
}

test.describe('User Guide: Exporting to Google Slides', () => {

  test.describe('Admin Setup', () => {
    test('capture credentials upload workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupGoogleSlidesMocks(page, { credentialsConfigured: false, authorized: false });
      const capture = new UserGuideCapture(page, '07-exporting-to-google-slides');

      // Step 01: Navigate to Admin page
      await page.goto('/admin');
      await page.waitForTimeout(500);
      await capture.capture({
        step: '01',
        name: 'admin-page',
        description: 'Open the Admin page — tabs provide access to Feedback and Google Slides settings',
      });

      // Step 02: Click Google Slides tab
      const googleTab = page.getByRole('tab', { name: 'Google Slides' });
      await googleTab.click();
      await page.waitForTimeout(300);
      await capture.capture({
        step: '02',
        name: 'google-slides-tab',
        description: 'The Google Slides tab shows credential status and authorization controls',
        highlightSelector: '#google-slides-tab',
      });

      // Step 03: Credentials upload area
      await capture.capture({
        step: '03',
        name: 'credentials-upload-area',
        description: 'Drag and drop your credentials.json file from Google Cloud Console',
        highlightSelector: 'text=Drop credentials.json here',
      });

      console.log('\n=== Generated Markdown for Admin Setup ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });

    test('capture credentials uploaded state', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupGoogleSlidesMocks(page, { credentialsConfigured: true, authorized: false });
      const capture = new UserGuideCapture(page, '07-exporting-to-google-slides');

      await page.goto('/admin');
      await page.waitForTimeout(500);

      // Switch to Google Slides tab
      await page.getByRole('tab', { name: 'Google Slides' }).click();
      await page.waitForTimeout(300);

      // Step 04: Credentials uploaded status
      await capture.capture({
        step: '04',
        name: 'credentials-uploaded',
        description: 'After uploading, the status confirms credentials are configured',
      });

      // Step 05: Authorize button
      await capture.capture({
        step: '05',
        name: 'authorize-button',
        description: 'Click "Authorize with Google" to link your Google account',
        highlightSelector: 'button:has-text("Authorize")',
      });

      console.log('\n=== Generated Markdown for Credentials Uploaded ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });

    test('capture authorized state', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupGoogleSlidesMocks(page, { credentialsConfigured: true, authorized: true });
      const capture = new UserGuideCapture(page, '07-exporting-to-google-slides');

      await page.goto('/admin');
      await page.waitForTimeout(500);

      // Switch to Google Slides tab
      await page.getByRole('tab', { name: 'Google Slides' }).click();
      await page.waitForTimeout(300);

      // Step 06: Authorized status
      await capture.capture({
        step: '06',
        name: 'authorized-status',
        description: 'After authorization, the status confirms your Google account is linked',
      });

      console.log('\n=== Generated Markdown for Authorized State ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });

  test.describe('Export Workflow', () => {
    test('capture export dropdown', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupGoogleSlidesMocks(page, { credentialsConfigured: true, authorized: true });
      const capture = new UserGuideCapture(page, '07-exporting-to-google-slides');

      // Mock slide deck so the export button is available
      const { mockSlides, createStreamingResponse } = await import('../fixtures/mocks');
      
      await page.route('http://127.0.0.1:8000/api/chat', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: createStreamingResponse(mockSlides),
        });
      });

      // Navigate to generator and generate slides
      await goToGenerator(page);

      const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
      await chatInput.fill('Create a presentation about cloud computing');
      await page.getByRole('button', { name: 'Send' }).click();
      await page.waitForTimeout(1500);

      // Step 07: Export dropdown
      const exportButton = page.getByRole('button', { name: /Export/i });
      if (await exportButton.isVisible({ timeout: 3000 })) {
        await exportButton.click();
        await page.waitForTimeout(300);

        await capture.capture({
          step: '07',
          name: 'export-dropdown',
          description: 'Click Export to see available export formats including Google Slides',
        });

        // Step 08: Google Slides option
        await capture.capture({
          step: '08',
          name: 'google-slides-option',
          description: 'Select "Export to Google Slides" to create an editable presentation',
          highlightSelector: 'text=Export to Google Slides',
        });
      } else {
        // Fallback: capture whatever state is visible
        await capture.capture({
          step: '07',
          name: 'export-dropdown',
          description: 'The Export button appears when slides have been generated',
        });
        await capture.capture({
          step: '08',
          name: 'google-slides-option',
          description: 'Select "Export to Google Slides" from the export menu',
        });
      }

      console.log('\n=== Generated Markdown for Export Workflow ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });
});
