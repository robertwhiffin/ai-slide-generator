"""Fire-and-forget usage-event recording with in-process dedup.

Mirrors the request_logs middleware pattern: writes happen on an executor
thread (or inline when already off the event loop) and never raise.

Dedup semantics (per spec):
- ``login``: one event per username per 30-minute window ("visit").
- ``deck_retrieved``: one event per (username, session_id) per 30-minute window.
- ``deck_created``: never deduped.

Caches are per-process; a restart may produce occasional extra login
events, which is acceptable.
"""

import asyncio
import logging
import time

from src.database.models.usage_event import (
    EVENT_DECK_CREATED,
    EVENT_DECK_RETRIEVED,
    EVENT_LOGIN,
)

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_SECONDS = 30 * 60

_login_cache: dict[str, float] = {}
_retrieval_cache: dict[tuple[str, str], float] = {}


def reset_dedup_caches() -> None:
    """Clear dedup caches (test helper)."""
    _login_cache.clear()
    _retrieval_cache.clear()


def _write_event(username: str, event_type: str, session_id) -> None:
    """Synchronously insert one usage event. Never raises."""
    try:
        from src.core.database import get_session_local
        from src.database.models.usage_event import UsageEvent

        session_factory = get_session_local()
        db = session_factory()
        try:
            db.add(
                UsageEvent(
                    username=username,
                    event_type=event_type,
                    session_id=session_id,
                )
            )
            db.commit()
        except Exception:
            logger.debug("Failed to write usage event", exc_info=True)
            db.rollback()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to write usage event", exc_info=True)


def _submit(username: str, event_type: str, session_id) -> None:
    """Dispatch a write without blocking the caller.

    On the event loop -> run_in_executor; in a worker thread (no running
    loop) -> write inline, which is already off the loop.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _write_event, username, event_type, session_id)
    except RuntimeError:
        _write_event(username, event_type, session_id)
    except Exception:
        logger.debug("Failed to submit usage event", exc_info=True)


def record_login(username) -> None:
    """Record a login "visit": first request after >=30 min of inactivity."""
    if not username:
        return
    now = time.monotonic()
    last = _login_cache.get(username)
    if last is not None and (now - last) < _DEDUP_WINDOW_SECONDS:
        return
    _login_cache[username] = now
    _submit(username, EVENT_LOGIN, None)


def record_deck_created(username, session_id) -> None:
    """Record a deck creation. Never deduped."""
    if not username:
        return
    _submit(username, EVENT_DECK_CREATED, session_id)


def record_deck_retrieved(username, session_id) -> None:
    """Record a deck open, deduped per (user, deck) per 30-minute window."""
    if not username:
        return
    key = (username, str(session_id))
    now = time.monotonic()
    last = _retrieval_cache.get(key)
    if last is not None and (now - last) < _DEDUP_WINDOW_SECONDS:
        return
    _retrieval_cache[key] = now
    _submit(username, EVENT_DECK_RETRIEVED, session_id)
