"""#271 Task 6: the lifecycle journey attributes a failure to the stage that caused it.

Pure: no database, no HTTP.  These tests pin the attribution contract that
``tests/integration/graph_lifecycle_journey.py`` gives the PostgreSQL journey
(and Tasks 7 and 8, which reuse it):

* an exception inside ``stage(S)`` becomes a ``StageFailure`` labelled with S's
  ticket, code, name and seam;
* ``require(upstream, False, ...)`` is labelled with the UPSTREAM stage, so a
  wrong value is blamed on the stage that produced it, not the one that noticed;
* any read of a code-owned definition source after ``CodeDefaultTripwire.arm``
  is labelled ``[AC1/#271]`` — even when production code swallows the error;
* a ``StageFailure`` passes through a nested ``stage()`` unchanged.
"""

from __future__ import annotations

import sys

import pytest

from tests.integration.graph_lifecycle_journey import (
    STAGES,
    CodeDefaultRead,
    CodeDefaultTripwire,
    LifecycleJourney,
    Stage,
    StageFailure,
    require,
    stage,
)

S09 = STAGES["S09"]
S10 = STAGES["S10"]
S11 = STAGES["S11"]


def test_the_stage_table_names_each_ticket_and_seam() -> None:
    assert S11 == Stage(
        code="S11",
        name="publish",
        ticket="#269",
        seam="POST /api/admin/agent-definitions/releases",
    )
    assert (S09.ticket, S09.name) == ("#268", "readiness")
    assert list(STAGES) == [
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
        "S09",
        "S10",
        "S11",
        "S12",
        "S12b",
        "S14",
        "S15",
        "S16",
        "S18",
    ]
    assert all(code == STAGES[code].code for code in STAGES)


_ADMIN = "/api/admin/agent-definitions"

#: The whole table, as the brief's ticket column names it (fix round 1, I1): a
#: stage relabelled to another ticket would misroute every failure it reports.
EXPECTED_STAGES = [
    ("S01", "bootstrap", "#260", f"GET {_ADMIN}/workbench"),
    ("S02", "old conversation", "#261", "POST /api/sessions"),
    ("S03", "edit prompts and model", "#263", f"PUT {_ADMIN}/draft/{{agent_key}}"),
    ("S04", "overlay", "#264", f"POST {_ADMIN}/draft/{{agent_key}}/schema-contract-upgrade"),
    ("S05", "assembly", "#265", f"POST {_ADMIN}/draft/{{agent_key}}/protected-assembly-upgrade"),
    ("S06", "endpoint", "#266", f"GET {_ADMIN}/model-endpoints"),
    ("S07", "test", "#267", f"POST {_ADMIN}/draft/{{agent_key}}/test-runs"),
    ("S08", "approve", "#268", f"POST {_ADMIN}/test-runs/{{run_id}}/verdict"),
    ("S09", "readiness", "#268", f"GET {_ADMIN}/readiness"),
    ("S10", "preview", "#269", f"GET {_ADMIN}/release-preview"),
    ("S11", "publish", "#269", f"POST {_ADMIN}/releases"),
    ("S12", "pinned conversations", "#262", "POST /api/sessions/{session_id}/contribute"),
    (
        "S12b",
        "collaboration history",
        "#262",
        "GET /api/sessions/{session_id}/collaboration-history",
    ),
    ("S14", "history", "#270", f"GET {_ADMIN}/releases"),
    ("S15", "rollback", "#270", f"POST {_ADMIN}/releases/{{version_number}}/rollback"),
    ("S16", "post-rollback pins", "#270", "POST /api/sessions"),
    ("S18", "closing checks", "#271", "graph_release rows"),
]


def test_the_whole_stage_table_is_pinned() -> None:
    assert [
        (stage_.code, stage_.name, stage_.ticket, stage_.seam) for stage_ in STAGES.values()
    ] == EXPECTED_STAGES


def test_an_exception_inside_a_stage_is_labelled_with_that_stage() -> None:
    with pytest.raises(StageFailure) as caught:
        with stage(S11):
            raise KeyError("version_number")
    message = str(caught.value)
    assert message.startswith("[#269] S11 publish via POST"), message
    assert message == (
        "[#269] S11 publish via POST /api/admin/agent-definitions/releases: "
        "KeyError: 'version_number'"
    )
    assert isinstance(caught.value.__cause__, KeyError)


def test_an_assertion_inside_a_stage_is_labelled_with_that_stage() -> None:
    with pytest.raises(StageFailure) as caught:
        with stage(S10):
            assert 1 == 2, "changed roles differ"
    assert str(caught.value).startswith("[#269] S10 preview via GET "), str(caught.value)
    assert "AssertionError: changed roles differ" in str(caught.value)


def test_require_blames_the_upstream_stage_not_the_one_that_noticed() -> None:
    with pytest.raises(StageFailure) as caught:
        with stage(S10):
            require(S09, False, "builder rerun approval missing")
    message = str(caught.value)
    assert message.startswith("[#268] S09 readiness via GET "), message
    assert message.endswith(": builder rerun approval missing"), message
    assert "S10" not in message


def test_require_is_silent_when_the_upstream_output_is_right() -> None:
    with stage(S10):
        require(S09, True, "unused")


def test_a_stage_failure_passes_through_a_nested_stage_unchanged() -> None:
    inner = STAGES["S03"]
    with pytest.raises(StageFailure) as caught:
        with stage(S11):
            with stage(inner):
                raise ValueError("stale")
    assert str(caught.value) == (
        f"[#263] S03 edit prompts and model via {inner.seam}: ValueError: stale"
    )


