"""Exact response contract for the admin Agent Definition workbench."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from src.services.graph_definition_manifest import AgentKey, AssemblyCondition


class _AttributeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class WorkbenchModelResponse(_AttributeResponse):
    endpoint_name: str
    temperature: float
    max_tokens: int
    top_p: float


class SchemaOverlayResponse(_AttributeResponse):
    field_overrides: dict[str, object]
    additional_optional_fields: tuple[str, ...]


class AuthoredPromptBlockResponse(_AttributeResponse):
    kind: Literal["authored_prompt"]
    condition: Literal["always"]


class ProtectedBlockResponse(_AttributeResponse):
    kind: Literal["protected"]
    name: Literal[
        "build_reviewer_deck_brief",
        "slide_frame_constraints",
        "design_system_precedence",
    ]
    condition: AssemblyCondition


class PayloadJsonBlockResponse(_AttributeResponse):
    kind: Literal["payload_json"]
    condition: Literal["always"]
    indent: Literal[2]
    default: Literal["str"]


class StructuredOutputBindingBlockResponse(_AttributeResponse):
    kind: Literal["structured_output_binding"]
    condition: Literal["always"]
    binding: Literal["langchain.with_structured_output"]
    terminal: Literal[True]


AssemblyBlockResponse = Annotated[
    AuthoredPromptBlockResponse
    | ProtectedBlockResponse
    | PayloadJsonBlockResponse
    | StructuredOutputBindingBlockResponse,
    Field(discriminator="kind"),
]


class AssemblyRulesResponse(_AttributeResponse):
    format_version: Literal[1]
    separator: Literal["\n\n"]
    blocks: tuple[AssemblyBlockResponse, ...]


class ContentIdentityResponse(_AttributeResponse):
    version: int
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _content_field(name: str):
    """Accept the legacy flat shape or read the shared snapshot content record."""
    return Field(validation_alias=AliasChoices(name, AliasPath("content", name)))


class _DefinitionContentResponse(_AttributeResponse):
    """Flatten the shared snapshot content record onto the existing wire shape."""

    definition_version: int = _content_field("definition_version")
    prompt_text: str = _content_field("prompt_text")
    model: WorkbenchModelResponse = _content_field("model")
    schema_overlay: SchemaOverlayResponse = _content_field("schema_overlay")
    assembly_rules: AssemblyRulesResponse = _content_field("assembly_rules")
    protected_assembly: ContentIdentityResponse = _content_field("protected_assembly")
    schema_contract: ContentIdentityResponse = _content_field("schema_contract")


class _PublishedDefinitionIdentityResponse(_AttributeResponse):
    revision_id: int
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


# Pydantic collects multiple-base fields right-to-left.  Keep the identity base
# second so the serialized key order remains identical to the original wire contract.
class PublishedDefinitionResponse(
    _DefinitionContentResponse,
    _PublishedDefinitionIdentityResponse,
):
    """Published identity plus shared definition content."""


class _DraftDefinitionIdentityResponse(_AttributeResponse):
    base_revision_id: int
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftDefinitionResponse(
    _DefinitionContentResponse,
    _DraftDefinitionIdentityResponse,
):
    """Draft identity plus shared definition content."""


class ModelAgentNodeResponse(_AttributeResponse):
    agent_key: AgentKey
    display_name: str
    execution_kind: Literal["model"]
    editable: Literal[True]
    changed: bool
    published: PublishedDefinitionResponse
    draft: DraftDefinitionResponse
    read_only_reason: None


class DeterministicAgentNodeResponse(_AttributeResponse):
    agent_key: Literal["foreman"]
    display_name: Literal["Foreman"]
    execution_kind: Literal["deterministic"]
    editable: Literal[False]
    changed: Literal[False]
    published: None
    draft: None
    read_only_reason: str


AgentNodeResponse = Annotated[
    ModelAgentNodeResponse | DeterministicAgentNodeResponse,
    Field(discriminator="execution_kind"),
]


class ActiveReleaseResponse(_AttributeResponse):
    release_id: int
    version_number: int
    previous_release_id: int | None
    restored_from_release_id: int | None
    release_note: str
    published_by: str
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None


class DraftMetadataResponse(_AttributeResponse):
    draft_id: int
    base_release_id: int
    base_version_number: int
    lock_version: int
    updated_by: str
    updated_at: datetime


class GraphWorkbenchResponse(_AttributeResponse):
    active_release: ActiveReleaseResponse
    draft: DraftMetadataResponse
    nodes: tuple[AgentNodeResponse, ...]
