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
    CatalogRemoteEndpointDraftValidator,
    DraftAggregateSnapshot,
    DraftCandidateValidator,
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftLegacyPromptSourceRecord,
    DraftProbeCandidate,
    DraftSaveConflict,
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    RemoteEndpointDraftValidator,
    _GraphConfigurationDraft,
)
from src.services.graph_configuration_publication import (
    ChangedDefinitionPreview,
    EvidenceKind,
    EvidenceLink,
    FieldDiff,
    NothingToPublish,
    PublicationConflict,
    PublicationEvidenceGate,
    PublicationGap,
    PublicationGapCode,
    PublicationNotReady,
    PublicationOutcome,
    PublicationRejected,
    PublishedMapping,
    PublishedRelease,
    ReleasePreview,
    _GraphConfigurationPublication,
    definition_field_diffs,
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
    _GraphConfigurationPublication,
    _GraphConfigurationDraft,
    _GraphConfigurationWorkbench,
    _GraphConfigurationBootstrap,
):
    """Read, edit, publish, or atomically bootstrap the Graph Configuration aggregate.

    ``_GraphConfigurationBootstrap`` and ``_GraphConfigurationPublication`` rely
    on ``_GraphConfigurationWorkbench``'s parent lock through this MRO.
    """


def build_remote_endpoint_draft_validator() -> RemoteEndpointDraftValidator:
    """Production remote endpoint validator for draft saves.

    Each validation derives a bounded-retry client from the system client's own
    configuration (no new credential source) and checks the exact candidate
    endpoint.  Nothing is built until the first validation.  A system-client
    failure is the typed ``endpoint_unavailable`` outcome, never a 500; its text
    is not read.
    """
    from src.core import databricks_client
    from src.services import model_endpoint_catalog

    def _catalog() -> model_endpoint_catalog.ModelEndpointCatalog:
        try:
            system_client = databricks_client.get_system_client()
        except databricks_client.DatabricksClientError as error:
            raise model_endpoint_catalog.EndpointValidationFailure(
                "endpoint_unavailable",
                "Endpoint validation is temporarily unavailable. Retry the save.",
                True,
            ) from error
        return model_endpoint_catalog.DatabricksModelEndpointCatalog(
            model_endpoint_catalog.bounded_catalog_workspace_client(system_client)
        )

    return CatalogRemoteEndpointDraftValidator(_catalog)


def bootstrap_graph_configuration(session_factory: sessionmaker) -> BootstrapResult:
    """Packaged-startup wrapper for the atomic bootstrap service."""
    return GraphConfiguration().bootstrap_v1(session_factory)


__all__ = [
    "ActiveReleaseSnapshot",
    "BootstrapResult",
    "CatalogRemoteEndpointDraftValidator",
    "ChangedDefinitionPreview",
    "DeterministicAgentNodeSnapshot",
    "DraftAggregateSnapshot",
    "DraftCandidateValidator",
    "DraftContentRejected",
    "DraftDefinitionSnapshot",
    "DraftLegacyPromptSource",
    "DraftLegacyPromptSourceRecord",
    "DraftMetadataSnapshot",
    "DraftProbeCandidate",
    "DraftSaveConflict",
    "DraftSaveResult",
    "DraftValidationIssue",
    "EditableModelDraft",
    "EvidenceKind",
    "EvidenceLink",
    "FieldDiff",
    "GraphConfiguration",
    "GraphConfigurationIntegrityError",
    "GraphWorkbenchSnapshot",
    "ModelAgentNodeSnapshot",
    "NothingToPublish",
    "PublicationConflict",
    "PublicationEvidenceGate",
    "PublicationGap",
    "PublicationGapCode",
    "PublicationNotReady",
    "PublicationOutcome",
    "PublicationRejected",
    "PublishedDefinitionSnapshot",
    "PublishedMapping",
    "PublishedRelease",
    "REQUIRED_SMOKE_PAYLOADS",
    "ReleasePreview",
    "RemoteEndpointDraftValidator",
    "bootstrap_graph_configuration",
    "build_remote_endpoint_draft_validator",
    "definition_field_diffs",
]
