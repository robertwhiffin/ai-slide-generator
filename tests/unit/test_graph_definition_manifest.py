from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW
from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON
from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS
from src.services.graph_definition_manifest import (
    AssemblyRulesV1,
    AssemblyRulesV2,
    CanonicalFieldGuidance,
    ContentIdentity,
    CustomTextBlock,
    DefinitionContent,
    GraphV1Manifest,
    SchemaOverlay,
    assembly_rules_for,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.prompt_assembler import PromptAssembler, PromptAssemblyRejected

EXPECTED_COMMON_BLOCKS = [
    ("authored_prompt", "always", None),
    ("protected", "design_system_inactive", "slide_frame_constraints"),
    ("protected", "design_system_active", "design_system_precedence"),
    ("payload_json", "always", None),
    ("structured_output_binding", "always", None),
]
EXPECTED_BUILD_REVIEWER_BLOCKS = [
    ("authored_prompt", "always", None),
    ("protected", "payload_has_deck_brief", "build_reviewer_deck_brief"),
    ("protected", "design_system_inactive", "slide_frame_constraints"),
    ("protected", "design_system_active", "design_system_precedence"),
    ("payload_json", "always", None),
    ("structured_output_binding", "always", None),
]


@dataclass(frozen=True)
class ReplayedAssembly:
    prompt: str
    terminal_binding: str


def _block_signature(content: DefinitionContent) -> list[tuple[str, str, str | None]]:
    return [
        (
            block.kind,
            block.condition,
            getattr(block, "name", None),
        )
        for block in content.assembly_rules.blocks
    ]


def _definition_by_key(manifest: GraphV1Manifest, agent_key: str) -> DefinitionContent:
    return next(item for item in manifest.definitions if item.agent_key == agent_key)


def _custom(
    block_id: str,
    text: str,
    *,
    anchor: str = "after_authored_prompt",
    condition: str = "always",
) -> CustomTextBlock:
    """Build literal v2 wire data; the grammar must preserve these values unchanged."""
    return CustomTextBlock.model_validate(
        {
            "kind": "custom_text",
            "block_id": block_id,
            "anchor": anchor,
            "condition": condition,
            "text": text,
        }
    )


def _v2(
    agent_key: str,
    custom_blocks: list[CustomTextBlock],
) -> DefinitionContent:
    raw = _definition_by_key(load_graph_v1_manifest(), agent_key).model_dump(mode="python")
    raw["assembly_rules"] = {
        "format_version": 2,
        "custom_blocks": [block.model_dump(mode="python") for block in custom_blocks],
    }
    return DefinitionContent.model_validate(raw)


def _replay_literal_v1_rules(
    content: DefinitionContent,
    payload: dict[str, Any],
    design_system_active: bool,
) -> ReplayedAssembly:
    protected_values = {
        "build_reviewer_deck_brief": DECK_BRIEF_REVIEW,
        "slide_frame_constraints": _SLIDE_FRAME_CONSTRAINTS,
        "design_system_precedence": DESIGN_SYSTEM_PRECEDENCE,
    }
    expected_blocks = (
        EXPECTED_BUILD_REVIEWER_BLOCKS
        if content.agent_key == "build_reviewer"
        else EXPECTED_COMMON_BLOCKS
    )
    assert _block_signature(content) == expected_blocks

    parts: list[str] = []
    terminal_binding = ""
    for kind, condition, name in expected_blocks:
        applies = {
            "always": True,
            "design_system_active": design_system_active,
            "design_system_inactive": not design_system_active,
            "payload_has_deck_brief": bool(payload.get("deck_brief")),
        }[condition]
        if not applies:
            continue
        if kind == "authored_prompt":
            parts.append(content.prompt_text)
        elif kind == "protected":
            assert name is not None
            if name == "slide_frame_constraints" and content.agent_key != "builder":
                continue
            if name == "design_system_precedence" and content.agent_key != "architect":
                continue
            parts.append(protected_values[name])
        elif kind == "payload_json":
            parts.append(json.dumps(payload, indent=2, default=str))
        elif kind == "structured_output_binding":
            terminal_binding = "langchain.with_structured_output"
        else:  # pragma: no cover - literals above close this test evaluator
            raise AssertionError(f"unexpected literal test block: {kind}")
    return ReplayedAssembly(
        prompt="\n\n".join(parts),
        terminal_binding=terminal_binding,
    )


def _semantic_mutations(original: DefinitionContent) -> list[DefinitionContent]:
    model_mutations = [
        original.model_copy(update={"definition_version": 3}),
        original.model_copy(update={"prompt_text": original.prompt_text + "!"}),
        original.model_copy(
            update={
                "model": original.model.model_copy(
                    update={"endpoint_name": original.model.endpoint_name + "-changed"}
                )
            }
        ),
        original.model_copy(
            update={
                "model": original.model.model_copy(
                    update={"temperature": Decimal("0.71")}
                )
            }
        ),
        original.model_copy(
            update={
                "model": original.model.model_copy(
                    update={"max_tokens": original.model.max_tokens + 1}
                )
            }
        ),
        original.model_copy(
            update={
                "model": original.model.model_copy(update={"top_p": Decimal("0.96")})
            }
        ),
        original.model_copy(
            update={
                "schema_overlay": original.schema_overlay.model_copy(
                    update={"additional_optional_fields": ("synthetic",)}
                )
            }
        ),
        original.model_copy(
            update={
                "assembly_rules": original.assembly_rules.model_copy(
                    update={"blocks": tuple(reversed(original.assembly_rules.blocks))}
                )
            }
        ),
        original.model_copy(
            update={
                "protected_assembly": original.protected_assembly.model_copy(
                    update={"version": original.protected_assembly.version + 1}
                )
            }
        ),
        original.model_copy(
            update={
                "protected_assembly": original.protected_assembly.model_copy(
                    update={"digest": "0" * 64}
                )
            }
        ),
        original.model_copy(
            update={
                "schema_contract": original.schema_contract.model_copy(
                    update={"version": original.schema_contract.version + 1}
                )
            }
        ),
        original.model_copy(
            update={
                "schema_contract": original.schema_contract.model_copy(
                    update={"digest": "0" * 64}
                )
            }
        ),
    ]
    return model_mutations


def _assert_no_tool_grants(value: object) -> None:
    if isinstance(value, dict):
        assert "tool_grants" not in value
        for nested in value.values():
            _assert_no_tool_grants(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_tool_grants(nested)


def test_importing_typed_manifest_does_not_import_static_snapshot():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import src.services.graph_definition_manifest; "
                "assert 'src.services.agent_definition_manifest_v1' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_packaged_v1_manifest_hashes_and_contracts_match_stable_literals():
    """Compare manifest against literals and load_skill as a test-side historical record."""
    manifest = load_graph_v1_manifest()
    assert tuple(item.agent_key for item in manifest.definitions) == MODEL_DRIVEN_AGENT_KEYS
    # Protected-assembly oracle: the one shared digest literal.
    expected_protected_digest = "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"
    for item in manifest.definitions:
        # load_skill is the test-side historical record: the manifest's prompt_text must
        # equal the shipped skill instructions (C-24: a literal, not an import).
        assert item.prompt_text == load_skill(item.agent_key).instructions
        assert definition_content_hash(item) == PACKAGED_V1_CONTENT_HASHES[item.agent_key]
        assert item.schema_contract.version == 1
        assert item.schema_contract.digest == V1_SCHEMA_CONTRACT_DIGESTS[item.agent_key]
        assert item.protected_assembly.version == 1
        assert item.protected_assembly.digest == expected_protected_digest


def test_v1_definition_versions_are_frozen_at_two():
    assert {item.definition_version for item in load_graph_v1_manifest().definitions} == {2}


def test_manifest_contains_no_foreman_or_tool_grants():
    raw = json.loads(GRAPH_VERSION_1_MANIFEST_JSON)
    assert tuple(item["agent_key"] for item in raw["definitions"]) == MODEL_DRIVEN_AGENT_KEYS
    _assert_no_tool_grants(raw)


def test_cached_manifest_overlay_cannot_mutate_shared_or_canonical_state():
    first = load_graph_v1_manifest().definitions[0]
    before_dump = first.model_dump(mode="python")
    before_hash = definition_content_hash(first)

    overrides = cast(Any, first.schema_overlay.field_overrides)
    with pytest.raises(TypeError):
        overrides["review_probe"] = {"nested": True}

    second = load_graph_v1_manifest().definitions[0]
    assert second is first
    assert second.model_dump(mode="python") == before_dump
    assert definition_content_hash(second) == before_hash


def test_nested_overlay_containers_are_immutable_but_dump_as_json_containers():
    """Nested JSON inside a typed guidance entry stays frozen but dumps as JSON.

    Under the typed overlay grammar arbitrary nested JSON reaches the carrier as a
    guidance entry's retained extra properties, so the frozen containers must be
    reached through ``forbidden_properties()``.  Subscripting the guidance model
    itself would raise ``TypeError`` merely because a model is not subscriptable,
    which would make this guard pass without measuring immutability at all.
    """
    original = load_graph_v1_manifest().definitions[0]
    raw = original.model_dump(mode="python")
    raw["schema_overlay"]["field_overrides"] = {
        "message": {"outer": {"values": [{"enabled": True}]}}
    }
    candidate = DefinitionContent.model_validate(raw)
    before_hash = definition_content_hash(candidate)
    guidance = candidate.schema_overlay.field_overrides["message"]
    overrides = cast(Any, guidance.forbidden_properties())

    assert isinstance(overrides["outer"], MappingProxyType)
    assert isinstance(overrides["outer"]["values"], tuple)
    with pytest.raises(TypeError):
        overrides["outer"]["added"] = False
    with pytest.raises(TypeError):
        overrides["outer"]["values"][0]["enabled"] = False
    with pytest.raises(TypeError):
        overrides["outer"]["values"][0] = {"enabled": False}

    assert candidate.model_dump(mode="python") == raw
    assert definition_content_hash(candidate) == before_hash


def test_static_assembly_rule_shapes_are_literal_and_role_specific():
    manifest = load_graph_v1_manifest()
    for item in manifest.definitions:
        expected = (
            EXPECTED_BUILD_REVIEWER_BLOCKS
            if item.agent_key == "build_reviewer"
            else EXPECTED_COMMON_BLOCKS
        )
        assert _block_signature(item) == expected
        assert item.assembly_rules.format_version == 1
        assert item.assembly_rules.separator == "\n\n"


def test_generated_v1_rules_use_the_frozen_v1_model_and_reject_literal_changes():
    for content in load_graph_v1_manifest().definitions:
        assert isinstance(content.assembly_rules, AssemblyRulesV1)
        for index, _block in enumerate(content.assembly_rules.blocks):
            raw = content.model_dump(mode="python")
            raw["assembly_rules"]["blocks"][index]["kind"] = "changed_literal"
            with pytest.raises(ValidationError):
                DefinitionContent.model_validate(raw)


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
@pytest.mark.parametrize("design_system_active", [False, True])
def test_manifest_assembly_replays_exact_runtime_prompt(
    agent_key: str,
    design_system_active: bool,
):
    payload = (
        {"deck_brief": "Synthetic brief"}
        if agent_key == "build_reviewer"
        else {"synthetic": True}
    )
    manifest_definition = _definition_by_key(load_graph_v1_manifest(), agent_key)
    actual = PromptAssembler().assemble(
        definition=manifest_definition,
        payload=payload,
        context=AgentAssemblyContext(design_system_active),
    ).prompt
    replayed = _replay_literal_v1_rules(
        manifest_definition,
        payload,
        design_system_active,
    )
    assert replayed.prompt == actual
    assert replayed.terminal_binding == "langchain.with_structured_output"


def test_frozen_v1_manifest_identity_remains_exact_for_protected_assembler() -> None:
    """Catches changing historical v1 identity while introducing its v2 successor."""
    from src.services.prompt_assembler import V1_PROTECTED_ASSEMBLY_IDENTITY

    assert V1_PROTECTED_ASSEMBLY_IDENTITY.model_dump() == {
        "version": 1,
        "digest": "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852",
    }
    assert {
        definition.protected_assembly for definition in load_graph_v1_manifest().definitions
    } == {V1_PROTECTED_ASSEMBLY_IDENTITY}


@pytest.mark.parametrize("deck_brief", [None, "", "Synthetic brief"])
def test_build_reviewer_deck_brief_block_tracks_payload_truthiness(deck_brief: str | None):
    payload = {"deck_brief": deck_brief}
    content = _definition_by_key(load_graph_v1_manifest(), "build_reviewer")
    actual = PromptAssembler().assemble(
        definition=content,
        payload=payload,
        context=AgentAssemblyContext(False),
    ).prompt
    assert _replay_literal_v1_rules(content, payload, False).prompt == actual


def test_non_build_reviewer_ignores_deck_brief_protected_block():
    payload = {"deck_brief": "Synthetic brief"}
    content = _definition_by_key(load_graph_v1_manifest(), "architect")
    actual = PromptAssembler().assemble(
        definition=content,
        payload=payload,
        context=AgentAssemblyContext(False),
    ).prompt
    assert _replay_literal_v1_rules(content, payload, False).prompt == actual


def test_hash_covers_every_semantic_field():
    original = load_graph_v1_manifest().definitions[0]
    baseline = definition_content_hash(original)
    mutations = _semantic_mutations(original)
    assert len(mutations) == 12
    assert {definition_content_hash(item) for item in mutations}.isdisjoint({baseline})
    assert re.fullmatch(r"[0-9a-f]{64}", baseline)


def test_hash_normalizes_manifest_floats_and_database_decimals():
    original = load_graph_v1_manifest().definitions[0]
    database_shape = original.model_copy(
        update={
            "model": original.model.model_copy(
                update={
                    "temperature": Decimal("0.700000"),
                    "top_p": Decimal("0.950000"),
                }
            )
        }
    )
    assert definition_content_hash(database_shape) == definition_content_hash(original)


def test_v2_hash_includes_custom_identity_and_order() -> None:
    first = _v2(
        "architect",
        [
            _custom("00000000-0000-0000-0000-000000000001", "one"),
            _custom("00000000-0000-0000-0000-000000000002", "two"),
        ],
    )
    second = first.model_copy(
        update={
            "assembly_rules": AssemblyRulesV2(
                format_version=2,
                custom_blocks=tuple(reversed(first.assembly_rules.custom_blocks)),
            )
        }
    )
    assert definition_content_hash(first) != definition_content_hash(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("block_id", UUID("00000000-0000-0000-0000-000000000003")),
        ("text", "changed"),
        ("anchor", "after_environment_constraints"),
        ("condition", "design_system_active"),
    ],
)
def test_v2_hash_includes_every_custom_block_field(field: str, value: object) -> None:
    original = _v2("architect", [_custom("00000000-0000-0000-0000-000000000001", "one")])
    block = original.assembly_rules.custom_blocks[0].model_copy(update={field: value})
    changed = original.model_copy(
        update={
            "assembly_rules": AssemblyRulesV2(format_version=2, custom_blocks=(block,))
        }
    )
    assert definition_content_hash(changed) != definition_content_hash(original)


@pytest.mark.parametrize(
    "condition",
    [
        "always",
        "design_system_active",
        "design_system_inactive",
        "payload_has_deck_brief",
    ],
)
def test_v2_custom_block_accepts_every_condition_literal(condition: str) -> None:
    content = _v2(
        "architect",
        [_custom("00000000-0000-0000-0000-000000000001", "text", condition=condition)],
    )
    assert content.assembly_rules.custom_blocks[0].condition == condition


@pytest.mark.parametrize(
    "anchor",
    [
        "after_authored_prompt",
        "after_deck_brief",
        "after_environment_constraints",
    ],
)
def test_v2_custom_block_accepts_every_anchor_literal(anchor: str) -> None:
    content = _v2(
        "architect",
        [_custom("00000000-0000-0000-0000-000000000001", "text", anchor=anchor)],
    )
    assert content.assembly_rules.custom_blocks[0].anchor == anchor


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("custom_blocks", 0, "kind"), "unknown"),
        (("custom_blocks", 0, "condition"), "unknown"),
        (("custom_blocks", 0, "anchor"), "unknown"),
        (("custom_blocks", 0, "unexpected"), True),
        (("custom_blocks", 0, "text"), None),
    ],
)
def test_v2_rules_reject_unknown_vocabulary_extras_and_wrong_types(
    path: tuple[object, ...], value: object
) -> None:
    raw = _definition_by_key(load_graph_v1_manifest(), "architect").model_dump(mode="python")
    raw["assembly_rules"] = {
        "format_version": 2,
        "custom_blocks": [
            {
                "kind": "custom_text",
                "block_id": "00000000-0000-0000-0000-000000000001",
                "anchor": "after_authored_prompt",
                "condition": "always",
                "text": "text",
            }
        ],
    }
    target: object = raw["assembly_rules"]
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        DefinitionContent.model_validate(raw)


