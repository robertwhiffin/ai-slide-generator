"""Admin-only Agent Definition workbench routes."""

import dataclasses
import json
import logging
from collections.abc import Callable, Mapping
from typing import Annotated, Protocol, TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.schemas.agent_definitions import (
    MAX_ROW_ID,
    ActiveReleaseResponse,
    BaselineTestRunRequest,
    CandidateTestRunRequest,
    CreateTestCaseRequest,
    CustomTextBlockRequest,
    DraftDefinitionResponse,
    DraftFieldErrorResponse,
    DraftLockRequest,
    DraftMetadataResponse,
    DraftReadinessResponse,
    DraftSaveConflictResponse,
    DraftSaveConflictServerResponse,
    DraftSaveRequest,
    DraftSaveSuccessResponse,
    DraftValidationErrorResponse,
    EditableAssemblyRulesRequest,
    EditableModelDraftModelRequest,
    EditableModelDraftRequest,
    EditableSchemaOverlayRequest,
    GraphWorkbenchResponse,
    IneligibleForApprovalResponse,
    LegacyPromptSourceResponse,
    ModelEndpointCatalogErrorResponse,
    StructuredOutputProbeFailureResponse,
    StructuredOutputProbeSuccessResponse,
    SystemModelDiscoveryResponse,
    SystemModelEndpointResponse,
    TestCaseConflictResponse,
    TestCaseListResponse,
    TestCaseResponse,
    TestCaseValidationErrorResponse,
    TestRunEvidenceResponse,
    TestRunListResponse,
    TestRunUnavailableResponse,
    UpdateTestCaseRequest,
    VerdictRequest,
    VerdictValidationErrorResponse,
)
from src.api.schemas.graph_releases import (
    ChangedDefinitionResponse,
    FieldDiffResponse,
    NothingToPublishResponse,
    PublicationGapResponse,
    PublicationNotReadyResponse,
    PublicationValidationErrorResponse,
    PublishedMappingResponse,
    PublishReleaseRequest,
    PublishReleaseSuccessResponse,
    ReleaseEvidenceResponse,
    ReleaseIdentityResponse,
    ReleasePreviewResponse,
    StalePublicationResponse,
)
from src.core import databricks_client
from src.core.database import get_db
from src.core.user_context import get_current_user
from src.services import model_endpoint_catalog
from src.services.agent_schema_types import SchemaOverlay
from src.services.agent_test_workbench import (
    MAX_RUN_LIST_LIMIT,
    AgentTestWorkbench,
    IneligibleForApprovalError,
    TestCaseNotFound,
    TestCaseRejected,
    TestCaseStale,
    TestCaseVersion,
    TestRunCaseInactive,
    TestRunCaseRoleMismatch,
    TestRunEvidence,
    TestRunNotFound,
    TestRunUnavailable,
    VerdictRejected,
)
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    NothingToPublish,
    PublicationConflict,
    PublicationNotReady,
    PublicationRejected,
    PublishedRelease,
    RemoteEndpointDraftValidator,
    build_remote_endpoint_draft_validator,
)
from src.services.graph_configuration_publication import ReleasePreview
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    AssemblyRulesV2,
)
from src.services.graph_release_evidence import ApprovalEvidenceGate
from src.services.model_endpoint_catalog import (
    ModelEndpointCatalogFailure,
    SystemModelDiscovery,
)
from src.services.model_endpoint_probe import (
    DatabricksStructuredOutputProbe,
    ModelEndpointProbeService,
    SavedEndpointProbeResult,
    StructuredOutputProbeAdapter,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/agent-definitions",
    tags=["admin", "agent-definitions"],
    dependencies=[Depends(require_admin)],
)


def require_draft_write_principal() -> str:
    """Require a trusted audit actor after the router's admin gate succeeds."""
    actor = get_current_user()
    if actor is None or not actor.strip():
        raise HTTPException(
            status_code=403,
            detail="Authenticated principal required",
        )
    return actor


def get_remote_endpoint_draft_validator() -> RemoteEndpointDraftValidator:
    """The draft PUT's production remote endpoint validator.

    Resolved after the router's admin gate.  Building it performs no client or
    network work; the catalog client is derived only when a current locked
    candidate is validated.
    """
    return build_remote_endpoint_draft_validator()


class SystemModelEndpointLister(Protocol):
    """The discovery half of the model endpoint catalog."""

    def list_system_models(self) -> SystemModelDiscovery: ...


_CATALOG_UNAVAILABLE_MESSAGE = (
    "Model endpoint discovery is temporarily unavailable. Retry the request."
)


class _SystemModelEndpointDiscovery:
    """Production discovery over the discovery-bounded system catalog client.

    Nothing is built until ``list_system_models``.  A system-client failure is
    the typed unavailable outcome, never a 500; its text is not read.
    """

    def list_system_models(self) -> SystemModelDiscovery:
        try:
            system_client = databricks_client.get_system_client()
        except databricks_client.DatabricksClientError as error:
            raise ModelEndpointCatalogFailure(
                "catalog_unavailable", _CATALOG_UNAVAILABLE_MESSAGE, True
            ) from error
        catalog = model_endpoint_catalog.DatabricksModelEndpointCatalog(
            model_endpoint_catalog.bounded_discovery_workspace_client(system_client)
        )
        return catalog.list_system_models()


def get_model_endpoint_catalog() -> SystemModelEndpointLister:
    """The discovery route's catalog, resolved after the router's admin gate."""
    return _SystemModelEndpointDiscovery()


_CATALOG_FAILURE_STATUS = {"catalog_forbidden": 403, "catalog_unavailable": 503}


def get_structured_output_probe() -> StructuredOutputProbeAdapter:
    """The probe route's production adapter, resolved after the router's admin gate.

    Construction does no client or network work; the runtime-identity client is
    built only when a current saved candidate is probed.
    """
    return DatabricksStructuredOutputProbe()


_PROBE_FAILURE_STATUS = {
    "unsupported_structured_output": 422,
    "endpoint_probe_forbidden": 403,
    "structured_output_probe_failed": 503,
}


