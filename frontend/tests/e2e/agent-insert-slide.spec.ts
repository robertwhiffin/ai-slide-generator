/**
 * #314 — the deck after an "add a slide" turn, on the SSE transport.
 *
 * An insert shifts every later slide one place down. The client has no
 * insert-aware code (plan D5): it learns of the shift from the deck refetch that
 * ChatPanel's `complete` handler already does. This spec pins that end state in a
 * real browser:
 *
 *   - the viewer holds 4 slides;
 *   - the ribbon shows NEW at the second slot and B at the third;
 *   - the Spec view labels NEW's brief "Slide 2";
 *   - B's finding follows B to the third slide and leaves the second.
 *
 * Start: a 3-slide deck [A, B, C] with one finding stamped on B (slideIndex 1).
 * The turn "Add a slide after slide 1" delivers `slide_ready` for position 1,
 * then `complete` carrying the shifted deck, the way production does
 * (`chat_service.py`, graph path: `slides=self.get_slides(session_id)`). From
 * the moment the turn is requested, the mocked `GET .../slides` serves that same
 * shifted deck, with a higher version, deck_spec positions 0-3 and B's finding
 * at slideIndex 2.
 *
 * NOT asserted, on purpose: the mid-turn view. `slide_ready` for position 1
 * replaces B in the client until `complete` arrives. That is a known limit of
 * D5, not the behaviour under test.
 *
 * SSE only. The polling transport cannot be forced on localhost (see
 * incremental-slide-delivery.spec.ts), and Task 7 pins it at the route.
 *
 * Sabotage (the product, not the mock): remove the `onSlidesGenerated` calls
 * from ChatPanel's `complete` handler. The client then keeps its mid-turn view,
 * [A, NEW, C] with B's finding still on the second slide, and this spec goes
 * red. Swapping the refetch for `event.slides` stays green by design: both are
 * the server's final deck.
 */
import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import type { SlideFinding } from '../../src/types/finding';
import type { DeckSpec, SlideDeck, SlideSpec } from '../../src/types/slide';

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Each slide's HTML carries a `data-marker`, so a frame's content names its slide. */
function slideHtml(marker: string, heading: string): string {
  return `<div class="slide-container"><h1 data-marker="${marker}">${heading}</h1></div>`;
}

/** Slide rows as the server stores them. slide_id is the slide's identity and survives the shift. */
const ROW_A = { slide_id: 'slide-a', html: slideHtml('A', 'Churn is up'), scripts: '', content_hash: 'hash-a' };
const ROW_B = { slide_id: 'slide-b', html: slideHtml('B', 'The signal arrives late'), scripts: '', content_hash: 'hash-b' };
const ROW_C = { slide_id: 'slide-c', html: slideHtml('C', 'Fund the pipeline'), scripts: '', content_hash: 'hash-c' };
const ROW_NEW = { slide_id: 'slide-new', html: slideHtml('NEW', 'Churn by region'), scripts: '', content_hash: 'hash-new' };

/** Slide briefs. No text here may contain "Slide <n>", so the label assertion reads only the label. */
const SPEC_A: Omit<SlideSpec, 'position'> = {
  purpose: 'Open on the headline churn number.',
  content_brief: 'Title: the churn rate for the quarter.',
  assumes: 'Nothing; this opens the deck.',
  hands_off: 'The reader knows the number.',
  data_references: [],
};
const SPEC_B: Omit<SlideSpec, 'position'> = {
  purpose: 'Show the signal arrives after the renewal date.',
  content_brief: 'The lag between the leading indicator and renewal.',
  assumes: 'The reader accepts the churn number.',
  hands_off: 'The reader sees the problem is timing.',
  data_references: [],
};
const SPEC_C: Omit<SlideSpec, 'position'> = {
  purpose: 'Close on the two-engineer ask.',
  content_brief: 'Closing: the ask, scoped to one quarter.',
  assumes: 'The reader accepts the timing problem.',
  hands_off: 'A decision the reader can make in the room.',
  data_references: [],
};
const SPEC_NEW: Omit<SlideSpec, 'position'> = {
  purpose: 'Break the churn number down by region.',
  content_brief: 'A regional table of churn, worst region first.',
  assumes: 'The reader knows the headline number.',
  hands_off: 'The reader knows where churn concentrates.',
  data_references: [],
};

