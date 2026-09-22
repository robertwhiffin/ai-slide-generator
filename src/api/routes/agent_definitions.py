"""Admin-only Agent Definition workbench routes."""

import json
import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.schemas.agent_definitions import (
    DraftDefinitionResponse,
    DraftFieldErrorResponse,
    DraftSaveConflictResponse,
    DraftSaveConflictServerResponse,
    DraftSaveRequest,
    DraftSaveSuccessResponse,
    DraftValidationErrorResponse,
    EditableModelDraftModelRequest,
    EditableModelDraftRequest,
    GraphWorkbenchResponse,
)
from src.core.database import get_db
from src.core.user_context import get_current_user
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, AgentKey

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


_OWNED_FIELD_MESSAGES = {
    "candidate.prompt_text": "Prompt text must not be blank.",
    "candidate.model.endpoint_name": "Endpoint name must not be blank.",
    "candidate.model.temperature": "Temperature must be between 0 and 1.",
    "candidate.model.max_tokens": "Maximum tokens must be a positive integer.",
    "candidate.model.top_p": "Top-p must be between 0 and 1.",
}


def _draft_validation_response(
    errors: list[DraftFieldErrorResponse],
) -> JSONResponse:
    response = DraftValidationErrorResponse(code="invalid_draft", errors=errors)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


def _validation_error_code(field: str, error_type: str) -> str:
    if error_type == "extra_forbidden":
        return "extra_forbidden"
    if error_type == "finite_number":
        return "finite_number"
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


def _request_validation_errors(exc: ValidationError) -> list[DraftFieldErrorResponse]:
    errors: list[DraftFieldErrorResponse] = []
    for error in exc.errors():
        location = error["loc"]
        field = ".".join(str(part) for part in location) or "$"
        error_type = error["type"]
        code = _validation_error_code(field, error_type)
        errors.append(
            DraftFieldErrorResponse(
                field=field,
                code=code,
                message=_OWNED_FIELD_MESSAGES.get(field, error["msg"]),
            )
        )
    return errors


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


@router.put("/draft/{agent_key}", response_model=DraftSaveSuccessResponse)
async def save_agent_definition_draft(
    request: Request,
    agent_key: str,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> DraftSaveSuccessResponse | JSONResponse:
    """Save exactly the editable candidate fields through the locked draft facade."""
    try:
        raw_body = await request.json()
    except json.JSONDecodeError:
        return _malformed_json_response()

    if agent_key not in GRAPH_V1_AGENT_KEYS:
        return _draft_validation_response(
            [
                DraftFieldErrorResponse(
                    field="agent_key",
                    code="unknown_agent",
                    message="Agent key must identify an editable model role.",
                )
            ]
        )

    try:
        save_request = DraftSaveRequest.model_validate(raw_body)
    except ValidationError as exc:
        return _draft_validation_response(_request_validation_errors(exc))

    candidate = EditableModelDraft(
        prompt_text=save_request.candidate.prompt_text,
        endpoint_name=save_request.candidate.model.endpoint_name,
        temperature=save_request.candidate.model.temperature,
        max_tokens=save_request.candidate.model.max_tokens,
        top_p=save_request.candidate.model.top_p,
    )
    try:
        outcome = GraphConfiguration().save_editable_model_draft(
            db,
            agent_key=cast(AgentKey, agent_key),
            expected_lock_version=save_request.lock_version,
            candidate=candidate,
            actor=actor,
        )
    except DraftContentRejected as exc:
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
    except GraphConfigurationIntegrityError as exc:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(
            status_code=500,
            detail="Graph configuration is incomplete",
        ) from exc

    if isinstance(outcome, DraftSaveResult):
        return DraftSaveSuccessResponse.model_validate(outcome, from_attributes=True)

    if isinstance(outcome, DraftSaveConflict):
        client_candidate = EditableModelDraftRequest(
            prompt_text=outcome.client_candidate.prompt_text,
            model=EditableModelDraftModelRequest(
                endpoint_name=outcome.client_candidate.endpoint_name,
                temperature=outcome.client_candidate.temperature,
                max_tokens=outcome.client_candidate.max_tokens,
                top_p=outcome.client_candidate.top_p,
            ),
        )
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

    raise AssertionError(f"Unexpected draft save outcome: {type(outcome)!r}")
