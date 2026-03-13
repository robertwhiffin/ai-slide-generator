"""Thread-safe cancellation registry for agent generation interruption."""

import logging
import threading

logger = logging.getLogger(__name__)


class CancellationRegistry:
    """Thread-safe registry for tracking cancelled generations.

    Maps session_id → cancelled boolean. Used by CancellableAgentExecutor
    to check between agent iterations whether the user has requested cancellation.
    """

    _cancelled: dict[str, bool] = {}
    _lock = threading.Lock()

    @classmethod
    def cancel(cls, session_id: str) -> None:
        """Mark a session's generation as cancelled."""
        with cls._lock:
            cls._cancelled[session_id] = True
        logger.info("Generation cancelled", extra={"session_id": session_id})

    @classmethod
    def is_cancelled(cls, session_id: str) -> bool:
        """Check if a session's generation has been cancelled."""
        with cls._lock:
            return cls._cancelled.get(session_id, False)

    @classmethod
    def reset(cls, session_id: str) -> None:
        """Clear cancellation state for a session (call at start of each generation)."""
        with cls._lock:
            cls._cancelled.pop(session_id, None)
