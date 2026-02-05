"""Validation result data structures."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ValidationResult:
    """Result of a validation check.

    Attributes:
        valid: Whether the validation passed
        errors: List of error messages if validation failed
        warnings: List of warning messages (non-fatal issues)
        details: Optional dict with additional context
    """
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Optional[dict] = None

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.valid

    @classmethod
    def success(cls, details: Optional[dict] = None) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(valid=True, details=details)

    @classmethod
    def failure(cls, errors: List[str], details: Optional[dict] = None) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(valid=False, errors=errors, details=details)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another validation result into this one.

        The result is valid only if both are valid.
        Errors and warnings are combined.
        """
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            details={**(self.details or {}), **(other.details or {})}
        )
