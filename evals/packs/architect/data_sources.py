"""Generate the architect's data-source case set (agent-mode MCP and Genie Agents, Task 8a).
Idempotent.

Four cases, kept apart from the architect's train and held-out sets in
``evals/packs/architect/cases_data_sources/`` (``case.case_set_dir``), each with the usual four
files. The architect's payload carries ``data_sources``, the data agents the analyst has (Genie One,
each Genie Agent, each MCP server); the cases measure what the architect does with that list:

* ``genie_agent_listed_needs_figures``: Genie One and a "Sales" Genie Agent are listed, and a new
  deck needs regional sales figures: ``ask_data``;
* ``no_sources_needs_figures``: the same request with no data sources: ``build`` (the message names
  the data that would help);
* ``write_request_refused``: a seeded deck, and the user asks Tellr to post its summary to Slack:
  ``discuss`` (Tellr makes no changes in other systems);
* ``sources_listed_no_data_needed``: Genie One is listed, and the user retitles slide 2: ``edit``
  of position 1.

The judge sees only ``message`` and ``current_deck_spec`` of the payload, never ``data_sources``,
so each reference and should_fail differs in intent AND in a ``message`` that names what is asked
for or refused. Every payload goes through ``model_payload_for``, and the generator asserts that
``data_sources`` survived it (a projection that strips the key stops generation).

Run: ``python -m evals.packs.architect.data_sources``. Calibrate: ``python -m evals.run_eval
--agent architect --calibrate --case-set data_sources``.
"""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.packs.architect.image_tool import (
    LAYOUT,
    LIBRARY,
    PRIOR_ASSISTANT,
    PRIOR_USER,
    _contract,
    _out,
    _slide_spec,
    seeded_deck,
)
from src.domain.deck_spec import DeckSpec
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import model_payload_for
from src.services.graph.nodes import GENIE_ONE_DATA_SOURCE
from src.services.template_sections import section_inventory

AGENT = "architect"
CASE_SET = "data_sources"
CASES_DIR = case.case_set_dir(AGENT, CASE_SET)

SALES_SOURCE = {
    "name": "Sales",
    "description": "Regional sales by month: revenue, units and orders per region",
}
FIGURES_MESSAGE = "Build me a deck on our regional sales performance, with revenue by region"
WRITE_MESSAGE = "Post a summary of this deck to the #announcements channel in Slack"
RETITLE_MESSAGE = "Retitle slide 2 to 'A Passkey Cannot Be Phished'"
NEW_TITLE = "A Passkey Cannot Be Phished"

CASE_IDS = (
    "genie_agent_listed_needs_figures",
    "no_sources_needs_figures",
    "write_request_refused",
    "sources_listed_no_data_needed",
)
NEW_DECK = CASE_IDS[:2]

MESSAGES = {
    CASE_IDS[0]: FIGURES_MESSAGE,
    CASE_IDS[1]: FIGURES_MESSAGE,
    CASE_IDS[2]: WRITE_MESSAGE,
    CASE_IDS[3]: RETITLE_MESSAGE,
}


def _data_sources(cid: str) -> list[dict]:
    return {
        CASE_IDS[0]: [dict(GENIE_ONE_DATA_SOURCE), dict(SALES_SOURCE)],
        CASE_IDS[1]: [],
        CASE_IDS[2]: [dict(GENIE_ONE_DATA_SOURCE)],
        CASE_IDS[3]: [dict(GENIE_ONE_DATA_SOURCE)],
    }[cid]


def _payload(cid: str) -> dict:
    msg = MESSAGES[cid]
    deck = None if cid in NEW_DECK else seeded_deck()
    conversation = [{"role": "user", "content": msg}]
    if deck is not None:
        conversation = [
            {"role": "user", "content": PRIOR_USER},
            {"role": "assistant", "content": PRIOR_ASSISTANT},
            {"role": "user", "content": msg},
        ]
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if deck else [])
    payload = model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": len(deck["slides"]) if deck else 0,
        **slide_keys,
        "previous_deck_review": None,
        "available_design_contract": _contract(),
        "template_sections": section_inventory(LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": LIBRARY,
        "deck_style_context": case.meridian_deck_style_context(),
        "data_sources": _data_sources(cid),
    })
    assert "data_sources" in payload, f"{cid}: model_payload_for dropped data_sources"
    return payload


_SALES_SLIDES = [
    ("Open the review and frame the question: where is regional sales performance strong?",
     "Title slide with the deck title 'Regional Sales Performance' and a subtitle saying that "
     "revenue differs by region and the review shows where"),
    ("Show revenue by region",
     "A chart-plus-commentary slide comparing revenue by region, with a one-line takeaway on "
     "the strongest and weakest region. Revenue figures are to be supplied"),
    ("Show how each region moves month by month",
     "Three bullets on the monthly pattern per region, with a callout on the region that moves "
     "most. Monthly figures are to be supplied"),
    ("Draw out what the regional differences mean",
     "Three short bullets on what the differences imply for focus and investment"),
    ("Close with a clear ask",
     "Ask the leadership team to agree one action per region for next quarter"),
]


