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
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate():
    """Generate all 5 cases idempotently."""

    # figures_inline: positive, user provides StatCounter 98% figure
    _write(
        "figures_inline", "positive", "", {"outcome": "success"},
        _out("success",
             synthesis="Device render stats show 98% support across major browsers (StatCounter data).",
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
             synthesis="Memory usage varies significantly: 8–15 MB on some platforms (source A), under 1 MB on optimized builds (source B).",
             sources=["Platform analysis", "Build optimization report"],
             _data_request="How much memory does the application use? I've heard 8–15 MB typical, but also under 1 MB in some configurations."),
        _out("missing_data",
             gap="Memory requirements not documented",
             _data_request="How much memory does the application use? I've heard 8–15 MB typical, but also under 1 MB in some configurations."),
    )

    # missing_data: mutation, asks for data with specific constraints (no digits except 2023)
    _write(
        "missing_data", "mutation",
        "request for metrics not in the available data sources",
        {"outcome": "missing_data"},
        _out("missing_data",
             gap="Monthly active users data for presentations built with Reveal.js since 2023 is not available in current data sources.",
             _data_request="How many monthly active users have viewed presentations built with Reveal.js since 2023? We need this for our analysis."),
        _out("success",
             synthesis="Data indicates strong adoption of Reveal.js-based presentations.",
             sources=["Analytics"],
             _data_request="How many monthly active users have viewed presentations built with Reveal.js since 2023? We need this for our analysis."),
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
