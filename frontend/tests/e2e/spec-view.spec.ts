/**
 * E1 — the spec view toggle, end to end.
 *
 * The component test (src/components/SpecView/SpecView.test.tsx) covers what
 * SpecView renders.  This spec covers what only a real browser can show: that the
 * toggle switches panels WITHOUT unmounting either of them, that the conversation
 * and an in-flight stream survive the round trip, that dismissed findings survive
 * it, that spec visibility rides deck visibility, and that nothing about the view
 * reaches a request body.
 *
 * THE NO-REMOUNT WITNESS.  Several tests stamp `data-e2e-witness` onto a DOM node
 * before toggling and look for it afterwards.  React never removes an attribute it
 * does not manage while reconciling the SAME element, but an unmount replaces the
 * node outright — so the attribute surviving is direct evidence the element was
 * reconciled rather than rebuilt.  It is a copy taken BEFORE the act, not a second
 * reference to the thing under test.
 *
 * Sabotage targets, all in AppLayout.tsx: replace either pane's className ternary
 * with a conditional render (`{!showSpec && <SlideViewer …>}`); make the toggle
 * call setViewMode/navigate instead of setShowSpec; put showSpec into the chat
 * request body.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import type { SlideFinding } from '../../src/types/finding';
import {
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';

// ── fixtures ──────────────────────────────────────────────────────────────────

/**
 * Compiled style content — what design system #7 / template #3 resolve to on the
 * server.  It rides the deck as `css`, so it is in scope wherever the deck is, and
 * `the spec view renders no CSS-shaped text` below is only meaningful because it
 * is genuinely present (finding 18b's reshaped assertion).
 */
const COMPILED_DECK_CSS = [
  ":root { --brand-primary: #FF3621; --brand-body: 'Brand Sans'; }",
  "@font-face { font-family: 'Brand Sans'; src: url(/assets/brand.woff2); }",
  '.slide h1 { color: var(--brand-primary); font-family: var(--brand-body); }',
  '@media (min-width: 900px) { .slide { padding: 64px; } }',
].join('\n');

/** Order matters: neither a reverse nor an alphabetical sort reproduces it. */
const NARRATIVE_ARC = [
  'Frame the problem: renewals are slipping and nobody can say which accounts.',
  'Argue the cause: the signal exists but arrives after the renewal date.',
  'Close on the ask: fund the early-warning pipeline this quarter.',
];

const DECK_SPEC = {
  title: 'Renewal risk, Q3',
  audience: 'The regional sales leadership team, who own the renewal number.',
  purpose: 'Get the early-warning pipeline funded before the Q4 renewal wave.',
  argument: 'Churn is predictable a quarter ahead, and today nobody looks.',
  call_to_action: 'Approve two engineers for one quarter to build the pipeline.',
  narrative_arc: NARRATIVE_ARC,
  design_contract: { design_system_id: 7, template_id: 3, slide_style_id: null },
  resolved_data: {
    synthesis: 'Three quarters of churn history, aggregated by region.',
    figures: [{ key: 'churn_rate', value: '11.4%', source: 'warehouse.renewals' }],
    gaps: ['No data before FY23.'],
  },
  slides: [
    {
      position: 0,
      purpose: 'Open on the number nobody can explain.',
      content_brief: 'Title slide: the headline churn rate and the quarter it lands in.',
      assumes: 'Nothing. This is the first slide.',
      hands_off: 'The reader knows the number and wants to know why.',
      data_references: ['churn_rate'],
      template_section_index: 0,
    },
    {
      position: 1,
      purpose: 'Show that the signal already exists, just too late.',
      content_brief: 'The lag between the leading indicator and the renewal date.',
      assumes: 'The reader accepts the churn number from slide 1.',
      hands_off: 'The reader believes the problem is timing, not data.',
      data_references: [],
      template_section_index: 1,
    },
    {
      position: 2,
      purpose: 'Land the ask while the cause is still fresh.',
      content_brief: 'Closing slide: the two-engineer ask, scoped to one quarter.',
      assumes: 'The reader accepts that the signal arrives too late today.',
      hands_off: 'The deck ends on a decision the reader can make in the room.',
      data_references: [],
      template_section_index: 2,
    },
  ],
};

