"""Deck content stays out of the app's logs (S1).

``build_pptx_huashu`` echoes every line the sidecar prints on stderr into the app's log
(``[huashu-emit] ...``), and an app's logs are read by every manager of the app, outside
Tellr's per-deck permissions. The sidecar used to print a slide's own words there: the
slide summary's ``hiddenText``, the text-loss line's missing words, a validation message's
quote of a text box, and whatever message a page's failure carried. So by default the
sidecar prints counts and fixed text only:

* the slide summary counts the words its page hides (``hiddenWords``);
* the text-loss line is ``[html2pptx] text missing: {"slideIndex", "words"}``, the slide
  and how many of its words are missing;
* a validation message names the text box it is about by its length;
* a message a page's failure carried is said by its length (a Node or browser failure
  that carries no page text, a slide past its deadline or one that left itself, is said
  whole);
* what a page logs itself (its console, the slide's script and the engine's page-side
  passes alike, since the page's realm builds both) is counted, by level, in one
  ``[html2pptx] page console:`` line a slide.

``TELLR_EXPORT_DEBUG_TEXT=1`` adds the words: the summary's ``hiddenText``, a text-loss
line naming them, the quotes and the messages, and what a page logs, bounded: each
message cut at ``PAGE_MESSAGE_LIMIT`` characters, and at most ``PAGE_MESSAGES_PER_SLIDE``
messages a slide to each stream. No app passes it: it is not in the
sidecar's env allowlist, and the export fidelity harness, which reads the words, adds it
for its own runs alone (``sidecar_debug_text``). A failure entry, which goes to the user
who exported the deck and not to the log, keeps its whole message.

Each case exports a slide holding words that it hides, loses, puts too near the slide's
bottom edge, or fails on, and finds none of them in anything the wrapper printed or
logged without the flag, and each of them with it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    export_logged,
    fidelity_harness,
    node_json,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
    slide_summaries,
    teed_stderr,
    text_missing_reports,
)

LOG_LINE_MODULE = pptx_from_html_huashu.SIDECAR_DIR / "log_line.cjs"
RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"

# Words no ordinary slide holds: finding one in a log is finding the deck's content there.
HIDDEN_WORD = "Zyqhiddenword"
LOST_WORD = "Zyqlostword"
BOTTOM_WORD = "Zyqbottomword"
THROWN_WORD = "Zyqthrownword"

# A slide that hides one word (opacity 0), loses one (a <select>'s option, which no item
# holds) and sets a third in a text box too near its bottom edge (a validation error).
CONTENT_BODY = (
    '<div class="slide"><h1>Quarterly results</h1>'
    f'<p style="font-size: 20px;">Revenue <span style="opacity: 0;">{HIDDEN_WORD}</span> grew</p>'
    f'<select style="font-size: 20px;"><option>{LOST_WORD}</option></select>'
    '<p style="position: absolute; left: 80px; top: 676px; margin: 0; font-size: 24px;">'
    f"{BOTTOM_WORD} closes the slide</p></div>"
)
ORDINARY_BODY = '<div class="slide"><h1>Quarterly results</h1><p>Revenue grew 12%.</p></div>'
CONTENT_WORDS = (HIDDEN_WORD, LOST_WORD, BOTTOM_WORD)

TEXT_MISSING_PREFIX = "[html2pptx] text missing: "
VALIDATION_LINE = "ends too close to bottom edge"


@dataclass(frozen=True)
class _Logged:
    """Everything an export left in the log: the wrapper's stderr and every log record."""

    stderr: str
    records: str
    failures: list[dict]

    @property
    def everything(self) -> str:
        return self.stderr + "\n" + self.records


@contextlib.contextmanager
def _captured_records() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Keep(level=logging.DEBUG)
    root = logging.getLogger()
    telemetry = pptx_from_html_huashu.telemetry_logger
    previous = root.level
    root.addHandler(handler)
    telemetry.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        telemetry.removeHandler(handler)
        root.setLevel(previous)


def _formatted(records: list[logging.LogRecord]) -> str:
    return "\n".join(f"{record.getMessage()} {record.__dict__}" for record in records)


