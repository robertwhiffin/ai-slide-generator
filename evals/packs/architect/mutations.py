"""Generate the architect pack's cases from the Meridian gold deck. Idempotent."""
import json

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.services.agent_model_payload import model_payload_for
from src.services.template_sections import section_inventory

from evals.harness import case

AGENT = "architect"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"
LAYOUT = case.MERIDIAN_DIR / "bundle" / "templates" / "standard" / "index.html"

MERIDIAN_ID, MERIDIAN_TEMPLATE = 3, 5
ACME_ID, ACME_TEMPLATE = 4, 7

LIBRARY = [
    {
        "design_system_id": MERIDIAN_ID,
        "name": "Meridian Test Design System",
        "description": "Teal-led corporate design system used as the gold fixture.",
        "is_default": True,
        "templates": [{
            "template_id": MERIDIAN_TEMPLATE,
            "name": "Meridian Standard",
            "description": "Standard Meridian slide template.",
        }],
    },
    {
        "design_system_id": ACME_ID,
        "name": "Acme Test Design System",
        "description": "Synthetic second design system, a switch target for the eval.",
        "is_default": False,
        "templates": [{
            "template_id": ACME_TEMPLATE,
            "name": "Acme Standard",
            "description": "Standard Acme slide template.",
        }],
    },
]

PRIOR_USER = "Build a deck arguing HTML slides beat PowerPoint"
PRIOR_ASSISTANT = (
    "I've drafted a 10-slide deck arguing that HTML slides beat PowerPoint, "
    "and the slides are built."
)

MESSAGES = {
    "build_request": "Build a deck arguing HTML slides beat PowerPoint",
    "edit_request": "On slide 2, replace the bullet list with three stat cards",
    "ask_data": "Build a deck on our Q3 revenue by region, compared with Q2",
    "confirm_design": "Switch this deck to the Acme design system",
    "discuss": "What's the difference between Reveal.js and Slidev?",
}


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _payload(cid):
    has_deck = cid in ("edit_request", "confirm_design", "discuss")
    msg = MESSAGES[cid]
    conversation = [{"role": "user", "content": msg}]
    if has_deck:
        conversation = [
            {"role": "user", "content": PRIOR_USER},
            {"role": "assistant", "content": PRIOR_ASSISTANT},
            {"role": "user", "content": msg},
        ]
    contract = DesignContractRef(
        design_system_id=MERIDIAN_ID, template_id=MERIDIAN_TEMPLATE
    ).model_dump(mode="json")
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": case.gold_deck_spec() if has_deck else None,
        "committed_slide_count": 10 if has_deck else 0,
        "previous_deck_review": None,
        "available_design_contract": contract,
        "template_sections": section_inventory(LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": LIBRARY,
    })


def _out(intent, message, **kw):
    out = {
        "intent": intent, "message": message, "deck_spec": None,
        "data_request": None, "target_positions": [], "proposed_design_contract": None,
    }
    out.update(kw)
    ArchitectOutput.model_validate(out)  # fail fast
    return out


def _write(cid, kind, fault, expect, reference, should_fail):
    d = CASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", _payload(cid))
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate():
    gold = case.gold_deck_spec()
    discuss = _out("discuss", "Happy to talk it through; what would you like to know?")

    _write(
        "build_request", "positive", "", {"intent": "build"},
        _out("build", "Here is a 10-slide deck arguing HTML slides beat PowerPoint.",
             deck_spec=gold),
        discuss,
    )
    _write(
        "edit_request", "mutation",
        "edit of slide 2 (position 1): a 1-based position slips off by one",
        {"intent": "edit", "positions": [1]},
        _out("edit", "I'll replace the bullet list on slide 2 with three stat cards.",
             target_positions=[1]),
        _out("edit", "I'll replace the bullet list on slide 2 with three stat cards.",
             target_positions=[2]),
    )
    _write(
        "ask_data", "mutation",
        "deck on the user's own Q3 revenue with no data available",
        {"intent": "ask_data"},
        _out("ask_data", "I need your Q3 and Q2 revenue by region before I can build this.",
             data_request={
                 "metric": "revenue", "time_bound": "Q3 and Q2",
                 "grouping": "region", "units": None, "tool_preferences": [],
             }),
        _out("build", "Here is a deck on your Q3 revenue.", deck_spec=gold),
    )
    _write(
        "confirm_design", "mutation",
        "design switch must be proposed, not applied to deck_spec",
        {"intent": "confirm_design_contract"},
        _out("confirm_design_contract",
             "Do you want to switch this deck to the Acme design system?",
             proposed_design_contract={
                 "design_system_id": ACME_ID, "template_id": ACME_TEMPLATE,
             }),
        _out("edit", "Restyling the slides in the Acme design system now.",
             target_positions=[0]),
    )
    _write(
        "discuss", "positive", "", {"intent": "discuss"},
        _out("discuss",
             "Reveal.js is a general HTML presentation framework; Slidev is "
             "Markdown-first and aimed at developers."),
        _out("build", "Here is a deck comparing Reveal.js and Slidev.", deck_spec=gold),
    )


if __name__ == "__main__":
    generate()
