import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import { mockDesignSystems, mockDefaultAgentConfig } from '../fixtures/mocks';

/**
 * A design system and a slide style are MUTUALLY EXCLUSIVE style sources.
 *
 * Item 2 (user-facing bug). Picking a Slide Style left `design_system_id` set,
 * and a design system takes precedence in the prompt — so the style the user
 * just chose had no effect, silently. The config bar even rendered "Design
 * system takes precedence over slide style", documenting the confusion rather
 * than preventing it. Choosing either source must now CLEAR the other, in the
 * component state AND in what is PUT.
 *
 * Item 4 (user-facing bug). A config stored BEFORE `style_source` existed
 * carries no provenance marker. Treating that absence as "seeded" meant an
 * explicit "Design System: None", saved earlier, was silently replaced by the
 * org default on the next load. Absence of the marker on an EXISTING stored
 * config must read as USER-CHOSEN; only genuine session creation seeds.
 *
 * All fixtures SYNTHETIC.
 */

const DS_ID = mockDesignSystems.design_systems[0].id;
const OTHER_DS_ID = mockDesignSystems.design_systems[1].id;
const STYLE_ID = 2; // "Corporate Theme" in mockSlideStyles

async function expandAgentConfig(page: import('@playwright/test').Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('agent-config-bar')).toBeVisible();
  await page.getByTestId('agent-config-toggle').click();
  await expect(page.getByTestId('design-system-selector')).toBeVisible();
}

