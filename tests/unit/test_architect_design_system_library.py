"""ws4d D6c / §M1 — the design-system library reaches the architect's PAYLOAD.

§M1 asks for "the architect's tool manifest" to carry the library.  There is no
manifest: ``TOOL_GRANTS`` is ``[]``, ``bind_tools`` appears nowhere under
``src/``, and ``AgentRuntime`` invokes the architect with structured output and no
tools bound — so a library wired into ``tool_grants`` would be read by nothing.
The operator ratified delivering §M1 through the payload instead, and these
guards are written against the channel the architect actually reads.

Two of the four assertions here exist because of a specific way this could ship
looking correct:

*   **The catalog must be ids and labels, never compiled bytes.**  The seeded
    ``layout_html`` must not appear anywhere in the serialised payload.  Shipping
    the row wholesale would put a snapshot in the prompt that goes stale against
    ``COMPILER_VERSION`` — the exact staleness ``DesignContractRef`` stores ids to
    avoid — and would bill the whole catalog's CSS on every architect call.
*   **The payload must survive ``json.dumps``**, because that is what
    ``AgentRuntime`` does to it. An ORM row or a ``Row`` object in there
    passes every in-Python assertion and then raises at prompt assembly.
"""

from __future__ import annotations

import json

from src.database.models.design_system import DesignSystem, DesignSystemTemplate
from src.domain.skill_io import ArchitectOutput
from src.services.graph.nodes import _design_system_library, architect_node
from tests.unit.conftest_graph import graph_env, make_spec  # noqa: F401

SEEDED_LAYOUT = "<main class='deck'><section class='slide'>SEEDED LAYOUT</section></main>"


def _seed_library(env):
    """Two live systems (one with two templates, one with none) and a dead one."""
    db = env.factory()
    try:
        acme = DesignSystem(name="Acme", description="Acme brand", is_default=True)
        beta = DesignSystem(name="Beta", description="Beta brand")
        gone = DesignSystem(name="Retired", description="soft-deleted", is_active=False)
        db.add_all([acme, beta, gone])
        db.flush()
        db.add_all(
            [
                DesignSystemTemplate(
                    design_system_id=acme.id,
                    name="Title",
                    description="A title slide",
                    entry_path="templates/title/index.html",
                    layout_html=SEEDED_LAYOUT,
                    token_css=":root { --brand: #123456; }",
                ),
                DesignSystemTemplate(
                    design_system_id=acme.id,
                    name="Two column",
                    description="Two columns",
                    entry_path="templates/two-column/index.html",
                    layout_html=SEEDED_LAYOUT,
                ),
                # A template belonging to a soft-deleted system must vanish with it.
                DesignSystemTemplate(
                    design_system_id=gone.id,
                    name="Retired template",
                    description=None,
                    entry_path="templates/retired/index.html",
                    layout_html=SEEDED_LAYOUT,
                ),
            ]
        )
        db.commit()
        return {"acme": acme.id, "beta": beta.id, "gone": gone.id}
    finally:
        db.close()


def test_the_library_lists_live_systems_with_their_templates(graph_env):
    env = graph_env
    ids = _seed_library(env)

    library = _design_system_library()

    by_id = {entry["design_system_id"]: entry for entry in library}
    assert sorted(by_id) == sorted([ids["acme"], ids["beta"]]), library

    acme = by_id[ids["acme"]]
    assert acme["name"] == "Acme"
    assert acme["description"] == "Acme brand"
    assert acme["is_default"] is True
    assert [t["name"] for t in acme["templates"]] == ["Title", "Two column"]
    assert all(isinstance(t["template_id"], int) for t in acme["templates"])

    # A system with no templates carries an empty list, not a missing key: the
    # architect must be able to offer it as an unpinned design system.
    assert by_id[ids["beta"]]["templates"] == []


def test_the_library_is_absent_when_there_are_no_design_systems(graph_env):
    """The paired direction. Without this, a test that asserts "Acme is listed"
    would also pass against a hard-coded catalog."""
    assert _design_system_library() == []


def test_the_architect_payload_carries_the_library_and_no_compiled_bytes(graph_env):
    env = graph_env
    ids = _seed_library(env)
    env.skills.set(
        "architect",
        ArchitectOutput(intent="discuss", message="Which brand would you like?"),
    )

    architect_node(env.state(architect_message="what brands do we have?"))

    calls = env.skills.calls_for("architect")
    assert len(calls) == 1
    payload = calls[0]["payload"]

    assert "design_system_library" in payload, sorted(payload)
    listed = {entry["design_system_id"] for entry in payload["design_system_library"]}
    assert ids["acme"] in listed and ids["beta"] in listed
    assert ids["gone"] not in listed

    # The payload is JSON-serialised by AgentRuntime, so anything that
    # cannot cross json.dumps fails at prompt assembly rather than here.
    serialised = json.dumps(payload)
    # Ids and labels only: the template's compiled layout must NOT be in the prompt.
    assert "SEEDED LAYOUT" not in serialised
    assert "--brand" not in serialised
    # ...but the labels the architect chooses from must be.
    assert "Two column" in serialised


def test_an_unreadable_library_degrades_to_no_brand_on_offer(graph_env, monkeypatch):
    """A deck can be built with no brand at all, so a broken catalog read must
    cost the offer and not the turn."""

    def _boom():
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr("src.services.graph.nodes.get_db_session", _boom)
    assert _design_system_library() == []
