"""The tour's staged demo: each stage persists one beat of a graph turn."""
from __future__ import annotations

import contextlib
import copy
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.routes.tour import STAGES, StageOrderError, _phase1_create_session, _run_stage
from src.api.services.deck_level_writer import read_deck_spec
from src.api.services.session_manager import get_session_manager
from src.api.routes.tour import FIXTURE_PATH, _load_fixture
from src.database.models.profile_contributor import PermissionLevel
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_USER = "tour-taker@example.com"
_PATCHES = (
    "src.api.services.session_manager.get_db_session",
    "src.api.services.deck_level_writer.get_db_session",
)


@contextlib.contextmanager
def _patched(factory):
    fake = _make_fake_db(factory)
    with contextlib.ExitStack() as stack:
        for target in _PATCHES:
            stack.enter_context(patch(target, fake))
        # get_slide_deck resolves display names via SCIM; keep the read hermetic.
        stack.enter_context(
            patch(
                "src.services.identity_provider.resolve_display_names",
                lambda emails: {},
            )
        )
        yield


@pytest.fixture
def db():
    engine = _make_in_memory_engine()
    try:
        factory = _make_factory(engine)
        from src.services.graph_configuration import bootstrap_graph_configuration
        bootstrap_graph_configuration(factory)
        with _patched(factory):
            yield factory
    finally:
        engine.dispose()


def _start() -> str:
    return _phase1_create_session(_USER)["session_id"]


def _run_through(sid: str, last: str) -> None:
    for stage in STAGES[1 : STAGES.index(last) + 1]:
        _run_stage(sid, stage, _USER)


def _chat(sid):
    return [(m["role"], m["content"]) for m in get_session_manager().get_messages(sid)]