@pytest.mark.parametrize("missing", ["block_id", "anchor", "condition", "text"])
def test_v2_rules_reject_missing_custom_block_fields(missing: str) -> None:
    raw = _definition_by_key(load_graph_v1_manifest(), "architect").model_dump(mode="python")
    raw["assembly_rules"] = {
        "format_version": 2,
        "custom_blocks": [
            {
                "kind": "custom_text",
                "block_id": "00000000-0000-0000-0000-000000000001",
                "anchor": "after_authored_prompt",
                "condition": "always",
                "text": "text",
            }
        ],
    }
    del raw["assembly_rules"]["custom_blocks"][0][missing]
    with pytest.raises(ValidationError):
        DefinitionContent.model_validate(raw)


def test_v2_wire_grammar_preserves_deferred_semantic_candidates() -> None:
    content = _v2(
        "architect",
        [
            _custom(
                "00000000-0000-0000-0000-000000000001",
                "   ",
                anchor="after_environment_constraints",
                condition="always",
            ),
            _custom(
                "00000000-0000-0000-0000-000000000001",
                "second",
                anchor="after_authored_prompt",
                condition="design_system_active",
            ),
            _custom(
                "00000000-0000-0000-0000-000000000003",
                "third",
                anchor="after_deck_brief",
                condition="design_system_inactive",
            ),
        ],
    )
    assert isinstance(content.assembly_rules, AssemblyRulesV2)
    assert tuple(block.block_id for block in content.assembly_rules.custom_blocks) == (
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000003"),
    )
    assert tuple(block.text for block in content.assembly_rules.custom_blocks) == (
        "   ",
        "second",
        "third",
    )
    assert tuple(block.anchor for block in content.assembly_rules.custom_blocks) == (
        "after_environment_constraints",
        "after_authored_prompt",
        "after_deck_brief",
    )
    assert tuple(block.condition for block in content.assembly_rules.custom_blocks) == (
        "always",
        "design_system_active",
        "design_system_inactive",
    )


