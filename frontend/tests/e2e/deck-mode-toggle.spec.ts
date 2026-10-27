import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';

/**
 * Deck Mode toggle, Task 8: the Mode dropdown under the chat box, and the agent-only furniture
 * (the pinned-version badge `graph-version-status` and the conversation-surface
 * `mixed-release-warning`) hidden on legacy decks, including an unlocked deck with Legacy selected.
 * The Share dialog's `surface="collaboration"` copy (`shared-deck-provenance`) is untouched.
 *
 * No backend runs: every API call is mocked with page.route (registered AFTER setupMocks, so
 * Playwright's last-registered-wins ordering gives these handlers precedence). Playwright runs the
 * dev server, which uses the SSE transport, so the chat body is read from `/api/chat/stream`.
 *
 * AppLayout is covered here rather than in vitest: no vitest suite renders AppLayout (the shell
 * needs every provider, the router and the editing-lock lifecycle), and a source pin would not show
 * that the badge and notice actually disappear.
 */

const LOCKED_LEGACY = '44444444-4444-4444-8444-444444444444';
const UNLOCKED = '55555555-5555-4555-8555-555555555555';

const POPUP_LINES = [
  'Agent mode: plans the deck, then builds it slide by slide, showing progress as it goes.',
  'Legacy mode: a less capable agent. Usually faster, but harder to converse with and to adapt to changes.',
  "You can change this until you send your first message. After that it's fixed for this deck.",
];

/** Two releases on one deck: renders the conversation `mixed-release-warning` on an agent deck. */
const MIXED_HISTORY = {
  mixed_release_warning: true,
  has_legacy_evidence: false,
  groups: [
    { actor_label: 'Contributor 1', graph_version: 2, mutation_count: 3, last_mutation_at: '2026-09-20T10:15:00Z' },
    { actor_label: 'Contributor 2', graph_version: 1, mutation_count: 2, last_mutation_at: '2026-09-19T09:05:00Z' },
  ],
};

type DeckMode = 'agent' | 'legacy';

interface SessionShape {
  title: string | null;
  deckMode: DeckMode | null;
  graphVersion: number | null;
  activeGraphVersion: number;
  isOlder: boolean;
}

function sessionResponse(sessionId: string, s: SessionShape) {
  return {
    session_id: sessionId,
    title: s.title,
    created_at: new Date().toISOString(),
    has_slide_deck: false,
    my_permission: 'CAN_MANAGE',
    graph_version: s.graphVersion,
    active_graph_version: s.activeGraphVersion,
    is_older_than_active: s.isOlder,
    deck_mode: s.deckMode,
    messages: [],
  };
}

/** An unshared deck: the editing lock is granted at once, so the deck is editable. */
async function allowEditing(page: Page) {
  await page.route('**/api/user/current', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ username: 'test@example.com' }) });
  });
  await page.route(/\/api\/sessions\/[^/]+\/contributors$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ contributors: [] }) });
  });
}

async function mockSessionDetail(page: Page, sessionId: string, s: SessionShape) {
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, async (route, request) => {
    if (request.method() !== 'GET') {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessionResponse(sessionId, s)) });
  });
}

