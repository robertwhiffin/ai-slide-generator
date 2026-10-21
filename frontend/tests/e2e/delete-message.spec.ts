/**
 * #317: delete one chat message and its replies, and keep the deck exactly as it is.
 *
 * The backend is mocked with `page.route`, so this spec covers the UI journey only:
 * an editor's confirmed delete sends ONE DELETE to this session's
 * `/messages/{id}`, removes that turn from the panel, and leaves the slides and the
 * Spec as they were, without refetching them. The backend half (the turn's rows,
 * the architect's context and the graph checkpoint all forget it; editors only, own
 * conversation only) is proved by tests/unit/test_delete_message.py,
 * tests/integration/test_delete_message_routes.py and
 * tests/integration/test_delete_message_graph_turn.py, not here.
 *
 * Transport: the mocked app runs on the vite dev server at localhost, where
 * `isPollingMode()` is false, so a turn goes over SSE (`/api/chat/stream`). Test 2
 * shows a message sent in this tab gets its id from the turn-end read of
 * GET …/messages?limit=200; the polling-shaped turn is covered by the
 * ChatPanel.deleteMessage vitest.
 *
 * Playwright treats an `opacity: 0` element as visible and clickable, so where it
 * matters that the hover-only trash button is hidden, the tests read its opacity.
 *
 * Every route is registered AFTER setupMocks and mockSessionWithSlides, so
 * Playwright's last-registered-wins ordering puts these ahead of the generic ones.
 *
 * Sabotage targets, in frontend/src: make handleConfirmDeleteMessage refetch
 * `api.getSlides` (test 1, slides-GET count); drop `refreshMessageIds` from the
 * `complete` case (test 2, the new row never offers delete); skip `withoutTurn`
 * on success (tests 1 and 2); offer delete to viewers (test 3); drop `isLoading`
 * from `deleteMessageDisabled` (test 4); drop MessageList's `disabled:opacity-0`, so
 * every disabled trash button shows at 0.5 during a turn (test 4); confirm from the
 * dialog's onCancel (test 5); set no error after a refused delete (test 6).
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
  DELETE_MESSAGE_BUSY,
  DELETE_MESSAGE_CONFIRM_LABEL,
  DELETE_MESSAGE_DIALOG_MESSAGE,
  DELETE_MESSAGE_DIALOG_TITLE,
} from '../../src/components/ChatPanel/deleteMessageCopy';

// ── fixtures ──────────────────────────────────────────────────────────────────

interface TranscriptRow {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** The persisted conversation. None of these strings occurs in the ChatWelcome copy. */
const TRANSCRIPT: readonly TranscriptRow[] = [
  { id: 1, role: 'user', content: 'Build a deck about cloud adoption', created_at: '2026-10-19T09:00:00' },
  { id: 2, role: 'assistant', content: 'Building 3 slide(s).', created_at: '2026-10-19T09:00:30' },
  { id: 3, role: 'user', content: 'Make the title punchier', created_at: '2026-10-19T09:05:00' },
  { id: 4, role: 'assistant', content: 'Edited slide 1.', created_at: '2026-10-19T09:05:20' },
];
const FIRST_TURN = [TRANSCRIPT[0].content, TRANSCRIPT[1].content];
const SECOND_TURN = [TRANSCRIPT[2].content, TRANSCRIPT[3].content];
const TRANSCRIPT_TEXT = TRANSCRIPT.map((m) => m.content);

const messagePath = (messageId: number) => `/api/sessions/${TEST_SESSION_ID}/messages/${messageId}`;

/** A valid three-slide spec, the same shape as clear-chat.spec.ts's. */
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

/** The deck a turn's `complete` event carries: unchanged, so a turn never alters what the tests compare. */
const DECK_AFTER_TURN = { ...mockSlidesResponse.slide_deck, deck_spec: DECK_SPEC };