def _export(documents: list[str], monkeypatch: pytest.MonkeyPatch, *, debug_text: bool) -> _Logged:
    with _captured_records() as records:
        logged = export_logged(documents, monkeypatch=monkeypatch, debug_text=debug_text)
    return _Logged(stderr=logged.stderr, records=_formatted(records), failures=logged.failures)


@pytest.fixture(scope="module")
def content_logs() -> Iterator[dict[bool, _Logged]]:
    """The content slide exported as the routes export it, without the flag and with it."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield {
            debug: _export([slide_document(CONTENT_BODY)], monkeypatch, debug_text=debug)
            for debug in (False, True)
        }


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheAppsLogHoldsNoDeckText:
    def test_no_word_of_the_slide_is_logged(self, content_logs: dict[bool, _Logged]) -> None:
        logged = content_logs[False]
        assert logged.failures == [], logged.failures
        found = [word for word in CONTENT_WORDS if word in logged.everything]
        assert not found, f"the log holds the slide's words {found}:\n{logged.stderr[-3000:]}"

    def test_the_summary_counts_the_hidden_words(self, content_logs: dict[bool, _Logged]) -> None:
        (summary,) = slide_summaries(content_logs[False].stderr)
        assert summary["hiddenWords"] == 1 and "hiddenText" not in summary, summary

    def test_the_text_loss_line_counts_the_lost_words_of_its_slide(
        self, content_logs: dict[bool, _Logged]
    ) -> None:
        lines = [
            json.loads(line.split(TEXT_MISSING_PREFIX, 1)[1])
            for line in content_logs[False].stderr.splitlines()
            if TEXT_MISSING_PREFIX in line and "Browser console" not in line
        ]
        assert lines == [{"slideIndex": 0, "words": 1}], lines

    def test_the_validation_warning_names_the_text_box_by_its_length(
        self, content_logs: dict[bool, _Logged]
    ) -> None:
        warnings = [line for line in content_logs[False].stderr.splitlines() if VALIDATION_LINE in line]
        assert warnings, f"fixture drift: no text box too near the bottom edge:\n{content_logs[False].stderr}"
        assert all("characters" in line for line in warnings), warnings

    def test_with_the_flag_every_word_is_logged(self, content_logs: dict[bool, _Logged]) -> None:
        logged = content_logs[True]
        (summary,) = slide_summaries(logged.stderr)
        assert summary["hiddenText"].split() == [HIDDEN_WORD] and summary["hiddenWords"] == 1, summary
        assert text_missing_reports(logged.stderr) == [[LOST_WORD]], logged.stderr[-3000:]
        warnings = [line for line in logged.stderr.splitlines() if VALIDATION_LINE in line]
        assert any(BOTTOM_WORD in line for line in warnings), warnings


@pytest.mark.slow
@requires_huashu_sidecar
class TestAFailedSlideIsLoggedWithoutItsText:
    """Validation not bypassed: the slide fails, its quote in its failure entry alone."""

    @staticmethod
    def _failed(monkeypatch: pytest.MonkeyPatch, debug_text: bool) -> _Logged:
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        documents = [slide_document(ORDINARY_BODY, slide_id="kept"), slide_document(CONTENT_BODY, slide_id="failed")]
        debug = fidelity_harness().sidecar_debug_text() if debug_text else contextlib.nullcontext()
        with _captured_records() as records, teed_stderr() as buffer, debug:
            _, failures = pptx_from_html_huashu.build_pptx_huashu(
                "deck", [{"html": document} for document in documents], bypass_validation=False
            )
        return _Logged(stderr=buffer.getvalue(), records=_formatted(records), failures=failures)

    def test_the_fail_line_quotes_no_text_and_the_entry_keeps_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logged = self._failed(monkeypatch, debug_text=False)
        assert [failure["slide_index"] for failure in logged.failures] == [1], logged.failures
        assert BOTTOM_WORD in logged.failures[0]["error"], logged.failures
        fail_lines = [line for line in logged.stderr.splitlines() if "] FAIL:" in line]
        assert fail_lines and VALIDATION_LINE in fail_lines[0], fail_lines
        found = [word for word in CONTENT_WORDS if word in logged.everything]
        assert not found, f"the log holds {found}:\n{logged.stderr[-3000:]}"

    def test_with_the_flag_the_fail_line_quotes_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logged = self._failed(monkeypatch, debug_text=True)
        fail_lines = [line for line in logged.stderr.splitlines() if "] FAIL:" in line]
        assert any(BOTTOM_WORD in line for line in fail_lines), fail_lines


# Loaded into the sidecar (NODE_OPTIONS --import): every read of a slide's page fails with
# a message holding THROWN_WORD, as a page that throws its own text would make it fail.
THROWING_PAGE_PRELOAD = """
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright-core');
const launch = chromium.launch.bind(chromium);
chromium.launch = async (options) => {
  const browser = await launch(options);
  const newContext = browser.newContext.bind(browser);
  browser.newContext = async (...contextArguments) => {
    const context = await newContext(...contextArguments);
    const newPage = context.newPage.bind(context);
    context.newPage = async (...pageArguments) => {
      const page = await newPage(...pageArguments);
      page.evaluate = async () => { throw new Error(%(message)s); };
      return page;
    };
    return context;
  };
  return browser;
};
"""


@pytest.mark.slow
@requires_huashu_sidecar
class TestAPagesFailureIsLoggedWithoutItsMessage:
    @staticmethod
    def _thrown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, debug_text: bool) -> _Logged:
        preload = tmp_path / "throwing_page.mjs"
        preload.write_text(
            THROWING_PAGE_PRELOAD
            % {
                "sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_SCRIPT)),
                "message": json.dumps(f"the page threw {THROWN_WORD}"),
            },
            encoding="utf-8",
        )
        sidecar_env = pptx_from_html_huashu.sidecar_subprocess_env
        monkeypatch.setattr(
            pptx_from_html_huashu,
            "sidecar_subprocess_env",
            lambda: {**sidecar_env(), "NODE_OPTIONS": f"--import={preload.as_uri()}"},
        )
        return _export([slide_document(ORDINARY_BODY)], monkeypatch, debug_text=debug_text)

    def test_its_lines_say_the_message_by_its_length(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logged = self._thrown(tmp_path, monkeypatch, debug_text=False)
        assert len(logged.failures) == 1 and THROWN_WORD in logged.failures[0]["error"], logged.failures
        assert THROWN_WORD not in logged.everything, logged.stderr[-3000:]
        assert any("] FAIL:" in line for line in logged.stderr.splitlines()), logged.stderr[-3000:]

    def test_with_the_flag_its_lines_carry_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logged = self._thrown(tmp_path, monkeypatch, debug_text=True)
        fail_lines = [line for line in logged.stderr.splitlines() if "] FAIL:" in line]
        assert any(THROWN_WORD in line for line in fail_lines), logged.stderr[-3000:]


# A slide whose script logs a long message, then many short ones, each with the engine's
# own [html2pptx] prefix, which sends a page's message to stderr.
LONG_MESSAGE_CHARACTERS = 5000
SHORT_MESSAGES = 300
FLOODING_BODY = (
    '<div class="slide"><h1>Flood</h1><script>'
    f"console.warn('[html2pptx] long ' + 'x'.repeat({LONG_MESSAGE_CHARACTERS}));"
    f"for (let n = 0; n < {SHORT_MESSAGES}; n++) console.warn('[html2pptx] note ' + n);"
    "</script></div>"
)
BROWSER_CONSOLE = "Browser console: "


def _page_limits() -> dict:
    return node_json(
        f"const m = require({json.dumps(str(RENDER_SLIDE))});"
        "console.log(JSON.stringify({ length: m.PAGE_MESSAGE_LIMIT, count: m.PAGE_MESSAGES_PER_SLIDE }));"
    )


# A slide whose script logs its own words at three levels, once with the engine's
# [html2pptx] prefix, once with [preprocess], once with neither.
CONSOLE_WORD = "Zyqconsoleword"
CONSOLE_BODY = (
    '<div class="slide"><h1>Console</h1><script>'
    f"console.warn('[html2pptx] {CONSOLE_WORD} warned');"
    f"console.error('[preprocess] {CONSOLE_WORD} errored');"
    f"console.log('{CONSOLE_WORD} logged');"
    "</script></div>"
)
PAGE_CONSOLE_LINE = "[html2pptx] page console: "
PAGE_CONSOLE_COUNTS = re.compile(
    r"(?P<messages>\d+) message\(s\) \((?P<levels>[^)]*)\), (?P<engine>\d+) with the engine's prefix"
)


@pytest.mark.slow
@requires_huashu_sidecar
class TestWhatAPageLogsIsCounted:
    def test_without_the_flag_no_word_a_page_logs_is_logged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slide's script logs its words, under the engine's prefixes too: none is logged.

        What a page logs is its own text, whatever its prefix: the wrapper
        prints nothing of it and logs no record of it. One line counts the
        slide's messages by level, and how many carry the engine's prefix.
        """
        logged = _export([slide_document(CONSOLE_BODY)], monkeypatch, debug_text=False)
        assert logged.failures == [], logged.failures

        assert CONSOLE_WORD not in logged.everything, (
            f"a word the page logged is in the log:\n{logged.everything[-3000:]}"
        )
        counted = [line for line in logged.stderr.splitlines() if PAGE_CONSOLE_LINE in line]
        assert len(counted) == 1, counted
        match = PAGE_CONSOLE_COUNTS.search(counted[0])
        assert match, counted[0]
        levels = {
            level: int(count)
            for count, level in (part.split(" ") for part in match.group("levels").split(", "))
        }
        # The deck's own chart script logs one message on every slide besides the slide's three.
        assert levels["error"] == 1 and levels["warning"] == 1 and levels["log"] >= 1, levels
        assert int(match.group("messages")) == sum(levels.values()), counted[0]
        assert int(match.group("engine")) == 2, counted[0]

    def test_with_the_flag_what_a_page_logs_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ``TELLR_EXPORT_DEBUG_TEXT=1`` each message is forwarded, one line each.

        The prefixed messages go to stderr behind "Browser console:", which
        the wrapper echoes; the unprefixed one goes to stdout. Nothing counts
        them.
        """
        logged = _export([slide_document(CONSOLE_BODY)], monkeypatch, debug_text=True)
        assert logged.failures == [], logged.failures

        forwarded = [line for line in logged.stderr.splitlines() if CONSOLE_WORD in line]
        assert len(forwarded) == 2 and all(BROWSER_CONSOLE in line for line in forwarded), forwarded
        assert [line for line in logged.stderr.splitlines() if PAGE_CONSOLE_LINE in line] == []


@pytest.mark.slow
@requires_huashu_sidecar
class TestWhatAPageLogsIsBounded:
    def test_each_message_is_cut_and_a_slide_logs_a_bounded_number(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the flag, what a page logs is forwarded within its bounds."""
        limits = _page_limits()
        logged = export_logged(
            [slide_document(FLOODING_BODY)], monkeypatch=monkeypatch, debug_text=True
        )
        forwarded = [
            line.split(BROWSER_CONSOLE, 1)[1]
            for line in logged.stderr.splitlines()
            if BROWSER_CONSOLE in line
        ]
        assert len(forwarded) == limits["count"], len(forwarded)
        longest = max(len(text) for text in forwarded)
        assert longest < limits["length"] + 64, longest
        withheld = [line for line in logged.stderr.splitlines() if "page console:" in line]
        assert len(withheld) == 1 and str(SHORT_MESSAGES + 1 - limits["count"]) in withheld[0], withheld


# ---------------------------------------------------------------------------
# The flag: one name, and no app passes it
# ---------------------------------------------------------------------------


@requires_node
def test_the_flag_is_one_name_in_node_and_python() -> None:
    node = node_json(
        f"console.log(JSON.stringify(require({json.dumps(str(LOG_LINE_MODULE))}).DEBUG_TEXT_ENV));"
    )
    assert node == pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV == "TELLR_EXPORT_DEBUG_TEXT"


def test_no_app_passes_the_flag_to_its_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV, "1")
    assert pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV not in pptx_from_html_huashu._SIDECAR_ENV_ALLOWLIST
    assert pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV not in pptx_from_html_huashu.sidecar_subprocess_env()


def test_the_harness_passes_it_for_its_own_runs_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    flag = pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV
    monkeypatch.delenv(flag, raising=False)
    with fidelity_harness().sidecar_debug_text():
        assert pptx_from_html_huashu.sidecar_subprocess_env()[flag] == "1"
    assert flag not in pptx_from_html_huashu.sidecar_subprocess_env()
    assert flag not in pptx_from_html_huashu._SIDECAR_ENV_ALLOWLIST