def _on_disk_fixture() -> dict:
    """The fixture as shipped, bypassing the module cache."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_stage_order_is_the_documented_one():
    assert STAGES == ("prompt", "plan", "build", "review", "edit")


def test_full_run_leaves_the_chat_a_real_graph_turn_would_show(db):
    fx = _load_fixture()["stages"]
    sid = _start()
    _run_through(sid, "edit")
    assert _chat(sid) == [
        ("user", _load_fixture()["chat_prompt"]),
        ("assistant", fx["plan"]["architect_reply"]),
        ("assistant", fx["build"]["foreman_line"]),
        *[("assistant", line) for line in fx["build"]["review_lines"]],
        ("assistant", fx["review"]["advisory"]),
        ("user", fx["edit"]["user_prompt"]),
        ("assistant", fx["edit"]["architect_reply"]),
        ("assistant", fx["edit"]["review_line"]),
    ]


def test_message_types_and_nodes_mirror_the_graph(db):
    sid = _start()
    _run_through(sid, "edit")
    rows = get_session_manager().get_messages(sid)
    by_node = {}
    for m in rows:
        if m["role"] == "assistant":
            by_node.setdefault(m["metadata"]["node"], set()).add(m["message_type"])
    assert by_node == {
        "architect": {"llm_response"},
        "foreman": {"info"},
        "build_reviewer": {"info"},
        "deck_reviewer": {"info"},
    }
    assert {m["message_type"] for m in rows if m["role"] == "user"} == {"chat"}


def test_every_row_is_tagged_with_the_stage_that_wrote_it(db):
    # The idempotency gate reads these tags; an untagged or mis-tagged row
    # would let a re-entered step write its lines a second time.
    n_review_lines = len(_load_fixture()["stages"]["build"]["review_lines"])
    sid = _start()
    _run_through(sid, "edit")
    rows = get_session_manager().get_messages(sid)
    assert [m["metadata"]["tour_stage"] for m in rows] == [
        "prompt",
        "plan",
        "build",
        *["build"] * n_review_lines,
        "review",
        "edit",
        "edit",
        "edit",
    ]
    assert [m["metadata"]["node"] for m in rows if m["role"] == "assistant"] == [
        "architect",
        "foreman",
        *["build_reviewer"] * n_review_lines,
        "deck_reviewer",
        "architect",
        "build_reviewer",
    ]


def test_phase1_tags_the_prompt_row(db):
    sid = _start()
    (row,) = get_session_manager().get_messages(sid)
    assert row["role"] == "user"
    assert row["message_type"] == "chat"
    assert row["metadata"]["tour_stage"] == "prompt"


def test_run_stage_reports_what_it_did(db):
    sid = _start()
    _run_stage(sid, "plan", _USER)
    assert _run_stage(sid, "build", _USER) == {
        "session_id": sid,
        "stage": "build",
        "applied": True,
        "slide_count": 3,
    }


def test_no_slides_before_build_and_three_after(db):
    sid = _start()
    _run_through(sid, "plan")
    assert not (get_session_manager().get_slide_deck(sid) or {}).get("slides")
    _run_stage(sid, "build", _USER)
    assert len(get_session_manager().get_slide_deck(sid)["slides"]) == 3


def test_build_persists_the_spec(db):
    sid = _start()
    _run_through(sid, "build")
    assert read_deck_spec(sid)["narrative_arc"] == _load_fixture()["deck_spec"]["narrative_arc"]
    assert read_deck_spec(sid) == _on_disk_fixture()["deck_spec"]


@pytest.mark.parametrize("last", ["build", "review", "edit"])
def test_every_slide_is_verified_after_every_stage(db, last):
    # useAutoVerification fires an LLM judge on any slide whose verification is
    # falsy; the demo must never cost a model call.
    sid = _start()
    _run_through(sid, last)
    deck = get_session_manager().get_slide_deck(sid)
    for slide in deck["slides"]:
        assert slide.get("verification"), slide["index"]
        assert slide["verification"]["rating"] == _load_fixture()["stages"]["build"]["verification"]["rating"]


@pytest.mark.parametrize("last", ["build", "review", "edit"])
def test_verification_slot_carries_judge_and_review_payloads(db, last):
    judge = _load_fixture()["stages"]["build"]["verification"]
    sid = _start()
    _run_through(sid, last)
    slides = get_session_manager().get_slide_deck(sid)["slides"]
    for slide in slides:
        v = slide["verification"]
        assert v["score"] == judge["score"]
        assert v["rating"] == judge["rating"]
        assert v["explanation"] == judge["explanation"]
        assert v["issues"] == []
        assert v["duration_ms"] == 0
        assert v["error"] is False
    assert [s["verification"]["tellr_review"]["verdict"] for s in slides] == [
        "clean",
        "clean",
        "surfaced",
    ]


def test_the_surfaced_finding_reaches_the_flat_findings_list(db):
    sid = _start()
    _run_through(sid, "build")
    findings = get_session_manager().get_slide_deck(sid)["findings"]
    assert [(f["slideIndex"], f["criterion"], f["status"]) for f in findings] == [
        (2, "brief_not_delivered", "open")
    ]
    assert findings[0]["id"].startswith("brief_not_delivered:")


def test_the_finding_id_is_minted_from_the_slide_hash(db):
    fx = _load_fixture()
    scripted = fx["stages"]["build"]["findings"]["2"][0]
    sid = _start()
    _run_through(sid, "build")
    (finding,) = get_session_manager().get_slide_deck(sid)["findings"]
    slide_hash = compute_slide_hash(fx["slides"][2]["html"])
    assert finding["id"] == f"brief_not_delivered:{slide_hash}:0"
    assert finding["message"] == scripted["message"]
    assert finding["category"] == scripted["category"]
    assert finding["objective"] is scripted["objective"]


def test_edit_changes_only_the_target_slide_and_its_brief(db):
    fx = _load_fixture()
    sid = _start()
    _run_through(sid, "review")
    before = get_session_manager().get_slide_deck(sid)["slides"]
    _run_stage(sid, "edit", _USER)
    after = get_session_manager().get_slide_deck(sid)["slides"]
    assert after[1]["html"] == fx["stages"]["edit"]["slide"]["html"]
    assert [after[0]["html"], after[2]["html"]] == [before[0]["html"], before[2]["html"]]
    spec = read_deck_spec(sid)
    assert spec["slides"][1]["content_brief"] == fx["stages"]["edit"]["content_brief"]
    assert spec["slides"][0] == fx["deck_spec"]["slides"][0]
    # slide 3's finding survives the edit
    assert [f["slideIndex"] for f in get_session_manager().get_slide_deck(sid)["findings"]] == [2]


def test_edit_spec_differs_from_the_fixture_spec_only_in_that_brief(db):
    shipped = _on_disk_fixture()
    edit = shipped["stages"]["edit"]
    expected = copy.deepcopy(shipped["deck_spec"])
    expected["slides"][edit["position"]]["content_brief"] = edit["content_brief"]
    sid = _start()
    _run_through(sid, "edit")
    assert read_deck_spec(sid) == expected
    after = get_session_manager().get_slide_deck(sid)["slides"]
    assert after[1]["verification"]["tellr_review"]["verdict"] == "clean"


def test_a_full_run_does_not_mutate_the_cached_fixture(db):
    # _load_fixture() is a process-wide cache: an in-place edit of its spec or
    # slides would leak the edited deck into every later tour on the worker.
    _run_through(_start(), "edit")
    shipped = _on_disk_fixture()
    assert _load_fixture()["deck_spec"] == shipped["deck_spec"]
    assert _load_fixture()["slides"] == shipped["slides"]


def test_rerunning_a_stage_is_a_noop(db):
    sid = _start()
    _run_through(sid, "build")
    snapshot = _chat(sid)
    result = _run_stage(sid, "build", _USER)
    assert result["applied"] is False
    assert _chat(sid) == snapshot
    assert _run_stage(sid, "plan", _USER)["applied"] is False  # Back past an earlier stage
    assert _chat(sid) == snapshot


def test_rerunning_a_stage_does_not_rewrite_the_deck(db):
    sid = _start()
    _run_through(sid, "edit")
    version = get_session_manager().get_slide_deck(sid)["version"]
    for stage in ("build", "edit"):
        assert _run_stage(sid, stage, _USER)["applied"] is False
    deck = get_session_manager().get_slide_deck(sid)
    assert deck["version"] == version
    assert deck["slides"][1]["html"] == _load_fixture()["stages"]["edit"]["slide"]["html"]


def test_stage_out_of_order_is_409_and_writes_nothing(db):
    sid = _start()
    snapshot = _chat(sid)
    with pytest.raises(StageOrderError):
        _run_stage(sid, "build", _USER)
    assert _chat(sid) == snapshot
    assert not (get_session_manager().get_slide_deck(sid) or {}).get("slides")


def test_skipping_a_middle_stage_is_rejected_and_writes_nothing(db):
    sid = _start()
    _run_through(sid, "build")
    snapshot = _chat(sid)
    version = get_session_manager().get_slide_deck(sid)["version"]
    with pytest.raises(StageOrderError):
        _run_stage(sid, "edit", _USER)  # review has not run
    assert _chat(sid) == snapshot
    assert get_session_manager().get_slide_deck(sid)["version"] == version
    assert read_deck_spec(sid) == _on_disk_fixture()["deck_spec"]


def test_unknown_stage_raises_value_error(db):
    with pytest.raises(ValueError):
        _run_stage(_start(), "bogus", _USER)


def test_prompt_is_not_a_runnable_stage(db):
    # phase 1 owns the prompt row; _run_stage must not write it again.
    sid = _start()
    with pytest.raises(ValueError):
        _run_stage(sid, "prompt", _USER)
    assert len(_chat(sid)) == 1


def test_stages_never_mark_the_spec_dirty(db):
    with patch("src.services.spec_sync.mark_dirty") as dirty:
        _run_through(_start(), "edit")
    dirty.assert_not_called()


# ---------------------------------------------------------------------------
# Route contract (permission gating itself lives in test_authz_tour.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def open_client(monkeypatch):
    from src.api.main import app

    monkeypatch.setattr(
        "src.api.routes.tour._check_deck_permission_for_session",
        lambda session_id, min_permission=PermissionLevel.CAN_VIEW: None,
    )
    monkeypatch.setattr("src.api.routes.tour.get_current_user", lambda: _USER)
    return TestClient(app, raise_server_exceptions=False)


def test_route_returns_the_stage_result(open_client, monkeypatch):
    calls = []

    def fake_run(session_id, stage, created_by):
        calls.append((session_id, stage, created_by))
        return {"session_id": session_id, "stage": stage, "applied": True, "slide_count": 3}

    monkeypatch.setattr("src.api.routes.tour._run_stage", fake_run)
    resp = open_client.post("/api/tour/demo-deck/sess-1/stages/build")
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "sess-1", "stage": "build", "applied": True, "slide_count": 3}
    assert calls == [("sess-1", "build", _USER)]


@pytest.mark.parametrize("stage", ["bogus", "prompt"])
def test_route_unknown_stage_is_404(open_client, monkeypatch, stage):
    def fake_run(*args):
        raise AssertionError("_run_stage must not be reached for an unknown stage")

    monkeypatch.setattr("src.api.routes.tour._run_stage", fake_run)
    resp = open_client.post(f"/api/tour/demo-deck/sess-1/stages/{stage}")
    assert resp.status_code == 404


def test_route_maps_stage_order_error_to_409(open_client, monkeypatch):
    def fake_run(*args):
        raise StageOrderError("plan has not run")

    monkeypatch.setattr("src.api.routes.tour._run_stage", fake_run)
    resp = open_client.post("/api/tour/demo-deck/sess-1/stages/build")
    assert resp.status_code == 409


def test_route_maps_other_failures_to_500(open_client, monkeypatch):
    def fake_run(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.api.routes.tour._run_stage", fake_run)
    resp = open_client.post("/api/tour/demo-deck/sess-1/stages/build")
    assert resp.status_code == 500
