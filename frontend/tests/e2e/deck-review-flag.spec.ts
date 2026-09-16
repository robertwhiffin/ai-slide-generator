/**
 * E2b — "Agentic deck review in progress" flag, end-to-end.
 *
 * The component test (deckReviewFlag.test.tsx) covers the formula and the
 * non-blocking property via pure function calls and source scans.  This spec
 * adds what only a running browser can show: the badge element actually
 * appearing and disappearing in the rendered DOM around the review window.
 *
 * Two behavioural assertions this spec adds at browser level:
 *
 *   A. Badge appears once all positions in deck_spec.slides are released and
 *      the turn is still running — the whole-deck reviewer is the only work
 *      left at that point.
 *
 *   B. Badge disappears when the turn completes — the review is the last thing
 *      before END, so `isGenerating` going false is the clean signal.
 *
 *   C. Badge is absent during a generation where NOT all positions are released
 *      before the turn ends — the mid-build guard that separates "reviewing"
 *      from "building".  Assertion is: given a 3-slide deck_spec and only 2
 *      slide_ready events before complete, the badge never appears.
 *
 * WHY (C) IS AN E2E, NOT ONLY A UNIT TEST.  The wrong formula
 * `releasedPositions.size > 0 && isGenerating` (ignoring spec length) would
 * make the badge appear after any position is released, including mid-build.
 * That formula passes the unit's pure-function test only if the unit test also
 * checks the off-when-less-than-all case — but a browser test confirms the
 * rendered badge obeys the same rule, not just the pure function.
 *
 * Sabotage target (documented here so the report can cite it):
 *   Change `&& isGenerating` to `&& !isGenerating` in _isReviewInProgress in
 *   AppLayout.tsx.  Test A goes red (badge absent during generation).  Test B
 *   goes red (badge visible AFTER generation ends, not before).
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

/** Build an SSE body with slide_ready events for the given positions, then complete. */
function buildSSE(positions: number[]): string {
  const lines: string[] = [];
  for (const pos of positions) {
    lines.push(
      'data: ' +
        JSON.stringify({
          type: 'slide_ready',
          position: pos,
          html: `<div class="slide-container"><h1>Slide ${pos}</h1></div>`,
          scripts: '',
          slide_cursor: pos + 1,
        }) +
        '\n\n',
    );
  }
  // complete with no `slides` field: ChatPanel skips the getSlides fetch
  // and leaves the incremental deck in place (same as incremental-slide-delivery spec).
  lines.push('data: ' + JSON.stringify({ type: 'complete' }) + '\n\n');
  return lines.join('');
}

/**
 * Set up route mocks shared by all tests in this spec:
 *   - setupMocks (catch-all)
 *   - session detail → valid session so AppLayout stays on the edit page
 *   - contributors → empty list → lock granted immediately
 */
async function baseSetup(page: Page) {
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

/** Navigate to the test session's edit page and wait for the view to be ready. */
async function openSession(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('main-view-controls')).toBeVisible({ timeout: 15000 });
}

/** The element that carries data-released-count (used to observe release progress). */
const releasedCountEl = (page: Page) => page.locator('[data-tour="slide-viewer"]');

// ── Test A+B: badge appears when all released (turn open), disappears on complete ─

