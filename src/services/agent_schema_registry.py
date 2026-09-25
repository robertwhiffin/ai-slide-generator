"""Retained schema-contract bundles and safe, code-owned output overlays."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import textwrap
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from types import MappingProxyType
from typing import Annotated, Any, Protocol, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    create_model,
)

from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_schema_types import (
    ComposedAgentSchema,
    JsonValue,
    OptionalFieldDescriptor,
    SchemaContractBundle,
    SchemaContractIdentity,
    SchemaOverlay,
    SchemaValidationIssue,
    ValidatedAgentOutput,
    is_json_value,
    thaw_json_containers,
)

MODEL_DRIVEN_AGENT_KEYS = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)

_V1_DIGESTS = MappingProxyType(
    {
        "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
        "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
        "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
        "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
        "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
        "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
        "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
    }
)

_V2_DIGESTS = MappingProxyType(
    {
        "architect": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
        "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
        "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
        "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
        "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
        "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
        "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
    }
)

_DESCRIPTOR_TEXT = {
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

_V2_OPTIONAL_DESCRIPTORS = MappingProxyType(
    {
        role: OptionalFieldDescriptor(
            name="diagnostic_notes",
            description=_DESCRIPTOR_TEXT[role][0],
            example=_DESCRIPTOR_TEXT[role][1],
        )
        for role in MODEL_DRIVEN_AGENT_KEYS
    }
)

_OVERLAY_ISSUES = MappingProxyType(
    {
        "overlay_unknown_canonical_field": "Canonical field is not available for this agent.",
        "overlay_guidance_property_forbidden": "Only description and examples are editable.",
        "overlay_description_blank": "Description must not be blank.",
        "overlay_examples_empty": "Examples must contain at least one item.",
        "overlay_examples_invalid_json": "Examples must contain JSON-compatible values.",
        "overlay_optional_field_blank": "Optional field name must not be blank.",
        "overlay_optional_field_duplicate": "Optional field names must be unique.",
        "overlay_optional_field_canonical_collision": (
            "Optional field name collides with a canonical field."
        ),
        "overlay_optional_field_ineligible": "Optional field is not available for this agent.",
        "overlay_schema_contract_unavailable": "Schema contract bundle is unavailable.",
    }
)

_REGISTRY_GRAMMAR = {
    "overlay": {
        "field_overrides": {
            "allowed_properties": ["description", "examples"],
            "description": {"type": "string", "blank": "reject"},
            "examples": {
                "type": "array",
                "min_items": 1,
                "items": "recursive_json",
            },
        },
        "additional_optional_fields": {
            "type": "array",
            "item_type": "string",
            "blank": "reject",
            "duplicates": "reject_second_and_subsequent",
            "catalog": "closed_per_agent",
        },
    },
    "output": {
        "top_level_extra": "forbid",
        "raw_key_policy": "reject_undeclared_before_pydantic_projection",
        "canonical_projection": "canonical_names_only",
        "optional_projection": "selected_and_explicitly_supplied_only",
    },
    "validation_order": {
        "field_overrides": "request_insertion_order",
        "guidance_properties": ["description", "examples"],
        "additional_optional_fields": "tuple_index_order",
    },
    "overlay_issues": dict(_OVERLAY_ISSUES),
    "output_issue_codes": [
        "output_undeclared_top_level_field",
        "output_invalid_canonical_field",
        "output_invalid_optional_field",
    ],
}


def _canonical_digest(material: object) -> str:
    serialized = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _schema_configuration_material(schema: type[BaseModel]) -> list[dict[str, Any]]:
    configurations: dict[tuple[str, str], dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            model = node.get("cls")
            config = node.get("config")
            if (
                isinstance(model, type)
                and issubclass(model, BaseModel)
                and isinstance(config, dict)
            ):
                qualified_name = f"{model.__module__}.{model.__qualname__}"
                item = {"qualified_name": qualified_name, "config": config}
                configurations[(qualified_name, _canonical_digest(config))] = item
            for value in node.values():
                visit(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                visit(value)

    visit(schema.__pydantic_core_schema__)
    return [configurations[key] for key in sorted(configurations)]


def _schema_validator_material(schema: type[BaseModel]) -> list[dict[str, str]]:
    validators: dict[tuple[str, str, str], dict[str, str]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                visit(value)
            return
        if not callable(node) or isinstance(node, type):
            return
        function = getattr(node, "__func__", node)
        module = getattr(function, "__module__", "")
        if module != schema.__module__ and not module.startswith("src."):
            return
        qualified_name = getattr(function, "__qualname__", repr(function))
        try:
            source = textwrap.dedent(inspect.getsource(function)).strip()
        except (OSError, TypeError):
            return
        key = (module, qualified_name, source)
        validators[key] = {
            "module": module,
            "qualified_name": qualified_name,
            "source": source,
        }

    visit(schema.__pydantic_core_schema__)
    return [validators[key] for key in sorted(validators)]


def _schema_contract_material(agent_key: str, schema: type[BaseModel]) -> dict[str, object]:
    return {
        "agent_key": agent_key,
        "qualified_name": f"{schema.__module__}.{schema.__qualname__}",
        "json_schema": schema.model_json_schema(mode="validation"),
        "model_configurations": _schema_configuration_material(schema),
        "validators": _schema_validator_material(schema),
    }


def optional_field_descriptor_material(
    descriptor: OptionalFieldDescriptor,
) -> dict[str, object]:
    """The descriptor's code-owned material: hashed into v2 and shown by the wire.

    Public because the admin wire's display data is exactly this material; the v2
    digest reads the same function, so the two cannot drift apart.
    """
    return {
        "name": descriptor.name,
        "description": descriptor.description,
        "examples": [descriptor.example],
        "schema": {
            "type": ["array", "null"],
            "default": None,
            "max_items": descriptor.max_items,
            "items": {
                "type": "string",
                "strip_whitespace": descriptor.strip_whitespace,
                "min_length": descriptor.item_min_length,
                "max_length": descriptor.item_max_length,
            },
        },
    }


def _calculate_v2_digest(agent_key: str) -> str:
    material = {
        "canonical_v1": _schema_contract_material(agent_key, OUTPUT_SCHEMAS[agent_key]),
        "registry_grammar": _REGISTRY_GRAMMAR,
        "optional_field_descriptors": [
            optional_field_descriptor_material(_V2_OPTIONAL_DESCRIPTORS[agent_key])
        ],
    }
    return _canonical_digest(material)


V1_SCHEMA_IDENTITIES = MappingProxyType(
    {role: SchemaContractIdentity(role, 1, _V1_DIGESTS[role]) for role in MODEL_DRIVEN_AGENT_KEYS}
)
V2_SCHEMA_IDENTITIES = MappingProxyType(
    {role: SchemaContractIdentity(role, 2, _V2_DIGESTS[role]) for role in MODEL_DRIVEN_AGENT_KEYS}
)
SCHEMA_CONTRACT_BUNDLES = MappingProxyType(
    {
        (role, version): SchemaContractBundle(
            identity=(V1_SCHEMA_IDENTITIES if version == 1 else V2_SCHEMA_IDENTITIES)[role],
            canonical_model=OUTPUT_SCHEMAS[role],
            optional_fields=(() if version == 1 else (_V2_OPTIONAL_DESCRIPTORS[role],)),
        )
        for role in MODEL_DRIVEN_AGENT_KEYS
        for version in (1, 2)
    }
)


class SchemaContractMaterialChangedError(RuntimeError):
    """Frozen identity material changed without a corresponding literal update."""


class SchemaContractIdentityCarrierError(TypeError):
    """A schema-contract identity carrier is not one this registry recognises.

    The gate that raises this used to end in a silent ``else`` which replaced any
    unrecognised carrier with the server-owned identity, and a *second* class
    carrying ``SchemaContractIdentity``'s own field triple fell through to the
    structural dataclass branch without a word — the two reprs are byte-identical,
    so the divergence was invisible in a traceback.  Both are now loud.
    """


class SchemaOverlayValidationError(ValueError):
    def __init__(self, issues: tuple[SchemaValidationIssue, ...]):
        self.issues = issues
        super().__init__("Schema overlay validation failed.")


class AgentOutputValidationError(ValueError):
    def __init__(self, issues: tuple[SchemaValidationIssue, ...]):
        self.issues = issues
        super().__init__("Agent output validation failed.")


_DiagnosticItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=280),
]
_DiagnosticNotes = Annotated[list[_DiagnosticItem], Field(max_length=8)] | None
_DIAGNOSTIC_NOTES_ADAPTER = TypeAdapter(_DiagnosticNotes)


def _issue(code: str, *path: str | int) -> SchemaValidationIssue:
    return SchemaValidationIssue(code=code, message=_OVERLAY_ISSUES[code], path=path)


def _runtime_issue(code: str, message: str, *path: str | int) -> SchemaValidationIssue:
    return SchemaValidationIssue(code=code, message=message, path=path)


class AgentSchemaRegistry:
    """Resolve exact bundles, validate overlays, and project validated output."""

    def __init__(self) -> None:
        for role in MODEL_DRIVEN_AGENT_KEYS:
            actual_v1 = _canonical_digest(_schema_contract_material(role, OUTPUT_SCHEMAS[role]))
            if actual_v1 != _V1_DIGESTS[role]:
                raise SchemaContractMaterialChangedError(
                    f"Schema contract for {role!r} changed: expected v1 "
                    f"{_V1_DIGESTS[role]}, calculated {actual_v1}"
                )
            actual_v2 = _calculate_v2_digest(role)
            if actual_v2 != _V2_DIGESTS[role]:
                raise SchemaContractMaterialChangedError(
                    f"Schema contract for {role!r} changed: expected v2 "
                    f"{_V2_DIGESTS[role]}, calculated {actual_v2}"
                )

    def identity_for(self, agent_key: str, version: int) -> SchemaContractIdentity:
        return SCHEMA_CONTRACT_BUNDLES[(agent_key, version)].identity

    def _resolve(
        self, agent_key: str, identity: SchemaContractIdentity
    ) -> SchemaContractBundle | None:
        bundle = SCHEMA_CONTRACT_BUNDLES.get((agent_key, identity.version))
        if bundle is None or bundle.identity != identity:
            return None
        return bundle

    def validate_overlay(
        self,
        agent_key: str,
        identity: SchemaContractIdentity,
        overlay: SchemaOverlay,
    ) -> tuple[SchemaValidationIssue, ...]:
        bundle = self._resolve(agent_key, identity)
        if bundle is None:
            return (_issue("overlay_schema_contract_unavailable"),)

        issues: list[SchemaValidationIssue] = []
        canonical_names = bundle.canonical_model.model_fields
        # Schema contract v1's frozen digest material carries no overlay grammar,
        # and the runtime refuses any non-empty v1 overlay.  So under v1 no
        # canonical field is available for guidance, exactly as v1's optional
        # catalog is empty: writer, route and runtime then agree (#264 I1).
        guidance_names = canonical_names if identity.version >= 2 else {}
        for field_name, guidance in overlay.field_overrides.items():
            path = ("field_overrides", field_name)
            if field_name not in guidance_names:
                issues.append(_issue("overlay_unknown_canonical_field", *path))
                continue

            if guidance.mutation_is_supplied("description") and (
                guidance.description is None or not guidance.description.strip()
            ):
                issues.append(_issue("overlay_description_blank", *path, "description"))

            if guidance.mutation_is_supplied("examples"):
                if guidance.examples is None or len(guidance.examples) == 0:
                    issues.append(_issue("overlay_examples_empty", *path, "examples"))
                elif not all(is_json_value(item) for item in guidance.examples):
                    issues.append(_issue("overlay_examples_invalid_json", *path, "examples"))

            if guidance.forbidden_properties():
                for property_name in guidance.forbidden_properties():
                    issues.append(
                        _issue(
                            "overlay_guidance_property_forbidden",
                            *path,
                            property_name,
                        )
                    )

        eligible = {descriptor.name for descriptor in bundle.optional_fields}
        seen: set[str] = set()
        for index, optional_name in enumerate(overlay.additional_optional_fields):
            path = ("additional_optional_fields", index)
            if not optional_name.strip():
                issues.append(_issue("overlay_optional_field_blank", *path))
                continue
            if optional_name in seen:
                issues.append(_issue("overlay_optional_field_duplicate", *path))
                continue
            seen.add(optional_name)
            if optional_name in canonical_names:
                issues.append(_issue("overlay_optional_field_canonical_collision", *path))
            elif optional_name not in eligible:
                issues.append(_issue("overlay_optional_field_ineligible", *path))

        return tuple(issues)

    def compose(
        self,
        agent_key: str,
        identity: SchemaContractIdentity,
        overlay: SchemaOverlay,
    ) -> ComposedAgentSchema:
        issues = self.validate_overlay(agent_key, identity, overlay)
        if issues:
            raise SchemaOverlayValidationError(issues)
        bundle = cast(SchemaContractBundle, self._resolve(agent_key, identity))

        strict_config = dict(bundle.canonical_model.model_config)
        strict_config["extra"] = "forbid"
        strict_base = type(
            f"_{bundle.canonical_model.__name__}StrictOverlayBase",
            (bundle.canonical_model,),
            {"model_config": ConfigDict(**strict_config)},
        )

        field_definitions: dict[str, tuple[object, object]] = {}
        for field_name, guidance in overlay.field_overrides.items():
            original = bundle.canonical_model.model_fields[field_name]
            field_info = copy.copy(original)
            if guidance.mutation_is_supplied("description"):
                field_info.description = guidance.description
            if guidance.mutation_is_supplied("examples"):
                field_info.examples = cast(list[object], thaw_json_containers(guidance.examples))
            field_definitions[field_name] = (original.annotation, field_info)

        descriptor_by_name = {descriptor.name: descriptor for descriptor in bundle.optional_fields}
        for optional_name in overlay.additional_optional_fields:
            descriptor = descriptor_by_name[optional_name]
            field_definitions[optional_name] = (
                _DiagnosticNotes,
                Field(
                    default=None,
                    description=descriptor.description,
                    examples=[[descriptor.example]],
                ),
            )

        # The composed class keeps the canonical class name and docstring: the
        # adapter's structured-output call names the forced tool after the model
        # and describes it with the docstring, and the prompts say "Return an
        # <CanonicalOutput>".  So composition changes only the parameters (AC3's
        # additionalProperties: false plus any guidance and selection), never the
        # tool the model is asked to call (#264 I5).  No digest or content hash
        # reads the composed class; both are computed from the canonical model.
        composed_model = create_model(
            bundle.canonical_model.__name__,
            __base__=strict_base,
            __doc__=bundle.canonical_model.__doc__,
            **field_definitions,
        )
        return ComposedAgentSchema(
            model=composed_model,
            canonical_model=bundle.canonical_model,
            declared_optional_names=overlay.additional_optional_fields,
        )

    def validate_output(
        self,
        composed: ComposedAgentSchema,
        raw_output: Mapping[str, object],
    ) -> ValidatedAgentOutput:
        canonical_names = composed.canonical_model.model_fields
        declared_optional_names = set(composed.declared_optional_names)
        allowed_names = set(canonical_names) | declared_optional_names
        undeclared = [key for key in raw_output if key not in allowed_names]
        if undeclared:
            raise AgentOutputValidationError(
                tuple(
                    _runtime_issue(
                        "output_undeclared_top_level_field",
                        "Output contains an undeclared top-level field.",
                        key,
                    )
                    for key in undeclared
                )
            )

        canonical_raw = {name: raw_output[name] for name in canonical_names if name in raw_output}
        try:
            canonical_output = composed.canonical_model.model_validate(canonical_raw)
        except ValidationError as error:
            raise AgentOutputValidationError(
                (
                    _runtime_issue(
                        "output_invalid_canonical_field",
                        "Output contains an invalid canonical field.",
                    ),
                )
            ) from error

        additional: dict[str, JsonValue] = {}
        optional_issues: list[SchemaValidationIssue] = []
        for name in composed.declared_optional_names:
            if name not in raw_output:
                continue
            try:
                value = _DIAGNOSTIC_NOTES_ADAPTER.validate_python(raw_output[name])
            except ValidationError:
                optional_issues.append(
                    _runtime_issue(
                        "output_invalid_optional_field",
                        "Output contains an invalid optional field.",
                        name,
                    )
                )
            else:
                additional[name] = cast(JsonValue, value)
        if optional_issues:
            raise AgentOutputValidationError(tuple(optional_issues))

        return ValidatedAgentOutput(
            canonical_output=canonical_output,
            additional_fields=additional,
        )


#: The one registry this module's own functions use.  Constructing it here runs the
#: fail-closed frozen-digest check once, at import of this module, instead of
#: repeating all fourteen digests on every ``upgrade_content_to_v2`` call.  The
#: draft writer's own import-time instance (``graph_configuration_draft``) and the
#: runtime's per-construction instance are unchanged.
_MODULE_REGISTRY = AgentSchemaRegistry()

_CANONICAL_IDENTITY_FIELD_NAMES = frozenset(("agent_key", "version", "digest"))
_STRUCTURAL_IDENTITY_FIELD_NAMES = frozenset(("version", "digest"))


def _carrier_name(carrier: object) -> str:
    carrier_type = type(carrier)
    return f"{carrier_type.__module__}.{carrier_type.__qualname__}"


def _replacement_schema_contract_identity(
    existing: object,
    identity: SchemaContractIdentity,
) -> object:
    """Return the server-owned identity in the carrier's own retained type.

    Every branch here is a carrier this registry understands.  An unrecognised
    carrier raises rather than being silently replaced, and a class that merely
    *looks* like :class:`SchemaContractIdentity` is named and refused rather than
    being handled structurally, so a re-duplication of that class cannot pass as
    an anonymous dataclass again.
    """
    if isinstance(existing, SchemaContractIdentity):
        return identity
    if isinstance(existing, BaseModel):
        return type(existing).model_validate(
            {"version": identity.version, "digest": identity.digest}
        )
    if is_dataclass(existing) and not isinstance(existing, type):
        names = frozenset(field.name for field in fields(existing))
        if names == _CANONICAL_IDENTITY_FIELD_NAMES:
            raise SchemaContractIdentityCarrierError(
                f"{_carrier_name(existing)} duplicates SchemaContractIdentity's fields but "
                "is not that class; converge on "
                "src.services.agent_schema_types.SchemaContractIdentity instead of "
                "shadowing it."
            )
        if not _STRUCTURAL_IDENTITY_FIELD_NAMES <= names:
            raise SchemaContractIdentityCarrierError(
                f"{_carrier_name(existing)} cannot carry a schema contract identity: "
                f"expected fields {sorted(_STRUCTURAL_IDENTITY_FIELD_NAMES)}, "
                f"found {sorted(names)}."
            )
        return replace(existing, version=identity.version, digest=identity.digest)
    raise SchemaContractIdentityCarrierError(
        f"{_carrier_name(existing)} is not a recognised schema contract identity carrier; "
        "expected src.services.agent_schema_types.SchemaContractIdentity, a Pydantic "
        "carrier, or a dataclass carrying 'version' and 'digest'."
    )


class _UpgradeableContent(Protocol):
    agent_key: str
    schema_contract: object
    schema_overlay: object


ContentT = TypeVar("ContentT", bound=_UpgradeableContent)


def upgrade_content_to_v2(content: ContentT) -> ContentT:
    """Return a copy with the server-owned v2 identity and typed overlay.

    This intentionally targets a structural carrier. Task 2 can pass its concrete
    manifest model without making this registry import that persistence layer.
    """
    identity = _MODULE_REGISTRY.identity_for(content.agent_key, 2)
    replacement_identity = _replacement_schema_contract_identity(
        content.schema_contract, identity
    )

    existing_overlay = content.schema_overlay
    if isinstance(existing_overlay, SchemaOverlay):
        replacement_overlay = existing_overlay
    elif isinstance(existing_overlay, BaseModel):
        replacement_overlay = SchemaOverlay.model_validate(
            existing_overlay.model_dump(mode="python")
        )
    else:
        replacement_overlay = SchemaOverlay.model_validate(existing_overlay)

    updates = {
        "schema_contract": replacement_identity,
        "schema_overlay": replacement_overlay,
    }
    if isinstance(content, BaseModel):
        return cast(ContentT, content.model_copy(update=updates))
    if is_dataclass(content):
        return cast(ContentT, replace(content, **updates))
    copier = getattr(content, "with_schema_contract", None)
    if callable(copier):
        return cast(ContentT, copier(replacement_identity, replacement_overlay))
    raise TypeError("Content carrier cannot be upgraded immutably.")
