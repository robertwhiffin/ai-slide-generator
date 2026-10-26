# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Graph-level acceptance for a MANUALLY inserted blank slide (#314 follow-up,
Task 5; plan D5, D6, AC4, AC8, AC9; PLAN-CORRECTIONS C11, C16(b)).

The viewer's "New slide" inserts the deck's blank shell through
``ChatService().insert_slide`` (rows and spec in one transaction).  Everything
after that is the COMPILED graph (``build_graph(checkpointer=False)``) on a real
file-backed SQLite database (``graph_env_threadsafe``): architect, foreman, the
per-slide pipeline, the deck reviewer and every row writer are the shipped code.
Only the models are stubbed, and every stub records its calls.

What is proved here, end to end:

* **AC8.** The architect's payload shows the blank entry and counts its row, so
  "Fill slide 3 with pricing" resolves to position 2 and is an equal-length edit
  of entry 2.  Exactly that position is built and reviewed, IN PLACE: the built
  slide keeps the blank's ``slide_id``.
* **AC4 through the graph.** Every other slide keeps its whole row (identity,
  authorship, timestamps, verification record, spec fragment) across the insert
  AND the turns after it, and its findings stay on it.
* **AC9.** A deck-level turn (a new audience, with a reviewer that fails every
  slide it re-reviews on an objective criterion) neither re-reviews nor rebuilds
  the blank; an arc-review (describe-only) turn that invents a purpose for the
  blank does not persist it and builds nothing; an ordinary edit of ANOTHER slide
  neither rebuilds nor drops the blank, even when the model also targets it.

How this file asserts (executing-plans-tellr §1 and §7):

* A built slide is found by the marker in its own HTML (the builder writes
  ``<h1>{purpose}</h1>``), a blank row (no text) by its ``slide_id``; never by
  position or count.
* Rows are compared WHOLE, minus ``position`` and ``id`` (``_identity``), after
  distinct authorship and timestamps are stamped per row.
* The blank's HTML is checked with ``is_blank_slide_html`` and against the deck's
  own shell (``blank_slide_shell`` over the rows it was inserted among), never
  against the bare constant.
* Model calls are sliced per turn, so "only the blank is built" is an exact list
  of positions.
* A "nothing happened to the blank" assertion is always paired with a proof that
  the turn DID something (a persisted change, a built slide), so a turn that
  silently did nothing cannot pass it.

Sabotage map (each run on the real product code, one at a time; see the Task 5
report for the exact edits):

1. N1: the rereview blank skip AND the rebuild-site drop removed -> the
   deck-level variant re-reviews and builds the blank (C16(b): the rebuild-site
   drop alone is a backstop behind the skip; the skip alone removed reddens the
   reviewer assertion);
2. N2(b) removed -> the arc-review turn persists the invented purpose;
3. a fresh ``slide_id`` on the reviewed write -> the in-place assertion;
4. N1's targets-site drop removed -> the edit of another slide whose model also
   targets the blank builds it;
5. the describe-only gate in ``architect_router`` removed -> the arc-review turn
   reaches the builders.

Green by construction (recorded, not sabotage-proved): the manual insert's own
by-marker row and finding checks under the attribution HEURISTIC (every row of a
graph-built deck has a unique ``slide_id``, so the heuristic's first pass is the
exact map), and under a ``_reindex_slide_ids`` call (it only mints an id for a
slide that has none).  Tasks 2 and 3 pin both on decks with id-less rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.database.models.session import SlideDeckVersion, UserSession
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.deck_spec_slides import (
    blank_slide_shell,
    is_blank_slide_html,
    is_blank_slide_spec,
)
from src.domain.finding import DeckReviewOutput
from src.domain.skill_io import ArchitectOutput
from src.services.foreman_service import CAP
from src.services.graph.builder import build_graph
from src.services.graph.state import scoped
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env_threadsafe is a fixture
    architect_build,
    finding,
    fixer_out,
    graph_env_threadsafe,
    make_spec,
    review_out,
)
from tests.unit.test_graph_insert_slide_turn import (
    _assert_old_rows_intact,
    _builder,
    _by_marker,
    _current_verdict,
    _deck,
    _identity,
    _insert_events,
    _marker,
    _persisted_spec,
    _positions,
    _rows,
    _slide_html,
    _stamp_authorship,
    _with_slides,
)

