/**
 * Interrupt generation, Task 9: the cancel API client, and the stop signals on the
 * polling transport.
 *
 * Contract (plan docs/superpowers/plans/2026-11-12-interrupt-generation.md, Task 9;
 * backend src/api/routes/chat.py `cancel_chat` / `poll_chat`):
 *   - `api.cancelChat(requestId)` sends `POST /api/chat/cancel/{requestId}`.
 *       200 -> resolves with the body: `{outcome: 'cancelled'|'already_finished', status}`.
 *       409 -> resolves with the body's `outcome` and `detail`
 *              (`refused_foreign_change` / `not_stoppable`).
 *       any other non-2xx -> rejects.
 *   - `startPolling`:
 *       - once `submitChatAsync` resolves: `onEvent({type: 'request_accepted', request_id})`, once,
 *         before the first poll;
 *       - poll `status: 'cancelled'` (a stop, maybe from another tab): stop polling and emit
 *         `{type: 'cancelled'}` (no `complete`, no `onError`);
 *       - poll `status: 'error'`: `onError(new ChatTurnError(error, response.rollback ?? null))`;
 *       - after the returned cancel function runs, nothing is forwarded, even from a poll that was
 *         already in flight when it ran.
 *
 * Harness: `api.startPolling` with a stubbed `fetch` that answers like the async/poll endpoints,
 * and fake timers (precedent: pollOverlap.test.ts). `cancelChat` gets real `Response` objects
 * (precedent: __tests__/chat503.test.ts).
 *
 * SABOTAGE (for the reviewer):
 *   - drop the `request_accepted` emit                     -> test_request_accepted_emitted_with_id RED.
 *   - emit it from inside the poll tick                    -> same test RED (not before the first poll / repeated).
 *   - treat 'cancelled' like 'running'                      -> test_cancelled_status_... RED (keeps polling, no event).
 *   - emit `complete` or call onError on 'cancelled'        -> same test RED.
 *   - onError(new Error(...)) on 'error'                    -> test_error_carries_rollback RED (rollback missing).
 *   - pass `response.rollback` without `?? null`            -> its "absent" case RED (undefined, not null).
 *   - no `cancelled` re-check after the awaited pollChat    -> test_no_events_forwarded_... RED (every case).
 *   - cancelChat throws on 409                              -> test_cancelChat_409_resolves_with_outcome RED.
 *   - cancelChat resolves on 500/404/403                    -> test_cancelChat_other_non_2xx_rejects RED.
 */

import { api, ChatTurnError } from './api';
import type { StreamEvent } from './api';

const REFUSED_STOP = "Someone else has edited this deck since you sent this, so it can't be rolled back.";
const NOT_STOPPABLE = "This generation can't be stopped.";
const RESTORE_PENDING = 'This deck is still being restored after a failed generation. Try again in a minute.';

type PollBody = Record<string, unknown>;

const RUNNING: PollBody = { status: 'running', events: [], last_message_id: 0, turn_progress: null, rollback: null };

/** The turn's events, without the `request_accepted` announcement (pinned by its own test). */
const turnEvents = (events: StreamEvent[]) => events.filter((e) => e.type !== 'request_accepted');

/** A poll answer as the transport reads it (plain object, as pollOverlap.test.ts does under fake timers). */
const pollAnswer = (body: PollBody) => ({ ok: true, status: 200, json: async () => body });

/**
 * A chat server: `/api/chat/async` answers `requestId`; poll N answers `answers[N]` (the last one
 * repeats). An answer may be a function returning a promise, to hold a poll in flight.
 */
function chatServer(requestId: string, answers: Array<PollBody | (() => Promise<PollBody>)>) {
  const polls: string[] = [];
  const fetchMock = vi.fn(async (url: string | URL) => {
    const u = String(url);
    if (u.includes('/api/chat/async')) {
      return { ok: true, status: 200, json: async () => ({ request_id: requestId }) };
    }
    if (u.includes('/api/chat/poll/')) {
      const answer = answers[Math.min(polls.length, answers.length - 1)];
      polls.push(u);
      return pollAnswer(typeof answer === 'function' ? await answer() : answer);
    }
    throw new Error(`unexpected fetch: ${u}`);
  });
  return { fetchMock, polls };
}

