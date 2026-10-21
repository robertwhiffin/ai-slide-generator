/**
 * #323 Task 4: the conversation API client (Clear chat).
 *
 * `conversationApi.clearChat(sessionId)` sends DELETE /api/sessions/{id}/context,
 * resolves to the parsed body on success, and rejects with the app's existing
 * `ApiError` (services/api.ts) carrying the HTTP status and the backend's message.
 *
 * SABOTAGE:
 *   - send POST instead of DELETE            -> "sends DELETE ..." RED.
 *   - drop encodeURIComponent on the id      -> "URL-encodes the session id" RED.
 *   - pass `detail` through as the message   -> detail-object case RED ("[object Object]").
 *   - resolve instead of throwing on !ok     -> every error case RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { conversationApi, type ClearChatResult } from './conversation';
import { ApiError } from '../services/api';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(makeResponse: () => Response) {
  const fetchMock = vi.fn(async () => makeResponse());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** The URL and method of the one fetch call, whether it passed (url, init) or a Request. */
function onlyRequest(fetchMock: ReturnType<typeof stubFetch>): { url: string; method: string } {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [input, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit | undefined];
  if (input instanceof Request) {
    return { url: input.url, method: (init?.method ?? input.method).toUpperCase() };
  }
  return { url: String(input), method: (init?.method ?? 'GET').toUpperCase() };
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (err) {
    return err;
  }
  throw new Error('expected the promise to reject, but it resolved');
}

describe('conversationApi.clearChat', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends DELETE to /api/sessions/<id>/context and resolves to the parsed body', async () => {
    const body: ClearChatResult = {
      status: 'cleared',
      session_id: 'sess-1',
      deleted_messages: 7,
      preserved_message_id: 42,
    };
    const fetchMock = stubFetch(() => jsonResponse(200, body));

    const result = await conversationApi.clearChat('sess-1');

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('DELETE');
    expect(url.endsWith('/api/sessions/sess-1/context')).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe('/api/sessions/sess-1/context');
    expect(parsed.search).toBe('');
    expect(parsed.hash).toBe('');
    expect(result).toEqual(body);
  });

  it('URL-encodes the session id as a single path segment', async () => {
    const sessionId = 'team/deck 1?x#y';
    const encoded = 'team%2Fdeck%201%3Fx%23y';
    const fetchMock = stubFetch(() =>
      jsonResponse(200, {
        status: 'cleared',
        session_id: sessionId,
        deleted_messages: 0,
        preserved_message_id: null,
      }),
    );

    await conversationApi.clearChat(sessionId);

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('DELETE');
    expect(url.endsWith(`/api/sessions/${encoded}/context`)).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe(`/api/sessions/${encoded}/context`);
    expect(parsed.search).toBe('');
    expect(parsed.hash).toBe('');
  });

  it('rejects with ApiError(409, detail) when detail is a string', async () => {
    stubFetch(() => jsonResponse(409, { detail: 'busy' }));

    const err = await rejectionOf(conversationApi.clearChat('sess-1'));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe('busy');
  });

  it('rejects with ApiError(403, detail.message) when detail is an object', async () => {
    stubFetch(() => jsonResponse(403, { detail: { code: 'forbidden', message: 'nope' } }));

    const err = await rejectionOf(conversationApi.clearChat('sess-1'));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).message).toBe('nope');
    expect((err as ApiError).message).not.toBe('[object Object]');
  });

  it('rejects with ApiError(500) and the fallback message when the body is not JSON', async () => {
    stubFetch(
      () =>
        new Response('<html><body>Internal Server Error</body></html>', {
          status: 500,
          headers: { 'Content-Type': 'text/html' },
        }),
    );

    const err = await rejectionOf(conversationApi.clearChat('sess-1'));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).message).toBe('Failed to clear the chat');
  });
});
