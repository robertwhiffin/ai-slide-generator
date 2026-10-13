"""Canonical finding schema and criteria registry for the Tellr LangGraph review graph.

Ordinal rule (settled in this PR — not deferred):
    A finding's ``id`` is composed of ``{criterion}:{subject_hash}:{ordinal}`` where
    ``ordinal`` is the **0-indexed position** of this finding within the list of
    findings for that same ``(criterion, subject)`` pair.

    The message-digest alternative was rejected: a reviewer rephrasing an existing
    finding would mint a new id, causing the finding to re-highlight as unseen on
    the next turn — the exact review-fatigue failure that id stability exists to
    prevent (PRD §14).  Position is stable while the slide is unchanged, different
    once the slide is edited (new subject_hash), and unique when multiple findings
    of the same criterion appear on one subject.

    Every call site MUST supply an explicit ordinal.  The default of 0 is a trap for
    call sites that have not yet determined which finding of that criterion they hold:
    two findings stamped at ordinal 0 mint the same id, the drawer renders one, and
    dismissing it marks the other seen.

This module is pure Pydantic — no DB, no framework imports.  It lives in src/domain/
alongside slide.py and slide_deck.py and must stay that way.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, model_validator

# ---------------------------------------------------------------------------
# Primitive unions — CLOSED.
# FindingCategory is consumed by an exhaustive TypeScript
# Record<SlideFinding['category'], string> at FeedbackDrawer.tsx:13; a fourth
# value fails to compile there.
# ---------------------------------------------------------------------------

FindingCategory = Literal["content", "design", "narrative"]
FindingStatus = Literal["open", "fixed"]
FindingLevel = Literal["slide", "deck"]

# "placeholder" verdicts are constructed by commit_placeholder (ws4c/d) which
# writes error:True into the record.  "placeholder" is NOT in this union so that
# no reviewer node can accidentally mint a placeholder verdict.
SlideVerdict = Literal["clean", "fixed", "surfaced"]

# Findings are nested under this key inside each per-hash verdict.
# is_placeholder_record() checks for error:True at the verdict level; by
# nesting findings one level deeper under VERDICT_KEY the helper never
# false-positives on a real review payload.
VERDICT_KEY = "tellr_review"


# ---------------------------------------------------------------------------
# Criterion registry
# ---------------------------------------------------------------------------


class FindingCriterion(BaseModel):
    """A single reviewable criterion.  The registry (CRITERIA) is the authority."""

    name: str
    category: FindingCategory
    level: FindingLevel
    objective: bool          # PREDICATE: could an automated fixer handle this?  NOT a state.
    description: str


# Initial registry — §A2 of the ws4b brief.
# Four later PRs (ws4c-e) read this dict; editing it is outside their scope.
CRITERIA: Dict[str, FindingCriterion] = {
    "overflow": FindingCriterion(
        name="overflow",
        category="design",
        level="slide",
        objective=True,
        description=(
            "Slide content overflows the frame.  Judge against "
            "_SLIDE_FRAME_CONSTRAINTS numbers, never reviewer-invented numbers."
        ),
    ),
    "contrast_failure": FindingCriterion(
        name="contrast_failure",
        category="design",
        level="slide",
        objective=True,
        description="Text/background contrast fails WCAG AA minimum.",
    ),
    "rogue_colour": FindingCriterion(
        name="rogue_colour",
        category="design",
        level="slide",
        objective=True,
        description=(
            "Colour is outside the resolved contract — compiled artifact tokens, "
            "or the resolved style on the legacy branch."
        ),
    ),
    "distorted_image": FindingCriterion(
        name="distorted_image",
        category="design",
        level="slide",
        objective=True,
        description="Image aspect ratio is distorted.",
    ),
    "source_contradiction": FindingCriterion(
        name="source_contradiction",
        category="content",
        level="slide",
        objective=True,
        description=(
            "A figure contradicts resolved_data.  Only assertable against "
            "resolved_data; a figure with no cited source is not this finding."
        ),
    ),
    "brief_not_delivered": FindingCriterion(
        name="brief_not_delivered",
        category="content",
        level="slide",
        objective=False,
        description=(
            "The slide does not deliver what the brief asked for.  "
            "The one subjective slide criterion; exercises the drawer's "
            "actionable path with real data rather than only fixtures."
        ),
    ),
    "arc_gap": FindingCriterion(
        name="arc_gap",
        category="narrative",
        level="deck",
        objective=False,
        description="The narrative arc has a gap or unexplained jump.",
    ),
    "cross_slide_repetition": FindingCriterion(
        name="cross_slide_repetition",
        category="narrative",
        level="deck",
        objective=False,
        description="The same point is made verbatim or near-verbatim on multiple slides.",
    ),
    "missing_conclusion": FindingCriterion(
        name="missing_conclusion",
        category="narrative",
        level="deck",
        objective=False,
        description="The deck has no conclusion or call-to-action.",
    ),
}


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A single review finding attached to a slide or the deck as a whole.

    ``objective`` is a predicate about the criterion (could an automated fixer
    handle this?).  ``status`` is state about whether a fixer *did* handle it.
    They are independent: a subjective finding can be marked fixed by a human;
    an objective finding can remain open if the fixer skipped it.
    """

    id: str
    slide_index: int          # -1 for deck-level findings
    category: FindingCategory
    criterion: str
    message: str
    objective: bool           # predicate — see class docstring
    status: FindingStatus = "open"   # STATE: did a fixer handle it (§F2 branches on this)
    seen: bool = False        # initial value only; lifecycle owned client-side

    @model_validator(mode="after")
    def _validate_against_registry(self) -> "Finding":
        """Reject unknown criteria and category/registry mismatches."""
        if self.criterion not in CRITERIA:
            raise ValueError(
                f"Unknown criterion {self.criterion!r}.  "
                f"Valid criteria: {sorted(CRITERIA)}"
            )
        expected_category = CRITERIA[self.criterion].category
        if self.category != expected_category:
            raise ValueError(
                f"Criterion {self.criterion!r} is category {expected_category!r} "
                f"in the registry, but this Finding has category {self.category!r}.  "
                f"They must match."
            )
        return self


