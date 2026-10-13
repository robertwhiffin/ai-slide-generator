"""Constrained persistence aggregate for versioned graph configuration.

Fresh-table DDL has one source of truth: these ORM tables. PostgreSQL mutation
guards for published artifacts are installed by :func:`src.core.database._run_migrations`.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declared_attr, mapped_column

from src.core.database import Base

GRAPH_AGENT_KEY_CHECK = (
    "agent_key IN ('architect', 'data_analyst', 'builder', 'build_reviewer', "
    "'fixer', 'fix_reviewer', 'deck_reviewer')"
)
_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
# Evidence columns bind Python ``None`` as SQL NULL, not the JSON ``'null'`` literal
# that plain JSON stores. Otherwise ``None`` would satisfy NOT NULL and slip past the
# ``IS NOT NULL`` / ``IS NULL`` checks and every query that reads absent output.
_EVIDENCE_JSON_DOCUMENT = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True), "postgresql"
)

DEFINITION_CONTENT_COLUMN_NAMES = (
    "agent_key",
    "definition_version",
    "prompt_text",
    "endpoint_name",
    "temperature",
    "max_tokens",
    "top_p",
    "schema_overlay",
    "assembly_rules",
    "protected_assembly_version",
    "protected_assembly_digest",
    "schema_contract_version",
    "schema_contract_digest",
)


def _definition_checks(table_name: str, hash_column: str) -> tuple[CheckConstraint, ...]:
    """Return the identical semantic checks shared by revision and draft rows."""
    hash_label = "content_hash" if hash_column == "content_hash" else "candidate_hash"
    return (
        CheckConstraint(
            GRAPH_AGENT_KEY_CHECK,
            name=f"ck_{table_name}_agent_key",
        ),
        CheckConstraint(
            "definition_version > 0",
            name=f"ck_{table_name}_definition_version_positive",
        ),
        CheckConstraint(
            f"length({hash_column}) = 64",
            name=f"ck_{table_name}_{hash_label}_length",
        ),
        CheckConstraint(
            "length(trim(prompt_text)) > 0",
            name=f"ck_{table_name}_prompt_nonblank",
        ),
        CheckConstraint(
            "length(trim(endpoint_name)) > 0",
            name=f"ck_{table_name}_endpoint_nonblank",
        ),
        CheckConstraint(
            "temperature >= 0 AND temperature <= 1",
            name=f"ck_{table_name}_temperature_range",
        ),
        CheckConstraint(
            "max_tokens > 0",
            name=f"ck_{table_name}_max_tokens_positive",
        ),
        CheckConstraint(
            "top_p >= 0 AND top_p <= 1",
            name=f"ck_{table_name}_top_p_range",
        ),
        CheckConstraint(
            "protected_assembly_version > 0",
            name=f"ck_{table_name}_protected_version_positive",
        ),
        CheckConstraint(
            "length(protected_assembly_digest) = 64",
            name=f"ck_{table_name}_protected_digest_length",
        ),
        CheckConstraint(
            "schema_contract_version > 0",
            name=f"ck_{table_name}_schema_version_positive",
        ),
        CheckConstraint(
            "length(schema_contract_digest) = 64",
            name=f"ck_{table_name}_schema_digest_length",
        ),
    )


def _definition_content_column(
    column_type,
    *,
    sort_order: int | None,
    agent_key: bool = False,
):
    @declared_attr
    def column(cls):
        resolved_sort_order = (
            cls.__definition_version_sort_order__
            if sort_order is None
            else sort_order
        )
        return mapped_column(
            column_type,
            nullable=False,
            primary_key=agent_key and cls.__definition_agent_key_primary_key__,
            sort_order=resolved_sort_order,
        )

    return column


class DefinitionContentColumns:
    """The one SQLAlchemy column shape shared by revisions and draft candidates."""

    __definition_agent_key_primary_key__ = False
    __definition_version_sort_order__ = 20

    agent_key = _definition_content_column(String(32), sort_order=10, agent_key=True)
    definition_version = _definition_content_column(Integer, sort_order=None)
    prompt_text = _definition_content_column(Text, sort_order=40)
    endpoint_name = _definition_content_column(Text, sort_order=50)
    temperature = _definition_content_column(Numeric(7, 6), sort_order=60)
    max_tokens = _definition_content_column(Integer, sort_order=70)
    top_p = _definition_content_column(Numeric(7, 6), sort_order=80)
    schema_overlay = _definition_content_column(_JSON_DOCUMENT, sort_order=90)
    assembly_rules = _definition_content_column(_JSON_DOCUMENT, sort_order=100)
    protected_assembly_version = _definition_content_column(Integer, sort_order=110)
    protected_assembly_digest = _definition_content_column(String(64), sort_order=120)
    schema_contract_version = _definition_content_column(Integer, sort_order=130)
    schema_contract_digest = _definition_content_column(String(64), sort_order=140)


class AgentDefinitionRevision(DefinitionContentColumns, Base):
    """One immutable semantic revision for a model-driven graph role."""

    __tablename__ = "agent_definition_revision"

    id = mapped_column(Integer, primary_key=True, sort_order=0)
    content_hash = mapped_column(String(64), nullable=False, sort_order=30)
    created_by = mapped_column(Text, nullable=False, sort_order=150)
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        sort_order=160,
    )

    __table_args__ = (
        *_definition_checks(__tablename__, "content_hash"),
        CheckConstraint(
            "length(trim(created_by)) > 0",
            name="ck_agent_definition_revision_created_by_nonblank",
        ),
        UniqueConstraint(
            "agent_key",
            "content_hash",
            name="uq_agent_definition_revision_agent_hash",
        ),
        UniqueConstraint(
            "id",
            "agent_key",
            name="uq_agent_definition_revision_id_agent",
        ),
    )


class GraphRelease(Base):
    """One immutable graph publication and its one-way SCD2 active interval."""

    __tablename__ = "graph_release"

    id = Column(Integer, primary_key=True)
    version_number = Column(Integer, nullable=False)
    previous_release_id = Column(Integer, nullable=True)
    restored_from_release_id = Column(Integer, nullable=True)
    release_note = Column(Text, nullable=False)
    published_by = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_from = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_to = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["previous_release_id"],
            ["graph_release.id"],
            name="fk_graph_release_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restored_from_release_id"],
            ["graph_release.id"],
            name="fk_graph_release_restored_from",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_graph_release_version_positive",
        ),
        CheckConstraint(
            "length(trim(release_note)) > 0",
            name="ck_graph_release_note_nonblank",
        ),
        CheckConstraint(
            "length(trim(published_by)) > 0",
            name="ck_graph_release_published_by_nonblank",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_graph_release_interval",
        ),
        UniqueConstraint("version_number", name="uq_graph_release_version_number"),
        Index(
            "uq_graph_release_one_active",
            text("(1)"),
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )


class GraphReleaseAgent(Base):
    """Role-compatible revision mapping for one complete graph release."""

    __tablename__ = "graph_release_agent"

    graph_release_id = Column(Integer, primary_key=True)
    agent_key = Column(String(32), primary_key=True)
    agent_definition_revision_id = Column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_release_id"],
            ["graph_release.id"],
            name="fk_graph_release_agent_release",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_definition_revision_id", "agent_key"],
            ["agent_definition_revision.id", "agent_definition_revision.agent_key"],
            name="fk_graph_release_agent_compatible_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            GRAPH_AGENT_KEY_CHECK,
            name="ck_graph_release_agent_agent_key",
        ),
    )


class GraphDraft(Base):
    """The singleton shared draft parent and optimistic concurrency token."""

    __tablename__ = "graph_draft"

    id = Column(SmallInteger, primary_key=True)
    base_release_id = Column(Integer, nullable=False)
    lock_version = Column(Integer, nullable=False, server_default=text("0"))
    updated_by = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["base_release_id"],
            ["graph_release.id"],
            name="fk_graph_draft_base_release",
            ondelete="RESTRICT",
        ),
        CheckConstraint("id = 1", name="ck_graph_draft_singleton"),
        CheckConstraint(
            "lock_version >= 0",
            name="ck_graph_draft_lock_version_nonnegative",
        ),
        CheckConstraint(
            "length(trim(updated_by)) > 0",
            name="ck_graph_draft_updated_by_nonblank",
        ),
    )


class GraphDraftAgent(DefinitionContentColumns, Base):
    """Mutable candidate content for one role in the singleton draft."""

    __tablename__ = "graph_draft_agent"
    __definition_agent_key_primary_key__ = True
    __definition_version_sort_order__ = 30

    graph_draft_id = mapped_column(SmallInteger, primary_key=True, sort_order=0)
    candidate_hash = mapped_column(String(64), nullable=False, sort_order=20)

    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_draft_id"],
            ["graph_draft.id"],
            name="fk_graph_draft_agent_draft",
            ondelete="RESTRICT",
        ),
        *_definition_checks(__tablename__, "candidate_hash"),
    )


class AgentTestCase(Base):
    """Versioned synthetic smoke input for one editable role."""

    __tablename__ = "agent_test_case"

    id = Column(Integer, primary_key=True)
    agent_key = Column(String(32), nullable=False)
    name = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())
    is_required = Column(Boolean, nullable=False, default=True, server_default=true())
    synthetic_payload = Column(_JSON_DOCUMENT, nullable=False)
    assembly_context = Column(_JSON_DOCUMENT, nullable=False)
    created_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            GRAPH_AGENT_KEY_CHECK,
            name="ck_agent_test_case_agent_key",
        ),
        CheckConstraint("version > 0", name="ck_agent_test_case_version_positive"),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_agent_test_case_name_nonblank",
        ),
        CheckConstraint(
            "length(trim(created_by)) > 0",
            name="ck_agent_test_case_created_by_nonblank",
        ),
        CheckConstraint(
            "length(trim(updated_by)) > 0",
            name="ck_agent_test_case_updated_by_nonblank",
        ),
        UniqueConstraint(
            "agent_key",
            "name",
            "version",
            name="uq_agent_test_case_agent_name_version",
        ),
    )


class AgentTestRun(Base):
    """Immutable evidence row for one isolated candidate or published-baseline run.

    Only the four verdict columns may change after insert; #268 writes them, and a
    PostgreSQL trigger installed by ``_run_migrations`` rejects every other update.
    """

    __tablename__ = "agent_test_run"

    id = Column(Integer, primary_key=True)

    # Case version that was run: a snapshot, because case versions are immutable.
    test_case_id = Column(Integer, nullable=False)
    test_case_version = Column(Integer, nullable=False)

    # Identity of what ran. A baseline run's candidate_hash is its revision's hash.
    agent_key = Column(String(32), nullable=False)
    run_kind = Column(String(24), nullable=False)
    candidate_hash = Column(String(64), nullable=False)

    # The published release and role-compatible revision this run compares against.
    compared_release_id = Column(Integer, nullable=False)
    compared_definition_revision_id = Column(Integer, nullable=False)

    # Input actually sent: the projected model payload and the assembled prompt,
    # which is absent when assembly failed.
    model_payload = Column(_EVIDENCE_JSON_DOCUMENT, nullable=False)
    assembled_prompt = Column(Text)

    # Outputs, absent when assembly or the model call failed before producing them.
    candidate_raw_output = Column(_EVIDENCE_JSON_DOCUMENT)
    candidate_structured_output = Column(_EVIDENCE_JSON_DOCUMENT)
    baseline_raw_output = Column(_EVIDENCE_JSON_DOCUMENT)
    baseline_structured_output = Column(_EVIDENCE_JSON_DOCUMENT)

    # Always written by the service, so there is deliberately no server default.
    deterministic_check_results = Column(_EVIDENCE_JSON_DOCUMENT, nullable=False)
    deterministic_checks_passed = Column(Boolean, nullable=False, default=False)

    execution_status = Column(String(32), nullable=False)
    error_detail = Column(Text)

    latency_ms = Column(Float)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)

    run_by = Column(Text, nullable=False)
    run_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Verdict columns: #267 owns the DDL, #268 writes them.
    verdict = Column(String(16))
    verdict_reviewer = Column(Text)
    verdict_at = Column(DateTime(timezone=True))
    verdict_notes = Column(Text)

    __table_args__ = (
        ForeignKeyConstraint(
            ["test_case_id"],
            ["agent_test_case.id"],
            name="fk_agent_test_run_test_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["compared_release_id"],
            ["graph_release.id"],
            name="fk_agent_test_run_release",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["compared_definition_revision_id", "agent_key"],
            ["agent_definition_revision.id", "agent_definition_revision.agent_key"],
            name="fk_agent_test_run_compatible_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(GRAPH_AGENT_KEY_CHECK, name="ck_agent_test_run_agent_key"),
        CheckConstraint(
            "test_case_version > 0",
            name="ck_agent_test_run_case_version_positive",
        ),
        CheckConstraint(
            "run_kind IN ('candidate', 'published_baseline')",
            name="ck_agent_test_run_run_kind",
        ),
        CheckConstraint(
            "execution_status IN ('completed', 'model_error', 'assembly_error', 'incomplete')",
            name="ck_agent_test_run_execution_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('approved', 'rejected')",
            name="ck_agent_test_run_verdict_enum",
        ),
        CheckConstraint(
            "(verdict IS NULL) = (verdict_reviewer IS NULL)",
            name="ck_agent_test_run_verdict_reviewer_paired",
        ),
        CheckConstraint(
            "(verdict IS NULL) = (verdict_at IS NULL)",
            name="ck_agent_test_run_verdict_at_paired",
        ),
        CheckConstraint(
            "verdict != 'approved' OR "
            "(execution_status = 'completed' AND deterministic_checks_passed)",
            name="ck_agent_test_run_approved_only_if_completed_and_passing",
        ),
        CheckConstraint(
            "execution_status <> 'completed' OR candidate_structured_output IS NOT NULL",
            name="ck_agent_test_run_completed_has_output",
        ),
        CheckConstraint(
            "length(trim(candidate_hash)) = 64",
            name="ck_agent_test_run_candidate_hash_len",
        ),
        CheckConstraint(
            "length(trim(run_by)) > 0",
            name="ck_agent_test_run_run_by_nonblank",
        ),
        Index("ix_agent_test_run_case_run_at", "test_case_id", "run_at"),
    )


class GraphReleaseTestRun(Base):
    """Links a Graph Release to the run evidence it was published against.

    The link is the retention anchor: its RESTRICT foreign key keeps linked runs
    from being deleted. #269 writes these rows; #267 owns only the DDL.
    """

    __tablename__ = "graph_release_test_run"

    graph_release_id = Column(Integer, primary_key=True, autoincrement=False)
    agent_test_run_id = Column(Integer, primary_key=True, autoincrement=False)
    evidence_kind = Column(String(20), nullable=False)
    source_release_id = Column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_release_id"],
            ["graph_release.id"],
            name="fk_graph_release_test_run_release",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_test_run_id"],
            ["agent_test_run.id"],
            name="fk_graph_release_test_run_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_release_id"],
            ["graph_release.id"],
            name="fk_graph_release_test_run_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "evidence_kind IN ('approval', 'historical_restore')",
            name="ck_graph_release_test_run_evidence_kind",
        ),
        CheckConstraint(
            "(evidence_kind = 'historical_restore') = (source_release_id IS NOT NULL)",
            name="ck_graph_release_test_run_source_paired",
        ),
        # The primary key leads with graph_release_id, so run-side lookups
        # (#268's NOT EXISTS, #269's linked-verdict trigger) need their own index.
        Index("ix_graph_release_test_run_run", "agent_test_run_id"),
    )
