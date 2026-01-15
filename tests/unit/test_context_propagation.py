"""Tests for context propagation to thread pools.

Verifies that user authentication tokens (stored in ContextVars) are
correctly propagated to worker threads when using the context utilities.

Note: Python 3.11+ asyncio.to_thread automatically copies context.
However, threading.Thread does NOT copy context automatically.
Our utilities ensure consistent behavior across both patterns.
"""

import asyncio
import contextvars
import threading
from unittest.mock import MagicMock

import pytest

from src.core.context_utils import (
    create_context_preserving_target,
    run_in_thread_with_context,
)
from src.core.databricks_client import (
    _user_client_var,
    reset_user_client,
    set_user_client,
)


@pytest.fixture(autouse=True)
def cleanup_user_client():
    """Ensure user client is reset after each test."""
    yield
    reset_user_client()


class TestRunInThreadWithContext:
    """Tests for run_in_thread_with_context utility."""

    @pytest.mark.asyncio
    async def test_context_propagates_to_thread(self):
        """Verify user client propagates to thread pool."""
        # Create a mock "user" client
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        def check_client_in_thread():
            return _user_client_var.get()

        result = await run_in_thread_with_context(check_client_in_thread)
        assert result is mock_user_client

    @pytest.mark.asyncio
    async def test_asyncio_to_thread_preserves_context_in_python311(self):
        """Verify asyncio.to_thread preserves context in Python 3.11+.

        Note: Python 3.11+ automatically copies context in asyncio.to_thread.
        Our wrapper is still useful for explicit clarity and compatibility.
        """
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        def check_client_in_thread():
            return _user_client_var.get()

        # In Python 3.11+, asyncio.to_thread preserves context
        result = await asyncio.to_thread(check_client_in_thread)
        assert result is mock_user_client

    @pytest.mark.asyncio
    async def test_wrapper_also_preserves_context(self):
        """Verify our wrapper also preserves context (for explicit clarity)."""
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        def check_get_user_client():
            return _user_client_var.get()

        # Our wrapper explicitly preserves context
        result = await run_in_thread_with_context(check_get_user_client)
        assert result is mock_user_client

    @pytest.mark.asyncio
    async def test_with_wrapper_preserves_user_client(self):
        """Verify get_user_client returns user client when context preserved."""
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        def check_get_user_client():
            return _user_client_var.get()

        # With wrapper - context is preserved
        result = await run_in_thread_with_context(check_get_user_client)
        assert result is mock_user_client

    @pytest.mark.asyncio
    async def test_passes_arguments_correctly(self):
        """Verify arguments are passed through to the function."""

        def add_numbers(a, b, multiplier=1):
            return (a + b) * multiplier

        result = await run_in_thread_with_context(add_numbers, 2, 3, multiplier=2)
        assert result == 10

    @pytest.mark.asyncio
    async def test_propagates_exceptions(self):
        """Verify exceptions are propagated from the thread."""

        def raise_error():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await run_in_thread_with_context(raise_error)


class TestCreateContextPreservingTarget:
    """Tests for create_context_preserving_target utility."""

    def test_context_propagates_to_thread(self):
        """Verify user client propagates to threading.Thread."""
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        result_holder = {}

        def worker():
            result_holder["client"] = _user_client_var.get()

        # Use the context-preserving wrapper
        wrapped = create_context_preserving_target(worker)
        thread = threading.Thread(target=wrapped)
        thread.start()
        thread.join()

        assert result_holder["client"] is mock_user_client

    def test_without_wrapper_loses_context(self):
        """Verify threading.Thread loses context without wrapper."""
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        result_holder = {}

        def worker():
            result_holder["client"] = _user_client_var.get()

        # Without wrapper - context is lost
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert result_holder["client"] is None

    def test_lambda_wrapper_preserves_context(self):
        """Verify the lambda ctx.run pattern works for threading.Thread."""
        mock_user_client = MagicMock(name="mock_user_client")
        set_user_client(mock_user_client)

        result_holder = {}
        ctx = contextvars.copy_context()

        def worker():
            result_holder["client"] = _user_client_var.get()

        # Using lambda with ctx.run (the pattern used in chat routes)
        thread = threading.Thread(target=lambda: ctx.run(worker))
        thread.start()
        thread.join()

        assert result_holder["client"] is mock_user_client
