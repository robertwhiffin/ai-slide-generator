"""Admin-only Agent Definition workbench routes."""

import json
import logging
from collections.abc import Mapping
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.schemas.agent_definitions import (
    CustomTextBlockRequest,
    DraftDefinitionResponse,
    DraftFieldErrorResponse,
    DraftLockRequest,
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
    LegacyPromptSourceResponse,
    ModelEndpointCatalogErrorResponse,
    StructuredOutputProbeFailureResponse,
    StructuredOutputProbeSuccessResponse,
    SystemModelDiscoveryResponse,
    SystemModelEndpointResponse,
)
from src.core import databricks_client
from src.core.database import get_db
from src.core.user_context import get_current_user
from src.services import model_endpoint_catalog
from src.services.agent_schema_types import SchemaOverlay
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    RemoteEndpointDraftValidator,
    build_remote_endpoint_draft_validator,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    AssemblyRulesV2,
)
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
