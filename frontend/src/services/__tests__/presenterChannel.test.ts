/**
 * Presenter view, Task 6: the channel and the window opener in services/presenterChannel.ts.
 *
 *   - Two windows of one session share a BroadcastChannel named `tellr-present:<sessionId>`. A message posted on
 *     one end reaches the other end, never the sender, and never another session.
 *   - Malformed messages are dropped before they reach the callback.
 *   - openPresenterWindow opens `/sessions/<id>/present` in a pop-up named `tellr-presenter-<id>` and focuses it.
 *     While that window is still open, a second call only focuses it: a same-name window.open would reload the
 *     presenter and reset its clock. It returns null when the browser blocked the pop-up.
 *
 * The BroadcastChannel below is an in-memory fake on globalThis: instances with the same name deliver to each
 * other (a structured clone, synchronously), not to themselves, and a closed instance neither sends nor receives.
 *
 * SABOTAGE targets:
 *   - drop the shape check in joinPresenterChannel             -> "malformed" RED.
 *   - always call window.open (no reuse of an open window)     -> "only focuses" RED.
 *   - keep reusing the window after it was closed               -> "opens again once closed" RED.
 *   - return a truthy value when window.open returned null      -> "returns null when the pop-up is blocked" RED.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Listener = (e: MessageEvent) => void;

class FakeBroadcastChannel {
  static channels = new Map<string, Set<FakeBroadcastChannel>>();

  readonly name: string;
  onmessage: Listener | null = null;
  closed = false;
  private listeners = new Set<Listener>();

  constructor(name: string) {
    this.name = name;
    const peers = FakeBroadcastChannel.channels.get(name) ?? new Set<FakeBroadcastChannel>();
    peers.add(this);
    FakeBroadcastChannel.channels.set(name, peers);
  }

  postMessage(data: unknown) {
    if (this.closed) throw new DOMException('BroadcastChannel is closed', 'InvalidStateError');
    const peers = [...(FakeBroadcastChannel.channels.get(this.name) ?? [])];
    for (const peer of peers) {
      if (peer !== this && !peer.closed) peer.deliver(structuredClone(data));
    }
  }

  addEventListener(type: string, listener: Listener) {
    if (type === 'message') this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: Listener) {
    if (type === 'message') this.listeners.delete(listener);
  }

  close() {
    this.closed = true;
    FakeBroadcastChannel.channels.get(this.name)?.delete(this);
  }

  private deliver(data: unknown) {
    const event = new MessageEvent('message', { data });
    this.onmessage?.(event);
    for (const listener of [...this.listeners]) listener(event);
  }
}

type PresenterChannelModule = typeof import('../presenterChannel');
let mod: PresenterChannelModule;

type FakeWindow = { focus: ReturnType<typeof vi.fn>; closed: boolean };
function fakeWindow(): FakeWindow {
  return { focus: vi.fn(), closed: false };
}

beforeEach(async () => {
  FakeBroadcastChannel.channels.clear();
  vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
  // A fresh module per test, so a window remembered by one test never leaks into the next.
  vi.resetModules();
  mod = await import('../presenterChannel');
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('presenterChannel names and timings', () => {
  it('exports the agreed channel name, window name, features and timings', () => {
    expect(mod.channelName('abc')).toBe('tellr-present:abc');
    expect(mod.presenterWindowName('abc')).toBe('tellr-presenter-abc');
    expect(mod.PRESENTER_FEATURES).toBe('popup,width=1200,height=760');
    expect(mod.LINK_TIMEOUT_MS).toBe(3000);
    expect(mod.STATE_HEARTBEAT_MS).toBe(1000);
  });
});

describe('joinPresenterChannel', () => {
  // Sabotage target: deliver to the sender too, or name the channel differently on the two ends.
  it('messages round-trip between two windows of one session, not back to the sender', () => {
    const slidesSide = vi.fn();
    const presenterSide = vi.fn();
    const slides = mod.joinPresenterChannel('s1', slidesSide);
    const presenter = mod.joinPresenterChannel('s1', presenterSide);

    const state = { type: 'state', index: 2, total: 7, deckVersion: 4 } as const;
    slides.post(state);
    expect(presenterSide).toHaveBeenCalledTimes(1);
    expect(presenterSide).toHaveBeenCalledWith(state);
    expect(slidesSide).not.toHaveBeenCalled();

    const cmd = { type: 'cmd', action: 'goto', index: 5 } as const;
    presenter.post(cmd);
    expect(slidesSide).toHaveBeenCalledTimes(1);
    expect(slidesSide).toHaveBeenCalledWith(cmd);
    expect(presenterSide).toHaveBeenCalledTimes(1);

    presenter.post({ type: 'cmd', action: 'next' });
    expect(slidesSide).toHaveBeenLastCalledWith({ type: 'cmd', action: 'next' });

    slides.close();
    presenter.close();
  });

  it('uses the tellr-present:<sessionId> channel, so another tab on the same channel name hears it', () => {
    const received: unknown[] = [];
    const raw = new FakeBroadcastChannel('tellr-present:s1');
    raw.onmessage = (e) => received.push(e.data);

    const end = mod.joinPresenterChannel('s1', () => {});
    end.post({ type: 'state', index: 0, total: 3, deckVersion: null });
    expect(received).toEqual([{ type: 'state', index: 0, total: 3, deckVersion: null }]);

    end.close();
    raw.close();
  });

  it('does not cross sessions', () => {
    const other = vi.fn();
    const a = mod.joinPresenterChannel('s1', () => {});
    const b = mod.joinPresenterChannel('s2', other);

    a.post({ type: 'cmd', action: 'next' });
    expect(other).not.toHaveBeenCalled();

    a.close();
    b.close();
  });

  // Sabotage target: forward every message without a shape check.
  it('ignores malformed messages', () => {
    const onMessage = vi.fn();
    const end = mod.joinPresenterChannel('s1', onMessage);
    const raw = new FakeBroadcastChannel('tellr-present:s1');

    raw.postMessage({});
    raw.postMessage({ type: 'state' });
    // Each of these differs from a valid state only in the index, so the index check alone must drop them.
    raw.postMessage({ type: 'state', total: 3, deckVersion: 2 });
    raw.postMessage({ type: 'state', index: '1', total: 3, deckVersion: 2 });
    raw.postMessage({ type: 'state', index: -1, total: 3, deckVersion: 2 });
    raw.postMessage({ type: 'state', index: 1.5, total: 3, deckVersion: 2 });
    raw.postMessage('state');
    raw.postMessage(null);
    raw.postMessage({ type: 'cmd', action: 'explode' });
    expect(onMessage).not.toHaveBeenCalled();

    // Control: a well-formed message on the same raw channel does arrive, so the misses above are the shape check.
    raw.postMessage({ type: 'state', index: 1, total: 3, deckVersion: 2 });
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith({ type: 'state', index: 1, total: 3, deckVersion: 2 });

    end.close();
    raw.close();
  });

  it('stops delivering after close', () => {
    const onMessage = vi.fn();
    const end = mod.joinPresenterChannel('s1', onMessage);
    end.close();

    const raw = new FakeBroadcastChannel('tellr-present:s1');
    raw.postMessage({ type: 'cmd', action: 'next' });
    expect(onMessage).not.toHaveBeenCalled();
    raw.close();
  });
});

describe('openPresenterWindow', () => {
  it('opens the presenter route in a named pop-up and focuses it', () => {
    const win = fakeWindow();
    const open = vi.spyOn(window, 'open').mockReturnValue(win as unknown as Window);

    const result = mod.openPresenterWindow('s1');

    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith('/sessions/s1/present', 'tellr-presenter-s1', 'popup,width=1200,height=760');
    expect(win.focus).toHaveBeenCalledTimes(1);
    expect(result).toBe(win);
  });

  // Sabotage target: call window.open on every call. A same-name open reloads the presenter and resets its clock.
  it('a second call while the window is open only focuses it', () => {
    const win = fakeWindow();
    const open = vi.spyOn(window, 'open').mockReturnValue(win as unknown as Window);

    mod.openPresenterWindow('s1');
    const second = mod.openPresenterWindow('s1');

    expect(open).toHaveBeenCalledTimes(1);
    expect(win.focus).toHaveBeenCalledTimes(2);
    expect(second).toBe(win);
  });

  // Sabotage target: remember one window for every session instead of one per session.
  it('remembers the window per session, so another session opens its own presenter', () => {
    const forS1 = fakeWindow();
    const forS2 = fakeWindow();
    const open = vi
      .spyOn(window, 'open')
      .mockReturnValueOnce(forS1 as unknown as Window)
      .mockReturnValueOnce(forS2 as unknown as Window);

    mod.openPresenterWindow('s1');
    const second = mod.openPresenterWindow('s2');

    expect(open).toHaveBeenCalledTimes(2);
    expect(open).toHaveBeenLastCalledWith('/sessions/s2/present', 'tellr-presenter-s2', 'popup,width=1200,height=760');
    expect(second).toBe(forS2);
    expect(forS1.focus).toHaveBeenCalledTimes(1);

    // And s1 still reaches its own window.
    expect(mod.openPresenterWindow('s1')).toBe(forS1);
    expect(open).toHaveBeenCalledTimes(2);
  });

  // Sabotage target: keep returning the remembered window after the user closed it.
  it('opens again once the remembered window was closed', () => {
    const first = fakeWindow();
    const next = fakeWindow();
    const open = vi
      .spyOn(window, 'open')
      .mockReturnValueOnce(first as unknown as Window)
      .mockReturnValueOnce(next as unknown as Window);

    mod.openPresenterWindow('s1');
    first.closed = true;
    const result = mod.openPresenterWindow('s1');

    expect(open).toHaveBeenCalledTimes(2);
    expect(open).toHaveBeenLastCalledWith('/sessions/s1/present', 'tellr-presenter-s1', 'popup,width=1200,height=760');
    expect(next.focus).toHaveBeenCalledTimes(1);
    expect(result).toBe(next);
  });

  // Review Focus 3: a pop-up blocker can refuse even with user activation. The caller relies on null.
  it('returns null when the pop-up is blocked', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);

    expect(mod.openPresenterWindow('s1')).toBeNull();

    // Nothing was remembered, so a later press (the toolbar button) tries again.
    const win = fakeWindow();
    open.mockReturnValue(win as unknown as Window);
    expect(mod.openPresenterWindow('s1')).toBe(win);
    expect(open).toHaveBeenCalledTimes(2);
  });
});
