# Flip-through Slide Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scrolling slide list with a single-slide stage, a vertical thumbnail ribbon, and a tabbed drawer showing per-slide AI feedback.

**Architecture:** Three new components under `frontend/src/components/SlideViewer/` — a stage that renders one slide, a ribbon that lists thumbnails and drives selection, and a drawer hosting AI-feedback findings. A `ViewerContext` owns current-slide index and drawer view-state (persisted to `localStorage`). `AppLayout` swaps `SelectionRibbon` + `SlidePanel` for the new trio. Checkbox/contiguous selection is deleted. Review findings arrive as props with mocked fixture data; the producing backend is a later workstream.

**Tech Stack:** React 19, TypeScript 5.9, Vite 7, Tailwind 3.4, `@dnd-kit` (drag-reorder), Playwright 1.57 (the only test runner — see Global Constraints).

**Spec:** `docs/superpowers/specs/2026-08-03-flip-through-viewer-design.md`

## Global Constraints

- **Strictly front-end.** No changes under `src/` (Python backend), no new endpoints, no domain-model or schema changes. If a task appears to need one, STOP and raise it. Final `git diff --stat` must touch `frontend/` and `docs/` only.
- **No unit-test runner exists.** `npm test` is Playwright only (`frontend/package.json`: `"test": "playwright test"`). There is no vitest/jest. All tests in this plan are Playwright specs in `frontend/tests/`. Do not add a unit-test framework.
- **Tests run backendless** via `page.route(...)` mocking — see `frontend/tests/helpers/setup-mocks.ts` and `frontend/tests/fixtures/mocks.ts`. Always call `setupMocks(page)` in `beforeEach`.
- **Playwright baseURL is `http://localhost:3000`**; the dev server is started automatically by `playwright.config.ts` (`webServer`, `reuseExistingServer: true`).
- **Speaker notes are out of scope entirely** — no domain field, no persistence, no editor. Build the drawer as a tabbed shell with one tab so notes drop in later.
- **`seen` state is client-side only** (`localStorage`), never sent to a server.
- **Findings are props, never fetched.** No `api.ts` calls for findings.
- **Do not touch** slide HTML rendering/sanitisation, export, or presentation mode.
- **Typecheck must pass:** `npm run typecheck` (`tsc -b`) and `npm run lint` (eslint).

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `frontend/src/contexts/ViewerContext.tsx` | Current-slide index + drawer view-state (open, height, active tab), `localStorage` persistence |
| `frontend/src/components/SlideViewer/SlideStage.tsx` | Renders exactly one slide; arrow controls; wheel-to-page |
| `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx` | Vertical thumbnail list, click-to-select, drag-reorder, unseen-feedback dot, auto-reveal |
| `frontend/src/components/SlideViewer/FeedbackDrawer.tsx` | Tabbed shell + AI-feedback list with Apply/Dismiss/Discuss |
| `frontend/src/components/SlideViewer/SlideViewer.tsx` | Composes stage + ribbon + drawer; owns keyboard handling |
| `frontend/src/components/SlideViewer/seenState.ts` | `localStorage` read/write for seen findings, with a deck-count cap |
| `frontend/src/types/finding.ts` | `SlideFinding`, `FindingCategory`, `DrawerCallbacks` |
| `frontend/tests/fixtures/findings.ts` | Mock findings fixture |
| `frontend/tests/e2e/slide-viewer.spec.ts` | All Playwright specs for this workstream |
| `docs/technical/slide-viewer.md` | Technical doc for the new surface |

**Modify:**

| Path | Change |
|---|---|
| `frontend/src/components/Layout/AppLayout.tsx:54,69,862-879` | Replace `SelectionRibbon`+`SlidePanel` with `SlideViewer`; drop `scrollTarget`/`scrollToSlide` |
| `frontend/src/components/SlidePanel/SlideSelection.tsx:3,32` | Delete (checkbox selection retired) |
| `frontend/src/components/SlidePanel/SelectionRibbon.tsx` | Delete (replaced by `ThumbnailRibbon`) |
| `frontend/src/utils/slideReplacements.ts:1` | Remove `isContiguous` (only consumer was `SlideSelection.tsx:32`) |
| `frontend/src/contexts/SelectionContext.tsx` | Delete provider usage; remove from app tree |
| `docs/technical/frontend-overview.md` | Correct 6 stale locations (see Task 9) |
| `README.md:131-142` | Add `slide-viewer.md` to doc table |
| `docs-site/sidebars.js:49` | Add `technical/slide-viewer` |

**Deliberately NOT deleted:** `SlidePanel.tsx`, `SlideTile.tsx`, `HTMLEditorModal.tsx`, `VisualEditorPanel.tsx`, `ElementTreeView.tsx`, `treeParser.ts`, `VerificationBadge.tsx`. `SlidePanel` hosts per-slide CRUD, the HTML editor, and verification badges that this workstream does not replace. Task 8 migrates the still-needed affordances; the inline WYSIWYG rebuild is workstream 8.

---

## Task 1: Types and findings fixture

**Files:**
- Create: `frontend/src/types/finding.ts`
- Create: `frontend/tests/fixtures/findings.ts`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `FindingCategory`, `SlideFinding`, `DrawerCallbacks` from `src/types/finding.ts`; `mockFindings` from `tests/fixtures/findings.ts`.

- [ ] **Step 1: Create the type module**

Create `frontend/src/types/finding.ts`:

```typescript
export type FindingCategory = 'content' | 'design' | 'narrative';

export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index
  category: FindingCategory;
  message: string;
  seen: boolean;        // initial value only; lifecycle owned client-side
}

export interface DrawerCallbacks {
  onApplyFinding: (findingId: string) => void;
  onDismissFinding: (findingId: string) => void;
  onDiscussFinding: (findingId: string) => void;
}
```

- [ ] **Step 2: Create the fixture**

Create `frontend/tests/fixtures/findings.ts`:

```typescript
import type { SlideFinding } from '../../src/types/finding';

export const mockFindings: SlideFinding[] = [
  { id: 'f1', slideIndex: 1, category: 'design',    message: 'This layout is busy; consider splitting it.', seen: false },
  { id: 'f2', slideIndex: 1, category: 'content',   message: 'The 35% figure is not supported by the source data.', seen: false },
  { id: 'f3', slideIndex: 3, category: 'narrative', message: 'This slide breaks the argument arc.', seen: false },
];
```

- [ ] **Step 3: Verify it compiles**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/finding.ts frontend/tests/fixtures/findings.ts
git commit -m "feat(viewer): add SlideFinding types and fixture"
```

---

## Task 2: Seen-state persistence

**Files:**
- Create: `frontend/src/components/SlideViewer/seenState.ts`
- Test: `frontend/tests/e2e/slide-viewer.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `loadSeen(deckKey: string): Set<string>`, `markSeen(deckKey: string, findingIds: string[]): void`, and `SEEN_STORAGE_KEY`.

