"""Generate the architect pack's HELD-OUT cases from the deck-2 gold fixture. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DesignContractRef
from src.domain.slide_numbering import architect_slide_payload
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
    # #313: intent and slide-reference cases on deck 2.
    "edit_polite_ordinal": (
        "Would you mind making the 4th slide lead with the 3-5 iteration rounds?"
    ),
    "edit_last_slide": "The final slide should open with the call to action, before the checklist",
    "edit_multi_slide": "Slides 2 and 3 are too dense — drop the callouts on both",
    "discuss_slide_question": "Why does slide 2 come before the techniques?",
    # #314: add a slide to deck 2.
    "add_slide_anchor": (
        "Could you add a slide before slide 5 with a worked before-and-after prompt example?"
    ),
    "add_slide_end": "Add one more slide at the end with a glossary of the prompt terms",
    "add_slide_as_number": "Add a new fourth slide on common prompt anti-patterns",
    "add_slide_and_revise": (
        "Add a slide after slide 3 on versioning prompts, and add it to the checklist on the "
        "final slide"
    ),
}

# The cases whose payload carries the deck: the prior exchange, the gold spec and its slide count.
HAS_DECK = (
    "edit_request", "confirm_design", "discuss",
    "edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question",
    "add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise",
)

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
    deck = case.gold_deck_spec(DECK) if has_deck else None
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if has_deck else []
    )
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": 6 if has_deck else 0,
        **slide_keys,
        "previous_deck_review": None,
        "available_design_contract": contract,
        "template_sections": section_inventory(m.LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": m.LIBRARY,
    })


# Revised briefs for the #313 edit references (positions are 0-based; the messages speak 1-based).
# No held-out target slide's purpose changes.
POLITE_BRIEF_3 = (
    "Three-stat card slide that leads with typical iteration cycles to production quality "
    "(3-5 rounds) as the headline stat, followed by token cost reduction (30-50%) and output "
    "consistency improvement (up to 40%)"
)
LAST_BRIEF_5 = (
    "Bullet slide that opens with the call to action — adopt this checklist for every new LLM "
    "feature starting this sprint — and then presents the five-item prompt optimisation checklist "
    "(define task scope, choose patterns, write eval criteria, run test suite, document winning "
    "prompt)"
)
MULTI_BRIEFS = {
    1: (
        "Bullet slide listing the three pain points of unoptimised prompts — inconsistent outputs, "
        "wasted tokens/cost, and slow iteration — with no callout"
    ),
    2: (
        "Bullet slide covering the four key patterns — system-prompt framing, few-shot examples, "
        "chain-of-thought reasoning, and structured output formatting — with no callout"
    ),
}


# #314: the new slides, by case (deck 2). ``m._inserted_spec`` adds the position and the empty
# data / slide-type / template-section fields.
ANCHOR_SLIDE = {
    "purpose": "Make the techniques concrete with one worked example",
    "content_brief": (
        "Two-column slide with an ad-hoc prompt on the left and its optimised version on the "
        "right, labelling where system-prompt framing, a few-shot example and a structured "
        "output format were applied"
    ),
    "assumes": (
        "Audience has seen the measured gains and wants to see what a better prompt looks like"
    ),
    "hands_off": "Applying the patterns to one real prompt is quick and visibly improves it",
}
# The judge-only calibration: right place and right targets, but a slide nobody asked for.
OFF_REQUEST_SLIDE = {
    "purpose": "Point the team at upcoming AI conferences",
    "content_brief": (
        "Bullet slide listing three upcoming AI conferences the team could attend, with dates "
        "and locations"
    ),
}
END_SLIDE = {
    "purpose": "Appendix — a glossary of the prompt terms used in the deck",
    "content_brief": (
        "Two-column glossary defining system prompt, few-shot example, chain-of-thought, "
        "structured output, eval criteria and test suite in one line each"
    ),
    "assumes": "Audience has heard each term during the talk",
    "hands_off": "Everyone leaves with the same vocabulary for prompt work",
}
AS_NUMBER_SLIDE = {
    "purpose": "Warn against the habits that undo prompt optimisation",
    "content_brief": (
        "Bullet slide listing four common prompt anti-patterns — vague instructions, "
        "contradictory constraints, examples that leak the answer, and unbounded output — each "
        "with a one-line fix"
    ),
    "assumes": "Audience knows the four core patterns from the previous slide",
    "hands_off": "Most bad outputs come from a handful of avoidable prompt habits",
}
AND_REVISE_SLIDE = {
    "purpose": "Show how to keep prompts under version control",
    "content_brief": (
        "Bullet slide explaining that every prompt change gets a version, a change note and a "
        "link to its eval results, so a regression can be traced and rolled back"
    ),
    "assumes": "Audience knows the four core patterns and that prompts change often",
    "hands_off": "A versioned prompt can be compared, reviewed and rolled back like code",
}
# The one revision, by wording: the gold checklist brief (gold position 5) with this phrase swapped.
CHECKLIST_ITEMS = (
    "five-item prompt optimisation checklist (define task scope, choose patterns, write eval "
    "criteria,",
    "six-item prompt optimisation checklist (define task scope, choose patterns, version every "
    "prompt, write eval criteria,",
)


def _checklist_brief(deck: dict, position: int) -> str:
    old, new = CHECKLIST_ITEMS
    brief = deck["slides"][position]["content_brief"]
    assert brief.count(old) == 1, position
    return brief.replace(old, new)


def _edited_deck_spec():
    """The deck-2 spec with ONLY slides[2].content_brief revised for the edit request."""
    return m._revised_spec(case.gold_deck_spec(DECK), {EDIT_POS: EDIT_BRIEF})


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

    # #313: intent and slide-reference cases on the same deck.
    _write(
        out, "edit_polite_ordinal", "mutation",
        "a polite question with an ordinal is still an edit request: act on position 3, do not ask",
        {"intent": "edit", "positions": [3]},
        m._out("edit", "I'll make the iteration rounds the headline stat on the fourth slide.",
               target_positions=[3], deck_spec=m._revised_spec(gold, {3: POLITE_BRIEF_3})),
        m._out("discuss",
               "Sure. Should the iteration figure replace the slide title or sit above the other "
               "stats?"),
    )
    last_reference = m._out(
        "edit",
        "I'll move the call to action to the top of the final slide, ahead of the checklist.",
        target_positions=[5], deck_spec=m._revised_spec(gold, {5: LAST_BRIEF_5}),
    )
    _write(
        out, "edit_last_slide", "mutation",
        "edit of the final slide of six (position 5): a 1-based position slips off by one",
        {"intent": "edit", "positions": [5]},
        last_reference, m._slipped(last_reference),
    )
    multi_reference = m._out(
        "edit", "I'll drop the callouts on slides 2 and 3.",
        target_positions=[1, 2], deck_spec=m._revised_spec(gold, MULTI_BRIEFS),
    )
    _write(
        out, "edit_multi_slide", "mutation",
        "edit of slides 2 and 3 (positions 1, 2): a 1-based list slips every position off by one",
        {"intent": "edit", "positions": [1, 2]},
        multi_reference, m._slipped(multi_reference),
    )
    _write(
        out, "discuss_slide_question", "mutation",
        "a question that names slide 2 is a discuss turn: answer it, do not move slide 2",
        {"intent": "discuss"},
        m._out("discuss",
               "Slide 2 sets out what ad-hoc prompting costs, so the four techniques on slide 3 "
               "land as the answer to a problem the audience already feels. I can swap them if "
               "you prefer."),
        m._out("edit", "I'll move slide 2 after the techniques.", target_positions=[1]),
    )

    # #314: add a slide to the same deck. ``positions`` and ``inserted`` are in the revised
    # deck's numbering; the references are the gold spec with the new slide spliced in.
    anchor = m._out(
        "edit",
        "I'll add a new slide 5 with a worked before-and-after prompt example, just before the "
        "workflow slide.",
        target_positions=[4], deck_spec=m._inserted_spec(gold, {4: ANCHOR_SLIDE}),
    )
    _write(
        out, "add_slide_anchor", "mutation",
        "add before slide 5 (position 4): the new slide takes position 4, only it is built, and "
        "the old slide 5 shifts unchanged",
        {"intent": "edit", "positions": [4], "inserted": [4]},
        anchor,
        m._retargeted(
            anchor, [4], m._inserted_spec(gold, {4: {**ANCHOR_SLIDE, **OFF_REQUEST_SLIDE}})
        ),
    )
    end = m._out(
        "edit", "I'll add a glossary of the prompt terms as a new final slide, slide 7.",
        target_positions=[6], deck_spec=m._inserted_spec(gold, {6: END_SLIDE}),
    )
    _write(
        out, "add_slide_end", "mutation",
        "add a final slide to a deck of six (new slide at position 6): append it; replacing the "
        "last slide (position 5) loses the closing slide",
        {"intent": "edit", "positions": [6], "inserted": [6]},
        end,
        m._retargeted(end, [5], m._replaced_spec(gold, {5: END_SLIDE})),
    )
    as_number = m._out(
        "edit",
        "I'll add a new slide 4 on common prompt anti-patterns; the impact slide moves to slide 5.",
        target_positions=[3], deck_spec=m._inserted_spec(gold, {3: AS_NUMBER_SLIDE}),
    )
    _write(
        out, "add_slide_as_number", "mutation",
        "a new fourth slide (position 3): it takes position 3 and the old slide 4 shifts up, one "
        "place late is wrong",
        {"intent": "edit", "positions": [3], "inserted": [3]},
        as_number,
        m._retargeted(as_number, [4], m._inserted_spec(gold, {4: AS_NUMBER_SLIDE})),
    )
    and_revise = m._out(
        "edit",
        "I'll add slide 4 on versioning prompts after slide 3, and add versioning to the "
        "checklist on the final slide, now slide 7.",
        target_positions=[3, 6],
        deck_spec=m._inserted_spec(gold, {3: AND_REVISE_SLIDE}, {6: _checklist_brief(gold, 5)}),
    )
    _write(
        out, "add_slide_and_revise", "mutation",
        "add after slide 3 (position 2): the new slide is position 3 and the checklist on the "
        "final slide (now position 6) must be revised to include it",
        {"intent": "edit", "positions": [3, 6], "inserted": [3]},
        and_revise,
        m._retargeted(and_revise, [3], m._inserted_spec(gold, {3: AND_REVISE_SLIDE})),
    )


if __name__ == "__main__":
    generate()
