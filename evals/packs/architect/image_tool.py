"""Generate the architect's image-tool case set (chat image generation, Task 9). Idempotent.

Eight cases, kept apart from the architect's train and held-out sets in
``evals/packs/architect/cases_image_tool/`` (``case.case_set_dir``), each with the usual four
files. They measure whether the ``generate_image`` tool's description, with no prompt change,
makes the architect use the tool as intended:

* open-ended asks (``picture_options``, ``icon_options``, and ``empty_deck_picture`` on no deck):
  one call of three images, intent ``discuss``, nothing placed;
* exact asks (``exact_icon``, ``exact_background``): one call of one image, an ``edit`` whose
  named slide's ``content_brief`` carries the returned ``{{image:TOKEN}}``, and no reference in
  ``message``;
* no image ask (``build_no_image``, ``concise_no_image``, ``image_question``): no call.

A case's ``expect`` holds the intent (and an edit's ``positions``), which ``expected_category``
scores, and ``image_tool``, which ``scorers.image_tool_score`` scores. The decks are a small seeded
deck (:func:`seeded_deck`, four slides) or none; every payload is built the way the train cases'
are, on the Meridian design system. A reference that places an image uses
:func:`reference_token`, a fixed token-shaped string; a run's own tokens are fresh.

Run: ``python -m evals.packs.architect.image_tool``. Sweep: ``python -m evals.run_eval --agent
architect --config evals/configs/architect/image-tool.yaml --case-set image_tool``.
"""
import base64
import copy
import hashlib
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.packs.architect.mutations import (
    LAYOUT,
    LIBRARY,
    MERIDIAN_ID,
    MERIDIAN_TEMPLATE,
)
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import model_payload_for
from src.services.template_sections import section_inventory

AGENT = "architect"
CASE_SET = "image_tool"
CASES_DIR = case.case_set_dir(AGENT, CASE_SET)

PRIOR_USER = "Build a 4-slide deck asking our staff to switch from passwords to passkeys"
PRIOR_ASSISTANT = (
    "I've drafted a 4-slide deck asking staff to switch from passwords to passkeys, and the "
    "slides are built."
)
DECISIONS_TOPIC = "why teams should write down their decisions"

MESSAGES = {
    "picture_options": "Make me a picture to get slide 2's message across",
    "icon_options": "Give me some icon options for slide 3",
    "exact_icon": "Add a shield icon to slide 2",
    "exact_background": "Add a calm blue background image to slide 1",
    "build_no_image": f"Build me a deck on {DECISIONS_TOPIC}",
    "concise_no_image": "Make slide 4 more concise",
    "empty_deck_picture": f"Make me a picture for a talk on {DECISIONS_TOPIC}",
    "image_question": "What kind of image would work best on the title slide?",
}
CASE_IDS = tuple(MESSAGES)
#: The cases whose payload carries no deck: a fresh session.
NO_DECK = ("build_no_image", "empty_deck_picture")

#: The seeded deck's four slides (positions 0-3). Slide 4's brief is wordy on purpose, so
#: "make slide 4 more concise" has something to cut.
_SEEDED_SLIDES = [
    {
        "purpose": "Open the talk and name the problem: passwords are the weakest link",
        "content_brief": (
            "Title slide with the deck title 'Passkeys for Every Employee' and a subtitle saying "
            "that stolen and reused passwords are behind most account takeovers"
        ),
        "assumes": "Everyone signs in to their work accounts with a password today",
        "hands_off": "There is a safer and faster way to sign in",
    },
    {
        "purpose": "Explain why passkeys stop phishing",
        "content_brief": (
            "Three short bullets: a passkey only works on the real site, so a fake sign-in page "
            "gets nothing; there is no secret to reuse or leak; the private key never leaves the "
            "device. Close with a callout: a passkey cannot be phished"
        ),
        "assumes": "The audience has seen a phishing email that asked for a password",
        "hands_off": "Passkeys remove the thing attackers steal",
    },
    {
        "purpose": "Make the switch feel easy",
        "content_brief": (
            "Three numbered steps side by side: open your account settings, choose 'Create a "
            "passkey', then confirm with your fingerprint, face or device PIN. Note that the "
            "whole switch takes under a minute"
        ),
        "assumes": "Staff worry that changing how they sign in will be a chore",
        "hands_off": "Setting up a passkey is quick",
    },
    {
        "purpose": "Close with one clear ask and a deadline",
        "content_brief": (
            "Wrap up by asking every employee to set up a passkey for their work account before "
            "the end of the quarter, and explain at some length that the IT service desk is "
            "available throughout the quarter for anyone who needs help, that there will be "
            "drop-in sessions in every office during the first two weeks of the rollout, that "
            "the passkey works alongside the existing password during a transition period so "
            "nobody gets locked out, that the security team will send reminder emails to anyone "
            "who has not yet switched, and that the intranet page has a short video walkthrough "
            "as well as a written guide and a list of supported devices"
        ),
        "assumes": "The audience now wants to switch",
        "hands_off": "Everyone knows what to do and by when",
    },
]
#: Slide 4's brief as the concise edit leaves it.
CONCISE_BRIEF_4 = (
    "Ask every employee to set up a passkey for their work account by the end of the quarter. "
    "One line on help: the IT service desk and the intranet guide"
)

