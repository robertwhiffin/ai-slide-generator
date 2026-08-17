import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import {
  mockDesignSystems,
  mockDesignSystemTemplatesWithLive,
  mockSessions,
} from '../fixtures/mocks';

/**
 * A session's config must NEVER leak into another session — not on screen, and
 * above all not into what is PERSISTED for the other session.
 *
 * The cross-vendor review's CRITICAL finding: entering session B stripped only
 * `template_id` from the previous session's in-memory config. Every other value
 * — design system, deck prompt, and the TOOL LIST including private Genie
 * space ids — stayed visible while B's own GET was in flight, and every mutator
 * builds its PUT by spreading that config, so editing one field in B wrote
 * session A's private tool into B's stored config.
 *
 * The fix is structural rather than another field-by-field strip (this state
 * machine has had four rounds of point-fixes): until a session's own config has
 * loaded, `agentConfig` exposes NO inherited values at all, so there is nothing
 * for a mutator to spread or a selector to render.
 *
 * All fixtures SYNTHETIC.
 */

const SESSION_A = TEST_SESSION_ID;
const SESSION_B = 'c7f3a2b1-4d5e-4f6a-8b9c-0d1e2f3a4b5c';

// Session A's PRIVATE state. The genie space id is the sentinel that makes a
// leak unambiguous: it is a credential-shaped value, not just a selection.
const A_SPACE_ID = 'A-SPACE-01JGKXPRIVATE0000000000';
const A_CONFIG = {
  tools: [
    {
      type: 'genie',
      space_id: A_SPACE_ID,
      space_name: 'A private tool',
      description: null,
      conversation_id: null,
    },
  ],
  slide_style_id: null,
  design_system_id: mockDesignSystems.design_systems[0].id, // 1
  template_id: 1,
  deck_prompt_id: 1,
  system_prompt: null,
  slide_editing_instructions: null,
  style_source: 'user',
};

// Session B's OWN state: no tools, no design system, a different deck prompt.
const B_CONFIG = {
  tools: [],
  slide_style_id: null,
  design_system_id: null,
  template_id: null,
  deck_prompt_id: 3,
  system_prompt: null,
  slide_editing_instructions: null,
  style_source: 'user',
};

