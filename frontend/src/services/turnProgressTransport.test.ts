/**
 * #319: the graph's stage summary on both chat transports.
 *
 * Polling (production): every poll of a running graph turn re-sends the turn's
 * latest snapshot as `turn_progress`.  `startPolling` forwards it to `onEvent` as
 * a `turn_progress` event only when its `seq` is higher than the last one it
 * forwarded, so ChatPanel is not re-sent an identical snapshot every 3 s.  A
 * legacy (monolith) poll carries no `turn_progress` key and forwards nothing.
 *
 * SSE: `streamChat` forwards every parsed `data:` line, so a `turn_progress`
 * line reaches `onEvent` unchanged.
 *
 * Behavioural only: `api.startPolling` / `api.streamChat` with a stubbed `fetch`
 * (and fake timers for polling), asserting what reaches `onEvent`.  Precedent:
 * slideRevisions.test.ts.
 *
 * SABOTAGE: drop `> lastProgressSeq` from the startPolling guard -> the repeated
 * seq 2 (and the older seq 4) are forwarded -> the seq tests go red.  Hoist
 * `lastProgressSeq` to module scope -> the second turn's seq 1 is swallowed ->
 * the new-turn test goes red, even when run alone.
 */

import { api } from './api';
import type { StreamEvent } from './api';
import type { TurnPhase, TurnProgress, TurnProgressSlides } from '../types/turnProgress';

const MARK = 1760000000.25;

function tp(seq: number, phase: TurnPhase = 'building', slides?: Partial<TurnProgressSlides>): TurnProgress {
  return {
    seq,
    phase,
    slides: { total: 3, building: [], reviewing: [], fixing: [], done: [], ...slides },
  };
}

/** A running poll with nothing else in it; `turn_progress` only when given. */
function running(extra: Record<string, unknown> = {}) {
  return { status: 'running', events: [], last_message_id: 0, ...extra };
}

/** The terminal poll as the backend serves it: progress nulled (D13). */
const COMPLETED = { status: 'completed', events: [], last_message_id: 0, turn_progress: null, result: {} };

/**
 * Answers the `POST /api/chat/async` submit, then the polls in order.  Each poll
 * URL is recorded; once `responses` runs out the last one repeats.
 */
function buildFetchMock(responses: object[], pollUrls: string[]) {
  return vi.fn(async (url: string) => {
    const u = String(url);
    if (u.includes('/api/chat/async')) {
      return { ok: true, json: async () => ({ request_id: 'progress-req' }) };
    }
    pollUrls.push(u);
    const body = responses[Math.min(pollUrls.length - 1, responses.length - 1)];
    return { ok: true, json: async () => body };
  });
}

const stageSeqs = (events: StreamEvent[]) =>
  events.filter((e) => e.type === 'turn_progress').map((e) => e.turn_progress?.seq);

