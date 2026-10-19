"""Tests for src/domain/finding_copy.py: plain-language copy for review findings (#316).

A reviewer's ``Finding.message`` is written for the fixer: hex codes, pixel sizes,
contrast ratios.  What a deck author sees leads instead with copy DERIVED from the
fields every finding already carries (``criterion``, the registry's ``objective``,
``status``) and never from ``message`` (plan D1, D2).  These tests are the contract
for that copy:

* it is exactly the D8 table, for every ``CRITERIA`` entry, and nothing else;
* no copy string a user can see carries technical detail, a criterion slug or a
  graph role name, and every whole sentence is a sentence (D11);
* open reads in the present tense, fixed in the past, and the status sentence is
  chosen by the REGISTRY's objectivity and the status (D8, D9);
* the reviewer's message never changes the plain text;
* an unknown criterion and an unrecognised status degrade, never raise (D10);
* a deck-wide advisory line never says "this slide" (D5);
* the copy and the details separator never reach a prompt (D2).

Every expected string is transcribed from the plan's D8 tables, never read back
from the module under test, so an implementation cannot pass by being consistent
with itself.

Sabotage checks.  Each was applied to the plan's module and turned the named tests
red; the unchanged module passes every test here.

* Put ``{finding.message}`` into ``plain_finding_message``'s output:
  ``test_plain_text_ignores_the_reviewer_message`` and
  ``test_plain_copy_never_carries_technical_detail`` (banned patterns and the
  140-character cap) go red, as do the exact-composition tests.
* Delete one ``PLAIN_ISSUES`` entry:
  ``test_every_criterion_has_copy_and_no_copy_lacks_a_criterion`` goes red (and
  that criterion's D8-table and sweep cases).
* Make ``deck_advisory_issue`` return ``plain_issue(criterion)`` unconditionally:
  ``test_deck_advisory_lines_never_say_this_slide`` goes red.
* Read the stored ``finding.objective`` instead of the registry's:
  ``test_objectivity_comes_from_the_registry_when_the_criterion_is_known`` and
  ``test_every_finding_reads_as_its_issue_then_its_status`` go red.
* Swap ``ADDRESSED`` and ``FIXED_AUTOMATICALLY`` in ``plain_status``:
  ``test_status_and_objectivity_choose_the_status_sentence`` goes red.
* Treat any status other than ``"open"`` as fixed:
  ``test_an_unrecognised_status_reads_as_open`` goes red.
* Make ``plain_issue`` raise ``KeyError`` for an unknown criterion:
  ``test_an_unknown_criterion_gets_the_generic_copy`` goes red.
* Paste a copy string into a ``CRITERIA`` description (the build reviewer's
  rendered CRITERIA stage): ``test_copy_is_not_rendered_into_any_prompt`` goes red.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pytest

from src.domain.finding import CRITERIA, Finding, make_finding_id
from src.domain.finding_copy import (
    ADDRESSED,
    DECK_ADVISORY_CLOSING,
    DECK_ADVISORY_HEADER_PREFIX,
    DECK_ADVISORY_HEADER_SUFFIX,
    DECK_GRAIN_ISSUE,
    FIXED_AUTOMATICALLY,
    GENERIC_ISSUE,
    LEFT_FOR_JUDGEMENT,
    NOT_FIXED_AUTOMATICALLY,
    PLAIN_ISSUES,
    REVIEWER_DETAILS_SEPARATOR,
    PlainIssue,
    deck_advisory_issue,
    plain_finding_issue,
    plain_finding_message,
    plain_issue,
    plain_status,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Inputs transcribed from the plan and the issue (never read from the module)
# ---------------------------------------------------------------------------

#: The verbatim technical message quoted in #316.  Importable by other test
#: modules (Task 3) as ``tests.unit.test_finding_copy.ISSUE_316_MESSAGE``.
ISSUE_316_MESSAGE = (
    'The "NOTE" label in the bottom callout is Coral #FF5F46 at 13px/700 over the '
    "box fill (rgba(255,95,70,0.12) composited on navy #1B3139 ≈ #2D3A3C), "
    "giving roughly 3.9:1 — below the 4.5:1 AA floor for text this size. The "
    "template's own dark-background eyebrow colour (#FFC9BF) clears AA; use that "
    "instead of raw coral."
)

#: Plan D8: criterion -> (present / open, past / fixed).  Exact.
D8_ISSUES: Dict[str, Tuple[str, str]] = {
    "overflow": (
        "Some content runs past the edge of the slide.",
        "Some content ran past the edge of the slide.",
    ),
    "contrast_failure": (
        "Some text is hard to read against its background.",
        "Some text was hard to read against its background.",
    ),
    "rogue_colour": (
        "A colour on this slide is outside the deck's colour scheme.",
        "A colour on this slide was outside the deck's colour scheme.",
    ),
    "distorted_image": (
        "An image looks stretched or squashed.",
        "An image looked stretched or squashed.",
    ),
    "source_contradiction": (
        "A figure on this slide does not match the source data.",
        "A figure on this slide did not match the source data.",
    ),
    "brief_not_delivered": (
        "This slide may not cover everything planned for it.",
        "This slide did not cover everything planned for it.",
    ),
    "off_template_treatment": (
        "This slide's background or colours differ from its template.",
        "This slide's background or colours differed from its template.",
    ),
    "layout_binding_mismatch": (
        "This slide does not use the layout planned for it.",
        "This slide did not use the layout planned for it.",
    ),
    "arc_gap": (
        "The story has a gap or an unexplained jump between slides.",
        "The story had a gap or an unexplained jump between slides.",
    ),
    "cross_slide_repetition": (
        "The same point is made on more than one slide.",
        "The same point was made on more than one slide.",
    ),
    "missing_conclusion": (
        "The deck has no clear conclusion or call to action.",
        "The deck had no clear conclusion or call to action.",
    ),
}
D8_GENERIC: Tuple[str, str] = (
    "Something here may need a closer look.",
    "Something here needed a closer look.",
)

#: Plan D8 status table: (objective, fixed) -> sentence.  Exact.
D8_STATUS: Dict[Tuple[bool, bool], str] = {
    (True, True): "This was fixed automatically.",
    (False, True): "This has been addressed.",
    (True, False): "This was not fixed automatically.",
    (False, False): "This is a judgement call, so it was left for you to decide.",
}

#: Plan D8 fixed deck-advisory strings.  Exact.
D8_DECK_GRAIN_ISSUE = "One of the slides may need a closer look."
D8_HEADER_PREFIX = "Deck review found "
D8_HEADER_SUFFIX = " to look at in how the deck reads as a whole:"
D8_CLOSING = (
    "None of these were changed automatically. Reply here if you'd like any of them addressed."
)
D8_SEPARATOR = "\n\nReviewer's details:\n"

#: A criterion that is not (or is no longer) in the registry.
UNKNOWN_CRITERION = "retired_criterion"

STATUSES = ("open", "fixed")
OBJECTIVITIES = (True, False)

#: D11: banned in every user-visible copy string (case-insensitive).
BANNED_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"#[0-9a-f]{3,8}\b",
        r"\d",
        r"px\b",
        r"rgba?\(",
        r"hsla?\(",
        r":\s*1\b",
        r"\bwcag\b",
        r"\baa\b",
        r"%",
        r"_",
        r"`",
        r"\*\*",
        r"\b(architect|foreman|builder|fixer|reviewer|analyst)\b",
    )
)
#: D11: per-criterion issue sentences describe the slide and stay third person.
SECOND_PERSON = re.compile(r"\byou(?:r|rs|rself|'d|'re|'ll|'ve)?\b", re.IGNORECASE)
#: D11: a whole sentence starts with a capital and ends with a full stop (one line).
SENTENCE_SHAPE = re.compile(r"[A-Z].*\.")
MAX_PLAIN_MESSAGE_LEN = 140


# ---------------------------------------------------------------------------
# Finding builders
# ---------------------------------------------------------------------------


def _real(criterion: str, *, status: str = "open", message: str = ISSUE_316_MESSAGE) -> Finding:
    """A validated ``Finding`` as a reviewer would emit it (registry category/objective)."""
    crit = CRITERIA[criterion]
    return Finding(
        id=make_finding_id(criterion, "subjecthash", 0),
        slide_index=-1 if crit.level == "deck" else 0,
        category=crit.category,
        criterion=criterion,
        message=message,
        objective=crit.objective,
        status=status,
    )


def _constructed(
    criterion: str,
    *,
    status: object,
    objective: bool,
    message: str = ISSUE_316_MESSAGE,
) -> Finding:
    """An unvalidated ``Finding`` so a stored objective may disagree with the registry,
    the criterion may be unknown, and the status may be unrecognised."""
    crit = CRITERIA.get(criterion)
    return Finding.model_construct(
        id=f"{criterion}:subjecthash:0",
        slide_index=-1 if crit is not None and crit.level == "deck" else 0,
        category=crit.category if crit is not None else "design",
        criterion=criterion,
        message=message,
        objective=objective,
        status=status,
        seen=False,
    )


# ---------------------------------------------------------------------------
# The sweep: every copy string a user can see
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Copy:
    produce: Callable[[], str]
    sentence: bool = True  # whole sentence(s): shape rule applies
    third_person: bool = False  # describes the slide: no second person
    max_len: Optional[int] = None


def _copy_cases() -> List:
    cases: List = []
    # Union, so a missing entry fails its own case and an extra entry is swept too.
    for c in sorted(set(CRITERIA) | set(PLAIN_ISSUES)):
        cases.append(
            pytest.param(
                _Copy(lambda c=c: PLAIN_ISSUES[c].present, third_person=True),
                id=f"issue-present-{c}",
            )
        )
        cases.append(
            pytest.param(
                _Copy(lambda c=c: PLAIN_ISSUES[c].past, third_person=True), id=f"issue-past-{c}"
            )
        )
    cases.append(
        pytest.param(_Copy(lambda: GENERIC_ISSUE.present, third_person=True), id="generic-present")
    )
    cases.append(
        pytest.param(_Copy(lambda: GENERIC_ISSUE.past, third_person=True), id="generic-past")
    )
    for name, value in (
        ("FIXED_AUTOMATICALLY", FIXED_AUTOMATICALLY),
        ("ADDRESSED", ADDRESSED),
        ("NOT_FIXED_AUTOMATICALLY", NOT_FIXED_AUTOMATICALLY),
        ("LEFT_FOR_JUDGEMENT", LEFT_FOR_JUDGEMENT),
    ):
        cases.append(pytest.param(_Copy(lambda v=value: v), id=f"status-{name}"))
    cases.append(
        pytest.param(_Copy(lambda: DECK_GRAIN_ISSUE, third_person=True), id="DECK_GRAIN_ISSUE")
    )
    cases.append(
        pytest.param(
            _Copy(lambda: DECK_ADVISORY_HEADER_PREFIX, sentence=False),
            id="DECK_ADVISORY_HEADER_PREFIX",
        )
    )
    cases.append(
        pytest.param(
            _Copy(lambda: DECK_ADVISORY_HEADER_SUFFIX, sentence=False),
            id="DECK_ADVISORY_HEADER_SUFFIX",
        )
    )
    cases.append(pytest.param(_Copy(lambda: DECK_ADVISORY_CLOSING), id="DECK_ADVISORY_CLOSING"))
    # Every criterion (and an unknown one) x status x stored objectivity.  The
    # findings carry the #316 technical message, so any leak of it trips the sweep.
    for c in sorted(CRITERIA) + [UNKNOWN_CRITERION]:
        for st in STATUSES:
            for ob in OBJECTIVITIES:
                tag = f"{c}-{st}-objective={ob}"
                cases.append(
                    pytest.param(
                        _Copy(
                            lambda c=c, st=st, ob=ob: plain_finding_message(
                                _constructed(c, status=st, objective=ob)
                            ),
                            max_len=MAX_PLAIN_MESSAGE_LEN,
                        ),
                        id=f"message-{tag}",
                    )
                )
                cases.append(
                    pytest.param(
                        _Copy(
                            lambda c=c, st=st, ob=ob: plain_finding_issue(
                                _constructed(c, status=st, objective=ob)
                            ),
                            third_person=True,
                        ),
                        id=f"issue-of-{tag}",
                    )
                )
    return cases


_COPY_CASES = _copy_cases()


def _sweep_strings(*, include_header_fragments: bool) -> List[str]:
    out: List[str] = []
    for param in _COPY_CASES:
        (copy,) = param.values
        if not copy.sentence and not include_header_fragments:
            continue
        out.append(copy.produce())
    return out


# ---------------------------------------------------------------------------
# Coverage and exact copy
# ---------------------------------------------------------------------------


def test_every_criterion_has_copy_and_no_copy_lacks_a_criterion():
    missing = sorted(set(CRITERIA) - set(PLAIN_ISSUES))
    extra = sorted(set(PLAIN_ISSUES) - set(CRITERIA))
    assert not missing and not extra, (
        f"criteria with no plain copy: {missing}; plain copy for no criterion: {extra}"
    )
    for criterion in CRITERIA:
        assert isinstance(PLAIN_ISSUES[criterion], PlainIssue), criterion


def test_the_copy_table_is_read_only():
    """Shared module state: a caller must not be able to rewrite another caller's copy."""
    before = dict(PLAIN_ISSUES)
    try:
        with pytest.raises(TypeError):
            PLAIN_ISSUES["overflow"] = GENERIC_ISSUE  # type: ignore[index]
        with pytest.raises(TypeError):
            del PLAIN_ISSUES["overflow"]  # type: ignore[attr-defined]
        assert dict(PLAIN_ISSUES) == before
    finally:
        # A mutable table fails above; undo the write so later tests see the real copy.
        if isinstance(PLAIN_ISSUES, dict) and PLAIN_ISSUES != before:
            PLAIN_ISSUES.clear()
            PLAIN_ISSUES.update(before)


