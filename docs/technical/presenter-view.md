# Presenter View

The presenter view is a second, private window that shows what to say and what comes next while the slides are on the shared screen. Presentation mode drives it, and it follows along. Read it with `presentation-mode.md`, which covers the slides window itself.

---

## Feature Summary

| Capability | Entry point | What happens |
| --- | --- | --- |
| Open the presenter view | P in presentation mode, or the "Presenter view" toolbar button | A pop-up window opens at `/sessions/<id>/present`, or the open one comes to the front |
| Follow the slides | Automatic | The presenter shows the slide presentation mode reports, within one second |
| Step from the presenter | Next and Back buttons, Right and Left, Space and Backspace, Page Down and Page Up (what most presentation clickers send) | The presenter asks presentation mode to move; both windows then show the new slide |
| Read the notes | N or the Notes button in the presenter | A panel with the slide's notes slides in over the Up next preview; N, the button or Esc closes it |
| One-screen option | N in presentation mode | A panel over the slides shows the talk track, or the notes when there is no talk track |

The presenter page shows, top to bottom:

1. "Slide N of M", the slide title (the first `h1` or `h2` of the slide, else "Slide N"), and an elapsed clock in `m:ss`.
2. **Read aloud:** the talk track in large type, one paragraph per beat. Beats are separated by a blank line.
3. **Coming up:** the next slide's title and the first beat of its talk track, or "End of deck".
4. **On screen now** and **Up next:** passive previews of the current and the next slide.
5. A bottom bar with Back, Next, Notes and a key hint.

The Notes panel is closed by default. When open, it covers only the Up next preview (see "The Notes Panel" below).

The page always fits the window, so it never scrolls. The previews take the space left under Coming up, and never less than 40% of the page. Each preview is the largest 16:9 box that fits its column and that height. A long talk track scrolls inside Read aloud, so the previews keep their room.

The first time the page opens, it shows: "Share only the slides window. Full screen on one screen will cover this window." The `localStorage` key `tellr-presenter-hint-seen` is set as soon as the hint shows, so it appears once per browser. A "Got it" button hides it right away.

The elapsed clock starts when the presenter page loads, not when the first slide changes.

---

## The Notes Panel

