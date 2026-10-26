"""Exact wire contract for Graph Release history, comparison and rollback (#270 Task 6).

The handlers live on the one admin router in ``src/api/routes/agent_definitions.py``
(Correction 37).  Every model here forbids extra keys; codes are snake_case and the
client owns every display label.  Releases are addressed by ``version_number``; a
``Ref`` (``ReleaseIdentityResponse``) carries both the id and the version, which
differ in production (a rolled-back publication consumes an id).

Task 7's strict TypeScript parsers mirror these models field for field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from src.api.schemas.agent_definitions import (
    ActiveReleaseResponse,
    DraftFieldErrorResponse,
    DraftMetadataResponse,
)
from src.api.schemas.graph_releases import (
    DiffFieldName,
    PublishedMappingResponse,
    ReleaseEvidenceResponse,
    ReleaseIdentityResponse,
    _RowId,
    _Sha256,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, AgentKey

DraftEffectWire = Literal["reset", "kept", "unchanged"]
RollbackBlockWire = Literal["source_is_active", "matches_active", "incompatible"]
_VersionNumber = Annotated[int, Field(ge=1)]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


def _require_seven_in_order(keys: object, what: str) -> None:
    if list(keys) != list(GRAPH_V1_AGENT_KEYS):  # type: ignore[call-overload]
        raise ValueError(f"{what} must list exactly the seven roles in Graph order")


# --- GET /releases ----------------------------------------------------------------


class ReleaseHistoryEntryResponse(_StrictResponse):
    release_id: _RowId
    version_number: _VersionNumber
    is_active: bool
    release_note: str
    published_by: str
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None
    previous: ReleaseIdentityResponse | None
    restored_from: ReleaseIdentityResponse | None
    #: Later releases whose ``restored_from`` is this one, ascending by version.
    restored_by: list[ReleaseIdentityResponse]
    #: Roles whose revision differs from ``previous``'s, in Graph order; v1 lists all seven.
    changed_agents: Annotated[list[AgentKey], Field(min_length=1)]


class ReleaseHistoryListResponse(_StrictResponse):
    active_release: ReleaseIdentityResponse
    #: Newest first.
    releases: Annotated[list[ReleaseHistoryEntryResponse], Field(min_length=1)]


# --- GET /releases/{version_number} ------------------------------------------------


class ReleaseDefinitionResponse(_StrictResponse):
    agent_definition_revision_id: _RowId
    content_hash: _Sha256
    #: ``DefinitionContent.canonical_payload()``: the hashed semantic content.
    content: dict[str, JsonValue]


class ReleaseHistoryEvidenceResponse(_StrictResponse):
    """One candidate run linked to the release (C38 item 4: not the publish item)."""

    agent_test_run_id: _RowId
    agent_key: AgentKey
    test_case_id: _RowId
    test_case_version: Annotated[int, Field(ge=1)]
    evidence_kind: Literal["approval", "historical_restore"]
    #: Non-null iff ``evidence_kind == "historical_restore"``.
    source: ReleaseIdentityResponse | None
    verdict: Literal["approved", "rejected"] | None
    verdict_reviewer: str | None
    verdict_at: datetime | None
    execution_status: Literal["completed", "model_error", "assembly_error", "incomplete"]
    deterministic_checks_passed: bool
    run_at: datetime

    @model_validator(mode="after")
    def source_agrees_with_kind(self) -> ReleaseHistoryEvidenceResponse:
        if (self.evidence_kind == "historical_restore") != (self.source is not None):
            raise ValueError("source is set exactly for historical_restore evidence")
        return self


class ReleaseDetailResponse(_StrictResponse):
    release: ReleaseHistoryEntryResponse
    definitions: dict[AgentKey, ReleaseDefinitionResponse]
    #: Ordered by (Graph role order, test case id, run id).
    evidence: list[ReleaseHistoryEvidenceResponse]

    @model_validator(mode="after")
    def require_exact_role_set(self) -> ReleaseDetailResponse:
        _require_seven_in_order(self.definitions, "definitions")
        return self


# --- GET /releases/{version_number}/comparison ---------------------------------------


class ReleaseFieldDiffResponse(_StrictResponse):
    """C46: the comparison's sides are the active and the historical release."""

    field: DiffFieldName
    active: JsonValue
    historical: JsonValue


class AgentComparisonResponse(_StrictResponse):
    agent_key: AgentKey
    active_revision_id: _RowId
    historical_revision_id: _RowId
    same_revision: bool
    #: Only differing fields, in ``DiffFieldName`` order; empty iff equal content.
    field_diffs: list[ReleaseFieldDiffResponse]


