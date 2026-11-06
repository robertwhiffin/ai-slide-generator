# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Speaker notes in Agent mode: the builder, reviewers and fixer (plan Task 5, D4, D5, D10).

The contract these tests hold:

* **Extract before the gate (D4).**  The builder and the fixer move an owned
  ``<aside class="speaker-notes">`` out of the model's HTML BEFORE
  ``gate_emitted_html`` scans it, so presenter prose such as "we fetch (and cache)
  it" never costs a corrective retry.  A regenerated answer is extracted too.
* **No aside means no change (D2, D5).**  An edit rebuild without an aside passes
  ``None`` and the row keeps its notes.  A build turn (``notes_reset``, branch-only)
  without an aside writes ``""``.
* **The winner's notes ship.**  A winning fix with an aside replaces the notes; a
  winning fix without one, a losing fix, and a landed original all ship the build's
  notes (``original_speaker_notes`` on the fix-map entry).
* **Typed notes are never replaced by the model (D10).**  A row whose notes are
  source ``"user"`` keeps them through an edit rebuild with an aside, a build turn
  and a winning fix with an aside.  A build turn over MODEL notes still resets them.
* **Never a model input.**  No reviewer, fixer or fix-reviewer payload carries notes.

Observed on what a user receives: rows read back off the real SQLite database
through the shipped ``SlideWriter`` (``conftest_graph``), the builder record, and
the skill calls the model stub recorded.  Only the model is stubbed; the safety gate
is the real one wherever a test names it.
"""

from __future__ import annotations

import json
import queue

import pytest

from src.api.services.slide_repository import SlideWriter
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import (
    build_branch_payload,
    build_review_payload,
    build_reviewer_node,
    builder_node,
    fix_reviewer_node,
    fixer_node,
    slide_pipeline_node,
)
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
    review_out,
)
from tests.unit.test_graph_nodes import TURN, _branch_payload, _fix_entry, _fix_state
from tests.unit.test_one_ground_on_builds import CALLOUT_STYLE, _branch_state

#: Presenter prose that trips the real scanner (``\bfetch\s*\(``) if it is scanned.
#: Used only by the two real-gate tests, so every other test's red names its own step
#: rather than failing on the gate first.
GATE_NOTES = "We fetch (and cache) it."
GATE_ASIDE = f'<aside class="speaker-notes"><p>{GATE_NOTES}</p></aside>'
#: Neutral presenter prose (the scanner passes it either way).
NOTES = "Revenue doubled, so we hire."
ASIDE = f'<aside class="speaker-notes"><p>{NOTES}</p></aside>'
BUILT = f"<div class='slide'>s0{ASIDE}</div>"
#: ``BUILT`` with the aside removed, as ``extract_speaker_notes`` reserialises it.
BUILT_STRIPPED = '<div class="slide">s0</div>'

FIX_NOTES = "Now the fix is said aloud."
FIX_ASIDE = f'<aside class="speaker-notes"><p>{FIX_NOTES}</p></aside>'
FIXED = f"<div class='slide'>fixed 0{FIX_ASIDE}</div>"
FIXED_STRIPPED = '<div class="slide">fixed 0</div>'

TYPED = "Typed."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(updates, position=0):
    return updates["slides"]["vals"][position]


def _seed_notes(env, notes, source, *, position=0, html="<div class='slide'>old</div>"):
    """A committed row at *position* carrying *notes* written by *source*."""
    SlideWriter().write_slide(
        session_id=env.session_id,
        position=position,
        html=html,
        speaker_notes=notes,
        speaker_notes_source=source,
    )
    row = env.rows()[position]
    assert row.speaker_notes == notes and row.speaker_notes_source == source


def _row(env, position=0):
    return [r for r in env.rows() if r.position == position][0]


def _drain(emitter: queue.Queue):
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    return events


def _fix_reviewer_state(env, *, fixed_html, fixed_notes, original_notes="Orig."):
    """The slide-local state the fix reviewer receives (test_graph_nodes.py:2944-2952)."""
    entry = _fix_entry(0, html="<p>original</p>", original_speaker_notes=original_notes)
    entry["in_flight"] = True
    fixed = {"html": fixed_html, "scripts": "", "changed": True}
    if fixed_notes is not None:
        fixed["speaker_notes"] = fixed_notes
    return env.state(
        turn_id=TURN,
        fix_target=0,
        fix_map=scoped(TURN, {0: entry}),
        fixed=scoped(TURN, {0: fixed}),
    )


def _flag_then_fix(env, *, fixer_html=FIXED, fix_review_findings=None):
    """Build reviewer opens a fix; the fixer answers *fixer_html*; the fix reviewer
    reports *fix_review_findings* (``None``: the fix holds)."""
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"], [finding("overflow", slide_index=payload["position"])]
        ),
    )
    env.skills.set("fixer", lambda payload: fixer_out(payload, html=fixer_html))
    env.skills.set(
        "fix_reviewer",
        lambda payload: review_out(payload["position"], fix_review_findings),
    )


# ===========================================================================
# 5.1 The builder
# ===========================================================================


def test_the_builder_moves_its_aside_into_the_record(graph_env):
    # Sabotage target: builder_node never calls extract_speaker_notes.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert record["html"] == BUILT_STRIPPED
    assert record["speaker_notes"] == NOTES


def test_the_real_safety_gate_never_sees_the_notes(graph_env):
    # Sabotage target: extract AFTER gate_emitted_html ("fetch (" forces a retry).
    graph_env.skills.set(
        "builder",
        lambda payload: builder_out(payload, html=f"<div class='slide'>s0{GATE_ASIDE}</div>"),
    )
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = builder_node(_branch_payload(graph_env, 0))
    finally:
        set_event_emitter(None)

    assert len(graph_env.skills.calls_for("builder")) == 1
    assert [e for e in _drain(emitter) if e.content == nodes.SAFETY_RETRY_NOTICE] == []
    assert "placeheld_positions" not in updates
    assert _record(updates)["speaker_notes"] == GATE_NOTES


def test_a_regenerated_answer_s_notes_win(graph_env, monkeypatch):
    # Sabotage target: _regenerate returns its html without extracting.
    def regenerating_gate(html, regenerate, session_id, on_retry=None):
        return regenerate(), True

    monkeypatch.setattr(nodes, "gate_emitted_html", regenerating_gate)
    second = "The second answer's notes."

    def handler(payload):
        if payload.get("corrective_instruction"):
            return builder_out(
                payload,
                html=f"<div class='slide'>s0<aside class=\"speaker-notes\">{second}</aside></div>",
            )
        return builder_out(payload, html=BUILT)

    graph_env.skills.set("builder", handler)

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert record["speaker_notes"] == second
    assert record["html"] == BUILT_STRIPPED


def test_no_aside_on_an_edit_turn_means_no_notes_value(graph_env):
    # Sabotage target: the record defaults speaker_notes to "" instead of None on an edit turn.
    graph_env.skills.set("builder", builder_out)

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert "speaker_notes" in record
    assert record["speaker_notes"] is None
    assert record["html"] == "<div class='slide'>slide 0</div>"  # never reserialised


def test_no_aside_on_a_build_turn_resets_the_notes(graph_env):
    # Sabotage target: builder_node ignores payload["notes_reset"] (record notes stay None).
    graph_env.skills.set("builder", builder_out)

    record = _record(builder_node(_branch_payload(graph_env, 0, notes_reset=True)))

    assert record["speaker_notes"] == ""


def test_an_aside_on_a_build_turn_is_kept(graph_env):
    # Sabotage target: notes_reset overrides an extracted aside with "".
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))

    record = _record(builder_node(_branch_payload(graph_env, 0, notes_reset=True)))

    assert record["speaker_notes"] == NOTES


# ===========================================================================
# 5.2 The draft and reviewed rows, and the fix-map entry
# ===========================================================================


def test_the_reviewed_row_stores_the_notes(graph_env):
    # Sabotage target: build_reviewer_node never passes speaker_notes to _write_reviewed_row.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    payload = _branch_payload(graph_env, 0)

    record = _record(builder_node(payload))
    build_reviewer_node(build_review_payload(record, payload))

    slide = SlideWriter().get_slide(graph_env.session_id, 0)
    assert slide["speaker_notes"] == NOTES
    assert slide["speaker_notes_source"] == "model"
    assert slide["html"] == BUILT_STRIPPED


def test_the_draft_row_stores_the_notes(graph_env):
    # Sabotage target: _write_draft_row never passes record["speaker_notes"] to write_slide.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    record = _record(builder_node(_branch_payload(graph_env, 0)))

    mutation = nodes._deck_mutation_context(
        graph_env.session_id, 1, operation="write_slide", object_type="slide"
    )
    assert nodes._write_draft_row(record, mutation) is True

    row = _row(graph_env)
    assert row.html == BUILT_STRIPPED
    assert row.speaker_notes == NOTES


def test_an_edit_rebuild_without_an_aside_keeps_the_row_s_notes(graph_env):
    # Sabotage target: the record passes "" instead of None when there is no aside (clears the row).
    _seed_notes(graph_env, "Keep.", "model")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"  # the rebuild landed
    assert row.speaker_notes == "Keep."


def test_the_fix_map_entry_carries_the_original_notes(graph_env):
    # Sabotage target: the fix-map entry omits "original_speaker_notes".
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set(
        "build_reviewer",
        lambda payload: review_out(0, [finding("overflow", slide_index=0)]),
    )
    payload = _branch_payload(graph_env, 0)
    record = _record(builder_node(payload))

    updates = build_reviewer_node(build_review_payload(record, payload))

    entry = updates["fix_map"]["vals"][0]
    assert entry["original_speaker_notes"] == NOTES
    assert entry["original_html"] == BUILT_STRIPPED


# ===========================================================================
# 5.4 The fixer
# ===========================================================================


def test_the_fixer_s_aside_is_extracted(graph_env):
    # Sabotage target: fixer_node never extracts (fixed html keeps the aside, no notes key).
    graph_env.skills.set("fixer", lambda payload: fixer_out(payload, html=FIXED))

    updates = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))

    fixed = updates["fixed"]["vals"][0]
    assert fixed["html"] == FIXED_STRIPPED
    assert fixed["speaker_notes"] == FIX_NOTES


def test_a_fixer_answer_without_an_aside_carries_no_notes_value(graph_env):
    # Sabotage target: the fixer records "" (not None) for a missing aside.
    graph_env.skills.set("fixer", fixer_out)

    updates = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))

    fixed = updates["fixed"]["vals"][0]
    assert "speaker_notes" in fixed
    assert fixed["speaker_notes"] is None


def test_the_real_safety_gate_never_sees_the_fixer_s_notes(graph_env):
    # Sabotage target: fixer extracts AFTER gate_emitted_html (two fixer calls, retry notice).
    graph_env.skills.set(
        "fixer",
        lambda payload: fixer_out(payload, html=f"<div class='slide'>fixed 0{GATE_ASIDE}</div>"),
    )
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))
    finally:
        set_event_emitter(None)

    assert len(graph_env.skills.calls_for("fixer")) == 1
    assert [e for e in _drain(emitter) if e.content == nodes.SAFETY_RETRY_NOTICE] == []
    assert updates["fixed"]["vals"][0]["speaker_notes"] == GATE_NOTES


# ===========================================================================
# 5.5 The fix reviewer, and landing the original
# ===========================================================================


def test_a_winning_fix_without_an_aside_keeps_the_original_notes(graph_env):
    # Sabotage target: a winning fix passes its None notes, no original fallback.
    graph_env.skills.set("fix_reviewer", lambda payload: review_out(0))

    fix_reviewer_node(
        _fix_reviewer_state(graph_env, fixed_html="<p>fixed</p>", fixed_notes=None)
    )

    row = _row(graph_env)
    assert row.html == "<p>fixed</p>"
    assert row.speaker_notes == "Orig."


def test_a_winning_fix_with_an_aside_replaces_the_notes(graph_env):
    # Sabotage target: fix_reviewer_node always ships original_speaker_notes.
    graph_env.skills.set("fix_reviewer", lambda payload: review_out(0))

    fix_reviewer_node(
        _fix_reviewer_state(graph_env, fixed_html="<p>fixed</p>", fixed_notes=FIX_NOTES)
    )

    row = _row(graph_env)
    assert row.html == "<p>fixed</p>"
    assert row.speaker_notes == FIX_NOTES


def test_a_losing_fix_ships_the_original_notes(graph_env):
    # Sabotage target: take fixed.get("speaker_notes") regardless of the verdict.
    graph_env.skills.set(
        "fix_reviewer", lambda payload: review_out(0, [finding("overflow", slide_index=0)])
    )

    fix_reviewer_node(
        _fix_reviewer_state(graph_env, fixed_html="<p>fixed</p>", fixed_notes=FIX_NOTES)
    )

    row = _row(graph_env)
    assert row.html == "<p>original</p>"  # the candidate lost
    assert row.speaker_notes == "Orig."


def test_landing_the_original_keeps_the_notes(graph_env):
    # Sabotage target: _land_original never passes entry["original_speaker_notes"].
    def boom(payload):
        raise RuntimeError("fixer exploded")

    graph_env.skills.set("fixer", boom)

    fixer_node(
        _fix_state(graph_env, {0: _fix_entry(0, original_speaker_notes="Orig.")})
    )

    row = _row(graph_env)
    assert row.html == "<p>original</p>"
    assert row.speaker_notes == "Orig."


# ===========================================================================
# 5.6 Never a model input
# ===========================================================================


def test_notes_never_reach_a_model_payload(graph_env):
    # Sabotage target: spread the builder record into review_payload.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    _flag_then_fix(graph_env)

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    roles = {call["name"] for call in graph_env.skills.calls}
    assert roles == {"builder", "build_reviewer", "fixer", "fix_reviewer"}
    for call in graph_env.skills.calls:
        payload = call["payload"]
        assert [k for k in payload if "notes" in k] == [], call["name"]
        dumped = json.dumps(payload)
        assert NOTES not in dumped, call["name"]
        assert FIX_NOTES not in dumped, call["name"]
        assert "speaker-notes" not in dumped, call["name"]
    # And the fix still shipped its notes, so the payloads were notes-free for a reason.
    assert _row(graph_env).speaker_notes == FIX_NOTES


# ===========================================================================
# 5.3 The branch key
# ===========================================================================


@pytest.mark.parametrize(
    "intent, builds",
    [
        pytest.param("build", True, id="build"),
        pytest.param("edit", False, id="edit"),
        pytest.param("discuss", False, id="discuss"),
        pytest.param(None, False, id="no_intent"),
    ],
)
@pytest.mark.parametrize("styled", [True, False], ids=["deck_style", "no_deck_style"])
def test_build_branch_payload_sets_notes_reset_only_on_a_build(
    graph_env, intent, builds, styled
):
    # Sabotage target: set notes_reset inside the `if spec.deck_style` block.
    state = _branch_state(
        graph_env, intent=intent, deck_style=CALLOUT_STYLE if styled else None
    )

    for position in (0, 1, 2):
        payload = build_branch_payload(state, position)
        if builds:
            assert payload.get("notes_reset") is True, position
        else:
            assert "notes_reset" not in payload, position


# ===========================================================================
# D10 Typed notes are never replaced by the model
# ===========================================================================


def test_an_edit_rebuild_with_an_aside_keeps_typed_notes(graph_env):
    # Sabotage target: drop the user guard in _upsert_slide_row (partial branch).
    _seed_notes(graph_env, TYPED, "user")
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0))

    row = _row(graph_env)
    assert row.html == BUILT_STRIPPED  # the rebuild landed, aside removed
    assert row.speaker_notes == TYPED
    assert row.speaker_notes_source == "user"


def test_a_build_turn_keeps_typed_notes(graph_env):
    # Sabotage target: the user guard (a build-turn reset "" would wipe typed notes).
    _seed_notes(graph_env, TYPED, "user")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"  # the rebuild landed
    assert row.speaker_notes == TYPED
    assert row.speaker_notes_source == "user"


def test_a_winning_fix_with_an_aside_keeps_typed_notes(graph_env):
    # Sabotage target: the user guard (the fix winner's model notes replace typed ones).
    _seed_notes(graph_env, TYPED, "user")
    graph_env.skills.set("builder", builder_out)
    _flag_then_fix(graph_env)

    slide_pipeline_node(_branch_payload(graph_env, 0))

    assert len(graph_env.skills.calls_for("fix_reviewer")) == 1
    row = _row(graph_env)
    assert row.html == FIXED_STRIPPED  # the fix won and landed, aside removed
    assert row.speaker_notes == TYPED
    assert row.speaker_notes_source == "user"


def test_a_build_turn_resets_model_notes(graph_env):
    # Sabotage target: builder_node ignores notes_reset (old model notes survive).
    _seed_notes(graph_env, "Model.", "model")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"
    assert row.speaker_notes is None
    assert row.speaker_notes_source is None
    assert SlideWriter().get_slide(graph_env.session_id, 0)["speaker_notes"] == ""
