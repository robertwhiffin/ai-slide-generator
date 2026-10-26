/**
 * A builder draft is released first and replaced by its reviewed version later
 * in the same turn.  The reorder buffer releases a position once, so the
 * replacement travels on `slide_revisions`, keyed off the `revision_mark` the
 * previous poll returned.  Behavioural only: `api.startPolling` with a stubbed
 * `fetch` and fake timers, asserting what reaches `onEvent` and what goes back
 * on the wire.
 */

import { api } from './api';
import type { StreamEvent } from './api';

const MARK = 1760000000.25;

function buildFetchMock(pollUrls: string[]) {
  return vi.fn(async (url: string) => {
    const u = String(url);
    if (u.includes('/api/chat/async')) {
      return { ok: true, json: async () => ({ request_id: 'revision-req' }) };
    }
    pollUrls.push(u);
    if (pollUrls.length === 1) {
      return {
        ok: true,
        json: async () => ({
          status: 'running',
          events: [],
          last_message_id: 0,
          slides: [{ position: 0, html: '<div>draft 0</div>', scripts: '' }],
          slide_cursor: 1,
          slide_revisions: [],
          revision_mark: MARK,
        }),
      };
    }
    if (pollUrls.length === 2) {
      return {
        ok: true,
        json: async () => ({
          status: 'running',
          events: [],
          last_message_id: 0,
          slides: [],
          slide_cursor: 1,
          slide_revisions: [{ position: 0, html: '<div>fixed 0</div>', scripts: 'x()' }],
          revision_mark: MARK + 3,
        }),
      };
    }
    return {
      ok: true,
      json: async () => ({ status: 'completed', events: [], last_message_id: 0, result: {} }),
    };
  });
}

describe('slide revisions on the polling transport', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function runThreePolls(pollUrls: string[], events: StreamEvent[]) {
    vi.stubGlobal('fetch', buildFetchMock(pollUrls));
    api.startPolling('session', 'msg', undefined, (e) => events.push(e), (e) => { throw e; });
    await vi.advanceTimersByTimeAsync(1);
    for (let i = 0; i < 3; i += 1) await vi.advanceTimersByTimeAsync(3001);
  }

  it('hands the previous revision_mark back, and only after one has arrived', async () => {
    const pollUrls: string[] = [];
    await runThreePolls(pollUrls, []);

    expect(pollUrls.length).toBeGreaterThanOrEqual(3);
    expect(pollUrls[0]).not.toContain('revisions_after=');
    expect(pollUrls[1]).toContain(`revisions_after=${MARK}`);
    expect(pollUrls[2]).toContain(`revisions_after=${MARK + 3}`);
  });

  it('delivers the draft, then its replacement for the SAME position', async () => {
    const events: StreamEvent[] = [];
    await runThreePolls([], events);

    const slides = events.filter((e) => e.type === 'slide_ready');
    expect(slides.map((e) => [e.position, e.html, e.scripts])).toEqual([
      [0, '<div>draft 0</div>', ''],
      [0, '<div>fixed 0</div>', 'x()'],
    ]);
  });
});
