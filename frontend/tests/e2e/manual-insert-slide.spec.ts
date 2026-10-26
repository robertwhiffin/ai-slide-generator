/**
 * #314 — inserting a blank slide by hand, end to end in a real browser (mocked server).
 *
 * What is pinned (plan AC1, AC2, AC3, AC5, AC6, AC10, AC13):
 *   (a) the stage toolbar's "New slide" inserts AFTER the current slide: the request is
 *       `{session_id, position}` with no `html`; the blank lands there, is selected and
 *       carries the "New" chip; its neighbours keep their content and order; its root paints
 *       the same ground as its neighbours (AC2) on a section-wrapper deck (W) and on an
 *       inline-styled deck (I), in the thumbnail and on the stage; the Spec view labels it
 *       "Blank slide" under its own number. The chip expires; the selection stays.
 *   (b) a ribbon gap: hidden at rest, revealed by hovering its strip, inside the ribbon box;
 *       gap 0 inserts before the first slide, and the last gap appends.
 *   (c) a refused insert (409) shows the server's own sentence, refetches, changes nothing.
 *   (d) viewers (`/view`) get neither the toolbar button nor the gaps.
 *   (e) the controls are disabled while a chat turn is open, and enabled once it completes.
 *   (f) mid-drag the gaps stay hidden even under the pointer, and the drop still reorders.
 *
 * The mock IS the server, by construction: `POST /api/slides` answers with the blank that
 * `blank_slide_shell(deck slides, position)` produces, read from
 * tests/fixtures/manual-insert-decks.json. tests/unit/test_manual_insert_e2e_fixture.py
 * asserts every blank there (and the busy sentence, and the blank spec entry) against the
 * production Python, so no string in this file is a hand copy of server output.
 *
 * Route order (PLAN-CORRECTIONS C20): the last route registered wins in Playwright, so the
 * `POST /api/slides` mock is registered after setupMocks / mockSessionWithSlides, and
 * matches the method.
 *
 * Gap buttons are `visibility: hidden` until their strip is hovered (ThumbnailRibbon
 * InsertGap), so every gap click hovers `ribbon-insert-k`'s parent strip first.
 *
 * SSE only: the polling transport cannot be forced on localhost (see
 * incremental-slide-delivery.spec.ts).
 *
 * Sabotage (the product, never the mock), each turns the named case red (verified in Chrome):
 *   - ribbon `onInsert` unwired in SlideViewer (gaps render, click does nothing) -> (b) both
 *   - toolbar `handleInsertSlide(currentIndex)` for `currentIndex + 1`  -> (a) W and I
 *   - `diffNewSlides` flags nothing                                     -> (a), (b) and
 *     agent-insert-slide.spec.ts
 *   - the indicator's `setCurrentIndex` skipped (chips kept)            -> (a), (b) and the agent spec
 *   - SpecView's "Blank slide" text, or its whole blank branch, removed -> (a) W and I
 *   - AppLayout stops passing `insertDisabled={isGenerating}`           -> (e)
 *   - InsertGap ignores `disabled`                                      -> (e)
 *   - `onDragStart` no longer sets `dragging`                           -> (f)
 *   - gap 0 centred like the others (its "+" pokes above the ribbon)    -> (b) gap 0
 *   - the 409 path drops its refetch, or shows a generic toast          -> (c)
 *   - the ribbon's `readOnly` gate removed                              -> (d)
 *   - `blank_slide_shell` returns the bare div, or a fixture blank is edited -> the fixture pytest
 */
