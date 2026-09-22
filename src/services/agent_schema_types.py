"""Pure types shared by schema-overlay persistence and runtime validation."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticUndefined

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]


@dataclass(frozen=True, slots=True)
class _CanonicalFieldGuidanceState:
    description: object
    examples: object
    extra_properties: Mapping[str, object]


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


def _deepcopy_frozen_containers(value: object, memo: dict[int, object]) -> object:
    """Deep-copy recursively frozen values without asking pickle to copy proxies."""
    value_id = id(value)
    if value_id in memo:
        return memo[value_id]
    if isinstance(value, MappingProxyType):
        copied = MappingProxyType(
            {
                _deepcopy_frozen_containers(key, memo): _deepcopy_frozen_containers(item, memo)
                for key, item in value.items()
            }
        )
        memo[value_id] = copied
        return copied
    if isinstance(value, dict):
        copied_dict: dict[object, object] = {}
        memo[value_id] = copied_dict
        copied_dict.update(
            {
                _deepcopy_frozen_containers(key, memo): _deepcopy_frozen_containers(item, memo)
                for key, item in value.items()
            }
        )
        return copied_dict
    if isinstance(value, list):
        copied_list: list[object] = []
        memo[value_id] = copied_list
        copied_list.extend(_deepcopy_frozen_containers(item, memo) for item in value)
        return copied_list
    if isinstance(value, tuple):
        copied_items = tuple(_deepcopy_frozen_containers(item, memo) for item in value)
        copied_tuple = (
            value
            if len(copied_items) == len(value)
            and all(copied is original for copied, original in zip(copied_items, value))
            else copied_items
        )
        memo[value_id] = copied_tuple
        return copied_tuple
    return copy.deepcopy(value, memo)


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

    __slots__ = ("_semantic_state_slot",)

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    description: str | None = Field(default_factory=lambda: cast(object, PydanticUndefined))
    examples: tuple[object, ...] | None = Field(
        default_factory=lambda: cast(object, PydanticUndefined)
    )

    @model_validator(mode="after")
    def freeze_recursive_values(self) -> CanonicalFieldGuidance:
        try:
            object.__getattribute__(self, "_semantic_state_slot")
        except AttributeError:
            pass
        else:
            return self

        field_values = object.__getattribute__(self, "__dict__")
        description = field_values.get("description", PydanticUndefined)
        examples = field_values.get("examples", PydanticUndefined)
        if examples is not PydanticUndefined and examples is not None:
            examples = tuple(freeze_json_containers(item) for item in examples)
            field_values["examples"] = examples

        extra_properties: Mapping[str, object] = MappingProxyType({})
        if self.__pydantic_extra__:
            extra_properties = MappingProxyType(
                {key: freeze_json_containers(item) for key, item in self.__pydantic_extra__.items()}
            )
            object.__setattr__(
                self,
                "__pydantic_extra__",
                extra_properties,
            )

        object.__setattr__(
            self,
            "_semantic_state_slot",
            _CanonicalFieldGuidanceState(
                description=description,
                examples=examples,
                extra_properties=extra_properties,
            ),
        )
        return self

    def __getattribute__(self, name: str) -> object:
        if name in {"description", "examples"}:
            try:
                state = object.__getattribute__(self, "_semantic_state_slot")
            except AttributeError:
                pass
            else:
                return getattr(state, name)
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_semantic_state_slot":
            raise AttributeError("Canonical guidance semantic state is immutable.")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name == "_semantic_state_slot":
            raise AttributeError("Canonical guidance semantic state is immutable.")
        super().__delattr__(name)

    def _semantic_state(self) -> _CanonicalFieldGuidanceState:
        return object.__getattribute__(self, "_semantic_state_slot")

    def mutation_is_supplied(self, name: str) -> bool:
        state = self._semantic_state()
        if name == "description":
            return state.description is not PydanticUndefined
        if name == "examples":
            return state.examples is not PydanticUndefined
        raise ValueError(f"Unknown canonical guidance mutation {name!r}")

    def forbidden_properties(self) -> Mapping[str, object]:
        return self._semantic_state().extra_properties

    def serialized_mutations(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.mutation_is_supplied("description"):
            result["description"] = self.description
        if self.mutation_is_supplied("examples"):
            result["examples"] = thaw_json_containers(self.examples)
        if self.forbidden_properties():
            result.update(
                {
                    key: thaw_json_containers(item)
                    for key, item in self.forbidden_properties().items()
                }
            )
        return result

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> CanonicalFieldGuidance:
        copied = self.__deepcopy__() if deep else self.__copy__()
        if update:
            state = copied._semantic_state()
            description = state.description
            examples = state.examples
            extra_properties = dict(state.extra_properties)
            for key, value in update.items():
                protected_value = freeze_json_containers(value)
                if key == "description":
                    description = protected_value
                    copied.__dict__[key] = protected_value
                elif key == "examples":
                    examples = protected_value
                    copied.__dict__[key] = protected_value
                else:
                    extra_properties[key] = protected_value

            protected_extras = MappingProxyType(extra_properties)
            object.__setattr__(copied, "__pydantic_extra__", protected_extras)
            object.__setattr__(
                copied,
                "_semantic_state_slot",
                _CanonicalFieldGuidanceState(
                    description=description,
                    examples=examples,
                    extra_properties=protected_extras,
                ),
            )
            copied.__pydantic_fields_set__.update(update)
        return copied

    def __copy__(self) -> CanonicalFieldGuidance:
        cls = type(self)
        copied = cls.__new__(cls)
        state = self._semantic_state()
        protected_extras = MappingProxyType(dict(state.extra_properties))
        field_values = copy.copy(self.__dict__)
        field_values["description"] = state.description
        field_values["examples"] = state.examples
        object.__setattr__(copied, "__dict__", field_values)
        object.__setattr__(copied, "__pydantic_extra__", protected_extras)
        object.__setattr__(
            copied, "__pydantic_fields_set__", copy.copy(self.__pydantic_fields_set__)
        )
        if not hasattr(self, "__pydantic_private__") or self.__pydantic_private__ is None:
            object.__setattr__(copied, "__pydantic_private__", None)
        else:
            object.__setattr__(
                copied,
                "__pydantic_private__",
                {
                    key: value
                    for key, value in self.__pydantic_private__.items()
                    if value is not PydanticUndefined
                },
            )
        object.__setattr__(
            copied,
            "_semantic_state_slot",
            _CanonicalFieldGuidanceState(
                description=state.description,
                examples=state.examples,
                extra_properties=protected_extras,
            ),
        )
        return copied

    def __deepcopy__(self, memo: dict[int, object] | None = None) -> CanonicalFieldGuidance:
        memo = {} if memo is None else memo
        cls = type(self)
        copied = cls.__new__(cls)
        memo[id(self)] = copied
        state = self._semantic_state()
        copied_description = _deepcopy_frozen_containers(state.description, memo)
        copied_examples = _deepcopy_frozen_containers(state.examples, memo)
        copied_extras = cast(
            Mapping[str, object],
            _deepcopy_frozen_containers(state.extra_properties, memo),
        )
        field_values = cast(dict[str, object], _deepcopy_frozen_containers(self.__dict__, memo))
        field_values["description"] = copied_description
        field_values["examples"] = copied_examples
        object.__setattr__(copied, "__dict__", field_values)
        object.__setattr__(copied, "__pydantic_extra__", copied_extras)
        object.__setattr__(
            copied, "__pydantic_fields_set__", copy.copy(self.__pydantic_fields_set__)
        )
        if not hasattr(self, "__pydantic_private__") or self.__pydantic_private__ is None:
            object.__setattr__(copied, "__pydantic_private__", None)
        else:
            object.__setattr__(
                copied,
                "__pydantic_private__",
                _deepcopy_frozen_containers(
                    {
                        key: value
                        for key, value in self.__pydantic_private__.items()
                        if value is not PydanticUndefined
                    },
                    memo,
                ),
            )
        object.__setattr__(
            copied,
            "_semantic_state_slot",
            _CanonicalFieldGuidanceState(
                description=copied_description,
                examples=copied_examples,
                extra_properties=copied_extras,
            ),
        )
        return copied

    @model_serializer(mode="plain")
    def serialize_guidance(self) -> dict[str, object]:
        return self.serialized_mutations()


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
