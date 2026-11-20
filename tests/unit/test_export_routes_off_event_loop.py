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

The threadpool those handlers run in is bounded too (40 threads per worker), and
an export waiting for a sidecar holds one. So the waiting is bounded: past the
cap and ``TELLR_SIDECAR_QUEUE`` waiting exports, or past
``TELLR_SIDECAR_WAIT_SECONDS`` of waiting, both Chrome export routes answer 429
with a message to retry. One case runs a real uvicorn worker with more exports
than threads and asks a sync route and an authenticated route meanwhile.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import googleapiclient.http
import httpx
import pytest

from src.api.routes import export as export_routes
from src.services import drive_uploader, pptx_from_html_huashu
from src.services.google_slides_auth import GoogleSlidesAuth
from tests.fixtures.export_snapshot_support import requires_node

REPO_ROOT = Path(__file__).resolve().parents[2]

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


# What a busy worker answers an export, on both Chrome routes.
BUSY_DETAIL = "Exports are busy right now. Please try again in a minute."
BUSY_RETRY_AFTER = "60"
# The phrases the frontend reads as "this export is not installed here", which it answers
# by falling back to the records pipeline (useDeckExport.ts); a busy answer holds neither.
UNAVAILABLE_PHRASES = re.compile(
    r"huashu pipeline not available|pipeline (?:still )?installing", re.IGNORECASE
)
EXPORT_ROUTES = {
    "pptx": "/api/export/pptx/editable/huashu/from-html",
    "google": "/api/export/google-slides/from-huashu",
}
# The bounded-wait cases' bound on the wait for a slot: shorter than the stub's run.
WAIT_BOUND_SECONDS = 1


def _bound(monkeypatch: pytest.MonkeyPatch, *, cap: int, queue: int, wait: float) -> None:
    """The worker's sidecar bounds: ``cap`` run at once, ``queue`` more wait, each ``wait`` s."""
    monkeypatch.setattr(pptx_from_html_huashu, "_sidecar_slots", threading.BoundedSemaphore(cap))
    monkeypatch.setattr(
        pptx_from_html_huashu, "_sidecar_admissions", threading.BoundedSemaphore(cap + queue)
    )
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_WAIT_SECONDS", wait)


@pytest.fixture
def both_export_routes(stub_sidecar: Path, google_route: dict, monkeypatch) -> None:
    """Both Chrome routes' collaborators stubbed, and their sidecar a ``STUB_SECONDS`` run."""
    chat = MagicMock()
    chat.get_slides.return_value = DECK
    monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
    monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)


