/**
 * The presenter-window end-to-end flow, as a plain function.
 *
 * WHY a helper and not the spec body: Playwright refuses a test file that
 * imports another test file, so a local runner (one that attaches to an
 * existing browser instead of launching one) cannot import
 * `tests/e2e/presenter-view.spec.ts`. Both the spec and any local wrapper
 * import `presenterFlow` from here instead.
 *
 * Mocks go on the BrowserContext, not the Page, so the presenter pop-up's own
 * requests (its `GET /slides`) are answered too. Every matcher is a pathname
 * predicate, never a host-pinned URL: the API origin is whatever VITE_API_URL
 * says (127.0.0.1:8000 under the repo config, a dead port in local runs), and a
 * pathname match covers both. That is also why this does not call
 * `setupMocks(page)`: several of its routes pin `http://127.0.0.1:8000`.
 */
import { expect, type BrowserContext, type Page, type Route } from '@playwright/test';
import {
  mockAvailableTools,
  mockDeckPrompts,
  mockDefaultAgentConfig,
  mockProfileSummaries,
  mockSessions,
  mockSlideStyles,
  mockVerificationResponse,
} from '../fixtures/mocks';
import { mockSessionDetail, TEST_SESSION_ID } from './session-helpers';
import { apiPath, apiPathMatching } from './api-route';
import { whatsNewSeenStorage } from './whats-new';

const SESSION_ID = TEST_SESSION_ID;
const DECK_VERSION = 7;

/** A distinct talk track and notes on each slide, so every assertion names one slide. */
export const PRESENTER_SLIDES = [
  {
    title: 'Why Teams Move to the Cloud',
    talkTrack: 'Open with the one question every team asks first: what does this change for us on Monday?',
    notes: 'Slide one notes: the survey covered 412 teams across three regions.',
  },
  {
    title: 'Cost Savings Come First',
    talkTrack: 'Most teams see their hosting bill fall within the first two quarters after the move.',
    notes: 'Slide two notes: the savings figure excludes one-off migration work.',
  },
  {
    title: 'What Teams Build Next',
    talkTrack: 'Close on the new work the freed-up time makes possible for each team.',
    notes: 'Slide three notes: keep five minutes for questions after this slide.',
  },
];

const presenterSlidesResponse = {
  session_id: SESSION_ID,
  my_permission: 'CAN_MANAGE',
  slide_deck: {
    title: 'Moving to the Cloud',
    slide_count: PRESENTER_SLIDES.length,
    css: '',
    external_scripts: [],
    scripts: '',
    version: DECK_VERSION,
    findings: [],
    slides: PRESENTER_SLIDES.map((s, i) => ({
      index: i,
      slide_id: `slide-${i}`,
      html: `<div class="slide-container"><h1>${s.title}</h1><p>Slide ${i + 1} body.</p></div>`,
      scripts: '',
      content_hash: `presenter-hash-${i}`,
      talk_track: s.talkTrack,
      talk_track_source: 'model',
      speaker_notes: s.notes,
      speaker_notes_source: 'user',
    })),
  },
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    headers: { 'access-control-allow-origin': '*' },
    body: JSON.stringify(body),
  });
}

/**
 * Context-level mocks for the edit page and the presenter page.
 * Playwright tries routes in REVERSE registration order, so the catch-all
 * registered first is the last resort: anything not mocked below gets a 404
 * and never reaches a real server.
 */
async function mockPresenterApi(context: BrowserContext, unmocked: string[]) {
  // Pathname predicate, not the '**/api/**' glob: the glob would also swallow
  // the dev server's own source modules under /src/api/.
  await context.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      unmocked.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
      return json(route, { detail: 'Not mocked in presenter-view e2e' }, 404);
    },
  );

  await context.route(apiPath('/api/setup/status'), (route) => json(route, { configured: true }));
  await context.route(apiPath('/api/profiles'), (route) => json(route, mockProfileSummaries));
  await context.route(apiPath('/api/tools/available'), (route) => json(route, mockAvailableTools));
  await context.route(apiPath('/api/settings/deck-prompts'), (route) => json(route, mockDeckPrompts));
  await context.route(apiPath('/api/settings/slide-styles'), (route) => json(route, mockSlideStyles));
  await context.route(apiPath('/api/settings/design-systems'), (route) =>
    json(route, { design_systems: [], total: 0 }),
  );
  await context.route(apiPath('/api/version'), (route) => json(route, { version: '1.0.0' }));
  await context.route(apiPath('/api/images'), (route) => json(route, { images: [], total: 0 }));
  await context.route(apiPathMatching(/^\/api\/verification\//), (route) =>
    json(route, mockVerificationResponse),
  );
  await context.route(apiPath('/api/user/current'), (route) =>
    json(route, { username: 'test@test.com', display_name: 'Test User' }),
  );
  await context.route(apiPath('/api/sessions'), (route) => json(route, mockSessions));

  const base = `/api/sessions/${SESSION_ID}`;
  await context.route(apiPath(base), (route) => json(route, mockSessionDetail));
  await context.route(apiPath(`${base}/slides`), (route) => json(route, presenterSlidesResponse));
  await context.route(apiPath(`${base}/versions`), (route) =>
    json(route, { versions: [], current_version: null }),
  );
  await context.route(apiPath(`${base}/messages`), (route) =>
    json(route, {
      messages: [
        { role: 'user', content: 'Create slides about moving to the cloud', created_at: '2026-01-08T20:39:00' },
        { role: 'assistant', content: "I'll create slides about moving to the cloud.", created_at: '2026-01-08T20:39:30' },
      ],
    }),
  );
  await context.route(apiPath(`${base}/agent-config`), (route) => json(route, mockDefaultAgentConfig));
  await context.route(apiPath(`${base}/collaboration-history`), (route) =>
    json(route, { mixed_release_warning: false, has_legacy_evidence: false, groups: [] }),
  );
  await context.route(apiPath(`${base}/lock`), (route) =>
    json(route, { locked_by: 'test@test.com', locked_at: new Date().toISOString() }),
  );
}

