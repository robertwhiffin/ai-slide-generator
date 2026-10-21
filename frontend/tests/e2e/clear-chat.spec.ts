/**
 * #323: clear the chat on an existing deck, then carry on from its Spec and slides.
 *
 * The backend is mocked with `page.route`, so this spec covers the UI journey only:
 * the confirmed action sends ONE DELETE to this session's `/context`, empties the
 * panel, and leaves the deck, its Spec, its save points and its pinned Graph
 * Version exactly as they were, without refetching any of them. The backend half
 * (a cleared conversation stays empty to every reader, the pin survives, a real
 * post-clear turn) is proved by tests/integration/test_clear_chat_routes.py and the
 * graph test, not here. In particular test 2's "only slide 3 changed" shows the UI
 * renders the deck the server returns after the turn; it is not evidence that the
 * architect rebuilds only slide 3.
 *
 * Every route is registered AFTER setupMocks and mockSessionWithSlides, so
 * Playwright's last-registered-wins ordering puts these ahead of the generic ones.
 *
 * Sabotage targets, all in ChatPanel.tsx: make handleConfirmClearChat refetch
 * `api.getSlides` (test 1 goes red on the slides-GET count); send the parent
 * session id for contributors (test 3's tripwire fires); drop `isLoading` from
 * `clearChatDisabled` (test 5); call the clear from the dialog's onCancel (test 6).
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import {
  mockSessionDetail,
  mockSessionWithSlides,
  mockSlidesResponse,
  TEST_SESSION_ID,
} from '../helpers/session-helpers';
import {
  CLEAR_CHAT_DIALOG_MESSAGE,
  CLEAR_CHAT_DIALOG_TITLE,
  CLEAR_CHAT_LABEL,
} from '../../src/components/ChatPanel/clearChatCopy';

// ── fixtures ──────────────────────────────────────────────────────────────────

/** The owner's root session, seen from a contributor's session. Nothing may ever clear it from here. */
const OWNER_SESSION_ID = 'owner-session-id';

const CONTEXT_PATH = `/api/sessions/${TEST_SESSION_ID}/context`;

/** The persisted conversation. None of these strings occurs in the ChatWelcome copy. */
const TRANSCRIPT = [
  { id: 1, role: 'user', content: 'Build a deck about cloud adoption', created_at: '2026-10-19T09:00:00' },
  { id: 2, role: 'assistant', content: 'Building 3 slide(s).', created_at: '2026-10-19T09:00:30' },
  { id: 3, role: 'user', content: 'Make the title punchier', created_at: '2026-10-19T09:05:00' },
  { id: 4, role: 'assistant', content: 'Edited slide 1.', created_at: '2026-10-19T09:05:20' },
];
const TRANSCRIPT_TEXT = TRANSCRIPT.map((m) => m.content);

/** A valid three-slide spec, shaped like spec-view.spec.ts's. */
const DECK_SPEC = {
  title: 'Benefits of Cloud Computing',
  audience: 'IT directors deciding whether to move their core workloads to the cloud.',
  purpose: 'Win approval for a phased cloud migration next financial year.',
  argument: 'The cloud cuts infrastructure cost first, then pays back in speed and resilience.',
  call_to_action: 'Approve a pilot migration of two workloads this quarter.',
  narrative_arc: [
    'Open on what the cloud changes for the business.',
    'Prove the cost case with the average savings.',
    'Close on the benefits that outlast the savings.',
  ],
  design_contract: { design_system_id: 7, template_id: 3, slide_style_id: null },
  resolved_data: {
    synthesis: 'Industry survey figures on cloud cost and adoption.',
    figures: [{ key: 'cost_reduction', value: '35%', source: 'survey.cloud_costs' }],
    gaps: [],
  },
  slides: [
    {
      position: 0,
      purpose: 'Frame the decision.',
      content_brief: 'Title slide: what moving to the cloud changes.',
      assumes: 'Nothing. This is the first slide.',
      hands_off: 'The reader knows the decision on the table.',
      data_references: [],
      template_section_index: 0,
    },
    {
      position: 1,
      purpose: 'Make the cost case.',
      content_brief: 'The average infrastructure saving in the first year.',
      assumes: 'The reader knows the decision on the table.',
      hands_off: 'The reader accepts the saving is real.',
      data_references: ['cost_reduction'],
      template_section_index: 1,
    },
    {
      position: 2,
      purpose: 'Show the benefits beyond cost.',
      content_brief: 'Scalability, security, collaboration and automatic updates.',
      assumes: 'The reader accepts the saving is real.',
      hands_off: 'The deck ends on the pilot the reader can approve.',
      data_references: [],
      template_section_index: 2,
    },
  ],
};

