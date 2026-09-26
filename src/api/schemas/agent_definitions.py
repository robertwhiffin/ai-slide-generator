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

from src.services.agent_schema_registry import (
    SCHEMA_CONTRACT_BUNDLES,
    optional_field_descriptor_material,
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


def _json_schema_type_label(node: dict[str, object]) -> str:
    """A compact display label for one JSON-schema node, e.g. ``array<string> | null``."""
    reference = node.get("$ref")
    if isinstance(reference, str):
        return reference.rsplit("/", 1)[-1]
    members = node.get("anyOf")
    if isinstance(members, list):
        return " | ".join(_json_schema_type_label(member) for member in members)
    declared = node.get("type")
    if declared == "array":
        items = node.get("items")
        return f"array<{_json_schema_type_label(items)}>" if isinstance(items, dict) else "array"
    if isinstance(declared, str):
        return declared
    return "any"


def _canonical_field_material(model: type[BaseModel]) -> tuple[dict[str, object], ...]:
    """Read-only display data for one code-owned canonical output model.

    Derived on every read from the canonical Pydantic model the registry bundle already
    holds; it is not part of any bundle digest, content hash, or stored record.  Each
    entry carries ``name``, ``type``, ``required`` and ``enum``, and ``default`` only
    when the field is optional, in model field order.
    """
    properties = model.model_json_schema(mode="validation")["properties"]
    material: list[dict[str, object]] = []
    for name, field in model.model_fields.items():
        node = properties[name]
        enum = node.get("enum")
        entry: dict[str, object] = {
            "name": name,
            "type": _json_schema_type_label(node),
            "required": field.is_required(),
            "enum": list(enum) if isinstance(enum, list) else None,
        }
        if not field.is_required():
            entry["default"] = node.get("default")
        material.append(entry)
    return tuple(material)


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
    #: Read-only descriptor display data for the optional fields available for
    #: this schema contract version.  Empty for v1; one entry for v2.  Never a
    #: request field — the client may display it and select from it, but the
    #: server computes it from the registry; it is never accepted from the wire.
    selectable_optional_fields: tuple[dict[str, object], ...] = Field(
        validation_alias=AliasChoices("selectable_optional_fields", "content"),
        default=(),
    )
    #: Read-only display data for the role's code-owned canonical output fields:
    #: name, type, required, enum and (for optional fields) default.  Never a request
    #: field and never stored; derived from the registry bundle's canonical model.
    canonical_fields: tuple[dict[str, object], ...] = Field(
        validation_alias=AliasChoices("canonical_fields", "content"),
        default=(),
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

    @field_validator("selectable_optional_fields", mode="before")
    @classmethod
    def derive_selectable_optional_fields(cls, value: object) -> object:
        """Read the registry's descriptor list for the stored schema contract version."""
        if isinstance(value, DefinitionContent):
            bundle = SCHEMA_CONTRACT_BUNDLES.get(
                (value.agent_key, value.schema_contract.version)
            )
            if bundle is None:
                return ()
            return tuple(optional_field_descriptor_material(d) for d in bundle.optional_fields)
        return value

    @field_validator("canonical_fields", mode="before")
    @classmethod
    def derive_canonical_fields(cls, value: object) -> object:
        """Read the canonical model's field display data for the stored contract."""
        if isinstance(value, DefinitionContent):
            bundle = SCHEMA_CONTRACT_BUNDLES.get(
                (value.agent_key, value.schema_contract.version)
            )
            if bundle is None:
                return ()
            return _canonical_field_material(bundle.canonical_model)
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


class EditableSchemaOverlayRequest(_StrictDraftRequest):
    """Editable overlay request.  Extra top-level keys are rejected via extra='forbid'.

    Inner ``field_overrides`` values are ``dict[str, object]`` so that extra guidance
    properties pass through to the domain validator, which reports them as the stable
    ``overlay_guidance_property_forbidden`` domain issue rather than leaking Pydantic's
    own implementation message.
    """

    field_overrides: dict[str, object] = Field(default_factory=dict)
    additional_optional_fields: list[str] = Field(default_factory=list)


class EditableModelDraftRequest(_StrictDraftRequest):
    prompt_text: str
    model: EditableModelDraftModelRequest
    assembly_rules: EditableAssemblyRulesRequest | None = None
    schema_overlay: EditableSchemaOverlayRequest | None = None

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


class SystemModelEndpointResponse(BaseModel):
    """One discovered foundation-model endpoint; display metadata only.

    A read-only response item: it carries no task, provider, ID, or request field,
    and the name is the exact endpoint name the catalog returned.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str | None
    description: str | None
    docs: str | None


class SystemModelDiscoveryResponse(BaseModel):
    """Successful model endpoint discovery; ``items`` may be empty."""

    model_config = ConfigDict(extra="forbid")

    items: list[SystemModelEndpointResponse]


class ModelEndpointCatalogErrorResponse(BaseModel):
    """The only documented discovery failures: 403 forbidden and 503 unavailable."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["catalog_forbidden", "catalog_unavailable"]
    message: str
    retryable: bool


class StructuredOutputProbeSuccessResponse(BaseModel):
    """The saved candidate bound and answered the code-owned probe schema.

    A strict sibling (correction 9): it approves nothing and carries only the
    identity of the exact saved candidate the probe ran against.
    """

    model_config = ConfigDict(extra="forbid")

    code: Literal["structured_output_probe_succeeded"]
    endpoint_name: str
    candidate_hash: str = Field(pattern=_LOWERCASE_SHA256)
    lock_version: int


class StructuredOutputProbeFailureResponse(BaseModel):
    """One sanitized probe failure: 422 unsupported, 403 forbidden, 503 failed."""

    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "unsupported_structured_output",
        "endpoint_probe_forbidden",
        "structured_output_probe_failed",
    ]
    message: str
    retryable: bool
    endpoint_name: str
    candidate_hash: str = Field(pattern=_LOWERCASE_SHA256)
    lock_version: int


# --- Agent Test Cases (#267) -------------------------------------------------
# Strict sibling DTOs: none of them extends a draft request or response type.


class TestCaseAssemblyContextRequest(_StrictDraftRequest):
    """Exactly the one field the runtime's assembler reads (C22)."""

    design_system_active: bool


class CreateTestCaseRequest(_StrictDraftRequest):
    #: A plain string so an unknown role reaches the service's ``unknown_agent``.
    agent_key: str
    name: str
    synthetic_payload: dict[str, object]
    assembly_context: TestCaseAssemblyContextRequest
    is_required: bool


class UpdateTestCaseRequest(_StrictDraftRequest):
    """A supersede body.  ``name`` may be echoed but never changed (C22)."""

    name: str | None = None
    synthetic_payload: dict[str, object]
    assembly_context: TestCaseAssemblyContextRequest
    is_required: bool


class TestCaseAssemblyContextResponse(_AttributeResponse):
    design_system_active: bool


class TestCaseResponse(_AttributeResponse):
    id: int
    agent_key: AgentKey
    name: str
    version: int
    is_active: bool
    is_required: bool
    synthetic_payload: dict[str, object]
    assembly_context: TestCaseAssemblyContextResponse
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    #: Display-only reminder that payloads must be synthetic (spec §16, P7).
    is_synthetic_data_warning: Literal[True] = True


class TestCaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TestCaseResponse]


