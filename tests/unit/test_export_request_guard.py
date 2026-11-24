"""The export page reads nothing but its slide and the hosts the slide CSP allows (C1).

``render_slide.cjs`` loads each slide from a ``file:`` URL in a browser context of its
own, and Node decides every request that context makes (``request_guard.cjs``, through
Playwright's routing), not the page. One line of slide script used to be enough to
navigate the export page to ``file:///etc/hosts`` and export that file's text, or a
directory's listing; on Databricks Apps any user who can edit a slide could have read
the container's files into a deck. So:

* a request is allowed only to the slide's own file URL, exactly, ``data:`` and
  ``blob:``, and the https hosts ``SLIDE_CSP`` allows for its kind of request: a script
  the ``script-src`` hosts, a stylesheet the ``style-src`` host, a font the
  ``font-src`` hosts. Everything else is aborted: any other ``file:``, ``http:``,
  loopback and link-local addresses, any other https host, WebSockets;
* a main-frame navigation away from the slide fails the slide, with a failure entry
  the routes report (``X-Huashu-Failures``); the deck carries nothing of the target,
  and the rest of the deck exports;
* a frame's navigation anywhere but the slide is aborted, and a popup is closed.

The hosts are ``SLIDE_CSP``'s own: ``src/utils/html_safety.py`` derives them
(``slide_csp_request_hosts``) and the wrapper passes them in the sidecar's stdin
payload (``allowedHosts``), so the CSP is their one source. A CSP source the guard
could not mirror stops no app from starting: ``html_safety`` still imports, warns once
naming the source, and leaves it out, so the guard aborts its requests and every other
host is as before.

Through the real engine, each way a slide's script could reach a local file, a
directory or a local server is tried, in a deck whose other slide is ordinary, once in
the document the routes build (``SLIDE_CSP`` in force) and once in a document without
it, where the guard holds alone: nothing any of them reaches is in the deck, as text or
as a picture's pixels, and the local server is never asked. A deck that loads Chart.js
from jsdelivr, Google Fonts and Tailwind still exports (``network``).
"""

from __future__ import annotations

import contextlib
import http.server
import importlib.util
import io
import json
import logging
import re
import socket
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

from src.services import pptx_from_html_huashu
from src.utils import html_safety
from tests.fixtures.export_snapshot_support import (
    CORPUS_DECK_CSS,
    LoggedExport,
    export_logged,
    node_json,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
    slide_summaries,
    slide_xml,
)

GUARD_MODULE = pptx_from_html_huashu.SIDECAR_DIR / "request_guard.cjs"

# Every slide here but the ordinary ones reaches for what the guard aborts.
pytestmark = pytest.mark.requests_blocked

# What the slides try to read. A word or a colour no ordinary slide holds, so finding one
# in the deck is finding what a slide read.
FILE_SECRET = "QuokkaFileSecret"
FRAME_SECRET = "QuokkaFrameSecret"
LISTING_SECRET = "QuokkaListingSecret"
SERVER_SECRET = "QuokkaServerSecret"
SECRETS = (FILE_SECRET, FRAME_SECRET, LISTING_SECRET, SERVER_SECRET)
# The ground of the secret page, picture and server page: a picture holding a pixel near
# it holds what a slide reached.
SECRET_COLOUR = (0x12, 0xAB, 0x34)
SECRET_COLOUR_TOLERANCE = 24
SECRET_PICTURE_PX = 40
# What every slide of the decks says, so a slide in the deck is told from a lost one.
ORDINARY_HEADING = "Quarterly results"
GUARDED_HEADING = "Guarded slide"

# The message a slide that navigates away fails with (render_slide.cjs).
NAVIGATED_AWAY = "navigated away from the slide"
# What the popup slide writes once its blank popup is closed, or when it never is.
POPUPS_CLOSED = "Popupsclosed"
POPUPS_OPEN = "Popupsopen"


@dataclass
class _ProbeServer:
    """A local HTTP server that answers every request with the secret page, and records each."""

    port: int
    hits: list[str] = field(default_factory=list)