def test_the_plans_table_covers_the_registry():
    """Guards this file: a criterion added to the registry must get D8 copy here too."""
    assert set(D8_ISSUES) == set(CRITERIA)


@pytest.mark.parametrize("criterion", sorted(D8_ISSUES))
def test_issue_copy_is_exactly_the_d8_table(criterion):
    present, past = D8_ISSUES[criterion]
    assert PLAIN_ISSUES[criterion].present == present
    assert PLAIN_ISSUES[criterion].past == past
    assert plain_issue(criterion) == present
    assert plain_issue(criterion, fixed=False) == present
    assert plain_issue(criterion, fixed=True) == past


def test_fixed_strings_are_exactly_the_d8_values():
    assert (GENERIC_ISSUE.present, GENERIC_ISSUE.past) == D8_GENERIC
    assert FIXED_AUTOMATICALLY == D8_STATUS[(True, True)]
    assert ADDRESSED == D8_STATUS[(False, True)]
    assert NOT_FIXED_AUTOMATICALLY == D8_STATUS[(True, False)]
    assert LEFT_FOR_JUDGEMENT == D8_STATUS[(False, False)]
    assert DECK_GRAIN_ISSUE == D8_DECK_GRAIN_ISSUE
    assert DECK_ADVISORY_HEADER_PREFIX == D8_HEADER_PREFIX
    assert DECK_ADVISORY_HEADER_SUFFIX == D8_HEADER_SUFFIX
    assert DECK_ADVISORY_CLOSING == D8_CLOSING


