"""Local-only Tellr → huashu-design pipeline bridge.

Spawns the ``services/pptx-emit-huashu/emit_deck.mjs`` Node sidecar, which
runs alchaincyf/huashu-design's ``html2pptx.js`` (Playwright + pptxgenjs
server-side) over each slide's complete HTML doc and writes a single
editable .pptx.

Why local-only: huashu's pipeline needs Chromium via Playwright. Databricks
Apps containers run as non-root with limited memory and ship without Chromium.
Adopting this on FEVM would require a deeper infra change than this round
covers. ``is_available()`` returns False outside the local-dev gate.
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
from typing import Any

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


def sidecar_subprocess_env() -> dict[str, str]:
    """Build the env dict for any node subprocess that ends up spawning
    Chromium. Prepends ``services/pptx-emit-huashu/sys-libs/`` onto
    ``LD_LIBRARY_PATH`` if the directory exists, so Chromium can find the
    bundled libnspr4/libnss3/etc. on Databricks Apps where the host glibc-
    next runtime libs aren't installed. Scoping it here (not as a global
    env in app.yaml) prevents the Python process from accidentally loading
    incompatible libs from the bundle.
    """
    env = os.environ.copy()
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


def build_pptx_huashu(
    title: str,
    slides_html: list[dict[str, Any]],
    *,
    bypass_validation: bool = False,
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

    Returns a 2-tuple:
      * pptx_bytes — the .pptx as bytes, even if some slides failed
        (empty if ALL slides failed; the caller should handle that).
      * failures  — list of ``{ slide_index, error }`` with one entry per
        slide huashu rejected. Empty list = clean run.
    """
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

        # Parse the sentinel line for structured failure data.
        failures: list[dict[str, Any]] = []
        for line in stderr.splitlines():
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
