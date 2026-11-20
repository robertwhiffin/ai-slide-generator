"""The export routes leave the event loop free: the server answers while an export runs.

An export blocks for as long as its slowest step takes: the sidecar
(``build_pptx_huashu``, tens of seconds for a real deck), the Drive upload or
replace (seconds), and the database, token and slide reads before them. The
PPTX ``/from-html`` route and the Google Slides ``/from-huashu`` and
``/from-records`` routes are plain ``def`` handlers, so FastAPI runs each whole
body in its threadpool; the admin ``install-chromium`` and ``probe-launch``
routes await ``run_sidecar_process`` in a worker thread. On the event loop any
of those steps would hold the worker, which would answer nothing else
meanwhile: health checks, other users' requests and their chat streams.

Each case drives the app through ``httpx.ASGITransport``, so the export and
everything else share one event loop. While the export runs, a ticker on that
loop records the longest gap between its ticks (the longest the loop was held),
and ``/api/health`` is asked for again and again: the loop is never held for
``ANSWER_WITHIN_SECONDS``, and every health check answers within it. The step
under test blocks for ``STUB_SECONDS``: a stub node script in the sidecar's
place, so the real ``build_pptx_huashu`` and ``run_sidecar_process`` run and
block as they do in production, or a Drive upload or a deck read made slow.
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

# How long the step under test blocks, and the longest the loop may be held.
STUB_SECONDS = 3
ANSWER_WITHIN_SECONDS = 1
# How often the ticker ticks and the health check is asked for.
TICK_SECONDS = 0.05
HEALTH_EVERY_SECONDS = 0.2

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
PRESENTATION = ("presentation-1", "https://docs.google.com/presentation/d/presentation-1")


def _app():
    from src.api.main import app

    return app


def _slowly(value: object):
    """A stand-in for a blocking step: it sleeps ``STUB_SECONDS``, then returns ``value``."""

    def step(*_: object, **__: object) -> object:
        time.sleep(STUB_SECONDS)
        return value

    return step


async def _during_the_export(method: str, path: str, payload: dict | None) -> dict:
    """Run the export, and measure the event loop and ``/api/health`` until it answers."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        started = time.monotonic()
        export = asyncio.create_task(client.request(method, path, json=payload))
        held: list[float] = []
        health: list[tuple[float, int]] = []

        async def tick() -> None:
            last = time.monotonic()
            while not export.done():
                await asyncio.sleep(TICK_SECONDS)
                now = time.monotonic()
                held.append(now - last - TICK_SECONDS)
                last = now

        async def ask_for_health() -> None:
            while not export.done():
                asked = time.monotonic()
                answer = await client.get("/api/health")
                health.append((time.monotonic() - asked, answer.status_code))
                await asyncio.sleep(HEALTH_EVERY_SECONDS)

        await asyncio.gather(tick(), ask_for_health())
        response = await export
    return {
        "response": response,
        "export_seconds": time.monotonic() - started,
        "longest_hold": max(held, default=0.0),
        "health": health,
    }


