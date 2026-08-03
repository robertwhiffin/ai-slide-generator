# Flip-through Slide Viewer + Feedback Drawer — Design

**Status:** Spec, ready for implementation
**Date:** 2026-08-03
**Parent:** `2026-07-30-tellr-agentic-rebuild-prd-design.md` (workstream 6)
**Scope:** Front-end only. Replaces the scrolling slide list with a single-slide
stage, a vertical thumbnail ribbon, and a tabbed drawer for AI feedback.

This workstream is **independent of the agent rebuild** and is built against
**fixture HTML**, not a live agent. Review findings are consumed from a typed
interface with mocked data; the backend that produces them is workstream 5.

**Strictly front-end.** No backend, domain-model, or API changes are in scope. If a
task appears to need one, stop and raise it rather than reaching into `src/`.

---

## 1. Why

Today `SlidePanel` renders every slide in one scrolling column. Two problems:

1. There is nowhere to put **per-slide AI feedback**. The review agents (PRD §7)
   produce slide-level findings, and a scrolling list has no stable "current slide"
   to attach them to.
2. Reviewing a deck by scrolling is unlike every tool users know. Decks are read
   one slide at a time.

### 1.1 On speaker notes (deferred)

An earlier draft of this spec claimed speaker notes already existed and merely
needed a UI. **That was wrong.** The codebase contains read-side plumbing only, in
two **independent** places (not one pipeline):

- **Frontend export walker:** `domWalker.ts:92-94` reads `speaker_notes` / `notes`
  with `||` fallbacks and serialises them to JSON; `domWalker.ts:129` injects that
  JSON as a `<script id="speaker-notes">` blob, which `domWalker.ts:695` reads back
  out per slide during extraction.
- **Backend huashu export route:** `export.py:1225` separately reads
  `slide.get("speaker_notes") or slide.get("notes") or ""` off the deck returned by
  `chat_service.get_slides()` when assembling `slides_with_html`.

But:

- there is no `notes` field on the domain model (`src/domain/slide_deck.py`);
- it is not declared on the `Slide` TypeScript type;
- **nothing anywhere ever writes it** — the reads always resolve to `''`.

It is defensive plumbing for a feature never built. Adding notes is therefore a
full vertical slice (domain field, persistence, type, serialisation), not a UI tab,
so it is **deferred out of this workstream**. The upside: the export leg is already
wired, so whenever notes are implemented they reach PPTX without export changes.

The drawer is still built as a **tabbed shell** so notes can drop in later without
restructuring (§5).

---

## 2. Layout

Preserves the existing three-region shell. Only the slide region changes — from a
scrolling list to a stage. Both left panels become collapsible.

```
┌────────┬──────────┬─────────────────────────────────────┐
│ «      │ «        │  ┌───┐                              │
│  NAV   │   CHAT   │  │▤ 1│                              │
│  opts  │          │  │▤ 2│        SLIDE  5              │
│        │  ┌────┐  │  │▤ 3│    (single pane, large)      │
│        │  │msg │  │  │▤ 4│                              │
│        │  └────┘  │  │▤5◀│                              │
│        │  ┌────┐  │  │▤6•│                              │
│        │  │msg │  │  │▤ 7├──────────────────────────────┤
│        │  └────┘  │  │ ▾ │ [ AI feedback ]              │
│        │ [type…]  │  │   │  • this layout is busy…      │
└────────┴──────────┴──┴───┴──────────────────────────────┘
  nav        chat      ribbon   stage + drawer
(collapsible)(collapsible)  (vertical)   (was: scrolling list)
```

**Regions**

| Region | Change | Notes |
|---|---|---|
| Nav / options (far left) | Becomes **collapsible** | Collapsed state persisted |
| Chat | Becomes **collapsible** | Collapsed state persisted; unchanged internally |
| Thumbnail ribbon | **New**, vertical, scrolls down | Left of the stage; see §4 for styling |
| Stage | **Replaces scroll list** — one slide, large | Uses the freed real estate |
| Drawer | **New**, under the stage, tabbed shell | One tab now (AI feedback); notes later |

Vertical ribbon is deliberate: down is the natural scroll direction, it scales to
long decks, and it makes drag-to-reorder a simple vertical list.

---

## 3. The stage

- Renders exactly one slide, scaled to fit its region while preserving aspect ratio.
- Paging: ribbon click, on-screen ◀ ▶ controls, keyboard (§6), and **scroll over the
  stage** (§4.1).
- The current slide is the single source of "where am I" for the drawer, and is
  addressable so chat can reference it.
- Slide rendering reuses the existing sandboxed-render approach from `SlideTile` —
  this workstream does not change how slide HTML is rendered or sanitised.

---

## 4. The thumbnail ribbon