def test_the_tour_finding_reads_as_the_worked_example():
    """D8 worked example: the tour's open ``brief_not_delivered`` finding."""
    f = _real("brief_not_delivered", status="open", message="The slide skips the pilot timeline.")
    assert plain_finding_message(f) == (
        "This slide may not cover everything planned for it. "
        "This is a judgement call, so it was left for you to decide."
    )
    assert plain_finding_issue(f) == "This slide may not cover everything planned for it."


# ---------------------------------------------------------------------------
# Banned content, shape, length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("copy", _COPY_CASES)
def test_plain_copy_never_carries_technical_detail(copy: _Copy):
    text = copy.produce()
    assert isinstance(text, str) and text.strip(), f"empty copy: {text!r}"

    hits = [p.pattern for p in BANNED_PATTERNS if p.search(text)]
    assert not hits, f"banned content {hits} in {text!r}"

    slugs = [k for k in CRITERIA if k.lower() in text.lower()]
    assert not slugs, f"criterion slug(s) {slugs} in {text!r}"

    if copy.sentence:
        assert SENTENCE_SHAPE.fullmatch(text), f"not a capitalised, full-stopped line: {text!r}"
    if copy.third_person:
        assert not SECOND_PERSON.search(text), f"an issue sentence must stay third person: {text!r}"
    if copy.max_len is not None:
        assert len(text) <= copy.max_len, f"{len(text)} > {copy.max_len} characters: {text!r}"


