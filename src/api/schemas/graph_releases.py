"""Exact wire contract for Graph Release preview and publication (#269 Task 5).

The handlers live on the one admin router in ``src/api/routes/agent_definitions.py``
(Corrections 31/35).  Every model here forbids extra keys; codes are snake_case and
the client owns every display label.  Task 6's strict TypeScript parsers mirror
these models field for field.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from src.api.schemas.agent_definitions import (
    MAX_ROW_ID,
    ActiveReleaseResponse,
    DraftFieldErrorResponse,
    DraftMetadataResponse,
    DraftReadinessResponse,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, AgentKey

_LOWERCASE_SHA256 = r"^[0-9a-f]{64}$"
_RowId = Annotated[int, Field(ge=1, le=MAX_ROW_ID)]
_Sha256 = Annotated[str, Field(pattern=_LOWERCASE_SHA256)]

#: ``graph_configuration_publication.DIFF_FIELD_NAMES``, in order (a unit test
#: pins the two together).
DiffFieldName = Literal[
    "definition_version",
    "prompt_text",
    "model.endpoint_name",
    "model.temperature",
    "model.max_tokens",
    "model.top_p",
    "schema_overlay",
    "assembly_rules",
    "protected_assembly.version",
    "protected_assembly.digest",
    "schema_contract.version",
    "schema_contract.digest",
]
PublicationGapCodeWire = Literal["no_required_case", "no_eligible_approval"]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# --- GET /release-preview ----------------------------------------------------


class FieldDiffResponse(_StrictResponse):
    field: DiffFieldName
    published: JsonValue
    candidate: JsonValue


class ChangedDefinitionResponse(_StrictResponse):
    agent_key: AgentKey
    published_revision_id: _RowId
    published_content_hash: _Sha256
    candidate_hash: _Sha256
    field_diffs: Annotated[list[FieldDiffResponse], Field(min_length=1)]


class ReleasePreviewResponse(_StrictResponse):
    """Advisory: ``publishable`` is the service's one definition (Correction 22);
    the evidence gate inside publication decides."""

    draft: DraftMetadataResponse
    active_release: ActiveReleaseResponse
    next_version_number: Annotated[int, Field(ge=2)]
    changed: list[ChangedDefinitionResponse]
    readiness: DraftReadinessResponse
    validation_issues: list[DraftFieldErrorResponse]
    publishable: bool


# --- POST /releases ------------------------------------------------------------


class PublishReleaseRequest(BaseModel):
    """Exactly ``{"lock_version", "release_note"}``.

    Types only: the lock range and the note's blank/length rules are the
    service's (``_lock_version_issues``, ``_validate_publication_request``), so
    there is no second copy here (Corrections 10, 36).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    lock_version: int
    release_note: str


class PublishedMappingResponse(_StrictResponse):
    agent_definition_revision_id: _RowId
    content_hash: _Sha256
    reused: bool


class ReleaseEvidenceResponse(_StrictResponse):
    """One evidence link a release wrote.

    Widened for #270 (Correction 38): a rollback links ``historical_restore``
    evidence naming the release it came from.  Publication stays approval-only
    (``PublishReleaseSuccessResponse``'s validator).
    """

    agent_test_run_id: _RowId
    agent_key: AgentKey
    test_case_id: _RowId
    evidence_kind: Literal["approval", "historical_restore"]
    #: Non-null iff ``evidence_kind == "historical_restore"``.
    source_release_id: _RowId | None

    @model_validator(mode="after")
    def source_agrees_with_kind(self) -> ReleaseEvidenceResponse:
        if (self.evidence_kind == "historical_restore") != (
            self.source_release_id is not None
        ):
            raise ValueError(
                "source_release_id is set exactly for historical_restore evidence"
            )
        return self


class PublishReleaseSuccessResponse(_StrictResponse):
    """200 (ruling Q6): the new active release and the rebased draft."""

    release: ActiveReleaseResponse
    previous_release_id: _RowId
    changed_agents: Annotated[list[AgentKey], Field(min_length=1)]
    mappings: dict[AgentKey, PublishedMappingResponse]
    evidence: list[ReleaseEvidenceResponse]
    draft: DraftMetadataResponse

    @model_validator(mode="after")
    def require_exact_role_set(self) -> PublishReleaseSuccessResponse:
        if list(self.mappings) != list(GRAPH_V1_AGENT_KEYS):
            raise ValueError("a published release maps exactly the seven roles in order")
        if any(item.evidence_kind != "approval" for item in self.evidence):
            raise ValueError("a publication links only approval evidence")
        return self


class ReleaseIdentityResponse(_StrictResponse):
    release_id: _RowId
    version_number: Annotated[int, Field(ge=1)]


class StalePublicationResponse(_StrictResponse):
    code: Literal["stale_publication"]
    expected_lock_version: int
    current_lock_version: Annotated[int, Field(ge=0)]
    active_release: ReleaseIdentityResponse
    draft: DraftMetadataResponse


class NothingToPublishResponse(_StrictResponse):
    code: Literal["nothing_to_publish"]
    active_release: ReleaseIdentityResponse
    draft: DraftMetadataResponse


class PublicationGapResponse(_StrictResponse):
    agent_key: AgentKey
    #: ``null`` iff ``code == "no_required_case"`` (Correction 1).
    test_case_id: _RowId | None
    code: PublicationGapCodeWire

    @model_validator(mode="after")
    def case_id_agrees_with_code(self) -> PublicationGapResponse:
        if (self.code == "no_required_case") != (self.test_case_id is None):
            raise ValueError("test_case_id is null exactly for a no_required_case gap")
        return self


class PublicationNotReadyResponse(_StrictResponse):
    """409: the gate's locked gaps are authoritative; ``readiness`` is #268's
    informational body, computed before any write (Correction 32)."""

    code: Literal["publication_not_ready"]
    gaps: Annotated[list[PublicationGapResponse], Field(min_length=1)]
    readiness: DraftReadinessResponse


class PublicationValidationErrorResponse(_StrictResponse):
    code: Literal["invalid_publication"]
    errors: list[DraftFieldErrorResponse]
