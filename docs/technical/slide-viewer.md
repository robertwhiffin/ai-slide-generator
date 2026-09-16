# Slide Viewer

A flip-through viewer that shows one slide at a time, a vertical thumbnail ribbon for navigation and reordering, and a collapsible drawer surfacing per-slide AI feedback. It replaces the former scrolling slide list and checkbox-based selection model.

---

## Stack & Entry Points

- **Components:** `frontend/src/components/SlideViewer/` (five files — see component table below)
- **Context:** `frontend/src/contexts/ViewerContext.tsx` — current-slide index, drawer open/height/tab
- **Types:** `frontend/src/types/finding.ts` — `SlideFinding`, `DrawerCallbacks`
- **Seen-state:** `frontend/src/components/SlideViewer/seenState.ts` — localStorage helpers
- **Slide rendering:** `frontend/src/services/slideDocument.ts` — shared `buildSlideDocument` (see Security Invariant below)
- **Export handlers:** `frontend/src/hooks/useDeckExport.ts` — extracted from `AppLayout`
- **Wired in:** `frontend/src/components/Layout/AppLayout.tsx`

---

## Architecture Snapshot

```
AppLayout
├── ChatPanel (32% width, collapsible)          ← chat history, slide generation
└── SlideViewer (flex-1)
    ├── ThumbnailRibbon (w-40, fixed left)       ← thumbnails, drag-reorder, unseen dots
    └── [stage column]
        ├── stage toolbar                        ← verify / edit HTML / delete (edit mode only)
        ├── SlideStage (flex-1)                  ← single slide iframe + prev/next arrows
        └── FeedbackDrawer (collapsible bottom)  ← AI findings tabbed shell
```

`SlideViewer` is the public surface. It wraps `ViewerProvider` around `ViewerBody`, which composes the above. An empty deck renders a placeholder instead of the full shell.

**Chat panel collapse:** `AppLayout` hides the chat panel by collapsing its width to `w-10` but does **not** unmount it, so conversation state is preserved. The collapse toggle is persisted to `localStorage` under key `tellr-panel-collapsed`.

**Presentation mode:** `SlideViewer` exposes a `SlideViewerHandle` ref. `AppLayout` holds this ref and triggers `openPresentationMode()` from the page header's Present button. The `PresentationMode` component is an overlay rendered by `ViewerBody` — it is not part of the viewer's layout column. See [Presentation Mode](presentation-mode.md) for full details.

---

## Key Concepts

### Scroll Semantics — INVARIANT

**These three rules must not be broken by future edits:**

1. Wheel over the **stage** pages exactly one slide per gesture (threshold 40 px, cooldown 350 ms — prevents trackpad flick from skipping multiple slides).
2. Wheel over the **thumbnail ribbon** scrolls the thumbnail list only and does **not** change the current slide. `ThumbnailRibbon` intentionally has no `onWheel` handler; adding one that calls `setCurrentIndex` would break this invariant.
3. The current slide is **always revealed** in the ribbon — when the current index changes, the corresponding thumbnail scrolls into view via `scrollIntoView({ block: 'nearest' })`.

### Keyboard Model and Focus Guard

Keyboard navigation is driven by a `window`-level `keydown` listener in `SlideViewer`:

| Key | Action |
|-----|--------|
| `ArrowRight` / `ArrowDown` / `PageDown` | Next slide |
| `ArrowLeft` / `ArrowUp` / `PageUp` | Previous slide |
| `Home` | First slide |
| `End` | Last slide |
| `Escape` | Return focus to the stage (from drawer or any other widget) |

**Focus guard — WHY it tests `document.activeElement`:** The guard calls `isTypingTarget(document.activeElement)` before paging. It does **not** rely on `stopPropagation`.

The reason matters: PRD workstream 8 will add inline WYSIWYG editable regions directly on the stage. If the guard used propagation-stopping, events inside those editable regions would stop propagating before reaching the window listener — which looks correct today but would silently break the moment workstream 8 adds an editable element that captures keydown for its own editing. The `document.activeElement` check covers any future editable element automatically, without any change to the guard.

**Iframe boundary (INVARIANT — the stage iframe must take neither pointer nor keyboard focus):**
Keydown inside the slide iframe fires in the iframe's own browsing context and
**never reaches the parent `window` listener**, and in the parent
`document.activeElement` becomes the `<iframe>` element itself.

That is why `SlideStage` renders the iframe with **both** `pointer-events: none` **and**
`tabIndex={-1}`. Both are required: `pointer-events` only blocks the mouse, so on its own a
Tab key still moves focus into the iframe and reintroduces the trap below. Without it
the iframe swallowed input in two user-visible ways: a single click on the slide
moved focus into the iframe and killed keyboard paging permanently (and `Escape`
could not recover it, because the iframe is *inside* `stageRef`, so the containment
check skipped the refocus), and wheel-over-the-stage paging did not work anywhere
except a ~16px margin around the slide, because the iframe covered the rest.
`ThumbnailRibbon` does the same for its preview iframes.

