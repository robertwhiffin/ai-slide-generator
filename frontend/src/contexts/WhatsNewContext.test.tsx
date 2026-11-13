/**
 * What's new popup, Task 2: WhatsNewProvider decides at page load whether the popup opens by
 * itself, and records the last release the user dismissed in localStorage.
 *
 *   isOpen     the popup is showing
 *   releases   newest first, ONLY releases with items
 *   unseen     unseenVersions(all releases, lastSeen)
 *   hasNotes   releases.length > 0
 *   open()     shows the popup; marks nothing as seen (the New badges must survive a reopen)
 *   close()    lastSeen := newestVersion(all releases, empty ones included), in state and storage;
 *              with no releases at all it writes nothing
 *
 * Rules pinned here (task brief + spec "When it opens by itself"):
 *   - Auto-open is decided once, at mount: only if the tour was already completed at mount and
 *     something is unseen. One timer, autoOpenDelayMs (default 800). When it fires it opens only if
 *     the tour is not active and the welcome guide is not showing, reading the LIVE tour values.
 *   - Never stacked: a brand-new user gets the welcome guide only. Their welcome dismissal, or tour
 *     end, records the newest release as seen and never opens the popup, in this load or the next.
 *   - An existing user who starts the tour before the timer fires gets no popup over the tour, and
 *     the release stays unseen for the next load.
 *   - Garbage in storage ('abc', a dev version) counts as "seen nothing".
 *
 * Harness: the REAL TourProvider (key 'tellr-app-tour-completed', welcome after 800 ms) around the
 * provider and a probe. Fake timers; every advance is wrapped in act(). `../whatsNew/releases` is
 * mocked so the default `releases` prop can be checked against a known RELEASES fixture.
 *
 * SABOTAGE (measured against a throwaway implementation outside the tracked tree; each turned at
 * least one test red):
 *   - the timer reads tour values from its mount closure, not a ref -> "starts the tour before the delay".
 *   - the timer ignores isTourActive / ignores showWelcome          -> the tour tests / "welcome guide is showing".
 *   - auto-open ignores hasCompletedTour at mount                   -> both brand-new tests.
 *   - auto-open re-armed when the tour ends                          -> "after a skipped auto-open".
 *   - the transition is not recorded, recorded only in storage, or
 *     opens the popup; or a brand-new user is marked seen at mount   -> both brand-new tests.
 *   - a tour ending is recorded for an existing user                 -> "after a skipped auto-open".
 *   - close() records the newest release WITH items                  -> "empty ones included" tests.
 *   - close() with no releases writes 'null' or removes the key      -> "with no releases at all".
 *   - open() or the auto-open marks releases seen                    -> "open() leaves unseen", the 800 ms test.
 *   - garbage lastSeen compared without isReleaseVersion             -> the 'abc' / '0.5.7.dev3' tests.
 *   - releases unsorted, string-sorted, or keeping empty ones        -> "newest first".
 *   - default releases [] / delay hard-coded / timer 1 ms early      -> the default, delay and 800 ms tests.
 *   - the hook does not throw outside the provider                   -> "throws outside the provider".
 *
 * Local runs need NODE_OPTIONS=--no-experimental-webstorage (PLAN-CORRECTIONS C1).
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { TourProvider, useTour } from './TourContext';
import { WhatsNewProvider, useWhatsNew } from './WhatsNewContext';
import { WHATS_NEW_STORAGE_KEY, compareVersions, type ReleaseNotes } from '../whatsNew/releaseNotes';

vi.mock('../whatsNew/releases', () => ({
  // Deliberately an empty release newer than one with items: the default must be this array,
  // filtered for display, with close() recording the empty one.
  RELEASES: [
    { version: '0.9.1', date: '2026-12-01', items: [] },
    { version: '0.9.0', date: '2026-11-20', items: [{ title: 'Default fixture', body: 'From the mocked RELEASES.' }] },
  ],
}));

const TOUR_KEY = 'tellr-app-tour-completed';

/** Release `v` with `n` items. */
function R(v: string, n: number): ReleaseNotes {
  return {
    version: v,
    date: '2026-11-13',
    items: Array.from({ length: n }, (_, i) => ({ title: `Item ${i + 1} of ${v}`, body: `Body ${i + 1} of ${v}.` })),
  };
}