/**
 * The spec as a later chat turn leaves it: the architect narrowed the audience and
 * collapsed the arc to two beats. Used by `the open spec pane follows a revised
 * deck_spec` — the feature's central loop.
 */
const REVISED_AUDIENCE =
  'The board only — the regional leads were briefed separately on the second turn.';

const REVISED_DECK_SPEC = {
  ...DECK_SPEC,
  audience: REVISED_AUDIENCE,
  narrative_arc: [NARRATIVE_ARC[0], NARRATIVE_ARC[2]],
};

/**
 * Two open findings on slide 0, for the dismissed-findings round trip.
 *
 * The shared `mockFindings` fixture puts its open finding on slideIndex 1, and its
 * ids are load-bearing for ~10 assertions in slide-viewer.spec.ts, so it is used
 * as-is elsewhere and not extended.
 */
const SLIDE0_FINDINGS: SlideFinding[] = [
  {
    id: 's0-dismiss-me',
    slideIndex: 0,
    category: 'content',
    criterion: 'source_contradiction',
    message: 'The churn figure is not supported by the cited table.',
    objective: true,
    status: 'open',
    seen: false,
  },
  {
    id: 's0-keep-me',
    slideIndex: 0,
    category: 'design',
    criterion: 'rogue_colour',
    message: 'The accent colour is not in the design system.',
    objective: true,
    status: 'open',
    seen: false,
  },
];

/**
 * Serve the deck WITH a spec (or, with `deckSpec: null`, as a specless deck).
 *
 * Registered after mockSessionWithSlides so Playwright's LIFO ordering puts this
 * ahead of it, and matched on pathname (apiPath) so a future query-string change
 * on getSlides cannot blind it.
 */
async function mockDeckSpec(page: Page, deckSpec: unknown) {
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSlidesResponse,
        slide_deck: {
          ...mockSlidesResponse.slide_deck,
          css: COMPILED_DECK_CSS,
          deck_spec: deckSpec,
        },
      }),
    });
  });
}

/**
 * Same as `mockDeckSpec`, but the served spec can be REVISED mid-test — the way a
 * chat turn revises it in production. Returns the setter.
 *
 * Deliberately not a call counter: AppLayout's own reads of `getSlides` (initial
 * load, and again after `complete`) would make a counter's behaviour depend on how
 * many times the app happens to fetch. An explicit flip is deterministic.
 */
async function mockRevisableDeckSpec(page: Page, initial: unknown) {
  const state: { spec: unknown } = { spec: initial };
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSlidesResponse,
        slide_deck: {
          ...mockSlidesResponse.slide_deck,
          css: COMPILED_DECK_CSS,
          deck_spec: state.spec,
        },
      }),
    });
  });
  return (next: unknown) => { state.spec = next; };
}

async function openDeck(page: Page, route: 'edit' | 'view' = 'edit') {
  await page.goto(`/sessions/${TEST_SESSION_ID}/${route}`);
  await expect(page.getByTestId('main-view-controls')).toBeVisible();
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
}

const showSpec = (page: Page) => page.getByTestId('view-toggle-spec').click();
const showSlides = (page: Page) => page.getByTestId('view-toggle-slides').click();

// ─────────────────────────────────────────────────────────────────────────────

