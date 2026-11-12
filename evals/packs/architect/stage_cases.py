"""The architect pack's Stage Slide cases: six per split, each on that split's own deck.

Each case is a message sent with a slide on the viewer's stage (``payload.stage_slide`` non-null).
They measure the architect stage policy (``src/core/skills/architect.py``, STAGE SLIDE):

* ``stage_restyle_deck``      an unqualified request about a KIND of element across the deck
                              ("the code blocks") stays deck-wide: ``deck_changes.deck_style``,
                              nothing rebuilt. should_fail: the restyle narrowed to the stage slide.
* ``stage_explicit_other``    a message naming another slide edits THAT slide. should_fail: the
                              stage slide edited instead.
* ``stage_deictic_title``     "this slide" is the stage slide, at its ``position``. should_fail: the
                              stage's 1-based ``slide_number`` used as a position (the next slide).
* ``stage_unqualified_title`` a content edit of one slide that names no slide edits the stage
                              slide. should_fail: asks which slide (the stage ignored).
* ``stage_question``          a question about the stage slide is answered (discuss). should_fail:
                              the stage slide edited.
* ``stage_move``              "move this slide after slide N": the stage slide moves, slide N is the
                              anchor. should_fail: the roles swapped (slide N moved after
                              the stage slide).

This module only DEFINES the cases (messages, stage snapshots, decks, references, calibrations).
``mutations.generate`` / ``heldout.generate`` write them, and their ``_payload`` passes
``stage_snapshot(split, cid)`` to ``architect_slide_payload`` as ``stage_slide`` (with
``slide_rows=[]``: an eval deck has no committed rows, so the snapshot carries no stable id and
the helper resolves its ``slide_number`` through ``slide_numbering``, as production does for older
slide data). Import this module from the generators freely: it imports them only inside functions.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

#: The six Stage Slide cases, in generation order. Both splits carry all six.
STAGE_CASE_IDS = (
    "stage_restyle_deck",
    "stage_explicit_other",
    "stage_deictic_title",
    "stage_unqualified_title",
    "stage_question",
    "stage_move",
)
#: The stage case whose current deck is the split's styled deck (the restyle_deck deck).
STYLED_STAGE_CASES = ("stage_restyle_deck",)


@dataclass(frozen=True)
class StageCase:
    case_id: str
    message: str
    #: The viewer's send-time snapshot as the browser sends it for a slide with no stable id.
    stage: dict
    styled: bool
    kind: str
    fault: str
    expect: dict
    reference: dict
    should_fail: dict


def _modules():
    from evals.packs.architect import heldout as h
    from evals.packs.architect import mutations as m

    return m, h


def _check_split(split: str) -> str:
    if split not in ("train", "heldout"):
        raise ValueError(f"Invalid split: {split!r}")
    return split


def current_deck(split: str, cid: str) -> dict:
    """The ``current_deck_spec`` a stage case's payload carries: the split's gold deck, or for the
    styled case the gold deck as a deck-style build leaves it (the split's restyle_deck deck)."""
    m, h = _modules()
    _check_split(split)
    if cid not in STAGE_CASE_IDS:
        raise KeyError(cid)
    if split == "train":
        gold = m.case.gold_deck_spec()
        return m._styled_deck(gold, m.RESTYLE_LOOKS) if cid in STYLED_STAGE_CASES else gold
    gold = m.case.gold_deck_spec(h.DECK)
    return m._styled_deck(gold, h.RESTYLE_LOOKS) if cid in STYLED_STAGE_CASES else gold


def _slide(deck: dict, position: int) -> dict:
    return next(s for s in deck["slides"] if s["position"] == position)


def _fields(slide: dict) -> dict:
    return {k: v for k, v in slide.items() if k != "position"}


def _content(fields: dict) -> dict:
    from src.domain.slide_operations import SlideContent

    return SlideContent.model_validate(fields).model_dump(mode="json")


def _swapped(deck: dict, position: int, old: str, new: str) -> dict:
    """The slide at ``position`` as a ``SlideContent``, its brief's ``old`` phrase made ``new``."""
    fields = _fields(_slide(deck, position))
    assert fields["content_brief"].count(old) == 1, (position, old)
    fields["content_brief"] = fields["content_brief"].replace(old, new)
    return _content(fields)


def _titled(deck: dict, position: int, title: str) -> dict:
    """The slide at ``position`` as a ``SlideContent`` whose brief now gives it ``title``."""
    fields = _fields(_slide(deck, position))
    fields["content_brief"] = f"Title the slide '{title}'. {fields['content_brief']}"
    return _content(fields)


def _appended(deck: dict, position: int, field: str, text: str) -> dict:
    """The slide at ``position`` as a ``SlideContent`` with ``text`` appended to ``field``."""
    fields = _fields(_slide(deck, position))
    fields[field] = f"{fields[field]} {text}"
    return _content(fields)


def _identity(deck: dict) -> list[int]:
    return [s["position"] for s in deck["slides"]]


def _moved(deck: dict, position: int, after: int) -> list[int]:
    """The persisted positions in order after moving ``position`` straight after ``after``."""
    order = [p for p in _identity(deck) if p != position]
    order.insert(order.index(after) + 1, position)
    return order


# --------------------------------------------------------------------------- per-split content

#: Per split and case: the message, the stage's 1-based slide number, and the case's own text.
_TRAIN = {
    "stage_restyle_deck": {
        "message": "Make the code blocks dark with light text",
        "stage": 6,
        "reply": (
            "I'll put every code block in the deck on the brand's darkest ink token with light "
            "text, and lighten the keyword, function, string and comment colours so they stay "
            "readable. Nothing else changes and no slide is rebuilt."
        ),
        "narrowed_reply": "I'll make the code block on slide 6 dark with light text.",
        "narrowed_look": "Its dk-code listing sits on a dark ground with light text.",
    },
    "stage_explicit_other": {
        "message": (
            "On slide 2, cut the callout down to the two worst pain points: bloated file sizes "
            "and font substitution"
        ),
        "stage": 4,
        "target": 1,
        "phrase": (
            "a callout highlighting common PowerPoint pain points: font substitution, "
            "fixed-resolution layouts, bloated file sizes (8–15 MB average), and version-control "
            "headaches",
            "a callout on the two worst PowerPoint pain points: bloated file sizes (8–15 MB "
            "average) and font substitution",
        ),
        "reply": (
            "I'll cut the callout on slide 2 down to bloated file sizes and font substitution."
        ),
        "wrong_text": (
            "Add a callout on the two worst PowerPoint pain points: bloated file sizes (8–15 MB "
            "average) and font substitution."
        ),
    },
    "stage_deictic_title": {
        "message": "Give this slide a shorter title: 'Typography that holds'",
        "stage": 5,
        "title": "Typography that holds",
        "reply": "I'll retitle slide 5 'Typography that holds'.",
    },
    "stage_unqualified_title": {
        "message": "Change the title to 'What HTML slides are'",
        "stage": 3,
        "title": "What HTML slides are",
        "reply": "I'll change the title of slide 3 to 'What HTML slides are'.",
        "ask": "Which slide's title would you like me to change to 'What HTML slides are'?",
    },
    "stage_question": {
        "message": "Why is this slide in the deck?",
        "stage": 8,
        "answer": (
            "Slide 8 is the fifth evidence beat, collaboration: it shows that HTML slide source "
            "is plain text that lives in Git, gets reviewed through pull requests and is shared "
            "as a URL, which completes the case before the objections on slide 9. I can trim or "
            "move it if you like."
        ),
        "wrong_reply": "I'll rework slide 8 to make its point clearer.",
    },
    "stage_move": {
        "message": "Move this slide so it comes straight after slide 2",
        "stage": 9,
        "anchor": 1,
        "reply": (
            "I'll move slide 9, on the objections, up to just after slide 2: it becomes slide 3, "
            "and slides 3 to 8 move down one place."
        ),
    },
}
_HELDOUT = {
    "stage_restyle_deck": {
        "message": "Switch the code listings to light text on a dark background",
        "stage": 3,
        "reply": (
            "I'll put every code listing in the deck on a dark background with light text, using "
            "the brand's darkest ink token, and lighten the keyword, function, string and comment "
            "colours so they stay readable. Nothing else changes and no slide is rebuilt."
        ),
        "narrowed_reply": (
            "I'll switch the code listing on slide 3 to light text on a dark background."
        ),
        "narrowed_look": "Its dk-code listing uses light text on a dark background.",
    },
    "stage_explicit_other": {
        "message": "On slide 5, number each step of the evaluation loop",
        "stage": 2,
        "target": 4,
        "phrase": (
            "a prompt evaluation loop (define criteria → build test set → score outputs → refine "
            "prompt → repeat)",
            "a numbered prompt evaluation loop (1. define criteria → 2. build test set → 3. score "
            "outputs → 4. refine prompt → 5. repeat)",
        ),
        "reply": "I'll number each step of the evaluation loop on slide 5.",
        "wrong_text": "Number each item, 1 to 3.",
    },
    "stage_deictic_title": {
        "message": "Retitle this slide 'What structured prompting saves'",
        "stage": 4,
        "title": "What structured prompting saves",
        "reply": "I'll retitle slide 4 'What structured prompting saves'.",
    },
    "stage_unqualified_title": {
        "message": "Change the title to 'Your prompt checklist'",
        "stage": 6,
        "title": "Your prompt checklist",
        "reply": "I'll change the title of slide 6 to 'Your prompt checklist'.",
        "ask": "Which slide's title would you like me to change to 'Your prompt checklist'?",
    },
    "stage_question": {
        "message": "What is this slide trying to show?",
        "stage": 5,
        "answer": (
            "Slide 5 gives the team the workflow: a prompt evaluation loop, from defining criteria "
            "and building a test set to scoring outputs and refining the prompt, with commentary "
            "on why each step matters, so the techniques and numbers before it become a repeatable "
            "practice. I can change it if you like."
        ),
        "wrong_reply": "I'll rework slide 5 so the evaluation loop is clearer.",
    },
    "stage_move": {
        "message": "Move this slide so it sits right after slide 2",
        "stage": 6,
        "anchor": 1,
        "reply": (
            "I'll move slide 6, the checklist, up to just after slide 2: it becomes slide 3, and "
            "slides 3 to 5 move down one place."
        ),
    },
}


def _table(split: str) -> dict:
    return _TRAIN if _check_split(split) == "train" else _HELDOUT


def messages(split: str) -> dict[str, str]:
    """Each stage case's user message, by case id."""
    return {cid: _table(split)[cid]["message"] for cid in STAGE_CASE_IDS}


def stage_snapshot(split: str, cid: str) -> dict | None:
    """The raw viewer snapshot ``_payload`` hands ``architect_slide_payload`` as ``stage_slide``:
    ``{"slide_number": N}`` for a stage case, ``None`` for every other case of the split."""
    row = _table(split).get(cid)
    return None if row is None else {"slide_number": row["stage"]}


def _numbered_position(deck: dict, number: int) -> int:
    from src.domain.slide_numbering import slide_numbering

    numbering = slide_numbering(_identity(deck))
    (entry,) = [e for e in numbering if e["slide_number"] == number]
    return entry["position"]


def cases(split: str) -> tuple[StageCase, ...]:
    """The six stage cases of ``split``, in ``STAGE_CASE_IDS`` order."""
    m, _ = _modules()
    table = _table(split)
    out = []
    for cid in STAGE_CASE_IDS:
        row = table[cid]
        deck = current_deck(split, cid)
        stage_pos = _numbered_position(deck, row["stage"])
        stage = {"slide_number": row["stage"]}
        styled = cid in STYLED_STAGE_CASES
        n = row["stage"]
        if cid == "stage_restyle_deck":
            kind, fault = "mutation", (
                f"an unqualified request about every code block, sent with slide {n} (position "
                f"{stage_pos}) on stage, stays deck-wide: {m.RESTYLE_FAULT}; narrowing it to the "
                "stage slide rebuilds that slide and leaves every other code block as it was"
            )
            expect = {"intent": "edit", "positions": [], "deck_style_keeps": list(m.RESTYLE_KEEPS)}
            reference = m._restyled(row["reply"])
            should_fail = m._operations_out(row["narrowed_reply"], [m._op(
                "update", position=stage_pos,
                slides=[_appended(deck, stage_pos, "look", row["narrowed_look"])])])
        elif cid == "stage_explicit_other":
            target = row["target"]
            kind, fault = "mutation", (
                f"the message names slide {target + 1} (position {target}) while slide {n} "
                f"(position {stage_pos}) is on stage: the named slide is the one edited, never the "
                "stage slide"
            )
            expect = {"intent": "edit", "positions": [target], "inserted": [],
                      "layout": _identity(deck)}
            old, new = row["phrase"]
            reference = m._operations_out(row["reply"], [m._op(
                "update", position=target, slides=[_swapped(deck, target, old, new)])])
            should_fail = m._operations_out(row["reply"], [m._op(
                "update", position=stage_pos,
                slides=[_appended(deck, stage_pos, "content_brief", row["wrong_text"])])])
        elif cid in ("stage_deictic_title", "stage_unqualified_title"):
            deictic = cid == "stage_deictic_title"
            kind, fault = "mutation", (
                (f"'this slide' is the stage slide, slide {n} at position {stage_pos}; reading the "
                 f"1-based slide number as a position edits slide {n + 1} instead")
                if deictic else
                (f"a content edit of one slide that names no slide, sent with slide {n} (position "
                 f"{stage_pos}) on stage, edits the stage slide; asking which slide ignores the "
                 "stage")
            )
            expect = {"intent": "edit", "positions": [stage_pos], "inserted": [],
                      "layout": _identity(deck)}
            reference = m._operations_out(row["reply"], [m._op(
                "update", position=stage_pos, slides=[_titled(deck, stage_pos, row["title"])])])
            if deictic:
                should_fail = m._operations_out(row["reply"], [m._op(
                    "update", position=stage_pos + 1,
                    slides=[_titled(deck, stage_pos + 1, row["title"])])])
            else:
                should_fail = m._out("discuss", row["ask"])
        elif cid == "stage_question":
            kind, fault = "mutation", (
                f"a question about the stage slide, slide {n} (position {stage_pos}), is answered "
                "with discuss: it does not edit the slide"
            )
            expect = {"intent": "discuss"}
            reference = m._out("discuss", row["answer"])
            should_fail = m._out("edit", row["wrong_reply"], target_positions=[stage_pos])
        else:  # stage_move
            anchor = row["anchor"]
            kind, fault = "mutation", (
                f"'move this slide after slide {anchor + 1}': the stage slide, slide {n} (position "
                f"{stage_pos}), moves and slide {anchor + 1} (position {anchor}) is its anchor; "
                "moving the named slide after the stage slide swaps the roles"
            )
            expect = {"intent": "edit", "positions": [], "inserted": [],
                      "layout": _moved(deck, stage_pos, anchor)}
            reference = m._operations_out(row["reply"], [m._op(
                "move", position=stage_pos, after_position=anchor)])
            should_fail = m._operations_out(row["reply"], [m._op(
                "move", position=anchor, after_position=stage_pos)])
        out.append(StageCase(
            case_id=cid, message=row["message"], stage=stage, styled=styled, kind=kind,
            fault=fault, expect=expect, reference=copy.deepcopy(reference),
            should_fail=copy.deepcopy(should_fail),
        ))
    return tuple(out)