type DeckSlide = (typeof mockSlidesResponse.slide_deck.slides)[number];

const ORIGINAL_SLIDES: DeckSlide[] = mockSlidesResponse.slide_deck.slides;

/** The deck after "Make slide 3 shorter": slides 1 and 2 untouched, slide 3 replaced. */
const SHORT_SLIDE_3_TITLE = 'Key Benefits (short)';
const SLIDES_AFTER_EDIT: DeckSlide[] = ORIGINAL_SLIDES.map((slide, i) => (i === 2
  ? {
    ...slide,
    html: `<div class="slide-container"><h1>${SHORT_SLIDE_3_TITLE}</h1></div>`,
    content_hash: 'short-3',
  }
  : slide));

/** Server-sent events in the shape spec-view.spec.ts's stream mocks use. */
function sse(...events: Record<string, unknown>[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

// ── the mocked backend ────────────────────────────────────────────────────────

interface ClearableDeck {
  /** `cleared` flips when the clear lands; `slides` can be swapped mid-test. */
  state: { cleared: boolean; slides: DeckSlide[] };
  /** Pathnames of the DELETEs this session's `/context` route answered. */
  clears: string[];
  /** Tripwire: anything that reached the OWNER's `/context`. Must stay empty. */
  ownerClears: string[];
  /** Every DELETE to any `.../context` the page sent, seen at the network layer. */
  contextDeletes: string[];
  counts: { slidesGets: number; sessionGets: number };
}

async function mockClearableDeck(
  page: Page,
  { myPermission, isContributor = false }: { myPermission: string; isContributor?: boolean },
): Promise<ClearableDeck> {
  const deck: ClearableDeck = {
    state: { cleared: false, slides: ORIGINAL_SLIDES },
    clears: [],
    ownerClears: [],
    contextDeletes: [],
    counts: { slidesGets: 0, sessionGets: 0 },
  };

  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() === 'DELETE' && pathname.endsWith('/context')) {
      deck.contextDeletes.push(pathname);
    }
  });

  // Session detail: the transcript until the clear lands, then nothing.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}`), (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    deck.counts.sessionGets += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionDetail,
        my_permission: myPermission,
        is_contributor_session: isContributor,
        parent_session_id: isContributor ? OWNER_SESSION_ID : null,
        graph_version: 1,
        active_graph_version: 1,
        is_older_than_active: false,
        messages: deck.state.cleared ? [] : TRANSCRIPT,
      }),
    });
  });

  // The clear itself.
  await page.route(apiPath(CONTEXT_PATH), (route) => {
    if (route.request().method() !== 'DELETE') return route.fallback();
    deck.clears.push(new URL(route.request().url()).pathname);
    deck.state.cleared = true;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'cleared',
        session_id: TEST_SESSION_ID,
        deleted_messages: 3,
        preserved_message_id: 1,
      }),
    });
  });

  // Tripwire on the owner's conversation. Answers 200 so that, if it ever fires,
  // the UI carries on as if it worked and the assertion on this array is what fails.
  await page.route(apiPathMatching(/^\/api\/sessions\/owner-session-id\/context$/), (route) => {
    deck.ownerClears.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'cleared',
        session_id: OWNER_SESSION_ID,
        deleted_messages: 3,
        preserved_message_id: 1,
      }),
    });
  });

  // The deck, with a Spec, counted so a refetch after the clear is visible.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`), (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    deck.counts.slidesGets += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSlidesResponse,
        slide_deck: {
          ...mockSlidesResponse.slide_deck,
          deck_spec: DECK_SPEC,
          slides: deck.state.slides,
        },
      }),
    });
  });

  // No contributors: AppLayout grants the editing lock at once, so the panel is not read-only.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ contributors: [] }),
  }));

  // One save point, so the header shows its trigger. Matched on pathname, so the
  // `?session_id=` query cannot blind it.
  await page.route(apiPath('/api/slides/versions'), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      versions: [{
        version_number: 1,
        description: 'Generated 3 slide(s)',
        created_at: '2026-10-19T09:00:40',
        slide_count: 3,
      }],
      current_version: 1,
    }),
  }));

  return deck;
}

// ── page helpers ──────────────────────────────────────────────────────────────

const chatPanel = (page: Page) => page.getByTestId('chat-panel');
const clearButton = (page: Page) => page.getByTestId('clear-chat-button');
const confirmDialog = (page: Page) => page.getByTestId('confirm-dialog');
/** Exact: the Clear chat button's tooltip also contains "save points". */
const savePointTrigger = (page: Page) => page.getByTitle('Save Points', { exact: true });

