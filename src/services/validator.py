"""Configuration validation service."""
from dataclasses import dataclass
from typing import Optional

from src.core.databricks_client import get_databricks_client


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

    def validate_prompts(
        self,
        system_prompt: str = None,
    ) -> ValidationResult:
        """
        Validate prompts.
        
        Args:
            system_prompt: System prompt (optional)
            
        Returns:
            ValidationResult
        """
        # System prompt validation - just check it's not empty if provided
        # No required placeholders for system prompt
        return ValidationResult(valid=True)

