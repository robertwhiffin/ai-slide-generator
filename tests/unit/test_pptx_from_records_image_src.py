"""SDR-4437 F-CR-35 — the records sidecar must never read files or URLs.

The editable-PPTX and Google Slides ``/from-records`` routes pass client-
supplied DOM-walker records to the pptxgenjs Node sidecar. pptxgenjs treats an
image ``path`` as a filesystem path (``fs.readFileSync``) or an https URL
(``https.get``) and embeds the raw bytes in the deck, so a record such as
``{"kind": "image", "src": "/proc/self/environ"}`` returned the sidecar's
environment — App SP secret included — inside the .pptx.

Three independent layers close it, each pinned here:

1. ``build_pptx`` drops every image record whose ``src`` is not a ``data:``
   URI before the payload reaches the sidecar (authoritative; covers both
   routes and any future caller).
2. ``emit.mjs`` (and the checked-in ``emit.bundle.mjs``) skips non-``data:``
   sources itself, so the sidecar is safe even if handed a raw payload.
3. The sidecar is spawned with the converter jail's scrubbed environment, so
   it holds no credentials of its own.

Scrubbing (3) alone is not a fix: the sidecar runs as the same OS user as the
app and could still read the parent's ``/proc/<ppid>/environ``. (1) and (2)
are what remove the read primitive.

Legitimate exports lose nothing: the walker emits gradients, canvases and
rasterized SVGs as ``data:`` URIs, and an ``<img>`` with any other source is
already blocked by the slide CSP (``img-src data:``), so it renders broken in
the preview too.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from src.services import pptx_from_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDS_BUNDLE = REPO_ROOT / "services" / "pptx-emit" / "emit.bundle.mjs"

# 1x1 transparent PNG.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PNG_DATA_URI = f"data:image/png;base64,{PNG_B64}"

CANARY = b"FAKE_DATABRICKS_CLIENT_SECRET=fcr35-canary-7f3a9c"

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="requires node")
requires_records_sidecar = pytest.mark.skipif(
    not pptx_from_records.is_available(),
    reason="requires node + services/pptx-emit/emit.bundle.mjs",
)

# A stand-in sidecar: writes the env it was spawned with and the payload it
# was sent to the output path, so tests observe exactly what the real sidecar
# would receive.
_ECHO_SIDECAR = """
import fs from 'node:fs';
const chunks = [];
for await (const c of process.stdin) chunks.push(c);
fs.writeFileSync(process.argv[3], JSON.stringify({
  env: process.env,
  payload: JSON.parse(Buffer.concat(chunks).toString('utf-8')),
}));
"""


@pytest.fixture
def echo_sidecar(tmp_path, monkeypatch):
    script = tmp_path / "echo_sidecar.mjs"
    script.write_text(_ECHO_SIDECAR, encoding="utf-8")
    monkeypatch.setattr(pptx_from_records, "SIDECAR_BUNDLE", script)

    def run(slides):
        out = pptx_from_records.build_pptx("t", slides)
        return json.loads(out)

    return run


@pytest.fixture
def canary_file(tmp_path):
    path = tmp_path / "canary-secret"
    path.write_bytes(CANARY)
    return path


def _slide(*records):
    return {"width": 1280, "height": 720, "records": list(records), "notes": ""}


def _image(src):
    return {"kind": "image", "x": 0, "y": 0, "w": 10, "h": 10, "src": src}


def _assert_canary_absent(pptx_bytes: bytes) -> None:
    with zipfile.ZipFile(BytesIO(pptx_bytes)) as zf:
        leaked = [n for n in zf.namelist() if CANARY in zf.read(n)]
    assert not leaked, f"canary file bytes embedded in {leaked}"


HOSTILE_SRCS = [
    "/proc/self/environ",
    "file:///proc/self/environ",
    "https://example.com/x.png",
    "http://169.254.169.254/latest/meta-data/",
    "blob:https://app.example/1234",
    "relative/path.png",
    " data:image/png;base64,AAAA",  # leading space: not a data: URI to emit.mjs
    "DATA:image/png;base64,AAAA",  # emit.mjs's check is case-sensitive
    ["/proc/self/environ"],
    {"href": "file:///proc/self/environ"},
]


@requires_node
@pytest.mark.parametrize("src", HOSTILE_SRCS, ids=repr)
def test_non_data_image_src_never_reaches_sidecar(echo_sidecar, src):
    rect = {"kind": "rect", "x": 0, "y": 0, "w": 5, "h": 5, "fill": "FFFFFF"}
    received = echo_sidecar([_slide(_image(PNG_DATA_URI), _image(src), rect)])

    records = received["payload"]["slides"][0]["records"]
    assert records == [_image(PNG_DATA_URI), rect]


@requires_node
def test_sidecar_env_excludes_app_secrets(echo_sidecar, monkeypatch):
    secrets = {
        "DATABRICKS_CLIENT_SECRET": "fcr35-sp-secret",
        "DATABRICKS_TOKEN": "fcr35-token",
        "TELLR_ENCRYPTION_KEY": "fcr35-fernet",
        "PGPASSWORD": "fcr35-pg",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)

    child_env = echo_sidecar([_slide(_image(PNG_DATA_URI))])["env"]

    # Report key names only: a failure must not print the child env (and with
    # it whatever real credentials the test runner's environment holds).
    leaked = sorted(k for k, v in child_env.items() if k in secrets or v in secrets.values())
    assert not leaked, f"sidecar inherited {leaked}"
    assert "PATH" in child_env


@requires_records_sidecar
def test_sidecar_itself_skips_non_data_image_src(tmp_path, canary_file):
    """Layer 2 alone: the bundle, driven directly (no Python filter)."""
    out = tmp_path / "out.pptx"
    payload = {"title": "t", "slides": [_slide(_image(str(canary_file)))]}

    result = subprocess.run(
        ["node", str(RECORDS_BUNDLE), "-", str(out)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    _assert_canary_absent(out.read_bytes())


@requires_records_sidecar
def test_build_pptx_does_not_embed_local_file(canary_file):
    pptx = pptx_from_records.build_pptx("t", [_slide(_image(str(canary_file)))])

    _assert_canary_absent(pptx)


@requires_records_sidecar
def test_data_image_is_still_embedded():
    pptx = pptx_from_records.build_pptx("t", [_slide(_image(PNG_DATA_URI))])

    with zipfile.ZipFile(BytesIO(pptx)) as zf:
        media = [
            zf.read(n)
            for n in zf.namelist()
            if n.startswith("ppt/media/") and not n.endswith("/")
        ]

    assert media == [base64.b64decode(PNG_B64)]
