/**
 * E2b — "Agentic deck review in progress" flag, end-to-end.
 *
 * The component test (deckReviewFlag.test.tsx) covers the formula and the
 * non-blocking property via pure function calls and source scans.  This spec
 * adds what only a running browser can show: the badge element actually
 * appearing and disappearing in the rendered DOM around the review window.
 *
 * Three behavioural assertions this spec adds at browser level:
 *
 *   A. Badge is absent before anything is released, and appears once all
 *      positions in deck_spec.slides are released while the turn is still
 *      running — the whole-deck reviewer is the only work left at that point.
 *
 *   B. Badge is ON during the review window and then disappears when the turn
 *      completes — the review is the last thing before END, so `isGenerating`
 *      going false is the clean signal.  The ON half is asserted FIRST, so this
 *      test cannot pass because the badge never rendered.
 *
 *   C. Badge is absent while only SOME positions are released (the mid-build
 *      guard that separates "reviewing" from "building"), and then appears when
 *      the last position lands.  The positive half is the vacuity control: a
 *      badge that can never render fails this test.
 *
 *   D. (Review finding I1) The released-position set is emptied between turns,
 *      so turn N+1 does not inherit turn N's positions and read "Reviewing arc"
 *      from its first frame.  Two real turns; see the block above test D.
 *
 * ── WHY THIS SPEC OWNS ITS OWN TRANSPORT ───────────────────────────────────
 *
 * The badge is ON only during a real interval: every position released AND the
 * turn still open.  `route.fulfill` cannot produce that interval.  It delivers
 * the whole SSE body as ONE chunk, so streamChat's reader loop hands the
 * slide_ready events and `complete` to handleStreamEvent in a single batch and
 * React coalesces them: `isGenerating` is already false before the first paint.
 * Measured on this branch before the fix — at the moment of the ON assertion,
 * data-released-count was 2 and the spec pane held 2 slide briefs, but
 * "• Generating..." was already gone.  The ON state was not observable in that
 * harness AT ALL, which also made the two absence assertions pass for the wrong
 * reason: they were satisfied by a badge that never rendered.  Delaying the
 * fulfil (the old `setTimeout` before `route.fulfill`) separates nothing — it
 * delays the whole body, chunk boundaries and all.
 *
 * So the transport is driven from the test instead: `installChunkedStream`
 * replaces `window.fetch` for `/api/chat/stream` ONLY, and returns a Response
 * whose body is a ReadableStream the test pushes into.  Each `pushEvents` call
 * is a genuinely separate network chunk, arriving at a time the test chooses,
 * and `closeStream` ends the body.  Everything downstream of the bytes is
 * production code and is exercised unchanged: streamChat's decoder and reader
 * loop, handleStreamEvent's `slide_ready` and `complete` cases, AppLayout's
 * releasedPositions / _isReviewInProgress, SpecView's badge.  A turn with no
 * `complete` pushed stays genuinely open (nothing but complete/error sets
 * isGenerating false), which is what makes the ON window stable rather than
 * racy — the assertions do not depend on winning a race.
 *
 * NOTE for a future reader: overriding `window.location` via addInitScript does
 * NOT work in Chromium (see incremental-slide-delivery.spec.ts) because those
 * properties come from native bindings.  `window.fetch` is an ordinary
 * writable property and the override below is load-bearing, not decorative.
 *
 * ── Sabotage targets, and which test each one reddens ──────────────────────
 *   S1  SpecView badge render condition → `false` (the badge never renders,
 *       i.e. the state this spec used to be blind to) → ALL THREE go red, each
 *       at its own "badge visible" assertion.  Measured: A at the all-released
 *       ON check, B at the ON check that now precedes its OFF check, C at the
 *       last-position positive control.  Before this rewrite the same state
 *       left B and C green.
 *   S2  `_isReviewInProgress`: drop `&& isGenerating` → B alone goes red
 *       (badge still visible after the turn completes).
 *   S3  `_isReviewInProgress`: `releasedCount === specSlideCount` →
 *       `releasedCount > 0` → C alone goes red (badge on at 2 of 3).
 *   S4  `_isReviewInProgress`: invert the zero guard → A alone goes red
 *       (badge visible before anything was released).
 *
 * Known-expected failures from other suites (not this spec):
 *   3 × slide-surface-fidelity, 11 × deck-integrity, 1 × export-ui
 */
import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

// ── Shared fixtures ──────────────────────────────────────────────────────────

