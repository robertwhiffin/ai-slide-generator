"""``ArchitectOutput`` gains ``operations`` / ``deck_changes``; the architect contract
is re-pinned (architect edit operations, plan Task 2, spec §1).

- Both fields are optional and default to ``None``. Nothing is removed or renamed,
  so every output valid today stays valid.
- An ``edit`` needs a non-empty ``target_positions``, or ``operations``, or
  ``deck_changes``; the rejection names all three. Other intent rules are unchanged.
- Adding the fields changes the architect's frozen schema material, so its v1/v2
  digests are re-pinned. The superseded digests move to the historical table (a
  persisted release may still name them) and resolve to the current
  ``ArchitectOutput``. No other role's digest moves.

Outputs are built with ``ArchitectOutput.model_validate`` from plain dicts, as the
runtime does with the model's JSON.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_operations import DeckChanges, SlideContent, SlideOperation
from src.services.agent_schema_registry import (
    HISTORICAL_SCHEMA_CONTRACT_BUNDLES,
    V1_SCHEMA_IDENTITIES,
    V2_SCHEMA_IDENTITIES,
    AgentSchemaRegistry,
)
from src.services.agent_schema_types import SchemaContractIdentity, SchemaOverlay

# The architect digests live before this change. Written as literals, never imported.
PREVIOUS_ARCHITECT_V1 = "9704af4e9213f942104f449f09b66e41461cc774c7bfdd47e8c86a25b53b6285"
PREVIOUS_ARCHITECT_V2 = "39ed9e91b3640ded4f2859c074db3d6a8f24c14dff49f7011e590b7473956da9"
# The architect digests already historical before this change (commit 5653f3ec).
OLDER_ARCHITECT_V1 = "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd"
OLDER_ARCHITECT_V2 = "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122"

# Every other role's live digests, copied verbatim from the registry before this change.
OTHER_ROLES_V1 = {
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}
OTHER_ROLES_V2 = {
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}


def _slide(position: int) -> dict[str, Any]:
    return {
        "position": position,
        "purpose": f"purpose {position}",
        "content_brief": f"brief {position}",
        "assumes": f"assumes {position}",
        "hands_off": f"hands off {position}",
        "data_references": [],
    }


def _deck_spec() -> dict[str, Any]:
    return {
        "title": "Q2 review",
        "audience": "execs",
        "purpose": "report",
        "argument": "growth held",
        "call_to_action": "approve",
        "narrative_arc": ["context", "results", "ask"],
        "design_contract": {"slide_style_id": 1},
        "resolved_data": {"synthesis": "ok", "figures": [], "gaps": []},
        "slides": [_slide(0), _slide(1)],
    }


def _content(purpose: str) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "content_brief": f"{purpose} brief",
        "assumes": "nothing",
        "hands_off": "nothing",
        "data_references": ["q2_revenue"],
    }


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow ``$ref`` and step into the non-null branch of an Optional ``anyOf``."""
    while True:
        if "$ref" in node:
            node = defs[node["$ref"].rsplit("/", 1)[-1]]
            continue
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if b.get("type") != "null"]
            assert len(branches) == 1, node
            node = branches[0]
            continue
        return node


def test_edit_with_operations_needs_no_targets():
    out = ArchitectOutput.model_validate(
        {
            "intent": "edit",
            "message": "m",
            "operations": [
                {"op": "delete", "position": 1},
                {"op": "insert", "after_position": -1, "slides": [_content("opener")]},
            ],
        }
    )

    assert out.target_positions == []
    assert out.deck_spec is None
    assert out.deck_changes is None
    assert len(out.operations) == 2
    delete, insert = out.operations
    assert isinstance(delete, SlideOperation)
    assert (delete.op, delete.position, delete.after_position, delete.slides) == (
        "delete",
        1,
        None,
        None,
    )
    assert isinstance(insert, SlideOperation)
    assert (insert.op, insert.position, insert.after_position) == ("insert", None, -1)
    assert len(insert.slides) == 1
    assert isinstance(insert.slides[0], SlideContent)
    assert insert.slides[0].purpose == "opener"
    assert insert.slides[0].data_references == ["q2_revenue"]

    # The keyword form the brief names validates the same way.
    built = ArchitectOutput(
        intent="edit", message="m", operations=[SlideOperation(op="delete", position=1)]
    )
    assert built.target_positions == []
    assert [(o.op, o.position) for o in built.operations] == [("delete", 1)]