class _ProbeHandler(http.server.BaseHTTPRequestHandler):
    server_record: _ProbeServer

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        self.server_record.hits.append(self.path)
        body = (
            f"<html><body style='margin:0;background:#12AB34'><p>{SERVER_SECRET}</p></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (the base's name)
        return


@contextlib.contextmanager
def _probe_server() -> Iterator[_ProbeServer]:
    record = _ProbeServer(port=0)
    handler = type("Handler", (_ProbeHandler,), {"server_record": record})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    record.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield record
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass(frozen=True)
class _Secrets:
    """Where the slides reach for: local files, a directory, and the probe server."""

    file_url: str
    page_url: str
    picture_url: str
    directory_url: str
    server: _ProbeServer


def _write_secrets(directory: Path, server: _ProbeServer) -> _Secrets:
    directory.mkdir(parents=True, exist_ok=True)
    text = directory / "secret.txt"
    text.write_text(f"{FILE_SECRET}\n", encoding="utf-8")
    page = directory / "secret.html"
    page.write_text(
        f"<html><body style='margin:0;background:#12AB34'><p>{FRAME_SECRET}</p></body></html>",
        encoding="utf-8",
    )
    picture = directory / "secret.png"
    Image.new("RGB", (SECRET_PICTURE_PX, SECRET_PICTURE_PX), SECRET_COLOUR).save(picture)
    listing = directory / "listing"
    listing.mkdir(exist_ok=True)
    (listing / f"{LISTING_SECRET}.txt").write_text("listed\n", encoding="utf-8")
    return _Secrets(
        file_url=text.as_uri(),
        page_url=page.as_uri(),
        picture_url=picture.as_uri(),
        directory_url=listing.as_uri() + "/",
        server=server,
    )


@dataclass(frozen=True)
class _Case:
    """One way a slide's script reaches outside its slide, and what the export does with it."""

    name: str
    # The slide's markup after its heading, given the secrets.
    markup: object
    # Whether the slide fails (it navigates away) or exports.
    fails: bool


def _read_into_out(expression: str) -> str:
    """Script that writes what ``expression`` (a promise of text) resolves to into #out."""
    return (
        "<script>(async () => { try { document.getElementById('out').textContent = "
        f"await {expression}; }} catch (e) {{ document.getElementById('out').textContent = "
        "'blocked'; } })();</script>"
    )


def _xhr(url: str) -> str:
    return (
        "new Promise((resolve, reject) => { const request = new XMLHttpRequest(); "
        f"request.open('GET', {json.dumps(url)}); request.onload = () => resolve(request.responseText); "
        "request.onerror = reject; request.send(); })"
    )


def _server(secrets: _Secrets, path: str) -> str:
    return f"http://127.0.0.1:{secrets.server.port}/{path}"


CASES = (
    _Case(
        "location-file",
        lambda s: f"<script>location.href = {json.dumps(s.file_url)};</script>",
        fails=True,
    ),
    _Case(
        "location-directory",
        lambda s: f"<script>location.href = {json.dumps(s.directory_url)};</script>",
        fails=True,
    ),
    _Case(
        "location-loopback",
        lambda s: f"<script>location.href = {json.dumps(_server(s, 'location'))};</script>",
        fails=True,
    ),
    _Case(
        "meta-refresh",
        lambda s: f'<meta http-equiv="refresh" content="0;url={s.file_url}">',
        fails=True,
    ),
    _Case(
        "blob-navigation",
        lambda s: (
            "<script>setTimeout(() => { location.href = URL.createObjectURL(new Blob("
            "['<p>blob page</p>'], { type: 'text/html' })); }, 0);</script>"
        ),
        fails=True,
    ),
    _Case(
        "frame-file",
        lambda s: f'<iframe src="{s.page_url}" width="400" height="200"></iframe>',
        fails=False,
    ),
    _Case(
        # A background image is captured: a local one would be drawn into the picture.
        "background-file",
        lambda s: (
            f'<div style="width: 200px; height: 100px; background-image: url({s.picture_url});">'
            "</div>"
        ),
        fails=False,
    ),
    _Case(
        "fetch-file",
        lambda s: _read_into_out(f"(await fetch({json.dumps(s.file_url)})).text()"),
        fails=False,
    ),
    _Case(
        "fetch-loopback",
        lambda s: _read_into_out(f"(await fetch({json.dumps(_server(s, 'fetch'))})).text()"),
        fails=False,
    ),
    _Case("xhr-file", lambda s: _read_into_out(_xhr(s.file_url)), fails=False),
    _Case("xhr-loopback", lambda s: _read_into_out(_xhr(_server(s, "xhr"))), fails=False),
    _Case(
        "websocket-loopback",
        lambda s: (
            f"<script>new WebSocket({json.dumps(_server(s, 'socket').replace('http:', 'ws:'))});"
            "</script>"
        ),
        fails=False,
    ),
    _Case(
        # The slide reads whether its own blank popup was closed, and writes it down: the
        # deck shows POPUPS_CLOSED once the guard has closed it.
        "window-open",
        lambda s: (
            f"<script>window.open({json.dumps(_server(s, 'popup'))}); "
            f"window.open({json.dumps(s.file_url)}); const blank = window.open('about:blank'); "
            "const out = document.getElementById('out'); const started = Date.now(); "
            "const poll = setInterval(() => { if (blank && blank.closed) { "
            f"out.textContent = {json.dumps(POPUPS_CLOSED)}; clearInterval(poll); }} "
            f"else if (Date.now() - started > 3000) {{ out.textContent = {json.dumps(POPUPS_OPEN)}; "
            "clearInterval(poll); } }, 20);</script>"
        ),
        fails=False,
    ),
)
CASE_NAMES = [case.name for case in CASES]


def _body(case: _Case, secrets: _Secrets) -> str:
    return (
        f'<div class="slide"><h1>{GUARDED_HEADING} {case.name}</h1>'
        f'<p id="out">nothing read</p>{case.markup(secrets)}</div>'
    )


ORDINARY_BODY = f'<div class="slide"><h1>{ORDINARY_HEADING}</h1><p>Revenue grew 12%.</p></div>'

# A document without the slide CSP: what reaches the sidecar is the caller's to build, so
# the guard holds whatever the document says.
BARE_DOCUMENT = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>html, body {{ width: '
    "1280px; height: 720px; margin: 0; overflow: hidden; }}</style></head><body>{body}</body></html>"
)

VARIANTS = ("with-csp", "without-csp")


def _document(variant: str, body: str, position: int) -> str:
    if variant == "with-csp":
        return slide_document(body, slide_id=f"guard-{position}")
    return BARE_DOCUMENT.format(body=body)


@dataclass(frozen=True)
class _GuardedDeck:
    logged: LoggedExport
    secrets: _Secrets
    # The deck's slide index of each case that exports.
    slide_of: dict[str, int]

    def failure_of(self, name: str) -> dict | None:
        position = CASE_NAMES.index(name) + 1
        return next((f for f in self.logged.failures if f["slide_index"] == position), None)

    def summary_of(self, name: str) -> dict:
        return slide_summaries(self.logged.stderr)[self.slide_of[name]]


def _export_guarded(variant: str, secrets: _Secrets, monkeypatch: pytest.MonkeyPatch) -> _GuardedDeck:
    bodies = [ORDINARY_BODY, *(_body(case, secrets) for case in CASES)]
    documents = [_document(variant, body, position) for position, body in enumerate(bodies)]
    logged = export_logged(documents, monkeypatch=monkeypatch)
    slide_of = {}
    exported = 1  # the ordinary slide is slide 0
    for case in CASES:
        if not case.fails:
            slide_of[case.name] = exported
            exported += 1
    return _GuardedDeck(logged=logged, secrets=secrets, slide_of=slide_of)


@pytest.fixture(scope="module")
def guarded_decks(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, _GuardedDeck]]:
    with _probe_server() as server, pytest.MonkeyPatch.context() as monkeypatch:
        secrets = _write_secrets(tmp_path_factory.mktemp("secrets"), server)
        yield {variant: _export_guarded(variant, secrets, monkeypatch) for variant in VARIANTS}


def _deck_parts_text(pptx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(pptx)) as deck:
        return "".join(
            deck.read(name).decode("utf-8", errors="replace")
            for name in deck.namelist()
            if name.endswith(".xml") or name.endswith(".rels")
        )


def _pictures(pptx: bytes) -> dict[str, Image.Image]:
    with zipfile.ZipFile(io.BytesIO(pptx)) as deck:
        return {
            name: Image.open(io.BytesIO(deck.read(name))).convert("RGBA")
            for name in deck.namelist()
            if name.startswith("ppt/media/") and name.lower().endswith(".png")
        }


def _holds_secret_colour(picture: Image.Image) -> bool:
    for red, green, blue, alpha in picture.getdata():
        if alpha and all(
            abs(channel - secret) <= SECRET_COLOUR_TOLERANCE
            for channel, secret in zip((red, green, blue), SECRET_COLOUR)
        ):
            return True
    return False


@pytest.mark.slow
@requires_huashu_sidecar
@pytest.mark.parametrize("variant", VARIANTS)
class TestNothingOutsideTheSlideReachesTheDeck:
    def test_the_deck_is_written_with_the_ordinary_slide(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str
    ) -> None:
        deck = guarded_decks[variant]
        assert deck.logged.pptx, f"no deck: {deck.logged.failures}"
        assert ORDINARY_HEADING in "".join(
            slide_xml(deck.logged.pptx, 0).itertext()
        ), "the ordinary slide is not the deck's first"

    def test_no_secret_is_in_the_deck(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str
    ) -> None:
        text = _deck_parts_text(guarded_decks[variant].logged.pptx)
        found = [secret for secret in SECRETS if secret in text]
        assert not found, f"the deck holds what a slide read: {found}"

    def test_no_picture_holds_the_secret_page_or_picture(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str
    ) -> None:
        pictures = _pictures(guarded_decks[variant].logged.pptx)
        drawn = sorted(name for name, picture in pictures.items() if _holds_secret_colour(picture))
        assert not drawn, f"these pictures hold the secret ground #12AB34: {drawn}"

    def test_the_local_server_is_never_asked(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str
    ) -> None:
        assert guarded_decks[variant].secrets.server.hits == [], (
            f"slides reached the local server: {guarded_decks[variant].secrets.server.hits}"
        )

    @pytest.mark.parametrize("name", [case.name for case in CASES if case.fails])
    def test_a_slide_that_navigates_away_fails_alone(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str, name: str
    ) -> None:
        failure = guarded_decks[variant].failure_of(name)
        assert failure is not None, f"{name} exported: {guarded_decks[variant].logged.failures}"
        assert NAVIGATED_AWAY in failure["error"], failure

    @pytest.mark.parametrize("name", [case.name for case in CASES if not case.fails])
    def test_a_slide_whose_reads_are_aborted_still_exports(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str, name: str
    ) -> None:
        deck = guarded_decks[variant]
        assert deck.failure_of(name) is None, deck.failure_of(name)
        text = "".join(slide_xml(deck.logged.pptx, deck.slide_of[name]).itertext())
        assert f"{GUARDED_HEADING} {name}" in text, f"slide {deck.slide_of[name]} is not {name}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheGuardCountsWhatItStops:
    """Without the CSP, every request a slide makes outside it reaches the guard, which counts it."""

    @pytest.mark.parametrize(
        "name",
        [
            case.name
            for case in CASES
            if not case.fails and case.name not in {"window-open"}
        ],
    )
    def test_each_slide_has_its_requests_blocked(
        self, guarded_decks: dict[str, _GuardedDeck], name: str
    ) -> None:
        summary = guarded_decks["without-csp"].summary_of(name)
        assert summary["blockedRequests"] >= 1, summary

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_the_popups_are_closed(
        self, guarded_decks: dict[str, _GuardedDeck], variant: str
    ) -> None:
        deck = guarded_decks[variant]
        summary = deck.summary_of("window-open")
        assert summary["closedPopups"] == 3, summary
        text = "".join(slide_xml(deck.logged.pptx, deck.slide_of["window-open"]).itertext())
        assert POPUPS_CLOSED in text, f"the slide's blank popup stayed open: {text!r}"

    def test_an_ordinary_slide_has_nothing_blocked(
        self, guarded_decks: dict[str, _GuardedDeck]
    ) -> None:
        (ordinary, *_) = slide_summaries(guarded_decks["with-csp"].logged.stderr)
        assert (ordinary["blockedRequests"], ordinary["closedPopups"]) == (0, 0), ordinary


# ---------------------------------------------------------------------------
# The hosts: SLIDE_CSP's, one source
# ---------------------------------------------------------------------------

_CSP_CONTENT = re.compile(r'content="([^"]*)"')
# The fetch directives whose hosts the guard allows, and the request type each governs
# (Playwright's resourceType()).
_DIRECTIVE_REQUEST_TYPES = {"script-src": "script", "style-src": "stylesheet", "font-src": "font"}


def _https_hosts_of_meta() -> dict[str, list[str]]:
    """Read independently of html_safety's parser: each directive's https hosts in the meta tag."""
    (content,) = _CSP_CONTENT.findall(html_safety.SLIDE_CSP_META)
    hosts: dict[str, list[str]] = {}
    for directive in filter(str.strip, content.split(";")):
        name, *sources = directive.split()
        https =[source.removeprefix("https://") for source in sources if source.startswith("https://")]
        if https:
            assert name in _DIRECTIVE_REQUEST_TYPES, f"{name} names https hosts the guard maps to no request type"
            hosts[_DIRECTIVE_REQUEST_TYPES[name]] = https
    return hosts


HTML_SAFETY_SOURCE = Path(html_safety.__file__)


def _import_html_safety(directory: Path, *edits: tuple[str, str]) -> ModuleType:
    """``src/utils/html_safety.py`` imported afresh, as an app's startup imports it.

    From a copy in ``directory`` where each ``(written, rewritten)`` of ``edits`` has the
    text the module writes once, ``written``, read ``rewritten``; with no edits the copy is
    the module as it is. The copy runs under the module's own name, so it logs where the
    module logs, and neither the module the tests import nor ``sys.modules`` is touched.
    """
    source = HTML_SAFETY_SOURCE.read_text(encoding="utf-8")
    for written, rewritten in edits:
        assert source.count(written) == 1, (
            f"fixture drift: html_safety.py writes {written!r} "
            f"{source.count(written)} times, not once"
        )
        source = source.replace(written, rewritten)
    copy = directory / "html_safety.py"
    copy.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(html_safety.__name__, copy)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _warnings_of(caplog: pytest.LogCaptureFixture) -> list[str]:
    """What html_safety logged at warning level or above, message by message."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == html_safety.__name__ and record.levelno >= logging.WARNING
    ]


class TestTheHostsAreTheCsps:
    def test_html_safety_derives_each_request_types_hosts_from_the_csp(self) -> None:
        assert {
            kind: list(hosts) for kind, hosts in html_safety.SLIDE_CSP_REQUEST_HOSTS.items()
        } == _https_hosts_of_meta()

    def test_the_hosts_are_the_cdns_the_slides_load(self) -> None:
        """Fixture drift guard: what the CSP allows today, read from the meta tag."""
        assert _https_hosts_of_meta() == {
            "script": ["cdn.jsdelivr.net", "cdn.tailwindcss.com"],
            "stylesheet": ["fonts.googleapis.com"],
            "font": ["cdn.jsdelivr.net", "fonts.gstatic.com"],
        }

    @pytest.mark.parametrize(
        ("csp", "source"),
        [
            (
                "default-src 'none'; img-src data: https://images.example.com;",
                "img-src https://images.example.com",
            ),
            (
                "default-src 'none'; script-src https://cdn.example.com/path/;",
                "script-src https://cdn.example.com/path/",
            ),
            (
                "default-src 'none'; script-src https://*.example.com;",
                "script-src https://*.example.com",
            ),
            (
                "default-src 'none'; script-src https://cdn.example.com:8443;",
                "script-src https://cdn.example.com:8443",
            ),
        ],
        ids=["an-image-host", "a-host-with-a-path", "a-wildcard-host", "a-host-with-a-port"],
    )
    def test_a_source_the_guard_cannot_mirror_is_left_out_and_named(
        self, csp: str, source: str
    ) -> None:
        """No host of it is allowed, for any request type, and it is named as unmirrored."""
        assert html_safety.slide_csp_request_hosts(csp) == ({}, (source,))

    def test_todays_csp_imports_with_todays_hosts_and_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Parity: html_safety imported as it is written gives the meta tag's hosts, unwarned."""
        with caplog.at_level(logging.WARNING, logger=html_safety.__name__):
            imported = _import_html_safety(tmp_path)

        assert {
            kind: list(hosts) for kind, hosts in imported.SLIDE_CSP_REQUEST_HOSTS.items()
        } == _https_hosts_of_meta()
        assert imported.SLIDE_CSP_UNMIRRORED_SOURCES == ()
        assert _warnings_of(caplog) == []

    def test_the_wrapper_gives_the_sidecar_the_csps_hosts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        production_request_hosts: dict[str, tuple[str, ...]],
    ) -> None:
        """An app's export gives the sidecar the wrapper's own hosts, which are the CSP's."""
        assert production_request_hosts is html_safety.SLIDE_CSP_REQUEST_HOSTS
        payloads: list[dict] = []

        def run(command: list[str], *, input: bytes, timeout: float, **_: object):  # noqa: A002
            payloads.append(json.loads(input))
            Path(command[-1]).write_bytes(b"deck")
            return pptx_from_html_huashu.subprocess.CompletedProcess(
                command, 0, b"", b'__HUASHU_RESULT__ {"failed": []}\n'
            )

        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", run)
        pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])

        (payload,) = payloads
        assert payload["allowedHosts"] == {
            kind: list(hosts) for kind, hosts in html_safety.SLIDE_CSP_REQUEST_HOSTS.items()
        }


