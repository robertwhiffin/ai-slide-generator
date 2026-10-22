# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""The architect never rebuilds, re-reviews, drops or re-describes an untouched blank
(#314 follow-up, Task 4; plan D5, D6, AC8, AC9; PLAN-CORRECTIONS C13-C16).

A blank slide is a spec entry whose ``purpose`` and ``content_brief`` are empty
(``is_blank_slide_spec``) over a row that is a slide frame with nothing on it
(``is_blank_slide_html``).  Two deterministic guards close the paths that would
otherwise build, judge or rewrite one nobody asked about:

* **N1** (edit turns that are not describe-only): an *untouched* blank — blank in
  the FINAL spec and neither inserted nor revised this turn — is dropped from the
  equal-length targets, from the design-contract rebuild-all and from the
  deck-level ``rebuild`` set, and ``rereview_committed_slides`` makes no judge
  call for it.  N1 is entry-based, so a blank someone typed into by hand is still
  safe from a rebuild from an empty brief.  A dropped blank the user NAMED gets one
  plain notice and one WARNING ``blank_named_but_not_described`` (m1, C13).
* **N2** (describe-only turns over a spec that describes the rows): a
  re-description with another position set is not persisted (WARNING
  ``describe_spec_positions_changed``; every deck, m4), and an invented
  description for a slide whose row and persisted entry are both still blank is
  replaced by the persisted entry.

How this file asserts, and why (m5): on ``target_positions``, the deck-level emit
metadata (``reviewed``, ``rebuilding``, ``surfaced``, ``stale``), the reviewer's
recorded call positions, ``error_state`` codes, persisted specs compared whole,
named log records and the EXISTENCE of ``info`` notice rows — never on notice
prose, except the slide NUMBER in the m1 notice, which is the thing C13 corrects.
Rows are found by ``slide_id`` (a blank row has no text to carry a marker) and
compared whole minus ``position`` and ``id``.

Helper names this file pins (call them by these names):
``nodes._description_keeps_what_it_cannot_see(spec, prior_spec, committed_rows)``
(N2; ``committed_rows`` are dicts read by ``"position"`` and ``"html"`` only) and
``rereview_committed_slides(...)["blank"]``.  N1's helpers are exercised through
``architect_node`` only, so their signatures are the implementer's.

Sabotage map (each line names what goes red; run against a throwaway reference
implementation outside the worktree before Task 4 was built):

* untouched = every blank entry (no ``- touched``) -> the agent-inserted blank
  entry (alone: a FILLED entry is not blank in the final spec, so only an inserted
  blank entry shows it);
* blankness read off the PRIOR spec, not the final one -> the restyle on an insert
  turn that moves the blank (C16(d); on an equal-length turn the revised set hides
  the difference, so the fill test cannot see it);
* both of the above -> the fill tests (equal length, twins, restyle), the
  described slide between twins, and the moved-blank restyle;
* N1 row-based (row must also be blank) -> the hand-typed-row targets case;
* N1 at the equal-length targets only -> the design-contract tests (and, with the
  rereview skip also removed, the deck-level ones — C16(b));
* touched read in the model's positions (``alignment.inserted``/``revised``) on an
  insert turn -> the gapped agent-inserted blank entry (Task 4 review);
* no rereview skip -> every reviewer-call-position assertion; skip AND rebuild-site
  drop removed -> ``rebuilding`` too; the rebuild-site drop removed alone -> the
  placeholder at an untouched blank entry (supervisor ruling; Task 4 review);
* rereview skip before ``_holds_placeholder`` -> the placeholder-at-a-blank test
  (C15); a row-based skip -> its hand-typed parametrisation;
* ``judged_nothing`` unchanged (with the skip) -> the all-blank deck;
  ``judged_nothing`` ignoring every unreviewed row -> the all-raise deck;
* notice on insert turns -> the insert anchored on a blank (C13);
* notice at every drop site -> the named blank on a restyle (C13, once per turn);
* notice numbered ``position + 1`` -> the gapped named blank (C13);
* the targets-site drop applied to ``updates`` only, not the local
  ``edit_targets`` (C14) -> red only together with the rebuild-site drop removed
  (the rebuild-site drop and the once-per-turn notice both mask it alone);
* N2(a) removed -> the dropped-entry describe-only tests (both shapes and intents);
  return ``prior_spec`` itself -> the direct identity test (C16(a));
* N2(b) without the row check -> the hand-typed describe-only test; N2(b) removed
  -> the invented-description tests;
* N2 without the ``_persisted_spec_describes_these_rows`` gate -> the stale spec.

Green before Task 4 by construction (pins, recorded per C16(c) and m11): the
alignment-driven insert-turn tests (twins, the refused blank-next-to-twins, the
new slide after a blank, the agent-inserted blank entry), the two fill directions
(equal length and restyle: they guard N1 against over-dropping), the m3
build-turn restyle, the all-blank deck's ``error_state is None`` (its
no-reviewer-call assertion is the red half), the hand-typed and stale
describe-only tests.
"""

from __future__ import annotations

import copy
import json
import logging
import queue
import re
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pytest

from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.deck_spec_slides import (
    BLANK_DECK_SPEC_ENTRY,
    BLANK_SLIDE_HTML,
    is_blank_slide_html,
    is_blank_slide_spec,
)
from src.domain.skill_io import ArchitectOutput
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import architect_node, rereview_committed_slides
from src.services.graph.state import scoped
from src.utils.slide_hash import compute_slide_hash
from tests.fixtures.notice_assertions import assert_plain_language
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    finding,
    graph_env,
    make_spec,
    review_out,
)
from tests.unit.test_architect_insert_slide import (
    NODES_LOGGER,
    PENDING_HASH,
    PENDING_HTML,
    PENDING_VERDICT,
    REFUSAL_TEXT,
    TURN,
    _canonical,
    _db_state,
    _decoded,
    _edit_out,
    _html,
    _identity,
    _named,
    _persist,
    _persisted_spec,
    _spec_of,
    _spy_on_the_shift,
)

#: A deck-derived blank shell (a section-wrapper deck's frame, plan D1).
SHELL = '<section data-label="G"><div class="slide"></div></section>'
#: The bare fallback blank.
BARE = BLANK_SLIDE_HTML
#: A blank slide someone typed into by hand: the row is no longer blank, the
#: spec entry still is.
TYPED = '<div class="slide"><h1>MK-TYPED</h1><p>typed into the blank by hand</p></div>'

NEW_AUDIENCE = "the CFO, not engineers"
RESTYLED = {"design_system_id": 7, "template_id": None, "slide_style_id": None}
NAMED_WARNING = "blank_named_but_not_described"
POSITIONS_WARNING = "describe_spec_positions_changed"

#: Any template for the deck-level fields; its one slide is always replaced.
_BASE = make_spec((0,))


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


def _entry(tag: str) -> SlideSpec:
    """A described entry (its position is set where it is placed)."""
    return SlideSpec(
        position=0,
        purpose=f"purpose {tag}",
        content_brief=f"brief {tag}",
        assumes=f"assumes {tag}",
        hands_off=f"hands-off {tag}",
        data_references=[],
    )


def _blank() -> SlideSpec:
    """A blank entry, exactly as the manual insert splices it."""
    return SlideSpec(position=0, **copy.deepcopy(BLANK_DECK_SPEC_ENTRY))


def _deck(*entries: SlideSpec, **deck) -> DeckSpec:
    """*entries* at positions ``0..n-1``."""
    return _canonical(_BASE, list(entries), **deck)


A, C, D = _entry("ALPHA"), _entry("CHARLIE"), _entry("DELTA")
B = _entry("BRAVO")
PRICING = _entry("PRICING")
NEW = _entry("NEW-SLIDE")


# ---------------------------------------------------------------------------
# Rows: rich seeds, found by slide_id
# ---------------------------------------------------------------------------


def _sid(label: str) -> str:
    return f"sid-{label}"


def _seed(env, layout: Mapping[int, Tuple[str, str]]) -> None:
    """Committed rows ``position -> (label, html)``, every column populated.

    ``slide_id`` is ``sid-<label>`` so a blank row (no text, no marker) can still
    be found after a shift.  A row whose HTML is the pending placeholder gets the
    pending verdict under its hash, exactly as ``insert_pending_slides`` writes it.
    """
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        if (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .first()
            is None
        ):
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    html_content="",
                    scripts_content=None,
                    slide_count=len(layout),
                    version=1,
                )
            )
        for day, (position, (label, html)) in enumerate(sorted(layout.items()), start=1):
            if html == PENDING_HTML:
                record = {PENDING_HASH: PENDING_VERDICT}
            else:
                record = {
                    compute_slide_hash(html): {
                        "score": 92,
                        "rating": "good",
                        "explanation": f"CURRENT-{label}",
                    }
                }
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=_sid(label),
                    html=html,
                    scripts=f"console.log('{label}');",
                    created_by=f"{label.lower()}-author@example.com",
                    created_at=datetime(2024, 1, day, 9, 0, 0),
                    modified_by=f"{label.lower()}-editor@example.com",
                    modified_at=datetime(2024, 2, day, 17, 30, 0),
                    verification_record=json.dumps(record),
                    deck_spec_slide=json.dumps(
                        {
                            "position": position,
                            "purpose": f"FRAGMENT-{label}",
                            "content_brief": "",
                            "assumes": "",
                            "hands_off": "",
                            "data_references": [],
                        }
                    ),
                )
            )
        db.commit()
    finally:
        db.close()


def _rows(env) -> List[Dict[str, Any]]:
    return [_decoded(r) for r in env.rows()]


def _by_sid(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row["slide_id"]: row for row in rows}


def _layout4(blank_html: str = SHELL) -> Dict[int, Tuple[str, str]]:
    return {
        0: ("ALPHA", _html("MK-ALPHA")),
        1: ("BLANK", blank_html),
        2: ("CHARLIE", _html("MK-CHARLIE")),
        3: ("DELTA", _html("MK-DELTA")),
    }


def _deck_with_a_blank(env, blank_html: str = SHELL) -> DeckSpec:
    """Rows ``[ALPHA, BLANK, CHARLIE, DELTA]``; the persisted spec's entry 1 is blank."""
    _seed(env, _layout4(blank_html))
    prior = _deck(A, _blank(), C, D)
    _persist(env, prior)
    return prior


