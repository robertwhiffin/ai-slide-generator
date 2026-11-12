"""Generate the data analyst's data-tools case set (agent-mode MCP and Genie Agents, Task 8a).
Idempotent.

Three cases, kept apart from the analyst's train and held-out sets in
``evals/packs/data_analyst/cases_data_tools/`` (``case.case_set_dir``), each with the usual four
files and ``expect.outcome: success``. They run with ``data_tools: true`` (the harness binds a fake
Genie One ``genie``, a fake Sales Genie Agent ``genie_agent_sales`` and a fake web search
``you-search``) and measure which tool the analyst asks FIRST, scored by ``scorers.data_tool_score``:

* ``fits_genie_agent``: revenue by region fits the Sales Genie Agent: ``genie_agent_sales``, asked
  in plain business language (``no_sql``);
* ``outside_genie_agent``: support-ticket volumes are outside the Sales agent: ``genie``;
* ``web_fact``: a public market-size estimate: ``you-search``.

The analyst judge sees the request and the answer, never the tool record, so a should_fail is a
different outcome from the reference.

Run: ``python -m evals.packs.data_analyst.data_tools``. Sweep: ``python -m evals.run_eval --agent
data_analyst --config evals/configs/data_analyst/multi-source-tools.yaml --case-set data_tools``.
"""
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.packs.data_analyst import mutations as m

AGENT = m.AGENT
CASE_SET = "data_tools"
CASES_DIR = case.case_set_dir(AGENT, CASE_SET)


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR

    request = "What was our revenue by region last quarter?"
    m._write(
        out, "fits_genie_agent", "positive", "",
        {"outcome": "success", "first_tool": "genie_agent_sales", "no_sql": True},
        m._out("success",
               synthesis="The request asks for last quarter's revenue by region; it states no "
                         "figures of its own.",
               sources=["The request"],
               _data_request=request),
        m._out("no_tool",
               reason="No tool or data source applies to a revenue question.",
               _data_request=request),
    )

    request = "How many support tickets were opened each month this year?"
    m._write(
        out, "outside_genie_agent", "positive", "",
        {"outcome": "success", "first_tool": "genie"},
        m._out("success",
               synthesis="The request asks for the number of support tickets opened each month "
                         "this year; it states no figures of its own.",
               sources=["The request"],
               _data_request=request),
        m._out("missing_data",
               gap="No support ticket data was found",
               _data_request=request),
    )

    request = "What is the estimated global market size for CRM software?"
    m._write(
        out, "web_fact", "positive", "",
        {"outcome": "success", "first_tool": "you-search"},
        m._out("success",
               synthesis="The request asks for an estimate of the global CRM software market "
                         "size; it states no figures of its own.",
               sources=["The request"],
               _data_request=request),
        m._out("no_tool",
               reason="No tool can fetch a public market-size estimate, and the request does "
                      "not state one.",
               _data_request=request),
    )


if __name__ == "__main__":
    generate()