# ---------------------------------------------------------------------------
# The verdicts, read from request_guard.cjs itself
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# WebRTC: no peer connection reaches the network
# ---------------------------------------------------------------------------

# Playwright's routing sees no WebRTC traffic: a peer connection's ICE gathering
# sends STUN over UDP and opens TURN over TCP to whatever its servers name, a
# loopback or internal address included. A slide that tries one, in its own realm,
# under the prefixed name, in a fresh iframe's realm and in a popup's.
PEER_HEADING = "Peer slide"
PEER_REALMS = ("main", "prefixed", "iframe", "popup")


def _peer_body(udp_port: int, tcp_port: int) -> str:
    servers = json.dumps(
        [
            {"urls": f"stun:127.0.0.1:{udp_port}"},
            {"urls": f"turn:127.0.0.1:{tcp_port}?transport=tcp", "username": "u", "credential": "c"},
        ]
    )
    return (
        f'<div class="slide"><h1>{PEER_HEADING}</h1><script>(async function () {{'
        "  async function attempt(Ctor) {"
        "    if (typeof Ctor !== 'function') return;"
        f"    const pc = new Ctor({{ iceServers: {servers} }});"
        "    pc.createDataChannel('x');"
        "    await pc.setLocalDescription(await pc.createOffer());"
        "  }"
        "  const frame = document.createElement('iframe');"
        "  document.body.appendChild(frame);"
        "  const popup = window.open('about:blank');"
        "  const realms = [window.RTCPeerConnection, window.webkitRTCPeerConnection,"
        "    frame.contentWindow.RTCPeerConnection, popup && popup.RTCPeerConnection];"
        "  for (const Ctor of realms) { try { await attempt(Ctor); } catch (error) {} }"
        "})();</script></div>"
    )