**Accepted trade-off:** because the slide cannot receive pointer events, users cannot select
or copy text out of a slide, follow in-slide links, or use Chart.js hover tooltips. Those all
worked when the slide was a scrolling tile. The stage is a pager, so this is judged an
acceptable loss for now — but it IS a loss, not a no-op, and it is the reason to be careful
about "just re-enabling pointer events" to fix a future interaction bug. If in-slide
interaction is wanted back, it needs a deliberate design that keeps paging and focus working
(see the workstream 8 notes below).

Note: the `sandbox="allow-scripts"` attribute does **not** make iframe content
non-interactive. `sandbox` governs capabilities such as form submission and
navigation; it does not disable input elements or stop them receiving focus. The
`pointer-events: none` + `tabIndex={-1}` pair is what keeps focus out, not `sandbox`.

### Security Invariant — `buildSlideDocument`

All slide iframes — both the full-size stage iframe and each ribbon thumbnail — are rendered via `buildSlideDocument` in `frontend/src/services/slideDocument.ts`. This function injects a Content-Security-Policy `<meta>` tag that blocks outbound network requests from LLM-generated slide content (`connect-src 'none'`, `form-action 'none'`, restricted `script-src`).

**The viewer did not introduce a new rendering path.** It reuses the same `buildSlideDocument` function used by `PresentationMode` and the visual editor. Any future rendering surface must route through this function — bypassing it removes the CSP protection.

### Drawer State

| Behaviour | Detail |
|-----------|--------|
| **Sticky tab** | The active tab is remembered in `ViewerContext` and persisted to `localStorage`. Navigating between slides does not reset it. |
| **Stays-on-empty** | When a slide has no findings, the drawer shows an empty state message. It never auto-switches tabs or auto-closes. |
| **Persisted open/height** | `drawerOpen` (boolean) and `drawerHeight` (px, clamped 96–480) are written to `localStorage` key `tellr-viewer-view-state` on every change. |
| **Tabbed shell** | The drawer is built as a tabbed shell with one tab today (`feedback`). Speaker notes (`notes`) land as a second tab in a later workstream without requiring structural changes. |

### Seen-State

AI feedback findings display an amber unseen dot on the thumbnail and the drawer tab when unread. Reading is defined as: the drawer is open on the `feedback` tab while the slide is current.

| Property | Value |
|----------|-------|
| **Storage** | `localStorage` key `tellr-viewer-seen-findings` |
| **Per-user** | Per browser profile by construction — one user reading a finding does not clear the highlight for another user on a shared deck |
| **Scoping** | `Record<deckKey, string[]>` — the key is the session ID (passed as `deckKey` prop); finding IDs are deck-specific strings |
| **Growth bound** | `MAX_DECKS = 50` — when the store exceeds 50 deck keys, the oldest insertion-ordered keys are pruned |
| **Trade-off** | Seen-state does not follow the user to another browser or device |

---

## Data Contracts

### `SlideFinding` (`frontend/src/types/finding.ts`)

```typescript
export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index
  category: 'content' | 'design' | 'narrative';
  message: string;
  seen: boolean;        // initial value only; lifecycle owned client-side
}
```

### `DrawerCallbacks` (`frontend/src/types/finding.ts`)

```typescript
export interface DrawerCallbacks {
  onApplyFinding: (findingId: string) => void;
  onDismissFinding: (findingId: string) => void;
  onDiscussFinding: (findingId: string) => void;
}
```

**Findings arrive as props.** `SlideViewer` receives `findings: SlideFinding[]` and `callbacks: DrawerCallbacks` from `AppLayout`. The findings are never fetched by the viewer — the producing backend (AI review agents) is PRD workstream 5. Until that workstream ships, `findings` is an empty array in production (the callbacks log to console for development-time testing).

---

## Component Responsibilities

| File | Responsibility |
|------|----------------|
| `frontend/src/components/SlideViewer/SlideViewer.tsx` | Public entry point. Wraps `ViewerProvider`. Renders empty state when deck is null or has no slides. Owns keyboard listener, seen-state lifecycle, stage CRUD, presentation-mode handle (`SlideViewerHandle` ref). |
| `frontend/src/components/SlideViewer/SlideStage.tsx` | Renders the single current slide in a sandboxed iframe via `buildSlideDocument`. Handles wheel-paging (threshold + cooldown). Shows prev/next arrow controls and slide position counter. |
| `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx` | Vertical ribbon of scaled slide thumbnails (each at `134/1280 ≈ 10.5%` scale). Drives current-slide selection on click. Supports drag-reorder via `@dnd-kit`. Shows amber unseen dot per slide. Wheel events scroll the list only. |
| `frontend/src/components/SlideViewer/FeedbackDrawer.tsx` | Collapsible tabbed drawer docked to the bottom of the stage column. One `feedback` tab today; tabbed shell ready for `notes`. Drag-resize handle (pointer capture). Shows per-slide findings with Apply / Dismiss / Discuss actions. |
| `frontend/src/components/SlideViewer/seenState.ts` | `localStorage` read/write for seen finding IDs. Exports `loadSeen(deckKey)` and `markSeen(deckKey, ids[])`. Enforces `MAX_DECKS = 50` growth bound. |
| `frontend/src/contexts/ViewerContext.tsx` | Current-slide index (with deck-shrink clamping), next/prev/first/last helpers, drawer open/height/tab. Height clamped to 96–480 px. Persists drawer state to `localStorage`. |
| `frontend/src/types/finding.ts` | `SlideFinding` and `DrawerCallbacks` type definitions. |
| `frontend/src/hooks/useDeckExport.ts` | PDF, PPTX, and HTML export handlers, extracted from `AppLayout`. |