/** A minimal DeckSpec with N slide entries (positions 0..N-1). */
function makeDeckSpec(slideCount: number) {
  return {
    title: 'Test deck',
    audience: 'Test audience',
    purpose: 'Test purpose',
    argument: 'Test argument',
    call_to_action: 'Test CTA',
    narrative_arc: ['Beat 1', 'Beat 2'],
    design_contract: { design_system_id: null, template_id: null, slide_style_id: null },
    resolved_data: { synthesis: '', figures: [], gaps: [] },
    slides: Array.from({ length: slideCount }, (_, i) => ({
      position: i,
      purpose: `Purpose ${i}`,
      content_brief: `Brief ${i}`,
      assumes: `Assumes ${i}`,
      hands_off: `Hands off ${i}`,
      data_references: [],
      template_section_index: null,
    })),
  };
}

/** One SSE `slide_ready` frame for the given position. */
function slideReadyFrame(position: number): string {
  return (
    'data: ' +
    JSON.stringify({
      type: 'slide_ready',
      position,
      html: `<div class="slide-container"><h1>Slide ${position}</h1></div>`,
      scripts: '',
      slide_cursor: position + 1,
    }) +
    '\n\n'
  );
}

/**
 * One SSE `complete` frame, with no `slides` field: the ChatPanel complete
 * handler checks `if (event.slides && ...)` and skips the getSlides fetch, so
 * the incrementally built deck (and its released-count) survives the turn.
 */
function completeFrame(): string {
  return 'data: ' + JSON.stringify({ type: 'complete' }) + '\n\n';
}

// ── Chunk-controlled SSE transport (see the header comment for WHY) ──────────

/**
 * Replace window.fetch for /api/chat/stream with a Response whose body is a
 * ReadableStream the test controls.  Must be called before page.goto.
 */
async function installChunkedStream(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __sseStream: {
        /** How many times the app has opened /api/chat/stream (one per turn). */
        opens: number;
        pending: string[];
        controller: ReadableStreamDefaultController<Uint8Array> | null;
        push(text: string): void;
        close(): void;
      };
      fetch: typeof fetch;
    };

    w.__sseStream = {
      opens: 0,
      pending: [],
      controller: null,
      push(text: string) {
        if (this.controller) {
          this.controller.enqueue(new TextEncoder().encode(text));
        } else {
          // The request has not been made yet — replay on start().
          this.pending.push(text);
        }
      },
      close() {
        if (this.controller) {
          this.controller.close();
          this.controller = null;
        }
      },
    };

    const originalFetch = w.fetch.bind(window);
    w.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : (input as Request).url;
      if (!url.includes('/api/chat/stream')) {
        return originalFetch(input as RequestInfo, init);
      }
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          w.__sseStream.controller = controller;
          w.__sseStream.opens += 1;
          const encoder = new TextEncoder();
          for (const chunk of w.__sseStream.pending) {
            controller.enqueue(encoder.encode(chunk));
          }
          w.__sseStream.pending = [];
        },
      });
      return Promise.resolve(
        new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      );
    }) as typeof fetch;
  });
}

/**
 * Wait until the app has opened the chat stream for turn `turnNumber`.
 * Counted, not a boolean, so a second turn is distinguishable from the first.
 */
async function waitForStreamOpen(page: Page, turnNumber = 1) {
  await page.waitForFunction(
    (n) => ((window as unknown as { __sseStream?: { opens: number } }).__sseStream?.opens ?? 0) >= n,
    turnNumber,
    { timeout: 10000 },
  );
}

/** Push one network chunk containing the given SSE frames. */
async function pushEvents(page: Page, frames: string[]) {
  await page.evaluate(
    (text) =>
      (window as unknown as { __sseStream: { push(t: string): void } }).__sseStream.push(text),
    frames.join(''),
  );
}

/** End the SSE body (the reader loop sees `done`). */
async function closeStream(page: Page) {
  await page.evaluate(() =>
    (window as unknown as { __sseStream: { close(): void } }).__sseStream.close(),
  );
}

/**
 * Set up route mocks shared by all tests in this spec:
 *   - setupMocks (catch-all)
 *   - session detail → valid session so AppLayout stays on the edit page
 *   - contributors → empty list → lock granted immediately
 *
 * /api/chat/stream is deliberately NOT routed here: it is served in-page by
 * installChunkedStream, which never reaches the network layer.
 */
async function baseSetup(page: Page) {
  await installChunkedStream(page);
  await setupMocks(page);
  await mockSessionWithSlides(page);

  // Registered AFTER mockSessionWithSlides to override its session-detail route
  // (Playwright LIFO ordering means this handler is matched first).
  await page.route(
    (url) => /^\/api\/sessions\/[^/]+$/.test(url.pathname),
    (route, request) => {
      if (request.method() !== 'GET') { route.fallback(); return; }
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: TEST_SESSION_ID,
          user_id: null,
          created_by: 'dev@local.dev',
          title: 'Review Flag Test Session',
          has_slide_deck: true,
          messages: [],
          my_permission: 'CAN_MANAGE',
        }),
      });
    },
  );

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

