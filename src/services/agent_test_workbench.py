"""Agent Test Case create/read/update/retire service (#267).

One locked writer per aggregate: every write to a role's cases first takes the
L2 lock, ``SELECT ... FROM agent_test_case WHERE agent_key = :k ORDER BY id FOR
UPDATE`` with no ``is_active`` filter, then re-reads the role's rows and decides
from them.  It takes no draft or release lock (L0) and makes no remote call.

Invariants held here:

- **Versioning (C22).** A case's ``name`` is its immutable lineage key.  An
  update supersedes: it retires the old row and inserts ``version + 1`` in one
  transaction, so a lineage never has two active versions.  A historical row is
  never modified except by its own retirement.
- **Last required case (C9).** No write may leave a role without an active
  required case, because the next boot's integrity check
  (``graph_configuration_bootstrap.py`` ``_validate_current_graph``) would then
  raise and the replica would exit.  Such a write is refused with the
  ``last_required_case`` issue before any row changes.

Execution (Task 4) runs one active case version against the saved draft
candidate (``execute_candidate_run``) or the active published definition
(``execute_baseline_rerun``) and persists one immutable ``agent_test_run`` row:

- **No transaction across the model call (C8/C32).** Short read transactions
  copy the candidate (#266's probe read, lock-pinned) and the case into frozen
  values and commit; the model is called with no open transaction; a second
  transaction re-locks release then draft ``FOR SHARE`` and inserts the run with
  the first transactions' identity verbatim.  If the draft, case or base
  release moved meanwhile the run is still persisted (it records exactly what
  ran) and the returned evidence says so.
- **What the model sees (C37).** The stored payload is projected onto the
  role's production model keys by ``agent_model_payload``; both are evidence.
- **Outcome (C15/C16/C17).** The runtime's own classification and single
  output validation decide the status and the one check; ``error_detail`` is a
  code, never exception text.  A database failure writes no run and raises
  ``TestRunUnavailable``.
- **Baseline (C20).** The newest completed ``published_baseline`` run of this
  case row and revision is copied into a candidate row; no verdict is read.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.database.models.graph_configuration import (
    AgentTestCase,
    AgentTestRun,
    GraphDraft,
    GraphDraftAgent,
    GraphReleaseAgent,
)
from src.services.agent_model_payload import model_payload_for
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentInvocationResult,
    AgentRuntime,
    RunObservation,
    UnknownAgentKeyError,
    get_agent_test_runtime,
)
from src.services.agent_schema_registry import AgentOutputValidationError
from src.services.agent_schema_types import thaw_json_containers
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_configuration_draft import DraftSaveConflict
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.persisted_graph_release import (
    GraphReleaseIncompleteError,
    GraphReleaseNotFoundError,
    PersistedConfigurationUnavailableError,
)

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 200
MAX_SYNTHETIC_PAYLOAD_BYTES = 64 * 1024

_UNIQUE_VERSION_CONSTRAINT = "uq_agent_test_case_agent_name_version"
_SQLITE_UNIQUE_VERSION_MESSAGE = (
    "UNIQUE constraint failed: agent_test_case.agent_key, "
    "agent_test_case.name, agent_test_case.version"
)

#: C9's issue order.  ``actor`` and ``agent_key`` precede it: they are checked
#: before anything else and are never combined with a body issue by a route.
_FIELD_ORDER = (
    "actor",
    "agent_key",
    "name",
    "synthetic_payload",
    "assembly_context",
    "is_required",
    "is_active",
)

_LAST_REQUIRED_MESSAGE = (
    "A role must keep at least one active required test case. "
    "Add its replacement before retiring this one."
)


@dataclass(frozen=True)
class TestCaseIssue:
    __test__ = False  # not a pytest test class

    field: str
    code: str
    message: str


class TestCaseRejected(ValueError):  # noqa: N818 - stable public domain name
    """One or more ordered validation issues; nothing was written."""

    __test__ = False
    issues: tuple[TestCaseIssue, ...]

    def __init__(self, *issues: TestCaseIssue) -> None:
        if not issues:
            raise ValueError("TestCaseRejected requires at least one issue")
        self.issues = tuple(
            sorted(issues, key=lambda issue: _FIELD_ORDER.index(issue.field))
        )
        super().__init__("; ".join(issue.message for issue in self.issues))


class TestCaseNotFound(LookupError):  # noqa: N818 - stable public domain name
    __test__ = False

    def __init__(self, test_case_id: int) -> None:
        self.test_case_id = test_case_id
        super().__init__(f"test case {test_case_id} does not exist")


class TestCaseStale(Exception):  # noqa: N818 - stable public domain name
    """The addressed version is no longer the lineage's active version."""

    __test__ = False

    def __init__(self, test_case_id: int) -> None:
        self.test_case_id = test_case_id
        super().__init__(f"test case {test_case_id} is not the active version")


