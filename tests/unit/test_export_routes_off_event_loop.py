"""The export routes run the sidecar off the event loop: the server answers while one runs.

The PPTX and Google Slides exports run ``build_pptx_huashu``, and the admin
``install-chromium`` and ``probe-launch`` routes run ``run_sidecar_process``:
each blocks for as long as its node script runs, tens of seconds for a real
deck. The routes are ``async``, so a direct call would hold the event loop for
all of it, and the worker would answer nothing else meanwhile, health checks and
other users' requests included. Each route awaits the call in a worker thread
(``asyncio.to_thread``) instead.

Each case drives the app through ``httpx.ASGITransport``, so the export and a
second request share one event loop: the export starts, and ``/api/health``,
asked for while the export's stub sidecar sleeps ``STUB_SECONDS``, must answer
within ``ANSWER_WITHIN_SECONDS`` of the export's start. The stub is a node
script in the sidecar's place, so the real ``build_pptx_huashu`` and
``run_sidecar_process`` run and block as they do in production.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.api.routes import export as export_routes
from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import requires_node

# How long each stub sidecar runs, and how soon a second request must be answered.
STUB_SECONDS = 3
ANSWER_WITHIN_SECONDS = 1
# How long after the export's start the second request is sent: the export is
# in its sidecar by then.
SECOND_REQUEST_AFTER_SECONDS = 0.3

# The export's sidecar: it reads the payload, sleeps, writes the .pptx and the result line.
STUB_EMIT_DECK = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const slides = JSON.parse(Buffer.concat(chunks).toString('utf-8')).slides.length;
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
fs.writeFileSync(process.argv[2], 'PK stub deck');
const result = { totalSlides: slides, succeeded: slides, failed: [] };
console.error('__HUASHU_RESULT__ ' + JSON.stringify(result));
"""

# An admin route's node script: it sleeps, then exits 0.
STUB_SCRIPT = """
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
console.log('PROBE_OK');
"""

DECK = {
    "title": "Deck",
    "slides": [{"slide_id": "s1", "html": "<div class='slide'><p>x</p></div>"}],
}


def _app():
    from src.api.main import app

    return app


async def _export_and_health(method: str, path: str, payload: dict | None) -> dict:
    """Start the export, ask for /api/health while it runs, and time both from the start."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        started = time.monotonic()
        export = asyncio.create_task(client.request(method, path, json=payload))
        await asyncio.sleep(SECOND_REQUEST_AFTER_SECONDS)
        health = await client.get("/api/health")
        health_at = time.monotonic() - started
        response = await export
        export_at = time.monotonic() - started
    return {
        "response": response,
        "health": health,
        "health_at": health_at,
        "export_at": export_at,
    }


def _assert_answered_meanwhile(timed: dict, what: str) -> None:
    assert timed["health"].status_code == 200, timed["health"].text
    assert timed["export_at"] >= STUB_SECONDS, (
        f"fixture drift: the {what} took {timed['export_at']:.1f}s, under its "
        f"{STUB_SECONDS}s sidecar"
    )
    assert timed["health_at"] < ANSWER_WITHIN_SECONDS, (
        f"/api/health answered {timed['health_at']:.1f}s after the {what} started: the "
        "export held the event loop"
    )


@pytest.fixture
def stub_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The sidecar directory, its scripts stubbed: emit_deck, probe_launch, the installer."""
    ms = STUB_SECONDS * 1000
    (tmp_path / "emit_deck.mjs").write_text(STUB_EMIT_DECK % {"ms": ms}, encoding="utf-8")
    (tmp_path / "probe_launch.mjs").write_text(STUB_SCRIPT % {"ms": ms}, encoding="utf-8")
    installer = tmp_path / "node_modules" / "playwright"
    installer.mkdir(parents=True)
    (installer / "cli.js").write_text(STUB_SCRIPT % {"ms": ms}, encoding="utf-8")
    (installer / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_DIR", tmp_path)
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", tmp_path / "emit_deck.mjs")
    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
    return tmp_path


@pytest.fixture
def admin_and_db() -> Iterator[None]:
    """The admin check passed and a database session stubbed, for the routes that take them."""
    from src.api.routes._authz import require_admin
    from src.core.database import get_db

    app = _app()

    def no_db() -> Iterator[None]:
        yield None

    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = no_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_db, None)


@requires_node
@pytest.mark.usefixtures("admin_and_db")
class TestTheServerAnswersDuringAnExport:
    def test_the_pptx_export(
        self, stub_sidecar: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat = MagicMock()
        chat.get_slides.return_value = DECK
        monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
        monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)

        timed = asyncio.run(
            _export_and_health(
                "POST", "/api/export/pptx/editable/huashu/from-html", {"session_id": "s1"}
            )
        )

        assert timed["response"].status_code == 200, timed["response"].text
        assert timed["response"].content == b"PK stub deck"
        _assert_answered_meanwhile(timed, "PPTX export")

    def test_the_google_slides_export(
        self, stub_sidecar: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = MagicMock()
        auth.is_authorized.return_value = True
        chat = MagicMock()
        chat.get_slides.return_value = DECK
        sessions = MagicMock()
        sessions.get_google_slides_info.return_value = None
        uploaded = []

        def upload(auth, pptx_bytes, title):
            uploaded.append(pptx_bytes)
            return "presentation-1", "https://docs.google.com/presentation/d/presentation-1"

        routes = "src.api.routes.google_slides"
        monkeypatch.setattr(f"{routes}._check_deck_permission_for_session", lambda *a, **k: None)
        monkeypatch.setattr(f"{routes}._get_auth", lambda db: auth)
        monkeypatch.setattr(f"{routes}.get_chat_service", lambda: chat)
        monkeypatch.setattr(f"{routes}._build_slide_html", lambda slide, deck: "<html></html>")
        monkeypatch.setattr(f"{routes}.upload_pptx_as_slides", upload)
        monkeypatch.setattr(
            "src.api.services.chat_service.resolve_active_design_system_id", lambda session_id: None
        )
        monkeypatch.setattr("src.utils.image_utils.substitute_deck_dict_images", lambda d, db: None)
        monkeypatch.setattr(
            "src.utils.ds_asset_utils.substitute_deck_dict_ds_assets",
            lambda deck, db, design_system_id=None: None,
        )
        monkeypatch.setattr(
            "src.api.services.session_manager.get_session_manager", lambda: sessions
        )
        monkeypatch.setattr("src.core.database.get_db_session", lambda: _no_session())

        timed = asyncio.run(
            _export_and_health(
                "POST", "/api/export/google-slides/from-huashu", {"session_id": "s1"}
            )
        )

        assert timed["response"].status_code == 200, timed["response"].text
        assert json.loads(timed["response"].text)["presentation_id"] == "presentation-1"
        assert uploaded == [b"PK stub deck"]
        _assert_answered_meanwhile(timed, "Google Slides export")

    @pytest.mark.parametrize(
        "path", ["/api/export/pptx/editable/huashu/probe-launch",
                 "/api/export/pptx/editable/huashu/install-chromium"]
    )
    def test_an_admin_diagnostic(self, stub_sidecar: Path, path: str) -> None:
        timed = asyncio.run(_export_and_health("POST", path, None))

        assert timed["response"].status_code == 200, timed["response"].text
        assert timed["response"].json() == {"ok": True, "returncode": 0}
        _assert_answered_meanwhile(timed, path.rsplit("/", 1)[-1])


class _NoSession:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


def _no_session() -> _NoSession:
    return _NoSession()
