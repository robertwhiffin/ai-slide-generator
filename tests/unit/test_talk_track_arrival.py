# ruff: noqa: F811 — the shared fixtures are imported, then requested by name.
"""Every arrival path carries BOTH presenter fields (talk track plan, Task 2).

A slide's talk track (``talk_track`` / ``talk_track_source``) arrives exactly where
its notes do, and each field is protected on its own:

* **Agent mode.**  The builder and the fixer move both asides out of the HTML
  BEFORE ``gate_emitted_html`` scans it; a corrective retry's answer wins for both
  fields; a build turn (``notes_reset``) with no talk-track aside writes ``""``.
  The reviewed row, the draft row, the fix-map entry (``original_talk_track``), a
  winning or losing fix and a landed original all STORE the right talk track,
  observed on ``SlideWriter.write_slide``'s recorded call AND on the row read back.
  The fix reviewer starts from the ORIGINAL pair and takes the fixer's talk track
  only when the fix wins and the fixer brought one (plan review round 2, I-B).
* **Never a model input.**  No skill payload carries either field or an aside.
* **Legacy mode and chat edits.**  ``_parse_slide_replacements`` reads both asides;
  a replacement (``_apply_slide_replacements`` and the RC8 branch) refreshes ONLY the
  model-owned field (Review Focus 1); a user HTML save and an insert move a
  talk-track aside into the field as source ``"user"``.
* **The notes-only save.**  ``update_slide_notes(..., talk_track=...)`` changes only
  the field it is given (Review Focus 5), and its route takes either field but
  refuses a body with neither.

Sources (``"model"`` / ``"user"`` / ``None``) are asserted beside every text.
Only the model is stubbed in the graph tests; the database is the real SQLite one
(``conftest_graph``).  Each test names the production change that turns it red.
"""

from __future__ import annotations

import inspect
import json
import queue
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from src.api.services.session_manager import SessionManager, VersionConflictError
from src.api.services.slide_repository import SlideWriter
from src.database.models.session import SessionSlide, UserSession
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import (
    build_branch_payload,  # noqa: F401 — kept beside its siblings for readers
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
    review_out,
)
from tests.unit.test_graph_nodes import TURN, _branch_payload, _fix_entry, _fix_state
from tests.unit.test_manual_insert_service import (  # noqa: F401 — fixtures
    OWNER_SID,
    _rows,
    factory,
    seeded,
    service,
)
from tests.unit.test_speaker_notes_legacy import (  # noqa: F401 — agent_stub is a fixture
    _drive_rc8,
    _replace,
    _saved_deck_dict,
    _service,
    _session_manager,
    agent_stub,
)
from tests.unit.test_speaker_notes_save import SID as ROUTE_SID
from tests.unit.test_speaker_notes_save import (  # noqa: F401 — every name is a fixture
    client,  # noqa: F401
    env,  # noqa: F401
    events,  # noqa: F401
    locks,  # noqa: F401
    marks,  # noqa: F401
    route,  # noqa: F401
    slide_gate,  # noqa: F401
    stub_service,  # noqa: F401
)

# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

#: Presenter prose that trips the real scanner (``\bfetch\s*\(``) if it is scanned.
GATE_TALK = "We fetch (and cache) it, then pause."
GATE_TALK_ASIDE = f'<aside data-presenter="talk-track" hidden><p>{GATE_TALK}</p></aside>'

TALK = "Revenue grew twelve percent. Ask which region led."
TALK_ASIDE = f'<aside data-presenter="talk-track" hidden><p>{TALK}</p></aside>'
NOTES = "Source: the sales table, third quarter."
NOTES_ASIDE = f'<aside data-presenter="speaker-notes" hidden><p>{NOTES}</p></aside>'
BUILT = f"<div class='slide'>s0{TALK_ASIDE}{NOTES_ASIDE}</div>"
BUILT_STRIPPED = '<div class="slide">s0</div>'

FIX_TALK = "Now the fixed slide is said aloud."
FIX_TALK_ASIDE = f'<aside data-presenter="talk-track" hidden><p>{FIX_TALK}</p></aside>'
FIX_NOTES = "Fixed slide background."
FIX_NOTES_ASIDE = f'<aside data-presenter="speaker-notes" hidden><p>{FIX_NOTES}</p></aside>'
FIXED = f"<div class='slide'>fixed 0{FIX_TALK_ASIDE}{FIX_NOTES_ASIDE}</div>"
FIXED_STRIPPED = '<div class="slide">fixed 0</div>'

ORIG_TALK = "The original slide's talk track."
ORIG_NOTES = "The original slide's notes."

TYPED_TALK = "Typed talk track."
TYPED_NOTES = "Typed notes."

#: Every marker an aside could leak through, in HTML or a dumped payload.
ASIDE_MARKERS = ("<aside", "data-presenter", "talk-track", "speaker-notes")


# ---------------------------------------------------------------------------
# Spies and helpers (graph)
# ---------------------------------------------------------------------------


@pytest.fixture
def writes(monkeypatch) -> List[Dict[str, Any]]:
    """Record every ``SlideWriter.write_slide`` call with defaults applied, then
    write for real, so a test checks the call AND the row it produced."""
    calls: List[Dict[str, Any]] = []
    real = SlideWriter.write_slide
    signature = inspect.signature(real)

    def spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        arguments.pop("self", None)
        calls.append(arguments)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SlideWriter, "write_slide", spy)
    return calls


@pytest.fixture
def gate_inputs(monkeypatch) -> List[str]:
    """Record the HTML ``gate_emitted_html`` scans; the real gate still runs."""
    seen: List[str] = []
    real = nodes.gate_emitted_html

    def spy(html, *args, **kwargs):
        seen.append(html)
        return real(html, *args, **kwargs)

    monkeypatch.setattr(nodes, "gate_emitted_html", spy)
    return seen


def _record(updates, position=0):
    return updates["slides"]["vals"][position]


def _row(env_, position=0):
    return [r for r in env_.rows() if r.position == position][0]


def _pair(row) -> Dict[str, Any]:
    return {
        "talk_track": row.talk_track,
        "talk_track_source": row.talk_track_source,
        "speaker_notes": row.speaker_notes,
        "speaker_notes_source": row.speaker_notes_source,
    }


