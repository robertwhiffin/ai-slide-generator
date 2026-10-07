"""Generate the architect pack's HELD-OUT cases from the deck-2 gold fixture. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import copy
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.services.agent_model_payload import model_payload_for
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.packs.architect import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"
EDIT_POS = 2

PRIOR_USER = "Build a deck arguing that structured prompt optimisation beats ad-hoc prompting"
PRIOR_ASSISTANT = (
    "I've drafted a 6-slide deck on prompt optimisation, and the slides are built."
)

MESSAGES = {
    "build_request": (
        "Build a deck for engineers and product teams arguing that structured prompt "
        "optimisation beats ad-hoc prompting"
    ),
    "edit_request": "On slide 3, show the four patterns as four cards instead of a bullet list",
    "ask_data": (
        "Build a deck on our team's measured prompt success rates by model over the last quarter"
    ),
    "confirm_design": "Can you re-theme this deck with the Acme design system instead?",
    "discuss": "When should I use few-shot examples rather than chain-of-thought prompting?",
}

EDIT_BRIEF = (
    "Four cards in place of the bullet list covering the four key patterns — system-prompt framing, "
    "few-shot examples, chain-of-thought reasoning, and structured output formatting — one pattern "
    "per card, with a callout on when to combine them"
)


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
        design_system_id=m.MERIDIAN_ID, template_id=m.MERIDIAN_TEMPLATE
    ).model_dump(mode="json")
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": case.gold_deck_spec(DECK) if has_deck else None,
        "committed_slide_count": 6 if has_deck else 0,
        "previous_deck_review": None,
        "available_design_contract": contract,
        "template_sections": section_inventory(m.LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": m.LIBRARY,
    })


HAS_DECK = ("edit_request", "confirm_design", "discuss")


def _edited_deck_spec():
    """The deck-2 spec with ONLY slides[2].content_brief revised for the edit request."""
    spec = copy.deepcopy(case.gold_deck_spec(DECK))
    assert spec["slides"][EDIT_POS]["position"] == EDIT_POS
    spec["slides"][EDIT_POS]["content_brief"] = EDIT_BRIEF
    DeckSpec.model_validate(spec)  # fail fast
    return spec


def _write(out, cid, kind, fault, expect, reference, should_fail):
    """Same as the train writer but with the held-out payload."""
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(m.yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    m._dump(d / "payload.json", _payload(cid))
    m._dump(d / "reference.json", reference)
    m._dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    gold = case.gold_deck_spec(DECK)
    discuss = m._out("discuss", "Happy to talk it through; what would you like to know?")

    _write(
        out, "build_request", "positive", "", {"intent": "build"},
        m._out("build", "Here is a 6-slide deck arguing that structured prompt optimisation "
                        "beats ad-hoc prompting.", deck_spec=gold),
        discuss,
    )
    edit_msg = "I'll show the four patterns on slide 3 as four cards instead of a bullet list."
    _write(
        out, "edit_request", "mutation",
        "edit of slide 3 (position 2): a 1-based position slips off by one",
        {"intent": "edit", "positions": [EDIT_POS]},
        m._out("edit", edit_msg, target_positions=[EDIT_POS], deck_spec=_edited_deck_spec()),
        m._out("edit", edit_msg, target_positions=[EDIT_POS + 1]),
    )
    _write(
        out, "ask_data", "mutation",
        "deck on the team's own prompt success rates with no data available",
        {"intent": "ask_data"},
        m._out("ask_data",
               "I need your measured prompt success rates by model for the last quarter "
               "before I can build this.",
               data_request={
                   "metric": "prompt success rate", "time_bound": "last quarter",
                   "grouping": "model", "units": None, "tool_preferences": [],
               }),
        m._out("build", "Here is a deck on your prompt success rates.", deck_spec=gold),
    )
    _write(
        out, "confirm_design", "mutation",
        "design switch must be proposed, not applied to deck_spec",
        {"intent": "confirm_design_contract"},
        m._out("confirm_design_contract",
               "Do you want to re-theme this deck with the Acme design system? "
               "Every slide will be rebuilt in the new design.",
               proposed_design_contract={
                   "design_system_id": m.ACME_ID, "template_id": m.ACME_TEMPLATE,
               }),
        m._out("edit", "Restyling the slides in the Acme design system now.",
               target_positions=[0]),
    )
    _write(
        out, "discuss", "positive", "", {"intent": "discuss"},
        m._out("discuss",
               "Few-shot examples work best when the output format or style is hard to describe; "
               "chain-of-thought helps when the task needs multi-step reasoning."),
        m._out("build", "Here is a deck comparing few-shot and chain-of-thought prompting.",
               deck_spec=gold),
    )


if __name__ == "__main__":
    generate()
