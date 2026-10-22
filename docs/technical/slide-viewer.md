# Slide Viewer

A flip-through viewer that shows one slide at a time, a vertical thumbnail ribbon for navigation and reordering, and a collapsible drawer surfacing per-slide AI feedback. It replaces the former scrolling slide list and checkbox-based selection model.

---

## Stack & Entry Points

- **Components:** `frontend/src/components/SlideViewer/` (six files — see component table below)
- **Context:** `frontend/src/contexts/ViewerContext.tsx` — current-slide index, drawer open/height/tab
- **Types:** `frontend/src/types/finding.ts` — `SlideFinding`, `DrawerCallbacks`
- **Finding text:** `frontend/src/utils/findingText.ts` — plain-language drawer text, the Apply/Discuss chat text, and the parsers that fold the reviewer's details in chat. Its copy is derived server-side by `src/domain/finding_copy.py`.
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
    ├── ThumbnailRibbon (w-40, fixed left)       ← thumbnails, drag-reorder, unseen dots, insert gaps, New chips
    └── [stage column]
        ├── stage toolbar                        ← verify / new slide / edit HTML / delete (edit mode only)
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
export type FindingCategory = 'content' | 'design' | 'narrative';
export type FindingStatus = 'open' | 'fixed';

export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index; -1 for deck-level findings
  category: FindingCategory;
  criterion: string;    // key into the Python CRITERIA registry
  message: string;      // the reviewer's technical note, verbatim
  plainMessage: string; // issue + status in plain words; derived at read time, NOT a Python Finding field
  plainIssue: string;   // the issue sentence alone (tense by status); same derivation
  objective: boolean;   // could an automated fixer handle this?
  status: FindingStatus; // open = unaddressed; fixed = handled by the auto-fixer
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

**Findings arrive in the deck.** The viewer never fetches them. `SessionManager.get_slide_deck` projects each stored `Finding` through `_finding_to_camel` (`src/api/services/session_manager.py`) onto the `SlideFinding` shape and returns them as `slideDeck.findings`. `AppLayout` passes that list, plus `callbacks: DrawerCallbacks`, to `SlideViewer`, which scopes it to the current slide and drops deck-level criteria (`DECK_LEVEL_CRITERIA`; those go to chat). The projection is generic over `Finding.model_dump()` (snake_case to camelCase) plus two read-time keys, `plainMessage` and `plainIssue`. `src/domain/finding_copy.py` derives both from the finding's `criterion`, the registry's `objective` and its `status`, and never from `message`. They are not `Finding` fields and are never persisted, so findings stored before they existed read the same as new ones. They stay off `Finding` because it is nested in the reviewers' output schemas, and a new field would move the schema digests pinned in `src/services/agent_schema_registry.py`.

### Plain message and details

A reviewer's `message` is written for the fixer and is technical (hex codes, sizes, contrast ratios). The user sees plain words first, and the technical text one click away.