/**
 * Override the getSlides response to include a deck_spec with `slideCount` slides.
 * Registered AFTER baseSetup so it takes LIFO priority over mockSessionWithSlides.
 */
async function mockDeckWithSpec(page: Page, slideCount: number) {
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSlidesResponse,
          slide_deck: {
            ...mockSlidesResponse.slide_deck,
            deck_spec: makeDeckSpec(slideCount),
          },
        }),
      });
    },
  );
}

/** Navigate to the test session's edit page, open the spec pane. */
async function openSpecPane(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('main-view-controls')).toBeVisible({ timeout: 15000 });
  // Switch to spec view before sending — both panels are mounted; the toggle
  // never unmounts either pane (AppLayoutSpecToggle.test.ts pins this).
  await page.getByTestId('view-toggle-spec').click();
  await expect(page.getByTestId('spec-view')).toBeVisible();
}

/** Send a chat message and wait for the stream to be opened by the app. */
async function sendAndWaitForStream(page: Page, message: string, turnNumber = 1) {
  await page.getByTestId('chat-input').fill(message);
  await page.getByRole('button', { name: 'Send' }).click();
  // "• Generating..." appears immediately (isGenerating flipped to true).
  await expect(page.getByText('• Generating...')).toBeVisible({ timeout: 5000 });
  await waitForStreamOpen(page, turnNumber);
}

/** The element that carries data-released-count (used to observe release progress). */
const releasedCountEl = (page: Page) => page.locator('[data-tour="slide-viewer"]');

/** Wait for the released-position count to reach `n`. */
async function expectReleasedCount(page: Page, n: number) {
  await expect
    .poll(
      () => releasedCountEl(page).getAttribute('data-released-count'),
      { message: `waiting for data-released-count to reach ${n}`, timeout: 10000 },
    )
    .toBe(String(n));
}

const badge = (page: Page) => page.getByTestId('deck-review-in-progress');
const generatingText = (page: Page) => page.getByText('• Generating...');

// ── Test A+B: badge appears when all released (turn open), disappears on complete ─

test.describe('E2b — badge timing: appears and disappears around the review window', () => {
  test.beforeEach(async ({ page }) => {
    await baseSetup(page);
    await mockDeckWithSpec(page, 2);
  });

  test('badge appears in spec header once all positions released (turn still open)', async ({ page }) => {
    await openSpecPane(page);

    // Precondition: spec has 2 slides, nothing released, badge absent.
    await expect(badge(page)).not.toBeVisible();

    await sendAndWaitForStream(page, 'Rebuild the deck');

    // Nothing released yet and the turn is open: badge must still be off.
    // (This is what S4 — inverting the zero guard — reddens.)
    await expect(badge(page)).not.toBeVisible();

    // Chunk 1: both positions released.  No `complete` in this chunk, so the
    // turn stays genuinely open and the ON window does not close behind us.
    await pushEvents(page, [slideReadyFrame(0), slideReadyFrame(1)]);
    await expectReleasedCount(page, 2);

    // Both operands hold: all positions out, turn still open.
    await expect(generatingText(page)).toBeVisible();
    await expect(badge(page)).toBeVisible({ timeout: 5000 });

    await closeStream(page);
  });

  test('badge disappears once the turn completes', async ({ page }) => {
    await openSpecPane(page);
    await sendAndWaitForStream(page, 'Rebuild the deck');

    // Chunk 1: all positions released, turn still open → badge ON.  Asserting
    // the ON state FIRST is what stops this test passing because the badge was
    // never rendered at all (its previous failure mode).
    await pushEvents(page, [slideReadyFrame(0), slideReadyFrame(1)]);
    await expectReleasedCount(page, 2);
    await expect(badge(page)).toBeVisible({ timeout: 5000 });

    // Chunk 2, a separate network chunk at a time we choose: the turn completes.
    await pushEvents(page, [completeFrame()]);
    await closeStream(page);

    // "• Generating..." gone means isGenerating flipped to false.
    await expect(generatingText(page)).not.toBeVisible({ timeout: 15000 });

    // The released positions are still all out (the complete handler does not
    // touch them — asserted, so "badge off" cannot be explained by a reset),
    // so the ONLY reason the badge may now be off is the turn being over.
    await expectReleasedCount(page, 2);
    await expect(badge(page)).not.toBeVisible();
  });
});