/** Open the deck and wait until ChatPanel has rendered the persisted transcript. */
async function openDeck(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('main-view-controls')).toBeVisible();
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
  for (const text of TRANSCRIPT_TEXT) {
    await expect(chatPanel(page).getByText(text, { exact: true })).toBeVisible();
  }
}

async function readSpecAudience(page: Page): Promise<string> {
  await page.getByTestId('view-toggle-spec').click();
  await expect(page.getByTestId('spec-audience')).toContainText(DECK_SPEC.audience);
  const audience = await page.getByTestId('spec-audience').innerText();
  await page.getByTestId('view-toggle-slides').click();
  await expect(page.getByTestId('slide-viewer')).toBeVisible();
  return audience;
}

/** Click Clear chat, check the dialog's copy, confirm inside the dialog, and wait for the empty panel. */
async function clearTheChat(page: Page) {
  await expect(clearButton(page)).toBeEnabled();
  await clearButton(page).click();

  const dialog = confirmDialog(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(CLEAR_CHAT_DIALOG_TITLE);
  await expect(dialog).toContainText(CLEAR_CHAT_DIALOG_MESSAGE);
  // Scoped to the dialog: unscoped, this name also matches the header button (strict-mode violation).
  await dialog.getByRole('button', { name: CLEAR_CHAT_LABEL, exact: true }).click();

  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('chat-welcome')).toBeVisible();
}