- **Drawer.** Each finding leads with `plainMessage` (`finding-plain-<id>`). A per-finding **Show details** / **Hide details** toggle (`finding-details-toggle-<id>`) reveals `message` verbatim. It is collapsed by default, keyed by finding id, held in component state and not persisted, and the technical text is absent from the DOM until opened. It is not rendered when `message` is blank. A finding that arrives without `plainMessage` or `plainIssue` falls back to `PLAIN_MESSAGE_FALLBACK`.
- **Apply and Discuss.** `AppLayout`'s `handleApplyFinding` and `handleDiscussFinding` post `applyFindingRequest(f)` / `discussFindingRequest(f)` from `findingText.ts`: `<lead> <slideIndex + 1>: <plainIssue>`, then `REVIEWER_DETAILS_SEPARATOR` and `message` verbatim (omitted when `message` is blank). The lead uses `plainIssue`, not `plainMessage`, because only open findings show these buttons and a status sentence would contradict the request. The technical message is sent in full because the architect acts on it.
- **Chat bubble.** `Message.tsx` folds everything after the separator behind a native `<details>` labelled "Reviewer's details", closed by default. It does so only for a user Apply/Discuss request (`splitFindingRequest`) and the assistant deck-review advisory (`splitDeckAdvisory`), and only when the text matches that exact shape. Anything else, including chat messages stored before this change, renders as it was. This is render-only: the sent, stored and polled content is unchanged.
- **Deck advisory.** `_advisory_text` in `src/services/graph/nodes.py` writes plain lines (one per deck-level criterion, repeats merged as "(noted N times)"; a non-deck criterion gets a generic "one of the slides" line), a closing line, then the same separator and one bullet per reviewer message verbatim. The no-findings sentence ("Deck review complete: no narrative issues found across the deck.") is unchanged and has no details section.
- **Deck-level findings** appear only in that advisory, never in the drawer. Their detail also reaches the architect on the next turn as `previous_deck_review`. The advisory is an `info` row, which neither replay path feeds back to the architect.
- **Agents still get the technical text.** The fixer, fix reviewer and architect still receive the full technical `message`. No prompt, schema, agent payload or replayed advisory carries the plain copy. The one route to a model is the user's own Apply/Discuss message, which leads with `plainIssue` and carries `message` verbatim after the separator, so editing `PLAIN_ISSUES` changes what the architect reads on those turns.

---

## Component Responsibilities

| File | Responsibility |
|------|----------------|
| `frontend/src/components/SlideViewer/SlideViewer.tsx` | Public entry point. Wraps `ViewerProvider`. Renders empty state when deck is null or has no slides. Owns keyboard listener, seen-state lifecycle, stage CRUD (including the manual insert), the new-slide indicator effect, presentation-mode handle (`SlideViewerHandle` ref). |
| `frontend/src/components/SlideViewer/SlideStage.tsx` | Renders the single current slide in a sandboxed iframe via `buildSlideDocument`. Handles wheel-paging (threshold + cooldown). Shows prev/next arrow controls and slide position counter. |
| `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx` | Vertical ribbon of scaled slide thumbnails (each at `134/1280 ≈ 10.5%` scale). Drives current-slide selection on click. Supports drag-reorder via `@dnd-kit`. Shows amber unseen dot per slide, the insert gaps ("+") between thumbnails, and the "New" chip and ring on slides the indicator flags. Wheel events scroll the list only. |
| `frontend/src/components/SlideViewer/FeedbackDrawer.tsx` | Collapsible tabbed drawer docked to the bottom of the stage column. One `feedback` tab today; tabbed shell ready for `notes`. Drag-resize handle (pointer capture). Shows per-slide findings led by their plain message, with a per-finding Show details toggle and Apply / Dismiss / Discuss actions. |
| `frontend/src/components/SlideViewer/newSlides.ts` | Pure half of the new-slide indicator: `diffNewSlides`, `syntheticSlideId`, `NEW_SLIDE_INDICATOR_MS`. |
| `frontend/src/components/SlideViewer/seenState.ts` | `localStorage` read/write for seen finding IDs. Exports `loadSeen(deckKey)` and `markSeen(deckKey, ids[])`. Enforces `MAX_DECKS = 50` growth bound. |
| `frontend/src/contexts/ViewerContext.tsx` | Current-slide index (with deck-shrink clamping), next/prev/first/last helpers, drawer open/height/tab. Height clamped to 96–480 px. Persists drawer state to `localStorage`. |
| `frontend/src/types/finding.ts` | `SlideFinding` and `DrawerCallbacks` type definitions. |
| `frontend/src/utils/findingText.ts` | Pure helpers for finding text: `findingPlainText`, `findingPlainIssue`, `applyFindingRequest`, `discussFindingRequest`, and the `splitFindingRequest` / `splitDeckAdvisory` parsers `Message.tsx` uses to fold the reviewer's details. Holds the request leads and the TS mirrors of the separator and deck-advisory strings. |
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
- **New slide** (`stage-insert-slide`) — inserts a blank slide after the current one: `api.insertSlide(currentIndex + 1, sessionId)` posts to `POST /api/slides` with no HTML, so the server builds the deck's own blank frame (see [Backend Overview](backend-overview.md), "Inserting a blank slide by hand"). The viewer then refetches the deck with `api.getSlides`, hands it up through `onSlideChange`, and selects the new slide (see "New-slide indicator" below).
- **Edit HTML** — opens `HTMLEditorModal`; on save calls `api.updateSlide(currentIndex, html, sessionId)`, then refreshes the deck.
- **Delete** — confirms via `ConfirmDialog`, calls `api.deleteSlide(currentIndex, sessionId)`, then refreshes the deck.