describe('turn_progress on the polling transport', () => {
  let cancel: (() => void) | null = null;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** Start polling and run exactly one interval tick per response. */
  async function runPolls(responses: object[], events: StreamEvent[], errors: Error[], pollUrls: string[] = []) {
    vi.stubGlobal('fetch', buildFetchMock(responses, pollUrls));
    cancel = api.startPolling('session', 'msg', undefined, (e) => events.push(e), (e) => errors.push(e));
    await vi.advanceTimersByTimeAsync(1);
    for (let i = 0; i < responses.length; i += 1) await vi.advanceTimersByTimeAsync(3001);
  }

  it('startPolling forwards a stage only when its seq increases', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    const pollUrls: string[] = [];
    await runPolls(
      [
        running({ turn_progress: tp(2, 'planning') }),
        running({ turn_progress: tp(2, 'planning') }),
        running({ turn_progress: tp(5, 'building', { building: [0, 1, 2] }) }),
        COMPLETED,
      ],
      events,
      errors,
      pollUrls,
    );

    expect(errors).toEqual([]);
    expect(pollUrls).toHaveLength(4);
    expect(stageSeqs(events)).toEqual([2, 5]);
    // The snapshot travels unchanged.
    const stages = events.filter((e) => e.type === 'turn_progress');
    expect(stages[0].turn_progress).toEqual(tp(2, 'planning'));
    expect(stages[1].turn_progress).toEqual(tp(5, 'building', { building: [0, 1, 2] }));
    // Both stages, then complete; the null on the completed poll forwards nothing.
    expect(events.map((e) => e.type)).toEqual(['turn_progress', 'turn_progress', 'complete']);
  });

  it('an older seq in a later poll is not forwarded', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls(
      [
        running({ turn_progress: tp(5, 'building', { reviewing: [2] }) }),
        running({ turn_progress: tp(4, 'building', { building: [2] }) }),
        COMPLETED,
      ],
      events,
      errors,
    );

    expect(errors).toEqual([]);
    expect(stageSeqs(events)).toEqual([5]);
    expect(events.map((e) => e.type)).toEqual(['turn_progress', 'complete']);
  });

  it("a new turn's seq 1 is forwarded after the previous turn reached a higher seq", async () => {
    // D14: each startPolling call is one turn, and every invoke_graph restarts
    // seq at 1, so the held seq must belong to this turn only.
    const turn1: StreamEvent[] = [];
    const turn2: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls(
      [running({ turn_progress: tp(1, 'planning') }), running({ turn_progress: tp(40, 'reviewing_deck') }), COMPLETED],
      turn1,
      errors,
    );
    cancel?.();
    await runPolls(
      [running({ turn_progress: tp(1, 'planning') }), running({ turn_progress: tp(2, 'building', { building: [0] }) }), COMPLETED],
      turn2,
      errors,
    );

    expect(errors).toEqual([]);
    expect(stageSeqs(turn1)).toEqual([1, 40]);
    expect(stageSeqs(turn2)).toEqual([1, 2]);
    expect(turn2.map((e) => e.type)).toEqual(['turn_progress', 'turn_progress', 'complete']);
  });

  it('a stage on a pending poll is forwarded; the server, not the client, decides by status', async () => {
    // poll_chat serves turn_progress for every non-terminal status.
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    await runPolls([running({ status: 'pending', turn_progress: tp(1, 'planning') }), COMPLETED], events, errors);

    expect(errors).toEqual([]);
    expect(stageSeqs(events)).toEqual([1]);
    expect(events.map((e) => e.type)).toEqual(['turn_progress', 'complete']);
  });

  it('a poll response with no turn_progress key (legacy engine) forwards no stage', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    const legacyCompleted = { status: 'completed', events: [], last_message_id: 0, result: {} };
    await runPolls([running(), running(), legacyCompleted], events, errors);

    expect(errors).toEqual([]);
    expect(events.filter((e) => e.type === 'turn_progress')).toEqual([]);
    // The legacy turn still completes as before.
    expect(events.map((e) => e.type)).toEqual(['complete']);
  });

  // A turn with messages, released slides, a revision and a title, as the
  // polling transport delivered it before #319, now also carrying stages.
  const DECK = { title: 'Deck', slides: [] } as unknown;
  const FULL_TURN = [
    running({
      events: [{ type: 'assistant', content: 'Planning the deck.', message_id: 1 }],
      last_message_id: 1,
      slides: [{ position: 0, html: '<div>draft 0</div>', scripts: '' }],
      slide_cursor: 1,
      slide_revisions: [],
      revision_mark: MARK,
      turn_progress: tp(1, 'building', { building: [1, 2], reviewing: [0] }),
    }),
    running({
      events: [],
      last_message_id: 1,
      slides: [{ position: 1, html: '<div>draft 1</div>', scripts: 's1()' }],
      slide_cursor: 2,
      slide_revisions: [{ position: 0, html: '<div>fixed 0</div>', scripts: 'x()' }],
      revision_mark: MARK + 3,
      turn_progress: tp(2, 'building', { building: [2], reviewing: [1], done: [0] }),
    }),
    {
      status: 'completed',
      events: [{ type: 'assistant', content: 'Here is your deck.', message_id: 2 }],
      last_message_id: 2,
      turn_progress: null,
      result: { slides: DECK, session_title: 'Quarterly review' },
    },
  ];

  it('startPolling still delivers messages, slides, revisions and complete in their existing order when polls also carry turn_progress', async () => {
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    const pollUrls: string[] = [];
    await runPolls(FULL_TURN, events, errors, pollUrls);

    expect(errors).toEqual([]);
    // Exactly the pre-#319 delivery, once the new stage events are set aside.
    expect(events.filter((e) => e.type !== 'turn_progress')).toEqual([
      { type: 'assistant', content: 'Planning the deck.', message_id: 1 },
      { type: 'slide_ready', position: 0, html: '<div>draft 0</div>', scripts: '', agent: undefined, slide_cursor: 1 },
      { type: 'slide_ready', position: 1, html: '<div>draft 1</div>', scripts: 's1()', agent: undefined, slide_cursor: 2 },
      { type: 'slide_ready', position: 0, html: '<div>fixed 0</div>', scripts: 'x()', agent: undefined, slide_cursor: 2 },
      { type: 'assistant', content: 'Here is your deck.', message_id: 2 },
      { type: 'session_title', session_title: 'Quarterly review' },
      {
        type: 'complete',
        slides: DECK,
        raw_html: undefined,
        replacement_info: undefined,
        experiment_url: undefined,
        metadata: undefined,
      },
    ]);
    // The message id, slide cursor and revision mark are still handed back.
    expect(pollUrls).toHaveLength(3);
    expect(pollUrls[0]).toContain('after_message_id=0');
    expect(pollUrls[0]).not.toContain('slide_cursor=');
    expect(pollUrls[0]).not.toContain('revisions_after=');
    expect(pollUrls[1]).toContain('after_message_id=1');
    expect(pollUrls[1]).toContain('slide_cursor=1');
    expect(pollUrls[1]).toContain(`revisions_after=${MARK}`);
    expect(pollUrls[2]).toContain('after_message_id=1');
    expect(pollUrls[2]).toContain('slide_cursor=2');
    expect(pollUrls[2]).toContain(`revisions_after=${MARK + 3}`);
  });

  it("forwards a poll's stage in the same tick, after that poll's messages and slides", async () => {
    // Pins the plan's insertion point: after the revision_mark block, before
    // lastMessageId, so after every slide_ready of the poll and before the
    // terminal session_title / complete.
    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    vi.stubGlobal('fetch', buildFetchMock(FULL_TURN, []));
    cancel = api.startPolling('session', 'msg', undefined, (e) => events.push(e), (e) => errors.push(e));
    await vi.advanceTimersByTimeAsync(1);

    const tag = (e: StreamEvent) =>
      e.type === 'turn_progress' ? `turn_progress:${e.turn_progress?.seq}`
        : e.type === 'slide_ready' ? `slide_ready:${e.position}`
          : e.type;

    await vi.advanceTimersByTimeAsync(3001);
    expect(events.map(tag)).toEqual(['assistant', 'slide_ready:0', 'turn_progress:1']);

    await vi.advanceTimersByTimeAsync(3001);
    expect(events.slice(3).map(tag)).toEqual(['slide_ready:1', 'slide_ready:0', 'turn_progress:2']);

    await vi.advanceTimersByTimeAsync(3001);
    expect(events.slice(6).map(tag)).toEqual(['assistant', 'session_title', 'complete']);
    expect(errors).toEqual([]);
  });
});

describe('turn_progress on the SSE transport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('streamChat forwards a turn_progress data line unchanged', async () => {
    const evt = {
      type: 'turn_progress',
      turn_progress: tp(3, 'building', { total: 4, building: [3], reviewing: [1], fixing: [2], done: [0] }),
    };
    const chunks = [new TextEncoder().encode('event: turn_progress\ndata: ' + JSON.stringify(evt) + '\n\n')];
    const reader = {
      read: vi.fn(async () =>
        chunks.length > 0 ? { done: false, value: chunks.shift() } : { done: true, value: undefined },
      ),
    };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: { getReader: () => reader } })));

    const events: StreamEvent[] = [];
    const errors: Error[] = [];
    const cancel = api.streamChat('session', 'msg', undefined, (e) => events.push(e), (e) => errors.push(e));
    await vi.waitFor(() => expect(reader.read).toHaveBeenCalledTimes(2));
    cancel();

    expect(errors).toEqual([]);
    expect(events).toEqual([evt]);
  });
});
