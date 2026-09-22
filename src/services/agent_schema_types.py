"""Pure types shared by schema-overlay persistence and runtime validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_serializer, model_validator

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]


def freeze_json_containers(value: object) -> object:
    """Recursively freeze containers while retaining invalid leaves for diagnostics."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json_containers(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json_containers(item) for item in value)
    return value


def thaw_json_containers(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_json_containers(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json_containers(item) for item in value]
    return value


def is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(is_json_value(item) for item in value)
    return False


class CanonicalFieldGuidance(BaseModel):
    """Requested documentation-only mutations for one canonical field.

    Extra properties are deliberately retained so the registry can return its stable,
    ordered domain diagnostic instead of leaking Pydantic's implementation message.
    """

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    description: str | None = None
    examples: tuple[object, ...] | None = None
    _supplied_mutations: frozenset[str] = PrivateAttr(default_factory=frozenset)

    @model_validator(mode="after")
    def freeze_recursive_values(self) -> CanonicalFieldGuidance:
        self._supplied_mutations = frozenset(
            name for name in ("description", "examples") if name in self.__pydantic_fields_set__
        )
        object.__setattr__(
            self,
            "__pydantic_fields_set__",
            frozenset(self.__pydantic_fields_set__),
        )
        if self.examples is not None:
            object.__setattr__(
                self,
                "examples",
                tuple(freeze_json_containers(item) for item in self.examples),
            )
        if self.__pydantic_extra__:
            object.__setattr__(
                self,
                "__pydantic_extra__",
                MappingProxyType(
                    {
                        key: freeze_json_containers(item)
                        for key, item in self.__pydantic_extra__.items()
                    }
                ),
            )
        return self

    def mutation_is_supplied(self, name: str) -> bool:
        return name in self._supplied_mutations

    def serialized_mutations(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.mutation_is_supplied("description"):
            result["description"] = self.description
        if self.mutation_is_supplied("examples"):
            result["examples"] = thaw_json_containers(self.examples)
        if self.__pydantic_extra__:
            result.update(
                {key: thaw_json_containers(item) for key, item in self.__pydantic_extra__.items()}
            )
        return result


class SchemaOverlay(BaseModel):
    """Frozen, serializable user-editable overlay material only."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    field_overrides: Mapping[str, CanonicalFieldGuidance] = Field(default_factory=dict)
    additional_optional_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def freeze_field_overrides(self) -> SchemaOverlay:
        object.__setattr__(
            self,
            "field_overrides",
            MappingProxyType(dict(self.field_overrides)),
        )
        return self

    @field_serializer("field_overrides")
    def serialize_field_overrides(
        self, value: Mapping[str, CanonicalFieldGuidance]
    ) -> dict[str, object]:
        return {name: guidance.serialized_mutations() for name, guidance in value.items()}


@dataclass(frozen=True)
class OptionalFieldDescriptor:
    name: str
    description: str
    example: str
    max_items: int = 8
    item_min_length: int = 1
    item_max_length: int = 280
    strip_whitespace: bool = True


@dataclass(frozen=True)
class SchemaContractIdentity:
    agent_key: str
    version: int
    digest: str


@dataclass(frozen=True)
class SchemaValidationIssue:
    code: str
    message: str
    path: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class ValidatedAgentOutput:
    canonical_output: BaseModel
    additional_fields: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        frozen = {
            name: cast(JsonValue, freeze_json_containers(value))
            for name, value in self.additional_fields.items()
        }
        object.__setattr__(self, "additional_fields", MappingProxyType(frozen))


@dataclass(frozen=True)
class ComposedAgentSchema:
    model: type[BaseModel]
    canonical_model: type[BaseModel]
    declared_optional_names: tuple[str, ...]


@dataclass(frozen=True)
class SchemaContractBundle:
    identity: SchemaContractIdentity
    canonical_model: type[BaseModel]
    optional_fields: tuple[OptionalFieldDescriptor, ...]
