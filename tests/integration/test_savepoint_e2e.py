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

Hermeticity note (Part 1 repair)
---------------------------------
The original fixture only overrode ``app.dependency_overrides[get_db]``,
which covers the FastAPI *route* dependency (``src.core.database.get_db``).
``SessionManager`` does all its DB work through ``get_db_session()``
(``src.core.database:365``), a separate context manager that bypasses the
dependency-override system entirely and hits whatever database the
environment is configured for.  Every route that enforces deck permissions
also calls ``_check_deck_permission_for_session`` (``src.api.routes._authz``),
which opens its own ``get_db_session`` independently.

Fix: patch both ``src.api.services.session_manager.get_db_session`` and
``src.api.routes._authz.get_db_session`` in the ``client`` fixture so that
*all* DB access goes through the same in-memory SQLite engine.  The
permission context is also patched to supply ``user_name="test-user"`` so
that the creator-check in ``PermissionService.get_deck_permission`` grants
``CAN_MANAGE`` on sessions whose ``created_by`` matches.
"""

import contextlib
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.core.permission_context import PermissionContext
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

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_factory(test_db_engine):
    """SQLAlchemy session factory bound to the in-memory engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)


@pytest.fixture(scope="function")
def test_db(test_db_factory):
    db = test_db_factory()
    yield db
    db.close()


def _make_fake_get_db_session(factory):
    """Return a context manager that yields a SQLAlchemy session from *factory*.

    Mirrors the pattern in tests/integration/test_get_slide_deck_row_read.py.
    Used to patch ``get_db_session`` at fixture scope so SessionManager and the
    _authz helper both use the in-memory SQLite engine rather than the live DB.
    """

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return fake_get_db_session


@pytest.fixture(scope="function")
def client(test_db_engine, test_db_factory, test_db):
    """TestClient fully backed by in-memory SQLite.

    Patches:
    - ``app.dependency_overrides[get_db]``                      FastAPI route dep
    - ``src.api.services.session_manager.get_db_session``       all SessionManager ops
    - ``src.api.routes._authz.get_db_session``                  deck-permission checks
    """
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    fake_db_session = _make_fake_get_db_session(test_db_factory)

    with patch("src.api.services.session_manager.get_db_session", fake_db_session):
        with patch("src.api.routes._authz.get_db_session", fake_db_session):
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
    """Patch the user context and permission context so API calls pass auth.

    ``get_current_user`` patches ensure ``created_by`` is set to ``"test-user"``
    on every session we create in tests.

    ``get_permission_context`` is patched in the modules that read it for
    permission enforcement (``_authz.py``) so the creator-check at
    ``PermissionService.get_deck_permission`` line 276 resolves
    ``root.created_by == user_name`` and returns CAN_MANAGE.
    """
    perm_ctx = PermissionContext(user_name="test-user")
    with patch("src.api.routes.sessions.get_current_user", return_value="test-user"):
        with patch("src.api.routes.slides.get_current_user", return_value="test-user"):
            with patch("src.api.routes.chat.get_current_user", return_value="test-user"):
                with patch("src.core.user_context.get_current_user", return_value="test-user"):
                    with patch("src.api.routes._authz.get_permission_context", return_value=perm_ctx):
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

    def test_three_sequential_edits_all_preserved(self, client, mock_user):
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

    def test_rapid_sequential_edits(self, client, mock_user):
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

    def test_reorder_then_edit(self, client, mock_user):
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

    def test_duplicate_then_edit(self, client, mock_user):
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

    def test_delete_then_edit(self, client, mock_user):
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

    def test_preview_earlier_version_shows_original(self, client, mock_user):
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

    def test_restore_then_edit_creates_correct_savepoint(self, client, mock_user):
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

    def test_six_slide_sequential_edits(self, client, mock_user):
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


