"""Stable external interface for the shared Graph Configuration aggregate.

The implementation is divided by reason to change: bootstrap/write/history
validation, locked workbench reads, draft writes, publication, rollback and
prompt shipping. All cross the same semantic-content seam.
"""

from __future__ import annotations

from importlib import metadata
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
from src.services.graph_configuration_rollback import (
    AgentComparison,
    DraftEffect,
    ReleaseComparison,
    RestoredRelease,
    RollbackBlock,
    RollbackIncompatible,
    RollbackMatchesActive,
    RollbackOutcome,
    RollbackPreview,
    RollbackSourceActive,
    _GraphConfigurationRollback,
)
from src.services.graph_configuration_seed import REQUIRED_SMOKE_PAYLOADS
from src.services.graph_configuration_shipping import (
    CODE_SHIP_ACTOR,
    SYSTEM_ACTOR_PREFIX,
    AdoptOutcome,
    PackagedBlockReason,
    PackagedUpdateStatus,
    ShipBlocked,
    ShipInvalid,
    ShipNothing,
    ShipOutcome,
    Shipped,
    _GraphConfigurationShipping,
)
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
    _GraphConfigurationShipping,
    _GraphConfigurationRollback,
    _GraphConfigurationPublication,
    _GraphConfigurationDraft,
    _GraphConfigurationWorkbench,
    _GraphConfigurationBootstrap,
):
    """Read, edit, publish, roll back, ship, or bootstrap the Graph Configuration aggregate.

    ``_GraphConfigurationBootstrap``, ``_GraphConfigurationPublication`` and
    ``_GraphConfigurationRollback`` rely on ``_GraphConfigurationWorkbench``'s
    parent lock through this MRO.  ``_GraphConfigurationShipping`` comes first:
    it reuses rollback's draft rebase and bootstrap's advisory lock.
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


_APP_PACKAGE_NAME = "databricks-tellr-app"


def _installed_app_version() -> str:
    """The installed ``databricks-tellr-app`` version, else ``"unknown"``.

    Not ``src.__version__``, which is a stale hard-coded value.
    """
    try:
        return metadata.version(_APP_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"


def ship_packaged_graph_configuration(session_factory: sessionmaker) -> ShipOutcome:
    """Packaged-startup wrapper: ship the packaged manifest to an untouched install.

    Runs after bootstrap.  Bootstrap loads the packaged manifest only for an
    empty database, so on an existing install this is the startup step that
    reads it; the shipping service itself takes it as a parameter.
    """
    from src.services.graph_definition_manifest import load_graph_v1_manifest

    return GraphConfiguration().ship_packaged_manifest(
        session_factory,
        manifest=load_graph_v1_manifest(),
        app_version=_installed_app_version(),
    )


__all__ = [
    "ActiveReleaseSnapshot",
    "AdoptOutcome",
    "AgentComparison",
    "BootstrapResult",
    "CODE_SHIP_ACTOR",
    "CatalogRemoteEndpointDraftValidator",
    "ChangedDefinitionPreview",
    "DeterministicAgentNodeSnapshot",
    "DraftAggregateSnapshot",
    "DraftCandidateValidator",
    "DraftContentRejected",
    "DraftDefinitionSnapshot",
    "DraftEffect",
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
    "PackagedBlockReason",
    "PackagedUpdateStatus",
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
    "ReleaseComparison",
    "ReleasePreview",
    "RemoteEndpointDraftValidator",
    "RestoredRelease",
    "RollbackBlock",
    "RollbackIncompatible",
    "RollbackMatchesActive",
    "RollbackOutcome",
    "RollbackPreview",
    "RollbackSourceActive",
    "SYSTEM_ACTOR_PREFIX",
    "ShipBlocked",
    "ShipInvalid",
    "ShipNothing",
    "ShipOutcome",
    "Shipped",
    "bootstrap_graph_configuration",
    "build_remote_endpoint_draft_validator",
    "definition_field_diffs",
    "ship_packaged_graph_configuration",
]
