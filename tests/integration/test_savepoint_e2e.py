"""End-to-end save point tests for no-Genie (prompt-only) mode.

These tests exercise the full API stack (routes -> services -> database)
to verify that sequential edits produce save points containing ALL prior
changes cumulatively.

Key scenario:
    1. Generate slides (3-slide deck)
    2. Panel-edit slide 2 (color change)     -> save point V1
    3. Panel-edit slide 1 (title change)     -> save point V2
    4. Panel-edit slide 3 (content change)   -> save point V3
    5. Assert V3 contains ALL three edits, V2 contains edits 1+2, etc.

The LLM agent is mocked (we don't need real generation), but everything
else runs through real services and a real (in-memory) database.

Run with: pytest tests/integration/test_savepoint_e2e.py -v
"""

import json
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck

from tests.fixtures.html import load_3_slide_deck, load_6_slide_deck


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_db_engine():
    """In-memory SQLite for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    tables_to_create = [
        table for table in Base.metadata.sorted_tables
        if table.name != "config_history"
    ]
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES config_profiles (id) ON DELETE CASCADE
            )
        """))
        conn.commit()

    yield engine

    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_db):
    """TestClient backed by in-memory DB, real SessionManager, mocked agent."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset service singletons between tests to avoid cross-test pollution."""
    import src.api.services.chat_service as cs_mod
    import src.api.services.session_manager as sm_mod
    old_cs = cs_mod._chat_service_instance
    old_sm = sm_mod._session_manager
    cs_mod._chat_service_instance = None
    sm_mod._session_manager = None
    yield
    cs_mod._chat_service_instance = old_cs
    sm_mod._session_manager = old_sm


@pytest.fixture
def mock_user():
    """Patch the user context so API calls don't fail on auth."""
    with patch("src.api.routes.sessions.get_current_user", return_value="test-user"):
        with patch("src.api.routes.slides.get_current_user", return_value="test-user"):
            with patch("src.api.routes.chat.get_current_user", return_value="test-user"):
                with patch("src.core.user_context.get_current_user", return_value="test-user"):
                    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session(client) -> str:
    """Create a session via the API and return the session_id."""
    resp = client.post("/api/sessions", json={"title": "E2E savepoint test"})
    assert resp.status_code == 200, f"create session failed: {resp.text}"
    return resp.json()["session_id"]


def _seed_deck(session_id: str, html: str = None):
    """Seed the ChatService cache and DB with a known slide deck.

    This bypasses the LLM agent entirely (no generation needed).
    """
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager

    if html is None:
        html = load_3_slide_deck()

    deck = SlideDeck.from_html_string(html)
    service = get_chat_service()

    with service._cache_lock:
        service._deck_cache[session_id] = deck

    sm = get_session_manager()
    sm.save_slide_deck(
        session_id=session_id,
        title=deck.title,
        html_content=deck.knit(),
        slide_count=len(deck.slides),
        deck_dict=deck.to_dict(),
    )

    return deck


def _edit_slide(client, session_id: str, index: int, new_html: str):
    """Edit a slide's HTML via the PATCH API endpoint."""
    resp = client.patch(
        f"/api/slides/{index}",
        json={"session_id": session_id, "html": new_html},
    )
    assert resp.status_code == 200, f"edit slide {index} failed: {resp.text}"
    return resp.json()


def _create_savepoint(client, session_id: str, description: str):
    """Create a save point via the API endpoint."""
    resp = client.post(
        "/api/slides/versions/create",
        json={"session_id": session_id, "description": description},
    )
    assert resp.status_code == 200, f"create savepoint failed: {resp.text}"
    return resp.json()


def _list_versions(client, session_id: str):
    """List all versions for a session."""
    resp = client.get("/api/slides/versions", params={"session_id": session_id})
    assert resp.status_code == 200, f"list versions failed: {resp.text}"
    return resp.json()


def _preview_version(client, session_id: str, version_number: int):
    """Preview a specific save point's deck snapshot."""
    resp = client.get(
        f"/api/slides/versions/{version_number}",
        params={"session_id": session_id},
    )
    assert resp.status_code == 200, f"preview version {version_number} failed: {resp.text}"
    return resp.json()


