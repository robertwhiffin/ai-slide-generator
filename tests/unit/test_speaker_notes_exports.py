"""Speaker notes in the server-built exports (speaker-notes plan, Task 6 / D7).

Covers the shared ``slide_notes_text`` helper, the screenshot PPTX route
(``/pptx/editable/from-images``), the Google Slides huashu route, and a
regression lock on the huashu PPTX route.
"""

import base64
import contextlib
import io
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation

FROM_IMAGES = "/api/export/pptx/editable/from-images"
HUASHU_FROM_HTML = "/api/export/pptx/editable/huashu/from-html"
GOOGLE_FROM_HUASHU = "/api/export/google-slides/from-huashu"


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _png_data_url() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_pptx(content: bytes):
    return Presentation(io.BytesIO(content))


def _notes_of(slide) -> str:
    return slide.notes_slide.notes_text_frame.text


# A deck whose slides carry the new key, the older key, and neither.
def _deck() -> dict:
    return {
        "title": "Notes deck",
        "slides": [
            {"html": "<div class='slide'>A</div>", "speaker_notes": "Say A."},
            {"html": "<div class='slide'>B</div>", "notes": "Legacy B."},
            {"html": "<div class='slide'>C</div>"},
        ],
    }


EXPECTED_DECK_NOTES = ["Say A.", "Legacy B.", ""]


# ---------------------------------------------------------------------------
# slide_notes_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slide, expected",
    [
        ({"speaker_notes": "New.", "notes": "Old."}, "New."),
        ({"notes": "Old."}, "Old."),
        ({}, ""),
        ({"speaker_notes": None, "notes": None}, ""),
        ({"speaker_notes": None, "notes": "Old."}, "Old."),
        # Ruling (controller, 2026-11-06): a present speaker_notes string wins even when
        # empty, so notes a presenter cleared never come back from a stale `notes` key.
        ({"speaker_notes": "", "notes": "Old."}, ""),
    ],
    ids=["both-keys", "only-notes", "neither", "none-values", "none-speaker", "empty-speaker"],
)
def test_slide_notes_text_prefers_speaker_notes(slide, expected):
    # Sabotage target: slide_notes_text reads `notes` before `speaker_notes`.
    from src.api.routes.export import slide_notes_text

    assert slide_notes_text(slide) == expected


# ---------------------------------------------------------------------------
# /pptx/editable/from-images
# ---------------------------------------------------------------------------


def test_from_images_writes_notes_into_the_pptx(client):
    # Sabotage target: skip the notes_text_frame write in export_pptx_screenshot_from_images.
    resp = client.post(
        FROM_IMAGES,
        json={"images": [_png_data_url(), _png_data_url()], "notes": ["Say A.", ""]},
    )
    assert resp.status_code == 200, resp.text
    slides = list(_parse_pptx(resp.content).slides)
    assert len(slides) == 2
    assert slides[0].has_notes_slide is True
    assert _notes_of(slides[0]) == "Say A."
    assert slides[1].has_notes_slide is False


def test_from_images_without_notes_is_unchanged(client):
    # Sabotage target: write a notes slide for every slide even when `notes` is absent.
    resp = client.post(FROM_IMAGES, json={"images": [_png_data_url(), _png_data_url()]})
    assert resp.status_code == 200, resp.text
    slides = list(_parse_pptx(resp.content).slides)
    assert len(slides) == 2
    assert all(s.has_notes_slide is False for s in slides)


def test_a_short_notes_list_and_a_bad_image_still_export(client):
    # Sabotage target: write notes after the bad-image `continue`, so slide 1 loses its notes.
    resp = client.post(
        FROM_IMAGES,
        json={
            "images": [_png_data_url(), "not-a-data-url", _png_data_url()],
            "notes": ["Say A.", "Say B."],
        },
    )
    assert resp.status_code == 200, resp.text
    slides = list(_parse_pptx(resp.content).slides)
    assert len(slides) == 3
    assert slides[0].has_notes_slide is True
    assert _notes_of(slides[0]) == "Say A."
    assert slides[1].has_notes_slide is True
    assert _notes_of(slides[1]) == "Say B."
    assert slides[2].has_notes_slide is False