@dataclass
class _PeerListeners:
    """A local UDP socket (a STUN server's) and TCP listener (a TURN server's), counting what reaches them."""

    udp_port: int
    tcp_port: int
    datagrams: int = 0
    connections: int = 0


@contextlib.contextmanager
def _peer_listeners() -> Iterator[_PeerListeners]:
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(0.2)
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(16)
    tcp.settimeout(0.2)
    record = _PeerListeners(udp.getsockname()[1], tcp.getsockname()[1])
    stopping = threading.Event()

    def receive() -> None:
        while not stopping.is_set():
            with contextlib.suppress(OSError):
                udp.recvfrom(4096)
                record.datagrams += 1

    def accept() -> None:
        while not stopping.is_set():
            with contextlib.suppress(OSError):
                connection, _ = tcp.accept()
                record.connections += 1
                connection.close()

    threads = [threading.Thread(target=target, daemon=True) for target in (receive, accept)]
    for thread in threads:
        thread.start()
    try:
        yield record
    finally:
        stopping.set()
        for thread in threads:
            thread.join(timeout=5)
        udp.close()
        tcp.close()


# The same document in a plain browser of the sidecar's own build and channel, with
# none of the export's settings: what a page reaches there (a fixture-drift guard).
PLAIN_PAGE_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch(process.platform === 'darwin' ? { channel: 'chrome' } : {});
  try {
    const page = await browser.newPage();
    await page.goto(%(url)s);
    await page.waitForTimeout(2000);
  } finally {
    await browser.close();
  }
  console.log('null');
})();
"""


@pytest.mark.slow
@requires_huashu_sidecar
class TestNoPeerConnectionReachesTheNetwork:
    def test_a_slide_that_opens_peer_connections_reaches_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Peer connections to a local STUN (UDP) and TURN (TCP) listener reach neither.

        In a plain browser the slide's peer connections reach both listeners
        (checked first). Exported, the slide's every realm (its own, a fresh
        iframe's, a popup's) has no peer-connection constructor, which an init
        script takes away before any of the page's own script runs, and the
        browser sends no UDP but through a proxy, which it has none of (the
        launch's IP-handling policy, for Chrome and Chromium alike). Neither
        listener is reached, and the slide exports.
        """
        with _peer_listeners() as plain:
            document = tmp_path / "peer.html"
            document.write_text(
                slide_document(_peer_body(plain.udp_port, plain.tcp_port)), encoding="utf-8"
            )
            node_json(PLAIN_PAGE_SCRIPT % {"url": json.dumps(document.as_uri())})
        assert plain.datagrams > 0 and plain.connections > 0, (
            f"fixture drift: in a plain browser the slide reaches {plain.datagrams} datagram(s) "
            f"and {plain.connections} connection(s)"
        )

        with _peer_listeners() as exported:
            logged = export_logged(
                [slide_document(_peer_body(exported.udp_port, exported.tcp_port))],
                monkeypatch=monkeypatch,
            )
        assert logged.failures == [], logged.failures
        assert PEER_HEADING in "".join(slide_xml(logged.pptx, 0).itertext())
        assert (exported.datagrams, exported.connections) == (0, 0), (
            f"the exported slide reached {exported.datagrams} datagram(s) and "
            f"{exported.connections} connection(s)"
        )


