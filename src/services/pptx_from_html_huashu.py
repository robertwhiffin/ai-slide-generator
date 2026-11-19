"""Local-only Tellr → huashu-design pipeline bridge.

Spawns the ``services/pptx-emit-huashu/emit_deck.mjs`` Node sidecar, which
runs alchaincyf/huashu-design's ``html2pptx.js`` (Playwright + pptxgenjs
server-side) over each slide's complete HTML doc and writes a single
editable .pptx.

Why local-only: huashu's pipeline needs Chromium via Playwright. Databricks
Apps containers run as non-root with limited memory and ship without Chromium.
Adopting this on FEVM would require a deeper infra change than this round
covers. ``is_available()`` returns False outside the local-dev gate.

Renderer target. ``build_pptx_huashu(..., target=...)`` names the app the deck
is written for: ``"pptx"`` (the default) for PowerPoint and the .pptx download,
``"gslides"`` for the Google Slides conversion. The two place a few constructs
apart, and only those are written differently, all on lines that hold a
superscript or subscript run (task-11 rulings R11g, R11i and R11j and
findings r4, measured in both apps; ``scripts/export_fidelity/CALIBRATION.md``
A2, A4 and A5):

* a script run's size. PowerPoint shrinks a script run and places its line by
  its other runs, so the run is written enlarged and PowerPoint draws it at the
  browser's size; Google Slides sizes the whole line by that enlarged size and
  draws it low, so for it the run is capped at its line's size (its glyph then
  drawn at 0.8 of the browser's, the trade-off R11i accepts);
* for PowerPoint alone, a word joiner after a script run that ends its line,
  which PowerPoint would otherwise size the line by;
* the growth of a later line the browser set further down than its spacing
  (a raised script run's line box, a larger run's own line height, the
  block's strut), which both apps space by its paragraph alone: written as
  that line's space before, in both decks but for a line within its paragraph
  that holds a script run, which Google Slides grows by the run's written
  size instead (R11g; a later paragraph's first line holding one takes the
  space before, R11j).

So a deck with no script run is the same for both targets.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

def _resolve_sidecar_dir() -> Path:
    # Dev / editable install: services/ lives at the repo root.
    dev = Path(__file__).resolve().parents[2] / "services" / "pptx-emit-huashu"
    if dev.exists():
        return dev
    # Wheel install: setup.py copies the sidecar under databricks_tellr_app/_assets/sidecars/.
    try:
        import databricks_tellr_app  # type: ignore
        wheel = Path(databricks_tellr_app.__file__).resolve().parent / "_assets" / "sidecars" / "pptx-emit-huashu"
        if wheel.exists():
            return wheel
    except Exception:
        pass
    return dev


SIDECAR_DIR = _resolve_sidecar_dir()
SIDECAR_SCRIPT = SIDECAR_DIR / "emit_deck.mjs"
SIDECAR_SYS_LIBS_DIR = SIDECAR_DIR / "sys-libs"
SIDECAR_TIMEOUT_SECONDS = 180  # huashu opens chromium per-slide; slower than pptx-emit

# SDR-4437 F-CR-35: the only environment keys the node/Chromium child gets.
# No DATABRICKS_*, no Fernet key, no Lakebase creds. HOME stays real (unlike
# the converter jail's scrubbed env): Playwright finds Chromium under
# ~/.cache/ms-playwright. Proxy and CA settings stay so the page can still
# load Chart.js from its CDN.
_SIDECAR_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "LD_LIBRARY_PATH",
    "PLAYWRIGHT_BROWSERS_PATH",
    "XDG_CACHE_HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
)


def sidecar_subprocess_env() -> dict[str, str]:
    """Build the env dict for any node subprocess that ends up spawning
    Chromium: an allowlist of the app's environment (see
    ``_SIDECAR_ENV_ALLOWLIST``), never a copy of it. Prepends
    ``services/pptx-emit-huashu/sys-libs/`` onto
    ``LD_LIBRARY_PATH`` if the directory exists, so Chromium can find the
    bundled libnspr4/libnss3/etc. on Databricks Apps where the host glibc-
    next runtime libs aren't installed. Scoping it here (not as a global
    env in app.yaml) prevents the Python process from accidentally loading
    incompatible libs from the bundle.
    """
    env = {k: os.environ[k] for k in _SIDECAR_ENV_ALLOWLIST if k in os.environ}
    if SIDECAR_SYS_LIBS_DIR.exists():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{SIDECAR_SYS_LIBS_DIR}:{existing}" if existing else str(SIDECAR_SYS_LIBS_DIR)
        )
    return env


class HuashuExportError(RuntimeError):
    """Raised when the huashu sidecar cannot run at all (setup, timeout)."""


def _local_dev_gate() -> bool:
    """True iff this process is running on a developer machine, not Apps.

    Hard rules (in priority order):
      - HUASHU_PIPELINE_ENABLED=1 explicit opt-in. This is what
        app.yaml.darwish sets so the route works on Databricks Apps
        (Chromium installed during boot via `npx playwright install
        chromium`). Wins over the Apps-name check.
      - DATABRICKS_APP_NAME being set without the opt-in means a
        deployed Apps container that hasn't installed Chromium —
        keep disabled to fail fast.
      - Otherwise allow if ENVIRONMENT=development.
    """
    if os.environ.get("HUASHU_PIPELINE_ENABLED") == "1":
        return True
    if os.environ.get("DATABRICKS_APP_NAME"):
        return False
    return os.environ.get("ENVIRONMENT") == "development"


def _has_chromium() -> bool:
    """Cheap heuristic for whether `npx playwright install chromium` ran.

    The browser binary lives under ``~/Library/Caches/ms-playwright/``
    (macOS) or ``~/.cache/ms-playwright/`` (Linux). We don't enumerate the
    chrome-mac.app subtree; the cache directory's existence is enough as
    a "did the user run the install step" proof.
    """
    home = Path.home()
    for candidate in (
        home / "Library" / "Caches" / "ms-playwright",
        home / ".cache" / "ms-playwright",
    ):
        if candidate.exists() and any(candidate.iterdir()):
            return True
    return False


def is_available() -> bool:
    """Whether the huashu pipeline is ready to use.

    Returns False on Databricks Apps, when node isn't on PATH, when the
    sidecar files aren't present, or when Chromium hasn't been installed.
    """
    if not _local_dev_gate():
        return False
    if shutil.which("node") is None:
        return False
    if not SIDECAR_SCRIPT.exists():
        return False
    if not (SIDECAR_DIR / "node_modules" / "playwright").exists():
        return False
    if not (SIDECAR_DIR / "node_modules" / "pptxgenjs").exists():
        return False
    if not _has_chromium():
        return False
    return True


RenderTarget = Literal["pptx", "gslides"]
RENDER_TARGETS: tuple[RenderTarget, ...] = ("pptx", "gslides")


def build_pptx_huashu(
    title: str,
    slides_html: list[dict[str, Any]],
    *,
    bypass_validation: bool = False,
    target: RenderTarget = "pptx",
) -> tuple[bytes, list[dict[str, Any]]]:
    """Run huashu's pipeline over each slide's HTML, return (pptx_bytes, failures).

    ``slides_html`` is a list of ``{ "html": "<full doc string>", "notes": "..." }``.
    The HTML string must be a complete standalone document with body sized
    to 1280×720 px (= 13.333"×7.5"); the caller assembles this — see
    ``src/api/routes/export.py::build_slide_html``.

    ``bypass_validation``: when True, huashu's design-rule validation
    (overflow > 100px, text-near-bottom-edge, layout dimension mismatch,
    other authoring quality checks) becomes a per-slide console warning
    instead of a throw. Slides that violate the rules still end up in the
    output PPTX. Used by the Google Slides Drive route to guarantee every
    slide ships, with the trade-off that some slides may render imperfectly.

    ``target``: the app the deck is written for, ``"pptx"`` (PowerPoint, the
    default) or ``"gslides"`` (the Google Slides conversion); see the module
    docstring. Any other value raises ``ValueError``.

    Returns a 2-tuple:
      * pptx_bytes — the .pptx as bytes, even if some slides failed
        (empty if ALL slides failed; the caller should handle that).
      * failures  — list of ``{ slide_index, error }`` with one entry per
        slide huashu rejected. Empty list = clean run.
    """
    if target not in RENDER_TARGETS:
        raise ValueError(f"unknown render target {target!r}: expected one of {RENDER_TARGETS}")
    if not is_available():
        raise HuashuExportError(
            "huashu pipeline not available (local dev only; needs node, "
            "playwright, sharp, and `npx playwright install chromium` to "
            "have run in services/pptx-emit-huashu/)"
        )

    payload_bytes = json.dumps({
        "title": title,
        "slides": slides_html,
        "bypassValidation": bypass_validation,
        # The sidecar's per-slide converter: "legacy" (html2pptx.js) or
        # "snapshot" (render_slide.cjs). Read here and sent in the payload, so the
        # sidecar env allowlist stays as it is.
        "engine": os.environ.get("TELLR_EXPORT_ENGINE", "legacy"),
        # The app the deck is written for (module docstring, Renderer target).
        "target": target,
    }).encode("utf-8")

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.pptx"
        cmd = ["node", str(SIDECAR_SCRIPT), str(out_path)]
        logger.info(
            "spawn huashu sidecar: %s (slides=%d, payload=%d bytes)",
            " ".join(cmd), len(slides_html), len(payload_bytes),
        )
        try:
            result = subprocess.run(
                cmd,
                input=payload_bytes,
                capture_output=True,
                timeout=SIDECAR_TIMEOUT_SECONDS,
                check=False,
                env=sidecar_subprocess_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise HuashuExportError(
                f"huashu sidecar timed out after {SIDECAR_TIMEOUT_SECONDS}s"
            ) from e

        stderr = result.stderr.decode("utf-8", errors="replace")
        # Echo informational stderr lines into our log so the user sees
        # per-slide progress. The result line is parsed separately.
        for line in stderr.splitlines():
            if line.strip() and not line.startswith("__HUASHU_RESULT__"):
                print(f"[huashu-emit] {line}", file=sys.stderr, flush=True)

        # Parse the sentinel line for structured failure data. emit_deck.mjs
        # prints it last, once every slide is done, so the last one is its own:
        # anything a slide's page made the sidecar print comes before it.
        failures: list[dict[str, Any]] = []
        for line in reversed(stderr.splitlines()):
            if line.startswith("__HUASHU_RESULT__"):
                try:
                    parsed = json.loads(line.removeprefix("__HUASHU_RESULT__").strip())
                    failures = parsed.get("failed", []) or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not parse huashu result line: %s", exc)
                break

        if not out_path.exists():
            # All-fail or hard-fail; still return failures so caller can show them.
            if failures:
                return b"", failures
            raise HuashuExportError(
                f"huashu sidecar exited {result.returncode} with no pptx and no result line. "
                f"stderr tail: {stderr[-500:]}"
            )

        return out_path.read_bytes(), failures
