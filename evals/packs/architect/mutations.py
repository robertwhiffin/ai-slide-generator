"""Generate the architect pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload
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
    # #313: intent and slide-reference cases on the existing deck.
    "edit_polite_ordinal": "Could you make the second slide less wordy?",
    "edit_last_slide": (
        "Simplify the last slide: drop the stat cards and keep just the verdict "
        "and the call to action"
    ),
    "edit_multi_slide": "Slides 4-6 are too text-heavy; cut the wording on each by about half",
    "discuss_slide_question": "Why is the accessibility point on slide 7?",
}

# The cases whose payload carries the deck: the prior exchange, the gold spec and its slide count.
HAS_DECK = (
    "edit_request", "confirm_design", "discuss",
    "edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question",
)


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _payload(cid):
    has_deck = cid in HAS_DECK
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
    deck = case.gold_deck_spec() if has_deck else None
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if has_deck else []
    )
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": 10 if has_deck else 0,
        **slide_keys,
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


EDIT_BRIEF_1 = (
    "Explain that presentations are a primary vehicle for persuasion and decision-making, yet most "
    "are constrained by a 30-year-old format. Present three stat cards in place of the bullet list, "
    "one per common PowerPoint pain point: bloated file sizes (8–15 MB average), font substitution, "
    "and fixed-resolution layouts, with a callout noting the version-control headaches"
)


# Revised briefs for the #313 edit references (positions are 0-based; the messages speak 1-based).
POLITE_BRIEF_1 = (
    "State in one short line that presentations drive persuasion and decisions yet most are stuck "
    "in a 30-year-old format, then three terse bullets: font substitution, fixed-resolution "
    "layouts and bloated files (8–15 MB)"
)
LAST_BRIEF_9 = (
    "Deliver the final verdict in one line: HTML slides are the stronger format. No stat cards. "
    "End with the call to action: try an HTML slide framework for your next presentation"
)
# Gold position 9 promises "a visual scorecard", which the request removes.
LAST_PURPOSE_9 = "Closing slide — verdict and call to action"
MULTI_BRIEFS = {
    3: (
        "Show that HTML slides adapt fluidly to any screen size while PowerPoint locks content to "
        "a fixed canvas. Keep the chart-plus-commentary layout with the device rendering "
        "comparison, and cut the commentary to two short lines"
    ),
    4: (
        "Explain that CSS gives HTML slides precise, reliable typography with no font "
        "substitution, in three short bullets and a one-line callout"
    ),
    5: (
        "Show that HTML slides support live demos, embedded video and interactive charts natively "
        "in the browser, in three short bullets and a one-line callout"
    ),
}


def _revised_spec(
    deck: dict, briefs: dict[int, str], purposes: dict[int, str] | None = None
) -> dict:
    """``deck`` with only the named slides revised: ``briefs`` (and ``purposes``) by position."""
    spec = copy.deepcopy(deck)
    for field, revisions in (("content_brief", briefs), ("purpose", purposes or {})):
        for position, text in revisions.items():
            assert spec["slides"][position]["position"] == position
            spec["slides"][position][field] = text
    DeckSpec.model_validate(spec)  # fail fast
    return spec


def _slipped(reference: dict) -> dict:
    """``reference`` with every target position slipped by +1: the realistic 1-based slip."""
    bad = copy.deepcopy(reference)
    bad["target_positions"] = [p + 1 for p in reference["target_positions"]]
    ArchitectOutput.model_validate(bad)  # fail fast
    return bad


def _edited_deck_spec():
    """The gold deck spec with ONLY slide position 1's content_brief revised for the edit request."""
    return _revised_spec(case.gold_deck_spec(), {1: EDIT_BRIEF_1})


def _write(out, cid, kind, fault, expect, reference, should_fail):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", _payload(cid))
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    gold = case.gold_deck_spec()
    discuss = _out("discuss", "Happy to talk it through; what would you like to know?")

    _write(
        out, "build_request", "positive", "", {"intent": "build"},
        _out("build", "Here is a 10-slide deck arguing HTML slides beat PowerPoint.",
             deck_spec=gold),
        discuss,
    )
    _write(
        out, "edit_request", "mutation",
        "edit of slide 2 (position 1): a 1-based position slips off by one",
        {"intent": "edit", "positions": [1]},
        _out("edit", "I'll replace the bullet list on slide 2 with three stat cards.",
             target_positions=[1], deck_spec=_edited_deck_spec()),
        _out("edit", "I'll replace the bullet list on slide 2 with three stat cards.",
             target_positions=[2]),
    )
    _write(
        out, "ask_data", "mutation",
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
        out, "confirm_design", "mutation",
        "design switch must be proposed, not applied to deck_spec",
        {"intent": "confirm_design_contract"},
        _out("confirm_design_contract",
             "Do you want to switch this deck to the Acme design system? "
             "Every slide will be rebuilt in the new design.",
             proposed_design_contract={
                 "design_system_id": ACME_ID, "template_id": ACME_TEMPLATE,
             }),
        _out("edit", "Restyling the slides in the Acme design system now.",
             target_positions=[0]),
    )
    _write(
        out, "discuss", "positive", "", {"intent": "discuss"},
        _out("discuss",
             "Reveal.js is a general HTML presentation framework; Slidev is "
             "Markdown-first and aimed at developers."),
        _out("build", "Here is a deck comparing Reveal.js and Slidev.", deck_spec=gold),
    )

    # #313: intent and slide-reference cases on the same deck.
    _write(
        out, "edit_polite_ordinal", "mutation",
        "a polite question with an ordinal is still an edit request: act on position 1, do not ask",
        {"intent": "edit", "positions": [1]},
        _out("edit", "I'll cut the second slide down to one short line and three terse bullets.",
             target_positions=[1], deck_spec=_revised_spec(gold, {1: POLITE_BRIEF_1})),
        _out("discuss",
             "Happy to tighten it. Which parts of the second slide feel too wordy to you?"),
    )
    last_reference = _out(
        "edit", "I'll simplify the last slide to the verdict and the call to action.",
        target_positions=[9],
        deck_spec=_revised_spec(gold, {9: LAST_BRIEF_9}, {9: LAST_PURPOSE_9}),
    )
    _write(
        out, "edit_last_slide", "mutation",
        "edit of the last slide of ten (position 9): a 1-based position slips off by one",
        {"intent": "edit", "positions": [9]},
        last_reference, _slipped(last_reference),
    )
    multi_reference = _out(
        "edit",
        "I'll cut the wording on slides 4, 5 and 6 by about half and keep each slide's layout.",
        target_positions=[3, 4, 5], deck_spec=_revised_spec(gold, MULTI_BRIEFS),
    )
    _write(
        out, "edit_multi_slide", "mutation",
        "edit of slides 4-6 (positions 3, 4, 5): a 1-based range slips every position off by one",
        {"intent": "edit", "positions": [3, 4, 5]},
        multi_reference, _slipped(multi_reference),
    )
    _write(
        out, "discuss_slide_question", "mutation",
        "a question that names slide 7 is a discuss turn: answer it, do not rework slide 7",
        {"intent": "discuss"},
        _out("discuss",
             "Slide 7 is the fourth evidence beat: after responsiveness, typography and "
             "interactivity, it shows that HTML is accessible by design, and it sets up the "
             "collaboration beat on slide 8. I can move or reword it if you like."),
        _out("edit", "I'll rework the accessibility point on slide 7.", target_positions=[6]),
    )


if __name__ == "__main__":
    generate()