/** Server-sent events in the shape spec-view.spec.ts's stream mocks use. */
function sse(...events: Record<string, unknown>[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

// ── the mocked backend ────────────────────────────────────────────────────────

interface DeletableDeck {
  state: {
    /** The stored conversation. A successful delete removes its turn; a test may push a turn's rows. */
    transcript: TranscriptRow[];
    /** The delete route's answer: 200 deletes, anything else refuses with that status. */
    deleteStatus: number;
    /** While set, GET …/messages is held until it resolves. */
    messagesReadGate: Promise<void> | null;
  };
  /** Pathnames of the DELETEs this session's `/messages/{id}` route answered. */
  deletes: string[];
  /** Every DELETE to any `/messages/` path the page sent, seen at the network layer. */
  messageDeletes: string[];
  /** The query string of every GET …/messages (the turn-end id read). */
  messagesReads: string[];
  counts: { slidesGets: number; sessionGets: number; messagesGets: number };
}

/** The backend's turn rule: the user row and every row after it up to the next user row. */
function withoutStoredTurn(rows: TranscriptRow[], userMessageId: number): TranscriptRow[] | null {
  const start = rows.findIndex((r) => r.role === 'user' && r.id === userMessageId);
  if (start === -1) return null;
  let end = start + 1;
  while (end < rows.length && rows[end].role !== 'user') end += 1;
  return [...rows.slice(0, start), ...rows.slice(end)];
}

async function mockDeletableDeck(
  page: Page,
  { myPermission }: { myPermission: string },
): Promise<DeletableDeck> {
  const deck: DeletableDeck = {
    state: { transcript: TRANSCRIPT.map((row) => ({ ...row })), deleteStatus: 200, messagesReadGate: null },
    deletes: [],
    messageDeletes: [],
    messagesReads: [],
    counts: { slidesGets: 0, sessionGets: 0, messagesGets: 0 },
  };

  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    if (request.method() === 'DELETE' && pathname.includes('/messages/')) {
      deck.messageDeletes.push(pathname);
    }
  });

  // Session detail: whatever the stored conversation is now.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}`), (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    deck.counts.sessionGets += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionDetail,
        my_permission: myPermission,
        is_contributor_session: false,
        parent_session_id: null,
        graph_version: 1,
        active_graph_version: 1,
        is_older_than_active: false,
        messages: deck.state.transcript,
      }),
    });
  });

  // The delete itself.
  await page.route(
    apiPathMatching(new RegExp(`^/api/sessions/${TEST_SESSION_ID}/messages/(\\d+)$`)),
    (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      const { pathname } = new URL(route.request().url());
      deck.deletes.push(pathname);
      if (deck.state.deleteStatus !== 200) {
        return route.fulfill({
          status: deck.state.deleteStatus,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'busy' }),
        });
      }
      const messageId = Number(pathname.split('/').pop());
      const kept = withoutStoredTurn(deck.state.transcript, messageId);
      if (kept === null) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Message not found' }),
        });
      }
      const deletedMessages = deck.state.transcript.length - kept.length;
      deck.state.transcript = kept;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'deleted',
          session_id: TEST_SESSION_ID,
          message_id: messageId,
          deleted_messages: deletedMessages,
          hidden_message_id: null,
        }),
      });
    },
  );

  // The stored conversation, with ids: the panel's turn-end id read.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/messages`), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    deck.counts.messagesGets += 1;
    deck.messagesReads.push(new URL(route.request().url()).search);
    if (deck.state.messagesReadGate) await deck.state.messagesReadGate;
    const messages = deck.state.transcript;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session_id: TEST_SESSION_ID, messages, count: messages.length }),
    });
  });

  // The deck, with a Spec, counted so a refetch after the delete is visible.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/slides`), (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    deck.counts.slidesGets += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSlidesResponse,
        slide_deck: { ...mockSlidesResponse.slide_deck, deck_spec: DECK_SPEC },
      }),
    });
  });

  // No contributors: AppLayout grants the editing lock at once, so the panel is not read-only.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ contributors: [] }),
  }));

  // One save point, as clear-chat.spec.ts serves.
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
const confirmDialog = (page: Page) => page.getByTestId('confirm-dialog');
const messageRow = (page: Page, text: string) => page.getByTestId('chat-message-row').filter({ hasText: text });
const deleteButtonIn = (page: Page, text: string) => messageRow(page, text).getByTestId('delete-message-button');

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