def _sales_deck(gap: str) -> dict:
    deck = {
        "title": "Regional Sales Performance",
        "audience": "The sales leadership team",
        "purpose": "Review regional sales performance and agree one action per region",
        "argument": (
            "Revenue differs by region and month, and seeing the differences side by side shows "
            "where to focus next quarter"
        ),
        "call_to_action": "Agree one action per region for next quarter",
        "narrative_arc": [
            "Frame the question",
            "Show revenue by region",
            "Show the monthly pattern",
            "Draw out what it means",
            "Close with a clear ask",
        ],
        "design_contract": _contract(),
        "resolved_data": {"synthesis": "", "figures": [], "gaps": [gap]},
        "slides": [
            _slide_spec(i, purpose, brief, "The audience knows its own regions",
                        "The regional picture builds toward one action each")
            for i, (purpose, brief) in enumerate(_SALES_SLIDES)
        ],
    }
    DeckSpec.model_validate(deck)  # fail fast
    return deck


def _retitled_slide() -> dict:
    slide = {k: v for k, v in copy.deepcopy(seeded_deck()["slides"][1]).items() if k != "position"}
    slide["content_brief"] = f"Title the slide '{NEW_TITLE}'. " + slide["content_brief"]
    return slide


def _cases() -> dict[str, tuple[str, dict, dict, dict]]:
    """Each case: (fault, expect, reference, should_fail)."""
    gap = "No regional sales figures are connected: revenue by region and month"
    return {
        CASE_IDS[0]: (
            "a Genie Agent for sales is listed and the new deck needs regional sales figures: "
            "ask for the data, do not build a deck around figures that do not exist",
            {"intent": "ask_data"},
            _out("ask_data",
                 "I need your sales revenue by region, by month, before I can build this deck.",
                 data_request={
                     "metric": "revenue", "time_bound": "by month", "grouping": "region",
                     "units": None, "tool_preferences": []}),
            _out("build",
                 "Here is a 5-slide deck on your regional sales performance, with revenue by "
                 "region.",
                 deck_spec=_sales_deck(gap)),
        ),
        CASE_IDS[1]: (
            "no data source is listed: build the deck now and say which data would help, rather "
            "than asking for data nothing can fetch",
            {"intent": "build"},
            _out("build",
                 "Here is a 5-slide deck on your regional sales performance. No data source is "
                 "connected, so the figures are left to fill in. Connecting a source with revenue "
                 "by region and by month would help.",
                 deck_spec=_sales_deck(gap)),
            _out("ask_data",
                 "I need your sales revenue by region, by month, before I can build this deck.",
                 data_request={
                     "metric": "revenue", "time_bound": "by month", "grouping": "region",
                     "units": None, "tool_preferences": []}),
        ),
        CASE_IDS[2]: (
            "a request to act in another system (post to Slack): refuse in the message, change "
            "nothing in the deck",
            {"intent": "discuss"},
            _out("discuss",
                 "I can't post to Slack: Tellr does not make changes in other systems. I can "
                 "write the summary here for you to copy into the #announcements channel. Would "
                 "you like that?"),
            _out("edit", "I've posted a summary of this deck to the #announcements channel in "
                 "Slack.", target_positions=[0]),
        ),
        CASE_IDS[3]: (
            "data sources are listed but the edit needs no data: retitle slide 2 (position 1) "
            "without asking for any",
            {"intent": "edit", "positions": [1]},
            _out("edit", f"I've retitled slide 2 '{NEW_TITLE}'.", target_positions=[1],
                 operations=[{"op": "update", "position": 1, "slides": [_retitled_slide()]}]),
            _out("ask_data",
                 "I need to pull some data from your sales tools before I can retitle slide 2.",
                 data_request={
                     "metric": "revenue", "time_bound": None, "grouping": None,
                     "units": None, "tool_preferences": []}),
        ),
    }


def _dump(path: pathlib.Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def generate(out_dir: pathlib.Path | None = None) -> None:
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    cases = _cases()
    assert tuple(cases) == CASE_IDS
    for cid, (fault, expect, reference, should_fail) in cases.items():
        payload = _payload(cid)  # asserts data_sources survived the projection
        d = out / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / "case.yaml").write_text(yaml.safe_dump({
            "kind": "mutation", "fault": fault, "expect": expect, "design_system_active": True,
        }, sort_keys=False))
        _dump(d / "payload.json", payload)
        _dump(d / "reference.json", reference)
        _dump(d / "calibration.json", {"should_fail": should_fail})


if __name__ == "__main__":
    generate()
