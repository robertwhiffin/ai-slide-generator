# Architect stage context: exposure trade-off

**Status:** keep the current behavior. The tool-based alternative below is a future option, not implemented.
**Scope:** Agent mode only; Legacy is unchanged.

## Current choice

Capture the Stage Slide when the user presses Send and include its resolved Slide Number and Slide Position in the Architect's input on every Agent turn where a stage exists. It is background focus, not a mandatory edit target.

For example, “make slide 5 blue” while viewing slide 10 includes both the explicit request and a `stage_slide` pointing to slide 10. The prompt tells the Architect that the explicit reference wins. This avoids another model round-trip, but exposes potentially irrelevant focus information and relies on the model applying the precedence rule correctly.

The conversational default remains local: **“make the title bigger” means the visible heading on the currently staged slide**, rather than automatically meaning the presentation's cover/title or deck-level title metadata. There is no universally correct interpretation; this is the chosen default. Explicit targets and deck-wide requests still take precedence. Questions do not imply edits.

## Alternative: retrieve stage context on demand

Still capture the snapshot at Send, but keep it in server-side turn state instead of exposing it in the initial model payload. Give the Architect a read-only tool, tentatively named `get_staged_slide_at_send`, that returns that message's captured context.

- “Make slide 5 blue” normally needs no stage lookup.
- “Make this slide blue” can request the snapshot.
- “Move this slide after slide 5” needs the snapshot for the source and the explicit reference for the destination anchor.
- An unqualified local title edit should retain the current-slide default.

The Architect can make the tool-use decision itself; a separate classifier model is not required. The lookup can be local and cheap, but consuming its result normally adds a model round-trip. Tool selection can also fail by fetching context unnecessarily or not fetching it when needed. The tool definition itself has prompt overhead.

Do not simply suppress stage context whenever a message contains a slide number: mixed deictic/numbered requests need both references.

## Invariant: capture time is independent of exposure time

Whether context is supplied immediately or retrieved later, it must describe the slide staged **when this message was sent**, not the browser's selection when the tool executes. Sending on slide 10 and navigating to slide 12 must still make a later lookup return the captured slide 10.

Preserve identity-based resolution when an ID is available, turn isolation, and the rule that an unresolved supplied ID never silently falls back to another slide's number.

## When to revisit

Reconsider on-demand exposure if competing focus cues cause targeting mistakes, or if selective context is preferable despite the extra round-trip. Measure targeting accuracy, unnecessary/missing tool calls and latency before changing the default. Reuse the existing stage-aware cases, add tool-use/navigation coverage, and account for Conversation Pin compatibility and eval payload parity.

Domain vocabulary lives in the repository-root `CONTEXT.md`. Current implementation: `getStageSlide` in `SlideViewer.tsx`, send-time capture in `ChatPanel.tsx`, `resolve_stage_slide` in `src/domain/slide_numbering.py`, and the Architect's `STAGE SLIDE` instructions.
