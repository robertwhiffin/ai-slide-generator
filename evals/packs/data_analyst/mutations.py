"""Generate the data_analyst pack's cases. Idempotent."""
import json

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.skill_io import AnalystOutput
from src.services.agent_model_payload import model_payload_for

from evals.harness import case

AGENT = "data_analyst"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _payload(data_request):
    """Build the production payload for data_analyst."""
    return model_payload_for(AGENT, {
        "data_request": data_request,
        "deck_purpose": None,
    })


def _out(outcome, **kw):
    """Create and validate an AnalystOutput."""
    out = {
        "outcome": outcome,
        "synthesis": None,
        "sources": None,
        "gap": None,
        "tried_tools": [],
        "reason": None,
    }
    out.update(kw)
    AnalystOutput.model_validate(out)  # fail fast
    return out


def _write(cid, kind, fault, expect, reference, should_fail):
    """Write a case to disk."""
    d = CASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", _payload(reference["_data_request"]))
    ref = {k: v for k, v in reference.items() if k != "_data_request"}
    _dump(d / "reference.json", ref)
    bad = {k: v for k, v in should_fail.items() if k != "_data_request"}
    _dump(d / "calibration.json", {"should_fail": bad})


def generate():
    """Generate all 5 cases idempotently."""

    # figures_inline: positive, user provides StatCounter 98% figure. One source, so the
    # skill's "ONE source returned data -> pass it through verbatim" rule: the request's own
    # figure and source wording, not a paraphrase.
    _write(
        "figures_inline", "positive", "", {"outcome": "success"},
        _out("success",
             synthesis="98% on StatCounter",
             sources=["StatCounter"],
             _data_request="What browser support do we have for device rendering? I've seen 98% on StatCounter."),
        _out("missing_data",
             gap="No device support data available",
             _data_request="What browser support do we have for device rendering? I've seen 98% on StatCounter."),
    )

    # two_sources: positive, cite both sources (8-15 MB and under 1 MB)
    _write(
        "two_sources", "positive", "", {"outcome": "success"},
        _out("success",
             synthesis="Two reported figures differ: 8–15 MB is described as typical, while under 1 MB is reported for some configurations.",
             sources=["Reported figure: 8–15 MB typical", "Reported figure: under 1 MB in some configurations"],
             _data_request="How much memory does the application use? I've heard 8–15 MB typical, but also under 1 MB in some configurations."),
        _out("missing_data",
             gap="Memory requirements not documented",
             _data_request="How much memory does the application use? I've heard 8–15 MB typical, but also under 1 MB in some configurations."),
    )

    # unsourced_public_stat: mutation. A public statistic the message does not contain.
    # The graph runtime binds the analyst ZERO tools, so no retrieval is ever attempted:
    # the skill's "No applicable tool" rule applies (no_tool), not "No source returned
    # data" (missing_data, which presupposes an attempted retrieval and is unreachable).
    # The failure this case tests is hallucination: inventing a plausible figure.
    _write(
        "unsourced_public_stat", "mutation",
        "public statistic not in the request and no tool is bound to fetch it",
        {"outcome": "no_tool"},
        _out("no_tool",
             tried_tools=[],
             reason="No data source or tool is available to retrieve this public statistic "
                    "(Reveal.js monthly active users in 2023), and the request does not supply it.",
             _data_request="How many monthly active users did Reveal.js have in 2023? We need this for our analysis."),
        _out("success",
             synthesis="Reveal.js had approximately 4.7 million monthly active users in 2023, "
                       "according to the npm Developer Survey.",
             sources=["npm Developer Survey"],
             _data_request="How many monthly active users did Reveal.js have in 2023? We need this for our analysis."),
    )

    # needs_tool: mutation, requires database query that isn't available
    _write(
        "needs_tool", "mutation",
        "database query required but no query tool is bound at runtime",
        {"outcome": "no_tool"},
        _out("no_tool",
             tried_tools=[],
             reason="This request requires a database query to fetch revenue by region, but no query tool is available.",
             _data_request="Can you query our data warehouse to get revenue by region for the last quarter?"),
        _out("success",
             synthesis="Regional revenue breakdown shows strong performance in EMEA and APAC.",
             sources=["Data warehouse"],
             _data_request="Can you query our data warehouse to get revenue by region for the last quarter?"),
    )

    # conflicting_figures: mutation, two conflicting figures from different surveys
    _write(
        "conflicting_figures", "mutation",
        "two conflicting figures in the request (8 MB vs 15 MB) that should be flagged",
        {"outcome": "success"},
        _out("success",
             synthesis="Survey A reports 8 MB typical memory usage, while Survey B reports 15 MB. There is a conflict between these measurements that needs investigation.",
             sources=["Survey A", "Survey B"],
             _data_request="What's the typical memory usage? Survey A says 8 MB, but Survey B says 15 MB."),
        _out("success",
             synthesis="The typical memory usage is approximately 12 MB based on available data.",
             sources=["Survey A", "Survey B"],
             _data_request="What's the typical memory usage? Survey A says 8 MB, but Survey B says 15 MB."),
    )


if __name__ == "__main__":
    generate()