class TestCaseValidationErrorResponse(BaseModel):
    """The ordered case 422 named by correction 9."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["invalid_test_case"]
    issues: list[DraftFieldErrorResponse]


class TestCaseConflictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["stale_test_case"]
    test_case_id: int
    message: str


# --- Agent Test Runs (#267 Task 5) -------------------------------------------
# Strict siblings again: the run bodies name only what the admin chooses — the
# case, and for a candidate the lock that pins the candidate on their screen.
# The endpoint, sampling values, prompt, payload and baseline are server-owned.

#: A stored row id: ``agent_test_case.id`` / ``agent_test_run.id`` are
#: ``Integer`` columns, so a larger value could never name a row and would be a
#: driver range error in PostgreSQL rather than a clean refusal.
MAX_ROW_ID = 2**31 - 1
_RowId = Annotated[int, Field(ge=1, le=MAX_ROW_ID)]


class CandidateTestRunRequest(_StrictDraftRequest):
    """``POST /draft/{agent_key}/test-runs``: exactly ``{test_case_id, lock_version}``."""

    test_case_id: _RowId
    lock_version: Annotated[int, Field(ge=0)]


class BaselineTestRunRequest(_StrictDraftRequest):
    """``POST /published/{agent_key}/test-runs``: exactly ``{test_case_id}``; no draft is read."""

    test_case_id: _RowId


class DeterministicCheckIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    field: str | None


class DeterministicCheckResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["output_contract", "execution"]
    passed: bool
    message: str | None
    issues: list[DeterministicCheckIssueResponse]


class TestRunEvidenceResponse(BaseModel):
    """One immutable ``agent_test_run`` row, as evidence (Phase A).

    Every field is the stored row, except ``synthetic_payload`` (the run's own
    immutable case version) and the two currency flags.  Those are computed
    when the run is written: an execute response carries booleans, and a later
    read returns ``null`` because nothing recomputes them (C8.5).  The four
    verdict keys are required and ``null`` until a verdict is recorded (#268
    C16): the client's parser is exact-key, so they are never omitted.  Release
    and revision ids are ``ge=1`` so no ``-1`` sentinel can ever serialize
    (Task 3 M-1).
    """

    model_config = ConfigDict(extra="forbid")

    run_id: _RowId
    run_kind: Literal["candidate", "published_baseline"]
    test_case_id: _RowId
    test_case_version: Annotated[int, Field(ge=1)]
    agent_key: AgentKey
    candidate_hash: str = Field(pattern=_LOWERCASE_SHA256)
    compared_release_id: _RowId
    compared_definition_revision_id: _RowId
    synthetic_payload: dict[str, object]
    model_payload: dict[str, object]
    assembled_prompt: str | None
    execution_status: Literal["completed", "model_error", "assembly_error", "incomplete"]
    error_detail: str | None
    deterministic_checks_passed: bool
    deterministic_check_results: list[DeterministicCheckResultResponse]
    candidate_raw_output: dict[str, object] | None
    candidate_structured_output: dict[str, object] | None
    baseline_raw_output: dict[str, object] | None
    baseline_structured_output: dict[str, object] | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    run_by: str
    run_at: datetime
    verdict: Literal["approved", "rejected"] | None
    verdict_reviewer: str | None
    verdict_at: datetime | None
    verdict_notes: str | None
    candidate_is_current: bool | None
    base_release_is_current: bool | None


class TestRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TestRunEvidenceResponse]


class TestRunUnavailableResponse(BaseModel):
    """503: the database failed before or after the model call; no run was written."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["test_run_unavailable"]
    message: str
    retryable: Literal[True]