def _probe_result_response(
    result: SavedEndpointProbeResult,
) -> StructuredOutputProbeSuccessResponse | JSONResponse:
    identity = result.identity
    if result.failure is None:
        return StructuredOutputProbeSuccessResponse(
            code="structured_output_probe_succeeded",
            endpoint_name=identity.endpoint_name,
            candidate_hash=identity.candidate_hash,
            lock_version=identity.lock_version,
        )
    failure = result.failure
    response = StructuredOutputProbeFailureResponse(
        code=failure.code,
        message=failure.message,
        retryable=failure.retryable,
        endpoint_name=identity.endpoint_name,
        candidate_hash=identity.candidate_hash,
        lock_version=identity.lock_version,
    )
    return JSONResponse(
        status_code=_PROBE_FAILURE_STATUS[failure.code],
        content=response.model_dump(mode="json"),
    )


def _catalog_failure_response(failure: ModelEndpointCatalogFailure) -> JSONResponse:
    response = ModelEndpointCatalogErrorResponse(
        code=failure.code,
        message=str(failure),
        retryable=failure.retryable,
    )
    return JSONResponse(
        status_code=_CATALOG_FAILURE_STATUS[failure.code],
        content=response.model_dump(mode="json"),
    )


_OWNED_FIELD_MESSAGES = {
    "candidate.prompt_text": "Prompt text must not be blank.",
    "candidate.model.endpoint_name": "Endpoint name must not be blank.",
    "candidate.model.temperature": "Temperature must be between 0 and 1.",
    "candidate.model.max_tokens": "Maximum tokens must be a positive integer.",
    "candidate.model.top_p": "Top-p must be between 0 and 1.",
}


_OWNED_SCHEMA_OVERLAY_MESSAGES = {
    ("candidate.schema_overlay", "strict_type"): "Schema overlay must be an object.",
    ("candidate.schema_overlay.field_overrides", "strict_type"): (
        "Field overrides must be an object."
    ),
    ("candidate.schema_overlay.additional_optional_fields", "strict_type"): (
        "Additional optional fields must be an array."
    ),
}
_OWNED_ASSEMBLY_MESSAGES = {
    ("candidate.assembly_rules", "strict_type"): "Assembly rules must be an object.",
    (
        "candidate.assembly_rules.format_version",
        "unsupported_assembly_version",
    ): "Editable assembly rules must use format version 2.",
    (
        "candidate.assembly_rules.custom_blocks",
        "strict_type",
    ): "Custom blocks must be an array.",
    (
        "candidate.assembly_rules.custom_blocks.*.kind",
        "unknown_block_kind",
    ): "Custom block kind must be custom_text.",
    (
        "candidate.assembly_rules.custom_blocks.*.block_id",
        "strict_type",
    ): "Custom block ID must be a UUID string.",
    (
        "candidate.assembly_rules.custom_blocks.*.anchor",
        "unknown_anchor",
    ): "Custom block anchor is not supported.",
    (
        "candidate.assembly_rules.custom_blocks.*.anchor",
        "strict_type",
    ): "Custom block anchor must be a string.",
    (
        "candidate.assembly_rules.custom_blocks.*.condition",
        "unknown_condition",
    ): "Custom block condition is not supported.",
    (
        "candidate.assembly_rules.custom_blocks.*.condition",
        "strict_type",
    ): "Custom block condition must be a string.",
    (
        "candidate.assembly_rules.custom_blocks.*.text",
        "strict_type",
    ): "Custom block text must be a string.",
}
_UNKNOWN_AGENT_ERROR = DraftFieldErrorResponse(
    field="agent_key",
    code="unknown_agent",
    message="Agent key must identify an editable model role.",
)


def _field_shape(field: str) -> str:
    """Collapse list indices so one owned message covers every custom block."""
    return ".".join(
        "*" if part.isdigit() else part for part in field.split(".")
    )


def _draft_validation_response(
    errors: list[DraftFieldErrorResponse],
) -> JSONResponse:
    response = DraftValidationErrorResponse(code="invalid_draft", errors=errors)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


def _validation_error_code(field: str, error_type: str, error_input: object) -> str:
    if error_type == "extra_forbidden":
        return "extra_forbidden"
    if error_type == "finite_number":
        return "finite_number"
    shape = _field_shape(field)
    if error_type == "literal_error":
        if shape == "candidate.assembly_rules.format_version":
            return "unsupported_assembly_version"
        if shape == "candidate.assembly_rules.custom_blocks.*.kind":
            return "unknown_block_kind"
        if shape == "candidate.assembly_rules.custom_blocks.*.anchor":
            return "unknown_anchor" if isinstance(error_input, str) else "strict_type"
        if shape == "candidate.assembly_rules.custom_blocks.*.condition":
            return "unknown_condition" if isinstance(error_input, str) else "strict_type"
        return "strict_type"
    if error_type in {"uuid_type", "uuid_parsing", "list_type", "tuple_type"}:
        return "strict_type"
    if error_type in {"greater_than", "greater_than_equal"}:
        return "positive_integer" if field == "candidate.model.max_tokens" else "out_of_range"
    if error_type in {"less_than", "less_than_equal"}:
        return "out_of_range"
    if error_type in {
        "int_type",
        "float_type",
        "string_type",
        "model_type",
        "missing",
    }:
        return "strict_type"
    if error_type == "value_error" and field in {
        "candidate.prompt_text",
        "candidate.model.endpoint_name",
    }:
        return "blank"
    return "strict_type"


def _request_error_message(
    field: str, code: str, error: Mapping[str, object]
) -> str:
    owned = _OWNED_FIELD_MESSAGES.get(field)
    if owned is not None:
        return owned
    if error["type"] in {"missing", "extra_forbidden"}:
        return str(error["msg"])
    shape = _field_shape(field)
    overlay_msg = _OWNED_SCHEMA_OVERLAY_MESSAGES.get((shape, code))
    if overlay_msg is not None:
        return overlay_msg
    return _OWNED_ASSEMBLY_MESSAGES.get((shape, code), str(error["msg"]))


