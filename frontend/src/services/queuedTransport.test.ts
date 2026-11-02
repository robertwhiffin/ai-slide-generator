/**
 * A chat turn that waits for a free job runner.
 *
 * The backend serves `status: 'pending'` until a runner on its process picks the
 * turn up; a running graph turn then carries `turn_progress`.  `startPolling`
 * forwards a `queued` event once when a poll is pending with no progress (the turn
 * has not started), and `queued: false` once when that ends.  A turn that never
 * waits forwards no `queued` event, so every existing event sequence is unchanged.
 *
 * Behavioural only: `api.startPolling` with a stubbed `fetch` and fake timers,
 * asserting what reaches `onEvent` (precedent: turnProgressTransport.test.ts).
 *
 * SABOTAGE: drop the "no progress" condition -> a pending poll that already carries
 * progress forwards `queued` -> 'progress on a pending poll is not queued' goes red.
 * Forward `queued` on every pending poll -> 'forwarded once' goes red.
 */

import { api } from './api';
import type { StreamEvent } from './api';
import type { TurnPhase, TurnProgress } from '../types/turnProgress';

function tp(seq: number, phase: TurnPhase = 'planning'): TurnProgress {
  return { seq, phase, slides: { total: 0, building: [], reviewing: [], fixing: [], done: [] } };
}

const pending = (extra: Record<string, unknown> = {}) => ({ status: 'pending', events: [], last_message_id: 0, ...extra });
const running = (extra: Record<string, unknown> = {}) => ({ status: 'running', events: [], last_message_id: 0, ...extra });
const COMPLETED = { status: 'completed', events: [], last_message_id: 0, turn_progress: null, result: {} };
const ERRORED = { status: 'error', events: [], last_message_id: 0, error: 'boom' };

function buildFetchMock(responses: object[]) {
  let polls = 0;
  return vi.fn(async (url: string) => {
    if (String(url).includes('/api/chat/async')) {
      return { ok: true, json: async () => ({ request_id: 'queued-req' }) };
    }
    const body = responses[Math.min(polls, responses.length - 1)];
    polls += 1;
    return { ok: true, json: async () => body };
  });
}

const types = (events: StreamEvent[]) =>
  events.map((e) => (e.type === 'queued' ? `queued:${e.queued}` : e.type));

describe('queued turns on the polling transport', () => {
  let cancel: (() => void) | null = null;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function runPolls(responses: object[], events: StreamEvent[], errors: Error[]) {
    vi.stubGlobal('fetch', buildFetchMock(responses));
    cancel = api.startPolling('session', 'msg', undefined, (e) => events.push(e), (e) => errors.push(e));
    await vi.advanceTimersByTimeAsync(1);
    for (let i = 0; i < responses.length; i += 1) await vi.advanceTimersByTimeAsync(3001);
  }

  it('a turn that waits is forwarded once as queued, then not queued when it starts', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([pending(), pending(), pending(), running({ turn_progress: tp(1) }), COMPLETED], events, errors);

    expect(errors).toEqual([]);
    expect(types(events)).toEqual(['queued:true', 'queued:false', 'turn_progress', 'complete']);
  });

  it('a legacy turn that waits ends its queue when it runs, with no progress at all', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    const legacyCompleted = { status: 'completed', events: [], last_message_id: 0, result: {} };
    await runPolls([pending(), running(), legacyCompleted], events, errors);

    expect(types(events)).toEqual(['queued:true', 'queued:false', 'complete']);
  });

  it('a turn that never waits forwards no queued event', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([running({ turn_progress: tp(1) }), running({ turn_progress: tp(2, 'building') }), COMPLETED], events, errors);

    expect(types(events)).toEqual(['turn_progress', 'turn_progress', 'complete']);
  });

  it('progress on a pending poll is not queued: the turn has started', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([pending({ turn_progress: tp(1) }), COMPLETED], events, errors);

    expect(types(events)).toEqual(['turn_progress', 'complete']);
  });

  it('a queued turn that ends in an error is told not queued before the error', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([pending(), ERRORED], events, errors);

    expect(types(events)).toEqual(['queued:true', 'queued:false']);
    expect(errors.map((e) => e.message)).toEqual(['boom']);
  });

  it('each turn starts unqueued', async () => {
    const turn1: StreamEvent[] = [];
    const turn2: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([pending(), running({ turn_progress: tp(1) }), COMPLETED], turn1, errors);
    cancel?.();
    await runPolls([running({ turn_progress: tp(1) }), COMPLETED], turn2, errors);

    expect(types(turn2)).toEqual(['turn_progress', 'complete']);
  });
});
