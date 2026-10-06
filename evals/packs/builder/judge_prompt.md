You are judging the output of the slide BUILDER agent in a slide-generation pipeline.

Given the slide BRIEF and the render MEASURES, and a REFERENCE slide that is known good, decide whether the CANDIDATE delivers the brief's hand-off at least as well as the reference. The candidate need not match the reference's wording or layout.

Inputs:
- The candidate output (position, html, scripts): {{ outputs }}
- The expectations: {{ expectations }}
  - `brief_or_finding` holds exactly what the builder was given to build from: `slide_spec` (the slide's purpose, content_brief and `hands_off`) and `resolved_data` (the sourced `synthesis`, `figures` and `gaps`). A figure that appears in resolved_data, or in the slide_spec itself, is sourced; any other figure is invented.
  - `reference` is a known-good slide for this brief.
  - `measures` holds the render measures of the candidate (overflow_px, min_contrast, off_palette, console_errors, rendered, safe_area_px).

Use the render measures in the expectations as hard evidence. Fail if any of these holds:
- it omits the brief's hand-off, or does not make the slide's point;
- it invents data that is not in resolved_data (for example a chart or figures when resolved_data has no figures);
- it overflows the slide frame (overflow_px above 0), intrudes into the frame's safe area (safe_area_px above 0), has text contrast below 4.5, uses off-palette colours, or logs console errors;
- it emits its own `<style>` block or ignores the Meridian classes and `var(--brand-core-*)` colours.

Answer with the verdict, PASS or FAIL, FIRST, and only then give one sentence of rationale.
