import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import {
  mockDesignSystems,
  mockDefaultAgentConfig,
  mockDesignSystemDetail,
  mockDesignSystemTemplatesWithLive,
  mockSessions,
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
    await page.route(apiPath('/api/settings/design-systems'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystems) });
      } else {
        route.continue();
      }
    });
  });

  test('choosing a design system sets design_system_id in the config PUT', async ({ page }) => {
    let capturedConfig: Record<string, unknown> | null = null;
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route) => {
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
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route) => {
      if (route.request().method() === 'PUT') {
        serverConfig = JSON.parse(route.request().postData() ?? '{}');
        configPuts.push(serverConfig);
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(serverConfig) });
    });

    // Templates of the selected design system (so the Template select renders).
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });

    // Editing lock + current user, so the chat input is enabled.
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
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
    await page.route(apiPath('/api/chat/stream'), (route) => {
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
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Session not found' }) });
        return;
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });

    await expandAgentConfig(page);

    // DS selection carried over; the template pin did NOT.
    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(dsId));
    await expect(page.getByTestId('template-selector')).toHaveValue('');
  });

  test('RACE: a send during a pending config load carries NO config; the existing session keeps its own (codex repro)', async ({ page }) => {
    // codex repro: A {ds:1, tpl:1}; B an EXISTING session with its own
    // persisted {ds:2, tpl:2}; switch A->B with B's agent-config GET
    // delayed; send immediately. The request must not carry ANY of A's
    // config (ownership: config rides only for the session it was
    // loaded-for/edited-in) — otherwise the backend sync would overwrite
    // B's persisted config with A's leftovers.
    const dsA = mockDesignSystems.design_systems[0].id; // 1
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd'; // mockSessions[1]
    await mockSessionWithSlides(page, SESSION_B);

    const configPutBodies: string[] = [];
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isA = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        configPutBodies.push(request.postData() ?? '');
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      if (!isA) await new Promise((r) => setTimeout(r, 2000));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: isA ? dsA : 2,
          template_id: isA ? 1 : 2,
        }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else if (request.method() === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ released: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    const streamBodies: string[] = [];
    await page.route(apiPath('/api/chat/stream'), (route, request) => {
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

    // Client-side switch to session B via the sidebar.
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
    const sentBody = JSON.parse(streamBodies[0]);
    // No config that wasn't loaded-for/edited-in B may ride the request.
    expect(sentBody.agent_config ?? null).toBe(null);
    // No PUT ever pushed A's config onto B either.
    for (const put of configPutBodies) {
      expect(JSON.parse(put).design_system_id).not.toBe(dsA);
    }

    // Once B's own config lands, B still shows ITS persisted values.
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2', { timeout: 5000 });
    await expect(page.getByTestId('template-selector')).toHaveValue('2');
  });

  test('rapid double-switch A->B->C: sends stay config-free and C wins the late GETs', async ({ page }) => {
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    const SESSION_C = 'c3d6e2f0-1234-4abc-9def-0123456789ab';
    await mockSessionWithSlides(page, SESSION_B);
    await mockSessionWithSlides(page, SESSION_C);

    // Sidebar needs all three sessions.
    await page.route(apiPath('/api/sessions'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            ...mockSessions.sessions,
            {
              ...mockSessions.sessions[1],
              session_id: SESSION_C,
              title: 'Session C fixture',
            },
          ],
          count: 3,
        }),
      });
    });

    // A instant {ds:1,tpl:1}; B delayed 3s {ds:2,tpl:2}; C delayed 1s {ds:2,tpl:null}.
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      if (request.method() !== 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      const url = request.url();
      let delay = 0;
      let ds: number | null = 1;
      let tpl: number | null = 1;
      if (url.includes(SESSION_B)) { delay = 3000; ds = 2; tpl = 2; }
      else if (url.includes(SESSION_C)) { delay = 1000; ds = 2; tpl = null; }
      if (delay) await new Promise((r) => setTimeout(r, delay));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: ds, template_id: tpl }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else if (request.method() === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ released: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });
    const streamBodies: string[] = [];
    await page.route(apiPath('/api/chat/stream'), (route, request) => {
      streamBodies.push(request.postData() ?? '');
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type": "complete", "message": "done", "slides": {"title": "d", "slides": [], "css": "", "external_scripts": []}}\n\n',
      });
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    // A -> B -> C in quick succession.
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    await page.getByText('Session C fixture').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_C}/edit`));

    const chatInput = page.getByTestId('chat-input');
    await expect(chatInput).toBeEnabled();
    await page.waitForTimeout(300);
    await chatInput.fill('Prompt on C');
    await expect(chatInput).toHaveValue('Prompt on C');
    await chatInput.press('Enter');

    await expect.poll(() => streamBodies.length).toBeGreaterThan(0);
    expect(JSON.parse(streamBodies[0]).agent_config ?? null).toBe(null);

    // C's GET (1s) lands: C's config shows. B's slower GET (3s) must NOT
    // clobber it after the fact.
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2', { timeout: 5000 });
    await expect(page.getByTestId('template-selector')).toHaveValue('');
    await page.waitForTimeout(2500); // B's late response has now arrived (and been discarded)
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2');
    await expect(page.getByTestId('template-selector')).toHaveValue('');
  });

  test('FAILED edit mid-load restores the session OWN snapshot, never foreign residue (codex repro)', async ({ page }) => {
    // A loaded {ds:1,tpl:1} -> switch to existing B {ds:2,tpl:2} (GET
    // delayed) -> explicit edit in B claims ownership -> B's GET resolves
    // mid-PUT (discarded for display, STASHED as B's own state) -> the PUT
    // FAILS. The revert target must be B's stashed snapshot — never the
    // pre-edit in-memory values, which are A's. And the NEXT edit in B must
    // PUT B-based values.
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    await mockSessionWithSlides(page, SESSION_B);

    const configPutBodies: string[] = [];
    let putCount = 0;
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isA = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        putCount += 1;
        configPutBodies.push(request.postData() ?? '');
        if (putCount === 1) {
          // First edit's PUT: slow enough for B's GET to land mid-flight,
          // then FAIL.
          await new Promise((r) => setTimeout(r, 1500));
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'sync failed' }) });
          return;
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      if (!isA) await new Promise((r) => setTimeout(r, 1200));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: isA ? 1 : 2,
          template_id: isA ? 1 : 2,
        }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // Explicit edit in B inside the pending window (PUT will fail at ~1.8s;
    // B's GET lands at ~1.2s, mid-PUT).
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption('');

    // After the failure: B shows B's OWN persisted config, not A's.
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2', { timeout: 5000 });
    await expect(page.getByTestId('template-selector')).toHaveValue('2');

    // And the NEXT edit in B builds on B's values on the wire.
    await page.getByTestId('template-selector').selectOption('1');
    await expect.poll(() => configPutBodies.length).toBeGreaterThan(1);
    const secondPut = JSON.parse(configPutBodies[configPutBodies.length - 1]);
    expect(secondPut.design_system_id).toBe(2); // B-based, never A's ds:1
    expect(secondPut.template_id).toBe(1);
  });

  test('FAILED edit before any session snapshot falls back to defaults + re-fetch, never foreign values', async ({ page }) => {
    // Variant: the edit's PUT fails BEFORE B's config ever resolved — there
    // is no B snapshot to restore. The revert must not resurrect A's
    // values: defaults with no owner, then the session's real config lands.
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    await mockSessionWithSlides(page, SESSION_B);

    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isA = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        await new Promise((r) => setTimeout(r, 300));
        route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'sync failed' }) });
        return;
      }
      if (!isA) await new Promise((r) => setTimeout(r, 3000));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: isA ? 1 : 2,
          template_id: isA ? 1 : 2,
        }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // Edit fails at ~0.6s; B's GET is still 2.4s away — no snapshot exists.
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption('');

    // Right after the failure: NEVER A's values — defaults instead.
    await page.waitForTimeout(700);
    await expect(page.getByTestId('design-system-selector')).not.toHaveValue('1');
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');

    // Eventually B's real config lands (original delayed GET / re-fetch).
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2', { timeout: 6000 });
    await expect(page.getByTestId('template-selector')).toHaveValue('2');
  });

  test('a FAILED B PUT settling while on C never touches C (settle invariant, codex repro)', async ({ page }) => {
    // A loaded -> edit B while B's GET/PUT are in flight (B's GET stashes
    // {ds:2,tpl:2}) -> switch to C BEFORE B's PUT fails -> B's catch settles
    // from its stale closure while the UI is on C. It must not mutate C's
    // visible state or ownership; C's next explicit edit PUTs C-based
    // values.
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    const SESSION_C = 'c3d6e2f0-1234-4abc-9def-0123456789ab';
    await mockSessionWithSlides(page, SESSION_B);
    await mockSessionWithSlides(page, SESSION_C);
    await page.route(apiPath('/api/sessions'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            ...mockSessions.sessions,
            { ...mockSessions.sessions[1], session_id: SESSION_C, title: 'Session C fixture' },
          ],
          count: 3,
        }),
      });
    });

    const putBodies: { url: string; body: string }[] = [];
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const url = request.url();
      if (request.method() === 'PUT') {
        putBodies.push({ url, body: request.postData() ?? '' });
        if (url.includes(SESSION_B)) {
          // B's edit PUT: hold long enough for the user to be on C, then FAIL.
          await new Promise((r) => setTimeout(r, 2500));
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'sync failed' }) });
          return;
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      let ds: number | null = 1;
      let tpl: number | null = 1;
      let delay = 0;
      if (url.includes(SESSION_B)) { ds = 2; tpl = 2; delay = 800; }
      // C's GET is held open for the whole test: the failure must settle,
      // AND be observed, while C has no loaded config of its own (codex's
      // exact ordering). If C's GET were allowed to land it would correct
      // the poisoned state and mask the bug.
      else if (url.includes(SESSION_C)) { ds = null; tpl = null; delay = 30000; }
      if (delay) await new Promise((r) => setTimeout(r, delay));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: ds, template_id: tpl }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    // -> B; edit inside B's pending window (B GET lands ~0.8s and stashes
    // {ds:2,tpl:2}; B's PUT will fail at ~2.9s).
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption('');

    // -> C BEFORE B's PUT settles; C's own GET is still 4s out.
    await page.waitForTimeout(700);
    await page.getByText('Session C fixture').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_C}/edit`));

    // B's PUT failure settles ~1.8s after the switch, while C's GET is
    // still held open. On C the screen must NOT paint B's stashed
    // {ds:2,tpl:2}; C keeps the stripped carry-over ({ds:null}, since B's
    // last visible edit set None). Assert IN this window — before any
    // (here: never) C GET could mask it.
    await page.waitForTimeout(2200);
    await expect(page.getByTestId('design-system-selector')).not.toHaveValue('2');
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    // No DS visible -> no template control (pre-fix it appears with '2').
    await expect(page.getByTestId('template-selector')).toHaveCount(0);

    // Wire discriminator: a style edit PRESERVES the base config, so its
    // PUT body reveals whether the base was poisoned. Post-fix ds is null
    // (C's own stripped state); pre-fix it is B's residual 2.
    await page.getByTestId('style-selector').selectOption('2');
    await expect
      .poll(() => putBodies.filter((p) => p.url.includes(SESSION_C)).length)
      .toBeGreaterThan(0);
    const cPut = JSON.parse(putBodies.filter((p) => p.url.includes(SESSION_C)).pop()!.body);
    expect(cPut.design_system_id).toBe(null); // no B residue (B's ds was 2)
    expect(cPut.template_id).toBe(null);      // no B residue (B's tpl was 2)
    expect(cPut.slide_style_id).toBe(2);      // the explicit edit
  });

  test('a late-settling SUCCESSFUL B PUT updates only B stash — never the C screen', async ({ page }) => {
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    const SESSION_C = 'c3d6e2f0-1234-4abc-9def-0123456789ab';
    await mockSessionWithSlides(page, SESSION_B);
    await mockSessionWithSlides(page, SESSION_C);
    await page.route(apiPath('/api/sessions'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            ...mockSessions.sessions,
            { ...mockSessions.sessions[1], session_id: SESSION_C, title: 'Session C fixture' },
          ],
          count: 3,
        }),
      });
    });

    let bGetCount = 0;
    let bPutCount = 0;
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const url = request.url();
      if (request.method() === 'PUT') {
        if (url.includes(SESSION_B)) {
          bPutCount += 1;
          if (bPutCount === 1) {
            // First B PUT: SUCCEEDS, but only after the user is on C.
            await new Promise((r) => setTimeout(r, 2500));
            route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
            return;
          }
          // Second B PUT (after returning to B): fails fast — the revert
          // target must be B's stash, which the late confirm updated.
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'sync failed' }) });
          return;
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      let ds: number | null = 1;
      let tpl: number | null = 1;
      let delay = 0;
      if (url.includes(SESSION_B)) {
        bGetCount += 1;
        ds = 2; tpl = 2;
        delay = bGetCount === 1 ? 800 : 3000; // slow on the return visit
      } else if (url.includes(SESSION_C)) { ds = null; tpl = null; delay = 800; }
      if (delay) await new Promise((r) => setTimeout(r, delay));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: ds, template_id: tpl }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    // -> B; edit (DS -> 1, visibly distinct from both B's {ds:2} and C's
    // {ds:null}) whose PUT confirms late.
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption('1');

    // -> C before the confirm settles.
    await page.waitForTimeout(700);
    await page.getByText('Session C fixture').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_C}/edit`));
    await expect(page.getByTestId('design-system-selector')).toHaveValue('', { timeout: 5000 });

    // B's PUT confirms {ds:1} (~2.9s) while on C: C's screen must not
    // repaint with it — it stays C's own {ds:null}.
    await page.waitForTimeout(2200);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');

    // Return to B (its GET is now slow): a fast-failing edit reverts to B's
    // stash — which the late confirm updated to {ds:1} — NOT B's server
    // snapshot {ds:2}. That observable difference proves the keyed stash
    // took the late confirm.
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    await page.waitForTimeout(300);
    await page.getByTestId('style-selector').selectOption('2'); // any explicit edit
    await page.waitForTimeout(800); // second B PUT fails fast -> stash revert
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');
  });

  test('interleaved switches with delayed settles only ever show the current session values', async ({ page }) => {
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    await mockSessionWithSlides(page, SESSION_B);

    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isA = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      if (!isA) await new Promise((r) => setTimeout(r, 700));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: isA ? 1 : 2,
          template_id: isA ? 1 : 2,
        }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // Two quick A->B->A cycles: B's delayed GETs keep settling while back on
    // A and must never repaint A with B's values.
    for (let i = 0; i < 2; i++) {
      await page.getByText('Session 2026-01-08 20:20').first().click();
      await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
      await page.waitForTimeout(150); // leave before B's 700ms GET settles
      await page.getByText('Session 2026-01-08 20:38').first().click();
      await page.waitForURL(new RegExp(`/sessions/${TEST_SESSION_ID}/edit`));
      // A resolves instantly; B's stale GET lands ~550ms later and must be
      // discarded: A keeps showing A.
      await expect(page.getByTestId('design-system-selector')).toHaveValue('1', { timeout: 3000 });
      await page.waitForTimeout(900);
      await expect(page.getByTestId('design-system-selector')).toHaveValue('1');
      await expect(page.getByTestId('template-selector')).toHaveValue('1');
    }

    // Settle on B for real: B's own values arrive.
    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    await expect(page.getByTestId('design-system-selector')).toHaveValue('2', { timeout: 5000 });
    await expect(page.getByTestId('template-selector')).toHaveValue('2');
  });

  test('a stale same-session GET settling after a successful PUT does not regress the stash (codex repro)', async ({ page }) => {
    // B's GET is issued early but returns OLD server state {ds:2,tpl:2} and
    // is DELAYED. The user edits B and the edit PUT succeeds FIRST, stashing
    // {ds:1,tpl:null}. The old GET then settles: repaint is display-guarded
    // (owner=B), but its stash write must ALSO be rejected as outdated —
    // otherwise a later failed edit reverts to the stale {ds:2,tpl:2}.
    const dsB = 1; // the value the successful edit sets
    const putBodies: string[] = [];
    let bPutCount = 0;
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isB = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        putBodies.push(request.postData() ?? '');
        if (isB) {
          bPutCount += 1;
          if (bPutCount === 1) {
            // The successful edit — confirms promptly (before the slow GET).
            route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
            return;
          }
          // A LATER edit that FAILS — its revert reveals what the stash holds.
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'sync failed' }) });
          return;
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      // B's GET: OLD state, DELAYED so it lands after the first PUT confirms.
      await new Promise((r) => setTimeout(r, 1500));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: 2, template_id: 2 }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    // Land on session A (=TEST_SESSION_ID here) with its GET in flight.
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await expect(page.getByTestId('design-system-selector')).toBeVisible();

    // Edit BEFORE the slow GET lands: set DS to 1 (distinct from the GET's
    // stale 2). This edit's PUT confirms first and stashes {ds:1,tpl:null}.
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption(String(dsB));
    await expect.poll(() => putBodies.length).toBeGreaterThan(0);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // Let the stale OLD GET ({ds:2}) settle (issued before the PUT → lower
    // generation → stash write rejected). Screen stays {ds:1}.
    await page.waitForTimeout(1600);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // Now a SECOND edit whose PUT FAILS — the revert must land on the
    // post-PUT {ds:1}, NOT the stale GET's {ds:2}.
    //
    // The probe is the DECK PROMPT selector, not the slide style: a style and a
    // design system are now mutually exclusive, so editing the style would
    // legitimately clear design_system_id and this assertion could no longer
    // distinguish "stash regressed to the stale GET" from "exclusivity did its
    // job". The deck prompt is orthogonal to the style slot, so it still probes
    // exactly what this test is about.
    await page.getByTestId('deck-prompt-selector').selectOption('2');
    await page.waitForTimeout(500);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // And the next edit's wire body builds from {ds:1}, never {ds:2}.
    await page.getByTestId('deck-prompt-selector').selectOption('1');
    await expect.poll(() => putBodies.length).toBeGreaterThan(2);
    const lastPut = JSON.parse(putBodies[putBodies.length - 1]);
    expect(lastPut.design_system_id).toBe(1); // post-PUT truth, not stale 2
  });

  test('B->C->B: a pre-round-trip stale B GET settling after return cannot regress B (generation)', async ({ page }) => {
    const SESSION_C = 'c3d6e2f0-1234-4abc-9def-0123456789ab';
    await mockSessionWithSlides(page, SESSION_C);
    await page.route(apiPath('/api/sessions'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            ...mockSessions.sessions,
            { ...mockSessions.sessions[1], session_id: SESSION_C, title: 'Session C fixture' },
          ],
          count: 3,
        }),
      });
    });

    const putBodies: { url: string; body: string }[] = [];
    let bGetCount = 0;
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const url = request.url();
      const isB = url.includes(TEST_SESSION_ID);
      const isC = url.includes(SESSION_C);
      if (request.method() === 'PUT') {
        putBodies.push({ url, body: request.postData() ?? '' });
        if (isB) {
          // Every B edit FAILS so its revert reads (and thus reveals) B's
          // stash — the observable that proves the stale GET was rejected.
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'fail' }) });
          return;
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      if (isB) {
        bGetCount += 1;
        // The FIRST B GET (before the round trip) is very slow AND stale
        // ({ds:2}); the second (on return) is prompt ({ds:1}).
        if (bGetCount === 1) {
          await new Promise((r) => setTimeout(r, 2000));
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: 2, template_id: 2 }) });
          return;
        }
        await new Promise((r) => setTimeout(r, 300));
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: 1, template_id: 1 }) });
        return;
      }
      if (isC) {
        await new Promise((r) => setTimeout(r, 300));
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: null, template_id: null }) });
        return;
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    // Start on B; its first GET is 4s out (stale {ds:2}).
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    // B -> C -> B quickly (each new GET bumps B's generation on return).
    await page.getByText('Session C fixture').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_C}/edit`));
    await page.getByText('Session 2026-01-08 20:38').first().click();
    await page.waitForURL(new RegExp(`/sessions/${TEST_SESSION_ID}/edit`));

    // On return, B's prompt GET ({ds:1}) lands (~300ms).
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1', { timeout: 4000 });

    // The pre-round-trip stale B GET ({ds:2}) settles at ~2s from the first
    // mount: it was issued at an OLDER generation than the return GET →
    // stash write rejected, screen stays {ds:1}. Wait past its settle.
    await page.waitForTimeout(2500);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // Prove the STASH wasn't regressed: a failing edit reverts to {ds:1}
    // (pre-fix the unconditional stale-GET stash would revert to {ds:2}).
    await page.getByTestId('style-selector').selectOption('2');
    await page.waitForTimeout(500);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');
  });

  test('overlapping PUTs: an earlier-issued PUT settling later does not regress the stash', async ({ page }) => {
    const putBodies: string[] = [];
    let putSeen = 0;
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isB = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        putSeen += 1;
        putBodies.push(request.postData() ?? '');
        if (isB && putSeen === 1) {
          // First-issued PUT: confirm SLOWLY (settles after the 2nd).
          await new Promise((r) => setTimeout(r, 1500));
          route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
          return;
        }
        if (isB && putSeen === 2) {
          // Second-issued PUT: confirm fast (newer generation wins).
          route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
          return;
        }
        // Any later (failing) edit exposes the stash via revert.
        route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'fail' }) });
        return;
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockDefaultAgentConfig, design_system_id: 1, template_id: 1 }) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1', { timeout: 4000 });

    // Two edits in quick succession: PUT#1 (style->2, slow) then PUT#2
    // (style->1, fast). PUT#2 confirms first at a higher generation; PUT#1
    // settles later and must NOT regress the stash OR the visible state.
    await page.getByTestId('style-selector').selectOption('2'); // PUT#1 (slow)
    await page.getByTestId('style-selector').selectOption('1'); // PUT#2 (fast)
    await page.waitForTimeout(1800); // PUT#1 has now settled late

    // (a) VISIBLE state, asserted IN the post-late-confirm window: the stale
    // PUT#1 confirm must NOT repaint style 2 (pre-fix it does — the confirm
    // ignored the generation verdict and called setAgentConfig(stale)).
    await expect(page.getByTestId('style-selector')).toHaveValue('1');

    // (b) The next edit's WIRE body builds from the newer value. The probe is a
    // DECK PROMPT change, which is orthogonal to the style slot and so leaves
    // slide_style_id alone: the PUT body reveals the base style, post-fix 1 and
    // pre-fix 2 (built from the regressed visible state). It used to be a DESIGN
    // SYSTEM change, on the reasoning that a DS change preserves
    // slide_style_id — no longer true now that the two style sources are
    // mutually exclusive (choosing a DS clears the style), which would make this
    // read null for a reason that has nothing to do with the race under test.
    const putsBefore = putBodies.length;
    await page.getByTestId('deck-prompt-selector').selectOption('2');
    await expect.poll(() => putBodies.length).toBeGreaterThan(putsBefore);
    const nextEdit = JSON.parse(putBodies[putBodies.length - 1]);
    expect(nextEdit.slide_style_id).toBe(1); // newer value, never stale 2

    // (c) That edit FAILED (mock 500) — its revert also lands on style 1,
    // proving the stash likewise held the newer value.
    await page.waitForTimeout(400);
    await expect(page.getByTestId('style-selector')).toHaveValue('1');
  });

  test('an explicit edit during the pending config load wins over the late GET', async ({ page }) => {
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    await mockSessionWithSlides(page, SESSION_B);

    const configPutBodies: string[] = [];
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isA = request.url().includes(TEST_SESSION_ID);
      if (request.method() === 'PUT') {
        configPutBodies.push(request.postData() ?? '');
        route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
        return;
      }
      if (!isA) await new Promise((r) => setTimeout(r, 2000));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockDefaultAgentConfig,
          design_system_id: isA ? 1 : 2,
          template_id: isA ? 1 : 2,
        }),
      });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('template-selector')).toHaveValue('1');

    await page.getByText('Session 2026-01-08 20:20').first().click();
    await page.waitForURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // Explicit edit for B inside the pending window: clear the DS.
    await page.waitForTimeout(300);
    await page.getByTestId('design-system-selector').selectOption('');
    await expect.poll(() => configPutBodies.length).toBeGreaterThan(0);
    expect(JSON.parse(configPutBodies[0]).design_system_id ?? null).toBe(null);

    // The late GET (B's old {ds:2,tpl:2}) lands afterwards and must be
    // DISCARDED — the user's explicit choice stands.
    await page.waitForTimeout(2500);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
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
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route, request) => {
      if (request.method() === 'PUT') {
        serverConfig = JSON.parse(request.postData() ?? '{}');
        configPuts.push(serverConfig);
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(serverConfig) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      if (request.method() === 'POST') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ acquired: true, locked_by: null }) });
      } else if (request.method() === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ released: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ locked: false, locked_by: null }) });
      }
    });
    const streamBodies: string[] = [];
    await page.route(apiPath('/api/chat/stream'), (route, request) => {
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
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route, request) => {
      if (request.method() === 'PUT') sessionConfigPuts.push(request.postData() ?? '');
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDefaultAgentConfig) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+$/), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemDetail) });
        return;
      }
      route.continue();
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/files$/), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [], total: 0 }) });
    });
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates\/2\/source$/), (route) => {
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

// ---------------------------------------------------------------------------
// Org-default design system vs. the server-seeded LEGACY slide-style default
// ---------------------------------------------------------------------------

/**
 * The product decision is that an org-default DESIGN SYSTEM outranks the legacy
 * default slide style. But the server-seeded default profile carries the legacy
 * default slide-style id (`init_default_profile.py` / the profile ->
 * agent_config migration both populate `selected_slide_style_id`), and the
 * browser loads that profile BEFORE resolving defaults. Backend tests omit
 * `agent_config` entirely, so they never see this: in the real browser flow the
 * seeded style always occupied the slot and the org default never applied.
 *
 * A USER'S OWN explicit slide-style choice must still win, so these tests pin
 * both halves of the distinction. All fixtures synthetic.
 */
test.describe('org-default design system vs. seeded legacy style default', () => {
  const ORG_DEFAULT_DS_ID = mockDesignSystems.design_systems[0].id; // is_default: true
  const SEEDED_STYLE_ID = 1; // mockSlideStyles' is_system + is_default style

  /**
   * The default profile exactly as the server seeds it: is_default, and an
   * agent_config whose slide_style_id is the legacy default style.
   */
  const seededDefaultProfile = {
    id: 1,
    name: 'Default',
    description: 'Server-seeded default profile.',
    is_default: true,
    agent_config: {
      tools: [],
      slide_style_id: SEEDED_STYLE_ID,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
      system_prompt: null,
      slide_editing_instructions: null,
    },
    created_at: '2026-01-08T20:10:29.720015',
    created_by: 'system',
    updated_at: '2026-01-08T20:10:29.720025',
  };

  async function mockOrgDefaults(
    page: import('@playwright/test').Page,
    profile: Record<string, unknown>,
  ) {
    await setupMocks(page);
    // The seeded default profile is what the browser loads pre-session.
    await page.route(apiPathMatching(/\/api\/profiles$/), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([profile]),
      });
    });
    // An org-default design system exists.
    await page.route(apiPath('/api/settings/design-systems'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDesignSystems),
        });
      } else {
        route.continue();
      }
    });
    await page.addInitScript(() => {
      localStorage.removeItem('pendingAgentConfig');
      localStorage.removeItem('userDefaultSlideStyleId');
      localStorage.removeItem('userDefaultProfileId');
    });
  }

  /** The pre-session config the app would send with the first message. */
  async function pendingConfig(page: import('@playwright/test').Page) {
    return await expect
      .poll(async () => {
        const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
        return raw ? JSON.parse(raw) : null;
      })
      .not.toBeNull()
      .then(async () => {
        const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
        return JSON.parse(raw ?? '{}') as Record<string, unknown>;
      });
  }

  test('the org-default DS wins over the seeded legacy style default', async ({ page }) => {
    await mockOrgDefaults(page, seededDefaultProfile);

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    // The org default is preselected, and the legacy seeded style did not
    // occupy the slot instead.
    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(ORG_DEFAULT_DS_ID),
    );
    const config = await pendingConfig(page);
    expect(config.design_system_id).toBe(ORG_DEFAULT_DS_ID);
    expect(config.slide_style_id).toBeNull();
  });

  test("a USER'S OWN explicit style choice still beats the org-default DS", async ({ page }) => {
    // Distinguished from the seeded default by provenance: this user actively
    // picked a style, recorded as their personal preference.
    await mockOrgDefaults(page, seededDefaultProfile);
    await page.addInitScript(
      ([key, value]) => localStorage.setItem(key, value),
      ['userDefaultSlideStyleId', String(2)] as [string, string],
    );

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    const config = await pendingConfig(page);
    expect(config.slide_style_id).toBe(2);
    expect(config.design_system_id).toBeNull();
  });

  test('a profile style that is NOT the seeded default is treated as a real choice', async ({
    page,
  }) => {
    // A profile someone deliberately built around a specific non-default style
    // is an explicit choice, not the seed — it must not be overridden.
    await mockOrgDefaults(page, {
      ...seededDefaultProfile,
      agent_config: { ...seededDefaultProfile.agent_config, slide_style_id: 2 },
    });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    const config = await pendingConfig(page);
    expect(config.slide_style_id).toBe(2);
    expect(config.design_system_id).toBeNull();
  });

  test('an EXISTING configured session keeps its explicit None across a reload', async ({
    page,
  }) => {
    // Default seeding is a NEW-SESSION default. A user who picked Design
    // System = None and saved it must not have the org default silently
    // restored when they come back to the session.
    await mockOrgDefaults(page, seededDefaultProfile);
    await mockSessionWithSlides(page);

    const configPuts: Record<string, unknown>[] = [];
    await page.route(
      apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`),
      (route, request) => {
        if (request.method() === 'PUT') {
          configPuts.push(JSON.parse(request.postData() ?? '{}'));
          route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
          return;
        }
        // The session's SAVED config: explicitly configured, explicitly no
        // style source at all.
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            tools: [],
            slide_style_id: null,
            design_system_id: null,
            template_id: null,
            deck_prompt_id: null,
            system_prompt: null,
            slide_editing_instructions: null,
            is_configured: true,
          }),
        });
      },
    );

    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await expect(page.getByTestId('design-system-selector')).toBeVisible();

    // Both selectors stay empty: the saved "None" survived the reload…
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    await expect(page.getByTestId('style-selector')).toHaveValue('');
    // …and nothing was written back to the session.
    expect(configPuts).toEqual([]);
  });

  test('an UNCONFIGURED session still gets the org default', async ({ page }) => {
    // The counterpart: a session that never had a config saved is effectively
    // new, so the org default does apply.
    await mockOrgDefaults(page, seededDefaultProfile);
    await mockSessionWithSlides(page);

    await page.route(
      apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`),
      (route, request) => {
        if (request.method() === 'PUT') {
          route.fulfill({ status: 200, contentType: 'application/json', body: request.postData() ?? '{}' });
          return;
        }
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            tools: [],
            slide_style_id: null,
            design_system_id: null,
            template_id: null,
            deck_prompt_id: null,
            system_prompt: null,
            slide_editing_instructions: null,
            is_configured: false,
          }),
        });
      },
    );

    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(ORG_DEFAULT_DS_ID),
    );
  });

  test('with NO org-default DS the seeded style default is left alone', async ({ page }) => {
    await mockOrgDefaults(page, seededDefaultProfile);
    // No design system is marked default.
    await page.route(apiPath('/api/settings/design-systems'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            design_systems: mockDesignSystems.design_systems.map(ds => ({
              ...ds,
              is_default: false,
            })),
            total: mockDesignSystems.design_systems.length,
          }),
        });
      } else {
        route.continue();
      }
    });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    const config = await pendingConfig(page);
    expect(config.design_system_id).toBeNull();
    expect(config.slide_style_id).toBe(SEEDED_STYLE_ID);
  });
});