The panel follows the presenter notes drawer in html-it 0.5.1 (`template-present-notes.html`): the eyebrow, the heading and the slide-in. Its look is Tellr's own dark presenter palette and fonts. Unlike html-it's drawer, which runs the full height of the right side, it covers only the Up next preview, so the talk track always stays whole (the author's choice, 2026-11-19).

- **Where it sits.** It lies exactly over the Up next column. Its left and right edges are Up next's. Its top is the label row of the two previews, and it reaches down to just above the bottom bar. It is positioned against the previews row (`position: absolute`), so it takes no space and moves nothing.
- **What stays in view.** The header, Read aloud, Coming up and On screen now keep their size and place, open or closed. Back, Next and Notes stay in the bottom bar.
- **What it shows.** A small uppercase eyebrow, "Notes · this slide", then the heading "Notes", then the slide's notes, one paragraph per block. A blank line separates blocks. A slide without notes reads "No speaker notes for this slide." Long notes scroll inside the panel.
- **Opening and closing.** N and the Notes button (`aria-label="Show notes"`, pressed while open) toggle it. Esc closes it. Neither key moves the slides.
- **Motion.** It slides in from the right with a 280 ms transform transition. Closed, it waits just past the right edge and is hidden (`visibility: hidden`, `aria-hidden`), so it is out of the tab order. Under `prefers-reduced-motion` it appears and disappears with no transition.
- **Last slide.** There is no Up next preview, and the panel opens over the same column.

---

## Stack and Entry Points

- **Channel and opener:** `frontend/src/services/presenterChannel.ts`
- **Presenter page:** `frontend/src/components/Presenter/PresenterPage.tsx`
- **Route:** `/sessions/:sessionId/present` in `frontend/src/App.tsx`. It sits outside `AppLayout`, so the page has no editor chrome. The editor's tour, welcome and "What's new" overlays are not rendered on this route either (`EditorOverlays` in `App.tsx`). The backend's single-page-app fallback already serves `index.html` for it.
- **Slides window:** `frontend/src/components/PresentationMode/PresentationMode.tsx`. Its callers, `SlidePanel.tsx` and `SlideViewer.tsx`, pass `sessionId`. Without a `sessionId` the toolbar button is hidden and P does nothing.
- **Data:** the presenter loads the deck with `api.getSlides(sessionId)`, the same call the viewer uses, so view access is enough.

---

## Opening the Window

`openPresenterWindow(sessionId)` calls:

```ts
window.open('/sessions/<id>/present', 'tellr-presenter-<id>', 'popup,width=1200,height=760')
```

Then it focuses the window and remembers it for that session. A second call while the remembered window is still open only focuses it. A same-name `window.open` would reload the presenter and reset its clock, so it is not repeated.

Browsers allow a pop-up only during a user action. So `window.open` runs directly inside the handler that sees the action, never from an effect or a timer:

- the P keydown handler in presentation mode;
- the `message` handler that receives a P forwarded from the sandboxed slide frame (`tellr:slide-key`, the same bridge the arrow keys use);
- the toolbar button's click handler.

A P with Cmd, Ctrl or Alt held is left to the browser, so Cmd+P still prints.

A pop-up blocker can still refuse. Then `openPresenterWindow` returns `null`, nothing is remembered, and presenting carries on. The toolbar button is the fallback, since a direct click is the most reliable way to open a pop-up.

---

## The Channel

Both windows join a same-origin `BroadcastChannel` named `tellr-present:<sessionId>`. Each session has its own channel, so two decks presented at once never mix. When `BroadcastChannel` is unavailable, `joinPresenterChannel` does nothing. The presenter then stays on slide 1 without an error.

| Message | Sent by | Shape |
| --- | --- | --- |
| State | Presentation mode | `{ type: 'state', index, total, deckVersion }` |
| Command | Presenter | `{ type: 'cmd', action: 'next' \| 'prev' \| 'goto', index? }` |

- `index` and `total` are whole numbers. `index` is zero-based.
- `deckVersion` is the `version` of the deck snapshot presentation mode took when it opened, or `null` when the deck has none.
- `goto` must carry an integer `index`. Presentation mode clamps every command to the deck.
- `joinPresenterChannel` drops anything else before it reaches the page, including an unknown `action`.

### Timing

- Presentation mode posts a state message when it joins, on every slide change, and every `STATE_HEARTBEAT_MS` (1000 ms) while open. Closing presentation mode clears the heartbeat and closes the channel.
- Before the first state message, the presenter shows slide 1. A presenter opened mid-deck learns the slide from the next heartbeat, within one second.
- The presenter shows no link status in this release. A "Slides: linked" status and an "Open presentation" button are planned for a later release.

---

## Presentation Mode Is the Only Source of Truth

The audience sees the slides window, so that window decides which slide is current. The presenter never moves on its own. Next, Back and the keys in the presenter only post a command, and the presenter changes slide when the answering state message arrives.

This keeps the two windows from drifting apart. A command lost while presentation mode is closed does nothing, instead of moving the presenter away from what the audience sees. It also means a reopened presentation mode resets the presenter to its own position on its first state message.

### Deck freshness

Presentation mode snapshots the deck when it opens, so chat edits do not reload the slides in front of an audience. The presenter compares its own deck with the posted `deckVersion`:

- When the posted version changes and differs from the deck it holds, the presenter fetches the deck again. A heartbeat with the same version never triggers a fetch.
- Whenever the deck the presenter holds has a different version from the posted one, it shows "Slides changed. Reopen the presentation to see them." That includes the moment a refetch is in flight. The banner stays when the refetched deck still differs, which happens when chat edited the deck after Present was pressed.

---

## Previews

Each preview is a 16:9 box holding a 1280x720 frame built with `buildSlideDocument`, laid out with `slideHostFrameStyle`, and scaled to the box width. The box is sized in script to the largest 16:9 rectangle that fits its column's width and height, as html-it's presenter does. The frames use `sandbox="allow-scripts"` without same-origin access, like every other slide frame, and `pointer-events: none`. They are passive in this release. On the last slide only "On screen now" shows.

---

## Read-Only Scope

The presenter page has no text box, editor or save control. Talk tracks and notes are edited in the editor drawer, on its "Talk track" and "Notes" tabs. The page can only step the slides and open or close the Notes panel.

---

## Testing

- `frontend/src/services/__tests__/presenterChannel.test.ts`: names and timings, round trips, the shape check, window reuse per session, and a blocked pop-up.
- `frontend/src/components/Presenter/PresenterPage.test.tsx`: the layout, stepping only on state messages, no link status, the Notes panel (its place over Up next, an unchanged top section, the slide-in and the reduced-motion opt-out, N, the button and Esc), refetch on a new deck version, the first-run hint, cleanup on close, and the read-only page.
- `frontend/src/components/PresentationMode/PresentationMode.test.tsx` ("PresentationMode presenter view"): opening from P, the button and the key bridge, state posting and the heartbeat, clamped commands, leaving the channel and clearing the heartbeat on close, and the N panel order.
- `frontend/tests/e2e/presenter-view.spec.ts`, with its steps in `frontend/tests/helpers/presenter-flow.ts`: in a real browser, P opens the presenter on the slide presentation mode shows, the two windows step both ways, and the open Notes panel lies over Up next, leaves Read aloud its full width, and the page does not scroll.
- `frontend/src/App.presenterRoute.test.tsx`: the editor overlays never mount on the presenter route, and stay on the editor routes.

---

## Cross-References

- `docs/technical/presentation-mode.md`: The slides window that drives the presenter view
- `docs/technical/export-features.md`: PDF and PowerPoint export functionality
- `docs/superpowers/specs/2026-11-18-speaker-notes-presenter-design.md`: The design spec for speaker notes and the presenter view
