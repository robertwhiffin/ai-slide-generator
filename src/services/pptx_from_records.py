"""Editable PPTX emitter — thin wrapper over the pptxgenjs Node sidecar.

Pipeline:
    records JSON (scaffold shape) ─stdin─▶ node services/pptx-emit/emit.mjs ─▶ .pptx

The client-side walker (``frontend/src/services/domWalker.ts``) extracts
DOM records in the user's browser (no Chromium on the Databricks Apps
container — non-root + memory-constrained). The records are POSTed to
the FastAPI route which calls :func:`build_pptx` here. We spawn a short-
lived Node subprocess that runs the pre-bundled ``emit.bundle.mjs`` (which
inlines pptxgenjs via esbuild so no ``node_modules`` need ship). Output
is a .pptx byte stream.

Record shape, per scaffold reference:
    { width, height, records: [rect|image|text], notes }
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_DIR = REPO_ROOT / "services" / "pptx-emit"
SIDECAR_BUNDLE = SIDECAR_DIR / "emit.bundle.mjs"
SIDECAR_SCRIPT = SIDECAR_DIR / "emit.mjs"
SIDECAR_TIMEOUT_SECONDS = 120


class EmitError(RuntimeError):
    """Raised when the Node sidecar fails to produce a PPTX."""


def is_available() -> bool:
    """True iff Node is on PATH and the sidecar bundle is shipped.

    Prefer the self-contained bundle (no ``node_modules`` needed, survives
    ``.databricksignore``). Fall back to the un-bundled script only for
    local-dev where ``node_modules`` is present.
    """
    if shutil.which("node") is None:
        return False
    if SIDECAR_BUNDLE.exists():
        return True
    if SIDECAR_SCRIPT.exists() and (SIDECAR_DIR / "node_modules" / "pptxgenjs").exists():
        return True
    return False


def _sidecar_entrypoint() -> Path:
    return SIDECAR_BUNDLE if SIDECAR_BUNDLE.exists() else SIDECAR_SCRIPT


def build_pptx(
    title: str,
    slides: list[dict[str, Any]],
    font_mode: str = "universal",
    design_w: int | None = None,  # kept for caller-signature parity; ignored
    design_h: int | None = None,
) -> bytes:
    """Emit a .pptx via the pptxgenjs sidecar.

    ``slides`` must be scaffold-shape: each entry is
    ``{ width, height, records: [...], notes: "..." }``. Slide dimensions
    come from the records themselves, so ``design_w`` / ``design_h`` are
    accepted for backward compatibility with callers but unused.

    ``font_mode`` is one of ``universal`` (Arial/Consolas fallback),
    ``custom`` (keep authored fonts), ``google_slides`` (keep brand names
    so Google Slides pulls from Google Fonts on import).
    """
    if not is_available():
        raise EmitError(
            "pptxgenjs Node sidecar not available. Ensure `node` is on PATH "
            f"and `{SIDECAR_BUNDLE}` is present (run `npx esbuild emit.mjs "
            f"--bundle ...` in `{SIDECAR_DIR}`)."
        )
    if font_mode not in ("universal", "custom", "google_slides"):
        font_mode = "universal"

    payload = {"title": title, "font_mode": font_mode, "slides": slides}
    payload_bytes = json.dumps(payload).encode("utf-8")

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.pptx"
        cmd = ["node", str(_sidecar_entrypoint()), "-", str(out_path)]
        logger.info(
            "spawn pptxgenjs sidecar: %s (payload=%d bytes, slides=%d)",
            " ".join(cmd), len(payload_bytes), len(slides),
        )
        try:
            result = subprocess.run(
                cmd,
                input=payload_bytes,
                capture_output=True,
                timeout=SIDECAR_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise EmitError(f"Sidecar timed out after {SIDECAR_TIMEOUT_SECONDS}s") from e

        if result.stderr:
            for line in result.stderr.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    print(f"[pptx-emit] {line}", file=sys.stderr, flush=True)

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise EmitError(f"Sidecar exited {result.returncode}: {stderr[-500:]}")
        if not out_path.exists():
            raise EmitError("Sidecar completed but no output file was produced")
        return out_path.read_bytes()
