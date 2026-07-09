import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import {
  mockDesignSystems,
  mockDefaultAgentConfig,
  mockDesignSystemDetail,
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

  test('DS + template pin SURVIVE a generation (session-scoped sticky)', async ({ page }) => {
    // Selections are SESSION-SCOPED STICKY: within a session they persist
    // across every prompt/generation until the user changes them manually —
    // there is no after-generation reset.
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
      title: 'Sticky Pin Deck',
      slides: [{ slide_id: 's1', html: '<h1>One</h1>', scripts: '', verification: null }],
      css: '',
      external_scripts: [],
    };
    let completedGenerations = 0;
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
      completedGenerations += 1;
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
    await expect.poll(() => completedGenerations).toBeGreaterThan(0);
    await expect(page.getByText('Sticky Pin Deck').first()).toBeVisible({ timeout: 10000 }).catch(() => {
      /* deck title rendering is not what this test asserts */
    });

    // Both selections SURVIVE: still pinned, no PUT ever cleared them.
    await expect(templateSelector).toHaveValue('1');
    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(dsId));
    expect(configPuts.filter((c) => c.template_id === null)).toEqual([]);
  });

  test('a NEW session always starts with template = None (design system carries over)', async ({ page }) => {
    // template_id is session-scoped state: cross-session stores (the
    // pre-session localStorage mirror, profiles) never carry it, and a fresh
    // session's config load strips any in-memory leftovers. Design-system
    // defaulting is unchanged.
    const dsId = mockDesignSystems.design_systems[0].id;

    // Simulate a stale cross-session store from before the rule existed.
    await page.addInitScript(
      ([key, value]) => localStorage.setItem(key, value),
      [
        'pendingAgentConfig',
        JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: dsId,
          template_id: 1,
        }),
      ] as [string, string],
    );

    // Fresh session: its agent-config is not persisted yet (local-uuid 404).
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Session not found' }) });
        return;
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });

    await expandAgentConfig(page);

    // DS selection carried over; the template pin did NOT.
    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(dsId));
    await expect(page.getByTestId('template-selector')).toHaveValue('');
  });

  test('RACE: switching sessions never sends the previous session template pin (delayed config load)', async ({ page }) => {
    // codex-reported race: entering a fresh session, the in-memory config
    // still holds the PREVIOUS session's pin until the new session's
    // agent-config GET resolves; a chat sent in that window used to carry —
    // and server-side persist — the stale pin. The context now strips
    // session-scoped state synchronously on session change.
    const dsId = mockDesignSystems.design_systems[0].id;
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd'; // mockSessions[1]
    await mockSessionWithSlides(page, SESSION_B);

    // Agent-config: session A answers instantly WITH a pin; any other
    // session's GET is DELAYED past the chat send (the race window).
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
      const url = request.url();
      const isA = url.includes(TEST_SESSION_ID);
      if (request.method() === 'GET') {
        if (!isA) await new Promise((r) => setTimeout(r, 2000));
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockDefaultAgentConfig,
            design_system_id: dsId,
            template_id: isA ? 1 : null,
          }),
        });
        return;
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
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

    const streamBodies: string[] = [];
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route, request) => {
      streamBodies.push(request.postData() ?? '');
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type": "complete", "message": "done", "slides": {"title": "d", "slides": [], "css": "", "external_scripts": []}}\n\n',
      });
    });

    // Session A: pin loaded and visible.
    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    // Client-side switch to session B via the sidebar (SPA navigation keeps
    // the provider — and its in-memory config — mounted).
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // Send inside B's delayed config-load window (well before the 2s GET).
    const chatInput = page.getByTestId('chat-input');
    await expect(chatInput).toBeEnabled();
    await page.waitForTimeout(300); // let the switch's re-renders settle
    await chatInput.fill('First prompt in the new session');
    await expect(chatInput).toHaveValue('First prompt in the new session');
    await chatInput.press('Enter');

    await expect.poll(() => streamBodies.length).toBeGreaterThan(0);
    const sentConfig = JSON.parse(streamBodies[0]).agent_config;
    // The previous session's pin must NOT ride along…
    expect(sentConfig.template_id).toBe(null);
    // …while the design system still carries over.
    expect(sentConfig.design_system_id).toBe(dsId);
  });

  test('a template picked IN a fresh session before the first prompt still applies', async ({ page }) => {
    // Legit flow guard for the race fix: pinning inside the new session
    // (before any prompt) persists and rides on the chat request.
    const dsId = mockDesignSystems.design_systems[0].id;

    const configPuts: Record<string, unknown>[] = [];
    let serverConfig: Record<string, unknown> = {
      ...mockDefaultAgentConfig,
      design_system_id: dsId,
      template_id: null,
    };
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route, request) => {
      if (request.method() === 'PUT') {
        serverConfig = JSON.parse(request.postData() ?? '{}');
        configPuts.push(serverConfig);
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(serverConfig) });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
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
    const streamBodies: string[] = [];
    await page.route('http://127.0.0.1:8000/api/chat/stream', (route, request) => {
      streamBodies.push(request.postData() ?? '');
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type": "complete", "message": "done", "slides": {"title": "d", "slides": [], "css": "", "external_scripts": []}}\n\n',
      });
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('');

    // Pin a template IN this session, before the first prompt.
    await page.getByTestId('template-selector').selectOption('2');
    await expect.poll(() => configPuts.length).toBeGreaterThan(0);
    expect(configPuts[configPuts.length - 1].template_id).toBe(2);

    const chatInput = page.getByTestId('chat-input');
    await chatInput.fill('First prompt');
    await chatInput.press('Enter');

    await expect.poll(() => streamBodies.length).toBeGreaterThan(0);
    const sentConfig = JSON.parse(streamBodies[0]).agent_config;
    expect(sentConfig.template_id).toBe(2);
    expect(sentConfig.design_system_id).toBe(dsId);
  });

  test('Use from the detail panel affects only the current session config', async ({ page }) => {
    // Using a template from the design-system library (a non-session route)
    // must not write into any existing session's config, and the
    // cross-session localStorage mirror never keeps the template part.
    const dsId = mockDesignSystems.design_systems[0].id;

    const sessionConfigPuts: string[] = [];
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/agent-config`, (route, request) => {
      if (request.method() === 'PUT') sessionConfigPuts.push(request.postData() ?? '');
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+$/, (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemDetail) });
        return;
      }
      route.continue();
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/files$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [], total: 0 }) });
    });
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, name: 'Acme Content', layout_html: '<section></section>', token_css: null }) });
    });

    // Pick a template from the library page (no active session in the URL).
    await page.goto('/design-systems');
    await page.locator('[data-testid="design-system-card"]').filter({ hasText: 'Acme Design System' }).click();
    await expect(page.getByTestId('design-system-detail')).toBeVisible();
    await page.getByTestId('use-template-button').first().click();

    // No session config was touched…
    expect(sessionConfigPuts).toEqual([]);
    // …and the cross-session mirror keeps the design system but never the pin.
    await expect
      .poll(async () => {
        const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
        return raw ? JSON.parse(raw) : null;
      })
      .toMatchObject({ design_system_id: dsId, template_id: null });
  });
});
