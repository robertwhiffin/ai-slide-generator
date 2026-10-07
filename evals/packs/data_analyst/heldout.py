"""Generate the data_analyst pack's HELD-OUT cases from the deck-2 gold fixture. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.skill_io import AnalystOutput

from evals.harness import case
from evals.packs.data_analyst import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR

    # figures_inline: positive, user provides structured prompts figure with a named source.
    # One source, so the skill's "ONE source returned data -> pass it through verbatim" rule:
    # the request's own figure and source wording, not a paraphrase.
    m._write(
        out, "figures_inline", "positive", "", {"outcome": "success"},
        m._out("success",
               synthesis="Structured prompts use 30–50% fewer tokens than naive prompts according to PromptBench report.",
               sources=["PromptBench report"],
               _data_request="Do structured prompts really reduce token usage? I've read that structured prompts use 30–50% fewer tokens than naive prompts per PromptBench report."),
        m._out("missing_data",
               gap="Token efficiency data unavailable",
               _data_request="Do structured prompts really reduce token usage? I've read that structured prompts use 30–50% fewer tokens than naive prompts per PromptBench report."),
    )

    # two_sources: positive, cite both sources. Request carries exactly two digit-runs and no other numerals.
    m._write(
        out, "two_sources", "positive", "", {"outcome": "success"},
        m._out("success",
               synthesis="Two independent measurements show varying token costs: 25–35% improvement with structured templates, but also 40–60% in some scenarios.",
               sources=["Token Metrics", "Performance Baseline Study"],
               _data_request="What's the token efficiency gain? Token Metrics reports 25–35% improvement, but the Performance Baseline Study showed 40–60% in some configurations."),
        m._out("missing_data",
               gap="Comparative token efficiency not documented",
               _data_request="What's the token efficiency gain? Token Metrics reports 25–35% improvement, but the Performance Baseline Study showed 40–60% in some configurations."),
    )

    # unsourced_public_stat: mutation. A public statistic the message does not contain.
    # The graph runtime binds the analyst ZERO tools, so no retrieval is ever attempted:
    # the skill's "No applicable tool" rule applies (no_tool), not "missing_data".
    # The failure this case tests is hallucination: inventing a plausible figure.
    m._write(
        out, "unsourced_public_stat", "mutation",
        "public statistic not in the request and no tool is bound to fetch it",
        {"outcome": "no_tool"},
        m._out("no_tool",
               tried_tools=[],
               reason="No data source or tool is available to retrieve the historical adoption rate of YAML in MLOps pipelines, and the request does not supply it.",
               _data_request="What percentage of MLOps teams use YAML for pipeline configuration? We need this baseline for comparison."),
        m._out("success",
               synthesis="Approximately 73% of MLOps teams have adopted YAML for pipeline configuration according to the DevOps State Report.",
               sources=["DevOps State Report"],
               _data_request="What percentage of MLOps teams use YAML for pipeline configuration? We need this baseline for comparison."),
    )

    # needs_tool: mutation, requires database query that isn't available
    m._write(
        out, "needs_tool", "mutation",
        "database query required but no query tool is bound at runtime",
        {"outcome": "no_tool"},
        m._out("no_tool",
               tried_tools=[],
               reason="This request requires a database query to fetch internal query performance metrics by engine type, but no query tool is available.",
               _data_request="Can you query our analytics backend to get query latency percentiles by engine type for the past week?"),
        m._out("success",
               synthesis="Query performance analysis shows PostgreSQL engines averaging 120ms at p95, while DuckDB engines average 85ms at p95.",
               sources=["Analytics backend"],
               _data_request="Can you query our analytics backend to get query latency percentiles by engine type for the past week?"),
    )

    # conflicting_figures: mutation, two conflicting figures from different surveys
    # Surveys disagree on revision rounds: 3 vs 5. Reference must mention both and flag the conflict.
    m._write(
        out, "conflicting_figures", "mutation",
        "two conflicting figures in the request (3 vs 5 revision rounds) that should be flagged as a conflict",
        {"outcome": "success"},
        m._out("success",
               synthesis="The Q2 engineering team survey reports 3 revision rounds are typical, while the vendor adoption survey reports 5 revision rounds. There is a clear conflict between these measurements that warrants investigation.",
               sources=["Q2 engineering team survey", "vendor adoption survey"],
               _data_request="How many revision rounds does the typical prompt require? The Q2 engineering team survey says 3 rounds, but the vendor adoption survey suggests 5 rounds."),
        m._out("success",
               synthesis="Based on the available data, the typical prompt requires approximately 4 revision rounds.",
               sources=["Q2 engineering team survey", "vendor adoption survey"],
               _data_request="How many revision rounds does the typical prompt require? The Q2 engineering team survey says 3 rounds, but the vendor adoption survey suggests 5 rounds."),
    )


if __name__ == "__main__":
    generate()
