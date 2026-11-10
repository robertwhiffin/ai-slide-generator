# ruff: noqa: F811 — the library fixture is imported, then requested by name.
"""The ``generate_image`` rulings added after the Unit G tests were written (R6, R7, R8, R11).

Contract: ``docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md``.

* **R6.**  A job whose ``generate`` returned before the wall claims its save; a claimed
  job is waited for, so a row that was saved is reported with its reference, never as
  "did not finish in time".
* **R7.**  An abandoned straggler keeps its semaphore slot until it really finishes, so
  real concurrency never exceeds ``MAX_CONCURRENT``.
* **R8.**  No owner: refused, nothing started.
* **R11.**  Options are numbered from ``ImageToolContext.first_option``.

The doubles and the real-SQLite library are ``test_image_generation_tool``'s.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.services.agent_tools import image_generation_tool as tool_module
from src.services.agent_tools.image_generation_tool import FAIL_TIMEOUT, MAX_CONCURRENT
from tests.unit.test_image_generation_tool import (  # noqa: F401 — fixtures by name
    REF_RE,
    FakeGenerator,
    _assert_refused,
    _assert_spotlighted,
    _in_background,
    _no_real_gateway,
    _run,
    _tool,
    library,
)

# ---------------------------------------------------------------------------
# R8: no owner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("owner", [None, ""], ids=["none", "empty"])
def test_no_owner_is_refused_and_starts_nothing(library, owner):
    progress: list = []
    fake = FakeGenerator()
    tool = _tool(fake, owner=owner, on_call=lambda k, n: progress.append((k, n)))

    result = _run(tool, kind="illustration", count=3)

    _assert_refused(result, fake, tool)
    assert progress == []
    assert library.rows() == []
    assert (tool.calls, tool.images) == (0, 0)


# ---------------------------------------------------------------------------
# R6: a claimed save is waited for and reported as saved
# ---------------------------------------------------------------------------


def test_a_save_still_running_at_the_wall_is_reported_as_saved(library, monkeypatch):
    """``generate`` returns at once; the save takes 1.5 s against a 1 s wall.  The job
    claimed its save before the wall, so ``run`` waits for it and reports the row."""
    monkeypatch.setattr(tool_module, "MIN_START_SECONDS", 0.1)
    fake = FakeGenerator(["ok"])
    saved: list[str] = []

    def slow_save(img, **kwargs: Any) -> str:
        time.sleep(1.5)
        token = tool_module.save_to_library(img, **kwargs)
        saved.append(token)
        return token

    tool = _tool(fake, seconds_left=1.0, save=slow_save)

    result = _run(tool, kind="illustration", count=1)

    body = _assert_spotlighted(result)
    (row,) = library.rows()
    assert saved == [row["token"]]
    assert FAIL_TIMEOUT not in body, body
    assert REF_RE.findall(body) == [row["token"]]
    assert tool.saved_tokens() == [row["token"]]


# ---------------------------------------------------------------------------
# R7: an abandoned straggler keeps its slot
# ---------------------------------------------------------------------------


def test_an_abandoned_straggler_keeps_its_slot_until_it_finishes(library, monkeypatch):
    """A 1 s run leaves one straggler blocked; another run holds three slots.  Two are
    free, so a run asking for three makes two.  Once everything finishes, all
    ``MAX_CONCURRENT`` slots are free again."""
    monkeypatch.setattr(tool_module, "MIN_START_SECONDS", 0.1)
    straggler = FakeGenerator(["block"])
    holder = FakeGenerator(["block"] * 3)
    background: list = []
    try:
        result = _run(_tool(straggler, seconds_left=1.0), kind="icon", count=1)
        assert FAIL_TIMEOUT in _assert_spotlighted(result)
        assert not straggler.block_returned.is_set(), "the straggler is still running"

        background.append(_in_background(_tool(holder), kind="icon", count=3))
        assert holder.wait_started(3), "the holding run started its three generations"

        fake = FakeGenerator()
        made = _run(_tool(fake), kind="background", count=3)

        assert len(fake.calls) == MAX_CONCURRENT - 1 - 3, (
            "the straggler's slot is still taken: only two are free"
        )
        assert len(REF_RE.findall(made)) == 2
    finally:
        straggler.release.set()
        holder.release.set()
        for thread, _ in background:
            thread.join(15)

    assert straggler.block_returned.wait(5)
    for _, box in background:
        assert "error" not in box, box.get("error")
    time.sleep(0.3)  # a moment's grace for the pool threads' ``finally``
    probe = FakeGenerator(["block"] * MAX_CONCURRENT)
    boxes = [_in_background(_tool(probe), kind="icon", count=3) for _ in range(2)]
    try:
        assert probe.wait_started(MAX_CONCURRENT), "every slot is free again"
    finally:
        probe.release.set()
        for thread, _ in boxes:
            thread.join(15)
    for _, box in boxes:
        assert len(REF_RE.findall(box["result"])) == 3


# ---------------------------------------------------------------------------
# R11: numbering from first_option
# ---------------------------------------------------------------------------


def test_options_are_numbered_from_first_option(library):
    fake = FakeGenerator()
    tool = _tool(fake, first_option=4)

    first = _assert_spotlighted(_run(tool, kind="illustration", count=2))
    second = _assert_spotlighted(_run(tool, kind="illustration", count=1))

    assert "Option 4:" in first and "Option 5:" in first
    assert "Option 1:" not in first
    assert "Option 6:" in second
    assert [ref["option"] for ref in tool.generated] == [4, 5, 6]


def test_first_option_defaults_to_one(library):
    fake = FakeGenerator()
    tool = _tool(fake)

    body = _assert_spotlighted(_run(tool, kind="icon", count=2))

    assert "Option 1:" in body and "Option 2:" in body
    assert [ref["option"] for ref in tool.generated] == [1, 2]


# ---------------------------------------------------------------------------
# The time budget is the tool's whole budget, across its calls
# ---------------------------------------------------------------------------


class _SlowGenerator(FakeGenerator):
    """Each ``generate`` takes *delay* seconds (after recording its call)."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    def generate(self, prompt, preset_id, model=None, quality=None, *, timeout_s=None):
        image = super().generate(prompt, preset_id, model, quality, timeout_s=timeout_s)
        time.sleep(self.delay)
        return image


