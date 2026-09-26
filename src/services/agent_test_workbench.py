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

Execution of cases lives elsewhere (Task 4); this module never calls a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.database.models.graph_configuration import AgentTestCase
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

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


class AgentTestWorkbench:
    """Administrator operations on Agent Test Cases (CRUD slice)."""

    def __init__(self) -> None:
        pass

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