def test_every_criterion_reads_differently():
    presents = [PLAIN_ISSUES[c].present for c in CRITERIA] + [GENERIC_ISSUE.present]
    pasts = [PLAIN_ISSUES[c].past for c in CRITERIA] + [GENERIC_ISSUE.past]
    assert len(set(presents)) == len(presents), f"duplicate present copy: {presents}"
    assert len(set(pasts)) == len(pasts), f"duplicate past copy: {pasts}"
    for criterion in CRITERIA:
        issue = PLAIN_ISSUES[criterion]
        assert issue.present != issue.past, criterion
    assert GENERIC_ISSUE.present != GENERIC_ISSUE.past


# ---------------------------------------------------------------------------
# Tense and status selection
# ---------------------------------------------------------------------------


def test_status_and_objectivity_choose_the_status_sentence():
    # Objective criterion.
    open_overflow = plain_finding_message(_real("overflow", status="open"))
    assert open_overflow.startswith(PLAIN_ISSUES["overflow"].present)
    assert open_overflow.endswith(NOT_FIXED_AUTOMATICALLY)
    assert open_overflow == f"{D8_ISSUES['overflow'][0]} {D8_STATUS[(True, False)]}"

    fixed_overflow = plain_finding_message(_real("overflow", status="fixed"))
    assert fixed_overflow.startswith(PLAIN_ISSUES["overflow"].past)
    assert fixed_overflow.endswith(FIXED_AUTOMATICALLY)
    assert fixed_overflow == f"{D8_ISSUES['overflow'][1]} {D8_STATUS[(True, True)]}"

    # Subjective criterion.
    open_brief = plain_finding_message(_real("brief_not_delivered", status="open"))
    assert open_brief.endswith(LEFT_FOR_JUDGEMENT)
    assert open_brief == f"{D8_ISSUES['brief_not_delivered'][0]} {D8_STATUS[(False, False)]}"

    fixed_brief = plain_finding_message(_real("brief_not_delivered", status="fixed"))
    assert fixed_brief.endswith(ADDRESSED)
    assert fixed_brief == f"{D8_ISSUES['brief_not_delivered'][1]} {D8_STATUS[(False, True)]}"

    # The four status sentences are pairwise distinct, and plain_status picks them.
    assert len({FIXED_AUTOMATICALLY, ADDRESSED, NOT_FIXED_AUTOMATICALLY, LEFT_FOR_JUDGEMENT}) == 4
    for (objective, fixed), sentence in D8_STATUS.items():
        assert plain_status(objective=objective, fixed=fixed) == sentence, (objective, fixed)

    # The issue alone is a prefix of the message, in every case.
    for c in sorted(CRITERIA) + [UNKNOWN_CRITERION]:
        for st in STATUSES:
            for ob in OBJECTIVITIES:
                f = _constructed(c, status=st, objective=ob)
                assert plain_finding_message(f).startswith(plain_finding_issue(f) + " "), (
                    c,
                    st,
                    ob,
                )