- Vertical strip of slide thumbnails, index-labelled, scrolls independently.
- Current slide clearly marked (border/ring; use similar styling to the current
  selection indicator: blue border #3b82f6, subtle background tint, shadow).
  Reference `SlideSelection.css` for the selected-state colors and effects, but
  note that the ribbon's scaled thumbnails differ from its grid-based tile layout
  — adapt the colors and shadow treatment but size thumbnails vertically without
  the full-width tiles.
- **Unseen-feedback indicator:** a slide with AI feedback the user has not yet
  viewed shows a **highlight** — a small dot or accent edge in a distinct color
  (e.g., red/orange indicator, or a top accent stripe) positioned consistently on
  the thumbnail. This is deliberately *not* a count. A boolean is far cheaper to
  keep correct than a count (no dedupe, no decrement on dismissal, no
  reconciliation when a slide is re-reviewed). Choose styling that does not
  conflict with the current-slide border.
- **Drag to reorder**, reusing the existing `@dnd-kit` wiring from `SlidePanel`.
- **Always reveals the current slide.** However the slide changes — keyboard, arrow
  controls, stage scroll, or programmatically — the ribbon scrolls so the current
  slide is visible. The displayed slide is never off-screen in the ribbon.

### 4.1 Scroll semantics (Google Slides model)

Scroll means different things over the two regions. This is deliberate:

| Gesture | Effect |
|---|---|
| Scroll wheel **over the ribbon** | Scrolls the thumbnail list **only**. The stage does *not* change. Lets the user browse a long deck without losing their place. |
| Scroll wheel **over the stage** | **Advances/reverses the slide** — the stage is a pager, not a scrolling document. The ribbon follows to keep the new slide visible. |
| **Click a thumbnail** | Selects that slide; stage changes to it. |

So the ribbon can be temporarily scrolled away from the current slide while
browsing — that is correct and expected. Selection only changes on click (or via
stage scroll / keys / arrows), and any selection change re-reveals the current slide
in the ribbon.

Stage scrolling should be **discretised** — one slide per scroll gesture, not
proportional to scroll delta — with enough debounce/threshold that a single
trackpad flick does not skip several slides.

**Retired:** checkbox selection and the `MessageSquare` "add to chat context"
button. Slide targeting becomes conversational (PRD §6.1, workstream 7). Removing
them is in scope here; the `@slide` reference chip that replaces them is **not** —
it belongs with workstream 7.

With checkbox selection retired, the contiguous-only constraint becomes dead code:
`isContiguous` is defined in `utils/slideReplacements.ts:1` and its **only** consumer
is `SlideSelection.tsx:32`. Remove both the call site and the now-orphaned helper if
nothing else picks it up. Note that `frontend-overview.md:110` and
`technical-doc-template.md:44` both present contiguous selection as a standing
invariant — those references must be corrected (§9.2), not left describing a rule
that no longer exists.

---

## 5. The drawer

Sits directly beneath the stage, built as a **tabbed shell** with one tab today:
**AI feedback**. Speaker notes are deferred (§1.1); the shell exists so a second tab
is a drop-in addition rather than a restructure.

### 5.1 Behaviour

- **Tabbed shell, one tab.** Build the tab bar and an `activeDrawerTab` value even
  though only one tab is populated. Adding a tab must not require reworking the
  drawer's layout or state.
- **Sticky tab.** `activeDrawerTab` is view state, not per-slide data. Paging slides
  swaps the drawer's *content*, never the selected tab. (Trivially true with one
  tab; the rule is stated so it holds when a second arrives.)
- **Stays on empty.** If the active tab has nothing for the current slide, show a
  useful empty state ("No feedback for this slide") rather than auto-switching.
  Predictability over cleverness.
- **Highlight, not count.** A tab with unseen AI feedback is highlighted — a
  boolean, deliberately *not* a count of findings. Counts need dedupe, decrement on
  dismissal, and reconciliation on re-review; a highlight needs none of that.
  Cleared once the user views that tab for that slide.

### 5.1.1 What "unseen" means, and where it lives

Seen-state is stored **client-side in `localStorage`**, not in the database.

- **Per-user for free.** Client-side storage is inherently per-browser, so one user
  marking a finding read never clears another user's highlight on a shared deck — no
  server-side per-user keying required.
- **Survives reload**, unlike pure in-memory view state: reopening a deck does not
  re-highlight feedback you have already read.
- **`localStorage`, not a cookie.** Cookies are transmitted on every HTTP request,
  are capped around 4KB, and this data never needs to reach the server. `localStorage`
  avoids all three, and matches the mechanism already used for drawer state and
  pre-session config (`AgentConfigContext.tsx`).
- **Keying:** scope the entry by deck/session identity *and* finding id, so seen-state
  from one deck cannot leak into another.
- **Bound the growth.** Prune entries for decks that no longer exist (or cap total
  size) so the store does not accumulate indefinitely.

