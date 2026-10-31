"""Admin routes for the packaged prompt update (prompt shipping Task 3).

Status and adopt for the prompts that ship in the app package.  They only call the
facade helpers in ``src.services.graph_configuration``; they never read the
packaged manifest themselves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.routes.agent_definitions import (
    _graph_integrity_failure,
    _issue_responses,
    _json,
    _parse_release_body,
    require_draft_write_principal,
)
from src.api.schemas.agent_definitions import (
    ActiveReleaseResponse,
    DraftFieldErrorResponse,
    DraftMetadataResponse,
)
from src.api.schemas.graph_releases import (
    AdoptPackagedUpdateRequest,
    AdoptValidationErrorResponse,
    FieldDiffResponse,
    NothingToAdoptResponse,
    PackagedAdoptSuccessResponse,
    PackagedAgentDiffResponse,
    PackagedInvalidResponse,
    PackagedUpdateResponse,
    ReleaseIdentityResponse,
    StalePublicationResponse,
)
from src.core.database import get_db
from src.services.graph_configuration import (
    GraphConfigurationIntegrityError,
    PackagedUpdateStatus,
    PublicationConflict,
    PublicationRejected,
    ShipInvalid,
    ShipNothing,
    Shipped,
    adopt_packaged_update,
    read_packaged_update_status,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

router = APIRouter(
    prefix="/api/admin/graph-shipping",
    tags=["admin", "graph-shipping"],
    dependencies=[Depends(require_admin)],
)


def _adopt_validation_response(errors: list[DraftFieldErrorResponse]) -> JSONResponse:
    return _json(422, AdoptValidationErrorResponse(code="invalid_adopt_request", errors=errors))


# --- Packaged prompt update: status and adopt -----------------------------------
# The routes only call the facade helpers; they never read the packaged manifest.


def _packaged_update_response(status: PackagedUpdateStatus) -> PackagedUpdateResponse:
    return PackagedUpdateResponse(
        available=status.available,
        differing_agents=list(status.differing_agents),
        blocked_reason=status.blocked_reason,
        hand_edited_agents=list(status.hand_edited_agents),
        validation_issues=_issue_responses(status.validation_issues),
        diffs=[
            PackagedAgentDiffResponse(
                agent_key=key,
                field_diffs=[
                    FieldDiffResponse(
                        field=diff.field, published=diff.published, candidate=diff.candidate
                    )
                    for diff in diffs
                ],
            )
            for key, diffs in status.field_diffs.items()
        ],
        active_version_number=status.active_release.version_number,
        lock_version=status.lock_version,
    )


@router.get(
    "/packaged-update",
    response_model=PackagedUpdateResponse,
    responses={403: {"description": "Admin access required"}},
)
async def get_packaged_update(db: Session = Depends(get_db)) -> PackagedUpdateResponse:
    """The packaged prompts against the active release.  Writes nothing."""
    try:
        status = await run_in_threadpool(read_packaged_update_status, db)
    except GraphConfigurationIntegrityError as exc:
        raise _graph_integrity_failure(exc) from exc
    return _packaged_update_response(status)


@router.post(
    "/packaged-update/adopt",
    response_model=PackagedAdoptSuccessResponse,
    responses={
        403: {"description": "Admin access or an authenticated principal required"},
        409: {"model": StalePublicationResponse | NothingToAdoptResponse},
        422: {"model": AdoptValidationErrorResponse | PackagedInvalidResponse},
    },
)
async def adopt_packaged_update_route(
    request: Request,
    actor: Annotated[str, Depends(require_draft_write_principal)],
    db: Session = Depends(get_db),
) -> PackagedAdoptSuccessResponse | JSONResponse:
    """Publish the packaged prompts as the next Graph Version.  Body: ``{"lock_version"}``."""
    parsed = await _parse_release_body(
        request, AdoptPackagedUpdateRequest, _adopt_validation_response
    )
    if isinstance(parsed, JSONResponse):
        return parsed
    try:
        outcome = await run_in_threadpool(
            adopt_packaged_update,
            db,
            actor=actor,
            expected_lock_version=parsed.lock_version,
        )
    except PublicationRejected as exc:
        if any(issue.field == "actor" for issue in exc.issues):
            raise HTTPException(
                status_code=403, detail="Authenticated principal required"
            ) from exc
        return _adopt_validation_response(_issue_responses(exc.issues))
    except GraphConfigurationIntegrityError as exc:
        raise _graph_integrity_failure(exc) from exc

    if isinstance(outcome, Shipped):
        return PackagedAdoptSuccessResponse(
            release=ActiveReleaseResponse.model_validate(
                outcome.published.release, from_attributes=True
            ),
            changed_agent_keys=list(outcome.published.changed_agent_keys),
            draft_effect={key: outcome.draft_effect[key] for key in GRAPH_V1_AGENT_KEYS},
        )
    if isinstance(outcome, PublicationConflict):
        return _json(
            409,
            StalePublicationResponse(
                code="stale_publication",
                expected_lock_version=outcome.expected_lock_version,
                current_lock_version=outcome.current_lock_version,
                active_release=ReleaseIdentityResponse(
                    release_id=outcome.active_release_id,
                    version_number=outcome.active_version_number,
                ),
                draft=DraftMetadataResponse.model_validate(
                    outcome.draft, from_attributes=True
                ),
            ),
        )
    if isinstance(outcome, ShipNothing):
        return _json(409, NothingToAdoptResponse(code="nothing_to_adopt"))
    if isinstance(outcome, ShipInvalid):
        return _json(
            422,
            PackagedInvalidResponse(
                code="packaged_invalid", errors=_issue_responses(outcome.issues)
            ),
        )
    raise AssertionError(f"Unexpected adopt outcome: {type(outcome)!r}")
