"""`extra=` may never carry a reserved LogRecord attribute name.

`logging.Logger.makeRecord` raises `KeyError: "Attempt to overwrite 'X' in
LogRecord"` when an `extra=` dict contains a key that LogRecord already defines.
The raise happens while BUILDING the record, so it is invisible until something
actually emits at that level — and it takes out the calling code, not just the log
line.

Why this needs a test rather than a careful reading
--------------------------------------------------
The collision is latent behind the log level.  Nothing in this app currently sets
the root logger to INFO: `setup_logging()` exists with no caller,
`src/api/_otel_bootstrap.py` says in its own docstring that it is "Loaded first
from main.py" and nothing imports it, and `otel_logging.py` adds a root handler
without a root level.  So the root stays at WARNING, `logger.info()`
short-circuits before `makeRecord`, and the collision never fires — which is
exactly why one lived at `deck_level_writer.py` through a real-model graph run
without incident.

The moment anyone calls the `setup_logging()` that already exists, or wires
`_otel_bootstrap` as its docstring says it should be, every graph turn would start
raising AFTER its `db.flush()` — `write_deck_level_columns` runs twice per turn.

So there are two guards here:

1. `TestTheDeckLevelWriterSurvivesInfoLevel` — emits for real at INFO through the
   writer.  This is the one that would have caught the original defect: it fails
   with the KeyError, in the writer, on the code path a graph turn uses.
2. `TestNoReservedKeyAnywhereInSrc` — an AST sweep of `src/`, so the class cannot
   reappear in a module that has no test of its own.  The reserved set is derived
   from a real LogRecord at runtime rather than hardcoded, so it cannot drift from
   the standard library.

Four sites were fixed when this file was written: `created` in
`deck_level_writer.py` and `filename` in `html_to_google_slides.py` and TWICE in
`html_to_pptx.py`.
"""
from __future__ import annotations

import ast
import contextlib
import logging
from pathlib import Path
from typing import List, Tuple

import pytest
from unittest.mock import patch

from src.api.services.deck_level_writer import write_deck_level_columns
from src.database.models.session import UserSession
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"


def _reserved_names() -> set:
    """The names LogRecord defines, taken from a real record, plus the two that
    `Formatter` adds later (`message`, `asctime`) and that logging also guards.
    """
    record = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
    return set(record.__dict__) | {"message", "asctime"}


@contextlib.contextmanager
def _patched(factory):
    fake = _make_fake_db(factory)
    with patch(_WRITER_DB, fake), patch(_MANAGER_DB, fake):
        yield


