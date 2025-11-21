"""Configuration validation service."""
from dataclasses import dataclass
from typing import Optional

from src.config.client import get_databricks_client


@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    error: Optional[str] = None


class ConfigValidator:
    """Validate configuration values."""

    def validate_ai_infra(
        self,
        llm_endpoint: str,
        llm_temperature: float,
        llm_max_tokens: int,
    ) -> ValidationResult:
        """
        Validate AI infrastructure configuration.
        
        Args:
            llm_endpoint: LLM endpoint name
            llm_temperature: Temperature value
            llm_max_tokens: Max tokens value
            
        Returns:
            ValidationResult
        """
        # Validate temperature range
        if not (0.0 <= llm_temperature <= 1.0):
            return ValidationResult(
                valid=False,
                error=f"Temperature must be between 0 and 1, got {llm_temperature}",
            )

        # Validate max tokens
        if llm_max_tokens <= 0:
            return ValidationResult(
                valid=False,
                error=f"Max tokens must be positive, got {llm_max_tokens}",
            )

        # Check if endpoint exists
        try:
            client = get_databricks_client()
            endpoints = [e.name for e in client.serving_endpoints.list()]

            if llm_endpoint not in endpoints:
                return ValidationResult(
                    valid=False,
                    error=f"Endpoint '{llm_endpoint}' not found. Available: {', '.join(endpoints[:5])}...",
                )
        except Exception as e:
            # Don't fail validation if we can't check endpoints
            print(f"Warning: Could not validate endpoint: {e}")

        return ValidationResult(valid=True)

    def validate_genie_space(self, space_id: str) -> ValidationResult:
        """
        Validate Genie space.
        
        Args:
            space_id: Genie space ID
            
        Returns:
            ValidationResult
        """
        if not space_id or not space_id.strip():
            return ValidationResult(
                valid=False,
                error="Genie space ID cannot be empty",
            )

        # Could add more validation here (check if space exists)
        # For now, just basic validation

        return ValidationResult(valid=True)

    def validate_mlflow(self, experiment_name: str) -> ValidationResult:
        """
        Validate MLflow configuration.
        
        Args:
            experiment_name: Experiment name
            
        Returns:
            ValidationResult
        """
        if not experiment_name or not experiment_name.strip():
            return ValidationResult(
                valid=False,
                error="Experiment name cannot be empty",
            )

        # Validate format (should be a valid path)
        if not experiment_name.startswith("/"):
            return ValidationResult(
                valid=False,
                error="Experiment name must start with /",
            )

        return ValidationResult(valid=True)

    def validate_prompts(
        self,
        system_prompt: str = None,
        user_prompt_template: str = None,
    ) -> ValidationResult:
        """
        Validate prompts.
        
        Args:
            system_prompt: System prompt
            user_prompt_template: User prompt template
            
        Returns:
            ValidationResult
        """
        # Check required placeholders in user template
        if user_prompt_template is not None:
            if "{question}" not in user_prompt_template:
                return ValidationResult(
                    valid=False,
                    error="User prompt template must contain {question} placeholder",
                )

        # Check system prompt mentions max_slides
        if system_prompt is not None:
            if "{max_slides}" not in system_prompt:
                return ValidationResult(
                    valid=False,
                    error="System prompt should reference {max_slides} placeholder",
                )

        return ValidationResult(valid=True)