#: The reference build for ``build_no_image`` (five slides, no data: a generic public topic).
_DECISIONS_SLIDES = [
    ("Open the talk and frame the problem: decisions that live only in meetings get lost",
     "Title slide with the deck title 'Write It Down: Why Teams Should Record Their Decisions' "
     "and a subtitle saying that a decision nobody wrote down gets made again"),
    ("Show the cost of unwritten decisions",
     "Three bullets: the same debate is reopened months later, newcomers cannot learn why things "
     "are the way they are, and people leave a meeting with different memories of what was agreed"),
    ("Describe what a good decision record holds",
     "A short template in four parts: the decision, the context, the options considered and who "
     "decided, each with a one-line example"),
    ("Make the habit easy to start",
     "Three steps: keep one shared decision log, add an entry before the meeting ends, and link "
     "to it from the work it affects"),
    ("Close with a clear ask",
     "Ask each team to record its next three decisions in a shared log and review the log after "
     "a month"),
]


def _slide_spec(
    position: int, purpose: str, content_brief: str, assumes: str, hands_off: str
) -> dict:
    return {
        "position": position, "purpose": purpose, "content_brief": content_brief,
        "assumes": assumes, "hands_off": hands_off, "data_references": [], "slide_type": None,
    }


def _contract() -> dict:
    return DesignContractRef(
        design_system_id=MERIDIAN_ID, template_id=MERIDIAN_TEMPLATE
    ).model_dump(mode="json")


def seeded_deck() -> dict:
    """The four-slide deck the deck cases start from (a fresh copy, validated)."""
    deck = {
        "title": "Passkeys for Every Employee",
        "audience": "All staff at a mid-size company, from leadership to front-line teams",
        "purpose": "Persuade staff to switch their work accounts from passwords to passkeys",
        "argument": (
            "Passwords cause most account takeovers; passkeys cannot be phished or reused and "
            "take under a minute to set up"
        ),
        "call_to_action": "Set up a passkey for your work account before the end of the quarter",
        "narrative_arc": [
            "Name the problem: passwords are the weakest link",
            "Show why passkeys stop phishing",
            "Make the switch feel easy",
            "Close with one clear ask and a deadline",
        ],
        "design_contract": _contract(),
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "slides": [
            _slide_spec(i, **slide) for i, slide in enumerate(copy.deepcopy(_SEEDED_SLIDES))
        ],
    }
    DeckSpec.model_validate(deck)  # fail fast
    return deck


def _decisions_deck() -> dict:
    deck = {
        "title": "Write It Down: Why Teams Should Record Their Decisions",
        "audience": "Team leads and members of cross-functional teams",
        "purpose": "Persuade teams to keep a written record of the decisions they make",
        "argument": (
            "Unwritten decisions get lost, reopened and misremembered; a short shared decision "
            "log fixes that at almost no cost"
        ),
        "call_to_action": "Record your team's next three decisions in a shared log",
        "narrative_arc": [
            "Frame the problem: decisions that live only in meetings get lost",
            "Show what unwritten decisions cost",
            "Describe a good decision record",
            "Make the habit easy to start",
            "Close with a clear ask",
        ],
        "design_contract": _contract(),
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "slides": [
            _slide_spec(i, purpose, brief, "The audience works in a team that makes decisions",
                        "The case for writing decisions down builds")
            for i, (purpose, brief) in enumerate(_DECISIONS_SLIDES)
        ],
    }
    DeckSpec.model_validate(deck)  # fail fast
    return deck


def reference_token(cid: str) -> str:
    """A fixed token for ``cid``'s reference, shaped like ``secrets.token_urlsafe(32)``."""
    digest = hashlib.sha256(f"tellr-eval-image-tool:{cid}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _ref(cid: str) -> str:
    return "{{image:" + reference_token(cid) + "}}"


def _payload(cid: str) -> dict:
    msg = MESSAGES[cid]
    deck = None if cid in NO_DECK else seeded_deck()
    conversation = [{"role": "user", "content": msg}]
    if deck is not None:
        conversation = [
            {"role": "user", "content": PRIOR_USER},
            {"role": "assistant", "content": PRIOR_ASSISTANT},
            {"role": "user", "content": msg},
        ]
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if deck else [])
    return model_payload_for(AGENT, {
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
    })


def _out(intent: str, message: str, **kw) -> dict:
    out = {
        "intent": intent, "message": message, "deck_spec": None,
        "data_request": None, "target_positions": [], "proposed_design_contract": None,
    }
    out.update(kw)
    ArchitectOutput.model_validate(out)  # fail fast
    return out


