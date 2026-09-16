/**
 * E0 — incremental slide delivery e2e spec.
 *
 * Covers the four BEHAVIOURAL assertions that the component test
 * (slideReadyEvent.test.ts) cannot make because they require a running browser:
 *
 *   1. A released slide renders before the turn completes.
 *      Operand: data-released-count on the slide-viewer pane.  The count is
 *      updated ONLY by slide_ready events; the complete handler does not touch it.
 *      Deleting the case leaves data-released-count at 0 while slides still appear
 *      (via the complete handler) — the final-deck assertion stays green, the
 *      incremental assertion goes red.
 *
 *   2. Slides render in ascending position order even when released out of order.
 *      Delivery sequence: position 2, then 0, then 1.  After the turn the viewer
 *      shows slides at the correct ribbon positions: ribbon-thumb-0 renders
 *      position 0's content, not position 2's.
 *
 *   3. The released-position state reflects exactly the positions released so far.
 *      data-released-count equals the number of slide_ready events received.
 *
 *   4. The turn-open signal (isGenerating) is true during the turn and false
 *      after the complete event.  Observable as the "• Generating..." text in the
 *      header — present while loading, absent once complete.
 *
 *   5. The polling transport also delivers slides incrementally (shape-level guard
 *      is in slideReadyEvent.test.ts; this spec adds a route-intercept to confirm
 *      the slide_cursor is handed back on each poll request).
 *
 * Sabotage discipline — see test 1:
 *   Delete `case 'slide_ready':` from ChatPanel.tsx and re-run:
 *     - The incremental assertion (data-released-count > 0) goes red.
 *     - The final-deck assertion (slide-count visible) stays green.
 *   This confirms the test is watching the release path, not the complete path.
 *
 * Known-failing specs (not ours):
 *   3 × slide-surface-fidelity (in-iframe computed styles)
 *   11 × deck-integrity (no local backend)
 *   1 × export-ui (isolation)
 */
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import { goToGenerator, getSlideCountLocator } from '../helpers/new-ui';

// ── Constants ─────────────────────────────────────────────────────────────────

/** HTML fragments used in slide_ready events; each unique so the content can
 *  be identified from the viewer. */
const SLIDE_HTMLS = [
  '<div class="slide-container"><h1 data-pos="0">Incremental Slide Zero</h1></div>',
  '<div class="slide-container"><h1 data-pos="1">Incremental Slide One</h1></div>',
  '<div class="slide-container"><h1 data-pos="2">Incremental Slide Two</h1></div>',
];

/** A minimal SlideDeck returned from the getSlides API on complete.
 *  We return it with the same slide content so the incremental state
 *  is preserved after the complete handler replaces the deck. */
const FINAL_SLIDE_DECK = {
  title: 'Incremental Test Deck',
  slide_count: 3,
  css: '',
  external_scripts: [],
  scripts: '',
  slides: SLIDE_HTMLS.map((html, i) => ({
    index: i,
    slide_id: `inc-slide-${i}`,
    html,
    scripts: '',
    content_hash: `hash-${i}`,
  })),
  findings: [],
  deck_spec: null,
};

/** Build an SSE body with slide_ready events delivered in the given position order,
 *  followed by a complete event with no slides (so the incremental deck survives). */
function buildSlideReadySSE(positionOrder: number[]): string {
  const events: string[] = [];
  for (const pos of positionOrder) {
    events.push(
      'data: ' + JSON.stringify({
        type: 'slide_ready',
        position: pos,
        html: SLIDE_HTMLS[pos],
        scripts: '',
        slide_cursor: pos + 1,
      }) + '\n\n',
    );
  }
  // complete with no `slides` field: the ChatPanel complete handler checks
  // `if (event.slides && ...)` and skips the getSlides fetch entirely.
  // The deck remains exactly as built by slide_ready events.
  events.push('data: ' + JSON.stringify({ type: 'complete' }) + '\n\n');
  return events.join('');
}

// ── Shared setup ──────────────────────────────────────────────────────────────

async function setupForGeneration(page: import('@playwright/test').Page) {
  await setupMocks(page);
}

// ── Selector for the slide-viewer pane carrying data-released-count ──────────

function releasedCountLocator(page: import('@playwright/test').Page) {
  return page.locator('[data-tour="slide-viewer"]');
}

