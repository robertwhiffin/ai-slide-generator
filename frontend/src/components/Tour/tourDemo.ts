import { api } from '../../services/api';

export type DemoStage = 'plan' | 'build' | 'review' | 'edit';

// Settle times are the existing tour's measured values (AppTour.tsx before this
// change): long enough for the double-navigate refresh to remount the session.
const OPEN_MS = 1500;
const REFRESH_MS = 1200;
const BRIDGE_MS = 300;

let demoSessionId: string | null = null;
const applied = new Set<DemoStage>();
// Stage calls still awaiting the server. react-joyride's beforeTimeout (5 s)
// does not cancel a slow hook, so Back/Next can re-enter a step while its stage
// is in flight: the second call must join the first, not POST again.
const inflight = new Map<DemoStage, Promise<void>>();

const wait = (ms: number) => new Promise<void>(r => setTimeout(r, ms));
const emit = (type: string, detail?: unknown) =>
  window.dispatchEvent(detail === undefined ? new Event(type) : new CustomEvent(type, { detail }));

export async function startDemo(): Promise<void> {
  if (demoSessionId) return;
  try {
    const result = await api.createTourDemoDeck();
    demoSessionId = result.session_id;
    emit('tour:load-demo-deck', { sessionId: demoSessionId });
    await wait(OPEN_MS);
  } catch (err) {
    console.error('Failed to create tour demo deck:', err);
    emit('tour:navigate-main');
    await wait(400);
  }
}

/** Advance the demo by one scripted stage. Idempotent: react-joyride re-runs
 *  `before` hooks on Back, and the server also no-ops a repeated stage. A call
 *  made while the same stage is still in flight returns that call's promise. */
export function runStage(stage: DemoStage): Promise<void> {
  if (!demoSessionId || applied.has(stage)) return Promise.resolve();
  const pending = inflight.get(stage);
  if (pending) return pending;
  const run: Promise<void> = postStage(demoSessionId, stage).finally(() => {
    // endDemo may have cleared the map and a new demo started this stage.
    if (inflight.get(stage) === run) inflight.delete(stage);
  });
  inflight.set(stage, run);
  return run;
}

async function postStage(sid: string, stage: DemoStage): Promise<void> {
  try {
    await api.runTourDemoStage(sid, stage);
    // endDemo ran (Skip) while the call was in flight: this result belongs to
    // a deleted demo, so it must not mark the stage applied for the next one.
    if (demoSessionId !== sid) return;
    applied.add(stage);
    emit('tour:refresh-session', { sessionId: sid });
    await wait(REFRESH_MS);
  } catch (err) {
    console.error(`Failed to run tour demo stage ${stage}:`, err);
  }
}

export async function showView(view: 'slides' | 'spec'): Promise<void> {
  emit('tour:show-view', { view });
  await wait(BRIDGE_MS);
}

export async function focusViewer(opts: { index?: number; drawerOpen?: boolean; tab?: 'feedback' }): Promise<void> {
  emit('tour:viewer', opts);
  await wait(BRIDGE_MS);
}

/** Leave the demo session in the UI, then delete it server-side (errors ignored).
 *  The sidebar refresh runs only after DELETE succeeds so the list does not still show the demo. */
export function endDemo(): void {
  const sid = demoSessionId;
  demoSessionId = null;
  applied.clear();
  inflight.clear();
  if (!sid) return;
  emit('tour:demo-session-deleted', { sessionId: sid });
  void api
    .deleteSession(sid)
    .then(() => emit('tour:sessions-list-refresh'))
    .catch(() => {});
}

export function _resetDemoForTests(): void {
  demoSessionId = null;
  applied.clear();
  inflight.clear();
}
