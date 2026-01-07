"""
Slide Deck Prompt Library API endpoints.

CRUD operations for the global library of slide deck prompts.
These prompts guide the agent in creating specific presentation types.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.database.models import SlideDeckPromptLibrary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deck-prompts", tags=["deck-prompts"])


# Request/Response schemas

class DeckPromptBase(BaseModel):
    """Base schema for deck prompts."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    prompt_content: str = Field(..., min_length=1)


class DeckPromptCreate(DeckPromptBase):
    """Request to create a deck prompt."""
    pass


class DeckPromptUpdate(BaseModel):
    """Request to update a deck prompt."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    prompt_content: Optional[str] = Field(None, min_length=1)


class DeckPromptResponse(DeckPromptBase):
    """Response schema for deck prompts."""
    id: int
    is_active: bool
    created_by: Optional[str]
    created_at: str
    updated_by: Optional[str]
    updated_at: str

    class Config:
        from_attributes = True


class DeckPromptListResponse(BaseModel):
    """Response for listing deck prompts."""
    prompts: List[DeckPromptResponse]
    total: int


# API endpoints

@router.get("", response_model=DeckPromptListResponse)
def list_deck_prompts(
    include_inactive: bool = False,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all deck prompts from the library.
    
    Args:
        include_inactive: If True, include soft-deleted prompts
        category: Filter by category (optional)
        
    Returns:
        List of deck prompts
    """
    try:
        query = db.query(SlideDeckPromptLibrary)
        
        if not include_inactive:
            query = query.filter(SlideDeckPromptLibrary.is_active == True)
        
        if category:
            query = query.filter(SlideDeckPromptLibrary.category == category)
        
        prompts = query.order_by(SlideDeckPromptLibrary.name).all()
        
        return DeckPromptListResponse(
            prompts=[
                DeckPromptResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    category=p.category,
                    prompt_content=p.prompt_content,
                    is_active=p.is_active,
                    created_by=p.created_by,
                    created_at=p.created_at.isoformat(),
                    updated_by=p.updated_by,
                    updated_at=p.updated_at.isoformat(),
                )
                for p in prompts
            ],
            total=len(prompts),
        )
    except Exception as e:
        logger.error(f"Error listing deck prompts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list deck prompts",
        )


@router.get("/{prompt_id}", response_model=DeckPromptResponse)
def get_deck_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a specific deck prompt by ID.
    
    Args:
        prompt_id: Deck prompt ID
        
    Returns:
        Deck prompt details
        
    Raises:
        404: Prompt not found
    """
    try:
        prompt = db.query(SlideDeckPromptLibrary).filter(
            SlideDeckPromptLibrary.id == prompt_id
        ).first()
        
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deck prompt {prompt_id} not found",
            )
        
        return DeckPromptResponse(
            id=prompt.id,
            name=prompt.name,
            description=prompt.description,
            category=prompt.category,
            prompt_content=prompt.prompt_content,
            is_active=prompt.is_active,
            created_by=prompt.created_by,
            created_at=prompt.created_at.isoformat(),
            updated_by=prompt.updated_by,
            updated_at=prompt.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deck prompt {prompt_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get deck prompt",
        )


@router.post("", response_model=DeckPromptResponse, status_code=status.HTTP_201_CREATED)
def create_deck_prompt(
    request: DeckPromptCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new deck prompt in the library.
    
    Args:
        request: Deck prompt creation request
        
    Returns:
        Created deck prompt
        
    Raises:
        409: Prompt with same name already exists
    """
    try:
        # Check for existing prompt with same name
        existing = db.query(SlideDeckPromptLibrary).filter(
            SlideDeckPromptLibrary.name == request.name
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Deck prompt with name '{request.name}' already exists",
            )
        
        # Get current user
        try:
            from src.core.databricks_client import get_databricks_client
            client = get_databricks_client()
            user = client.current_user.me().user_name
        except Exception:
            user = "system"
        
        prompt = SlideDeckPromptLibrary(
            name=request.name,
            description=request.description,
            category=request.category,
            prompt_content=request.prompt_content,
            is_active=True,
            created_by=user,
            updated_by=user,
        )
        
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        
        logger.info(f"Created deck prompt: {prompt.name} (id={prompt.id})")
        
        return DeckPromptResponse(
            id=prompt.id,
            name=prompt.name,
            description=prompt.description,
            category=prompt.category,
            prompt_content=prompt.prompt_content,
            is_active=prompt.is_active,
            created_by=prompt.created_by,
            created_at=prompt.created_at.isoformat(),
            updated_by=prompt.updated_by,
            updated_at=prompt.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating deck prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create deck prompt",
        )


@router.put("/{prompt_id}", response_model=DeckPromptResponse)
def update_deck_prompt(
    prompt_id: int,
    request: DeckPromptUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing deck prompt.
    
    Args:
        prompt_id: Deck prompt ID
        request: Update request (only provided fields are updated)
        
    Returns:
        Updated deck prompt
        
    Raises:
        404: Prompt not found
        409: Name conflicts with another prompt
    """
    try:
        prompt = db.query(SlideDeckPromptLibrary).filter(
            SlideDeckPromptLibrary.id == prompt_id
        ).first()
        
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deck prompt {prompt_id} not found",
            )
        
        # Check for name conflict if name is being updated
        if request.name and request.name != prompt.name:
            existing = db.query(SlideDeckPromptLibrary).filter(
                SlideDeckPromptLibrary.name == request.name,
                SlideDeckPromptLibrary.id != prompt_id,
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Deck prompt with name '{request.name}' already exists",
                )
            prompt.name = request.name
        
        if request.description is not None:
            prompt.description = request.description
        if request.category is not None:
            prompt.category = request.category
        if request.prompt_content is not None:
            prompt.prompt_content = request.prompt_content
        
        # Update the user
        try:
            from src.core.databricks_client import get_databricks_client
            client = get_databricks_client()
            prompt.updated_by = client.current_user.me().user_name
        except Exception:
            prompt.updated_by = "system"
        
        db.commit()
        db.refresh(prompt)
        
        logger.info(f"Updated deck prompt: {prompt.name} (id={prompt.id})")
        
        return DeckPromptResponse(
            id=prompt.id,
            name=prompt.name,
            description=prompt.description,
            category=prompt.category,
            prompt_content=prompt.prompt_content,
            is_active=prompt.is_active,
            created_by=prompt.created_by,
            created_at=prompt.created_at.isoformat(),
            updated_by=prompt.updated_by,
            updated_at=prompt.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating deck prompt {prompt_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update deck prompt",
        )


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck_prompt(
    prompt_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
):
    """
    Delete a deck prompt (soft-delete by default).
    
    Args:
        prompt_id: Deck prompt ID
        hard_delete: If True, permanently delete. Otherwise, mark as inactive.
        
    Raises:
        404: Prompt not found
    """
    try:
        prompt = db.query(SlideDeckPromptLibrary).filter(
            SlideDeckPromptLibrary.id == prompt_id
        ).first()
        
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deck prompt {prompt_id} not found",
            )
        
        if hard_delete:
            db.delete(prompt)
            logger.info(f"Hard deleted deck prompt: {prompt.name} (id={prompt.id})")
        else:
            prompt.is_active = False
            try:
                from src.core.databricks_client import get_databricks_client
                client = get_databricks_client()
                prompt.updated_by = client.current_user.me().user_name
            except Exception:
                prompt.updated_by = "system"
            logger.info(f"Soft deleted deck prompt: {prompt.name} (id={prompt.id})")
        
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting deck prompt {prompt_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete deck prompt",
        )

