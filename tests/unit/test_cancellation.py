"""Tests for the cancellation registry and CancellableAgentExecutor."""

import threading

from src.services.cancellation import CancellationRegistry


class TestCancellationRegistry:
    """Tests for CancellationRegistry thread-safe operations."""

    def setup_method(self):
        """Reset registry state before each test."""
        CancellationRegistry._cancelled.clear()

    def test_cancel_sets_flag(self):
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True

    def test_is_cancelled_default_false(self):
        assert CancellationRegistry.is_cancelled("nonexistent") is False

    def test_reset_clears_flag(self):
        CancellationRegistry.cancel("session-1")
        CancellationRegistry.reset("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is False

    def test_reset_nonexistent_is_noop(self):
        CancellationRegistry.reset("nonexistent")  # should not raise

    def test_cancel_is_idempotent(self):
        CancellationRegistry.cancel("session-1")
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True

    def test_independent_sessions(self):
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True
        assert CancellationRegistry.is_cancelled("session-2") is False

    def test_thread_safety(self):
        """Concurrent cancel/check/reset should not raise."""
        errors = []

        def worker(session_id):
            try:
                for _ in range(100):
                    CancellationRegistry.cancel(session_id)
                    CancellationRegistry.is_cancelled(session_id)
                    CancellationRegistry.reset(session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"s-{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