Growth is bounded inside `markSeen` via the `MAX_DECKS` cap, so no separate prune function is needed — do not add one (an exported helper nothing calls is dead API).

Spec §5.1.1: `localStorage` (not cookies), keyed by deck *and* finding id, growth-bounded.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/components/SlideViewer/seenState.ts`:

```typescript
/**
 * Seen-state for AI-feedback findings.
 *
 * Stored client-side in localStorage, never sent to a server:
 *  - per-user by construction (per browser profile), so one user reading a
 *    finding cannot clear another user's highlight on a shared deck;
 *  - survives reload, so reopening a deck does not re-highlight read feedback.
 * Accepted trade-off: does not follow the user to another browser or device.
 */
export const SEEN_STORAGE_KEY = 'tellr-viewer-seen-findings';

// Guard against unbounded growth (spec §5.1.1).
const MAX_DECKS = 50;

type SeenStore = Record<string, string[]>;   // deckKey -> finding ids

function read(): SeenStore {
  try {
    const raw = localStorage.getItem(SEEN_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SeenStore) : {};
  } catch {
    return {};
  }
}

function write(store: SeenStore): void {
  try {
    localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Quota or disabled storage: seen-state is advisory, so degrade silently.
  }
}

export function loadSeen(deckKey: string): Set<string> {
  return new Set(read()[deckKey] ?? []);
}

export function markSeen(deckKey: string, findingIds: string[]): void {
  if (findingIds.length === 0) return;
  const store = read();
  const merged = new Set([...(store[deckKey] ?? []), ...findingIds]);
  store[deckKey] = Array.from(merged);

  // Trim oldest insertion-ordered deck keys if we exceed the cap.
  const keys = Object.keys(store);
  if (keys.length > MAX_DECKS) {
    for (const stale of keys.slice(0, keys.length - MAX_DECKS)) {
      delete store[stale];
    }
  }
  write(store);
}

```

- [ ] **Step 2: Write the failing test**

Create `frontend/tests/e2e/slide-viewer.spec.ts`. This module is exercised in the browser via `page.evaluate` against the app's own bundle, because there is no unit-test runner (see Global Constraints):

```typescript
import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';

test.describe('seen-state persistence', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('markSeen persists per deck and loadSeen reads it back', async ({ page }) => {
    await page.goto('/');

    const result = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      m.markSeen('deck-a', ['f1', 'f2']);
      m.markSeen('deck-b', ['f9']);
      return {
        a: Array.from(m.loadSeen('deck-a')).sort(),
        b: Array.from(m.loadSeen('deck-b')),
        empty: Array.from(m.loadSeen('deck-missing')),
      };
    });

    expect(result.a).toEqual(['f1', 'f2']);
    expect(result.b).toEqual(['f9']);      // scoped per deck
    expect(result.empty).toEqual([]);
  });

  test('markSeen merges rather than overwrites', async ({ page }) => {
    await page.goto('/');

    const merged = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      m.markSeen('deck-c', ['f1']);
      m.markSeen('deck-c', ['f2']);
      return Array.from(m.loadSeen('deck-c')).sort();
    });

    expect(merged).toEqual(['f1', 'f2']);
  });

  test('markSeen caps stored decks so the store cannot grow unbounded', async ({ page }) => {
    await page.goto('/');

    const deckCount = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      localStorage.removeItem(m.SEEN_STORAGE_KEY);
      for (let i = 0; i < 60; i++) m.markSeen(`deck-${i}`, [`f${i}`]);
      return Object.keys(JSON.parse(localStorage.getItem(m.SEEN_STORAGE_KEY) ?? '{}')).length;
    });

    expect(deckCount).toBeLessThanOrEqual(50);   // MAX_DECKS
  });
});
```

- [ ] **Step 3: Run the tests**

Run: `cd frontend && npx playwright test tests/e2e/slide-viewer.spec.ts --project=chromium`
Expected: PASS (implementation was written in Step 1; if it fails, fix `seenState.ts`, not the test).

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SlideViewer/seenState.ts frontend/tests/e2e/slide-viewer.spec.ts
git commit -m "feat(viewer): add localStorage seen-state for findings"
```

---

## Task 3: ViewerContext

**Files:**
- Create: `frontend/src/contexts/ViewerContext.tsx`
- Test: `frontend/tests/e2e/slide-viewer.spec.ts` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `ViewerProvider` (props: `{ slideCount: number; children: React.ReactNode }`) and `useViewer()` returning:
  `{ currentIndex: number; setCurrentIndex: (i: number) => void; next: () => void; prev: () => void; first: () => void; last: () => void; drawerOpen: boolean; setDrawerOpen: (v: boolean) => void; drawerHeight: number; setDrawerHeight: (px: number) => void; activeTab: DrawerTab; setActiveTab: (t: DrawerTab) => void }`
  plus `export type DrawerTab = 'feedback'`.

Spec §5.1: sticky tab, persisted open/height. `DrawerTab` is a single-member union today so a second tab is additive.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/contexts/ViewerContext.tsx`:

```tsx
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/** Single member today; speaker notes add 'notes' later without restructuring (spec §5). */
export type DrawerTab = 'feedback';

const VIEW_STATE_KEY = 'tellr-viewer-view-state';
const DEFAULT_HEIGHT = 180;
const MIN_HEIGHT = 96;
const MAX_HEIGHT = 480;

interface PersistedViewState {
  drawerOpen: boolean;
  drawerHeight: number;
  activeTab: DrawerTab;
}

const DEFAULT_VIEW_STATE: PersistedViewState = {
  drawerOpen: true,
  drawerHeight: DEFAULT_HEIGHT,
  activeTab: 'feedback',
};

function readViewState(): PersistedViewState {
  try {
    const raw = localStorage.getItem(VIEW_STATE_KEY);
    if (!raw) return DEFAULT_VIEW_STATE;
    return { ...DEFAULT_VIEW_STATE, ...(JSON.parse(raw) as Partial<PersistedViewState>) };
  } catch {
    return DEFAULT_VIEW_STATE;
  }
}

function writeViewState(state: PersistedViewState): void {
  try {
    localStorage.setItem(VIEW_STATE_KEY, JSON.stringify(state));
  } catch {
    // Non-fatal: view state is a convenience.
  }
}

interface ViewerContextValue {
  currentIndex: number;
  setCurrentIndex: (i: number) => void;
  next: () => void;
  prev: () => void;
  first: () => void;
  last: () => void;
  drawerOpen: boolean;
  setDrawerOpen: (v: boolean) => void;
  drawerHeight: number;
  setDrawerHeight: (px: number) => void;
  activeTab: DrawerTab;
  setActiveTab: (t: DrawerTab) => void;
}