def _seed(env_, *, talk=None, talk_source="model", notes=None, notes_source="model"):
    """A committed row at position 0 carrying the given presenter fields."""
    SlideWriter().write_slide(
        session_id=env_.session_id,
        position=0,
        html="<div class='slide'>old</div>",
        speaker_notes=notes,
        speaker_notes_source=notes_source,
        talk_track=talk,
        talk_track_source=talk_source,
    )
    row = _row(env_)
    assert row.talk_track == talk and row.speaker_notes == notes, "seed did not land"


def _writes_at(writes, position=0):
    return [c for c in writes if c["position"] == position]


def _drain(emitter: queue.Queue):
    events_ = []
    while not emitter.empty():
        events_.append(emitter.get_nowait())
    return events_


def _no_aside(html: str) -> None:
    for marker in ASIDE_MARKERS:
        assert marker not in html, f"{marker!r} reached the HTML: {html!r}"


# ===========================================================================
# The builder
# ===========================================================================


def test_builder_moves_both_asides_before_gate(graph_env, gate_inputs):
    # Sabotage: builder_node keeps extract_speaker_notes (talk track dropped), or
    # extracts after gate_emitted_html.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert len(gate_inputs) == 1
    _no_aside(gate_inputs[0])
    assert TALK not in gate_inputs[0] and NOTES not in gate_inputs[0]
    assert record["html"] == BUILT_STRIPPED
    assert record["talk_track"] == TALK
    assert record["speaker_notes"] == NOTES


def test_the_real_gate_never_sees_the_talk_track(graph_env):
    # Sabotage: extract the talk-track aside AFTER gate_emitted_html ("fetch (" forces a retry).
    graph_env.skills.set(
        "builder",
        lambda payload: builder_out(payload, html=f"<div class='slide'>s0{GATE_TALK_ASIDE}</div>"),
    )
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = builder_node(_branch_payload(graph_env, 0))
    finally:
        set_event_emitter(None)

    assert len(graph_env.skills.calls_for("builder")) == 1
    assert [e for e in _drain(emitter) if e.content == nodes.SAFETY_RETRY_NOTICE] == []
    assert _record(updates)["talk_track"] == GATE_TALK
    assert _record(updates)["speaker_notes"] is None


def _regenerating(monkeypatch):
    def regenerating_gate(html, regenerate, session_id, on_retry=None):
        return regenerate(), True

    monkeypatch.setattr(nodes, "gate_emitted_html", regenerating_gate)


def test_builder_retry_carries_talk_track(graph_env, monkeypatch):
    # Sabotage: _regenerate extracts only the notes (captured has no "talk" slot),
    # so the first answer's talk track ships with the retry's HTML.
    _regenerating(monkeypatch)
    second = "The second answer's talk track."

    def handler(payload):
        if payload.get("corrective_instruction"):
            return builder_out(
                payload,
                html=(
                    "<div class='slide'>s0"
                    f'<aside data-presenter="talk-track" hidden><p>{second}</p></aside>'
                    "</div>"
                ),
            )
        return builder_out(payload, html=BUILT)

    graph_env.skills.set("builder", handler)

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert record["html"] == BUILT_STRIPPED
    assert record["talk_track"] == second
    # The retry's answer wins for BOTH fields: it brought no notes aside.
    assert record["speaker_notes"] is None


def test_builder_retry_without_a_talk_track_drops_the_first_answers(graph_env, monkeypatch):
    # Sabotage: keep the first answer's talk track when the retry brought none.
    _regenerating(monkeypatch)

    def handler(payload):
        if payload.get("corrective_instruction"):
            return builder_out(payload, html=f"<div class='slide'>s0{NOTES_ASIDE}</div>")
        return builder_out(payload, html=f"<div class='slide'>s0{TALK_ASIDE}</div>")

    graph_env.skills.set("builder", handler)

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert record["talk_track"] is None
    assert record["speaker_notes"] == NOTES


def test_no_talk_track_aside_on_an_edit_turn_means_no_value(graph_env):
    # Sabotage: default the record's talk_track to "" (it would clear the row) or omit the key.
    graph_env.skills.set(
        "builder",
        lambda payload: builder_out(payload, html=f"<div class='slide'>s0{NOTES_ASIDE}</div>"),
    )

    record = _record(builder_node(_branch_payload(graph_env, 0)))

    assert "talk_track" in record
    assert record["talk_track"] is None
    assert record["speaker_notes"] == NOTES


def test_build_turn_resets_missing_talk_track(graph_env):
    # Sabotage: under notes_reset, reset only speaker_notes (talk_track stays None).
    graph_env.skills.set("builder", builder_out)

    record = _record(builder_node(_branch_payload(graph_env, 0, notes_reset=True)))

    assert record["talk_track"] == ""
    assert record["speaker_notes"] == ""


def test_build_turn_resets_talk_track_beside_an_extracted_note(graph_env):
    # Sabotage: reset talk_track only when BOTH asides are missing.
    graph_env.skills.set(
        "builder",
        lambda payload: builder_out(payload, html=f"<div class='slide'>s0{NOTES_ASIDE}</div>"),
    )

    record = _record(builder_node(_branch_payload(graph_env, 0, notes_reset=True)))

    assert record["talk_track"] == ""
    assert record["speaker_notes"] == NOTES


def test_a_talk_track_aside_on_a_build_turn_is_kept(graph_env):
    # Sabotage: notes_reset overrides an extracted talk track with "".
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))

    record = _record(builder_node(_branch_payload(graph_env, 0, notes_reset=True)))

    assert record["talk_track"] == TALK
    assert record["speaker_notes"] == NOTES


# ===========================================================================
# The reviewed row, the draft row and the fix-map entry
# ===========================================================================