function Probe() {
  const w = useWhatsNew();
  const t = useTour();
  return (
    <>
      <output data-testid="is-open">{String(w.isOpen)}</output>
      <output data-testid="unseen">{JSON.stringify([...w.unseen].sort(compareVersions))}</output>
      <output data-testid="has-notes">{String(w.hasNotes)}</output>
      <output data-testid="releases">{JSON.stringify(w.releases.map((r) => r.version))}</output>
      <output data-testid="welcome">{String(t.showWelcome)}</output>
      <output data-testid="tour-active">{String(t.isTourActive)}</output>
      <button onClick={() => w.open()}>open</button>
      <button onClick={() => w.close()}>close</button>
      <button onClick={() => t.dismissWelcome()}>dismissWelcome</button>
      <button onClick={() => t.startTour()}>startTour</button>
      <button onClick={() => t.endTour()}>endTour</button>
      <button onClick={() => t.resetTour()}>resetTour</button>
    </>
  );
}

const text = (id: string) => screen.getByTestId(id).textContent;
const isOpen = () => text('is-open');
const unseen = () => JSON.parse(text('unseen') ?? 'null') as string[];
const shownReleases = () => JSON.parse(text('releases') ?? 'null') as string[];
const hasNotes = () => text('has-notes');
const welcome = () => text('welcome');
const tourActive = () => text('tour-active');
const stored = () => localStorage.getItem(WHATS_NEW_STORAGE_KEY);

const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

function mount(releases: ReleaseNotes[], extra: { autoOpenDelayMs?: number } = {}) {
  return render(
    <TourProvider>
      <WhatsNewProvider releases={releases} {...extra}>
        <Probe />
      </WhatsNewProvider>
    </TourProvider>,
  );
}

/** An existing user: the welcome guide was completed on an earlier load. */
const existingUser = () => localStorage.setItem(TOUR_KEY, 'true');

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('auto-open at page load', () => {
  it('an existing user with no record sees the popup at exactly 800 ms, everything badged unseen', () => {
    existingUser();
    mount([R('0.5.7', 2)]);

    expect(unseen()).toEqual(['0.5.7']);
    advance(799);
    expect(isOpen()).toBe('false');
    advance(1);
    expect(isOpen()).toBe('true');

    // Opening marks nothing as seen: the badges must survive while the popup is showing.
    expect(unseen()).toEqual(['0.5.7']);
    expect(stored()).toBeNull();
  });

  it('an up-to-date user never sees it open', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.7');
    mount([R('0.5.7', 2)]);

    advance(5000);
    expect(isOpen()).toBe('false');
    expect(unseen()).toEqual([]);
    expect(stored()).toBe('0.5.7');
  });

  it('a user behind by several releases sees it open with every newer release unseen', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.5');
    mount([R('0.5.5', 1), R('0.5.6', 1), R('0.5.7', 1)]);

    expect(unseen()).toEqual(['0.5.6', '0.5.7']);
    advance(799);
    expect(isOpen()).toBe('false');
    advance(1);
    expect(isOpen()).toBe('true');
    expect(unseen()).toEqual(['0.5.6', '0.5.7']);
  });

  it('does not open when the only newer release has no items', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.7');
    mount([R('0.5.7', 1), R('0.5.8', 0)]);

    advance(5000);
    expect(isOpen()).toBe('false');
    expect(unseen()).toEqual([]);
  });

  it.each(['abc', '0.5.7.dev3'])('treats a stored %j as no record: opens at 800 ms', (garbage) => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, garbage);
    mount([R('0.5.7', 1)]);

    expect(unseen()).toEqual(['0.5.7']);
    advance(799);
    expect(isOpen()).toBe('false');
    advance(1);
    expect(isOpen()).toBe('true');

    click('close');
    expect(stored()).toBe('0.5.7');
  });

  it('honours autoOpenDelayMs', () => {
    existingUser();
    mount([R('0.5.7', 1)], { autoOpenDelayMs: 300 });

    advance(299);
    expect(isOpen()).toBe('false');
    advance(1);
    expect(isOpen()).toBe('true');
  });
});