const ViewerContext = createContext<ViewerContextValue | null>(null);

export const ViewerProvider: React.FC<{ slideCount: number; children: React.ReactNode }> = ({
  slideCount,
  children,
}) => {
  const initial = readViewState();
  const [currentIndex, setIndex] = useState(0);
  const [drawerOpen, setOpen] = useState(initial.drawerOpen);
  const [drawerHeight, setHeight] = useState(initial.drawerHeight);
  const [activeTab, setTab] = useState<DrawerTab>(initial.activeTab);

  useEffect(() => {
    writeViewState({ drawerOpen, drawerHeight, activeTab });
  }, [drawerOpen, drawerHeight, activeTab]);

  // Keep the index addressable when the deck shrinks (delete/reorder).
  useEffect(() => {
    if (slideCount === 0) {
      setIndex(0);
    } else if (currentIndex > slideCount - 1) {
      setIndex(slideCount - 1);
    }
  }, [slideCount, currentIndex]);

  const clamp = useCallback(
    (i: number) => Math.min(Math.max(i, 0), Math.max(slideCount - 1, 0)),
    [slideCount],
  );

  const setCurrentIndex = useCallback((i: number) => setIndex(clamp(i)), [clamp]);

  const value = useMemo<ViewerContextValue>(
    () => ({
      currentIndex,
      setCurrentIndex,
      next: () => setIndex(i => clamp(i + 1)),
      prev: () => setIndex(i => clamp(i - 1)),
      first: () => setIndex(0),
      last: () => setIndex(clamp(slideCount - 1)),
      drawerOpen,
      setDrawerOpen: setOpen,
      drawerHeight,
      setDrawerHeight: (px: number) => setHeight(Math.min(Math.max(px, MIN_HEIGHT), MAX_HEIGHT)),
      activeTab,
      setActiveTab: setTab,
    }),
    [currentIndex, setCurrentIndex, clamp, slideCount, drawerOpen, drawerHeight, activeTab],
  );

  return <ViewerContext.Provider value={value}>{children}</ViewerContext.Provider>;
};

export function useViewer(): ViewerContextValue {
  const ctx = useContext(ViewerContext);
  if (!ctx) throw new Error('useViewer must be used within a ViewerProvider');
  return ctx;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/contexts/ViewerContext.tsx
git commit -m "feat(viewer): add ViewerContext for current slide and drawer state"
```

---

## Task 4: SlideStage

**Files:**
- Create: `frontend/src/components/SlideViewer/SlideStage.tsx`

**Interfaces:**
- Consumes: `useViewer()` (Task 3); `Slide` from `src/types/slide.ts`.
- Produces: `SlideStage` with props `{ slides: Slide[]; css: string; externalScripts: string[] }`.

Spec §3 and §4.1: one slide, aspect-preserving, arrow controls, **wheel over the stage pages one slide per gesture**.

Slide rendering must reuse the existing sandboxed-iframe approach. Read `frontend/src/components/SlidePanel/SlideTile.tsx` first and mirror how it builds the iframe document (CSP, `deck.css`, `external_scripts`, per-slide `scripts`). Do not invent a new rendering path.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/SlideViewer/SlideStage.tsx`:

```tsx
import React, { useCallback, useRef } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/ui/button';
import type { Slide } from '../../types/slide';
import { useViewer } from '../../contexts/ViewerContext';

interface SlideStageProps {
  slides: Slide[];
  css: string;
  externalScripts: string[];
}

/** One discrete slide change per gesture, so a trackpad flick cannot skip slides (spec §4.1). */
const WHEEL_THRESHOLD = 40;
const WHEEL_COOLDOWN_MS = 350;

export const SlideStage: React.FC<SlideStageProps> = ({ slides, css, externalScripts }) => {
  const { currentIndex, next, prev } = useViewer();
  const lastWheelRef = useRef(0);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (Math.abs(e.deltaY) < WHEEL_THRESHOLD) return;
      const now = Date.now();
      if (now - lastWheelRef.current < WHEEL_COOLDOWN_MS) return;
      lastWheelRef.current = now;
      if (e.deltaY > 0) next();
      else prev();
    },
    [next, prev],
  );

  const slide = slides[currentIndex];

  if (!slide) {
    return (
      <div
        data-testid="slide-stage-empty"
        className="flex flex-1 items-center justify-center text-sm text-muted-foreground"
      >
        No slides yet — generate a deck to get started.
      </div>
    );
  }

  const srcDoc = `<!DOCTYPE html>
<html><head><meta charset="utf-8">
${externalScripts.map(src => `<script src="${src}"></script>`).join('\n')}
<style>html,body{margin:0;padding:0;}${css}</style>
</head><body>${slide.html}
<script>try{${slide.scripts || ''}}catch(e){console.debug(e)}</script>
</body></html>`;

  return (
    <div
      data-testid="slide-stage"
      className="relative flex flex-1 items-center justify-center overflow-hidden bg-muted/30 p-4"
      onWheel={handleWheel}
    >
      <Button
        variant="outline"
        size="icon"
        aria-label="Previous slide"
        data-testid="stage-prev"
        onClick={prev}
        disabled={currentIndex === 0}
        className="absolute left-2 z-10"
      >
        <ChevronLeft className="size-4" />
      </Button>

      <div className="aspect-video h-full max-h-full w-full max-w-full bg-white shadow-lg">
        <iframe
          key={slide.slide_id}
          title={`Slide ${currentIndex + 1}`}
          data-testid="slide-stage-frame"
          sandbox="allow-scripts"
          srcDoc={srcDoc}
          className="size-full border-0"
        />
      </div>

      <Button
        variant="outline"
        size="icon"
        aria-label="Next slide"
        data-testid="stage-next"
        onClick={next}
        disabled={currentIndex >= slides.length - 1}
        className="absolute right-2 z-10"
      >
        <ChevronRight className="size-4" />
      </Button>

      <div
        data-testid="stage-position"
        className="absolute bottom-2 rounded bg-background/80 px-2 py-1 text-xs text-muted-foreground"
      >
        {currentIndex + 1} / {slides.length}
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Reconcile with SlideTile's render approach**

Run: `grep -n "srcDoc\|sandbox\|iframe\|CSP\|Content-Security" frontend/src/components/SlidePanel/SlideTile.tsx`

If `SlideTile` injects a CSP meta tag or additional sandbox flags, copy them into `srcDoc` above so the stage matches the established security posture. Do not weaken it.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SlideViewer/SlideStage.tsx
git commit -m "feat(viewer): add single-slide stage with arrow and wheel paging"
```

---

## Task 5: ThumbnailRibbon

**Files:**
- Create: `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx`

**Interfaces:**
- Consumes: `useViewer()` (Task 3); `SlideFinding` (Task 1); `Slide`, `SlideDeck` types.
- Produces: `ThumbnailRibbon` with props `{ slideDeck: SlideDeck; unseenSlideIndices: Set<number>; onReorder: (from: number, to: number) => void }`.

Spec §4: vertical, click-to-select, unseen dot (boolean not count), drag-reorder via existing `@dnd-kit` wiring, and **auto-reveal the current slide**. Spec §4.1: **wheel over the ribbon scrolls thumbnails only** — it must NOT change the slide, so do not attach a paging wheel handler here.

Read `frontend/src/components/SlidePanel/SlidePanel.tsx` for the established `@dnd-kit` setup (`DndContext`, `SortableContext`, `verticalListSortingStrategy`, `useSortable`) and mirror it. Colours: adapt `SlideSelection.css` (blue `#3b82f6` border, subtle tint, shadow) per spec §4 — adapt, do not reuse its grid tile layout.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx`:

```tsx
import React, { useEffect, useRef } from 'react';
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { SlideDeck } from '../../types/slide';
import { useViewer } from '../../contexts/ViewerContext';

interface ThumbnailRibbonProps {
  slideDeck: SlideDeck;
  unseenSlideIndices: Set<number>;
  onReorder: (from: number, to: number) => void;
}

interface ThumbProps {
  id: string;
  index: number;
  isCurrent: boolean;
  hasUnseen: boolean;
  onSelect: (index: number) => void;
}

const Thumb: React.FC<ThumbProps> = ({ id, index, isCurrent, hasUnseen, onSelect }) => {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const ref = useRef<HTMLButtonElement | null>(null);

  // Auto-reveal: whenever this becomes current, scroll it into view (spec §4).
  useEffect(() => {
    if (isCurrent) ref.current?.scrollIntoView({ block: 'nearest' });
  }, [isCurrent]);

  return (
    <button
      ref={node => { setNodeRef(node); ref.current = node; }}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...attributes}
      {...listeners}
      type="button"
      data-testid={`ribbon-thumb-${index}`}
      data-current={isCurrent ? 'true' : 'false'}
      aria-current={isCurrent ? 'true' : undefined}
      onClick={() => onSelect(index)}
      className={[
        'relative flex w-full items-center gap-2 rounded-md border p-2 text-left text-xs transition',
        isCurrent
          ? 'border-[#3b82f6] bg-[#3b82f6]/10 shadow-sm ring-1 ring-[#3b82f6]'
          : 'border-border hover:bg-muted/50',
      ].join(' ')}
    >
      <span className="w-5 shrink-0 text-muted-foreground">{index + 1}</span>
      <span className="truncate">Slide {index + 1}</span>
      {hasUnseen && (
        <span
          data-testid={`ribbon-unseen-${index}`}
          aria-label="Unread AI feedback"
          className="ml-auto size-2 shrink-0 rounded-full bg-amber-500"
        />
      )}
    </button>
  );
};

