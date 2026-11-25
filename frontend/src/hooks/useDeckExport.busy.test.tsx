/**
 * A busy worker's 429 on the PPTX export: useDeckExport -> api.exportPptxHuashu -> POST
 * /api/export/pptx/editable/huashu/from-html.
 *
 * Contract: when the worker has no room for another export,
 * both Chrome export routes answer 429 with `Retry-After: 60` and
 * `{"detail": "Exports are busy right now. Please try again in a minute."}`. The hook shows that
 * detail to the user as it is (an alert) and does NOT fall back to the records pipeline: that fallback
 * is for an export that is not installed here (a 503, or the "huashu pipeline not available" /
 * "pipeline installing" phrases), and running it on a 429 would hide the message behind a slower,
 * different export.
 *
 * The REAL hook and the REAL api client run. `fetch` is stubbed with a tiny fake server
 * (api.imageGeneration.test.ts style) that records every request, `window.alert` is spied on, and
 * domWalker (the records pipeline's in-browser extraction) is stubbed so a fallback, if one ran,
 * would reach the records route instead of rendering slides in jsdom.
 *
 * SABOTAGE (for the reviewer):
 *   - a 429 read as unavailable (`status === 503 || status === 429`) -> both tests RED.
 *   - a generic alert instead of the server's message                -> "shows the detail" RED.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '../contexts/ToastContext';
import type { SlideDeck } from '../types/slide';
import { useDeckExport } from './useDeckExport';

vi.mock('../services/domWalker', () => ({ extractSlideRecordsForExport: vi.fn(async () => []) }));

const BUSY = 'Exports are busy right now. Please try again in a minute.';
const PPTX_ROUTE = '/api/export/pptx/editable/huashu/from-html';
const FALLBACK_STATUS = 'Falling back to records pipeline (slower)…';

const DECK = {
  title: 'Deck',
  slide_count: 1,
  css: '',
  external_scripts: [],
  scripts: '',
  version: 1,
  findings: [],
  slides: [{ index: 0, slide_id: 's1', html: '<div class="slide"><h1>One</h1></div>', scripts: '' }],
} as unknown as SlideDeck;

type Call = { method: string; path: string };

/** Answers the PPTX route with the busy 429; anything else (a fallback) with a deck, recorded. */
function busyServer() {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname;
      calls.push({ method: (init?.method ?? 'GET').toUpperCase(), path });
      if (path === PPTX_ROUTE) {
        return new Response(JSON.stringify({ detail: BUSY }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '60' },
        });
      }
      return new Response(new Blob(['PK records deck']), { status: 200 });
    }),
  );
  return calls;
}

/** Run the PPTX export while the worker is busy: what it fetched, alerted, and said meanwhile. */
async function exportWhileBusy() {
  const calls = busyServer();
  const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
  const statuses: Array<string | null> = [];
  const { result } = renderHook(
    () =>
      useDeckExport({
        slideDeck: DECK,
        sessionId: 'sess-1',
        onExportStatusChange: (status) => statuses.push(status),
      }),
    { wrapper: ToastProvider },
  );
  await act(async () => {
    await result.current.handleExportPPTX();
  });
  return { calls, alert, statuses, result };
}

describe('the PPTX export while the worker is busy (429)', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {}); // the hook logs the failed export
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('shows the busy detail as it is, in an alert', async () => {
    const { alert, result } = await exportWhileBusy();

    expect(alert).toHaveBeenCalledTimes(1);
    expect(alert).toHaveBeenCalledWith(BUSY);
    expect(result.current.isExportingPPTX).toBe(false);
  });

  it('does not fall back to the records pipeline', async () => {
    const { calls, statuses } = await exportWhileBusy();

    expect(calls).toEqual([{ method: 'POST', path: PPTX_ROUTE }]);
    expect(statuses).not.toContain(FALLBACK_STATUS);
  });
});