function deckSpec(slides: Array<Omit<SlideSpec, 'position'>>): DeckSpec {
  return {
    title: 'Renewal risk',
    audience: 'Regional sales leadership.',
    purpose: 'Fund the early-warning pipeline.',
    argument: 'Churn is predictable a quarter ahead.',
    call_to_action: 'Approve two engineers for one quarter.',
    narrative_arc: ['The number', 'The cause', 'The ask'],
    design_contract: { design_system_id: null, template_id: null, slide_style_id: null },
    resolved_data: { synthesis: '', figures: [], gaps: [] },
    slides: slides.map((s, position) => ({ ...s, position })),
  };
}

/** The one finding, stamped on B. Its id is B's; only its slideIndex moves. */
const B_FINDING_ID = 'insert-finding-on-b';
const B_FINDING: SlideFinding = {
  id: B_FINDING_ID,
  slideIndex: 1,
  category: 'content',
  criterion: 'source_contradiction',
  message: 'The lag figure is not supported by the cited table.',
  objective: true,
  status: 'open',
  seen: false,
};

function deck(
  rows: Array<typeof ROW_A>,
  version: number,
  findings: SlideFinding[],
  spec: DeckSpec,
): SlideDeck {
  return {
    title: 'Renewal risk',
    slide_count: rows.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: rows.map((row, index) => ({ index, ...row })),
    html_content: rows.map((row) => row.html).join('\n'),
    version,
    findings,
    deck_spec: spec,
  };
}

const DECK_BEFORE = deck(
  [ROW_A, ROW_B, ROW_C],
  3,
  [B_FINDING],
  deckSpec([SPEC_A, SPEC_B, SPEC_C]),
);

const DECK_AFTER = deck(
  [ROW_A, ROW_NEW, ROW_B, ROW_C],
  4,
  [{ ...B_FINDING, slideIndex: 2 }],
  deckSpec([SPEC_A, SPEC_NEW, SPEC_B, SPEC_C]),
);

/**
 * The insert turn's SSE body: the assistant's reply, `slide_ready` for the new
 * slide at position 1 (slide_cursor = position + 1, as event_emitter.py stamps
 * it), then `complete` carrying the shifted deck.
 */
function buildInsertTurnSSE(): string {
  const events = [
    { type: 'assistant', content: 'Added a slide on churn by region after slide 1.' },
    {
      type: 'slide_ready',
      position: 1,
      html: ROW_NEW.html,
      scripts: '',
      slide_cursor: 2,
      metadata: { node: 'release' },
    },
    { type: 'complete', slides: DECK_AFTER, metadata: { engine_mode: 'graph' } },
  ];
  return events.map((e) => 'data: ' + JSON.stringify(e) + '\n\n').join('');
}

// ── Shared setup ──────────────────────────────────────────────────────────────

