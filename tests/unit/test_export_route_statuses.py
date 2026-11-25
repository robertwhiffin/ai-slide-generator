"""How the export routes answer a failed export: 503 only where the pipeline cannot run (M1).

The frontend answers a 503 from the Google Slides route by falling back to the records
pipeline, without a word (frontend/src/services/api.ts exportToGoogleSlides). The route used
to answer 503 for every ``HuashuExportError``, a timed-out export included, so an export
that ran and failed fell back silently. Now the wrapper says which failure it is:

* ``HuashuUnavailableError``: the pipeline cannot run here (not enabled, not installed):
  503, which the frontend falls back on;
* ``HuashuTimeoutError``: the sidecar ran past ``SIDECAR_TIMEOUT_SECONDS``: 504;
* any other ``HuashuExportError`` (the sidecar exited with no deck): 500.

Both are ``HuashuExportError``s, so a caller that catches that one still does. The PPTX
route answers the same way; the Google Slides route's own cases are in
``tests/unit/test_google_slides_routes.py`` (``TestFromHuashuEndpoint``).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.api.routes import export as export_routes
from src.services import pptx_from_html_huashu
from src.services.pptx_from_html_huashu import (
    HuashuExportError,
    HuashuTimeoutError,
    HuashuUnavailableError,
)
FAILURES = [
    (HuashuUnavailableError("huashu pipeline not available: not installed"), 503),
    (HuashuTimeoutError("huashu sidecar timed out after 180s"), 504),
    (HuashuExportError("huashu sidecar exited 1 with no pptx and no result line"), 500),
]
FAILURE_IDS = ["unavailable", "timed-out", "failed"]


class TestTheWrapperSaysWhichFailure:
    def test_a_pipeline_that_cannot_run_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: False)
        with pytest.raises(HuashuUnavailableError):
            pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])

    def test_a_run_past_the_timeout_timed_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def run(command: list[str], **_: object):
            raise subprocess.TimeoutExpired(command, 1, output=b"", stderr=b"")

        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", run)
        with pytest.raises(HuashuTimeoutError, match="timed out"):
            pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])

    def test_both_are_export_errors(self) -> None:
        assert issubclass(HuashuUnavailableError, HuashuExportError)
        assert issubclass(HuashuTimeoutError, HuashuExportError)


class TestThePptxRoute:
    @pytest.mark.parametrize(("error", "status"), FAILURES, ids=FAILURE_IDS)
    def test_it_answers_each_failure_its_status(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
    ) -> None:
        def fake_build(*_: object, **__: object):
            raise error

        chat = MagicMock()
        chat.get_slides.return_value = {"title": "Deck", "slides": [{"html": "<p>x</p>"}]}
        monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
        monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "build_pptx_huashu", fake_build)

        with pytest.raises(HTTPException) as raised:
            export_routes.export_pptx_huashu_from_html(
                export_routes.ExportPPTXEditableRequest(session_id="session")
            )

        assert raised.value.status_code == status, raised.value.detail
        assert raised.value.detail
