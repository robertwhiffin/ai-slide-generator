/**
 * #319 — the chat placeholder shows the graph's current stage, over SSE, in a real browser.
 *
 * The polling transport is not in this harness (plan D21): the one webServer runs on
 * localhost:3000, where isPollingMode() is false, so sendChatMessage always streams.
 * Polling is covered by vitest (api.startPolling with a stubbed fetch) and the backend
 * integration test.
 *
 * How a turn is kept open under route.fulfill:
 *   route.fulfill delivers the whole body, then EOF.  streamChat (api.ts) treats EOF as
 *   neither completion nor error: its read loop just breaks.  ChatPanel clears isLoading
 *   only on a `complete` or `error` event, on onError, or on unmount/session change.  So a
 *   body with no `complete` leaves the turn open and the placeholder mounted, showing the
 *   label from whatever the body delivered.
 *
 *   The body arrives in one read, so its events are handled in one batch and no
 *   intermediate label is ever painted.  To know the batch has been handled before
 *   asserting the label, test 1 ends its body with an `assistant` sentinel.  Events are
 *   handled in order, so once the sentinel is in the transcript every snapshot before it
 *   has been applied.  The label assertion then sees the settled state, not a transient one.
 *
 * Sabotage (plan Task 9 Step 2): delete `case 'turn_progress':` from ChatPanel.tsx.  Test 1
 * goes red (the label stays "Generating slides...").  Dropping the seq guard (always take
 * the incoming snapshot) also turns test 1 red: the stale seq-3 snapshot, delivered last,
 * would show "Reviewing 2 slides… (1 of 3 done)".
 */
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';

import { goToGenerator } from '../helpers/new-ui';

// ── SSE helpers ───────────────────────────────────────────────────────────────

type Positions = number[];
interface SlidesPatch {
  total?: number;
  building?: Positions;
  reviewing?: Positions;
  fixing?: Positions;
  done?: Positions;
}

/** A turn_progress event as the backend emits it (src/services/graph/progress.py). */
function tp(seq: number, phase: string, slides: SlidesPatch = {}) {
  return {
    type: 'turn_progress',
    metadata: { node: 'progress' },
    turn_progress: {
      seq,
      phase,
      slides: { total: 0, building: [], reviewing: [], fixing: [], done: [], ...slides },
    },
  };
}

/** An SSE body: one `data: <json>\n\n` line per event. */
function sse(events: object[]): string {
  return events.map((event) => 'data: ' + JSON.stringify(event) + '\n\n').join('');
}

async function routeStream(page: import('@playwright/test').Page, body: string) {
  await page.route(
    (url) => url.pathname === '/api/chat/stream',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      });
    },
  );
}

async function sendMessage(page: import('@playwright/test').Page, text: string) {
  await goToGenerator(page);
  await page.getByRole('textbox').fill(text);
  await page.getByRole('button', { name: 'Send' }).click();
}

// ── Shared setup (verbatim from incremental-slide-delivery.spec.ts) ─────────────

async function setupForGeneration(page: import('@playwright/test').Page) {
  await setupMocks(page);

  // setup-mocks.ts returns 404 for session details, which causes AppLayout to call
  // navigate('/help'), detaching the chat textarea before fill() can reach it.
  // Override: return a minimal valid session so AppLayout stays on the edit page.
  // Registered AFTER setupMocks so it takes Playwright's LIFO priority.
  await page.route(
    (url) => /^\/api\/sessions\/[^/]+$/.test(url.pathname),
    (route, request) => {
      if (request.method() !== 'GET') { route.fallback(); return; }
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-session-id',
          user_id: null,
          created_by: 'dev@local.dev',
          title: 'Incremental Test Session',
          has_slide_deck: false,
          messages: [],
          my_permission: 'CAN_MANAGE',
        }),
      });
    },
  );

  // setup-mocks.ts also returns 404 for the contributors endpoint, which causes
  // AppLayout's lock acquisition to never resolve (the .then callback is never
  // called), leaving isLockHolder=false and the textarea disabled.
  // Return an empty contributors list — AppLayout immediately sets isLockHolder=true
  // when contributors.length === 0 (no lock contention possible).
  await page.route(
    (url) => /^\/api\/sessions\/[^/]+\/contributors$/.test(url.pathname),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ contributors: [] }),
      });
    },
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('#319 — the chat placeholder shows the graph stage (SSE)', () => {
  test.beforeEach(async ({ page }) => {
    await setupForGeneration(page);
  });

  test('the placeholder shows the newest stage the stream delivered, never a stale one', async ({ page }) => {
    // seq 4 arrives before seq 3: the stale seq-3 snapshot must not overwrite it.
    // No `complete`, so the turn stays open.
    await routeStream(page, sse([
      tp(1, 'planning'),
      tp(2, 'building', { total: 3, building: [0, 1, 2] }),
      tp(4, 'building', { total: 3, reviewing: [2], done: [0, 1] }),
      tp(3, 'building', { total: 3, reviewing: [1, 2], done: [0] }),
      { type: 'assistant', content: 'Stage events delivered' },
    ]));

    await sendMessage(page, 'Build me a three slide deck');

    // The sentinel is in the transcript, so every snapshot before it has been applied.
    await expect(page.getByText('Stage events delivered')).toBeVisible({ timeout: 15000 });

    await expect(page.getByTestId('chat-turn-progress')).toHaveText('Reviewing slide 3… (2 of 3 done)');
    // The stage is only in the placeholder, never also in the transcript.
    await expect(page.getByText('Reviewing slide 3', { exact: false })).toHaveCount(1);
  });

  test('the placeholder disappears when the turn completes', async ({ page }) => {
    // Hold the response until the test has seen the placeholder mounted.  Otherwise
    // "count 0" would also pass if the placeholder never carried the test id at all.
    let release!: () => void;
    const released = new Promise<void>((resolve) => { release = resolve; });
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      async (route) => {
        await released;
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: sse([
            tp(1, 'planning'),
            tp(2, 'reviewing_deck'),
            { type: 'complete' },
          ]),
        });
      },
    );

    await sendMessage(page, 'Build me a deck');

    // The turn is open: the placeholder is mounted with the generic text.
    await expect(page.getByTestId('chat-turn-progress')).toHaveText('Generating slides...', { timeout: 15000 });

    release();

    await expect(page.getByTestId('chat-turn-progress')).toHaveCount(0);
    // The last stage did not get left behind anywhere on the page.
    await expect(page.getByText('Reviewing the narrative', { exact: false })).toHaveCount(0);
  });

  test('a stream with no stage events (the legacy engine) keeps the generic text', async ({ page }) => {
    // No `complete`, so the turn stays open.
    await routeStream(page, sse([
      { type: 'assistant', content: 'Working on it' },
    ]));

    await sendMessage(page, 'Build me a deck');

    // The stream has been handled (its only event is in the transcript)...
    await expect(page.getByText('Working on it')).toBeVisible({ timeout: 15000 });
    // ...and the placeholder is still the generic, byte-identical legacy text.
    await expect(page.getByTestId('chat-turn-progress')).toHaveText('Generating slides...');
  });
});