def test_the_reviewed_row_stores_the_talk_track(graph_env, writes):
    # Sabotage: build_reviewer_node never passes talk_track to _write_reviewed_row
    # (or _write_reviewed_row never passes it to write_slide).
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    payload = _branch_payload(graph_env, 0)

    record = _record(builder_node(payload))
    build_reviewer_node(build_review_payload(record, payload))

    (call,) = _writes_at(writes)
    assert call["talk_track"] == TALK
    assert call["speaker_notes"] == NOTES
    assert call["html"] == BUILT_STRIPPED
    slide = SlideWriter().get_slide(graph_env.session_id, 0)
    assert slide["talk_track"] == TALK and slide["talk_track_source"] == "model"
    assert slide["speaker_notes"] == NOTES and slide["speaker_notes_source"] == "model"


def test_draft_row_fallback_stores_talk_track(graph_env, writes):
    # Sabotage: _write_draft_row never passes record["talk_track"] to write_slide.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    record = _record(builder_node(_branch_payload(graph_env, 0)))

    mutation = nodes._deck_mutation_context(
        graph_env.session_id, 1, operation="write_slide", object_type="slide"
    )
    assert nodes._write_draft_row(record, mutation) is True

    (call,) = _writes_at(writes)
    assert call["talk_track"] == TALK
    assert call["speaker_notes"] == NOTES
    assert _pair(_row(graph_env)) == {
        "talk_track": TALK,
        "talk_track_source": "model",
        "speaker_notes": NOTES,
        "speaker_notes_source": "model",
    }


def test_the_landing_write_fallback_stores_talk_track(graph_env, writes):
    # Sabotage: the replace_real=True branch of _write_draft_row drops talk_track.
    _seed(graph_env, talk="Old talk.", notes="Old notes.")
    writes.clear()
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    record = _record(builder_node(_branch_payload(graph_env, 0)))

    mutation = nodes._deck_mutation_context(
        graph_env.session_id, 1, operation="write_slide", object_type="slide"
    )
    assert nodes._write_draft_row(record, mutation, replace_real=True) is True

    (call,) = _writes_at(writes)
    assert call["talk_track"] == TALK
    assert _row(graph_env).talk_track == TALK
    assert _row(graph_env).talk_track_source == "model"


def test_the_fix_map_entry_carries_the_original_talk_track(graph_env, writes):
    # Sabotage: the fix-map entry omits "original_talk_track".
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set(
        "build_reviewer",
        lambda payload: review_out(0, [finding("overflow", slide_index=0)]),
    )
    payload = _branch_payload(graph_env, 0)
    record = _record(builder_node(payload))

    updates = build_reviewer_node(build_review_payload(record, payload))

    entry = updates["fix_map"]["vals"][0]
    assert entry["original_talk_track"] == TALK
    assert entry["original_speaker_notes"] == NOTES
    assert entry["original_html"] == BUILT_STRIPPED
    assert _writes_at(writes) == [], "a flagged slide is not written by the build reviewer"


def test_an_edit_rebuild_without_a_talk_track_keeps_the_row_s(graph_env):
    # Sabotage: the record passes "" for a missing talk-track aside on an edit turn.
    _seed(graph_env, talk="Keep this talk.", notes="Keep these notes.")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"  # the rebuild landed
    assert _pair(row) == {
        "talk_track": "Keep this talk.",
        "talk_track_source": "model",
        "speaker_notes": "Keep these notes.",
        "speaker_notes_source": "model",
    }


# ===========================================================================
# The fixer
# ===========================================================================


def test_fixer_carries_talk_track(graph_env, writes, gate_inputs):
    # Sabotage: fixer_node extracts only notes (the "fixed" entry has no talk_track),
    # or fix_reviewer_node never ships fixed["talk_track"].
    graph_env.skills.set("fixer", lambda payload: fixer_out(payload, html=FIXED))

    updates = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))

    fixed = updates["fixed"]["vals"][0]
    assert fixed["html"] == FIXED_STRIPPED
    assert fixed["talk_track"] == FIX_TALK
    assert fixed["speaker_notes"] == FIX_NOTES
    assert len(gate_inputs) == 1
    _no_aside(gate_inputs[0])

    # And the stored row: the fix wins, so its talk track is what is written.
    graph_env.skills.set("fix_reviewer", lambda payload: review_out(0))
    fix_reviewer_node(
        graph_env.state(
            turn_id=TURN,
            fix_target=0,
            fix_map=scoped(TURN, {0: {**_fix_entry(0), "in_flight": True}}),
            fixed=scoped(TURN, {0: fixed}),
        )
    )
    (call,) = _writes_at(writes)
    assert call["html"] == FIXED_STRIPPED
    assert call["talk_track"] == FIX_TALK
    assert call["speaker_notes"] == FIX_NOTES
    row = _row(graph_env)
    assert (row.talk_track, row.talk_track_source) == (FIX_TALK, "model")


def test_a_fixer_answer_without_a_talk_track_carries_no_value(graph_env):
    # Sabotage: the fixer records "" (not None) for a missing talk-track aside, or omits the key.
    graph_env.skills.set("fixer", fixer_out)

    updates = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))

    fixed = updates["fixed"]["vals"][0]
    assert "talk_track" in fixed
    assert fixed["talk_track"] is None


def test_fixer_retry_carries_talk_track(graph_env, monkeypatch):
    # Sabotage: the fixer's _regenerate extracts only the notes.
    _regenerating(monkeypatch)
    second = "The fixer's retry talk track."

    def handler(payload):
        if payload.get("corrective_instruction"):
            return fixer_out(
                payload,
                html=(
                    "<div class='slide'>fixed 0"
                    f'<aside data-presenter="talk-track" hidden><p>{second}</p></aside>'
                    "</div>"
                ),
            )
        return fixer_out(payload, html=FIXED)

    graph_env.skills.set("fixer", handler)

    fixed = fixer_node(_fix_state(graph_env, {0: _fix_entry(0)}))["fixed"]["vals"][0]

    assert fixed["html"] == FIXED_STRIPPED
    assert fixed["talk_track"] == second
    assert fixed["speaker_notes"] is None


