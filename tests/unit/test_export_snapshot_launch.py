"""How the snapshot engine launches Chromium (render_slide.cjs launchOptions).

On Linux (Databricks Apps) headless Chromium hints glyph outlines fully, which
rounds every glyph's advance: measured on the deployed sidecar's Chromium, DM
Sans, DM Mono and Barlow lines came out 0.95 to 1.08 of their width on a Mac.
Launched with --font-render-hinting=none they are within 0.0004 of it, and the
flag changes no width on a Mac (Chrome there lays text out with CoreText) nor
for the Liberation faces of the font bundle. So the flag is on Linux alone, with
the sandbox flags. On both, WebRTC sends no UDP but through a proxy, which the
browser has none of: a slide's peer connection reaches no STUN server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.export_snapshot_support import node_json, requires_node

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_DIR = REPO_ROOT / "services" / "pptx-emit-huashu"
RENDER_SLIDE = SIDECAR_DIR / "render_slide.cjs"
MEASURE = REPO_ROOT / "tests" / "fixtures" / "export_snapshot" / "measure.cjs"

pytestmark = [
    requires_node,
    pytest.mark.skipif(
        not (SIDECAR_DIR / "node_modules" / "playwright").is_dir(),
        reason="requires services/pptx-emit-huashu/node_modules (run setup.sh)",
    ),
]


def _launch_args(platform: str) -> list[str]:
    """render_slide.cjs launchOptions(tmpDir).args, as Node on ``platform`` builds them."""
    script = (
        f"Object.defineProperty(process, 'platform', {{ value: {json.dumps(platform)} }});"
        f"const {{ launchOptions }} = require({json.dumps(str(RENDER_SLIDE))});"
        "process.stdout.write(JSON.stringify(launchOptions('/tmp').args));"
    )
    args = node_json(script)
    assert isinstance(args, list), args
    return args


def test_linux_lays_glyphs_out_unhinted() -> None:
    args = _launch_args("linux")

    assert "--font-render-hinting=none" in args
    assert {
        "--disable-gpu",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    } <= set(args)


# WebRTC's IP-handling policy, which Chrome reads from the first flag and Playwright's
# Chromium from the second: no UDP but through a proxy (request_guard.cjs, WebRTC).
WEBRTC_POLICY_FLAGS = [
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
]


def test_macos_launch_is_software_raster_and_the_webrtc_policy_alone() -> None:
    assert _launch_args("darwin") == ["--disable-gpu", *WEBRTC_POLICY_FLAGS]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_both_builds_get_the_webrtc_policy(platform: str) -> None:
    """Each flag is the one a build reads (measured): both go to both, the other ignored."""
    assert set(WEBRTC_POLICY_FLAGS) <= set(_launch_args(platform))


def test_the_test_measurer_launches_as_the_engine_does_on_linux() -> None:
    """measure.cjs, the tests' own browser oracle, sets text where the engine does on Linux."""
    source = MEASURE.read_text()
    linux_branch = source[source.index("function launchOptions()") :].split("return options;")[0]

    assert "'--font-render-hinting=none'" in linux_branch