@dataclass(frozen=True)
class TestCaseVersion:
    """An immutable snapshot of one ``agent_test_case`` row."""

    __test__ = False

    id: int
    agent_key: str
    name: str
    version: int
    is_active: bool
    is_required: bool
    synthetic_payload: dict[str, Any]
    assembly_context: dict[str, bool]
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime

    @classmethod
    def from_row(cls, row: AgentTestCase) -> "TestCaseVersion":
        return cls(
            id=row.id,
            agent_key=row.agent_key,
            name=row.name,
            version=row.version,
            is_active=row.is_active,
            is_required=row.is_required,
            synthetic_payload=row.synthetic_payload,
            assembly_context=row.assembly_context,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )


def _role_lock_statement(agent_key: str) -> Select:
    """L2: every row of the role, active or not, in id order, ``FOR UPDATE``.

    No ``is_active`` filter: a row retired by a concurrent writer must still be
    locked and re-read, or two retirements of a role's last two required cases
    would both see the other as active.
    """
    return (
        select(AgentTestCase)
        .where(AgentTestCase.agent_key == agent_key)
        .order_by(AgentTestCase.id)
        .with_for_update()
    )


def _lock_role_rows(session: Session, agent_key: str) -> None:
    session.execute(
        _role_lock_statement(agent_key).execution_options(populate_existing=True)
    ).all()


def _reread_role_rows(session: Session, agent_key: str) -> list[AgentTestCase]:
    """Re-read the locked role after the lock is held.

    Under READ COMMITTED this is a fresh snapshot, so it also sees a row a
    concurrent writer inserted while this writer waited for the lock.  Once the
    lock is held no other case writer can change the role.
    """
    return list(
        session.scalars(
            select(AgentTestCase)
            .where(AgentTestCase.agent_key == agent_key)
            .order_by(AgentTestCase.id)
            .execution_options(populate_existing=True)
        )
    )


def _active_required_count(rows: list[AgentTestCase]) -> int:
    return sum(1 for row in rows if row.is_active and row.is_required)


def _last_required_issue(field: str) -> TestCaseIssue:
    return TestCaseIssue(field, "last_required_case", _LAST_REQUIRED_MESSAGE)


def _actor_issues(actor: object) -> list[TestCaseIssue]:
    if not isinstance(actor, str) or not actor.strip():
        return [TestCaseIssue("actor", "blank", "Actor must not be blank.")]
    return []


def _agent_key_issues(agent_key: object) -> list[TestCaseIssue]:
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        return [
            TestCaseIssue(
                "agent_key",
                "unknown_agent",
                "Agent key must identify an editable model role.",
            )
        ]
    return []


def _name_issues(name: object) -> list[TestCaseIssue]:
    if not isinstance(name, str):
        return [TestCaseIssue("name", "strict_type", "Test case name must be a string.")]
    trimmed = name.strip()
    if not trimmed:
        return [TestCaseIssue("name", "blank", "Test case name must not be blank.")]
    if len(trimmed) > MAX_NAME_LENGTH:
        return [
            TestCaseIssue(
                "name",
                "too_long",
                f"Test case name must be at most {MAX_NAME_LENGTH} characters.",
            )
        ]
    return []


def _payload_issues(payload: object) -> list[TestCaseIssue]:
    if not isinstance(payload, dict):
        return [
            TestCaseIssue(
                "synthetic_payload",
                "strict_type",
                "Synthetic payload must be a JSON object.",
            )
        ]
    try:
        serialized = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError):
        return [
            TestCaseIssue(
                "synthetic_payload",
                "invalid_json",
                "Synthetic payload must contain only JSON values.",
            )
        ]
    if len(serialized.encode("utf-8")) > MAX_SYNTHETIC_PAYLOAD_BYTES:
        return [
            TestCaseIssue(
                "synthetic_payload",
                "too_large",
                f"Synthetic payload must be at most {MAX_SYNTHETIC_PAYLOAD_BYTES} "
                "bytes as JSON.",
            )
        ]
    return []


def _assembly_context_issues(context: object) -> list[TestCaseIssue]:
    # The runtime's assembler reads only ``design_system_active`` (C22).
    if (
        not isinstance(context, dict)
        or set(context) != {"design_system_active"}
        or not isinstance(context["design_system_active"], bool)
    ):
        return [
            TestCaseIssue(
                "assembly_context",
                "strict_type",
                'Assembly context must be exactly {"design_system_active": true or false}.',
            )
        ]
    return []


def _is_required_issues(is_required: object) -> list[TestCaseIssue]:
    if not isinstance(is_required, bool):
        return [
            TestCaseIssue("is_required", "strict_type", "Required must be true or false.")
        ]
    return []


def _content_issues(
    *, synthetic_payload: object, assembly_context: object, is_required: object
) -> list[TestCaseIssue]:
    return [
        *_payload_issues(synthetic_payload),
        *_assembly_context_issues(assembly_context),
        *_is_required_issues(is_required),
    ]