/**
 * PROVENANCE: "the server seeded this" vs "the user chose this" (round 2).
 *
 * The previous fix inferred provenance by comparing a stored `slide_style_id` to
 * the CURRENT seeded-default id. Value equality cannot express that distinction,
 * and it broke two ways:
 *
 *  - A user who DELIBERATELY selects the style that also happens to be the
 *    seeded default had their choice discarded and replaced by the org-default
 *    design system.
 *  - Flipping `is_default` later retroactively reinterpreted configs that were
 *    already stored, because the comparison is re-evaluated on every load.
 *
 * Provenance is therefore PERSISTED alongside the config (`style_source`), and
 * the resolver reads it instead of comparing ids. All fixtures synthetic.
 */
test.describe('persisted style provenance', () => {
  const ORG_DEFAULT_DS_ID = mockDesignSystems.design_systems[0].id;
  const SEEDED_STYLE_ID = 1; // mockSlideStyles' is_system + is_default style

  const seededDefaultProfile = {
    id: 1,
    name: 'Default',
    description: 'Server-seeded default profile.',
    is_default: true,
    agent_config: {
      tools: [],
      slide_style_id: SEEDED_STYLE_ID,
      design_system_id: null,
      template_id: null,
      deck_prompt_id: null,
      system_prompt: null,
      slide_editing_instructions: null,
    },
    created_at: '2026-01-08T20:10:29.720015',
    created_by: 'system',
    updated_at: '2026-01-08T20:10:29.720025',
  };

  async function mockOrgDefaults(page: import('@playwright/test').Page) {
    await setupMocks(page);
    await page.route(apiPathMatching(/\/api\/profiles$/), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([seededDefaultProfile]),
      });
    });
    await page.route(apiPath('/api/settings/design-systems'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDesignSystems),
        });
      } else {
        route.continue();
      }
    });
  }

  async function readStored(page: import('@playwright/test').Page) {
    const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
  }

  async function seedStoredConfig(
    page: import('@playwright/test').Page,
    config: Record<string, unknown>,
  ) {
    await page.addInitScript(
      ([key, value]) => {
        localStorage.setItem(key, value);
        localStorage.removeItem('userDefaultSlideStyleId');
        localStorage.removeItem('userDefaultProfileId');
      },
      ['pendingAgentConfig', JSON.stringify(config)] as [string, string],
    );
  }

  const baseConfig = {
    tools: [],
    slide_style_id: SEEDED_STYLE_ID,
    design_system_id: null,
    template_id: null,
    deck_prompt_id: null,
    system_prompt: null,
    slide_editing_instructions: null,
  };

  test('deliberately choosing the style that IS the seeded default survives a reload', async ({
    page,
  }) => {
    // The reviewer's repro: the user actively picked style 1. That it is also
    // the server's seeded default is a coincidence, not evidence of provenance.
    await mockOrgDefaults(page);
    await seedStoredConfig(page, { ...baseConfig, style_source: 'user' });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('style-selector')).toHaveValue(String(SEEDED_STYLE_ID));
    const stored = await readStored(page);
    expect(stored?.slide_style_id).toBe(SEEDED_STYLE_ID);
    expect(stored?.design_system_id ?? null).toBeNull();
  });

  test('a SERVER-SEEDED style is still overridden by the org-default design system', async ({
    page,
  }) => {
    // The other half of the same distinction: same id, seeded provenance.
    await mockOrgDefaults(page);
    await seedStoredConfig(page, { ...baseConfig, style_source: 'seeded' });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(ORG_DEFAULT_DS_ID),
    );
  });

  test('flipping is_default later does NOT reinterpret an already-stored config', async ({
    page,
  }) => {
    // Style 2 was the user's explicit choice; the org later makes style 2 the
    // seeded default. Under value-comparison the stored choice would suddenly
    // read as "seeded" and be discarded. Stored provenance is immutable.
    await mockOrgDefaults(page);
    await page.route(apiPath('/api/settings/slide-styles'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            styles: [
              { id: 1, name: 'System Default', category: 'System', is_active: true, is_system: true, is_default: false },
              { id: 2, name: 'Corporate Theme', category: 'Brand', is_active: true, is_system: false, is_default: true },
            ],
          }),
        });
      } else {
        route.continue();
      }
    });
    await seedStoredConfig(page, {
      ...baseConfig,
      slide_style_id: 2,
      style_source: 'user',
    });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('style-selector')).toHaveValue('2');
    expect((await readStored(page))?.design_system_id ?? null).toBeNull();
  });

  test('a LEGACY stored config with no provenance field is NOT overridden', async ({ page }) => {
    // Written before provenance existed. This test previously asserted the
    // OPPOSITE — that such a config is treated as SEEDED and the org-default
    // design system is substituted in — on the reasoning that these configs were
    // mirrored from the seeded profile.
    //
    // That reasoning does not hold for the case that matters: a config whose
    // only edit was choosing "Design System: None" is byte-identical to a
    // mirrored seeded one (no style_source, no ids, no tools), so "seeded" threw
    // away a deliberate user choice — the very bug provenance was introduced to
    // fix, arriving through another door. Absence of the marker on an EXISTING
    // STORED config is therefore USER-CHOSEN; only a genuinely new surface (no
    // stored config at all) is seeded, which the test below pins.
    await mockOrgDefaults(page);
    await seedStoredConfig(page, { ...baseConfig });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    // The stored config's own style slot survives; no design system is injected.
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    await expect(page.getByTestId('style-selector')).toHaveValue(String(SEEDED_STYLE_ID));
  });

  test('with NOTHING stored, the org-default design system is still seeded', async ({ page }) => {
    // The other side of the rule above: protecting existing stored configs must
    // not disable org-default seeding for a genuinely new surface.
    await mockOrgDefaults(page);

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(ORG_DEFAULT_DS_ID),
    );
  });

  test('choosing a style through the UI records USER provenance', async ({ page }) => {
    await mockOrgDefaults(page);
    await page.addInitScript(() => localStorage.removeItem('pendingAgentConfig'));

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await page.getByTestId('style-selector').selectOption('2');

    await expect.poll(async () => (await readStored(page))?.style_source).toBe('user');
    expect((await readStored(page))?.slide_style_id).toBe(2);
  });
});

