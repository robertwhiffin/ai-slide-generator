"""I3: every expectation field a pack's judge_prompt.md names must really reach that pack's judge.

The judge sees ``expectations = {reference, brief_or_finding, measures}``. A prompt that names an input
(``resolved_data``, ``slides``, ...) the judge never receives forces it to guess, so its verdicts
cannot be attributed. This test reads what ``judge_payload`` actually supplies for every case.
"""
import re
import types

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)

from evals.harness import case, judge

AGENTS = ["builder", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer", "architect", "data_analyst"]

# Expectation / input field names a prompt might claim the judge receives.
FIELDS = (
    "resolved_data", "slide_spec", "hands_off", "measures", "finding", "narrative_arc",
    "call_to_action", "slides", "data_request", "current_deck_spec", "message", "brief_or_finding",
)
# Bare English words: count them only when the prompt marks them as a field (`slides`).
PLAIN_WORDS = {"measures", "finding", "slides", "message"}


def _named(text):
    names = set()
    for f in FIELDS:
        pat = rf"`{f}`" if f in PLAIN_WORDS else rf"(?<![\w-]){f}(?![\w-])"
        if re.search(pat, text):
            names.add(f)
    return names


def _supplied(c, exp):
    """What the judge really gets: top-level expectation keys, brief_or_finding's keys and one level
    below them (slide_spec.hands_off), and the payload key brief_or_finding IS (fixer: ``finding``)."""
    keys = set(exp)
    bof = exp.get("brief_or_finding")
    if isinstance(bof, dict):
        keys |= set(bof)
        for v in bof.values():
            if isinstance(v, dict):
                keys |= set(v)
    if bof is not None:
        keys |= {k for k, v in c.payload.items() if v == bof}
    return keys


@pytest.mark.parametrize("agent", AGENTS)
def test_every_field_the_judge_prompt_names_is_supplied(agent):
    cases = case.load_cases(agent)
    assert cases
    # Candidate OUTPUT fields arrive in {{ outputs }}; a prompt may name those freely.
    output_fields = set().union(*(set(c.reference) for c in cases))
    named = _named(judge.judge_prompt(agent)) - output_fields
    for c in cases:
        exp = judge.judge_payload(c, types.SimpleNamespace(structured=c.reference), None)
        exp.pop("candidate")
        missing = named - _supplied(c, exp)
        assert not missing, (
            f"{agent}/{c.case_id}: judge_prompt.md names {sorted(missing)} but the judge never receives them"
        )
