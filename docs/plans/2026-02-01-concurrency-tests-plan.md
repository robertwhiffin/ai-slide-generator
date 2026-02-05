# Concurrency Test Suite Plan

**Date:** 2026-02-01
**Status:** Ready for Implementation
**Estimated Tests:** ~20 tests
**Priority:** Low

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** Project root

```bash
pytest tests/unit/test_concurrency.py -v
```

**Python environment:**
```bash
source .venv/bin/activate
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **Session manager:** `src/api/services/session_manager.py` (locking logic)
2. **Chat routes:** `src/api/routes/chat.py` (async handling)
3. **Slide routes:** `src/api/routes/slides.py` (session locking)
4. **Database models:** `src/database/models.py`
5. **Existing tests:** `tests/unit/test_context_propagation.py`
6. **Test fixtures:** `tests/conftest.py`

---

## Context: What Concurrency Tests Cover

The app handles multiple simultaneous requests:
- Multiple users accessing different sessions
- Same user with multiple tabs/requests
- Background verification while user edits
- Auto-save during manual operations

These tests verify:
- Session locking prevents race conditions
- Concurrent reads don't block each other
- Writes are properly serialized
- No data corruption under load
- Deadlocks are prevented

---

## Concurrency Scenarios

| Scenario | Expected Behavior |
|----------|-------------------|
| Two edits to same session | Second request gets 409 (busy) |
| Two reads from same session | Both succeed |
| Edit while verification runs | Verification completes or is cancelled |
| Two users, different sessions | Both succeed independently |
| Rapid-fire requests | Proper queueing/rejection |

---

## Test Categories

### 1. Session Locking Tests

```python
import pytest
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor


class TestSessionLocking:
    """Tests for session lock behavior."""

    def test_acquire_lock_success(self):
        """Can acquire lock on unlocked session."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager()
        result = manager.acquire_session_lock("session-123")

        assert result is True

    def test_acquire_lock_fails_when_locked(self):
        """Cannot acquire lock on already locked session."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager()
        manager.acquire_session_lock("session-123")

        # Second attempt should fail
        result = manager.acquire_session_lock("session-123")
        assert result is False

    def test_release_lock_allows_reacquire(self):
        """Released lock can be reacquired."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager()
        manager.acquire_session_lock("session-123")
        manager.release_session_lock("session-123")

        # Should succeed now
        result = manager.acquire_session_lock("session-123")
        assert result is True

    def test_different_sessions_lock_independently(self):
        """Different sessions have independent locks."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager()
        result1 = manager.acquire_session_lock("session-1")
        result2 = manager.acquire_session_lock("session-2")

        assert result1 is True
        assert result2 is True

    def test_lock_timeout_releases_stale_lock(self):
        """Stale locks are released after timeout."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager(lock_timeout_seconds=1)
        manager.acquire_session_lock("session-123")

        # Wait for timeout
        import time
        time.sleep(1.5)

        # Should be able to acquire now
        result = manager.acquire_session_lock("session-123")
        assert result is True
```

### 2. Concurrent Request Tests

```python
class TestConcurrentRequests:
    """Tests for concurrent HTTP requests."""

    def test_concurrent_reads_succeed(self, client, mock_chat_service):
        """Multiple concurrent reads to same session succeed."""
        mock_chat_service.get_slides.return_value = {"slides": [], "slide_count": 0}

        results = []

        def make_request():
            response = client.get("/api/slides?session_id=test-123")
            results.append(response.status_code)

        threads = [threading.Thread(target=make_request) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(code == 200 for code in results)

    def test_concurrent_writes_serialized(self, client, mock_chat_service, mock_session_manager):
        """Concurrent writes to same session are serialized."""
        mock_chat_service.send_message.return_value = {"messages": [], "slide_deck": None}

        results = []
        lock_acquired = [0]

        def track_lock(*args):
            if lock_acquired[0] == 0:
                lock_acquired[0] = 1
                return True
            return False

        mock_session_manager.acquire_session_lock.side_effect = track_lock

        def make_request(msg):
            response = client.post("/api/chat", json={
                "session_id": "test-123",
                "message": msg
            })
            results.append(response.status_code)

        threads = [
            threading.Thread(target=make_request, args=(f"Message {i}",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # One should succeed, others should get 409
        assert results.count(200) == 1
        assert results.count(409) == 2

    def test_different_sessions_concurrent_writes(self, client, mock_chat_service, mock_session_manager):
        """Writes to different sessions proceed concurrently."""
        mock_chat_service.send_message.return_value = {"messages": [], "slide_deck": None}
        mock_session_manager.acquire_session_lock.return_value = True

        results = []

        def make_request(session_id):
            response = client.post("/api/chat", json={
                "session_id": session_id,
                "message": "Hello"
            })
            results.append((session_id, response.status_code))

        threads = [
            threading.Thread(target=make_request, args=(f"session-{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed (different sessions)
        assert all(code == 200 for _, code in results)
```

### 3. Race Condition Tests

```python
class TestRaceConditions:
    """Tests for race condition prevention."""

    def test_slide_edit_during_verification(self, mock_session_manager, mock_verification_service):
        """Edit and verification don't corrupt state."""
        from src.api.services.chat_service import ChatService

        chat_service = ChatService(session_manager=mock_session_manager)

        # Set up initial state
        initial_state = {
            "slides": [{"index": 0, "html": "<div>Original</div>", "verification_status": "pending"}]
        }
        mock_session_manager.get_session_state.return_value = initial_state

        # Simulate concurrent edit and verification
        def edit_slide():
            chat_service.update_slide("session-123", 0, "<div>Edited</div>")

        def verify_slide():
            chat_service.verify_slide("session-123", 0)

        threads = [
            threading.Thread(target=edit_slide),
            threading.Thread(target=verify_slide)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Final state should be consistent
        final_state = mock_session_manager.get_session_state("session-123")
        assert final_state["slides"][0]["html"] is not None

    def test_rapid_reorder_operations(self, mock_session_manager):
        """Rapid reorder operations don't corrupt deck."""
        from src.api.services.chat_service import ChatService

        chat_service = ChatService(session_manager=mock_session_manager)

        initial_state = {
            "slides": [{"index": i, "html": f"<div>Slide {i}</div>"} for i in range(5)]
        }
        mock_session_manager.get_session_state.return_value = initial_state.copy()
        mock_session_manager.acquire_session_lock.return_value = True

        # Make 10 rapid reorder requests
        orders = [
            [4, 3, 2, 1, 0],
            [0, 1, 2, 3, 4],
            [2, 0, 4, 1, 3],
            [1, 2, 3, 4, 0],
        ]

        for order in orders:
            chat_service.reorder_slides("session-123", order)

        # Final state should still have 5 slides
        final_state = mock_session_manager.get_session_state("session-123")
        assert len(final_state["slides"]) == 5

    def test_add_delete_race(self, mock_session_manager):
        """Add and delete don't cause index errors."""
        from src.api.services.chat_service import ChatService

        chat_service = ChatService(session_manager=mock_session_manager)

        state = {"slides": [{"index": 0, "html": "<div>Initial</div>"}]}
        mock_session_manager.get_session_state.return_value = state
        mock_session_manager.acquire_session_lock.return_value = True

        errors = []

        def add_slide():
            try:
                chat_service.add_slide("session-123", "<div>New</div>")
            except Exception as e:
                errors.append(e)

        def delete_slide():
            try:
                chat_service.delete_slide("session-123", 0)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_slide),
            threading.Thread(target=delete_slide),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without index errors
        index_errors = [e for e in errors if isinstance(e, IndexError)]
        assert len(index_errors) == 0