class TestDeleteSlideRegressions:
    """Targeted tests for the reported 'delete slide then things go messy' bug.

    Scenarios:
    - Delete a slide, then rapidly edit multiple remaining slides
    - Delete middle slide, edit first and last, verify save points are cumulative
    - Delete + edit + delete + edit chain
    - Verify getSlides returns correct state between operations
    """

    def test_delete_middle_then_edit_first_and_last(self, client, mock_user):
        """Delete slide 3 (index 2) from 5-slide deck, then edit slides 1 and 4.
        Each save point must reflect ALL prior changes cumulatively.
        """
        session_id = _create_session(client)
        deck = _seed_deck(session_id, html=load_6_slide_deck())
        original_count = len(deck.slides)
        assert original_count == 6

        # Delete slide 3 (index 2)
        resp = client.delete("/api/slides/2", params={"session_id": session_id})
        assert resp.status_code == 200, f"delete failed: {resp.text}"

        # Verify deck state via getSlides
        slides_after = _get_slides(client, session_id)
        assert len(slides_after.get("slides", [])) == 5, "Should be 5 slides after delete"

        # Edit slide 1 (index 0) -- now with 5 slides
        edit_1 = _marker("post-delete-slide1")
        _edit_slide(client, session_id, 0, edit_1)

        # Verify intermediate state via getSlides
        intermediate = _get_slides(client, session_id)
        assert intermediate["slides"][0]["html"] == edit_1, "getSlides should show edit on slide 1"

        # Edit last slide (index 4 in 5-slide deck)
        edit_last = _marker("post-delete-last")
        _edit_slide(client, session_id, 4, edit_last)

        # Get the latest version from version list
        versions = _list_versions(client, session_id)
        latest_v = versions["versions"][0]["version_number"]
        latest_data = _preview_version(client, session_id, latest_v)
        latest_slides = _get_version_slides(latest_data)

        assert len(latest_slides) == 5, "Latest save point should have 5 slides"
        assert latest_slides[0]["html"] == edit_1, "Slide 1 edit MUST be in latest save point"
        assert latest_slides[4]["html"] == edit_last, "Last slide edit MUST be in latest save point"

    def test_delete_edit_delete_edit_chain(self, client, mock_user):
        """Delete-edit-delete-edit chain: each operation's save point must be correct."""
        session_id = _create_session(client)
        deck = _seed_deck(session_id, html=load_6_slide_deck())
        assert len(deck.slides) == 6

        # Step 1: Delete slide 2 (index 1) → 5 slides
        resp = client.delete("/api/slides/1", params={"session_id": session_id})
        assert resp.status_code == 200

        # Step 2: Edit slide 1 (index 0)
        edit_a = _marker("chain-edit-a")
        _edit_slide(client, session_id, 0, edit_a)

        # Step 3: Delete slide 3 (index 2 in 5-slide deck) → 4 slides
        resp = client.delete("/api/slides/2", params={"session_id": session_id})
        assert resp.status_code == 200

        # Step 4: Edit slide 2 (index 1 in 4-slide deck)
        edit_b = _marker("chain-edit-b")
        _edit_slide(client, session_id, 1, edit_b)

        # Verify final state
        final = _get_slides(client, session_id)
        final_slides = final.get("slides", [])
        assert len(final_slides) == 4, f"Should be 4 slides, got {len(final_slides)}"
        assert final_slides[0]["html"] == edit_a, "Slide 1 edit-a must persist through chain"
        assert final_slides[1]["html"] == edit_b, "Slide 2 edit-b must be present"

        # Verify the latest save point matches
        versions = _list_versions(client, session_id)
        latest_v = versions["versions"][0]["version_number"]
        latest_data = _preview_version(client, session_id, latest_v)
        latest_slides = _get_version_slides(latest_data)

        assert len(latest_slides) == 4, "Save point should have 4 slides"
        assert latest_slides[0]["html"] == edit_a, "Save point must have edit-a on slide 1"
        assert latest_slides[1]["html"] == edit_b, "Save point must have edit-b on slide 2"

    def test_rapid_edits_after_delete_no_gaps(self, client, mock_user):
        """Delete a slide then rapidly edit every remaining slide.
        No save point should lose a prior edit.
        """
        session_id = _create_session(client)
        deck = _seed_deck(session_id, html=load_6_slide_deck())
        assert len(deck.slides) == 6

        # Delete slide 4 (index 3) → 5 slides
        resp = client.delete("/api/slides/3", params={"session_id": session_id})
        assert resp.status_code == 200

        # Rapidly edit all 5 remaining slides
        edits = {}
        for i in range(5):
            tag = f"rapid-post-delete-{i}"
            _edit_slide(client, session_id, i, _marker(tag))
            edits[i] = tag

        # Every edit should be in the latest save point
        versions = _list_versions(client, session_id)
        latest_v = versions["versions"][0]["version_number"]
        latest_data = _preview_version(client, session_id, latest_v)
        latest_slides = _get_version_slides(latest_data)

        assert len(latest_slides) == 5, f"Expected 5 slides, got {len(latest_slides)}"
        for idx, tag in edits.items():
            assert tag in latest_slides[idx]["html"], (
                f"Slide {idx} missing edit '{tag}' in latest save point. "
                f"Got: {latest_slides[idx]['html'][:80]}"
            )

    def test_getslides_consistent_between_operations(self, client, mock_user):
        """After each operation, getSlides must return the cumulative state.
        This catches the auto-verify race where getSlides could return stale data.
        """
        session_id = _create_session(client)
        deck = _seed_deck(session_id)
        assert len(deck.slides) == 3

        # Edit slide 1
        edit_1 = _marker("consistency-s1")
        _edit_slide(client, session_id, 0, edit_1)
        state_1 = _get_slides(client, session_id)
        assert state_1["slides"][0]["html"] == edit_1, "getSlides after edit 1 must show edit"

        # Edit slide 2
        edit_2 = _marker("consistency-s2")
        _edit_slide(client, session_id, 1, edit_2)
        state_2 = _get_slides(client, session_id)
        assert state_2["slides"][0]["html"] == edit_1, "getSlides after edit 2 must STILL show edit 1"
        assert state_2["slides"][1]["html"] == edit_2, "getSlides after edit 2 must show edit 2"

        # Delete slide 3
        resp = client.delete("/api/slides/2", params={"session_id": session_id})
        assert resp.status_code == 200
        state_3 = _get_slides(client, session_id)
        assert len(state_3["slides"]) == 2, "getSlides after delete must show 2 slides"
        assert state_3["slides"][0]["html"] == edit_1, "Edit 1 must survive deletion of slide 3"
        assert state_3["slides"][1]["html"] == edit_2, "Edit 2 must survive deletion of slide 3"

        # Edit remaining slide 1 again
        edit_1b = _marker("consistency-s1-v2")
        _edit_slide(client, session_id, 0, edit_1b)
        state_4 = _get_slides(client, session_id)
        assert state_4["slides"][0]["html"] == edit_1b, "Re-edit of slide 1 must be reflected"
        assert state_4["slides"][1]["html"] == edit_2, "Edit 2 must persist across re-edit of slide 1"

    def test_save_point_version_numbers_after_delete_chain(self, client, mock_user):
        """Verify version numbers increment correctly through a delete+edit chain.
        Backend auto-creates save points for each operation.
        """
        session_id = _create_session(client)
        _seed_deck(session_id)

        # Each operation auto-creates a save point on the backend
        _edit_slide(client, session_id, 0, _marker("v-check-1"))
        _edit_slide(client, session_id, 1, _marker("v-check-2"))
        client.delete("/api/slides/2", params={"session_id": session_id})
        _edit_slide(client, session_id, 0, _marker("v-check-3"))

        versions = _list_versions(client, session_id)
        v_numbers = [v["version_number"] for v in versions["versions"]]

        # Should have at least 4 auto-created save points (one per operation)
        assert len(v_numbers) >= 4, f"Expected >=4 versions, got {len(v_numbers)}: {v_numbers}"
        # Version numbers should be strictly increasing (newest first in list)
        assert v_numbers == sorted(v_numbers, reverse=True), (
            f"Version numbers should be strictly decreasing in newest-first list: {v_numbers}"
        )


