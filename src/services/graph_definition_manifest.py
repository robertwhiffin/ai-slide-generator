"""Typed contract for the checked-in Graph Version 1 manifest.

The large generated snapshot is intentionally imported only by
``load_graph_v1_manifest``. Existing installations can therefore use the contract and
hash helpers without parsing every frozen prompt.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

AgentKey: TypeAlias = Literal[
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
]
GRAPH_V1_AGENT_KEYS: tuple[AgentKey, ...] = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)

AssemblyCondition: TypeAlias = Literal[
    "always",
    "design_system_active",
    "design_system_inactive",
    "payload_has_deck_brief",
]
_LOWERCASE_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelConfiguration(_FrozenModel):
    endpoint_name: str = Field(min_length=1)
    temperature: float | Decimal = Field(ge=0, le=1)
    max_tokens: PositiveInt
    top_p: float | Decimal = Field(ge=0, le=1)


class SchemaOverlay(_FrozenModel):
    field_overrides: dict[str, object]
    additional_optional_fields: tuple[str, ...]


class AuthoredPromptBlock(_FrozenModel):
    kind: Literal["authored_prompt"]
    condition: Literal["always"]


class ProtectedBlock(_FrozenModel):
    kind: Literal["protected"]
    name: Literal[
        "build_reviewer_deck_brief",
        "slide_frame_constraints",
        "design_system_precedence",
    ]
    condition: AssemblyCondition

    @model_validator(mode="after")
    def validate_name_condition_pair(self) -> ProtectedBlock:
        expected = {
            "build_reviewer_deck_brief": "payload_has_deck_brief",
            "slide_frame_constraints": "design_system_inactive",
            "design_system_precedence": "design_system_active",
        }[self.name]
        if self.condition != expected:
            raise ValueError(
                f"protected block {self.name!r} requires condition {expected!r}"
            )
        return self


class PayloadJsonBlock(_FrozenModel):
    kind: Literal["payload_json"]
    condition: Literal["always"]
    indent: Literal[2]
    default: Literal["str"]


class StructuredOutputBindingBlock(_FrozenModel):
    kind: Literal["structured_output_binding"]
    condition: Literal["always"]
    binding: Literal["langchain.with_structured_output"]
    terminal: Literal[True]


AssemblyBlock: TypeAlias = Annotated[
    AuthoredPromptBlock
    | ProtectedBlock
    | PayloadJsonBlock
    | StructuredOutputBindingBlock,
    Field(discriminator="kind"),
]


class AssemblyRules(_FrozenModel):
    format_version: Literal[1]
    separator: Literal["\n\n"]
    blocks: tuple[AssemblyBlock, ...]


class ContentIdentity(_FrozenModel):
    version: PositiveInt
    digest: str = Field(pattern=_LOWERCASE_SHA256_PATTERN)


def assembly_rules_for(agent_key: str) -> dict[str, object]:
    """Return the exact static v1 assembly description for one editable role."""
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        raise ValueError(
            f"Unknown model-driven agent key {agent_key!r}; "
            f"expected one of {list(GRAPH_V1_AGENT_KEYS)!r}"
        )

    blocks: list[dict[str, object]] = [
        {"kind": "authored_prompt", "condition": "always"},
    ]
    if agent_key == "build_reviewer":
        blocks.append(
            {
                "kind": "protected",
                "name": "build_reviewer_deck_brief",
                "condition": "payload_has_deck_brief",
            }
        )
    blocks.extend(
        [
            {
                "kind": "protected",
                "name": "slide_frame_constraints",
                "condition": "design_system_inactive",
            },
            {
                "kind": "protected",
                "name": "design_system_precedence",
                "condition": "design_system_active",
            },
            {
                "kind": "payload_json",
                "condition": "always",
                "indent": 2,
                "default": "str",
            },
            {
                "kind": "structured_output_binding",
                "condition": "always",
                "binding": "langchain.with_structured_output",
                "terminal": True,
            },
        ]
    )
    return {
        "format_version": 1,
        "separator": "\n\n",
        "blocks": blocks,
    }


class DefinitionContent(_FrozenModel):
    agent_key: AgentKey
    definition_version: PositiveInt
    prompt_text: str = Field(min_length=1)
    model: ModelConfiguration
    schema_overlay: SchemaOverlay
    assembly_rules: AssemblyRules
    protected_assembly: ContentIdentity
    schema_contract: ContentIdentity

    @model_validator(mode="after")
    def validate_role_assembly(self) -> DefinitionContent:
        expected = AssemblyRules.model_validate(assembly_rules_for(self.agent_key))
        if self.assembly_rules != expected:
            raise ValueError(
                f"assembly rules for {self.agent_key!r} do not match Graph Version 1"
            )
        return self

    def canonical_payload(self) -> dict[str, object]:
        """Return semantic content normalized for stable canonical JSON hashing.

        Numeric values cross the JSON/SQLAlchemy boundary as ``float``/``Decimal``.
        Both are first reduced through their shortest decimal value and returned as a
        JSON number, so ``0.7`` and ``Decimal('0.700000')`` hash identically.
        """
        dumped = self.model_dump(mode="python")
        normalized = _normalize_canonical_value(dumped)
        assert isinstance(normalized, dict)
        return normalized


class GraphV1Manifest(_FrozenModel):
    manifest_version: Literal[1]
    definitions: tuple[DefinitionContent, ...]

    @model_validator(mode="after")
    def assert_complete_role_set(self) -> GraphV1Manifest:
        actual = tuple(item.agent_key for item in self.definitions)
        if actual != GRAPH_V1_AGENT_KEYS:
            raise ValueError(
                "Graph Version 1 definitions must contain the exact ordered role set: "
                f"expected {GRAPH_V1_AGENT_KEYS!r}, received {actual!r}"
            )
        return self

    def assert_complete(self, expected_keys: tuple[str, ...]) -> None:
        actual = tuple(item.agent_key for item in self.definitions)
        if actual != expected_keys:
            raise ValueError(
                "Graph Version 1 definitions do not match expected keys: "
                f"expected {expected_keys!r}, received {actual!r}"
            )


def _normalize_canonical_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _normalize_canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_canonical_value(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical numeric values must be finite")
        return float(value.normalize())
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical numeric values must be finite")
        return float(Decimal(str(value)).normalize())
    raise TypeError(f"unsupported canonical value {value!r}")


def definition_content_hash(content: DefinitionContent) -> str:
    payload = content.canonical_payload()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def load_graph_v1_manifest() -> GraphV1Manifest:
    from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON

    manifest = GraphV1Manifest.model_validate_json(GRAPH_VERSION_1_MANIFEST_JSON)
    manifest.assert_complete(GRAPH_V1_AGENT_KEYS)
    return manifest
