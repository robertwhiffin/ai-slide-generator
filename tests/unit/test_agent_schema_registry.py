from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, astuple, dataclass, fields, replace
from types import MappingProxyType
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import PydanticUndefined

from src.domain.skill_io import OUTPUT_SCHEMAS, ArchitectOutput
from src.services.agent_schema_registry import (
    MODEL_DRIVEN_AGENT_KEYS,
    SCHEMA_CONTRACT_BUNDLES,
    V1_SCHEMA_IDENTITIES,
    V2_SCHEMA_IDENTITIES,
    AgentOutputValidationError,
    AgentSchemaRegistry,
    SchemaContractMaterialChangedError,
    SchemaOverlayValidationError,
    upgrade_content_to_v2,
)
from src.services.agent_schema_types import (
    CanonicalFieldGuidance,
    SchemaContractIdentity,
    SchemaOverlay,
    SchemaValidationIssue,
)

EXPECTED_ROLES = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)

EXPECTED_V1_DIGESTS = {
    "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}

EXPECTED_V2_DIGESTS = {
    "architect": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}

EXPECTED_DESCRIPTOR_TEXT = {
    "architect": (
        "Concise assumptions or ambiguities that influenced the selected intent; "
        "never substitute for `message`, `deck_spec`, `data_request`, targets, or a "
        "design proposal.",
        "Assumed the request refers to the existing Q2 deck; no target slide numbers "
        "were supplied.",
    ),
    "data_analyst": (
        "Concise retrieval limitations, source disagreement, or interpretation assumptions; "
        "never replace `outcome`, `synthesis`, `sources`, `gap`, `reason`, or `tried_tools`.",
        "The two sources use different fiscal calendars; synthesis compares "
        "calendar-quarter totals.",
    ),
    "builder": (
        "Concise non-executable rendering/design trade-offs or unavailable inputs; never contain "
        "HTML, scripts, image IDs, or a substitute for canonical slide output.",
        "No supplied image IDs; used a text-and-chart composition.",
    ),
    "build_reviewer": (
        "Concise review-scope/evidence notes; never hide, replace, or add a finding "
        "outside canonical "
        "`findings`.",
        "Contrast was assessed against the resolved style tokens supplied in this invocation.",
    ),
    "fixer": (
        "Concise reason for a narrowly limited or declined attempted fix; never replace `changed` "
        "or `change_summary`.",
        "Did not alter the chart because the reported issue concerns only title overflow.",
    ),
    "fix_reviewer": (
        "Concise evidence about whether the original issue was resolved or a review limitation; "
        "never replace the canonical verdict/findings.",
        "Verified the original overflow against the corrected title container.",
    ),
    "deck_reviewer": (
        "Concise deck-level review scope/limitations; never replace deck findings or introduce "
        "slide-level findings.",
        "Narrative assessment used the supplied slide sequence; no presenter notes were available.",
    ),
}


def _issue(code: str, message: str, *path: str | int) -> SchemaValidationIssue:
    return SchemaValidationIssue(code=code, message=message, path=path)


def test_recursive_overlay_is_frozen_and_serializes_as_exact_json() -> None:
    overlay = SchemaOverlay.model_validate(
        {
            "field_overrides": {
                "message": {
                    "description": "  Keep intentional edge spaces.  ",
                    "examples": [
                        {"nested": [1, True, None, {"label": "value"}]},
                        "plain",
                    ],
                }
            },
            "additional_optional_fields": ["diagnostic_notes"],
        }
    )

    guidance = overlay.field_overrides["message"]
    assert isinstance(overlay.field_overrides, MappingProxyType)
    assert isinstance(guidance.examples, tuple)
    assert isinstance(guidance.examples[0], MappingProxyType)
    assert guidance.examples[0]["nested"] == (1, True, None, MappingProxyType({"label": "value"}))
    assert overlay.model_dump(mode="json") == {
        "field_overrides": {
            "message": {
                "description": "  Keep intentional edge spaces.  ",
                "examples": [
                    {"nested": [1, True, None, {"label": "value"}]},
                    "plain",
                ],
            }
        },
        "additional_optional_fields": ["diagnostic_notes"],
    }
    assert SchemaOverlay().model_dump(mode="json") == {
        "field_overrides": {},
        "additional_optional_fields": [],
    }
    with pytest.raises(TypeError):
        overlay.field_overrides["message"] = CanonicalFieldGuidance()  # type: ignore[index]
    protected = CanonicalFieldGuidance.model_validate({"type": {"nested": []}})
    with pytest.raises(TypeError):
        protected.__pydantic_extra__["type"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        protected.__pydantic_extra__["type"]["nested"] = ()  # type: ignore[index]
    with pytest.raises(ValidationError):
        SchemaOverlay.model_validate(
            {"field_overrides": {}, "additional_optional_fields": [], "identity": {}}
        )


def test_guidance_supplied_mutations_cannot_be_changed_through_model_fields_set() -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)
    overlay = SchemaOverlay.model_validate(
        {
            "field_overrides": {
                "message": {
                    "description": "Replacement description",
                    "examples": ["Replacement example"],
                }
            }
        }
    )
    guidance = overlay.field_overrides["message"]
    expected_dump = overlay.model_dump(mode="json")
    assert registry.validate_overlay("architect", identity, overlay) == ()
    expected_property = registry.compose("architect", identity, overlay).model.model_json_schema(
        mode="validation"
    )["properties"]["message"]

    with pytest.raises(ValidationError):
        guidance.description = "Changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        guidance.examples = ()  # type: ignore[misc]
    guidance._supplied_mutations = frozenset()
    guidance.__pydantic_private__ = {"_supplied_mutations": frozenset()}
    with pytest.raises(AttributeError):
        guidance._semantic_state_slot = object()
    with pytest.raises(FrozenInstanceError):
        guidance._semantic_state_slot.description = "injected"
    guidance.__dict__["_semantic_state_slot"] = object()
    assert overlay.model_dump(mode="json") == expected_dump
    guidance.model_fields_set.clear()

    assert overlay.model_dump(mode="json") == expected_dump
    assert registry.validate_overlay("architect", identity, overlay) == ()
    actual_property = registry.compose("architect", identity, overlay).model.model_json_schema(
        mode="validation"
    )["properties"]["message"]
    assert actual_property == expected_property
    assert actual_property["description"] == "Replacement description"
    assert actual_property["examples"] == ["Replacement example"]

    omitted = SchemaOverlay.model_validate({"field_overrides": {"message": {}}})
    omitted_guidance = omitted.field_overrides["message"]
    omitted_guidance._supplied_mutations = frozenset({"description"})
    omitted_guidance.__pydantic_private__ = {"_supplied_mutations": frozenset({"description"})}
    assert omitted.model_dump(mode="json")["field_overrides"]["message"] == {}
    omitted_guidance.__dict__["description"] = "injected"
    omitted_guidance.__dict__["examples"] = ("injected example",)
    assert omitted.model_dump(mode="json")["field_overrides"]["message"] == {}
    omitted_guidance.model_fields_set.add("description")
    assert omitted.model_dump(mode="json")["field_overrides"]["message"] == {}
    assert registry.validate_overlay("architect", identity, omitted) == ()


@pytest.mark.parametrize(
    "direct_dict_mutation",
    [
        "replace_with_undefined",
        "remove",
        "replace_with_other_values",
        "replace_entire_dict",
    ],
)
def test_guidance_semantics_ignore_direct_dict_mutation(
    direct_dict_mutation: str,
) -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)
    guidance = CanonicalFieldGuidance.model_validate(
        {"description": "Kept description", "examples": ["Kept example"]}
    )
    overlay = SchemaOverlay(field_overrides={"message": guidance})

    if direct_dict_mutation == "replace_with_undefined":
        guidance.__dict__["description"] = PydanticUndefined
        guidance.__dict__["examples"] = PydanticUndefined
        assert guidance.__dict__["description"] is PydanticUndefined
    elif direct_dict_mutation == "remove":
        guidance.__dict__.pop("description")
        guidance.__dict__.pop("examples")
        assert "description" not in guidance.__dict__
    elif direct_dict_mutation == "replace_with_other_values":
        guidance.__dict__["description"] = "Injected description"
        guidance.__dict__["examples"] = ("Injected example",)
        assert guidance.__dict__["description"] == "Injected description"
    else:
        guidance.__dict__ = {
            "description": "Injected description",
            "examples": ("Injected example",),
        }
        assert guidance.__dict__["description"] == "Injected description"

    assert overlay.model_dump(mode="json")["field_overrides"]["message"] == {
        "description": "Kept description",
        "examples": ["Kept example"],
    }
    assert registry.validate_overlay("architect", identity, overlay) == ()
    composed_property = registry.compose("architect", identity, overlay).model.model_json_schema(
        mode="validation"
    )["properties"]["message"]
    assert composed_property["description"] == "Kept description"
    assert composed_property["examples"] == ["Kept example"]


