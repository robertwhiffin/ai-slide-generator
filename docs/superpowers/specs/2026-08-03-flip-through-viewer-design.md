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
needed a UI. **That was wrong.** The codebase contains read-side plumbing only —
`domWalker.ts:92-94` and `export.py:1225` read `speaker_notes` / `notes` with `||`
fallbacks, and `domWalker.ts:129` round-trips them through a `<script
id="speaker-notes">` blob on the export path. But:

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
| Thumbnail ribbon | **New**, vertical, scrolls down | Left of the stage |
| Stage | **Replaces scroll list** — one slide, large | Uses the freed real estate |
| Drawer | **New**, under the stage, tabbed shell | One tab now (AI feedback); notes later |

Vertical ribbon is deliberate: down is the natural scroll direction, it scales to
long decks, and it makes drag-to-reorder a simple vertical list.

---

## 3. The stage

- Renders exactly one slide, scaled to fit its region while preserving aspect ratio.
- Paging: ribbon click, on-screen ◀ ▶ controls, and keyboard (§6).
- The current slide is the single source of "where am I" for the drawer, and is
  addressable so chat can reference it.
- Slide rendering reuses the existing sandboxed-render approach from `SlideTile` —
  this workstream does not change how slide HTML is rendered or sanitised.

---

## 4. The thumbnail ribbon

- Vertical strip of slide thumbnails, index-labelled, scrolls independently.
- Current slide clearly marked (border/ring, consistent with existing selection
  styling; see `SlideSelection.css` for reference: blue border #3b82f6, subtle
  background tint, shadow).
- **Unseen-feedback indicator:** a slide with AI feedback the user has not yet
  viewed shows a **highlight** — a small dot or accent edge in a distinct color
  (e.g., red/orange indicator, or a top accent stripe) positioned consistently on
  the thumbnail. This is deliberately *not* a count. A boolean is far cheaper to
  keep correct than a count (no dedupe, no decrement on dismissal, no
  reconciliation when a slide is re-reviewed). Choose styling that does not
  conflict with the current-slide border.
- **Drag to reorder**, reusing the existing `@dnd-kit` wiring from `SlidePanel`.
- Auto-scrolls to keep the current slide in view when paging by keyboard.

**Retired:** checkbox selection and the `MessageSquare` "add to chat context"
button. Slide targeting becomes conversational (PRD §6.1, workstream 7). Removing
them is in scope here; the `@slide` reference chip that replaces them is **not** —
it belongs with workstream 7. With checkbox selection retired, the current
contiguous-only constraint in `SlideSelection.tsx` becomes dead code and should
be removed (or left in place if it imposes no maintenance burden, but it is not
needed for the new single-slide viewer).

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
rely on stopping propagation at the drawer. This rule matters more than it looks
today — the inline WYSIWYG editor (workstream 8) will put editable regions directly
on the stage.

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

## 9. Verification

- Renders a fixture deck (use `tests/sample_htmls/original_deck.html`, which
  contains a multi-slide test deck suitable for pagination testing), pages through
  all slides via ribbon, buttons, and keyboard.
- Keyboard paging does **not** fire while typing in the chat input.
- Empty state shown for slides with no findings (not a blank panel).
- Unseen-feedback highlight appears on the ribbon thumbnail and the tab, and clears
  once viewed.
- Drawer height and open/closed state survive slide changes and a page reload.
- Drag-reorder still works from the ribbon.
- Both left panels collapse and their state persists across reload.
- Apply / Dismiss / Discuss fire their callbacks (Dismiss also updates the view).
- Ribbon auto-scrolls to keep the current slide visible when paging by keyboard.
- No changes under `src/` — `git diff --stat` touches `frontend/` only.
- Existing E2E suite still passes (Playwright, `frontend/`), updated where it
  asserted the old scrolling list or checkbox selection.
