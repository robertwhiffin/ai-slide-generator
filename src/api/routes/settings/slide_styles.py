"""
Slide Style Library API endpoints.

CRUD operations for the global library of slide styles.
These styles control the visual appearance of generated slides
(typography, colors, layout, etc.).
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.database.models import SlideStyleLibrary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slide-styles", tags=["slide-styles"])


# Request/Response schemas

class SlideStyleBase(BaseModel):
    """Base schema for slide styles."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    style_content: str = Field(..., min_length=1)


class SlideStyleCreate(SlideStyleBase):
    """Request to create a slide style."""
    pass


class SlideStyleUpdate(BaseModel):
    """Request to update a slide style."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    style_content: Optional[str] = Field(None, min_length=1)


class SlideStyleResponse(SlideStyleBase):
    """Response schema for slide styles."""
    id: int
    is_active: bool
    is_system: bool  # Protected system styles cannot be edited/deleted
    created_by: Optional[str]
    created_at: str
    updated_by: Optional[str]
    updated_at: str

    class Config:
        from_attributes = True


class SlideStyleListResponse(BaseModel):
    """Response for listing slide styles."""
    styles: List[SlideStyleResponse]
    total: int


# API endpoints

@router.get("", response_model=SlideStyleListResponse)
def list_slide_styles(
    include_inactive: bool = False,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all slide styles from the library.
    
    Args:
        include_inactive: If True, include soft-deleted styles
        category: Filter by category (optional)
        
    Returns:
        List of slide styles
    """
    try:
        query = db.query(SlideStyleLibrary)
        
        if not include_inactive:
            query = query.filter(SlideStyleLibrary.is_active == True)
        
        if category:
            query = query.filter(SlideStyleLibrary.category == category)
        
        styles = query.order_by(SlideStyleLibrary.name).all()
        
        return SlideStyleListResponse(
            styles=[
                SlideStyleResponse(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    category=s.category,
                    style_content=s.style_content,
                    is_active=s.is_active,
                    is_system=s.is_system,
                    created_by=s.created_by,
                    created_at=s.created_at.isoformat(),
                    updated_by=s.updated_by,
                    updated_at=s.updated_at.isoformat(),
                )
                for s in styles
            ],
            total=len(styles),
        )
    except Exception as e:
        logger.error(f"Error listing slide styles: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list slide styles",
        )


@router.get("/{style_id}", response_model=SlideStyleResponse)
def get_slide_style(
    style_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a specific slide style by ID.
    
    Args:
        style_id: Slide style ID
        
    Returns:
        Slide style details
        
    Raises:
        404: Style not found
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            is_active=style.is_active,
            is_system=style.is_system,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get slide style",
        )


@router.post("", response_model=SlideStyleResponse, status_code=status.HTTP_201_CREATED)
def create_slide_style(
    request: SlideStyleCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new slide style in the library.
    
    Args:
        request: Slide style creation request
        
    Returns:
        Created slide style
        
    Raises:
        409: Style with same name already exists
    """
    try:
        # Check for existing style with same name
        existing = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.name == request.name
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Slide style with name '{request.name}' already exists",
            )
        
        # Get current user (skip Databricks call in test/dev to avoid network timeout)
        if os.getenv("ENVIRONMENT") in ("development", "test"):
            user = "system"
        else:
            try:
                from src.core.databricks_client import get_user_client
                client = get_user_client()
                user = client.current_user.me().user_name
            except Exception:
                user = "system"
        
        style = SlideStyleLibrary(
            name=request.name,
            description=request.description,
            category=request.category,
            style_content=request.style_content,
            is_active=True,
            created_by=user,
            updated_by=user,
        )
        
        db.add(style)
        db.commit()
        db.refresh(style)
        
        logger.info(f"Created slide style: {style.name} (id={style.id})")
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            is_active=style.is_active,
            is_system=style.is_system,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating slide style: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create slide style",
        )


@router.put("/{style_id}", response_model=SlideStyleResponse)
def update_slide_style(
    style_id: int,
    request: SlideStyleUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing slide style.
    
    Args:
        style_id: Slide style ID
        request: Update request (only provided fields are updated)
        
    Returns:
        Updated slide style
        
    Raises:
        404: Style not found
        409: Name conflicts with another style
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        # Protect system styles from editing
        if style.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System styles cannot be modified",
            )
        
        # Check for name conflict if name is being updated
        if request.name and request.name != style.name:
            existing = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.name == request.name,
                SlideStyleLibrary.id != style_id,
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slide style with name '{request.name}' already exists",
                )
            style.name = request.name
        
        if request.description is not None:
            style.description = request.description
        if request.category is not None:
            style.category = request.category
        if request.style_content is not None:
            style.style_content = request.style_content
        
        # Update the user (skip Databricks call in test/dev to avoid network timeout)
        if os.getenv("ENVIRONMENT") in ("development", "test"):
            style.updated_by = "system"
        else:
            try:
                from src.core.databricks_client import get_user_client
                client = get_user_client()
                style.updated_by = client.current_user.me().user_name
            except Exception:
                style.updated_by = "system"
        
        db.commit()
        db.refresh(style)
        
        logger.info(f"Updated slide style: {style.name} (id={style.id})")
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            is_active=style.is_active,
            is_system=style.is_system,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update slide style",
        )


@router.delete("/{style_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slide_style(
    style_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
):
    """
    Delete a slide style (soft-delete by default).
    
    Args:
        style_id: Slide style ID
        hard_delete: If True, permanently delete. Otherwise, mark as inactive.
        
    Raises:
        404: Style not found
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        # Protect system styles from deletion
        if style.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System styles cannot be deleted",
            )
        
        if hard_delete:
            db.delete(style)
            logger.info(f"Hard deleted slide style: {style.name} (id={style.id})")
        else:
            style.is_active = False
            # Update the user (skip Databricks call in test/dev to avoid network timeout)
            if os.getenv("ENVIRONMENT") in ("development", "test"):
                style.updated_by = "system"
            else:
                try:
                    from src.core.databricks_client import get_user_client
                    client = get_user_client()
                    style.updated_by = client.current_user.me().user_name
                except Exception:
                    style.updated_by = "system"
            logger.info(f"Soft deleted slide style: {style.name} (id={style.id})")
        
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete slide style",
        )