async function setupInsertTurn(page: Page) {
  await setupMocks(page);
  await mockSessionWithSlides(page);

  // Empty contributors list → AppLayout grants the editing lock at once, so the
  // chat input is enabled.
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ contributors: [] }),
    }),
  );

  // The server's deck. It flips to the shifted deck when the turn is requested,
  // because the turn commits the shift on the server. An explicit flip, not a
  // call counter: how many times the app reads getSlides is not under test.
  const server: { deck: SlideDeck } = { deck: DECK_BEFORE };
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`),
    (route, request) => {
      if (request.method() !== 'GET') { route.fallback(); return; }
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: TEST_SESSION_ID, slide_deck: server.deck }),
      });
    },
  );

  await page.route(apiPath('/api/chat/stream'), (route) => {
    server.deck = DECK_AFTER;
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: buildInsertTurnSSE(),
    });
  });
}

async function openDeck(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
  await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
  await expect(page.getByTestId('chat-input')).toBeEnabled({ timeout: 15000 });
}

async function goToSlide(page: Page, index: number) {
  await page.getByTestId(`ribbon-thumb-${index}`).click();
  await expect(page.getByTestId(`ribbon-thumb-${index}`)).toHaveAttribute('data-current', 'true');
}

/** A marker inside one ribbon thumbnail's preview frame. */
function thumbMarker(page: Page, index: number, marker: string) {
  return page
    .getByTestId(`ribbon-thumb-${index}`)
    .locator('iframe')
    .contentFrame()
    .locator(`[data-marker="${marker}"]`);
}

/** A marker inside the main stage frame (the current slide). */
function stageMarker(page: Page, marker: string) {
  return page.getByTestId('slide-stage-frame').contentFrame().locator(`[data-marker="${marker}"]`);
}

const allThumbs = (page: Page) => page.getByTestId(/^ribbon-thumb-\d+$/);

// ── The test ──────────────────────────────────────────────────────────────────

test.describe('#314 — the deck after an insert turn (SSE)', () => {
  test.beforeEach(async ({ page }) => {
    await setupInsertTurn(page);
  });

  test('the refetched deck shows the new slide at slot 2 and B, with its finding, at slot 3', async ({ page }) => {
    await openDeck(page);

    // Precondition: the starting deck is [A, B, C] with B's finding on the
    // second slide. Without this, the end-state assertions could pass against
    // a fixture that never started where the plan says.
    await expect(allThumbs(page)).toHaveCount(3);
    await expect(thumbMarker(page, 1, 'B')).toHaveCount(1);
    await goToSlide(page, 1);
    await expect(page.getByTestId(`finding-${B_FINDING_ID}`)).toBeVisible();

    await page.getByTestId('chat-input').fill('Add a slide after slide 1');
    await page.getByRole('button', { name: 'Send' }).click();

    // 4 slides. Before `complete` the client holds 3 (slide_ready replaced B
    // at index 1), so 4 is only reachable through the end-of-turn refetch.
    await expect(allThumbs(page)).toHaveCount(4, { timeout: 15000 });

    // The ribbon: NEW at the second slot, B at the third, C at the fourth.
    await expect(thumbMarker(page, 1, 'NEW')).toHaveCount(1);
    await expect(thumbMarker(page, 1, 'B')).toHaveCount(0);
    await expect(thumbMarker(page, 2, 'B')).toHaveCount(1);
    await expect(thumbMarker(page, 3, 'C')).toHaveCount(1);

    // The feedback drawer: B's finding is on the third slide (which is B)...
    await goToSlide(page, 2);
    await expect(stageMarker(page, 'B')).toHaveCount(1);
    await expect(page.getByTestId(`finding-${B_FINDING_ID}`)).toBeVisible();

    // ...and not on the second slide, which is now NEW.
    await goToSlide(page, 1);
    await expect(stageMarker(page, 'NEW')).toHaveCount(1);
    await expect(page.getByTestId('drawer-empty')).toBeVisible();
    await expect(page.getByTestId(`finding-${B_FINDING_ID}`)).toHaveCount(0);

    // The Spec view: NEW's brief is labelled "Slide 2", and B's "Slide 3".
    await page.getByTestId('view-toggle-spec').click();
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await expect(page.getByTestId(/^spec-slide-\d+$/)).toHaveCount(4);

    const newEntry = page.getByTestId(/^spec-slide-\d+$/).filter({ hasText: SPEC_NEW.purpose });
    await expect(newEntry).toHaveCount(1);
    await expect(newEntry.getByText(/^Slide 2$/)).toBeVisible();

    const bEntry = page.getByTestId(/^spec-slide-\d+$/).filter({ hasText: SPEC_B.purpose });
    await expect(bEntry).toHaveCount(1);
    await expect(bEntry.getByText(/^Slide 3$/)).toBeVisible();
  });
});
