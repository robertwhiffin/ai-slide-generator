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
from src.domain.slide_operations import (
    OperationsResult,
    SlideContent,
    SlideOperation,
    apply_operations,
    compose_edit_spec,
)
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
    # Architect edit operations (spec §9): delete, move, replace and a mixed edit on the deck.
    "delete_slide": (
        "Please delete slide 6. I'll show the interactivity live in a demo, so the rest of the "
        "deck can stay exactly as it is."
    ),
    "move_slide": (
        "Move slide 7 up to just after slide 4, so accessibility follows responsive design"
    ),
    "replace_slide_expand": (
        "Replace slide 5 with these four slides: a short overview of design fidelity, then one "
        "slide each on web fonts, spacing and kerning, and theming with CSS"
    ),
    "mixed_operations": (
        "Delete slide 3, make slide 2's callout lead with the 8–15 MB file sizes, and expand the "
        "bullets on slide 8 into three slides: collaboration, version control and distribution"
    ),
}

# The edit-operations cases (spec §9): their references answer in operations, not a deck_spec.
OPERATIONS_CASES = ("delete_slide", "move_slide", "replace_slide_expand", "mixed_operations")
# The cases whose payload carries the deck: the prior exchange, the gold spec and its slide count.
HAS_DECK = (
    "edit_request", "confirm_design", "discuss",
    "edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question",
    "add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise",
    "fill_blank_slide", "edit_beside_blank",
    *OPERATIONS_CASES,
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


# Architect edit operations (spec §9): the references answer in operations, as ArchitectOutput
# dumps them, with ``deck_spec`` null (§8). Positions are the CURRENT deck's (0-based).
def _op(op: str, **fields) -> dict:
    """One operation as the architect's structured output dumps it (every key, unset ones null)."""
    return SlideOperation.model_validate({"op": op, **fields}).model_dump(mode="json")


def _content(fields: dict) -> dict:
    """A new slide's ``SlideContent`` dump: its text fields, no data unless given."""
    return SlideContent.model_validate({**NEW_SLIDE_DEFAULTS, **fields}).model_dump(mode="json")


def _revised_content(deck: dict, position: int, phrase: tuple[str, str]) -> dict:
    """The ``SlideContent`` of ``deck``'s slide at ``position``, its brief's ``phrase`` swapped."""
    old, new = phrase
    slide = next(s for s in deck["slides"] if s["position"] == position)
    assert slide["content_brief"].count(old) == 1, position
    fields = {k: v for k, v in slide.items() if k != "position"}
    fields["content_brief"] = slide["content_brief"].replace(old, new)
    return SlideContent.model_validate(fields).model_dump(mode="json")


def _operations_out(message: str, operations: list[dict]) -> dict:
    """An edit given as operations, in the ArchitectOutput dump's own key order."""
    return _out("edit", message, operations=operations, deck_changes=None)


def _composed_spec(deck: dict, operations: list[dict]) -> dict:
    """The whole deck_spec production composes ``operations`` into over ``deck``.

    A replace case's should_fail is this, returned the old way: the right plan as a full grown
    deck_spec, which production's alignment cannot read (the production failure, spec "Why").
    """
    prior = DeckSpec.model_validate(deck)
    result = apply_operations(prior.slides, [SlideOperation.model_validate(o) for o in operations])
    assert isinstance(result, OperationsResult), result
    spec = compose_edit_spec(prior, result, None)
    assert isinstance(spec, DeckSpec), spec
    return spec.model_dump(mode="json")


# delete_slide: slide 6 (position 5, Evidence beat 3 — interactivity) goes; nothing is rebuilt.
DELETE_POS = 5
# move_slide: slide 7 (position 6, accessibility) goes straight after slide 4 (position 3).
MOVE_POS, MOVE_AFTER = 6, 3
# replace_slide_expand: slide 5 (position 4, typography) becomes these four slides.
REPLACE_POS = 4
REPLACE_SLIDES = [
    {
        "purpose": "Evidence beat 2 — Design fidelity: an overview",
        "content_brief": (
            "Introduce design fidelity as the second advantage: CSS gives HTML slides precise, "
            "reliable control over how every slide looks. A short framing statement with three "
            "signposts to the slides that follow: web fonts, spacing and kerning, and theming"
        ),
        "assumes": (
            "The audience has seen a PowerPoint deck where fonts broke on a different machine"
        ),
        "hands_off": (
            "CSS gives presenters design control that PowerPoint cannot match, in three ways"
        ),
    },
    {
        "purpose": "Design fidelity 1 — Web fonts that load reliably",
        "content_brief": (
            "Show that HTML slides load web fonts through CSS with no embedding, so text renders "
            "the same on every machine, where PowerPoint substitutes a missing font. Bullet points "
            "with a callout featuring the 1,700+ fonts available via CSS"
        ),
        "assumes": "The audience has just heard that CSS controls how every slide looks",
        "hands_off": "With web fonts, a deck's type never breaks on someone else's machine",
        "data_references": ["css_font_availability"],
    },
    {
        "purpose": "Design fidelity 2 — Precise spacing and kerning",
        "content_brief": (
            "Explain that CSS sets kerning, line-height and spacing exactly, so text sits where "
            "the designer put it at every screen size, where PowerPoint reflows and clips text "
            "boxes. Bullet points with a callout contrasting one CSS rule with nudging text boxes "
            "by hand"
        ),
        "assumes": "The audience knows web fonts load reliably in HTML slides",
        "hands_off": "CSS places every line of text exactly where it belongs",
    },
    {
        "purpose": "Design fidelity 3 — Theming with CSS",
        "content_brief": (
            "Show that CSS variables hold a deck's colours, type scale and spacing in one place, "
            "so restyling every slide is one change, where PowerPoint needs each slide master "
            "edited by hand. Bullet points with a callout on keeping every slide on brand"
        ),
        "assumes": "The audience has seen that CSS controls type and spacing precisely",
        "hands_off": "With CSS, the whole deck's design lives in one place and stays consistent",
    },
]
# mixed_operations: delete slide 3 (position 2), revise slide 2's callout (position 1), and
# expand slide 8 (position 7, collaboration) into three slides, in one message.
MIXED_DELETE, MIXED_UPDATE, MIXED_REPLACE = 2, 1, 7
MIXED_CALLOUT = (
    "a callout highlighting common PowerPoint pain points: font substitution, fixed-resolution "
    "layouts, bloated file sizes (8–15 MB average), and version-control headaches",
    "a callout that leads with bloated file sizes (8–15 MB average), then the other common "
    "PowerPoint pain points: font substitution, fixed-resolution layouts and version-control "
    "headaches",
)
MIXED_SLIDES = [
    {
        "purpose": "Evidence beat 5 — Collaboration",
        "content_brief": (
            "Show that HTML slide source is plain text, so a team edits one deck together through "
            "pull requests and diff reviews instead of emailing copies around. Bullet points on "
            "collaborative editing with a callout contrasting one reviewed change with a folder "
            "of final_v3.pptx files"
        ),
        "assumes": (
            "The audience is familiar with collaborative workflows, even if not with Git "
            "specifically"
        ),
        "hands_off": "HTML slides let a team work on one deck the way it works on code",
    },
    {
        "purpose": "Evidence beat 5, continued — Version control",
        "content_brief": (
            "Explain that a deck kept in Git has a full history: every change is recorded, any "
            "earlier version can be restored, and CI/CD can check and publish each one. Bullet "
            "points on history, rollback and automated checks"
        ),
        "assumes": "The audience has seen that the deck's source is plain text a team can review",
        "hands_off": "Every version of the deck is recorded and can be brought back",
    },
    {
        "purpose": "Evidence beat 5, continued — Distribution",
        "content_brief": (
            "Show that an HTML deck is shared as a URL, not a 15 MB email attachment, and opens in "
            "any browser. Bullet points on sharing and access with a callout contrasting file "
            "sizes: 8–15 MB .pptx vs. under 1 MB HTML deck"
        ),
        "assumes": "The audience has seen how a team edits and versions the deck",
        "hands_off": "An HTML deck reaches every audience with a single link",
        "data_references": ["pptx_average_file_size", "html_deck_file_size"],
    },
]
# mixed_operations' should_fail also rewrites the untouched closing slide (gold position 9).
MIXED_OVERREACH_SUMMARY = (
    "five advantage dimensions — responsiveness, typography, interactivity, accessibility, "
    "collaboration —",
    "five advantage dimensions — responsiveness, typography, interactivity, accessibility, and "
    "collaboration with version control and distribution —",
)


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

    # Architect edit operations (spec §9): the references answer in operations against the gold
    # deck. ``positions`` is the rebuild set and ``inserted`` the new slides, both in the edited
    # deck's numbering; ``layout`` (persisted positions, null = new) says which slide went where.
    delete_message = "I'll delete slide 6 on interactivity; slides 7 to 10 move up one place."
    _write(
        out, "delete_slide", "mutation",
        "delete slide 6 (position 5): only it goes, nothing is rebuilt and the later slides move "
        "up unchanged; deleting position 6 (slide 7) is the 1-based slip",
        {"intent": "edit", "positions": [], "inserted": [],
         "layout": [p for p in range(10) if p != DELETE_POS]},
        _operations_out(delete_message, [_op("delete", position=DELETE_POS)]),
        _operations_out(delete_message, [_op("delete", position=DELETE_POS + 1)]),
    )
    move_message = (
        "I'll move slide 7, on accessibility, up to just after slide 4: it becomes slide 5, and "
        "the typography and interactivity slides become slides 6 and 7."
    )
    _write(
        out, "move_slide", "mutation",
        "move slide 7 (position 6) to after slide 4 (position 3): a reorder that rebuilds "
        "nothing; anchoring it after position 4 (slide 5) is the 1-based slip",
        {"intent": "edit", "positions": [], "inserted": [],
         "layout": [0, 1, 2, 3, 6, 4, 5, 7, 8, 9]},
        _operations_out(move_message, [_op("move", position=MOVE_POS, after_position=MOVE_AFTER)]),
        _operations_out(
            move_message, [_op("move", position=MOVE_POS, after_position=MOVE_AFTER + 1)]),
    )
    replace_ops = [
        _op("replace", position=REPLACE_POS, slides=[_content(s) for s in REPLACE_SLIDES]),
    ]
    replace_positions = list(range(REPLACE_POS, REPLACE_POS + len(REPLACE_SLIDES)))
    replace_message = (
        "I'll replace slide 5 with four slides: slide 5 becomes a short overview of design "
        "fidelity, and new slides 6, 7 and 8 cover web fonts, spacing and kerning, and theming "
        "with CSS. The slides after them move down three places."
    )
    _write(
        out, "replace_slide_expand", "mutation",
        "replace slide 5 (position 4) with four slides: the first rewrites position 4 in place and "
        "three new slides follow at positions 5-7; the same plan as a whole grown deck_spec is "
        "refused by production's alignment as ambiguous",
        {"intent": "edit", "positions": replace_positions, "inserted": replace_positions[1:]},
        _operations_out(replace_message, replace_ops),
        _out("edit", replace_message, target_positions=replace_positions,
             deck_spec=_composed_spec(gold, replace_ops)),
    )
    mixed_ops = [
        _op("delete", position=MIXED_DELETE),
        _op("update", position=MIXED_UPDATE,
            slides=[_revised_content(gold, MIXED_UPDATE, MIXED_CALLOUT)]),
        _op("replace", position=MIXED_REPLACE, slides=[_content(s) for s in MIXED_SLIDES]),
    ]
    mixed_message = (
        "I'll delete slide 3, make slide 2's callout lead with the 8–15 MB file sizes, and expand "
        "the collaboration slide into three: slides 7, 8 and 9 on collaboration, version control "
        "and distribution. The objections and closing slides become slides 10 and 11."
    )
    _write(
        out, "mixed_operations", "mutation",
        "delete slide 3 (position 2), revise slide 2 (position 1) and expand slide 8 (position 7) "
        "into three, in one edit: production rebuilds positions 1 and 6-8 of the 11-slide result "
        "and nothing else; rewriting the untouched closing slide too builds a slide nobody asked "
        "for",
        {"intent": "edit", "positions": [1, 6, 7, 8], "inserted": [7, 8],
         "layout": [0, 1, 3, 4, 5, 6, 7, None, None, 8, 9]},
        _operations_out(mixed_message, mixed_ops),
        _operations_out(
            mixed_message + " I'll also update the summary on the closing slide to match.",
            [*mixed_ops,
             _op("update", position=9,
                 slides=[_revised_content(gold, 9, MIXED_OVERREACH_SUMMARY)])],
        ),
    )


if __name__ == "__main__":
    generate()
