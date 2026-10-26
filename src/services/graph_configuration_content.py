"""Shared semantic-content seam for persisted Graph Configuration definitions.

``DefinitionContent`` is the authoritative backend record.  The field registry in
this module is the only mapping between that nested record and the intentionally
flat revision/draft tables.  Both writers, both readers, hashing validation, and
workbench snapshots cross this seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select

from src.database.models.graph_configuration import (
    DEFINITION_CONTENT_COLUMN_NAMES,
    AgentDefinitionRevision,
    GraphDraftAgent,
)
from src.services.graph_definition_manifest import (
    DefinitionContent,
    definition_content_hash,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class GraphConfigurationIntegrityError(RuntimeError):
    """Persisted graph configuration is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class _PersistedContentField:
    column_name: str
    content_path: tuple[str, ...]
    json_document: bool = False


_PERSISTED_CONTENT_FIELDS = (
    _PersistedContentField("agent_key", ("agent_key",)),
    _PersistedContentField("definition_version", ("definition_version",)),
    _PersistedContentField("prompt_text", ("prompt_text",)),
    _PersistedContentField("endpoint_name", ("model", "endpoint_name")),
    _PersistedContentField("temperature", ("model", "temperature")),
    _PersistedContentField("max_tokens", ("model", "max_tokens")),
    _PersistedContentField("top_p", ("model", "top_p")),
    _PersistedContentField("schema_overlay", ("schema_overlay",), json_document=True),
    _PersistedContentField("assembly_rules", ("assembly_rules",), json_document=True),
    _PersistedContentField(
        "protected_assembly_version", ("protected_assembly", "version")
    ),
    _PersistedContentField(
        "protected_assembly_digest", ("protected_assembly", "digest")
    ),
    _PersistedContentField("schema_contract_version", ("schema_contract", "version")),
    _PersistedContentField("schema_contract_digest", ("schema_contract", "digest")),
)

if tuple(field.column_name for field in _PERSISTED_CONTENT_FIELDS) != (
    DEFINITION_CONTENT_COLUMN_NAMES
):  # pragma: no cover - import-time authoring invariant
    raise RuntimeError("definition content mapping does not match ORM content columns")


def _content_value(content: DefinitionContent, path: tuple[str, ...]) -> object:
    value: object = content
    for segment in path:
        value = getattr(value, segment)
    return value


def definition_content_values(content: DefinitionContent) -> dict[str, object]:
    """Flatten one authoritative content record for either persistence row."""
    values: dict[str, object] = {}
    for field in _PERSISTED_CONTENT_FIELDS:
        value = _content_value(content, field.content_path)
        if field.json_document:
            if not isinstance(value, BaseModel):  # pragma: no cover - registry invariant
                raise TypeError(f"{field.content_path!r} is not a Pydantic model")
            value = value.model_dump(mode="json")
        values[field.column_name] = value
    return values


def definition_content_from_row(
    row: AgentDefinitionRevision | GraphDraftAgent,
) -> DefinitionContent:
    """Rebuild the authoritative content record from either persistence row."""
    payload: dict[str, object] = {}
    for field in _PERSISTED_CONTENT_FIELDS:
        target = payload
        for segment in field.content_path[:-1]:
            child = target.setdefault(segment, {})
            if not isinstance(child, dict):  # pragma: no cover - registry invariant
                raise TypeError(f"content mapping path collision at {segment!r}")
            target = child
        target[field.content_path[-1]] = getattr(row, field.column_name)
    return DefinitionContent.model_validate(payload)


def revision_from_definition(
    definition: DefinitionContent,
    *,
    actor: str,
    timestamp: datetime,
) -> AgentDefinitionRevision:
    """Create an immutable revision row from authoritative semantic content."""
    return AgentDefinitionRevision(
        **definition_content_values(definition),
        content_hash=definition_content_hash(definition),
        created_by=actor,
        created_at=timestamp,
    )


def draft_from_definition(
    definition: DefinitionContent,
    *,
    draft_id: int,
) -> GraphDraftAgent:
    """Create a mutable candidate row from authoritative semantic content."""
    return GraphDraftAgent(
        **definition_content_values(definition),
        graph_draft_id=draft_id,
        candidate_hash=definition_content_hash(definition),
    )


def validate_definition_hash(
    row: AgentDefinitionRevision | GraphDraftAgent,
    *,
    expected_hash: str,
    label: str,
) -> DefinitionContent:
    """Validate persisted semantic content and return its authoritative record."""
    try:
        content = definition_content_from_row(row)
        actual_hash = definition_content_hash(content)
    except (TypeError, ValueError) as exc:
        raise GraphConfigurationIntegrityError(
            f"{label} has invalid semantic content"
        ) from exc
    if actual_hash != expected_hash:
        raise GraphConfigurationIntegrityError(
            f"{label} content hash does not match persisted content"
        )
    return content


def as_utc_aware(value: datetime) -> datetime:
    """Label a naive stored timestamp UTC; return an aware value unchanged.

    SQLite loads ``DateTime(timezone=True)`` columns naive while PostgreSQL loads
    them aware.  This never converts an aware value to another timezone.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def database_transaction_timestamp(session: Session) -> datetime:
    """The one tz-aware transaction timestamp used by every graph-configuration writer."""
    timestamp = session.scalar(select(func.current_timestamp()))
    if timestamp is None:
        raise GraphConfigurationIntegrityError(
            "database did not return a transaction timestamp"
        )
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def materialize_or_reuse_revision(
    session: Session,
    content: DefinitionContent,
    *,
    actor: str,
    timestamp: datetime,
) -> tuple[AgentDefinitionRevision, bool]:
    """Return the immutable revision for ``content`` and whether it was newly added.

    ``True`` means a new revision was added to the session; ``False`` means the
    existing ``(agent_key, content_hash)`` revision is reused after its persisted
    content is re-validated against ``content``.  Never calls ``flush()`` itself;
    the lookup may autoflush revisions added earlier in the same session, which is
    harmless because each is complete.
    """
    content_hash = definition_content_hash(content)
    revision = session.scalar(
        select(AgentDefinitionRevision).where(
            AgentDefinitionRevision.agent_key == content.agent_key,
            AgentDefinitionRevision.content_hash == content_hash,
        )
    )
    if revision is None:
        revision = revision_from_definition(content, actor=actor, timestamp=timestamp)
        session.add(revision)
        return revision, True
    existing = validate_definition_hash(
        revision,
        expected_hash=content_hash,
        label=f"reusable revision {revision.id}",
    )
    if existing.canonical_payload() != content.canonical_payload():
        raise GraphConfigurationIntegrityError(
            f"reusable revision {revision.id} does not match its hash"
        )
    return revision, False
