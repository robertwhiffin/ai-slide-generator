"""Admin-only Agent Definition workbench routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.schemas.agent_definitions import GraphWorkbenchResponse
from src.core.database import get_db
from src.services.graph_configuration import (
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/agent-definitions",
    tags=["admin", "agent-definitions"],
    dependencies=[Depends(require_admin)],
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
