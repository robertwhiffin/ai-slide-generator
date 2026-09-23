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
import inspect
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionNotFoundError
from src.domain.slide_deck import SlideDeck
from src.services.shared_deck_attribution import (
    _OPERATION_OBJECT_TYPES,
    DeckMutationContext,
    MutationActor,
)

from tests.fixtures.html import load_6_slide_deck

SESSION_ID = "multiworker-session"

# The pin the simulated conversation carries.  A DeckMutationContext exists to
# transport exactly this value from the session row to the evidence row, so a
# non-null pin is what makes a dropped or rebuilt context observable here.
GRAPH_RELEASE_ID = 77


class FakeDeckStore:
    """Stand-in for the shared database (session_manager persistence).

    Mirrors the behaviour of SessionManager.save_slide_deck/get_slide_deck
    that matters for coherence: version increments on every save, and reads
    return fresh copies (like real DB rows), never shared object references.

    It also carries the real attribution seam.  Every ChatService mutation path
    now builds a ``DeckMutationContext`` from the session row and threads it into
    the write, so a double without that behaviour does not merely lack an
    attribute — it stops this suite exercising the production path at all, which
    is exactly what happened (correction C-11 R3).  ``deck_mutation_context``
    below therefore reproduces SessionManager's contract, and
    ``save_slide_deck`` applies the same operation/object and actor checks the
    real recorder applies before it will write evidence.
    """

    def __init__(self):
        self.decks: Dict[str, Dict[str, Any]] = {}
        # session_id -> persisted graph_release_id. This is the only UserSession
        # state deck_mutation_context reads, so it is the only state the double
        # needs in order to produce a faithful context.
        self.session_pins: Dict[str, Optional[int]] = {SESSION_ID: GRAPH_RELEASE_ID}
        # Every context that reached a write, in order.
        self.mutations: List[DeckMutationContext] = []

    # -- attribution seam ----------------------------------------------------

    def deck_mutation_context(
        self,
        session_id: str,
        *,
        operation: str,
        object_type: str,
        object_id: Optional[str] = None,
    ) -> DeckMutationContext:
        """Snapshot an immutable session pin for a forthcoming deck write.

        Same contract as ``SessionManager.deck_mutation_context``: load the
        session, refuse an unknown one, and freeze its persisted pin into the
        context.  Returning a real ``DeckMutationContext`` (not a stub) is what
        lets the writer-side checks below be the production checks.
        """
        if session_id not in self.session_pins:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return DeckMutationContext(
            actor=MutationActor(session_id, self.session_pins[session_id]),
            operation=operation,
            object_type=object_type,
            object_id=object_id,
            suppress_nested_events=True,
        )

    def _accept_mutation(
        self, session_id: str, mutation: DeckMutationContext
    ) -> None:
        """Apply the checks record_shared_deck_mutation applies before writing.

        A context that would be rejected by the real recorder must be rejected
        here too, otherwise the double would happily accept a malformed one and
        this suite would pass on evidence production could not persist.
        """
        assert isinstance(mutation, DeckMutationContext), (
            f"save_slide_deck got {type(mutation).__name__}, not a "
            "DeckMutationContext — the production writers pass the real object"
        )
        allowed = _OPERATION_OBJECT_TYPES.get(mutation.operation)
        assert allowed is not None and mutation.object_type in allowed, (
            "illegal shared-deck mutation operation/object pair: "
            f"{mutation.operation}/{mutation.object_type}"
        )
        assert mutation.actor.actor_session_id == session_id, (
            "mutation actor must equal the session being written: "
            f"{mutation.actor.actor_session_id} != {session_id}"
        )
        assert mutation.actor.graph_release_id == self.session_pins[session_id], (
            "mutation actor must carry the session's persisted pin: "
            f"{mutation.actor.graph_release_id} != {self.session_pins[session_id]}"
        )
        self.mutations.append(mutation)

    def mutation_trace(self) -> List[tuple]:
        """(operation, object_type, actor pin) for every recorded write."""
        return [
            (m.operation, m.object_type, m.actor.graph_release_id)
            for m in self.mutations
        ]

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
        mutation: Optional[DeckMutationContext] = None,
    ) -> Dict[str, Any]:
        if mutation is not None:
            self._accept_mutation(session_id, mutation)
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

    def acquire_session_lock(self, session_id: str, timeout_seconds: int = 300) -> bool:
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

        # The mutation that produced that DB state carried its attribution with
        # it: one context, naming the operation and the session's persisted pin.
        assert shared_db.mutation_trace() == [
            ("delete_slide", "deck", GRAPH_RELEASE_ID)
        ]

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

        # Both workers attributed their own write. The stale worker is the point:
        # reloading the deck to recover from staleness must not lose or rebuild
        # the context, and its actor pin is still the session's persisted one.
        assert shared_db.mutation_trace() == [
            ("delete_slide", "deck", GRAPH_RELEASE_ID),
            ("reorder_slides", "deck", GRAPH_RELEASE_ID),
        ]

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

        # The edit that landed on the stale worker is attributed to the slide it
        # actually wrote — the one surviving in the DB, not the resurrected one.
        assert shared_db.mutation_trace() == [
            ("delete_slide", "deck", GRAPH_RELEASE_ID),
            ("update_slide", "deck", GRAPH_RELEASE_ID),
        ]
        edit = shared_db.mutations[-1]
        assert edit.object_id is not None
        assert edit.object_id == saved["slides"][0]["slide_id"]
        assert edit.suppress_nested_events is True