**Accepted trade-off:** seen-state does not follow the user to another browser or
device — they will see the highlight again there. Judged not worth a database table
and a persistence endpoint for a read-marker on advisory feedback. If this becomes a
real annoyance, promoting it to server-side storage is a self-contained later change,
and the `seen` field on `SlideFinding` (§7) already gives it a home.

Consequence for scope: the `seen` flag on incoming findings (§7) is treated as an
initial value only; this workstream owns the seen-state lifecycle entirely client-side
and needs **nothing** from workstream 5 to do it.
- **Persisted, resizable.** Open/closed state, height (user-draggable), and active
  tab all persist across slide changes and across reloads via `localStorage`
  (matching the existing pre-session-config pattern; see `AgentConfigContext.tsx`
  for reference implementation).

### 5.2 AI feedback tab

Lists the current slide's **subjective** review findings. (Objective defects are
auto-fixed before the user sees the deck — PRD §7.2 — so they never appear here;
the summary of what was auto-fixed goes to chat, not the drawer.)

Each finding shows its category (content / design / narrative), the finding text,
and three actions:

| Action | Behaviour in this workstream |
|---|---|
| **Apply** | Emits an intent via the callback interface. Wired to the builder in workstream 5; here it is a stub the fixture harness logs. |
| **Dismiss** | Local: removes the finding from view and clears highlight state. |
| **Discuss** | Emits an intent to push the finding into the chat panel. Stubbed as above. |

**Deck-level findings do not appear here** — they go to the main chat (PRD §6.3).

---

## 6. Keyboard

| Key | Action |
|---|---|
| `→` / `↓` / `PageDown` | Next slide |
| `←` / `↑` / `PageUp` | Previous slide |
| `Home` / `End` | First / last slide |

**Focus rule (important):** paging keys must only fire when focus is **not** inside
a text input, textarea, contentEditable, or the chat composer. Pressing `→` while
typing a chat message must never move the slide. Guard on the active element; do not
rely on stopping propagation at the drawer. This generic guard covers all current
inputs (chat composer) and future ones (e.g., notes editor on the drawer) — no
change needed when new editable regions are added to the stage or drawer. This rule
matters more than it looks today — the inline WYSIWYG editor (workstream 8) will put
editable regions directly on the stage.

`Escape` returns focus from the drawer to the stage.

---

## 7. Data interfaces

Typed contracts so this workstream can be built and tested with fixtures while the
producing backend is built separately.

```ts
type FindingCategory = 'content' | 'design' | 'narrative';

interface SlideFinding {
  id: string;
  slideIndex: number;          // 0-based, matches existing deck indexing
  category: FindingCategory;
  message: string;             // user-facing finding text
  seen: boolean;               // drives the unseen highlight
}

interface DrawerCallbacks {
  onApplyFinding: (findingId: string) => void;
  onDismissFinding: (findingId: string) => void;
  onDiscussFinding: (findingId: string) => void;
}
```

Findings are supplied to the viewer as props/context. **Do not** fetch them from an
endpoint in this workstream — the endpoint does not exist yet.

---

## 8. Out of scope

- **Speaker notes** entirely (§1.1) — no domain field, no persistence, no editor.
  The drawer's tabbed shell leaves room for it.
- **Any backend change.** No `src/` edits, no new endpoints, no domain-model or
  schema changes. If something seems to require one, stop and raise it.
- **Inline WYSIWYG editing** (PRD §6.4, workstream 8) — build the stage so an
  editing layer can be added on top, but include no editing affordances.
- **`@slide` reference chips** and conversational slide targeting (workstream 7).
- **Producing** review findings (workstream 5) — consumed via §7 interface only.
- Changes to slide HTML rendering, sanitisation, or export.
- Presentation mode (already exists; unchanged).

---

## 9. Technical documentation (in scope)

Documentation is part of this workstream, not a follow-up. The repo rule in
`.cursor/rules/readme-summary.mdc` requires companion docs in `docs/technical/` to be
updated whenever underlying behaviour changes, and this workstream changes behaviour
that is currently documented as fact.

Follow `docs/technical/technical-doc-template.md` for structure and tone (lead with
outcomes, tables for mappings, call out invariants, reference real paths in
backticks).

### 9.1 New: `docs/technical/slide-viewer.md`

A focused doc for the new surface — the stage, ribbon, and drawer. The template's
extend-vs-create rule (§5) says create new for a major feature area; the drawer and
review-feedback surface qualify. Cover:

- **Architecture snapshot** — stage / ribbon / drawer and how they relate to
  `AppLayout` and the chat panel.
- **Scroll semantics (§4.1)** — the ribbon-browses / stage-pages split, and the
  invariant that the current slide is always revealed in the ribbon. This is
  non-obvious and will be broken by future edits if undocumented.
