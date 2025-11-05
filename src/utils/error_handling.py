"""
Custom exceptions and error handling utilities.

This module defines application-specific exceptions and error handling patterns.
"""

from typing import Any, Optional


class AppException(Exception):
    """Base exception for application-specific errors."""

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ):
        """
        Initialize application exception.

        Args:
            message: Human-readable error message
            details: Additional context about the error
            error_code: Machine-readable error code for API responses
        """
        self.message = message
        self.details = details or {}
        self.error_code = error_code or "INTERNAL_ERROR"
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(AppException):
    """Raised when configuration is invalid or cannot be loaded."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="CONFIGURATION_ERROR")


class ValidationError(AppException):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="VALIDATION_ERROR")


class LLMError(AppException):
    """Raised when LLM service operations fail."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="LLM_ERROR")


class GenieError(AppException):
    """Raised when Genie service operations fail."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="GENIE_ERROR")


class DataRetrievalError(AppException):
    """Raised when data retrieval from Genie fails."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="DATA_RETRIEVAL_ERROR")


class SlideGenerationError(AppException):
    """Raised when slide generation fails."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="SLIDE_GENERATION_ERROR")


class TimeoutError(AppException):
    """Raised when operations timeout."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="TIMEOUT_ERROR")


class AuthenticationError(AppException):
    """Raised when authentication fails."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="AUTHENTICATION_ERROR")


class ResourceNotFoundError(AppException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details, error_code="RESOURCE_NOT_FOUND")


def format_exception_for_logging(exc: Exception) -> dict[str, Any]:
    """
    Format an exception for structured logging.

    Args:
        exc: Exception to format

    Returns:
        Dictionary with exception information
    """
    result = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
    }

    # Add additional context for AppExceptions
    if isinstance(exc, AppException):
        result["error_code"] = exc.error_code
        result["details"] = exc.details

    return result

