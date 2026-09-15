/**
 * The spec toggle is LOCAL STATE, and neither panel is unmounted by it.
 *
 * Read as text on purpose, for the same reason ws4d's StreamEventType guard reads
 * api.ts as text: what is being asserted here is not observable at runtime
 * without mounting the whole app shell.  `ViewMode` is a type and is erased; and
 * the difference between "hidden" and "unmounted" is a property of the JSX, which
 * a jsdom render of AppLayout could only reach behind SessionContext,
 * GenerationContext, ToastContext, a Router and a mocked api.  The behavioural
 * proof lives in frontend/tests/e2e/spec-view.spec.ts, which drives a real
 * browser; this file is the cheap net under the one specific mistake the ws4e
 * plan singles out.
 *
 * WHY IT MATTERS (plan §E1, round-1 finding 19): `ViewMode` drives route-level
 * navigation through navigate().  A 'spec' member would therefore unmount the
 * ChatPanel — losing the conversation and any in-flight stream — and the
 * SlideViewer, whose `dismissed` findings live in useState and are reset on
 * deckKey change.  A round trip to the spec and back would resurrect every
 * dismissed finding.  AppLayout.tsx already carries a shipped comment warning
 * that React must reconcile the chat element as the SAME element across collapse
 * toggles for exactly this reason.
 *
 * Sabotage targets: add 'spec' to the ViewMode union; change `showSpec` to a
 * ViewMode-backed value; replace the pane's className ternary with a conditional
 * render.
 */
import appLayoutSource from './AppLayout.tsx?raw';

describe('the spec toggle is not a ViewMode', () => {
  it('the ViewMode union was found and has members', () => {
    // Vacuity guard, in its own test: every assertion below is an ABSENCE
    // assertion over this union, and an absence assertion passes for free when
    // the thing it searches was never found.
    const match = /^type ViewMode\s*=\s*([^;]+);/m.exec(appLayoutSource);
    expect(match, 'type ViewMode not found in AppLayout.tsx').not.toBeNull();

    const members = match![1].split('|').map((m) => m.trim().replace(/^'|'$/g, ''));
    expect(members.length).toBeGreaterThan(1);
    expect(members).toContain('main');
  });

  it('has no spec member', () => {
    const match = /^type ViewMode\s*=\s*([^;]+);/m.exec(appLayoutSource);
    const members = match![1].split('|').map((m) => m.trim().replace(/^'|'$/g, ''));

    expect(
      members,
      "ViewMode gained a 'spec' member. ViewMode drives navigate(), so a route "
      + 'change unmounts the ChatPanel and the SlideViewer: the conversation, any '
      + "in-flight stream, and the viewer's dismissed findings are all lost. The "
      + 'spec/slides switch is local `showSpec` state inside the main view.',
    ).not.toContain('spec');
  });
});

describe('the spec toggle is local component state', () => {
  it('showSpec is a useState in AppLayout', () => {
    expect(
      /const \[showSpec, setShowSpec\] = useState\(/.test(appLayoutSource),
      'showSpec is no longer a useState in AppLayout. If it moved to a router, a '
      + 'context or a URL parameter, re-read the ViewMode note above: the toggle '
      + 'must not be able to change the route.',
    ).toBe(true);
  });

  it('showSpec is never persisted, so it cannot leak into a later request', () => {
    // The view is a hint, never a mode: intent comes from language, so nothing
    // about which panel is open may travel. `collapsed` IS persisted a few lines
    // above showSpec, which is how a copy-paste would introduce this.
    const persisted = appLayoutSource
      .split('\n')
      .filter((line) => /showSpec/.test(line) && /localStorage|sessionStorage|JSON\.stringify/.test(line));
    expect(persisted, 'showSpec must not be persisted or serialised').toEqual([]);
  });
});

describe('neither panel is unmounted by the toggle', () => {
  it('the slide-viewer pane hides by className rather than being rendered away', () => {
    const paneStart = appLayoutSource.indexOf('data-testid="slide-viewer-pane"');
    expect(paneStart, 'the slide-viewer-pane wrapper is gone').toBeGreaterThan(-1);

    const viewerStart = appLayoutSource.indexOf('<SlideViewer', paneStart);
    expect(viewerStart, '<SlideViewer no longer follows its pane wrapper').toBeGreaterThan(-1);

    const wrapper = appLayoutSource.slice(paneStart, viewerStart);
    expect(
      wrapper,
      'the slide-viewer pane must hide via a className ternary on showSpec. '
      + "Rendering it away instead resets SlideViewer's `dismissed` useState, so "
      + 'every dismissed finding comes back on the round trip from the spec.',
    ).toContain("className={showSpec ? 'hidden'");
  });

  it('showSpec never gates a render', () => {
    // `showSpec && <X/>` and `showSpec ? <X/> : <Y/>` both UNMOUNT the branch that
    // is not taken. Hiding is the only permitted mechanism, so a JSX-valued
    // conditional on showSpec is forbidden outright rather than checked per site.
    const gating = appLayoutSource
      .split('\n')
      .filter((line) => /showSpec\s*(&&|\?[^']*<)/.test(line));
    expect(
      gating,
      'showSpec must not gate a render. Hide the pane with a className instead: a '
      + 'conditional render unmounts the panel and destroys its state.',
    ).toEqual([]);
  });
});