def test_guidance_model_copy_update_preserves_pydantic_and_omission_semantics() -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)
    original = CanonicalFieldGuidance.model_validate(
        {"description": "Original", "examples": ["Example"]}
    )

    copied = original.model_copy(update={"description": "Copied"})
    assert copied.model_dump(mode="json") == {
        "description": "Copied",
        "examples": ["Example"],
    }
    copied_overlay = SchemaOverlay(field_overrides={"message": copied})
    assert copied_overlay.model_dump(mode="json")["field_overrides"]["message"] == {
        "description": "Copied",
        "examples": ["Example"],
    }
    assert registry.validate_overlay("architect", identity, copied_overlay) == ()
    copied_property = registry.compose(
        "architect", identity, copied_overlay
    ).model.model_json_schema(mode="validation")["properties"]["message"]
    assert copied_property["description"] == "Copied"
    assert copied_property["examples"] == ["Example"]

    omitted = CanonicalFieldGuidance()
    explicit_null = omitted.model_copy(update={"description": None})
    explicit_null.__dict__["description"] = "injected"
    assert omitted.model_dump(mode="json") == {}
    assert explicit_null.model_dump(mode="json") == {"description": None}
    assert (
        SchemaOverlay(field_overrides={"message": omitted}).model_dump(mode="json")[
            "field_overrides"
        ]["message"]
        == {}
    )
    explicit_null_overlay = SchemaOverlay(field_overrides={"message": explicit_null})
    assert explicit_null_overlay.model_dump(mode="json")["field_overrides"]["message"] == {
        "description": None
    }
    assert registry.validate_overlay("architect", identity, explicit_null_overlay) == (
        _issue(
            "overlay_description_blank",
            "Description must not be blank.",
            "field_overrides",
            "message",
            "description",
        ),
    )


