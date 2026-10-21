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
 *
 * #317 Task 6 adds `deleteMessage(sessionId, messageId)` (DELETE /api/sessions/{id}/messages/{messageId})
 * and `listMessages(sessionId, limit?)` (GET /api/sessions/{id}/messages[?limit=N]), with the same
 * error contract.
 *
 * SABOTAGE (#317):
 *   - send POST from deleteMessage            -> "deleteMessage sends one DELETE ..." RED.
 *   - drop the `?limit=` query from listMessages -> "listMessages with a limit ..." RED.
 *   - always send `?limit=` from listMessages -> "listMessages sends one GET ..." RED.
 *   - resolve instead of throwing on !ok      -> every #317 error case RED.
 *   - encodeURI (not encodeURIComponent) on the session id in deleteMessage / listMessages
 *                                             -> the "URL-encodes the session id" cases RED.
 *   - reword listMessages' fallback text       -> "listMessages rejects with the fallback ..." RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  conversationApi,
  type ClearChatResult,
  type DeleteMessageResult,
  type SessionMessagesResult,
} from './conversation';
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

describe('conversationApi.deleteMessage (#317)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends one DELETE to /api/sessions/<id>/messages/<messageId> and resolves to the parsed body', async () => {
    const body: DeleteMessageResult = {
      status: 'deleted',
      session_id: 'sess 1',
      message_id: 42,
      deleted_messages: 3,
      hidden_message_id: null,
    };
    const fetchMock = stubFetch(() => jsonResponse(200, body));

    const result = await conversationApi.deleteMessage('sess 1', 42);

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('DELETE');
    expect(url.endsWith('/api/sessions/sess%201/messages/42')).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe('/api/sessions/sess%201/messages/42');
    expect(parsed.search).toBe('');
    expect(parsed.hash).toBe('');
    expect(result).toEqual(body);
  });

  it('URL-encodes the session id as a single path segment', async () => {
    const sessionId = 'team/deck 1?x#y';
    const encoded = 'team%2Fdeck%201%3Fx%23y';
    const fetchMock = stubFetch(() =>
      jsonResponse(200, {
        status: 'deleted',
        session_id: sessionId,
        message_id: 42,
        deleted_messages: 2,
        hidden_message_id: null,
      }),
    );

    await conversationApi.deleteMessage(sessionId, 42);

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('DELETE');
    expect(url.endsWith(`/api/sessions/${encoded}/messages/42`)).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe(`/api/sessions/${encoded}/messages/42`);
    expect(parsed.search).toBe('');
    expect(parsed.hash).toBe('');
  });

  it('rejects with ApiError(404, detail) when the message is gone', async () => {
    stubFetch(() => jsonResponse(404, { detail: 'gone' }));

    const err = await rejectionOf(conversationApi.deleteMessage('sess 1', 42));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).toBe('gone');
  });

  it('rejects with ApiError(409) when a turn is running', async () => {
    stubFetch(() => jsonResponse(409, { detail: 'busy' }));

    const err = await rejectionOf(conversationApi.deleteMessage('sess 1', 42));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe('busy');
  });

  it('rejects with ApiError(500) and the fallback message when the body is not JSON', async () => {
    stubFetch(
      () =>
        new Response('<html><body>Internal Server Error</body></html>', {
          status: 500,
          headers: { 'Content-Type': 'text/html' },
        }),
    );

    const err = await rejectionOf(conversationApi.deleteMessage('sess 1', 42));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).message).toBe('Failed to delete the message');
  });
});

describe('conversationApi.listMessages (#317)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const BODY: SessionMessagesResult = {
    session_id: 'sess 1',
    messages: [
      { id: 1, role: 'user', content: 'Build a deck about puffins', message_type: 'chat', created_at: '2026-10-20T10:00:00' },
      { id: 2, role: 'assistant', content: 'Here is a plan.', message_type: 'llm_response', created_at: '2026-10-20T10:00:05' },
    ],
    count: 2,
  };

  it('sends one GET to /api/sessions/<id>/messages, with no query, and resolves to the body', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, BODY));

    const result = await conversationApi.listMessages('sess 1');

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('GET');
    expect(url.endsWith('/api/sessions/sess%201/messages')).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe('/api/sessions/sess%201/messages');
    expect(parsed.search).toBe('');
    expect(result).toEqual(BODY);
  });

  it('with a limit, sends one GET to /api/sessions/<id>/messages?limit=<limit> (the newest rows)', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, BODY));

    const result = await conversationApi.listMessages('sess 1', 200);

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('GET');
    expect(url.endsWith('/api/sessions/sess%201/messages?limit=200')).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe('/api/sessions/sess%201/messages');
    expect(parsed.search).toBe('?limit=200');
    expect(result).toEqual(BODY);
  });

  it('URL-encodes the session id as a single path segment, and the limit stays in the query', async () => {
    const sessionId = 'team/deck 1?x#y';
    const encoded = 'team%2Fdeck%201%3Fx%23y';
    const fetchMock = stubFetch(() => jsonResponse(200, { ...BODY, session_id: sessionId }));

    await conversationApi.listMessages(sessionId, 200);

    const { url, method } = onlyRequest(fetchMock);
    expect(method).toBe('GET');
    expect(url.endsWith(`/api/sessions/${encoded}/messages?limit=200`)).toBe(true);
    const parsed = new URL(url, 'http://placeholder.invalid');
    expect(parsed.pathname).toBe(`/api/sessions/${encoded}/messages`);
    expect(parsed.search).toBe('?limit=200');
    expect(parsed.hash).toBe('');
  });

  it('rejects with the fallback message when the error body is not JSON', async () => {
    stubFetch(
      () =>
        new Response('<html><body>Bad Gateway</body></html>', {
          status: 502,
          headers: { 'Content-Type': 'text/html' },
        }),
    );

    const err = await rejectionOf(conversationApi.listMessages('sess 1'));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).message).toBe('Failed to load the conversation');
  });

  it('rejects with ApiError(403) when the caller is not the session creator', async () => {
    stubFetch(() => jsonResponse(403, { detail: 'Only the session creator can read its conversation.' }));

    const err = await rejectionOf(conversationApi.listMessages('sess 1'));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).message).toBe('Only the session creator can read its conversation.');
  });
});