async function expectNoTranscript(page: Page) {
  for (const text of TRANSCRIPT_TEXT) {
    await expect(chatPanel(page)).not.toContainText(text);
  }
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe('clear chat', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
  });

  test('an owner clears the chat; slides, Spec, save points and pin are unchanged; a reload stays empty', async ({ page }) => {
    const deck = await mockClearableDeck(page, { myPermission: 'CAN_MANAGE' });
    await openDeck(page);

    // ── before ──
    const audienceBefore = await readSpecAudience(page);
    const pinBefore = await page.getByTestId('graph-version-status').innerText();
    expect(pinBefore).toContain('Pinned Graph Version 1');   // a real pin, not the "unavailable" fallback
    await expect(savePointTrigger(page)).toBeVisible();
    const savePointBefore = await savePointTrigger(page).innerText();
    expect(savePointBefore).toContain('v1');
    for (const i of [0, 1, 2]) {
      await expect(page.getByTestId(`ribbon-thumb-${i}`)).toBeVisible();
    }
    expect(deck.counts.slidesGets).toBeGreaterThan(0);
    const slidesGetsBefore = deck.counts.slidesGets;

    // ── the clear ──
    await clearTheChat(page);

    // ── after ──
    await expectNoTranscript(page);
    expect(deck.clears).toEqual([CONTEXT_PATH]);
    expect(deck.contextDeletes).toEqual([CONTEXT_PATH]);

    for (const i of [0, 1, 2]) {
      await expect(page.getByTestId(`ribbon-thumb-${i}`)).toBeVisible();
    }
    expect(await page.getByTestId('graph-version-status').innerText()).toBe(pinBefore);
    expect(await savePointTrigger(page).innerText()).toBe(savePointBefore);
    expect(await readSpecAudience(page)).toBe(audienceBefore);

    // Read last, after the Spec round trip, so a refetch the clear set off has had time to land.
    expect(deck.counts.slidesGets, 'the clear refetched the slides').toBe(slidesGetsBefore);

    // ── a reload stays empty ──
    const sessionGetsBeforeReload = deck.counts.sessionGets;
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    // The witness that the conversation has LOADED, not merely not loaded yet: the
    // button needs my_permission, which ChatPanel sets in the same render as the
    // messages from the same session read. It is disabled because there are none.
    await expect(clearButton(page)).toBeVisible();
    await expect(clearButton(page), 'the reloaded conversation is not empty').toBeDisabled();
    expect(deck.counts.sessionGets).toBeGreaterThan(sessionGetsBeforeReload);
    await expect(page.getByTestId('chat-welcome')).toBeVisible();
    await expectNoTranscript(page);
  });

  test('after clearing, an edit turn shows only the new conversation and changes only slide 3', async ({ page }) => {
    const deck = await mockClearableDeck(page, { myPermission: 'CAN_MANAGE' });
    const reply = 'Editing slide 3.';
    const prompt = 'Make slide 3 shorter';
    const streamBodies: Record<string, unknown>[] = [];
    await page.route(apiPath('/api/chat/stream'), (route) => {
      streamBodies.push(route.request().postDataJSON());
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse(
          { type: 'assistant', content: reply },
          {
            type: 'complete',
            slides: { ...mockSlidesResponse.slide_deck, deck_spec: DECK_SPEC, slides: SLIDES_AFTER_EDIT },
          },
        ),
      });
    });

    await openDeck(page);
    await clearTheChat(page);
    expect(deck.clears).toEqual([CONTEXT_PATH]);

    // The turn's commit lands on the server: slide 3 is the only one that changed.
    deck.state.slides = SLIDES_AFTER_EDIT;
    await page.getByTestId('chat-input').fill(prompt);
    await page.getByRole('button', { name: 'Send' }).click();

    const chat = chatPanel(page);
    await expect(chat.getByText(reply, { exact: true })).toBeVisible({ timeout: 15000 });

    expect(streamBodies).toHaveLength(1);
    expect(streamBodies[0].message).toBe(prompt);
    expect(streamBodies[0].session_id).toBe(TEST_SESSION_ID);

    // Exactly the new conversation: each new message once, nothing of the old one.
    await expect(chat.getByText(prompt, { exact: true })).toHaveCount(1);
    await expect(chat.getByText(reply, { exact: true })).toHaveCount(1);
    await expectNoTranscript(page);
    await expect(page.getByTestId('chat-welcome')).toHaveCount(0);

    const stageHeading = page.getByTestId('slide-stage-frame').contentFrame().locator('h1');
    await page.getByTestId('ribbon-thumb-2').click();
    await expect(stageHeading).toHaveText(SHORT_SLIDE_3_TITLE, { timeout: 10000 });

    await page.getByTestId('ribbon-thumb-0').click();
    await expect(stageHeading).toHaveText('Benefits of Cloud Computing');
    await page.getByTestId('ribbon-thumb-1').click();
    await expect(stageHeading).toHaveText('Cost Savings Drive Cloud Adoption');
  });

  test('a contributor with edit rights clears their own session, never the owner\'s', async ({ page }) => {
    // A REGRESSION TRIPWIRE, not evidence for D3. The handler sends the sessionId
    // from useSession, so the owner's /context is reachable only after a contrived
    // code change. D3's proof is the backend creator-gate tests (Task 3).
    const deck = await mockClearableDeck(page, { myPermission: 'CAN_EDIT', isContributor: true });
    await openDeck(page);

    await clearTheChat(page);
    await expectNoTranscript(page);

    expect(deck.ownerClears, "a clear reached the owner's conversation").toEqual([]);
    expect(deck.clears).toEqual([CONTEXT_PATH]);
    expect(deck.contextDeletes).toEqual([CONTEXT_PATH]);
  });

  test('a viewer is not offered Clear chat', async ({ page }) => {
    const deck = await mockClearableDeck(page, { myPermission: 'CAN_VIEW' });
    // openDeck waits for the transcript, which ChatPanel renders in the same update
    // as it applies my_permission, so the absence below is not "not loaded yet".
    await openDeck(page);

    await expect(clearButton(page)).toHaveCount(0);
    expect(deck.clears).toEqual([]);
  });

  test('Clear chat is disabled while a reply is being generated', async ({ page }) => {
    await mockClearableDeck(page, { myPermission: 'CAN_MANAGE' });
    const prompt = 'Tighten slide 2';
    const reply = 'Tightened slide 2.';
    let releaseStream: () => void = () => {};
    const streamHeld = new Promise<void>((resolve) => { releaseStream = resolve; });
    await page.route(apiPath('/api/chat/stream'), async (route) => {
      await streamHeld;
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse({ type: 'assistant', content: reply }, { type: 'complete', message: 'done' }),
      });
    });

    await openDeck(page);
    // Precondition: enabled before the turn, so the disable below is the turn's doing.
    await expect(clearButton(page)).toBeEnabled();

    await page.getByTestId('chat-input').fill(prompt);
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(chatPanel(page).getByText(prompt, { exact: true })).toBeVisible();
    await expect(clearButton(page)).toBeDisabled();

    releaseStream();
    await expect(chatPanel(page).getByText(reply, { exact: true })).toBeVisible({ timeout: 15000 });
    await expect(clearButton(page)).toBeEnabled();
  });

  test('cancelling the dialog clears nothing', async ({ page }) => {
    const deck = await mockClearableDeck(page, { myPermission: 'CAN_MANAGE' });
    await openDeck(page);

    await clearButton(page).click();
    const dialog = confirmDialog(page);
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    // An absence needs a window to fail in: a DELETE sent on cancel would be on the
    // wire within milliseconds and would empty the panel as soon as it answered.
    await page.waitForTimeout(500);
    expect(deck.contextDeletes).toEqual([]);
    expect(deck.clears).toEqual([]);
    for (const text of TRANSCRIPT_TEXT) {
      await expect(chatPanel(page).getByText(text, { exact: true })).toBeVisible();
    }
    await expect(page.getByTestId('chat-welcome')).toHaveCount(0);
    await expect(clearButton(page)).toBeEnabled();
  });
});