def test_a_tripwire_read_inside_a_stage_is_labelled_ac1(monkeypatch) -> None:
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    import src.core.skills

    with pytest.raises(StageFailure) as caught:
        with stage(S11):
            src.core.skills.load_skill("architect")
    message = str(caught.value)
    assert message.startswith("[AC1/#271] S11 publish via POST"), message
    assert "code-owned definition read after Graph Version 1: " in message
    assert tripwire.reads == ["src.core.skills.load_skill"]


def test_a_swallowed_tripwire_read_is_still_labelled_ac1(monkeypatch) -> None:
    """Production code that catches the error cannot hide the read."""
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    import src.core.skills

    with pytest.raises(StageFailure) as caught:
        with stage(S10):
            try:
                src.core.skills._SKILLS["builder"]
            except Exception:
                pass
    assert str(caught.value).startswith("[AC1/#271] S10 preview via GET "), str(caught.value)
    assert tripwire.reads == ["src.core.skills._SKILLS"]


def test_a_tripwire_read_wins_over_the_assertion_it_caused(monkeypatch) -> None:
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    from src.services import graph_definition_manifest

    with pytest.raises(StageFailure) as caught:
        with stage(S10):
            try:
                graph_definition_manifest.load_graph_v1_manifest()
            except CodeDefaultRead:
                pass
            raise AssertionError("a 500 the swallowed read caused")
    assert str(caught.value).startswith("[AC1/#271] S10 "), str(caught.value)


def test_every_code_owned_source_is_trapped(monkeypatch) -> None:
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    import src.core.skills
    import src.services.agent_runtime as agent_runtime
    import src.services.graph_definition_manifest as manifest

    attempts = {
        "src.core.skills.load_skill": lambda: src.core.skills.load_skill("fixer"),
        "src.core.skills._SKILLS": lambda: list(src.core.skills._SKILLS),
        "src.services.graph_definition_manifest.load_graph_v1_manifest": (
            manifest.load_graph_v1_manifest
        ),
        "src.services.agent_definition_manifest_v1": lambda: (
            sys.modules["src.services.agent_definition_manifest_v1"]
        ).GRAPH_VERSION_1_MANIFEST_JSON,
        "CodeOwnedAgentDefinitionSource.resolve": lambda: (
            agent_runtime.CodeOwnedAgentDefinitionSource.resolve(None, "architect")
        ),
        "CompatibilityResolvedDefinitionLoader.resolve": lambda: (
            agent_runtime.CompatibilityResolvedDefinitionLoader.resolve(None, 1, "architect")
        ),
    }
    for name, attempt in attempts.items():
        with pytest.raises(CodeDefaultRead, match=f"read after Graph Version 1: {name}$"):
            attempt()
    assert tripwire.reads == list(attempts)


def test_a_by_name_manifest_binding_is_trapped_through_sys_modules(monkeypatch) -> None:
    """A caller holding its own reference misses the cache and hits the swapped module."""
    from src.services.graph_definition_manifest import load_graph_v1_manifest as bound

    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    with pytest.raises(CodeDefaultRead):
        bound()
    assert tripwire.reads == ["src.services.agent_definition_manifest_v1"]


def test_dunder_probes_of_the_swapped_module_are_not_reads(monkeypatch) -> None:
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    module = sys.modules["src.services.agent_definition_manifest_v1"]
    assert not hasattr(module, "__path__")
    assert not hasattr(module, "__warningregistry__")
    assert tripwire.reads == []


def test_no_read_before_arm_and_a_disarmed_stage_is_silent() -> None:
    tripwire = CodeDefaultTripwire()
    import src.core.skills

    with stage(S11):
        src.core.skills.load_skill("architect")
    assert tripwire.reads == []


class _FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"ok": True}


class _FakeClient:
    def request(self, method, path, json=None):
        return _FakeResponse()


def _bare_journey() -> LifecycleJourney:
    client = _FakeClient()
    return LifecycleJourney(
        factory=None, admin=client, user=client, adapter=None, tripwire=CodeDefaultTripwire()
    )


S13 = Stage("S13", "graph turn", "#262", "POST /api/chat/stream")


def test_in_stage_runs_a_caller_stage_with_recording_and_attribution() -> None:
    journey = _bare_journey()
    with journey.in_stage(S13):
        body = journey.call("turn", "GET", "/x", principal="p@example.com", expect=200)
    assert body == {"ok": True}
    assert [(e.id, e.method, e.path, e.status) for e in journey.exchanges] == [
        ("S13-turn", "GET", "/x", 200)
    ]
    assert journey._current is None
    assert journey.completed == [], "a caller stage is not a journey stage"

    with pytest.raises(StageFailure) as caught:
        with journey.in_stage(S13):
            raise RuntimeError("boom")
    assert (
        str(caught.value) == "[#262] S13 graph turn via POST /api/chat/stream: RuntimeError: boom"
    )
    assert journey._current is None


def test_in_stage_restores_the_enclosing_stage() -> None:
    journey = _bare_journey()
    with journey.in_stage(S11):
        with journey.in_stage(S13):
            assert journey._current is S13
        assert journey._current is S11
    assert journey._current is None


def test_call_outside_any_stage_is_refused() -> None:
    with pytest.raises(AssertionError, match="outside a stage"):
        _bare_journey().call("x", "GET", "/x", principal="p", expect=200)