export const ThumbnailRibbon: React.FC<ThumbnailRibbonProps> = ({
  slideDeck, unseenSlideIndices, onReorder,
}) => {
  const { currentIndex, setCurrentIndex } = useViewer();
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const ids = slideDeck.slides.map(s => s.slide_id);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from !== -1 && to !== -1) onReorder(from, to);
  };

  return (
    // No wheel handler: scrolling here browses thumbnails only (spec §4.1).
    <div
      data-testid="thumbnail-ribbon"
      className="flex h-full w-40 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border bg-card p-2"
    >
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {slideDeck.slides.map((slide, index) => (
            <Thumb
              key={slide.slide_id}
              id={slide.slide_id}
              index={index}
              isCurrent={index === currentIndex}
              hasUnseen={unseenSlideIndices.has(index)}
              onSelect={setCurrentIndex}
            />
          ))}
        </SortableContext>
      </DndContext>
    </div>
  );
};
```

- [ ] **Step 2: Reconcile with SlidePanel's dnd-kit usage**

Run: `grep -n "DndContext\|SortableContext\|useSensor\|verticalListSortingStrategy\|restrictTo" frontend/src/components/SlidePanel/SlidePanel.tsx`

Align sensor config and any modifiers with what `SlidePanel` already uses, so reorder behaves identically.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SlideViewer/ThumbnailRibbon.tsx
git commit -m "feat(viewer): add vertical thumbnail ribbon with unseen indicator"
```

---

## Task 6: FeedbackDrawer

**Files:**
- Create: `frontend/src/components/SlideViewer/FeedbackDrawer.tsx`

**Interfaces:**
- Consumes: `useViewer()` (Task 3); `SlideFinding`, `DrawerCallbacks` (Task 1).
- Produces: `FeedbackDrawer` with props `{ findings: SlideFinding[]; callbacks: DrawerCallbacks; hasUnseen: boolean }`. `findings` are already filtered to the current slide by the parent, and `hasUnseen` is computed by the parent (Task 7) — the drawer does not read seen-state itself.

Spec §5: tabbed shell with one tab, stays-on-empty with a useful empty state, highlight-not-count, resizable + persisted height, three actions per finding.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/SlideViewer/FeedbackDrawer.tsx`:

```tsx
import React, { useCallback, useRef } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/ui/button';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import { useViewer } from '../../contexts/ViewerContext';

interface FeedbackDrawerProps {
  findings: SlideFinding[];        // already scoped to the current slide
  callbacks: DrawerCallbacks;
  hasUnseen: boolean;
}

const CATEGORY_LABEL: Record<SlideFinding['category'], string> = {
  content: 'Content',
  design: 'Design',
  narrative: 'Narrative',
};

