"""The one model-payload projection for #267 test runs (Corrections 10 and 37).

A test run must hand each role's model exactly what production hands it: the
content keys only, never a session, user, turn or release identifier (#258).
``MODEL_PAYLOAD_KEYS`` is pinned to the union of every production call's key
set in ``tests/fixtures/model_payload_keys.py`` (which ``test_graph_nodes.py``
pins production to), and the builder's set to the production allowlist.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS, model_payload_for
from src.services.agent_runtime import MODEL_DRIVEN_AGENT_KEYS, UnknownAgentKeyError
from src.services.graph_configuration_seed import REQUIRED_SMOKE_PAYLOADS
from tests.fixtures.model_payload_keys import EVERY_MODEL_CALL

#: What the projection drops from each seeded smoke payload (C37's evidence).
_SEED_DROPPED = {
    "architect": {"session_id"},
    "data_analyst": {"session_id"},
    "builder": {"session_id", "turn_id", "initiated_by", "design_contract"},
    "build_reviewer": set(),
    "fixer": set(),
    "fix_reviewer": set(),
    "deck_reviewer": {"session_id"},
}


def _production_union(role: str) -> frozenset[str]:
    union: frozenset[str] = frozenset()
    for _label, call_role, keys in EVERY_MODEL_CALL:
        if call_role == role:
            union |= keys
    return union


def test_the_projection_covers_exactly_the_seven_model_roles():
    assert set(MODEL_PAYLOAD_KEYS) == set(MODEL_DRIVEN_AGENT_KEYS)


@pytest.mark.parametrize("role", MODEL_DRIVEN_AGENT_KEYS)
def test_each_role_key_set_is_the_union_of_its_production_calls(role):
    assert MODEL_PAYLOAD_KEYS[role] == _production_union(role)


def test_the_builder_set_is_the_production_allowlist_plus_the_retry_instruction():
    from src.services.graph import nodes

    assert (
        MODEL_PAYLOAD_KEYS["builder"] - {"corrective_instruction"}
        == nodes._BUILDER_MODEL_PAYLOAD_KEYS
    )


@pytest.mark.parametrize("role", MODEL_DRIVEN_AGENT_KEYS)
def test_the_seed_projection_drops_exactly_the_identifier_keys(role):
    seed = REQUIRED_SMOKE_PAYLOADS[role]
    projected = model_payload_for(role, seed)
    assert set(seed) - set(projected) == _SEED_DROPPED[role]
    assert set(projected) == set(seed) & MODEL_PAYLOAD_KEYS[role]


@pytest.mark.parametrize("role", MODEL_DRIVEN_AGENT_KEYS)
def test_the_projection_keeps_payload_order_and_values(role):
    seed = REQUIRED_SMOKE_PAYLOADS[role]
    projected = model_payload_for(role, seed)
    assert list(projected) == [key for key in seed if key in MODEL_PAYLOAD_KEYS[role]]
    for key, value in projected.items():
        if key != "previous_deck_review":
            assert value == seed[key]


def test_no_seeded_identifier_value_survives_any_projection():
    identifiers = (
        "synthetic-architect",
        "synthetic-data-analyst",
        "synthetic-builder",
        "synthetic-turn",
        "system:bootstrap",
        "synthetic-deck-reviewer",
    )
    for role in MODEL_DRIVEN_AGENT_KEYS:
        text = json.dumps(model_payload_for(role, REQUIRED_SMOKE_PAYLOADS[role]))
        for identifier in identifiers:
            assert identifier not in text, (role, identifier)


def test_the_previous_deck_review_loses_its_author_as_in_production():
    stored = {
        "digest": "d" * 64,
        "findings": [{"criterion": "arc_gap", "message": "gap"}],
        "author": "reviewer@example.com",
    }
    projected = model_payload_for(
        "architect", {"session_id": "s", "message": "m", "previous_deck_review": stored}
    )
    assert projected == {
        "message": "m",
        "previous_deck_review": {
            "digest": "d" * 64,
            "findings": [{"criterion": "arc_gap", "message": "gap"}],
        },
    }
    assert "reviewer@example.com" not in json.dumps(projected)


def test_a_null_previous_deck_review_stays_null():
    assert model_payload_for("architect", {"previous_deck_review": None}) == {
        "previous_deck_review": None
    }


def test_the_projection_is_a_detached_copy():
    seed = {"slide_spec": {"title": "t"}, "position": 1}
    projected = model_payload_for("builder", seed)
    projected["slide_spec"]["title"] = "changed"
    assert seed["slide_spec"]["title"] == "t"


@pytest.mark.parametrize("role", ["foreman", "nope", ""])
def test_an_unknown_role_is_refused(role):
    with pytest.raises(UnknownAgentKeyError):
        model_payload_for(role, {"message": "m"})


def test_the_module_imports_no_graph_or_runtime_module():
    """Import-light (C37): the workbench must not pull in the graph module."""
    path = Path(__file__).resolve().parents[2] / "src/services/agent_model_payload.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    modules = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in top_level_imports
        for alias in (node.names if isinstance(node, ast.Import) else [node])
    }
    assert all(not (module or "").startswith("src.") for module in modules), modules
