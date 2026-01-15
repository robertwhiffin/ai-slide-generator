"""Context propagation utilities for thread pool operations.

Python's ContextVar values don't automatically propagate to new threads.
This module provides wrappers that copy the current context before
running functions in thread pools, ensuring user authentication tokens
and other context variables are available in worker threads.
"""

import asyncio
import contextvars
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_in_thread_with_context(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking function in thread pool while preserving ContextVars.

    This is a drop-in replacement for asyncio.to_thread() that copies
    the current context (including user authentication tokens) to the
    worker thread.

    Args:
        func: The blocking function to run
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        The return value of func

    Example:
        # Instead of:
        result = await asyncio.to_thread(blocking_func, arg1, arg2)

        # Use:
        result = await run_in_thread_with_context(blocking_func, arg1, arg2)
    """
    ctx = contextvars.copy_context()
    return await asyncio.to_thread(ctx.run, func, *args, **kwargs)


def create_context_preserving_target(func: Callable[..., T]) -> Callable[..., T]:
    """Create a thread target that preserves the current context.

    Use this when creating threading.Thread instances to ensure
    ContextVar values are available in the new thread.

    Args:
        func: The function to wrap

    Returns:
        A wrapped function that runs with copied context

    Example:
        def worker():
            client = get_user_client()  # Now works!
            ...

        # Instead of:
        thread = threading.Thread(target=worker)

        # Use:
        thread = threading.Thread(target=create_context_preserving_target(worker))
    """
    ctx = contextvars.copy_context()

    def wrapper(*args: Any, **kwargs: Any) -> T:
        return ctx.run(func, *args, **kwargs)

    return wrapper