def _is_version_collision(error: IntegrityError) -> bool:
    original = error.orig
    diag = getattr(original, "diag", None)
    if getattr(diag, "constraint_name", None) == _UNIQUE_VERSION_CONSTRAINT:
        return True
    return _SQLITE_UNIQUE_VERSION_MESSAGE in str(original)


def _canonical_json(document: object) -> str:
    """Type-exact canonical text: ``1``, ``1.0`` and ``true`` stay distinct.

    Python ``==`` would treat ``{"a": 1}``, ``{"a": 1.0}`` and ``{"a": True}``
    as equal and silently drop a real edit, so content identity never uses it.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _copy_json(document: Mapping[str, Any]) -> dict[str, Any]:
    """Store a detached copy so a caller's later mutation cannot reach the row."""
    return json.loads(json.dumps(document))


# --- test run evidence (Task 4) ----------------------------------------------

RunKind = Literal["candidate", "published_baseline"]
ExecutionStatus = Literal["completed", "model_error", "assembly_error", "incomplete"]

#: ``_lock_current_parents``'s diagnosis when it was queued behind a committing
#: publication: the one transaction-2 failure retried once (C8.6).
_PARENT_HANDOFF_DIAGNOSIS = "graph configuration parent snapshot is inconsistent"

_CONTRACT_FAILED_MESSAGE = "The model output does not satisfy the output contract."
_NO_OUTPUT_MESSAGE = "The run produced no model output to check."

MAX_RUN_LIST_LIMIT = 100


@dataclass(frozen=True)
class DeterministicCheckIssue:
    code: str
    field: str | None


@dataclass(frozen=True)
class DeterministicCheckResult:
    """One check.  #267 has exactly one per run, derived from the runtime (C17)."""

    name: Literal["output_contract", "execution"]
    passed: bool
    message: str | None
    issues: tuple[DeterministicCheckIssue, ...] = ()


@dataclass(frozen=True)
class TestRunEvidence:
    """One persisted run, as read back from its immutable row.

    ``synthetic_payload`` is the stored case payload and ``model_payload`` the
    projection actually sent (C37).  ``candidate_is_current`` and
    ``base_release_is_current`` are computed when the run is written and are
    not persisted, so a later read returns ``None`` for both (C8.5).  Verdict
    columns are #268's and are deliberately absent (C11).
    """

    __test__ = False

    run_id: int
    run_kind: RunKind
    test_case_id: int
    test_case_version: int
    agent_key: str
    candidate_hash: str
    compared_release_id: int
    compared_definition_revision_id: int
    synthetic_payload: dict[str, Any]
    model_payload: dict[str, Any]
    assembled_prompt: str | None
    execution_status: ExecutionStatus
    error_detail: str | None
    deterministic_checks_passed: bool
    deterministic_check_results: tuple[DeterministicCheckResult, ...]
    candidate_raw_output: dict[str, Any] | None
    candidate_structured_output: dict[str, Any] | None
    baseline_raw_output: dict[str, Any] | None
    baseline_structured_output: dict[str, Any] | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    run_by: str
    run_at: datetime
    candidate_is_current: bool | None = None
    base_release_is_current: bool | None = None


class TestRunUnavailable(Exception):  # noqa: N818 - stable public domain name
    """The database failed before or after the model call; no run was written."""

    __test__ = False

    def __init__(self, phase: str) -> None:
        self.phase = phase
        super().__init__("Test run persistence is unavailable")


class TestRunCaseInactive(Exception):  # noqa: N818 - stable public domain name
    """Only an active case version may be run (ruling P5)."""

    __test__ = False

    def __init__(self, test_case_id: int) -> None:
        self.test_case_id = test_case_id
        super().__init__(f"test case {test_case_id} is not an active version")


class TestRunCaseRoleMismatch(ValueError):  # noqa: N818 - stable public domain name
    """The case belongs to another role than the one being run (C22)."""

    __test__ = False

    def __init__(self, test_case_id: int) -> None:
        self.test_case_id = test_case_id
        super().__init__(f"test case {test_case_id} belongs to another role")


class TestRunNotFound(LookupError):  # noqa: N818 - stable public domain name
    __test__ = False

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"test run {run_id} does not exist")


@dataclass(frozen=True)
class _CaseSnapshot:
    id: int
    version: int
    synthetic_payload: dict[str, Any]
    design_system_active: bool


@dataclass(frozen=True)
class _StoredBaseline:
    raw_output: dict[str, Any] | None
    structured_output: dict[str, Any] | None


@dataclass(frozen=True)
class _RunIdentity:
    """What ran, copied before the model call and inserted verbatim after it."""

    run_kind: RunKind
    agent_key: str
    candidate_hash: str
    compared_release_id: int
    compared_definition_revision_id: int


@dataclass(frozen=True)
class _Execution:
    status: ExecutionStatus
    error_detail: str | None
    checks: tuple[DeterministicCheckResult, ...]
    raw_output: dict[str, Any] | None
    structured_output: dict[str, Any] | None
    assembled_prompt: str | None
    latency_ms: float | None