test.describe('spec view toggle', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
    await mockDeckSpec(page, DECK_SPEC);

    // Empty contributors list → AppLayout grants the editing lock immediately,
    // so the chat input is enabled and readOnly is false.
    await page.route(
      apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`),
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ contributors: [] }),
      }),
    );

    // Findings are delivered through mockSlidesResponse.slide_deck.findings
    // (set in session-helpers.ts) — no window injection needed.
  });

  // ── the switch itself ──────────────────────────────────────────────────────

  test('the toggle switches between the slides and the spec', async ({ page }) => {
    await openDeck(page);
    await expect(page.getByTestId('spec-view')).toBeHidden();

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await expect(page.getByTestId('slide-viewer')).toBeHidden();

    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('spec-view')).toBeHidden();
  });

  test('the toggle does not navigate — the URL is unchanged', async ({ page }) => {
    // A ViewMode entry would call navigate(). The URL staying put is the
    // observable difference between local state and a route change.
    await openDeck(page);
    const before = page.url();

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();

    expect(page.url()).toBe(before);
  });

  // ── what the spec pane shows ───────────────────────────────────────────────

  test('the deck-level fields render', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);

    await expect(page.getByTestId('spec-audience')).toContainText(DECK_SPEC.audience);
    await expect(page.getByTestId('spec-purpose')).toContainText(DECK_SPEC.purpose);
    await expect(page.getByTestId('spec-argument')).toContainText(DECK_SPEC.argument);
    await expect(page.getByTestId('spec-call-to-action'))
      .toContainText(DECK_SPEC.call_to_action);
  });

  test('the open spec pane follows a revised deck_spec after a chat turn', async ({ page }) => {
    // THE FEATURE'S CENTRAL LOOP, and it had no guard. The spec is read-only, so a
    // chat turn is the ONLY thing that ever changes it: the user asks the architect
    // to narrow the audience, the deck comes back, and the spec pane — still open —
    // must show the new plan rather than the one it first rendered.
    //
    // The whole production path runs here: chat stream -> `complete` carrying
    // slides -> ChatPanel re-reads getSlides -> onSlidesGenerated ->
    // setSlideDeckGated -> SpecView's props change. A SpecView that latched its
    // first non-null spec passes every other test in this file and fails here.
    const revise = await mockRevisableDeckSpec(page, DECK_SPEC);
    await page.route(apiPath('/api/chat/stream'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type": "assistant", "content": "Narrowed the audience to the board."}\n\n'
          + `data: {"type": "complete", "slides": ${JSON.stringify(mockSlidesResponse.slide_deck)}}\n\n`,
      });
    });

    await openDeck(page);
    await showSpec(page);
    await expect(page.getByTestId('spec-audience')).toContainText(DECK_SPEC.audience);

    // The architect's next commit lands on the server...
    revise(REVISED_DECK_SPEC);
    // ...and the user asks for it through the one write path.
    await page.getByTestId('chat-input').fill('narrow the audience to the board only');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByTestId('spec-audience'))
      .toContainText(REVISED_AUDIENCE, { timeout: 15000 });
    // The superseded value is GONE, not merely joined by the new one.
    await expect(page.getByTestId('spec-audience')).not.toContainText(DECK_SPEC.audience);
    // And the pane did not switch itself back to the slides on the deck update:
    // `showSpec` is the user's choice, not a function of the deck.
    await expect(page.getByTestId('spec-view')).toBeVisible();
  });

  test('the narrative arc renders in order', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);

    // allTextContents() is in document order, and toEqual on an array is
    // order-sensitive — a set comparison would accept any permutation, which is
    // the defect this guards. An unordered arc is a different deck.
    const beats = await page.getByTestId(/^spec-arc-beat-/).allTextContents();
    expect(beats).toEqual(NARRATIVE_ARC);
  });

  test('each slide brief renders with its assumes / hands off contract', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);

    for (const slide of DECK_SPEC.slides) {
      await expect(page.getByTestId(`spec-slide-purpose-${slide.position}`))
        .toContainText(slide.purpose);
      await expect(page.getByTestId(`spec-slide-assumes-${slide.position}`))
        .toContainText(slide.assumes);
      await expect(page.getByTestId(`spec-slide-hands-off-${slide.position}`))
        .toContainText(slide.hands_off);
    }
  });

  test('the slide briefs render in the order the spec gives', async ({ page }) => {
    // Its own test, because every assertion in the one above is keyed by
    // `position` and reads a label of `position + 1` — expected and actual move
    // together, so a reversal is invisible to all of them. Measured: reversing the
    // render order left 42/42 vitest and 18/18 e2e green.
    //
    // Order is meaning here for the same reason it is for the narrative arc: the
    // briefs are that arc made concrete, and a reversed list renders
    // "Slide 3, Slide 2, Slide 1" to the reader. Asserted as a SEQUENCE, not a set.
    await openDeck(page);
    await showSpec(page);

    const rendered = await page.getByTestId(/^spec-slide-\d+$/)
      .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.testid));

    // Spelled out rather than derived from DECK_SPEC.slides: an expectation built
    // from the same array the component maps over would move with a fixture
    // reorder, and both sides moving together is no assertion at all (§32).
    expect(rendered).toEqual(['spec-slide-0', 'spec-slide-1', 'spec-slide-2']);
  });

  test('the design contract shows which brand, by id', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);

    await expect(page.getByTestId('spec-design-system-id')).toContainText('7');
    await expect(page.getByTestId('spec-template-id')).toContainText('3');
  });

  test('the spec view renders no CSS-shaped text (finding 18b, reshaped)', async ({ page }) => {
    // The deck served to this page carries real compiled style content in `css`
    // (see COMPILED_DECK_CSS), which is what design system #7 resolves to. The
    // spec stores a REFERENCE precisely so no snapshot can go stale against
    // COMPILER_VERSION, so none of that content may reach the spec surface.
    expect(COMPILED_DECK_CSS).toContain('var(--');
    expect(COMPILED_DECK_CSS).toContain('@media');
    expect(COMPILED_DECK_CSS).toContain('@font-face');

    await openDeck(page);
    await showSpec(page);
    await expect(page.getByTestId('spec-slide-0')).toBeVisible();   // populated

    const text = (await page.getByTestId('spec-view').innerText()) ?? '';
    expect(text).not.toContain('var(--');
    expect(text).not.toContain('@media');
    expect(text).not.toContain('@font-face');
    expect(text.match(/\{[^{}]*:[^{}]*\}/)).toBeNull();
  });

  test('the spec view offers no editable control', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);
    // Precondition, not a second subject: an absence assertion over an empty
    // subtree passes for the wrong reason.
    await expect(page.getByTestId('spec-slide-0')).toBeVisible();

    const pane = page.getByTestId('spec-view');
    await expect(pane.locator('input')).toHaveCount(0);
    await expect(pane.locator('textarea')).toHaveCount(0);
    // `select` is an edit affordance too, and read-only here is structural rather
    // than styling — so this list must match the component test's exactly.
    await expect(pane.locator('select')).toHaveCount(0);
    await expect(pane.locator('[contenteditable]')).toHaveCount(0);
  });

  // ── Discuss ────────────────────────────────────────────────────────────────

  test('Discuss hands off to the conversation and issues no request of its own', async ({ page }) => {
    await openDeck(page);
    await showSpec(page);

    // Collapse the chat first, so expanding it is an observable effect.
    await page.getByTestId('toggle-chat-panel').click();
    await expect(page.getByTestId('chat-input')).toBeHidden();

    const requests: string[] = [];
    page.on('request', (r) => requests.push(`${r.method()} ${r.url()}`));

    await page.getByTestId('spec-discuss').click();

    await expect(page.getByTestId('chat-input')).toBeVisible();
    // Editing the spec is conversational: Discuss opens the one write path, it
    // does not become a second one.
    expect(requests.filter((r) => r.includes('/api/'))).toEqual([]);
  });

  // ── nothing is unmounted ───────────────────────────────────────────────────

  test('the conversation survives the toggle', async ({ page }) => {
    // The conversation is built LIVE here rather than restored from the messages
    // mock on purpose: refetched-on-mount history would survive a remount too, so
    // a test written against it would pass even with the defect. `messages` is
    // useState inside ChatPanel, and only in-component state proves no remount.
    const question = 'does the arc land on the ask?';
    const reply = 'It does now — slide 3 carries it.';
    await page.route(apiPath('/api/chat/stream'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: {"type": "assistant", "content": ${JSON.stringify(reply)}}\n\n`
          + 'data: {"type": "complete", "message": "done"}\n\n',
      });
    });

    await openDeck(page);
    await page.getByTestId('chat-input').fill(question);
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(question)).toBeVisible();
    await expect(page.getByText(reply)).toBeVisible({ timeout: 15000 });

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();

    await expect(page.getByText(question)).toBeVisible();
    await expect(page.getByText(reply)).toBeVisible();
  });

  test('the chat panel is reconciled across the toggle, not rebuilt', async ({ page }) => {
    // The structural half of the test above, deliberately in its own test: with
    // both in one, a red run cannot say whether the panel was rebuilt or the
    // conversation was merely lost some other way.
    await openDeck(page);
    await page.evaluate(() => {
      document.querySelector('[data-testid="chat-panel"]')
        ?.setAttribute('data-e2e-witness', 'chat');
    });

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();

    // The witness survives only if this is the SAME DOM node — a remount would
    // have built a fresh one without the attribute.
    await expect(page.locator('[data-testid="chat-panel"][data-e2e-witness="chat"]'))
      .toHaveCount(1);
  });

  test('an in-flight message stream survives the toggle', async ({ page }) => {
    // ChatPanel's unmount cleanup CANCELS the in-flight stream, so a remount
    // during the round trip means the reply below never arrives.
    const reply = 'The arc now lands on the ask.';
    await page.route(apiPath('/api/chat/stream'), async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: {"type": "assistant", "content": ${JSON.stringify(reply)}}\n\n`
          + 'data: {"type": "complete", "message": "done"}\n\n',
      });
    });

    await openDeck(page);
    await page.getByTestId('chat-input').fill('tighten the arc');
    await page.getByRole('button', { name: 'Send' }).click();

    // In flight: the request is out and the reply has not landed.
    await expect(page.getByText(reply)).toHaveCount(0);

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await showSlides(page);

    await expect(page.getByText(reply)).toBeVisible({ timeout: 15000 });
  });

  test('dismissed findings are still dismissed after toggling to the spec and back', async ({ page }) => {
    // `dismissed` is useState inside SlideViewer, reset on deckKey change, so a
    // remount here resurrects every dismissed finding.
    //
    // BOTH findings sit on slideIndex 0, not on the shared fixture's slideIndex 1.
    // That matters: a remount also resets ViewerContext's currentIndex to 0, so
    // with the findings on slide 1 the resurrected finding would be off-screen and
    // this test would only ever fail on its control assertion — the defect would be
    // detected, but not the one named in the test's title. Measured, by sabotage.
    //
    // Findings are now delivered through the API (E2 wired the real path).
    // Override the slides endpoint for this test to return SLIDE0_FINDINGS.
    // Registered AFTER mockSessionWithSlides so Playwright's LIFO ordering makes
    // this more specific route take precedence.
    await page.route(
      apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`),
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: TEST_SESSION_ID,
          slide_deck: { ...mockSlidesResponse.slide_deck, findings: SLIDE0_FINDINGS },
        }),
      }),
    );

    await openDeck(page);
    await expect(page.getByTestId('finding-s0-dismiss-me')).toBeVisible();
    await expect(page.getByTestId('finding-s0-keep-me')).toBeVisible();

    await page.getByTestId('finding-dismiss-s0-dismiss-me').click();
    await expect(page.getByTestId('finding-s0-dismiss-me')).toHaveCount(0);

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();

    // The dismissed one stays dismissed, and the other is still there — so this is
    // not passing because the drawer emptied for some other reason.
    await expect(page.getByTestId('finding-s0-dismiss-me')).toHaveCount(0);
    await expect(page.getByTestId('finding-s0-keep-me')).toBeVisible();
  });

  test('the slide viewer is reconciled across the toggle, not rebuilt', async ({ page }) => {
    // The structural half of the test above, in its own test for the same reason.
    await openDeck(page);
    await page.evaluate(() => {
      document.querySelector('[data-testid="slide-viewer"]')
        ?.setAttribute('data-e2e-witness', 'viewer');
    });

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();

    await expect(page.locator('[data-testid="slide-viewer"][data-e2e-witness="viewer"]'))
      .toHaveCount(1);
  });

  // ── the view is a hint, never a mode ───────────────────────────────────────

  test('the toggle state never reaches a request body', async ({ page }) => {
    // Intent comes from language, not view state: "tighten the arc" edits the
    // spec and "make slide 5 bolder" edits the slide whichever panel is open. So
    // a message sent FROM the spec view must be byte-identical in shape to one
    // sent from the slides view.
    const bodies: string[] = [];
    const chatBodies: string[] = [];

    await page.route(apiPath('/api/chat/stream'), (route) => {
      chatBodies.push(route.request().postData() ?? '');
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type": "complete", "message": "done"}\n\n',
      });
    });
    page.on('request', (r) => {
      const data = r.postData();
      if (data) bodies.push(data);
    });

    await openDeck(page);
    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();

    await page.getByTestId('chat-input').fill('tighten the arc');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect.poll(() => chatBodies.length).toBeGreaterThan(0);

    await showSlides(page);

    // Vacuity guard: a scan over zero bodies proves nothing.
    expect(bodies.length).toBeGreaterThan(0);

    for (const token of ['showSpec', 'show_spec', 'specView', 'spec_view', 'viewMode', 'view_mode']) {
      const leaked = bodies.filter((b) => b.includes(token));
      expect(leaked, `"${token}" reached a request body`).toEqual([]);
    }

    // And nothing NEW at all on the chat request: an unexpected key is how view
    // state would arrive under a name this list does not anticipate.
    const ALLOWED = ['session_id', 'message', 'slide_context', 'image_ids', 'agent_config'];
    const unexpected = Object.keys(JSON.parse(chatBodies[0]))
      .filter((key) => !ALLOWED.includes(key));
    expect(unexpected, 'the chat request body gained a key').toEqual([]);
  });

  // ── specless decks ─────────────────────────────────────────────────────────

  test('a specless deck renders an empty state rather than crashing', async ({ page }) => {
    // Pre-cutover decks and MCP-built decks have no spec; the read path serves
    // deck_spec as JSON null for them.
    await mockDeckSpec(page, null);
    await openDeck(page);
    await showSpec(page);

    await expect(page.getByTestId('spec-view-empty')).toBeVisible();
    await expect(page.getByTestId('spec-audience')).toHaveCount(0);

    // Still alive: the toggle works both ways and the viewer comes back.
    await showSlides(page);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// §7.5 — spec visibility EQUALS deck visibility
// ─────────────────────────────────────────────────────────────────────────────

test.describe('spec visibility rides deck visibility', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
    await mockDeckSpec(page, DECK_SPEC);
  });

  test('someone on the read-only route sees the spec', async ({ page }) => {
    // The spec rides get_slide_deck's dict, so anyone who can read the deck can
    // read the spec: contributors and read-only viewer links included. Nothing
    // extra is granted and nothing extra is withheld.
    await openDeck(page, 'view');
    await expect(page.getByTestId('chat-input')).toBeDisabled();   // genuinely read-only

    await showSpec(page);
    await expect(page.getByTestId('spec-view')).toBeVisible();
    await expect(page.getByTestId('spec-audience')).toContainText(DECK_SPEC.audience);
  });

  test('the permission gate lives in the route, not in get_slide_deck', async () => {
    // E1 adds NO permission code — that is the point of §7.5. What must not
    // silently disappear is the gate the spec rides behind, and it is in the
    // route handler: get_slide_deck itself does not check permissions, so
    // asserting there would pin a check that does not exist.
    const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
    const routes = readFileSync(`${repoRoot}src/api/routes/slides.py`, 'utf8');

    const getSlides = routes.slice(routes.indexOf('async def get_slides('));
    expect(getSlides, 'async def get_slides( not found in slides.py').not.toEqual('');

    const body = getSlides.slice(0, getSlides.indexOf('\n@router'));
    expect(
      /_require_slide_permission\(\s*session_id,\s*db,\s*PermissionLevel\.CAN_VIEW\s*\)/
        .test(body),
      'the CAN_VIEW gate is gone from the get_slides route handler. The deck spec '
      + 'rides this response, so removing the gate exposes the spec to anyone with '
      + 'a session id.',
    ).toBe(true);

    // ...and get_slide_deck is NOT where it lives, so nobody "restores" it there.
    const sessionManager = readFileSync(
      `${repoRoot}src/api/services/session_manager.py`, 'utf8',
    );
    const readPath = sessionManager.slice(sessionManager.indexOf('def get_slide_deck('));
    expect(readPath).not.toEqual('');
    expect(readPath.slice(0, readPath.indexOf('\n    def ')))
      .not.toContain('_require_slide_permission');
  });
});

