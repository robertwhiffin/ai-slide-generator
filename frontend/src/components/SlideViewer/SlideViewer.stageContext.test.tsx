/**
 * Architect stage awareness, Task 1: SlideViewerHandle.getStageSlide().
 *
 * Contract (task brief + PLAN-CORRECTIONS C3): the viewer's imperative handle exposes a SYNCHRONOUS
 * getter returning the slide on stage as `{ slide_number, slide_id? }`, where slide_number is the
 * 1-based number the stage shows ("N / total"), and slide_id is that displayed slide's stable id. An
 * empty viewer supplies no stage (undefined).
 *
 * Each test below names the production mutation it catches:
 *   - getter returns currentIndex (0-based) instead of the 1-based number   -> "the first slide" + paging.
 *   - getter derives the number from `slide.index` rather than the position on stage (an optimistic
 *     reorder leaves `index` fields stale)                                   -> "stale index fields".
 *   - getter caches the stage at navigation time (state/ref updated only on next/prev/select), so a
 *     deck replacement or a deletion leaves a stale id                       -> "deck changes under the stage".
 *   - getter still answers after the deck empties (handle cached on the outer component) -> "empty".
 *   - getter not reset on remount (module-level/static cache)               -> "remount".
 *
 * Harness as SlideViewer.imageAction.test.tsx: api mocked, in-memory localStorage (Node 26 has none
 * for jsdom), feedback drawer closed, decks without content_hash so auto-verification stays idle.
 */
import { createRef } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SlideViewer, type SlideViewerHandle } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks } from '../../types/finding';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getSlides: vi.fn().mockResolvedValue({ slide_deck: null }),
      verifySlide: vi.fn().mockResolvedValue({}),
    },
  };
});

/** Structural mirror of the StageSlideContext the task adds to types/slide.ts. */
interface StageSlide { slide_number: number; slide_id?: string }
/** The handle as the task extends it; cast so this file compiles before and after the change. */
type StageHandle = SlideViewerHandle & { getStageSlide?: () => StageSlide | undefined };

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

const noop = () => undefined;
const callbacks: DrawerCallbacks = { onApplyFinding: noop, onDismissFinding: noop, onDiscussFinding: noop };

/** A deck whose slide_ids are NOT derivable from their positions. `indexFields` overrides slide.index. */
function deck(ids: string[], indexFields?: number[]): SlideDeck {
  return {
    title: 'Deck',
    slide_count: ids.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: ids.map((slide_id, i) => ({
      index: indexFields ? indexFields[i] : i,
      slide_id,
      html: `<div class="slide"><h1>${slide_id}</h1></div>`,
      scripts: '',
    })),
  };
}

const FOUR = ['alpha', 'bravo', 'charlie', 'delta'];

function viewer(slideDeck: SlideDeck | null, ref: React.Ref<SlideViewerHandle>, deckKey = 'sess-stage') {
  return (
    <ToastProvider>
      <SlideViewer
        ref={ref}
        slideDeck={slideDeck}
        deckKey={deckKey}
        findings={[]}
        callbacks={callbacks}
        onReorder={noop}
        onSlideChange={noop}
        onSendMessage={noop}
        sessionId={deckKey}
      />
    </ToastProvider>
  );
}

/** Call the getter as a consumer would. A missing getter yields undefined (a red assertion, not a crash). */
const stageOf = (ref: React.RefObject<SlideViewerHandle | null>) =>
  (ref.current as StageHandle | null)?.getStageSlide?.();