# --- verdicts and readiness (#268 Task 3) ------------------------------------
# The verdict body names only the admin's choice and an optional note.  The
# reviewer is the authenticated principal and the time is the database clock,
# so neither is a body field (C15).  Choice, blank and length rules are the
# writer's (``record_verdict``), so they are reported in one ordered list.


class VerdictRequest(_StrictDraftRequest):
    """``POST /test-runs/{run_id}/verdict``: exactly ``{verdict, notes}``."""

    verdict: str
    notes: str | None


class VerdictValidationErrorResponse(BaseModel):
    """422: an invalid verdict body, in the ordered issue shape (C15)."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["invalid_verdict"]
    errors: list[DraftFieldErrorResponse]


class IneligibleForApprovalResponse(BaseModel):
    """422: the run cannot carry this verdict; nothing was written (C5, C15)."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["ineligible_for_approval"]
    reason: Literal["not_completed", "checks_failed"]
    message: str


class TestCaseReadinessResponse(BaseModel):
    """One active required case row of a role (C11, C17): snake_case codes only;
    the client owns the display labels."""

    __test__ = False
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    agent_key: AgentKey
    test_case_id: _RowId
    test_case_name: str
    test_case_version: Annotated[int, Field(ge=1)]
    status: Literal["needs_test", "test_failed", "awaiting_review", "approved"]
    blocking: bool
    run_id: _RowId | None
    run_verdict: Literal["approved", "rejected"] | None
    run_checks_passed: bool | None


class AgentReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    agent_key: AgentKey
    candidate_hash: str = Field(pattern=_LOWERCASE_SHA256)
    is_changed_from_base: bool
    ready: bool
    missing_required_case: bool
    cases: list[TestCaseReadinessResponse]


class DraftReadinessResponse(BaseModel):
    """``GET /readiness``: the draft's publication readiness (C10, C11, C17).

    Informational: #269's publication gate decides on its own locked read.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    draft_lock_version: Annotated[int, Field(ge=0)]
    base_release_id: _RowId
    all_ready: bool
    blocking_agents: list[AgentKey]
    agents: list[AgentReadinessResponse]