export const FeedbackDrawer: React.FC<FeedbackDrawerProps> = ({ findings, callbacks, hasUnseen }) => {
  const { drawerOpen, setDrawerOpen, drawerHeight, setDrawerHeight, activeTab, setActiveTab } = useViewer();
  const dragStart = useRef<{ y: number; h: number } | null>(null);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragStart.current = { y: e.clientY, h: drawerHeight };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [drawerHeight]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragStart.current) return;
    // Drawer sits below the stage, so dragging up (negative dy) grows it.
    setDrawerHeight(dragStart.current.h + (dragStart.current.y - e.clientY));
  }, [setDrawerHeight]);

  const onPointerUp = useCallback(() => { dragStart.current = null; }, []);

  return (
    <div data-testid="feedback-drawer" className="flex flex-col border-t border-border bg-card">
      {drawerOpen && (
        <div
          data-testid="drawer-resize-handle"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className="h-1 cursor-row-resize bg-border hover:bg-primary/40"
        />
      )}

      <div className="flex items-center gap-1 px-2 py-1">
        {/* Tabbed shell: one tab today; 'notes' is additive (spec §5.1). */}
        <button
          type="button"
          data-testid="drawer-tab-feedback"
          data-active={activeTab === 'feedback' ? 'true' : 'false'}
          onClick={() => setActiveTab('feedback')}
          className={[
            'relative rounded-t px-3 py-1.5 text-xs font-medium',
            activeTab === 'feedback' ? 'bg-muted text-foreground' : 'text-muted-foreground',
          ].join(' ')}
        >
          AI feedback
          {hasUnseen && (
            <span
              data-testid="drawer-tab-unseen"
              aria-label="Unread AI feedback"
              className="ml-2 inline-block size-2 rounded-full bg-amber-500 align-middle"
            />
          )}
        </button>

        <Button
          variant="ghost"
          size="icon"
          aria-label={drawerOpen ? 'Collapse feedback drawer' : 'Expand feedback drawer'}
          data-testid="drawer-toggle"
          onClick={() => setDrawerOpen(!drawerOpen)}
          className="ml-auto size-7"
        >
          {drawerOpen ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </Button>
      </div>

      {drawerOpen && (
        <div
          data-testid="drawer-body"
          style={{ height: drawerHeight }}
          className="overflow-y-auto px-3 pb-3"
        >
          {findings.length === 0 ? (
            <p data-testid="drawer-empty" className="py-4 text-xs text-muted-foreground">
              No feedback for this slide.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {findings.map(f => (
                <li
                  key={f.id}
                  data-testid={`finding-${f.id}`}
                  className="rounded-md border border-border p-2"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {CATEGORY_LABEL[f.category]}
                    </span>
                  </div>
                  <p className="mb-2 text-xs text-foreground">{f.message}</p>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" data-testid={`finding-apply-${f.id}`}
                      onClick={() => callbacks.onApplyFinding(f.id)}>Apply</Button>
                    <Button size="sm" variant="ghost" data-testid={`finding-dismiss-${f.id}`}
                      onClick={() => callbacks.onDismissFinding(f.id)}>Dismiss</Button>
                    <Button size="sm" variant="ghost" data-testid={`finding-discuss-${f.id}`}
                      onClick={() => callbacks.onDiscussFinding(f.id)}>Discuss</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SlideViewer/FeedbackDrawer.tsx
git commit -m "feat(viewer): add tabbed feedback drawer with per-finding actions"
```

---

## Task 7: SlideViewer composition + keyboard

**Files:**
- Create: `frontend/src/components/SlideViewer/SlideViewer.tsx`
- Test: `frontend/tests/e2e/slide-viewer.spec.ts` (append)

**Interfaces:**
- Consumes: `SlideStage` (4), `ThumbnailRibbon` (5), `FeedbackDrawer` (6), `ViewerProvider`/`useViewer` (3), `seenState` (2), `SlideFinding`/`DrawerCallbacks` (1).
- Produces: `SlideViewer` with props `{ slideDeck: SlideDeck | null; deckKey: string; findings: SlideFinding[]; callbacks: DrawerCallbacks; onReorder: (from: number, to: number) => void }`.

Spec §6: `→`/`↓`/`PageDown` next; `←`/`↑`/`PageUp` prev; `Home`/`End` first/last. **The focus guard is the critical requirement** — paging must not fire when focus is in an input, textarea, contentEditable, or the chat composer. Guard on the active element (not propagation), because workstream 8 adds editable regions to the stage.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/SlideViewer/SlideViewer.tsx`:

```tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import { ViewerProvider, useViewer } from '../../contexts/ViewerContext';
import { SlideStage } from './SlideStage';
import { ThumbnailRibbon } from './ThumbnailRibbon';
import { FeedbackDrawer } from './FeedbackDrawer';
import { loadSeen, markSeen } from './seenState';

interface SlideViewerProps {
  slideDeck: SlideDeck | null;
  deckKey: string;                 // scopes seen-state; use the session id
  findings: SlideFinding[];
  callbacks: DrawerCallbacks;
  onReorder: (from: number, to: number) => void;
}

/**
 * True when focus is somewhere that consumes arrow keys, so paging must not fire.
 * Checked on the active element rather than relying on stopPropagation, so future
 * editable regions on the stage (workstream 8) are covered automatically.
 */
function isTypingTarget(el: Element | null): boolean {
  if (!el) return false;
  const node = el as HTMLElement;
  if (node.isContentEditable) return true;
  const tag = node.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

const ViewerBody: React.FC<Omit<SlideViewerProps, 'slideDeck'> & { slideDeck: SlideDeck }> = ({
  slideDeck, deckKey, findings, callbacks, onReorder,
}) => {
  const { currentIndex, next, prev, first, last, activeTab, drawerOpen } = useViewer();
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen(deckKey));
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { setSeen(loadSeen(deckKey)); }, [deckKey]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(document.activeElement)) return;
      switch (e.key) {
        case 'ArrowRight': case 'ArrowDown': case 'PageDown': e.preventDefault(); next(); break;
        case 'ArrowLeft':  case 'ArrowUp':   case 'PageUp':   e.preventDefault(); prev(); break;
        case 'Home': e.preventDefault(); first(); break;
        case 'End':  e.preventDefault(); last();  break;
        // Escape returns focus from the drawer to the stage (spec §6).
        case 'Escape':
          if (stageRef.current?.contains(document.activeElement) === false) {
            stageRef.current?.focus();
          }
          break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [next, prev, first, last]);

  const visible = useMemo(
    () => findings.filter(f => !dismissed.has(f.id)),
    [findings, dismissed],
  );

  const currentFindings = useMemo(
    () => visible.filter(f => f.slideIndex === currentIndex),
    [visible, currentIndex],
  );

  const unseenSlideIndices = useMemo(() => {
    const set = new Set<number>();
    for (const f of visible) if (!seen.has(f.id)) set.add(f.slideIndex);
    return set;
  }, [visible, seen]);

  // Viewing the feedback tab for a slide marks that slide's findings read (spec §5.1.1).
  useEffect(() => {
    if (!drawerOpen || activeTab !== 'feedback') return;
    const unread = currentFindings.filter(f => !seen.has(f.id)).map(f => f.id);
    if (unread.length === 0) return;
    markSeen(deckKey, unread);
    setSeen(prev => new Set([...prev, ...unread]));
  }, [drawerOpen, activeTab, currentFindings, seen, deckKey]);

  const handleDismiss = useCallback((findingId: string) => {
    setDismissed(prev => new Set(prev).add(findingId));
    markSeen(deckKey, [findingId]);
    setSeen(prev => new Set(prev).add(findingId));
    callbacks.onDismissFinding(findingId);
  }, [callbacks, deckKey]);

  return (
    <div data-testid="slide-viewer" className="flex h-full min-h-0 flex-1">
      <ThumbnailRibbon
        slideDeck={slideDeck}
        unseenSlideIndices={unseenSlideIndices}
        onReorder={onReorder}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        {/* tabIndex makes the stage a focus target so Escape can return focus here. */}
        <div ref={stageRef} tabIndex={-1} className="flex min-h-0 flex-1 outline-none">
          <SlideStage
            slides={slideDeck.slides}
            css={slideDeck.css}
            externalScripts={slideDeck.external_scripts}
          />
        </div>
        <FeedbackDrawer
          findings={currentFindings}
          hasUnseen={currentFindings.some(f => !seen.has(f.id))}
          callbacks={{ ...callbacks, onDismissFinding: handleDismiss }}
        />
      </div>
    </div>
  );
};

export const SlideViewer: React.FC<SlideViewerProps> = ({ slideDeck, ...rest }) => {
  if (!slideDeck || slideDeck.slides.length === 0) {
    return (
      <div
        data-testid="slide-viewer-empty"
        className="flex flex-1 items-center justify-center text-sm text-muted-foreground"
      >
        No slides yet — generate a deck to get started.
      </div>
    );
  }
  return (
    <ViewerProvider slideCount={slideDeck.slides.length}>
      <ViewerBody slideDeck={slideDeck} {...rest} />
    </ViewerProvider>
  );
};
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SlideViewer/SlideViewer.tsx
git commit -m "feat(viewer): compose stage, ribbon and drawer with keyboard paging"
```

---

## Task 8: Wire into AppLayout and retire checkbox selection

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx:54,69,862-879`
- Delete: `frontend/src/components/SlidePanel/SelectionRibbon.tsx`
- Delete: `frontend/src/components/SlidePanel/SlideSelection.tsx`
- Delete: `frontend/src/components/SlidePanel/SlideSelection.css`
- Modify: `frontend/src/utils/slideReplacements.ts:1` (remove `isContiguous`)
- Modify: `frontend/src/contexts/SelectionContext.tsx` (remove provider from tree)

**Interfaces:**
- Consumes: `SlideViewer` (Task 7).
- Produces: an app rendering the new viewer at `/sessions/:id/edit`.

Spec §4 "Retired": checkbox selection and the `MessageSquare` button go. `isContiguous` is defined at `utils/slideReplacements.ts:1` with `SlideSelection.tsx:32` as its only consumer, so both go.

**Findings are supplied as fixture data for now** — no endpoint exists. Wire `findings={[]}` in app code and let tests inject via `window.__TELLR_TEST_FINDINGS__` (Step 3), so no fake data ships to users.

- [ ] **Step 1: Read the current wiring**

Run: `sed -n '840,900p' frontend/src/components/Layout/AppLayout.tsx`

Note how `SelectionRibbon` and `SlidePanel` are laid out, which props each receives, and how `slidePanelRef`/`scrollTarget` are used.

- [ ] **Step 2: Replace the ribbon + panel with SlideViewer**

In `AppLayout.tsx`:
1. Add `import { SlideViewer } from '../SlideViewer/SlideViewer';` and remove the `SelectionRibbon` import (line 6).
2. Delete the `scrollTarget` state (line 54) and every reference to it, including the `scrollToSlide` prop (line 879).
3. Replace the `<SelectionRibbon .../>` + `<SlidePanel .../>` block (≈862-879) with:

```tsx
<SlideViewer
  slideDeck={slideDeck}
  deckKey={sessionId ?? 'no-session'}
  findings={testFindings}
  callbacks={{
    onApplyFinding: (id) => console.info('[viewer] apply finding', id),
    onDismissFinding: (id) => console.info('[viewer] dismiss finding', id),
    onDiscussFinding: (id) => console.info('[viewer] discuss finding', id),
  }}
  onReorder={handleReorderSlides}
/>
```

4. If no `handleReorderSlides(from, to)` exists on `AppLayout`, lift the reorder handler out of `SlidePanel.tsx` (it calls `api.reorderSlides`) and reuse it verbatim — do not rewrite the API call.

- [ ] **Step 3: Add the test-only findings hook**

In `AppLayout.tsx`, above the return:

```tsx
// Findings have no producing endpoint yet (PRD workstream 5). Tests inject
// fixtures on window; production renders an empty list.
const [testFindings, setTestFindings] = useState<SlideFinding[]>([]);
useEffect(() => {
  const injected = (window as unknown as { __TELLR_TEST_FINDINGS__?: SlideFinding[] })
    .__TELLR_TEST_FINDINGS__;
  if (injected) setTestFindings(injected);
}, []);
```

Add `import type { SlideFinding } from '../../types/finding';`.

- [ ] **Step 4: Remove SelectionContext from the app tree**

Run: `grep -rn "SelectionProvider\|useSelection" frontend/src/ | grep -v node_modules`

Remove `SelectionProvider` from wherever it wraps the tree, and delete each `useSelection()` consumer's selection logic. `ChatPanel.tsx` builds `slide_context` from selection (spec §6.1 retires this) — pass `undefined` for `slideContext` so chat still sends messages. Do **not** delete `SelectionContext.tsx` if any consumer still imports it; finish the consumers first, then delete the file.

- [ ] **Step 5: Delete the retired files**

```bash
cd frontend
rm src/components/SlidePanel/SelectionRibbon.tsx
rm src/components/SlidePanel/SlideSelection.tsx
rm src/components/SlidePanel/SlideSelection.css
```

Then remove `isContiguous` from `src/utils/slideReplacements.ts` (verify no other consumer first: `grep -rn "isContiguous" src/`).

- [ ] **Step 6: Make the nav and chat panels collapsible**

Spec §2 requires **both** left panels (nav/options and chat) to be collapsible with
persisted state.

First check whether either already collapses: `grep -n "collaps\|isOpen\|sidebar" frontend/src/components/Layout/AppLayout.tsx frontend/src/components/Layout/app-sidebar.tsx`

- If collapse behaviour exists (e.g. a sidebar primitive), reuse it and only add
  persistence if missing.
- If not, add a persisted boolean per panel in `AppLayout`, following the
  `localStorage` read/write pattern from `ViewerContext`:

```tsx
const PANEL_STATE_KEY = 'tellr-panel-collapsed';

const [collapsed, setCollapsed] = useState<{ nav: boolean; chat: boolean }>(() => {
  try {
    const raw = localStorage.getItem(PANEL_STATE_KEY);
    return raw ? { nav: false, chat: false, ...JSON.parse(raw) } : { nav: false, chat: false };
  } catch {
    return { nav: false, chat: false };
  }
});

useEffect(() => {
  try { localStorage.setItem(PANEL_STATE_KEY, JSON.stringify(collapsed)); } catch { /* non-fatal */ }
}, [collapsed]);
```

Render a toggle per panel with `data-testid="toggle-nav-panel"` and
`data-testid="toggle-chat-panel"`, and collapse by rendering a narrow strip (or
`hidden`) rather than unmounting the chat panel — unmounting would drop chat state.

- [ ] **Step 7: Typecheck and lint until clean**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS. Fix every dangling import the deletions caused.

- [ ] **Step 8: Write the viewer behaviour tests**

Append to `frontend/tests/e2e/slide-viewer.spec.ts`:

```typescript
import { mockFindings } from '../fixtures/findings';

test.describe('flip-through viewer', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await page.addInitScript(
      findings => { (window as any).__TELLR_TEST_FINDINGS__ = findings; },
      mockFindings,
    );
  });

  // Replace with the helper this repo already uses to reach a deck-loaded session.
  const openDeck = async (page: import('@playwright/test').Page) => {
    await page.goto('/sessions/test-session-id/edit');
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
  };

  test('shows exactly one slide and pages with arrow controls', async ({ page }) => {
    await openDeck(page);
    await expect(page.getByTestId('slide-stage-frame')).toHaveCount(1);
    await expect(page.getByTestId('stage-position')).toContainText('1 /');

    await page.getByTestId('stage-next').click();
    await expect(page.getByTestId('stage-position')).toContainText('2 /');
    await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
  });

  test('keyboard pages slides but not while typing in chat', async ({ page }) => {
    await openDeck(page);
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('stage-position')).toContainText('2 /');

    const chat = page.locator('textarea, input[type="text"]').first();
    await chat.click();
    await chat.press('ArrowRight');
    await expect(page.getByTestId('stage-position')).toContainText('2 /');  // unchanged
  });

  test('wheel over the ribbon does not change the slide; wheel over the stage does', async ({ page }) => {
    await openDeck(page);
    await page.getByTestId('thumbnail-ribbon').hover();
    await page.mouse.wheel(0, 300);
    await expect(page.getByTestId('stage-position')).toContainText('1 /');

    await page.getByTestId('slide-stage').hover();
    await page.mouse.wheel(0, 300);
    await expect(page.getByTestId('stage-position')).toContainText('2 /');
  });

  test('drawer shows findings for the current slide and an empty state otherwise', async ({ page }) => {
    await openDeck(page);
    await expect(page.getByTestId('drawer-empty')).toBeVisible();   // slide 1 has none

    await page.getByTestId('ribbon-thumb-1').click();
    await expect(page.getByTestId('finding-f1')).toBeVisible();
    await expect(page.getByTestId('finding-f2')).toBeVisible();
  });

  test('unseen indicator appears then clears once viewed', async ({ page }) => {
    await openDeck(page);
    await expect(page.getByTestId('ribbon-unseen-1')).toBeVisible();

    await page.getByTestId('ribbon-thumb-1').click();
    await expect(page.getByTestId('ribbon-unseen-1')).toBeHidden();

    await page.reload();                                   // persists across reload
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('ribbon-unseen-1')).toBeHidden();
  });

  test('dismiss removes a finding; drawer height survives reload', async ({ page }) => {
    await openDeck(page);
    await page.getByTestId('ribbon-thumb-1').click();
    await page.getByTestId('finding-dismiss-f1').click();
    await expect(page.getByTestId('finding-f1')).toHaveCount(0);

    await page.getByTestId('drawer-toggle').click();       // collapse
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('drawer-body')).toHaveCount(0);   // still collapsed
  });

  test('no checkbox selection remains', async ({ page }) => {
    await openDeck(page);
    await expect(page.locator('.slide-checkbox-input')).toHaveCount(0);
    await expect(page.getByText('Select consecutive slides')).toHaveCount(0);
  });

  test('Home and End jump to first and last slide', async ({ page }) => {
    await openDeck(page);
    await page.keyboard.press('End');
    await expect(page.getByTestId('stage-position')).toContainText('/ ');
    const last = await page.getByTestId('stage-position').textContent();
    expect(last?.split('/')[0].trim()).toBe(last?.split('/')[1].trim());  // n / n

    await page.keyboard.press('Home');
    await expect(page.getByTestId('stage-position')).toContainText('1 /');
  });

  test('the current slide is revealed in the ribbon after paging far', async ({ page }) => {
    await openDeck(page);
    await page.keyboard.press('End');
    // Auto-reveal (spec §4): the last thumbnail must be scrolled into view.
    const lastThumb = page.getByTestId('ribbon-thumb-13');   // original_deck.html has 14 slides
    await expect(lastThumb).toHaveAttribute('data-current', 'true');
    await expect(lastThumb).toBeInViewport();
  });

  test('nav and chat panels collapse and the state survives reload', async ({ page }) => {
    await openDeck(page);
    await page.getByTestId('toggle-chat-panel').click();
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('toggle-chat-panel')).toBeVisible();  // toggle still reachable
  });
});
```

- [ ] **Step 9: Run the tests and fix failures**

Run: `cd frontend && npx playwright test tests/e2e/slide-viewer.spec.ts --project=chromium`
Expected: PASS.

If `openDeck` cannot reach a loaded deck, read `frontend/tests/helpers/session-helpers.ts` and `frontend/tests/e2e/export-ui.spec.ts` for the established way to open a session with mocked slides, and use that instead. Do not weaken assertions to make tests pass.

- [ ] **Step 10: Run the full suite for regressions**

Run: `cd frontend && npx playwright test --project=chromium`
Expected: PASS. Specs asserting the old scrolling list or checkbox selection will fail — update them to the new model (that is expected work, not a reason to revert). Note any you change.

- [ ] **Step 11: Commit**

```bash
git add -A frontend/
git commit -m "feat(viewer): wire flip-through viewer into AppLayout, retire checkbox selection"
```

---

## Task 9: Technical documentation

**Files:**
- Create: `docs/technical/slide-viewer.md`
- Modify: `docs/technical/frontend-overview.md` (6 locations)
- Modify: `README.md:131-142`
- Modify: `docs-site/sidebars.js:49`

**Interfaces:**
- Consumes: the shipped behaviour from Tasks 1-8.
- Produces: documentation. No code.

Spec §9. Follow `docs/technical/technical-doc-template.md`: lead with outcomes, tables for mappings, call out invariants, real paths in backticks.

- [ ] **Step 1: Read the template**

Run: `cat docs/technical/technical-doc-template.md`

- [ ] **Step 2: Write `docs/technical/slide-viewer.md`**

Cover, per spec §9.1:
- **One-line summary + architecture snapshot:** stage / ribbon / drawer and their relation to `AppLayout` and the chat panel.
- **Scroll semantics (invariant):** wheel over the ribbon browses thumbnails and does **not** change the slide; wheel over the stage pages one slide per gesture; the current slide is always revealed in the ribbon. State this as an invariant — it is non-obvious and will be broken by future edits otherwise.
- **Keyboard model and the focus guard:** the key map, and *why* the guard tests `document.activeElement` rather than relying on propagation (workstream 8 adds editable regions to the stage).
- **Drawer state:** sticky tab, stays-on-empty, persisted open/height, and the tabbed-shell-with-one-tab decision plus its reason (speaker notes land later).
- **Seen-state:** `localStorage`, per-user by construction, deck+finding key scoping, `MAX_DECKS` growth bound, and the recorded trade-off that it does not cross browsers or devices.
- **Data contracts:** the `SlideFinding` / `DrawerCallbacks` interfaces, and that findings arrive as props with the producer deferred to PRD workstream 5 (so Apply/Discuss are currently stubs that log).
- **Component table:** file → responsibility.
- **Extension guidance:** how to add a drawer tab; how the inline WYSIWYG editor (workstream 8) is expected to layer onto the stage.

- [ ] **Step 3: Correct `frontend-overview.md`**

Each row below is currently stated as fact and is now false. Fix all six:

| Location | Currently says | Correct to |
|---|---|---|
| `:48-50` | "Click slide preview – scrolls the main SlidePanel to that slide"; "Click checkbox – toggles slide selection for chat context (contiguous only)"; `SlidePanel` "Accepts `scrollToSlide` prop" | Ribbon click *selects* the slide; the stage renders one slide; no checkboxes; no `scrollToSlide` |
| `:54` | "`scrollTarget: { index, key } \| null` – coordinates ribbon-to-panel navigation" | Removed; current-slide index lives in `ViewerContext` |
| `:110` | "### 3. Selection Context" — `selectedIndices`, "Enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`" | Retired. Describe `ViewerContext` instead; note conversational targeting arrives in PRD workstream 7 |
| `:299-309` | Component rows for `SlidePanel`, `SlideTile`, `SelectionRibbon`+`SlideSelection` | Rows for `SlideViewer`, `SlideStage`, `ThumbnailRibbon`, `FeedbackDrawer`; drop deleted files |
| `:368-376` | "### Selecting Slides and Navigation"; "`SelectionContext` cleared after fresh slides arrive"; "Ribbon navigation: … scrolls `SlidePanel` … via `scrollToSlide`" | Rewrite for the new model |
| `:509-511` | "4. Navigate slides – Click slide preview in ribbon to scroll main panel"; "6. Refine slides – Use checkbox in ribbon to select contiguous slides" | Rewrite; no checkbox step |

Then remove the contiguous-selection invariant where it is presented as a rule that must not break — including `docs/technical/technical-doc-template.md:44`, which uses "contiguous selection" as its example invariant.

- [ ] **Step 4: Index the new doc**

1. `README.md` — add to the table at `:131-142`:
   `| [Slide Viewer](docs/technical/slide-viewer.md) | Flip-through stage, thumbnail ribbon, AI feedback drawer |`
2. `docs-site/sidebars.js` — add `'technical/slide-viewer',` alongside the existing `technical/*` entries (near `:49`). Without an entry it will not appear on the published site.
3. Cross-link `slide-viewer.md` ↔ `frontend-overview.md`, and reference `presentation-mode.md` as the adjacent single-slide surface.

- [ ] **Step 5: Check the user guide for stale instructions**

Run: `grep -rln "checkbox\|scroll through\|consecutive" docs/user-guide/`

Flag anything describing the old scrolling list or checkbox selection in your task report. Update prose you can fix confidently; do not fabricate replacement screenshots.

- [ ] **Step 6: Verify no stale references remain**

Run:
```bash
grep -n "checkbox\|contiguous\|scrollToSlide\|scrollTarget" docs/technical/frontend-overview.md
grep -rn "SelectionRibbon\|SlideSelection" docs/technical/ README.md
```
Expected: no hits describing current behaviour.

- [ ] **Step 7: Commit**

```bash
git add docs/ README.md docs-site/sidebars.js
git commit -m "docs: document the flip-through viewer and correct stale frontend docs"
```

---

## Task 10: Final verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything.
- Produces: a verified branch.

- [ ] **Step 1: Confirm the front-end-only constraint**

Run: `git diff --stat main...HEAD -- src/`
Expected: **empty**. Any output violates a Global Constraint — stop and report.

- [ ] **Step 2: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS both.

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 4: Full test suite**

Run: `cd frontend && npx playwright test --project=chromium`
Expected: PASS. Report any spec you modified and why.

- [ ] **Step 5: Walk the spec's verification checklist**

Open `docs/superpowers/specs/2026-08-03-flip-through-viewer-design.md` §10 and confirm each bullet, including:
- one slide shown; paging via ribbon, buttons, keyboard, stage scroll;
- ribbon wheel does not change the stage; stage wheel does, one slide per gesture;
- current slide always visible in the ribbon after a selection change;
- keyboard paging inert while typing in chat;
- empty state for slides with no findings;
- unseen highlight on ribbon and tab, clearing when viewed, persisting across reload, scoped per deck;
- drawer height and open/closed survive slide changes and reload;
- drag-reorder works from the ribbon;
- both left panels collapse and persist;
- Apply / Dismiss / Discuss fire callbacks (Dismiss updates the view);
- docs: `slide-viewer.md` exists; no stale checkbox/contiguous statements; README and sidebar updated.

Report any bullet that does not hold rather than silently leaving it.

- [ ] **Step 6: Report**

Summarise: tasks completed, specs modified and why, anything in §10 not satisfied, and any stale user-guide content found in Task 9 Step 5.

---

## Notes for the implementer

- **Collapsible nav and chat panels** (spec §2) are part of Task 8's `AppLayout` work. If `AppLayout` already has collapse behaviour for either, reuse it; if not, add a persisted boolean per panel following the `localStorage` pattern in `ViewerContext`.
- **`SlidePanel.tsx` is not deleted.** It still hosts per-slide CRUD, the HTML editor modal, and verification badges. Task 8 removes its use as the *scrolling list*; if a still-needed affordance (delete slide, open HTML editor, verification badge) has no home in the new viewer, surface it on the stage or the thumbnail and note the choice in your report. Do not silently drop functionality.
- **Do not build the `@slide` reference chip** — that is PRD workstream 7.
- **Do not fake builder behaviour** in the Apply/Discuss stubs. They log. A faked edit would make the tests test fiction.
