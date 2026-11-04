/**
 * `api.getSession(sessionId)` asks for the session WITHOUT its deck.
 *
 * None of its callers reads `slide_deck`: a deck open reads title/flags (AppLayout, SessionContext),
 * messages and permission (ChatPanel), and deck mode (ChatPanel's error reconcile), and takes the deck
 * from `getSlides`. Without `include_deck=false` every call downloaded the whole deck again: in a prod
 * trace, two extra 3.16 MB downloads per deck open, the second one ahead of the chat.
 *
 * SABOTAGE (run against a throwaway implementation, then reverted):
 *   - fetch `/api/sessions/{id}` with no query          -> "include_deck=false" RED.
 *   - drop the ApiError on !ok                           -> "status" RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api';

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function stubFetch(response: Response) {
  const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>(async () => response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('api.getSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests the session with include_deck=false', async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ session_id: 'sess-1', messages: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const session = await api.getSession('sess-1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/sessions\/sess-1\?include_deck=false$/);
    expect(session.session_id).toBe('sess-1');
  });

  it('throws an ApiError carrying the status on a failed response', async () => {
    stubFetch(new Response('{"detail":"Session not found"}', { status: 404 }));

    const error = await api.getSession('missing').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
  });
});
