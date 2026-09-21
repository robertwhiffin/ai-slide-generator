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

from src.core.database import Base

GRAPH_AGENT_KEY_CHECK = (
    "agent_key IN ('architect', 'data_analyst', 'builder', 'build_reviewer', "
    "'fixer', 'fix_reviewer', 'deck_reviewer')"
)
_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


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


class AgentDefinitionRevision(Base):
    """One immutable semantic revision for a model-driven graph role."""

    __tablename__ = "agent_definition_revision"

    id = Column(Integer, primary_key=True)
    agent_key = Column(String(32), nullable=False)
    definition_version = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    prompt_text = Column(Text, nullable=False)
    endpoint_name = Column(Text, nullable=False)
    temperature = Column(Numeric(7, 6), nullable=False)
    max_tokens = Column(Integer, nullable=False)
    top_p = Column(Numeric(7, 6), nullable=False)
    schema_overlay = Column(_JSON_DOCUMENT, nullable=False)
    assembly_rules = Column(_JSON_DOCUMENT, nullable=False)
    protected_assembly_version = Column(Integer, nullable=False)
    protected_assembly_digest = Column(String(64), nullable=False)
    schema_contract_version = Column(Integer, nullable=False)
    schema_contract_digest = Column(String(64), nullable=False)
    created_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

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


class GraphDraftAgent(Base):
    """Mutable candidate content for one role in the singleton draft."""

    __tablename__ = "graph_draft_agent"

    graph_draft_id = Column(SmallInteger, primary_key=True)
    agent_key = Column(String(32), primary_key=True)
    candidate_hash = Column(String(64), nullable=False)
    definition_version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    endpoint_name = Column(Text, nullable=False)
    temperature = Column(Numeric(7, 6), nullable=False)
    max_tokens = Column(Integer, nullable=False)
    top_p = Column(Numeric(7, 6), nullable=False)
    schema_overlay = Column(_JSON_DOCUMENT, nullable=False)
    assembly_rules = Column(_JSON_DOCUMENT, nullable=False)
    protected_assembly_version = Column(Integer, nullable=False)
    protected_assembly_digest = Column(String(64), nullable=False)
    schema_contract_version = Column(Integer, nullable=False)
    schema_contract_digest = Column(String(64), nullable=False)

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