def test_assembler_rejects_v2_rules_paired_with_v1_identity() -> None:
    content = _v2(
        "architect",
        [_custom("00000000-0000-0000-0000-000000000001", "custom")],
    )
    with pytest.raises(PromptAssemblyRejected) as caught:
        PromptAssembler().assemble(
            definition=content,
            payload={"synthetic": True},
            context=AgentAssemblyContext(False),
        )
    assert [issue.code for issue in caught.value.issues] == ["assembly_bundle_mismatch"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", float("nan")),
        ("temperature", float("inf")),
        ("temperature", Decimal("NaN")),
        ("top_p", Decimal("Infinity")),
    ],
)
def test_hash_rejects_non_finite_numeric_values(field: str, value: object):
    original = load_graph_v1_manifest().definitions[0]
    changed = original.model_copy(
        update={"model": original.model.model_copy(update={field: value})}
    )
    with pytest.raises(ValueError, match="finite"):
        definition_content_hash(changed)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("assembly_rules", "blocks", 0, "kind"), "unknown"),
        (("assembly_rules", "blocks", 0, "condition"), "unknown"),
    ],
)
def test_manifest_rejects_unknown_assembly_vocabulary(
    path: tuple[object, ...],
    value: str,
):
    raw = json.loads(GRAPH_VERSION_1_MANIFEST_JSON)
    target: object = raw["definitions"][0]
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        GraphV1Manifest.model_validate(raw)


