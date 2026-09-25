"""Validated, locked writes for the shared Graph Configuration draft."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from types import MappingProxyType
from typing import Callable, Generic, Literal, Mapping, Protocol, TypeVar

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.agent_schema_registry import (
    AgentSchemaRegistry,
    upgrade_content_to_v2,
)
from src.services.agent_schema_types import SchemaOverlay, SchemaValidationIssue
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
    AssemblyRulesV2,
    DefinitionContent,
    ModelConfiguration,
    definition_content_hash,
    schema_contract_identity,
)
from src.services.model_endpoint_catalog import (
    EndpointValidationFailure,
    ModelEndpointCatalog,
    validate_endpoint_name_policy,
)
from src.services.prompt_assembler import PromptAssembler, PromptAssemblyRejected


@dataclass(frozen=True)
class EditableModelDraft:
    prompt_text: str
    endpoint_name: str
    temperature: float
    max_tokens: int
    top_p: float
    assembly_rules: AssemblyRulesV2 | None = None
    #: Absent means "retain the stored overlay"; it never means "clear it".  The
    #: protected ``schema_contract`` identity is deliberately NOT a member here,
    #: so an ordinary client save cannot name it at all.
    schema_overlay: SchemaOverlay | None = None


@dataclass(frozen=True)
class DraftSaveResult:
    draft: DraftMetadataSnapshot
    definition: DraftDefinitionSnapshot
    changed: bool


@dataclass(frozen=True)
class DraftAggregateSnapshot:
    draft: DraftMetadataSnapshot
    definitions: Mapping[AgentKey, DraftDefinitionSnapshot]


@dataclass(frozen=True)
class DraftLegacyPromptSourceRecord:
    """Server-authored retained Graph Version 1 prompt source for one role."""

    prompt_text: str
    revision_id: int
    content_hash: str


@dataclass(frozen=True)
class DraftLegacyPromptSource:
    """Read-only recovery result; it carries no candidate and causes no write."""

    draft: DraftMetadataSnapshot
    agent_key: AgentKey
    lock_version: int
    source: DraftLegacyPromptSourceRecord


@dataclass(frozen=True)
class DraftProbeCandidate:
    """An immutable copy of one role's saved candidate for the #266 probe.

    It is copied inside a transaction that has already ended when this value
    is returned, so no database lock outlives the read.
    """

    agent_key: AgentKey
    lock_version: int
    candidate_hash: str
    model: ModelConfiguration


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


_PROMPT_ASSEMBLER = PromptAssembler()
_SCHEMA_REGISTRY = AgentSchemaRegistry()

#: Wire prefix for every overlay issue that names a location inside the candidate's
#: own editable overlay.  The protected identity keeps #263's unprefixed
#: ``schema_contract`` field instead, so one condition never gets two spellings.
_OVERLAY_ISSUE_ROOT = "candidate.schema_overlay"
_SCHEMA_CONTRACT_FIELD = "schema_contract"
_SCHEMA_ALREADY_CURRENT = DraftValidationIssue(
    _SCHEMA_CONTRACT_FIELD,
    "already_current",
    "Schema contract is already current.",
)

#: One ordered tuple of validators over a complete rehydrated ``DefinitionContent``.
#: A validator owns no persistence and returns its issues in its own declared order.
DraftCandidateValidator = Callable[[DefinitionContent], tuple[DraftValidationIssue, ...]]

_LEGACY_SOURCE_ROLES: tuple[Literal["data_analyst", "build_reviewer"], ...] = (
    "data_analyst",
    "build_reviewer",
)
_LEGACY_SOURCE_UNSUPPORTED = DraftValidationIssue(
    "agent_key",
    "legacy_prompt_source_unsupported",
    "Legacy Graph Version 1 prompt recovery is supported only for Data Analyst "
    "and Build Reviewer.",
)
_LEGACY_SOURCE_NOT_REQUIRED = DraftValidationIssue(
    "prompt_text",
    "legacy_prompt_source_not_required",
    "The draft already uses the exact Graph Version 1 prompt.",
)
_EDITABLE_RULES_INVALID = DraftValidationIssue(
    "candidate.assembly_rules",
    "invalid_protected_placement",
    "Assembly rules must satisfy the persisted assembly contract.",
)
_LEGACY_SOURCE_UNAVAILABLE = DraftValidationIssue(
    "prompt_text",
    "legacy_prompt_source_unavailable",
    "The exact published Graph Version 1 prompt source is unavailable for this draft.",
)


def _copied_assembly_issues(
    rejection: PromptAssemblyRejected,
) -> tuple[DraftValidationIssue, ...]:
    """Copy assembler-owned field/code/message values in order; own no policy."""
    return tuple(
        DraftValidationIssue(issue.field, issue.code, issue.message)
        for issue in rejection.issues
    )


def _assembly_candidate_validator(
    content: DefinitionContent,
) -> tuple[DraftValidationIssue, ...]:
    """Structural adapter for ``PromptAssembler.validate``; it adds no semantics."""
    try:
        _PROMPT_ASSEMBLER.validate(definition=content)
    except PromptAssemblyRejected as rejection:
        return _copied_assembly_issues(rejection)
    return ()


def _overlay_issue_field(issue: SchemaValidationIssue) -> str:
    """Name one registry overlay issue in this writer's wire vocabulary.

    A located issue is reported under the candidate's own overlay prefix.  The one
    unlocated issue — the stored contract bundle failing to resolve — is server
    state rather than candidate content, so it is reported on the protected
    ``schema_contract`` field, matching the identity's existing spelling.
    """
    if not issue.path:
        return _SCHEMA_CONTRACT_FIELD
    return ".".join((_OVERLAY_ISSUE_ROOT, *(str(segment) for segment in issue.path)))


def _schema_overlay_candidate_validator(
    content: DefinitionContent,
) -> tuple[DraftValidationIssue, ...]:
    """Structural adapter for ``AgentSchemaRegistry.validate_overlay``.

    It adds no semantics and owns no catalog: the registry decides eligibility,
    and the role is taken from the record rather than from the stored identity, so
    a stored version/digest pair can never select another role's contract.
    """
    identity = schema_contract_identity(content.agent_key, content.schema_contract)
    return tuple(
        DraftValidationIssue(_overlay_issue_field(issue), issue.code, issue.message)
        for issue in _SCHEMA_REGISTRY.validate_overlay(
            content.agent_key, identity, content.schema_overlay
        )
    )


_ENDPOINT_FIELD = "candidate.model.endpoint_name"


def _endpoint_issue(failure: EndpointValidationFailure) -> DraftValidationIssue:
    """Copy the catalog-owned code and message; never echo endpoint text."""
    return DraftValidationIssue(_ENDPOINT_FIELD, failure.code, failure.message)


def _endpoint_name_policy_validator(
    content: DefinitionContent,
) -> tuple[DraftValidationIssue, ...]:
    """Pure local endpoint-name policy; it performs no SDK or network work."""
    try:
        validate_endpoint_name_policy(content.model.endpoint_name)
    except EndpointValidationFailure as failure:
        return (_endpoint_issue(failure),)
    return ()


class RemoteEndpointDraftValidator(Protocol):
    """Remote exact-endpoint check over one complete reconstructed candidate.

    It raises ``EndpointValidationFailure`` to reject and returns ``None`` to
    accept.  The draft writer calls it only for a current locked candidate.
    """

    def validate(self, content: DefinitionContent) -> None: ...


class CatalogRemoteEndpointDraftValidator:
    """Delegate the exact, unchanged candidate endpoint to the model catalog.

    The catalog is obtained from the factory on each call, so constructing the
    validator performs no client or network work.
    """

    def __init__(self, catalog_factory: Callable[[], ModelEndpointCatalog]) -> None:
        self._catalog_factory = catalog_factory

    def validate(self, content: DefinitionContent) -> None:
        self._catalog_factory().validate_custom_endpoint_remote(
            content.model.endpoint_name
        )


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

    #: Deterministic/local validators; they run before the stale comparison.
    #: Schema-overlay validation belongs here and not in ``post_stale_validators``:
    #: the stale comparison short-circuits the post-stale phase, so registering it
    #: there would turn the mandated invalid-plus-stale ordered 422 into a 409 and
    #: make every overlay issue invisible.
    local_candidate_validators: tuple[DraftCandidateValidator, ...] = (
        _assembly_candidate_validator,
        _schema_overlay_candidate_validator,
    )
    #: Remote/expensive validators; they run only for a current candidate and
    #: immediately before the one mapper/hash/flush/audit/lock write.
    post_stale_validators: tuple[DraftCandidateValidator, ...] = ()

    def __init__(
        self,
        *,
        remote_endpoint_validator: RemoteEndpointDraftValidator | None = None,
    ) -> None:
        """``None`` skips the remote endpoint phase (trusted/test composition only).

        Production draft saves are composed with
        ``build_remote_endpoint_draft_validator()``; the admin PUT wiring is #266
        Task 3.  Upgrades never consult this validator.
        """
        super().__init__()
        self._remote_endpoint_validator = remote_endpoint_validator

    def _run_candidate_validators(
        self,
        validators: tuple[DraftCandidateValidator, ...],
        content: DefinitionContent,
    ) -> None:
        """Aggregate one reached phase in validator order, then issue order."""
        issues: list[DraftValidationIssue] = []
        for validator in validators:
            issues.extend(validator(content))
        if issues:
            raise DraftContentRejected(*issues)

    def _save_local_validators(self) -> tuple[DraftCandidateValidator, ...]:
        """The two saves' local phase: the class tuple, then the endpoint policy.

        The endpoint policy is composed here rather than into
        ``local_candidate_validators`` so that neither upgrade runs it: an
        upgrade never edits the endpoint and must do no endpoint work.
        """
        return self.local_candidate_validators + (_endpoint_name_policy_validator,)

    def _validate_remote_endpoint(self, content: DefinitionContent) -> None:
        """The saves' remote phase: once, for a current locked candidate only."""
        if self._remote_endpoint_validator is None:
            return
        try:
            self._remote_endpoint_validator.validate(content)
        except EndpointValidationFailure as failure:
            raise DraftContentRejected(_endpoint_issue(failure)) from failure

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
            payload = locked.selected.draft.content.model_dump(mode="python")
            payload["prompt_text"] = candidate.prompt_text
            payload["model"] = {
                "endpoint_name": candidate.endpoint_name,
                "temperature": candidate.temperature,
                "max_tokens": candidate.max_tokens,
                "top_p": candidate.top_p,
            }
            supplied_rules = candidate.assembly_rules is not None
            if supplied_rules:
                payload["assembly_rules"] = candidate.assembly_rules.model_dump(
                    mode="python"
                )
            if candidate.schema_overlay is not None:
                payload["schema_overlay"] = candidate.schema_overlay.model_dump(
                    mode="python"
                )
            try:
                content = DefinitionContent.model_validate(payload)
            except ValidationError as exc:
                if not supplied_rules or any(
                    error["loc"][:1] != ("assembly_rules",) for error in exc.errors()
                ):
                    raise
                raise DraftContentRejected(_EDITABLE_RULES_INVALID) from exc
            self._run_candidate_validators(self._save_local_validators(), content)
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=candidate,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            self._run_candidate_validators(self.post_stale_validators, content)
            self._validate_remote_endpoint(content)
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
            self._run_candidate_validators(self._save_local_validators(), validated)
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=validated,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            self._run_candidate_validators(self.post_stale_validators, validated)
            self._validate_remote_endpoint(validated)
            return self._write_locked_content(
                session,
                locked=locked,
                content=validated,
                actor=actor,
            )

    def upgrade_draft_protected_assembly(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
        actor: str,
    ) -> DraftSaveResult | DraftSaveConflict[None]:
        """Apply the one permitted v1 to v2 protected-assembly transition."""
        self._validate_common(actor, expected_lock_version, agent_key)
        with session.begin():
            locked = self._read_workbench_for_draft_write(
                session,
                agent_key=agent_key,
            )
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=None,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            try:
                target = _PROMPT_ASSEMBLER.upgrade_definition_to_v2(
                    definition=locked.selected.draft.content
                )
            except PromptAssemblyRejected as rejection:
                raise DraftContentRejected(
                    *_copied_assembly_issues(rejection)
                ) from rejection
            self._run_candidate_validators(self.local_candidate_validators, target)
            self._run_candidate_validators(self.post_stale_validators, target)
            return self._write_locked_content(
                session,
                locked=locked,
                content=target,
                actor=actor,
            )

    def upgrade_draft_schema_contract(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
        actor: str,
    ) -> DraftSaveResult | DraftSaveConflict[None]:
        """Apply the one permitted v1 to v2 schema-contract transition.

        This is a **separate** entry point from
        :meth:`upgrade_draft_protected_assembly`, and the two deliberately differ in
        precedence.  That sibling returns its stale conflict *before* reaching any
        validation; this one validates the existing content *first*, so an
        invalid-plus-stale request returns the ordered 422 the schema-overlay wire
        contract requires while a valid stale request still returns 409.  The
        difference is intentional: harmonising them would silently change the
        already-shipped protected-assembly status for the same request shape.

        Inner ordering mirrors ``PromptAssembler.upgrade_definition_to_v2``, which
        validates before reporting ``already_current`` — here on field
        ``schema_contract``.  It reuses the one locked aggregate, the one
        mapper/hash/flush/audit/lock write, and adds no second lookup or
        transaction.
        """
        self._validate_common(actor, expected_lock_version, agent_key)
        with session.begin():
            locked = self._read_workbench_for_draft_write(
                session,
                agent_key=agent_key,
            )
            current = locked.selected.draft.content
            self._run_candidate_validators(self.local_candidate_validators, current)
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=None,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            if schema_contract_identity(
                agent_key, current.schema_contract
            ) == _SCHEMA_REGISTRY.identity_for(agent_key, 2):
                raise DraftContentRejected(_SCHEMA_ALREADY_CURRENT)
            target = upgrade_content_to_v2(current)
            self._run_candidate_validators(self.local_candidate_validators, target)
            self._run_candidate_validators(self.post_stale_validators, target)
            return self._write_locked_content(
                session,
                locked=locked,
                content=target,
                actor=actor,
            )

    def get_draft_legacy_prompt_source(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
        actor: str,
    ) -> DraftLegacyPromptSource | DraftSaveConflict[None]:
        """Read the retained Graph Version 1 prompt source; never write anything."""
        self._validate_common(actor, expected_lock_version, agent_key)
        with session.begin():
            locked = self._read_workbench_for_draft_write(
                session,
                agent_key=agent_key,
            )
            if expected_lock_version != locked.snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=locked.snapshot.draft.lock_version,
                    client_candidate=None,
                    server=self._draft_aggregate_snapshot(locked.snapshot),
                )
            return self._legacy_prompt_source(locked, agent_key=agent_key)

    def read_draft_probe_candidate(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
    ) -> DraftProbeCandidate | DraftSaveConflict[None]:
        """Copy one role's saved candidate for the structured-output probe.

        Read-only.  The copy is taken under the workbench's shared parent locks
        inside its own transaction, which ends before this returns (correction
        13), so the caller's remote model call holds no database lock.  A stale
        lock is the coherent null-candidate conflict.  The saved endpoint name
        is then re-checked against the local policy after the locks are
        released, so a URL- or path-shaped stored name never reaches a provider.
        """
        self._validate_lock_and_agent_key(expected_lock_version, agent_key)
        with session.begin():
            snapshot = self.read_workbench(session)
            aggregate = self._draft_aggregate_snapshot(snapshot)
            if expected_lock_version != snapshot.draft.lock_version:
                return DraftSaveConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=snapshot.draft.lock_version,
                    client_candidate=None,
                    server=aggregate,
                )
            selected = aggregate.definitions[agent_key]
            candidate = DraftProbeCandidate(
                agent_key=agent_key,
                lock_version=snapshot.draft.lock_version,
                candidate_hash=selected.candidate_hash,
                model=selected.content.model,
            )
        self._run_candidate_validators(
            (_endpoint_name_policy_validator,), selected.content
        )
        return candidate

    @staticmethod
    def _legacy_prompt_source(
        locked: _LockedDraftWriteAggregate,
        *,
        agent_key: AgentKey,
    ) -> DraftLegacyPromptSource:
        if agent_key not in _LEGACY_SOURCE_ROLES:
            raise DraftContentRejected(_LEGACY_SOURCE_UNSUPPORTED)
        transition = _PROMPT_ASSEMBLER.legacy_v1_prompt_source(agent_key=agent_key)
        draft = locked.selected.draft.content
        if (
            draft.definition_version != transition.source_definition_version
            or draft.protected_assembly != transition.source_protected_assembly
            or draft.assembly_rules != transition.source_assembly_rules
        ):
            raise DraftContentRejected(_LEGACY_SOURCE_UNAVAILABLE)
        if draft.prompt_text == transition.source_composite_prompt:
            raise DraftContentRejected(_LEGACY_SOURCE_NOT_REQUIRED)
        published = locked.selected.published
        if (
            published.content.agent_key != agent_key
            or published.content.definition_version
            != transition.source_definition_version
            or published.content.protected_assembly
            != transition.source_protected_assembly
            or published.content.assembly_rules != transition.source_assembly_rules
            or published.content.prompt_text != transition.source_composite_prompt
        ):
            raise DraftContentRejected(_LEGACY_SOURCE_UNAVAILABLE)
        return DraftLegacyPromptSource(
            draft=locked.snapshot.draft,
            agent_key=agent_key,
            lock_version=locked.snapshot.draft.lock_version,
            source=DraftLegacyPromptSourceRecord(
                prompt_text=transition.source_composite_prompt,
                revision_id=published.revision_id,
                content_hash=published.content_hash,
            ),
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
        issues.extend(
            _GraphConfigurationDraft._lock_and_agent_key_issues(lock_version, agent_key)
        )
        if issues:
            raise DraftContentRejected(*issues)

    @staticmethod
    def _validate_lock_and_agent_key(lock_version: object, agent_key: object) -> None:
        issues = _GraphConfigurationDraft._lock_and_agent_key_issues(
            lock_version, agent_key
        )
        if issues:
            raise DraftContentRejected(*issues)

    @staticmethod
    def _lock_and_agent_key_issues(
        lock_version: object, agent_key: object
    ) -> list[DraftValidationIssue]:
        issues: list[DraftValidationIssue] = []
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
        return issues

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
            if candidate.assembly_rules is not None and not isinstance(
                candidate.assembly_rules, AssemblyRulesV2
            ):
                issues.append(
                    DraftValidationIssue(
                        "candidate.assembly_rules",
                        "strict_type",
                        "Assembly rules must be the current editable custom-block record.",
                    )
                )
            if candidate.schema_overlay is not None and not isinstance(
                candidate.schema_overlay, SchemaOverlay
            ):
                issues.append(
                    DraftValidationIssue(
                        _OVERLAY_ISSUE_ROOT,
                        "strict_type",
                        "Schema overlay must be the current editable overlay record.",
                    )
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