def test_guidance_shallow_copies_preserve_nested_identity_and_copy_field_set() -> None:
    original = CanonicalFieldGuidance.model_validate(
        {
            "description": "Original",
            "examples": [{"nested": ["example"]}],
            "forbidden": {"nested": ["extra"]},
        }
    )
    original.model_fields_set.add("synthetic")

    for copied in (original.model_copy(), copy.copy(original)):
        assert copied is not original
        assert copied.examples is original.examples
        assert copied.examples[0] is original.examples[0]
        assert copied.forbidden_properties() is not original.forbidden_properties()
        assert (
            copied.forbidden_properties()["forbidden"]
            is original.forbidden_properties()["forbidden"]
        )
        assert copied.model_fields_set == original.model_fields_set
        assert copied.model_fields_set is not original.model_fields_set


def test_guidance_deep_copies_detach_nested_values_and_copy_field_set() -> None:
    original = CanonicalFieldGuidance.model_validate(
        {
            "description": "Original",
            "examples": [{"nested": ["example"]}],
            "forbidden": {"nested": ["extra"]},
        }
    )
    original.model_fields_set.add("synthetic")

    for copied in (original.model_copy(deep=True), copy.deepcopy(original)):
        assert copied is not original
        assert copied.examples is not original.examples
        assert copied.examples[0] is not original.examples[0]
        assert copied.forbidden_properties() is not original.forbidden_properties()
        assert (
            copied.forbidden_properties()["forbidden"]
            is not original.forbidden_properties()["forbidden"]
        )
        assert copied.model_fields_set == original.model_fields_set
        assert copied.model_fields_set is not original.model_fields_set


def test_guidance_model_copy_update_is_trusted_and_semantically_protected() -> None:
    original = CanonicalFieldGuidance()
    invalid_examples = object()

    copied = original.model_copy(
        update={
            "description": 123,
            "examples": invalid_examples,
            "forbidden": 456,
        }
    )

    assert copied.description == 123
    assert copied.examples is invalid_examples
    assert copied.forbidden == 456
    assert copied.forbidden_properties() == {"forbidden": 456}
    assert copied.model_fields_set == {"description", "examples", "forbidden"}
    assert copied.serialized_mutations() == {
        "description": 123,
        "examples": invalid_examples,
        "forbidden": 456,
    }

    mutable_examples = [{"nested": ["Kept example"]}]
    copied_container = original.model_copy(update={"examples": mutable_examples})
    mutable_examples[0]["nested"][0] = "Injected example"
    assert copied_container.serialized_mutations() == {"examples": [{"nested": ["Kept example"]}]}
    assert original.serialized_mutations() == {}

    copied.__dict__ = {
        "description": "Injected description",
        "examples": ("Injected example",),
    }
    copied.__pydantic_extra__ = {"forbidden": "Injected extra"}
    copied.__pydantic_private__ = {"semantic_state": "Injected private state"}
    copied.model_fields_set.clear()

    assert copied.description == 123
    assert copied.examples is invalid_examples
    assert copied.forbidden_properties() == {"forbidden": 456}
    assert copied.serialized_mutations() == {
        "description": 123,
        "examples": invalid_examples,
        "forbidden": 456,
    }


