# Slide Host Frame Contract

**One-Line Summary:** The rules that make a slide render identically in every preview surface and in every export — fixed frame geometry, an unmodified box model, and scoped resets — together with what breaks when each one is violated.

---

## 1. Overview

A slide is authored once and rendered in seven places: four preview surfaces, a pop-out viewer, presentation mode, and the export builders. They share no rendering code, so consistency is a **contract** rather than a consequence.

The contract has three rules. Each has been broken at least once, and each break produced a defect that a passing test suite did not catch — so each rule is documented here with its failure mode.

Ground truth for these rules is the reference design system's own rendering. When a surface and ground truth disagree, **ground truth wins** — not the majority of surfaces.

---

## 2. Rule 1 — Fixed frame, measured at the origin

Every slide occupies a fixed 16:9 frame, positioned at the origin of its host. Both the slide root **and** any wrapper element it sits inside must occupy that frame.

**Why the wrapper matters.** Design-system templates wrap the slide root in a `<section>` that carries the deck background. If that wrapper is allowed to collapse to zero height, its background paints nothing and whatever sits behind it shows through instead.

**Failure mode — dark-on-dark.** A collapsed wrapper over a dark page background produces dark text on a dark ground at a contrast ratio near 1.3:1 — unreadable, and invisible to any check that measures element *positions*, because nothing moves. Its signature is a contrast ratio in the 1.25–1.35 band; if you see one, suspect a collapsed wrapper before suspecting the palette.

**Do not diagnose this from computed style.** Where a background image or gradient is involved, `getComputedStyle` reports the declared value regardless of whether anything painted. **Sample the painted pixel.**

---

## 3. Rule 2 — Do not change the box model

**Slide content uses the browser default box model (`content-box`).** No surface may introduce a universal `* { box-sizing: border-box }` rule.

This is counter-intuitive, so it is worth stating plainly: the reference design system's templates declare **no** `box-sizing` at all, and the rules that do exist in its stage component are **scoped to specific containers**. Slide content therefore inherits the UA default, and a surface that "helpfully" normalises the box model diverges from ground truth.

**Failure mode — surfaces agreeing with each other and all being wrong.** A universal rule added to *some* surfaces makes those surfaces disagree with the rest; added to *all* surfaces it makes them agree with each other while every one of them diverges from ground truth. The second case is the dangerous one, because inter-surface parity tests pass.

> **Inter-surface agreement is not a correctness oracle.** A test asserting that all preview surfaces match one another will pass when every surface is wrong in the same way. Any parity assertion must compare against ground truth, not against a sibling surface.

**Where the resets belong.** Margin, padding and `box-sizing` resets are scoped to `html, body`, which works precisely because `box-sizing` does not inherit — the document shell is normalised while slide content keeps the UA default.

**Deleting the shell reset is not the fix either.** Removing it entirely lets the export shell overflow its own frame, because the document sizes itself with `width: 100%` and then pads `body`. Scope it; do not delete it.

---

## 4. Rule 3 — Give the deck's CSS its own stylesheet

`@import` is only valid at the **top of a stylesheet**. A deck that opens its CSS with a webfont `@import` therefore cannot have anything prepended to it.

**Failure mode — silent webfont loss.** Concatenating injected resets ahead of the deck's CSS pushes the `@import` out of first position, the browser discards it, and the export renders in a fallback face. Nothing errors; the file simply comes out in the wrong typeface.

**The contract.** Emit injected resets as **separate `<style>` elements**, before and after the deck's own stylesheet, and pass the deck's CSS through **verbatim**. Cascade order between style elements follows document order, so precedence is unchanged.

This also removes a class of parsing bug entirely: with the deck's CSS in its own sheet, there is no need to *find* the leading `@import` in order to hoist it — and hand-written CSS tokenizers are where several defects lived before the restructure. **Prefer restructuring over parsing.**

---

## 5. Emit-Time Hazards

Two failure modes occur **after** the document is built, so they are invisible to any check that inspects the document handed to an emitter.

**The emitter mutates the DOM.** The huashu preprocessing step measures table cells by appending them to `<body>`, which makes every cell a direct child of the document body for the duration of the measurement. **A document-level rule matching `body > *` therefore matches every table cell**, and one that sets `inset: 0` with full width and height collapses all of them onto a single rectangle. The rendered document is unaffected; only the emitted artifact is damaged.

**Corollary for verification:** an export-fidelity claim must be measured on the **emitted artifact**, not on the document passed to the emitter. A document-level comparison will report a perfect match while the exported file is destroyed.

**Injected rules must target one element, not a class of elements.** A selector written for "the slide root" that in fact matches *every direct child of the host* will also match sibling elements — images, decorative layers, measurement scaffolding. The blast radius is invisible on a document with a single child and severe on one with several.

---

## 6. Verification Guidance

The contract is easy to test badly. Four rules, each learned from a check that produced a confident wrong answer:

| Rule | Why |
|---|---|
| **Measure painted pixels for anything about colour** | Computed style reports declared values even when nothing painted. |
| **Measure the emitted artifact for anything about export** | Emit-time DOM mutation is invisible upstream. |
| **Anchor geometry probes at the slide root, not at `.slide`** | A `.slide` that is `position: absolute; inset: 0` resolves against its containing block and reports the full frame **even when its wrapper has collapsed** — so the probe reads healthy on the exact defect it was written to catch. |
| **Never use settle-to-stable screenshots for a transient defect** | Waiting for two identical captures structurally discards the unsettled window. A frame-timeline capture is required for anything that appears during navigation or load. |

And one rule about the corpus rather than the instrument: **a deck that declares its own universal `box-sizing` is immune to box-model defects.** A corpus composed only of such decks cannot exhibit the failure, so a green result across it means nothing. Fixture selection must include a deck that relies on the host contract.

---

## 7. Cross-References

- [Export Features](export-features.md) — the export routes and their fidelity behaviour
- [Presentation Mode](presentation-mode.md) — the presentation surface's host styles
- [Design System Library](design-system-library.md) — templates and the wrapper shapes they use
- [Slide Parser & Script Management](slide-parser-and-script-management.md) — how slide roots are discovered
