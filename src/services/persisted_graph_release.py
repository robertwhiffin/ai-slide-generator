"""Load one exact, complete immutable persisted graph release."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal, Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    validate_definition_hash,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
)


class PersistedRuntimeError(RuntimeError):
    """Base error for an unavailable immutable persisted runtime."""


#: Attributes the interpreter and the standard library assign on a live
#: exception: ``raise ... from``, ``contextlib`` re-binding the traceback of a
#: ``RuntimeError`` in ``_GeneratorContextManager.__exit__``, and
#: ``BaseException.add_note`` (LangGraph notes the failing task on every error).
_EXCEPTION_RUNTIME_ATTRIBUTES = frozenset(
    {"__traceback__", "__cause__", "__context__", "__suppress_context__", "__notes__"}
)

_ErrorT = TypeVar("_ErrorT", bound=type[BaseException])


def _context_manager_safe(cls: _ErrorT) -> _ErrorT:
    """Keep a frozen dataclass exception's fields read-only, and nothing else.

    A frozen dataclass's ``__setattr__`` refuses EVERY assignment on an instance
    of the class itself, including the interpreter-managed exception attributes.
    (With ``slots=True`` the refusal even surfaces as ``TypeError: super(type,
    obj)``.)  So a typed pinned-runtime error raised inside any
    ``@contextmanager`` -- LangGraph runs every node inside
    ``set_config_context`` -- was replaced by that ``TypeError`` before any
    caller could match it (#271 C52).  This wrapper lets exactly
    :data:`_EXCEPTION_RUNTIME_ATTRIBUTES` through and keeps the dataclass
    refusal for the declared fields.
    """
    frozen_setattr = cls.__setattr__
    frozen_delattr = cls.__delattr__

    def setattr_(self, name: str, value: object) -> None:
        if name in _EXCEPTION_RUNTIME_ATTRIBUTES:
            object.__setattr__(self, name, value)
        else:
            frozen_setattr(self, name, value)

    def delattr_(self, name: str) -> None:
        if name in _EXCEPTION_RUNTIME_ATTRIBUTES:
            object.__delattr__(self, name)
        else:
            frozen_delattr(self, name)

    setattr_.__name__ = "__setattr__"
    delattr_.__name__ = "__delattr__"
    cls.__setattr__ = setattr_  # type: ignore[method-assign]
    cls.__delattr__ = delattr_  # type: ignore[method-assign]
    return cls


class GraphReleaseNotFoundError(PersistedRuntimeError):
    """The exact requested Graph Release does not exist."""


class GraphReleaseIncompleteError(PersistedRuntimeError):
    """The exact requested Graph Release is not a complete role aggregate."""


@_context_manager_safe
@dataclass(frozen=True)
class PersistedConfigurationUnavailableError(PersistedRuntimeError):
    code: Literal[
        "lakebase_unavailable",
        "invalid_persisted_definition",
        "protected_bundle_unavailable",
        "schema_contract_unavailable",
        "conversation_pin_unavailable",
    ]

    def __post_init__(self) -> None:
        PersistedRuntimeError.__init__(self, self.code)

    def __str__(self) -> str:
        return "Persisted graph configuration is unavailable"


@_context_manager_safe
@dataclass(frozen=True)
class PinnedInvocationEndpointError(PersistedRuntimeError):
    endpoint_name: str
    graph_release_id: int
    agent_definition_revision_id: int

    def __post_init__(self) -> None:
        PersistedRuntimeError.__init__(
            self,
            self.endpoint_name,
            self.graph_release_id,
            self.agent_definition_revision_id,
        )

    def __str__(self) -> str:
        return "Pinned graph model endpoint is unavailable"


@dataclass(frozen=True)
class ResolvedDefinition:
    graph_version: int
    graph_release_id: int
    agent_key: str
    agent_definition_revision_id: int
    content_hash: str
    content: DefinitionContent


class ResolvedDefinitionLoader(Protocol):
    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition: ...


_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)


class PersistedGraphReleaseLoader:
    """Resolve role definitions only from an exact validated Graph Release ID."""

    def __init__(self, *, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._cache: dict[int, dict[str, ResolvedDefinition]] = {}

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        return self._load_complete_release(graph_release_id)[agent_key]

    def _load_complete_release(
        self, graph_release_id: int
    ) -> dict[str, ResolvedDefinition]:
        cached = self._cache.get(graph_release_id)
        if cached is not None:
            return cached

        with self._open_session() as session:
            rows = session.execute(
                select(GraphRelease, GraphReleaseAgent, AgentDefinitionRevision)
                .outerjoin(
                    GraphReleaseAgent,
                    GraphReleaseAgent.graph_release_id == GraphRelease.id,
                )
                .outerjoin(
                    AgentDefinitionRevision,
                    AgentDefinitionRevision.id
                    == GraphReleaseAgent.agent_definition_revision_id,
                )
                .where(GraphRelease.id == graph_release_id)
            ).all()

        if not rows:
            raise GraphReleaseNotFoundError(graph_release_id)

        release = rows[0][0]
        try:
            snapshot = self._validate_complete_snapshot(release, rows)
        except GraphConfigurationIntegrityError as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc

        self._cache[graph_release_id] = snapshot
        return snapshot

    @contextmanager
    def _open_session(self) -> Iterator[object]:
        """Open the persistence boundary, translating only factory/open failures."""
        try:
            session_context = self._session_factory()
        except Exception as exc:
            raise PersistedConfigurationUnavailableError(
                code="lakebase_unavailable"
            ) from exc

        try:
            session = session_context.__enter__()
        except Exception as exc:
            raise PersistedConfigurationUnavailableError(
                code="lakebase_unavailable"
            ) from exc

        try:
            yield session
        except BaseException as exc:
            session_context.__exit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            session_context.__exit__(None, None, None)

    @staticmethod
    def _validate_complete_snapshot(
        release: GraphRelease,
        rows: list[tuple[GraphRelease, GraphReleaseAgent | None, AgentDefinitionRevision | None]],
    ) -> dict[str, ResolvedDefinition]:
        mappings = [(mapping, revision) for _release, mapping, revision in rows]
        if any(mapping is None or revision is None for mapping, revision in mappings):
            raise GraphReleaseIncompleteError(release.id)

        typed_mappings = [
            (mapping, revision)
            for mapping, revision in mappings
            if mapping is not None and revision is not None
        ]
        keys = {mapping.agent_key for mapping, _revision in typed_mappings}
        if len(typed_mappings) != len(_EXPECTED_AGENT_KEYS) or keys != _EXPECTED_AGENT_KEYS:
            raise GraphReleaseIncompleteError(release.id)

        snapshot: dict[str, ResolvedDefinition] = {}
        for mapping, revision in typed_mappings:
            if revision.agent_key != mapping.agent_key:
                raise GraphReleaseIncompleteError(release.id)
            content = validate_definition_hash(
                revision,
                expected_hash=revision.content_hash,
                label=f"revision {revision.id}",
            )
            snapshot[mapping.agent_key] = ResolvedDefinition(
                graph_version=release.version_number,
                graph_release_id=release.id,
                agent_key=mapping.agent_key,
                agent_definition_revision_id=revision.id,
                content_hash=revision.content_hash,
                content=content,
            )

        if len(snapshot) != len(_EXPECTED_AGENT_KEYS):
            raise GraphReleaseIncompleteError(release.id)
        return snapshot