def _get_slides(client, session_id: str):
    """Get the current slide deck from the API."""
    resp = client.get("/api/slides", params={"session_id": session_id})
    assert resp.status_code == 200, f"get slides failed: {resp.text}"
    return resp.json()


MARKER_HTML = '<div class="slide" data-marker="{marker}"><h2>Edited - {marker}</h2><p>Marker content for {marker}</p></div>'


def _marker(tag: str) -> str:
    """Create distinctive HTML that we can search for in save points."""
    return MARKER_HTML.format(marker=tag)


def _get_version_slides(version_data: dict) -> list:
    """Extract slides list from version preview response.

    The preview endpoint returns {"deck": {..., "slides": [...]}, ...}.
    """
    deck = version_data.get("deck", version_data.get("deck_dict", version_data))
    return deck.get("slides", [])


def _version_has_marker(version_data: dict, marker_tag: str) -> bool:
    """Check if a version's deck contains a specific marker string."""
    for slide in _get_version_slides(version_data):
        if marker_tag in slide.get("html", ""):
            return True
    return False


def _version_slide_html(version_data: dict, index: int) -> str:
    """Get a specific slide's HTML from version data."""
    slides = _get_version_slides(version_data)
    if index < len(slides):
        return slides[index].get("html", "")
    return ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSequentialEditsE2E:
    """The core bug reproduction: sequential panel edits losing earlier changes."""

    @patch("src.api.services.chat_service.create_agent")
    def test_three_sequential_edits_all_preserved(self, mock_agent, client, mock_user):
        """Edit slide 2, then slide 1, then slide 3. Each save point must
        contain ALL prior edits cumulatively.

        This is the exact bug scenario: in no-Genie mode, V3 would lose
        the edit from V1 (slide 2 color change).
        """
        session_id = _create_session(client)
        deck = _seed_deck(session_id)
        originals = [s.html for s in deck.slides]

        # V1: Edit slide 2 (index 1) -- e.g. color change
        html_edit_1 = _marker("red-background")
        _edit_slide(client, session_id, 1, html_edit_1)
        time.sleep(0.1)
        v1 = _create_savepoint(client, session_id, "Changed slide 2 color")

        # V2: Edit slide 1 (index 0) -- e.g. title change
        html_edit_2 = _marker("bold-title")
        _edit_slide(client, session_id, 0, html_edit_2)
        time.sleep(0.1)
        v2 = _create_savepoint(client, session_id, "Changed slide 1 title")

        # V3: Edit slide 3 (index 2) -- e.g. content change
        html_edit_3 = _marker("bullet-points")
        _edit_slide(client, session_id, 2, html_edit_3)
        time.sleep(0.1)
        v3 = _create_savepoint(client, session_id, "Changed slide 3 content")

        # Verify version list
        versions = _list_versions(client, session_id)
        assert len(versions["versions"]) >= 3, f"Expected >=3 versions, got {len(versions['versions'])}"

        # Preview each version and check cumulative state
        v1_data = _preview_version(client, session_id, v1["version_number"])
        v1_slides = _get_version_slides(v1_data)
        assert len(v1_slides) == 3
        assert v1_slides[0]["html"] == originals[0], "V1: slide 1 should be original"
        assert v1_slides[1]["html"] == html_edit_1, "V1: slide 2 should have red-background"
        assert v1_slides[2]["html"] == originals[2], "V1: slide 3 should be original"

        v2_data = _preview_version(client, session_id, v2["version_number"])
        v2_slides = _get_version_slides(v2_data)
        assert len(v2_slides) == 3
        assert v2_slides[0]["html"] == html_edit_2, "V2: slide 1 should have bold-title"
        assert v2_slides[1]["html"] == html_edit_1, "V2: slide 2 MUST still have red-background (BUG if lost)"
        assert v2_slides[2]["html"] == originals[2], "V2: slide 3 should be original"

        v3_data = _preview_version(client, session_id, v3["version_number"])
        v3_slides = _get_version_slides(v3_data)
        assert len(v3_slides) == 3
        assert v3_slides[0]["html"] == html_edit_2, "V3: slide 1 MUST still have bold-title"
        assert v3_slides[1]["html"] == html_edit_1, "V3: slide 2 MUST still have red-background"
        assert v3_slides[2]["html"] == html_edit_3, "V3: slide 3 should have bullet-points"

    @patch("src.api.services.chat_service.create_agent")
    def test_rapid_sequential_edits(self, mock_agent, client, mock_user):
        """Rapid edits with minimal delay -- simulates fast user typing in no-Genie mode."""
        session_id = _create_session(client)
        _seed_deck(session_id)

        markers = []
        for i in range(5):
            idx = i % 3
            tag = f"rapid-edit-{i}"
            markers.append((idx, tag))
            _edit_slide(client, session_id, idx, _marker(tag))
            _create_savepoint(client, session_id, f"Rapid edit {i}")

        # The final save point should contain the LAST edit on each slide
        versions = _list_versions(client, session_id)
        assert len(versions["versions"]) >= 5

        last_v = _preview_version(
            client, session_id, versions["versions"][0]["version_number"]
        )

        last_edits = {}
        for idx, tag in markers:
            last_edits[idx] = tag

        for idx, expected_tag in last_edits.items():
            html = _version_slide_html(last_v, idx)
            assert expected_tag in html, (
                f"Final version missing edit '{expected_tag}' on slide {idx}. "
                f"Got: {html[:100]}"
            )