async def _exports_at_once(path: str, count: int) -> list[tuple[httpx.Response, float]]:
    """``count`` exports sent together: each answer with the seconds it took, in answer order."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        started = time.monotonic()
        answers: list[tuple[httpx.Response, float]] = []

        async def export() -> None:
            response = await client.post(path, json={"session_id": "s1"})
            answers.append((response, time.monotonic() - started))

        await asyncio.gather(*(export() for _ in range(count)))
    return answers


def _statuses(answers: list[tuple[httpx.Response, float]]) -> list[tuple[int, float, str]]:
    return [
        (response.status_code, round(seconds, 1), response.text[:120])
        for response, seconds in answers
    ]


def _assert_asks_for_a_retry(response: httpx.Response) -> None:
    assert response.status_code == 429, response.text
    assert response.json() == {"detail": BUSY_DETAIL}
    assert response.headers.get("retry-after") == BUSY_RETRY_AFTER, dict(response.headers)
    assert not UNAVAILABLE_PHRASES.search(response.text), response.text


@requires_node
@pytest.mark.usefixtures("admin_and_db", "both_export_routes")
class TestABusyWorkerAsksForARetry:
    """Past its sidecar bounds, a worker answers an export 429, ``Retry-After: 60``, on both routes.

    Cap 1: one sidecar per worker. An export past the cap and the
    ``TELLR_SIDECAR_QUEUE`` waiting ones is answered at once, and one that waits
    ``TELLR_SIDECAR_WAIT_SECONDS`` for a slot is answered then. Its detail is a
    sentence the frontend shows as it is, in an alert or a toast. It is never a 503
    and holds no "unavailable" phrase: the frontend answers those by falling back to
    the records pipeline without a word.
    """

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_an_export_past_the_queue_is_answered_at_once(
        self, route: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cap 1 and queue 1: of three exports at once, two are built and the third is refused."""
        _bound(monkeypatch, cap=1, queue=1, wait=4 * STUB_SECONDS)

        answers = asyncio.run(_exports_at_once(EXPORT_ROUTES[route], 3))

        assert sorted(response.status_code for response, _ in answers) == [200, 200, 429], (
            _statuses(answers)
        )
        refused, seconds = answers[0]
        _assert_asks_for_a_retry(refused)
        assert seconds < ANSWER_WITHIN_SECONDS, f"the export past the queue waited {seconds:.1f}s"

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_a_wait_past_its_bound_is_answered_then(
        self, route: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cap 1 and a 1 s bound: the second export is refused after 1 s, the first still runs."""
        _bound(monkeypatch, cap=1, queue=15, wait=WAIT_BOUND_SECONDS)

        answers = asyncio.run(_exports_at_once(EXPORT_ROUTES[route], 2))

        assert [response.status_code for response, _ in answers] == [429, 200], _statuses(answers)
        refused, seconds = answers[0]
        _assert_asks_for_a_retry(refused)
        assert WAIT_BOUND_SECONDS - 0.1 <= seconds < WAIT_BOUND_SECONDS + ANSWER_WITHIN_SECONDS, (
            f"refused after {seconds:.1f}s, the bound {WAIT_BOUND_SECONDS}s"
        )

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_with_the_default_bounds_two_exports_both_succeed(
        self, route: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normal use: the second export waits its turn and is built; neither is refused."""
        _bound(
            monkeypatch,
            cap=pptx_from_html_huashu.sidecar_concurrency({}),
            queue=pptx_from_html_huashu.sidecar_queue({}),
            wait=pptx_from_html_huashu.sidecar_wait_seconds({}),
        )

        answers = asyncio.run(_exports_at_once(EXPORT_ROUTES[route], 2))

        assert [response.status_code for response, _ in answers] == [200, 200], _statuses(answers)
        assert answers[1][1] >= 2 * STUB_SECONDS, (
            f"the second export answered after {answers[1][1]:.1f}s: the sidecars overlapped"
        )


# More exports than a worker's 40 threads, sent to it at once.
EXPORT_BURST = 50
# How long the exports past the bounds have to be answered before the probes ask.
SETTLE_SECONDS = 3
# A probe that has no answer after this got none.
PROBE_TIMEOUT_SECONDS = 5
# How long the real worker has to start answering.
WORKER_START_SECONDS = 60
# The parked exports' sidecar sleeps past the whole case, so none of them finishes in it.
PARKED_RUN_MS = 60_000

# What the real worker is asked while its exports are parked: a sync def route, which runs in
# the threadpool, and an async route with an access token, whose identity lookup does too.
WORKER_PROBES = {
    "a sync def route (/api/tools/discover/genie)": ("/api/tools/discover/genie", {}),
    "an authenticated async route (/api/health with an access token)": (
        "/api/health",
        {"x-forwarded-access-token": "token"},
    ),
}

# The parked exports' sidecar: it records its start, then sleeps.
STUB_PARKED_EMIT_DECK = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
fs.appendFileSync(%(runs)s, 'start\\n');
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
fs.writeFileSync(process.argv[2], 'PK stub deck');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
"""

# One uvicorn worker of the real app, run as production runs it: Starlette's threadpool, and the
# sidecar bounds read from the environment at import (their defaults here). Stubbed: the export's
# deck read and permission check, the identity lookup an access token makes, the Genie listing,
# the database session, and the sidecar (argv[1]). It writes the port it serves on to argv[2].
WORKER_SCRIPT = """
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import uvicorn

import src.api.main as main
from src.api.routes import export as export_routes, tools
from src.core.database import get_db
from src.services import pptx_from_html_huashu

pptx_from_html_huashu.SIDECAR_SCRIPT = Path(sys.argv[1])
pptx_from_html_huashu.is_available = lambda: True
chat = MagicMock()
chat.get_slides.return_value = {"title": "Deck", "slides": [{"slide_id": "s1", "html": "<p>x</p>"}]}
export_routes._check_deck_permission_for_session = lambda *a, **k: None
export_routes.get_chat_service = lambda: chat
tools._discover_genie_spaces = lambda: []
main.get_or_create_user_client_and_identity = lambda token: (
    SimpleNamespace(), SimpleNamespace(id="u1", user_name="alice@example.com")
)


def no_db():
    yield MagicMock()


main.app.dependency_overrides[get_db] = no_db
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
Path(sys.argv[2] + ".part").write_text(str(listener.getsockname()[1]), encoding="utf-8")
os.replace(sys.argv[2] + ".part", sys.argv[2])
uvicorn.Server(uvicorn.Config(main.app, lifespan="off", log_level="error")).run(sockets=[listener])
"""


def _started_worker(worker: subprocess.Popen, port_file: Path, log: Path) -> int:
    """The port the worker serves on, once it answers; fails with its log if it never does."""
    deadline = time.monotonic() + WORKER_START_SECONDS
    while time.monotonic() < deadline and worker.poll() is None:
        if port_file.exists():
            port = int(port_file.read_text(encoding="utf-8"))
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                    return port
            except httpx.HTTPError:
                pass
        time.sleep(0.1)
    pytest.fail(
        f"the worker never answered (exit {worker.poll()}): "
        f"{log.read_text(encoding='utf-8', errors='replace')[-2000:]}"
    )


def _answer(response: httpx.Response) -> tuple[int, object]:
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:120]


async def _a_burst_then_probes(port: int) -> dict:
    """``EXPORT_BURST`` exports at once; once the refusals are in, each probe, timed."""
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=0)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", limits=limits) as client:
        exports = [
            asyncio.create_task(
                client.post(EXPORT_ROUTES["pptx"], json={"session_id": "s1"}, timeout=None)
            )
            for _ in range(EXPORT_BURST)
        ]
        done, parked = await asyncio.wait(exports, timeout=SETTLE_SECONDS)

        async def probe(path: str, headers: dict[str, str]) -> tuple[int | None, float]:
            asked = time.monotonic()
            try:
                response = await client.get(path, headers=headers, timeout=PROBE_TIMEOUT_SECONDS)
            except httpx.TimeoutException:
                return None, time.monotonic() - asked
            return response.status_code, time.monotonic() - asked

        probes = await asyncio.gather(
            *(probe(path, headers) for path, headers in WORKER_PROBES.values())
        )
        for export in parked:
            export.cancel()
        await asyncio.gather(*parked, return_exceptions=True)
    answered = [
        repr(export.exception()) if export.exception() else _answer(export.result())
        for export in done
    ]
    return {"probes": dict(zip(WORKER_PROBES, probes)), "parked": len(parked), "answered": answered}


@requires_node
class TestAWorkerFullOfExportsStillAnswers:
    """A real uvicorn worker sent more exports than it has threads still answers everything else.

    An export waiting for a sidecar holds a thread of the worker's threadpool: 40 by
    default, shared with every sync ``def`` route and every authenticated request's
    identity lookup (``user_auth_middleware``). Unbounded, 40 waiting exports took them
    all, and the worker answered none of those until the exports drained. Here
    ``EXPORT_BURST`` exports reach one worker at the default bounds. The cap plus the
    queue of them (16) are parked, one running and the rest waiting; the others are
    answered 429 at once; and a sync route and an authenticated async route each answer
    within ``ANSWER_WITHIN_SECONDS``.
    """

    def test_a_sync_route_and_an_authenticated_route_answer(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs.log"
        stub = tmp_path / "emit_deck_parked.mjs"
        stub.write_text(
            STUB_PARKED_EMIT_DECK % {"runs": json.dumps(str(runs)), "ms": PARKED_RUN_MS},
            encoding="utf-8",
        )
        script = tmp_path / "worker.py"
        script.write_text(WORKER_SCRIPT, encoding="utf-8")
        port_file = tmp_path / "port"
        log = tmp_path / "worker.log"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("TELLR_SIDECAR_")
        }
        env.update(
            DATABASE_URL=f"sqlite:///{tmp_path / 'worker.sqlite'}",
            ENVIRONMENT="test",
            PYTHONPATH=str(REPO_ROOT),
        )
        with log.open("wb") as output:
            worker = subprocess.Popen(
                [sys.executable, str(script), str(stub), str(port_file)],
                stdout=output,
                stderr=subprocess.STDOUT,
                cwd=REPO_ROOT,
                env=env,
                start_new_session=True,
            )
        try:
            port = _started_worker(worker, port_file, log)
            measured = asyncio.run(_a_burst_then_probes(port))
        finally:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait()
            subprocess.run(["pkill", "-9", "-f", str(stub)], check=False)

        for name, (status, seconds) in measured["probes"].items():
            assert status == 200 and seconds < ANSWER_WITHIN_SECONDS, (
                f"{name}: {status or 'no answer'} after {seconds:.1f}s, "
                f"with {measured['parked']} of {EXPORT_BURST} exports parked"
            )
        cap = pptx_from_html_huashu.sidecar_concurrency({})
        queue = pptx_from_html_huashu.sidecar_queue({})
        assert measured["parked"] == cap + queue, measured
        refused = EXPORT_BURST - cap - queue
        assert measured["answered"] == [(429, {"detail": BUSY_DETAIL})] * refused, (
            measured["answered"]
        )
        assert runs.read_text(encoding="utf-8").split() == ["start"] * cap, "past the cap"



# A Drive request that has heard nothing for this long fails (the test's
# DRIVE_HTTP_TIMEOUT_SECONDS), and an export must answer within this many of
# them plus the slack: the sidecar stub, and the app around the upload.
DRIVE_SILENCE_SECONDS = 1
DRIVE_ANSWER_SLACK_SECONDS = 4
# What bounds a Drive request when the export's own timeout does not: the
# socket timeout googleapiclient's build_http gives a request by default
# (googleapiclient.http.DEFAULT_HTTP_TIMEOUT_SEC, 60 s), made this for the
# Drive tests (``_real_drive``), so an export that lost its own timeout fails
# them in seconds, not minutes. It must outlast each request's share of the
# bound the test asserts (5 s for the upload, 3 s for each of a replace's two
# requests), or such an export would still answer in time, and pass. The
# export's thread is waited for this long per request, so it ends before the
# redirect to the silent server does, whatever the export got wrong.
LIBRARY_SOCKET_TIMEOUT_SECONDS = 10
# The hosts the redirect holds: every Google API and account host.
GOOGLE_DOMAINS = ("googleapis.com", "google.com")
# The settings that send a client's requests through a proxy instead of to their
# host: httplib2, the Drive client's, reads https_proxy (with PySocks installed),
# and urllib and requests read all of these. None is left set while the redirect
# holds Google's hosts.
PROXY_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
# An address off this machine that no network routes (TEST-NET-1, RFC 5737), and
# a proxy there: what a developer's environment could point the Drive client at.
NON_LOOPBACK_ADDRESS = "192.0.2.1"
NON_LOOPBACK_PROXY = f"http://{NON_LOOPBACK_ADDRESS}:3128"
# A token Credentials take as valid: it expires long after the test, so no refresh is tried.
FAKE_GOOGLE_TOKEN = {
    "token": "fake-access-token",
    "expiry": "2099-01-01T00:00:00Z",
    "refresh_token": "fake-refresh-token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _is_google(host: object) -> bool:
    return isinstance(host, str) and any(
        host == domain or host.endswith("." + domain) for domain in GOOGLE_DOMAINS
    )


def _is_this_machine(host: object) -> bool:
    """Whether ``host`` is this machine: none, ``localhost``, or a loopback or unspecified address.

    A host name is not: looking it up, let alone connecting to it, leaves the machine.
    """
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None or host in ("", "localhost"):
        return True
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


class _SilentGoogle:
    """Google's hosts, for one test: a local server that takes each connection and never answers.

    While it is open, every lookup of a Google host (``GOOGLE_DOMAINS``) answers
    its address and every connection to one is made to it, so the real Drive
    client, from its http object to its TLS handshake, waits on a server that
    never answers: the Drive that hangs. Once it is closed, a lookup of a Google
    host fails and a connection to one is refused. Either way nothing to a
    Google host falls through to the network. Nor to any other host: while it
    is installed, a lookup or a connection to a host off this machine that is
    not Google's (a proxy's, say) is refused, and recorded in ``refused``.
    ``threads`` are the test's threads that may still talk to Google: they must
    end before it closes.
    """

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self._address = self._server.getsockname()
        self._closed = False
        self.threads: list[threading.Thread] = []
        # The hosts looked up, and the addresses connected to, that it refused.
        self.refused: list[object] = []
        self._lookup = socket.getaddrinfo
        self._connect = socket.socket.connect
        # socket.socket inherits connect from _socket.socket: undone, it inherits it again.
        self._own_connect = "connect" in vars(socket.socket)

    def resolve(self, host, port, *args, **kwargs):
        if _is_google(host):
            if self._closed:
                raise socket.gaierror(socket.EAI_NONAME, f"{host}: no Google host in this test")
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", self._address)]
        if not _is_this_machine(host):
            self.refused.append(host)
            raise socket.gaierror(socket.EAI_NONAME, f"{host}: off this machine, in this test")
        return self._lookup(host, port, *args, **kwargs)

    def connect(self, sock: socket.socket, address: object) -> None:
        if isinstance(address, tuple):
            if _is_google(address[0]):
                if self._closed:
                    raise ConnectionRefusedError(f"{address[0]}: no Google host in this test")
                address = self._address
            elif not _is_this_machine(address[0]):
                self.refused.append(address)
                raise ConnectionRefusedError(f"{address[0]}: off this machine, in this test")
        return self._connect(sock, address)

    def install(self) -> None:
        silent = self
        socket.getaddrinfo = self.resolve
        socket.socket.connect = lambda sock, address: silent.connect(sock, address)

    def close(self) -> None:
        self._closed = True
        self._server.close()

    def uninstall(self) -> None:
        socket.getaddrinfo = self._lookup
        if self._own_connect:
            socket.socket.connect = self._connect
        else:
            del socket.socket.connect


@pytest.fixture
def silent_drive(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SilentGoogle]:
    """Google's hosts held by a ``_SilentGoogle`` for the test, and torn down in order.

    No proxy setting is left while it holds them (``PROXY_VARIABLES``): with
    one, the Drive client would send its requests to the proxy's host, not a
    Google one. First the test's threads are waited for, then the server is
    closed, and only then is the redirect undone: a thread still running then
    would reach the network, so the redirect stays, refusing every host off this
    machine, and the test errs. The proxy settings come back after it.
    """
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    silent = _SilentGoogle()
    silent.install()
    try:
        yield silent
    finally:
        for thread in silent.threads:
            thread.join(timeout=2 * LIBRARY_SOCKET_TIMEOUT_SECONDS + DRIVE_ANSWER_SLACK_SECONDS)
        running = [thread.name for thread in silent.threads if thread.is_alive()]
        silent.close()
        if not running:
            silent.uninstall()
    assert not running, (
        f"{running} still running at teardown: Google's hosts stay refused for this process"
    )


@pytest.fixture
def proxy_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> str:
    """Every proxy setting pointed off this machine, as a developer's environment could be.

    Listed before ``silent_drive``, it is set up first: the environment the test started in.
    """
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, NON_LOOPBACK_PROXY)
    return NON_LOOPBACK_PROXY


def _proxy_settings() -> list[str]:
    """The proxy settings the environment holds now."""
    return [name for name in PROXY_VARIABLES if name in os.environ]


class TestTheSilentGoogle:
    """The redirect the Drive tests run under: Google's hosts are the silent server, and only them.

    A test that fails must not reach the network either. So while the redirect
    is installed, a lookup or a connection to any host off this machine but
    Google's is refused, and recorded, and no proxy setting is left that would
    send the Drive client's requests to another host.
    """

    def test_no_proxy_setting_is_left(
        self, proxy_in_the_environment: str, silent_drive: _SilentGoogle
    ) -> None:
        assert _proxy_settings() == [], (
            f"proxy settings left while Google's hosts are redirected: {_proxy_settings()}"
        )

    def test_nothing_off_this_machine_but_google_is_reached(
        self, silent_drive: _SilentGoogle
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            with pytest.raises(ConnectionRefusedError):
                sock.connect((NON_LOOPBACK_ADDRESS, 3128))
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("example.com", 443)
        ((_, _, _, _, silent_server),) = socket.getaddrinfo("www.googleapis.com", 443)
        for address in (("www.googleapis.com", 443), silent_server):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(address)  # the silent server takes it, and says nothing
        assert silent_drive.refused == [(NON_LOOPBACK_ADDRESS, 3128), "example.com"]


@requires_node
@pytest.mark.usefixtures("admin_and_db")
class TestADriveThatNeverAnswers:
    """A Drive request whose server never answers fails, and the export answers 502.

    The real Drive client runs: ``upload_pptx_as_slides`` and
    ``replace_presentation`` (drive_uploader.py) on the service
    ``GoogleSlidesAuth.build_drive_service`` builds, with the timeout
    ``DRIVE_HTTP_TIMEOUT_SECONDS`` on its http object. Each request waits on
    its socket until the timeout ends it, and the route answers as for any Drive
    failure, 502 "Drive upload failed", having recorded nothing. Without the
    timeout a hung Drive request would hold the export, and its thread, for as
    long as the library's default lets it: 60 s per request, made
    ``LIBRARY_SOCKET_TIMEOUT_SECONDS`` here, so such a run fails in seconds.
    """

    @pytest.fixture(autouse=True)
    def _real_drive(
        self, stub_sidecar: Path, google_route: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (stub_sidecar / "emit_deck.mjs").write_text(STUB_EMIT_DECK % {"ms": 0}, encoding="utf-8")
        auth = GoogleSlidesAuth(credentials_json="{}", token_json=json.dumps(FAKE_GOOGLE_TOKEN))
        assert auth.is_authorized(), "fixture drift: the fake token is not valid"
        routes = google_route["routes"]
        monkeypatch.setattr(f"{routes}._get_auth", lambda db: auth)
        monkeypatch.setattr(f"{routes}.upload_pptx_as_slides", drive_uploader.upload_pptx_as_slides)
        monkeypatch.setattr(f"{routes}.replace_presentation", drive_uploader.replace_presentation)
        monkeypatch.setattr(drive_uploader, "DRIVE_HTTP_TIMEOUT_SECONDS", DRIVE_SILENCE_SECONDS)
        # The library's own default made short (LIBRARY_SOCKET_TIMEOUT_SECONDS).
        # build_http takes a process-wide default socket timeout over it.
        assert socket.getdefaulttimeout() is None, (
            "fixture drift: a default socket timeout, not the library's, would bound Drive"
        )
        monkeypatch.setattr(
            googleapiclient.http, "DEFAULT_HTTP_TIMEOUT_SEC", LIBRARY_SOCKET_TIMEOUT_SECONDS
        )

    @pytest.mark.parametrize(
        ("existing", "requests"),
        [(None, 1), ("existing-1", 2)],
        ids=["upload", "replace"],
    )
    def test_the_export_is_answered_502_within_the_timeout(
        self,
        existing: str | None,
        requests: int,
        google_route: dict,
        silent_drive: _SilentGoogle,
    ) -> None:
        """A first export uploads (one request); a re-export deletes, then uploads (two)."""
        self._assert_answered_502_in_time(existing, requests, google_route, silent_drive)

    def test_a_proxy_in_the_environment_is_not_used(
        self, proxy_in_the_environment: str, google_route: dict, silent_drive: _SilentGoogle
    ) -> None:
        """A proxy set where the test runs: the upload meets the silent Drive, never the proxy.

        httplib2 sends an https request through ``https_proxy`` once PySocks is
        installed, to the proxy's host, not a Google one: past the redirect, off
        this machine.
        """
        assert _proxy_settings() == [], f"proxy settings left: {_proxy_settings()}"
        self._assert_answered_502_in_time(None, 1, google_route, silent_drive)

    def _assert_answered_502_in_time(
        self,
        existing: str | None,
        requests: int,
        google_route: dict,
        silent_drive: _SilentGoogle,
    ) -> None:
        """The export answered 502 once its ``requests`` Drive requests timed out, and no sooner.

        Whatever the export does, its thread ends before the test does: past the
        bound the test asserts, it is waited for as long as the library's own
        socket timeout could hold each request. And it tried no host off this
        machine but Google's.
        """
        from fastapi.testclient import TestClient

        google_route["sessions"].get_google_slides_info.return_value = (
            None if existing is None else {"presentation_id": existing}
        )
        bound = requests * DRIVE_SILENCE_SECONDS + DRIVE_ANSWER_SLACK_SECONDS
        assert LIBRARY_SOCKET_TIMEOUT_SECONDS > bound / requests, (
            f"fixture drift: the library's {LIBRARY_SOCKET_TIMEOUT_SECONDS}s default would end "
            f"each of {requests} request(s) within the {bound}s bound, so an export that lost "
            "its own Drive timeout would pass"
        )
        answer: dict = {}

        def export() -> None:
            started = time.monotonic()
            answer["response"] = TestClient(_app()).post(
                "/api/export/google-slides/from-huashu", json={"session_id": "s1"}
            )
            answer["seconds"] = time.monotonic() - started

        thread = threading.Thread(target=export, name="drive-export", daemon=True)
        silent_drive.threads.append(thread)
        thread.start()
        try:
            thread.join(timeout=bound)
            answered_in_time = not thread.is_alive()
        finally:
            thread.join(
                timeout=requests * LIBRARY_SOCKET_TIMEOUT_SECONDS + DRIVE_ANSWER_SLACK_SECONDS
            )

        assert answered_in_time, (
            f"no answer within {bound}s: a Drive request that never answers holds the export"
        )
        response = answer["response"]
        assert (response.status_code, response.json()) == (502, {"detail": "Drive upload failed"})
        assert answer["seconds"] >= requests * DRIVE_SILENCE_SECONDS, (
            f"answered after {answer['seconds']:.1f}s, before its Drive requests timed out"
        )
        google_route["sessions"].set_google_slides_info.assert_not_called()
        assert silent_drive.refused == [], (
            f"the export tried hosts off this machine: {silent_drive.refused}"
        )