def test_a_second_call_gets_only_what_the_first_left_of_seconds_left(library, monkeypatch):
    """``seconds_left`` is the tool's budget for ALL its calls: on a toolset whose own clock
    runs longer (the image tool beside Gateway tools), a second call must not be handed the
    whole budget again.  4 s budget, the first call takes at least 1 s: the second call's
    wall is at most 3 s, not 4 s."""
    monkeypatch.setattr(tool_module, "MIN_START_SECONDS", 0.1)
    fake = _SlowGenerator(delay=1.0)
    tool = _tool(fake, seconds_left=4.0)

    _run(tool, kind="icon", count=1, remaining=120.0)
    _run(tool, kind="icon", count=1, remaining=120.0)

    first, second = (call["timeout_s"] for call in fake.calls)
    assert first == pytest.approx(4.0, abs=0.05)
    assert second <= first - 1.0 + 0.05, f"the second call was handed {second:.2f}s of a 4s budget"


def test_a_spent_time_budget_refuses_the_next_call(library, monkeypatch):
    monkeypatch.setattr(tool_module, "MIN_START_SECONDS", 0.5)
    fake = _SlowGenerator(delay=1.0)
    tool = _tool(fake, seconds_left=1.2)

    _run(tool, kind="icon", count=1, remaining=120.0)
    result = _run(tool, kind="icon", count=1, remaining=120.0)

    assert len(fake.calls) == 1
    assert REF_RE.search(result) is None
    assert "time" in _assert_spotlighted(result).lower()


# ---------------------------------------------------------------------------
# A prompt of whitespace is no prompt (it would be a paid call with no subject)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prompt", ["   ", "\n\t "], ids=["spaces", "newline-tab"])
def test_a_whitespace_prompt_is_rejected(prompt):
    from pydantic import ValidationError

    from src.services.agent_tools.image_generation_tool import ImageGenerationArgs

    with pytest.raises(ValidationError):
        ImageGenerationArgs(prompt=prompt, kind="icon")


def test_a_prompt_is_stripped():
    from src.services.agent_tools.image_generation_tool import ImageGenerationArgs

    assert ImageGenerationArgs(prompt="  a shield  ", kind="icon").prompt == "a shield"

