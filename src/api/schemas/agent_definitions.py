"""Exact response contract for the admin Agent Definition workbench."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    AssemblyCondition,
    CustomAnchor,
    DefinitionContent,
)
from src.services.prompt_assembler import PromptAssembler

_LOWERCASE_SHA256 = r"^[0-9a-f]{64}$"
_PROTECTED_STAGE_VIEW_ASSEMBLER = PromptAssembler()


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


class AssemblyRulesV1Response(_AttributeResponse):
    format_version: Literal[1]
    separator: Literal["\n\n"]
    blocks: tuple[AssemblyBlockResponse, ...]


class CustomTextBlockResponse(_AttributeResponse):
    kind: Literal["custom_text"]
    block_id: UUID
    anchor: CustomAnchor
    condition: AssemblyCondition
    text: str


class AssemblyRulesV2Response(_AttributeResponse):
    format_version: Literal[2]
    custom_blocks: tuple[CustomTextBlockResponse, ...]


AssemblyRulesResponse = Annotated[
    AssemblyRulesV1Response | AssemblyRulesV2Response,
    Field(discriminator="format_version"),
]


class ProtectedStageViewResponse(_AttributeResponse):
    """One locked, server-derived protected stage row; never a request field."""

    stage_id: str
    label: str
    condition: AssemblyCondition
    locked: Literal[True]
    display_text: str
    bundle_version: int
    bundle_digest: str = Field(pattern=_LOWERCASE_SHA256)
    legal_adjacent_custom_anchors: tuple[CustomAnchor, ...]


class ContentIdentityResponse(_AttributeResponse):
    version: int
    digest: str = Field(pattern=_LOWERCASE_SHA256)


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
    protected_stage_view: tuple[ProtectedStageViewResponse, ...] = Field(
        validation_alias=AliasChoices("protected_stage_view", "content")
    )

    @field_validator("protected_stage_view", mode="before")
    @classmethod
    def derive_protected_stage_view(cls, value: object) -> object:
        """Read the locked protected view from the assembler, never from a client."""
        if isinstance(value, DefinitionContent):
            return _PROTECTED_STAGE_VIEW_ASSEMBLER.protected_stage_view(
                agent_key=value.agent_key,
                identity=value.protected_assembly,
            )
        return value


class _PublishedDefinitionIdentityResponse(_AttributeResponse):
    revision_id: int
    content_hash: str = Field(pattern=_LOWERCASE_SHA256)


# Pydantic collects multiple-base fields right-to-left.  Keep the identity base
# second so the serialized key order remains identical to the original wire contract.
class PublishedDefinitionResponse(
    _DefinitionContentResponse,
    _PublishedDefinitionIdentityResponse,
):
    """Published identity plus shared definition content."""


class _DraftDefinitionIdentityResponse(_AttributeResponse):
    base_revision_id: int
    candidate_hash: str = Field(pattern=_LOWERCASE_SHA256)


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


class _StrictDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EditableModelDraftModelRequest(_StrictDraftRequest):
    endpoint_name: str
    temperature: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    max_tokens: Annotated[int, Field(gt=0)]
    top_p: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @field_validator("endpoint_name", mode="after")
    @classmethod
    def endpoint_name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Endpoint name must not be blank.")
        return value


class CustomTextBlockRequest(_StrictDraftRequest):
    kind: Literal["custom_text"]
    block_id: Annotated[UUID, Field(strict=False)]
    anchor: CustomAnchor
    condition: AssemblyCondition
    text: str


class EditableAssemblyRulesRequest(_StrictDraftRequest):
    format_version: Literal[2]
    custom_blocks: list[CustomTextBlockRequest]


class EditableModelDraftRequest(_StrictDraftRequest):
    prompt_text: str
    model: EditableModelDraftModelRequest
    assembly_rules: EditableAssemblyRulesRequest | None = None

    @field_validator("prompt_text", mode="after")
    @classmethod
    def prompt_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt text must not be blank.")
        return value


class DraftSaveRequest(_StrictDraftRequest):
    lock_version: Annotated[int, Field(ge=0)]
    candidate: EditableModelDraftRequest


class DraftLockRequest(_StrictDraftRequest):
    """The only accepted body for the upgrade and legacy-source POST routes."""

    lock_version: Annotated[int, Field(ge=0)]


class DraftSaveSuccessResponse(_AttributeResponse):
    draft: DraftMetadataResponse
    definition: DraftDefinitionResponse
    changed: bool


class DraftFieldErrorResponse(BaseModel):
    field: str
    code: str
    message: str


class DraftValidationErrorResponse(BaseModel):
    code: Literal["invalid_draft"]
    errors: list[DraftFieldErrorResponse]


class DraftSaveConflictServerResponse(BaseModel):
    draft: DraftMetadataResponse
    definitions: dict[AgentKey, DraftDefinitionResponse]

    @model_validator(mode="after")
    def require_exact_role_set(self) -> "DraftSaveConflictServerResponse":
        if set(self.definitions) != set(GRAPH_V1_AGENT_KEYS):
            raise ValueError("conflict server definitions must contain all seven roles")
        return self


class DraftSaveConflictResponse(BaseModel):
    code: Literal["stale_draft"]
    expected_lock_version: int
    current_lock_version: int
    #: An ordinary save echoes its submitted candidate; upgrade and legacy-source
    #: recovery carry no candidate at all.
    client_candidate: EditableModelDraftRequest | None
    server: DraftSaveConflictServerResponse


class LegacyPromptSourceRecordResponse(_AttributeResponse):
    prompt_text: str
    revision_id: int
    content_hash: str = Field(pattern=_LOWERCASE_SHA256)


class LegacyPromptSourceResponse(_AttributeResponse):
    draft: DraftMetadataResponse
    agent_key: AgentKey
    lock_version: int
    source: LegacyPromptSourceRecordResponse