describe('the polling transport: request id, stop and failure signals', () => {
  let cancel: (() => void) | null = null;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function start(fetchMock: ReturnType<typeof vi.fn>) {
    vi.stubGlobal('fetch', fetchMock);
    const events: StreamEvent[] = [];
    const onError = vi.fn();
    cancel = api.startPolling('sess-1', 'Build a Q3 deck', undefined, (e) => events.push(e), onError);
    return { events, onError };
  }

  it('test_request_accepted_emitted_with_id', async () => {
    const { fetchMock, polls } = chatServer('req-42', [RUNNING]);
    const { events, onError } = start(fetchMock);

    await vi.advanceTimersByTimeAsync(0);

    // Accepted as soon as the submit answers, before the first poll (3 s later).
    expect(polls).toHaveLength(0);
    expect(events).toEqual([{ type: 'request_accepted', request_id: 'req-42' }]);

    await vi.advanceTimersByTimeAsync(9_100);

    // Polling carries on against that id, and the id is announced once, not per poll.
    expect(polls.length).toBeGreaterThanOrEqual(3);
    expect(polls.every((u) => u.includes('/api/chat/poll/req-42?'))).toBe(true);
    expect(events).toEqual([{ type: 'request_accepted', request_id: 'req-42' }]);
    expect(onError).not.toHaveBeenCalled();
  });

  it('test_cancelled_status_stops_polling_and_emits_cancelled', async () => {
    const { fetchMock, polls } = chatServer('req-7', [
      RUNNING,
      { status: 'cancelled', events: [], last_message_id: 0, result: null, error: null, turn_progress: null, rollback: 'rolled_back' },
    ]);
    const { events, onError } = start(fetchMock);

    await vi.advanceTimersByTimeAsync(6_100);
    expect(polls).toHaveLength(2);
    expect(events.filter((e) => e.type === 'cancelled')).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(30_000);

    // No poll after the cancelled answer, one cancelled event, and nothing that reads as a finish.
    expect(polls).toHaveLength(2);
    expect(turnEvents(events).map((e) => e.type)).toEqual(['cancelled']);
    expect(onError).not.toHaveBeenCalled();
  });

  it.each([
    ['rolled_back', 'rolled_back'],
    ['restore_failed', 'restore_failed'],
    ['absent', null],
  ] as const)('test_cancelled_event_carries_rollback: %s', async (label, expected) => {
    const answer: PollBody = { status: 'cancelled', events: [], last_message_id: 0, result: null, error: null, turn_progress: null };
    if (label !== 'absent') answer.rollback = expected;
    const { fetchMock } = chatServer('req-8', [answer]);
    const { events } = start(fetchMock);

    await vi.advanceTimersByTimeAsync(3_100);

    expect(turnEvents(events)).toEqual([{ type: 'cancelled', rollback: expected }]);
  });

  it('test_submit_rejecting_after_local_cancel_does_not_call_onError', async () => {
    let fail: (e: Error) => void = () => {};
    const held = new Promise<never>((_, reject) => {
      fail = reject;
    });
    vi.stubGlobal('fetch', vi.fn(() => held));
    const onError = vi.fn();
    const events: StreamEvent[] = [];
    cancel = api.startPolling('sess-1', 'Build a Q3 deck', undefined, (e) => events.push(e), onError);

    cancel();
    fail(new Error('network down'));
    await vi.advanceTimersByTimeAsync(1_000);

    expect(onError).not.toHaveBeenCalled();
    expect(events).toEqual([]);
  });

  it.each([
    ['rolled_back', 'The model endpoint timed out.', 'rolled_back'],
    ['kept_foreign_change', 'The model endpoint timed out.', 'kept_foreign_change'],
    ['restore_failed', RESTORE_PENDING, 'restore_failed'],
    ['null (Legacy)', 'The model endpoint timed out.', null],
    ['absent', 'The model endpoint timed out.', undefined],
  ] as const)('test_error_carries_rollback: %s', async (_label, message, rollback) => {
    const errorAnswer: PollBody = { status: 'error', events: [], last_message_id: 0, result: null, error: message, turn_progress: null };
    if (rollback !== undefined) errorAnswer.rollback = rollback;
    const { fetchMock, polls } = chatServer('req-9', [RUNNING, errorAnswer]);
    const { events, onError } = start(fetchMock);

    await vi.advanceTimersByTimeAsync(30_000);

    expect(onError).toHaveBeenCalledTimes(1);
    const err = onError.mock.calls[0][0];
    expect(err.rollback).toBe(rollback ?? null);
    expect(err.message).toBe(message);
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ChatTurnError);
    // A failed turn stops polling and is not also reported as finished or cancelled.
    expect(polls).toHaveLength(2);
    expect(turnEvents(events)).toEqual([]);
  });

  const DECK = { slides: [{ slide_id: 's1', html: '<div>1</div>' }], css: '', scripts: '' };
  const ASSISTANT = { type: 'assistant', content: 'Here is your deck.', message_id: 11 };
  const LATE_ANSWERS: Array<[string, PollBody]> = [
    [
      'a running turn',
      {
        status: 'running',
        events: [ASSISTANT],
        last_message_id: 11,
        slides: [{ position: 0, html: '<div>1</div>', scripts: '', agent: 'builder' }],
        slide_cursor: 1,
        slide_revisions: [{ position: 0, html: '<div>1b</div>', scripts: '', agent: 'reviewer' }],
        revision_mark: 1,
        turn_progress: { seq: 1, phase: 'building', slides: { total: 3, building: [1, 2], reviewing: [], fixing: [], done: [0] } },
        rollback: null,
      },
    ],
    [
      'a waiting turn',
      { status: 'pending', events: [], last_message_id: 0, turn_progress: null, rollback: null },
    ],
    [
      'a finished turn',
      {
        status: 'completed',
        events: [ASSISTANT],
        last_message_id: 11,
        result: { slides: DECK, session_title: 'Q3 review' },
        turn_progress: null,
        rollback: null,
      },
    ],
    [
      'a failed turn',
      { status: 'error', events: [], last_message_id: 0, error: 'The model endpoint timed out.', turn_progress: null, rollback: 'rolled_back' },
    ],
    [
      'a stopped turn',
      { status: 'cancelled', events: [], last_message_id: 0, turn_progress: null, rollback: 'rolled_back' },
    ],
  ];

  it.each(LATE_ANSWERS)('test_no_events_forwarded_after_local_cancel_even_mid_poll: %s', async (_label, late) => {
    let release: (body: PollBody) => void = () => {};
    const held = new Promise<PollBody>((resolve) => {
      release = resolve;
    });
    const { fetchMock, polls } = chatServer('req-3', [() => held]);
    const { events, onError } = start(fetchMock);

    // The first poll is sent and is still waiting for its answer.
    await vi.advanceTimersByTimeAsync(3_100);
    expect(polls).toHaveLength(1);
    const before = events.length;

    // The panel ends the turn locally (cancelStreamRef), then the poll answers.
    cancel?.();
    release(late);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(events.slice(before)).toEqual([]);
    expect(onError).not.toHaveBeenCalled();
    expect(polls).toHaveLength(1);
  });
});