def _require_seven_agents(agents: list[AgentComparisonResponse]) -> None:
    _require_seven_in_order((agent.agent_key for agent in agents), "agents")


class ReleaseComparisonResponse(_StrictResponse):
    active_release: ReleaseIdentityResponse
    release: ReleaseIdentityResponse
    agents: list[AgentComparisonResponse]

    @model_validator(mode="after")
    def require_exact_role_set(self) -> ReleaseComparisonResponse:
        _require_seven_agents(self.agents)
        return self


# --- GET /releases/{version_number}/rollback-preview ---------------------------------


class RollbackPreviewEvidenceResponse(_StrictResponse):
    """A link the rollback would write (as ``historical_restore`` from ``source``)."""

    agent_test_run_id: _RowId
    agent_key: AgentKey
    test_case_id: _RowId


class RollbackPreviewResponse(_StrictResponse):
    """Advisory: the rollback re-checks everything under its own locks."""

    source: ReleaseIdentityResponse
    active_release: ReleaseIdentityResponse
    next_version_number: Annotated[int, Field(ge=2)]
    lock_version: Annotated[int, Field(ge=0)]
    default_release_note: str
    #: Exactly ``blocked is None``.
    restorable: bool
    blocked: RollbackBlockWire | None
    #: Structural issues (``definitions.<key>.<field>``); shown even when blocked earlier.
    issues: list[DraftFieldErrorResponse]
    #: Remote endpoint failures (Correction 2): advisory, never blocking.
    warnings: list[DraftFieldErrorResponse]
    agents: list[AgentComparisonResponse]
    evidence: list[RollbackPreviewEvidenceResponse]
    draft_effect: dict[AgentKey, DraftEffectWire]

    @model_validator(mode="after")
    def require_consistent_preview(self) -> RollbackPreviewResponse:
        if self.restorable != (self.blocked is None):
            raise ValueError("restorable is exactly blocked is None")
        _require_seven_agents(self.agents)
        _require_seven_in_order(self.draft_effect, "draft_effect")
        return self


# --- POST /releases/{version_number}/rollback ----------------------------------------


class RollbackRequest(BaseModel):
    """Exactly ``{"lock_version", "release_note"}``.

    Types only: the lock range and the note's blank/length rules are the
    service's (#269's ``_validate_publication_request``, Correction 31), so there
    is no second copy here (#269 C10).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    lock_version: int
    release_note: str


class RollbackSuccessResponse(_StrictResponse):
    """200: the restoring release, its source, and the three-way rebased draft."""

    release: ActiveReleaseResponse
    restored_from: ReleaseIdentityResponse
    previous_release_id: _RowId
    changed_agents: Annotated[list[AgentKey], Field(min_length=1)]
    mappings: dict[AgentKey, PublishedMappingResponse]
    evidence: list[ReleaseEvidenceResponse]
    draft: DraftMetadataResponse
    draft_effect: dict[AgentKey, DraftEffectWire]

    @model_validator(mode="after")
    def require_a_pure_restoration(self) -> RollbackSuccessResponse:
        _require_seven_in_order(self.mappings, "mappings")
        _require_seven_in_order(self.draft_effect, "draft_effect")
        if not all(mapping.reused for mapping in self.mappings.values()):
            raise ValueError("a rollback reuses every revision")
        if any(item.evidence_kind != "historical_restore" for item in self.evidence):
            raise ValueError("a rollback links only historical_restore evidence")
        return self


class RollbackValidationErrorResponse(_StrictResponse):
    code: Literal["invalid_rollback"]
    errors: Annotated[list[DraftFieldErrorResponse], Field(min_length=1)]


class RollbackIncompatibleResponse(_StrictResponse):
    code: Literal["rollback_incompatible"]
    source: ReleaseIdentityResponse
    errors: Annotated[list[DraftFieldErrorResponse], Field(min_length=1)]


class StaleRollbackResponse(_StrictResponse):
    code: Literal["stale_rollback"]
    expected_lock_version: int
    current_lock_version: Annotated[int, Field(ge=0)]
    active_release: ReleaseIdentityResponse
    draft: DraftMetadataResponse


class RollbackSourceActiveResponse(_StrictResponse):
    code: Literal["rollback_source_active"]
    active_release: ReleaseIdentityResponse


class RollbackMatchesActiveResponse(_StrictResponse):
    code: Literal["rollback_matches_active"]
    active_release: ReleaseIdentityResponse
    source: ReleaseIdentityResponse