describe('close() records the newest release', () => {
  it('records the newest release, empty ones included, and clears unseen', () => {
    existingUser();
    mount([R('0.5.7', 1), R('0.5.8', 0)]);

    advance(800);
    expect(isOpen()).toBe('true');
    expect(unseen()).toEqual(['0.5.7']);

    click('close');
    expect(stored()).toBe('0.5.8');
    expect(unseen()).toEqual([]);
    expect(isOpen()).toBe('false');

    // It stays closed.
    advance(5000);
    expect(isOpen()).toBe('false');
  });

  it.each([null, '0.5.5'])('with no releases at all, writes nothing (stored before: %j)', (before) => {
    existingUser();
    if (before !== null) localStorage.setItem(WHATS_NEW_STORAGE_KEY, before);
    mount([]);

    // Whether open() shows an empty popup is not pinned; the sidebar hides the item when !hasNotes.
    click('open');
    click('close');
    expect(isOpen()).toBe('false');
    expect(stored()).toBe(before);
  });
});

describe('never stacked on the welcome guide or the tour', () => {
  it('a brand-new user gets the welcome guide only; dismissing it records the newest release; it never opens', () => {
    const releases = [R('0.5.7', 1)];
    const { unmount } = mount(releases);

    advance(5000);
    expect(welcome()).toBe('true'); // harness check: the real TourProvider is showing the guide
    expect(isOpen()).toBe('false');
    expect(stored()).toBeNull(); // nothing is recorded until the guide is dismissed
    expect(unseen()).toEqual(['0.5.7']);

    click('dismissWelcome');
    expect(localStorage.getItem(TOUR_KEY)).toBe('true'); // harness check
    expect(stored()).toBe('0.5.7');
    expect(unseen()).toEqual([]);
    expect(isOpen()).toBe('false');

    advance(5000);
    expect(isOpen()).toBe('false');

    // The next load: no welcome guide, and nothing to show.
    unmount();
    mount(releases);
    advance(5000);
    expect(welcome()).toBe('false');
    expect(isOpen()).toBe('false');
    expect(unseen()).toEqual([]);
  });

  it('a brand-new user who takes the tour: ending it records the newest release, empty ones included; it never opens', () => {
    mount([R('0.5.7', 1), R('0.5.8', 0)]);

    advance(800);
    expect(welcome()).toBe('true');
    click('startTour');
    expect(tourActive()).toBe('true');

    advance(5000);
    expect(isOpen()).toBe('false');
    expect(stored()).toBeNull();

    click('endTour');
    expect(stored()).toBe('0.5.8');
    expect(unseen()).toEqual([]);

    advance(5000);
    expect(isOpen()).toBe('false');
  });

  it('an existing user who starts the tour before the delay gets no popup over it, and the release stays unseen', () => {
    existingUser();
    mount([R('0.5.7', 1)]);

    advance(500);
    click('startTour');
    advance(1500); // t = 2000 ms: the 800 ms timer has fired while the tour was active

    expect(tourActive()).toBe('true');
    expect(isOpen()).toBe('false');
    expect(stored()).toBeNull();
    expect(unseen()).toEqual(['0.5.7']);
  });

  it('after a skipped auto-open, ending the tour neither opens the popup nor records it; the next load opens it', () => {
    existingUser();
    const releases = [R('0.5.7', 1)];
    const { unmount } = mount(releases);

    advance(500);
    click('startTour');
    advance(1500);
    click('endTour');
    expect(tourActive()).toBe('false');

    advance(5000);
    expect(isOpen()).toBe('false'); // decided once, at mount: no late open after the tour
    expect(stored()).toBeNull(); // the tour flag was already set, so there is no transition to record
    expect(unseen()).toEqual(['0.5.7']);

    unmount();
    mount(releases);
    advance(799);
    expect(isOpen()).toBe('false');
    advance(1);
    expect(isOpen()).toBe('true');
  });

  it('does not open if the welcome guide is showing when the timer fires', () => {
    existingUser();
    mount([R('0.5.7', 1)], { autoOpenDelayMs: 2000 });

    click('resetTour'); // the real TourProvider shows the welcome guide 800 ms later
    advance(800);
    expect(welcome()).toBe('true');

    advance(1200); // t = 2000 ms: the What's new timer fires while the guide is showing
    expect(isOpen()).toBe('false');
    advance(5000);
    expect(isOpen()).toBe('false');
  });
});

