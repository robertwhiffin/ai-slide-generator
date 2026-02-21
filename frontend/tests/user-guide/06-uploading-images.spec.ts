/**
 * User Guide: Uploading Images
 * 
 * This Playwright spec captures screenshots for the "Uploading Images" workflow.
 * Run with: npx playwright test user-guide/06-uploading-images.spec.ts
 * 
 * The workflow covers:
 * 1. The Image Library — browsing, uploading, filtering, and editing images
 * 2. Paste-to-chat — attaching images directly in the chat input
 * 3. Image Guidelines — configuring automatic image placement in slide styles
 */

import { test, expect } from '@playwright/test';
import { 
  UserGuideCapture, 
  setupUserGuideMocks, 
  goToImageLibrary,
  goToGenerator,
  goToSlideStyles
} from './shared';

async function setupImageMocks(page: import('@playwright/test').Page): Promise<void> {
  const { 
    mockImageListResponse, 
    mockImageUploadResponse 
  } = await import('../fixtures/mocks');

  await page.route('http://127.0.0.1:8000/api/images', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockImageListResponse)
      });
    } else {
      route.continue();
    }
  });

  await page.route('http://127.0.0.1:8000/api/images/upload', (route) => {
    route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(mockImageUploadResponse)
    });
  });

  await page.route('http://127.0.0.1:8000/api/images/*/data', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 1,
        base64_data: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
      })
    });
  });
}

test.describe('User Guide: Uploading Images', () => {

  test.describe('Image Library', () => {
    test('capture image library workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupImageMocks(page);
      const capture = new UserGuideCapture(page, '06-uploading-images');

      // Step 01: Navigate to Image Library (shared goToImageLibrary uses /images)
      await goToImageLibrary(page);
      await page.waitForTimeout(500);
      await capture.capture({
        step: '01',
        name: 'image-library-page',
        description: 'Open the Image Library from the sidebar or URL',
        highlightSelector: 'button:has-text("Images")',
      });

      // Step 02: Upload area
      await capture.capture({
        step: '02',
        name: 'upload-area',
        description: 'Drag and drop files onto the upload area, or click browse to select files',
        highlightSelector: '[data-testid="image-library"] >> text=Drop images here',
      });

      // Step 03: Category filter
      await capture.capture({
        step: '03',
        name: 'category-filter',
        description: 'Filter images by category: branding, content, or background',
        highlightSelector: 'button:has-text("branding")',
      });

      // Step 04: Image card details — click on an image if visible
      const imageCard = page.locator('[data-testid="image-library"]').locator('img').first();
      if (await imageCard.isVisible({ timeout: 2000 })) {
        await imageCard.click();
        await page.waitForTimeout(300);
      }
      await capture.capture({
        step: '04',
        name: 'image-card-details',
        description: 'Click an image to view its metadata — tags, description, and category',
      });

      console.log('\n=== Generated Markdown for Image Library ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });

  test.describe('Paste-to-Chat', () => {
    test('capture paste-to-chat workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupImageMocks(page);
      const capture = new UserGuideCapture(page, '06-uploading-images');

      // Navigate to generator
      await goToGenerator(page);

      // Step 05: Simulate a pasted image by uploading via the mock
      // Trigger the paste handler by evaluating clipboard paste with an image
      const chatInput = page.getByRole('textbox');
      await chatInput.click();

      // Simulate paste event with an image blob
      await page.evaluate(() => {
        const canvas = document.createElement('canvas');
        canvas.width = 100;
        canvas.height = 100;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.fillStyle = '#4285f4';
          ctx.fillRect(0, 0, 100, 100);
        }
        canvas.toBlob((blob) => {
          if (!blob) return;
          const file = new File([blob], 'pasted-image.png', { type: 'image/png' });
          const dt = new DataTransfer();
          dt.items.add(file);
          const pasteEvent = new ClipboardEvent('paste', {
            clipboardData: dt,
            bubbles: true,
            cancelable: true,
          });
          const textarea = document.querySelector('textarea');
          textarea?.dispatchEvent(pasteEvent);
        }, 'image/png');
      });

      await page.waitForTimeout(1000);

      await capture.capture({
        step: '05',
        name: 'chat-input-paste',
        description: 'Paste an image into the chat input — it uploads and appears as an attachment',
      });

      // Step 06: Save to library toggle
      await capture.capture({
        step: '06',
        name: 'save-to-library-toggle',
        description: 'The "Save to library" checkbox controls whether pasted images persist in the library',
        highlightSelector: 'text=Save to library',
      });

      console.log('\n=== Generated Markdown for Paste-to-Chat ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });

  test.describe('Image Guidelines', () => {
    test('capture image guidelines workflow', async ({ page }) => {
      await setupUserGuideMocks(page);
      await setupImageMocks(page);
      const capture = new UserGuideCapture(page, '06-uploading-images');

      // Navigate to Slide Styles
      await goToSlideStyles(page);

      // Open the Create Style modal to access Image Guidelines
      await page.getByRole('button', { name: 'New Style' }).click();
      await expect(page.getByRole('heading', { name: 'Create Slide Style' })).toBeVisible();
      await page.waitForTimeout(300);

      // Step 07: Image Guidelines editor
      await capture.capture({
        step: '07',
        name: 'image-guidelines-editor',
        description: 'The Image Guidelines section in the style editor lets you specify automatic image placement',
        highlightSelector: 'text=Image Guidelines',
      });

      // Step 08: Insert Image Ref button
      await capture.capture({
        step: '08',
        name: 'insert-image-ref-button',
        description: 'Click "Insert Image Ref" to browse the library and insert an image reference',
        highlightSelector: 'button:has-text("Insert Image Ref")',
      });

      console.log('\n=== Generated Markdown for Image Guidelines ===\n');
      console.log(capture.generateMarkdown());
      console.log('\n=== End of Markdown ===\n');
    });
  });
});