# ---------------------------------------------------------------------------
# Running a turn and reading what it said
# ---------------------------------------------------------------------------


def _turn(env, out: ArchitectOutput, *, message: Optional[str] = None, describe_only=False):
    """Run ``architect_node``; return its updates, every emitted event and the
    transcript rows the turn added (``notices`` are the ``info`` ones)."""
    env.skills.set("architect", out)
    before = len(env.messages())
    overrides: Dict[str, Any] = {}
    if message is not None:
        overrides["architect_message"] = message
    if describe_only:
        overrides["describe_only"] = scoped(TURN, True)
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = architect_node(env.state(**overrides))
    finally:
        set_event_emitter(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    added = env.messages()[before:]
    return SimpleNamespace(
        updates=updates,
        events=events,
        added=added,
        notices=[m for m in added if m.get("message_type") == "info"],
    )


def _deck_level(events) -> List[Dict[str, Any]]:
    """The metadata of every deck-level re-review emit."""
    return [
        e.metadata
        for e in events
        if (e.metadata or {}).get("spec_change") == "deck_level"
    ]


def _reviewer_positions(env) -> List[int]:
    """Every ``build_reviewer`` call's position, in call order (duplicates kept)."""
    return [c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")]


def _fails_every_slide(payload):
    """A reviewer that fails whatever it is shown, for a reason a spec change can
    cause and the re-review counts as failing."""
    position = payload["position"]
    return review_out(
        position, [finding("brief_not_delivered", slide_index=position)]
    )


def _passes_every_slide(payload):
    return review_out(payload["position"])


def _always_raises(payload):
    raise RuntimeError("the reviewer is down")


def _references(env) -> List[List[int]]:
    payload = env.skills.calls_for("architect")[0]["payload"]
    return [ref["positions"] for ref in payload["slide_references"]]


def _numbers_in(text: str) -> List[str]:
    return re.findall(r"\d+", text or "")


def _build_out(spec: DeckSpec) -> ArchitectOutput:
    return ArchitectOutput(intent="build", message="Building.", deck_spec=spec)


# ---------------------------------------------------------------------------
# 0. The fixtures are what they claim (a precondition, not a behaviour)
# ---------------------------------------------------------------------------


def test_the_fixture_rows_and_entries_are_what_they_claim():
    assert is_blank_slide_html(SHELL)
    assert is_blank_slide_html(BARE)
    assert not is_blank_slide_html(TYPED)
    assert not is_blank_slide_html(_html("MK-ALPHA"))
    assert not is_blank_slide_html(PENDING_HTML)
    assert is_blank_slide_spec(_blank())
    for entry in (A, B, C, D, PRICING, NEW):
        assert not is_blank_slide_spec(entry)


# ---------------------------------------------------------------------------
# 1. Equal-length edits: the targets site (N1)
# ---------------------------------------------------------------------------


class TestEqualLengthTargets:
    @pytest.mark.parametrize(
        "blank_html", [SHELL, BARE, TYPED], ids=["shell", "bare-div", "hand-typed-row"]
    )
    def test_an_untouched_blank_the_model_targeted_is_not_built(
        self, graph_env, blank_html
    ):
        """The model revises slide 0 and also targets the blank at 1, which it
        left blank: only 0 is built.  Entry-based: a row someone typed into is
        dropped too, so an empty brief never rebuilds over their typing.  Nobody
        named the blank, so nothing is said about it.

        Sabotage: no N1 -> ``[0, 1]``; N1 row-based -> the hand-typed row red.
        """
        prior = _deck_with_a_blank(graph_env, blank_html)
        revised = _deck(_entry("ALPHA-REVISED"), _blank(), C, D)

        t = _turn(graph_env, _edit_out(revised, [0, 1]))

        assert t.updates["architect_intent"] == "edit"
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0]
        assert t.updates["deck_spec"] == revised
        assert _persisted_spec(graph_env) == revised
        assert prior.slides[1] == revised.slides[1]
        assert t.notices == []

    def test_filling_the_blank_builds_it(self, graph_env):
        """"Fill slide 2 with pricing": the model revises entry 1 and targets it.
        The entry is not blank in the FINAL spec, and it was revised, so it is
        built (in place; Task 5 proves the slide_id is kept).

        Sabotage: blankness read off the PRIOR spec with no ``- touched`` ->
        ``[]``.  Either alone stays green here (C16(d) as written cannot bite: the
        final entry is not blank, and the prior blank is in ``revised``); the
        moved-blank restyle on an insert turn is C16(d)'s proof.
        """
        _deck_with_a_blank(graph_env)
        filled = _deck(A, PRICING, C, D)

        t = _turn(
            graph_env, _edit_out(filled, [1]), message="Fill slide 2 with pricing"
        )

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [1]
        assert t.updates["deck_spec"] == filled
        assert t.notices == []

    def test_filling_one_of_two_adjacent_blanks_builds_only_that_one(self, graph_env):
        """m11: twin blank entries at 1 and 2.  Filling 2 with targets ``[1, 2]``
        builds 2 only; its twin stays untouched.

        Sabotage: no N1 -> ``[1, 2]``; prior-spec blankness with no ``- touched``
        -> ``[]``.
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("BLANK-1", SHELL),
                2: ("BLANK-2", SHELL),
                3: ("DELTA", _html("MK-DELTA")),
            },
        )
        _persist(graph_env, _deck(A, _blank(), _blank(), D))
        filled = _deck(A, _blank(), PRICING, D)

        t = _turn(graph_env, _edit_out(filled, [1, 2]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [2]

    def test_a_named_blank_left_undescribed_is_dropped_and_said_once(
        self, graph_env, caplog
    ):
        """m1 / C13 on a GAPPED deck (rows at 0, 2, 5, 6; the blank at 2 is the
        user's slide 2).  "Fill slide 2 with pricing" resolves to position 2; the
        model targets it but leaves its entry blank, so it is dropped and the turn
        says so: one ``info`` notice and one WARNING.  The notice numbers the slide
        from ``slide_numbering`` (2), not ``position + 1`` (3).

        Sabotage: no notice -> red; numbered ``position + 1`` -> "3".
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                2: ("BLANK", SHELL),
                5: ("CHARLIE", _html("MK-CHARLIE")),
                6: ("DELTA", _html("MK-DELTA")),
            },
        )
        prior = _spec_of(_BASE, [(0, A), (2, _blank()), (5, C), (6, D)])
        _persist(graph_env, prior)

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            t = _turn(
                graph_env, _edit_out(prior, [2]), message="Fill slide 2 with pricing"
            )

        assert _references(graph_env) == [[2]], "precondition: slide 2 is position 2"
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == []
        assert len(_named(caplog, NAMED_WARNING)) == 1
        assert len(t.notices) == 1, [m["content"] for m in t.added]
        numbers = _numbers_in(t.notices[0]["content"])
        assert "2" in numbers and "3" not in numbers, t.notices[0]["content"]
        # #321's plain-language property (no position, no list, no identifier),
        # not a prose pin (m5).
        assert_plain_language(t.notices[0]["content"])

    def test_a_named_blank_dropped_at_two_sites_is_said_once(self, graph_env, caplog):
        """C13: one turn can drop the same named blank at the targets site AND the
        design-contract site.  It is said once: one notice row, one WARNING.  The
        restyle still rebuilds everything else.

        Sabotage: a notice per drop site -> two.
        """
        prior = _deck_with_a_blank(graph_env)
        restyled = _deck(A, _blank(), C, D, design_contract=RESTYLED)

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            t = _turn(
                graph_env,
                _edit_out(restyled, [1]),
                message="Use the Acme brand and fill slide 2 with pricing",
            )

        assert prior.slides[1] == restyled.slides[1]
        assert _references(graph_env) == [[1]]
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 2, 3]
        assert len(_named(caplog, NAMED_WARNING)) == 1
        assert len(t.notices) == 1, [m["content"] for m in t.added]
        assert "2" in _numbers_in(t.notices[0]["content"])