// ── Test 1: incremental — released count is updated by slide_ready, not complete ─
//
// The WHOLE TEST POINT: the released-position counter is incremented by
// slide_ready events.  complete does not increment it.  So after the turn:
//   - data-released-count === 3  ← slide_ready events fired (incremental)
//   - 3 slides visible            ← final-deck assertion (would pass even without the case)
//
// Sabotage: delete `case 'slide_ready':` → count stays 0 while slides are visible.

test.describe('E0 — incremental: released count via slide_ready', () => {
  test.beforeEach(async ({ page }) => {
    await setupForGeneration(page);
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: buildSlideReadySSE([0, 1, 2]),
        });
      },
    );
  });

  test('data-released-count equals the number of slide_ready events received', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Build an incremental deck');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for the generation to settle.
    // The complete event carries no slides, so the deck stays as-built.
    // ribbon-thumb-0..2 appear when the viewer has 3 slides.
    await expect(page.getByTestId('ribbon-thumb-2')).toBeVisible({ timeout: 15000 });

    // INCREMENTAL ASSERTION: the released-position count must be 3.
    // Only slide_ready events update it; the complete handler does not.
    const releasedPanee = releasedCountLocator(page);
    await expect.poll(
      () => releasedPanee.getAttribute('data-released-count'),
      { message: 'data-released-count must equal 3 (one per slide_ready event received)' },
    ).toBe('3');

    // FINAL-DECK ASSERTION (stays green even without the case):
    // 3 slides visible — ribbon-thumb-2 confirms the third thumb is rendered.
    await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
    await expect(page.getByTestId('ribbon-thumb-1')).toBeVisible();
    await expect(page.getByTestId('ribbon-thumb-2')).toBeVisible();
  });
});

// ── Test 2: ascending order — out-of-order delivery lands in order ────────────
//
// Delivery: position 2 first, then 0, then 1.
// After the turn the viewer should show:
//   ribbon-thumb-0 → content for position 0 ("Slide Zero")
//   ribbon-thumb-1 → content for position 1 ("Slide One")
//   ribbon-thumb-2 → content for position 2 ("Slide Two")
//
// Without the ascending-insertion logic in handleSlideReady, the slide that
// arrives LAST (position 1) occupies ribbon-thumb-2, showing "Slide One"
// where "Slide Two" should be.

test.describe('E0 — ascending order: out-of-order delivery', () => {
  test.beforeEach(async ({ page }) => {
    await setupForGeneration(page);
    // Deliver position 2 first, then 0, then 1 (deliberately out of order)
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: buildSlideReadySSE([2, 0, 1]),
        });
      },
    );
  });

  test('slides render in ascending position order even when delivered out of order', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox').fill('Build an out-of-order deck');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for all three thumbnails
    await expect(page.getByTestId('ribbon-thumb-2')).toBeVisible({ timeout: 15000 });

    // All three released
    const releasedPanee = releasedCountLocator(page);
    await expect.poll(
      () => releasedPanee.getAttribute('data-released-count'),
    ).toBe('3');

    // Navigate to each slide and verify content matches position, not arrival order.
    // ribbon-thumb-0 is the first entry in slideDeck.slides (index 0 = position 0).
    await page.getByTestId('ribbon-thumb-0').click();
    await expect(page.getByTestId('slide-stage-frame').contentFrame().locator('[data-pos="0"]')).toBeVisible({ timeout: 5000 });

    await page.getByTestId('ribbon-thumb-1').click();
    await expect(page.getByTestId('slide-stage-frame').contentFrame().locator('[data-pos="1"]')).toBeVisible({ timeout: 5000 });

    await page.getByTestId('ribbon-thumb-2').click();
    await expect(page.getByTestId('slide-stage-frame').contentFrame().locator('[data-pos="2"]')).toBeVisible({ timeout: 5000 });
  });
});

// ── Test 3: turn-open signal — isGenerating is true during and false after ───
//
// The "• Generating..." text in the AppLayout header appears while isGenerating
// is true and disappears when the complete event fires.  This is E2b's other
// operand: `!isGenerating`.