# ---------------------------------------------------------------------------
# Google Slides /from-huashu
# ---------------------------------------------------------------------------


@pytest.fixture
def google_huashu_env(monkeypatch):
    """Stub every collaborator of the Google huashu route; record what huashu receives."""
    from src.api.main import app
    from src.core.database import get_db

    recorded: dict = {}

    def fake_build(title, slides_html, *, bypass_validation=False):
        recorded["title"] = title
        recorded["slides_html"] = slides_html
        return b"x", []

    auth = MagicMock()
    auth.is_authorized.return_value = True

    chat = MagicMock()
    chat.get_slides.return_value = _deck()

    session_manager = MagicMock()
    session_manager.get_google_slides_info.return_value = None

    gs = "src.api.routes.google_slides"
    monkeypatch.setattr(f"{gs}._check_deck_permission_for_session", lambda *a, **k: None)
    monkeypatch.setattr(f"{gs}._get_auth", lambda db: auth)
    monkeypatch.setattr(f"{gs}.get_chat_service", lambda: chat)
    monkeypatch.setattr(f"{gs}.upload_pptx_as_slides", lambda *a, **k: ("pid", "url"))
    # Keeps the test off the real HTML assembly; notes do not flow through it.
    monkeypatch.setattr(f"{gs}._build_slide_html", lambda slide, deck: slide["html"])
    monkeypatch.setattr(
        "src.api.services.chat_service.resolve_active_design_system_id", lambda sid: None
    )
    monkeypatch.setattr(
        "src.core.database.get_db_session", lambda: contextlib.nullcontext(MagicMock())
    )
    monkeypatch.setattr("src.utils.image_utils.substitute_deck_dict_images", lambda *a, **k: None)
    monkeypatch.setattr(
        "src.utils.ds_asset_utils.substitute_deck_dict_ds_assets", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "src.api.services.session_manager.get_session_manager", lambda: session_manager
    )
    monkeypatch.setattr("src.services.pptx_from_html_huashu.build_pptx_huashu", fake_build)

    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield recorded
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_google_slides_from_huashu_sends_speaker_notes(client, google_huashu_env):
    # Sabotage target: revert google_slides.py from-huashu to `slide.get("notes") or ""`.
    resp = client.post(GOOGLE_FROM_HUASHU, json={"session_id": "s1"})
    assert resp.status_code == 200, resp.text
    sent = google_huashu_env["slides_html"]
    assert [s["notes"] for s in sent] == EXPECTED_DECK_NOTES


# ---------------------------------------------------------------------------
# /pptx/editable/huashu/from-html (regression lock)
# ---------------------------------------------------------------------------


def test_huashu_export_sends_speaker_notes(client, monkeypatch):
    # Sabotage target: return "" from slide_notes_text (or drop speaker_notes at the huashu route).
    recorded: dict = {}

    def fake_build(title, slides_html, *, bypass_validation=False):
        recorded["slides_html"] = slides_html
        return b"x", []

    chat = MagicMock()
    chat.get_slides.return_value = _deck()

    ex = "src.api.routes.export"
    monkeypatch.setattr(f"{ex}._check_deck_permission_for_session", lambda *a, **k: None)
    monkeypatch.setattr(f"{ex}.get_chat_service", lambda: chat)
    monkeypatch.setattr(f"{ex}.build_slide_html", lambda slide, deck: slide["html"])
    monkeypatch.setattr("src.services.pptx_from_html_huashu.is_available", lambda: True)
    monkeypatch.setattr("src.services.pptx_from_html_huashu.build_pptx_huashu", fake_build)

    resp = client.post(HUASHU_FROM_HTML, json={"session_id": "s1"})
    assert resp.status_code == 200, resp.text
    assert [s["notes"] for s in recorded["slides_html"]] == EXPECTED_DECK_NOTES