const position = () => screen.getByTestId('stage-position').textContent?.replace(/\s+/g, ' ').trim();

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('SlideViewer getStageSlide(): the displayed slide', () => {
  it('on mount it is the first slide: 1-based number and its id', () => {
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(FOUR), ref));

    expect(position()).toBe('1 / 4');
    expect(stageOf(ref)).toEqual({ slide_number: 1, slide_id: 'alpha' });
  });

  it('follows next and previous on the stage', () => {
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(FOUR), ref));

    fireEvent.click(screen.getByTestId('stage-next'));
    fireEvent.click(screen.getByTestId('stage-next'));
    expect(position()).toBe('3 / 4');
    expect(stageOf(ref)).toEqual({ slide_number: 3, slide_id: 'charlie' });

    fireEvent.click(screen.getByTestId('stage-prev'));
    expect(position()).toBe('2 / 4');
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'bravo' });
  });

  it('follows keyboard paging (ArrowRight, End, Home)', () => {
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(FOUR), ref));

    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'bravo' });
    fireEvent.keyDown(window, { key: 'End' });
    expect(stageOf(ref)).toEqual({ slide_number: 4, slide_id: 'delta' });
    fireEvent.keyDown(window, { key: 'Home' });
    expect(stageOf(ref)).toEqual({ slide_number: 1, slide_id: 'alpha' });
  });

  it('follows a ribbon selection', () => {
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(FOUR), ref));

    fireEvent.click(screen.getByTestId('ribbon-thumb-3'));
    expect(screen.getByTestId('ribbon-thumb-3')).toHaveAttribute('data-current', 'true');
    expect(stageOf(ref)).toEqual({ slide_number: 4, slide_id: 'delta' });

    fireEvent.click(screen.getByTestId('ribbon-thumb-1'));
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'bravo' });
  });

  it('numbers by position on stage, not by stale slide.index fields (an optimistic reorder keeps them)', () => {
    // Display order charlie, alpha, bravo; their `index` fields still say 2, 0, 1.
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(['charlie', 'alpha', 'bravo'], [2, 0, 1]), ref));

    expect(stageOf(ref)).toEqual({ slide_number: 1, slide_id: 'charlie' });
    fireEvent.click(screen.getByTestId('stage-next'));
    expect(position()).toBe('2 / 3');
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'alpha' });
  });

  it('the same handle answers the new slide after paging (no handle frozen at its first render, e.g. empty useImperativeHandle deps)', () => {
    const ref = createRef<SlideViewerHandle>();
    render(viewer(deck(FOUR), ref));

    const before = stageOf(ref);
    fireEvent.click(screen.getByTestId('stage-next'));
    const after = stageOf(ref);

    expect(before).toEqual({ slide_number: 1, slide_id: 'alpha' });
    expect(after).toEqual({ slide_number: 2, slide_id: 'bravo' });
  });
});

describe('SlideViewer getStageSlide(): the deck changes under the stage', () => {
  it('after the slide on stage is deleted, it is the slide now displayed at that number', () => {
    const ref = createRef<SlideViewerHandle>();
    const { rerender } = render(viewer(deck(FOUR), ref));
    fireEvent.click(screen.getByTestId('ribbon-thumb-1'));
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'bravo' });

    // bravo deleted elsewhere: the refetched deck no longer holds it.
    rerender(viewer(deck(['alpha', 'charlie', 'delta']), ref));

    expect(position()).toBe('2 / 3');
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'charlie' });
  });

  it('a shorter deck for another session clamps to its last slide, with that deck\'s id', () => {
    const ref = createRef<SlideViewerHandle>();
    const { rerender } = render(viewer(deck(FOUR), ref, 'sess-a'));
    fireEvent.click(screen.getByTestId('ribbon-thumb-3'));
    expect(stageOf(ref)).toEqual({ slide_number: 4, slide_id: 'delta' });

    rerender(viewer(deck(['b-one', 'b-two']), ref, 'sess-b'));

    expect(position()).toBe('2 / 2');
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'b-two' });
  });

  it('an empty viewer supplies no stage, including after a deck that had one empties', () => {
    const ref = createRef<SlideViewerHandle>();
    const { rerender } = render(viewer(deck(FOUR), ref));
    fireEvent.click(screen.getByTestId('stage-next'));
    expect(stageOf(ref)).toEqual({ slide_number: 2, slide_id: 'bravo' });

    rerender(viewer(deck([]), ref));
    expect(screen.getByTestId('slide-viewer-empty')).toBeInTheDocument();
    expect(stageOf(ref)).toBeUndefined();

    rerender(viewer(null, ref));
    expect(stageOf(ref)).toBeUndefined();

    // Positive half: a deck arriving again supplies its own first slide, not the old stage.
    rerender(viewer(deck(['new-1', 'new-2']), ref));
    expect(stageOf(ref)).toEqual({ slide_number: 1, slide_id: 'new-1' });
  });

  it('a remount (AppLayout re-keys the viewer, e.g. leaving a save-point preview) starts again on slide 1', () => {
    const ref = createRef<SlideViewerHandle>();
    const keyed = (key: string) => (
      <ToastProvider>
        <SlideViewer
          key={key}
          ref={ref}
          slideDeck={deck(FOUR)}
          deckKey="sess-stage"
          findings={[]}
          callbacks={callbacks}
          onReorder={noop}
        />
      </ToastProvider>
    );
    const { rerender } = render(keyed('current'));
    fireEvent.click(screen.getByTestId('ribbon-thumb-2'));
    expect(stageOf(ref)).toEqual({ slide_number: 3, slide_id: 'charlie' });

    act(() => { rerender(keyed('preview-v1')); });

    expect(position()).toBe('1 / 4');
    expect(stageOf(ref)).toEqual({ slide_number: 1, slide_id: 'alpha' });
  });
});
