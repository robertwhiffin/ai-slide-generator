/**
 * I1 — typed chat 503 body shows the backend message, not [object Object].
 *
 * Both chat transports (streamChat and submitChatAsync) receive 503 with a
 * dict body from the backend:
 *   {"code": "lakebase_unavailable", "message": "Conversation configuration
 *    is temporarily unavailable. Please retry."}
 *
 * Before the fix, `api.ts` passed `error.detail` (the dict) directly as the
 * ApiError message, so `err.message === "[object Object]"`.
 * After the fix, the `message` field is extracted and `err.message` equals
 * the backend string.
 *
 * SABOTAGE: revert the call-site fix so `error.detail` is passed as-is.
 *   - streamChat test → RED: `err.message === "[object Object]"`, not the backend message.
 *   - submitChatAsync test → RED: thrown ApiError message is "[object Object]".
 */

import { api, ApiError } from '../api';

const BACKEND_MESSAGE = 'Conversation configuration is temporarily unavailable. Please retry.';

const BACKEND_503_DETAIL = {
  code: 'lakebase_unavailable',
  message: BACKEND_MESSAGE,
};

const make503 = () =>
  new Response(JSON.stringify({ detail: BACKEND_503_DETAIL }), {
    status: 503,
    headers: { 'Content-Type': 'application/json' },
  });

// ---------------------------------------------------------------------------
// streamChat — error is delivered via the onError callback
// ---------------------------------------------------------------------------

describe('I1 — streamChat typed 503 body', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('delivers the backend message string, not [object Object]', () => {
    vi.stubGlobal('fetch', vi.fn(async () => make503()));

    return new Promise<void>((resolve, reject) => {
      const cancel = api.streamChat(
        'session-x',
        'hello',
        undefined,
        () => {},
        (err) => {
          try {
            expect(err).toBeInstanceOf(ApiError);
            expect(err.message).toBe(BACKEND_MESSAGE);
            expect(err.message).not.toBe('[object Object]');
            resolve();
          } catch (e) {
            reject(e);
          } finally {
            cancel();
          }
        },
      );
    });
  });
});

// ---------------------------------------------------------------------------
// submitChatAsync — error is thrown (awaited)
// ---------------------------------------------------------------------------

describe('I1 — submitChatAsync typed 503 body', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('throws ApiError whose message equals the backend message, not [object Object]', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => make503()));

    let caught: ApiError | null = null;
    try {
      await api.submitChatAsync('session-x', 'hello');
    } catch (err) {
      if (err instanceof ApiError) caught = err;
    }

    expect(caught).not.toBeNull();
    expect(caught!.message).toBe(BACKEND_MESSAGE);
    expect(caught!.message).not.toBe('[object Object]');
    expect(caught!.status).toBe(503);
  });
});