def test_retained_identity_tables_and_bundle_order_are_frozen_literals() -> None:
    assert MODEL_DRIVEN_AGENT_KEYS == EXPECTED_ROLES
    assert tuple(V1_SCHEMA_IDENTITIES) == EXPECTED_ROLES
    assert tuple(V2_SCHEMA_IDENTITIES) == EXPECTED_ROLES
    assert tuple(SCHEMA_CONTRACT_BUNDLES) == tuple(
        (role, version) for role in EXPECTED_ROLES for version in (1, 2)
    )
    assert {role: item.digest for role, item in V1_SCHEMA_IDENTITIES.items()} == EXPECTED_V1_DIGESTS
    assert {role: item.digest for role, item in V2_SCHEMA_IDENTITIES.items()} == EXPECTED_V2_DIGESTS
    assert all(
        item.version == 1 and item.agent_key == role for role, item in V1_SCHEMA_IDENTITIES.items()
    )
    assert all(
        item.version == 2 and item.agent_key == role for role, item in V2_SCHEMA_IDENTITIES.items()
    )
    with pytest.raises(TypeError):
        V1_SCHEMA_IDENTITIES["architect"] = V1_SCHEMA_IDENTITIES["architect"]  # type: ignore[index]


def test_v1_catalogs_are_empty_and_v2_catalogs_have_exact_role_descriptors() -> None:
    for role in EXPECTED_ROLES:
        v1 = SCHEMA_CONTRACT_BUNDLES[(role, 1)]
        v2 = SCHEMA_CONTRACT_BUNDLES[(role, 2)]
        assert v1.canonical_model is OUTPUT_SCHEMAS[role]
        assert v1.optional_fields == ()
        assert len(v2.optional_fields) == 1
        descriptor = v2.optional_fields[0]
        assert descriptor.name == "diagnostic_notes"
        assert (descriptor.description, descriptor.example) == EXPECTED_DESCRIPTOR_TEXT[role]
        assert descriptor.max_items == 8
        assert descriptor.item_min_length == 1
        assert descriptor.item_max_length == 280
        assert descriptor.strip_whitespace is True
        with pytest.raises(FrozenInstanceError):
            descriptor.name = "speaker_notes"  # type: ignore[misc]


def test_registry_fails_closed_if_frozen_v2_bundle_material_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.services.agent_schema_registry as module

    changed = dict(module._V2_OPTIONAL_DESCRIPTORS)
    changed["architect"] = replace(changed["architect"], description="changed")
    monkeypatch.setattr(module, "_V2_OPTIONAL_DESCRIPTORS", MappingProxyType(changed))

    with pytest.raises(SchemaContractMaterialChangedError, match="architect"):
        AgentSchemaRegistry()


def test_identity_resolution_is_exact_and_mismatches_return_one_immutable_issue() -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)
    assert identity == V2_SCHEMA_IDENTITIES["architect"]

    unavailable = (
        replace(identity, digest="0" * 64),
        replace(identity, agent_key="builder"),
        replace(identity, version=999),
    )
    for wrong in unavailable:
        issues = registry.validate_overlay("architect", wrong, SchemaOverlay())
        assert issues == (
            _issue(
                "overlay_schema_contract_unavailable",
                "Schema contract bundle is unavailable.",
            ),
        )
        with pytest.raises(AttributeError):
            issues.append(issues[0])  # type: ignore[attr-defined]
        with pytest.raises(FrozenInstanceError):
            issues[0].code = "changed"  # type: ignore[misc]


def test_overlay_validation_reports_field_and_property_issues_in_request_order() -> None:
    registry = AgentSchemaRegistry()
    overlay = SchemaOverlay.model_validate(
        {
            "field_overrides": {
                "unknown": {"description": "fine"},
                "message": {
                    "examples": [],
                    "description": " \t",
                    "json_schema": {"type": "integer"},
                    "nested": {"protected": True},
                },
                "intent": {"examples": [object()]},
            },
            "additional_optional_fields": [],
        }
    )

    assert registry.validate_overlay(
        "architect", registry.identity_for("architect", 2), overlay
    ) == (
        _issue(
            "overlay_unknown_canonical_field",
            "Canonical field is not available for this agent.",
            "field_overrides",
            "unknown",
        ),
        _issue(
            "overlay_description_blank",
            "Description must not be blank.",
            "field_overrides",
            "message",
            "description",
        ),
        _issue(
            "overlay_examples_empty",
            "Examples must contain at least one item.",
            "field_overrides",
            "message",
            "examples",
        ),
        _issue(
            "overlay_guidance_property_forbidden",
            "Only description and examples are editable.",
            "field_overrides",
            "message",
            "json_schema",
        ),
        _issue(
            "overlay_guidance_property_forbidden",
            "Only description and examples are editable.",
            "field_overrides",
            "message",
            "nested",
        ),
        _issue(
            "overlay_examples_invalid_json",
            "Examples must contain JSON-compatible values.",
            "field_overrides",
            "intent",
            "examples",
        ),
    )


