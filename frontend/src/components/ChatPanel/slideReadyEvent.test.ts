/**
 * E0 — shape tests for the slide_ready incremental delivery wiring.
 *
 * Read as text on purpose, for the same reason AppLayoutSpecToggle reads
 * AppLayout.tsx as text and api.ts's StreamEventType is guarded as text:
 *  - `handleStreamEvent`'s switch is inside a closure, unreachable without
 *    mounting ChatPanel behind SessionContext/AgentConfigContext/GenerationContext/Router.
 *  - TypeScript erases the union member at runtime, so deleting it leaves
 *    `npm run typecheck` at exit 0.
 *  - The behavioural proofs (slide renders before complete, ascending order,
 *    releasedPositions state, polling path) are in
 *    frontend/tests/e2e/incremental-slide-delivery.spec.ts.
 *
 * Rule 6 — a shape assertion and a behaviour assertion must not share a test.
 * Each test below covers exactly one shape claim.
 *
 * Sabotage targets (one per test, documented inline):
 *  - Remove `case 'slide_ready':` from ChatPanel.tsx → test 1 goes red.
 *  - Remove `onSlideReady` from ChatPanelProps → test 2 goes red.
 *  - Remove `releasedPositions` from AppLayout.tsx → test 3 goes red.
 *  - Remove the `setReleasedPositions(new Set())` call in onGenerationStart → test 4 goes red.
 *  - Remove `data-released-count` attribute → test 5 goes red (E2b's operand becomes unobservable).
 */

import chatPanelSource from './ChatPanel.tsx?raw';
import appLayoutSource from '../Layout/AppLayout.tsx?raw';
import apiSource from '../../services/api.ts?raw';

// ── 1. slide_ready case exists in handleStreamEvent ──────────────────────────
//
// Sabotage: remove `case 'slide_ready':` from ChatPanel.tsx.
// Without it the event falls through the switch default and onSlideReady is
// never called — the entire incremental delivery feature is dead.

describe('E0 — slide_ready switch case', () => {
  it("handleStreamEvent has a 'slide_ready' case", () => {
    expect(
      chatPanelSource,
      "case 'slide_ready' not found in ChatPanel.tsx. Without it the event falls "
      + 'through the switch default and onSlideReady is never called.',
    ).toContain("case 'slide_ready':");
  });
});

// ── 2. onSlideReady prop exists in ChatPanelProps ────────────────────────────
//
// Sabotage: remove the `onSlideReady?:` field from ChatPanelProps.
// Without it AppLayout cannot pass the callback down, and TypeScript
// would catch the prop but only if type-checking runs (which it does
// in CI via `npm run typecheck`).  This text check catches it sooner.

describe('E0 — onSlideReady prop declaration', () => {
  it('ChatPanelProps declares an onSlideReady callback', () => {
    expect(
      chatPanelSource,
      'onSlideReady not declared in ChatPanelProps.  AppLayout cannot wire '
      + 'the incremental callback without it.',
    ).toMatch(/onSlideReady\??:\s*\(position:\s*number/);
  });
});

// ── 3. releasedPositions state exists in AppLayout ───────────────────────────
//
// Sabotage: remove `releasedPositions` from AppLayout.tsx.
// E2b reads this state; without it the flag formula has no operand and
// the review gate can never fire.

describe('E0 — releasedPositions state in AppLayout', () => {
  it('AppLayout declares releasedPositions as a useState', () => {
    expect(
      appLayoutSource,
      'releasedPositions state not found in AppLayout.tsx.  E2b reads '
      + 'releasedPositions.size === deckSpec.slides.length && !isGenerating '
      + 'to decide whether the review gate should open.',
    ).toMatch(/const \[releasedPositions, setReleasedPositions\] = useState/);
  });
});

// ── 4. releasedPositions resets on generation start ─────────────────────────
//
// Sabotage: remove the setReleasedPositions(new Set()) call.
// Without the reset a position released in turn N is still present at the
// start of turn N+1, making the gate fire immediately on the next build
// even before any slide_ready event arrives.

describe('E0 — releasedPositions resets on generation start', () => {
  it('setReleasedPositions(new Set()) is called in the onGenerationStart wrapper', () => {
    expect(
      appLayoutSource,
      'setReleasedPositions(new Set()) not found near onGenerationStart in AppLayout.tsx. '
      + 'Without this reset, stale positions from a prior turn leak into the next one.',
    ).toMatch(/setReleasedPositions\(new Set\(\)\)/);
  });
});

// ── 5. data-released-count attribute exposes size for E2b and tests ──────────
//
// Sabotage: remove the data-released-count attribute.
// E2b uses releasedPositions.size; the e2e spec reads it via
// page.getAttribute('data-released-count').  Without it the state is
// a black box to both.

describe('E0 — data-released-count attribute', () => {
  it('AppLayout renders a data-released-count attribute driven by releasedPositions.size', () => {
    expect(
      appLayoutSource,
      'data-released-count={releasedPositions.size} not found in AppLayout.tsx. '
      + 'The e2e spec and E2b read this attribute to observe the released-position count.',
    ).toContain('data-released-count={releasedPositions.size}');
  });
});

// ── 6. Polling transport: startPolling tracks slide_cursor from events ────────
//
// Sabotage: remove the `slidesCursor` tracking in startPolling.
// Without it the client never hands the cursor back, so the backend
// re-delivers all slides on every poll — degraded but not broken.
// The key delivery path is still the `onEvent` dispatch for each event.

describe('E0 — polling transport cursor tracking', () => {
  it('startPolling tracks slide_cursor from slide_ready events', () => {
    expect(
      apiSource,
      'slide_cursor tracking not found in startPolling. The cursor from slide_ready '
      + 'events must be handed back on the next poll so the backend delivers only '
      + 'new slides.',
    ).toMatch(/slide_cursor.*slidesCursor|slidesCursor.*slide_cursor/s);
  });

  it('pollChat accepts a slide_cursor parameter and appends it to the URL', () => {
    expect(
      apiSource,
      'slide_cursor not passed to pollChat URL. Without it every poll re-fetches all '
      + 'slides from position 0.',
    ).toMatch(/slide_cursor=.*slideCursor|cursorParam.*slide_cursor/s);
  });
});
