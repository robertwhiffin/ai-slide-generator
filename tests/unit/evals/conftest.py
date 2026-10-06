"""Shared fixtures for the eval-harness self-tests.

``requires_chromium``: request it (``@pytest.mark.usefixtures("requires_chromium")``) on every test
that really renders a slide. It skips with an explicit reason when no Playwright chromium can be
launched (e.g. the CI unit job, which installs no browser), instead of failing on ``rendered=False``.

Set ``EVALS_FORCE_NO_CHROMIUM=1`` to force ``render.chromium_available()`` to False. In that mode
this conftest also makes ``render.render_slide`` raise, so any render-dependent test that is missing the fixture errors
loudly rather than passing or failing vacuously.
"""
import os

import pytest

from evals.harness import render

CHROMIUM_SKIP_REASON = "Playwright chromium not installed"

if os.environ.get("EVALS_FORCE_NO_CHROMIUM") == "1":
    def _no_render(*a, **k):
        raise AssertionError("render_slide called by a test that does not request requires_chromium")

    render.render_slide = _no_render


@pytest.fixture
def requires_chromium():
    if not render.chromium_available():
        pytest.skip(CHROMIUM_SKIP_REASON)