describe('manual open and the release list', () => {
  it('open() when up to date shows the popup with nothing unseen', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.7');
    mount([R('0.5.7', 2)]);

    advance(5000);
    expect(isOpen()).toBe('false');
    click('open');
    expect(isOpen()).toBe('true');
    expect(unseen()).toEqual([]);
    expect(hasNotes()).toBe('true');

    click('close');
    expect(isOpen()).toBe('false');
    expect(stored()).toBe('0.5.7');
  });

  it('open() leaves unseen releases unseen until close() (the sidebar reopen after a skipped auto-open)', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.6');
    mount([R('0.5.6', 1), R('0.5.7', 1)]);

    advance(100);
    click('startTour');
    advance(1900); // the auto-open was skipped under the tour
    click('endTour');
    expect(isOpen()).toBe('false');

    click('open');
    expect(isOpen()).toBe('true');
    expect(unseen()).toEqual(['0.5.7']);
    expect(stored()).toBe('0.5.6');

    click('close');
    expect(isOpen()).toBe('false');
    expect(unseen()).toEqual([]);
    expect(stored()).toBe('0.5.7');
  });

  it('only empty releases: hasNotes is false, the list is empty and it never opens', () => {
    existingUser();
    mount([R('0.5.7', 0)]);

    expect(hasNotes()).toBe('false');
    expect(shownReleases()).toEqual([]);
    expect(unseen()).toEqual([]);
    advance(5000);
    expect(isOpen()).toBe('false');
  });

  it('lists releases newest first (numeric per component) and drops the empty ones', () => {
    existingUser();
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.10');
    mount([R('0.5.6', 1), R('0.5.11', 0), R('0.5.10', 2), R('0.5.9', 1)]);

    expect(shownReleases()).toEqual(['0.5.10', '0.5.9', '0.5.6']);
    expect(hasNotes()).toBe('true');
    expect(unseen()).toEqual([]);
  });

  it('defaults to the bundled RELEASES when no releases prop is given', () => {
    existingUser();
    render(
      <TourProvider>
        <WhatsNewProvider>
          <Probe />
        </WhatsNewProvider>
      </TourProvider>,
    );

    expect(shownReleases()).toEqual(['0.9.0']);
    expect(hasNotes()).toBe('true');
    expect(unseen()).toEqual(['0.9.0']);
    advance(800);
    expect(isOpen()).toBe('true');
    click('close');
    expect(stored()).toBe('0.9.1');
  });
});

describe('useWhatsNew', () => {
  it('throws outside the provider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // Calls the hook and touches nothing it returns, so only the hook itself can throw.
    function Bare() {
      useWhatsNew();
      return null;
    }
    expect(() =>
      render(
        <TourProvider>
          <Bare />
        </TourProvider>,
      ),
    ).toThrow();
  });
});
