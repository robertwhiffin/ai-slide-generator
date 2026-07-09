import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import {
  mockDesignSystems,
  mockDefaultAgentConfig,
  mockDesignSystemTemplatesWithLive,
} from '../fixtures/mocks';

/**
 * Design System selector in the AgentConfigBar — Phase 4.
 *
 * Verifies that choosing a design system sets `agentConfig.design_system_id`
 * (Phase-2 precedence: design_system_id -> slide_style_id -> default), while the
 * existing slide-style selector keeps working (backward compatible).
 *
 * Uses an active session so the config PUT can be captured and asserted.
 */

async function expandAgentConfig(page: import('@playwright/test').Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('agent-config-bar')).toBeVisible();
  await page.getByTestId('agent-config-toggle').click();
  await expect(page.getByTestId('design-system-selector')).toBeVisible();
}

test.describe('AgentConfigBar — design system selector', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
    // Populated design-systems list (registered after shared mocks → wins).
    await page.route(/\/api\/settings\/design-systems(\?[^/]*)?$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystems) });
      } else {
        route.continue();
      }
    });
  });

  test('choosing a design system sets design_system_id in the config PUT', async ({ page }) => {
    let capturedConfig: Record<string, unknown> | null = null;
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route) => {
      if (route.request().method() === 'PUT') {
        capturedConfig = JSON.parse(route.request().postData() ?? '{}');
        route.fulfill({ status: 200, contentType: 'application/json', body: route.request().postData() ?? '{}' });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
      }
    });

    await expandAgentConfig(page);

    await page.getByTestId('design-system-selector').selectOption(String(mockDesignSystems.design_systems[0].id));

    await expect.poll(() => capturedConfig?.design_system_id).toBe(mockDesignSystems.design_systems[0].id);
  });

  test('the design-system selector lists systems from the API', async ({ page }) => {
    await expandAgentConfig(page);
    const selector = page.getByTestId('design-system-selector');
    await expect(selector.locator('option', { hasText: 'Acme Design System' })).toHaveCount(1);
    await expect(selector.locator('option', { hasText: 'Nimbus Theme' })).toHaveCount(1);
  });

  test('the existing slide-style selector still works (backward compatible)', async ({ page }) => {
    await expandAgentConfig(page);
    // The legacy slide-style selector is still present and populated.
    const styleSelector = page.getByTestId('style-selector');
    await expect(styleSelector).toBeVisible();
    await expect(styleSelector.locator('option', { hasText: 'Corporate Theme' })).toHaveCount(1);
  });

  test('template pin resets to None after a generation; design system stays sticky', async ({ page }) => {
    // Template selection is a PER-GENERATION choice (Claude Design behavior):
    // completing a slide generation consumes the pin, while the design-system
    // selection persists.
    const dsId = mockDesignSystems.design_systems[0].id;

    // Stateful agent-config: starts with a pinned template; PUTs update it.
    let serverConfig: Record<string, unknown> = {
      ...mockDefaultAgentConfig,
      design_system_id: dsId,
      template_id: 1,
    };
    const configPuts: Record<string, unknown>[] = [];
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route) => {
      if (route.request().method() === 'PUT') {
        serverConfig = JSON.parse(route.request().postData() ?? '{}');
        configPuts.push(serverConfig);
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(serverConfig) });
    });

    // Templates of the selected design system (so the Template select renders).
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });

    // Editing lock + current user, so the chat input is enabled.
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else if (request.method() === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ released: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    // A generation stream that completes WITH slides.
    const deck = {
      title: 'Pin Reset Deck',
      slides: [{ slide_id: 's1', html: '<h1>One</h1>', scripts: '', verification: null }],
      css: '',
      external_scripts: [],
    };
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'data: {"type": "start", "message": "Starting slide generation..."}\n\n' +
          `data: {"type": "complete", "message": "Generation complete", "slides": ${JSON.stringify(deck)}}\n\n`,
      });
    });

    await expandAgentConfig(page);

    // Pinned template is showing.
    const templateSelector = page.getByTestId('template-selector');
    await expect(templateSelector).toBeVisible();
    await expect(templateSelector).toHaveValue('1');

    // Run a generation.
    await page.getByTestId('chat-input').fill('Create a deck');
    await page.getByTestId('chat-input').press('Enter');

    // The pin resets to None...
    await expect(templateSelector).toHaveValue('');
    // ...via a persisted config update that keeps the design system.
    await expect.poll(() => configPuts.length).toBeGreaterThan(0);
    const lastPut = configPuts[configPuts.length - 1];
    expect(lastPut.template_id).toBe(null);
    expect(lastPut.design_system_id).toBe(dsId);
    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(dsId));
  });
});
