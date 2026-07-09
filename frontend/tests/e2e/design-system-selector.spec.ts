import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route('http://127.0.0.1:8000/api/sessions?limit=5', (route) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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

    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    await page.route('http://127.0.0.1:8000/api/sessions?limit=5', (route) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    await page.route('http://127.0.0.1:8000/api/sessions?limit=5', (route) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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

    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    await page.getByTestId('style-selector').selectOption('2');
    await page.waitForTimeout(500);
    await expect(page.getByTestId('design-system-selector')).toHaveValue('1');

    // And the next edit's wire body builds from {ds:1}, never {ds:2}.
    await page.getByTestId('style-selector').selectOption('1');
    await expect.poll(() => putBodies.length).toBeGreaterThan(2);
    const lastPut = JSON.parse(putBodies[putBodies.length - 1]);
    expect(lastPut.design_system_id).toBe(1); // post-PUT truth, not stale 2
  });

  test('B->C->B: a pre-round-trip stale B GET settling after return cannot regress B (generation)', async ({ page }) => {
    const SESSION_C = 'c3d6e2f0-1234-4abc-9def-0123456789ab';
    await mockSessionWithSlides(page, SESSION_C);
    await page.route('http://127.0.0.1:8000/api/sessions?limit=5', (route) => {
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
    let bPutCount = 0;
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
      const url = request.url();
      const isB = url.includes(TEST_SESSION_ID);
      const isC = url.includes(SESSION_C);
      if (request.method() === 'PUT') {
        putBodies.push({ url, body: request.postData() ?? '' });
        if (isB) {
          // Every B edit FAILS so its revert reads (and thus reveals) B's
          // stash — the observable that proves the stale GET was rejected.
          bPutCount += 1;
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
    // settles later and must NOT regress the stash back to style 2.
    await page.getByTestId('style-selector').selectOption('2'); // PUT#1 (slow)
    await page.getByTestId('style-selector').selectOption('1'); // PUT#2 (fast)
    await page.waitForTimeout(1800); // PUT#1 has now settled late

    // A failing edit reveals the stash: it must hold PUT#2's style=1.
    await page.getByTestId('design-system-selector').selectOption('2');
    await page.waitForTimeout(400);
    await expect(page.getByTestId('style-selector')).toHaveValue('1');
  });

  test('an explicit edit during the pending config load wins over the late GET', async ({ page }) => {
    const SESSION_B = 'a2c5f1d9-8ef7-48dc-be69-0ead7be316dd';
    await mockSessionWithSlides(page, SESSION_B);

    const configPutBodies: string[] = [];
    await page.route(/\/api\/sessions\/[^/]+\/agent-config$/, async (route, request) => {
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
    await page.route(/\/api\/settings\/design-systems\/\d+\/templates$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDesignSystemTemplatesWithLive) });
    });
    await page.route(/\/api\/user\/current$/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: 'dev@local.dev' }) });
    });
    await page.route(/\/api\/sessions\/[^/]+\/lock$/, (route, request) => {
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