SLIDE_URL = "file:///tmp/huashu-deck-x/slide-000.html"
CSP_HOSTS = {
    "script": ["cdn.jsdelivr.net", "cdn.tailwindcss.com"],
    "stylesheet": ["fonts.googleapis.com"],
    "font": ["cdn.jsdelivr.net", "fonts.gstatic.com"],
}
JSDELIVR_SCRIPT = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
# (url, resourceType, navigation, mainFrame) -> verdict.
VERDICTS = [
    ((SLIDE_URL, "document", True, True), "allow"),
    ((SLIDE_URL + "#part", "document", True, True), "allow"),
    ((SLIDE_URL + "?again", "document", True, True), "leave"),
    (("file:///etc/hosts", "document", True, True), "leave"),
    (("file:///etc/", "document", True, True), "leave"),
    (("http://127.0.0.1:8000/", "document", True, True), "leave"),
    (("https://cdn.jsdelivr.net/npm/x", "document", True, True), "leave"),
    (("file:///etc/hosts", "document", True, False), "block"),
    (("https://cdn.jsdelivr.net/npm/x", "document", True, False), "block"),
    ((SLIDE_URL, "document", True, False), "allow"),
    ((JSDELIVR_SCRIPT, "script", False, True), "allow"),
    (("https://cdn.tailwindcss.com/", "script", False, True), "allow"),
    (("https://fonts.googleapis.com/css2?family=DM+Sans", "stylesheet", False, True), "allow"),
    (("https://fonts.gstatic.com/s/dmsans/v17/x.woff2", "font", False, True), "allow"),
    (("https://cdn.jsdelivr.net/npm/@fontsource/x.woff2", "font", False, True), "allow"),
    # A host the CSP allows for one kind of request is no host for another.
    (("https://fonts.gstatic.com/s/x.js", "script", False, True), "block"),
    (("https://cdn.jsdelivr.net/npm/x.css", "stylesheet", False, True), "block"),
    ((JSDELIVR_SCRIPT, "fetch", False, True), "block"),
    ((JSDELIVR_SCRIPT, "xhr", False, True), "block"),
    ((JSDELIVR_SCRIPT, "image", False, True), "block"),
    # Exactly the host, on https's own port, without credentials.
    (("http://cdn.jsdelivr.net/npm/x.js", "script", False, True), "block"),
    (("https://cdn.jsdelivr.net:8443/npm/x.js", "script", False, True), "block"),
    (("https://user:pass@cdn.jsdelivr.net/npm/x.js", "script", False, True), "block"),
    (("https://cdn.jsdelivr.net.example.com/x.js", "script", False, True), "block"),
    (("https://evil.cdn.jsdelivr.net/x.js", "script", False, True), "block"),
    (("https://CDN.JSDELIVR.NET/npm/x.js", "script", False, True), "allow"),
    (("file:///etc/hosts", "fetch", False, True), "block"),
    (("file:///etc/hosts", "image", False, True), "block"),
    (("http://127.0.0.1:9/", "fetch", False, True), "block"),
    (("http://[::1]:9/", "fetch", False, True), "block"),
    (("http://169.254.169.254/latest/meta-data/", "xhr", False, True), "block"),
    (("http://localhost:9/", "script", False, True), "block"),
    (("chrome://version/", "other", False, True), "block"),
    (("data:image/png;base64,AAAA", "image", False, True), "allow"),
    (("blob:null/0a1b2c", "image", False, True), "allow"),
    (("not a url", "fetch", False, True), "block"),
]