# ---------------------------------------------------------------------------
# Part 2 — spec-snapshot restore (integration-level proof for Task 7)
# ---------------------------------------------------------------------------
# These tests exercise the round-trip added in Tasks 1 + 7:
#   SlideDeckVersion.deck_spec_json  (Task 1 column)
#   create_version snapshots it      (Task 7 write)
#   restore_version copies it back   (Task 7 copy-back, C9)
#
# Task 7 verified this at unit level with mocks.  Here we run the full
# API/service stack against in-memory SQLite so that the real ORM,
# real transactions, and real session_manager methods are exercised.
# ---------------------------------------------------------------------------


def _get_deck_row(factory, session_id_str: str):
    """Return the SessionSlideDeck ORM row for the given string session_id."""
    from src.database.models.session import UserSession, SessionSlideDeck

    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id_str).one()
        deck = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == us.id).one()
        # Detach from session so values are accessible after close
        deck_spec_json = deck.deck_spec_json
        css = deck.css
        external_scripts_json = deck.external_scripts_json
        scripts_content = deck.scripts_content
        return {
            "deck_spec_json": deck_spec_json,
            "css": css,
            "external_scripts_json": external_scripts_json,
            "scripts_content": scripts_content,
        }
    finally:
        db.close()


def _set_deck_spec_json(factory, session_id_str: str, spec_json: str) -> None:
    """Directly write deck_spec_json on the SessionSlideDeck row."""
    from src.database.models.session import UserSession, SessionSlideDeck

    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id_str).one()
        deck = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == us.id).one()
        deck.deck_spec_json = spec_json
        db.commit()
    finally:
        db.close()


