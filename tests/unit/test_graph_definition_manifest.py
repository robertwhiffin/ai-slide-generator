from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from scripts.generate_graph_definition_manifest_v1 import (
    build_manifest_json,
    render_manifest_module,
)
from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW
from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON
from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
    CodeOwnedAgentDefinitionSource,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS
from src.services.graph_definition_manifest import (
    AssemblyRulesV1,
    AssemblyRulesV2,
    CustomTextBlock,
    DefinitionContent,
    GraphV1Manifest,
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


def test_packaged_v1_manifest_matches_exact_compatibility_definitions():
    manifest = load_graph_v1_manifest()
    assert tuple(item.agent_key for item in manifest.definitions) == MODEL_DRIVEN_AGENT_KEYS
    source = CodeOwnedAgentDefinitionSource()
    for item in manifest.definitions:
        current = source.resolve(item.agent_key)
        assert item.prompt_text == current.prompt_text
        assert item.definition_version == current.definition_version
        assert item.model.model_dump() == dataclasses.asdict(current.model_configuration)
        assert item.protected_assembly.model_dump() == {
            "version": current.protected_prompt.version,
            "digest": current.protected_prompt.digest,
        }
        assert current.schema_contract.agent_key == item.agent_key
        assert item.schema_contract.model_dump() == {
            "version": current.schema_contract.version,
            "digest": current.schema_contract.digest,
        }


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
    original = load_graph_v1_manifest().definitions[0]
    raw = original.model_dump(mode="python")
    raw["schema_overlay"]["field_overrides"] = {
        "outer": {"values": [{"enabled": True}]}
    }
    candidate = DefinitionContent.model_validate(raw)
    before_hash = definition_content_hash(candidate)
    overrides = cast(Any, candidate.schema_overlay.field_overrides)

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


def test_generator_output_is_deterministic_and_matches_packaged_snapshot():
    generated_json = build_manifest_json()
    assert generated_json == GRAPH_VERSION_1_MANIFEST_JSON
    expected_file = Path("src/services/agent_definition_manifest_v1.py").read_text()
    assert render_manifest_module(generated_json) == expected_file


def test_generated_python_literal_safely_round_trips_arbitrary_prompt_bytes(tmp_path: Path):
    json_text = json.dumps(
        {"prompt": "quotes ''' and \"\"\", slashes \\\\, unicode λ, newline\n"},
        ensure_ascii=False,
        indent=2,
    )
    module_path = tmp_path / "generated_probe.py"
    module_path.write_text(render_manifest_module(json_text))
    spec = importlib.util.spec_from_file_location("generated_probe", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.GRAPH_VERSION_1_MANIFEST_JSON == json_text


def test_generator_runs_via_documented_direct_script_invocation(tmp_path: Path):
    output_path = tmp_path / "agent_definition_manifest_v1.py"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_graph_definition_manifest_v1.py",
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output_path.read_text() == render_manifest_module(build_manifest_json())
