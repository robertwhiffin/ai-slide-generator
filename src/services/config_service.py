"""Configuration service for managing settings within profiles."""
from typing import List

from sqlalchemy.orm import Session

from src.core.databricks_client import get_databricks_client
from src.database.models import (
    ConfigAIInfra,
    ConfigHistory,
    ConfigMLflow,
    ConfigPrompts,
)


class ConfigService:
    """Manage configuration within profiles."""

    def __init__(self, db: Session):
        self.db = db

    # AI Infrastructure

    def get_ai_infra_config(self, profile_id: int) -> ConfigAIInfra:
        """Get AI db_app_deployment settings for specific profile."""
        config = self.db.query(ConfigAIInfra).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"AI db_app_deployment settings not found for profile {profile_id}")
        return config

    def update_ai_infra_config(
        self,
        profile_id: int,
        llm_endpoint: str = None,
        llm_temperature: float = None,
        llm_max_tokens: int = None,
        user: str = None,
    ) -> ConfigAIInfra:
        """Update AI infrastructure configuration."""
        config = self.get_ai_infra_config(profile_id)

        changes = {}

        if llm_endpoint is not None and llm_endpoint != config.llm_endpoint:
            changes["llm_endpoint"] = {"old": config.llm_endpoint, "new": llm_endpoint}
            config.llm_endpoint = llm_endpoint

        if llm_temperature is not None and llm_temperature != config.llm_temperature:
            changes["llm_temperature"] = {"old": float(config.llm_temperature), "new": llm_temperature}
            config.llm_temperature = llm_temperature

        if llm_max_tokens is not None and llm_max_tokens != config.llm_max_tokens:
            changes["llm_max_tokens"] = {"old": config.llm_max_tokens, "new": llm_max_tokens}
            config.llm_max_tokens = llm_max_tokens

        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="ai_infra",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)

        self.db.commit()
        self.db.refresh(config)

        return config

    def get_available_endpoints(self) -> List[str]:
        """
        Get list of available Databricks serving endpoints.
        Returns endpoints sorted with databricks- prefixed first.
        """
        try:
            client = get_databricks_client()
            endpoints = client.serving_endpoints.list()
            names = [endpoint.name for endpoint in endpoints]

            # Sort: databricks- prefixed first, then others
            databricks_endpoints = sorted([n for n in names if n.startswith("databricks-")])
            other_endpoints = sorted([n for n in names if not n.startswith("databricks-")])

            return databricks_endpoints + other_endpoints
        except Exception as e:
            # Log error but don't fail
            print(f"Warning: Could not list endpoints: {e}")
            return []

    # MLflow

    def get_mlflow_config(self, profile_id: int) -> ConfigMLflow:
        """Get MLflow settings for specific profile."""
        config = self.db.query(ConfigMLflow).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"MLflow settings not found for profile {profile_id}")
        return config

    def update_mlflow_config(
        self,
        profile_id: int,
        experiment_name: str,
        user: str,
    ) -> ConfigMLflow:
        """Update MLflow configuration (experiment name only)."""
        config = self.get_mlflow_config(profile_id)

        changes = {}

        if experiment_name != config.experiment_name:
            changes["experiment_name"] = {"old": config.experiment_name, "new": experiment_name}
            config.experiment_name = experiment_name

        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="mlflow",
                action="update",
                changed_by=user,
                changes=changes,
            )
            self.db.add(history)

        self.db.commit()
        self.db.refresh(config)

        return config

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
        system_prompt: str = None,
        slide_editing_instructions: str = None,
        user_prompt_template: str = None,
        user: str = None,
    ) -> ConfigPrompts:
        """Update prompts configuration."""
        config = self.get_prompts_config(profile_id)

        changes = {}

        if system_prompt is not None and system_prompt != config.system_prompt:
            changes["system_prompt"] = {"old": "...", "new": "..."}  # Don't log full prompts
            config.system_prompt = system_prompt

        if slide_editing_instructions is not None and slide_editing_instructions != config.slide_editing_instructions:
            changes["slide_editing_instructions"] = {"old": "...", "new": "..."}
            config.slide_editing_instructions = slide_editing_instructions

        if user_prompt_template is not None and user_prompt_template != config.user_prompt_template:
            changes["user_prompt_template"] = {"old": config.user_prompt_template, "new": user_prompt_template}
            config.user_prompt_template = user_prompt_template

        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="prompts",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)

        self.db.commit()
        self.db.refresh(config)

        return config

    # History

    def get_config_history(
        self,
        profile_id: int = None,
        domain: str = None,
        limit: int = 100,
    ) -> List[ConfigHistory]:
        """Get configuration change history."""
        query = self.db.query(ConfigHistory)

        if profile_id:
            query = query.filter(ConfigHistory.profile_id == profile_id)

        if domain:
            query = query.filter(ConfigHistory.domain == domain)

        return query.order_by(ConfigHistory.timestamp.desc()).limit(limit).all()

