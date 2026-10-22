"""Generate the architect pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.deck_spec_slides import spec_json_with_blank_entry
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
    # #314: add a slide to the existing deck.
    "add_slide_anchor": (
        "Add a slide after slide 3 that compares Reveal.js, Slidev and Marp side by side"
    ),
    "add_slide_end": "Add a final slide that lists the sources behind the evidence",
    "add_slide_as_number": "Insert a new slide 2 with an agenda for the talk",
    "add_slide_and_revise": (
        "Add a slide after slide 8 on offline use and security, and add it to the summary on the "
        "last slide"
    ),
    # #314 follow-up: the same deck with a manually inserted blank slide.
    "fill_blank_slide": (
        "Use slide 6 to show that one stylesheet restyles the whole deck, so a rebrand is a "
        "single edit"
    ),
    "edit_beside_blank": (
        "Trim slide 7 to live code demos, embedded video and interactive charts; drop the rest"
    ),
}

# The cases whose payload carries the deck: the prior exchange, the gold spec and its slide count.
HAS_DECK = (
    "edit_request", "confirm_design", "discuss",
    "edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question",
    "add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise",
    "fill_blank_slide", "edit_beside_blank",
)
# The cases whose deck holds a manually inserted blank slide, spliced in at BLANK_AT.
BLANK_CASES = ("fill_blank_slide", "edit_beside_blank")
BLANK_AT = 5


def _blank_deck(deck: dict, at: int) -> dict:
    """``deck`` with a blank slide inserted at ``at``, exactly as production persists it.

    The same splice as a manual insert: ``spec_json_with_blank_entry`` on the persisted spec
    column, which adds ``BLANK_DECK_SPEC_ENTRY`` and re-stamps every position.
    """
    spliced = json.loads(spec_json_with_blank_entry(json.dumps(deck), at))
    DeckSpec.model_validate(spliced)  # fail fast
    return spliced


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
    if cid in BLANK_CASES:
        deck = _blank_deck(deck, BLANK_AT)
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if has_deck else []
    )
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": len(deck["slides"]) if has_deck else 0,
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


# #314: the new slides, by case. Each is the text of one SlideSpec; ``_inserted_spec`` adds the
# position and the empty data / slide-type / template-section fields.
ANCHOR_SLIDE = {
    "purpose": "Compare the leading HTML slide frameworks side by side",
    "content_brief": (
        "Comparison table of Reveal.js, Slidev and Marp across authoring format, interactivity, "
        "theming and export options, one column per framework"
    ),
    "assumes": "The audience has just met HTML slides and heard the leading frameworks named",
    "hands_off": "Whichever framework a team picks, the case for HTML slides holds",
}
# The judge-only calibration: right place and right targets, but a slide nobody asked for.
OFF_REQUEST_SLIDE = {
    "purpose": "Recount the history of PowerPoint",
    "content_brief": (
        "Timeline of PowerPoint releases from 1987 to today, one milestone per version"
    ),
}
END_SLIDE = {
    "purpose": "Appendix — the sources behind the evidence",
    "content_brief": (
        "Bulleted list of the sources behind the five evidence beats, one line per beat: "
        "responsiveness, typography, interactivity, accessibility and collaboration"
    ),
    "assumes": "The audience has heard the verdict and may want to check the evidence",
    "hands_off": "Every claim in the deck can be traced to a source",
}
AS_NUMBER_SLIDE = {
    "purpose": "Set out the agenda for the talk",
    "content_brief": (
        "Agenda slide listing the five narrative beats in order: why the tool matters, "
        "PowerPoint's limits, the evidence for HTML slides, the objections, and the verdict"
    ),
    "assumes": "The audience has seen the title and knows the topic",
    "hands_off": "The talk moves from the problem, through the evidence, to a verdict",
}
AND_REVISE_SLIDE = {
    "purpose": "Evidence beat 6 — Offline use and security",
    "content_brief": (
        "Show that HTML slides run offline as one self-contained file and can be served from an "
        "access-controlled internal site, with no macros or embedded executables, as three short "
        "bullets and a callout"
    ),
    "assumes": "The audience has seen the collaboration and distribution advantages",
    "hands_off": "HTML slides are safe to share and work without a network",
}
# The one revision, by wording: the gold summary brief (gold position 9) with this phrase swapped.
SUMMARY_DIMENSIONS = (
    "five advantage dimensions — responsiveness, typography, interactivity, accessibility, "
    "collaboration —",
    "six advantage dimensions — responsiveness, typography, interactivity, accessibility, "
    "collaboration, and offline use and security —",
)

# #314 follow-up (manual insert): the blank-slide cases. The payload deck is the gold spec with a
# manually inserted blank at BLANK_AT, so gold positions 5..9 shift to 6..10 and the user's slide
# numbers count the blank. ``positions`` / ``inserted: []`` are in that blank deck's numbering.
BESIDE_POS = BLANK_AT + 1  # the slide edit_beside_blank names: just after the blank
# fill_blank_slide's reference: the blank filled in place with these text fields.
FILLED_SLIDE = {
    "purpose": "Theming — one stylesheet restyles the whole deck",
    "content_brief": (
        "Show that one CSS stylesheet sets the colours, fonts and spacing of every slide, so a "
        "rebrand is a single edit, where PowerPoint needs each slide master and layout changed by "
        "hand. Three short bullets and a callout"
    ),
    "assumes": "The audience has just seen that CSS controls typography precisely",
    "hands_off": "With HTML slides, the whole deck's look lives in one place",
}
# edit_beside_blank's one revision: BESIDE_POS's brief with the first phrase swapped for the second.
BESIDE_REVISION = (
    "live code demos, embedded videos, interactive charts (D3, Chart.js), scroll-triggered "
    "animations, and audience polling",
    "live code demos, embedded videos and interactive charts (D3, Chart.js)",
)
# edit_beside_blank's should_fail fills the untouched blank with invented text.
INVENTED_FILL = {
    "purpose": "Bridge from design fidelity to interactivity",
    "content_brief": (
        "Transition slide with one line linking precise typography to the interactive features "
        "that follow"
    ),
    "assumes": "The audience has seen the typography evidence",
    "hands_off": "Design fidelity is only half the story",
}

# Every new slide carries no data and no slide type or template section.
NEW_SLIDE_DEFAULTS = {"data_references": [], "slide_type": None, "template_section_index": None}


def _new_slide(position: int, fields: dict) -> dict:
    return {"position": position, **fields, **NEW_SLIDE_DEFAULTS}


def _inserted_spec(
    deck: dict, inserts: dict[int, dict], briefs: dict[int, str] | None = None
) -> dict:
    """``deck`` with new slides spliced in and every slide re-stamped to its index.

    ``inserts`` maps each new slide's FINAL position (its place in the returned deck) to its text
    fields; ``briefs`` maps a FINAL position to a revised ``content_brief``. Nothing else changes.
    """
    spec = copy.deepcopy(deck)
    slides = spec["slides"]
    for final in sorted(inserts):
        slides.insert(final, _new_slide(final, inserts[final]))
    for index, slide in enumerate(slides):
        slide["position"] = index
    for final, brief in (briefs or {}).items():
        slides[final]["content_brief"] = brief
    DeckSpec.model_validate(spec)  # fail fast
    return spec


def _replaced_spec(deck: dict, replacements: dict[int, dict]) -> dict:
    """``deck`` with the slides at the named positions replaced by new slides (count kept)."""
    spec = copy.deepcopy(deck)
    for position, fields in replacements.items():
        spec["slides"][position] = _new_slide(position, fields)
    DeckSpec.model_validate(spec)  # fail fast
    return spec


def _retargeted(reference: dict, targets: list[int], deck_spec: dict | None = None) -> dict:
    """``reference`` with its ``target_positions`` (and, if given, its ``deck_spec``) replaced."""
    bad = copy.deepcopy(reference)
    bad["target_positions"] = list(targets)
    if deck_spec is not None:
        bad["deck_spec"] = deck_spec
    ArchitectOutput.model_validate(bad)  # fail fast
    return bad


def _summary_brief(deck: dict, position: int) -> str:
    """The brief at ``position`` with the dimensions phrase swapped for the six-dimension one."""
    old, new = SUMMARY_DIMENSIONS
    brief = deck["slides"][position]["content_brief"]
    assert brief.count(old) == 1, position
    return brief.replace(old, new)


def _beside_brief(deck: dict, position: int) -> str:
    """The brief at ``position`` with the interactivity phrase swapped for the trimmed one."""
    old, new = BESIDE_REVISION
    brief = deck["slides"][position]["content_brief"]
    assert brief.count(old) == 1, position
    return brief.replace(old, new)


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

    # #314: add a slide to the existing deck. ``positions`` and ``inserted`` are in the revised
    # deck's numbering; the references are the gold spec with the new slide spliced in.
    anchor = _out(
        "edit",
        "I'll add a new slide 4 comparing Reveal.js, Slidev and Marp side by side, straight "
        "after slide 3.",
        target_positions=[3], deck_spec=_inserted_spec(gold, {3: ANCHOR_SLIDE}),
    )
    _write(
        out, "add_slide_anchor", "mutation",
        "add after slide 3 (position 2): the new slide is position 3, only it is built, and the "
        "later slides shift unchanged",
        {"intent": "edit", "positions": [3], "inserted": [3]},
        anchor,
        _retargeted(anchor, [3], _inserted_spec(gold, {3: {**ANCHOR_SLIDE, **OFF_REQUEST_SLIDE}})),
    )
    end = _out(
        "edit", "I'll add a final slide, slide 11, listing the sources behind the evidence.",
        target_positions=[10], deck_spec=_inserted_spec(gold, {10: END_SLIDE}),
    )
    _write(
        out, "add_slide_end", "mutation",
        "add a final slide to a deck of ten (new slide at position 10): append it; replacing the "
        "last slide (position 9) loses the closing slide",
        {"intent": "edit", "positions": [10], "inserted": [10]},
        end,
        _retargeted(end, [9], _replaced_spec(gold, {9: END_SLIDE})),
    )
    as_number = _out(
        "edit",
        "I'll insert a new slide 2 with the agenda for the talk; the current slide 2 becomes "
        "slide 3.",
        target_positions=[1], deck_spec=_inserted_spec(gold, {1: AS_NUMBER_SLIDE}),
    )
    _write(
        out, "add_slide_as_number", "mutation",
        "insert a new slide 2 (position 1): the new slide takes position 1 and the old slide 2 "
        "shifts to position 2, one place late is wrong",
        {"intent": "edit", "positions": [1], "inserted": [1]},
        as_number,
        _retargeted(as_number, [2], _inserted_spec(gold, {2: AS_NUMBER_SLIDE})),
    )
    and_revise = _out(
        "edit",
        "I'll add slide 9 on offline use and security after slide 8, and add it to the summary "
        "on the last slide, now slide 11.",
        target_positions=[8, 10],
        deck_spec=_inserted_spec(gold, {8: AND_REVISE_SLIDE}, {10: _summary_brief(gold, 9)}),
    )
    _write(
        out, "add_slide_and_revise", "mutation",
        "add after slide 8 (position 7): the new slide is position 8 and the summary on the last "
        "slide (now position 10) must be revised to include it; the gold narrative_arc lists five "
        "dimensions and must stay unchanged",
        {"intent": "edit", "positions": [8, 10], "inserted": [8]},
        and_revise,
        _retargeted(and_revise, [8], _inserted_spec(gold, {8: AND_REVISE_SLIDE})),
    )

    # #314 follow-up (manual insert): the same deck with a blank slide at BLANK_AT. The references
    # leave every other slide exactly as the payload has it (the blank included, unless filled).
    blank_deck = _blank_deck(gold, BLANK_AT)
    fill = _out(
        "edit", "I'll use the blank slide 6 to show that one stylesheet restyles the whole deck.",
        target_positions=[BLANK_AT], deck_spec=_replaced_spec(blank_deck, {BLANK_AT: FILLED_SLIDE}),
    )
    _write(
        out, "fill_blank_slide", "mutation",
        "fill the blank slide 6 (position 5) in place: a new slide beside it leaves the blank "
        "empty and every later slide one place on",
        {"intent": "edit", "positions": [BLANK_AT], "inserted": []},
        fill,
        _retargeted(fill, [BLANK_AT], _inserted_spec(blank_deck, {BLANK_AT: FILLED_SLIDE})),
    )
    beside = _out(
        "edit",
        "I'll trim slide 7 to live code demos, embedded video and interactive charts.",
        target_positions=[BESIDE_POS],
        deck_spec=_revised_spec(blank_deck, {BESIDE_POS: _beside_brief(blank_deck, BESIDE_POS)}),
    )
    _write(
        out, "edit_beside_blank", "mutation",
        "edit of slide 7 (position 6), the slide after the blank slide 6 (position 5): change "
        "only slide 7; filling the blank too builds a slide nobody asked for",
        {"intent": "edit", "positions": [BESIDE_POS], "inserted": []},
        beside,
        _retargeted(
            beside, [BLANK_AT, BESIDE_POS],
            _replaced_spec(beside["deck_spec"], {BLANK_AT: INVENTED_FILL}),
        ),
    )


if __name__ == "__main__":
    generate()