describe('api.cancelChat', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const respond = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

  function expectOneCancelPost(fetchMock: ReturnType<typeof vi.fn>, requestId: string) {
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string | URL, RequestInit | undefined];
    expect(String(url).endsWith(`/api/chat/cancel/${requestId}`)).toBe(true);
    expect(init?.method).toBe('POST');
  }

  it.each([
    ['refused_foreign_change', REFUSED_STOP],
    ['not_stoppable', NOT_STOPPABLE],
  ])('test_cancelChat_409_resolves_with_outcome: %s', async (outcome, detail) => {
    const fetchMock = respond(409, { detail, outcome });
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.cancelChat('req-7');

    expect(result).toEqual({ outcome, detail });
    expectOneCancelPost(fetchMock, 'req-7');
  });

  it.each([
    ['no outcome', { detail: 'odd' }],
    ['an empty body', {}],
  ])('test_cancelChat_409_without_outcome_rejects: %s', async (_label, body) => {
    const fetchMock = respond(409, body);
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.cancelChat('req-6')).rejects.toMatchObject({ status: 409 });
  });

  it('test_cancelChat_409_unparseable_body_rejects', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>conflict</html>', { status: 409 })));

    await expect(api.cancelChat('req-6')).rejects.toMatchObject({ status: 409 });
  });

  it.each([
    [{ outcome: 'cancelled', status: 'cancelled' }],
    [{ outcome: 'already_finished', status: 'completed' }],
  ])('test_cancelChat_200_resolves_with_outcome: %o', async (body) => {
    const fetchMock = respond(200, body);
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.cancelChat('req-8');

    expect(result).toEqual(body);
    expectOneCancelPost(fetchMock, 'req-8');
  });

  it.each([
    [500, { detail: 'Internal server error' }],
    [404, { detail: 'Request not found' }],
    [403, { detail: 'Forbidden' }],
  ])('test_cancelChat_other_non_2xx_rejects: %i', async (status, body) => {
    const fetchMock = respond(status, body);
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.cancelChat('req-5')).rejects.toBeInstanceOf(Error);
    expectOneCancelPost(fetchMock, 'req-5');
  });

  it('test_cancelChat_network_failure_rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );

    await expect(api.cancelChat('req-6')).rejects.toBeInstanceOf(Error);
  });
});