/**
 * Design System = None must survive a reload (round 2).
 *
 * A stored config with ZERO TOOLS was discarded outright, so the deliberate
 * `design_system_id: null` inside it was thrown away and the org default
 * re-seeded on the next load. A config with no tools is still a real user
 * configuration. All fixtures synthetic.
 */
test.describe('explicit Design System = None survives', () => {
  const ORG_DEFAULT_DS_ID = mockDesignSystems.design_systems[0].id;

  async function mockWithOrgDefault(page: import('@playwright/test').Page) {
    await setupMocks(page);
    await page.route(apiPath('/api/settings/design-systems'), (route, request) => {
      if (request.method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDesignSystems),
        });
      } else {
        route.continue();
      }
    });
  }

  async function readStored(page: import('@playwright/test').Page) {
    const raw = await page.evaluate(() => localStorage.getItem('pendingAgentConfig'));
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
  }

  test('pre-session: choosing None then reloading keeps None', async ({ page }) => {
    await mockWithOrgDefault(page);
    // Clear the mirror for the FIRST load only. `addInitScript` runs on every
    // navigation including `reload()`, so an unconditional clear here would wipe
    // the very state this test reloads to inspect.
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('specDidClearConfig')) {
        sessionStorage.setItem('specDidClearConfig', '1');
        localStorage.removeItem('pendingAgentConfig');
      }
    });

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    // The org default is preselected; the user explicitly clears it.
    await page.getByTestId('design-system-selector').selectOption('');
    await expect
      .poll(async () => (await readStored(page))?.design_system_id ?? null)
      .toBeNull();

    // Reload: the stored config has ZERO tools, and must not be discarded.
    await page.reload();
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    const stored = await readStored(page);
    expect(stored?.design_system_id ?? null).toBeNull();
  });

  test('a stored zero-tool config is authoritative, not discarded', async ({ page }) => {
    await mockWithOrgDefault(page);
    await page.addInitScript(
      ([key, value]) => localStorage.setItem(key, value),
      [
        'pendingAgentConfig',
        JSON.stringify({
          tools: [],
          slide_style_id: null,
          design_system_id: null,
          template_id: null,
          deck_prompt_id: null,
          system_prompt: null,
          slide_editing_instructions: null,
          style_source: 'user',
        }),
      ] as [string, string],
    );

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();

    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    expect((await readStored(page))?.design_system_id ?? null).toBeNull();
  });
});