import { readFileSync } from 'node:fs';
import { test, expect } from '../fixtures/base-test';
import type { FrameLocator, Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath } from '../helpers/api-route';
import { mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';
import type { DeckSpec, Slide, SlideDeck, SlideSpec } from '../../src/types/slide';

// ── Fixtures ──────────────────────────────────────────────────────────────────

type DeckName = 'W' | 'I';
type Brief = Omit<SlideSpec, 'position'>;

interface FixtureDeck {
  about: string;
  css: string;
  /** The computed background-color every content slide's root paints. */
  ground: string;
  markers: string[];
  slides: string[];
  /** `blank_slide_shell(slides, p)` for every landing position p = 0..n (pytest-checked). */
  blank_html_by_position: string[];
}

interface InsertFixture {
  /** `CONVERSATION_BUSY_DETAIL` (pytest-checked). */
  busy_detail: string;
  /** `BLANK_DECK_SPEC_ENTRY` (pytest-checked). */
  blank_spec_entry: Brief;
  decks: Record<DeckName, FixtureDeck>;
}

const FIXTURE: InsertFixture = JSON.parse(
  readFileSync(new URL('../fixtures/manual-insert-decks.json', import.meta.url), 'utf8'),
);

/** Briefs for the content slides. No text here contains "Slide <n>" or "Blank slide". */
const BRIEFS: Record<string, Brief> = {
  A: {
    purpose: 'Open on the headline churn number.',
    content_brief: 'Title: the churn rate for the quarter.',
    assumes: 'Nothing; this opens the deck.',
    hands_off: 'The reader knows the number.',
    data_references: [],
  },
  B: {
    purpose: 'Show the signal arrives after the renewal date.',
    content_brief: 'The lag between the leading indicator and renewal.',
    assumes: 'The reader accepts the churn number.',
    hands_off: 'The reader sees the problem is timing.',
    data_references: [],
  },
  C: {
    purpose: 'Close on the two-engineer ask.',
    content_brief: 'Closing: the ask, scoped to one quarter.',
    assumes: 'The reader accepts the timing problem.',
    hands_off: 'A decision the reader can make in the room.',
    data_references: [],
  },
};

const BLANK_SLIDE_ID = 'slide-blank';

function deckSpec(name: DeckName, briefs: Brief[]): DeckSpec {
  return {
    title: 'Renewal risk',
    audience: 'Regional sales leadership.',
    purpose: 'Fund the early-warning pipeline.',
    argument: 'Churn is predictable a quarter ahead.',
    call_to_action: 'Approve two engineers for one quarter.',
    narrative_arc: ['The number', 'The cause', 'The ask'],
    // W is the pinned design-system shape; I is an unpinned graph deck.
    design_contract: {
      design_system_id: name === 'W' ? 7 : null,
      template_id: null,
      slide_style_id: null,
    },
    resolved_data: { synthesis: '', figures: [], gaps: [] },
    slides: briefs.map((b, position) => ({ ...b, position })),
  };
}

function deckOf(name: DeckName, slides: Array<Omit<Slide, 'index'>>, briefs: Brief[], version: number): SlideDeck {
  return {
    title: 'Renewal risk',
    slide_count: slides.length,
    css: FIXTURE.decks[name].css,
    external_scripts: [],
    scripts: '',
    slides: slides.map((s, index) => ({ index, ...s })),
    html_content: slides.map((s) => s.html).join('\n'),
    version,
    findings: [],
    deck_spec: deckSpec(name, briefs),
  };
}

/** The 3-slide starting deck [A, B, C]; slide_id is each slide's identity. */
function startingDeck(name: DeckName): SlideDeck {
  const d = FIXTURE.decks[name];
  return deckOf(
    name,
    d.slides.map((html, i) => ({
      slide_id: `slide-${d.markers[i].toLowerCase()}`,
      html,
      scripts: '',
      content_hash: `hash-${d.markers[i].toLowerCase()}`,
    })),
    d.markers.map((m) => BRIEFS[m]),
    3,
  );
}

/**
 * What the server holds after a blank insert at `position`: the deck's blank shell spliced
 * into the rows, the blank spec entry spliced into the spec (later entries renumbered), one
 * version bump. Mirrors chat_service.insert_slide's reloaded deck.
 */
function deckAfterInsert(name: DeckName, before: SlideDeck, position: number): SlideDeck {
  const slides: Array<Omit<Slide, 'index'>> = before.slides.map(({ index: _index, ...s }) => s);
  slides.splice(position, 0, {
    slide_id: BLANK_SLIDE_ID,
    html: FIXTURE.decks[name].blank_html_by_position[position],
    scripts: '',
    content_hash: 'hash-blank',
  });
  const briefs: Brief[] = (before.deck_spec?.slides ?? []).map(({ position: _p, ...b }) => b);
  briefs.splice(position, 0, structuredClone(FIXTURE.blank_spec_entry));
  return deckOf(name, slides, briefs, (before.version ?? 0) + 1);
}

/**
 * The body `POST /api/slides` answers with: `ChatService.insert_slide` returns the reloaded
 * deck's `SlideDeck.to_dict()` (title, slide_count, css, external_scripts, scripts, slides
 * as {index, html, slide_id, scripts}, head_meta) plus `inserted_slide_id` and
 * `inserted_position`. No version, spec, findings or content hashes: those only come back
 * from the GET the viewer does next, so the mock must not hand them over here either.
 */
function insertRouteBody(deck: SlideDeck, insertedSlideId: string, insertedPosition: number) {
  return {
    title: deck.title,
    slide_count: deck.slides.length,
    css: deck.css,
    external_scripts: deck.external_scripts,
    scripts: deck.scripts,
    slides: deck.slides.map((s, index) => ({
      index,
      html: s.html,
      slide_id: s.slide_id,
      scripts: s.scripts,
    })),
    head_meta: {},
    inserted_slide_id: insertedSlideId,
    inserted_position: insertedPosition,
  };
}

// ── Shared setup ──────────────────────────────────────────────────────────────

interface Harness {
  /** The server's deck; the GET-slides mock serves whatever is here. */
  server: { deck: SlideDeck };
  /** Every POST /api/slides body, in order. */
  insertBodies: Array<Record<string, unknown>>;
  /** Every PUT /api/slides/reorder body, in order. */
  reorderBodies: Array<{ new_order: number[] }>;
  /** 'GET' and 'POST' in arrival order, for "the refusal refetched". */
  log: string[];
  /** Answers the held chat turn with `complete` (only with `holdTurn`). */
  releaseTurn: () => void;
}

interface HarnessOptions {
  /** Answer POST /api/slides with 409 and the server's busy sentence. */
  refuseInsert?: boolean;
  /** Hold the chat stream open until `releaseTurn()`. */
  holdTurn?: boolean;
}

async function setupManualInsert(page: Page, name: DeckName, opts: HarnessOptions = {}): Promise<Harness> {
  await setupMocks(page);
  await mockSessionWithSlides(page);

  // Empty contributors list → AppLayout grants the editing lock at once, so the viewer is
  // editable (readOnly false) and the chat input enabled.
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ contributors: [] }),
    }),
  );

  const h: Harness = {
    server: { deck: startingDeck(name) },
    insertBodies: [],
    reorderBodies: [],
    log: [],
    releaseTurn: () => {},
  };

  // The server's deck, served as it stands: the insert mock flips it. An explicit flip, not
  // a call counter — how often the app reads getSlides is not under test.
  await page.route(
    apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`),
    (route, request) => {
      if (request.method() !== 'GET') { route.fallback(); return; }
      h.log.push('GET');
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: TEST_SESSION_ID, slide_deck: h.server.deck }),
      });
    },
  );

  await page.route(apiPath('/api/slides/reorder'), (route, request) => {
    if (request.method() !== 'PUT') { route.fallback(); return; }
    h.reorderBodies.push(request.postDataJSON());
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(h.server.deck),
    });
  });

  if (opts.holdTurn) {
    let release!: () => void;
    const released = new Promise<void>((resolve) => { release = resolve; });
    h.releaseTurn = release;
    await page.route(apiPath('/api/chat/stream'), async (route) => {
      await released;
      const events = [
        { type: 'assistant', content: 'Nothing to change.' },
        { type: 'complete', slides: h.server.deck, metadata: { engine_mode: 'graph' } },
      ];
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: events.map((e) => 'data: ' + JSON.stringify(e) + '\n\n').join(''),
      });
    });
  }

  // LAST (C20): the insert. A blank insert lands the deck's own shell at body.position.
  await page.route(apiPath('/api/slides'), (route, request) => {
    if (request.method() !== 'POST') { route.fallback(); return; }
    const body = request.postDataJSON() as Record<string, unknown>;
    h.insertBodies.push(body);
    h.log.push('POST');
    if (opts.refuseInsert) {
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: FIXTURE.busy_detail }),
      });
      return;
    }
    const position = body.position;
    const count = h.server.deck.slides.length;
    if (typeof position !== 'number' || !Number.isInteger(position) || position < 0 || position > count) {
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `Invalid position ${String(position)}` }),
      });
      return;
    }
    h.server.deck = deckAfterInsert(name, h.server.deck, position);
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(insertRouteBody(h.server.deck, BLANK_SLIDE_ID, position)),
    });
  });

  return h;
}

async function openDeck(page: Page, route: 'edit' | 'view' = 'edit') {
  await page.goto(`/sessions/${TEST_SESSION_ID}/${route}`);
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
  await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
  if (route === 'edit') {
    // The lock is held: the viewer is editable.
    await expect(page.getByTestId('chat-input')).toBeEnabled({ timeout: 15000 });
    await expect(page.getByTestId('stage-insert-slide')).toBeVisible();
  }
}

async function goToSlide(page: Page, index: number) {
  await page.getByTestId(`ribbon-thumb-${index}`).click();
  await expect(page.getByTestId(`ribbon-thumb-${index}`)).toHaveAttribute('data-current', 'true');
}

const allThumbs = (page: Page) => page.getByTestId(/^ribbon-thumb-\d+$/);
const allChips = (page: Page) => page.getByTestId(/^ribbon-new-\d+$/);
const allGaps = (page: Page) => page.getByTestId(/^ribbon-insert-\d+$/);

function thumbFrame(page: Page, index: number): FrameLocator {
  return page.getByTestId(`ribbon-thumb-${index}`).locator('iframe').contentFrame();
}

function stageFrame(page: Page): FrameLocator {
  return page.getByTestId('slide-stage-frame').contentFrame();
}

interface RootProbe { tag: string; background: string; width: number; height: number; text: string }

/**
 * The slide ROOT of a rendered frame — the body's first element child (buildSlideDocument
 * puts the slide first in <body>; findSlideRoot agrees for every fixture here) — and the
 * background it computes. Waits for the srcdoc's `.slide` first: a fresh iframe briefly
 * holds an empty about:blank body.
 */
async function rootProbe(frame: FrameLocator): Promise<RootProbe> {
  await expect(frame.locator('.slide').first()).toBeAttached();
  return frame.locator('body').evaluate((body) => {
    const root = body.firstElementChild as HTMLElement;
    const rect = root.getBoundingClientRect();
    return {
      tag: root.tagName.toLowerCase(),
      background: getComputedStyle(root).backgroundColor,
      width: rect.width,
      height: rect.height,
      text: (body.textContent ?? '').trim(),
    };
  });
}

/** Asserts the deck is [markers...] in the ribbon, by each thumbnail's content. */
async function expectThumbMarkers(page: Page, expected: Array<string | null>) {
  await expect(allThumbs(page)).toHaveCount(expected.length);
  for (const [i, marker] of expected.entries()) {
    const markers = thumbFrame(page, i).locator('[data-marker]');
    if (marker === null) {
      await expect(markers).toHaveCount(0);
    } else {
      await expect(markers).toHaveCount(1);
      await expect(markers).toHaveAttribute('data-marker', marker);
    }
  }
}

/**
 * AC2: the blank at `blankIndex` paints its neighbour's ground on the SAME root element type,
 * in the thumbnail and on the stage (the blank is the current slide). The neighbour's
 * ground is checked against the fixture too, so the comparison is not two transparent roots.
 */
async function expectBlankPaintsTheDeckGround(page: Page, name: DeckName, blankIndex: number, neighbourIndex: number) {
  const neighbour = await rootProbe(thumbFrame(page, neighbourIndex));
  expect(neighbour.background, 'the deck paints its ground on the slide root').toBe(FIXTURE.decks[name].ground);

  const blankThumb = await rootProbe(thumbFrame(page, blankIndex));
  expect(blankThumb.tag, 'thumbnail: the blank has the neighbour\'s root element').toBe(neighbour.tag);
  expect(blankThumb.background, 'thumbnail: the blank paints the neighbour\'s ground').toBe(neighbour.background);
  expect(blankThumb.width * blankThumb.height, 'thumbnail: the blank root has area').toBeGreaterThan(0);
  expect(blankThumb.text, 'thumbnail: the blank has no text').toBe('');

  const blankStage = await rootProbe(stageFrame(page));
  expect(blankStage.tag, 'stage: the blank has the neighbour\'s root element').toBe(neighbour.tag);
  expect(blankStage.background, 'stage: the blank paints the neighbour\'s ground').toBe(neighbour.background);
  expect(blankStage.width * blankStage.height, 'stage: the blank root has area').toBeGreaterThan(0);
  expect(blankStage.text, 'stage: the blank has no text').toBe('');
}

/** The insert request carried the session and the position, and no html (the server builds the shell). */
function expectBlankInsertRequest(h: Harness, position: number) {
  expect(h.insertBodies).toHaveLength(1);
  const body = h.insertBodies[0];
  expect(body.session_id).toBe(TEST_SESSION_ID);
  expect(body.position).toBe(position);
  expect(body).not.toHaveProperty('html');
}

/** Hover the gap's strip (the "+" is visibility:hidden until then), then click the "+". */
async function clickGap(page: Page, position: number) {
  const gap = page.getByTestId(`ribbon-insert-${position}`);
  await gap.locator('..').hover();
  await expect(gap).toBeVisible();
  await gap.click();
}

// ── The tests ─────────────────────────────────────────────────────────────────

test.describe('#314 — inserting a blank slide by hand', () => {
  for (const name of ['W', 'I'] as const) {
    test(`(a) the toolbar inserts a blank after the current slide, in the deck's own ground (deck ${name})`, async ({ page }) => {
      const h = await setupManualInsert(page, name);
      await openDeck(page);

      // Precondition: [A, B, C], nothing flagged new, on slide 2.
      await expectThumbMarkers(page, ['A', 'B', 'C']);
      await expect(allChips(page)).toHaveCount(0);
      await goToSlide(page, 1);

      await page.getByTestId('stage-insert-slide').click();

      // 4 slides: reachable only through the insert's refetch.
      await expect(allThumbs(page)).toHaveCount(4, { timeout: 15000 });
      expectBlankInsertRequest(h, 2);

      // The indicator (AC10): the blank, at slot 3, is selected and marked New; nothing else is.
      // Checked first: the chip lasts NEW_SLIDE_INDICATOR_MS (5 s).
      await expect(page.getByTestId('ribbon-new-2')).toBeVisible();
      await expect(allChips(page)).toHaveCount(1);
      await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-new', 'true');
      await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'true');
      await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'false');
      await expect(page.getByTestId('new-slide-status')).toHaveText('Slide 3 added');

      // Neighbours keep their content and order; the blank has none.
      await expectThumbMarkers(page, ['A', 'B', null, 'C']);
      await expect(stageFrame(page).locator('[data-marker]')).toHaveCount(0);

      // AC2: the blank paints the deck's ground, like slide 2 before it and slide 4 after it.
      await expectBlankPaintsTheDeckGround(page, name, 2, 1);
      const after = await rootProbe(thumbFrame(page, 3));
      expect(after.background).toBe(FIXTURE.decks[name].ground);

      // AC3: the Spec view has a blank entry at the landed position, labelled by its number.
      await page.getByTestId('view-toggle-spec').click();
      await expect(page.getByTestId('spec-view')).toBeVisible();
      await expect(page.getByTestId(/^spec-slide-\d+$/)).toHaveCount(4);
      await expect(page.getByTestId('spec-slide-2').getByText(/^Slide 3$/)).toBeVisible();
      await expect(page.getByTestId('spec-slide-blank-2')).toHaveText('Blank slide');
      await expect(page.getByTestId(/^spec-slide-blank-\d+$/)).toHaveCount(1);
      // The entries after it moved down one: C's brief is now "Slide 4".
      await expect(page.getByTestId('spec-slide-3')).toContainText(BRIEFS.C.purpose);
      await expect(page.getByTestId('spec-slide-3').getByText(/^Slide 4$/)).toBeVisible();
      await expect(page.getByTestId('spec-slide-1')).toContainText(BRIEFS.B.purpose);

      // The chip expires; the selection stays on the blank.
      await page.getByTestId('view-toggle-slides').click();
      await expect(page.getByTestId('ribbon-new-2')).toHaveCount(0, { timeout: 8000 });
      await expect(page.getByTestId('new-slide-status')).toHaveCount(0);
      await expect(page.getByTestId('ribbon-thumb-2')).not.toHaveAttribute('data-new', 'true');
      await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'true');
    });
  }

  test('(b) the gap above the first thumbnail inserts at position 0 (deck I)', async ({ page }) => {
    const h = await setupManualInsert(page, 'I');
    await openDeck(page);
    await expectThumbMarkers(page, ['A', 'B', 'C']);
    // Start on slide 3, so selecting the blank at index 0 is a move the indicator made (the
    // viewer opens on index 0, which is where the blank lands).
    await goToSlide(page, 2);

    // At rest the "+" is hidden, so it never swallows a click aimed at a thumbnail edge.
    const gap0 = page.getByTestId('ribbon-insert-0');
    await page.getByTestId('slide-stage').hover();
    await expect(gap0).toBeHidden();
    await expect(allGaps(page)).toHaveCount(4);

    // Hovering its strip reveals it, inside the ribbon's scroll box (not clipped above it).
    await gap0.locator('..').hover();
    await expect(gap0).toBeVisible();
    const ribbon = await page.getByTestId('thumbnail-ribbon').boundingBox();
    const plus = await gap0.boundingBox();
    if (!ribbon || !plus) throw new Error('the ribbon or gap 0 has no layout box');
    expect(plus.y).toBeGreaterThanOrEqual(ribbon.y);
    expect(plus.y + plus.height).toBeLessThanOrEqual(ribbon.y + ribbon.height);
    expect(plus.x).toBeGreaterThanOrEqual(ribbon.x);
    expect(plus.x + plus.width).toBeLessThanOrEqual(ribbon.x + ribbon.width);

    await gap0.click();

    await expect(allThumbs(page)).toHaveCount(4, { timeout: 15000 });
    expectBlankInsertRequest(h, 0);

    await expect(page.getByTestId('ribbon-new-0')).toBeVisible();
    await expect(allChips(page)).toHaveCount(1);
    await expect(page.getByTestId('ribbon-thumb-0')).toHaveAttribute('data-current', 'true');
    await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'false');
    await expect(page.getByTestId('new-slide-status')).toHaveText('Slide 1 added');

    await expectThumbMarkers(page, [null, 'A', 'B', 'C']);
    await expectBlankPaintsTheDeckGround(page, 'I', 0, 1);
  });

  test('(b) the gap after the last thumbnail appends, and the appended slide is selected (deck W)', async ({ page }) => {
    const h = await setupManualInsert(page, 'W');
    await openDeck(page);
    await expectThumbMarkers(page, ['A', 'B', 'C']);
    // Start on slide 1, so selecting the appended slide is a move the indicator made.
    await expect(page.getByTestId('ribbon-thumb-0')).toHaveAttribute('data-current', 'true');

    await clickGap(page, 3);

    await expect(allThumbs(page)).toHaveCount(4, { timeout: 15000 });
    expectBlankInsertRequest(h, 3);

    // Index 3 did not exist in the render the click happened in: the selection must not be
    // clamped to the old last slide.
    await expect(page.getByTestId('ribbon-new-3')).toBeVisible();
    await expect(allChips(page)).toHaveCount(1);
    await expect(page.getByTestId('ribbon-thumb-3')).toHaveAttribute('data-current', 'true');
    await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'false');
    await expect(page.getByTestId('new-slide-status')).toHaveText('Slide 4 added');

    await expectThumbMarkers(page, ['A', 'B', 'C', null]);
    await expectBlankPaintsTheDeckGround(page, 'W', 3, 2);
  });

  test('(c) a refused insert shows the server\'s sentence, refetches and changes nothing', async ({ page }) => {
    const h = await setupManualInsert(page, 'W', { refuseInsert: true });
    await openDeck(page);
    await goToSlide(page, 1);

    await page.getByTestId('stage-insert-slide').click();

    await expect(page.getByTestId('toast').filter({ hasText: FIXTURE.busy_detail })).toBeVisible();
    expect(h.insertBodies).toHaveLength(1);
    // The view is refreshed after the refusal (AC6: "the UI shows the server's text and refetches").
    await expect.poll(() => h.log.slice(h.log.indexOf('POST') + 1).includes('GET')).toBe(true);

    await expectThumbMarkers(page, ['A', 'B', 'C']);
    await expect(allChips(page)).toHaveCount(0);
    await expect(page.getByTestId('new-slide-status')).toHaveCount(0);
    await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
    // Nothing is left in flight: the control works again.
    await expect(page.getByTestId('stage-insert-slide')).toBeEnabled();
  });

  test('(d) viewers get neither the toolbar button nor the ribbon gaps', async ({ page }) => {
    const h = await setupManualInsert(page, 'W');

    // The positive, same mocks: an editor has the button and one gap per landing position.
    await openDeck(page, 'edit');
    await expect(page.getByTestId('stage-insert-slide')).toBeVisible();
    await expect(allGaps(page)).toHaveCount(4);

    await openDeck(page, 'view');
    await expectThumbMarkers(page, ['A', 'B', 'C']);
    // The toolbar itself renders for viewers (verification badge); only the mutating controls go.
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();
    await expect(page.getByTestId('stage-verification-badge')).toBeVisible();
    await expect(page.getByTestId('stage-insert-slide')).toHaveCount(0);
    await expect(allGaps(page)).toHaveCount(0);
    expect(h.insertBodies).toHaveLength(0);
  });

  test('(e) the insert controls are disabled while a turn is open, and enabled once it completes', async ({ page }) => {
    const h = await setupManualInsert(page, 'W', { holdTurn: true });
    await openDeck(page);

    const controls = [
      page.getByTestId('stage-insert-slide'),
      ...[0, 1, 2, 3].map((k) => page.getByTestId(`ribbon-insert-${k}`)),
    ];
    for (const control of controls) await expect(control).toBeEnabled();

    await page.getByTestId('chat-input').fill('Tighten the wording on slide 2');
    await page.getByRole('button', { name: 'Send' }).click();

    // The turn is open (its placeholder is up), and every insert control is disabled.
    await expect(page.getByTestId('chat-turn-progress')).toBeVisible({ timeout: 15000 });
    for (const control of controls) await expect(control).toBeDisabled();

    h.releaseTurn();

    await expect(page.getByTestId('chat-turn-progress')).toHaveCount(0, { timeout: 15000 });
    for (const control of controls) await expect(control).toBeEnabled();
    expect(h.insertBodies).toHaveLength(0);
  });

  test('(f) mid-drag the gaps stay hidden under the pointer, and the drop still reorders', async ({ page }) => {
    const h = await setupManualInsert(page, 'W');
    await openDeck(page);

    const gap2 = page.getByTestId('ribbon-insert-2');
    const strip2 = await gap2.locator('..').boundingBox();
    const from = await page.getByTestId('ribbon-thumb-0').boundingBox();
    const to = await page.getByTestId('ribbon-thumb-2').boundingBox();
    if (!strip2 || !from || !to) throw new Error('the ribbon has no layout boxes');
    const stripX = strip2.x + strip2.width / 2;
    const stripY = strip2.y + strip2.height / 2;

    // Positive control: at rest, the pointer on strip 2 reveals its "+".
    await page.mouse.move(stripX, stripY);
    await expect(gap2).toBeVisible();
    await page.getByTestId('slide-stage').hover();
    await expect(gap2).toBeHidden();

    // Start a pointer drag on thumbnail 1 (dnd-kit needs discrete moves past 8 px).
    const startX = from.x + from.width / 2;
    const startY = from.y + from.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    for (let step = 1; step <= 4; step++) {
      await page.mouse.move(startX, startY + step * 6, { steps: 2 });
    }
    // Mid-drag, the pointer on strip 2: its "+" stays hidden.
    await page.mouse.move(stripX, stripY, { steps: 6 });
    await expect(gap2).toBeHidden();
    for (let k = 0; k <= 3; k++) await expect(page.getByTestId(`ribbon-insert-${k}`)).toBeHidden();

    // Drop on thumbnail 3.
    await page.mouse.move(startX, to.y + to.height / 2, { steps: 6 });
    await page.mouse.up();

    await expect.poll(() => h.reorderBodies.length, { timeout: 5000 }).toBeGreaterThan(0);
    const order = h.reorderBodies[0].new_order;
    expect([...order].sort()).toEqual([0, 1, 2]);
    expect(order).not.toEqual([0, 1, 2]);
    // A reorder adds no slide: nothing is flagged New.
    await expect(allChips(page)).toHaveCount(0);

    // After the drop the gaps answer hover again.
    await page.mouse.move(stripX, stripY);
    await expect(gap2).toBeVisible();
  });
});
