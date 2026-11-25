"""The PPTX route's ``X-Huashu-Failures`` header is bounded, its JSON whole.

The route answers a partly exported deck 200 with the slides that failed in a response header,
which the frontend parses (``frontend/src/services/api.ts`` exportPptxHuashu) to name them.
Measured on a deployed app: a browser that crashed at its launch failed its slide with a
14,424-character message, Chromium's whole launch log, and the header carried it all. Proxies
refuse a response whose headers are too large. So each failure's text in the header is cut at
``HUASHU_FAILURE_TEXT_LIMIT`` characters, "…" added, and the whole header is at most
``HUASHU_FAILURES_HEADER_LIMIT`` bytes: when every text at its cut is still too long, every text
is cut shorter, and when even entries holding "…" alone are, the first entries that fit are
kept. Every entry kept keeps its slide index, so the toast still names its slide. The header is
ASCII JSON. A failure list in a body (all slides failed: 422) keeps each message whole.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.api.routes import export as export_routes
from src.services import pptx_from_html_huashu

TEXT_LIMIT = 300
HEADER_LIMIT = 4096
ELISION = "…"
# The measured failure's first line, and a launch log of its length.
LAUNCH_CLOSED = "browserType.launch: Target page, context or browser has been closed"
CRASH_LOG_LINE = "[pid=66960][err] #0 0x561980790f5a\n"
CRASH_MESSAGE = (LAUNCH_CLOSED + "\nBrowser logs:\n\n" + CRASH_LOG_LINE * 500)[:14424]


def _export(
    monkeypatch: pytest.MonkeyPatch, failures: list[dict], *, slides: int, deck: bytes = b"PK"
):
    """The PPTX route's answer for a deck of ``slides`` whose export failed ``failures``."""
    chat = MagicMock()
    chat.get_slides.return_value = {
        "title": "Deck",
        "slides": [{"html": f"<p>{index}</p>"} for index in range(slides)],
    }
    monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
    monkeypatch.setattr(export_routes, "get_chat_service", lambda: chat)
    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
    monkeypatch.setattr(
        pptx_from_html_huashu, "build_pptx_huashu", lambda *_, **__: (deck, failures)
    )
    return export_routes.export_pptx_huashu_from_html(
        export_routes.ExportPPTXEditableRequest(session_id="session")
    )


def _header(monkeypatch: pytest.MonkeyPatch, failures: list[dict], *, slides: int) -> str:
    response = _export(monkeypatch, failures, slides=slides)
    assert response.status_code == 200
    header = response.headers["x-huashu-failures"]
    assert header.isascii(), header[:200]
    assert len(header.encode("ascii")) <= HEADER_LIMIT, f"{len(header)} bytes"
    return header


def _assert_cut_from(entry: dict, original: dict, limit: int = TEXT_LIMIT) -> None:
    """The entry is the original's, its text the original's first characters and "…"."""
    assert entry["slide_index"] == original["slide_index"], (entry, original)
    text = entry["error"]
    assert text.endswith(ELISION), text[-40:]
    kept = text.removesuffix(ELISION)
    assert len(kept) <= limit and original["error"].startswith(kept), (len(kept), kept[:80])


class TestEachFailureIsCut:
    def test_the_measured_launch_crash_is_cut_at_its_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = {"slide_index": 20, "error": CRASH_MESSAGE}
        assert len(CRASH_MESSAGE) == 14424

        (entry,) = json.loads(_header(monkeypatch, [original], slides=28))

        _assert_cut_from(entry, original)
        assert len(entry["error"]) == TEXT_LIMIT + len(ELISION)
        assert entry["error"].startswith(LAUNCH_CLOSED), "the toast's first line is lost"

    def test_a_failure_within_the_limit_is_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        failures = [
            {"slide_index": 1, "error": "the slide's page navigated away from the slide"},
            {"slide_index": 4, "error": "x" * TEXT_LIMIT},
        ]

        assert json.loads(_header(monkeypatch, failures, slides=6)) == failures

    def test_a_text_past_ascii_is_cut_by_its_characters_and_escaped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = {"slide_index": 0, "error": "收入增长" * 500}

        (entry,) = json.loads(_header(monkeypatch, [original], slides=2))

        _assert_cut_from(entry, original)
        assert len(entry["error"]) == TEXT_LIMIT + len(ELISION)


class TestTheWholeHeaderIsBounded:
    def test_many_long_failures_are_each_cut_shorter_and_all_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """27 slides of 28 crashed: each text at 300 characters makes some 8 KB, so each is
        cut shorter, and every slide is still named."""
        failures = [{"slide_index": index, "error": CRASH_MESSAGE} for index in range(27)]

        entries = json.loads(_header(monkeypatch, failures, slides=28))

        assert [entry["slide_index"] for entry in entries] == list(range(27))
        for entry, original in zip(entries, failures):
            _assert_cut_from(entry, original)
        assert len({len(entry["error"]) for entry in entries}) == 1, "the texts were cut unevenly"
        kept = len(entries[0]["error"]) - len(ELISION)
        assert kept < TEXT_LIMIT
        one_more = [
            {**original, "error": original["error"][: kept + 1] + ELISION} for original in failures
        ]
        assert len(json.dumps(one_more, separators=(",", ":"))) > HEADER_LIMIT, (
            f"cut at {kept} characters where a longer cut fits"
        )

    def test_more_failures_than_fit_keep_the_first_that_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failures = [{"slide_index": index, "error": CRASH_MESSAGE} for index in range(400)]

        entries = json.loads(_header(monkeypatch, failures, slides=401))

        kept = [entry["slide_index"] for entry in entries]
        assert kept == list(range(len(kept))) and 50 < len(kept) < 400, kept[-3:]
        assert all(entry["error"] == ELISION for entry in entries), entries[:2]

    def test_the_other_headers_still_count_every_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failures = [{"slide_index": index, "error": CRASH_MESSAGE} for index in range(400)]

        response = _export(monkeypatch, failures, slides=401)

        assert response.headers["x-huashu-total-slides"] == "401"
        assert response.headers["x-huashu-succeeded"] == "1"


def test_a_failure_list_in_a_body_keeps_each_message_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every slide failed: the 422's failures are the body's, which no header bound reaches."""
    failures = [{"slide_index": 0, "error": CRASH_MESSAGE}]

    with pytest.raises(HTTPException) as raised:
        _export(monkeypatch, failures, slides=1, deck=b"")

    assert raised.value.status_code == 422
    assert raised.value.detail["failures"] == failures