def _structured_output(result: AgentInvocationResult) -> dict[str, Any]:
    """C15: the canonical output plus the validated optional fields."""
    document = result.output.model_dump(mode="json")
    document.update(
        to_jsonable_python(thaw_json_containers(result.diagnostics.additional_fields))
    )
    return document


def _checks(
    status: ExecutionStatus, error: Exception | None
) -> tuple[DeterministicCheckResult, ...]:
    """C17: one check, from the runtime's single validation; no re-validation."""
    if status == "completed":
        return (DeterministicCheckResult("output_contract", True, None, ()),)
    if status == "incomplete":
        issues: tuple[DeterministicCheckIssue, ...] = ()
        if isinstance(error, AgentOutputValidationError):
            issues = tuple(
                DeterministicCheckIssue(
                    code=issue.code,
                    field=".".join(str(part) for part in issue.path) or None,
                )
                for issue in error.issues
            )
        return (
            DeterministicCheckResult(
                "output_contract", False, _CONTRACT_FAILED_MESSAGE, issues
            ),
        )
    return (DeterministicCheckResult("execution", False, _NO_OUTPUT_MESSAGE, ()),)


def _checks_document(checks: tuple[DeterministicCheckResult, ...]) -> list[dict[str, Any]]:
    return [
        {
            "name": check.name,
            "passed": check.passed,
            "message": check.message,
            "issues": [{"code": issue.code, "field": issue.field} for issue in check.issues],
        }
        for check in checks
    ]


def _checks_from_document(document: list[dict[str, Any]]) -> tuple[DeterministicCheckResult, ...]:
    return tuple(
        DeterministicCheckResult(
            name=check["name"],
            passed=check["passed"],
            message=check["message"],
            issues=tuple(
                DeterministicCheckIssue(code=issue["code"], field=issue["field"])
                for issue in check["issues"]
            ),
        )
        for check in document
    )


def _execution_from_outcome(
    status: ExecutionStatus,
    error_detail: str | None,
    error: Exception | None,
    *,
    result: AgentInvocationResult | None,
    raw_output: Mapping[str, Any] | None,
    observation: RunObservation,
) -> _Execution:
    completed = status == "completed" and result is not None
    return _Execution(
        status=status,
        error_detail=error_detail,
        checks=_checks(status, error),
        raw_output=dict(raw_output) if raw_output is not None else None,
        structured_output=_structured_output(result) if completed else None,
        assembled_prompt=(
            result.diagnostics.assembled_prompt if completed else observation.prompt
        ),
        latency_ms=(
            result.diagnostics.latency_ms if completed else observation.model_latency_ms
        ),
    )


def _evidence_from_row(
    row: AgentTestRun,
    *,
    synthetic_payload: dict[str, Any],
    candidate_is_current: bool | None = None,
    base_release_is_current: bool | None = None,
) -> TestRunEvidence:
    return TestRunEvidence(
        run_id=row.id,
        run_kind=row.run_kind,
        test_case_id=row.test_case_id,
        test_case_version=row.test_case_version,
        agent_key=row.agent_key,
        candidate_hash=row.candidate_hash,
        compared_release_id=row.compared_release_id,
        compared_definition_revision_id=row.compared_definition_revision_id,
        synthetic_payload=_copy_json(synthetic_payload),
        model_payload=row.model_payload,
        assembled_prompt=row.assembled_prompt,
        execution_status=row.execution_status,
        error_detail=row.error_detail,
        deterministic_checks_passed=row.deterministic_checks_passed,
        deterministic_check_results=_checks_from_document(row.deterministic_check_results),
        candidate_raw_output=row.candidate_raw_output,
        candidate_structured_output=row.candidate_structured_output,
        baseline_raw_output=row.baseline_raw_output,
        baseline_structured_output=row.baseline_structured_output,
        latency_ms=row.latency_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        run_by=row.run_by,
        run_at=row.run_at,
        candidate_is_current=candidate_is_current,
        base_release_is_current=base_release_is_current,
    )


def _unavailable(phase: str, agent_key: str, error: Exception) -> TestRunUnavailable:
    """Log the phase and class only: provider or driver text is never logged."""
    logger.warning(
        "agent_test_run_unavailable",
        extra={
            "agent_key": agent_key,
            "phase": phase,
            "error_class": type(error).__name__,
        },
    )
    return TestRunUnavailable(phase)


