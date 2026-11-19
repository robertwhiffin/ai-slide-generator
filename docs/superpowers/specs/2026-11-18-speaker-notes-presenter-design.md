# Speaker notes and presenter view: design

**Status.** Approved by the author on 2026-11-18, all four sections. Changed by the author on
2026-11-19 in sections 1, 3 and 4: three drawer tabs instead of two stacked boxes, a notes panel
over Up next instead of a bottom drawer, and link status and "Open presentation" deferred to a
later pull request.

**Goal.** Every Tellr deck arrives with a talk track and notes for each slide. A presenter can
read them in a private presenter window while the audience sees only the slides. People can edit
both, and the agent never overwrites what a person saved.

**Why.** Speaker notes were deferred in `docs/superpowers/specs/2026-08-03-flip-through-viewer-design.md`
(section 1.1). That spec found read-side plumbing only: the exports read `speaker_notes`, but no
field stores it and nothing writes it. The drawer was built as a tabbed shell so a Notes tab could
drop in later (section 5). This design fills that slot, writes the text at build time, and adds
the presenter view that makes notes useful during a live call.

**Model.** The presenter experience follows html-it 0.5.1 (the field deck plugin). Tellr slides
have no builds, so every Tellr slide is html-it's "Builds off" case: one script for the whole
slide (`data-whole-say` in html-it).

---

## 1. What a Tellr user sees (approved)

**While building.** The user asks for a deck as usual. Each slide arrives with a talk track and
notes the agent wrote. No extra steps, and no extra model calls.

**In the editor.** The drawer has three tabs, "AI feedback", "Talk track" and "Notes". Each of the
two new tabs holds one box with its own Save:
- **Talk track:** "What you say." Two to four short spoken beats, ending on the slide's question.
- **Notes:** "What you need to know." Sources for each figure, the likely question and its answer,
  and what to stress.

Text a person saves is kept when the agent rebuilds the slide. Text the agent wrote is refreshed
when the slide is rebuilt. The hint sits beside "Save talk track" and reads: "Chat rewrites the
talk track only when it rebuilds the slide." Chat cannot edit notes on their own in this release.
A read-only viewer of a slide with no talk track sees "No talk track for this slide."

*Changed by the author on 2026-11-19.* The first build stacked both boxes on one Notes tab. At the
drawer's height that needed a scroll, so each box now has its own tab.

**When presenting.**
- Present works as today.
- **P**, or a **Presenter view** button in the presentation toolbar, opens a separate window. It
  shows, top to bottom:
  - "Slide 3 of 7", the slide title, and an elapsed clock;
  - **Read aloud**: the talk track, large;
  - **Coming up**: the next slide's title and the first beat of its talk track;
  - **On screen now** and **Up next**: previews of the current and next slide;
  - a bottom bar with Back, Next, Notes and a key hint.
- N or the Notes button slides a **Notes** panel in from the right. It lies exactly over the Up
  next preview, from the previews' label row to just above the bottom bar. It has a small eyebrow,
  "Notes · this slide", and the heading "Notes". The header, Read aloud, Coming up and On screen
  now stay as they are. Esc closes it. The page fits the window open or closed, with no scrolling.
- Next and Back in either window move both.
- The first time it opens, the window says: "Share only the slides window. Full screen on one
  screen will cover this window."
- The presenter window is read-only in this release.
- The existing N panel over the slides stays as the one-screen option, hidden by default. It
  shows the talk track.

*Changed by the author on 2026-11-19.* The first build opened the notes as a drawer below the
previews. At 1900x1036 the presenter had to scroll to read the notes, and then lost sight of Read
aloud. The panel follows html-it 0.5.1's presenter notes drawer, but covers only Up next. The link
status ("Slides: linked") and the "Open presentation" button move to a later pull request.

**Exports.** The PowerPoint and Google Slides notes pane holds the talk track, then a "Notes:"
heading, then the notes. (html-it 0.5.1 writes only the script; this is a deliberate extension.)

## 2. How the text is stored and written (approved)

**Storage.** Two fields per slide, each with its own author.

| Field | Holds | Author field |
|---|---|---|
| `talk_track` (new) | What the presenter says | `talk_track_source`: `"model"`, `"user"`, or `None` |
| `speaker_notes` | What the presenter needs to know | `speaker_notes_source`: `"model"`, `"user"`, or `None` |

- `speaker_notes` keeps its name because every export already reads that key.
- Each field is protected on its own: a person's save of one never freezes the other.
- The rules from the branch's existing speaker-notes work apply to both fields: a model arrival
  never replaces user text; an arrival with no aside keeps the existing text; a build turn resets
  model text when the new answer has no aside; an empty user save clears the text and its source.
- A design system README that already asks for `<aside class="speaker-notes">` keeps working; its
  text lands in Notes.

**Extraction.** The builder ends each slide with two hidden asides:

```html
<section class="slide">
  ...
  <aside data-presenter="talk-track" hidden><p>Beat one.</p><p>Beat two.</p></aside>
  <aside data-presenter="speaker-notes" hidden><p>Source: ...</p><p>Likely question: ...</p></aside>
</section>
```

The asides are marked with a `data-presenter` attribute, not a class, because the eval harness's
deck-style scorer fails any class the deck's CSS does not define (changed by the author on
2026-11-18 after the first measured run). Tellr also still accepts `class="speaker-notes"` and
`class="talk-track"`. Tellr moves each aside into its field wherever slide HTML arrives, and strips it from the HTML
before the unsafe-pattern scan and the reviewers see it, so presenter prose never costs a
corrective retry.

**Writing.** One paragraph is added to the builder's instructions. It asks the builder to:
- end each slide with the two hidden asides above;
- write `talk-track` as two to four short spoken beats, one `<p>` each, using the slide's own
  figures and names, leading into the next slide's `hands_off`, ending on the slide's question if
  it has one, and never using "click", "tap", or "on the slide";
- write `speaker-notes` as: each figure's source from `data_references`, the likely question with
  a short answer, and what to stress.

The wording must not clash with the existing rule "Never add a note or aside that says data was
unavailable". The change goes through the eval harness (`evals/README.md`): a candidate config in
`evals/configs/builder/`, a measured comparison with `v1-baseline`, then `evals.harness.promote`,
the contract re-record it prints, and a matching edit to `src/core/skills/builder.py`
`INSTRUCTIONS`. The architect and the fixer are unchanged. `Legacy mode` (Tellr's own label) is unchanged: its decks
start with empty text but get the editor, presenter view, and exports.

## 3. Presenter window wiring (approved)

- **Route.** `/sessions/:sessionId/present` renders a presenter page outside `AppLayout`'s editor
  chrome. It loads the deck with the same API the viewer uses, so view access is enough.
- **Opening.** P or the button calls `window.open(url, "tellr-presenter-<sessionId>",
  "popup,width=1200,height=760")` from the user's key press or click, so pop-up blockers allow it.
  Reopening focuses the same window.
- **Sync.** Both windows join a same-origin `BroadcastChannel` named `tellr-present:<sessionId>`.
  Presentation mode is the only source of truth. It posts `{type: "state", index, total,
  deckVersion}` on every slide change and every second while open. The presenter posts
  `{type: "cmd", action: "next" | "prev" | "goto", index?}` and renders only what arrives. A
  presenter opened mid-deck learns the slide from the next state message.
- **Link status (deferred, 2026-11-19).** The "Slides: linked" status, the "Open presentation"
  button and the three-second timeout are not in this release. They will come in a later pull
  request, with the `my_permission` field the button needs.
- **Previews.** Both previews reuse the existing sandboxed slide frame (`sandbox="allow-scripts"`,
  no same-origin) at a reduced scale. They are passive in this release.
- **Freshness.** The presenter refetches the deck when `deckVersion` changes.
- **Keys in the presenter window.** Right and Left (or Space and Backspace) send next and prev; N
  toggles the Notes panel; Esc closes the panel.
- **Notes panel.** Positioned against the previews row over the Up next column, so it takes no
  space and moves nothing. It slides in with a short transform transition, and with none under
  `prefers-reduced-motion`. Long notes scroll inside it.

## 4. Testing (approved)

- **Backend unit.** Both asides extracted and stripped; per-field source protection on every
  arrival path (Agent-mode builder and fixer, `Legacy mode` parse and replacement, user HTML save,
  notes-only save); the export helper writes talk track, then "Notes:", then notes; the migration
  adds the two new columns idempotently.
- **Frontend unit (Vitest).** Talk track and Notes tabs, each with its box and its own save;
  presenter page renders each section; channel sync both ways; P and the button open the window;
  the first-run hint; the Notes panel over Up next, with the top section unchanged; no link status.
- **End to end (Playwright).** Open a deck, present, open the presenter view, step both ways, and
  check the talk track and notes shown match the stored fields. With the notes open, check that the
  panel lies over Up next, Read aloud keeps its width, and the page does not scroll.
- **Eval harness.** Builder candidate against `v1-baseline` on the train split, then held-out once
  on the finalist. Report pass rate, output tokens, and latency in the PR.
- **Live check on a local Tellr.** Build decks in Agent mode with no design system and confirm
  every slide has a model talk track and notes; type into both boxes and confirm a chat rebuild
  keeps them; present with the presenter window on one screen; export to PowerPoint and read the
  notes pane.
- Follow `executing-plans-tellr`: sabotage-verify every test a reviewer approves.

## Non-goals for this release

- Chat edits of talk tracks or notes on their own (needs a notes-only architect edit operation).
- Editing in the presenter window.
- On-slide action cues (html-it's `data-cue`).
- Model-written text for `Legacy mode` decks.
