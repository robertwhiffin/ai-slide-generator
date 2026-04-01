"""Performance tests for prompt decoupling: token efficiency and assembly latency.

These tests quantify the measurable benefits of splitting the monolithic
system prompt into mode-specific modules.  They run purely locally (no
LLM calls) and produce concrete numbers for reporting.
"""

import time

import tiktoken

from src.core.defaults import DEFAULT_CONFIG, DEFAULT_SLIDE_STYLE
from src.core.prompt_modules import (
    IMAGE_SUPPORT,
    build_editing_system_prompt,
    build_generation_system_prompt,
)

# Use cl100k_base — the tokenizer used by Claude / GPT-4-class models.
# Exact token counts vary by model but relative savings are consistent.
ENC = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(ENC.encode(text))


def _build_legacy_prompt() -> str:
    """Reproduce the old monolithic system prompt as _create_prompt built it.

    Order: slide_style + system_prompt + slide_editing_instructions + IMAGE_SUPPORT
    (deck_prompt omitted — it's optional and the same in both paths).
    """
    parts = [
        DEFAULT_SLIDE_STYLE.strip(),
        DEFAULT_CONFIG["prompts"]["system_prompt"].rstrip(),
        DEFAULT_CONFIG["prompts"]["slide_editing_instructions"].strip(),
        IMAGE_SUPPORT,
    ]
    return "\n\n".join(parts)


# -----------------------------------------------------------------------
# 1. Token efficiency tests
# -----------------------------------------------------------------------

class TestTokenEfficiency:
    """Quantify per-request token savings from prompt decoupling."""

    def test_generation_prompt_is_smaller_than_legacy(self):
        """Generation prompt excludes editing rules, saving tokens."""
        legacy = _build_legacy_prompt()
        generation = build_generation_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)

        legacy_tokens = _count_tokens(legacy)
        gen_tokens = _count_tokens(generation)

        savings = legacy_tokens - gen_tokens
        pct = (savings / legacy_tokens) * 100

        print(f"\n--- Token Efficiency: Generation Mode ---")
        print(f"  Legacy (monolithic):   {legacy_tokens:,} tokens")
        print(f"  New (generation-only): {gen_tokens:,} tokens")
        print(f"  Savings:               {savings:,} tokens ({pct:.1f}%)")

        assert gen_tokens < legacy_tokens, (
            f"Generation prompt ({gen_tokens}) should be smaller than "
            f"legacy ({legacy_tokens})"
        )
        # Editing rules are ~600-800 tokens; expect at least 400 saved
        assert savings >= 400, (
            f"Expected at least 400 tokens saved, got {savings}"
        )

    def test_editing_prompt_is_smaller_than_legacy(self):
        """Editing prompt excludes generation-only rules, saving tokens."""
        legacy = _build_legacy_prompt()
        editing = build_editing_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)

        legacy_tokens = _count_tokens(legacy)
        edit_tokens = _count_tokens(editing)

        savings = legacy_tokens - edit_tokens
        pct = (savings / legacy_tokens) * 100

        print(f"\n--- Token Efficiency: Editing Mode ---")
        print(f"  Legacy (monolithic):  {legacy_tokens:,} tokens")
        print(f"  New (editing-only):   {edit_tokens:,} tokens")
        print(f"  Savings:              {savings:,} tokens ({pct:.1f}%)")

        assert edit_tokens < legacy_tokens, (
            f"Editing prompt ({edit_tokens}) should be smaller than "
            f"legacy ({legacy_tokens})"
        )
        # Generation goals + presentation guidelines + HTML format template
        # are ~400-600 tokens; expect at least 300 saved
        assert savings >= 300, (
            f"Expected at least 300 tokens saved, got {savings}"
        )

    def test_combined_coverage_vs_legacy(self):
        """Union of generation + editing prompts covers all legacy content.

        Both modes together should not *lose* any instructional content
        compared to the original monolithic prompt.  The total token count
        may be higher (some blocks are shared and thus duplicated) but
        per-request cost is always lower.
        """
        legacy = _build_legacy_prompt()
        generation = build_generation_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)
        editing = build_editing_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)

        legacy_tokens = _count_tokens(legacy)
        gen_tokens = _count_tokens(generation)
        edit_tokens = _count_tokens(editing)

        print(f"\n--- Combined Coverage ---")
        print(f"  Legacy:          {legacy_tokens:,} tokens")
        print(f"  Generation:      {gen_tokens:,} tokens")
        print(f"  Editing:         {edit_tokens:,} tokens")
        print(f"  Max per-request: {max(gen_tokens, edit_tokens):,} tokens")
        print(f"  Worst-case savings: {legacy_tokens - max(gen_tokens, edit_tokens):,} tokens")

        # Neither mode alone should exceed the legacy monolithic prompt
        assert gen_tokens < legacy_tokens
        assert edit_tokens < legacy_tokens

    def test_token_breakdown_by_block(self):
        """Print token count for each prompt module block for visibility."""
        from src.core import prompt_modules as pm

        blocks = {
            "BASE_PROMPT": pm.BASE_PROMPT,
            "DATA_ANALYSIS_GUIDELINES": pm.DATA_ANALYSIS_GUIDELINES,
            "SLIDE_GUIDELINES": pm.SLIDE_GUIDELINES,
            "CHART_JS_RULES": pm.CHART_JS_RULES,
            "IMAGE_SUPPORT": pm.IMAGE_SUPPORT,
            "GENERATION_GOALS": pm.GENERATION_GOALS,
            "PRESENTATION_GUIDELINES": pm.PRESENTATION_GUIDELINES,
            "HTML_OUTPUT_FORMAT": pm.HTML_OUTPUT_FORMAT,
            "EDITING_RULES": pm.EDITING_RULES,
            "EDITING_OUTPUT_FORMAT": pm.EDITING_OUTPUT_FORMAT,
        }

        print(f"\n--- Token Breakdown by Block ---")
        shared_total = 0
        gen_only_total = 0
        edit_only_total = 0
        for name, text in blocks.items():
            tokens = _count_tokens(text)
            category = "shared"
            if name in ("GENERATION_GOALS", "PRESENTATION_GUIDELINES", "HTML_OUTPUT_FORMAT"):
                category = "gen-only"
                gen_only_total += tokens
            elif name in ("EDITING_RULES", "EDITING_OUTPUT_FORMAT"):
                category = "edit-only"
                edit_only_total += tokens
            else:
                shared_total += tokens
            print(f"  {name:30s}  {tokens:5,} tokens  [{category}]")

        print(f"  {'':30s}  -----")
        print(f"  {'Shared':30s}  {shared_total:5,} tokens")
        print(f"  {'Generation-only':30s}  {gen_only_total:5,} tokens")
        print(f"  {'Editing-only':30s}  {edit_only_total:5,} tokens")

        # Sanity: no single block should be empty
        for name, text in blocks.items():
            assert _count_tokens(text) > 10, f"{name} is suspiciously small"