#: The editor: ``chat_service.get_current_username`` (the new slide's author) and
#: the route's ``inserted_by`` (the usage event).
OWNER = "owner@test.com"
#: Turn 1's build reviewer gives these slides a subjective finding: purpose-0
#: stays at 0 on an insert at 2, purpose-2 moves to 3.
FLAGGED = frozenset({"purpose-0", "purpose-2"})
#: A judge verdict on purpose-2's current hash, so a verdict left on its POSITION
#: (rather than travelling with the slide) shows on the blank.
JUDGE = {"marker": "JUDGE-purpose-2", "score": 90}

PRICING = "purpose-PRICING"
FILL_MESSAGE = "Fill slide 3 with pricing"
NEW_AUDIENCE = "the CFO, not engineers"
INVENTED = "purpose-INVENTED"
REVISED_BRIEF = "brief-0 REVISED by the user"

#: The blank entry, written out (the oracle must not depend on the code under test).
BLANK_ENTRY: Dict[str, Any] = {
    "purpose": "",
    "content_brief": "",
    "assumes": "",
    "hands_off": "",
    "data_references": [],
}


# ---------------------------------------------------------------------------
# Model stubs
# ---------------------------------------------------------------------------


def _build_reviewer(payload: dict):
    """A subjective ``brief_not_delivered`` finding on the FLAGGED slides only.

    Keyed by purpose, not position, so a finding belongs to a slide's content.
    Subjective, so no fixer runs.
    """
    purpose = payload["slide_spec"]["purpose"]
    position = payload["position"]
    if purpose not in FLAGGED:
        return review_out(position)
    return review_out(
        position,
        [
            finding(
                "brief_not_delivered",
                slide_index=position,
                message=f"{purpose} does not deliver its brief",
            )
        ],
    )


def _fails_every_rereview(payload: dict):
    """Fails, OBJECTIVELY, every slide the deck-level re-review shows it.

    The re-review is the only ``build_reviewer`` call that carries ``deck_brief``
    (``rereview_committed_slides``); the post-build reviews of the rebuilt slides
    pass, so the turn ends without a fix loop and a rebuilt slide keeps its marker.
    """
    position = payload["position"]
    if "deck_brief" in payload:
        return review_out(
            position,
            [
                finding(
                    "overflow",
                    slide_index=position,
                    message=f"position {position} contradicts the new audience",
                )
            ],
        )
    return review_out(position)


def _wire(env) -> None:
    env.skills.set("builder", _builder)
    env.skills.set("build_reviewer", _build_reviewer)
    env.skills.set("fixer", fixer_out)
    env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))


def _edit(spec: DeckSpec, targets: Sequence[int], message: str = "Editing.") -> ArchitectOutput:
    return ArchitectOutput(
        intent="edit", message=message, target_positions=list(targets), deck_spec=spec
    )


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


def _blank_at(position: int) -> SlideSpec:
    return SlideSpec(position=position, **BLANK_ENTRY)


def _entry(tag: str, position: int) -> SlideSpec:
    return SlideSpec(
        position=position,
        purpose=f"purpose-{tag}",
        content_brief=f"brief-{tag}",
        assumes=f"assumes-{tag}",
        hands_off=f"hands-off-{tag}",
        data_references=[],
    )


def _canonical(base: DeckSpec, entries: Sequence[SlideSpec]) -> DeckSpec:
    """*base*'s deck-level fields with *entries* at positions ``0..n-1``."""
    return _with_slides(base, list(enumerate(entries)))


def _replace(spec: DeckSpec, position: int, entry: SlideSpec) -> DeckSpec:
    """*spec* with the entry at *position* replaced by *entry* (re-positioned)."""
    return spec.model_copy(
        update={
            "slides": [
                entry.model_copy(update={"position": position})
                if s.position == position
                else s
                for s in spec.slides
            ]
        }
    )


def _rebriefed(spec: DeckSpec, position: int, brief: str) -> DeckSpec:
    return _replace(
        spec, position, spec.slide_at(position).model_copy(update={"content_brief": brief})
    )


# ---------------------------------------------------------------------------
# Running a turn, and reading what it did
# ---------------------------------------------------------------------------


