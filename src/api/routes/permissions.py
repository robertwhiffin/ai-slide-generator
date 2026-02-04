"""Session permission management endpoints.

Provides APIs for managing session access control:
- Grant/revoke user and group permissions
- List session permissions
- Change session visibility
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.services.session_manager import (
    SessionNotFoundError,
    get_session_manager,
)
from src.services.permission_service import PermissionDeniedError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/permissions", tags=["permissions"])


class GrantPermissionRequest(BaseModel):
    """Request to grant permission to a user or group."""
    
    principal_type: str = Field(
        ...,
        description="Type of principal: 'user' or 'group'",
        pattern="^(user|group)$",
    )
    principal_id: str = Field(
        ...,
        description="User email or Databricks group name",
        min_length=1,
    )
    permission: str = Field(
        ...,
        description="Permission level: 'read' or 'edit'",
        pattern="^(read|edit)$",
    )


class RevokePermissionRequest(BaseModel):
    """Request to revoke permission from a user or group."""
    
    principal_type: str = Field(
        ...,
        description="Type of principal: 'user' or 'group'",
        pattern="^(user|group)$",
    )
    principal_id: str = Field(
        ...,
        description="User email or Databricks group name",
        min_length=1,
    )


class SetVisibilityRequest(BaseModel):
    """Request to change session visibility."""
    
    visibility: str = Field(
        ...,
        description="Visibility level: 'private', 'shared', or 'workspace'",
        pattern="^(private|shared|workspace)$",
    )


@router.post("")
async def grant_permission(session_id: str, request: GrantPermissionRequest):
    """Grant permission to a user or group on a session.
    
    Only the session owner can grant permissions.
    
    Args:
        session_id: Session to grant permission on
        request: Permission grant details
        
    Returns:
        Created permission info
        
    Raises:
        404: Session not found
        403: User is not the session owner
        500: Internal error
    """
    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.grant_session_permission,
            session_id=session_id,
            principal_type=request.principal_type,
            principal_id=request.principal_id,
            permission=request.permission,
        )
        
        logger.info(
            "Permission granted",
            extra={
                "session_id": session_id,
                "principal": f"{request.principal_type}:{request.principal_id}",
                "permission": request.permission,
            },
        )
        
        return result
        
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to grant permission: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to grant permission: {str(e)}")


@router.delete("")
async def revoke_permission(session_id: str, request: RevokePermissionRequest):
    """Revoke permission from a user or group on a session.
    
    Only the session owner can revoke permissions.
    
    Args:
        session_id: Session to revoke permission on
        request: Permission revoke details
        
    Returns:
        Status of revocation
        
    Raises:
        404: Session not found
        403: User is not the session owner
        500: Internal error
    """
    try:
        session_manager = get_session_manager()
        revoked = await asyncio.to_thread(
            session_manager.revoke_session_permission,
            session_id=session_id,
            principal_type=request.principal_type,
            principal_id=request.principal_id,
        )
        
        if revoked:
            logger.info(
                "Permission revoked",
                extra={
                    "session_id": session_id,
                    "principal": f"{request.principal_type}:{request.principal_id}",
                },
            )
            return {"status": "revoked", "session_id": session_id}
        else:
            return {"status": "not_found", "session_id": session_id}
        
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to revoke permission: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revoke permission: {str(e)}")


@router.get("")
async def list_permissions(session_id: str):
    """List all permissions for a session.
    
    Requires read permission on the session.
    
    Args:
        session_id: Session to list permissions for
        
    Returns:
        List of permissions
        
    Raises:
        404: Session not found
        403: User lacks read permission
        500: Internal error
    """
    try:
        session_manager = get_session_manager()
        permissions = await asyncio.to_thread(
            session_manager.list_session_permissions,
            session_id=session_id,
        )
        
        return {
            "session_id": session_id,
            "permissions": permissions,
            "count": len(permissions),
        }
        
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list permissions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list permissions: {str(e)}")


@router.patch("/visibility")
async def set_visibility(session_id: str, request: SetVisibilityRequest):
    """Change session visibility level.
    
    Only the session owner can change visibility.
    
    Visibility levels:
    - private: Only owner can access
    - shared: Owner + explicitly granted users/groups
    - workspace: All workspace users can view (read-only unless explicitly granted edit)
    
    Args:
        session_id: Session to update
        request: New visibility level
        
    Returns:
        Updated session info
        
    Raises:
        404: Session not found
        403: User is not the session owner
        500: Internal error
    """
    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.set_session_visibility,
            session_id=session_id,
            visibility=request.visibility,
        )
        
        logger.info(
            "Session visibility changed",
            extra={"session_id": session_id, "visibility": request.visibility},
        )
        
        return result
        
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to set visibility: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set visibility: {str(e)}")