def _request_validation_errors(
    exc: ValidationError, *, prefix: tuple[str, ...] = ()
) -> list[DraftFieldErrorResponse]:
    """Render a ValidationError into the ordered envelope.

    ``prefix`` roots a nested model's own locations in the request path that
    reached it — the domain overlay validates in isolation, so its ``loc`` is
    relative to itself and would otherwise report ``field_overrides.x`` where the
    client sent ``candidate.schema_overlay.field_overrides.x``.  Kept as a
    parameter rather than a second renderer so every ordered 422 in this module
    still comes from one place.
    """
    errors: list[DraftFieldErrorResponse] = []
    for error in exc.errors():
        location = (*prefix, *error["loc"])
        field = ".".join(str(part) for part in location) or "$"
        error_type = error["type"]
        code = _validation_error_code(field, error_type, error.get("input"))
        errors.append(
            DraftFieldErrorResponse(
                field=field,
                code=code,
                message=_request_error_message(field, code, error),
            )
        )
    return errors


def _rejection_response(exc: DraftContentRejected) -> JSONResponse:
    """Copy every domain issue verbatim into the existing ordered envelope."""
    return _draft_validation_response(
        [
            DraftFieldErrorResponse(
                field=issue.field,
                code=issue.code,
                message=issue.message,
            )
            for issue in exc.issues
        ]
    )


def _conflict_response(
    outcome: DraftSaveConflict,
    *,
    client_candidate: EditableModelDraftRequest | None,
) -> JSONResponse:
    conflict_response = DraftSaveConflictResponse(
        code="stale_draft",
        expected_lock_version=outcome.expected_lock_version,
        current_lock_version=outcome.current_lock_version,
        client_candidate=client_candidate,
        server=DraftSaveConflictServerResponse(
            draft=outcome.server.draft,
            definitions={
                key: DraftDefinitionResponse.model_validate(
                    definition,
                    from_attributes=True,
                )
                for key, definition in outcome.server.definitions.items()
            },
        ),
    )
    return JSONResponse(
        status_code=409,
        content=conflict_response.model_dump(mode="json"),
    )


async def _parse_lock_request(
    request: Request, agent_key: str
) -> DraftLockRequest | JSONResponse:
    """Strictly parse the one accepted POST body after authorization succeeded."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _malformed_json_response()
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        return _draft_validation_response([_UNKNOWN_AGENT_ERROR])
    try:
        return DraftLockRequest.model_validate(raw_body)
    except ValidationError as exc:
        return _draft_validation_response(_request_validation_errors(exc))


def _domain_schema_overlay(
    overlay: EditableSchemaOverlayRequest | None,
) -> SchemaOverlay | None:
    """Convert the parsed wire overlay to the domain type, or leave stored as-is."""
    if overlay is None:
        return None
    return SchemaOverlay.model_validate(
        {
            "field_overrides": overlay.field_overrides,
            "additional_optional_fields": overlay.additional_optional_fields,
        }
    )


def _domain_assembly_rules(
    rules: EditableAssemblyRulesRequest | None,
) -> AssemblyRulesV2 | None:
    """Rehydrate the parsed wire record onto the frozen server-owned rules model."""
    if rules is None:
        return None
    return AssemblyRulesV2.model_validate(rules.model_dump(mode="python"))


def _client_candidate_response(
    candidate: EditableModelDraft,
) -> EditableModelDraftRequest:
    """Serialize exactly the candidate the locked facade returned, nothing else."""
    overlay: EditableSchemaOverlayRequest | None = None
    if candidate.schema_overlay is not None:
        overlay = EditableSchemaOverlayRequest(
            field_overrides=dict(
                candidate.schema_overlay.serialize_field_overrides(
                    candidate.schema_overlay.field_overrides
                )
            ),
            additional_optional_fields=list(
                candidate.schema_overlay.additional_optional_fields
            ),
        )
    return EditableModelDraftRequest(
        prompt_text=candidate.prompt_text,
        model=EditableModelDraftModelRequest(
            endpoint_name=candidate.endpoint_name,
            temperature=candidate.temperature,
            max_tokens=candidate.max_tokens,
            top_p=candidate.top_p,
        ),
        assembly_rules=(
            None
            if candidate.assembly_rules is None
            else EditableAssemblyRulesRequest(
                format_version=2,
                custom_blocks=[
                    CustomTextBlockRequest(
                        kind=block.kind,
                        block_id=block.block_id,
                        anchor=block.anchor,
                        condition=block.condition,
                        text=block.text,
                    )
                    for block in candidate.assembly_rules.custom_blocks
                ],
            )
        ),
        schema_overlay=overlay,
    )


def _malformed_json_response() -> JSONResponse:
    return _draft_validation_response(
        [
            DraftFieldErrorResponse(
                field="$",
                code="invalid_json",
                message="Request body must be valid JSON.",
            )
        ]
    )


@router.get("/workbench", response_model=GraphWorkbenchResponse)
def get_agent_definition_workbench(
    db: Session = Depends(get_db),
) -> GraphWorkbenchResponse:
    try:
        snapshot = GraphConfiguration().read_workbench(db)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc
    return GraphWorkbenchResponse.model_validate(snapshot, from_attributes=True)


@router.get(
    "/model-endpoints",
    response_model=SystemModelDiscoveryResponse,
    responses={
        403: {"model": ModelEndpointCatalogErrorResponse},
        503: {"model": ModelEndpointCatalogErrorResponse},
    },
)
def list_model_endpoints(
    catalog: Annotated[SystemModelEndpointLister, Depends(get_model_endpoint_catalog)],
) -> SystemModelDiscoveryResponse | JSONResponse:
    """Read-only foundation-model endpoint discovery; it never writes a draft.

    Only a typed catalog failure becomes a documented 403/503 envelope; any
    other fault keeps the non-leaking 500 policy and is never empty success.
    """
    try:
        discovery = catalog.list_system_models()
    except ModelEndpointCatalogFailure as failure:
        return _catalog_failure_response(failure)
    return SystemModelDiscoveryResponse(
        items=[
            SystemModelEndpointResponse(
                name=endpoint.name,
                display_name=endpoint.display_name,
                description=endpoint.description,
                docs=endpoint.docs,
            )
            for endpoint in discovery.endpoints
        ]
    )


@router.put("/draft/{agent_key}", response_model=DraftSaveSuccessResponse)
async def save_agent_definition_draft(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    remote_endpoint_validator: Annotated[
        RemoteEndpointDraftValidator, Depends(get_remote_endpoint_draft_validator)
    ],
    db: Session = Depends(get_db),
) -> DraftSaveSuccessResponse | JSONResponse:
    """Save exactly the editable candidate fields through the locked draft facade."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _malformed_json_response()

    if agent_key not in GRAPH_V1_AGENT_KEYS:
        return _draft_validation_response([_UNKNOWN_AGENT_ERROR])

    try:
        save_request = DraftSaveRequest.model_validate(raw_body)
    except ValidationError as exc:
        return _draft_validation_response(_request_validation_errors(exc))

    # The wire overlay is deliberately loosely typed so that unknown guidance
    # properties reach the domain validator and come back as the stable
    # ``overlay_guidance_property_forbidden`` domain issue.  The cost is that a
    # TYPE error passes the wire layer and raises here instead, which reached the
    # client as a 500 until this catch existed.  Convert it to the same ordered
    # 422 every other rejection uses; do NOT tighten the wire types, which would
    # turn a documented domain issue into a Pydantic message.
    #
    # The catch wraps ONLY the overlay conversion: its prefix names the overlay, so
    # a ValidationError from any other conversion must not be reported under it.
    assembly_rules = _domain_assembly_rules(save_request.candidate.assembly_rules)
    try:
        schema_overlay = _domain_schema_overlay(save_request.candidate.schema_overlay)
    except ValidationError as exc:
        return _draft_validation_response(
            _request_validation_errors(exc, prefix=("candidate", "schema_overlay"))
        )
    candidate = EditableModelDraft(
        prompt_text=save_request.candidate.prompt_text,
        endpoint_name=save_request.candidate.model.endpoint_name,
        temperature=save_request.candidate.model.temperature,
        max_tokens=save_request.candidate.model.max_tokens,
        top_p=save_request.candidate.model.top_p,
        assembly_rules=assembly_rules,
        schema_overlay=schema_overlay,
    )
    # The save holds the draft row locks while it makes the remote endpoint check,
    # so it runs off the event loop, exactly as the structured-output probe does.
    try:
        outcome = await run_in_threadpool(
            GraphConfiguration(
                remote_endpoint_validator=remote_endpoint_validator
            ).save_editable_model_draft,
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=save_request.lock_version,
            candidate=candidate,
            actor=actor,
        )
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveResult):
        return DraftSaveSuccessResponse.model_validate(outcome, from_attributes=True)

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(
            outcome,
            client_candidate=_client_candidate_response(outcome.client_candidate),
        )

    raise AssertionError(f"Unexpected draft save outcome: {type(outcome)!r}")