test.describe('Session config isolation (no cross-session leak)', () => {
  /**
   * Routes both sessions' agent-config. B's GET is DELAYED so the window the
   * reviewer exploited is wide open; every PUT is captured with its session id.
   */
  async function routeSessions(
    page: import('@playwright/test').Page,
    { delayBGetMs = 5000 }: { delayBGetMs?: number } = {},
  ) {
    const puts: { session: 'A' | 'B'; body: Record<string, unknown> }[] = [];
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/agent-config$/), async (route, request) => {
      const isB = request.url().includes(SESSION_B);
      if (request.method() === 'PUT') {
        puts.push({
          session: isB ? 'B' : 'A',
          body: JSON.parse(request.postData() ?? '{}'),
        });
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: request.postData() ?? '{}',
        });
        return;
      }
      if (isB) await new Promise((resolve) => setTimeout(resolve, delayBGetMs));
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...(isB ? B_CONFIG : A_CONFIG),
          is_configured: true,
        }),
      });
    });
    return puts;
  }

  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page, SESSION_A);
    await mockSessionWithSlides(page, SESSION_B);
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
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDesignSystemTemplatesWithLive),
      });
    });
    await page.route(apiPathMatching(/\/api\/user\/current$/), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: 'dev@local.dev' }),
      });
    });
    await page.route(apiPathMatching(/\/api\/sessions\/[^/]+\/lock$/), (route, request) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body:
          request.method() === 'POST'
            ? JSON.stringify({ acquired: true, locked_by: null })
            : JSON.stringify({ locked: false, locked_by: null }),
      });
    });
    // Sessions list, so the switch happens by CLICKING in the history sidebar —
    // in-app navigation that preserves React state. A full `page.goto` would
    // remount the provider and destroy the very leak window under test.
    await page.route(apiPath('/api/sessions'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            { ...mockSessions.sessions[0], session_id: SESSION_A, title: 'Session A fixture' },
            { ...mockSessions.sessions[1], session_id: SESSION_B, title: 'Session B fixture' },
          ],
          count: 2,
        }),
      });
    });
  });

  /** Switch sessions the way a user does: click the other session in history. */
  async function switchToSession(
    page: import('@playwright/test').Page,
    sessionId: string,
    title: string,
  ) {
    await page.getByText(title).first().click();
    await page.waitForURL(new RegExp(`/sessions/${sessionId}/edit`));
  }

  async function openConfigBar(page: import('@playwright/test').Page, sessionId: string) {
    await page.goto(`/sessions/${sessionId}/edit`);
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
  }

  test("REVIEWER REPRO: session A's private config is never written into session B", async ({ page }) => {
    const puts = await routeSessions(page);

    // 1. Land on A and let its config load fully: DS 1, prompt 1, A's tool.
    await openConfigBar(page, SESSION_A);
    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(A_CONFIG.design_system_id),
      { timeout: 10000 },
    );
    await expect(page.getByTestId('deck-prompt-selector')).toHaveValue('1');

    // 2. Switch to B. B's GET is delayed 5s, so this is the vulnerable window.
    await switchToSession(page, SESSION_B, 'Session B fixture');

    // 3. While B is still loading, NOTHING of A's may be on screen.
    await expect(
      page.getByTestId('design-system-selector'),
      "session A's design system is visible in session B during load",
    ).toHaveValue('');
    await expect(
      page.getByTestId('deck-prompt-selector'),
      "session A's deck prompt is visible in session B during load",
    ).toHaveValue('');
    await expect(
      page.getByText('A private tool'),
      "session A's private tool is visible in session B during load",
    ).toHaveCount(0);

    // 4. Edit ONLY B's deck prompt inside that window — the reviewer's step.
    await page.getByTestId('deck-prompt-selector').selectOption('2');
    await expect.poll(() => puts.filter((p) => p.session === 'B').length, {
      timeout: 10000,
    }).toBeGreaterThan(0);

    // 5. The PUT stored for B must carry NONE of A's values.
    const bPut = puts.filter((p) => p.session === 'B').at(-1)!.body;
    expect(bPut.deck_prompt_id, "B's own edit did not persist").toBe(2);
    expect(
      JSON.stringify(bPut),
      `session A's private genie space leaked into session B's stored config: ${JSON.stringify(bPut)}`,
    ).not.toContain(A_SPACE_ID);
    expect(bPut.tools, "session A's tools leaked into session B").toEqual([]);
    expect(bPut.design_system_id, "session A's design system leaked into session B").toBeNull();
    expect(bPut.template_id, "session A's template pin leaked into session B").toBeNull();

    // 6. And no PUT was ever issued against A by B's edit.
    expect(
      puts.filter((p) => p.session === 'A'),
      "editing session B wrote to session A",
    ).toEqual([]);
  });

  test("REVERSE: session B's OWN values still save correctly once loaded", async ({ page }) => {
    // The isolation must not cost normal function: after B's config resolves,
    // B's own state is editable and its edits persist with B's real values.
    const puts = await routeSessions(page, { delayBGetMs: 0 });

    await openConfigBar(page, SESSION_B);
    // B's own loaded state is displayed.
    await expect(page.getByTestId('deck-prompt-selector')).toHaveValue(
      String(B_CONFIG.deck_prompt_id),
      { timeout: 10000 },
    );

    // Pick a design system: B's own edit, built on B's own config.
    await page.getByTestId('design-system-selector').selectOption(
      String(mockDesignSystems.design_systems[1].id),
    );
    await expect.poll(() => puts.filter((p) => p.session === 'B').length, {
      timeout: 10000,
    }).toBeGreaterThan(0);

    const bPut = puts.filter((p) => p.session === 'B').at(-1)!.body;
    expect(bPut.design_system_id).toBe(mockDesignSystems.design_systems[1].id);
    // B's own deck prompt is preserved — the config was NOT reset to defaults.
    expect(bPut.deck_prompt_id).toBe(B_CONFIG.deck_prompt_id);
    expect(JSON.stringify(bPut)).not.toContain(A_SPACE_ID);
  });

  test('a tool added during B\'s pending load does not carry A\'s tools with it', async ({ page }) => {
    // Tools are the highest-value leak (space ids are credential-shaped), and
    // addTool spreads the existing tool array — so it gets its own case.
    const puts = await routeSessions(page);

    await openConfigBar(page, SESSION_A);
    await expect(page.getByText('A private tool')).toHaveCount(1, { timeout: 10000 });

    await switchToSession(page, SESSION_B, 'Session B fixture');

    // Inside the load window, B shows no tools at all.
    await expect(page.getByText('A private tool')).toHaveCount(0);

    // Any edit in this window must not resurrect A's tool array.
    await page.getByTestId('deck-prompt-selector').selectOption('2');
    await expect.poll(() => puts.filter((p) => p.session === 'B').length, {
      timeout: 10000,
    }).toBeGreaterThan(0);
    for (const put of puts.filter((p) => p.session === 'B')) {
      expect(
        JSON.stringify(put.body),
        `a PUT for B carried A's private space id: ${JSON.stringify(put.body)}`,
      ).not.toContain(A_SPACE_ID);
    }
  });

  test("returning to A shows A's values again (isolation is not amnesia)", async ({ page }) => {
    const puts = await routeSessions(page, { delayBGetMs: 0 });

    await openConfigBar(page, SESSION_A);
    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(A_CONFIG.design_system_id),
      { timeout: 10000 },
    );

    await switchToSession(page, SESSION_B, 'Session B fixture');
    await expect(page.getByTestId('deck-prompt-selector')).toHaveValue(
      String(B_CONFIG.deck_prompt_id),
      { timeout: 10000 },
    );

    await switchToSession(page, SESSION_A, 'Session A fixture');
    await expect(page.getByTestId('design-system-selector')).toHaveValue(
      String(A_CONFIG.design_system_id),
      { timeout: 10000 },
    );
    await expect(page.getByText('A private tool')).toHaveCount(1);
    expect(puts).toEqual([]); // navigation alone never writes
  });
});
