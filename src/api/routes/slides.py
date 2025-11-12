"""Slide manipulation endpoints for reordering, editing, duplicating, and deleting slides.

Phase 2: Single session endpoints.
Phase 4: Add session management with session_id parameter.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.services.chat_service import get_chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slides", tags=["slides"])


class ReorderRequest(BaseModel):
    """Request to reorder slides."""
    new_order: List[int]


class UpdateSlideRequest(BaseModel):
    """Request to update a slide's HTML."""
    html: str


@router.get("")
async def get_slides():
    """Get current slide deck.
    
    Phase 4: Add session_id query parameter
    
    Returns:
        Slide deck dictionary
    
    Raises:
        HTTPException: 404 if no slides available, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = chat_service.get_slides()
        
        if not result:
            raise HTTPException(status_code=404, detail="No slides available")
        
        logger.info("Retrieved slides", extra={"slide_count": result.get("slide_count", 0)})
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get slides: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/reorder")
async def reorder_slides(request: ReorderRequest):
    """Reorder slides.
    
    Phase 4: Add session_id to request body
    
    Args:
        request: ReorderRequest with new slide order
    
    Returns:
        Updated slide deck
    
    Raises:
        HTTPException: 400 for validation errors, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = chat_service.reorder_slides(request.new_order)
        
        logger.info(
            "Reordered slides",
            extra={"new_order": request.new_order}
        )
        return result
        
    except ValueError as e:
        logger.warning(f"Validation error in reorder_slides: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reorder slides: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{index}")
async def update_slide(index: int, request: UpdateSlideRequest):
    """Update a single slide's HTML.
    
    Phase 4: Add session_id query parameter
    
    Args:
        index: Slide index to update
        request: UpdateSlideRequest with new HTML
    
    Returns:
        Updated slide information
    
    Raises:
        HTTPException: 400 for validation errors, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = chat_service.update_slide(index, request.html)
        
        logger.info("Updated slide", extra={"index": index})
        return result
        
    except ValueError as e:
        logger.warning(f"Validation error in update_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{index}/duplicate")
async def duplicate_slide(index: int):
    """Duplicate a slide.
    
    Phase 4: Add session_id query parameter
    
    Args:
        index: Slide index to duplicate
    
    Returns:
        Updated slide deck
    
    Raises:
        HTTPException: 400 for validation errors, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = chat_service.duplicate_slide(index)
        
        logger.info("Duplicated slide", extra={"index": index})
        return result
        
    except ValueError as e:
        logger.warning(f"Validation error in duplicate_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to duplicate slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{index}")
async def delete_slide(index: int):
    """Delete a slide.
    
    Phase 4: Add session_id query parameter
    
    Args:
        index: Slide index to delete
    
    Returns:
        Updated slide deck
    
    Raises:
        HTTPException: 400 for validation errors, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = chat_service.delete_slide(index)
        
        logger.info("Deleted slide", extra={"index": index})
        return result
        
    except ValueError as e:
        logger.warning(f"Validation error in delete_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