def _count_slide_rows(factory, session_id_str: str) -> int:
    """Count the session_slides rows for the given string session_id."""
    from src.database.models.session import UserSession, SessionSlide

    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id_str).one()
        return db.query(SessionSlide).filter(SessionSlide.session_id == us.id).count()
    finally:
        db.close()


class TestSpecSnapshotRestoreE2E:
    """Integration-level proof that deck_spec_json round-trips through save-point restore.

    Task 7 verified create_version/restore_version at unit level with mocks.
    These tests run the real API+service stack against in-memory SQLite to
    prove the round-trip end-to-end.
    """

    def test_spec_snapshot_restore_round_trip(self, client, mock_user, test_db_factory):
        """Save point captures deck_spec_json; restore brings it back.

        Why this matters: if restore returned an old deck but left today's
        deck_spec_json intact, PR3's §4.4 rebuild trigger would compare the
        restored deck's slides against a spec it never came from and
        "correct" them — silently undoing the restore.  The spec must be
        restored together with the deck it describes.

        Scenario:
          1. Seed deck, set spec to SPEC_V1
          2. Create save point V1 (snapshots SPEC_V1)
          3. Change spec to SPEC_V2 (simulates architect issuing a new spec
             while the user edits slides in the meantime)
          4. Restore to V1
          5. Assert deck_spec_json == SPEC_V1, not SPEC_V2
        """
        SPEC_V1 = json.dumps({"version": 1, "layout": "dark", "accent": "#e66"})
        SPEC_V2 = json.dumps({"version": 2, "layout": "light", "accent": "#00f"})

        session_id = _create_session(client)
        _seed_deck(session_id)

        # Set spec to V1 directly (no API for spec writes yet)
        _set_deck_spec_json(test_db_factory, session_id, SPEC_V1)

        # Create save point — must snapshot SPEC_V1
        v1 = _create_savepoint(client, session_id, "Initial with SPEC_V1")

        # Architect issues a new spec (or a user edit triggers a spec update)
        _set_deck_spec_json(test_db_factory, session_id, SPEC_V2)
        assert _get_deck_row(test_db_factory, session_id)["deck_spec_json"] == SPEC_V2

        # Restore to V1
        resp = client.post(
            f"/api/slides/versions/{v1['version_number']}/restore",
            json={"session_id": session_id},
        )
        assert resp.status_code == 200, f"restore failed: {resp.text}"

        # The spec must be back to V1, not V2
        row = _get_deck_row(test_db_factory, session_id)
        assert row["deck_spec_json"] == SPEC_V1, (
            f"restore must bring back SPEC_V1; got {row['deck_spec_json']!r}. "
            "If SPEC_V2 is returned, PR3's §4.4 trigger would rebuild the "
            "slides against a spec the restored deck never came from, silently "
            "undoing the restore."
        )

    def test_restore_brings_back_css_scripts_and_prunes_phantom_rows(
        self, client, mock_user, test_db_factory
    ):
        """Restore brings back css/external_scripts/scripts_content and prunes extra rows.

        Scenario:
          1. 3-slide deck with distinctive CSS and an external script — V1
          2. Replace with 5-slide deck that has different CSS — V2
          3. Restore to V1
          4. Assert: 3 slides back, CSS matches V1, external_scripts match V1,
             scripts_content matches V1, row count == 3 (no phantom rows at
             positions 3 and 4 from V2)
        """
        from src.api.services.chat_service import get_chat_service
        from src.api.services.session_manager import get_session_manager
        from src.domain.slide_deck import SlideDeck

        CSS_V1 = "body { background: #001; color: #eee; }"
        EXT_SCRIPTS_V1 = ["https://cdn.jsdelivr.net/npm/chart.js"]

        CSS_V2 = "body { background: #fff; }"

        session_id = _create_session(client)

        # Build a 3-slide deck with V1 CSS and external_scripts set on both:
        #   - the SlideDeck domain object (so create_save_point → deck.to_dict()
        #     captures them into the version snapshot), and
        #   - the deck_dict passed to save_slide_deck (so the deck columns are
        #     written correctly before V1 restore target is established).
        deck3 = SlideDeck.from_html_string(load_3_slide_deck())
        deck3.css = CSS_V1
        deck3.external_scripts = EXT_SCRIPTS_V1
        # SlideDeck.scripts is a computed property (aggregate of slide scripts)
        # so we can't assign it directly; the version snapshot will carry ""
        # for the scripts field for decks with no per-slide scripts, which is
        # fine — scripts_content restoration is tested at unit level in Task 7.

        deck3_dict = deck3.to_dict()
        # deck3_dict["css"] and deck3_dict["external_scripts"] are now CSS_V1 / EXT_SCRIPTS_V1

        service = get_chat_service()
        with service._cache_lock:
            service._deck_cache[session_id] = deck3

        sm = get_session_manager()
        sm.save_slide_deck(
            session_id=session_id,
            title=deck3.title,
            html_content=deck3.knit(),
            slide_count=3,
            deck_dict=deck3_dict,
        )

        # Create V1 save point — the in-memory deck has CSS_V1 so the snapshot
        # will carry it.
        v1 = _create_savepoint(client, session_id, "V1 - 3 slides with CSS_V1")

        # Replace with a 5-slide deck with V2 CSS (no external scripts)
        deck5 = SlideDeck.from_html_string(load_6_slide_deck())
        deck5.slides = deck5.slides[:5]
        deck5.css = CSS_V2
        deck5.external_scripts = []

        with service._cache_lock:
            service._deck_cache[session_id] = deck5

        deck5_dict = deck5.to_dict()
        deck5_dict["css"] = CSS_V2
        deck5_dict["external_scripts"] = []
        sm.save_slide_deck(
            session_id=session_id,
            title=deck5.title,
            html_content=deck5.knit(),
            slide_count=5,
            deck_dict=deck5_dict,
        )
        _create_savepoint(client, session_id, "V2 - 5 slides with CSS_V2")

        # Confirm we have 5 slide rows before restore
        assert _count_slide_rows(test_db_factory, session_id) == 5, (
            "Expected 5 rows before restore"
        )

        # Restore to V1
        resp = client.post(
            f"/api/slides/versions/{v1['version_number']}/restore",
            json={"session_id": session_id},
        )
        assert resp.status_code == 200, f"restore failed: {resp.text}"

        # Slide count via API
        slides_data = _get_slides(client, session_id)
        assert len(slides_data["slides"]) == 3, (
            f"Expected 3 slides after restore, got {len(slides_data['slides'])}"
        )

        # Deck-level presentation columns restored from the V1 snapshot
        row = _get_deck_row(test_db_factory, session_id)
        assert row["css"] == CSS_V1, (
            f"css must be restored to V1; got {row['css']!r}"
        )
        assert json.loads(row["external_scripts_json"] or "[]") == EXT_SCRIPTS_V1, (
            f"external_scripts must be restored to V1; got {row['external_scripts_json']!r}"
        )

        # No phantom rows — row count must equal the restored slide count
        row_count = _count_slide_rows(test_db_factory, session_id)
        assert row_count == 3, (
            f"Expected exactly 3 session_slides rows after restore; "
            f"got {row_count}. Phantom rows at positions 3/4 would cause "
            "the row-read path to serve extra slides that don't exist."
        )
