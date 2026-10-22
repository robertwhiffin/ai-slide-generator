/**
 * #314 Task 6: `api.insertSlide(position, sessionId, expectedVersion?)` (plan Task 6 Interfaces; the
 * C21 pre-brief on reading `detail`).
 *
 *   - POST `/api/slides` with a JSON body of `session_id` and `position`, plus `expected_version` only
 *     when the caller gives one, and NO `html` (the server then builds the deck's blank shell, D1).
 *   - Returns the parsed body: the deck plus `inserted_slide_id` / `inserted_position` (Task 3, m6).
 *   - On !ok throws `ApiError(status, message)`, where `message` is the body's `detail` when that is a
 *     string (FastAPI's 409/423 `{"detail": "..."}`: the server's own text, which the viewer toasts) and
 *     otherwise 'Failed to insert slide' (a validation list, an object, no JSON at all).
 *
 * SABOTAGE (each run against a throwaway implementation, then reverted):
 *   - always send `html: ''` (or any html)              -> "no html" RED.
 *   - drop `expected_version` when given               -> "expected_version" RED.
 *   - a fixed 'Deck was modified by another user' on 409 (the sibling methods' pattern) -> 409 RED.
 *   - pass a non-string `detail` through as the message -> "non-string detail" RED.
 *   - let a non-JSON error body throw its parse error   -> "non-JSON" RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api';

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async (..._args: FetchArgs) => response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const SID = 'sess-314';

const INSERTED = {
  title: 'Deck',
  slide_count: 3,
  css: '',
  external_scripts: [],
  scripts: '',
  slides: [
    { index: 0, slide_id: 'a', html: '<div class="slide">A</div>', scripts: '' },
    { index: 1, slide_id: 'new', html: '<section data-label="Ground"><div class="slide"></div></section>', scripts: '' },
    { index: 2, slide_id: 'b', html: '<div class="slide">B</div>', scripts: '' },
  ],
  version: 8,
  inserted_slide_id: 'new',
  inserted_position: 1,
};

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected api.insertSlide to reject');
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api.insertSlide — request', () => {
  it('POSTs session_id and position as JSON to /api/slides, with no html', async () => {
    const fetchMock = stubFetch(jsonResponse(INSERTED));

    await api.insertSlide(1, SID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/slides$/);
    expect(init?.method).toBe('POST');
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json');
    const body = JSON.parse(String(init?.body));
    expect(body.session_id).toBe(SID);
    expect(body.position).toBe(1);
    expect(body).not.toHaveProperty('html');
    // No version given: none sent (absent or null both mean "no check" to the route).
    expect(body.expected_version ?? null).toBeNull();
    expect(Object.keys(body).every((k) => ['session_id', 'position', 'expected_version'].includes(k))).toBe(true);
  });

  it('sends expected_version when the caller gives one', async () => {
    const fetchMock = stubFetch(jsonResponse(INSERTED));

    await api.insertSlide(3, SID, 7);

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({ session_id: SID, position: 3, expected_version: 7 });
  });

  it('returns the parsed body, inserted_slide_id and inserted_position included', async () => {
    stubFetch(jsonResponse(INSERTED));

    const result = await api.insertSlide(1, SID);

    expect(result).toEqual(INSERTED);
    expect(result.inserted_slide_id).toBe('new');
    expect(result.inserted_position).toBe(1);
  });
});

describe('api.insertSlide — errors', () => {
  it.each([
    [409, 'Something is still running on this deck. Wait for it to finish, then try again.'],
    [409, 'The deck changed while the slide was being added. Refresh and try again.'],
    [423, 'Session is locked by Alice Example'],
    [500, 'Failed to insert slide: database unavailable'],
  ])('a %i with a string detail throws ApiError(status, that detail)', async (status, detail) => {
    stubFetch(jsonResponse({ detail }, status));

    const error = await rejectionOf(api.insertSlide(1, SID));

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(status);
    expect((error as ApiError).message).toBe(detail);
  });

  it('a non-string detail (a 422 validation list) falls back to "Failed to insert slide"', async () => {
    stubFetch(
      jsonResponse(
        { detail: [{ loc: ['body', 'position'], msg: 'Input should be a valid integer', type: 'int_parsing' }] },
        422,
      ),
    );

    const error = await rejectionOf(api.insertSlide(1, SID));

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toBe('Failed to insert slide');
  });

  it('a body with no detail falls back to "Failed to insert slide"', async () => {
    stubFetch(jsonResponse({ error: 'nope' }, 409));

    const error = await rejectionOf(api.insertSlide(1, SID));

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe('Failed to insert slide');
  });

  it('a non-JSON error body (a proxy page) throws ApiError(status, "Failed to insert slide")', async () => {
    stubFetch(new Response('<html><body>502 Bad Gateway</body></html>', { status: 502 }));

    const error = await rejectionOf(api.insertSlide(1, SID));

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).message).toBe('Failed to insert slide');
  });
});
