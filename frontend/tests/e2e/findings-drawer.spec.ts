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
 *      to handleSendMessage in AppLayout.  Since #316 the request is a plain lead
 *      (built from plainIssue) followed by the reviewer's technical message under
 *      "Reviewer's details:" (plan D4).
 *
 *   4. Discuss sends the same shape with its own lead (#316 D4).
 *
 *   5. The drawer leads with the plain message; the reviewer's technical message
 *      is not on the page until "Show details" is clicked (#316 D3).
 *
 *   6–8. In the chat, the Apply and Discuss bubbles, and a reloaded Apply-shaped
 *      user row plus a deck-review advisory row, show only the plain lead; the
 *      reviewer's text sits in a closed "Reviewer's details" <details> until its
 *      summary is clicked (#316 D14, plan Task 7).
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
import { mockFindings } from '../fixtures/findings';
import {
  mockSessionDetail,
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

// f2: the open finding on slideIndex 1 that mockSessionWithSlides serves.
const f2 = mockFindings.find((f) => f.id === 'f2')!;

// The wire separator between the plain lead and the reviewer's text (#316 D4).
// Spelled out here rather than imported from src/utils/findingText.ts, so these
// tests pin the bytes the agents receive instead of echoing the helper's output.
const REVIEWER_DETAILS = "\n\nReviewer's details:\n";

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

// Captures every POST body sent to /api/chat/stream and answers with a minimal
// complete event.  Used by the Apply and Discuss tests.
async function captureChatBodies(page: import('@playwright/test').Page): Promise<string[]> {
  const chatBodies: string[] = [];
  await page.route(apiPath('/api/chat/stream'), (route) => {
    chatBodies.push(route.request().postData() ?? '');
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'data: {"type":"complete","message":"done"}\n\n',
    });
  });
  return chatBodies;
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
      plainMessage: "This slide may not cover everything planned for it. This is a judgement call, so it was left for you to decide.",
      plainIssue: "This slide may not cover everything planned for it.",
      objective: false,
      status: 'open',
      seen: false,
    };

    await page.addInitScript((f) => {
      (window as unknown as { __TELLR_TEST_FINDINGS__: Array<typeof f> }).__TELLR_TEST_FINDINGS__ = [f];
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
      plainMessage: "This slide may not cover everything planned for it. This is a judgement call, so it was left for you to decide.",
      plainIssue: "This slide may not cover everything planned for it.",
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
// #316 D4: the message is `Please fix this on slide <n>: <plainIssue>`, then the
// separator, then the reviewer's message verbatim (the architect acts on it).  The
// lead uses plainIssue, never plainMessage: an open finding's status sentence
// ("This was not fixed automatically.") must not end up in a fix request.
//
// Sabotage targets:
//   - put console.info back as the onApplyFinding handler in AppLayout.  The
//     captured chatBodies array stays empty and the test fails.
//   - revert handleApplyFinding to the old `...review suggestion for slide N:
//     ${finding.message}` template, or build the lead from plainMessage, or drop
//     the details section.  The strict toBe fails.

test.describe('findings-drawer — Apply handler wired to chat', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test('clicking Apply sends a chat request containing the finding message', async ({ page }) => {
    // One open finding on slideIndex 1 (f2 from mockFindings).
    const chatBodies = await captureChatBodies(page);

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
    // The whole message: plain lead (1-indexed slide, plainIssue), separator, verbatim message.
    expect(body.message).toBe(
      `Please fix this on slide 2: ${f2.plainIssue}${REVIEWER_DETAILS}${f2.message}`,
    );
    // The part the user reads first carries none of the reviewer's technical text.
    const [lead] = body.message.split(REVIEWER_DETAILS);
    expect(lead).not.toContain(f2.message);
  });
});

// ── Test 4: Discuss sends the plain lead and the reviewer's details ───────────
//
// Same shape as Apply (#316 D4), with the Discuss lead.
//
// Sabotage targets: revert handleDiscussFinding to the old `...discuss this review
// finding for slide N: ${finding.message}` template, or build the lead from
// plainMessage, or route Discuss through applyFindingRequest.  The strict toBe fails.

test.describe('findings-drawer — Discuss handler wired to chat', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test("clicking Discuss sends the plain lead and the reviewer's details", async ({ page }) => {
    const chatBodies = await captureChatBodies(page);

    await openDeck(page);
    await goToSlide(page, 1);
    await expect(page.getByTestId('finding-f2')).toBeVisible();

    await page.getByTestId('finding-discuss-f2').click();

    await expect.poll(() => chatBodies.length, { timeout: 5000 }).toBeGreaterThan(0);

    const body = JSON.parse(chatBodies[0]);
    expect(body).toHaveProperty('session_id', TEST_SESSION_ID);
    expect(body.message).toBe(
      `I'd like to discuss this on slide 2: ${f2.plainIssue}${REVIEWER_DETAILS}${f2.message}`,
    );
    const [lead] = body.message.split(REVIEWER_DETAILS);
    expect(lead).not.toContain(f2.message);
  });
});

// ── Test 5: the drawer leads with the plain message ───────────────────────────
//
// #316 D3: the drawer shows plainMessage.  The reviewer's message is not in the
// DOM until the "Show details" toggle is clicked.  The post-click getByText count
// of 1 proves the pre-click count of 0 is not vacuous.
//
// Sabotage targets:
//   - render {f.message} in finding-plain-*: toHaveText(plainMessage) fails and
//     the pre-click getByText count is 1.
//   - render the details unconditionally (or hide them with CSS only): the
//     pre-click getByText count is 1.
//   - drop aria-expanded from the toggle: both attribute checks fail.

test.describe('findings-drawer — plain message first, details on request', () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  test("the drawer leads with the plain message and hides the reviewer's details until asked", async ({ page }) => {
    await openDeck(page);
    await goToSlide(page, 1);
    await expect(page.getByTestId('finding-f2')).toBeVisible();

    await expect(page.getByTestId('finding-plain-f2')).toHaveText(f2.plainMessage);

    const toggle = page.getByTestId('finding-details-toggle-f2');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toHaveText('Show details');
    await expect(page.getByText(f2.message)).toHaveCount(0);
    await expect(page.getByTestId('finding-details-f2')).toHaveCount(0);

    await toggle.click();

    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(toggle).toHaveText('Hide details');
    await expect(page.getByTestId('finding-details-f2')).toHaveText(f2.message);
    await expect(page.getByTestId('finding-details-f2')).toBeVisible();
    await expect(page.getByText(f2.message)).toHaveCount(1);
  });
});

// ── Tests 6–8: the chat bubble collapses the reviewer's details ──────────────
//
// #316 D14: Message.tsx shows only the plain lead of the two shapes this PR
// writes (a user Apply/Discuss request; an assistant deck-review advisory) and
// puts the reviewer's text in a closed native <details>
// (data-testid="message-reviewer-details", summary "Reviewer's details").  The
// sent and stored content is unchanged.  Every expected string is a literal.
//
// The closed <details> body stays in the DOM, so "hidden" is not.toBeVisible()
// paired with toHaveCount(1) on the same locator (a bare not.toBeVisible() also
// passes when the element is absent), then toBeVisible() after the summary click.
//
// Sabotage targets:
//   - render message.content instead of the parsed lead: the exact-lead
//     getByText finds no element and the technical text is visible pre-click.
//   - render the details open, or as a plain <div>: the pre-click
//     not.toBeVisible() fails.
//   - drop the assistant (advisory) branch, or bind the parsers to the wrong
//     role: the reload test's toHaveCount(2) fails.

const APPLY_LEAD = `Please fix this on slide 2: ${f2.plainIssue}`;
const DISCUSS_LEAD = `I'd like to discuss this on slide 2: ${f2.plainIssue}`;

// nodes._advisory_text for one arc_gap finding, as literals (src/domain/finding_copy.py).
const ADVISORY_LEAD_LINES = [
  'Deck review found 1 thing to look at in how the deck reads as a whole:',
  '- The story has a gap or an unexplained jump between slides.',
  "None of these were changed automatically. Reply here if you'd like any of them addressed.",
];
const ADVISORY_DETAIL = 'Slide 3 restates slide 2 instead of moving the argument on.';
const ADVISORY = `${ADVISORY_LEAD_LINES.join('\n')}${REVIEWER_DETAILS}- ${ADVISORY_DETAIL}`;

test.describe("findings-drawer — chat bubbles collapse the reviewer's details", () => {
  test.beforeEach(async ({ page }) => {
    await setupSession(page);
  });

  for (const { action, testId, lead } of [
    { action: 'Apply', testId: 'finding-apply-f2', lead: APPLY_LEAD },
    { action: 'Discuss', testId: 'finding-discuss-f2', lead: DISCUSS_LEAD },
  ]) {
    test(`${action} shows the plain lead in the chat bubble with the reviewer's details collapsed`, async ({ page }) => {
      const chatBodies = await captureChatBodies(page);

      await openDeck(page);
      await goToSlide(page, 1);
      await expect(page.getByTestId('finding-f2')).toBeVisible();

      await page.getByTestId(testId).click();
      await expect.poll(() => chatBodies.length, { timeout: 5000 }).toBeGreaterThan(0);

      const chat = page.getByTestId('chat-panel');
      await expect(chat.getByText(lead, { exact: true })).toBeVisible();

      const details = chat.getByTestId('message-reviewer-details');
      await expect(details).toHaveCount(1);
      const tech = chat.getByText(f2.message, { exact: true });
      await expect(tech).toHaveCount(1);
      await expect(tech).not.toBeVisible();

      await details.locator('summary').click();
      await expect(tech).toBeVisible();

      // Render-only: the sent content still carries the reviewer's text verbatim.
      const body = JSON.parse(chatBodies[0]);
      expect(body.message).toBe(`${lead}${REVIEWER_DETAILS}${f2.message}`);
    });
  }

  test('persisted Apply-shaped and advisory-shaped messages reload collapsed', async ({ page }) => {
    const userRow = {
      id: 1,
      role: 'user',
      content: `${APPLY_LEAD}${REVIEWER_DETAILS}${f2.message}`,
      message_type: 'user_query',
      created_at: '2026-10-19T10:00:00Z',
      metadata: null,
    };
    const adviceRow = {
      id: 2,
      role: 'assistant',
      content: ADVISORY,
      message_type: 'info',
      created_at: '2026-10-19T10:00:05Z',
      metadata: null,
    };
    // Registered after setupSession, so (LIFO) it wins over mockSessionWithSlides'
    // detail route.  apiPath matches the exact pathname, never a sub-resource.
    await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}`), (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockSessionDetail, messages: [userRow, adviceRow] }),
      });
    });

    await openDeck(page);

    const chat = page.getByTestId('chat-panel');
    const details = chat.getByTestId('message-reviewer-details');
    await expect(details).toHaveCount(2);

    // The plain leads are visible.
    await expect(chat.getByText(APPLY_LEAD, { exact: true })).toBeVisible();
    for (const line of ADVISORY_LEAD_LINES) {
      await expect(chat.getByText(line)).toBeVisible();
    }

    // Neither reviewer's text is visible until its own summary is clicked.
    const userTech = chat.getByText(f2.message, { exact: true });
    const adviceTech = chat.getByText(ADVISORY_DETAIL);
    await expect(userTech).toHaveCount(1);
    await expect(adviceTech).toHaveCount(1);
    await expect(userTech).not.toBeVisible();
    await expect(adviceTech).not.toBeVisible();

    await details.nth(0).locator('summary').click();
    await expect(userTech).toBeVisible();
    await expect(adviceTech).not.toBeVisible();

    await details.nth(1).locator('summary').click();
    await expect(adviceTech).toBeVisible();
  });
});
