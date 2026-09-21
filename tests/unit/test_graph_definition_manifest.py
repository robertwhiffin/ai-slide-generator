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
from typing import Any

import pytest
from pydantic import ValidationError

from scripts.generate_graph_definition_manifest_v1 import (
    build_manifest_json,
    render_manifest_module,
)
from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON
from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
    AgentRuntime,
    CodeOwnedAgentDefinitionSource,
)
from src.services.graph_definition_manifest import (
    DefinitionContent,
    GraphV1Manifest,
    assembly_rules_for,
    definition_content_hash,
    load_graph_v1_manifest,
)

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


def _replay_literal_v1_rules(
    content: DefinitionContent,
    payload: dict[str, Any],
    design_system_active: bool,
) -> ReplayedAssembly:
    runtime = AgentRuntime.compatibility()
    current = CodeOwnedAgentDefinitionSource().resolve(content.agent_key)
    protected = runtime._protected_prompts.resolve(current.protected_prompt)
    protected_values = {
        "build_reviewer_deck_brief": protected.build_reviewer_deck_brief,
        "slide_frame_constraints": protected.slide_frame_constraints,
        "design_system_precedence": protected.design_system_precedence,
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


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
@pytest.mark.parametrize("design_system_active", [False, True])
def test_manifest_assembly_replays_exact_runtime_prompt(
    agent_key: str,
    design_system_active: bool,
):
    definition = CodeOwnedAgentDefinitionSource().resolve(agent_key)
    payload = (
        {"deck_brief": "Synthetic brief"}
        if agent_key == "build_reviewer"
        else {"synthetic": True}
    )
    runtime = AgentRuntime.compatibility()
    actual = runtime._assemble_prompt(
        definition,
        runtime._protected_prompts.resolve(definition.protected_prompt),
        payload,
        AgentAssemblyContext(design_system_active),
    )
    manifest_definition = _definition_by_key(load_graph_v1_manifest(), agent_key)
    replayed = _replay_literal_v1_rules(
        manifest_definition,
        payload,
        design_system_active,
    )
    assert replayed.prompt == actual
    assert replayed.terminal_binding == "langchain.with_structured_output"


@pytest.mark.parametrize("deck_brief", [None, "", "Synthetic brief"])
def test_build_reviewer_deck_brief_block_tracks_payload_truthiness(deck_brief: str | None):
    payload = {"deck_brief": deck_brief}
    content = _definition_by_key(load_graph_v1_manifest(), "build_reviewer")
    definition = CodeOwnedAgentDefinitionSource().resolve("build_reviewer")
    runtime = AgentRuntime.compatibility()
    actual = runtime._assemble_prompt(
        definition,
        runtime._protected_prompts.resolve(definition.protected_prompt),
        payload,
        AgentAssemblyContext(False),
    )
    assert _replay_literal_v1_rules(content, payload, False).prompt == actual


def test_non_build_reviewer_ignores_deck_brief_protected_block():
    payload = {"deck_brief": "Synthetic brief"}
    content = _definition_by_key(load_graph_v1_manifest(), "architect")
    definition = CodeOwnedAgentDefinitionSource().resolve("architect")
    runtime = AgentRuntime.compatibility()
    actual = runtime._assemble_prompt(
        definition,
        runtime._protected_prompts.resolve(definition.protected_prompt),
        payload,
        AgentAssemblyContext(False),
    )
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