```

### 4. Database Concurrency Tests

```python
class TestDatabaseConcurrency:
    """Tests for database-level concurrency."""

    def test_concurrent_session_creates(self, test_db):
        """Can create multiple sessions concurrently."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager(db=test_db)
        results = []

        def create_session(i):
            try:
                session_id = manager.create_session(
                    name=f"Session {i}",
                    profile_id=1
                )
                results.append(("success", session_id))
            except Exception as e:
                results.append(("error", str(e)))

        threads = [
            threading.Thread(target=create_session, args=(i,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed (unique names)
        successes = [r for r in results if r[0] == "success"]
        assert len(successes) == 10

    def test_concurrent_session_updates(self, test_db):
        """Concurrent updates to different sessions succeed."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager(db=test_db)

        # Create sessions first
        session_ids = [
            manager.create_session(name=f"Session {i}", profile_id=1)
            for i in range(5)
        ]

        results = []

        def update_session(session_id, new_name):
            try:
                manager.update_session(session_id, name=new_name)
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        threads = [
            threading.Thread(target=update_session, args=(sid, f"Updated {i}"))
            for i, sid in enumerate(session_ids)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(r == "success" for r in results)

    def test_no_deadlock_on_multi_table_update(self, test_db):
        """Updates spanning multiple tables don't deadlock."""
        from src.api.services.session_manager import SessionManager

        manager = SessionManager(db=test_db)
        session_id = manager.create_session(name="Test", profile_id=1)

        # Simulate complex update that touches multiple tables
        def complex_update():
            manager.save_session(session_id, {
                "slides": [{"index": 0, "html": "<div>Test</div>"}],
                "messages": [{"role": "user", "content": "Test"}]
            })

        # Run multiple complex updates
        threads = [threading.Thread(target=complex_update) for _ in range(5)]
        for t in threads:
            t.start()

        # Should complete without deadlock (with timeout)
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread appears deadlocked"
```

### 5. Async Operation Tests

```python
class TestAsyncOperations:
    """Tests for async operation handling."""

    @pytest.mark.asyncio
    async def test_concurrent_async_requests(self, async_client, mock_chat_service):
        """Async requests are handled correctly."""
        mock_chat_service.send_message.return_value = {"messages": [], "slide_deck": None}

        async def make_request(i):
            response = await async_client.post("/api/chat", json={
                "session_id": f"session-{i}",
                "message": f"Message {i}"
            })
            return response.status_code

        # Make 10 concurrent requests
        tasks = [make_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should succeed (different sessions)
        assert all(code == 200 for code in results)

    @pytest.mark.asyncio
    async def test_async_streaming_concurrent(self, async_client, mock_chat_service):
        """Multiple streaming requests work concurrently."""
        # Setup mock to yield events
        async def mock_stream():
            yield {"type": "start", "message": "Starting"}
            await asyncio.sleep(0.1)
            yield {"type": "complete", "message": "Done"}

        mock_chat_service.stream_message.return_value = mock_stream()

        async def stream_request(session_id):
            async with async_client.stream(
                "POST",
                "/api/chat/stream",
                json={"session_id": session_id, "message": "Test"}
            ) as response:
                events = []
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        events.append(line)
                return len(events)

        # Run 3 concurrent streams
        tasks = [stream_request(f"session-{i}") for i in range(3)]
        results = await asyncio.gather(*tasks)

        # All should receive events
        assert all(count > 0 for count in results)
```

---

## Helper Functions and Fixtures

```python
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_session_manager():
    """Mock session manager with locking."""
    manager = MagicMock()
    manager.locks = {}

    def acquire_lock(session_id):
        if session_id in manager.locks:
            return False
        manager.locks[session_id] = True
        return True

    def release_lock(session_id):
        manager.locks.pop(session_id, None)

    manager.acquire_session_lock.side_effect = acquire_lock
    manager.release_session_lock.side_effect = release_lock
    manager.cache = {}

    return manager


@pytest.fixture
def mock_chat_service():
    """Mock chat service."""
    with patch("src.api.routes.chat.get_chat_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def async_client():
    """Async test client for FastAPI."""
    from httpx import AsyncClient
    from src.api.main import app

    return AsyncClient(app=app, base_url="http://test")
```

---

## File to Create

**`tests/unit/test_concurrency.py`**

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `pytest tests/unit/test_concurrency.py -v`
- [ ] Session locking tested
- [ ] Concurrent reads tested
- [ ] Concurrent writes tested (same session → 409)
- [ ] Race conditions tested
- [ ] Database concurrency tested
- [ ] No deadlocks
- [ ] File committed to git

---

## Important Notes

1. **Threading vs Async:** The app uses FastAPI which is async, but some operations use `asyncio.to_thread`. Tests should cover both patterns.

2. **Flaky tests:** Concurrency tests can be flaky. Use proper synchronization and timeouts. Consider running multiple times to verify stability.

3. **Real vs Mock:** Some tests may need real database/services to properly test concurrency. Mark those as integration tests.

---

## Debug Commands

```bash
# Run concurrency tests
pytest tests/unit/test_concurrency.py -v

# Run with verbose threading output
pytest tests/unit/test_concurrency.py -v -s

# Run specific test class
pytest tests/unit/test_concurrency.py::TestSessionLocking -v

# Run multiple times to check for flakiness
for i in {1..5}; do pytest tests/unit/test_concurrency.py -v; done
```
