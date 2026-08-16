# src/services/converter_jail/protocol.py
"""Shared, dependency-free constants and helpers for the converter jail.

Imported by BOTH the trusted host (jail.py, the services) and the trusted
in-jail runners. Keep it stdlib-only so it imports cleanly under `python -I`.
"""

import json

# Sentinel prefix for the trusted progress channel on the child's stdout.
# Only the trusted runner emits it; generated code's stdout is redirected to
# stderr inside the runner so it cannot appear on stdout (see pptx_runner.py).
PROGRESS_PREFIX = "@@TELLR_JAIL_PROGRESS@@ "

# Placeholder URL scheme the Google generated code uses to reference an asset
# file by name; the host substitutes the real Drive URL after upload.
ASSET_SCHEME = "tellr-asset://"

# Job-directory layout written by the host, read by the runner.
MANIFEST_NAME = "manifest.json"
CODE_NAME = "code.py"
HTML_NAME = "html.txt"
ASSETS_DIR = "assets"


# Sentinel prefix for the trusted per-slide RESULT channel. Same trust property as
# PROGRESS_PREFIX and for the same reason: only the trusted runner emits it, and
# generated code's stdout is redirected to stderr before any snippet executes, so a
# snippet cannot forge a result for itself. The host needs this because whether a
# slide produced REAL content is only known after validation and execution — a
# non-empty snippet can still be rejected by the import allowlist or raise when it
# runs, and both outcomes fall back to a placeholder slide. Without a report, an
# all-placeholder deck is indistinguishable from a good one.
RESULT_PREFIX = "@@TELLR_JAIL_SLIDE_RESULT@@ "


def encode_slide_result(index: int, rendered: bool) -> str:
    """Encode one per-slide outcome as a single stdout line (with newline).

    ``rendered`` is True only when the slide's own generated code ran and produced
    its slide; False whenever the deterministic placeholder fallback was used.
    """
    payload = json.dumps({"index": index, "rendered": bool(rendered)})
    return f"{RESULT_PREFIX}{payload}\n"


def decode_slide_result(line: str):
    """Decode a stdout line into ``(index, rendered)``, or None when the line is
    not a slide-result line / is malformed."""
    if not line.startswith(RESULT_PREFIX):
        return None
    try:
        data = json.loads(line[len(RESULT_PREFIX):].strip())
        return int(data["index"]), bool(data["rendered"])
    except (ValueError, KeyError, TypeError):
        return None


def encode_progress(current: int, total: int, message: str) -> str:
    """Encode one progress event as a single stdout line (with newline)."""
    payload = json.dumps({"current": current, "total": total, "message": message})
    return f"{PROGRESS_PREFIX}{payload}\n"


def decode_progress(line: str):
    """Decode a stdout line into (current, total, message), or None if the
    line is not a progress line / is malformed."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        data = json.loads(line[len(PROGRESS_PREFIX):].strip())
        return int(data["current"]), int(data["total"]), str(data["message"])
    except (ValueError, KeyError, TypeError):
        return None
