/**
 * #317 Task 6: both chat transports end a turn with a signal the panel can hang its id read on.
 *
 * CHARACTERIZATION TEST: #317 makes no production change here; this file is green today. It pins
 * the behaviour plan decision D12 relies on: after a turn ends with a `complete` event, an `error`
 * event or the transport's `onError`, the panel reads the persisted rows to learn the ids of the
 * user messages it showed before they were stored. If a transport stopped sending that signal,
 * those messages would never become deletable until the next full load.
 *
 *   1. Polling, completed: events reach `onEvent` in order (the assistant event keeps its
 *      `message_id`), then exactly one synthesised `complete`.
 *   2. Polling, error: `onError` once, and no `complete`.
 *   3. SSE, complete: `onEvent` receives `assistant`, then `complete`.
 *   4. SSE, error event: the `error` event reaches `onEvent`; no `complete`, no `onError`.
 *
 * SABOTAGE (each run once, then reverted):
 *   - remove the synthesised `complete` in startPolling (api.ts, `onEvent({ type: 'complete', ... })`)
 *                                                          -> "1 — polling, completed" RED.
 *   - drop the `onError` call for `status: 'error'` in startPolling -> "2 — polling, error" RED.
 *   - in streamChat, forward no `complete` event           -> "3 — SSE, complete" RED.
 *   - in streamChat, forward no `error` event              -> "4 — SSE, error event" RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, type StreamEvent } from '../api';

// api.ts polls every POLL_INTERVAL_MS (3000 ms).
const POLL_INTERVAL_MS = 3000;

/** The completed poll body: `startPolling` emits `complete` only when `result` is present (C13). */
const COMPLETED_RESULT = {
  slides: null,
  raw_html: null,
  replacement_info: null,
  experiment_url: null,
  session_title: null,
  metadata: null,
};

type PollBody = Record<string, unknown>;

/** A fetch stub for the polling transport: the submit answers `{request_id}`, polls answer `polls` in turn. */
function stubPollingFetch(polls: PollBody[]) {
  const pollUrls: string[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/chat/async')) {
      return { ok: true, json: async () => ({ request_id: 'req-317' }) };
    }
    pollUrls.push(url);
    const body = polls[Math.min(pollUrls.length, polls.length) - 1];
    return { ok: true, json: async () => body };
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, pollUrls };
}

function stubStreamingFetch(body: string) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })));
}

describe('turn-end signal: polling transport', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('1 — polling, completed: the events, then exactly one `complete`', async () => {
    vi.useFakeTimers();
    const { pollUrls } = stubPollingFetch([
      {
        status: 'running',
        events: [{ type: 'assistant', content: 'Building 3 slides.', message_id: 7 }],
        last_message_id: 7,
      },
      { status: 'completed', events: [], last_message_id: 7, result: COMPLETED_RESULT },
    ]);
    const events: StreamEvent[] = [];
    const onError = vi.fn();

    const cancel = api.startPolling('sess-1', 'Build a deck about puffins', undefined, e => events.push(e), onError);
    await vi.advanceTimersByTimeAsync(1); // the submit resolves and the interval is registered
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); // poll 1: running
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); // poll 2: completed
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3); // polling has stopped: nothing more arrives
    cancel();

    expect(events.map(e => e.type)).toEqual(['assistant', 'complete']);
    expect(events[0].message_id).toBe(7);
    expect(events[0].content).toBe('Building 3 slides.');
    expect(pollUrls).toHaveLength(2);
    expect(onError).not.toHaveBeenCalled();
  });

  it('2 — polling, error: `onError` once, and no `complete`', async () => {
    vi.useFakeTimers();
    const { pollUrls } = stubPollingFetch([
      { status: 'error', events: [], last_message_id: 0, error: 'The turn failed.' },
    ]);
    const events: StreamEvent[] = [];
    const onError = vi.fn();

    const cancel = api.startPolling('sess-1', 'Build a deck about puffins', undefined, e => events.push(e), onError);
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
    cancel();

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
    expect((onError.mock.calls[0][0] as Error).message).toBe('The turn failed.');
    expect(events.filter(e => e.type === 'complete')).toEqual([]);
    expect(pollUrls).toHaveLength(1);
  });
});

describe('turn-end signal: SSE transport', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('3 — SSE, complete: `assistant`, then `complete`', async () => {
    stubStreamingFetch('data: {"type":"assistant","content":"hi"}\n\ndata: {"type":"complete"}\n\n');
    const events: StreamEvent[] = [];
    const onError = vi.fn();

    api.streamChat('sess-1', 'hello', undefined, e => events.push(e), onError);

    await vi.waitFor(() => expect(events.map(e => e.type)).toEqual(['assistant', 'complete']));
    expect(events[0].content).toBe('hi');
    expect(onError).not.toHaveBeenCalled();
  });

  it('4 — SSE, error event: the `error` event reaches `onEvent`', async () => {
    stubStreamingFetch('data: {"type":"error","error":"x"}\n\n');
    const events: StreamEvent[] = [];
    const onError = vi.fn();

    api.streamChat('sess-1', 'hello', undefined, e => events.push(e), onError);

    await vi.waitFor(() => expect(events).toEqual([{ type: 'error', error: 'x' }]));
    expect(onError).not.toHaveBeenCalled();
  });
});
