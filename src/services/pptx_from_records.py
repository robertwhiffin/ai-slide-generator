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

from src.services.converter_jail.jail import build_scrubbed_env

logger = logging.getLogger(__name__)

def _resolve_sidecar_dir() -> Path:
    # Dev / editable install: services/ lives at the repo root.
    dev = Path(__file__).resolve().parents[2] / "services" / "pptx-emit"
    if dev.exists():
        return dev
    # Wheel install: setup.py copies the sidecar under databricks_tellr_app/_assets/sidecars/.
    try:
        from databricks_tellr_app import _assets_root  # type: ignore
        wheel = Path(_assets_root()) / "sidecars" / "pptx-emit"
        if wheel.exists():
            return wheel
    except Exception:
        pass
    try:
        import databricks_tellr_app  # type: ignore
        wheel = Path(databricks_tellr_app.__file__).resolve().parent / "_assets" / "sidecars" / "pptx-emit"
        if wheel.exists():
            return wheel
    except Exception:
        pass
    return dev


SIDECAR_DIR = _resolve_sidecar_dir()
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


def _drop_non_data_images(slides: list[Any]) -> list[Any]:
    """Remove every image record whose ``src`` is not a ``data:`` URI.

    SDR-4437 F-CR-35: pptxgenjs resolves any other ``src`` as a filesystem
    path (``fs.readFileSync``) or an https URL and embeds the bytes in the
    deck, so a client-supplied ``/proc/self/environ`` came back inside the
    .pptx. The records are client-controlled, so this is the authoritative
    gate; ``emit.mjs`` repeats it. Nothing legitimate is lost: the walker
    emits ``data:`` URIs only, and the slide CSP (``img-src data:``) already
    blocks any other ``<img>`` source in the preview.

    The check mirrors ``emit.mjs`` exactly (``r.kind === 'image'``,
    ``typeof src === 'string' && src.startsWith('data:')``), and the sidecar
    receives this filtered structure re-serialized, so what passes here is
    what the sidecar sees.
    """
    dropped = 0
    cleaned: list[Any] = []
    for slide in slides:
        records = slide.get("records") if isinstance(slide, dict) else None
        if isinstance(records, list):
            kept = []
            for record in records:
                if isinstance(record, dict) and record.get("kind") == "image":
                    src = record.get("src")
                    if not (isinstance(src, str) and src.startswith("data:")):
                        dropped += 1
                        continue
                kept.append(record)
            slide = {**slide, "records": kept}
        cleaned.append(slide)
    if dropped:
        logger.warning(
            "Dropped %d image record(s) with a non-data: src before the "
            "pptx-emit sidecar (SDR-4437 F-CR-35)",
            dropped,
        )
    return cleaned


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

    payload = {"title": title, "font_mode": font_mode, "slides": _drop_non_data_images(slides)}
    payload_bytes = json.dumps(payload).encode("utf-8")

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.pptx"
        cmd = ["node", str(_sidecar_entrypoint()), "-", str(out_path)]
        logger.info(
            "spawn pptxgenjs sidecar: %s (payload=%d bytes, slides=%d)",
            " ".join(cmd), len(payload_bytes), len(slides),
        )
        try:
            # SDR-4437 F-CR-35: the sidecar holds no credentials of its own.
            # Defence in depth only — it runs as the app's OS user, so the
            # image-src filter above is what removes the file-read primitive.
            result = subprocess.run(
                cmd,
                input=payload_bytes,
                capture_output=True,
                timeout=SIDECAR_TIMEOUT_SECONDS,
                check=False,
                env=build_scrubbed_env(home=td),
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
