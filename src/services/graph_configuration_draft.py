"""Validated, locked writes for the shared Graph Configuration draft."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    definition_content_from_row,
    definition_content_values,
)
from src.services.graph_configuration_workbench import (
    DraftDefinitionSnapshot,
    DraftMetadataSnapshot,
    GraphWorkbenchSnapshot,
    _GraphConfigurationWorkbench,
    _LockedDraftWriteAggregate,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
    definition_content_hash,
)


@dataclass(frozen=True)
class EditableModelDraft:
    prompt_text: str
    endpoint_name: str
    temperature: float
    max_tokens: int
    top_p: float


@dataclass(frozen=True)
class DraftSaveResult:
    draft: DraftMetadataSnapshot
    definition: DraftDefinitionSnapshot
    changed: bool


@dataclass(frozen=True)
class DraftAggregateSnapshot:
    draft: DraftMetadataSnapshot
    definitions: Mapping[AgentKey, DraftDefinitionSnapshot]


ClientCandidateT = TypeVar("ClientCandidateT")


@dataclass(frozen=True)
class DraftSaveConflict(Generic[ClientCandidateT]):
    expected_lock_version: int
    current_lock_version: int
    client_candidate: ClientCandidateT
    server: DraftAggregateSnapshot


DraftSaveOutcome = DraftSaveResult | DraftSaveConflict[ClientCandidateT]


@dataclass(frozen=True)
class DraftValidationIssue:
    field: str
    code: str
    message: str


class DraftContentRejected(ValueError):  # noqa: N818 - stable public domain name
    issues: tuple[DraftValidationIssue, ...]

    def __init__(self, *issues: DraftValidationIssue) -> None:
        if not issues:
            raise ValueError("DraftContentRejected requires at least one issue")
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)
_IMMUTABLE_DRAFT_FIELDS = (
    "definition_version",
    "protected_assembly",
    "schema_contract",
)
_IMMUTABLE_ISSUES = {
    "definition_version": DraftValidationIssue(
        "definition_version",
        "immutable_field",
        "Definition version is immutable in a draft save.",
    ),
    "protected_assembly": DraftValidationIssue(
        "protected_assembly",
        "immutable_field",
        "Protected assembly identity is immutable in a draft save.",
    ),
    "schema_contract": DraftValidationIssue(
        "schema_contract",
        "immutable_field",
        "Schema contract identity is immutable in a draft save.",
    ),
}


class _GraphConfigurationDraft(_GraphConfigurationWorkbench):
    """Own complete draft reconstruction, validation, hashing, and audit writes."""

    def save_editable_model_draft(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
        candidate: EditableModelDraft,
        actor: str,
    ) -> DraftSaveResult | DraftSaveConflict[EditableModelDraft]:
        self._validate_actor_lock_and_editable_candidate(
            actor,
            expected_lock_version,
            agent_key,
            candidate,
        )
        with session.begin():
            locked = self._read_workbench_for_draft_write(
                session,
                agent_key=agent_key,
            )
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=candidate,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            payload = locked.selected.draft.content.model_dump(mode="python")
            payload["prompt_text"] = candidate.prompt_text
            payload["model"] = {
                "endpoint_name": candidate.endpoint_name,
                "temperature": candidate.temperature,
                "max_tokens": candidate.max_tokens,
                "top_p": candidate.top_p,
            }
            content = DefinitionContent.model_validate(payload)
            return self._write_locked_content(
                session,
                locked=locked,
                content=content,
                actor=actor,
            )

    def save_draft_content(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
        content: DefinitionContent,
        actor: str,
    ) -> DraftSaveResult | DraftSaveConflict[DefinitionContent]:
        self._validate_common(actor, expected_lock_version, agent_key)
        if not isinstance(content, DefinitionContent):
            raise DraftContentRejected(
                DraftValidationIssue(
                    "content",
                    "strict_type",
                    "Content must be a DefinitionContent value.",
                )
            )
        with session.begin():
            locked = self._read_workbench_for_draft_write(
                session,
                agent_key=agent_key,
            )
            try:
                validated = DefinitionContent.model_validate(
                    content.model_dump(mode="python")
                )
            except (TypeError, ValueError) as exc:
                raise DraftContentRejected(
                    DraftValidationIssue(
                        "content",
                        "invalid_content",
                        "Draft content must satisfy the DefinitionContent contract.",
                    )
                ) from exc
            issues = self._immutable_content_issues(
                target_agent_key=agent_key,
                current=locked.selected.draft.content,
                proposed=validated,
            )
            if issues:
                raise DraftContentRejected(*issues)
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=validated,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            return self._write_locked_content(
                session,
                locked=locked,
                content=validated,
                actor=actor,
            )

    @staticmethod
    def _validate_common(actor: object, lock_version: object, agent_key: object) -> None:
        issues: list[DraftValidationIssue] = []
        if not isinstance(actor, str):
            issues.append(
                DraftValidationIssue("actor", "strict_type", "Actor must be a string.")
            )
        elif not actor.strip():
            issues.append(
                DraftValidationIssue("actor", "blank", "Actor must not be blank.")
            )
        if isinstance(lock_version, bool) or not isinstance(lock_version, int):
            issues.append(
                DraftValidationIssue(
                    "lock_version",
                    "strict_type",
                    "Lock version must be an integer.",
                )
            )
        elif lock_version < 0:
            issues.append(
                DraftValidationIssue(
                    "lock_version",
                    "out_of_range",
                    "Lock version must be greater than or equal to 0.",
                )
            )
        if agent_key not in _EXPECTED_AGENT_KEYS:
            issues.append(
                DraftValidationIssue(
                    "agent_key",
                    "unknown_agent",
                    "Agent key must identify an editable model role.",
                )
            )
        if issues:
            raise DraftContentRejected(*issues)

    def _validate_actor_lock_and_editable_candidate(
        self,
        actor: object,
        lock_version: object,
        agent_key: object,
        candidate: object,
    ) -> None:
        issues: list[DraftValidationIssue] = []
        try:
            self._validate_common(actor, lock_version, agent_key)
        except DraftContentRejected as exc:
            issues.extend(exc.issues)
        if not isinstance(candidate, EditableModelDraft):
            issues.append(
                DraftValidationIssue(
                    "candidate",
                    "strict_type",
                    "Candidate must be an editable model draft.",
                )
            )
        else:
            if not isinstance(candidate.prompt_text, str):
                issues.append(
                    DraftValidationIssue(
                        "candidate.prompt_text",
                        "strict_type",
                        "Prompt text must be a string.",
                    )
                )
            elif not candidate.prompt_text.strip():
                issues.append(
                    DraftValidationIssue(
                        "candidate.prompt_text",
                        "blank",
                        "Prompt text must not be blank.",
                    )
                )
            if not isinstance(candidate.endpoint_name, str):
                issues.append(
                    DraftValidationIssue(
                        "candidate.model.endpoint_name",
                        "strict_type",
                        "Endpoint name must be a string.",
                    )
                )
            elif not candidate.endpoint_name.strip():
                issues.append(
                    DraftValidationIssue(
                        "candidate.model.endpoint_name",
                        "blank",
                        "Endpoint name must not be blank.",
                    )
                )
            self._append_number_issues(
                issues,
                value=candidate.temperature,
                field="candidate.model.temperature",
                label="Temperature",
            )
            if isinstance(candidate.max_tokens, bool) or not isinstance(
                candidate.max_tokens, int
            ):
                issues.append(
                    DraftValidationIssue(
                        "candidate.model.max_tokens",
                        "strict_type",
                        "Maximum tokens must be an integer.",
                    )
                )
            elif candidate.max_tokens < 1:
                issues.append(
                    DraftValidationIssue(
                        "candidate.model.max_tokens",
                        "positive_integer",
                        "Maximum tokens must be a positive integer.",
                    )
                )
            self._append_number_issues(
                issues,
                value=candidate.top_p,
                field="candidate.model.top_p",
                label="Top-p",
            )
        if issues:
            raise DraftContentRejected(*issues)

    @staticmethod
    def _append_number_issues(
        issues: list[DraftValidationIssue],
        *,
        value: object,
        field: str,
        label: str,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(
                DraftValidationIssue(field, "strict_type", f"{label} must be a number.")
            )
        elif not math.isfinite(value):
            issues.append(
                DraftValidationIssue(field, "finite_number", f"{label} must be finite.")
            )
        elif not 0 <= value <= 1:
            issues.append(
                DraftValidationIssue(
                    field,
                    "out_of_range",
                    f"{label} must be between 0 and 1.",
                )
            )

    @staticmethod
    def _immutable_content_issues(
        *,
        target_agent_key: AgentKey,
        current: DefinitionContent,
        proposed: DefinitionContent,
    ) -> tuple[DraftValidationIssue, ...]:
        issues: list[DraftValidationIssue] = []
        if proposed.agent_key != target_agent_key:
            issues.append(
                DraftValidationIssue(
                    "agent_key",
                    "immutable_field",
                    "Agent key must match the targeted draft definition.",
                )
            )
        for field in _IMMUTABLE_DRAFT_FIELDS:
            if getattr(proposed, field) != getattr(current, field):
                issues.append(_IMMUTABLE_ISSUES[field])
        return tuple(issues)

    @staticmethod
    def _draft_aggregate_snapshot(
        snapshot: GraphWorkbenchSnapshot,
    ) -> DraftAggregateSnapshot:
        definitions = {
            node.agent_key: node.draft
            for node in snapshot.nodes
            if node.execution_kind == "model"
        }
        if set(definitions) != _EXPECTED_AGENT_KEYS:
            raise GraphConfigurationIntegrityError(
                "shared draft snapshot does not have the exact role key set"
            )
        return DraftAggregateSnapshot(
            draft=snapshot.draft,
            definitions=MappingProxyType(definitions),
        )

    @staticmethod
    def _write_locked_content(
        session: Session,
        *,
        locked: _LockedDraftWriteAggregate,
        content: DefinitionContent,
        actor: str,
    ) -> DraftSaveResult:
        old_hash = locked.selected.draft.candidate_hash
        new_hash = definition_content_hash(content)
        for column_name, value in definition_content_values(content).items():
            setattr(locked.selected_row, column_name, value)
        locked.selected_row.candidate_hash = new_hash
        timestamp = session.scalar(select(func.current_timestamp()))
        if timestamp is None:
            raise GraphConfigurationIntegrityError(
                "database did not return a transaction timestamp"
            )
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        locked.draft_row.lock_version += 1
        locked.draft_row.updated_by = actor
        locked.draft_row.updated_at = timestamp
        session.flush()
        return DraftSaveResult(
            draft=DraftMetadataSnapshot(
                draft_id=locked.draft_row.id,
                base_release_id=locked.draft_row.base_release_id,
                base_version_number=locked.snapshot.active_release.version_number,
                lock_version=locked.draft_row.lock_version,
                updated_by=locked.draft_row.updated_by,
                updated_at=locked.draft_row.updated_at,
            ),
            definition=DraftDefinitionSnapshot(
                base_revision_id=locked.selected.draft.base_revision_id,
                candidate_hash=locked.selected_row.candidate_hash,
                content=definition_content_from_row(locked.selected_row),
            ),
            changed=new_hash != old_hash,
        )