def test_overlay_validation_accepts_each_guidance_mutation_independently_and_together() -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)

    for raw in (
        {"field_overrides": {"message": {"description": "New description"}}},
        {"field_overrides": {"message": {"examples": ["A", {"json": True}]}}},
        {"field_overrides": {"message": {"description": "New description", "examples": ["A"]}}},
    ):
        assert (
            registry.validate_overlay("architect", identity, SchemaOverlay.model_validate(raw))
            == ()
        )


def test_optional_name_validation_has_exact_precedence_and_index_order() -> None:
    registry = AgentSchemaRegistry()
    identity = registry.identity_for("architect", 2)
    overlay = SchemaOverlay(
        additional_optional_fields=(
            " ",
            "diagnostic_notes",
            "diagnostic_notes",
            "message",
            "speaker_notes",
        )
    )

    assert registry.validate_overlay("architect", identity, overlay) == (
        _issue(
            "overlay_optional_field_blank",
            "Optional field name must not be blank.",
            "additional_optional_fields",
            0,
        ),
        _issue(
            "overlay_optional_field_duplicate",
            "Optional field names must be unique.",
            "additional_optional_fields",
            2,
        ),
        _issue(
            "overlay_optional_field_canonical_collision",
            "Optional field name collides with a canonical field.",
            "additional_optional_fields",
            3,
        ),
        _issue(
            "overlay_optional_field_ineligible",
            "Optional field is not available for this agent.",
            "additional_optional_fields",
            4,
        ),
    )


def test_v1_rejects_every_optional_selection_because_its_catalog_is_empty() -> None:
    registry = AgentSchemaRegistry()
    issues = registry.validate_overlay(
        "architect",
        registry.identity_for("architect", 1),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )
    assert issues == (
        _issue(
            "overlay_optional_field_ineligible",
            "Optional field is not available for this agent.",
            "additional_optional_fields",
            0,
        ),
    )


def test_compose_applies_guidance_and_builds_a_strict_dynamic_model() -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay.model_validate(
            {
                "field_overrides": {
                    "message": {"description": "Replacement", "examples": ["Example"]}
                },
                "additional_optional_fields": ["diagnostic_notes"],
            }
        ),
    )

    schema = composed.model.model_json_schema(mode="validation")
    assert composed.canonical_model is ArchitectOutput
    assert composed.declared_optional_names == ("diagnostic_notes",)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["message"]["description"] == "Replacement"
    assert schema["properties"]["message"]["examples"] == ["Example"]
    assert schema["properties"]["diagnostic_notes"]["default"] is None
    assert schema["properties"]["diagnostic_notes"]["anyOf"][0]["maxItems"] == 8
    with pytest.raises(ValidationError):
        composed.model.model_validate({"intent": "discuss", "message": "ok", "rogue": True})


@pytest.mark.parametrize("role", EXPECTED_ROLES)
def test_composed_diagnostic_notes_has_exact_role_metadata(role: str) -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        role,
        registry.identity_for(role, 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )

    optional_property = composed.model.model_json_schema(mode="validation")["properties"][
        "diagnostic_notes"
    ]
    expected_description, expected_example = EXPECTED_DESCRIPTOR_TEXT[role]
    assert optional_property["description"] == expected_description
    assert optional_property["examples"] == [[expected_example]]
    assert optional_property["default"] is None
    assert optional_property["anyOf"][0]["maxItems"] == 8


def test_compose_rejects_invalid_overlay_with_ordered_diagnostics() -> None:
    registry = AgentSchemaRegistry()
    with pytest.raises(SchemaOverlayValidationError) as raised:
        registry.compose(
            "architect",
            registry.identity_for("architect", 2),
            SchemaOverlay(additional_optional_fields=("speaker_notes",)),
        )
    assert raised.value.issues == (
        _issue(
            "overlay_optional_field_ineligible",
            "Optional field is not available for this agent.",
            "additional_optional_fields",
            0,
        ),
    )


def test_raw_keys_are_rejected_before_pydantic_projection() -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )

    with pytest.raises(AgentOutputValidationError) as raised:
        registry.validate_output(
            composed,
            {"intent": "discuss", "message": "ok", "speaker_notes": ["must reject"]},
        )
    assert raised.value.issues == (
        _issue(
            "output_undeclared_top_level_field",
            "Output contains an undeclared top-level field.",
            "speaker_notes",
        ),
    )