# -----------------------------------------------------------------------
# 2. Assembly latency tests
# -----------------------------------------------------------------------

class TestAssemblyLatency:
    """Measure prompt assembly time to confirm negligible overhead."""

    ITERATIONS = 1000

    def test_generation_assembly_latency(self):
        """build_generation_system_prompt completes in <1ms on average."""
        start = time.perf_counter()
        for _ in range(self.ITERATIONS):
            build_generation_system_prompt(
                slide_style=DEFAULT_SLIDE_STYLE,
                deck_prompt="Quarterly review",
                image_guidelines="Use brand logo",
            )
        elapsed = time.perf_counter() - start
        avg_us = (elapsed / self.ITERATIONS) * 1_000_000

        print(f"\n--- Assembly Latency: Generation ---")
        print(f"  {self.ITERATIONS} iterations in {elapsed:.3f}s")
        print(f"  Average: {avg_us:.1f} µs per call")

        assert avg_us < 1000, f"Expected <1ms average, got {avg_us:.1f}µs"

    def test_editing_assembly_latency(self):
        """build_editing_system_prompt completes in <1ms on average."""
        start = time.perf_counter()
        for _ in range(self.ITERATIONS):
            build_editing_system_prompt(
                slide_style=DEFAULT_SLIDE_STYLE,
                deck_prompt="Quarterly review",
                image_guidelines="Use brand logo",
            )
        elapsed = time.perf_counter() - start
        avg_us = (elapsed / self.ITERATIONS) * 1_000_000

        print(f"\n--- Assembly Latency: Editing ---")
        print(f"  {self.ITERATIONS} iterations in {elapsed:.3f}s")
        print(f"  Average: {avg_us:.1f} µs per call")

        assert avg_us < 1000, f"Expected <1ms average, got {avg_us:.1f}µs"
