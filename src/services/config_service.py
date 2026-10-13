"""Configuration service for managing settings within profiles."""
from sqlalchemy.orm import Session

from src.database.models import (
    ConfigPrompts,
)


class ConfigService:
    """Manage configuration within profiles."""

    def __init__(self, db: Session):
        self.db = db

    # Prompts

    def get_prompts_config(self, profile_id: int) -> ConfigPrompts:
        """Get prompts settings for specific profile."""
        config = self.db.query(ConfigPrompts).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"Prompts settings not found for profile {profile_id}")
        return config

    def update_prompts_config(
        self,
        profile_id: int,
        selected_deck_prompt_id: int = None,
        selected_slide_style_id: int = None,
        user: str = None,
        clear_deck_prompt: bool = False,
        clear_slide_style: bool = False,
    ) -> ConfigPrompts:
        """Update prompts configuration.
        
        Args:
            profile_id: Profile ID
            selected_deck_prompt_id: ID of deck prompt from library (optional)
            selected_slide_style_id: ID of slide style from library (optional)
            user: User making the change
            clear_deck_prompt: If True, clear the selected deck prompt
            clear_slide_style: If True, clear the selected slide style
        """
        config = self.get_prompts_config(profile_id)

        changes = {}

        # Handle deck prompt selection
        if clear_deck_prompt:
            if config.selected_deck_prompt_id is not None:
                changes["selected_deck_prompt_id"] = {"old": config.selected_deck_prompt_id, "new": None}
                config.selected_deck_prompt_id = None
        elif selected_deck_prompt_id is not None and selected_deck_prompt_id != config.selected_deck_prompt_id:
            changes["selected_deck_prompt_id"] = {"old": config.selected_deck_prompt_id, "new": selected_deck_prompt_id}
            config.selected_deck_prompt_id = selected_deck_prompt_id

        # Handle slide style selection
        if clear_slide_style:
            if config.selected_slide_style_id is not None:
                changes["selected_slide_style_id"] = {"old": config.selected_slide_style_id, "new": None}
                config.selected_slide_style_id = None
        elif selected_slide_style_id is not None and selected_slide_style_id != config.selected_slide_style_id:
            changes["selected_slide_style_id"] = {"old": config.selected_slide_style_id, "new": selected_slide_style_id}
            config.selected_slide_style_id = selected_slide_style_id

        self.db.commit()
        self.db.refresh(config)

        return config