class TestMixedOperationsE2E:
    """Verify save point integrity across different operation types."""

    @patch("src.api.services.chat_service.create_agent")
    def test_reorder_then_edit(self, mock_agent, client, mock_user):
        """Reorder slides then edit one. Save point after edit must keep the reorder."""
        session_id = _create_session(client)
        deck = _seed_deck(session_id)
        original_count = len(deck.slides)

        # Reorder: reverse slide order [0, 1, 2] -> [2, 1, 0]
        resp = client.put(
            "/api/slides/reorder",
            json={"session_id": session_id, "new_order": [2, 1, 0]},
        )
        assert resp.status_code == 200, f"reorder failed: {resp.text}"
        _create_savepoint(client, session_id, "Reversed slide order")

        # Edit slide at position 0 (which is now original slide 3)
        html_edit = _marker("post-reorder")
        _edit_slide(client, session_id, 0, html_edit)
        v2 = _create_savepoint(client, session_id, "Edited first slide after reorder")

        v2_data = _preview_version(client, session_id, v2["version_number"])
        v2_slides = _get_version_slides(v2_data)
        assert len(v2_slides) == original_count
        assert v2_slides[0]["html"] == html_edit, "Position 0 should have the edit"

    @patch("src.api.services.chat_service.create_agent")
    def test_duplicate_then_edit(self, mock_agent, client, mock_user):
        """Duplicate a slide, edit the duplicate, verify save point has both."""
        session_id = _create_session(client)
        _seed_deck(session_id)

        resp = client.post(
            "/api/slides/1/duplicate",
            json={"session_id": session_id},
        )
        assert resp.status_code == 200, f"duplicate failed: {resp.text}"

        slides_after_dup = _get_slides(client, session_id)
        dup_count = slides_after_dup.get("slide_count", len(slides_after_dup.get("slides", [])))
        assert dup_count == 4, f"Expected 4 slides after duplication, got {dup_count}"

        _create_savepoint(client, session_id, "Duplicated slide 2")

        html_edit = _marker("dup-edited")
        _edit_slide(client, session_id, 2, html_edit)
        v2 = _create_savepoint(client, session_id, "Edited duplicated slide")

        v2_data = _preview_version(client, session_id, v2["version_number"])
        v2_slides = _get_version_slides(v2_data)
        assert len(v2_slides) == 4, "Still 4 slides"
        assert v2_slides[2]["html"] == html_edit, "Duplicate at index 2 should have edit"
        assert v2_slides[1]["html"] != html_edit, "Original at index 1 should NOT have edit"

    @patch("src.api.services.chat_service.create_agent")
    def test_delete_then_edit(self, mock_agent, client, mock_user):
        """Delete a slide, edit another, verify save point reflects both."""
        session_id = _create_session(client)
        _seed_deck(session_id)

        resp = client.delete("/api/slides/1", params={"session_id": session_id})
        assert resp.status_code == 200, f"delete failed: {resp.text}"

        _create_savepoint(client, session_id, "Deleted slide 2")

        html_edit = _marker("after-delete")
        _edit_slide(client, session_id, 0, html_edit)
        v2 = _create_savepoint(client, session_id, "Edited slide 1")

        v2_data = _preview_version(client, session_id, v2["version_number"])
        v2_slides = _get_version_slides(v2_data)
        assert len(v2_slides) == 2, "Should be 2 slides after delete"
        assert v2_slides[0]["html"] == html_edit, "Slide 1 should have edit"


