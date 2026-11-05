/**
 * The polling transport delivers each persisted chat message once.
 *
 * Seen on logfood (2026-11-05): mid-turn the chat showed the architect's message
 * and its "1 tool call · Genie One" bar nine times over, and a reload showed one.
 * `startPolling` ticked every 3 s whether or not the previous poll had answered,
 * and moved its `after_message_id` cursor only when an answer arrived, so slow
 * polls overlapped, each asked for the same rows, and every answer's events were
 * forwarded.  Two guarantees close it, one test each:
 *
 * - at most one poll is in flight, so a slow poll is never overlapped;
 * - a message id already forwarded is not forwarded again, whatever the server
 *   sends (its cursor is the LAST row by created_at, which need not be the
 *   highest id).
 *
 * Behavioural only: `api.startPolling` with a stubbed `fetch` that answers like
 * the poll endpoint (rows after `after_message_id`), and fake timers
 * (precedent: queuedTransport.test.ts).
 *
 * SABOTAGE: drop the in-flight guard -> 'one poll in flight' goes red (4 polls in
 * flight, 8 events).  Drop the message-id check -> 'a repeated message' goes red.
 * Release the guard on success only (not in `finally`) -> 'a failed poll' goes red.
 */

import { api } from './api';
import type { StreamEvent } from './api';

const ARCHITECT = { type: 'assistant', content: 'I need the account data first.', message_id: 11 };
const GENIE_CALL = {
  type: 'tool_call',
  content: 'Asking Genie One: Which accounts are close to adoption?',
  tool_name: 'genie_one',
  tool_input: { question: 'Which accounts are close to adoption?' },
  message_id: 12,
};

type Answer = { status: string; events: Array<Record<string, unknown>>; last_message_id: number };

/**
 * A poll endpoint over a fixed list of rows: each poll answers the rows after its
 * `after_message_id` cursor, `latencyMs` after it was sent.  `answer` may rewrite
 * an answer (by poll index) to model a server that repeats a row.
 */
function pollServer(
  rows: Array<Record<string, unknown>>,
  {
    latencyMs = 0,
    answer = (a: Answer) => a,
    failFirst = false,
  }: { latencyMs?: number; answer?: (a: Answer, index: number) => Answer; failFirst?: boolean } = {},
) {
  const state = { polls: 0, inFlight: 0, maxInFlight: 0, cursors: [] as number[] };
  const fetchMock = vi.fn(async (url: string) => {
    if (String(url).includes('/api/chat/async')) {
      return { ok: true, json: async () => ({ request_id: 'overlap-req' }) };
    }
    const index = state.polls;
    state.polls += 1;
    if (failFirst && index === 0) throw new TypeError('Failed to fetch');
    const after = Number(new URL(String(url), 'http://x').searchParams.get('after_message_id'));
    state.cursors.push(after);
    state.inFlight += 1;
    state.maxInFlight = Math.max(state.maxInFlight, state.inFlight);
    const fresh = rows.filter((r) => (r.message_id as number) > after);
    const body = answer(
      {
        status: 'running',
        events: fresh,
        last_message_id: fresh.length ? (fresh[fresh.length - 1].message_id as number) : after,
      },
      index,
    );
    await new Promise((resolve) => setTimeout(resolve, latencyMs));
    state.inFlight -= 1;
    return { ok: true, json: async () => body };
  });
  return { fetchMock, state };
}

const forwarded = (events: StreamEvent[]) =>
  events.filter((e) => e.type === 'assistant' || e.type === 'tool_call').map((e) => e.message_id);

describe('the polling transport delivers each chat message once', () => {
  let cancel: (() => void) | null = null;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function start(fetchMock: ReturnType<typeof vi.fn>, events: StreamEvent[]) {
    vi.stubGlobal('fetch', fetchMock);
    cancel = api.startPolling('session', 'msg', undefined, (e) => events.push(e), () => {});
  }

  it('one poll in flight: a poll slower than the interval is not overlapped', async () => {
    // Each poll takes 10 s to answer; the interval is 3 s.
    const { fetchMock, state } = pollServer([ARCHITECT, GENIE_CALL], { latencyMs: 10_000 });
    const events: StreamEvent[] = [];
    start(fetchMock, events);

    await vi.advanceTimersByTimeAsync(30_000);

    expect(state.maxInFlight).toBe(1);
    expect(forwarded(events)).toEqual([11, 12]);
  });

  it('a repeated message: a row the server sends again is not forwarded again', async () => {
    // The second poll's answer repeats row 12 beside the new row 13.
    const ANALYST = { type: 'assistant', content: 'Here are the accounts.', message_id: 13 };
    const { fetchMock } = pollServer([ARCHITECT, GENIE_CALL, ANALYST], {
      answer: (a, index) =>
        index === 0
          ? { ...a, events: [ARCHITECT, GENIE_CALL], last_message_id: 12 }
          : index === 1
            ? { ...a, events: [GENIE_CALL, ANALYST], last_message_id: 13 }
            : a,
    });
    const events: StreamEvent[] = [];
    start(fetchMock, events);

    await vi.advanceTimersByTimeAsync(9_100);

    expect(forwarded(events)).toEqual([11, 12, 13]);
  });

  it('a failed poll does not stop polling', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {}); // the transport logs the failure
    const { fetchMock, state } = pollServer([ARCHITECT, GENIE_CALL], { failFirst: true });
    const events: StreamEvent[] = [];
    start(fetchMock, events);

    await vi.advanceTimersByTimeAsync(6_100);

    expect(state.polls).toBe(2);
    expect(forwarded(events)).toEqual([11, 12]);
  });
});