def test_land_original_writes_original_talk_track(graph_env, writes):
    # Sabotage: _land_original never passes entry["original_talk_track"].
    def boom(payload):
        raise RuntimeError("fixer exploded")

    graph_env.skills.set("fixer", boom)

    fixer_node(
        _fix_state(
            graph_env,
            {
                0: _fix_entry(
                    0,
                    original_speaker_notes=ORIG_NOTES,
                    original_talk_track=ORIG_TALK,
                )
            },
        )
    )

    (call,) = _writes_at(writes)
    assert call["html"] == "<p>original</p>"
    assert call["talk_track"] == ORIG_TALK
    assert call["speaker_notes"] == ORIG_NOTES
    assert _pair(_row(graph_env)) == {
        "talk_track": ORIG_TALK,
        "talk_track_source": "model",
        "speaker_notes": ORIG_NOTES,
        "speaker_notes_source": "model",
    }


# ===========================================================================
# The fix reviewer (I-B: start from the original pair)
# ===========================================================================


def _fix_reviewer_state(env_, *, fixed_talk, fixed_notes):
    """The slide-local state the fix reviewer receives; the fixer always records
    both keys (``None`` when its answer had no aside)."""
    entry = _fix_entry(
        0,
        html="<p>original</p>",
        original_speaker_notes=ORIG_NOTES,
        original_talk_track=ORIG_TALK,
    )
    entry["in_flight"] = True
    fixed = {
        "html": "<p>fixed</p>",
        "scripts": "",
        "changed": True,
        "speaker_notes": fixed_notes,
        "talk_track": fixed_talk,
    }
    return env_.state(
        turn_id=TURN,
        fix_target=0,
        fix_map=scoped(TURN, {0: entry}),
        fixed=scoped(TURN, {0: fixed}),
    )


def _fix_wins(env_):
    env_.skills.set("fix_reviewer", lambda payload: review_out(0))


def _fix_loses(env_):
    env_.skills.set(
        "fix_reviewer", lambda payload: review_out(0, [finding("overflow", slide_index=0)])
    )


def test_fix_reviewer_winning_fix_stores_talk_track(graph_env, writes):
    # Sabotage: fix_reviewer_node never reads fixed["talk_track"] (always ships the original).
    _fix_wins(graph_env)

    fix_reviewer_node(_fix_reviewer_state(graph_env, fixed_talk=FIX_TALK, fixed_notes=FIX_NOTES))

    (call,) = _writes_at(writes)
    assert call["html"] == "<p>fixed</p>"
    assert call["talk_track"] == FIX_TALK
    assert call["speaker_notes"] == FIX_NOTES
    row = _row(graph_env)
    assert (row.talk_track, row.talk_track_source) == (FIX_TALK, "model")
    assert (row.speaker_notes, row.speaker_notes_source) == (FIX_NOTES, "model")


def test_fix_reviewer_losing_fix_keeps_the_original_talk_track(graph_env, writes):
    # Sabotage: take fixed["talk_track"] regardless of the verdict.
    _fix_loses(graph_env)

    fix_reviewer_node(_fix_reviewer_state(graph_env, fixed_talk=FIX_TALK, fixed_notes=FIX_NOTES))

    (call,) = _writes_at(writes)
    assert call["html"] == "<p>original</p>"  # the candidate lost
    assert call["talk_track"] == ORIG_TALK
    assert call["speaker_notes"] == ORIG_NOTES
    assert _pair(_row(graph_env)) == {
        "talk_track": ORIG_TALK,
        "talk_track_source": "model",
        "speaker_notes": ORIG_NOTES,
        "speaker_notes_source": "model",
    }


def test_fix_reviewer_winning_fix_without_a_talk_track_keeps_the_original(graph_env, writes):
    # Sabotage: a winning fix passes its None talk track (no original fallback),
    # which would also pass a None that preserves whatever the row held.
    _fix_wins(graph_env)

    fix_reviewer_node(_fix_reviewer_state(graph_env, fixed_talk=None, fixed_notes=FIX_NOTES))

    (call,) = _writes_at(writes)
    assert call["html"] == "<p>fixed</p>"
    assert call["talk_track"] == ORIG_TALK
    assert call["speaker_notes"] == FIX_NOTES  # per field: the notes did arrive
    row = _row(graph_env)
    assert (row.talk_track, row.talk_track_source) == (ORIG_TALK, "model")
    assert (row.speaker_notes, row.speaker_notes_source) == (FIX_NOTES, "model")


def test_fix_reviewer_winning_fix_with_only_a_talk_track_keeps_the_original_notes(
    graph_env, writes
):
    # Sabotage: couple the fields (take both of the fixer's values, or neither).
    _fix_wins(graph_env)

    fix_reviewer_node(_fix_reviewer_state(graph_env, fixed_talk=FIX_TALK, fixed_notes=None))

    (call,) = _writes_at(writes)
    assert call["talk_track"] == FIX_TALK
    assert call["speaker_notes"] == ORIG_NOTES


def test_fix_reviewer_failure_keeps_the_original_talk_track(graph_env, writes):
    # Sabotage: start winner_talk from fixed["talk_track"] instead of original_talk_track.
    def boom(payload):
        raise RuntimeError("fix reviewer exploded")

    graph_env.skills.set("fix_reviewer", boom)

    fix_reviewer_node(_fix_reviewer_state(graph_env, fixed_talk=FIX_TALK, fixed_notes=FIX_NOTES))

    (call,) = _writes_at(writes)
    assert call["html"] == "<p>original</p>"
    assert call["talk_track"] == ORIG_TALK
    assert call["speaker_notes"] == ORIG_NOTES


# ===========================================================================
# Never a model input
# ===========================================================================


def test_talk_track_never_reaches_a_model_payload(graph_env):
    # Sabotage: spread the builder record (or the fixed entry) into a reviewer payload.
    graph_env.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    graph_env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"], [finding("overflow", slide_index=payload["position"])]
        ),
    )
    graph_env.skills.set("fixer", lambda payload: fixer_out(payload, html=FIXED))
    graph_env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    roles = {call["name"] for call in graph_env.skills.calls}
    assert roles == {"builder", "build_reviewer", "fixer", "fix_reviewer"}
    for call in graph_env.skills.calls:
        payload = call["payload"]
        assert [k for k in payload if "notes" in k or "talk" in k] == [], call["name"]
        dumped = json.dumps(payload, default=str)
        for text in (TALK, NOTES, FIX_TALK, FIX_NOTES):
            assert text not in dumped, (call["name"], text)
        for marker in ASIDE_MARKERS[1:]:
            assert marker not in dumped, (call["name"], marker)
    # And the fix shipped both fields, so the payloads were clean for a reason.
    assert _pair(_row(graph_env)) == {
        "talk_track": FIX_TALK,
        "talk_track_source": "model",
        "speaker_notes": FIX_NOTES,
        "speaker_notes_source": "model",
    }


