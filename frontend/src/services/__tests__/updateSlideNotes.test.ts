/**
 * Speaker notes plan, Task 4: `api.updateSlideNotes(index, fields, sessionId, slideId?, expectedVersion?)`
 * where `fields` is `{ speaker_notes?: string; talk_track?: string }` (Task 4 Interfaces; the route body
 * is Task 2's `PATCH /api/slides/{index}/notes`).
 *
 *   - PATCH `/api/slides/<index>/notes` with a JSON body of `session_id` plus ONLY the text keys the
 *     caller gave. A missing key leaves that field untouched on the server, so saving the talk track
 *     must never resend a stale notes draft over a chat rebuild (plan risk 5).
 *   - An empty string is a real save (clearing), so it is sent, not dropped.
 *   - `slide_id` and `expected_version` pass through when given.
 *   - Resolves to the parsed body, `talk_track` included.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function stubFetch(response: Response) {
  const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>(async () => response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function sentBody(fetchMock: ReturnType<typeof stubFetch>): Record<string, unknown> {
  return JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
}

const SID = 'sess-notes';

const SAVED = {
  index: 2,
  slide_id: 'slide-abc',
  speaker_notes: 'Source: Q3 report.',
  talk_track: 'Revenue grew because of the new region.',
  version: 12,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api.updateSlideNotes — request', () => {
  // Sabotage target: a changed method or path (for example POST, or /api/slides/<index>/talk-track).
  it('PATCHes /api/slides/<index>/notes as JSON', async () => {
    const fetchMock = stubFetch(jsonResponse(SAVED));

    await api.updateSlideNotes(2, { talk_track: 'x' }, SID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/slides\/2\/notes$/);
    expect(init?.method).toBe('PATCH');
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json');
  });

  // Sabotage target: always sends both keys (a talk-track save resends the notes).
  it('a talk-track save sends talk_track and session_id, with no speaker_notes key', async () => {
    const fetchMock = stubFetch(jsonResponse(SAVED));

    await api.updateSlideNotes(2, { talk_track: 'x' }, SID);

    const body = sentBody(fetchMock);
    expect(body.talk_track).toBe('x');
    expect(body.session_id).toBe(SID);
    expect('speaker_notes' in body).toBe(false);
  });

  // Sabotage target: always sends both keys (a notes save resends the talk track).
  it('a notes save sends speaker_notes, with no talk_track key', async () => {
    const fetchMock = stubFetch(jsonResponse(SAVED));

    await api.updateSlideNotes(2, { speaker_notes: 'y' }, SID);

    const body = sentBody(fetchMock);
    expect(body.speaker_notes).toBe('y');
    expect(body.session_id).toBe(SID);
    expect('talk_track' in body).toBe(false);
  });

  // Sabotage target: a truthiness check (`if (fields.talk_track)`) that drops an empty string.
  it('an empty talk track is sent as talk_track: "" (clearing is a real save)', async () => {
    const fetchMock = stubFetch(jsonResponse({ ...SAVED, talk_track: '' }));

    await api.updateSlideNotes(2, { talk_track: '' }, SID);

    const body = sentBody(fetchMock);
    expect('talk_track' in body).toBe(true);
    expect(body.talk_track).toBe('');
    expect('speaker_notes' in body).toBe(false);
  });

  // Sabotage target: a truthiness check (`if (fields.speaker_notes)`) that drops an empty string.
  it('empty notes are sent as speaker_notes: "" (clearing is a real save)', async () => {
    const fetchMock = stubFetch(jsonResponse({ ...SAVED, speaker_notes: '' }));

    await api.updateSlideNotes(2, { speaker_notes: '' }, SID);

    const body = sentBody(fetchMock);
    expect('speaker_notes' in body).toBe(true);
    expect(body.speaker_notes).toBe('');
    expect('talk_track' in body).toBe(false);
  });

  // Sabotage target: sends only one key when the caller gives both.
  it('sends both keys when the caller gives both', async () => {
    const fetchMock = stubFetch(jsonResponse(SAVED));

    await api.updateSlideNotes(2, { speaker_notes: 'y', talk_track: 'x' }, SID);

    const body = sentBody(fetchMock);
    expect(body.speaker_notes).toBe('y');
    expect(body.talk_track).toBe('x');
  });

  // Sabotage target: drops slide_id or expected_version from the body.
  it('passes slide_id and expected_version through when given', async () => {
    const fetchMock = stubFetch(jsonResponse(SAVED));

    await api.updateSlideNotes(2, { talk_track: 'x' }, SID, 'slide-abc', 11);

    expect(sentBody(fetchMock)).toEqual({
      session_id: SID,
      talk_track: 'x',
      slide_id: 'slide-abc',
      expected_version: 11,
    });
  });
});

describe('api.updateSlideNotes — response', () => {
  // Sabotage target: a hand-built return value that drops talk_track from the response.
  it('resolves to the parsed body, talk_track included', async () => {
    stubFetch(jsonResponse(SAVED));

    const result = await api.updateSlideNotes(2, { talk_track: 'x' }, SID);

    expect(result).toEqual(SAVED);
    expect(result.talk_track).toBe('Revenue grew because of the new region.');
  });
});