def _guard_verdicts(hosts: object, requests: list[tuple[str, str, bool, bool]]) -> list[str]:
    """request_guard.cjs's verdict on each (url, resourceType, navigation, mainFrame) request.

    ``hosts`` is read as the stdin payload's ``allowedHosts`` is (``requestHostsOf``).
    """
    shaped = [
        {"url": url, "resourceType": kind, "navigation": navigation, "mainFrame": main}
        for url, kind, navigation, main in requests
    ]
    return node_json(
        f"const guard = require({json.dumps(str(GUARD_MODULE))});"
        f"const policy = {{ slideUrl: {json.dumps(SLIDE_URL)}, "
        f"hosts: guard.requestHostsOf({json.dumps(hosts)}).hosts }};"
        f"console.log(JSON.stringify({json.dumps(shaped)}.map("
        "(request) => guard.requestVerdict(request, policy))));"
    )


@requires_node
class TestTheVerdicts:
    def _verdicts(self, hosts: object) -> list[str]:
        return _guard_verdicts(hosts, [request for request, _ in VERDICTS])

    def test_each_request_gets_its_verdict(self) -> None:
        verdicts = self._verdicts(CSP_HOSTS)
        wrong = [
            (request, expected, verdict)
            for (request, expected), verdict in zip(VERDICTS, verdicts)
            if verdict != expected
        ]
        assert not wrong, wrong

    def test_without_hosts_no_https_request_is_allowed(self) -> None:
        verdicts = self._verdicts(None)
        allowed_https = [
            request
            for (request, _), verdict in zip(VERDICTS, verdicts)
            if verdict == "allow" and request[0].lower().startswith("https:")
        ]
        assert allowed_https == []

    @pytest.mark.parametrize(
        "hosts",
        [
            {"script": ["cdn.jsdelivr.net/npm"]},
            {"script": ["*.jsdelivr.net"]},
            {"script": ["cdn.jsdelivr.net:443"]},
            {"script": "cdn.jsdelivr.net"},
            {"no-such-type": ["cdn.jsdelivr.net"]},
            ["cdn.jsdelivr.net"],
        ],
    )
    def test_a_host_list_entry_that_is_not_a_host_name_is_ignored(self, hosts: object) -> None:
        read = node_json(
            f"const guard = require({json.dumps(str(GUARD_MODULE))});"
            f"const read = guard.requestHostsOf({json.dumps(hosts)});"
            "console.log(JSON.stringify({ hosts: [...read.hosts].map(([kind, names]) => "
            "[kind, [...names]]), ignored: read.ignored }));"
        )
        assert read["hosts"] == [] and read["ignored"] >= 1, read

    def test_the_csps_hosts_are_all_kept(self) -> None:
        payload = {
            kind: list(hosts) for kind, hosts in html_safety.SLIDE_CSP_REQUEST_HOSTS.items()
        }
        read = node_json(
            f"const guard = require({json.dumps(str(GUARD_MODULE))});"
            f"const read = guard.requestHostsOf({json.dumps(payload)});"
            "console.log(JSON.stringify({ hosts: Object.fromEntries([...read.hosts].map("
            "([kind, names]) => [kind, [...names]])), ignored: read.ignored }));"
        )
        assert read == {"hosts": payload, "ignored": 0}