All CRUD handlers guard against concurrent edits with a monotonic `deckEditCounterRef` and surface 409 conflicts to the user with a refresh. A `deckKey` change (a session switch) and unmounting the viewer also move the counter on, so an in-flight refetch never hands the old session's deck to the new one (AppLayout's version gate resets on a switch and would accept it).

**Ribbon "+" gaps.** `ThumbnailRibbon` renders an insert gap before every thumbnail and after the last (`ribbon-insert-0` to `ribbon-insert-n`; gap k inserts at position k, so the new slide lands where the gap is). The "+" shows when the pointer is over the gap. While a drag-reorder is active the gaps are hidden but still laid out (`invisible pointer-events-none`, never unmounted: `@dnd-kit` measures the sortable rects at drag start, and collapsing the gaps then would shift every thumbnail under the pointer). The gaps are `tabIndex={-1}`: they are pointer affordances. The keyboard path is the toolbar's **New slide**, which inserts after the current slide, so there is no keyboard way to insert before slide 1.

**Who sees them, and when they are off.** Both controls are for editors only: they render when `readOnly` is false and `onSlideChange` is supplied, so they are hidden for read-only viewers, view-only access, a version preview, and anyone who does not hold the editing lock (AppLayout's `isReadOnly`). They are disabled while a turn is running (`insertDisabled`, which AppLayout sets to `isGenerating`) or while an insert is in flight (`inserting` state, plus a synchronous `insertingRef` so two clicks in one tick make one insert).

**Refusals.** The server can refuse an insert with a 409 (something is still running on the deck, or the deck changed under the insert) or a 423 (another user holds the editing lock). The viewer shows the server's own sentence in a toast and refetches the deck so the view is not stale; any other failure of the insert request shows "Failed to insert slide". Once the insert has succeeded the slide is in the deck, so a failed refetch is never reported as a failed insert (the user would click again and get a second blank): the refetch is retried once, and if that fails too the viewer shows "Slide added. Refresh to see it." (an `info` toast), keeps the inserted slide's id pending so the next deck that holds it selects it, and never re-sends the insert. An insert superseded by a later deck edit, a session switch or an unmount is dropped, like the other handlers'.

### New-slide indicator

Slides that just appeared are marked so the eye finds them: a green "New" chip on the thumbnail (`ribbon-new-${index}`), a ring around it, and a screen-reader status line (`new-slide-status`, "Slide 4 added" or "Slides 2, 4 added"). It runs for every way a slide can appear: a manual insert, the assistant's insert, a duplicate, and a deck growing under a read-only viewer. Nothing in it looks at `readOnly`.

**What counts as new.** `diffNewSlides(baseline, slides)` (`newSlides.ts`, pure) is the only place that decides. The baseline is the `slide_id`s of the last server deck the viewer saw.
- A mid-turn view (built from `slide_ready` events, with synthetic `build-N` ids) flags nothing and does not replace the baseline, so the end-of-turn refetch is diffed against the deck from before the turn.
- With no baseline (first load) or an empty one (a first generation, 0 to N slides), nothing is flagged and the deck becomes the baseline. A `deckKey` change (a session switch) resets the baseline in the same effect, before diffing, and drops any pending selection and the current chips: nothing is new in a deck you have only just switched to.
- Only pure growth flags: every baseline id is still present, and the new ids are flagged in deck order. If a baseline id is gone (a replace or a shrink), nothing is flagged. Null or empty ids are ignored.

**Selection.** One effect in `SlideViewer`, after the new deck has rendered (the viewer's `setCurrentIndex` clamps to the slide count of the render it was created in, so selecting from the insert handler would clamp an append to the old last slide). The slide a manual insert just created wins whenever it is in the deck: its `slide_id` comes from the insert response and is held in a pending ref that is set only once the refetched deck is handed up (or once the refetch has failed twice, so a later deck can select it); a superseded insert never sets it. Otherwise the first new slide is selected.

**How long.** The chips, ring and status line last `NEW_SLIDE_INDICATOR_MS` (5 s) from the latest growth. The timer is cleared when the viewer unmounts.

**Both transports.** SSE and polling both deliver mid-turn slides through `handleSlideReady` (synthetic ids) and both end in the same `complete` refetch, so the indicator behaves the same on each.

**An errored turn.** `ChatPanel` refetches the deck after a failed turn (`refetchDeckAfterError`) and hands it to its optional `onDeckRefetched` prop, so the viewer does not keep a stale mid-turn view. It is called from the SSE `error` event and from the transport's `onError` callback, because polling, the production transport, never emits an `error` event. AppLayout wires it to `setSlideDeckGated(deck, deck.version)` and nothing else; it is deliberately not `onSlidesGenerated`, the success path (survey trigger, "saved just now", versions reload). A per-slide mid-turn error notice (an `error` event carrying `metadata.position`) does not refetch: the turn carries on to `complete`, whose own refetch is the right one. A newer send or a session switch drops the result, and a failed or empty refetch changes nothing.

### Blank slides in the frontend

A blank slide is decided structurally by `frontend/src/services/blankSlide.ts` (`isBlankSlideHtml` for a row, `isBlankSlideSpec` for a spec entry), the twin of the backend predicates. `tests/fixtures/blank_slide_cases.json` is the case table both languages are tested against.
- **Auto-verification** skips a blank slide (`useAutoVerification`, judged on the slide's current HTML): there is nothing on it to check against an empty brief. A blank the assistant later fills in place is verified then.
- **Spec view** labels a blank entry "Blank slide" (`spec-slide-blank-${position}`) in place of its empty purpose and brief, which would read as a broken plan.
- **Spec export** prints "Blank slide." in place of the entry's Purpose and Content brief lines. The view and the export use the same predicate, so they always agree on which slides are blank.

---

## Extension Guidance

### Editing finding copy

1. Edit `PLAIN_ISSUES` in `src/domain/finding_copy.py`: one present-tense and one past-tense sentence per criterion. `GENERIC_ISSUE` covers an unknown or retired criterion. The status sentences and deck-advisory strings are module constants in the same file.
2. A new `CRITERIA` entry in `src/domain/finding.py` needs a `PLAIN_ISSUES` entry, or `tests/unit/test_finding_copy.py` goes red.
3. The deck-advisory strings, `REVIEWER_DETAILS_SEPARATOR` and `PLAIN_MESSAGE_FALLBACK` are mirrored in `frontend/src/utils/findingText.ts` and `frontend/src/types/finding.ts`. `tests/unit/test_finding_conformance.py` pins each pair equal, so editing one side alone fails it.
4. Follow the style rules, which `test_finding_copy.py` enforces. Whole sentences start with a capital and end with a full stop. No digits, `%`, hex colours, `px`, `rgb(`/`hsl(`, contrast ratios, `WCAG`, underscores, backticks, criterion names, or agent role names. Issue sentences describe the slide in the third person; the second person is for action lines such as the closing line and the judgement-call sentence. A finding's full plain message is at most 140 characters.
5. Keep the copy out of `CRITERIA`: that registry is rendered into the build reviewer's prompt, so a separate mapping means editing copy never edits a prompt or a schema digest.

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
