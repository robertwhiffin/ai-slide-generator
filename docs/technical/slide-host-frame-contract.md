# Slide Host Frame Contract

**One-Line Summary:** The rules that make a slide render identically in every preview surface and in every export — fixed frame geometry, an unmodified box model, and scoped resets — together with what breaks when each one is violated.

---

## 1. Overview

A slide is authored once and rendered in seven places: four preview surfaces, a pop-out viewer, presentation mode, and the export builders. The surfaces **share some document-building and reset utilities** — `buildSlideDocument`, `SLIDE_ROOT_RESET_STYLE` and `slideHostFrameStyle` from `frontend/src/services/slideDocument.ts`, consumed by `SlideTile.tsx`, `SlideSelection.tsx`, `PresentationMode.tsx` and `config/templatePreviewDoc.ts` — but each still has its own wrapper, and the export builders are separate code in Python. Parity therefore depends on an explicit **contract** as well as on the shared helpers.

The contract has three rules, each documented with the failure mode it produces when violated — because in every case the failure is silent rather than an error.

**The reference for "correct" is the source design system's own rendering, not agreement between surfaces.** `tests/unit/test_preview_box_model_parity.py` pins the source-level invariants that follow from that reference: it reads the checked-in TypeScript and Python builders and asserts on their text. The reference bundle and the pixel proof are **not vendored in this repository**, so ground-truth visual parity cannot be reproduced from this checkout — the tests state the invariant and the direction of the reference, not a measurement you can re-run here.

---

## 2. Rule 1 — Fixed frame, measured at the origin

Every slide occupies a fixed 16:9 frame, positioned at the origin of its host.

**The child-stretch half of this rule is surface-specific.** Single-slide preview surfaces frame the host and stretch its slide wrapper through `slideHostFrameStyle`, so there both the slide root **and** the wrapper it sits inside occupy the frame. The Python `build_slide_html` builder **omits that child-stretch rule**, and its source comment records the omission as deliberate: on the huashu path a `body > *` important rule collapses the flattened table cells that `preprocess.mjs` appends to `body` (see §5), so that path relies on emitter-specific handling instead. Do not "restore consistency" by adding the rule to the Python builder.

**Why the wrapper matters.** Design-system templates wrap the slide root in a `<section>` that carries the deck background. If that wrapper is allowed to collapse to zero height, its background paints nothing and whatever sits behind it shows through instead.

**Failure mode — dark-on-dark.** A collapsed wrapper over a dark page background leaves dark text on a dark ground: unreadable, and invisible to any check that measures element *positions*, because nothing moves. If you measure a very low contrast ratio on text that looks correctly coloured in the source, suspect a collapsed wrapper before suspecting the palette.

**Do not diagnose this from computed style.** Where a background image or gradient is involved, `getComputedStyle` reports the declared value regardless of whether anything painted. **Sample the painted pixel.**

---

## 3. Rule 2 — Do not change the box model

**Slide content uses the browser default box model (`content-box`).** No surface may introduce a universal `* { box-sizing: border-box }` rule.

This is counter-intuitive, so it is worth stating plainly: slide content is expected to inherit the UA default. The reference design system's `deck-stage.js` declares `box-sizing` only **scoped** — `::slotted(*)` from inside its shadow root, plus its own chrome — so a surface that "helpfully" normalises the box model universally is not converging on the source rendering.

**Failure mode — surfaces agreeing with each other and all being wrong.** A universal rule added to *some* surfaces makes those surfaces disagree with the rest; added to *all* surfaces it makes them agree with each other while all of them share the same departure from the reference. The second case is the dangerous one, because inter-surface parity tests pass. `test_preview_box_model_parity.py` guards both halves for exactly this reason: the surfaces must agree, **and** they must agree on the reference box model, so a "fix" that restores parity by re-adding the universal rule to all four fails the second assertion.

> **Inter-surface agreement is not a correctness oracle.** A test asserting that all preview surfaces match one another will pass when every surface is wrong in the same way. Any parity assertion must compare against ground truth, not against a sibling surface.

