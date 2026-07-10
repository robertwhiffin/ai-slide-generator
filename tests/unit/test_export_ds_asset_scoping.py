"""Export seams scope {{ds-asset:ID}} resolution to the session's design system.

The PPTX export route resolves ds-asset handles a second time (after
``get_slides`` already substituted) right before emit. That resolution must be
scoped to the session's ACTIVE design system: a deck carrying a foreign handle
(e.g. one echoed from a crafted pinned template) must NOT have the other
system's private bytes embedded into the exported artifact.

Driven through ``POST /api/export/pptx`` (an unchanged boundary) with the PPTX
converter mocked to capture the built slide HTML, so the test reproduces the
leak on the pre-fix code. All fixtures SYNTHETIC.
"""
import base64
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.api.main import app
from src.core.database import Base, get_db

VICTIM_SECRET = b"<svg xmlns='http://www.w3.org/2000/svg'><!--VICTIM-EXPORT-SECRET--></svg>"
ATTACKER_OWN = b"<svg xmlns='http://www.w3.org/2000/svg'><!--attacker-own--></svg>"


def _seed(session):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    victim = DesignSystem(name="Victim Export DS")
    victim.assets.append(
        DesignSystemAsset(
            kind="logo", filename="v.svg", mime="image/svg+xml",
            data=VICTIM_SECRET, size_bytes=len(VICTIM_SECRET),
        )
    )
    attacker = DesignSystem(name="Attacker Export DS")
    attacker.assets.append(
        DesignSystemAsset(
            kind="logo", filename="a.svg", mime="image/svg+xml",
            data=ATTACKER_OWN, size_bytes=len(ATTACKER_OWN),
        )
    )
    session.add_all([victim, attacker])
    session.commit()
    session.refresh(victim)
    session.refresh(attacker)
    return victim.assets[0].id, attacker.id, attacker.assets[0].id


def test_pptx_export_does_not_leak_foreign_ds_asset_bytes():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    victim_id, attacker_ds_id, attacker_logo_id = _seed(db)

    # Model output persisted in the session deck: references the Victim's asset
    # id (echoed foreign handle) AND the Attacker's own asset id.
    deck = {
        "title": "deck",
        "slides": [
            {
                "slide_id": "s0",
                "html": (
                    f'<img src="{{{{ds-asset:{victim_id}}}}}">'
                    f'<img src="{{{{ds-asset:{attacker_logo_id}}}}}">'
                ),
            }
        ],
    }

    def override_get_db():
        yield db

    @contextmanager
    def _fake_db_session():
        yield db

    captured = {}

    class _FakeConverter:
        def __init__(self, *a, **k):
            pass

        async def convert_slide_deck(self, slides, **kwargs):
            captured["slides"] = list(slides)

    mock_cs = MagicMock()
    mock_cs.get_slides.return_value = deck
    # The session's active design system is the Attacker's (the pinned system).
    mock_sm = MagicMock()
    mock_sm.get_session.return_value = {
        "agent_config": {"design_system_id": attacker_ds_id}
    }

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("src.api.routes.export.get_chat_service", return_value=mock_cs), \
             patch("src.api.routes.export.HtmlToPptxConverterV3", _FakeConverter), \
             patch("src.core.database.get_db_session", _fake_db_session), \
             patch(
                 "src.api.services.session_manager.get_session_manager",
                 return_value=mock_sm,
             ):
            client = TestClient(app)
            resp = client.post(
                "/api/export/pptx",
                json={"session_id": "sess-attacker", "use_screenshot": False},
            )
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()

    assert resp.status_code == 200, resp.text
    built = "".join(captured.get("slides", []))
    victim_b64 = base64.b64encode(VICTIM_SECRET).decode()
    attacker_b64 = base64.b64encode(ATTACKER_OWN).decode()
    # The Victim's private bytes must NOT be embedded in the export.
    assert victim_b64 not in built
    # The session's OWN asset still resolves to inline bytes.
    assert attacker_b64 in built
