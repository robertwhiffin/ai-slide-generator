/**
 * Task 6 (admin permissions): the admin API client for /api/admin/admins.
 *
 * Contract as built (task-6-addendum.md):
 *   GET    /api/admin/admins        -> 200 {admins, sync}
 *   POST   /api/admin/admins        -> 201 {permission_id}; 422 with a STRING detail
 *                                       (bad type / blank name) or Pydantic's LIST detail
 *                                       (over-long field)
 *   DELETE /api/admin/admins/{id}   -> 204, empty body; 404 / 409 with a string detail
 *
 * SABOTAGE (each should turn the named test RED):
 *   - always call res.json() (no 204 branch)                -> "removeAdmin resolves on 204 ..."
 *   - throw new Error(text) (the old behaviour)              -> the `detail` cases
 *   - throw new Error(String(body.detail)) for any detail    -> the list-detail case
 *   - drop the text fallback for a non-JSON error body       -> "non-JSON error body ..."
 *   - wrong method / path / body on any of the three calls   -> that call's request test
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adminApi, type AppAdminsResponse } from './admin';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(makeResponse: () => Response) {
  const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
    async () => makeResponse(),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

interface SentRequest {
  path: string;
  search: string;
  method: string;
  body: unknown;
  contentType: string | null;
}

/** The one request made: path, method, parsed JSON body and Content-Type. */
function onlyRequest(fetchMock: ReturnType<typeof stubFetch>): SentRequest {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [input, init] = fetchMock.mock.calls[0] as unknown as [
    RequestInfo | URL,
    RequestInit | undefined,
  ];
  const url = input instanceof Request ? input.url : String(input);
  const parsed = new URL(url, 'http://placeholder.invalid');
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
  const rawBody = init?.body;
  const headers = new Headers(init?.headers);
  return {
    path: parsed.pathname,
    search: parsed.search,
    method,
    body: typeof rawBody === 'string' ? JSON.parse(rawBody) : rawBody ?? null,
    contentType: headers.get('Content-Type'),
  };
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (err) {
    return err;
  }
  throw new Error('expected the promise to reject, but it resolved');
}

const listBody: AppAdminsResponse = {
  admins: [
    {
      identity_type: 'USER',
      identity_name: 'sam@x.com',
      identity_id: 'u-sam',
      sources: ['can_manage_sync', 'manual'],
      manual_permission_id: 42,
      added_by: 'priya',
      added_at: '2026-11-01T10:00:00+00:00',
    },
  ],
  sync: {
    last_attempt_at: '2026-11-02T09:55:00+00:00',
    last_success_at: '2026-11-02T09:55:00+00:00',
    last_error: null,
  },
};

const NOT_MANUAL_DETAIL =
  "This admin comes from CAN_MANAGE on the app. Change it in the app's Permissions in Databricks.";

describe('adminApi — /api/admin/admins', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('listAdmins sends GET /api/admin/admins and resolves to the parsed body', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, listBody));

    const result = await adminApi.listAdmins();

    const req = onlyRequest(fetchMock);
    expect(req.method).toBe('GET');
    expect(req.path).toBe('/api/admin/admins');
    expect(req.search).toBe('');
    expect(result).toEqual(listBody);
  });

  it('addAdmin sends POST /api/admin/admins with the JSON body and resolves to {permission_id}', async () => {
    const fetchMock = stubFetch(() => jsonResponse(201, { permission_id: 7 }));
    const body = {
      identity_type: 'USER' as const,
      identity_name: 'priya@example.com',
      identity_id: 'u1',
    };

    const result = await adminApi.addAdmin(body);

    const req = onlyRequest(fetchMock);
    expect(req.method).toBe('POST');
    expect(req.path).toBe('/api/admin/admins');
    expect(req.body).toEqual(body);
    expect(req.contentType).toBe('application/json');
    expect(result).toEqual({ permission_id: 7 });
  });

  it('addAdmin sends a null identity_id through as null', async () => {
    const fetchMock = stubFetch(() => jsonResponse(201, { permission_id: 8 }));

    await adminApi.addAdmin({ identity_type: 'GROUP', identity_name: 'Team', identity_id: null });

    expect(onlyRequest(fetchMock).body).toEqual({
      identity_type: 'GROUP',
      identity_name: 'Team',
      identity_id: null,
    });
  });

  it('removeAdmin sends DELETE /api/admin/admins/<id> and resolves on 204 without calling res.json()', async () => {
    const res = new Response(null, { status: 204 });
    // An empty body: res.json() would reject with a SyntaxError.
    const jsonSpy = vi.spyOn(res, 'json');
    const fetchMock = stubFetch(() => res);

    await expect(adminApi.removeAdmin(42)).resolves.toBeUndefined();

    const req = onlyRequest(fetchMock);
    expect(req.method).toBe('DELETE');
    expect(req.path).toBe('/api/admin/admins/42');
    expect(jsonSpy).not.toHaveBeenCalled();
  });

  it('a non-OK response with a string `detail` rejects with an Error whose message is the detail', async () => {
    stubFetch(() => jsonResponse(403, { detail: 'x' }));

    const err = await rejectionOf(adminApi.listAdmins());

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe('x');
  });

  it('removeAdmin rejects with the 409 detail verbatim for a CAN_MANAGE-only row', async () => {
    stubFetch(() => jsonResponse(409, { detail: NOT_MANUAL_DETAIL }));

    const err = await rejectionOf(adminApi.removeAdmin(5));

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe(NOT_MANUAL_DETAIL);
  });

  it('addAdmin rejects with a 422 string detail verbatim', async () => {
    stubFetch(() => jsonResponse(422, { detail: 'identity_name must not be blank' }));

    const err = await rejectionOf(
      adminApi.addAdmin({ identity_type: 'USER', identity_name: ' ', identity_id: null }),
    );

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe('identity_name must not be blank');
  });

  it("addAdmin turns Pydantic's 422 list detail into a readable message", async () => {
    stubFetch(() =>
      jsonResponse(422, {
        detail: [
          {
            type: 'string_too_long',
            loc: ['body', 'identity_name'],
            msg: 'String should have at most 255 characters',
            input: 'x'.repeat(256),
            ctx: { max_length: 255 },
          },
        ],
      }),
    );

    const err = await rejectionOf(
      adminApi.addAdmin({ identity_type: 'USER', identity_name: 'x'.repeat(256), identity_id: null }),
    );

    expect(err).toBeInstanceOf(Error);
    const message = (err as Error).message;
    expect(message.trim()).not.toBe('');
    expect(message).not.toContain('[object Object]');
    // Not the raw JSON body.
    expect(message).not.toContain('"detail"');
    expect(message).not.toContain('string_too_long');
    // Either Pydantic's own message or a status fallback such as "Request rejected (422)".
    expect(message).toMatch(/String should have at most 255 characters|422/);
  });

  it('a non-JSON error body rejects with the body text', async () => {
    stubFetch(
      () =>
        new Response('upstream connect error', {
          status: 502,
          headers: { 'Content-Type': 'text/plain' },
        }),
    );

    const err = await rejectionOf(adminApi.listAdmins());

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe('upstream connect error');
  });

  it('an empty error body still rejects with a message naming the status', async () => {
    stubFetch(() => new Response(null, { status: 503, statusText: 'Service Unavailable' }));

    const err = await rejectionOf(adminApi.removeAdmin(1));

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toContain('503');
  });
});