# ---------------------------------------------------------------------------
# The double must not drift from the real store again.
# ---------------------------------------------------------------------------

#: Every SessionManager method ChatService calls through the mutation paths this
#: suite drives.  If ChatService starts calling another one, the double needs it
#: too, and an AttributeError here is the loud failure that says so.
_STORE_COLLABORATORS = (
    "save_slide_deck",
    "get_slide_deck",
    "get_slide_deck_version",
    "deck_mutation_context",
    "get_session",
    "acquire_session_lock",
    "release_session_lock",
    "get_verification_map",
    "create_version",
    "update_last_activity",
)


def test_fake_deck_store_accepts_every_call_the_real_store_accepts():
    """Break caught: the double silently drifts from SessionManager and this suite
    stops exercising a threaded production argument.

    Measured cause (correction C-11 R3): Task 3 added ``mutation`` to
    save_slide_deck and ``deck_mutation_context`` to SessionManager; the double
    gained neither, so all three coherence tests raised AttributeError instead of
    covering the new path.  A signature check is what catches that class at the
    boundary rather than one test at a time.
    """
    from src.api.services.session_manager import SessionManager

    for name in _STORE_COLLABORATORS:
        real = getattr(SessionManager, name, None)
        assert real is not None, (
            f"SessionManager.{name} no longer exists — this list is stale"
        )
        double = getattr(FakeDeckStore, name, None)
        assert double is not None, (
            f"FakeDeckStore has no {name}: the double has drifted from "
            "SessionManager and this suite would stop covering that call"
        )
        real_params = [
            parameter
            for parameter in inspect.signature(real).parameters.values()
            if parameter.name != "self"
        ]
        call_kwargs = {
            parameter.name: (
                None
                if parameter.default is inspect.Parameter.empty
                else parameter.default
            )
            for parameter in real_params
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        try:
            inspect.signature(double).bind(None, **call_kwargs)
        except TypeError as exc:
            raise AssertionError(
                f"FakeDeckStore.{name} cannot accept a call that "
                f"SessionManager.{name} accepts: {exc}"
            ) from exc


def test_fake_deck_store_context_matches_the_real_managers_contract():
    """Break caught: the double returns a stub instead of the real immutable
    context, so a writer that mangled the object would still pass here."""
    store = FakeDeckStore()

    context = store.deck_mutation_context(
        SESSION_ID, operation="update_slide", object_type="deck", object_id="s-1"
    )
    assert isinstance(context, DeckMutationContext)
    assert context.actor == MutationActor(SESSION_ID, GRAPH_RELEASE_ID)
    assert context.operation == "update_slide"
    assert context.object_type == "deck"
    assert context.object_id == "s-1"
    assert context.suppress_nested_events is True

    # Frozen, exactly like the production dataclass a writer must forward
    # unchanged rather than rebuild.
    with pytest.raises(Exception):
        context.operation = "delete_slide"

    # An unknown session cannot be attributed — the real manager raises, so does
    # the double.
    with pytest.raises(SessionNotFoundError):
        store.deck_mutation_context(
            "no-such-session", operation="update_slide", object_type="deck"
        )

    # An illegal operation/object pair is refused at the write boundary, as the
    # real recorder refuses it.
    with pytest.raises(AssertionError, match="operation/object pair"):
        store.save_slide_deck(
            session_id=SESSION_ID,
            title="t",
            html_content="<div></div>",
            mutation=DeckMutationContext(
                actor=MutationActor(SESSION_ID, GRAPH_RELEASE_ID),
                operation="write_slide",
                object_type="deck",
            ),
        )
