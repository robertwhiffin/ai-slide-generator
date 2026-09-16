/**
 * E2 — findings drawer e2e spec.
 *
 * The existing slide-viewer.spec.ts (after the E2 window-injection removal)
 * already covers: findings render from the API response, scoping by slideIndex,
 * unseen indicator, dismiss, and fixed/open status rendering.
 *
 * This spec adds the three assertions that slide-viewer.spec.ts does NOT exercise:
 *
 *   1. The window.__TELLR_TEST_FINDINGS__ fixture path is GONE — the old injection
 *      mechanism never fires, so no window global leaks findings through.
 *
 *   2. A finding travels with its slide across a reorder: after a reorder the
 *      finding appears on the slide's NEW position, not its old one.
 *
 *   3. Apply fires a real chat request (not console.info) — the handler is wired
 *      to handleSendMessage in AppLayout.
 *
 * Sabotage targets documented inline.
 *
 * Known-failing specs (not ours): 3 × slide-surface-fidelity (in-iframe computed
 * styles), 11 × deck-integrity (no local backend), 1 × export-ui (isolation).
 */
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import type { SlideFinding } from '../../src/types/finding';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

// ── helpers ───────────────────────────────────────────────────────────────────

async function setupSession(page: import('@playwright/test').Page) {
  await setupMocks(page);
  await mockSessionWithSlides(page);

  // Empty contributors list → lock granted immediately → readOnly=false.
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ contributors: [] }),
    }),
  );
}

async function openDeck(page: import('@playwright/test').Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
  await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
}

async function goToSlide(page: import('@playwright/test').Page, index: number) {
  await page.getByTestId(`ribbon-thumb-${index}`).click();
  await expect(page.getByTestId(`ribbon-thumb-${index}`))
    .toHaveAttribute('data-current', 'true');
}

// ── Test 1: window.__TELLR_TEST_FINDINGS__ is inert ──────────────────────────
//
// Sabotage target: re-add the window-injection reading back to AppLayout.
// If AppLayout reads window.__TELLR_TEST_FINDINGS__ again, this test goes red.

test.describe('findings-drawer — window global is gone', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test('injecting window.__TELLR_TEST_FINDINGS__ does not populate the drawer', async ({ page }) => {
    // Inject a finding that should NOT appear (slideIndex 0 with a unique id).
    const sentinel: SlideFinding = {
      id: 'sentinel-window-global',
      slideIndex: 0,
      category: 'content',
      criterion: 'brief_not_delivered',
      message: 'SHOULD NOT APPEAR: injected via window global',
      objective: false,
      status: 'open',
      seen: false,
    };

    await page.addInitScript((f) => {
      (window as unknown as { __TELLR_TEST_FINDINGS__: typeof f }).__TELLR_TEST_FINDINGS__ = [f];
    }, sentinel);

    await openDeck(page);

    // The mockSlidesResponse has no findings at slideIndex 0 (f1/f2 are at slideIndex 1).
    // The sentinel above would have appeared on slide 0 in the old implementation.
    // It must NOT appear — the window global path is dead.
    await expect(page.getByTestId('drawer-empty')).toBeVisible();
    await expect(page.getByTestId('finding-sentinel-window-global')).toHaveCount(0);
  });
});

// ── Test 2: finding travels with its slide across a reorder ──────────────────
//
// §F3's non-obvious property (and the 0a defect): findings are keyed to the
// slide by content hash (reflected in the id), not by position.  After a reorder
// the server returns findings with updated slideIndex values.  The frontend must
// render each finding on the slide its updated slideIndex says — not its original
// position.
//
// This test simulates the post-reorder state: the deck is reloaded with the
// finding's slideIndex updated.  Verified by navigating to both positions and
// checking which one has the finding.
//
// Sabotage target: hard-code the finding to always show on slideIndex 0 in
// SlideViewer (e.g. `f.slideIndex === 0` instead of `f.slideIndex === currentIndex`).
// The test goes red because the finding appears on slide 0 after the reorder too.

test.describe('findings-drawer — reorder travels with the slide', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test('finding renders on slide 1 when slideIndex is 1 (post-reorder state)', async ({ page }) => {
    // Simulate the post-reorder API response: the finding has moved to slideIndex 1.
    // This mirrors what the server returns after slide 0 is moved to position 1.
    const postReorderFinding: SlideFinding = {
      id: 'reorder-test-f1',
      slideIndex: 1,       // was on slide 0 before the reorder
      category: 'content',
      criterion: 'brief_not_delivered',
      message: 'This finding moved with its slide to position 1.',
      objective: false,
      status: 'open',
      seen: false,
    };

    await page.route(
      apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`),
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: TEST_SESSION_ID,
          slide_deck: { ...mockSlidesResponse.slide_deck, findings: [postReorderFinding] },
        }),
      }),
    );

    await openDeck(page);

    // Slide 0 must be empty (finding is at slideIndex 1 after the reorder).
    await expect(page.getByTestId('drawer-empty')).toBeVisible();

    // Navigate to slide 1.
    await goToSlide(page, 1);

    // Finding must appear on slide 1.
    await expect(page.getByTestId('finding-reorder-test-f1')).toBeVisible();
  });
});

// ── Test 3: Apply fires a real chat request ───────────────────────────────────
//
// Verifies that onApplyFinding is wired to handleSendMessage in AppLayout,
// not console.info.  The handler sends a POST to /api/chat/stream.
//
// Sabotage target: put console.info back as the onApplyFinding handler in
// AppLayout.  The captured chatBodies array stays empty and the test fails.

test.describe('findings-drawer — Apply handler wired to chat', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test('clicking Apply sends a chat request containing the finding message', async ({ page }) => {
    // One open finding on slideIndex 1 (f2 from mockFindings).
    const chatBodies: string[] = [];
    await page.route(apiPath('/api/chat/stream'), (route) => {
      chatBodies.push(route.request().postData() ?? '');
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"complete","message":"done"}\n\n',
      });
    });

    await openDeck(page);

    // Navigate to slide 1 where f2 (open) lives.
    await goToSlide(page, 1);
    await expect(page.getByTestId('finding-f2')).toBeVisible();

    // Click Apply on f2.
    await page.getByTestId('finding-apply-f2').click();

    // A real chat request must have been sent.
    await expect.poll(() => chatBodies.length, { timeout: 5000 }).toBeGreaterThan(0);

    // The request body must contain the session_id (not a console.info call).
    const body = JSON.parse(chatBodies[0]);
    expect(body).toHaveProperty('session_id', TEST_SESSION_ID);
    // The message must reference the finding's text.
    expect(body.message).toContain('35%');  // f2's message is 'The 35% figure is not supported...'
  });
});