def _run(env, turn_id: str, **overrides) -> Tuple[Dict[str, Any], List[dict]]:
    """One turn through the compiled graph; (final state, this turn's model calls).

    ``_invoke`` from ``test_graph_insert_slide_turn.py`` plus state overrides
    (the user's message, the describe-only flag).
    """
    start = len(env.skills.calls)
    graph = build_graph(checkpointer=False)
    final = graph.invoke(
        env.state(turn_id=turn_id, **overrides), {"max_concurrency": CAP}
    )
    return final, env.skills.calls[start:]


def _by_sid(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        assert row["slide_id"] not in out, f"two rows carry slide_id {row['slide_id']}"
        out[row["slide_id"]] = row
    return out


def _save_points(env) -> int:
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        return (
            db.query(SlideDeckVersion)
            .filter(SlideDeckVersion.session_id == owner.id)
            .count()
        )
    finally:
        db.close()


def _assert_findings_follow_their_slides(
    env, findings_before: Dict[str, Dict[str, Any]], expected: List[Tuple[str, int]]
) -> None:
    """Every finding is the one turn 1 minted, shown on the slide it was minted for
    (the content hash inside its own id), at the (marker, index) pairs expected."""
    deck = _deck(env)
    slides = deck["slides"]
    after = {f["id"]: f for f in deck["findings"]}
    assert set(after) == set(findings_before)
    for finding_id, f in after.items():
        assert slides[f["slideIndex"]]["content_hash"] in finding_id, (
            f"finding {finding_id} is shown on slide {f['slideIndex']}, which is not "
            "the slide it was minted for"
        )
        assert {k: v for k, v in f.items() if k != "slideIndex"} == {
            k: v for k, v in findings_before[finding_id].items() if k != "slideIndex"
        }
    assert sorted(
        (_marker(slides[f["slideIndex"]]["html"]), f["slideIndex"]) for f in after.values()
    ) == sorted(expected)
    judged = [i for i, s in enumerate(slides) if (s.get("verification") or {}).get("marker")]
    assert [(_marker(slides[i]["html"]), slides[i]["verification"]["marker"]) for i in judged] == [
        ("purpose-2", JUDGE["marker"])
    ], "the judge verdict is not on purpose-2's slide alone"


# ---------------------------------------------------------------------------
# Turn 1, and the manual insert
# ---------------------------------------------------------------------------


def _turn_1(env) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Build ``make_spec((0, 1, 2))``; return (spec, row snapshot, findings by id).

    After the build a judge verdict is merged into purpose-2's current-hash slot,
    and every row gets distinct authorship and timestamps.
    """
    _wire(env)
    spec = make_spec((0, 1, 2))
    env.skills.set("architect", architect_build(spec))
    final, _ = _run(env, "turn-1-build")
    assert final["error_state"] is None, final["error_state"]

    rows = env.rows()
    assert [(r.position, _marker(r.html)) for r in rows] == [
        (p, f"purpose-{p}") for p in range(3)
    ], "precondition: turn 1 built the three slides"
    SessionManager().write_slide_verification(
        env.session_id, 2, {compute_slide_hash(rows[2].html): dict(JUDGE)}
    )
    _stamp_authorship(env)

    before = _by_marker(_rows(env))
    assert len({r["slide_id"] for r in before.values()}) == 3
    assert len({r["created_by"] for r in before.values()}) == 3
    assert all(r["scripts"] and r["deck_spec_slide"] for r in before.values())
    assert _current_verdict(before["purpose-2"])["marker"] == JUDGE["marker"]
    findings = {f["id"]: f for f in _deck(env)["findings"]}
    assert sorted(f["slideIndex"] for f in findings.values()) == [0, 2], (
        "precondition: turn 1 left a subjective finding on slides 0 and 2"
    )
    return spec, before, findings


def _insert_blank(env, monkeypatch, position: int) -> Dict[str, Any]:
    """The viewer's "New slide" at *position*: ``ChatService().insert_slide`` with no
    HTML.  Returns the blank's row, found by the ``slide_id`` the insert minted.

    Pins what the insert itself must do on a graph-built deck: the deck's own
    shell, the editor as author, no record or fragment inherited from the slide
    that held the position, one version bump, one save point, one
    ``insert_slide`` event.
    """
    # The real lookup reaches the workspace client.
    monkeypatch.setattr(
        "src.api.services.chat_service.get_current_username", lambda: OWNER
    )
    htmls = [r.html for r in env.rows()]
    version = env.deck_row().version
    saves = _save_points(env)
    events = _insert_events(env)

    result = ChatService().insert_slide(env.session_id, position, inserted_by=OWNER)

    assert result["inserted_position"] == position
    rows = _rows(env)
    assert [r["position"] for r in rows] == list(range(len(htmls) + 1))
    blank = _by_sid(rows)[result["inserted_slide_id"]]
    assert blank["position"] == position
    assert is_blank_slide_html(blank["html"])
    assert blank["html"] == blank_slide_shell(htmls, position), (
        "the blank is not the deck's own shell"
    )
    assert blank["created_by"] == OWNER
    assert blank["verification_record"] is None, (
        "the blank inherited the record of the slide that held its position"
    )
    assert blank["deck_spec_slide"] is None, (
        "the blank inherited the fragment of the slide that held its position"
    )
    assert env.deck_row().version == version + 1
    assert _save_points(env) == saves + 1
    assert _insert_events(env) == events + 1
    return blank


def _fill_slide_3(env) -> Tuple[Dict[str, Any], List[dict]]:
    """Turn 2: "Fill slide 3 with pricing".  The model answers with the PERSISTED
    spec, entry 2 (the blank) revised to purpose-PRICING, targeting [2]."""
    persisted = _persisted_spec(env)
    assert is_blank_slide_spec(persisted.slide_at(2)), "precondition: entry 2 is the blank"
    env.skills.set(
        "architect",
        _edit(_replace(persisted, 2, _entry("PRICING", 2)), [2], "Filling slide 3."),
    )
    return _run(env, "turn-2-fill", architect_message=FILL_MESSAGE)


def _spec_after_insert(spec: DeckSpec) -> DeckSpec:
    p0, p1, p2 = (spec.slide_at(p) for p in range(3))
    return _canonical(spec, [p0, p1, _blank_at(0), p2])


# ---------------------------------------------------------------------------
# AC4 + AC8: the manual insert, then "Fill slide 3 with pricing"
# ---------------------------------------------------------------------------


class TestFillingAManuallyInsertedBlank:
    def test_the_insert_keeps_every_slide_whole_and_the_spec_gains_a_blank_entry(
        self, graph_env_threadsafe, monkeypatch
    ):
        env = graph_env_threadsafe
        spec, before, findings_before = _turn_1(env)

        blank = _insert_blank(env, monkeypatch, 2)

        rows = _rows(env)
        assert [_marker(r["html"]) for r in rows] == ["purpose-0", "purpose-1", None, "purpose-2"]
        assert rows[2]["slide_id"] == blank["slide_id"]
        _assert_old_rows_intact(rows, before)
        _assert_findings_follow_their_slides(
            env, findings_before, [("purpose-0", 0), ("purpose-2", 3)]
        )
        assert _persisted_spec(env) == _spec_after_insert(spec)

    def test_fill_slide_3_builds_only_the_blank_in_place(
        self, graph_env_threadsafe, monkeypatch
    ):
        env = graph_env_threadsafe
        spec, before, findings_before = _turn_1(env)
        blank = _insert_blank(env, monkeypatch, 2)

        final, calls = _fill_slide_3(env)

        assert (final["architect_intent"], final["error_state"]) == ("edit", None), (
            final["error_state"]
        )
        assert final["target_positions"] == [2]

        # D5 by construction: the payload shows the blank entry, counts its row,
        # and "slide 3" is position 2.
        [architect_call] = [c for c in calls if c["name"] == "architect"]
        payload = architect_call["payload"]
        shown = payload["current_deck_spec"]["slides"]
        assert len(shown) == 4
        assert shown[2]["position"] == 2 and is_blank_slide_spec(shown[2])
        assert payload["committed_slide_count"] == 4
        assert payload["slide_numbering"] == [
            {"slide_number": n + 1, "position": n} for n in range(4)
        ]
        assert [
            (ref["slide_numbers"], ref["positions"]) for ref in payload["slide_references"]
        ] == [([3], [2])]

        # Only the blank is built and reviewed; no fixer.
        assert _positions(calls, "builder") == [2]
        assert _positions(calls, "build_reviewer") == [2]
        assert _positions(calls, "fixer") == []
        [built] = [c for c in calls if c["name"] == "builder"]
        assert built["payload"]["slide_spec"]["purpose"] == PRICING

        # In place: the blank's row now holds PRICING under the blank's slide_id.
        rows = _rows(env)
        assert [_marker(r["html"]) for r in rows] == [
            "purpose-0", "purpose-1", PRICING, "purpose-2"
        ]
        filled = rows[2]
        assert filled["html"] == _slide_html(PRICING, "brief-PRICING")
        assert filled["slide_id"] == blank["slide_id"], (
            "the filled slide got a new slide_id: it was not built in place"
        )
        assert filled["created_at"] == blank["created_at"]
        assert filled["deck_spec_slide"]["purpose"] == PRICING

        # Every other slide is whole, and its findings stay on it.
        _assert_old_rows_intact(rows, before)
        _assert_findings_follow_their_slides(
            env, findings_before, [("purpose-0", 0), ("purpose-2", 3)]
        )

        persisted = _persisted_spec(env)
        assert [s.position for s in persisted.slides] == [0, 1, 2, 3]
        assert persisted == _replace(_spec_after_insert(spec), 2, _entry("PRICING", 2))
        assert _insert_events(env) == 1, "turn 2 recorded an insert_slide event"


# ---------------------------------------------------------------------------
# AC9: a deck-level turn
# ---------------------------------------------------------------------------


class TestADeckLevelTurn:
    def test_a_new_audience_neither_re_reviews_nor_rebuilds_the_blank(
        self, graph_env_threadsafe, monkeypatch
    ):
        """After the fill, a second blank at 1; then the audience changes and the
        re-review fails every slide it is shown on an objective criterion.  Every
        described slide is rebuilt; the blank reaches neither a builder nor the
        reviewer, and its row is untouched.

        Sabotage: the rereview skip AND the rebuild-site drop removed -> red
        (C16(b)); the skip alone removed -> the reviewer assertion red.
        """
        env = graph_env_threadsafe
        _turn_1(env)
        _insert_blank(env, monkeypatch, 2)
        final, _ = _fill_slide_3(env)
        assert final["error_state"] is None, final["error_state"]
        blank = _insert_blank(env, monkeypatch, 1)
        assert [_marker(r["html"]) for r in _rows(env)] == [
            "purpose-0", None, "purpose-1", PRICING, "purpose-2"
        ]
        prior = _persisted_spec(env)
        assert is_blank_slide_spec(prior.slide_at(1))
        env.skills.set("build_reviewer", _fails_every_rereview)
        retargeted = prior.model_copy(update={"audience": NEW_AUDIENCE})
        env.skills.set("architect", _edit(retargeted, [0], "Retargeting the deck."))

        final, calls = _run(
            env, "turn-4-retarget", architect_message="Retarget the deck at the CFO."
        )

        assert final["error_state"] is None, final["error_state"]
        rereviewed = sorted(
            c["payload"]["position"]
            for c in calls
            if c["name"] == "build_reviewer" and "deck_brief" in c["payload"]
        )
        assert rereviewed == [0, 2, 3, 4], "the blank was re-reviewed (judged)"
        assert 1 not in _positions(calls, "build_reviewer")
        assert _positions(calls, "builder") == [0, 2, 3, 4], "the blank was rebuilt"
        assert final["target_positions"] == [0, 2, 3, 4]

        rows = _rows(env)
        after = _by_sid(rows)[blank["slide_id"]]
        assert after["position"] == 1
        assert _identity(after) == _identity(blank), "the blank's row changed"
        assert [_marker(r["html"]) for r in rows] == [
            "purpose-0", None, "purpose-1", PRICING, "purpose-2"
        ]
        persisted = _persisted_spec(env)
        assert persisted.audience == NEW_AUDIENCE, "the turn persisted nothing"
        assert persisted.slide_at(1) == _blank_at(1)


# ---------------------------------------------------------------------------
# AC9 / D6: an arc-review (describe-only) turn
# ---------------------------------------------------------------------------


class TestAnArcReviewTurn:
    def test_an_invented_purpose_for_the_blank_is_not_persisted_and_nothing_is_built(
        self, graph_env_threadsafe, monkeypatch
    ):
        """The sweeper's architect sees no HTML.  It answers with the persisted
        spec's SAME positions (so N2(a) does not fire), an invented purpose for the
        blank and a re-description of slide 0.  The blank's entry stays blank, the
        re-description of slide 0 is the model's, and nothing is built or reviewed.

        Sabotage: N2(b) removed -> the invented purpose persists.
        """
        env = graph_env_threadsafe
        spec, _, _ = _turn_1(env)
        _insert_blank(env, monkeypatch, 2)
        rows_before = _rows(env)
        prior = _persisted_spec(env)
        assert prior == _spec_after_insert(spec)
        redescribed = _rebriefed(_replace(prior, 2, _entry("INVENTED", 2)), 0, REVISED_BRIEF)
        assert sorted(s.position for s in redescribed.slides) == [0, 1, 2, 3]
        env.skills.set("architect", _edit(redescribed, [2], "Re-describing the deck."))

        turn = "turn-2-arc-review"
        final, calls = _run(env, turn, describe_only=scoped(turn, True))

        assert final["error_state"] is None, final["error_state"]
        assert [c["name"] for c in calls] == ["architect"], (
            "a describe-only turn reached a model other than the architect"
        )
        persisted = _persisted_spec(env)
        assert persisted.slide_at(2) == _blank_at(2), "the invented purpose was persisted"
        assert persisted.slide_at(0).content_brief == REVISED_BRIEF, (
            "the turn persisted nothing"
        )
        assert persisted == _rebriefed(prior, 0, REVISED_BRIEF)
        assert _rows(env) == rows_before


# ---------------------------------------------------------------------------
# AC9: an ordinary edit of ANOTHER slide
# ---------------------------------------------------------------------------


class TestAnEditOfAnotherSlide:
    @pytest.mark.parametrize(
        "model_targets",
        [[0], [0, 2]],
        ids=["targets-only-slide-1", "model-also-targets-the-blank"],
    )
    def test_the_blank_is_neither_rebuilt_nor_dropped(
        self, graph_env_threadsafe, monkeypatch, model_targets
    ):
        """"Tighten slide 1's brief" after the insert.  Only slide 0 is rebuilt,
        in place; the blank's row and its spec entry are unchanged.

        Sabotage (the over-targeting model): N1's targets-site drop removed -> the
        blank is built from an empty brief.
        """
        env = graph_env_threadsafe
        spec, before, _ = _turn_1(env)
        blank = _insert_blank(env, monkeypatch, 2)
        prior = _persisted_spec(env)
        env.skills.set(
            "architect", _edit(_rebriefed(prior, 0, REVISED_BRIEF), model_targets, "Revising.")
        )

        final, calls = _run(
            env, "turn-2-revise-slide-1", architect_message="Tighten slide 1's brief"
        )

        assert (final["architect_intent"], final["error_state"]) == ("edit", None), (
            final["error_state"]
        )
        assert final["target_positions"] == [0]
        assert _positions(calls, "builder") == [0]
        assert _positions(calls, "build_reviewer") == [0]

        rows = _rows(env)
        assert [_marker(r["html"]) for r in rows] == ["purpose-0", "purpose-1", None, "purpose-2"]
        rebuilt = rows[0]
        assert rebuilt["html"] == _slide_html("purpose-0", REVISED_BRIEF)
        assert rebuilt["slide_id"] == before["purpose-0"]["slide_id"]
        after = _by_sid(rows)[blank["slide_id"]]
        assert after["position"] == 2
        assert _identity(after) == _identity(blank), "the blank's row changed"
        _assert_old_rows_intact(rows, {m: r for m, r in before.items() if m != "purpose-0"})

        persisted = _persisted_spec(env)
        assert [s.position for s in persisted.slides] == [0, 1, 2, 3]
        assert persisted.slide_at(2) == _blank_at(2), "the blank's spec entry changed"
        assert persisted == _rebriefed(_spec_after_insert(spec), 0, REVISED_BRIEF)
