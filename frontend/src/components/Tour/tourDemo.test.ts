import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../services/api', () => ({
  api: {
    createTourDemoDeck: vi.fn(),
    runTourDemoStage: vi.fn(),
    deleteSession: vi.fn(),
  },
}));

import { api } from '../../services/api';
import { startDemo, runStage, showView, focusViewer, endDemo, _resetDemoForTests } from './tourDemo';

const events: { type: string; detail: unknown }[] = [];
const record = (e: Event) => events.push({ type: e.type, detail: (e as CustomEvent).detail });
const TYPES = ['tour:load-demo-deck', 'tour:refresh-session', 'tour:show-view', 'tour:viewer',
  'tour:demo-session-deleted', 'tour:sessions-list-refresh', 'tour:navigate-main'];

beforeEach(() => {
  vi.useFakeTimers();
  _resetDemoForTests();
  events.length = 0;
  TYPES.forEach(t => window.addEventListener(t, record));
  vi.mocked(api.createTourDemoDeck).mockResolvedValue({ session_id: 'demo-1', title: 'Demo' });
  vi.mocked(api.runTourDemoStage).mockResolvedValue({ session_id: 'demo-1', stage: 'plan', applied: true, slide_count: 0 });
  vi.mocked(api.deleteSession).mockResolvedValue(undefined as never);
});
afterEach(() => {
  TYPES.forEach(t => window.removeEventListener(t, record));
  vi.useRealTimers();
  vi.clearAllMocks();
});

const settle = async (p: Promise<void>) => { await vi.runAllTimersAsync(); await p; };

describe('tourDemo', () => {
  it('startDemo creates the deck and opens it', async () => {
    await settle(startDemo());
    expect(events.map(e => e.type)).toEqual(['tour:load-demo-deck']);
    expect(events[0].detail).toEqual({ sessionId: 'demo-1' });
  });

  it('startDemo called twice (Back onto the first demo step) creates only one deck', async () => {
    await settle(startDemo());
    events.length = 0;
    await settle(startDemo());
    expect(api.createTourDemoDeck).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);
  });

  it('runStage posts the stage then refreshes the session', async () => {
    await settle(startDemo());
    events.length = 0;
    await settle(runStage('build'));
    expect(api.runTourDemoStage).toHaveBeenCalledWith('demo-1', 'build');
    expect(events).toEqual([{ type: 'tour:refresh-session', detail: { sessionId: 'demo-1' } }]);
  });

  it('runStage is idempotent: a second call (Back then Next) neither posts nor refreshes', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    events.length = 0;
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);
  });

  it('runStage tracks stages independently: each distinct stage posts once', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    await settle(runStage('build'));
    await settle(runStage('plan'));
    await settle(runStage('review'));
    await settle(runStage('edit'));
    expect(vi.mocked(api.runTourDemoStage).mock.calls).toEqual([
      ['demo-1', 'plan'], ['demo-1', 'build'], ['demo-1', 'review'], ['demo-1', 'edit'],
    ]);
  });

  it('runStage without a demo session is a no-op', async () => {
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).not.toHaveBeenCalled();
    expect(events).toEqual([]);
  });

  it('a failed stage resolves (the tour keeps going) and can be retried', async () => {
    await settle(startDemo());
    events.length = 0;
    vi.mocked(api.runTourDemoStage).mockRejectedValueOnce(new Error('409'));
    await expect(settle(runStage('build'))).resolves.toBeUndefined();
    // A failed stage must not refresh the session (nothing changed server-side).
    expect(events).toEqual([]);
    await settle(runStage('build'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(2);
    expect(events).toEqual([{ type: 'tour:refresh-session', detail: { sessionId: 'demo-1' } }]);
  });

  it('a failed startDemo falls back to the main view', async () => {
    vi.mocked(api.createTourDemoDeck).mockRejectedValueOnce(new Error('500'));
    await settle(startDemo());
    expect(events.map(e => e.type)).toEqual(['tour:navigate-main']);
  });

  it('after a failed startDemo, runStage and endDemo are no-ops', async () => {
    vi.mocked(api.createTourDemoDeck).mockRejectedValueOnce(new Error('500'));
    await settle(startDemo());
    events.length = 0;
    await settle(runStage('plan'));
    endDemo();
    await vi.runAllTimersAsync();
    expect(api.runTourDemoStage).not.toHaveBeenCalled();
    expect(api.deleteSession).not.toHaveBeenCalled();
    expect(events).toEqual([]);
  });

  it('showView and focusViewer dispatch their bridge events with explicit state', async () => {
    await settle(showView('spec'));
    await settle(focusViewer({ index: 2, drawerOpen: true, tab: 'feedback' }));
    expect(events).toEqual([
      { type: 'tour:show-view', detail: { view: 'spec' } },
      { type: 'tour:viewer', detail: { index: 2, drawerOpen: true, tab: 'feedback' } },
    ]);
  });

  it('endDemo deletes the session, then refreshes the list, and forgets stages', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    events.length = 0;
    endDemo();
    await vi.runAllTimersAsync();
    expect(events.map(e => e.type)).toEqual(['tour:demo-session-deleted', 'tour:sessions-list-refresh']);
    expect(events[0].detail).toEqual({ sessionId: 'demo-1' });
    expect(api.deleteSession).toHaveBeenCalledWith('demo-1');
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(1);
  });

  it('endDemo refreshes the sessions list only after DELETE resolves', async () => {
    let resolveDelete!: () => void;
    vi.mocked(api.deleteSession).mockReturnValueOnce(new Promise<void>(r => { resolveDelete = r; }));
    await settle(startDemo());
    events.length = 0;
    endDemo();
    await vi.runAllTimersAsync();
    expect(events.map(e => e.type)).toEqual(['tour:demo-session-deleted']);
    resolveDelete();
    await vi.runAllTimersAsync();
    expect(events.map(e => e.type)).toEqual(['tour:demo-session-deleted', 'tour:sessions-list-refresh']);
  });

  it('endDemo swallows a failed DELETE and does not refresh the list', async () => {
    vi.mocked(api.deleteSession).mockRejectedValueOnce(new Error('500'));
    await settle(startDemo());
    events.length = 0;
    expect(() => endDemo()).not.toThrow();
    await vi.runAllTimersAsync();
    expect(events.map(e => e.type)).toEqual(['tour:demo-session-deleted']);
  });

  it('a new demo after endDemo creates a fresh deck and runs stages again', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    endDemo();
    await vi.runAllTimersAsync();
    vi.mocked(api.createTourDemoDeck).mockResolvedValueOnce({ session_id: 'demo-2', title: 'Demo' });
    await settle(startDemo());
    await settle(runStage('plan'));
    expect(api.createTourDemoDeck).toHaveBeenCalledTimes(2);
    expect(api.runTourDemoStage).toHaveBeenLastCalledWith('demo-2', 'plan');
  });

  it('endDemo with no demo does nothing', () => {
    endDemo();
    expect(events).toEqual([]);
    expect(api.deleteSession).not.toHaveBeenCalled();
  });
});