@pytest.mark.parametrize("stored_objective", OBJECTIVITIES, ids=lambda o: f"stored-objective={o}")
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("criterion", sorted(D8_ISSUES))
def test_every_finding_reads_as_its_issue_then_its_status(criterion, status, stored_objective):
    """D8 composition, from the plan's tables: issue in status tense, a space, the
    status sentence chosen by the REGISTRY's objectivity (D9), whatever is stored."""
    fixed = status == "fixed"
    expected_issue = D8_ISSUES[criterion][1 if fixed else 0]
    expected_status = D8_STATUS[(CRITERIA[criterion].objective, fixed)]
    f = _constructed(criterion, status=status, objective=stored_objective)
    assert plain_finding_issue(f) == expected_issue
    assert plain_finding_message(f) == f"{expected_issue} {expected_status}"


# ---------------------------------------------------------------------------
# The #316 example and message independence
# ---------------------------------------------------------------------------


def test_the_issue_example_becomes_one_plain_sentence_pair():
    f = Finding(
        id=make_finding_id("contrast_failure", "subjecthash", 0),
        slide_index=3,
        category="design",
        criterion="contrast_failure",
        message=ISSUE_316_MESSAGE,
        objective=True,
        status="fixed",
    )
    message = plain_finding_message(f)
    issue = plain_finding_issue(f)
    assert (
        message
        == "Some text was hard to read against its background. This was fixed automatically."
    )
    assert issue == "Some text was hard to read against its background."
    for fragment in ("#FF5F46", "3.9:1", "13px", "NOTE", "coral"):
        assert fragment.lower() not in message.lower(), fragment
        assert fragment.lower() not in issue.lower(), fragment


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("criterion", sorted(CRITERIA))
def test_plain_text_ignores_the_reviewer_message(criterion, status):
    bare = _real(criterion, status=status, message="")
    technical = _real(criterion, status=status, message=ISSUE_316_MESSAGE)
    assert bare.model_dump(exclude={"message"}) == technical.model_dump(exclude={"message"})
    assert plain_finding_message(technical) == plain_finding_message(bare)
    assert plain_finding_issue(technical) == plain_finding_issue(bare)