def _assert_answered_meanwhile(measured: dict, what: str) -> None:
    assert measured["export_seconds"] >= STUB_SECONDS, (
        f"fixture drift: the {what} took {measured['export_seconds']:.1f}s, under its "
        f"{STUB_SECONDS}s step"
    )
    assert measured["longest_hold"] < ANSWER_WITHIN_SECONDS, (
        f"the {what} held the event loop for {measured['longest_hold']:.1f}s"
    )
    health = measured["health"]
    assert len(health) >= 2 and all(status == 200 for _, status in health), health
    slowest = max(seconds for seconds, _ in health)
    assert slowest < ANSWER_WITHIN_SECONDS, (
        f"/api/health took {slowest:.1f}s to answer while the {what} ran"
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


class _NoSession:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def google_route(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The Google Slides routes' collaborators stubbed; Drive's upload records what it was sent."""
    auth = MagicMock()
    auth.is_authorized.return_value = True
    chat = MagicMock()
    chat.get_slides.return_value = DECK
    sessions = MagicMock()
    sessions.get_google_slides_info.return_value = None
    uploaded: list[bytes] = []
    routes = "src.api.routes.google_slides"
    monkeypatch.setattr(f"{routes}._check_deck_permission_for_session", lambda *a, **k: None)
    monkeypatch.setattr(f"{routes}._get_auth", lambda db: auth)
    monkeypatch.setattr(f"{routes}.get_chat_service", lambda: chat)
    monkeypatch.setattr(f"{routes}._build_slide_html", lambda slide, deck: "<html></html>")
    monkeypatch.setattr(
        "src.api.services.chat_service.resolve_active_design_system_id", lambda session_id: None
    )
    monkeypatch.setattr("src.utils.image_utils.substitute_deck_dict_images", lambda d, db: None)
    monkeypatch.setattr(
        "src.utils.ds_asset_utils.substitute_deck_dict_ds_assets",
        lambda deck, db, design_system_id=None: None,
    )
    monkeypatch.setattr("src.api.services.session_manager.get_session_manager", lambda: sessions)
    monkeypatch.setattr("src.core.database.get_db_session", lambda: _NoSession())

    def upload(auth: object, pptx_bytes: bytes, title: str) -> tuple[str, str]:
        uploaded.append(pptx_bytes)
        return PRESENTATION

    monkeypatch.setattr(f"{routes}.upload_pptx_as_slides", upload)
    return {"uploaded": uploaded, "sessions": sessions, "routes": routes}


def _slow_upload(monkeypatch: pytest.MonkeyPatch, google: dict) -> None:
    """Drive's upload made to block for ``STUB_SECONDS``, still recording what it was sent."""

    def upload(auth: object, pptx_bytes: bytes, title: str) -> tuple[str, str]:
        google["uploaded"].append(pptx_bytes)
        time.sleep(STUB_SECONDS)
        return PRESENTATION

    monkeypatch.setattr(f"{google['routes']}.upload_pptx_as_slides", upload)


@requires_node
@pytest.mark.usefixtures("admin_and_db")
class TestTheServerAnswersDuringAnExport:
    def test_the_pptx_export_while_its_sidecar_runs(
        self, stub_sidecar: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat = MagicMock()
        chat.get_slides.return_value = DECK
        monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
        monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)

        measured = asyncio.run(
            _during_the_export(
                "POST", "/api/export/pptx/editable/huashu/from-html", {"session_id": "s1"}
            )
        )

        assert measured["response"].status_code == 200, measured["response"].text
        assert measured["response"].content == b"PK stub deck"
        _assert_answered_meanwhile(measured, "PPTX export")

    def test_the_pptx_export_while_it_reads_the_deck(
        self, stub_sidecar: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deck read before the sidecar (the database, image substitution) blocks too."""
        chat = MagicMock()
        chat.get_slides.side_effect = _slowly(DECK)
        monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
        monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)

        measured = asyncio.run(
            _during_the_export(
                "POST", "/api/export/pptx/editable/huashu/from-html", {"session_id": "s1"}
            )
        )

        assert measured["response"].status_code == 200, measured["response"].text
        _assert_answered_meanwhile(measured, "PPTX export's deck read")

    def test_the_google_slides_export_while_its_sidecar_runs(
        self, stub_sidecar: Path, google_route: dict
    ) -> None:
        measured = asyncio.run(
            _during_the_export(
                "POST", "/api/export/google-slides/from-huashu", {"session_id": "s1"}
            )
        )

        assert measured["response"].status_code == 200, measured["response"].text
        assert json.loads(measured["response"].text)["presentation_id"] == PRESENTATION[0]
        assert google_route["uploaded"] == [b"PK stub deck"]
        _assert_answered_meanwhile(measured, "Google Slides export")

    def test_the_google_slides_export_while_drive_uploads(
        self, stub_sidecar: Path, google_route: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _slow_upload(monkeypatch, google_route)

        measured = asyncio.run(
            _during_the_export(
                "POST", "/api/export/google-slides/from-huashu", {"session_id": "s1"}
            )
        )

        assert measured["response"].status_code == 200, measured["response"].text
        assert google_route["uploaded"] == [b"PK stub deck"]
        _assert_answered_meanwhile(measured, "Google Slides export's Drive upload")

    def test_the_records_export_while_drive_uploads(
        self, google_route: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _slow_upload(monkeypatch, google_route)
        monkeypatch.setattr(f"{google_route['routes']}.build_pptx", lambda **_: b"PK records deck")

        measured = asyncio.run(
            _during_the_export(
                "POST",
                "/api/export/google-slides/from-records",
                {"session_id": "s1", "title": "Deck", "slides": [{"elements": []}]},
            )
        )

        assert measured["response"].status_code == 200, measured["response"].text
        assert google_route["uploaded"] == [b"PK records deck"]
        _assert_answered_meanwhile(measured, "records export's Drive upload")

    @pytest.mark.parametrize(
        "path",
        [
            "/api/export/pptx/editable/huashu/probe-launch",
            "/api/export/pptx/editable/huashu/install-chromium",
        ],
    )
    def test_an_admin_diagnostic(self, stub_sidecar: Path, path: str) -> None:
        measured = asyncio.run(_during_the_export("POST", path, None))

        assert measured["response"].status_code == 200, measured["response"].text
        assert measured["response"].json() == {"ok": True, "returncode": 0}
        _assert_answered_meanwhile(measured, path.rsplit("/", 1)[-1])


@requires_node
@pytest.mark.usefixtures("admin_and_db")
class TestTheSharedDriveUpload:
    """``/from-huashu`` and ``/from-records`` answer as they did, through the one Drive helper."""

    ROUTES = {
        "huashu": ("/api/export/google-slides/from-huashu", {"session_id": "s1"}),
        "records": (
            "/api/export/google-slides/from-records",
            {"session_id": "s1", "title": "Deck", "slides": [{"elements": []}]},
        ),
    }

    @pytest.fixture(autouse=True)
    def _quick_sidecar(self, stub_sidecar: Path, google_route: dict, monkeypatch) -> None:
        (stub_sidecar / "emit_deck.mjs").write_text(STUB_EMIT_DECK % {"ms": 0}, encoding="utf-8")
        monkeypatch.setattr(f"{google_route['routes']}.build_pptx", lambda **_: b"PK records deck")

    def _post(self, route: str) -> httpx.Response:
        from fastapi.testclient import TestClient

        path, payload = self.ROUTES[route]
        return TestClient(_app()).post(path, json=payload)

    @pytest.mark.parametrize("route", ["huashu", "records"])
    def test_a_drive_failure_is_a_502(
        self, route: str, google_route: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(*_: object) -> None:
            raise RuntimeError("drive is down")

        monkeypatch.setattr(f"{google_route['routes']}.upload_pptx_as_slides", fail)
        response = self._post(route)
        assert (response.status_code, response.json()) == (502, {"detail": "Drive upload failed"})
        google_route["sessions"].set_google_slides_info.assert_not_called()

    @pytest.mark.parametrize("route", ["huashu", "records"])
    def test_a_reexport_replaces_the_sessions_presentation(
        self, route: str, google_route: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        google_route["sessions"].get_google_slides_info.return_value = {
            "presentation_id": "existing-1"
        }
        replaced = []

        def replace(auth: object, presentation_id: str, pptx_bytes: bytes, title: str):
            replaced.append((presentation_id, pptx_bytes, title))
            return "existing-1", "https://docs.google.com/presentation/d/existing-1"

        monkeypatch.setattr(f"{google_route['routes']}.replace_presentation", replace)
        response = self._post(route)
        assert response.status_code == 200, response.text
        assert response.json()["presentation_id"] == "existing-1"
        assert [entry[0] for entry in replaced] == ["existing-1"] and google_route["uploaded"] == []
        google_route["sessions"].set_google_slides_info.assert_called_once_with(
            session_id="s1",
            presentation_id="existing-1",
            presentation_url="https://docs.google.com/presentation/d/existing-1",
        )

    def test_the_huashu_answer(self, google_route: dict) -> None:
        response = self._post("huashu")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "presentation_id": PRESENTATION[0],
            "presentation_url": PRESENTATION[1],
            "total_slides": 1,
            "succeeded": 1,
            "failures": [],
        }

    def test_the_records_answer(self, google_route: dict) -> None:
        response = self._post("records")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "presentation_id": PRESENTATION[0],
            "presentation_url": PRESENTATION[1],
            "total_slides": None,
            "succeeded": None,
            "failures": [],
        }
        assert google_route["uploaded"] == [b"PK records deck"]