def test_edit_with_only_deck_changes_validates():
    out = ArchitectOutput.model_validate(
        {
            "intent": "edit",
            "message": "m",
            "deck_changes": {
                "title": "Q2 review, revised",
                "design_contract": {"slide_style_id": 7},
            },
        }
    )

    assert out.target_positions == []
    assert out.operations is None
    assert out.deck_spec is None
    assert isinstance(out.deck_changes, DeckChanges)
    assert out.deck_changes.title == "Q2 review, revised"
    assert out.deck_changes.design_contract.slide_style_id == 7
    assert out.deck_changes.audience is None


def test_edit_with_nothing_still_rejected():
    for payload in (
        {"intent": "edit", "message": "m"},
        {
            "intent": "edit",
            "message": "m",
            "target_positions": [],
            "operations": None,
            "deck_changes": None,
        },
    ):
        with pytest.raises(ValidationError) as excinfo:
            ArchitectOutput.model_validate(payload)

        errors = excinfo.value.errors()
        assert len(errors) == 1, errors
        assert errors[0]["type"] == "value_error"
        message = errors[0]["msg"]
        assert "target_positions" in message
        assert "operations" in message
        assert "deck_changes" in message


def test_edit_with_explicit_empty_operations_validates():
    # The rule is ``operations is not None``, not truthiness: an explicit empty list
    # is a valid edit here and reaches the node, which reports a retryable
    # "nothing to do" instead of failing schema validation.
    out = ArchitectOutput.model_validate({"intent": "edit", "message": "m", "operations": []})

    assert out.operations == []
    assert out.target_positions == []
    assert out.deck_changes is None


@pytest.mark.parametrize(
    ("intent", "payload"),
    [
        ("discuss", {}),
        ("build", {"deck_spec": _deck_spec()}),
        ("ask_data", {"data_request": {"metric": "revenue"}}),
        ("confirm_design_contract", {"proposed_design_contract": {"slide_style_id": 3}}),
    ],
)
def test_non_edit_intents_do_not_reject_operations_or_deck_changes(
    intent: str, payload: dict[str, Any]
):
    # Only the edit rule reads the new fields; no other intent's rule changed, so
    # a stray operations / deck_changes on another intent is carried, not rejected.
    out = ArchitectOutput.model_validate(
        {
            "intent": intent,
            "message": "m",
            **payload,
            "operations": [{"op": "delete", "position": 0}],
            "deck_changes": {"title": "t"},
        }
    )

    assert out.intent == intent
    assert [(o.op, o.position) for o in out.operations] == [("delete", 0)]
    assert out.deck_changes.title == "t"


def test_old_shape_still_valid():
    spec = _deck_spec()

    edit = ArchitectOutput.model_validate(
        {"intent": "edit", "message": "m", "deck_spec": spec, "target_positions": [1]}
    )
    assert edit.intent == "edit"
    assert edit.target_positions == [1]
    assert edit.deck_spec == DeckSpec.model_validate(spec)
    assert getattr(edit, "operations", None) is None
    assert getattr(edit, "deck_changes", None) is None

    build = ArchitectOutput.model_validate({"intent": "build", "message": "m", "deck_spec": spec})
    assert build.intent == "build"
    assert build.target_positions == []
    assert build.deck_spec == DeckSpec.model_validate(spec)
    assert getattr(build, "operations", None) is None
    assert getattr(build, "deck_changes", None) is None


