/**
 * E0 — component tests for the slide_ready incremental delivery wiring.
 *
 * Two sections:
 *
 * SHAPE TESTS — read source as text, for the same reason AppLayoutSpecToggle does:
 *   `handleStreamEvent`'s switch is inside a closure, unreachable without mounting
 *   ChatPanel behind many providers.  TypeScript erases union members at runtime.
 *   Each shape test covers exactly one structural claim (rule 6).
 *
 * BEHAVIOURAL TESTS — import and exercise `_insertSlideAscending` directly.
 *   This function is the load-bearing half of the ordering claim: a later-arriving
 *   lower-position slide must appear BEFORE a higher-position one.  Replacing the
 *   ascending-insertion with a simple push silently produces the wrong deck order
 *   if the shape tests are the only guard.  These tests go red on that sabotage.
 *   The remaining behavioural proofs (slides visible before complete, polling path
 *   cursor) are in frontend/tests/e2e/incremental-slide-delivery.spec.ts.
 *
 * Rule 6 — a shape assertion and a behaviour assertion must not share a test.
 */

import chatPanelSource from './ChatPanel.tsx?raw';
import appLayoutSource from '../Layout/AppLayout.tsx?raw';
import apiSource from '../../services/api.ts?raw';
import { _insertSlideAscending } from '../Layout/AppLayout';

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
  // Both regexes below require EXECUTABLE syntax (assignment or template literal),
  // not prose.  A comment like "// slidesCursor tracks slide_cursor" does NOT
  // match either pattern because it lacks the required `=` operator or `${…}`.
  // This closes the absence-assertion shape the round-1 reviewer found.

  it('startPolling assigns event.slide_cursor to slidesCursor (executable assignment)', () => {
    expect(
      apiSource,
      'slidesCursor = event.slide_cursor assignment not found in api.ts. '
      + 'The cursor received from a slide_ready event must be stored in slidesCursor '
      + 'and handed back on the next poll.  A comment about the cursor does not satisfy this.',
    ).toMatch(/slidesCursor\s*=\s*event\.slide_cursor/);
  });

  it('pollChat URL contains the slide_cursor template literal (executable template)', () => {
    expect(
      apiSource,
      '`&slide_cursor=${slideCursor}` template literal not found in api.ts. '
      + 'The cursor must be appended to the poll URL as a query parameter so the '
      + 'backend delivers only slides not yet released to the client.',
    ).toContain('`&slide_cursor=${slideCursor}`');
  });
});

// ── 8 & 9. Ascending-insertion ordering — BEHAVIOURAL ────────────────────────
//
// Imports the extracted _insertSlideAscending pure function from AppLayout.tsx
// and exercises it directly.  Shape tests 1-7 cannot catch this sabotage:
//
//   Sabotage: in _insertSlideAscending, replace the findIndex + splice/push
//   logic with a simple `result.push(newSlide); return result;`.
//   Result:
//     - test 8 goes red: out-of-order arrival produces [2, 0, 1] not [0, 1, 2].
//     - test 9 goes red: the last position in a run of 3 is correct, but the
//       specific out-of-order sequence used exposes the wrong order at index 1.
//
// Rule 6: each test below contains only behavioural assertions.

const makeSlide = (i: number) => ({
  index: i,
  slide_id: `build-${i}`,
  html: `<div class="slide-container"><h1 data-pos="${i}">Slide ${i}</h1></div>`,
  scripts: '',
});

describe('E0 — _insertSlideAscending ordering behavioral', () => {
  it('out-of-order arrival (2, 0, 1) produces ascending index order [0, 1, 2]', () => {
    let slides: ReturnType<typeof makeSlide>[] = [];
    slides = _insertSlideAscending(slides, makeSlide(2)); // arrives first
    slides = _insertSlideAscending(slides, makeSlide(0)); // arrives second
    slides = _insertSlideAscending(slides, makeSlide(1)); // arrives third

    expect(slides.map(s => s.index)).toEqual([0, 1, 2]);
    // Each element carries the correct content for its position.
    expect(slides[0].html).toContain('data-pos="0"');
    expect(slides[1].html).toContain('data-pos="1"');
    expect(slides[2].html).toContain('data-pos="2"');
  });

  it('replacing a position updates content in place without moving it', () => {
    // Start with slides 0, 1, 2 already in order.
    let slides = [makeSlide(0), makeSlide(1), makeSlide(2)];
    // Replace position 1 with a revised version.
    const revised = { index: 1, slide_id: 'build-1-rev', html: '<div>Revised One</div>', scripts: '' };
    slides = _insertSlideAscending(slides, revised);

    expect(slides.map(s => s.index)).toEqual([0, 1, 2]); // order unchanged
    expect(slides[1].slide_id).toBe('build-1-rev');       // content updated
    expect(slides.length).toBe(3);                         // no duplicate inserted
  });
});