class TestVersionPreviewAndRestore:
    """Verify that previewing and restoring versions returns correct state."""

    @patch("src.api.services.chat_service.create_agent")
    def test_preview_earlier_version_shows_original(self, mock_agent, client, mock_user):
        """Previewing V1 after additional edits should show V1's state."""
        session_id = _create_session(client)
        deck = _seed_deck(session_id)
        originals = [s.html for s in deck.slides]

        v1 = _create_savepoint(client, session_id, "Initial generation")

        _edit_slide(client, session_id, 0, _marker("edit-1"))
        _edit_slide(client, session_id, 1, _marker("edit-2"))
        v2 = _create_savepoint(client, session_id, "Edited slides 1 and 2")

        # Preview V1 -- should show original state
        v1_data = _preview_version(client, session_id, v1["version_number"])
        v1_slides = _get_version_slides(v1_data)
        assert v1_slides[0]["html"] == originals[0], "V1 preview should show original slide 1"
        assert v1_slides[1]["html"] == originals[1], "V1 preview should show original slide 2"

        # Preview V2 -- should show both edits
        v2_data = _preview_version(client, session_id, v2["version_number"])
        v2_slides = _get_version_slides(v2_data)
        assert "edit-1" in v2_slides[0]["html"], "V2 should have edit-1"
        assert "edit-2" in v2_slides[1]["html"], "V2 should have edit-2"

    @patch("src.api.services.chat_service.create_agent")
    def test_restore_then_edit_creates_correct_savepoint(self, mock_agent, client, mock_user):
        """Restore to V1, then edit -> new V2 should have V1 state + edit."""
        session_id = _create_session(client)
        deck = _seed_deck(session_id)
        originals = [s.html for s in deck.slides]

        _create_savepoint(client, session_id, "Initial V1")

        _edit_slide(client, session_id, 0, _marker("v2-edit"))
        _create_savepoint(client, session_id, "V2 with edit")

        # Restore to V1
        resp = client.post(
            "/api/slides/versions/1/restore",
            json={"session_id": session_id},
        )
        assert resp.status_code == 200, f"restore failed: {resp.text}"

        # Now edit slide 2 and save
        post_restore_html = _marker("post-restore")
        _edit_slide(client, session_id, 1, post_restore_html)
        v_new = _create_savepoint(client, session_id, "Post-restore edit")

        v_data = _preview_version(client, session_id, v_new["version_number"])
        v_slides = _get_version_slides(v_data)
        assert v_slides[0]["html"] == originals[0], "Slide 1 should be V1 original (not V2 edit)"
        assert v_slides[1]["html"] == post_restore_html, "Slide 2 should have post-restore edit"


class TestLargerDeck:
    """Verify save point correctness with a 6-slide deck."""

    @patch("src.api.services.chat_service.create_agent")
    def test_six_slide_sequential_edits(self, mock_agent, client, mock_user):
        """Edit every other slide in a 6-slide deck. Final save point must have all."""
        session_id = _create_session(client)
        deck = _seed_deck(session_id, html=load_6_slide_deck())
        assert len(deck.slides) == 6

        _create_savepoint(client, session_id, "Initial 6 slides")

        edits = {}
        for idx in [1, 3, 5]:
            tag = f"six-edit-{idx}"
            _edit_slide(client, session_id, idx, _marker(tag))
            edits[idx] = tag
            time.sleep(0.05)

        final_v = _create_savepoint(client, session_id, "Edited odd slides")

        v_data = _preview_version(client, session_id, final_v["version_number"])
        v_slides = _get_version_slides(v_data)
        assert len(v_slides) == 6

        for idx, tag in edits.items():
            assert tag in v_slides[idx]["html"], (
                f"Slide {idx} should have marker '{tag}', got: {v_slides[idx]['html'][:80]}"
            )

        for idx in [0, 2, 4]:
            assert "data-marker" not in v_slides[idx]["html"], (
                f"Slide {idx} should NOT have been edited"
            )