# ---------------------------------------------------------------------------
# 2. The design-contract rebuild-all (N1)
# ---------------------------------------------------------------------------


class TestADesignContractChange:
    def test_a_restyle_rebuilds_every_slide_but_the_untouched_blank(self, graph_env):
        """§4.6's rebuild-all skips a blank nobody filled (its old classes stay:
        the D1 residual).  Setup as ``test_deck_level_spec_change.py``'s
        design-contract test, with rows.

        Sabotage: N1 at the equal-length targets only -> ``[0, 1, 2, 3]``.
        """
        _deck_with_a_blank(graph_env)
        restyled = _deck(A, _blank(), C, D, design_contract=RESTYLED)

        t = _turn(graph_env, _edit_out(restyled, [0]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 2, 3]
        assert t.notices == []

    def test_a_restyle_that_also_fills_the_blank_rebuilds_it_too(self, graph_env):
        """The paired direction: the same restyle with entry 1 filled rebuilds
        every position.

        Sabotage: prior-spec blankness with no ``- touched`` -> ``[0, 2, 3]``.
        """
        _deck_with_a_blank(graph_env)
        restyled = _deck(A, PRICING, C, D, design_contract=RESTYLED)

        t = _turn(graph_env, _edit_out(restyled, [1]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 1, 2, 3]

    def test_a_build_turn_restyle_is_outside_n1(self, graph_env):
        """Scope (pre-brief): N1 exists only on edit turns, so a BUILD answer's
        restyle keeps the full list, blank included — the m3 residual (a build
        replaces the deck by request).  Pinned so N1 does not silently widen.

        Sabotage: N1 on build turns -> ``[0, 2, 3]``.
        """
        _deck_with_a_blank(graph_env)
        restyled = _deck(A, _blank(), C, D, design_contract=RESTYLED)

        t = _turn(graph_env, _build_out(restyled))

        assert t.updates["architect_intent"] == "build"
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# 3. The deck-level re-review (N1, m2, C14, C15)
# ---------------------------------------------------------------------------


class TestADeckLevelChange:
    @pytest.mark.parametrize("intent", ["edit", "build"])
    def test_the_blank_is_neither_re_reviewed_nor_rebuilt(self, graph_env, intent):
        """A new audience with a reviewer that fails EVERY slide it is shown: the
        reviewer is called for 0, 2 and 3 only, those are rebuilt, and nothing is
        surfaced for the blank.  On a deck-level BUILD the rereview skip alone
        spares it (pre-brief: documented).

        Sabotage: no rereview skip -> the reviewer call positions red; skip and
        rebuild-site drop both removed -> ``rebuilding`` red as well (C16(b)).
        """
        _deck_with_a_blank(graph_env)
        graph_env.skills.set("build_reviewer", _fails_every_slide)
        retargeted = _deck(A, _blank(), C, D, audience=NEW_AUDIENCE)
        out = _edit_out(retargeted, [0]) if intent == "edit" else _build_out(retargeted)

        t = _turn(graph_env, out)

        assert _reviewer_positions(graph_env) == [0, 2, 3]
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 2, 3]
        [meta] = _deck_level(t.events)
        assert meta["reviewed"] == [0, 2, 3]
        assert meta["rebuilding"] == [0, 2, 3]
        assert 1 not in {item["position"] for item in meta["surfaced"]}
        assert meta["stale"] is False

    def test_a_named_blank_the_model_targeted_is_not_rebuilt_and_is_said_once(
        self, graph_env, caplog
    ):
        """C14: the targets-site drop reassigns the LOCAL ``edit_targets``, which
        the deck-level branch reads as ``requested``.  Every slide still fits, so
        nothing is rebuilt and the blank does not come back through ``requested``;
        the named blank is said once.

        Sabotage: drop from ``updates`` only AND remove the rebuild-site drop ->
        ``[1]`` is rebuilt (C14 alone is masked by the rebuild-site drop and the
        once-per-turn notice; the edit variant of the all-blank deck goes red on
        the same pair).
        """
        _deck_with_a_blank(graph_env)
        graph_env.skills.set("build_reviewer", _passes_every_slide)
        retargeted = _deck(A, _blank(), C, D, audience=NEW_AUDIENCE)

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            t = _turn(
                graph_env,
                _edit_out(retargeted, [1]),
                message="Retarget the deck at the CFO and fill slide 2 with pricing",
            )

        assert _references(graph_env) == [[1]]
        assert _reviewer_positions(graph_env) == [0, 2, 3]
        assert t.updates["target_positions"] == []
        [meta] = _deck_level(t.events)
        assert meta["rebuilding"] == []
        assert len(_named(caplog, NAMED_WARNING)) == 1
        assert len(t.notices) == 1, [m["content"] for m in t.added]

    def test_when_every_other_re_review_raises_the_pass_judged_nothing(
        self, graph_env
    ):
        """m2: the blank is not judged, but the slides that should have been all
        failed to be, so the pass still records the deck as stale — over the
        three slides it tried, not the blank.

        Sabotage: no rereview skip -> positions ``[0, 1, 2, 3]``; a
        ``judged_nothing`` that treats a blank as judged -> no error_state.
        """
        _deck_with_a_blank(graph_env)
        graph_env.skills.set("build_reviewer", _always_raises)
        retargeted = _deck(A, _blank(), C, D, audience=NEW_AUDIENCE)

        t = _turn(graph_env, _build_out(retargeted))

        assert _reviewer_positions(graph_env) == [0, 2, 3]
        assert t.updates["error_state"]["code"] == "rereview_judged_nothing"
        assert t.updates["error_state"]["positions"] == [0, 2, 3]
        assert t.updates["target_positions"] == []
        [meta] = _deck_level(t.events)
        assert meta["stale"] is True
        assert meta["unreviewable"] == [0, 2, 3]

    @pytest.mark.parametrize("intent", ["edit", "build"])
    def test_a_deck_of_only_blanks_is_not_judged_nothing(self, graph_env, intent):
        """m2 / C16(c): every committed row is a blank, so the pass judges nothing
        BECAUSE there is nothing to judge — not a failure.  No reviewer call, no
        ``error_state``, nothing rebuilt (on the edit, the blank the model
        targeted is untouched and dropped; nobody named it, so nothing is said).

        ``error_state is None`` is green on the pre-Task-4 code (the reviewer was
        called for the blanks); its proof is "keep the skip, revert
        ``judged_nothing``" -> ``rereview_judged_nothing``.  The no-call
        assertion is the half that is red today.
        """
        _seed(graph_env, {0: ("BLANK-1", SHELL), 1: ("BLANK-2", BARE)})
        _persist(graph_env, _deck(_blank(), _blank()))
        graph_env.skills.set("build_reviewer", _fails_every_slide)
        retargeted = _deck(_blank(), _blank(), audience=NEW_AUDIENCE)
        out = _edit_out(retargeted, [0]) if intent == "edit" else _build_out(retargeted)

        t = _turn(graph_env, out)

        assert _reviewer_positions(graph_env) == []
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == []
        assert t.notices == []
        [meta] = _deck_level(t.events)
        assert meta["stale"] is False
        assert meta["rebuilding"] == []

    def test_a_placeholder_at_an_untouched_blank_entry_is_not_rebuilt(self, graph_env):
        """Supervisor ruling: an agent-inserted blank entry whose build left a
        pending placeholder (#337) is placeheld and failing in the re-review (C15),
        but its entry is still blank and this edit did not touch it, so a
        deck-level edit does not rebuild it from an empty brief.  The rereview skip
        cannot keep it out (the placeholder check runs first); the rebuild-site
        drop is the only thing that does, and this is its one proof with the skip
        in place.

        Sabotage: no rebuild-site drop -> ``[0, 1]``.
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("PENDING", PENDING_HTML),
                2: ("CHARLIE", _html("MK-CHARLIE")),
            },
        )
        _persist(graph_env, _deck(A, _blank(), C))
        graph_env.skills.set("build_reviewer", _passes_every_slide)
        retargeted = _deck(A, _blank(), C, audience=NEW_AUDIENCE)

        t = _turn(graph_env, _edit_out(retargeted, [0]))

        assert _reviewer_positions(graph_env) == [0, 2]
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0]
        [meta] = _deck_level(t.events)
        assert meta["rebuilding"] == [0]
        assert t.notices == []


class TestTheRereviewPass:
    """``rereview_committed_slides`` called directly: ``verdicts`` is local to
    ``architect_node`` (C15)."""

    _BRAND = {
        "resolved_style": "STUB STYLE PROSE",
        "deterministic_css": "",
        "design_system_active": False,
        "template_layout_html": "",
    }

    @pytest.mark.parametrize(
        "blank_html", [SHELL, BARE, TYPED], ids=["shell", "bare-div", "hand-typed-row"]
    )
    def test_a_blank_entry_is_committed_but_never_judged(self, graph_env, blank_html):
        """m2: a blank entry is counted in ``committed`` and in the new ``blank``
        set, and in neither ``reviewed`` nor ``failing``; no model call is made
        for it.  Entry-based, like N1.

        Sabotage: no skip -> a call for 1, ``blank`` missing; row-based skip -> the
        hand-typed row red.
        """
        _seed(graph_env, _layout4(blank_html))
        graph_env.skills.set("build_reviewer", _fails_every_slide)
        spec = _deck(A, _blank(), C, D, audience=NEW_AUDIENCE)

        verdicts = rereview_committed_slides(graph_env.session_id, spec, self._BRAND, 1)

        assert _reviewer_positions(graph_env) == [0, 2, 3]
        assert verdicts["committed"] == {0, 1, 2, 3}
        assert verdicts["blank"] == {1}
        assert verdicts["reviewed"] == {0, 2, 3}
        assert verdicts["failing"] == {0, 2, 3}
        assert verdicts["placeheld"] == set()
        assert verdicts["unreviewable"] == set()
        assert {item["position"] for item in verdicts["surfaced"]} == {0, 2, 3}

    def test_a_placeholder_at_a_blank_entry_is_still_placeheld(self, graph_env):
        """C15: an agent-inserted blank entry's pending row (#337) holds a
        placeholder.  The placeholder check runs first, so it is placeheld and
        failing — no model call — and not in ``blank``.

        Sabotage: the blank check before ``_holds_placeholder`` -> ``blank == {1}``
        and ``placeheld == set()``.
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("PENDING", PENDING_HTML),
                2: ("CHARLIE", _html("MK-CHARLIE")),
            },
        )
        graph_env.skills.set("build_reviewer", _passes_every_slide)
        spec = _deck(A, _blank(), C, audience=NEW_AUDIENCE)

        verdicts = rereview_committed_slides(graph_env.session_id, spec, self._BRAND, 1)

        assert _reviewer_positions(graph_env) == [0, 2]
        assert verdicts["committed"] == {0, 1, 2}
        assert verdicts["placeheld"] == {1}
        assert verdicts["failing"] == {1}
        assert verdicts["blank"] == set()
        assert verdicts["reviewed"] == {0, 2}

    def test_a_deck_with_no_rows_still_reports_a_blank_set(self, graph_env):
        """The early-return result carries ``blank`` too, so a caller reading
        ``verdicts["blank"]`` never meets a KeyError."""
        verdicts = rereview_committed_slides(
            graph_env.session_id, _deck(A, _blank()), self._BRAND, 1
        )

        assert verdicts["committed"] == set()
        assert verdicts["blank"] == set()


