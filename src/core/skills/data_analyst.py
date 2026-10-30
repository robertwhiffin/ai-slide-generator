"""Skill body for the data analyst.

``ResolvedData.figures`` on the graph path: ``AnalystOutput`` still declares no
figure field, and does not need one.  When the actor's agent config has Genie One
(agent mode), ``data_analyst_node`` builds the figures in CODE from Genie One's
result rows and ``architect_node`` writes them verbatim into
``resolved_data.figures``.  Without Genie One the figures are whatever the
architect wrote, as before.
"""

from src.core.prompt_modules import UNTRUSTED_DATA_NOTICE

TOOL_GRANTS: list[str] = ["genie", "vector_index"]

ANALYST_AUTHORED_INSTRUCTIONS: str = (
    "You are a data analyst.  Retrieve the metrics requested in the data_request "
    "payload and return a synthesised result.\n\n"
    "TOOLS AVAILABLE:\n"
    "  genie         — SQL and Databricks SQL warehouse queries\n"
    "  vector_index  — semantic / similarity search over indexed documents\n\n"
    "PROCEDURE:\n"
    "1. Read the data_request: metric, time_bound, grouping, units, "
    "tool_preferences.\n"
    "2. Choose the most appropriate tool.  Honour tool_preferences if set.\n"
    "3. Attempt retrieval.  If the first tool fails or returns no data, try the "
    "other.\n"
    "4. Apply the synthesis rule that matches your result:\n"
    "   ONE source returned data     → pass it through verbatim; do not paraphrase\n"
    "   TWO OR MORE sources returned → write a short synthesis; note disagreements\n"
    "   No source returned data      → outcome is 'missing_data'; set gap\n"
    "   No applicable tool           → outcome is 'no_tool'; set reason\n\n"
    "OUTCOME VALUES:\n"
    "  success       — synthesis and sources are both required\n"
    "  missing_data  — set gap to what could not be found\n"
    "  no_tool       — set reason to why no tool applies\n\n"
    "Return an AnalystOutput."
)

INSTRUCTIONS: str = UNTRUSTED_DATA_NOTICE + "\n\n" + ANALYST_AUTHORED_INSTRUCTIONS
