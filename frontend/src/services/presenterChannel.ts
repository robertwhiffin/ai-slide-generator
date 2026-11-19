/**
 * The link between presentation mode and the presenter window.
 *
 * Both windows of one session join a same-origin BroadcastChannel named
 * `tellr-present:<sessionId>`. Presentation mode is the only source of truth:
 * it posts `state` on every slide change and every STATE_HEARTBEAT_MS, and the
 * presenter posts `cmd` and renders only what `state` says. See
 * docs/technical/presenter-view.md.
 */

export type PresenterState = { type: 'state'; index: number; total: number; deckVersion: number | null };
export type PresenterCmd = { type: 'cmd'; action: 'next' | 'prev' | 'goto'; index?: number };
export type PresenterMessage = PresenterState | PresenterCmd;

export const channelName = (sessionId: string) => `tellr-present:${sessionId}`;
export const presenterWindowName = (sessionId: string) => `tellr-presenter-${sessionId}`;
export const presenterUrl = (sessionId: string) => `/sessions/${sessionId}/present`;
export const PRESENTER_FEATURES = 'popup,width=1200,height=760';
/** Presentation mode re-posts its state this often while open. */
export const STATE_HEARTBEAT_MS = 1000;

const CMD_ACTIONS = new Set(['next', 'prev', 'goto']);

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

/** Shape check for anything arriving on the channel. Everything else is dropped. */
export function isPresenterMessage(data: unknown): data is PresenterMessage {
  if (!data || typeof data !== 'object') return false;
  const m = data as Record<string, unknown>;
  if (m.type === 'state') {
    return (
      isNonNegativeInteger(m.index) &&
      isNonNegativeInteger(m.total) &&
      (m.deckVersion === null || (typeof m.deckVersion === 'number' && Number.isFinite(m.deckVersion)))
    );
  }
  if (m.type === 'cmd') {
    if (typeof m.action !== 'string' || !CMD_ACTIONS.has(m.action)) return false;
    if (m.action === 'goto') return typeof m.index === 'number' && Number.isInteger(m.index);
    return m.index === undefined || (typeof m.index === 'number' && Number.isInteger(m.index));
  }
  return false;
}

/**
 * The presenter window each session opened, so a second press focuses it
 * instead of calling window.open again. A same-name window.open would reload
 * the presenter and reset its clock. Keyed by session so one session never
 * focuses another's window.
 */
const openedWindows = new Map<string, Window>();

/**
 * Opens or focuses the presenter window. Returns null when the browser blocked it.
 *
 * Call it directly from the key, click or message handler, never from an
 * effect or a timer, so the browser still sees the user's activation.
 */
export function openPresenterWindow(sessionId: string): Window | null {
  const remembered = openedWindows.get(sessionId);
  if (remembered && !remembered.closed) {
    remembered.focus();
    return remembered;
  }
  openedWindows.delete(sessionId);

  const win = window.open(presenterUrl(sessionId), presenterWindowName(sessionId), PRESENTER_FEATURES);
  if (!win) return null;
  openedWindows.set(sessionId, win);
  win.focus();
  return win;
}

/** Opens the channel; returns a close function. Ignores malformed messages. */
export function joinPresenterChannel(
  sessionId: string,
  onMessage: (m: PresenterMessage) => void,
): { post: (m: PresenterMessage) => void; close: () => void } {
  if (typeof BroadcastChannel === 'undefined') {
    return { post: () => {}, close: () => {} };
  }
  const channel = new BroadcastChannel(channelName(sessionId));
  const listener = (e: MessageEvent) => {
    if (isPresenterMessage(e.data)) onMessage(e.data);
  };
  channel.addEventListener('message', listener);
  return {
    post: (m) => channel.postMessage(m),
    close: () => {
      channel.removeEventListener('message', listener);
      channel.close();
    },
  };
}