# ---------------------------------------------------------------------------
# 4. Insert turns (#337 agent inserts next to blanks; m11; C13; C16(d))
# ---------------------------------------------------------------------------


class TestInsertTurns:
    def test_a_new_slide_after_the_blank_leaves_the_blank_alone(self, graph_env):
        """A new slide at 3 is the only target; the blank (found by slide_id)
        keeps its whole row, at its own position.  Green by construction: an
        insert turn targets exactly the inserted and revised slides."""
        _deck_with_a_blank(graph_env)
        before = _by_sid(_rows(graph_env))
        grown = _deck(A, _blank(), C, NEW, D)

        t = _turn(graph_env, _edit_out(grown, [3]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [3]
        after = _by_sid(_rows(graph_env))
        assert after[_sid("BLANK")]["position"] == 1
        for sid, old in before.items():
            assert _identity(after[sid]) == _identity(old), sid
        assert t.notices == []

    def test_a_described_slide_between_twin_blanks_aligns(self, graph_env):
        """m11: a non-blank new slide between two identical blank entries aligns
        (``inserted=(2,)``), targets only the new index, and both blanks keep
        their rows — the second shifted to 3."""
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("BLANK-1", SHELL),
                2: ("BLANK-2", SHELL),
                3: ("DELTA", _html("MK-DELTA")),
            },
        )
        _persist(graph_env, _deck(A, _blank(), _blank(), D))
        before = _by_sid(_rows(graph_env))
        grown = _deck(A, _blank(), NEW, _blank(), D)

        t = _turn(graph_env, _edit_out(grown, [2]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [2]
        after = _by_sid(_rows(graph_env))
        assert after[_sid("BLANK-1")]["position"] == 1
        assert after[_sid("BLANK-2")]["position"] == 3
        for sid, old in before.items():
            assert _identity(after[sid]) == _identity(old), sid

    def test_a_blank_new_slide_next_to_twin_blanks_is_refused(self, graph_env):
        """m11: a blank new entry next to identical blanks cannot be placed
        without guessing, so the edit degrades ``edit_insert_ambiguous`` and
        nothing is written."""
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("BLANK-1", SHELL),
                2: ("BLANK-2", SHELL),
                3: ("DELTA", _html("MK-DELTA")),
            },
        )
        _persist(graph_env, _deck(A, _blank(), _blank(), D))
        snapshot = _db_state(graph_env)

        t = _turn(graph_env, _edit_out(_deck(A, _blank(), _blank(), _blank(), D), [3]))

        assert t.updates["error_state"]["code"] == "edit_insert_ambiguous"
        assert t.updates["architect_message"] == REFUSAL_TEXT["edit_insert_ambiguous"]
        assert t.updates["target_positions"] is None
        assert _db_state(graph_env) == snapshot

    def test_an_agent_inserted_blank_entry_is_still_built(self, graph_env, monkeypatch):
        """#337: the model adds a slide but leaves its entry blank.  The new entry
        is INSERTED, never "untouched", so it is targeted and its pending row is
        opened (built from an empty brief: the D5 residual).

        Sabotage: no ``- touched`` -> ``[]``.
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                1: ("BRAVO", _html("MK-BRAVO")),
                2: ("CHARLIE", _html("MK-CHARLIE")),
            },
        )
        _persist(graph_env, _deck(A, B, C))
        calls = _spy_on_the_shift(monkeypatch)

        t = _turn(graph_env, _edit_out(_deck(A, _blank(), B, C), [1]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [1]
        assert len(calls) == 1 and list(calls[0]["insert_at"]) == [1]
        assert [r["html"] for r in _rows(graph_env)][1] == PENDING_HTML

    def test_an_agent_inserted_blank_entry_on_a_gapped_deck_is_built_at_its_index(
        self, graph_env, monkeypatch
    ):
        """#337 on a gapped deck (rows and spec at 0, 2, 5): the model keeps the old
        numbers and gives its blank new slide position 3, whose canonical INDEX is
        2.  On an insert turn the spec is re-stamped to indices, so "touched" is
        ``inserted_indices | revised_indices``, and the new blank is built at 2.

        Sabotage: touched from ``alignment.inserted``/``alignment.revised`` (the
        model's positions) -> the new blank reads as untouched -> ``[]``.  The
        canonical-numbered insert above cannot see this: there index == position.
        """
        _seed(
            graph_env,
            {
                0: ("ALPHA", _html("MK-ALPHA")),
                2: ("BRAVO", _html("MK-BRAVO")),
                5: ("CHARLIE", _html("MK-CHARLIE")),
            },
        )
        _persist(graph_env, _spec_of(_BASE, [(0, A), (2, B), (5, C)]))
        calls = _spy_on_the_shift(monkeypatch)
        model = _spec_of(_BASE, [(0, A), (2, B), (3, _blank()), (5, C)])

        t = _turn(graph_env, _edit_out(model, [3]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [2]
        assert t.updates["deck_spec"] == _deck(A, B, _blank(), C)
        assert len(calls) == 1 and list(calls[0]["insert_at"]) == [2]
        assert [r["html"] for r in _rows(graph_env)][2] == PENDING_HTML

    def test_an_insert_anchored_on_a_blank_says_nothing_about_it(
        self, graph_env, caplog
    ):
        """C13: on an insert turn a named slide is the ANCHOR, numbered BEFORE the
        insert.  "Add a slide after slide 2" names the blank; the restyle drops it
        from the rebuild-all (it is untouched) but no notice is raised.

        Sabotage: notice on insert turns -> one notice and the WARNING.
        """
        _deck_with_a_blank(graph_env)
        grown = _deck(A, _blank(), NEW, C, D, design_contract=RESTYLED)

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            t = _turn(
                graph_env,
                _edit_out(grown, [2]),
                message="Use the Acme brand and add a slide on pricing after slide 2",
            )

        assert _references(graph_env) == [[1]]
        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 2, 3, 4]
        assert _named(caplog, NAMED_WARNING) == []
        assert t.notices == [], [m["content"] for m in t.added]

    def test_a_restyle_on_an_insert_turn_skips_the_blank_at_its_new_position(
        self, graph_env
    ):
        """C16(d): a new slide BEFORE the blank moves it from 1 to 2.  Untouched is
        decided on the FINAL spec, so the rebuild-all skips 2 (the blank), and
        builds the new slide at 1.  The blank's row travels whole.

        Sabotage: blankness read off the prior spec -> ``[0, 1, 2, 3, 4]``.
        """
        _deck_with_a_blank(graph_env)
        before = _by_sid(_rows(graph_env))
        grown = _deck(A, NEW, _blank(), C, D, design_contract=RESTYLED)

        t = _turn(graph_env, _edit_out(grown, [1]))

        assert t.updates["error_state"] is None
        assert t.updates["target_positions"] == [0, 1, 3, 4]
        after = _by_sid(_rows(graph_env))
        assert after[_sid("BLANK")]["position"] == 2
        assert _identity(after[_sid("BLANK")]) == _identity(before[_sid("BLANK")])


# ---------------------------------------------------------------------------
# 5. Describe-only (arc-review) turns (N2, m4, D6)
# ---------------------------------------------------------------------------


class TestADescribeOnlyTurn:
    @pytest.mark.parametrize("intent", ["edit", "build"])
    @pytest.mark.parametrize(
        "placed",
        [[(0, A), (1, C), (2, D)], [(0, A), (2, C), (3, D)]],
        ids=["renumbered", "gap-left"],
    )
    def test_a_re_description_that_drops_a_slide_is_not_persisted(
        self, graph_env, caplog, intent, placed
    ):
        """N2(a): the architect sees no HTML, so a re-description with another
        position set describes slides that are not there.  The persisted spec is
        kept, the turn does not fail, and it is logged.

        Sabotage: N2(a) removed -> the three-entry spec persists.
        """
        prior = _deck_with_a_blank(graph_env)
        rows_before = _rows(graph_env)
        version_before = graph_env.deck_row().version
        shorter = _spec_of(_BASE, placed)
        out = _edit_out(shorter, [0]) if intent == "edit" else _build_out(shorter)

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            t = _turn(graph_env, out, describe_only=True)

        assert t.updates["error_state"] is None
        assert t.updates["deck_spec"] == prior
        assert _persisted_spec(graph_env) == prior
        assert len(_named(caplog, POSITIONS_WARNING)) == 1
        assert _rows(graph_env) == rows_before
        assert graph_env.deck_row().version == version_before

    @pytest.mark.parametrize("blank_html", [BARE, SHELL], ids=["bare-div", "shell"])
    def test_an_invented_description_for_a_still_blank_slide_is_discarded(
        self, graph_env, blank_html
    ):
        """N2(b): the row and the persisted entry are both still blank, so a
        purpose for entry 1 is invention (it would later fail re-review and
        rebuild the blank).  The persisted blank entry is kept; the rest of the
        re-description — a revised entry 0 and a new narrative arc — is the
        model's.

        Sabotage: N2(b) removed -> the invented entry persists.
        """
        prior = _deck_with_a_blank(graph_env, blank_html)
        graph_env.skills.set("build_reviewer", _passes_every_slide)
        arc = ["a hook", "the evidence", "the ask"]
        assert arc != prior.narrative_arc
        redescribed = _deck(
            _entry("ALPHA-REDESCRIBED"), _entry("INVENTED"), C, D, narrative_arc=arc
        )

        t = _turn(graph_env, _edit_out(redescribed, [0]), describe_only=True)

        expected = _deck(_entry("ALPHA-REDESCRIBED"), _blank(), C, D, narrative_arc=arc)
        assert t.updates["deck_spec"] == expected
        assert _persisted_spec(graph_env) == expected

    def test_a_blank_someone_typed_into_keeps_the_models_description(self, graph_env):
        """N2(b) needs BOTH blanks: the row was typed into by hand, so describing
        it is reading, not invention, and the model's entry is kept.

        Sabotage: N2(b) without the row check -> the blank entry is restored.
        """
        _deck_with_a_blank(graph_env, TYPED)
        described = _deck(A, _entry("WHAT-WAS-TYPED"), C, D)

        t = _turn(graph_env, _edit_out(described, [1]), describe_only=True)

        assert t.updates["error_state"] is None
        assert t.updates["deck_spec"] == described
        assert _persisted_spec(graph_env) == described

    def test_a_stale_persisted_spec_takes_the_models_description(self, graph_env):
        """The sweeper runs BECAUSE the spec went stale (rows at 0 and 1, the spec
        describes 0, 1 and 2).  N2 applies only when the persisted spec describes
        the rows, so the re-description persists unchanged — the blank's invented
        purpose included.

        Sabotage: N2 without the ``_persisted_spec_describes_these_rows`` gate ->
        the stale three-entry spec is kept.
        """
        _seed(graph_env, {0: ("ALPHA", _html("MK-ALPHA")), 1: ("BLANK", SHELL)})
        _persist(graph_env, _deck(A, _blank(), C))
        redescribed = _deck(A, _entry("INVENTED"))

        t = _turn(graph_env, _edit_out(redescribed, [1]), describe_only=True)

        assert t.updates["error_state"] is None
        assert t.updates["deck_spec"] == redescribed
        assert _persisted_spec(graph_env) == redescribed


class TestTheDescriptionHelper:
    """``_description_keeps_what_it_cannot_see`` called directly (C16(a)):
    through ``architect_node`` the copy is unobservable, because ``prior_spec`` is
    built inside it — and ``complete_index_only_bindings`` mutates its argument
    before ``classify_spec_change(spec, prior_spec)`` runs."""

    _ROWS = [
        {"position": 0, "html": _html("MK-ALPHA")},
        {"position": 1, "html": SHELL},
        {"position": 2, "html": _html("MK-CHARLIE")},
        {"position": 3, "html": _html("MK-DELTA")},
    ]

    def test_another_position_set_returns_a_deep_copy_of_the_prior(self, caplog):
        prior = _deck(A, _blank(), C, D)
        snapshot = prior.model_dump()

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            result = nodes._description_keeps_what_it_cannot_see(
                _deck(A, C, D), prior, self._ROWS
            )

        assert result == prior
        assert result is not prior
        for mine, theirs in zip(result.slides, prior.slides):
            assert mine is not theirs
        assert len(_named(caplog, POSITIONS_WARNING)) == 1

        result.slides[0].purpose = "MUTATED"
        result.slides[1].data_references.append("MUTATED")
        result.narrative_arc.append("MUTATED")
        result.slides.pop()
        assert prior.model_dump() == snapshot

    def test_a_kept_blank_entry_is_a_copy_of_the_prior_entry(self):
        prior = _deck(A, _blank(), C, D)
        snapshot = prior.model_dump()
        arc = ["a hook", "the ask"]
        model = _deck(_entry("ALPHA-REDESCRIBED"), _entry("INVENTED"), C, D, narrative_arc=arc)

        result = nodes._description_keeps_what_it_cannot_see(model, prior, self._ROWS)

        assert result == _deck(_entry("ALPHA-REDESCRIBED"), _blank(), C, D, narrative_arc=arc)
        assert result.slides[1] == prior.slides[1]
        assert result.slides[1] is not prior.slides[1]

        result.slides[1].data_references.append("MUTATED")
        result.slides[1].purpose = "MUTATED"
        assert prior.model_dump() == snapshot