def test_canonical_and_optional_validation_fail_with_distinct_diagnostics() -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )

    with pytest.raises(AgentOutputValidationError) as canonical:
        registry.validate_output(composed, {"intent": "build", "message": "missing deck"})
    assert canonical.value.issues[0].code == "output_invalid_canonical_field"
    assert canonical.value.issues[0].path == ()

    with pytest.raises(AgentOutputValidationError) as optional:
        registry.validate_output(
            composed,
            {
                "intent": "discuss",
                "message": "ok",
                "diagnostic_notes": ["valid"] * 9,
            },
        )
    assert optional.value.issues == (
        _issue(
            "output_invalid_optional_field",
            "Output contains an invalid optional field.",
            "diagnostic_notes",
        ),
    )


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("x", ("x",)),
        (f"  {'x' * 280}  ", ("x" * 280,)),
    ],
)
def test_diagnostic_note_item_accepts_stripped_length_boundaries(
    note: str, expected: tuple[str, ...]
) -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )

    result = registry.validate_output(
        composed,
        {"intent": "discuss", "message": "ok", "diagnostic_notes": [note]},
    )
    assert result.additional_fields["diagnostic_notes"] == expected


@pytest.mark.parametrize("note", [" \t\n ", "x" * 281])
def test_diagnostic_note_item_rejects_invalid_stripped_length_boundaries(
    note: str,
) -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )

    with pytest.raises(AgentOutputValidationError) as raised:
        registry.validate_output(
            composed,
            {"intent": "discuss", "message": "ok", "diagnostic_notes": [note]},
        )
    assert raised.value.issues == (
        _issue(
            "output_invalid_optional_field",
            "Output contains an invalid optional field.",
            "diagnostic_notes",
        ),
    )


@pytest.mark.parametrize(
    ("optional_fragment", "expected"),
    [
        ({}, {}),
        ({"diagnostic_notes": None}, {"diagnostic_notes": None}),
        ({"diagnostic_notes": []}, {"diagnostic_notes": ()}),
        (
            {"diagnostic_notes": ["  stripped  "]},
            {"diagnostic_notes": ("stripped",)},
        ),
    ],
)
def test_output_retains_only_explicitly_supplied_selected_optional_values(
    optional_fragment: dict[str, Any], expected: dict[str, Any]
) -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(additional_optional_fields=("diagnostic_notes",)),
    )
    result = registry.validate_output(
        composed,
        {"intent": "discuss", "message": "ok", **optional_fragment},
    )

    assert type(result.canonical_output) is ArchitectOutput
    assert result.canonical_output.model_dump() == {
        "intent": "discuss",
        "message": "ok",
        "deck_spec": None,
        "data_request": None,
        "target_positions": [],
        "proposed_design_contract": None,
    }
    assert isinstance(result.additional_fields, MappingProxyType)
    assert dict(result.additional_fields) == expected
    with pytest.raises(TypeError):
        result.additional_fields["diagnostic_notes"] = []  # type: ignore[index]


def test_unselected_optional_default_is_never_projected() -> None:
    registry = AgentSchemaRegistry()
    composed = registry.compose(
        "architect",
        registry.identity_for("architect", 2),
        SchemaOverlay(),
    )
    result = registry.validate_output(composed, {"intent": "discuss", "message": "ok"})
    assert result.additional_fields == {}


def test_upgrade_content_to_v2_preserves_content_and_uses_server_owned_identity() -> None:
    class Content(BaseModel):
        model_config = ConfigDict(frozen=True)
        agent_key: str
        schema_contract: SchemaContractIdentity
        schema_overlay: SchemaOverlay
        prompt_text: str

    original = Content(
        agent_key="architect",
        schema_contract=V1_SCHEMA_IDENTITIES["architect"],
        schema_overlay=SchemaOverlay(),
        prompt_text="unchanged",
    )
    upgraded = upgrade_content_to_v2(original)

    assert upgraded is not original
    assert upgraded.agent_key == original.agent_key
    assert upgraded.prompt_text == original.prompt_text
    assert upgraded.schema_overlay == original.schema_overlay
    assert upgraded.schema_contract == V2_SCHEMA_IDENTITIES["architect"]


# ---------------------------------------------------------------------------
# Task 2 (#264): the registry's typed grammar is the one the storage carrier uses.
# Exact values are literals rather than imports (epic correction C-24).
# ---------------------------------------------------------------------------


def test_registry_overlay_grammar_is_the_storage_carriers_overlay_grammar() -> None:
    """There is one overlay type; the manifest re-exports it rather than redefining it."""
    import src.services.graph_definition_manifest as manifest_module

    assert manifest_module.SchemaOverlay is SchemaOverlay
    assert manifest_module.CanonicalFieldGuidance is CanonicalFieldGuidance
    assert (
        manifest_module.DefinitionContent.model_fields["schema_overlay"].annotation is SchemaOverlay
    )


