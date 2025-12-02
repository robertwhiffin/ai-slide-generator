"""Utility modules."""

from src.utils.error_handling import (
    AppException,
    AuthenticationError,
    ConfigurationError,
    DataRetrievalError,
    GenieError,
    LLMError,
    ResourceNotFoundError,
    SlideGenerationError,
    TimeoutError,
    ValidationError,
    format_exception_for_logging,
)
from src.utils.html_utils import extract_canvas_ids_from_html, extract_canvas_ids_from_script
from src.utils.logging_config import get_logger, setup_logging

__all__ = [
    # Error handling
    "AppException",
    "AuthenticationError",
    "ConfigurationError",
    "DataRetrievalError",
    "GenieError",
    "LLMError",
    "ResourceNotFoundError",
    "SlideGenerationError",
    "TimeoutError",
    "ValidationError",
    "format_exception_for_logging",
    # HTML utilities
    "extract_canvas_ids_from_html",
    "extract_canvas_ids_from_script",
    # Logging
    "get_logger",
    "setup_logging",
]