class AgentTestWorkbench:
    """Administrator operations on Agent Test Cases and their test runs."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime | None = None,
        graph_configuration: GraphConfiguration | None = None,
    ) -> None:
        """``runtime`` defaults to the bounded ``get_agent_test_runtime()`` (C33),
        resolved at the first run so constructing a workbench builds nothing."""
        self._runtime_override = runtime
        self._graph_configuration = graph_configuration or GraphConfiguration()

    # --- reads -----------------------------------------------------------

    def list_test_cases(
        self,
        session: Session,
        *,
        agent_key: str | None = None,
        include_inactive: bool = False,
    ) -> list[TestCaseVersion]:
        if agent_key is not None:
            issues = _agent_key_issues(agent_key)
            if issues:
                raise TestCaseRejected(*issues)
        with session.begin():
            statement = select(AgentTestCase)
            if agent_key is not None:
                statement = statement.where(AgentTestCase.agent_key == agent_key)
            if not include_inactive:
                statement = statement.where(AgentTestCase.is_active.is_(True))
            rows = [TestCaseVersion.from_row(row) for row in session.scalars(statement)]
        role_order = {key: index for index, key in enumerate(GRAPH_V1_AGENT_KEYS)}
        return sorted(
            rows,
            key=lambda case: (role_order[case.agent_key], case.name, case.version, case.id),
        )

    # --- writes ----------------------------------------------------------

    def create_test_case(
        self,
        session: Session,
        *,
        agent_key: str,
        name: str,
        synthetic_payload: dict[str, Any],
        assembly_context: dict[str, bool],
        is_required: bool,
        actor: str,
    ) -> TestCaseVersion:
        issues = _actor_issues(actor)
        if issues:
            raise TestCaseRejected(*issues)
        issues = _agent_key_issues(agent_key)
        if issues:
            raise TestCaseRejected(*issues)
        issues = [
            *_name_issues(name),
            *_content_issues(
                synthetic_payload=synthetic_payload,
                assembly_context=assembly_context,
                is_required=is_required,
            ),
        ]
        if issues:
            raise TestCaseRejected(*issues)
        trimmed = name.strip()
        try:
            with session.begin():
                # A create can never reduce required coverage; it takes the role
                # lock only so every case write is serialized per role.  Every
                # lineage keeps its version-1 row forever, so a reused name is
                # refused by ``uq_agent_test_case_agent_name_version`` below.
                _lock_role_rows(session, agent_key)
                row = AgentTestCase(
                    agent_key=agent_key,
                    name=trimmed,
                    version=1,
                    is_active=True,
                    is_required=is_required,
                    synthetic_payload=_copy_json(synthetic_payload),
                    assembly_context=dict(assembly_context),
                    created_by=actor,
                    updated_by=actor,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return TestCaseVersion.from_row(row)
        except IntegrityError as error:
            if _is_version_collision(error):
                raise TestCaseRejected(
                    TestCaseIssue(
                        "name",
                        "duplicate_name",
                        "This role already has a test case with this name.",
                    )
                ) from error
            raise

    def update_test_case(
        self,
        session: Session,
        *,
        test_case_id: int,
        synthetic_payload: dict[str, Any],
        assembly_context: dict[str, bool],
        is_required: bool,
        actor: str,
        name: str | None = None,
    ) -> TestCaseVersion:
        """Supersede the active version ``test_case_id`` with ``version + 1``.

        The retirement and the insert commit together or not at all.  Content
        identical to the current version returns it unchanged.
        """
        issues = _actor_issues(actor)
        if issues:
            raise TestCaseRejected(*issues)
        content_issues = _content_issues(
            synthetic_payload=synthetic_payload,
            assembly_context=assembly_context,
            is_required=is_required,
        )
        try:
            with session.begin():
                rows, old = self._lock_role_of(session, test_case_id)
                issues = list(content_issues)
                if name is not None:
                    name_issues = _name_issues(name)
                    if not name_issues and name.strip() != old.name:
                        name_issues = [
                            TestCaseIssue(
                                "name",
                                "name_immutable",
                                "A test case name cannot be changed.",
                            )
                        ]
                    issues.extend(name_issues)
                if (
                    old.is_active
                    and old.is_required
                    and is_required is False
                    and _active_required_count(rows) == 1
                ):
                    issues.append(_last_required_issue("is_required"))
                if issues:
                    raise TestCaseRejected(*issues)
                if not old.is_active:
                    raise TestCaseStale(test_case_id)
                # An identical save is a no-op: no retire, no new version, and
                # no approval of the current version orphaned.
                if (
                    is_required is old.is_required
                    and _canonical_json(synthetic_payload)
                    == _canonical_json(old.synthetic_payload)
                    and _canonical_json(assembly_context)
                    == _canonical_json(old.assembly_context)
                ):
                    return TestCaseVersion.from_row(old)

                old.is_active = False
                old.updated_by = actor
                old.updated_at = func.now()
                # Retire before inserting: the old row must never be active at
                # the same time as its successor, even inside the transaction.
                session.flush()
                successor = AgentTestCase(
                    agent_key=old.agent_key,
                    name=old.name,
                    version=old.version + 1,
                    is_active=True,
                    is_required=is_required,
                    synthetic_payload=_copy_json(synthetic_payload),
                    assembly_context=dict(assembly_context),
                    created_by=actor,
                    updated_by=actor,
                )
                session.add(successor)
                session.flush()
                session.refresh(successor)
                return TestCaseVersion.from_row(successor)
        except IntegrityError as error:
            if _is_version_collision(error):
                raise TestCaseStale(test_case_id) from error
            raise

    def deactivate_test_case(
        self,
        session: Session,
        *,
        test_case_id: int,
        actor: str,
    ) -> TestCaseVersion:
        """Retire one version.  Retiring an already inactive version is a no-op."""
        issues = _actor_issues(actor)
        if issues:
            raise TestCaseRejected(*issues)
        with session.begin():
            rows, row = self._lock_role_of(session, test_case_id)
            if not row.is_active:
                return TestCaseVersion.from_row(row)
            if row.is_required and _active_required_count(rows) == 1:
                raise TestCaseRejected(_last_required_issue("is_active"))
            row.is_active = False
            row.updated_by = actor
            row.updated_at = func.now()
            session.flush()
            session.refresh(row)
            return TestCaseVersion.from_row(row)

    @staticmethod
    def _lock_role_of(
        session: Session, test_case_id: int
    ) -> tuple[list[AgentTestCase], AgentTestCase]:
        # ``agent_key`` never changes on a row, so an unlocked column read is
        # enough to find the role to lock.  No entity is loaded here, so the
        # locked re-read below cannot be served stale from the identity map.
        agent_key = session.scalar(
            select(AgentTestCase.agent_key).where(AgentTestCase.id == test_case_id)
        )
        if agent_key is None:
            raise TestCaseNotFound(test_case_id)
        _lock_role_rows(session, agent_key)
        rows = _reread_role_rows(session, agent_key)
        row = next((candidate for candidate in rows if candidate.id == test_case_id), None)
        if row is None:  # pragma: no cover - rows are never deleted by any writer
            raise TestCaseNotFound(test_case_id)
        return rows, row

    # --- test runs (Task 4) ----------------------------------------------

    def execute_candidate_run(
        self,
        session: Session,
        *,
        agent_key: str,
        test_case_id: int,
        expected_lock_version: int,
        actor: str,
    ) -> TestRunEvidence | DraftSaveConflict[None]:
        """Run one active case version against the role's saved draft candidate.

        ``expected_lock_version`` pins the candidate on the admin's screen: a
        stale lock is the probe's null-candidate conflict, with no model call
        and no row (C32).
        """
        self._require_no_transaction(session)
        self._require_actor(actor)
        session.expire_all()
        # Transaction 1a: #266's probe read (lock and role checks, one short
        # FOR SHARE transaction, the stale-lock conflict, the endpoint policy).
        try:
            candidate = self._graph_configuration.read_draft_test_candidate(
                session, agent_key=agent_key, expected_lock_version=expected_lock_version
            )
        except SQLAlchemyError as error:
            raise _unavailable("read_candidate", agent_key, error) from error
        if isinstance(candidate, DraftSaveConflict):
            return candidate
        identity = _RunIdentity(
            run_kind="candidate",
            agent_key=agent_key,
            candidate_hash=candidate.candidate_hash,
            compared_release_id=candidate.base_release_id,
            compared_definition_revision_id=candidate.base_revision_id,
        )
        # Transaction 1b: the case version and the stored baseline.  Both are
        # immutable rows; only ``is_active`` can change, and transaction 2
        # re-reads it.
        case, baseline = self._read_case_and_baseline(
            session,
            agent_key=agent_key,
            test_case_id=test_case_id,
            baseline_revision_id=candidate.base_revision_id,
        )
        model_payload = model_payload_for(agent_key, case.synthetic_payload)
        observation = RunObservation()

        if session.in_transaction():  # pragma: no cover - C8 invariant
            raise RuntimeError("a test run must not hold a transaction across the model call")
        try:
            outcome = self._runtime().run_candidate(
                agent_key,
                candidate.content,
                candidate.candidate_hash,
                model_payload,
                AgentAssemblyContext(design_system_active=case.design_system_active),
                observation=observation,
            )
        except (UnknownAgentKeyError, ValueError) as error:
            # run_candidate's own caller checks (C16): the snapshot copy cannot
            # normally trip them, so this is an assembly error, not a 500.
            execution = _execution_from_outcome(
                "assembly_error",
                "invalid_candidate",
                error,
                result=None,
                raw_output=None,
                observation=observation,
            )
        else:
            execution = _execution_from_outcome(
                outcome.status,
                outcome.error_detail,
                outcome.error,
                result=outcome.result,
                raw_output=outcome.raw_output,
                observation=observation,
            )
        return self._persist_run(
            session,
            identity=identity,
            case=case,
            model_payload=model_payload,
            execution=execution,
            baseline=baseline,
            actor=actor,
        )

    def execute_baseline_rerun(
        self,
        session: Session,
        *,
        agent_key: str,
        test_case_id: int,
        actor: str,
    ) -> TestRunEvidence:
        """Rerun one active case version against the active published definition.

        It goes through ``AgentRuntime.run_published_baseline`` on the active
        release, which resolves exactly as ``run`` does (C20), and is persisted
        as ``published_baseline`` evidence whose ``candidate_*`` columns hold its
        output.
        """
        self._require_no_transaction(session)
        self._require_actor(actor)
        issues = _agent_key_issues(agent_key)
        if issues:
            raise TestCaseRejected(*issues)
        session.expire_all()
        try:
            with session.begin():
                snapshot = self._graph_configuration.read_workbench(session)
                node = next(
                    node
                    for node in snapshot.nodes
                    if node.execution_kind == "model" and node.agent_key == agent_key
                )
                identity = _RunIdentity(
                    run_kind="published_baseline",
                    agent_key=agent_key,
                    candidate_hash=node.published.content_hash,
                    compared_release_id=snapshot.active_release.release_id,
                    compared_definition_revision_id=node.published.revision_id,
                )
                case = self._load_active_case(
                    session, agent_key=agent_key, test_case_id=test_case_id
                )
        except SQLAlchemyError as error:
            raise _unavailable("read_published", agent_key, error) from error
        model_payload = model_payload_for(agent_key, case.synthetic_payload)
        observation = RunObservation()

        if session.in_transaction():  # pragma: no cover - C8 invariant
            raise RuntimeError("a test run must not hold a transaction across the model call")
        try:
            outcome = self._runtime().run_published_baseline(
                agent_key,
                identity.compared_release_id,
                model_payload,
                AgentAssemblyContext(design_system_active=case.design_system_active),
                observation=observation,
            )
        except PersistedConfigurationUnavailableError as error:
            # A resolution failure, raised exactly as ``run`` raises it.
            if error.code == "lakebase_unavailable":
                raise _unavailable("resolve_published", agent_key, error) from error
            execution = _execution_from_outcome(
                "assembly_error",
                error.code,
                error,
                result=None,
                raw_output=None,
                observation=observation,
            )
        except (GraphReleaseNotFoundError, GraphReleaseIncompleteError) as error:
            execution = _execution_from_outcome(
                "assembly_error",
                "invalid_persisted_definition",
                error,
                result=None,
                raw_output=None,
                observation=observation,
            )
        else:
            execution = _execution_from_outcome(
                outcome.status,
                outcome.error_detail,
                outcome.error,
                result=outcome.result,
                raw_output=outcome.raw_output,
                observation=observation,
            )
        return self._persist_run(
            session,
            identity=identity,
            case=case,
            model_payload=model_payload,
            execution=execution,
            baseline=None,
            actor=actor,
        )

    def get_test_run(self, session: Session, *, run_id: int) -> TestRunEvidence:
        with session.begin():
            row = session.get(AgentTestRun, run_id, populate_existing=True)
            if row is None:
                raise TestRunNotFound(run_id)
            synthetic_payload = session.scalar(
                select(AgentTestCase.synthetic_payload).where(
                    AgentTestCase.id == row.test_case_id
                )
            )
            return _evidence_from_row(row, synthetic_payload=synthetic_payload)

    def list_test_runs(
        self, session: Session, *, test_case_id: int, limit: int = 20
    ) -> list[TestRunEvidence]:
        """One case version's runs, newest first."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RUN_LIST_LIMIT
        ):
            raise ValueError(f"limit must be an integer from 1 to {MAX_RUN_LIST_LIMIT}")
        with session.begin():
            synthetic_payload = session.scalar(
                select(AgentTestCase.synthetic_payload).where(
                    AgentTestCase.id == test_case_id
                )
            )
            rows = session.scalars(
                select(AgentTestRun)
                .where(AgentTestRun.test_case_id == test_case_id)
                .order_by(AgentTestRun.run_at.desc(), AgentTestRun.id.desc())
                .limit(limit)
                .execution_options(populate_existing=True)
            ).all()
            return [
                _evidence_from_row(row, synthetic_payload=synthetic_payload) for row in rows
            ]

    # --- test run internals ----------------------------------------------

    def _runtime(self) -> AgentRuntime:
        if self._runtime_override is not None:
            return self._runtime_override
        return get_agent_test_runtime()

    @staticmethod
    def _require_no_transaction(session: Session) -> None:
        if session.in_transaction():
            raise RuntimeError(
                "a test run owns its transactions; call it with no transaction open"
            )

    @staticmethod
    def _require_actor(actor: object) -> None:
        issues = _actor_issues(actor)
        if issues:
            raise TestCaseRejected(*issues)

    @staticmethod
    def _load_active_case(
        session: Session, *, agent_key: str, test_case_id: int
    ) -> _CaseSnapshot:
        row = session.scalar(
            select(AgentTestCase)
            .where(AgentTestCase.id == test_case_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise TestCaseNotFound(test_case_id)
        if row.agent_key != agent_key:
            raise TestRunCaseRoleMismatch(test_case_id)
        if not row.is_active:
            raise TestRunCaseInactive(test_case_id)
        return _CaseSnapshot(
            id=row.id,
            version=row.version,
            synthetic_payload=_copy_json(row.synthetic_payload),
            design_system_active=bool(row.assembly_context["design_system_active"]),
        )

    def _read_case_and_baseline(
        self,
        session: Session,
        *,
        agent_key: str,
        test_case_id: int,
        baseline_revision_id: int,
    ) -> tuple[_CaseSnapshot, _StoredBaseline | None]:
        try:
            with session.begin():
                case = self._load_active_case(
                    session, agent_key=agent_key, test_case_id=test_case_id
                )
                # C20: never a candidate row, never a failed run, never another
                # case version's or another revision's run.  No verdict is read.
                stored = session.execute(
                    select(
                        AgentTestRun.candidate_raw_output,
                        AgentTestRun.candidate_structured_output,
                    )
                    .where(
                        AgentTestRun.run_kind == "published_baseline",
                        AgentTestRun.test_case_id == case.id,
                        AgentTestRun.agent_key == agent_key,
                        AgentTestRun.compared_definition_revision_id
                        == baseline_revision_id,
                        AgentTestRun.execution_status == "completed",
                    )
                    .order_by(AgentTestRun.run_at.desc(), AgentTestRun.id.desc())
                    .limit(1)
                ).first()
        except SQLAlchemyError as error:
            raise _unavailable("read_case", agent_key, error) from error
        baseline = (
            _StoredBaseline(raw_output=stored[0], structured_output=stored[1])
            if stored is not None
            else None
        )
        return case, baseline

    def _persist_run(
        self,
        session: Session,
        *,
        identity: _RunIdentity,
        case: _CaseSnapshot,
        model_payload: dict[str, Any],
        execution: _Execution,
        baseline: _StoredBaseline | None,
        actor: str,
    ) -> TestRunEvidence:
        """Transaction 2: release then draft ``FOR SHARE``, then the one insert.

        A publication committing while this waited surfaces as the handoff
        diagnosis, retried once (C8.6).  Any other failure writes nothing and is
        ``TestRunUnavailable``; the model is never called again.
        """
        for attempt in (1, 2):
            try:
                with session.begin():
                    session.expire_all()
                    release, _draft = self._graph_configuration._lock_current_parents(
                        session, exclusive=False
                    )
                    candidate_is_current, base_release_is_current = self._currency(
                        session, identity=identity, case=case, active_release_id=release.id
                    )
                    row = AgentTestRun(
                        test_case_id=case.id,
                        test_case_version=case.version,
                        agent_key=identity.agent_key,
                        run_kind=identity.run_kind,
                        candidate_hash=identity.candidate_hash,
                        compared_release_id=identity.compared_release_id,
                        compared_definition_revision_id=identity.compared_definition_revision_id,
                        model_payload=model_payload,
                        assembled_prompt=execution.assembled_prompt,
                        candidate_raw_output=execution.raw_output,
                        candidate_structured_output=execution.structured_output,
                        baseline_raw_output=baseline.raw_output if baseline else None,
                        baseline_structured_output=(
                            baseline.structured_output if baseline else None
                        ),
                        deterministic_check_results=_checks_document(execution.checks),
                        deterministic_checks_passed=(
                            execution.status == "completed"
                            and all(check.passed for check in execution.checks)
                        ),
                        execution_status=execution.status,
                        error_detail=execution.error_detail,
                        latency_ms=execution.latency_ms,
                        input_tokens=None,
                        output_tokens=None,
                        run_by=actor,
                    )
                    session.add(row)
                    session.flush()
                    session.refresh(row)
                    return _evidence_from_row(
                        row,
                        synthetic_payload=case.synthetic_payload,
                        candidate_is_current=candidate_is_current,
                        base_release_is_current=base_release_is_current,
                    )
            except GraphConfigurationIntegrityError as error:
                if attempt == 1 and str(error) == _PARENT_HANDOFF_DIAGNOSIS:
                    continue
                raise _unavailable("persist", identity.agent_key, error) from error
            except SQLAlchemyError as error:
                raise _unavailable("persist", identity.agent_key, error) from error
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _currency(
        session: Session,
        *,
        identity: _RunIdentity,
        case: _CaseSnapshot,
        active_release_id: int,
    ) -> tuple[bool, bool]:
        """C8.5: did what ran stay current while the model was called?"""
        case_active = session.scalar(
            select(AgentTestCase.is_active).where(AgentTestCase.id == case.id)
        )
        if identity.run_kind == "candidate":
            current_hash = session.scalar(
                select(GraphDraftAgent.candidate_hash).where(
                    GraphDraftAgent.agent_key == identity.agent_key
                )
            )
            base_release_id = session.scalar(select(GraphDraft.base_release_id))
            same_candidate = current_hash == identity.candidate_hash
        else:
            current_revision = session.scalar(
                select(GraphReleaseAgent.agent_definition_revision_id).where(
                    GraphReleaseAgent.graph_release_id == active_release_id,
                    GraphReleaseAgent.agent_key == identity.agent_key,
                )
            )
            base_release_id = active_release_id
            same_candidate = current_revision == identity.compared_definition_revision_id
        return (
            bool(same_candidate and case_active),
            base_release_id == identity.compared_release_id,
        )