- **Keyboard model and the focus guard (§6)** — including *why* the guard is generic
  (workstream 8 adds editable regions to the stage).
- **Drawer state** — sticky tab, stays-on-empty, persisted height/open state, and the
  tabbed-shell-with-one-tab decision plus its reason (notes land later).
- **Seen-state (§5.1.1)** — `localStorage`, per-user by construction, key scoping,
  growth bound, and the recorded trade-off that it does not cross browsers/devices.
- **Data contracts** — the `SlideFinding` / `DrawerCallbacks` interfaces (§7), and
  that findings are supplied as props with the producer deferred to workstream 5.
- **Extension guidance** — how to add a drawer tab; how the inline editor
  (workstream 8) is expected to layer onto the stage.

### 9.2 Update: `docs/technical/frontend-overview.md`

This workstream makes several statements in the existing overview **actively wrong**.
Each must be corrected, not merely supplemented:

| Location | Currently documents | Needs |
|---|---|---|
| `:48-50` | "Click slide preview – scrolls the main SlidePanel"; "Click checkbox – toggles slide selection (contiguous only)"; `scrollToSlide` prop | Ribbon click *selects*; stage shows one slide; no checkboxes |
| `:54` | `scrollTarget: { index, key }` coordinating "ribbon-to-panel navigation" | Replaced by current-slide state |
| `:110` | Selection Context section — `selectedIndices`, and "enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`" | Retired — describe what replaces it, and note conversational targeting arrives in workstream 7 |
| `:299-309` | Component rows for `SlidePanel`, `SlideTile`, `SelectionRibbon`/`SlideSelection` | New stage/ribbon/drawer components |
| `:368-376` | "Selecting Slides and Navigation" flow; `SelectionContext` cleared after slides arrive | Rewrite for the new model |
| `:509-511` | User flow: "use checkbox in ribbon to select contiguous slides for chat context" | Rewrite; no checkbox step |

Also remove the **contiguous-selection invariant** where the docs present it as a
rule that must not break (the template itself cites it as an example invariant at
`technical-doc-template.md:44`) — it ceases to exist.

### 9.3 Index and cross-references

- **`README.md`** — add `slide-viewer.md` to the documentation table (`:131-142`).
- **`docs-site/sidebars.js`** — add the new doc (it lists `technical/*` entries
  explicitly at `:49`/`:60`; without an entry it will not appear on the published
  site).
- **Cross-link** `slide-viewer.md` ↔ `frontend-overview.md`, and reference
  `presentation-mode.md` (adjacent single-slide surface) so the set stays coherent.
- Check `docs/user-guide/` for screenshots or instructions describing the scrolling
  list or checkbox selection; flag anything stale rather than silently leaving it.

### 9.4 Scope boundary

Document **what this workstream ships**. Do not document the review agents, the
builder, or conversational targeting as though they exist — reference them as
forthcoming (PRD workstreams 5 and 7) where a reader needs to understand why a
callback is currently a stub.

---

## 10. Verification

- Renders a fixture deck (use `tests/sample_htmls/original_deck.html`, which
  contains a multi-slide test deck suitable for pagination testing), pages through
  all slides via ribbon, buttons, keyboard, and stage scroll.
- **Scroll semantics (§4.1):** wheel over the ribbon scrolls thumbnails without
  changing the stage; wheel over the stage changes slide and the ribbon follows.
- Stage scroll advances exactly one slide per gesture — a single trackpad flick does
  not skip several.
- The current slide is always visible in the ribbon after any selection change,
  including when the ribbon had been scrolled away from it.
- Keyboard paging does **not** fire while typing in the chat input.
- Empty state shown for slides with no findings (not a blank panel).
- Unseen-feedback highlight appears on the ribbon thumbnail and the tab, and clears
  once viewed.
- Seen-state persists across a page reload (§5.1.1) and is scoped per deck — findings
  in one deck do not affect highlights in another.
- Drawer height and open/closed state survive slide changes and a page reload.
- Drag-reorder still works from the ribbon.
- Both left panels collapse and their state persists across reload.
- Apply / Dismiss / Discuss fire their callbacks (Dismiss also updates the view).
- No changes under `src/` — `git diff --stat` touches `frontend/` and `docs/` only.
- Existing E2E suite still passes (Playwright, `frontend/`), updated where it
  asserted the old scrolling list or checkbox selection.

**Documentation (§9):**
- `docs/technical/slide-viewer.md` exists and covers scroll semantics, the focus
  guard, drawer state, seen-state, and the data contracts.
- No statement in `docs/technical/frontend-overview.md` still describes checkbox
  selection, contiguous-only selection, `scrollToSlide`/`scrollTarget`, or
  ribbon-scrolls-the-panel navigation. Grepping the doc for `checkbox` and
  `contiguous` returns nothing stale.
- `README.md` doc table and `docs-site/sidebars.js` both list the new doc.
