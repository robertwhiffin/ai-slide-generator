"""Test-only loader for the checked-in Graph Version 1 manifest.

``PackagedGraphV1Loader`` serves the packaged bootstrap manifest as ONE synthetic
release, for unit tests only.  ``packaged_v1_runtime`` wraps it in the full
runtime for tests that need a live runtime backed by the known-good v1 definitions.

Neither of these ships in the product: production resolves only persisted Graph
Releases.  These let unit tests drive the full runtime without a database.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.services.agent_runtime import (
    AgentModelAdapter,
    AgentRuntime,
)
from src.services.agent_runtime_identity import (
    AgentInvocationIdentitySink,
    RecordingAgentInvocationIdentitySink,
)
from src.services.graph_definition_manifest import (
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import (
    GraphReleaseNotFoundError,
    ResolvedDefinition,
)

PACKAGED_RELEASE_ID: int = 1
PACKAGED_GRAPH_VERSION: int = 1


class PackagedGraphV1Loader:
    """Serves the packaged bootstrap manifest as ONE synthetic release, for unit tests only."""

    def __init__(
        self,
        *,
        graph_release_id: int = PACKAGED_RELEASE_ID,
        graph_version: int = PACKAGED_GRAPH_VERSION,
        content_overrides: Mapping[str, DefinitionContent] | None = None,
    ) -> None:
        self._graph_release_id = graph_release_id
        self._graph_version = graph_version
        manifest = load_graph_v1_manifest()
        self._contents: dict[str, DefinitionContent] = {
            defn.agent_key: defn for defn in manifest.definitions
        }
        if content_overrides:
            self._contents.update(content_overrides)

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        if graph_release_id != self._graph_release_id:
            raise GraphReleaseNotFoundError(graph_release_id)
        content = self._contents[agent_key]  # KeyError for unknown role
        return ResolvedDefinition(
            graph_version=self._graph_version,
            graph_release_id=self._graph_release_id,
            agent_key=agent_key,
            agent_definition_revision_id=content.definition_version,
            content_hash=definition_content_hash(content),
            content=content,
        )


def packaged_v1_runtime(
    *,
    model_adapter: AgentModelAdapter,
    identity_sink: AgentInvocationIdentitySink | None = None,
    content_overrides: Mapping[str, DefinitionContent] | None = None,
) -> AgentRuntime:
    """Build a runtime backed by the packaged v1 manifest, for unit tests only."""
    return AgentRuntime(
        persisted_release_loader=PackagedGraphV1Loader(content_overrides=content_overrides),
        model_adapter=model_adapter,
        identity_sink=identity_sink or RecordingAgentInvocationIdentitySink(),
    )