# ---------------------------------------------------------------------------
# ID minting
# ---------------------------------------------------------------------------


def make_finding_id(criterion: str, subject_hash: str, ordinal: int = 0) -> str:
    """Return a stable, unique id for one finding.

    Format: ``{criterion}:{subject_hash}:{ordinal}``

    ``ordinal`` is the 0-indexed position of this finding in the list of
    findings for the same ``(criterion, subject_hash)`` pair.

    The default of 0 is intentionally a trap: two findings stamped without an
    explicit ordinal both get ordinal 0, mint the same id, and the pair
    collapses to one in the client's seen-state map.  Every call site that can
    produce more than one finding of the same criterion on one subject MUST
    supply explicit ordinals.
    """
    return f"{criterion}:{subject_hash}:{ordinal}"


# ---------------------------------------------------------------------------
# Review output containers
# ---------------------------------------------------------------------------


class SlideReviewOutput(BaseModel):
    """Output of the slide-level reviewer node."""

    slide_index: int
    verdict: SlideVerdict
    findings: List[Finding] = []

    @property
    def objective_findings(self) -> List[Finding]:
        """Findings the auto-fixer may act on."""
        return [f for f in self.findings if f.objective]

    @property
    def subjective_findings(self) -> List[Finding]:
        """Findings that require a human decision."""
        return [f for f in self.findings if not f.objective]


class DeckReviewOutput(BaseModel):
    """Output of the deck-level reviewer node."""

    findings: List[Finding] = []


# ---------------------------------------------------------------------------
# Verification record helpers
# ---------------------------------------------------------------------------


def build_verification_record(
    *,
    content_hash: str,
    findings: List[Finding],
    verdict: SlideVerdict,
) -> Dict[str, Any]:
    """Return a ``{content_hash: verdict}`` record for storage in the verification_map.

    Shape::

        {
            content_hash: {
                VERDICT_KEY: {
                    "verdict": <SlideVerdict>,
                    "findings": [<Finding.model_dump()>, ...],
                }
            }
        }

    The findings are nested under VERDICT_KEY so that ``is_placeholder_record()``
    (which checks for ``error: True`` at the verdict-dict level) never fires on
    this payload.  Placeholder records are written by ``commit_placeholder`` with
    ``error: True`` at the same level; VERDICT_KEY is never "error".

    The record has exactly one top-level key (``content_hash``) so that
    ``get_verification_map`` can merge a sequence of these records into a flat
    ``{content_hash: verdict}`` dict without losing entries.
    """
    return {
        content_hash: {
            VERDICT_KEY: {
                "verdict": verdict,
                "findings": [f.model_dump() for f in findings],
            }
        }
    }


def findings_from_record(
    record: Dict[str, Any],
    content_hash: str,
) -> List[Finding]:
    """Reconstruct the findings list from a verification record.

    Returns an empty list when:
    - ``record`` is not a dict
    - ``content_hash`` is absent from ``record``
    - the entry has no VERDICT_KEY payload
    - individual finding dicts fail validation (they are skipped)
    """
    if not isinstance(record, dict):
        return []
    entry = record.get(content_hash)
    if not isinstance(entry, dict):
        return []
    review_data = entry.get(VERDICT_KEY)
    if not isinstance(review_data, dict):
        return []
    raw_findings = review_data.get("findings") or []
    result: List[Finding] = []
    for raw in raw_findings:
        if isinstance(raw, dict):
            try:
                result.append(Finding(**raw))
            except Exception:
                pass
    return result