# ---------------------------------------------------------------------------
# A CSP source the guard cannot mirror stops no startup
# ---------------------------------------------------------------------------

# A source the guard cannot mirror, added to SLIDE_CSP where html_safety.py writes it: the
# text written there, that text with the source added, the source as html_safety names it,
# and a request (url, resourceType) that source alone allows.
UNMIRRORABLE_SOURCES = [
    pytest.param(
        '"img-src data:; "',
        '"img-src data: https:; "',
        "img-src https:",
        ("https://images.example.com/p.png", "image"),
        id="a-directive-the-guard-maps-to-no-request-type",
    ),
    pytest.param(
        'https://cdn.tailwindcss.com; "',
        'https://cdn.tailwindcss.com https://*.example.com; "',
        "script-src https://*.example.com",
        ("https://cdn.example.com/x.js", "script"),
        id="a-wildcard-host",
    ),
    pytest.param(
        'https://cdn.tailwindcss.com; "',
        'https://cdn.tailwindcss.com https://cdn.example.com/lib/; "',
        "script-src https://cdn.example.com/lib/",
        ("https://cdn.example.com/lib/x.js", "script"),
        id="a-host-with-a-path",
    ),
    pytest.param(
        'https://fonts.gstatic.com; "',
        'https://fonts.gstatic.com https://fonts.example.com:8443; "',
        "font-src https://fonts.example.com:8443",
        ("https://fonts.example.com:8443/x.woff2", "font"),
        id="a-host-with-a-port",
    ),
]