def test_registry_resolves_identities_bridged_from_the_stored_content_identity() -> None:
    """The stored (version, digest) carrier resolves only for its own role."""
    from src.services.graph_definition_manifest import (
        ContentIdentity,
        load_graph_v1_manifest,
        schema_contract_identity,
    )

    registry = AgentSchemaRegistry()
    for definition in load_graph_v1_manifest().definitions:
        identity = schema_contract_identity(definition.agent_key, definition.schema_contract)
        assert (
            registry.validate_overlay(definition.agent_key, identity, definition.schema_overlay)
            == ()
        )

        # The same stored pair under a different role must not resolve.
        other = "builder" if definition.agent_key != "builder" else "architect"
        mismatched = schema_contract_identity(other, definition.schema_contract)
        assert [
            issue.code for issue in registry.validate_overlay(other, mismatched, SchemaOverlay())
        ] == ["overlay_schema_contract_unavailable"]

        # A stored version the registry does not publish must not resolve either.
        unpublished = schema_contract_identity(
            definition.agent_key,
            ContentIdentity(version=3, digest=definition.schema_contract.digest),
        )
        assert [
            issue.code
            for issue in registry.validate_overlay(
                definition.agent_key, unpublished, SchemaOverlay()
            )
        ] == ["overlay_schema_contract_unavailable"]


def test_upgrade_content_to_v2_keeps_the_manifest_identity_carrier_type() -> None:
    """The v2 upgrade writes server-owned values into the retained wire carrier."""
    from src.services.graph_definition_manifest import (
        ContentIdentity,
        definition_content_hash,
        load_graph_v1_manifest,
    )

    definition = next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == "deck_reviewer"
    )
    upgraded = upgrade_content_to_v2(definition)

    assert isinstance(upgraded.schema_contract, ContentIdentity)
    assert upgraded.schema_contract.model_dump() == {
        "version": 2,
        "digest": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
    }
    assert isinstance(upgraded.schema_overlay, SchemaOverlay)
    assert definition_content_hash(definition) == (
        "8c876db55cddbaa2f9015321117e36adb5b63fb7c47dbb067a432d04c30cf54e"
    )
    assert definition_content_hash(upgraded) != definition_content_hash(definition)
    # The #265 assembly identity is not coupled to the schema contract version.
    assert upgraded.protected_assembly.model_dump() == {
        "version": 1,
        "digest": "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852",
    }


def test_upgraded_content_round_trips_through_the_persistence_mapper() -> None:
    """A v2 schema contract survives the one landed row mapper unchanged.

    The mapper writes ``schema_overlay`` with ``mode='json'``, so the fresh value
    per call matters: each assertion re-reads from a newly built row rather than
    reusing one already-consumed mapping.
    """
    from src.services.graph_configuration_content import (
        definition_content_from_row,
        definition_content_values,
    )
    from src.services.graph_definition_manifest import (
        definition_content_hash,
        load_graph_v1_manifest,
    )

    definition = next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == "architect"
    )
    upgraded = upgrade_content_to_v2(definition).model_copy(
        update={
            "schema_overlay": SchemaOverlay(
                field_overrides={
                    "message": CanonicalFieldGuidance.model_validate(
                        {"description": "Say why.", "examples": [{"a": [1, 2]}]}
                    )
                },
                additional_optional_fields=("diagnostic_notes",),
            )
        }
    )

    class _Row:
        pass

    def fresh_row() -> _Row:
        row = _Row()
        for name, value in definition_content_values(upgraded).items():
            setattr(row, name, value)
        return row

    first = definition_content_from_row(fresh_row())
    second = definition_content_from_row(fresh_row())

    assert first is not second
    assert definition_content_values(upgraded)["schema_overlay"] == {
        "field_overrides": {"message": {"description": "Say why.", "examples": [{"a": [1, 2]}]}},
        "additional_optional_fields": ["diagnostic_notes"],
    }
    for restored in (first, second):
        assert isinstance(restored.schema_overlay, SchemaOverlay)
        guidance = restored.schema_overlay.field_overrides["message"]
        assert isinstance(guidance, CanonicalFieldGuidance)
        assert guidance.description == "Say why."
        assert guidance.mutation_is_supplied("examples") is True
        assert restored.schema_overlay.additional_optional_fields == ("diagnostic_notes",)
        assert restored.schema_contract.model_dump() == {
            "version": 2,
            "digest": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
        }
        assert definition_content_hash(restored) == definition_content_hash(upgraded)


# ---------------------------------------------------------------------------
# Task 3 (#264): one SchemaContractIdentity, and a carrier gate that is loud.
#
# Correction C-12's remaining half.  ``agent_runtime`` used to define a second
# frozen ``SchemaContractIdentity`` with the identical field triple, so the two
# registries produced identities that compared unequal while their reprs were
# byte-identical, and the carrier gate in ``upgrade_content_to_v2`` let such an
# identity fall through to the structural ``is_dataclass`` branch *silently*.
# Exact values are literals rather than imports (epic correction C-24).
# ---------------------------------------------------------------------------


