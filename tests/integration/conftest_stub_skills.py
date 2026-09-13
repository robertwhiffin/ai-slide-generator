"""The layer-1 skill stub: one recorder that stands in for ``call_skill``.

REGISTRATION — this module is HELPERS-ONLY and is consumed by PLAIN IMPORT.
------------------------------------------------------------------------
It declares **no** ``@pytest.fixture``, so nothing here needs registering and
no test can fail on an unknown fixture.  ``tests/integration/conftest.py``
imports :class:`SkillRecorder` and builds the recorder inside its
``graph_turn_env`` fixture; the test module imports the constructors it needs
directly.  The alternative — a fixture in this file plus
``pytest_plugins = ["tests.integration.conftest_stub_skills"]`` in the suite —
was rejected because a second consumer (the conftest fixture) needs the class
anyway, and two registration mechanisms for one object is worse than none.
Pytest auto-collects only ``conftest.py``: a ``@pytest.fixture`` here would be
invisible, and every test requesting it would error.

PARAMETRISATION LIVES ON THE RECORDER, NEVER IN GRAPH STATE
-----------------------------------------------------------
``slide_count``, ``fail_positions``, ``slow_positions`` and
``objective_findings_at`` are attributes of the recorder object a test mutates
before it runs the graph.  They are deliberately NOT passed through
``invoke()``: the runtime silently drops undeclared state keys, so an earlier
draft's ``_stub_slide_count`` was discarded on every turn and every test built
three slides regardless — six failed and two passed *vacuously*.  Declaring it
in ``GraphState`` instead would put test scaffolding in the production
contract.  Neither: it lives here.

SCHEMA-VALID OUTPUTS, NEVER MAGICMOCKS
--------------------------------------
Every return value is an instance of the frozen pydantic model in
``src/domain/skill_io.py`` that the skill's ``OUTPUT_SCHEMAS`` entry names, so
the model's own validators police the stub: a ``BuilderOutput`` carrying a
``<style>`` element is rejected by ``BuilderOutput`` itself, and a ``Finding``
whose category disagrees with ``CRITERIA`` is rejected by ``Finding``.  An
unhandled skill name raises rather than returning a mock that satisfies every
assertion.

THREAD SAFETY IS NOT OPTIONAL HERE
----------------------------------
Builders are ``Send``-fanned across Pregel worker threads, so every mutation of
the recorder's own bookkeeping is taken under a lock.  ``peak_concurrent`` is
measured by that same bookkeeping: it is the high-water mark of *concurrently
executing* builder calls, which is only observable from inside the stub.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set

from src.domain.deck_spec import DeckSpec
from src.domain.finding import CRITERIA, DeckReviewOutput, Finding, SlideReviewOutput
from src.domain.skill_io import ArchitectOutput, BuilderOutput, FixerOutput

#: The criterion every objective-finding scenario uses.  ``overflow`` is
#: ``objective=True`` in ``CRITERIA``, which is what opens the fix path.
OBJECTIVE_CRITERION = "overflow"


def make_deck_spec(slide_count: int, *, title: str = "Layer-1 Stub Deck") -> DeckSpec:
    """A valid, UNPINNED ``DeckSpec`` over positions ``0..slide_count-1``.

    Unpinned (all three ``design_contract`` ids ``None``) is deliberate: with no
    ``design_system_id``/``template_id`` the architect's brand resolution takes
    neither the design-system limb of ``resolve_style_source`` nor
    ``resolve_template_bytes``, so this suite exercises the real resolvers
    without needing a design-system row or a workspace.  Brand resolution is
    C4's subject, not this suite's.
    """
    return DeckSpec(
        title=title,
        audience="Layer-1 stub audience",
        purpose="Layer-1 stub purpose",
        argument="Layer-1 stub argument",
        call_to_action="Layer-1 stub call to action",
        narrative_arc=["open", "middle", "close"],
        design_contract={},
        resolved_data={"synthesis": "stub synthesis", "figures": [], "gaps": []},
        slides=[
            {
                "position": position,
                "purpose": f"purpose-{position}",
                "content_brief": f"brief-{position}",
                "assumes": f"assumes-{position}",
                "hands_off": f"hands-off-{position}",
                "data_references": [],
                "template_section_index": None,
            }
            for position in range(slide_count)
        ],
    )


def objective_finding(position: int, message: str = "content overflows the frame") -> Finding:
    """One objective slide finding — the shape that opens a fix round.

    ``id`` is a placeholder: ``_stamp_findings`` re-mints it with the subject
    hash and a per-criterion ordinal, and re-derives ``objective`` from
    ``CRITERIA``, so what this stub sets for those two fields is discarded by
    design.  ``category`` must agree with the registry or ``Finding`` itself
    rejects it.
    """
    return Finding(
        id="stub-unstamped",
        slide_index=position,
        category=CRITERIA[OBJECTIVE_CRITERION].category,
        criterion=OBJECTIVE_CRITERION,
        message=message,
        objective=CRITERIA[OBJECTIVE_CRITERION].objective,
    )


def builder_html(position: int) -> str:
    """The canned body HTML a stub builder emits for *position*."""
    return f"<div class='slide'><h1>Slide {position}</h1></div>"


def fixed_html(position: int) -> str:
    """The canned body HTML a stub fixer emits for *position*."""
    return f"<div class='slide'><h1>Fixed {position}</h1></div>"


class SkillRecorder:
    """Stands in for ``call_skill``; every knob and every observation lives here.

    Knobs (mutate before running the graph)
    ---------------------------------------
    slide_count
        How many positions the architect's ``DeckSpec`` declares.
    fail_positions
        Builder positions whose ``call_skill`` raises — the terminal-failure path.
    slow_positions
        Builder positions that sleep ``slow_seconds`` before returning, which is
        how dispatch skew is created without a real model.
    objective_findings_at
        Positions whose ``build_reviewer`` returns one objective finding, which
        is what opens a fix round.
    surviving_defect_at
        Positions whose ``fix_reviewer`` reports the SAME criterion again, so the
        fix does not survive re-review and the original must be written back
        with the finding surfaced.
    edit_target_positions
        Non-empty makes the architect return ``intent="edit"`` over those
        positions and **no** ``deck_spec``, which is the real shape of an edit
        turn: the architect edits the spec the previous turn persisted, so
        ``architect_node`` reads it back through ``read_deck_spec`` and the turn
        runs with ``target_positions`` AND ``deck_spec`` both populated.  That
        combination is what makes the turn-coverage precedence observable —
        neither key alone can distinguish it.  Empty (the default) means a build
        turn.

    There is deliberately no deck-findings knob: what the deck reviewer DOES with
    its findings (they never enter the ``findings`` channel — §9) is pinned by
    C4's unit suite, and an unused knob here would read as coverage this suite
    does not provide.

    Observations
    ------------
    calls
        Every invocation, in completion order, as
        ``{"name", "payload", "design_system_active"}``.
    counts(name) / positions(name)
        Call count, and the sorted positions seen, for one skill.
    peak_concurrent
        High-water mark of concurrently executing builder calls.  This is the
        only place concurrency is observable: the runtime provides no
        "a slot freed" event.
    builder_started_at / builder_ended_at
        ``time.monotonic()`` per builder position, for ordering-under-skew
        assertions ("nothing outside the in-flight batch started before that
        batch completed").
    """

    def __init__(self, slide_count: int = 3) -> None:
        self.slide_count = slide_count
        self.slow_seconds: float = 0.25
        self.fail_positions: Set[int] = set()
        self.slow_positions: Set[int] = set()
        self.objective_findings_at: Set[int] = set()
        self.surviving_defect_at: Set[int] = set()
        self.edit_target_positions: Set[int] = set()

        self.calls: List[Dict[str, Any]] = []
        self.peak_concurrent: int = 0
        self.builder_started_at: Dict[int, float] = {}
        self.builder_ended_at: Dict[int, float] = {}

        self._lock = threading.Lock()
        self._live_builders = 0

    # -- configuration ------------------------------------------------------

    def configure(
        self,
        *,
        slide_count: Optional[int] = None,
        fail_positions: Iterable[int] = (),
        slow_positions: Iterable[int] = (),
        objective_findings_at: Iterable[int] = (),
        surviving_defect_at: Iterable[int] = (),
        edit_target_positions: Iterable[int] = (),
        slow_seconds: Optional[float] = None,
    ) -> "SkillRecorder":
        """Set every knob in one call and return self, for readable tests."""
        if slide_count is not None:
            self.slide_count = slide_count
        if slow_seconds is not None:
            self.slow_seconds = slow_seconds
        self.fail_positions = set(fail_positions)
        self.slow_positions = set(slow_positions)
        self.objective_findings_at = set(objective_findings_at)
        self.surviving_defect_at = set(surviving_defect_at)
        self.edit_target_positions = set(edit_target_positions)
        return self

    def reset_observations(self) -> None:
        """Clear the recorded calls and timings, keeping every knob.

        Used between turn 1 and turn 2: "turn 2 dispatched N builders" is a
        statement about turn 2's calls alone.
        """
        with self._lock:
            self.calls = []
            self.peak_concurrent = 0
            self.builder_started_at = {}
            self.builder_ended_at = {}
            self._live_builders = 0

    # -- observation --------------------------------------------------------

    def calls_for(self, name: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [call for call in self.calls if call["name"] == name]

    def counts(self, name: str) -> int:
        return len(self.calls_for(name))

    def positions(self, name: str) -> List[int]:
        """The sorted positions this skill was called for (absent ones dropped)."""
        return sorted(
            call["payload"]["position"]
            for call in self.calls_for(name)
            if isinstance(call["payload"], dict) and "position" in call["payload"]
        )

    # -- the call_skill surface --------------------------------------------

    def __call__(self, name: str, payload: dict, design_system_active: bool) -> Any:
        """``call_skill(name, payload, design_system_active)`` — three arguments."""
        with self._lock:
            self.calls.append(
                {
                    "name": name,
                    "payload": payload,
                    "design_system_active": design_system_active,
                }
            )

        handler = getattr(self, f"_skill_{name}", None)
        if handler is None:
            raise AssertionError(
                f"SkillRecorder has no handler for skill {name!r}; the graph "
                f"reached a model this suite does not stub"
            )
        return handler(payload)

    # -- per-skill handlers -------------------------------------------------

    def _skill_architect(self, payload: dict) -> ArchitectOutput:
        if self.edit_target_positions:
            # An edit turn carries target_positions and NO deck_spec: the deck it
            # edits is the one the previous turn persisted, which architect_node
            # reads back with read_deck_spec.  ArchitectOutput's own validator
            # rejects intent="edit" with an empty target_positions list.
            return ArchitectOutput(
                intent="edit",
                message=f"Editing slide(s) {sorted(self.edit_target_positions)}.",
                target_positions=sorted(self.edit_target_positions),
            )
        return ArchitectOutput(
            intent="build",
            message=f"Building {self.slide_count} slide(s).",
            deck_spec=make_deck_spec(self.slide_count),
        )

    def _skill_builder(self, payload: dict) -> BuilderOutput:
        position = payload["position"]
        with self._lock:
            self._live_builders += 1
            self.peak_concurrent = max(self.peak_concurrent, self._live_builders)
            self.builder_started_at[position] = time.monotonic()
        try:
            if position in self.slow_positions:
                time.sleep(self.slow_seconds)
            if position in self.fail_positions:
                raise RuntimeError(f"stub builder failed at position {position}")
            return BuilderOutput(
                position=position, html=builder_html(position), scripts=""
            )
        finally:
            with self._lock:
                self._live_builders -= 1
                self.builder_ended_at[position] = time.monotonic()

    def _skill_build_reviewer(self, payload: dict) -> SlideReviewOutput:
        position = payload["position"]
        findings = (
            [objective_finding(position)]
            if position in self.objective_findings_at
            else []
        )
        return SlideReviewOutput(
            slide_index=position,
            verdict="surfaced" if findings else "clean",
            findings=findings,
        )

    def _skill_fixer(self, payload: dict) -> FixerOutput:
        position = payload["position"]
        return FixerOutput(
            position=position,
            html=fixed_html(position),
            scripts="",
            changed=True,
            change_summary=f"stub fix at {position}",
        )

    def _skill_fix_reviewer(self, payload: dict) -> SlideReviewOutput:
        position = payload["position"]
        if position in self.surviving_defect_at:
            # The same criterion again: the fixer did not fix it, so the
            # original must be written back with the finding surfaced.
            return SlideReviewOutput(
                slide_index=position,
                verdict="surfaced",
                findings=[objective_finding(position, "still overflows after the fix")],
            )
        return SlideReviewOutput(slide_index=position, verdict="clean", findings=[])

    def _skill_deck_reviewer(self, payload: dict) -> DeckReviewOutput:
        """No findings: every scenario here is about orchestration, not the arc."""
        return DeckReviewOutput(findings=[])

    def _skill_data_analyst(self, payload: dict) -> Any:
        raise AssertionError(
            "the data analyst is not part of any layer-1 orchestration scenario; "
            "an ask_data turn reaching here means the architect stub changed"
        )