@router.post(
    "/draft/{agent_key}/protected-assembly-upgrade",
    response_model=DraftSaveSuccessResponse,
)
async def upgrade_agent_definition_protected_assembly(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> DraftSaveSuccessResponse | JSONResponse:
    """Apply the server-owned protected assembly upgrade through the locked facade."""
    parsed = await _parse_lock_request(request, agent_key)
    if isinstance(parsed, JSONResponse):
        return parsed

    try:
        outcome = GraphConfiguration().upgrade_draft_protected_assembly(
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=parsed.lock_version,
            actor=actor,
        )
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveResult):
        return DraftSaveSuccessResponse.model_validate(outcome, from_attributes=True)

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(outcome, client_candidate=None)

    raise AssertionError(f"Unexpected upgrade outcome: {type(outcome)!r}")


@router.post(
    "/draft/{agent_key}/schema-contract-upgrade",
    response_model=DraftSaveSuccessResponse,
)
async def upgrade_agent_definition_schema_contract(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> DraftSaveSuccessResponse | JSONResponse:
    """Apply the one permitted v1 to v2 schema-contract upgrade through the locked facade."""
    parsed = await _parse_lock_request(request, agent_key)
    if isinstance(parsed, JSONResponse):
        return parsed

    try:
        outcome = GraphConfiguration().upgrade_draft_schema_contract(
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=parsed.lock_version,
            actor=actor,
        )
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveResult):
        return DraftSaveSuccessResponse.model_validate(outcome, from_attributes=True)

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(outcome, client_candidate=None)

    raise AssertionError(f"Unexpected schema-contract upgrade outcome: {type(outcome)!r}")


@router.post(
    "/draft/{agent_key}/legacy-prompt-source",
    response_model=LegacyPromptSourceResponse,
)
async def read_agent_definition_legacy_prompt_source(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> LegacyPromptSourceResponse | JSONResponse:
    """Return the retained Graph Version 1 prompt source; this route never writes."""
    parsed = await _parse_lock_request(request, agent_key)
    if isinstance(parsed, JSONResponse):
        return parsed

    try:
        outcome = GraphConfiguration().get_draft_legacy_prompt_source(
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=parsed.lock_version,
            actor=actor,
        )
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftLegacyPromptSource):
        return LegacyPromptSourceResponse.model_validate(outcome, from_attributes=True)

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(outcome, client_candidate=None)

    raise AssertionError(f"Unexpected legacy prompt source outcome: {type(outcome)!r}")


@router.post(
    "/draft/{agent_key}/model-endpoint-probe",
    response_model=StructuredOutputProbeSuccessResponse,
    responses={
        403: {"model": StructuredOutputProbeFailureResponse},
        409: {"model": DraftSaveConflictResponse},
        422: {"model": StructuredOutputProbeFailureResponse | DraftValidationErrorResponse},
        503: {"model": StructuredOutputProbeFailureResponse},
    },
)
async def probe_agent_definition_model_endpoint(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    probe: Annotated[StructuredOutputProbeAdapter, Depends(get_structured_output_probe)],
    db: Session = Depends(get_db),
) -> StructuredOutputProbeSuccessResponse | JSONResponse:
    """Probe the role's saved endpoint once for structured output; never writes.

    The body is exactly ``{"lock_version": n}``.  The endpoint, sampling values,
    prompt and schema are all server-owned.  The saved candidate is copied and
    the database released before the model call, which runs off the event loop.
    """
    del actor  # authorization only: the probe writes and audits nothing
    parsed = await _parse_lock_request(request, agent_key)
    if isinstance(parsed, JSONResponse):
        return parsed

    service = ModelEndpointProbeService(probe)
    try:
        outcome = await run_in_threadpool(
            service.probe_saved_candidate,
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=parsed.lock_version,
        )
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(outcome, client_candidate=None)

    if isinstance(outcome, SavedEndpointProbeResult):
        return _probe_result_response(outcome)

    raise AssertionError(f"Unexpected probe outcome: {type(outcome)!r}")