# ---------------------------------------------------------------------------
# Objectivity source, unknown criterion, unrecognised status
# ---------------------------------------------------------------------------


def test_objectivity_comes_from_the_registry_when_the_criterion_is_known():
    # overflow is objective in the registry; the stored False is a model's mistake.
    assert CRITERIA["overflow"].objective is True
    f = _constructed("overflow", status="open", objective=False)
    assert plain_finding_message(f).endswith(NOT_FIXED_AUTOMATICALLY)
    assert plain_finding_message(f) == f"{D8_ISSUES['overflow'][0]} {D8_STATUS[(True, False)]}"

    # The converse: brief_not_delivered is subjective; a stored True is ignored.
    assert CRITERIA["brief_not_delivered"].objective is False
    f = _constructed("brief_not_delivered", status="open", objective=True)
    assert plain_finding_message(f).endswith(LEFT_FOR_JUDGEMENT)
    f = _constructed("brief_not_delivered", status="fixed", objective=True)
    assert plain_finding_message(f).endswith(ADDRESSED)
    f = _constructed("overflow", status="fixed", objective=False)
    assert plain_finding_message(f).endswith(FIXED_AUTOMATICALLY)


def test_an_unknown_criterion_gets_the_generic_copy():
    assert UNKNOWN_CRITERION not in CRITERIA

    # Status sentence from the STORED objective (D10), generic issue, no raise.
    f = _constructed(UNKNOWN_CRITERION, status="open", objective=False)
    assert plain_finding_message(f) == f"{GENERIC_ISSUE.present} {LEFT_FOR_JUDGEMENT}"
    assert plain_finding_message(f) == f"{D8_GENERIC[0]} {D8_STATUS[(False, False)]}"
    assert plain_finding_issue(f) == D8_GENERIC[0]

    f = _constructed(UNKNOWN_CRITERION, status="open", objective=True)
    assert plain_finding_message(f) == f"{D8_GENERIC[0]} {D8_STATUS[(True, False)]}"

    f = _constructed(UNKNOWN_CRITERION, status="fixed", objective=True)
    assert plain_finding_message(f) == f"{D8_GENERIC[1]} {D8_STATUS[(True, True)]}"
    assert plain_finding_issue(f) == D8_GENERIC[1]

    f = _constructed(UNKNOWN_CRITERION, status="fixed", objective=False)
    assert plain_finding_message(f) == f"{D8_GENERIC[1]} {D8_STATUS[(False, True)]}"

    assert plain_issue(UNKNOWN_CRITERION, fixed=True) == GENERIC_ISSUE.past
    assert plain_issue(UNKNOWN_CRITERION, fixed=True) == D8_GENERIC[1]
    assert plain_issue(UNKNOWN_CRITERION) == D8_GENERIC[0]


@pytest.mark.parametrize("status", ["weird", "", None, "FIXED"], ids=repr)
@pytest.mark.parametrize("criterion", ["overflow", "brief_not_delivered"])
def test_an_unrecognised_status_reads_as_open(criterion, status):
    f = _constructed(criterion, status=status, objective=CRITERIA[criterion].objective)
    present = D8_ISSUES[criterion][0]
    open_status = D8_STATUS[(CRITERIA[criterion].objective, False)]
    assert plain_finding_issue(f) == present
    assert plain_finding_message(f) == f"{present} {open_status}"


