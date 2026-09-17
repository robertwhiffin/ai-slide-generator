"""Canonical preview fixture + generation fingerprint for slide-style previews.

A slide style is prose the model interprets, not deterministic CSS, so the only
faithful "what will my slides look like" preview is a generated sample. To make
that sample (a) representative and (b) safely cacheable, this module defines:

- A FIXED, versioned canonical brief that asks for a small deck spanning the
  slide archetypes a style most differs across (cover, content/comparison, and
  an optional data/image slide). One ambiguous slide can misrepresent a style;
  a small canonical deck is fairer.
- A structured GENERATION FINGERPRINT. A preview can go stale even when the
  style text is unchanged — e.g. after a prompt-module, model, generator, or
  renderer release. Hashing only the style text would leave those previews
  looking valid while silently wrong. The fingerprint folds every
  preview-affecting input plus an umbrella version so a release can invalidate
  all previews at once without touching rows.
"""

from __future__ import annotations

import contextvars
import hashlib
from typing import Optional

from src.core.defaults import DEFAULT_CONFIG

# --- Version markers ---------------------------------------------------------
# Bump the specific marker whose behaviour changed; bump PREVIEW_GENERATION_VERSION
# to force-invalidate ALL previews after a cross-cutting release. Every marker is
# folded into the fingerprint below.
PREVIEW_BRIEF_VERSION = "1"        # the canonical brief text / slide set below
PREVIEW_PROMPT_VERSION = "1"       # how we assemble the preview generation prompt
PREVIEW_GENERATOR_VERSION = "2"    # bumped: preview now runs with a capped max_tokens
PREVIEW_RENDERER_VERSION = "1"     # the frontend render contract (buildSlideDocument use)
PREVIEW_GENERATION_VERSION = "1"   # umbrella: bump to invalidate every preview

# --- Preview generation budget ----------------------------------------------
# Previews keep the SAME model as real decks (so palette/typography/layout are
# faithful), but cap max_tokens far below the deck default. The dominant preview
# latency is the model's extended-THINKING budget, which scales with max_tokens;
# a 3-slide sample needs a fraction of a full deck's budget. This is a deliberate
# fidelity/latency trade-off: same model, less deliberation. Set high enough that
# the canonical 3-slide brief completes without truncation (the output validator
# fails-safe to 'failed' + last-known-good if a generation is cut short).
PREVIEW_MAX_TOKENS = 12000

# Thread/async-local override read at model-creation time (see agent model
# factories). Set only for the duration of a preview generation; None otherwise
# so real deck generation always uses the full DEFAULT_CONFIG budget.
preview_max_tokens_override: "contextvars.ContextVar[Optional[int]]" = contextvars.ContextVar(
    "preview_max_tokens_override", default=None
)

# Number of slides the canonical brief asks for. The output validator rejects a
# generation whose slide count is not in this inclusive range (model may merge
# or split), preventing a broken 0-slide or runaway output from being cached.
PREVIEW_MIN_SLIDES = 2
PREVIEW_MAX_SLIDES = 4

# The fixed brief. Neutral, brandless subject matter so the preview reflects the
# STYLE, not the topic; explicitly spans archetypes so one attractive-but-atypical
# slide cannot give a false sense of consistency.
PREVIEW_BRIEF = (
    "Create a short SAMPLE slide deck that demonstrates this visual style. "
    "Use neutral, brand-agnostic placeholder content about a fictional product "
    "launch (call it \"Northwind\"). Produce exactly these slides in order:\n"
    "1. A COVER/TITLE slide: a title, a subtitle, and a small metadata line.\n"
    "2. A CONTENT slide: a section heading and 3-4 concise bullet points.\n"
    "3. A DATA slide: a heading plus a simple chart or a 2-3 row metric layout.\n"
    "Keep the text short. The goal is to showcase typography, color, spacing, "
    "and layout so a viewer can judge the style before generating a real deck."
)


def model_config_version() -> str:
    """A stable marker for the model configuration that affects preview output.

    Reads the same fixed LLM config the agent uses (endpoint/temperature/
    max_tokens). A change here (model swap, temperature change) legitimately
    changes previews, so it participates in the fingerprint.
    """
    llm = DEFAULT_CONFIG.get("llm", {})
    # Include the preview-specific max_tokens cap: changing it changes generation
    # output/latency, so cached previews should regenerate when it moves.
    return (
        f"{llm.get('endpoint')}|{llm.get('temperature')}|{llm.get('max_tokens')}"
        f"|preview_max_tokens={PREVIEW_MAX_TOKENS}"
    )


def compute_content_hash(style_content: str, image_guidelines: Optional[str]) -> str:
    """Hash only the style-authored inputs (used to detect user edits)."""
    h = hashlib.sha256()
    h.update((style_content or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((image_guidelines or "").encode("utf-8"))
    return h.hexdigest()


def compute_fingerprint(style_content: str, image_guidelines: Optional[str]) -> str:
    """Full generation fingerprint: style inputs + every generation dependency.

    Two previews with the same fingerprint are interchangeable; a mismatch means
    the cached preview is stale and must be regenerated.
    """
    h = hashlib.sha256()
    for part in (
        style_content or "",
        image_guidelines or "",
        PREVIEW_BRIEF_VERSION,
        PREVIEW_PROMPT_VERSION,
        PREVIEW_GENERATOR_VERSION,
        PREVIEW_RENDERER_VERSION,
        model_config_version(),
        PREVIEW_GENERATION_VERSION,
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
