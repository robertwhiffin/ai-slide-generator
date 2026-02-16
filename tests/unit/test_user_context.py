"""Tests for the request-scoped user context module."""

import asyncio
import threading

import pytest

from src.core.user_context import get_current_user, require_current_user, set_current_user


class TestSetAndGetCurrentUser:
    """Basic lifecycle: set, read, clear."""

    def test_default_is_none(self):
        """Without an explicit set, the context returns None."""
        set_current_user(None)
        assert get_current_user() is None

    def test_set_and_get(self):
        """set_current_user stores the value for get_current_user."""
        set_current_user("alice@example.com")
        assert get_current_user() == "alice@example.com"
        # cleanup
        set_current_user(None)

    def test_overwrite(self):
        """A second set_current_user replaces the previous value."""
        set_current_user("alice@example.com")
        set_current_user("bob@example.com")
        assert get_current_user() == "bob@example.com"
        set_current_user(None)

    def test_clear(self):
        """Setting None clears the identity."""
        set_current_user("alice@example.com")
        set_current_user(None)
        assert get_current_user() is None


class TestRequireCurrentUser:
    """require_current_user raises when identity is missing."""

    def test_raises_when_unset(self):
        set_current_user(None)
        with pytest.raises(RuntimeError, match="No authenticated user"):
            require_current_user()

    def test_returns_user_when_set(self):
        set_current_user("alice@example.com")
        assert require_current_user() == "alice@example.com"
        set_current_user(None)


class TestContextIsolation:
    """ContextVars are isolated per-thread and per-asyncio-task."""

    def test_thread_isolation(self):
        """Threads do NOT inherit ContextVar state; child starts with default."""
        set_current_user("main-thread-user")
        child_values = []

        def target():
            # New threads get the default value (None), not the parent's.
            child_values.append(get_current_user())
            set_current_user("child-thread-user")
            child_values.append(get_current_user())

        t = threading.Thread(target=target)
        t.start()
        t.join()

        # Main thread is unaffected by the child's mutation.
        assert get_current_user() == "main-thread-user"
        # Child thread started with None (default), then set its own value.
        assert child_values[0] is None
        assert child_values[1] == "child-thread-user"

        set_current_user(None)

    def test_asyncio_task_isolation(self):
        """Each asyncio task gets its own context copy."""

        async def run():
            set_current_user("parent-task")

            async def child():
                # asyncio.create_task copies the current context
                assert get_current_user() == "parent-task"
                set_current_user("child-task")
                assert get_current_user() == "child-task"

            await asyncio.create_task(child())

            # Parent task is unaffected
            assert get_current_user() == "parent-task"
            set_current_user(None)

        asyncio.run(run())
