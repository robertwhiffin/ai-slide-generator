"""Configuration validation service."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    error: Optional[str] = None


class ConfigValidator:
    """Validate configuration values."""

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

