"""Stable external interface for the shared Graph Configuration aggregate.

The implementation is divided by reason to change: bootstrap/write/history
validation and locked workbench reads. Both cross the same semantic-content seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.services.graph_configuration_bootstrap import (
    BootstrapResult,
    _GraphConfigurationBootstrap,
)
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_configuration_draft import (
    DraftAggregateSnapshot,
    DraftCandidateValidator,
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftLegacyPromptSourceRecord,
    DraftSaveConflict,
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    _GraphConfigurationDraft,
)
from src.services.graph_configuration_seed import REQUIRED_SMOKE_PAYLOADS
from src.services.graph_configuration_workbench import (
    ActiveReleaseSnapshot,
    DeterministicAgentNodeSnapshot,
    DraftDefinitionSnapshot,
    DraftMetadataSnapshot,
    GraphWorkbenchSnapshot,
    ModelAgentNodeSnapshot,
    PublishedDefinitionSnapshot,
    _GraphConfigurationWorkbench,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


class GraphConfiguration(
    _GraphConfigurationDraft,
    _GraphConfigurationWorkbench,
    _GraphConfigurationBootstrap,
):
    """Read, edit, or atomically bootstrap the Graph Configuration aggregate."""


def bootstrap_graph_configuration(session_factory: sessionmaker) -> BootstrapResult:
    """Packaged-startup wrapper for the atomic bootstrap service."""
    return GraphConfiguration().bootstrap_v1(session_factory)


__all__ = [
    "ActiveReleaseSnapshot",
    "BootstrapResult",
    "DeterministicAgentNodeSnapshot",
    "DraftAggregateSnapshot",
    "DraftCandidateValidator",
    "DraftContentRejected",
    "DraftDefinitionSnapshot",
    "DraftLegacyPromptSource",
    "DraftLegacyPromptSourceRecord",
    "DraftMetadataSnapshot",
    "DraftSaveConflict",
    "DraftSaveResult",
    "DraftValidationIssue",
    "EditableModelDraft",
    "GraphConfiguration",
    "GraphConfigurationIntegrityError",
    "GraphWorkbenchSnapshot",
    "ModelAgentNodeSnapshot",
    "PublishedDefinitionSnapshot",
    "REQUIRED_SMOKE_PAYLOADS",
    "bootstrap_graph_configuration",
]