# --- Agent Test Cases (#267 Task 2) ------------------------------------------
# On this one admin router (C23): every route inherits ``require_admin``, and a
# write takes its actor from ``require_draft_write_principal``; bodies are read
# only after both succeed.  The case writer waits on the role's L2 row lock, so
# it never runs on the event loop: the body routes hand it to the threadpool,
# and the body-less routes are plain ``def`` handlers, which FastAPI runs there.


def _test_case_validation_response(
    errors: list[DraftFieldErrorResponse],
) -> JSONResponse:
    response = TestCaseValidationErrorResponse(code="invalid_test_case", issues=errors)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


def _test_case_rejection_response(exc: TestCaseRejected) -> JSONResponse:
    """Copy every ordered domain issue verbatim into the case envelope."""
    return _test_case_validation_response(
        [
            DraftFieldErrorResponse(field=issue.field, code=issue.code, message=issue.message)
            for issue in exc.issues
        ]
    )


def _test_case_stale_response(exc: TestCaseStale) -> JSONResponse:
    response = TestCaseConflictResponse(
        code="stale_test_case",
        test_case_id=exc.test_case_id,
        message="This test case version is no longer active. Reload and retry.",
    )
    return JSONResponse(status_code=409, content=response.model_dump(mode="json"))


def _test_case_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Test case not found")


def _test_case_response(version: TestCaseVersion) -> TestCaseResponse:
    return TestCaseResponse.model_validate(dataclasses.asdict(version))


_TestCaseBodyT = TypeVar("_TestCaseBodyT", CreateTestCaseRequest, UpdateTestCaseRequest)


async def _read_test_case_body(
    request: Request, request_model: type[_TestCaseBodyT]
) -> _TestCaseBodyT | JSONResponse:
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _test_case_validation_response(
            [
                DraftFieldErrorResponse(
                    field="$",
                    code="invalid_json",
                    message="Request body must be valid JSON.",
                )
            ]
        )
    try:
        return request_model.model_validate(raw_body)
    except ValidationError as exc:
        return _test_case_validation_response(_request_validation_errors(exc))


_TEST_CASE_WRITE_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"description": "Test case not found"},
    409: {"model": TestCaseConflictResponse},
    422: {"model": TestCaseValidationErrorResponse},
}