async function mockCollaborationHistory(page: Page, sessionId: string, body: unknown) {
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/collaboration-history`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

/** Every chat request body, on either transport (the dev server uses /stream). */
async function recordChat(page: Page): Promise<Array<Record<string, unknown>>> {
  const bodies: Array<Record<string, unknown>> = [];
  await page.route(/\/api\/chat(\/stream|\/async)?$/, async (route, request) => {
    bodies.push(request.postDataJSON() as Record<string, unknown>);
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"complete"}\n\n' });
  });
  return bodies;
}

const modeSelect = (page: Page) => page.getByTestId('deck-mode-select');
const badge = (page: Page) => page.getByTestId('graph-version-status');
const conversationNotice = (page: Page) => page.getByTestId('mixed-release-warning');
const titleButton = (page: Page, title: string) => page.getByRole('button', { name: title, exact: true });

/** The info trigger: the `deck-mode-info` button, or the button the `deck-mode-info` icon sits in. */
const infoTrigger = (page: Page) =>
  page.locator('button[data-testid="deck-mode-info"], button:has([data-testid="deck-mode-info"])');

async function expectPopupLines(page: Page, how: 'hover' | 'focus') {
  if (how === 'hover') {
    await page.getByTestId('deck-mode-info').hover();
  } else {
    // Keyboard reach: a disabled trigger cannot take focus (Chromium still fires pointermove on a
    // disabled button, so hover alone would not show a locked control's popup is reachable).
    await expect(infoTrigger(page)).toBeEnabled();
    await infoTrigger(page).focus();
  }
  // Radix renders the content twice; the role="tooltip" copy exists only while it is open (C4).
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toHaveCount(1);
  for (const line of POPUP_LINES) {
    await expect(tooltip).toContainText(line);
  }
}

test.describe('deck mode toggle', () => {
  test('choosing Legacy hides the version badge, sends deck_mode legacy, then locks the control', async ({ page }) => {
    await setupMocks(page);
    await allowEditing(page);

    const created = new Set<string>();
    const chatBodies: Array<Record<string, unknown>> = [];
    let streamServed: () => void = () => {};
    const streamDone = new Promise<void>((resolve) => { streamServed = resolve; });
    const reRestores: string[] = [];

    // The landing deck's first send persists its browser-local id (ensureGraphCapableRoot).
    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      const body = request.postDataJSON() as Record<string, unknown>;
      const id = body.session_id as string;
      created.add(id);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(id, { title: null, deckMode: null, graphVersion: 2, activeGraphVersion: 2, isOlder: false })),
      });
    });
    // GET /api/sessions/{id}: 404 until persisted (a browser-local id); afterwards a STATIC
    // `deck_mode: null` (the lock has not committed when the re-restore reads it). Held until the
    // turn's `complete` has been served, so the same-id re-restore that ensureGraphCapableRoot's
    // navigate triggers lands AFTER the turn: a clobbered optimistic lock would re-enable the select.
    await page.route(
      (url) => /^\/api\/sessions\/[^/]+$/.test(url.pathname),
      async (route, request) => {
        if (request.method() !== 'GET') {
          await route.fallback();
          return;
        }
        const id = new URL(request.url()).pathname.split('/').pop() as string;
        if (!created.has(id)) {
          await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Session not found' }) });
          return;
        }
        await streamDone;
        reRestores.push(id);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(sessionResponse(id, { title: 'Puffin deck', deckMode: null, graphVersion: 2, activeGraphVersion: 2, isOlder: false })),
        });
      },
    );
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route, request) => {
      chatBodies.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"complete"}\n\n' });
      streamServed();
    });

    // The browser-local root (as conversation-graph-version.spec.ts starts): this is the production
    // first-send path, including the same-id re-restore (PLAN-CORRECTIONS Task 7 C2).
    await page.goto('/');
    await expect(page.getByTestId('chat-input')).toBeEnabled();
    await expect(modeSelect(page)).toBeEnabled();
    await expect(modeSelect(page)).toHaveValue('agent');
    await expect(badge(page)).toBeVisible();

    await modeSelect(page).selectOption('legacy');
    await expect(badge(page)).toHaveCount(0); // hidden before anything is sent
    await expect(modeSelect(page)).toHaveValue('legacy');
    await expect(modeSelect(page)).toBeEnabled();
    expect(chatBodies).toEqual([]); // choosing sends nothing

    await page.getByTestId('chat-input').fill('Build a deck about puffins');
    await page.getByTestId('chat-input').press('Enter');

    await expect.poll(() => chatBodies.length).toBe(1);
    expect(chatBodies[0]).toMatchObject({ deck_mode: 'legacy' });
    const sentTo = chatBodies[0].session_id as string;
    expect(created.has(sentTo)).toBe(true);

    // After the `complete` event AND the same-id re-restore: the re-restore has committed (its title
    // is on screen), the turn is over (the input is enabled again), and the control is still locked
    // on Legacy with no badge.
    await expect(titleButton(page, 'Puffin deck')).toBeVisible();
    expect(reRestores).toContain(sentTo);
    await expect(page).toHaveURL(new RegExp(`/sessions/${sentTo}/edit`));
    await expect(page.getByTestId('chat-input')).toBeEnabled();
    await expect(modeSelect(page)).toBeDisabled();
    await expect(modeSelect(page)).toHaveValue('legacy');
    await expect(badge(page)).toHaveCount(0);
    expect(chatBodies).toHaveLength(1);
  });

  test('a locked legacy deck opens greyed on Legacy with no badge, loaded by URL', async ({ page }) => {
    await setupMocks(page);
    await allowEditing(page);
    // Pinned to an older release, with mixed-release history: on an agent deck both the badge
    // ("Pinned Graph Version 1; latest is 2" + Start latest) and the conversation notice would show.
    await mockSessionDetail(page, LOCKED_LEGACY, { title: 'Legacy deck', deckMode: 'legacy', graphVersion: 1, activeGraphVersion: 2, isOlder: true });
    await mockCollaborationHistory(page, LOCKED_LEGACY, MIXED_HISTORY);
    const chatBodies = await recordChat(page);

    const expectLockedLegacy = async () => {
      await expect(titleButton(page, 'Legacy deck')).toBeVisible(); // the restore has committed
      await expect(page.getByTestId('chat-input')).toBeEnabled(); // editable: the grey is the lock
      await expect(modeSelect(page)).toBeDisabled();
      await expect(modeSelect(page)).toHaveValue('legacy');
      await expect(badge(page)).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Start latest' })).toHaveCount(0);
    };
    /** The Share dialog's copy proves the history has landed; the conversation copy stays hidden. */
    const expectShareDialogKeepsProvenance = async () => {
      await page.getByRole('button', { name: 'Share', exact: true }).click();
      await expect(page.getByTestId('shared-deck-provenance')).toBeVisible();
      await expect(conversationNotice(page)).toHaveCount(0);
    };

    // The loadSessionFromServer restore path.
    await page.goto(`/sessions/${LOCKED_LEGACY}/edit`);
    await expectLockedLegacy();
    // The info popup still opens when the control is locked, by keyboard focus as well as by hover.
    await expectPopupLines(page, 'focus');
    await expectShareDialogKeepsProvenance();

    await page.reload();
    await expectLockedLegacy();
    await expectPopupLines(page, 'hover');
    await expectShareDialogKeepsProvenance();
    expect(chatBodies).toEqual([]);
  });

  test('on an unlocked saved deck, Legacy hides the badge and the mixed-release notice before sending; Agent brings them back', async ({ page }) => {
    await setupMocks(page);
    await allowEditing(page);
    await mockSessionDetail(page, UNLOCKED, { title: 'Unlocked deck', deckMode: null, graphVersion: 1, activeGraphVersion: 2, isOlder: true });
    await mockCollaborationHistory(page, UNLOCKED, MIXED_HISTORY);
    const chatBodies = await recordChat(page);

    await page.goto(`/sessions/${UNLOCKED}/edit`);
    await expect(titleButton(page, 'Unlocked deck')).toBeVisible();
    await expect(modeSelect(page)).toBeEnabled();
    await expect(modeSelect(page)).toHaveValue('agent');
    // Positive control: on Agent mode this deck shows both pieces of agent furniture.
    await expect(badge(page)).toContainText('Pinned Graph Version 1; latest is 2');
    await expect(conversationNotice(page)).toBeVisible();

    const mutations: string[] = [];
    page.on('request', (request) => {
      if (request.method() !== 'GET' && request.url().includes('/api/')) mutations.push(`${request.method()} ${request.url()}`);
    });

    await modeSelect(page).selectOption('legacy');
    await expect(badge(page)).toHaveCount(0);
    await expect(conversationNotice(page)).toHaveCount(0);
    await expect(modeSelect(page)).toBeEnabled(); // still unlocked: nothing was sent

    await modeSelect(page).selectOption('agent');
    await expect(badge(page)).toContainText('Pinned Graph Version 1; latest is 2');
    await expect(conversationNotice(page)).toBeVisible();

    // Legacy again, then the Share dialog: its collaboration copy is not the conversation notice.
    await modeSelect(page).selectOption('legacy');
    await expect(conversationNotice(page)).toHaveCount(0);
    await page.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(page.getByTestId('shared-deck-provenance')).toBeVisible();
    await expect(conversationNotice(page)).toHaveCount(0);

    expect(chatBodies).toEqual([]);
    expect(mutations).toEqual([]); // choosing a mode saves nothing
  });
});
