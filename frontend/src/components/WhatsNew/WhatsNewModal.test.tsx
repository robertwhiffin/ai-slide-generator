/**
 * What's new popup, Task 3: WhatsNewModal, the popup itself (task-3-brief.md "Modal requirements").
 *
 * Contract pinned here:
 *   - Closed: it renders nothing. No [role="dialog"] is left anywhere, so useEscapeToStop can act.
 *   - Open: a panel with the role="dialog" ATTRIBUTE and aria-modal="true", named "What's new in
 *     Tellr", carrying the title and the subtitle "Highlights from each release". It has to be the
 *     attribute, because useEscapeToStop queries [role="dialog"], which a native <dialog> does not match.
 *   - One <section aria-label="Tellr {version}"> per release WITH items, newest first. An empty
 *     release gets nothing. Each section shows its version, a "New" badge only when
 *     unseen.has(version), its month (formatReleaseMonth: "November 2026") and a <ul> of
 *     <li><strong>{title}.</strong> {body}</li>.
 *   - "Got it" takes focus whenever the popup opens, not only the first time.
 *   - "Got it", ✕ (aria-label "Close"), Esc and a click on the overlay (the dialog's parent) all call
 *     close(). close() records the newest release EMPTY ONES INCLUDED: '0.5.8' here, never '0.5.7', the
 *     newest with items. A click inside the panel does nothing.
 *   - Esc: a window keydown listener, present only while open, that calls preventDefault() and then
 *     close(), copying ConfirmDialog.tsx:38-49. Other keys are not handled and not swallowed.
 *
 * Review Focus 1 (Esc while a generation is running): Esc closes the popup only. A probe runs the REAL
 * useEscapeToStop(true, onStop), mounted both before the popup opens and after it opens. In a real
 * browser React commits the close in the microtask checkpoint between two window listeners. So when the
 * popup's listener runs first, the dialog is already gone by the time useEscapeToStop runs, and only
 * preventDefault() keeps the generation going. jsdom cannot reproduce that commit: inside act() the
 * dialog stays in the DOM for the whole dispatch. So the test asserts the defaultPrevented flag (the
 * fireEvent return value) directly, and pairs every "onStop not called" with a second Esc that must stop.
 *
 * Harness: the REAL TourProvider (tour flag 'true', so no welcome guide) and the REAL WhatsNewProvider
 * with fixture releases and autoOpenDelayMs={0}. The stored last-seen version is '0.5.6'. Fake timers:
 * runTimers() fires the 0 ms auto-open inside act(), which flushes the render and its effects. A second
 * pass runs anything the opened popup defers (for example a focus timer). The modal sits in a
 * data-testid slot so "renders nothing" can be checked. A `reopen` button stands in for the sidebar item.
 *
 * SABOTAGE (each was measured against a throwaway reference outside the tracked tree, since deleted;
 * each turned at least one test red):
 *   - a native <dialog open> with no role attribute     -> the first test, and RF1 "already running"
 *                                                          (the stop hook runs first and sees no [role="dialog"]).
 *   - Esc without preventDefault, or stopPropagation     -> both RF1 rows (the event is not marked handled).
 *   - the Esc listener kept while closed                 -> both RF1 rows (the second Esc is swallowed).
 *   - no Esc listener / Esc via onKeyDown on the panel   -> the Esc row, the reopen test and both RF1 rows.
 *   - preventDefault on every key / any key closes       -> "other keys neither close it nor get swallowed".
 *   - overlay click does nothing / any click closes      -> the overlay row / "a click inside the panel".
 *   - an overlay or a hidden [role="dialog"] left behind when closed -> the first test and every close row.
 *   - "New" on every / no / only the newest release, or `unseen` frozen at mount -> the badge or reopen test.
 *   - oldest first / only unseen releases listed         -> "newest first" (and others).
 *   - section label "v0.5.7" or a <div> (no region) / version not shown -> the section tests.
 *   - lead-in period outside <strong>, no space, no period, <b> not <strong>, no ul/li -> the item test.
 *   - the newest month on every release / the raw date / no month -> the item test.
 *   - no focus / focus only at mount / focus on ✕        -> the focus test and the reopen test.
 *   - "Got it" not wired / ✕ without aria-label "Close"  -> that close row.
 *   - curly apostrophe in the name / no aria-modal / no title text / no subtitle -> the first test.
 * Equivalents that stay green: an autoFocus attribute, focus deferred by setTimeout 0, a capture-phase
 * Esc listener, a portal into document.body, aria-labelledby on the h2, the version and month on one
 * line, and overlay onClick={close} with stopPropagation on the panel.
 *
 * Local runs need NODE_OPTIONS=--no-experimental-webstorage (PLAN-CORRECTIONS C1).
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { TourProvider } from '@/contexts/TourContext';
import { WhatsNewProvider, useWhatsNew } from '@/contexts/WhatsNewContext';
import { useEscapeToStop } from '@/components/ChatPanel/useEscapeToStop';
import { WHATS_NEW_STORAGE_KEY, type ReleaseNoteItem, type ReleaseNotes } from '@/whatsNew/releaseNotes';
import { WhatsNewModal } from './WhatsNewModal';

const TITLE = "What's new in Tellr";
const SUBTITLE = 'Highlights from each release';
const TOUR_KEY = 'tellr-app-tour-completed';

const IMAGES: ReleaseNoteItem = { title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.' };
const STOP: ReleaseNoteItem = { title: 'Stop a generation', body: 'Press Esc to cancel mid-flow.' };
const FASTER: ReleaseNoteItem = { title: 'Faster deck loading', body: 'Large decks open in seconds.' };

/** Release `version`, dated `date`, with these items. No item text contains a version number. */
function R(version: string, date: string, items: ReleaseNoteItem[]): ReleaseNotes {
  return { version, date, items };
}