# ===========================================================================
# Per-field ownership through the graph (Review Focus 1, Agent mode)
# ===========================================================================


def _pipeline_clean(env_, **extra):
    env_.skills.set("builder", lambda payload: builder_out(payload, html=BUILT))
    env_.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    slide_pipeline_node(_branch_payload(env_, 0, **extra))


def test_a_graph_rebuild_keeps_a_typed_talk_track_and_refreshes_model_notes(graph_env):
    # Sabotage: the user guard in _upsert_slide_row checks speaker_notes_source for both fields.
    _seed(graph_env, talk=TYPED_TALK, talk_source="user", notes="Old model notes.")

    _pipeline_clean(graph_env)

    row = _row(graph_env)
    assert row.html == BUILT_STRIPPED
    assert _pair(row) == {
        "talk_track": TYPED_TALK,
        "talk_track_source": "user",
        "speaker_notes": NOTES,
        "speaker_notes_source": "model",
    }


def test_user_notes_do_not_freeze_a_model_talk_track_on_rebuild(graph_env):
    # Sabotage: treat a row with ANY user field as fully user-owned.
    _seed(graph_env, talk="Old model talk.", notes=TYPED_NOTES, notes_source="user")

    _pipeline_clean(graph_env)

    assert _pair(_row(graph_env)) == {
        "talk_track": TALK,
        "talk_track_source": "model",
        "speaker_notes": TYPED_NOTES,
        "speaker_notes_source": "user",
    }


def test_a_build_turn_resets_a_model_talk_track(graph_env):
    # Sabotage: builder_node does not reset talk_track under notes_reset (old model text survives).
    _seed(graph_env, talk="Old model talk.", notes="Old model notes.")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"
    assert (row.talk_track, row.talk_track_source) == (None, None)
    slide = SlideWriter().get_slide(graph_env.session_id, 0)
    assert (slide["talk_track"], slide["talk_track_source"]) == ("", None)


def test_a_build_turn_keeps_a_typed_talk_track(graph_env):
    # Sabotage: the per-field user guard (a build-turn reset "" would wipe the typed talk track).
    _seed(graph_env, talk=TYPED_TALK, talk_source="user")
    graph_env.skills.set("builder", builder_out)
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    slide_pipeline_node(_branch_payload(graph_env, 0, notes_reset=True))

    row = _row(graph_env)
    assert row.html == "<div class='slide'>slide 0</div>"
    assert (row.talk_track, row.talk_track_source) == (TYPED_TALK, "user")


# ===========================================================================
# Legacy parse (SlideGeneratorAgent)
# ===========================================================================


def test_legacy_parse_reads_talk_track(agent_stub):
    # Sabotage: _parse_slide_replacements keeps pop_speaker_notes (talk track dropped)
    # or never sets talk_track_source.
    response = (
        f'<div class="slide"><h1>R0</h1>{TALK_ASIDE}{NOTES_ASIDE}</div>'
        '<div class="slide"><h1>R1</h1></div>'
    )

    slides = agent_stub._parse_slide_replacements(response, [1])["replacement_slides"]

    assert len(slides) == 2
    _no_aside(slides[0].html)
    assert (slides[0].talk_track, slides[0].talk_track_source) == (TALK, "model")
    assert (slides[0].speaker_notes, slides[0].speaker_notes_source) == (NOTES, "model")
    assert (slides[1].talk_track, slides[1].talk_track_source) == (None, None)
    assert (slides[1].speaker_notes, slides[1].speaker_notes_source) == (None, None)


def test_legacy_parse_keeps_the_section_root_with_both_asides_as_siblings(agent_stub):
    # Sabotage: pop the asides after find_slide_roots in _parse_slide_replacements.
    response = (
        '<section class="ground"><div class="slide"><h1>R0</h1></div>'
        f'{TALK_ASIDE}<aside class="speaker-notes"><p>{NOTES}</p></aside></section>'
    )

    slides = agent_stub._parse_slide_replacements(response, [0])["replacement_slides"]

    assert len(slides) == 1
    assert slides[0].html.startswith("<section")
    _no_aside(slides[0].html)
    assert slides[0].talk_track == TALK
    assert slides[0].speaker_notes == NOTES


# ===========================================================================
# Legacy replacement carry (Review Focus 1)
# ===========================================================================


def _slide(i, *, notes, nsrc, talk, tsrc, marker=None) -> Slide:
    return Slide(
        html=f'<div class="slide"><h1>{marker or f"MK-{i}"}</h1></div>',
        slide_id=f"sid-{i}",
        speaker_notes=notes,
        speaker_notes_source=nsrc,
        talk_track=talk,
        talk_track_source=tsrc,
    )


def _deck(middle: Dict[str, Any]) -> SlideDeck:
    """Three slides; the middle one carries *middle*'s presenter fields."""
    return SlideDeck(
        title="Talk deck",
        slides=[
            _slide(0, notes="A", nsrc="model", talk="TA", tsrc="model"),
            _slide(1, **middle),
            _slide(2, notes="C", nsrc="model", talk="TC", tsrc="model"),
        ],
    )


def _new(*, notes, talk) -> Slide:
    """A parsed replacement: None = no aside, "" = empty aside, else model text."""
    return Slide(
        html='<div class="slide"><h1>MK-NEW</h1></div>',
        speaker_notes=notes,
        speaker_notes_source="model" if notes else None,
        talk_track=talk,
        talk_track_source="model" if talk else None,
    )


def _field(deck_dict, field) -> List[Any]:
    return [(s[field], s[f"{field}_source"]) for s in deck_dict["slides"]]