test.describe('Style source exclusivity (design system XOR slide style)', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
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
    // Shape matters: the client reads ``res.templates``, so a bare array makes
    // the selectors row throw and NOTHING renders.
    await page.route(apiPathMatching(/\/api\/settings\/design-systems\/\d+\/templates$/), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ templates: [] }),
      });
    });
  });

  /** Stateful agent-config route: PUTs update the served config, and are captured.
   *
   * Registered on the EXACT session path (like ``design-system-selector.spec.ts``)
   * so it wins over the shared ``setup-mocks`` handler, which also answers
   * ``/agent-config`` and would otherwise serve the default config back. */
  async function statefulConfig(
    page: import('@playwright/test').Page,
    initial: Record<string, unknown>,
  ) {
    const puts: Record<string, unknown>[] = [];
    let served: Record<string, unknown> = { ...initial };
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/agent-config`), (route) => {
      const request = route.request();
      if (request.method() === 'PUT') {
        served = JSON.parse(request.postData() ?? '{}');
        puts.push(served);
      }
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(served),
      });
    });
    return puts;
  }

  test('choosing a slide style CLEARS the design system in the PUT', async ({ page }) => {
    // The reported repro: a session already carrying design_system_id.
    const puts = await statefulConfig(page, {
      ...mockDefaultAgentConfig,
      slide_style_id: null,
      design_system_id: DS_ID,
      style_source: 'user',
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(DS_ID));

    await page.getByTestId('style-selector').selectOption(String(STYLE_ID));

    // The outgoing request body is the contract the backend and prompt see.
    await expect.poll(() => puts.at(-1)?.slide_style_id).toBe(STYLE_ID);
    expect(puts.at(-1)?.design_system_id).toBeNull();
    // And the picked style is a user decision, so provenance says so.
    expect(puts.at(-1)?.style_source).toBe('user');
  });

  test('choosing a slide style clears the design system in the CONFIG BAR', async ({ page }) => {
    await statefulConfig(page, {
      ...mockDefaultAgentConfig,
      slide_style_id: null,
      design_system_id: DS_ID,
      style_source: 'user',
    });

    await expandAgentConfig(page);
    await page.getByTestId('style-selector').selectOption(String(STYLE_ID));

    // Visible state, not just the wire: the DS select falls back to "None".
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    await expect(page.getByTestId('style-selector')).toHaveValue(String(STYLE_ID));
    // The precedence hint is meaningless once they are exclusive.
    await expect(
      page.getByText('Design system takes precedence over slide style'),
    ).toHaveCount(0);
  });

  test('choosing a design system CLEARS the slide style (the mirrored direction)', async ({ page }) => {
    const puts = await statefulConfig(page, {
      ...mockDefaultAgentConfig,
      slide_style_id: STYLE_ID,
      design_system_id: null,
      style_source: 'user',
    });

    await expandAgentConfig(page);
    await expect(page.getByTestId('style-selector')).toHaveValue(String(STYLE_ID));

    await page.getByTestId('design-system-selector').selectOption(String(DS_ID));

    await expect.poll(() => puts.at(-1)?.design_system_id).toBe(DS_ID);
    expect(puts.at(-1)?.slide_style_id).toBeNull();
    await expect(page.getByTestId('style-selector')).toHaveValue('');
  });

  test('clearing the slide style to None does NOT resurrect a design system', async ({ page }) => {
    const puts = await statefulConfig(page, {
      ...mockDefaultAgentConfig,
      slide_style_id: STYLE_ID,
      design_system_id: null,
      style_source: 'user',
    });

    await expandAgentConfig(page);
    await page.getByTestId('style-selector').selectOption('');

    await expect.poll(() => puts.length).toBeGreaterThan(0);
    expect(puts.at(-1)?.slide_style_id).toBeNull();
    expect(puts.at(-1)?.design_system_id).toBeNull();
  });

  test('switching between two design systems keeps the style slot clear', async ({ page }) => {
    const puts = await statefulConfig(page, {
      ...mockDefaultAgentConfig,
      slide_style_id: null,
      design_system_id: DS_ID,
      style_source: 'user',
    });

    await expandAgentConfig(page);
    await page.getByTestId('design-system-selector').selectOption(String(OTHER_DS_ID));

    await expect.poll(() => puts.at(-1)?.design_system_id).toBe(OTHER_DS_ID);
    expect(puts.at(-1)?.slide_style_id).toBeNull();
  });

  test('a LEGACY stored config with no style_source is NOT re-seeded (Item 4)', async ({ page }) => {
    // A pre-provenance config that recorded an explicit "Design System: None":
    // no style_source key at all, and both style slots null. The org default DS
    // is available (mockDesignSystems[0].is_default), so a config treated as
    // "seeded" would have it substituted in.
    await page.addInitScript(
      ([key, value]) => localStorage.setItem(key, value),
      [
        'pendingAgentConfig',
        JSON.stringify({
          tools: [],
          slide_style_id: null,
          design_system_id: null,
          deck_prompt_id: null,
          template_id: null,
          system_prompt: null,
          slide_editing_instructions: null,
          // NOTE: no style_source key — this is the legacy shape.
        }),
      ] as [string, string],
    );

    const puts = await statefulConfig(page, {
      tools: [],
      slide_style_id: null,
      design_system_id: null,
    });

    await expandAgentConfig(page);

    // The stored "None" survives: the org default must NOT be substituted.
    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    // Nor may a background resolve PUT one in behind the user's back.
    await page.waitForTimeout(1000);
    expect(
      puts.filter((c) => c.design_system_id != null),
      'a legacy explicit-None config was silently re-seeded with the org default',
    ).toEqual([]);
  });

  test('PRE-SESSION: a legacy explicit-None mirror is not discarded and re-seeded', async ({ page }) => {
    // The pre-session surface (no /sessions/:id in the URL) decides whether a
    // stored mirror is authoritative via `isConfigResolved`. A legacy config that
    // recorded an explicit "Design System: None" has NO style_source, no tools,
    // no design system and no deck prompt — so it satisfied none of those tests,
    // was treated as an unresolved first-paint placeholder, and the org default
    // design system was seeded straight over the user's saved "None".
    await page.addInitScript(
      ([key, value]) => localStorage.setItem(key, value),
      [
        'pendingAgentConfig',
        JSON.stringify({
          tools: [],
          slide_style_id: null,
          design_system_id: null,
          deck_prompt_id: null,
          template_id: null,
          system_prompt: null,
          slide_editing_instructions: null,
          // NOTE: no style_source key — the legacy shape.
        }),
      ] as [string, string],
    );

    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await expect(page.getByTestId('design-system-selector')).toBeVisible();
    await page.waitForTimeout(1500);

    await expect(
      page.getByTestId('design-system-selector'),
      'a legacy explicit-None config was re-seeded with the org default',
    ).toHaveValue('');
  });

  test('PRE-SESSION: a genuinely EMPTY first paint still loads the default profile', async ({ page }) => {
    // The other side of the same coin: with NOTHING stored, seeding must still
    // happen — otherwise "never treat absence as seeded" would break the real
    // new-user default. Only an EXISTING stored config is protected.
    await page.goto('/');
    await expect(page.getByTestId('agent-config-bar')).toBeVisible();
    await page.getByTestId('agent-config-toggle').click();
    await expect(page.getByTestId('design-system-selector')).toBeVisible();

    await expect(page.getByTestId('design-system-selector')).toHaveValue(String(DS_ID));
  });

  test('a config with no style_source and NO ids still shows None after reload', async ({ page }) => {
    // Same as above, via the SESSION load path rather than the localStorage
    // mirror: the stored server config carries no provenance marker.
    await statefulConfig(page, {
      tools: [],
      slide_style_id: null,
      design_system_id: null,
      deck_prompt_id: null,
      // no style_source
      is_configured: true,
    });

    await expandAgentConfig(page);

    await expect(page.getByTestId('design-system-selector')).toHaveValue('');
    await expect(page.getByTestId('style-selector')).toHaveValue('');
  });
});