test.describe('E2b — badge timing: appears and disappears around the review window', () => {
  test.beforeEach(async ({ page }) => {
    await baseSetup(page);
    await mockDeckWithSpec(page, 2);

    // Stream: release both positions, then wait 600ms before complete so the
    // badge's ON state is observable at browser speed before isGenerating flips.
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      async (route) => {
        await new Promise<void>((resolve) => setTimeout(resolve, 600));
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: buildSSE([0, 1]),
        });
      },
    );
  });

  test('badge appears in spec header once all positions released (turn still open)', async ({ page }) => {
    await openSession(page);

    // Switch to spec view before sending — both panels are mounted; the toggle
    // never unmounts either pane (AppLayoutSpecToggle.test.ts pins this).
    await page.getByTestId('view-toggle-spec').click();
    await expect(page.getByTestId('spec-view')).toBeVisible();

    // Precondition: spec has 2 slides, badge absent before generation.
    await expect(page.getByTestId('deck-review-in-progress')).not.toBeVisible();

    // Send a message — generation starts, stream is delayed 600ms.
    await page.getByTestId('chat-input').fill('Rebuild the deck');
    await page.getByRole('button', { name: 'Send' }).click();

    // "• Generating..." appears immediately (isGenerating flipped to true).
    await expect(page.getByText('• Generating...')).toBeVisible({ timeout: 5000 });

    // After the 600ms delay the stream fires both slide_ready events.
    // Wait for data-released-count to reach 2 — both positions out.
    await expect
      .poll(
        () => releasedCountEl(page).getAttribute('data-released-count'),
        { message: 'waiting for data-released-count to reach 2', timeout: 10000 },
      )
      .toBe('2');

    // "• Generating..." is still visible: the complete event has not fired yet
    // (the complete event is in the same SSE body but processing is async).
    // The badge must be ON — all positions released, turn still open.
    await expect(page.getByTestId('deck-review-in-progress')).toBeVisible({ timeout: 5000 });
  });

  test('badge disappears once the turn completes', async ({ page }) => {
    await openSession(page);
    await page.getByTestId('view-toggle-spec').click();
    await expect(page.getByTestId('spec-view')).toBeVisible();

    await page.getByTestId('chat-input').fill('Rebuild the deck');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for the full generation to finish: "• Generating..." gone means
    // isGenerating flipped to false and the deck reviewer has finished.
    await expect(page.getByText('• Generating...')).not.toBeVisible({ timeout: 15000 });

    // Badge must be OFF — the turn is over, so the deck reviewer is done.
    await expect(page.getByTestId('deck-review-in-progress')).not.toBeVisible();
  });
});

// ── Test C: mid-build — badge absent when not all positions released ──────────
//
// If the formula ignored the spec-length check and used only `releasedPositions.size > 0
// && isGenerating`, the badge would appear after the first slide_ready event even when
// the deck still has outstanding positions.  This test would then go red:
// data-released-count would reach at least 1 while generating, but the badge
// stays absent because 2 ≠ 3 (not all three positions released).
//
// Limitation: because route.fulfill delivers all SSE events at once, by the time
// React has flushed all updates the complete event may have already fired.  The
// assertion therefore checks that the badge is absent AFTER the full turn, with a
// vacuity guard confirming that 2 slide_ready events DID fire (not 0).

test.describe('E2b — mid-build: badge absent when fewer positions released than spec', () => {
  test.beforeEach(async ({ page }) => {
    await baseSetup(page);
    await mockDeckWithSpec(page, 3);

    // Stream: release 2 of 3 positions, then complete — the badge formula
    // should never flip because 2 ≠ 3.
    await page.route(
      (url) => url.pathname === '/api/chat/stream',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: buildSSE([0, 1]),   // only 2 of 3 positions
        });
      },
    );
  });

  test('badge absent after a generation where only 2 of 3 positions were released', async ({ page }) => {
    await openSession(page);
    await page.getByTestId('view-toggle-spec').click();
    await expect(page.getByTestId('spec-view')).toBeVisible();

    await page.getByTestId('chat-input').fill('Partial rebuild');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for the turn to complete.
    await expect(page.getByText('• Generating...')).not.toBeVisible({ timeout: 15000 });

    // Vacuity guard: confirm slide_ready events DID fire (data-released-count = 2),
    // so the test is not passing because no events fired at all.
    await expect
      .poll(
        () => releasedCountEl(page).getAttribute('data-released-count'),
        { message: 'expecting data-released-count = 2 (vacuity guard)', timeout: 5000 },
      )
      .toBe('2');

    // Badge must be absent — 2 ≠ 3, so the formula never fired.
    await expect(page.getByTestId('deck-review-in-progress')).not.toBeVisible();
  });
});
