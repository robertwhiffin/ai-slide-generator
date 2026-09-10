"""Object-storage backend for slide-style preview payloads.

The app's durable, multi-replica-safe binary store is Postgres ``bytea`` (see
``ImageAsset.image_data`` / ``DesignSystemAsset.data``). This module mirrors that
pattern for preview HTML/CSS bundles: they live gzipped in
``slide_style_preview_payload``, keyed by ``(style_id, fingerprint)``, so the
frequently-queried ``slide_style_library`` rows stay blob-free and a stale
last-known-good bundle can survive alongside a newer fingerprint.

Referenced image bytes are NOT stored here — previews reference the existing
image library (served by its own controlled route), so only the HTML/CSS bundle
plus a lightweight asset manifest is persisted.
"""

from __future__ import annotations

import gzip
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.database.models.slide_style_preview import SlideStylePreviewPayload

logger = logging.getLogger(__name__)


def _pack(
    slides: list[str], css: str, assets: Optional[list[dict[str, Any]]]
) -> tuple[bytes, int]:
    """gzip(JSON) the bundle; return (compressed_bytes, uncompressed_size).

    ``slides`` is a list of per-slide HTML fragments (kept separate so the UI can
    page a mini-deck — slide roots are ``position:absolute`` and would stack if
    concatenated into one document).
    """
    raw = json.dumps(
        {"slides": list(slides or []), "css": css or "", "assets": assets or []},
        separators=(",", ":"),
    ).encode("utf-8")
    return gzip.compress(raw), len(raw)


def _unpack(blob: bytes) -> dict[str, Any]:
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def store_payload(
    db: Session,
    style_id: int,
    fingerprint: str,
    slides: list[str],
    css: str,
    assets: Optional[list[dict[str, Any]]] = None,
) -> tuple[int, int]:
    """Idempotently persist a preview bundle for (style_id, fingerprint).

    Returns (payload_id, total_uncompressed_bytes). If a row already exists for
    the pair it is overwritten (a regeneration for the same fingerprint).
    """
    blob, total_bytes = _pack(slides, css, assets)
    existing = (
        db.query(SlideStylePreviewPayload)
        .filter(
            SlideStylePreviewPayload.style_id == style_id,
            SlideStylePreviewPayload.fingerprint == fingerprint,
        )
        .first()
    )
    if existing:
        existing.bundle_gzip = blob
        existing.total_bytes = total_bytes
        db.flush()
        return existing.id, total_bytes

    row = SlideStylePreviewPayload(
        style_id=style_id,
        fingerprint=fingerprint,
        bundle_gzip=blob,
        total_bytes=total_bytes,
    )
    db.add(row)
    db.flush()  # populate row.id
    return row.id, total_bytes


def load_payload(db: Session, payload_id: int) -> Optional[dict[str, Any]]:
    """Return {'slides','css','assets'} for a payload id, or None if missing."""
    row = (
        db.query(SlideStylePreviewPayload)
        .filter(SlideStylePreviewPayload.id == payload_id)
        .first()
    )
    if not row or not row.bundle_gzip:
        return None
    try:
        return _unpack(row.bundle_gzip)
    except Exception:  # noqa: BLE001 — corrupt payload should not 500 the read
        logger.warning("Corrupt slide-style preview payload id=%s", payload_id, exc_info=True)
        return None


def prune_payloads(db: Session, style_id: int, keep_ids: set[int]) -> int:
    """Delete stored payloads for a style except those in keep_ids. Returns count.

    Keeps the current + last-known-good bundle; sweeps abandoned fingerprints.
    """
    rows = (
        db.query(SlideStylePreviewPayload)
        .filter(SlideStylePreviewPayload.style_id == style_id)
        .all()
    )
    removed = 0
    for r in rows:
        if r.id not in keep_ids:
            db.delete(r)
            removed += 1
    return removed