def test_rebuild_refreshes_model_field_only():
    # Sabotage: _carry_presenter_text checks one source for both fields, or the
    # replace path still calls the notes-only _carry_speaker_notes.
    deck = _deck({"notes": "B", "nsrc": "model", "talk": TYPED_TALK, "tsrc": "user"})

    result = _replace(deck, [_new(notes="B2", talk="Model talk.")])

    assert "MK-NEW" in result["slides"][1]["html"]
    assert _field(result, "talk_track") == [
        ("TA", "model"), (TYPED_TALK, "user"), ("TC", "model"),
    ]
    assert _field(result, "speaker_notes") == [
        ("A", "model"), ("B2", "model"), ("C", "model"),
    ]


def test_rebuild_with_user_notes_refreshes_a_model_talk_track():
    # Sabotage: treat a slide with user notes as fully user-owned (talk track frozen).
    deck = _deck({"notes": TYPED_NOTES, "nsrc": "user", "talk": "TB", "tsrc": "model"})

    result = _replace(deck, [_new(notes="B2", talk="Model talk.")])

    assert _field(result, "talk_track")[1] == ("Model talk.", "model")
    assert _field(result, "speaker_notes")[1] == (TYPED_NOTES, "user")


def test_a_replacement_without_a_talk_track_keeps_the_replaced_one():
    # Sabotage: no "is None" carry for talk_track (the replacement's None wipes it).
    deck = _deck({"notes": "B", "nsrc": "model", "talk": "TB", "tsrc": "model"})

    result = _replace(deck, [_new(notes="B2", talk=None)])

    assert _field(result, "talk_track")[1] == ("TB", "model")
    assert _field(result, "speaker_notes")[1] == ("B2", "model")


def test_an_empty_talk_track_aside_clears_a_model_talk_track():
    # Sabotage: treat "" like None (carry) for the talk track.
    deck = _deck({"notes": "B", "nsrc": "model", "talk": "TB", "tsrc": "model"})

    result = _replace(deck, [_new(notes=None, talk="")])

    assert _field(result, "talk_track")[1] == ("", None)
    assert _field(result, "speaker_notes")[1] == ("B", "model")


def test_an_empty_talk_track_aside_never_clears_a_typed_one():
    # Sabotage: let an empty model aside through the talk-track user guard.
    deck = _deck({"notes": "B", "nsrc": "model", "talk": TYPED_TALK, "tsrc": "user"})

    result = _replace(deck, [_new(notes=None, talk="")])

    assert _field(result, "talk_track")[1] == (TYPED_TALK, "user")


def _rc8_deck(middle: Dict[str, Any]) -> SlideDeck:
    """``_drive_rc8``'s deck shape (markers MK-A..C), with presenter fields on slide 1."""
    return SlideDeck(
        title="Talk deck",
        slides=[
            _slide(0, notes="A", nsrc="model", talk="TA", tsrc="model", marker="MK-A"),
            _slide(1, marker="MK-B", **middle),
            _slide(2, notes="C", nsrc="model", talk="TC", tsrc="model", marker="MK-C"),
        ],
    )


RC8_BOTH = (
    '<div class="slide"><h1>MK-REWRITE</h1>'
    '<aside data-presenter="talk-track" hidden><p>New talk.</p></aside>'
    '<aside data-presenter="speaker-notes" hidden><p>B2</p></aside></div>'
)


def test_an_rc8_edit_refreshes_model_field_only():
    # Sabotage: the RC8 carry (near valid_refs) still calls the notes-only carry.
    saved = _drive_rc8(
        _rc8_deck({"notes": "B", "nsrc": "model", "talk": TYPED_TALK, "tsrc": "user"}),
        RC8_BOTH,
    )

    assert _field(saved, "talk_track")[1] == (TYPED_TALK, "user")
    assert _field(saved, "speaker_notes")[1] == ("B2", "model")
    _no_aside(saved["slides"][1]["html"])


def test_an_rc8_edit_refreshes_a_model_talk_track():
    # Sabotage: carry the existing talk track in RC8 even when the new slide brought one.
    saved = _drive_rc8(
        _rc8_deck({"notes": TYPED_NOTES, "nsrc": "user", "talk": "TB", "tsrc": "model"}),
        RC8_BOTH,
    )

    assert _field(saved, "talk_track")[1] == ("New talk.", "model")
    assert _field(saved, "speaker_notes")[1] == (TYPED_NOTES, "user")


# ===========================================================================
# User HTML save (update_slide)
# ===========================================================================


def _update(deck: SlideDeck, index: int, html: str) -> Dict[str, Any]:
    from tests.unit.test_speaker_notes_legacy import EDITOR, SID

    svc = _service()
    svc._deck_cache[SID] = deck
    sm = _session_manager()
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=sm
    ), patch("src.api.services.chat_service.get_current_username", return_value=EDITOR):
        svc.update_slide(SID, index, html)
    return _saved_deck_dict(sm)


def test_user_html_save_moves_talk_track_aside():
    # Sabotage: update_slide keeps extract_speaker_notes (talk track dropped), or tags it "model".
    deck = _deck({"notes": "B", "nsrc": "model", "talk": "TB", "tsrc": "model"})

    saved = _update(deck, 1, f'<div class="slide"><p>x</p>{TALK_ASIDE}</div>')

    assert saved["slides"][1]["html"] == '<div class="slide"><p>x</p></div>'
    assert _field(saved, "talk_track") == [("TA", "model"), (TALK, "user"), ("TC", "model")]
    # No notes aside: the notes pair is kept as it was.
    assert _field(saved, "speaker_notes")[1] == ("B", "model")


def test_user_html_save_without_an_aside_keeps_the_old_pair():
    # Sabotage: build new_slide without carrying original_slide.talk_track / its source.
    deck = _deck({"notes": TYPED_NOTES, "nsrc": "user", "talk": TYPED_TALK, "tsrc": "user"})

    saved = _update(deck, 1, '<div class="slide"><p>x</p></div>')

    assert _field(saved, "talk_track")[1] == (TYPED_TALK, "user")
    assert _field(saved, "speaker_notes")[1] == (TYPED_NOTES, "user")