def test_operations_in_json_schema():
    schema = ArchitectOutput.model_json_schema(mode="validation")
    props = schema["properties"]
    defs = schema.get("$defs", {})

    assert "operations" in props
    assert "deck_changes" in props
    required = set(schema.get("required", []))
    assert "operations" not in required
    assert "deck_changes" not in required
    assert required == {"intent", "message"}
    assert props["operations"].get("default", None) is None
    assert props["deck_changes"].get("default", None) is None

    operations = _deref(props["operations"], defs)
    assert operations["type"] == "array"
    item_ref = operations["items"]
    assert item_ref.get("$ref", "").endswith("/SlideOperation"), item_ref
    operation = _deref(item_ref, defs)
    assert {"op", "position", "after_position", "slides"} <= set(operation["properties"])
    op = operation["properties"]["op"]
    assert sorted(op["enum"]) == sorted(["insert", "update", "delete", "replace", "move"])
    assert len(op["enum"]) == 5
    assert operation.get("required") == ["op"]
    slides = _deref(operation["properties"]["slides"], defs)
    assert slides["items"].get("$ref", "").endswith("/SlideContent"), slides

    deck_changes_ref = [b for b in props["deck_changes"]["anyOf"] if b.get("type") != "null"]
    assert len(deck_changes_ref) == 1
    assert deck_changes_ref[0].get("$ref", "").endswith("/DeckChanges"), deck_changes_ref
    deck_changes = _deref(props["deck_changes"], defs)
    assert {"title", "design_contract", "resolved_data"} <= set(deck_changes["properties"])
    assert not deck_changes.get("required")


def test_historical_architect_digests_resolve():
    for version, digest in ((1, PREVIOUS_ARCHITECT_V1), (2, PREVIOUS_ARCHITECT_V2)):
        key = ("architect", version, digest)
        assert key in HISTORICAL_SCHEMA_CONTRACT_BUNDLES, (
            f"superseded architect v{version} digest {digest} is not retained"
        )
        bundle = HISTORICAL_SCHEMA_CONTRACT_BUNDLES[key]
        assert bundle.canonical_model is ArchitectOutput
        assert bundle.identity == SchemaContractIdentity("architect", version, digest)

    for version, digest in ((1, OLDER_ARCHITECT_V1), (2, OLDER_ARCHITECT_V2)):
        key = ("architect", version, digest)
        assert key in HISTORICAL_SCHEMA_CONTRACT_BUNDLES, f"historical row {key} was removed"
        assert HISTORICAL_SCHEMA_CONTRACT_BUNDLES[key].canonical_model is ArchitectOutput

    # The contract really was re-pinned: the live digests are new ones.
    live_v1 = V1_SCHEMA_IDENTITIES["architect"].digest
    live_v2 = V2_SCHEMA_IDENTITIES["architect"].digest
    assert live_v1 not in {PREVIOUS_ARCHITECT_V1, OLDER_ARCHITECT_V1}
    assert live_v2 not in {PREVIOUS_ARCHITECT_V2, OLDER_ARCHITECT_V2}

    # The live pins match the calculated material (raises otherwise), and a release
    # naming a superseded digest still composes, against the current model.
    registry = AgentSchemaRegistry()
    for version, digest in ((1, PREVIOUS_ARCHITECT_V1), (2, PREVIOUS_ARCHITECT_V2)):
        identity = SchemaContractIdentity("architect", version, digest)
        assert registry.identity_for("architect", version) != identity
        composed = registry.compose("architect", identity, SchemaOverlay())
        assert composed.canonical_model is ArchitectOutput


def test_other_roles_digests_unchanged():
    assert set(V1_SCHEMA_IDENTITIES) == {"architect", *OTHER_ROLES_V1}
    assert set(V2_SCHEMA_IDENTITIES) == {"architect", *OTHER_ROLES_V2}
    assert {role: V1_SCHEMA_IDENTITIES[role].digest for role in OTHER_ROLES_V1} == OTHER_ROLES_V1
    assert {role: V2_SCHEMA_IDENTITIES[role].digest for role in OTHER_ROLES_V2} == OTHER_ROLES_V2
    # The pins are the calculated material, so no other role's schema moved.
    AgentSchemaRegistry()