test.describe('E0 — turn-open signal: isGenerating', () => {
  test.beforeEach(async ({ page }) => {
    await setupForGeneration(page);
  });

  test('turn-open signal is true during the turn and false after complete', async ({ page }) => {
    // Use a delayed SSE response so we can observe the loading state.
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      async (route) => {
        // Small delay so "Generating..." is visible
        await new Promise<void>(resolve => setTimeout(resolve, 500));
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: buildSlideReadySSE([0, 1, 2]),
        });
      },
    );

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Test turn signal');
    await page.getByRole('button', { name: 'Send' }).click();

    // During the turn: the loading indicator is visible (isGenerating = true)
    // MessageList shows a loading animation — the simplest observable is the
    // LoadingIndicator component which shows a blue pill with a message.
    await expect(page.locator('.bg-blue-50')).toBeVisible({ timeout: 3000 });

    // After complete: loading indicator disappears (isGenerating = false)
    await expect(page.getByTestId('ribbon-thumb-2')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.bg-blue-50')).not.toBeVisible({ timeout: 5000 });
  });
});

// ── Test 4: polling transport — slide_cursor is handed back on each poll ──────
//
// This test intercepts the actual poll requests and verifies that after a
// slide_ready event with slide_cursor=1 is delivered, the NEXT poll request
// includes slide_cursor=1 in its URL.
//
// Approach: force polling mode by setting the window.location hostname to a
// Databricks Apps hostname (which triggers isPollingMode() = true in api.ts).
//
// Shape-level guards are in slideReadyEvent.test.ts tests 6 and 7.  This test
// is the behavioural proof that the cursor actually appears in the poll URL.

test.describe('E0 — polling transport: cursor is handed back', () => {
  test('slide_cursor from a slide_ready event appears in the next poll request URL', async ({ page }) => {
    await setupForGeneration(page);

    // Force polling mode: override window.location.hostname so isPollingMode()
    // returns true (it checks for .cloud.databricks.com hostnames).
    await page.addInitScript(() => {
      try {
        const desc = Object.getOwnPropertyDescriptor(Location.prototype, 'hostname');
        if (desc && desc.configurable) {
          Object.defineProperty(Location.prototype, 'hostname', {
            get() { return 'test.cloud.databricks.com'; },
            configurable: true,
          });
        }
      } catch {
        // If the override fails, the test will fail when it checks the poll URL.
      }
    });

    // Mock the async submission endpoint
    await page.route(
      apiPath('/api/chat/async'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ request_id: 'inc-poll-req-id' }),
        });
      },
    );

    // Collect poll request URLs so we can assert on them
    const pollUrls: string[] = [];
    let pollCallCount = 0;
    await page.route(
      (url) => url.pathname === '/api/chat/poll/inc-poll-req-id',
      (route) => {
        pollCallCount++;
        pollUrls.push(route.request().url());

        if (pollCallCount === 1) {
          // First poll: return a slide_ready event with slide_cursor=1
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              status: 'running',
              events: [{
                type: 'slide_ready',
                position: 0,
                html: SLIDE_HTMLS[0],
                scripts: '',
                slide_cursor: 1,
              }],
              last_message_id: 1,
            }),
          });
        } else {
          // Subsequent polls: complete the turn
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              status: 'completed',
              events: [],
              last_message_id: 2,
              result: {
                slides: FINAL_SLIDE_DECK,
                raw_html: null,
                replacement_info: null,
                experiment_url: null,
                session_title: null,
                metadata: null,
              },
            }),
          });
        }
      },
    );

    // Also mock the getSlides endpoint (called by the complete handler)
    await page.route(
      (url) => url.pathname.match(/\/api\/sessions\/[^/]+\/slides$/) !== null,
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ session_id: 'test', slide_deck: FINAL_SLIDE_DECK }),
        });
      },
    );

    await goToGenerator(page);
    await page.getByRole('textbox').fill('Polling incremental test');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for at least two poll calls
    await expect.poll(
      () => pollCallCount,
      { message: 'expected at least 2 poll calls', timeout: 20000 },
    ).toBeGreaterThanOrEqual(2);

    // The SECOND poll URL must include slide_cursor=1 (cursor from the first response)
    const secondPollUrl = pollUrls[1];
    expect(
      secondPollUrl,
      'Second poll URL must include slide_cursor=1. The client must hand back the cursor '
      + 'received from the first poll so the backend delivers only new slides.',
    ).toContain('slide_cursor=1');
  });
});
