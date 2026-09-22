import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';

const SESSION_A = '11111111-1111-4111-8111-111111111111';
const SESSION_B = '22222222-2222-4222-8222-222222222222';

function sessionResponse(sessionId: string, graphVersion: number | null, activeGraphVersion: number, isOlder: boolean) {
  return {
    session_id: sessionId,
    title: 'Pinned conversation',
    created_at: new Date().toISOString(),
    has_slide_deck: false,
    graph_version: graphVersion,
    active_graph_version: activeGraphVersion,
    is_older_than_active: isOlder,
  };
}

async function allowEditing(page: import('@playwright/test').Page) {
  await page.route('**/api/user/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'test@example.com' }),
    });
  });
  await page.route(/\/api\/sessions\/[^/]+\/contributors$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ contributors: [] }),
    });
  });
}

test.describe('conversation graph versions', () => {
  test('New Deck persists a graph-capable root before its first USE AGENT MODE turn', async ({ page }) => {
    await setupMocks(page);
    const creations: Array<Record<string, unknown>> = [];
    const graphTurns: Array<Record<string, unknown>> = [];

    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      const body = request.postDataJSON() as Record<string, unknown>;
      creations.push(body);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(body.session_id as string, 2, 2, false)),
      });
    });
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route, request) => {
      graphTurns.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"complete"}\n\n',
      });
    });
    await page.route(
      (url) => /^\/api\/sessions\/[^/]+$/.test(url.pathname),
      async (route, request) => {
        if (request.method() !== 'GET') {
          await route.fallback();
          return;
        }
        const sessionId = request.url().split('/').pop()!;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(sessionResponse(sessionId, 2, 2, false)),
        });
      },
    );
    await allowEditing(page);

    await page.goto('/');
    await page.getByRole('button', { name: 'New Deck' }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);

    expect(creations).toHaveLength(1);
    const createdId = creations[0].session_id;
    expect(createdId).toMatch(/[0-9a-f-]{36}/);
    expect(creations[0]).toMatchObject({ session_id: createdId, graph_capable: true });
    expect(graphTurns).toHaveLength(0);

    await page.getByTestId('chat-input').fill('USE AGENT MODE build a deck about puffins');
    await page.getByTestId('chat-input').press('Enter');
    await expect.poll(() => graphTurns.length).toBe(1);
    expect(graphTurns[0]).toMatchObject({ session_id: createdId });
  });

  test('Start latest creates graph-capable B without mutating older A', async ({ page }) => {
    await setupMocks(page);
    const creationBodies: Array<Record<string, unknown>> = [];
    const oldSessionMutations: string[] = [];

    await page.route(`http://127.0.0.1:8000/api/sessions/${SESSION_A}`, async (route, request) => {
      if (request.method() !== 'GET') oldSessionMutations.push(request.method());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(SESSION_A, 1, 2, true)),
      });
    });
    await page.route(`http://127.0.0.1:8000/api/sessions/${SESSION_B}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(SESSION_B, 2, 2, false)),
      });
    });
    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      creationBodies.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(SESSION_B, 2, 2, false)),
      });
    });
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('graph-version-status')).toContainText('Agent version 1; latest is 2');
    await page.getByRole('button', { name: 'Start latest' }).click();

    await expect(page).toHaveURL(new RegExp(`/sessions/${SESSION_B}/edit`));
    expect(creationBodies).toEqual([{ graph_capable: true }]);
    expect(oldSessionMutations).toEqual([]);
  });

  test('Start latest creation 503 retains older A without a graph turn', async ({ page }) => {
    await setupMocks(page);
    const creationBodies: Array<Record<string, unknown>> = [];
    const graphTurns: Array<Record<string, unknown>> = [];
    const oldSessionMutations: string[] = [];

    await page.route(`http://127.0.0.1:8000/api/sessions/${SESSION_A}`, async (route, request) => {
      if (request.method() !== 'GET') oldSessionMutations.push(request.method());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(SESSION_A, 1, 2, true)),
      });
    });
    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      creationBodies.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Graph runtime is unavailable' }),
      });
    });
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route, request) => {
      graphTurns.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    });
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('graph-version-status')).toContainText('Agent version 1; latest is 2');
    await page.getByRole('button', { name: 'Start latest' }).click();

    await expect(page.locator('[data-testid="toast"]').first()).toContainText('Failed to start the latest conversation');
    await expect(page).toHaveURL(new RegExp(`/sessions/${SESSION_A}/edit`));
    await expect(page.getByTestId('graph-version-status')).toContainText('Agent version 1; latest is 2');
    expect(creationBodies).toEqual([{ graph_capable: true }]);
    expect(graphTurns).toEqual([]);
    expect(oldSessionMutations).toEqual([]);
  });

  test('New Deck creation 503 leaves a local null-version session and sends no graph turn', async ({ page }) => {
    await setupMocks(page);
    const graphTurns: Array<Record<string, unknown>> = [];

    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Graph runtime is unavailable' }),
      });
    });
    await page.route('http://127.0.0.1:8000/api/chat/stream', async (route, request) => {
      graphTurns.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    });
    await allowEditing(page);

    await page.goto('/');
    await page.getByRole('button', { name: 'New Deck' }).click();

    await expect(page.locator('[data-testid="toast"]').first()).toContainText('Failed to create a new session');
    await expect(page).toHaveURL('/');
    await expect(page.getByTestId('graph-version-status')).toContainText('Agent version unavailable');
    expect(graphTurns).toEqual([]);
  });
});