class TestASourceTheGuardCannotMirror:
    """A CSP edit such as ``img-src https:``: every app still starts, and only an export's
    requests to that source are aborted.

    ``html_safety`` is imported by the security-headers middleware, the agent and the
    streaming callback, so raising at its import used to stop the whole app, chat included.
    """

    @pytest.mark.parametrize(
        ("written", "rewritten", "source", "blocked_request"), UNMIRRORABLE_SOURCES
    )
    def test_html_safety_still_imports_and_warns_once_naming_it(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        written: str,
        rewritten: str,
        source: str,
        blocked_request: tuple[str, str],
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=html_safety.__name__):
            imported = _import_html_safety(tmp_path, (written, rewritten))

        warnings = _warnings_of(caplog)
        assert len(warnings) == 1 and source in warnings[0], warnings
        assert imported.SLIDE_CSP_UNMIRRORED_SOURCES == (source,)

    def test_several_are_named_in_one_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The image directive's source and the wildcard script host, in the CSP's order."""
        image, wildcard = (param.values for param in UNMIRRORABLE_SOURCES[:2])

        with caplog.at_level(logging.WARNING, logger=html_safety.__name__):
            imported = _import_html_safety(tmp_path, image[:2], wildcard[:2])

        sources = ("script-src https://*.example.com", "img-src https:")
        warnings = _warnings_of(caplog)
        assert len(warnings) == 1 and all(source in warnings[0] for source in sources), warnings
        assert imported.SLIDE_CSP_UNMIRRORED_SOURCES == sources

    @requires_node
    @pytest.mark.parametrize(
        ("written", "rewritten", "source", "blocked_request"), UNMIRRORABLE_SOURCES
    )
    def test_the_guard_aborts_its_requests_and_keeps_every_other_host(
        self,
        tmp_path: Path,
        written: str,
        rewritten: str,
        source: str,
        blocked_request: tuple[str, str],
    ) -> None:
        """Fails closed for that source alone: no host of it, and the CSP's others all kept."""
        imported = _import_html_safety(tmp_path, (written, rewritten))
        assert imported.SLIDE_CSP_REQUEST_HOSTS == html_safety.SLIDE_CSP_REQUEST_HOSTS
        # As the wrapper passes them in the stdin payload (allowedHosts).
        allowed_hosts = {
            kind: list(hosts) for kind, hosts in imported.SLIDE_CSP_REQUEST_HOSTS.items()
        }
        url, resource_type = blocked_request
        cdn_requests = [
            cdn_request
            for cdn_request, expected in VERDICTS
            if expected == "allow" and cdn_request[0].lower().startswith("https:")
        ]

        verdict, *cdn_verdicts = _guard_verdicts(
            allowed_hosts, [(url, resource_type, False, True), *cdn_requests]
        )

        assert verdict == "block", f"{source}: the guard lets {url} ({resource_type}) through"
        assert cdn_verdicts == ["allow"] * len(cdn_requests), list(zip(cdn_requests, cdn_verdicts))


# ---------------------------------------------------------------------------
# A real deck from the CSP's CDNs still exports
# ---------------------------------------------------------------------------

CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
TAILWIND = "https://cdn.tailwindcss.com"
NETWORK_CHART_SCRIPT = (
    "(function() { var el = document.getElementById('guardChart'); if (!el) return; "
    "new Chart(el, { type: 'bar', data: { labels: ['A', 'B'], datasets: [{ data: [3, 5], "
    "backgroundColor: '#FF5F46' }] }, options: { animation: false, responsive: false } }); })();"
)
NETWORK_BODY = (
    '<div class="slide"><h1 class="text-red-600">Revenue by region</h1>'
    '<canvas id="guardChart" width="400" height="200"></canvas></div>'
)
# Tailwind's text-red-600.
TAILWIND_RED = "DC2626"


def _cdns_reachable() -> bool:
    for host in ("cdn.jsdelivr.net", "fonts.googleapis.com", "cdn.tailwindcss.com"):
        try:
            with socket.create_connection((host, 443), timeout=3):
                pass
        except OSError:
            return False
    return True


@pytest.mark.slow
@pytest.mark.network
@requires_huashu_sidecar
class TestTheCspsCdnsStillLoad:
    def test_a_deck_with_chart_js_google_fonts_and_tailwind_exports(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not _cdns_reachable():
            pytest.skip("the slide CSP's CDN hosts cannot be reached from here")
        document = slide_document(
            NETWORK_BODY,
            css=CORPUS_DECK_CSS,
            scripts=NETWORK_CHART_SCRIPT,
            external_scripts=(CHART_JS, TAILWIND),
        )
        assert "fonts.googleapis.com" in document, "fixture drift: the deck CSS loads no webfont"

        logged = export_logged([document], monkeypatch=monkeypatch)

        assert logged.failures == [], logged.failures
        (summary,) = slide_summaries(logged.stderr)
        assert (summary["blockedRequests"], summary["captureFailures"]) == (0, 0), summary
        assert summary["pictures"] >= 1, f"the chart was not captured: {summary}"
        xml = slide_xml(logged.pptx, 0)
        namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        typefaces = {font.get("typeface") for font in xml.iterfind(".//a:latin", namespace)}
        assert any(face and face.startswith("DM Sans") for face in typefaces), typefaces
        colours = {colour.get("val") for colour in xml.iterfind(".//a:rPr//a:srgbClr", namespace)}
        assert TAILWIND_RED in colours, f"Tailwind's class did not apply: {colours}"


def test_the_secret_colour_is_found_where_it_is() -> None:
    """Guard on the pixel oracle: a picture of the secret ground is found, a white one is not."""
    assert _holds_secret_colour(Image.new("RGBA", (4, 4), (*SECRET_COLOUR, 255)))
    assert not _holds_secret_colour(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