**Where the resets belong.** Shell resets are narrow rather than universal, and they are not uniform across builders: the Python slide builder's shell reset omits `box-sizing` entirely, while the preview host applies `box-sizing: border-box` to the host's **direct child**. What matters is that no rule reaches slide content generally — which works because `box-sizing` does not inherit.

**Deleting a shell reset is not the fix either.** Removing the margin/padding reset lets the export shell overflow its own frame, because the document sizes itself with `width: 100%` and then pads `body`. Narrow them; do not delete them.

---

## 4. Rule 3 — Give the deck's CSS its own stylesheet

`@import` is only valid at the **top of a stylesheet**. A deck that opens its CSS with a webfont `@import` therefore cannot have anything prepended to it.

**Failure mode — silent webfont loss.** Concatenating injected resets ahead of the deck's CSS pushes the `@import` out of first position, the browser discards it, and the export renders in a fallback face. Nothing errors; the file simply comes out in the wrong typeface.

**The contract.** The deck's CSS must be passed through **verbatim** with nothing prepended to it. The Python `build_slide_html` builder satisfies this by emitting injected resets as **separate `<style>` elements** around the deck's own sheet; `buildStandaloneDeckDocument` instead concatenates deck and wrapper CSS into a single `<style>` and stays correct only because the deck's CSS is placed first within it. The separate-element form is the more robust of the two, since it cannot be broken by a later change to concatenation order.

Either way, note what this avoids: there is no need to *find* the leading `@import` in order to hoist it, and hand-written CSS tokenizers are a recurring source of defects. **Prefer restructuring over parsing.**

---

## 5. Emit-Time Hazards

Two failure modes occur **after** the document is built, so they are invisible to any check that inspects the document handed to an emitter.

**The emitter mutates the DOM.** The huashu preprocessing step measures table cells by appending them to `<body>`, which makes every cell a direct child of the document body for the duration of the measurement. **A document-level rule matching `body > *` therefore matches every table cell**, and one that sets `inset: 0` with full width and height collapses all of them onto a single rectangle. The rendered document is unaffected; only the emitted artifact is damaged.

**Corollary for verification:** an export-fidelity claim must be measured on the **emitted artifact**, not on the document passed to the emitter. A document-level comparison will report a perfect match while the exported file is destroyed.

**Injected rules must target one element, not a class of elements.** A selector written for "the slide root" that in fact matches *every direct child of the host* will also match sibling elements — images, decorative layers, measurement scaffolding. The blast radius is invisible on a document with a single child and severe on one with several.

---

## 6. Verification Guidance

The contract is easy to test badly. Four rules, each naming the wrong answer it prevents:

| Rule | Why |
|---|---|
| **Measure painted pixels for anything about colour** | Computed style reports declared values even when nothing painted. |
| **Measure the emitted artifact for anything about export** | Emit-time DOM mutation is invisible upstream. |
| **Anchor geometry probes at the slide root, not at `.slide`** | A `.slide` that is `position: absolute; inset: 0` resolves against its containing block and reports the full frame **even when its wrapper has collapsed** — so the probe reads healthy on the exact defect it was written to catch. |
| **Never use settle-to-stable screenshots for a transient defect** | Waiting for two identical captures structurally discards the unsettled window. A frame-timeline capture is required for anything that appears during navigation or load. |

And one rule about the corpus rather than the instrument: **a deck that declares its own universal `box-sizing` is immune to box-model defects, while a deck that declares one only scoped (`.slide { … }`) takes whatever the host injects.** A corpus composed only of the first kind cannot exhibit the failure, so a green result across it means nothing. Fixture selection must include a deck that relies on the host contract — which is harder than it sounds here, since the reference bundle is not vendored.

---

## 7. Cross-References

- [Export Features](export-features.md) — the export routes and their fidelity behaviour
- [Presentation Mode](presentation-mode.md) — the presentation surface's host styles
- [Design System Library](design-system-library.md) — templates and the wrapper shapes they use
- [Slide Parser & Script Management](slide-parser-and-script-management.md) — how slide roots are discovered