def test_schema_contract_identity_is_defined_exactly_once_in_the_repository() -> None:
    """The public home is the only definition; other modules import it."""
    import pathlib
    import re

    import src.services.agent_runtime as runtime_module
    import src.services.agent_schema_types as types_module
    import src.services.graph_definition_manifest as manifest_module

    assert runtime_module.SchemaContractIdentity is types_module.SchemaContractIdentity
    assert manifest_module.SchemaContractIdentity is types_module.SchemaContractIdentity

    source_root = pathlib.Path(types_module.__file__).resolve().parent.parent
    definition = re.compile(r"^class SchemaContractIdentity[(:]", re.MULTILINE)
    definitions = sorted(
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if definition.search(path.read_text(encoding="utf-8"))
    )
    assert definitions == ["services/agent_schema_types.py"]


def test_runtime_and_registry_agree_on_identity_class_equality_and_isinstance() -> None:
    """The two registries must produce equal, mutually-isinstance identities."""
    from src.services.agent_runtime import _SchemaContractRegistry

    runtime_registry = _SchemaContractRegistry()
    registry = AgentSchemaRegistry()

    for role in EXPECTED_ROLES:
        runtime_identity = runtime_registry.identity_for(role)
        public_identity = registry.identity_for(role, 1)
        assert type(runtime_identity) is type(public_identity)
        assert isinstance(runtime_identity, SchemaContractIdentity)
        assert runtime_identity == public_identity
        assert runtime_identity.digest == EXPECTED_V1_DIGESTS[role]


def test_upgrade_rejects_a_shadow_identity_carrier_loudly_instead_of_replacing_it() -> None:
    """A second class with the identity's own field triple must not pass silently."""
    from src.services.agent_schema_registry import SchemaContractIdentityCarrierError

    @dataclass(frozen=True)
    class ShadowSchemaContractIdentity:
        agent_key: str
        version: int
        digest: str

    class Content(BaseModel):
        model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
        agent_key: str
        schema_contract: Any
        schema_overlay: SchemaOverlay

    shadow = ShadowSchemaContractIdentity(
        agent_key="architect",
        version=1,
        digest="a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    )
    # The defect this guards: the shadow is structurally indistinguishable, so
    # neither a field comparison nor a repr body can tell it from the real class.
    real = SchemaContractIdentity(
        agent_key="architect",
        version=1,
        digest="a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    )
    assert [item.name for item in fields(shadow)] == [item.name for item in fields(real)]
    assert astuple(shadow) == astuple(real)
    assert shadow != real
    assert not isinstance(shadow, SchemaContractIdentity)

    content = Content(
        agent_key="architect", schema_contract=shadow, schema_overlay=SchemaOverlay()
    )
    with pytest.raises(SchemaContractIdentityCarrierError) as raised:
        upgrade_content_to_v2(content)

    assert "ShadowSchemaContractIdentity" in str(raised.value)
    assert "agent_schema_types.SchemaContractIdentity" in str(raised.value)
    assert isinstance(raised.value, TypeError)


@pytest.mark.parametrize(
    "carrier",
    [None, "1:abc", 2, ("architect", 2, "abc"), {"version": 2, "digest": "abc"}],
)
def test_upgrade_rejects_an_unrecognised_identity_carrier_instead_of_substituting(
    carrier: Any,
) -> None:
    """The removed ``else`` branch silently discarded any unknown carrier."""
    from src.services.agent_schema_registry import SchemaContractIdentityCarrierError

    class Content(BaseModel):
        model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
        agent_key: str
        schema_contract: Any
        schema_overlay: SchemaOverlay

    content = Content(
        agent_key="architect", schema_contract=carrier, schema_overlay=SchemaOverlay()
    )
    with pytest.raises(SchemaContractIdentityCarrierError):
        upgrade_content_to_v2(content)


def test_upgrade_rejects_a_dataclass_carrier_that_cannot_hold_the_identity_values() -> None:
    """A structural dataclass carrier without the values fails loudly, not silently."""
    from src.services.agent_schema_registry import SchemaContractIdentityCarrierError

    @dataclass(frozen=True)
    class WrongFields:
        contract_version: int
        contract_digest: str

    class Content(BaseModel):
        model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
        agent_key: str
        schema_contract: Any
        schema_overlay: SchemaOverlay

    content = Content(
        agent_key="architect",
        schema_contract=WrongFields(contract_version=1, contract_digest="abc"),
        schema_overlay=SchemaOverlay(),
    )
    with pytest.raises(SchemaContractIdentityCarrierError):
        upgrade_content_to_v2(content)