/** Mark the app tour and every bundled release note as seen, on every page of the context. */
async function seedStorage(context: BrowserContext) {
  const entries = [{ name: 'tellr-app-tour-completed', value: 'true' }, ...whatsNewSeenStorage()];
  await context.addInitScript((items: { name: string; value: string }[]) => {
    try {
      for (const { name, value } of items) window.localStorage.setItem(name, value);
    } catch {
      // about:blank and opaque origins have no storage; nothing to seed there.
    }
  }, entries);
}

/** The presentation overlay (portal on document.body), as in presentation-mode.spec.ts. */
function presentationOverlay(page: Page) {
  return page.locator('div[style*="position: fixed"][style*="z-index: 9999"]');
}

/** The presenter's Read aloud section, so "Coming up" text never satisfies a talk-track check. */
function readAloud(presenter: Page) {
  return presenter
    .locator('section')
    .filter({ has: presenter.getByRole('heading', { name: 'Read aloud', exact: true }) });
}

async function expectBothOnSlide(page: Page, presenter: Page, index: number) {
  const n = index + 1;
  await expect(presentationOverlay(page).getByText(`${n} / ${PRESENTER_SLIDES.length}`, { exact: true })).toBeVisible();
  await expect(presenter.getByText(`Slide ${n} of ${PRESENTER_SLIDES.length}`, { exact: true })).toBeVisible();
  await expect(readAloud(presenter)).toContainText(PRESENTER_SLIDES[index].talkTrack);
  for (const [i, other] of PRESENTER_SLIDES.entries()) {
    if (i !== index) await expect(readAloud(presenter)).not.toContainText(other.talkTrack);
  }
}

/**
 * Open presentation mode, open the presenter with P, then step forward from the
 * presenter and back from the presentation, and open the presenter's notes.
 */
export async function presenterFlow(context: BrowserContext, baseURL: string) {
  const unmocked: string[] = [];
  await seedStorage(context);
  await mockPresenterApi(context, unmocked);

  const page = await context.newPage();
  let presenter: Page | undefined;
  try {
    await page.goto(`${baseURL}/sessions/${SESSION_ID}/edit`);

    const presentButton = page.getByRole('button', { name: 'Present', exact: true });
    await presentButton.waitFor({ state: 'visible', timeout: 15000 });
    await presentButton.click();
    await expect(presentationOverlay(page)).toBeVisible({ timeout: 5000 });
    await expect(presentationOverlay(page).getByText(`1 / ${PRESENTER_SLIDES.length}`, { exact: true })).toBeVisible();

    // P on the presentation overlay opens the presenter as a pop-up in this context.
    [presenter] = await Promise.all([context.waitForEvent('page'), page.keyboard.press('p')]);
    // A pop-up starts on about:blank; wait until it reaches the presenter route.
    await presenter.waitForURL((url) => url.pathname === `/sessions/${SESSION_ID}/present`);

    // Linked: presentation mode's state message has arrived.
    await expect(presenter.getByText('Slides: linked', { exact: true })).toBeVisible({ timeout: 10000 });
    await expectBothOnSlide(page, presenter, 0);

    // Forward from the presenter: it only asks; presentation mode moves, then reports back.
    await presenter.keyboard.press('ArrowRight');
    await expectBothOnSlide(page, presenter, 1);

    // Back from the presentation window: the presenter follows.
    await page.keyboard.press('ArrowLeft');
    await expectBothOnSlide(page, presenter, 0);

    // N in the presenter opens the notes drawer for the slide on screen.
    await presenter.keyboard.press('n');
    const drawer = presenter.getByTestId('presenter-notes-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText(PRESENTER_SLIDES[0].notes);
    await expect(drawer).not.toContainText(PRESENTER_SLIDES[1].notes);
  } finally {
    // The catch-all's 404s, for whoever debugs a failure. None of them are presenter calls.
    if (unmocked.length > 0) console.log(`[presenter-view] unmocked API calls (404): ${[...new Set(unmocked)].join(', ')}`);
    if (presenter && !presenter.isClosed()) await presenter.close();
    if (!page.isClosed()) await page.close();
  }
}