// The brief's [R('0.5.6',1), R('0.5.7',2), R('0.5.8',0)], in that unsorted order.
const RELEASES = [
  R('0.5.6', '2026-10-30', [FASTER]),
  R('0.5.7', '2026-11-14', [IMAGES, STOP]),
  R('0.5.8', '2026-11-20', []), // the newest, but empty: no section, yet close() records it
];

/** Stands in for the sidebar's "What's new" item. */
function Reopen() {
  const { open } = useWhatsNew();
  return <button onClick={open}>reopen</button>;
}

/** A running generation: the real Esc-to-stop hook, active. */
function StopProbe({ onStop }: { onStop: () => void }) {
  useEscapeToStop(true, onStop);
  return null;
}

function ui(extra?: ReactNode) {
  return (
    <TourProvider>
      <WhatsNewProvider releases={RELEASES} autoOpenDelayMs={0}>
        <Reopen />
        <div data-testid="modal-slot">
          <WhatsNewModal />
        </div>
        {extra}
      </WhatsNewProvider>
    </TourProvider>
  );
}

/** Fires the 0 ms auto-open, then anything the opened popup defers. act() flushes renders and effects. */
function runTimers() {
  act(() => {
    vi.runAllTimers();
  });
  act(() => {
    vi.runAllTimers();
  });
}

function mountOpen(extra?: ReactNode) {
  const utils = render(ui(extra));
  runTimers();
  return { ...utils, dialog: screen.getByRole('dialog', { name: TITLE }) };
}

const stored = () => localStorage.getItem(WHATS_NEW_STORAGE_KEY);
const gotIt = (dialog: HTMLElement) => within(dialog).getByRole('button', { name: 'Got it' });
const section = (dialog: HTMLElement, version: string) =>
  within(dialog).getByRole('region', { name: `Tellr ${version}` });
/** The text of each list entry in a release section, whitespace collapsed. */
const itemTexts = (s: HTMLElement) =>
  within(within(s).getByRole('list'))
    .getAllByRole('listitem')
    .map((li) => (li.textContent ?? '').replace(/\s+/g, ' ').trim());
/** An Escape keydown that bubbles from `target` to window. Returns false if a listener prevented it. */
const esc = (target: Element = document.body) => fireEvent.keyDown(target, { key: 'Escape', code: 'Escape' });

/** The release sections, in document order, are exactly these versions. */
function expectReleaseSections(dialog: HTMLElement, versions: string[]) {
  const all = within(dialog).getAllByRole('region', { name: /^Tellr / });
  expect(all).toHaveLength(versions.length);
  versions.forEach((v, i) => expect(all[i]).toBe(section(dialog, v)));
}

/** The popup is gone: nothing in its slot, and no [role="dialog"] left for useEscapeToStop to find. */
function expectClosed() {
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(screen.getByTestId('modal-slot')).toBeEmptyDOMElement();
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  localStorage.setItem(TOUR_KEY, 'true'); // an existing user: the welcome guide was done on an earlier load
  localStorage.setItem(WHATS_NEW_STORAGE_KEY, '0.5.6'); // who last dismissed the 0.5.6 notes
});

afterEach(() => {
  vi.useRealTimers();
});