# ---------------------------------------------------------------------------
# Deck advisory grain
# ---------------------------------------------------------------------------


def test_deck_advisory_lines_never_say_this_slide():
    deck_level = [c for c, crit in CRITERIA.items() if crit.level == "deck"]
    other = [c for c in CRITERIA if c not in deck_level]
    assert deck_level and other, "the registry must have both deck- and slide-level criteria"
    # Non-vacuity: slide copy really does say "this slide", so a pass-through would fail.
    assert any("this slide" in PLAIN_ISSUES[c].present.lower() for c in other)

    for c in deck_level:
        assert deck_advisory_issue(c) == PLAIN_ISSUES[c].present, c
        assert deck_advisory_issue(c) == D8_ISSUES[c][0], c
    for c in other + [UNKNOWN_CRITERION]:
        assert deck_advisory_issue(c) == DECK_GRAIN_ISSUE, c
        assert deck_advisory_issue(c) == D8_DECK_GRAIN_ISSUE, c
    for c in list(CRITERIA) + [UNKNOWN_CRITERION]:
        assert "this slide" not in deck_advisory_issue(c).lower(), c


# ---------------------------------------------------------------------------
# Separator
# ---------------------------------------------------------------------------


def test_the_separator_is_exact_and_never_occurs_in_copy():
    assert REVIEWER_DETAILS_SEPARATOR == D8_SEPARATOR
    label = D8_SEPARATOR.strip("\n")  # "Reviewer's details:"
    for text in _sweep_strings(include_header_fragments=True):
        assert REVIEWER_DETAILS_SEPARATOR not in text, text
        assert label not in text, text
        # The chat split and the advisory parser are line-based: no copy spans lines.
        assert "\n" not in text, repr(text)


# ---------------------------------------------------------------------------
# No prompt carries the copy
# ---------------------------------------------------------------------------


def _manifest_strings(node: object) -> List[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _manifest_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _manifest_strings(v)]
    return []


def test_copy_is_not_rendered_into_any_prompt():
    from src.core.skills import (
        build_reviewer,
        deck_reviewer,
        fix_reviewer,
        fixer,
        list_skills,
        load_skill,
    )
    from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON

    manifest_path = REPO_ROOT / "src/services/agent_definition_manifest_v1.py"
    br = build_reviewer
    prompts: Dict[str, str] = {
        "build_reviewer.INSTRUCTIONS": br.INSTRUCTIONS,
        "build_reviewer.build_instructions()": br.build_instructions(),
        "build_reviewer.BUILD_REVIEWER_CRITERIA_STAGE": br.BUILD_REVIEWER_CRITERIA_STAGE,
        "build_reviewer.BUILD_REVIEWER_AUTHORED_INSTRUCTIONS": (
            br.BUILD_REVIEWER_AUTHORED_INSTRUCTIONS
        ),
        "build_reviewer.DECK_BRIEF_REVIEW": br.DECK_BRIEF_REVIEW,
        "deck_reviewer.INSTRUCTIONS": deck_reviewer.INSTRUCTIONS,
        "fix_reviewer.INSTRUCTIONS": fix_reviewer.INSTRUCTIONS,
        "fixer.INSTRUCTIONS": fixer.INSTRUCTIONS,
        "agent_definition_manifest_v1.py (raw text)": manifest_path.read_text(encoding="utf-8"),
        # The raw source escapes apostrophes and newlines; scan the decoded values too.
        "agent_definition_manifest_v1 (decoded)": "\n".join(
            _manifest_strings(json.loads(GRAPH_VERSION_1_MANIFEST_JSON))
        ),
    }
    for name in list_skills():
        prompts[f"load_skill({name!r}).instructions"] = load_skill(name).instructions
    for where, text in prompts.items():
        assert isinstance(text, str) and text.strip(), (
            f"empty prompt source {where}: the scan would be vacuous"
        )

    copy = _sweep_strings(include_header_fragments=False) + [
        REVIEWER_DETAILS_SEPARATOR,
        REVIEWER_DETAILS_SEPARATOR.strip("\n"),
    ]
    leaks = [(where, s) for where, text in prompts.items() for s in copy if s in text]
    assert not leaks, f"plain copy rendered into a prompt: {leaks}"
