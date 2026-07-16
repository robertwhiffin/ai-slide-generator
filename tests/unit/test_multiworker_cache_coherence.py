"""Multi-worker deck-cache coherence tests.

Production runs uvicorn with multiple worker processes (see
databricks_tellr_app/run.py: UVICORN_WORKERS, default 4). Each process has its
own ChatService singleton and therefore its own in-memory ``_deck_cache``.
The database is the only state shared between workers.

The invariant these tests enforce:

    A worker's view of the deck must never be staler than the database.

Topology simulation: each "worker" is a separate ChatService instance; the
shared database is a single FakeDeckStore. This is faithful to production
(the per-process singleton is instance state; Lakebase is shared) while
letting the test deterministically route each request to a chosen worker —
something a real multi-process test cannot do.

Regression context: in prod, worker B's stale cache caused
- PUT /api/slides/reorder → 400 "Invalid reorder: wrong number of indices"
- deleted slides resurrecting after a later mutation landed on a stale worker
"""

import copy
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.api.services.chat_service import ChatService
from src.domain.slide_deck import SlideDeck

from tests.fixtures.html import load_6_slide_deck

SESSION_ID = "multiworker-session"


class FakeDeckStore:
    """Stand-in for the shared database (session_manager persistence).

    Mirrors the behaviour of SessionManager.save_slide_deck/get_slide_deck
    that matters for coherence: version increments on every save, and reads
    return fresh copies (like real DB rows), never shared object references.
    """

    def __init__(self):
        self.decks: Dict[str, Dict[str, Any]] = {}

    def save_slide_deck(
        self,
        session_id: str,
        title: Optional[str],
        html_content: str,
        scripts_content: Optional[str] = None,
        slide_count: int = 0,
        deck_dict: Optional[Dict[str, Any]] = None,
        modified_by: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        existing = self.decks.get(session_id)
        version = existing["version"] + 1 if existing else 1
        self.decks[session_id] = {
            "session_id": session_id,
            "title": title,
            "html_content": html_content,
            "scripts_content": scripts_content,
            "slide_count": slide_count,
            "slides": copy.deepcopy(deck_dict.get("slides", [])) if deck_dict else [],
            "css": deck_dict.get("css", "") if deck_dict else "",
            "version": version,
        }
        return {"session_id": session_id, "slide_count": slide_count, "version": version}

    def get_slide_deck(self, session_id: str) -> Optional[Dict[str, Any]]:
        record = self.decks.get(session_id)
        return copy.deepcopy(record) if record else None

    def get_slide_deck_version(self, session_id: str) -> Optional[int]:
        record = self.decks.get(session_id)
        return record["version"] if record else None

    # -- collaborators ChatService touches during mutations ------------------

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return {"id": session_id}

    def acquire_session_lock(self, session_id: str) -> bool:
        return True

    def release_session_lock(self, session_id: str) -> None:
        pass

    def get_verification_map(self, session_id: str) -> Dict[str, Any]:
        return {}

    def create_version(self, session_id: str, description: str, deck_dict, **kwargs):
        return {"version_number": 1, "description": description}

    def update_last_activity(self, session_id: str) -> None:
        pass


def make_worker() -> ChatService:
    """One simulated uvicorn worker: a ChatService with its own deck cache."""
    worker = ChatService.__new__(ChatService)
    worker.agent = MagicMock()
    worker._deck_cache = {}
    worker._cache_lock = threading.Lock()
    return worker


def seed_db(store: FakeDeckStore, html: str) -> SlideDeck:
    deck = SlideDeck.from_html_string(html)
    store.save_slide_deck(
        session_id=SESSION_ID,
        title=deck.title,
        html_content=deck.knit(),
        slide_count=len(deck.slides),
        deck_dict=deck.to_dict(),
    )
    return deck


@pytest.fixture
def shared_db():
    """The shared 'database' both workers read and write."""
    store = FakeDeckStore()
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=store
    ):
        yield store


class TestVersionProbeCost:
    """The cache-validation probe must be a lightweight version lookup."""

    def test_cache_hit_probe_does_not_fetch_full_deck(self):
        """A warm cache hit pays one version read, never a full deck fetch
        (get_slide_deck parses the whole deck JSON and hashes every slide —
        running it per mutation made deletes visibly slow)."""
        worker = make_worker()
        deck = SlideDeck.from_html_string(load_6_slide_deck())
        worker._deck_cache[SESSION_ID] = deck
        worker._deck_cache_versions = {SESSION_ID: 7}

        sm = MagicMock()
        sm.get_slide_deck_version.return_value = 7

        with patch(
            "src.api.services.chat_service.get_session_manager", return_value=sm
        ):
            result = worker._get_or_load_deck(SESSION_ID)

        assert result is deck
        sm.get_slide_deck.assert_not_called()


class TestMultiWorkerCacheCoherence:
    """Worker-local cache must never serve state older than the database."""

    def test_worker_deck_read_is_not_staler_than_db(self, shared_db):
        """Generic invariant: after another worker mutates, a cached read
        must reflect the database, not the process-local snapshot."""
        seed_db(shared_db, load_6_slide_deck())
        worker_a, worker_b = make_worker(), make_worker()

        # Worker B serves a read and caches the 6-slide deck
        assert len(worker_b._get_or_load_deck(SESSION_ID).slides) == 6

        # A mutation lands on worker A: deck is now 5 slides in the DB
        worker_a.delete_slide(SESSION_ID, 0)
        assert len(shared_db.get_slide_deck(SESSION_ID)["slides"]) == 5

        # Worker B's next read must match the database
        deck_b = worker_b._get_or_load_deck(SESSION_ID)
        assert len(deck_b.slides) == len(shared_db.get_slide_deck(SESSION_ID)["slides"])

    def test_reorder_on_stale_worker_accepts_current_db_order(self, shared_db):
        """Prod regression: reorder validated against a stale worker cache
        returned 400 'wrong number of indices (got 5, expected 6)'."""
        seed_db(shared_db, load_6_slide_deck())
        worker_a, worker_b = make_worker(), make_worker()

        worker_b._get_or_load_deck(SESSION_ID)  # warm B's cache (6 slides)
        worker_a.delete_slide(SESSION_ID, 0)  # DB now has 5 slides

        # The frontend refetched from the DB and sends a 5-index permutation
        worker_b.reorder_slides(SESSION_ID, [4, 3, 2, 1, 0])

        saved = shared_db.get_slide_deck(SESSION_ID)
        assert len(saved["slides"]) == 5

    def test_stale_worker_mutation_does_not_resurrect_deleted_slide(self, shared_db):
        """Prod regression: a mutation landing on a stale worker wrote the
        stale 6-slide deck back to the DB, resurrecting the deleted slide."""
        seed_db(shared_db, load_6_slide_deck())
        worker_a, worker_b = make_worker(), make_worker()

        worker_b._get_or_load_deck(SESSION_ID)  # warm B's cache (6 slides)

        deleted_html = shared_db.get_slide_deck(SESSION_ID)["slides"][0]["html"]
        worker_a.delete_slide(SESSION_ID, 0)  # DB now has 5 slides

        # An unrelated edit lands on stale worker B; index 0 is valid in both
        # the stale and fresh deck, so no validation error fires
        worker_b.update_slide(
            SESSION_ID, 0, '<div class="slide"><h1>Edited on worker B</h1></div>'
        )

        saved = shared_db.get_slide_deck(SESSION_ID)
        saved_htmls: List[str] = [s["html"] for s in saved["slides"]]
        assert len(saved["slides"]) == 5
        assert deleted_html not in saved_htmls
