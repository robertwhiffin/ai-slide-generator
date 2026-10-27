/**
 * Deck Mode toggle, Task 7: both chat transports carry the deck's mode in the request body.
 *
 * `deckMode` is a trailing parameter on each of `sendChatMessage`, `startPolling`, `submitChatAsync`
 * and `streamChat` (after `agentConfig`), and each request body sends it as `deck_mode`. The backend
 * (Task 4) reads `deck_mode` from both `POST /api/chat/stream` and `POST /api/chat/async`.
 *
 * Behavioural only: the real `api` with a stubbed `fetch`, asserting the JSON body each transport
 * POSTs. The threading tests go through `sendChatMessage` in both modes (SSE by default under jsdom's
 * localhost; polling via `VITE_USE_POLLING`), and assert the URL too, so a green result cannot come
 * from the other transport.
 *
 * SABOTAGE (measured against a throwaway implementation outside the worktree; each turned at least one
 * test red):
 *   - drop `deck_mode` from streamChat's body                         -> the streamChat and SSE threading tests.
 *   - drop `deck_mode` from submitChatAsync's body                    -> the submitChatAsync and polling threading tests.
 *   - sendChatMessage forgets to pass deckMode to either transport    -> that transport's threading test.
 *   - startPolling forgets to pass deckMode to submitChatAsync        -> the polling threading test.
 *   - a hardcoded `deck_mode: 'agent'` (or 'legacy')                  -> the it.each case for the other value.
 */

import { api, type DeckMode } from '../api';

interface Posted { url: string; body: Record<string, unknown> }

/** Answers every POST with an empty 200 SSE/JSON body and records the URL and parsed JSON body. */
function stubFetch(posted: Posted[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST' && typeof init.body === 'string') {
      posted.push({ url, body: JSON.parse(init.body) as Record<string, unknown> });
    }
    if (url.includes('/api/chat/async')) {
      return new Response(JSON.stringify({ request_id: 'req-deck-mode' }), { status: 200 });
    }
    // The SSE stream: one complete event, then the body ends.
    return new Response('data: {"type":"complete"}\n\n', { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const MODES: DeckMode[] = ['legacy', 'agent'];

describe('deck_mode on the chat request bodies', () => {
  let cancel: (() => void) | null = null;

  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it.each(MODES)('streamChat POSTs deck_mode %j to /api/chat/stream', async (mode) => {
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    cancel = api.streamChat('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, mode);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/stream');
    expect(posted[0].body.deck_mode).toBe(mode);
    // The rest of the body is unchanged.
    expect(posted[0].body.session_id).toBe('sess-1');
    expect(posted[0].body.message).toBe('hello');
  });

  it.each(MODES)('submitChatAsync POSTs deck_mode %j to /api/chat/async', async (mode) => {
    const posted: Posted[] = [];
    stubFetch(posted);

    await expect(api.submitChatAsync('sess-1', 'hello', undefined, undefined, undefined, mode))
      .resolves.toEqual({ request_id: 'req-deck-mode' });

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/async');
    expect(posted[0].body.deck_mode).toBe(mode);
    expect(posted[0].body.session_id).toBe('sess-1');
    expect(posted[0].body.message).toBe('hello');
  });

  it.each(MODES)('sendChatMessage threads deck_mode %j to the SSE transport', async (mode) => {
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    cancel = api.sendChatMessage('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, mode);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/stream');
    expect(posted[0].body.deck_mode).toBe(mode);
  });

  it.each(MODES)(
    'sendChatMessage threads deck_mode %j through startPolling to the async submit (polling, the production transport)',
    async (mode) => {
      vi.stubEnv('VITE_USE_POLLING', 'true');
      const posted: Posted[] = [];
      const fetchMock = stubFetch(posted);

      cancel = api.sendChatMessage('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, mode);
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

      expect(posted).toHaveLength(1);
      expect(posted[0].url).toContain('/api/chat/async');
      expect(posted[0].body.deck_mode).toBe(mode);
    },
  );
});
