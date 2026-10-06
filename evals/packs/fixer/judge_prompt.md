You are judging the output of the slide FIXER agent in a slide-generation pipeline.

The fixer was shown one built slide that has a single FAULT, together with a reviewer FINDING describing it. Its job is to remove that fault, preserve the slide's message, and change only what the finding requires.

Inputs:
- The candidate output (position, html, scripts, changed, change_summary): {{ outputs }}
- The expectations: {{ expectations }}
  - `brief_or_finding` is the FINDING the fixer was given (criterion, slide_index, message).
  - `reference` is the known-good fixed slide (the original before the fault was planted). The candidate need not match its wording or layout.
  - `measures` holds the render measures of the candidate (overflow_px, min_contrast, off_palette, console_errors). Treat them as hard evidence.
  If the reference is empty or shows nothing to fix, PASS a candidate that leaves the slide unchanged and introduces no render fault.

PASS only if all of these hold:
- the fault named in the finding is gone (for example no off-palette colour, overflow_px is 0, min_contrast is at least 4.5, the figure is corrected to the sourced value stated in the finding message, or the brief's point is delivered again);
- the slide's message and content are preserved, with only what the finding required changed;
- the measures show no new fault: overflow_px is 0, min_contrast is at least 4.5, off_palette is empty, and there are no console_errors.

FAIL if the candidate leaves the fault in place, alters or drops unrelated content, or introduces a new render fault.

Answer with the verdict, PASS or FAIL, FIRST, and only then give one sentence of rationale.