def _update(position: int, brief: str, message: str) -> dict:
    """An edit of one seeded slide's brief, given as one update operation."""
    slide = {k: v for k, v in seeded_deck()["slides"][position].items() if k != "position"}
    slide["content_brief"] = brief
    return _out("edit", message, target_positions=[position],
                operations=[{"op": "update", "position": position, "slides": [slide]}])


def _brief(position: int) -> str:
    return _SEEDED_SLIDES[position]["content_brief"]


#: Each case: (fault, expect, reference, should_fail). Every case is a mutation: its trap is named
#: in ``fault`` and its ``should_fail`` falls into it in a way the judge can see.
def _cases() -> dict[str, tuple[str, dict, dict, dict]]:
    illustration = {"called": True, "count": 3, "kinds": ["illustration"]}
    icons = {"called": True, "count": 3, "kinds": ["icon", "vector_icon"]}
    no_call = {"called": False}
    return {
        "picture_options": (
            "open-ended ask: three illustration options in one call, discussed, nothing placed",
            {"intent": "discuss", "image_tool": illustration},
            _out("discuss",
                 "Here are three illustration options for slide 2, each showing a fake sign-in "
                 "page that gets nothing from a passkey. Which one would you like on the slide?"),
            _update(1, _brief(1) + " Show " + _ref("picture_options") + " beside the bullets.",
                    "I've added an illustration to slide 2."),
        ),
        "icon_options": (
            "open-ended ask: three icon options in one call, discussed, nothing placed",
            {"intent": "discuss", "image_tool": icons},
            _out("discuss",
                 "Here are three icon options for the steps on slide 3. Which one would you like "
                 "me to use?"),
            _update(2, _brief(2) + " Put " + _ref("icon_options") + " above each step.",
                    "I've added icons to slide 3."),
        ),
        "exact_icon": (
            "exact ask: one icon placed in slide 2's content_brief (position 1), not three options",
            {"intent": "edit", "positions": [1],
             "image_tool": {"called": True, "count": 1, "kinds": ["icon", "vector_icon"],
                            "slide": 2}},
            _update(1, _brief(1) + " Place " + _ref("exact_icon") + " as a small shield icon "
                    "beside the slide title, about 64px square.",
                    "I've added a shield icon beside the title on slide 2."),
            _out("discuss",
                 "Here are three shield icon options for slide 2. Which one would you like?"),
        ),
        "exact_background": (
            "exact ask: one background placed in slide 1's content_brief (position 0), not three "
            "options",
            {"intent": "edit", "positions": [0],
             "image_tool": {"called": True, "count": 1, "kinds": ["background"], "slide": 1}},
            _update(0, _brief(0) + ". Use " + _ref("exact_background") + " as a full-slide "
                    "background image behind the title, keeping the title text readable.",
                    "I've put a calm blue background image behind slide 1."),
            _out("discuss",
                 "Here are three calm blue background options for slide 1. Which one would you "
                 "like?"),
        ),
        "build_no_image": (
            "no image ask: a plain deck build calls no image tool",
            {"intent": "build", "image_tool": no_call},
            _out("build", f"Here is a 5-slide deck on {DECISIONS_TOPIC}.",
                 deck_spec=_decisions_deck()),
            _out("discuss",
                 "Before I build it, here are three illustration options for the deck. Which one "
                 "would you like?"),
        ),
        "concise_no_image": (
            "no image ask: trimming slide 4 (position 3) calls no image tool",
            {"intent": "edit", "positions": [3], "image_tool": no_call},
            _update(3, CONCISE_BRIEF_4,
                    "I've cut slide 4 down to the ask, the deadline and where to get help."),
            _out("edit", "I've made slide 4 more concise.", target_positions=[2]),
        ),
        "empty_deck_picture": (
            "empty deck: a picture request gets options to discuss, never a deck built around it",
            {"intent": "discuss", "image_tool": illustration},
            _out("discuss",
                 f"Here are three illustration options for your talk on {DECISIONS_TOPIC}. "
                 "Which one would you like?"),
            _out("build",
                 f"Here is a deck on {DECISIONS_TOPIC}, with a picture on the title slide.",
                 deck_spec=_decisions_deck()),
        ),
        "image_question": (
            "a question about images is not a request for one: answer it, call no image tool",
            {"intent": "discuss", "image_tool": no_call},
            _out("discuss",
                 "A calm, simple illustration works best on a title slide: one clear subject in "
                 "the deck's palette, with room for the title and no text in the image. Would "
                 "you like me to make a few options?"),
            _update(0, _brief(0) + ". Use " + _ref("image_question") + " as the title slide's "
                    "illustration.", "I've added an illustration to the title slide."),
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
        d = out / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / "case.yaml").write_text(yaml.safe_dump({
            "kind": "mutation", "fault": fault, "expect": expect, "design_system_active": True,
        }, sort_keys=False))
        _dump(d / "payload.json", _payload(cid))
        _dump(d / "reference.json", reference)
        _dump(d / "calibration.json", {"should_fail": should_fail})


if __name__ == "__main__":
    generate()