def test_user_html_save_keeps_a_model_talk_track_beside_a_notes_aside():
    # Sabotage: couple the fields (a notes aside resets the talk track too).
    deck = _deck({"notes": "B", "nsrc": "model", "talk": "TB", "tsrc": "model"})

    saved = _update(deck, 1, f'<div class="slide"><p>x</p>{NOTES_ASIDE}</div>')

    assert _field(saved, "talk_track")[1] == ("TB", "model")
    assert _field(saved, "speaker_notes")[1] == (NOTES, "user")


def test_user_html_save_with_an_empty_talk_track_aside_clears_it():
    # Sabotage: treat an empty talk-track aside like no aside in update_slide.
    deck = _deck({"notes": "B", "nsrc": "model", "talk": TYPED_TALK, "tsrc": "user"})

    saved = _update(
        deck,
        1,
        '<div class="slide"><p>x</p><aside data-presenter="talk-track" hidden></aside></div>',
    )

    assert _field(saved, "talk_track")[1] == ("", None)
    assert _field(saved, "speaker_notes")[1] == ("B", "model")


# ===========================================================================
# Insert (ChatService.insert_slide)
# ===========================================================================


def _insert_and_spy(service_, html):
    real_insert = SessionManager.insert_slide
    seen: List[Dict[str, Any]] = []

    def _spy(self, *args, **kwargs):
        seen.append(kwargs["slide"])
        return real_insert(self, *args, **kwargs)

    with patch.object(SessionManager, "insert_slide", _spy):
        service_.insert_slide(OWNER_SID, 1, html=html)
    assert len(seen) == 1
    return seen[0]


def test_insert_with_talk_track_aside(factory, service, seeded):
    # Sabotage: insert_slide keeps extract_speaker_notes, or never tags the talk track "user".
    slide = _insert_and_spy(
        service, f'<div class="slide"><h2>MK-NOTED</h2>{TALK_ASIDE}{NOTES_ASIDE}</div>'
    )

    assert slide["html"] == '<div class="slide"><h2>MK-NOTED</h2></div>'
    assert (slide["talk_track"], slide["talk_track_source"]) == (TALK, "user")
    assert (slide["speaker_notes"], slide["speaker_notes_source"]) == (NOTES, "user")
    row = _rows(factory, seeded["owner_pk"])[1]
    assert row["html"] == '<div class="slide"><h2>MK-NOTED</h2></div>'
    assert (row["talk_track"], row["talk_track_source"]) == (TALK, "user")
    assert (row["speaker_notes"], row["speaker_notes_source"]) == (NOTES, "user")


def test_insert_with_only_a_talk_track_aside_has_no_notes(factory, service, seeded):
    # Sabotage: copy the talk track into the notes (or tag empty notes "user").
    slide = _insert_and_spy(service, f'<div class="slide"><h2>MK-NOTED</h2>{TALK_ASIDE}</div>')

    assert (slide["talk_track"], slide["talk_track_source"]) == (TALK, "user")
    assert (slide["speaker_notes"], slide["speaker_notes_source"]) == ("", None)


# ===========================================================================
# The notes-only save (ChatService.update_slide_notes), Review Focus 5
# ===========================================================================


def _presenter_row(env_, pos: int) -> Dict[str, Any]:
    db = env_.fixture._factory()
    try:
        owner_id = (
            db.query(UserSession).filter(UserSession.session_id == env_.sid).one().id
        )
        r = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_id, SessionSlide.position == pos)
            .one()
        )
        return {
            "html": r.html,
            "talk_track": r.talk_track,
            "talk_track_source": r.talk_track_source,
            "speaker_notes": r.speaker_notes,
            "speaker_notes_source": r.speaker_notes_source,
        }
    finally:
        db.close()


def _seed_model_fields(env_, pos=1, *, notes=None, talk=None):
    """Model-written presenter fields on row *pos*, HTML unchanged, before any load."""
    html = _presenter_row(env_, pos)["html"]
    SlideWriter(env_.sm).write_slide(
        env_.sid, pos, html, speaker_notes=notes, talk_track=talk
    )
    row = _presenter_row(env_, pos)
    assert row["speaker_notes"] == notes and row["talk_track"] == talk, "seed did not land"


def test_notes_save_with_only_talk_track_leaves_notes(env):
    # Sabotage: update_slide_notes writes speaker_notes unconditionally (a None
    # becomes "" and clears them, or the source is re-stamped "user").
    _seed_model_fields(env, notes="Model notes.")
    before_rows = [_presenter_row(env, p) for p in range(3)]
    before_version = env.fixture.version()
    slide_id = env.fixture.row_snapshot()[1]["slide_id"]

    result = env.service.update_slide_notes(env.sid, 1, talk_track="say this")

    assert result == {
        "index": 1,
        "slide_id": slide_id,
        "speaker_notes": "Model notes.",
        "talk_track": "say this",
        "version": before_version + 1,
    }
    after = _presenter_row(env, 1)
    assert after == {
        **before_rows[1],
        "talk_track": "say this",
        "talk_track_source": "user",
    }
    for pos in (0, 2):
        assert _presenter_row(env, pos) == before_rows[pos], pos
    read = env.fixture.get_slide_deck()["slides"][1]
    assert (read["speaker_notes"], read["speaker_notes_source"]) == ("Model notes.", "model")
    assert (read["talk_track"], read["talk_track_source"]) == ("say this", "user")


def test_notes_save_with_only_notes_leaves_the_talk_track(env):
    # Sabotage: update_slide_notes writes talk_track unconditionally (None clears it).
    _seed_model_fields(env, talk="Model talk.")

    result = env.service.update_slide_notes(env.sid, 1, "Pause here.")

    row = _presenter_row(env, 1)
    assert (row["talk_track"], row["talk_track_source"]) == ("Model talk.", "model")
    assert (row["speaker_notes"], row["speaker_notes_source"]) == ("Pause here.", "user")
    assert result["talk_track"] == "Model talk."
    assert result["speaker_notes"] == "Pause here."