def test_manifest_models_forbid_extra_fields_and_incomplete_role_sets():
    raw = json.loads(GRAPH_VERSION_1_MANIFEST_JSON)
    raw["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GraphV1Manifest.model_validate(raw)

    incomplete = json.loads(GRAPH_VERSION_1_MANIFEST_JSON)
    incomplete["definitions"].pop()
    with pytest.raises(ValueError, match="exact ordered role set"):
        GraphV1Manifest.model_validate(incomplete)


def test_assembly_rules_for_rejects_unknown_roles():
    with pytest.raises(ValueError, match="Unknown model-driven agent key"):
        assembly_rules_for("foreman")


# ---------------------------------------------------------------------------
# Task 2 (#264): typed overlay grammar integrated into the storage carrier.
#
# Every exact value below is written as a literal rather than imported from the
# implementation (epic correction C-24): a test that imports the constant it
# asserts agrees with the code by construction and can never disagree with the
# requirement.
# ---------------------------------------------------------------------------

# The seven packaged v1 content hashes, recomputed from landed source and used
# here as the byte-identity oracle for the grammar change.
PACKAGED_V1_CONTENT_HASHES = {
    "architect": "4a332258160d807513e8e268fdbec7d0b02c4ab71ad089f5f260f53dc4ea5d81",
    "data_analyst": "287da422d4aeb6c328685ace87be167feac639e4318cff07f147d9cd181be3c3",
    "builder": "46d7137b5c94c18acac4ebf6d4bebe5206c192852dffcc6e84fb0404be45598a",
    "build_reviewer": "c5b057097c6f952de7b4984d19ad0c6cceaf68e1641401dcf8ae5c3af707d622",
    "fixer": "1d42f0d7c437ae1714eacaf09bb7d5047463e20acf581daf136d411ed9b5c825",
    "fix_reviewer": "ff14c8e8b1622482f675f726eaeb10db2618b28afdce9598f1a6198ce36f04c0",
    "deck_reviewer": "7f015a2cb032f3d528ec9e5391e79ec21d7fe77514dcf33855734571c0bced1b",
}

V1_SCHEMA_CONTRACT_DIGESTS = {
    "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}

V2_SCHEMA_CONTRACT_DIGESTS = {
    "architect": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}


def test_manifest_overlay_is_the_one_typed_grammar_and_not_a_second_definition() -> None:
    """Clause: import/re-export the typed grammar; leave no competing definition."""
    import src.services.agent_schema_types as typed_module
    import src.services.graph_definition_manifest as manifest_module

    assert manifest_module.SchemaOverlay is typed_module.SchemaOverlay
    # The class must be *homed* in the public types module, not redefined here.
    assert manifest_module.SchemaOverlay.__module__ == "src.services.agent_schema_types"
    assert DefinitionContent.model_fields["schema_overlay"].annotation is (
        typed_module.SchemaOverlay
    )
    # The overlay field values are the typed guidance model, not raw JSON objects.
    assert (
        manifest_module.SchemaOverlay.model_fields["field_overrides"].annotation
        == Mapping[str, typed_module.CanonicalFieldGuidance]
    )
    # The freeze helper converged too: no third copy of the #260 pattern here.
    assert not hasattr(manifest_module, "_freeze_json_containers")
    assert not hasattr(manifest_module, "_thaw_json_containers")


def test_packaged_v1_overlay_payload_is_byte_identical_under_the_chosen_mode() -> None:
    """Clause: byte-identical v1 payloads.

    The decision is recorded in the assertions rather than left implicit:
    ``mode='json'`` is the storage/wire serialization (it is what
    ``definition_content_values`` writes to the JSON column), and it yields
    ``[]``.  ``mode='python'`` yields ``()`` and is asserted separately so a
    future silent swap of one for the other cannot pass.
    """
    from src.services.graph_configuration_content import definition_content_values

    for definition in load_graph_v1_manifest().definitions:
        assert definition.model_dump(mode="json")["schema_overlay"] == {
            "field_overrides": {},
            "additional_optional_fields": [],
        }
        assert definition.model_dump(mode="python")["schema_overlay"] == {
            "field_overrides": {},
            "additional_optional_fields": (),
        }
        # The exact value the one landed mapper hands to the JSON column.  This
        # re-serialises the mapper's dict, so it pins that value canonically; it
        # is not a capture of the bytes SQLAlchemy itself emits.
        persisted = definition_content_values(definition)["schema_overlay"]
        assert json.dumps(persisted, sort_keys=True, separators=(",", ":")) == (
            '{"additional_optional_fields":[],"field_overrides":{}}'
        )


def test_packaged_v1_content_hashes_are_the_seven_frozen_literals() -> None:
    """Clause: byte-identical v1 hashes, against the recomputed landed oracle."""
    actual = {
        definition.agent_key: definition_content_hash(definition)
        for definition in load_graph_v1_manifest().definitions
    }
    assert actual == PACKAGED_V1_CONTENT_HASHES


def test_typed_guidance_round_trips_through_the_storage_carrier() -> None:
    """Clause: typed guidance round-trip, including absent-versus-null retention."""
    original = _definition_by_key(load_graph_v1_manifest(), "architect")
    raw = original.model_dump(mode="python")
    raw["schema_overlay"] = {
        "field_overrides": {
            "message": {
                "description": "Explain the selected intent.",
                "examples": [{"nested": {"values": [1, 2]}}, "flat"],
            },
            "intent": {"description": None},
            "deck_spec": {"examples": ["only examples supplied"]},
        },
        "additional_optional_fields": ("diagnostic_notes",),
    }
    content = DefinitionContent.model_validate(raw)

    wire = content.model_dump(mode="json")
    assert wire["schema_overlay"] == {
        "field_overrides": {
            "message": {
                "description": "Explain the selected intent.",
                "examples": [{"nested": {"values": [1, 2]}}, "flat"],
            },
            "intent": {"description": None},
            "deck_spec": {"examples": ["only examples supplied"]},
        },
        "additional_optional_fields": ["diagnostic_notes"],
    }

    restored = DefinitionContent.model_validate(wire)
    assert restored.model_dump(mode="json") == wire
    assert definition_content_hash(restored) == definition_content_hash(content)

    for carrier in (content, restored):
        overrides = carrier.schema_overlay.field_overrides
        message = overrides["message"]
        assert type(message).__name__ == "CanonicalFieldGuidance"
        assert message.mutation_is_supplied("description") is True
        assert message.mutation_is_supplied("examples") is True
        # Explicit null is retained as supplied-and-null.
        assert overrides["intent"].mutation_is_supplied("description") is True
        assert overrides["intent"].description is None
        # An omitted mutation stays absent rather than becoming null.
        assert overrides["intent"].mutation_is_supplied("examples") is False
        assert overrides["deck_spec"].mutation_is_supplied("description") is False
        assert overrides["deck_spec"].mutation_is_supplied("examples") is True


def test_typed_guidance_nested_containers_are_frozen_inside_the_carrier() -> None:
    """Clause: the #260 recursive freeze reaches through the typed grammar."""
    original = _definition_by_key(load_graph_v1_manifest(), "architect")
    raw = original.model_dump(mode="python")
    raw["schema_overlay"] = {
        "field_overrides": {
            "message": {"examples": [{"outer": {"values": [{"enabled": True}]}}]}
        },
        "additional_optional_fields": (),
    }
    content = DefinitionContent.model_validate(raw)
    before_hash = definition_content_hash(content)

    overrides = cast(Any, content.schema_overlay.field_overrides)
    with pytest.raises(TypeError):
        overrides["message"] = None
    examples = cast(Any, overrides["message"].examples)
    assert isinstance(examples, tuple)
    with pytest.raises(TypeError):
        examples[0]["added"] = False
    with pytest.raises(TypeError):
        examples[0]["outer"]["added"] = False
    with pytest.raises(TypeError):
        examples[0]["outer"]["values"][0]["enabled"] = False
    with pytest.raises(TypeError):
        examples[0]["outer"]["values"][0] = {"enabled": False}

    # Frozen in memory, plain JSON containers on the wire, hash unchanged.
    assert content.model_dump(mode="json")["schema_overlay"]["field_overrides"] == {
        "message": {"examples": [{"outer": {"values": [{"enabled": True}]}}]}
    }
    assert definition_content_hash(content) == before_hash


@pytest.mark.parametrize(
    "agent_key",
    [
        "architect",
        "data_analyst",
        "builder",
        "build_reviewer",
        "fixer",
        "fix_reviewer",
        "deck_reviewer",
    ],
)
def test_schema_contract_upgrade_changes_the_hash_and_only_the_schema_identity(
    agent_key: str,
) -> None:
    """Clauses: v2 hash change, all v1/v2 identities, no client-selected identity."""
    from src.services.agent_schema_registry import upgrade_content_to_v2

    original = _definition_by_key(load_graph_v1_manifest(), agent_key)
    assert original.schema_contract.model_dump() == {
        "version": 1,
        "digest": V1_SCHEMA_CONTRACT_DIGESTS[agent_key],
    }

    upgraded = upgrade_content_to_v2(original)

    # The storage/wire carrier is retained: still ContentIdentity(version, digest).
    assert type(upgraded.schema_contract) is type(original.schema_contract)
    assert upgraded.schema_contract.model_dump() == {
        "version": 2,
        "digest": V2_SCHEMA_CONTRACT_DIGESTS[agent_key],
    }
    assert definition_content_hash(upgraded) != definition_content_hash(original)
    assert definition_content_hash(original) == PACKAGED_V1_CONTENT_HASHES[agent_key]

    # Schema and assembly versions are not coupled: the #265 assembly identity,
    # its rules and the prompt are untouched by a schema-contract upgrade.
    assert upgraded.protected_assembly.model_dump() == {
        "version": 1,
        "digest": "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852",
    }
    assert upgraded.assembly_rules == original.assembly_rules
    assert upgraded.prompt_text == original.prompt_text
    assert upgraded.definition_version == original.definition_version
    assert upgraded.model == original.model


def test_assembly_upgrade_leaves_the_schema_contract_untouched() -> None:
    """Clause: independent #265 assembly identity validation, the other direction."""
    original = _definition_by_key(load_graph_v1_manifest(), "architect")
    upgraded = PromptAssembler().upgrade_definition_to_v2(definition=original)

    assert upgraded.protected_assembly.model_dump() == {
        "version": 2,
        "digest": "fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a",
    }
    assert upgraded.schema_contract.model_dump() == {
        "version": 1,
        "digest": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    }
    assert upgraded.schema_overlay == original.schema_overlay


@pytest.mark.parametrize(
    "agent_key",
    [
        "architect",
        "data_analyst",
        "builder",
        "build_reviewer",
        "fixer",
        "fix_reviewer",
        "deck_reviewer",
    ],
)
@pytest.mark.parametrize("version", [1, 2])
def test_stored_identity_resolves_the_exact_role_and_version_bundle(
    agent_key: str, version: int
) -> None:
    """Clause: all v1/v2 identities resolve from the retained storage carrier."""
    from src.services.agent_schema_registry import AgentSchemaRegistry
    from src.services.graph_definition_manifest import schema_contract_identity

    expected = (V1_SCHEMA_CONTRACT_DIGESTS if version == 1 else V2_SCHEMA_CONTRACT_DIGESTS)
    stored = ContentIdentity(version=version, digest=expected[agent_key])
    identity = schema_contract_identity(agent_key, stored)

    assert (identity.agent_key, identity.version, identity.digest) == (
        agent_key,
        version,
        expected[agent_key],
    )
    registry = AgentSchemaRegistry()
    assert registry.validate_overlay(agent_key, identity, SchemaOverlay()) == ()


@pytest.mark.parametrize(
    ("agent_key", "version", "digest", "reason"),
    [
        (
            "not_a_role",
            1,
            "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
            "unknown role",
        ),
        (
            "architect",
            3,
            "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
            "unknown version",
        ),
        (
            "architect",
            1,
            "0" * 64,
            "mismatched digest",
        ),
        (
            "builder",
            1,
            "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
            "another role's digest",
        ),
        (
            "architect",
            2,
            "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
            "v1 digest under v2",
        ),
        (
            "architect",
            1,
            "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
            "v2 digest under v1",
        ),
    ],
)
def test_stored_identity_resolution_fails_closed(
    agent_key: str, version: int, digest: str, reason: str
) -> None:
    """Clause: fail-closed missing/mismatched role, version and digest."""
    from src.services.agent_schema_registry import AgentSchemaRegistry
    from src.services.graph_definition_manifest import schema_contract_identity

    identity = schema_contract_identity(
        agent_key, ContentIdentity(version=version, digest=digest)
    )
    issues = AgentSchemaRegistry().validate_overlay(agent_key, identity, SchemaOverlay())
    assert [issue.code for issue in issues] == ["overlay_schema_contract_unavailable"], reason
    assert [issue.path for issue in issues] == [()], reason


def test_schema_contract_upgrade_does_not_regenerate_graph_v1() -> None:
    """Clause: do not regenerate Graph V1.

    The packaged snapshot and its cached manifest must be unchanged by an
    upgrade, which returns a new record rather than mutating the shared one.
    """
    from src.services.agent_schema_registry import upgrade_content_to_v2

    before_snapshot = GRAPH_VERSION_1_MANIFEST_JSON
    manifest = load_graph_v1_manifest()
    before = {item.agent_key: definition_content_hash(item) for item in manifest.definitions}

    for definition in manifest.definitions:
        upgraded = upgrade_content_to_v2(definition)
        assert upgraded is not definition

    again = load_graph_v1_manifest()
    assert again is manifest
    assert {
        item.agent_key: definition_content_hash(item) for item in again.definitions
    } == before
    assert before == PACKAGED_V1_CONTENT_HASHES
    assert GRAPH_VERSION_1_MANIFEST_JSON is before_snapshot


def test_hashing_still_fails_closed_on_a_non_json_guidance_value() -> None:
    """The converged grammar retains invalid leaves; hashing must still refuse them.

    The removed local freeze helper rejected non-JSON overlay values at validation
    time.  The typed grammar deliberately retains them so the registry can return
    its own ordered domain diagnostic, so the fail-closed guarantee has to be
    asserted at the hashing boundary instead of silently disappearing with it.
    """
    original = _definition_by_key(load_graph_v1_manifest(), "architect")
    guidance = CanonicalFieldGuidance.model_validate({"examples": [object()]})
    candidate = original.model_copy(
        update={
            "schema_overlay": SchemaOverlay(
                field_overrides={"message": guidance},
                additional_optional_fields=(),
            )
        }
    )
    with pytest.raises(TypeError):
        definition_content_hash(candidate)


# ---------------------------------------------------------------------------
# Task 2 fix round 1 — corrections 27 through 30.
# ---------------------------------------------------------------------------


def test_canonical_payload_mode_is_load_bearing_for_the_finiteness_guard() -> None:
    """Correction 27: the canonical dump mode is NOT free to change.

    `mode='json'` serialises a `Decimal` to a *string*, which
    `_normalize_canonical_value` passes through un-normalised.  Two things break:
    `Decimal('0.700000')` stops hashing equal to the packaged float `0.7`, and —
    worse — `Decimal('NaN')` becomes the string `'NaN'`, so the finiteness check
    never fires and a non-finite numeric is **silently hashed**.

    The seven packaged v1 hash literals cannot catch this, because all seven are
    byte-identical under both modes.  This test is what pins the mode, so the
    swap cannot be re-derived as free.  `Decimal` is the shape these values take
    crossing the SQLAlchemy boundary, which is the case `canonical_payload`'s own
    docstring exists for.
    """
    definition = load_graph_v1_manifest().definitions[0]

    decimal_valued = definition.model_copy(
        update={
            "model": definition.model.model_copy(
                update={"temperature": Decimal("0.700000")}
            )
        }
    )
    temperature = decimal_valued.canonical_payload()["model"]["temperature"]
    assert temperature == 0.7
    assert isinstance(temperature, float), "a stringified Decimal would break normalisation"
    assert definition_content_hash(decimal_valued) == definition_content_hash(definition)

    for non_finite in (Decimal("NaN"), Decimal("Infinity")):
        broken = definition.model_copy(
            update={
                "model": definition.model.model_copy(update={"temperature": non_finite})
            }
        )
        with pytest.raises(ValueError, match="canonical numeric values must be finite"):
            definition_content_hash(broken)


def test_hashing_rejects_non_string_object_keys_inside_guidance() -> None:
    """Correction 29: the key half of the removed helper's fail-closed behaviour.

    Without this check `{1: "a"}` and `{"1": "a"}` hash identically, the persist
    path silently coerces `1` to `"1"`, and mixed keys fail only incidentally
    through `json.dumps(sort_keys=True)` raising a comparison `TypeError` with no
    domain meaning.  Two distinct semantic inputs must not share one content
    hash in a content-addressed identity system.
    """
    original = _definition_by_key(load_graph_v1_manifest(), "architect")

    def built(example: object) -> DefinitionContent:
        raw = original.model_dump(mode="python")
        raw["schema_overlay"] = {
            "field_overrides": {"message": {"examples": [example]}},
            "additional_optional_fields": (),
        }
        return DefinitionContent.model_validate(raw)

    for rejected in ({1: "a"}, {1: "a", "b": "c"}, {"nested": {2: "b"}}):
        with pytest.raises(TypeError, match="canonical object keys must be strings"):
            definition_content_hash(built(rejected))

    # The string-keyed sibling is unaffected, so no existing hash moves.
    assert definition_content_hash(built({"1": "a"})) == (
        "cfa22bd3da5ed2bbd7f6a04b28736599167f8126e856655190899d04df2b5ad8"
    )


def test_converged_overlay_defaults_two_fields_the_removed_carrier_required() -> None:
    """Correction 30: a disclosed relaxation, pinned rather than left latent.

    The removed manifest-local overlay declared `field_overrides` and
    `additional_optional_fields` with no defaults, so `schema_overlay: {}` raised
    two `missing` errors.  The converged carrier defaults both, so the same input
    now validates to an empty overlay.  Harmless while all seven v1 overlays are
    empty; Tasks 4 and 5 introduce the first non-empty ones, so it is recorded
    here instead of being discovered there.
    """
    original = _definition_by_key(load_graph_v1_manifest(), "architect")
    raw = original.model_dump(mode="python")

    relaxed = DefinitionContent.model_validate({**raw, "schema_overlay": {}})
    assert relaxed.schema_overlay.field_overrides == {}
    assert relaxed.schema_overlay.additional_optional_fields == ()
    # The relaxation cannot move a v1 hash: the default is the packaged value.
    assert definition_content_hash(relaxed) == definition_content_hash(original)

    # It is a defaults-only relaxation — unknown keys are still refused.
    with pytest.raises(ValidationError):
        DefinitionContent.model_validate(
            {**raw, "schema_overlay": {"unexpected_key": True}}
        )
