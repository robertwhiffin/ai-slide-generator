"""SDR-4437 F-CR-35 follow-up — the huashu sidecar must never read files.

The sidecar renders each slide in server-side Chromium and hands pptxgenjs the
pictures the slide model names. pptxgenjs reads any image given to it as a
``path`` from disk and embeds it, the same file-read class as the records
sidecar, and the slide CSP (``img-src data:``) stops Chromium loading such an
image but not the Node side reading it: an ``<img>``'s ``src`` still reports the
attribute.

Fixed the same two ways as the records sidecar:

1. Only raster ``data:`` sources are ever embedded: ``emit_model.cjs`` writes a
   picture from a capture ``render_slide.cjs`` took of the page, or from the
   item's own raster ``data:`` ``src``, and skips anything else; the snapshot
   takes a body ``background-image`` only when it is a raster ``data:`` URI.
   Legitimate decks lose nothing: what the browser draws without a raster
   source (an SVG, a canvas, a gradient) is captured, and stored images are
   data URIs.
2. ``sidecar_subprocess_env`` is an allowlist instead of a copy of the app's
   environment. Unlike the records sidecar it must keep the real ``HOME``
   (Playwright finds Chromium under ``~/.cache/ms-playwright``) and any proxy
   settings (the page loads Chart.js from a CDN).

Every export here goes through the model check's zero-drop guard
(``export_documents``), so a slide model the check dropped part of cannot pass
for one that never named the file.
"""

from __future__ import annotations

import base64
import os
import zipfile
from io import BytesIO
from unittest import mock

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import export_documents

# 1x1 transparent PNG.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PNG_DATA_URI = f"data:image/png;base64,{PNG_B64}"

IMG_CANARY = b"FAKE_SECRET_IMG=fcr35-huashu-img-canary"
BG_CANARY = b"FAKE_SECRET_BG=fcr35-huashu-bg-canary"


def _huashu_available() -> bool:
    with mock.patch.dict(os.environ, {"HUASHU_PIPELINE_ENABLED": "1"}):
        return pptx_from_html_huashu.is_available()


requires_huashu_sidecar = pytest.mark.skipif(
    not _huashu_available(),
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)


def _slide_html(img_src: str, body_bg: str = "none") -> str:
    # Production slides carry the slide CSP; keep it so the test exercises
    # the case where Chromium refuses the image but the attribute survives.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">
  <meta charset="UTF-8">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 1280px; height: 720px; overflow: hidden;
      background-color: #ffffff; background-image: {body_bg};
      font-family: Arial, Helvetica, sans-serif;
    }}
  </style>
</head>
<body>
  <div style="position:relative;width:1280px;height:720px;">
    <h1 style="position:absolute;left:88px;top:72px;width:800px;font-size:40px;">Title</h1>
    <img src="{img_src}" style="position:absolute;left:88px;top:200px;width:200px;height:100px;">
  </div>
</body>
</html>"""


def _zip_entries(pptx: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(pptx)) as zf:
        return {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}


@pytest.mark.slow
@requires_huashu_sidecar
class TestHuashuImageSrc:
    def test_local_files_are_not_embedded(self, tmp_path, monkeypatch):
        img = tmp_path / "img-canary"
        img.write_bytes(IMG_CANARY)
        bg = tmp_path / "bg-canary"
        bg.write_bytes(BG_CANARY)
        html = _slide_html(img.as_uri(), body_bg=f'url("{bg.as_uri()}")')

        pptx, failures = export_documents([html], monkeypatch=monkeypatch, title="t")

        assert failures == [], failures
        leaked = [
            n for n, blob in _zip_entries(pptx).items()
            if IMG_CANARY in blob or BG_CANARY in blob
        ]
        assert not leaked, f"canary file bytes embedded in {leaked}"

    def test_data_image_is_still_embedded(self, monkeypatch):
        pptx, failures = export_documents(
            [_slide_html(PNG_DATA_URI)], monkeypatch=monkeypatch, title="t"
        )

        assert failures == [], failures
        media = [b for n, b in _zip_entries(pptx).items() if n.startswith("ppt/media/")]
        assert base64.b64decode(PNG_B64) in media


class TestSidecarEnv:
    SECRETS = {
        "DATABRICKS_CLIENT_SECRET": "fcr35-sp-secret",
        "DATABRICKS_TOKEN": "fcr35-token",
        "TELLR_ENCRYPTION_KEY": "fcr35-fernet",
        "PGPASSWORD": "fcr35-pg",
    }

    def test_excludes_app_secrets(self, monkeypatch):
        for key, value in self.SECRETS.items():
            monkeypatch.setenv(key, value)

        env = pptx_from_html_huashu.sidecar_subprocess_env()

        # Key names only: a failure must not print real credentials.
        leaked = sorted(
            k for k, v in env.items() if k in self.SECRETS or v in self.SECRETS.values()
        )
        assert not leaked, f"huashu sidecar env carries {leaked}"

    def test_keeps_what_playwright_and_chromium_need(self, monkeypatch):
        keep = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/app",
            "LANG": "C.UTF-8",
            "TMPDIR": "/tmp/x",
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/pw",
            "XDG_CACHE_HOME": "/home/app/.cache",
            "HTTPS_PROXY": "http://proxy:3128",
            "NO_PROXY": "localhost",
        }
        for key, value in keep.items():
            monkeypatch.setenv(key, value)

        env = pptx_from_html_huashu.sidecar_subprocess_env()

        assert {k: env.get(k) for k in keep} == keep

    def test_prepends_bundled_sys_libs(self, tmp_path, monkeypatch):
        sys_libs = tmp_path / "sys-libs"
        sys_libs.mkdir()
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SYS_LIBS_DIR", sys_libs)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/lib/x")

        env = pptx_from_html_huashu.sidecar_subprocess_env()

        assert env["LD_LIBRARY_PATH"] == f"{sys_libs}:/usr/lib/x"