@router.get(
    "/test-cases",
    response_model=TestCaseListResponse,
    responses={422: {"model": TestCaseValidationErrorResponse}},
)
def list_agent_test_cases(
    agent_key: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> TestCaseListResponse | JSONResponse:
    """Active case versions in role order; ``include_inactive`` adds history."""
    try:
        cases = AgentTestWorkbench().list_test_cases(
            db, agent_key=agent_key, include_inactive=include_inactive
        )
    except TestCaseRejected as exc:
        return _test_case_rejection_response(exc)
    return TestCaseListResponse(items=[_test_case_response(case) for case in cases])


@router.post(
    "/test-cases",
    status_code=201,
    response_model=TestCaseResponse,
    responses={422: {"model": TestCaseValidationErrorResponse}},
)
async def create_agent_test_case(
    request: Request,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> TestCaseResponse | JSONResponse:
    """Add a new case lineage at version 1."""
    parsed = await _read_test_case_body(request, CreateTestCaseRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    try:
        version = await run_in_threadpool(
            AgentTestWorkbench().create_test_case,
            db,
            agent_key=parsed.agent_key,
            name=parsed.name,
            synthetic_payload=parsed.synthetic_payload,
            assembly_context=parsed.assembly_context.model_dump(),
            is_required=parsed.is_required,
            actor=actor,
        )
    except TestCaseRejected as exc:
        return _test_case_rejection_response(exc)
    return _test_case_response(version)


@router.put(
    "/test-cases/{test_case_id}",
    response_model=TestCaseResponse,
    responses=_TEST_CASE_WRITE_RESPONSES,
)
async def update_agent_test_case(
    request: Request,
    test_case_id: int,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> TestCaseResponse | JSONResponse:
    """Supersede the active version: retire it and return ``version + 1``."""
    parsed = await _read_test_case_body(request, UpdateTestCaseRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    try:
        version = await run_in_threadpool(
            AgentTestWorkbench().update_test_case,
            db,
            test_case_id=test_case_id,
            name=parsed.name,
            synthetic_payload=parsed.synthetic_payload,
            assembly_context=parsed.assembly_context.model_dump(),
            is_required=parsed.is_required,
            actor=actor,
        )
    except TestCaseRejected as exc:
        return _test_case_rejection_response(exc)
    except TestCaseStale as exc:
        return _test_case_stale_response(exc)
    except TestCaseNotFound as exc:
        raise _test_case_not_found() from exc
    return _test_case_response(version)


@router.delete(
    "/test-cases/{test_case_id}",
    response_model=TestCaseResponse,
    responses={
        404: {"description": "Test case not found"},
        422: {"model": TestCaseValidationErrorResponse},
    },
)
def deactivate_agent_test_case(
    test_case_id: int,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> TestCaseResponse | JSONResponse:
    """Retire one version (never a row delete); retiring it again is a no-op."""
    try:
        version = AgentTestWorkbench().deactivate_test_case(
            db, test_case_id=test_case_id, actor=actor
        )
    except TestCaseRejected as exc:
        return _test_case_rejection_response(exc)
    except TestCaseNotFound as exc:
        raise _test_case_not_found() from exc
    return _test_case_response(version)


# --- Agent Test Runs (#267 Task 5) ------------------------------------------
# Still the one admin router (C23): ``/draft/{agent_key}/test-runs`` runs the
# saved candidate, ``/published/{agent_key}/test-runs`` reruns the published
# definition, and ``/test-runs/{run_id}`` is the one run (#268 adds
# ``/test-runs/{run_id}/verdict`` beside it).  The two executes reach a model,
# so they are ``async``, read the body only after both auth gates, and run the
# executor in the threadpool (C36).  Refusals map in the executor's order:
# lock/role 422 -> stale lock 409 -> endpoint policy 422 -> case 404 -> role
# mismatch 422 -> inactive case 409.  A model failure is not a refusal: it is
# a persisted run, returned 201 like any other evidence (C33).


def get_agent_test_workbench() -> AgentTestWorkbench:
    """The run routes' executor, resolved after the router's admin gate.

    Construction builds nothing; the first run resolves the bounded
    ``get_agent_test_runtime()`` (C33), never the production runtime.
    """
    return AgentTestWorkbench()


_TEST_RUN_UNAVAILABLE_MESSAGE = (
    "Test run storage is temporarily unavailable. Retry the request."
)
_ROLE_MISMATCH_MESSAGE = "This test case belongs to another agent role."

_RunRequestT = TypeVar("_RunRequestT", CandidateTestRunRequest, BaselineTestRunRequest)


async def _parse_test_run_request(
    request: Request, agent_key: str, request_model: type[_RunRequestT]
) -> _RunRequestT | JSONResponse:
    """``_parse_lock_request``'s order: malformed JSON, unknown role, strict body."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _malformed_json_response()
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        return _draft_validation_response([_UNKNOWN_AGENT_ERROR])
    try:
        return request_model.model_validate(raw_body)
    except ValidationError as exc:
        return _draft_validation_response(_request_validation_errors(exc))


def _test_run_response(evidence: TestRunEvidence) -> TestRunEvidenceResponse:
    return TestRunEvidenceResponse.model_validate(dataclasses.asdict(evidence))


def _test_run_unavailable_response() -> JSONResponse:
    response = TestRunUnavailableResponse(
        code="test_run_unavailable",
        message=_TEST_RUN_UNAVAILABLE_MESSAGE,
        retryable=True,
    )
    return JSONResponse(status_code=503, content=response.model_dump(mode="json"))


def _test_run_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Test run not found")


def _is_storable_row_id(value: int) -> bool:
    return 1 <= value <= MAX_ROW_ID


async def _execute_test_run(
    call, db: Session, **arguments
) -> TestRunEvidenceResponse | JSONResponse:
    """Run one executor off the event loop and map its refusals (C16, C36)."""
    try:
        outcome = await run_in_threadpool(call, db, **arguments)
    except DraftContentRejected as exc:
        return _rejection_response(exc)
    except TestCaseRejected as exc:
        return _test_case_rejection_response(exc)
    except TestCaseNotFound as exc:
        raise _test_case_not_found() from exc
    except TestRunCaseRoleMismatch:
        return _test_case_validation_response(
            [
                DraftFieldErrorResponse(
                    field="test_case_id",
                    code="agent_key_mismatch",
                    message=_ROLE_MISMATCH_MESSAGE,
                )
            ]
        )
    except TestRunCaseInactive as exc:
        return _test_case_stale_response(TestCaseStale(exc.test_case_id))
    except TestRunUnavailable:
        # The executor already logged the phase and the error class only.
        return _test_run_unavailable_response()
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveConflict):
        return _conflict_response(outcome, client_candidate=None)
    if isinstance(outcome, TestRunEvidence):
        return _test_run_response(outcome)
    raise AssertionError(f"Unexpected test run outcome: {type(outcome)!r}")


_TEST_RUN_EXECUTE_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"description": "Test case not found"},
    409: {"model": DraftSaveConflictResponse | TestCaseConflictResponse},
    422: {"model": DraftValidationErrorResponse | TestCaseValidationErrorResponse},
    503: {"model": TestRunUnavailableResponse},
}


@router.post(
    "/draft/{agent_key}/test-runs",
    status_code=201,
    response_model=TestRunEvidenceResponse,
    responses=_TEST_RUN_EXECUTE_RESPONSES,
)
async def execute_agent_candidate_test_run(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> TestRunEvidenceResponse | JSONResponse:
    """Run one active case version against the role's saved draft candidate.

    The body is exactly ``{"test_case_id": n, "lock_version": n}``; the lock
    pins the saved candidate the admin is looking at (C32).
    """
    parsed = await _parse_test_run_request(request, agent_key, CandidateTestRunRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    return await _execute_test_run(
        workbench.execute_candidate_run,
        db,
        agent_key=agent_key,
        test_case_id=parsed.test_case_id,
        expected_lock_version=parsed.lock_version,
        actor=actor,
    )


@router.post(
    "/published/{agent_key}/test-runs",
    status_code=201,
    response_model=TestRunEvidenceResponse,
    responses=_TEST_RUN_EXECUTE_RESPONSES,
)
async def execute_agent_published_baseline_test_run(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> TestRunEvidenceResponse | JSONResponse:
    """Rerun one active case version against the active published definition.

    The body is exactly ``{"test_case_id": n}``: no draft is read or pinned.
    """
    parsed = await _parse_test_run_request(request, agent_key, BaselineTestRunRequest)
    if isinstance(parsed, JSONResponse):
        return parsed
    return await _execute_test_run(
        workbench.execute_baseline_rerun,
        db,
        agent_key=agent_key,
        test_case_id=parsed.test_case_id,
        actor=actor,
    )


@router.get(
    "/test-runs/{run_id}",
    response_model=TestRunEvidenceResponse,
    responses={404: {"description": "Test run not found"}},
)
def get_agent_test_run(
    run_id: int,
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> TestRunEvidenceResponse:
    """One stored run; the write-time currency flags read back as ``null``."""
    if not _is_storable_row_id(run_id):
        raise _test_run_not_found()
    try:
        evidence = workbench.get_test_run(db, run_id=run_id)
    except TestRunNotFound as exc:
        raise _test_run_not_found() from exc
    return _test_run_response(evidence)


@router.get(
    "/test-cases/{test_case_id}/runs",
    response_model=TestRunListResponse,
    responses={
        404: {"description": "Test case not found"},
        422: {"model": TestCaseValidationErrorResponse},
    },
)
def list_agent_test_case_runs(
    test_case_id: int,
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    limit: int = 20,
    db: Session = Depends(get_db),
) -> TestRunListResponse | JSONResponse:
    """One case version's runs, newest first, at most ``limit`` (1-100)."""
    if not 1 <= limit <= MAX_RUN_LIST_LIMIT:
        return _test_case_validation_response(
            [
                DraftFieldErrorResponse(
                    field="limit",
                    code="out_of_range",
                    message=f"Limit must be an integer from 1 to {MAX_RUN_LIST_LIMIT}.",
                )
            ]
        )
    if not _is_storable_row_id(test_case_id):
        raise _test_case_not_found()
    try:
        runs = workbench.list_test_runs(db, test_case_id=test_case_id, limit=limit)
    except TestCaseNotFound as exc:
        raise _test_case_not_found() from exc
    return TestRunListResponse(items=[_test_run_response(run) for run in runs])


# --- Verdicts and readiness (#268 Task 3) ------------------------------------
# Still the one admin router (C15).  The verdict takes its reviewer from
# ``require_draft_write_principal`` and reads the body only after both gates; the
# body is exactly ``{verdict, notes}``.  The writer waits on the run row's L3
# ``FOR UPDATE`` lock, so it runs in the threadpool (a body route must be
# ``async`` to read the body).  Readiness waits on the shared L0 parent lock and
# is a plain ``def`` handler, which FastAPI runs there.  A verdict on a run that
# is published evidence is the typed ``linked_to_release`` 422 (#269 C48).  An
# ``IntegrityError`` from the verdict write (the DDL checks, or #269's linked-
# verdict trigger, the backstop for direct writes) is never mapped: it
# propagates as a 500 (C7).

_INELIGIBLE_MESSAGES = {
    "not_completed": "Only a completed run can take a verdict.",
    "checks_failed": "A run whose deterministic checks failed cannot be approved.",
    "linked_to_release": (
        "This run is evidence for a published Graph Version; its verdict cannot change."
    ),
}


def _verdict_validation_response(errors: list[DraftFieldErrorResponse]) -> JSONResponse:
    response = VerdictValidationErrorResponse(code="invalid_verdict", errors=errors)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


def _ineligible_response(exc: IneligibleForApprovalError) -> JSONResponse:
    response = IneligibleForApprovalResponse(
        code="ineligible_for_approval",
        reason=exc.reason,
        message=_INELIGIBLE_MESSAGES[exc.reason],
    )
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


async def _parse_verdict_request(request: Request) -> VerdictRequest | JSONResponse:
    """Malformed JSON, then the strict body; every 422 is ``invalid_verdict``."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _verdict_validation_response(
            [
                DraftFieldErrorResponse(
                    field="$",
                    code="invalid_json",
                    message="Request body must be valid JSON.",
                )
            ]
        )
    try:
        return VerdictRequest.model_validate(raw_body)
    except ValidationError as exc:
        return _verdict_validation_response(_request_validation_errors(exc))


@router.post(
    "/test-runs/{run_id}/verdict",
    response_model=TestRunEvidenceResponse,
    responses={
        403: {"description": "Admin access or an authenticated principal required"},
        404: {"description": "Test run not found"},
        422: {"model": VerdictValidationErrorResponse | IneligibleForApprovalResponse},
    },
)
async def record_agent_test_run_verdict(
    request: Request,
    run_id: int,
    reviewer: Annotated[str, Depends(require_draft_write_principal)],
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> TestRunEvidenceResponse | JSONResponse:
    """Approve or reject one stored run; returns its evidence with the verdict.

    The reviewer is the authenticated principal, never a body field.  An
    identical re-submit writes nothing and returns the stored evidence.
    """
    parsed = await _parse_verdict_request(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    if not _is_storable_row_id(run_id):
        raise _test_run_not_found()
    try:
        evidence = await run_in_threadpool(
            workbench.record_verdict,
            db,
            run_id=run_id,
            verdict=parsed.verdict,
            reviewer=reviewer,
            notes=parsed.notes,
        )
    except VerdictRejected as exc:
        if any(issue.field == "actor" for issue in exc.issues):
            # The writer's blank-reviewer issue: the principal, not the body, is
            # at fault, so it is the principal gate's 403, never a client 422.
            raise HTTPException(
                status_code=403,
                detail="Authenticated principal required",
            ) from exc
        return _verdict_validation_response(
            [
                DraftFieldErrorResponse(
                    field=issue.field, code=issue.code, message=issue.message
                )
                for issue in exc.issues
            ]
        )
    except TestRunNotFound as exc:
        raise _test_run_not_found() from exc
    except IneligibleForApprovalError as exc:
        return _ineligible_response(exc)
    return _test_run_response(evidence)


@router.get("/readiness", response_model=DraftReadinessResponse)
def get_agent_definition_draft_readiness(
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> DraftReadinessResponse:
    """Each changed role's required cases and whether they block publication.

    Informational: #269's publication gate performs its own locked read.
    """
    try:
        result = workbench.draft_readiness(db)
    except GraphConfigurationIntegrityError as exc:
        # Includes the un-retried parent-handoff diagnosis, as ``/workbench``.
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc
    return DraftReadinessResponse.model_validate(result, from_attributes=True)


# --- Graph Release preview and publication (#269 Task 5) ----------------------
# Still the one admin router (C31/C35): a separate module decorating ``router``
# after ``main.py``'s ``include_router`` would register nothing.  The publish
# body is read only after both auth gates; the actor is the principal, never a
# body field.  Publication can wait on L0 behind a save's remote endpoint check,
# so it runs in the threadpool (C46); the preview is a plain ``def``, which
# FastAPI runs there.  Readiness is informational (C32): the evidence gate
# decides under its own locks.  Every outcome maps explicitly; an
# ``IntegrityError`` is never mapped and stays a 500 (#268 C7).


def _readiness_callable(workbench: AgentTestWorkbench) -> Callable[[Session], object]:
    """The one production binding to #268 readiness (C39).

    ``workbench`` is the route's resolved ``get_agent_test_workbench`` dependency,
    so one override of that dependency covers runs, verdicts and readiness.
    """
    return workbench.readiness_under_parent_lock


def _publication_validation_response(
    errors: list[DraftFieldErrorResponse],
) -> JSONResponse:
    response = PublicationValidationErrorResponse(code="invalid_publication", errors=errors)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


async def _parse_publish_request(
    request: Request,
) -> PublishReleaseRequest | JSONResponse:
    """Malformed JSON, then the strict body; every 422 is ``invalid_publication``."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _publication_validation_response(
            [
                DraftFieldErrorResponse(
                    field="$",
                    code="invalid_json",
                    message="Request body must be valid JSON.",
                )
            ]
        )
    try:
        return PublishReleaseRequest.model_validate(raw_body)
    except ValidationError as exc:
        return _publication_validation_response(_request_validation_errors(exc))


def _graph_integrity_failure(exc: GraphConfigurationIntegrityError) -> HTTPException:
    logger.exception("Persisted Graph Configuration is incomplete")
    return HTTPException(status_code=500, detail="Graph configuration is incomplete")


def _readiness_body(readiness: object) -> DraftReadinessResponse:
    return DraftReadinessResponse.model_validate(readiness, from_attributes=True)


def _release_preview_response(preview: ReleasePreview) -> ReleasePreviewResponse:
    return ReleasePreviewResponse(
        draft=DraftMetadataResponse.model_validate(preview.draft, from_attributes=True),
        active_release=ActiveReleaseResponse.model_validate(
            preview.active_release, from_attributes=True
        ),
        next_version_number=preview.next_version_number,
        changed=[
            ChangedDefinitionResponse(
                agent_key=item.agent_key,
                published_revision_id=item.published_revision_id,
                published_content_hash=item.published_content_hash,
                candidate_hash=item.candidate_hash,
                field_diffs=[
                    FieldDiffResponse(
                        field=diff.field,
                        published=diff.published,
                        candidate=diff.candidate,
                    )
                    for diff in item.field_diffs
                ],
            )
            for item in preview.changed
        ],
        readiness=_readiness_body(preview.readiness),
        validation_issues=[
            DraftFieldErrorResponse(
                field=issue.field, code=issue.code, message=issue.message
            )
            for issue in preview.validation_issues
        ],
        publishable=preview.publishable,
    )


def _published_response(outcome: PublishedRelease) -> PublishReleaseSuccessResponse:
    return PublishReleaseSuccessResponse(
        release=ActiveReleaseResponse.model_validate(outcome.release, from_attributes=True),
        previous_release_id=outcome.previous_release_id,
        changed_agents=list(outcome.changed_agent_keys),
        mappings={
            key: PublishedMappingResponse(
                agent_definition_revision_id=outcome.mappings[key].agent_definition_revision_id,
                content_hash=outcome.mappings[key].content_hash,
                reused=outcome.mappings[key].reused,
            )
            for key in GRAPH_V1_AGENT_KEYS
        },
        evidence=[
            ReleaseEvidenceResponse(
                agent_test_run_id=link.agent_test_run_id,
                agent_key=link.agent_key,
                test_case_id=link.test_case_id,
                evidence_kind=link.evidence_kind,
            )
            for link in outcome.evidence
        ],
        draft=DraftMetadataResponse.model_validate(outcome.draft, from_attributes=True),
    )


def _publication_refusal(
    outcome: PublicationConflict | NothingToPublish | PublicationNotReady,
) -> JSONResponse:
    response: StalePublicationResponse | NothingToPublishResponse | PublicationNotReadyResponse
    if isinstance(outcome, PublicationConflict):
        response = StalePublicationResponse(
            code="stale_publication",
            expected_lock_version=outcome.expected_lock_version,
            current_lock_version=outcome.current_lock_version,
            active_release=ReleaseIdentityResponse(
                release_id=outcome.active_release_id,
                version_number=outcome.active_version_number,
            ),
            draft=DraftMetadataResponse.model_validate(outcome.draft, from_attributes=True),
        )
    elif isinstance(outcome, NothingToPublish):
        response = NothingToPublishResponse(
            code="nothing_to_publish",
            active_release=ReleaseIdentityResponse(
                release_id=outcome.active_release_id,
                version_number=outcome.active_version_number,
            ),
            draft=DraftMetadataResponse.model_validate(outcome.draft, from_attributes=True),
        )
    else:
        response = PublicationNotReadyResponse(
            code="publication_not_ready",
            gaps=[
                PublicationGapResponse(
                    agent_key=gap.agent_key,
                    test_case_id=gap.test_case_id,
                    code=gap.code,
                )
                for gap in outcome.locked_gaps
            ],
            readiness=_readiness_body(outcome.readiness),
        )
    return JSONResponse(status_code=409, content=response.model_dump(mode="json"))


@router.get(
    "/release-preview",
    response_model=ReleasePreviewResponse,
    responses={403: {"description": "Admin access required"}},
)
def get_graph_release_preview(
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> ReleasePreviewResponse:
    """What publishing the shared draft now would change; it writes nothing."""
    try:
        preview = GraphConfiguration().preview_release(
            db, readiness=_readiness_callable(workbench)
        )
    except GraphConfigurationIntegrityError as exc:
        raise _graph_integrity_failure(exc) from exc
    return _release_preview_response(preview)


@router.post(
    "/releases",
    response_model=PublishReleaseSuccessResponse,
    responses={
        403: {"description": "Admin access or an authenticated principal required"},
        409: {
            "model": StalePublicationResponse
            | NothingToPublishResponse
            | PublicationNotReadyResponse
        },
        422: {"model": PublicationValidationErrorResponse},
    },
)
async def publish_graph_release(
    request: Request,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    workbench: Annotated[AgentTestWorkbench, Depends(get_agent_test_workbench)],
    db: Session = Depends(get_db),
) -> PublishReleaseSuccessResponse | JSONResponse:
    """Publish the shared draft as the next complete Graph Version.

    The body is exactly ``{"lock_version", "release_note"}``.  The route builds
    the production evidence gate; its readiness is the #268 binding (C39).
    """
    parsed = await _parse_publish_request(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    gate = ApprovalEvidenceGate(readiness=_readiness_callable(workbench))
    try:
        outcome = await run_in_threadpool(
            GraphConfiguration().publish_draft,
            db,
            expected_lock_version=parsed.lock_version,
            release_note=parsed.release_note,
            actor=actor,
            evidence_gate=gate,
        )
    except PublicationRejected as exc:
        if any(issue.field == "actor" for issue in exc.issues):
            # The principal, not the body, is at fault (the verdict route's rule).
            raise HTTPException(
                status_code=403,
                detail="Authenticated principal required",
            ) from exc
        return _publication_validation_response(
            [
                DraftFieldErrorResponse(
                    field=issue.field, code=issue.code, message=issue.message
                )
                for issue in exc.issues
            ]
        )
    except GraphConfigurationIntegrityError as exc:
        raise _graph_integrity_failure(exc) from exc

    if isinstance(outcome, PublishedRelease):
        return _published_response(outcome)
    if isinstance(outcome, (PublicationConflict, NothingToPublish, PublicationNotReady)):
        return _publication_refusal(outcome)
    raise AssertionError(f"Unexpected publication outcome: {type(outcome)!r}")