def test_notes_save_of_both_fields_tags_both_user(env):
    # Sabotage: save only the first field given.
    env.service.update_slide_notes(env.sid, 1, "N.", talk_track="T.")

    row = _presenter_row(env, 1)
    assert (row["speaker_notes"], row["speaker_notes_source"]) == ("N.", "user")
    assert (row["talk_track"], row["talk_track_source"]) == ("T.", "user")


def test_notes_save_empty_talk_track_clears_it_and_source(env):
    # Sabotage: store whitespace as is, or keep source "user" on an empty talk-track save.
    _seed_model_fields(env, notes="Model notes.")
    env.service.update_slide_notes(env.sid, 1, talk_track="say this")
    assert _presenter_row(env, 1)["talk_track_source"] == "user"

    result = env.service.update_slide_notes(env.sid, 1, talk_track="   \n ")

    row = _presenter_row(env, 1)
    assert (row["talk_track"], row["talk_track_source"]) == (None, None)
    assert (row["speaker_notes"], row["speaker_notes_source"]) == ("Model notes.", "model")
    assert result["talk_track"] == ""
    read = env.fixture.get_slide_deck()["slides"][1]
    assert (read["talk_track"], read["talk_track_source"]) == ("", None)


def test_a_stale_talk_track_save_restores_both_pairs(env):
    # Sabotage: the except-restore puts back only the notes pair on the cached slide.
    first = env.service.update_slide_notes(env.sid, 1, "Old notes.", talk_track="Old talk.")
    stale = first["version"] - 1

    with pytest.raises(VersionConflictError):
        env.service.update_slide_notes(
            env.sid, 1, "Rejected notes.", talk_track="Rejected talk.", expected_version=stale
        )

    cached = env.service._get_or_load_deck(env.sid).slides[1]
    assert (cached.talk_track, cached.talk_track_source) == ("Old talk.", "user")
    assert (cached.speaker_notes, cached.speaker_notes_source) == ("Old notes.", "user")
    # A later legitimate save rewrites every row from that cache: nothing rejected rides along.
    env.service.update_slide_notes(env.sid, 0, "Slide one notes.")
    row = _presenter_row(env, 1)
    assert (row["talk_track"], row["talk_track_source"]) == ("Old talk.", "user")
    assert (row["speaker_notes"], row["speaker_notes_source"]) == ("Old notes.", "user")


def test_a_typed_talk_track_survives_a_later_model_write(env):
    # Sabotage: tag the talk-track save "model" (or None), so the per-field user guard lets "M" in.
    env.service.update_slide_notes(env.sid, 1, talk_track="say this")

    SlideWriter(env.sm).write_slide(
        env.sid, 1, "<div class='slide'><h1>Rebuilt</h1></div>", talk_track="M"
    )

    row = _presenter_row(env, 1)
    assert "Rebuilt" in row["html"], "the model write must land"
    assert (row["talk_track"], row["talk_track_source"]) == ("say this", "user")


# ===========================================================================
# The route (PATCH /api/slides/{index}/notes)
# ===========================================================================


def _patch_body(route_, body, index=1):
    return route_.client.patch(f"/api/slides/{index}/notes", json=body)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="neither_key"),
        pytest.param({"speaker_notes": None, "talk_track": None}, id="both_null"),
    ],
)
def test_notes_route_requires_a_field(route, body):
    # Sabotage: drop the model_validator on UpdateSlideNotesRequest.
    resp = _patch_body(route, {"session_id": ROUTE_SID, **body})

    assert resp.status_code == 422, resp.text
    assert route.service.calls == []
    assert route.locks.acquired == []


def test_notes_route_old_client_body_still_works(route):
    # Sabotage: make talk_track required, or pass a default "" (it would clear the talk track).
    resp = _patch_body(route, {"session_id": ROUTE_SID, "speaker_notes": "Pause here."})

    assert resp.status_code == 200, resp.text
    assert route.service.calls == [
        {
            "session_id": ROUTE_SID,
            "index": 1,
            "speaker_notes": "Pause here.",
            "talk_track": None,
            "slide_id": None,
            "expected_version": None,
        }
    ]


def test_notes_route_passes_a_talk_track_alone(route):
    # Sabotage: never pass request.talk_track to the service, or default speaker_notes to "".
    resp = _patch_body(
        route,
        {
            "session_id": ROUTE_SID,
            "talk_track": "Say this.",
            "slide_id": "sid-b",
            "expected_version": 7,
        },
    )

    assert resp.status_code == 200, resp.text
    assert route.service.calls == [
        {
            "session_id": ROUTE_SID,
            "index": 1,
            "speaker_notes": None,
            "talk_track": "Say this.",
            "slide_id": "sid-b",
            "expected_version": 7,
        }
    ]
    assert route.marks == [], "a talk-track save scheduled a spec review"


def test_notes_route_accepts_an_empty_talk_track(route):
    # Sabotage: the validator treats "" as missing (a clear could then never be sent).
    resp = _patch_body(route, {"session_id": ROUTE_SID, "talk_track": ""})

    assert resp.status_code == 200, resp.text
    assert route.service.calls[0]["talk_track"] == ""
    assert route.service.calls[0]["speaker_notes"] is None


def test_notes_route_rejects_an_over_long_talk_track(route):
    # Sabotage: drop Field(max_length=20000) on talk_track.
    resp = _patch_body(route, {"session_id": ROUTE_SID, "talk_track": "x" * 20001})
    assert resp.status_code == 422, resp.text
    assert route.service.calls == []

    resp = _patch_body(route, {"session_id": ROUTE_SID, "talk_track": "x" * 20000})
    assert resp.status_code == 200, resp.text
    assert len(route.service.calls) == 1


def test_a_talk_track_save_on_a_slide_without_notes_returns_empty_notes(env):
    # Reviewer addition. Sabotage: return slide.speaker_notes without the `or ""`
    # twin of talk_track, so a talk-track-only save answers speaker_notes=null
    # where the client expects a string.
    cached = env.service._get_or_load_deck(env.sid).slides[1]
    cached.speaker_notes, cached.speaker_notes_source = None, None

    result = env.service.update_slide_notes(env.sid, 1, talk_track="say this")

    assert result["speaker_notes"] == ""
    assert result["talk_track"] == "say this"