// ── Test C: mid-build — badge absent when not all positions released ──────────

test.describe('E2b — mid-build: badge absent when fewer positions released than spec', () => {
  test.beforeEach(async ({ page }) => {
    await baseSetup(page);
    await mockDeckWithSpec(page, 3);
  });

  test('badge absent at 2 of 3 released, and appears when the third lands', async ({ page }) => {
    await openSpecPane(page);
    await sendAndWaitForStream(page, 'Partial rebuild');

    // Chunk 1: 2 of 3 positions released, turn still open.  A formula that
    // ignored the spec-length check (`releasedPositions.size > 0 &&
    // isGenerating`) would light the badge here.
    await pushEvents(page, [slideReadyFrame(0), slideReadyFrame(1)]);
    await expectReleasedCount(page, 2);
    await expect(generatingText(page)).toBeVisible();

    // Mid-build: the badge must be OFF while a position is still outstanding.
    await expect(badge(page)).not.toBeVisible();

    // Chunk 2: the last position lands.  POSITIVE CONTROL — the badge must now
    // appear.  Without this half, the absence assertion above would be
    // satisfied by a badge that can never render (which is exactly how this
    // test used to pass while the feature was invisible).
    await pushEvents(page, [slideReadyFrame(2)]);
    await expectReleasedCount(page, 3);
    await expect(badge(page)).toBeVisible({ timeout: 5000 });

    await pushEvents(page, [completeFrame()]);
    await closeStream(page);
  });
});

// ── Test D: the between-turn reset of releasedPositions — BEHAVIOURAL ─────────
//
// I1 from the whole-branch review.  `setReleasedPositions(new Set())` in the
// onGenerationStart wrapper (AppLayout.tsx) was guarded only by a source-text
// match in slideReadyEvent.test.ts (`/setReleasedPositions\(new Set\(\)\)/`).
// That guard is COMMENT-SATISFIABLE: commenting the call out while leaving the
// matched text in the comment left the whole vitest suite green.  It is the same
// lesson E0's fix-round-3 applied to two other patterns in that same file and
// missed on this third one.
//
// The failure it must catch is user-visible and lasts a whole build: without the
// reset, turn N+1 starts with turn N's positions still in the set, so whenever
// turn N released as many positions as the spec had slides, the badge reads
// "Reviewing arc" from turn N+1's very FIRST frame — the flag says "reviewing"
// for the entire build, which is precisely what §7.4 exists to prevent.
//
// This is the cross-turn e2e the review names as one of the two acceptable
// fixes.  A pure-helper extraction would not do: the sabotage removes the CALL,
// so a test of the callee stays green.  Only running two turns can see it.
//
// Sabotage (S5): comment out `setReleasedPositions(new Set())` in the
// onGenerationStart wrapper, leaving its text present inside the comment.
// Expected: vitest stays green (proving the old guard is comment-satisfiable)
// and THIS test goes red at the turn-2 assertions.

test.describe('E2b/I1 — releasedPositions resets between turns', () => {
  test.beforeEach(async ({ page }) => {
    await baseSetup(page);
    await mockDeckWithSpec(page, 2);
  });

  test('turn 2 starts with no released positions, so the badge is off on its first frame', async ({ page }) => {
    await openSpecPane(page);

    // ── Turn 1: release both positions, then complete the turn. ──────────────
    await sendAndWaitForStream(page, 'Build the deck', 1);
    await pushEvents(page, [slideReadyFrame(0), slideReadyFrame(1)]);
    await expectReleasedCount(page, 2);
    // The badge is ON here: this is the state that must NOT survive the turn.
    await expect(badge(page)).toBeVisible({ timeout: 5000 });
    await pushEvents(page, [completeFrame()]);
    await closeStream(page);
    await expect(generatingText(page)).not.toBeVisible({ timeout: 15000 });
    // Turn 1 left the set full — the precondition for the defect.
    await expectReleasedCount(page, 2);

    // ── Turn 2: a new turn opens, and nothing has been released in it yet. ───
    await sendAndWaitForStream(page, 'Rebuild the deck again', 2);

    // The user-visible consequence FIRST, because it is the symptom: the flag
    // must NOT read "Reviewing arc" on turn 2's first frame.  The spec still has
    // 2 slides and the turn is open, so without the reset this is exactly
    // 2 === 2 && true → badge ON for the whole of the next build.
    await expect(generatingText(page)).toBeVisible();
    await expect(badge(page)).not.toBeVisible();

    // Then the mechanism: the released set was emptied by the reset.
    await expectReleasedCount(page, 0);

    await pushEvents(page, [completeFrame()]);
    await closeStream(page);
  });
});