describe('WhatsNewModal: what it shows', () => {
  it('renders nothing until it opens, then a modal dialog named "What\'s new in Tellr" with its title and subtitle', () => {
    render(ui());
    expectClosed();

    runTimers();
    const dialog = screen.getByRole('dialog', { name: TITLE });
    expect(dialog).toHaveAttribute('role', 'dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByText(TITLE)).toBeInTheDocument();
    expect(within(dialog).getByText(SUBTITLE)).toBeInTheDocument();
  });

  it('lists the releases that have items, newest first, each showing its version; the empty 0.5.8 gets nothing', () => {
    const { dialog } = mountOpen();

    expectReleaseSections(dialog, ['0.5.7', '0.5.6']);
    expect(section(dialog, '0.5.7')).toHaveTextContent('0.5.7');
    expect(section(dialog, '0.5.6')).toHaveTextContent('0.5.6');
    expect(within(dialog).queryByRole('region', { name: 'Tellr 0.5.8' })).toBeNull();
    expect(dialog).not.toHaveTextContent('0.5.8');
  });

  it('badges "New" on the release newer than the last one dismissed, and nowhere else', () => {
    const { dialog } = mountOpen();

    expect(within(section(dialog, '0.5.7')).getByText('New')).toBeInTheDocument();
    expect(within(section(dialog, '0.5.6')).queryByText('New')).toBeNull();
    expect(within(dialog).getAllByText('New')).toHaveLength(1);
  });

  it('renders each item as a list entry, "<strong>Title.</strong> Body", and each release its own month', () => {
    const { dialog } = mountOpen();
    const s57 = section(dialog, '0.5.7');
    const s56 = section(dialog, '0.5.6');

    expect(itemTexts(s57)).toEqual([
      'Images in chat. Ask for an image of a monkey at a keyboard.',
      'Stop a generation. Press Esc to cancel mid-flow.',
    ]);
    expect(itemTexts(s56)).toEqual(['Faster deck loading. Large decks open in seconds.']);

    // The title and its full stop are the bold lead-in, inside the first list entry.
    const lead = within(s57).getByText('Images in chat.', { selector: 'strong' });
    expect(lead.closest('li')).toBe(within(s57).getAllByRole('listitem')[0]);
    expect(within(s56).getByText('Faster deck loading.', { selector: 'strong' })).toBeInTheDocument();

    expect(s57).toHaveTextContent('November 2026'); // date 2026-11-14
    expect(s57).not.toHaveTextContent('October 2026');
    expect(s56).toHaveTextContent('October 2026'); // date 2026-10-30
    expect(s56).not.toHaveTextContent('November 2026');
  });

  it('puts focus on "Got it" when it opens', () => {
    const { dialog } = mountOpen();
    expect(gotIt(dialog)).toHaveFocus();
  });
});

describe('WhatsNewModal: closing', () => {
  const ways: Array<[string, (dialog: HTMLElement) => void]> = [
    ['"Got it"', (d) => { fireEvent.click(gotIt(d)); }],
    ['the ✕ button', (d) => { fireEvent.click(within(d).getByRole('button', { name: 'Close' })); }],
    ['Esc on document.body', () => { esc(); }],
    ['a click on the overlay', (d) => { fireEvent.click(d.parentElement as HTMLElement); }],
  ];

  it.each(ways)('%s closes it and records the newest release, empty ones included', (_, dismiss) => {
    const { dialog } = mountOpen();
    expect(stored()).toBe('0.5.6');

    dismiss(dialog);
    expectClosed();
    expect(stored()).toBe('0.5.8');

    // It stays closed.
    runTimers();
    expectClosed();
  });

  it('a click inside the panel leaves it open', () => {
    const { dialog } = mountOpen();

    fireEvent.click(dialog);
    fireEvent.click(within(dialog).getByText(SUBTITLE));
    fireEvent.click(section(dialog, '0.5.6'));
    fireEvent.click(within(dialog).getByText('Images in chat.', { selector: 'strong' }));
    expect(screen.getByRole('dialog', { name: TITLE })).toBe(dialog);
    expect(stored()).toBe('0.5.6');

    // Positive: the same popup does close from its button.
    fireEvent.click(gotIt(dialog));
    expectClosed();
  });

  it('other keys neither close it nor get swallowed', () => {
    const { dialog } = mountOpen();

    expect(fireEvent.keyDown(document.body, { key: 'a', code: 'KeyA' })).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: 'Enter', code: 'Enter' })).toBe(true);
    expect(screen.getByRole('dialog', { name: TITLE })).toBe(dialog);
    expect(stored()).toBe('0.5.6');

    // Positive: Esc, on the same target, does close it.
    esc();
    expectClosed();
  });

  it('reopened after dismissal: the same releases, no "New" badge, and "Got it" focused again', () => {
    const { dialog } = mountOpen();
    fireEvent.click(gotIt(dialog));
    expectClosed();

    fireEvent.click(screen.getByRole('button', { name: 'reopen' }));
    runTimers();
    const again = screen.getByRole('dialog', { name: TITLE });
    expectReleaseSections(again, ['0.5.7', '0.5.6']);
    expect(within(again).queryByText('New')).toBeNull();
    expect(gotIt(again)).toHaveFocus();

    esc();
    expectClosed();
    expect(stored()).toBe('0.5.8');
  });
});

describe('Review Focus 1: Esc while a generation is running and the popup is open', () => {
  it.each([
    ['was already running when the popup opened', 'before'],
    ['started while the popup was open', 'after'],
  ] as const)('a generation that %s: Esc closes the popup only, and the next Esc stops it', (_, order) => {
    const onStop = vi.fn();
    const probe = <StopProbe onStop={onStop} />;
    const { rerender } = render(ui(order === 'before' ? probe : undefined));
    runTimers();
    if (order === 'after') rerender(ui(probe));
    expect(screen.getByRole('dialog', { name: TITLE })).toBeInTheDocument();

    // The popup marks the Esc handled (preventDefault), closes, and the generation goes on.
    expect(esc()).toBe(false);
    expectClosed();
    expect(stored()).toBe('0.5.8');
    expect(onStop).not.toHaveBeenCalled();

    // Positive: the probe's listener is live, and with the popup gone nothing swallows Esc.
    expect(esc()).toBe(true);
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