@pytest.fixture
def session_without_a_deck():
    """A UserSession with no deck row, and its factory.

    The writer's CREATE branch is the one that reports `created=True`, which is
    where the reserved-key collision lived.
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    try:
        db = factory()
        try:
            db.add(UserSession(session_id="log-probe", created_by="u@example.com"))
            db.commit()
        finally:
            db.close()
        yield factory
    finally:
        engine.dispose()


class TestTheReservedSetIsRealAndTheRaiseIsReal:
    """Guard the premise: if logging stopped raising, these guards mean nothing."""

    def test_created_and_filename_are_reserved(self):
        reserved = _reserved_names()
        assert "created" in reserved
        assert "filename" in reserved
        # And a name we deliberately use is NOT reserved.
        assert "session_id" not in reserved
        assert "row_created" not in reserved
        assert "image_filename" not in reserved

    def test_logging_still_raises_on_a_reserved_key(self):
        """Pins the mechanism this whole file defends against."""
        log = logging.getLogger("tests.reserved-key-probe")
        log.setLevel(logging.INFO)
        log.addHandler(logging.NullHandler())
        with pytest.raises(KeyError, match="Attempt to overwrite 'created'"):
            log.info("boom", extra={"created": 1})


class TestTheDeckLevelWriterSurvivesInfoLevel:
    """The behavioural guard: emit for real, on the graph's write path."""

    def test_a_create_write_logs_at_info_without_raising(
        self, session_without_a_deck, caplog
    ):
        with caplog.at_level(logging.INFO, logger="src.api.services.deck_level_writer"):
            with _patched(session_without_a_deck):
                result = write_deck_level_columns(
                    "log-probe", title="Logged At Info", deck_spec={"title": "x"}
                )

        assert result["created"] is True, (
            "the RETURN key is still 'created' — only the log extra was renamed"
        )
        record = next(
            r for r in caplog.records if r.msg == "Wrote deck-level columns"
        )
        assert record.levelno == logging.INFO, (
            "the record was never built at INFO, so this test could not have seen "
            "the KeyError even if the reserved key were back"
        )
        assert record.row_created is True
        # The reserved attribute is intact and still LogRecord's own float
        # timestamp, not our boolean.
        assert isinstance(record.created, float)

    def test_both_writes_of_a_graph_turn_log_without_raising(
        self, session_without_a_deck, caplog
    ):
        """`write_deck_level_columns` runs twice per turn: create, then update.

        The second call takes the `created=False` branch, so both values of the
        renamed field are emitted.
        """
        with caplog.at_level(logging.INFO, logger="src.api.services.deck_level_writer"):
            with _patched(session_without_a_deck):
                write_deck_level_columns("log-probe", title="Pre fan-out")
                write_deck_level_columns("log-probe", slide_count=3)

        records = [r for r in caplog.records if r.msg == "Wrote deck-level columns"]
        assert len(records) == 2, f"expected two writes, logged {len(records)}"
        assert [r.row_created for r in records] == [True, False]

    def test_the_write_still_happened_at_info_level(
        self, session_without_a_deck, caplog
    ):
        """Paired assertion: emitting at INFO did not break the write itself.

        The original defect raised AFTER `db.flush()`, so a test that only caught
        the exception would still leave the caller's transaction half-reported.
        """
        with caplog.at_level(logging.INFO, logger="src.api.services.deck_level_writer"):
            with _patched(session_without_a_deck):
                write_deck_level_columns(
                    "log-probe", title="Persisted While Logging", slide_count=7
                )

        from src.database.models.session import SessionSlideDeck

        db = session_without_a_deck()
        try:
            deck = db.query(SessionSlideDeck).one()
            assert deck.title == "Persisted While Logging"
            assert deck.slide_count == 7
        finally:
            db.close()


class TestNoReservedKeyAnywhereInSrc:
    """The static sweep, so the class cannot reappear in an untested module."""

    @staticmethod
    def _collisions() -> List[Tuple[str, int, str]]:
        reserved = _reserved_names()
        hits: List[Tuple[str, int, str]] = []
        for path in sorted(_SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover - src must always parse
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "extra" or not isinstance(kw.value, ast.Dict):
                        continue
                    for key in kw.value.keys:
                        if isinstance(key, ast.Constant) and key.value in reserved:
                            hits.append(
                                (
                                    path.relative_to(_REPO_ROOT).as_posix(),
                                    key.lineno,
                                    key.value,
                                )
                            )
        return hits

    def test_the_sweep_actually_finds_extra_dicts(self):
        """Guard the guard: a sweep that parses nothing would pass vacuously."""
        found = 0
        for path in sorted(_SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call):
                    found += sum(
                        1
                        for kw in node.keywords
                        if kw.arg == "extra" and isinstance(kw.value, ast.Dict)
                    )
        assert found > 50, (
            f"only {found} extra= dicts found in src/; the sweep is not reaching "
            "the tree and its clean result would be meaningless"
        )

    def test_no_extra_dict_in_src_uses_a_reserved_key(self):
        collisions = self._collisions()
        assert collisions == [], (
            "extra= carries a reserved LogRecord key; logging will raise KeyError "
            "as soon as anything emits at that level:\n"
            + "\n".join(f"  {f}:{n}  {k!r}" for f, n, k in collisions)
        )