---

## State & Data Flow

### Initialisation

1. `AppLayout` renders `SlideViewer` with `slideDeck`, `deckKey` (session ID), `findings`, and `callbacks`.
2. `SlideViewer` wraps the content in `ViewerProvider`, which reads persisted drawer state from `localStorage` and starts `currentIndex` at 0.
3. Seen-state is loaded from `localStorage` keyed on `deckKey`.

### Navigating Slides

1. User clicks a thumbnail → `ThumbnailRibbon` calls `setCurrentIndex(index)` on `ViewerContext`.
2. User wheels over the stage → `SlideStage.handleWheel` calls `next()` or `prev()`.
3. User presses arrow/page keys → `SlideViewer` keyboard listener calls `next()`, `prev()`, `first()`, or `last()`.
4. `ViewerContext` updates `currentIndex` (clamped to deck bounds).
5. `SlideStage` re-renders the new slide; `ThumbnailRibbon` scrolls the new entry into view.

### Marking Findings as Seen

When the drawer is open on the `feedback` tab and the current slide changes, the `useEffect` in `SlideViewer` computes which finding IDs are newly unread, calls `markSeen(deckKey, ids)` to persist them, and updates the `seen` Set — removing the amber dot from that slide's thumbnail and the drawer tab badge.

### Per-Slide CRUD (edit mode)

The stage toolbar (visible only when `readOnly=false`) provides:

- **Verify** — calls `api.verifySlide(sessionId, currentIndex)`, updates the verification badge.
- **Edit HTML** — opens `HTMLEditorModal`; on save calls `api.updateSlide(currentIndex, html, sessionId)`, then refreshes the deck.
- **Delete** — confirms via `ConfirmDialog`, calls `api.deleteSlide(currentIndex, sessionId)`, then refreshes the deck.

All CRUD handlers guard against concurrent edits with a monotonic `deckEditCounterRef` and surface 409 conflicts to the user with a refresh.

---

## Extension Guidance

### Adding a drawer tab

1. Add the new tab name to `DrawerTab` in `frontend/src/contexts/ViewerContext.tsx` (currently `type DrawerTab = 'feedback'`).
2. Add the tab button in `FeedbackDrawer.tsx` alongside the existing `feedback` button.
3. Render the tab body inside the `{drawerOpen && ...}` block in `FeedbackDrawer`.
4. The `activeTab` value is already persisted to `localStorage` — no changes needed in `ViewerContext`.

Speaker notes are the first planned second tab (PRD workstream TBD).

### Inline WYSIWYG editor (workstream 8)

PRD workstream 8 will add editable text regions on the slide. **Read the iframe-boundary
invariant above before starting** — this is the part of the design most likely to trip you up.

The stage iframe currently sets `pointer-events: none` and `tabIndex={-1}`, so the slide
takes neither mouse nor keyboard focus. Making the slide editable means undoing that, and the
moment focus can enter the iframe, two things break:

- **Keyboard paging stops.** Keydowns fire in the iframe's browsing context and never reach
  the parent `window` listener. `isTypingTarget` cannot help: it never runs, because the
  event does not arrive. This is not a guard bug — it is a browsing-context boundary.
- **Wheel-to-page stops** over the slide area, for the same reason.

Two workable approaches, in order of preference:

1. **Keep editing in the parent document.** Overlay editable regions positioned over the
   slide rather than inside the iframe. The existing focus guard then works unchanged,
   because `document.activeElement` is a real parent-document element and
   `isTypingTarget` sees it (`INPUT`/`TEXTAREA`/`contentEditable`).
2. **If editing must live inside the iframe,** forward keyboard events out with a
   `postMessage` bridge — `KEY_BRIDGE_SCRIPT` in `frontend/src/services/slideDocument.ts`
   already does exactly this for presentation mode (`includeKeyBridge`). You would then
   need an explicit "am I editing?" signal so paging is suppressed during editing rather
   than inferred from focus.

Either way, the paging and focus model needs revisiting; it will not carry over for free.

---

## Cross-References

- [Frontend Overview](frontend-overview.md) — component inventory, context model, backend endpoints
- [Presentation Mode](presentation-mode.md) — adjacent single-slide surface (full-window / fullscreen overlay)
- [Slide Parser & Script Management](slide-parser-and-script-management.md) — `buildSlideDocument` rendering pipeline and CSP
- [Save Points / Versioning](save-points-versioning.md) — how `SlideViewer` is remounted on version preview switches (`key={versionKey}`)