/** Hover the row that holds `text`, click its trash button, and wait for the dialog. */
async function openDeleteDialog(page: Page, text: string) {
  await messageRow(page, text).hover();
  await expect(deleteButtonIn(page, text)).toBeEnabled();
  await deleteButtonIn(page, text).click();
  const dialog = confirmDialog(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(DELETE_MESSAGE_DIALOG_TITLE);
  return dialog;
}

/** Confirm inside the dialog (C18: unscoped, "Delete" also names every trash button). */
async function confirmDelete(page: Page) {
  const dialog = confirmDialog(page);
  await dialog.getByRole('button', { name: DELETE_MESSAGE_CONFIRM_LABEL, exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

async function sendPrompt(page: Page, prompt: string) {
  await page.getByTestId('chat-input').fill(prompt);
  await page.getByRole('button', { name: 'Send' }).click();
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe('delete a message', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);
  });

  test('an owner deletes a message and its reply; the slides, the Spec and the other messages stay; a reload agrees', async ({ page }) => {
    const deck = await mockDeletableDeck(page, { myPermission: 'CAN_MANAGE' });
    await openDeck(page);

    // ── before ──
    const audienceBefore = await readSpecAudience(page);
    for (const i of [0, 1, 2]) {
      await expect(page.getByTestId(`ribbon-thumb-${i}`)).toBeVisible();
    }
    expect(deck.counts.slidesGets).toBeGreaterThan(0);
    const slidesGetsBefore = deck.counts.slidesGets;

    // The action is on the user's messages only, and hidden until its row is hovered.
    await expect(chatPanel(page).getByTestId('delete-message-button')).toHaveCount(2);
    await expect(messageRow(page, TRANSCRIPT[3].content).getByTestId('delete-message-button')).toHaveCount(0);
    const trash = deleteButtonIn(page, TRANSCRIPT[2].content);
    await expect(trash).toHaveCSS('opacity', '0');
    await messageRow(page, TRANSCRIPT[2].content).hover();
    await expect(trash).toHaveCSS('opacity', '1');

    // ── the delete ──
    const dialog = await openDeleteDialog(page, TRANSCRIPT[2].content);
    await expect(dialog).toContainText(DELETE_MESSAGE_DIALOG_MESSAGE);
    // The promise the user is asked to accept: what that turn changed stays.
    await expect(dialog).toContainText('it is not rolled back');
    await confirmDelete(page);

    // ── after ──
    const chat = chatPanel(page);
    for (const text of SECOND_TURN) {
      await expect(chat.getByText(text, { exact: true })).toHaveCount(0);
    }
    for (const text of FIRST_TURN) {
      await expect(chat.getByText(text, { exact: true })).toBeVisible();
    }
    expect(deck.deletes).toEqual([messagePath(3)]);
    expect(deck.messageDeletes).toEqual([messagePath(3)]);

    for (const i of [0, 1, 2]) {
      await expect(page.getByTestId(`ribbon-thumb-${i}`)).toBeVisible();
    }
    expect(await readSpecAudience(page)).toBe(audienceBefore);

    // Read last, after the Spec round trip, so a refetch the delete set off has had time to land.
    expect(deck.counts.slidesGets, 'the delete refetched the slides').toBe(slidesGetsBefore);

    // ── a reload agrees ──
    const sessionGetsBeforeReload = deck.counts.sessionGets;
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    for (const text of FIRST_TURN) {
      await expect(chatPanel(page).getByText(text, { exact: true })).toBeVisible();
    }
    expect(deck.counts.sessionGets).toBeGreaterThan(sessionGetsBeforeReload);
    for (const text of SECOND_TURN) {
      await expect(chatPanel(page)).not.toContainText(text);
    }
    expect(deck.messageDeletes).toEqual([messagePath(3)]);
  });

  test('a message sent in this tab can be deleted once its turn completes, without a reload', async ({ page }) => {
    const deck = await mockDeletableDeck(page, { myPermission: 'CAN_MANAGE' });
    const prompt = 'Make slide 3 shorter';
    const reply = 'Editing slide 3.';
    const streamBodies: Record<string, unknown>[] = [];
    await page.route(apiPath('/api/chat/stream'), (route) => {
      streamBodies.push(route.request().postDataJSON());
      // The turn's rows are stored before the stream answers, as the real turn does.
      deck.state.transcript.push(
        { id: 5, role: 'user', content: prompt, created_at: '2026-10-19T09:10:00' },
        { id: 6, role: 'assistant', content: reply, created_at: '2026-10-19T09:10:20' },
      );
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse({ type: 'assistant', content: reply }, { type: 'complete', slides: DECK_AFTER_TURN }),
      });
    });
    // Hold the turn-end read, so the test sees the id arrive with it and not before.
    let releaseRead: () => void = () => {};
    deck.state.messagesReadGate = new Promise<void>((resolve) => { releaseRead = resolve; });

    await openDeck(page);
    await sendPrompt(page, prompt);

    const chat = chatPanel(page);
    await expect(chat.getByText(reply, { exact: true })).toBeVisible({ timeout: 15000 });
    expect(streamBodies, 'the mocked app sends its turn over SSE').toHaveLength(1);
    expect(streamBodies[0].session_id).toBe(TEST_SESSION_ID);

    // Until the stored conversation is read, the new message has no id and offers no delete.
    await expect.poll(() => deck.counts.messagesGets).toBeGreaterThan(0);
    await expect(deleteButtonIn(page, prompt)).toHaveCount(0);
    releaseRead();
    await expect(deleteButtonIn(page, prompt)).toHaveCount(1);
    expect(deck.messagesReads[0]).toBe('?limit=200');

    await openDeleteDialog(page, prompt);
    await confirmDelete(page);

    await expect(chat.getByText(prompt, { exact: true })).toHaveCount(0);
    await expect(chat.getByText(reply, { exact: true })).toHaveCount(0);
    expect(deck.deletes).toEqual([messagePath(5)]);
    expect(deck.messageDeletes).toEqual([messagePath(5)]);
    for (const text of TRANSCRIPT_TEXT) {
      await expect(chat.getByText(text, { exact: true })).toBeVisible();
    }
  });

  test('a viewer is not offered delete', async ({ page }) => {
    const deck = await mockDeletableDeck(page, { myPermission: 'CAN_VIEW' });
    // openDeck waits for the transcript, which ChatPanel renders in the same update
    // as it applies my_permission, so the absence below is not "not loaded yet".
    await openDeck(page);

    await expect(page.getByTestId('chat-message-row')).toHaveCount(TRANSCRIPT.length);
    await expect(page.getByTestId('delete-message-button')).toHaveCount(0);
    expect(deck.messageDeletes).toEqual([]);
  });

  test('delete is disabled while a reply is being generated', async ({ page }) => {
    await mockDeletableDeck(page, { myPermission: 'CAN_MANAGE' });
    const prompt = 'Tighten slide 2';
    const reply = 'Tightened slide 2.';
    let releaseStream: () => void = () => {};
    const streamHeld = new Promise<void>((resolve) => { releaseStream = resolve; });
    await page.route(apiPath('/api/chat/stream'), async (route) => {
      await streamHeld;
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse({ type: 'assistant', content: reply }, { type: 'complete', slides: DECK_AFTER_TURN }),
      });
    });

    await openDeck(page);
    const buttons = chatPanel(page).getByTestId('delete-message-button');
    // Precondition: enabled before the turn, so the disable below is the turn's doing.
    await expect(buttons).toHaveCount(2);
    for (const i of [0, 1]) await expect(buttons.nth(i)).toBeEnabled();

    await sendPrompt(page, prompt);
    await expect(chatPanel(page).getByText(prompt, { exact: true })).toBeVisible();
    for (const i of [0, 1]) {
      await expect(buttons.nth(i)).toBeDisabled();
      // Not hovered, so not shown: the Button base's `disabled:opacity-50` must not win.
      await expect(buttons.nth(i)).toHaveCSS('opacity', '0');
    }

    releaseStream();
    await expect(chatPanel(page).getByText(reply, { exact: true })).toBeVisible({ timeout: 15000 });
    for (const i of [0, 1]) await expect(buttons.nth(i)).toBeEnabled();
  });

  test('cancelling the dialog deletes nothing', async ({ page }) => {
    const deck = await mockDeletableDeck(page, { myPermission: 'CAN_MANAGE' });
    await openDeck(page);

    const dialog = await openDeleteDialog(page, TRANSCRIPT[2].content);
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    // An absence needs a window to fail in: a DELETE sent on cancel would be on the
    // wire within milliseconds and would empty the turn as soon as it answered.
    await page.waitForTimeout(500);
    expect(deck.messageDeletes).toEqual([]);
    expect(deck.deletes).toEqual([]);
    for (const text of TRANSCRIPT_TEXT) {
      await expect(chatPanel(page).getByText(text, { exact: true })).toBeVisible();
    }
    await expect(deleteButtonIn(page, TRANSCRIPT[2].content)).toBeEnabled();
  });

  test('a busy deck keeps the message and says why', async ({ page }) => {
    const deck = await mockDeletableDeck(page, { myPermission: 'CAN_MANAGE' });
    deck.state.deleteStatus = 409;
    await openDeck(page);

    await openDeleteDialog(page, TRANSCRIPT[2].content);
    await confirmDelete(page);

    await expect(chatPanel(page).getByText(DELETE_MESSAGE_BUSY, { exact: true })).toBeVisible();
    // The refusal was the server's: the DELETE went out and was answered 409.
    expect(deck.deletes).toEqual([messagePath(3)]);
    for (const text of TRANSCRIPT_TEXT) {
      await expect(chatPanel(page).getByText(text, { exact: true })).toBeVisible();
    }
    // The action is usable again once the refusal lands.
    await expect(deleteButtonIn(page, TRANSCRIPT[2].content)).toBeEnabled();
  });
});
