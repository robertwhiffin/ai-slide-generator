"""Tests for scripts/build_metrics.py: Claude Code transcripts, list-price cost, and the
two anchors of a build window (first task dispatch, end of the final review).

Interface under test (Task 1 of docs/superpowers/plans/2026-11-13-chained-plan-execution.md,
with correction C1 of its PLAN-CORRECTIONS.md):

    ApiCall(ts, family, input, output, cache_read, cache_write)   # frozen dataclasses
    Dispatch(ts, description)
    AgentSpan(description, start, end)
    Transcript(session_ids, calls, dispatches, spans)

    model_family(model_id) -> "opus" | "sonnet" | "haiku" | None
    load_sessions(projects_dir, session_ids) -> Transcript
    find_sessions(projects_dir, needle) -> list[str]                # sorted session ids
    cost_usd(calls, start, end) -> dict[str, float]                 # inclusive window
    first_task_at(t) -> Dispatch | None
    final_review_end(t) -> datetime | None

On-disk layout these tests write (C1 overrides the plan's single-directory layout):

    <projects_dir>/<project dir>/<session_id>.jsonl                          main transcript
    <projects_dir>/<any project dir>/<session_id>/subagents/agent-<id>.jsonl  subagents, any depth
    <projects_dir>/<any project dir>/<session_id>/subagents/agent-<id>.meta.json

A session that enters a worktree has files in two project dirs, so a session's files are
found by session id across every project dir, never by "the dir next to the main file".

Every test uses ``tmp_path`` as the projects dir; nothing reads ``~/.claude``.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.build_metrics as bm
from scripts.build_metrics import (
    AgentSpan,
    ApiCall,
    Dispatch,
    cost_usd,
    final_review_end,
    find_sessions,
    first_task_at,
    load_sessions,
    model_family,
)

OPUS = "system.ai.claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
GPT = "system.ai.gpt-6-1-sol"

# Project dirs as Claude Code names them: the primary checkout, and a worktree of it.
PRIMARY = "-Users-dev-Repos-app"
WORKTREE = "-Users-dev-Repos-app--claude-worktrees-feat"

BASE = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
WIDE_START = BASE - timedelta(days=1)
WIDE_END = BASE + timedelta(days=1)


def at(seconds: float) -> datetime:
    """A timezone-aware UTC instant ``seconds`` after BASE."""
    return BASE + timedelta(seconds=seconds)


def iso(ts: datetime) -> str:
    """ISO-8601 with milliseconds and a ``Z`` suffix, as Claude Code writes it."""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Line builders
# ---------------------------------------------------------------------------


def agent_block(description: str) -> dict:
    return {
        "type": "tool_use",
        "id": "toolu_agent_" + description.replace(" ", "_"),
        "name": "Agent",
        "input": {
            "description": description,
            "prompt": f"You are the {description}.",
            "subagent_type": "general-purpose",
        },
    }


def bash_block(description: str) -> dict:
    """A non-Agent tool call. Bash calls carry an ``input.description`` too."""
    return {
        "type": "tool_use",
        "id": "toolu_bash_" + description.replace(" ", "_"),
        "name": "Bash",
        "input": {"command": "uv run pytest -q", "description": description},
    }


def assistant(
    ts: datetime,
    msg_id: str,
    model: str,
    *,
    input: int = 0,
    output: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    dispatch: str | None = None,
    blocks: tuple[dict, ...] = (),
) -> dict:
    """One assistant transcript line. ``dispatch`` adds an Agent tool_use block."""
    content = list(blocks)
    if dispatch is not None:
        content.append(agent_block(dispatch))
    if not content:
        content = [{"type": "text", "text": "Working on it."}]
    return {
        "type": "assistant",
        "timestamp": iso(ts),
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": None,
            "usage": {
                "input_tokens": input,
                "output_tokens": output,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
                # Real transcripts also carry this breakdown of the cache write. It is the
                # same tokens again, so it must not be added on top.
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_write,
                    "ephemeral_1h_input_tokens": 0,
                },
                "service_tier": "standard",
            },
        },
    }


def user(ts: datetime, text: str) -> dict:
    """One user transcript line (a prompt, or a subagent's opening brief)."""
    return {
        "type": "user",
        "timestamp": iso(ts),
        "message": {"role": "user", "content": text},
    }


def tool_result(ts: datetime, text: str = "done") -> dict:
    return {
        "type": "user",
        "timestamp": iso(ts),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_x", "content": text}],
        },
    }


def _write_jsonl(path: Path, lines: list) -> None:
    """Dicts are JSON-encoded; a ``str`` is written verbatim (e.g. a truncated line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def write_session(
    root: Path,
    session_id: str,
    main_lines: list,
    subagents: dict[str, tuple] | None = None,
    *,
    project: str = PRIMARY,
) -> None:
    """Write one session under ``root`` (the projects dir).

    ``subagents`` maps agent id -> ``(description, lines)`` or
    ``(description, lines, extra)``. ``extra`` is a dict of additional meta keys
    (``parentAgentId``, ``spawnDepth``) plus an optional ``"project"``: the project dir
    to write that subagent under, which defaults to the main transcript's ``project``.
    """
    _write_jsonl(root / project / f"{session_id}.jsonl", main_lines)
    for agent_id, spec in (subagents or {}).items():
        description, lines, *rest = spec
        extra = dict(rest[0]) if rest else {}
        sub_project = extra.pop("project", project)
        sub_dir = root / sub_project / session_id / "subagents"
        _write_jsonl(sub_dir / f"agent-{agent_id}.jsonl", lines)
        meta = {"description": description, **extra}
        (sub_dir / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))


def write_decoy_session(root: Path, session_id: str, *, project: str, sub_project: str) -> None:
    """Another session in the same projects dir, with calls, dispatches and a subagent of
    its own. Loading one session must not pick any of this up."""
    write_session(
        root,
        session_id,
        [
            user(at(1), "An unrelated session."),
            assistant(
                at(2), f"{session_id}-m1", OPUS, input=777, output=777, dispatch="Task 7 supervisor"
            ),
        ],
        {
            f"{session_id}x": (
                "Task 7 supervisor",
                [
                    user(at(3), "Unrelated subagent."),
                    assistant(at(4), f"{session_id}-s1", SONNET, output=888),
                ],
                {"project": sub_project},
            )
        },
        project=project,
    )


def session_cost(root: Path, session_id: str, lines: list) -> dict[str, float]:
    """Write a main-only session, load it, and cost it over a window that covers it all."""
    write_session(root, session_id, lines)
    return cost_usd(load_sessions(root, [session_id]).calls, WIDE_START, WIDE_END)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_split_message_counted_once(tmp_path):
    # One API response streamed as two lines (a text block, then a tool_use block) that
    # repeat the same message id and usage. It is one call, but neither line's content is
    # thrown away: the dispatch on the repeat line still counts.
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Execute the plan."),
            assistant(at(10), "msg_split", OPUS, output=1000),
            assistant(at(11), "msg_split", OPUS, output=1000, dispatch="Task 1 supervisor"),
        ],
    )

    t = load_sessions(tmp_path, ["S"])

    assert cost_usd(t.calls, at(0), at(60)) == {"opus": pytest.approx(0.02)}
    assert len(t.calls) == 1
    assert list(t.dispatches) == [Dispatch(ts=at(11), description="Task 1 supervisor")]


def test_model_ids_are_classified_by_family(tmp_path):
    assert model_family("system.ai.claude-opus-5-5") == "opus"
    assert model_family("claude-sonnet-5-5") == "sonnet"
    assert model_family("claude-haiku-5-5") == "haiku"
    assert model_family("<synthetic>") is None
    assert model_family("system.ai.gpt-6-1-sol") is None

    cost = session_cost(
        tmp_path,
        "S",
        [
            assistant(at(0), "m_gpt", GPT, input=1_000_000, output=1_000_000),
            assistant(at(1), "m_haiku", HAIKU, output=1_000_000),
        ],
    )

    assert set(cost) == {"haiku"}
    # The gpt call costs nothing and is not folded into any priced family.
    assert cost == {"haiku": pytest.approx(0.5)}


def test_cost_prices_every_token_kind(tmp_path):
    # The plan's two cases: 1,000,000 of every token kind in one call.
    assert session_cost(
        tmp_path,
        "opus-all",
        [
            assistant(
                at(0), "m1", OPUS, input=10**6, output=10**6, cache_read=10**6, cache_write=10**6
            )
        ],
    ) == {"opus": pytest.approx(32.2)}
    assert session_cost(
        tmp_path,
        "sonnet-all",
        [
            assistant(
                at(0), "m2", SONNET, input=10**6, output=10**6, cache_read=10**6, cache_write=10**6
            )
        ],
    ) == {"sonnet": pytest.approx(16.1)}

    # Equal counts of every kind cannot tell a swapped price apart (input <-> cache write
    # sums the same), so price each usage key on its own. List prices, $ per million.
    one_kind_at_a_time = [
        (OPUS, "opus", "input", 4.00),
        (OPUS, "opus", "output", 20.00),
        (OPUS, "opus", "cache_read", 0.20),
        (OPUS, "opus", "cache_write", 8.00),
        (SONNET, "sonnet", "input", 2.00),
        (SONNET, "sonnet", "output", 10.00),
        (SONNET, "sonnet", "cache_read", 0.10),
        (SONNET, "sonnet", "cache_write", 4.00),
        (HAIKU, "haiku", "input", 0.10),
        (HAIKU, "haiku", "output", 0.50),
        (HAIKU, "haiku", "cache_read", 0.01),
        (HAIKU, "haiku", "cache_write", 0.20),
    ]
    for i, (model, family, kind, expected) in enumerate(one_kind_at_a_time):
        got = session_cost(
            tmp_path, f"kind-{i}", [assistant(at(0), f"k{i}", model, **{kind: 10**6})]
        )
        assert got == {family: pytest.approx(expected)}, (model, kind)


def test_cost_window_is_inclusive(tmp_path):
    start, end = at(100), at(200)
    write_session(
        tmp_path,
        "S",
        [
            assistant(start - timedelta(seconds=1), "before", OPUS, output=1_000_000),
            assistant(start, "at-start", OPUS, output=1_000_000),
            assistant(end, "at-end", OPUS, output=1_000_000),
            assistant(end + timedelta(seconds=1), "after", OPUS, output=1_000_000),
        ],
    )

    t = load_sessions(tmp_path, ["S"])

    assert cost_usd(t.calls, start, end) == {"opus": pytest.approx(40.0)}


def test_subagents_at_any_depth_are_loaded(tmp_path):
    # Main dispatches a supervisor; the supervisor dispatches a nested reviewer, whose
    # file sits flat in the same subagents/ dir with a parentAgentId in its meta.
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Execute the plan."),
            assistant(
                at(5),
                "m-main",
                OPUS,
                input=11,
                output=12,
                cache_read=13,
                cache_write=14,
                dispatch="Task 1 supervisor",
            ),
            # A session that is still running can end on a half-written line.
            '{"type": "assistant", "timestamp": "2026-11-17T09:10:00.000Z", '
            '"message": {"id": "m-tr',
        ],
        {
            "a1": (
                "Task 1 supervisor",
                [
                    user(at(6), "You are the Task 1 supervisor."),
                    assistant(
                        at(30),
                        "m-sup",
                        SONNET,
                        input=21,
                        output=22,
                        cache_read=23,
                        cache_write=24,
                        dispatch="Review Task 1",
                    ),
                    tool_result(at(300), "Review passed."),
                ],
            ),
            "a2": (
                "Review Task 1",
                [
                    user(at(31), "You are the Task 1 reviewer."),
                    assistant(
                        at(120), "m-rev", HAIKU, input=31, output=32, cache_read=33, cache_write=34
                    ),
                ],
                {"parentAgentId": "a1", "spawnDepth": 2},
            ),
        },
    )
    write_decoy_session(tmp_path, "OTHER", project=PRIMARY, sub_project=PRIMARY)

    t = load_sessions(tmp_path, ["S"])

    assert tuple(t.session_ids) == ("S",)
    assert len(t.calls) == 3
    assert set(t.calls) == {
        ApiCall(ts=at(5), family="opus", input=11, output=12, cache_read=13, cache_write=14),
        ApiCall(ts=at(30), family="sonnet", input=21, output=22, cache_read=23, cache_write=24),
        ApiCall(ts=at(120), family="haiku", input=31, output=32, cache_read=33, cache_write=34),
    }
    assert len(t.spans) == 2
    # A span runs from the subagent file's first line to its last line, whatever their
    # type; its description comes from the meta file.
    assert set(t.spans) == {
        AgentSpan(description="Task 1 supervisor", start=at(6), end=at(300)),
        AgentSpan(description="Review Task 1", start=at(31), end=at(120)),
    }
    # Dispatches are collected from the main transcript and from subagent transcripts.
    assert set(t.dispatches) == {
        Dispatch(ts=at(5), description="Task 1 supervisor"),
        Dispatch(ts=at(30), description="Review Task 1"),
    }


def test_find_sessions_matches_needle_in_main_or_subagent(tmp_path):
    needle = "docs/superpowers/plans/x.md"
    # Written C, B, A so the expected order comes from sorting, not from write order.
    write_session(
        tmp_path,
        "C",
        [
            user(at(0), "Execute docs/superpowers/plans/y.md with subagents."),
            assistant(at(1), "c1", OPUS, dispatch="Task 1 supervisor"),
        ],
        {
            "c-a1": (
                "Task 1 supervisor",
                [user(at(2), "Read x.md and plans/ for context."), assistant(at(3), "c2", SONNET)],
            )
        },
    )
    write_session(
        tmp_path,
        "B",
        [
            user(at(0), "Carry on with the build."),
            assistant(at(1), "b1", OPUS, dispatch="Task 1 supervisor"),
        ],
        {
            "b-a1": (
                "Task 1 supervisor",
                [
                    user(at(2), f"Implement Task 1 of {needle}."),
                    assistant(at(3), "b2", SONNET),
                ],
            )
        },
    )
    # A names the plan in its main transcript, and again in each brief it hands out.
    # It is still one session.
    write_session(
        tmp_path,
        "A",
        [
            user(at(0), "Morning."),
            user(at(1), f"Execute the plan at {needle} with subagents."),
            assistant(at(2), "a1", OPUS, dispatch="Task 1 supervisor"),
            assistant(at(9), "a2", OPUS, dispatch="Task 2 supervisor"),
        ],
        {
            "a-t1": (
                "Task 1 supervisor",
                [user(at(3), f"Supervise Task 1 of {needle}."), assistant(at(4), "a3", SONNET)],
            ),
            "a-t2": (
                "Task 2 supervisor",
                [user(at(10), f"Supervise Task 2 of {needle}."), assistant(at(11), "a4", SONNET)],
            ),
        },
    )

    assert find_sessions(tmp_path, needle) == ["A", "B"]


def test_first_task_at_ignores_prepass_and_exploration(tmp_path):
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Execute the plan."),
            assistant(at(10), "m0", OPUS, dispatch="Explore tests dir"),  # t0
            # Not a dispatch: a Bash call whose description mentions Task 1.
            assistant(at(15), "m-bash", OPUS, blocks=(bash_block("Baseline for Task 1 tests"),)),
            assistant(at(20), "m1", OPUS, dispatch="Pre-pass"),  # t1
            assistant(at(30), "m2", OPUS, dispatch="Task 1 supervisor"),  # t2
            assistant(at(40), "m3", OPUS, dispatch="Task 2 supervisor"),  # t3
        ],
        {
            # The supervisor's own later dispatch also matches TASK_RE; the earliest
            # matching dispatch is chosen by time, not by which file is read first.
            "sup1": (
                "Task 1 supervisor",
                [
                    user(at(31), "You are the Task 1 supervisor."),
                    assistant(at(35), "s1", SONNET, dispatch="Task 1 implementer"),
                    tool_result(at(38)),
                ],
            ),
        },
    )

    assert first_task_at(load_sessions(tmp_path, ["S"])) == Dispatch(
        ts=at(30), description="Task 1 supervisor"
    )

    # The same build resumed in a second session. Session ids sort in no time order, so
    # "earliest" is by timestamp across every loaded session, not by load order.
    write_session(
        tmp_path,
        "0-resumed",
        [
            user(at(900), "Resume the build from the ledger."),
            assistant(at(910), "r1", OPUS, dispatch="Task 3 supervisor"),
        ],
    )
    assert first_task_at(load_sessions(tmp_path, ["0-resumed", "S"])) == Dispatch(
        ts=at(30), description="Task 1 supervisor"
    )

    write_session(
        tmp_path,
        "T9",
        [user(at(0), "Go."), assistant(at(50), "t9", OPUS, dispatch="T9 docs writer")],
    )
    assert first_task_at(load_sessions(tmp_path, ["T9"])) == Dispatch(
        ts=at(50), description="T9 docs writer"
    )

    write_session(
        tmp_path,
        "NOTASK",
        [
            assistant(at(10), "n0", OPUS, dispatch="Explore tests dir"),
            assistant(at(20), "n1", OPUS, dispatch="Pre-pass"),
        ],
    )
    assert first_task_at(load_sessions(tmp_path, ["NOTASK"])) is None


def test_final_review_end_is_last_matching_span_end(tmp_path):
    t5, t6, t7, t8 = at(500), at(600), at(700), at(800)
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Execute the plan."),
            assistant(at(90), "m-final", OPUS, dispatch="Final agent"),
            assistant(at(110), "m-rev2", OPUS, dispatch="Review Task 2"),
        ],
        {
            "fa": (
                "Final agent",
                [
                    user(at(91), "You are the final agent."),
                    assistant(at(95), "fa1", OPUS, dispatch="Final branch review"),
                    assistant(at(605), "fa2", OPUS, dispatch="Final review re-run"),
                    tool_result(t8, "PR marked ready for review."),
                ],
            ),
            "fbr": (
                "Final branch review",
                [user(at(96), "Review the whole branch."), assistant(t5, "fbr1", OPUS)],
                {"parentAgentId": "fa", "spawnDepth": 2},
            ),
            "rt2": (
                "Review Task 2",
                [user(at(111), "Review Task 2."), assistant(t6, "rt21", SONNET)],
            ),
            "frr": (
                "Final review re-run",
                [user(at(606), "Review the branch again."), assistant(t7, "frr1", OPUS)],
                {"parentAgentId": "fa", "spawnDepth": 2},
            ),
        },
    )

    assert final_review_end(load_sessions(tmp_path, ["S"])) == t7

    write_session(
        tmp_path,
        "ONLY-FINAL-AGENT",
        [user(at(0), "Go."), assistant(at(1), "o1", OPUS, dispatch="Final agent")],
        {
            "fa": (
                "Final agent",
                [user(at(2), "You are the final agent."), assistant(t8, "o2", OPUS)],
            )
        },
    )
    assert final_review_end(load_sessions(tmp_path, ["ONLY-FINAL-AGENT"])) is None

    write_session(tmp_path, "NO-SPANS", [user(at(0), "Go."), assistant(at(1), "n1", OPUS)])
    assert final_review_end(load_sessions(tmp_path, ["NO-SPANS"])) is None


def test_session_split_across_project_dirs_is_loaded(tmp_path):
    # The session starts in the primary checkout and explores there (that subagent stays
    # under PRIMARY/S/subagents/), then enters a worktree: the main transcript moves to
    # WORKTREE/S.jsonl and later subagents are written under WORKTREE/S/subagents/.
    needle = "docs/superpowers/plans/x.md"
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Build the feature."),
            assistant(at(30), "m-main", OPUS, input=1, output=2, cache_read=3, cache_write=4),
        ],
        {
            "explore": (
                "Explore plan",
                [
                    user(at(2), f"Summarise {needle} for the controller."),
                    assistant(
                        at(10), "m-explore", SONNET, input=5, output=6, cache_read=7, cache_write=8
                    ),
                    tool_result(at(20)),
                ],
                {"project": PRIMARY},
            ),
            "sup1": (
                "Task 1 supervisor",
                [
                    user(at(40), "You are the Task 1 supervisor."),
                    assistant(
                        at(50), "m-sup", HAIKU, input=9, output=10, cache_read=11, cache_write=12
                    ),
                    tool_result(at(90)),
                ],
            ),
        },
        project=WORKTREE,
    )
    # Another session split the same way across the same two dirs.
    write_decoy_session(tmp_path, "OTHER", project=PRIMARY, sub_project=WORKTREE)
    expected_calls = {
        ApiCall(ts=at(30), family="opus", input=1, output=2, cache_read=3, cache_write=4),
        ApiCall(ts=at(10), family="sonnet", input=5, output=6, cache_read=7, cache_write=8),
        ApiCall(ts=at(50), family="haiku", input=9, output=10, cache_read=11, cache_write=12),
    }

    t = load_sessions(tmp_path, ["S"])

    assert tuple(t.session_ids) == ("S",)
    assert set(t.calls) == expected_calls
    assert len(t.calls) == 3
    assert set(t.spans) == {
        AgentSpan(description="Explore plan", start=at(2), end=at(20)),
        AgentSpan(description="Task 1 supervisor", start=at(40), end=at(90)),
    }
    assert len(t.spans) == 2
    # The needle is only in the subagent left behind in the primary checkout's dir, which
    # holds no main transcript for S.
    assert find_sessions(tmp_path, needle) == ["S"]

    # Now a stale copy of the start of S's main transcript turns up in the old dir. Calls
    # are de-duplicated by message id across all of a session's files, so it adds nothing.
    _write_jsonl(
        tmp_path / PRIMARY / "S.jsonl",
        [
            user(at(0), "Build the feature."),
            assistant(at(30), "m-main", OPUS, input=1, output=2, cache_read=3, cache_write=4),
        ],
    )
    t = load_sessions(tmp_path, ["S"])
    assert len(t.calls) == 3
    assert set(t.calls) == expected_calls
    assert find_sessions(tmp_path, needle) == ["S"]


# ---------------------------------------------------------------------------
# Task 2: GitHub PR data, the baseline handover, and edits after it
# ---------------------------------------------------------------------------
#
# Interface under test (Task 2 of the plan):
#
#     REPO = "robertwhiffin/ai-slide-generator"
#     PARKED_RE = re.compile(r"^Parked-task:\s*\S+", re.M)
#     Commit(sha, committed_at, parents, lines, message)           # frozen dataclasses
#     PullRequest(number, created_at, merged_at, body, commits)    # commits: tuple[Commit, ...]
#     Edits(commits, lines, share, parked_commits, parked_lines)
#
#     fetch_pr(number, *, repo=REPO, gh=gh_json) -> PullRequest
#     baseline_handover(pr, t) -> datetime
#     edits_after(pr, handover) -> Edits
#
# The Task 2 names are reached through ``bm`` rather than imported at the top, so that
# while they are missing only these tests fail and Task 1's still run. ``gh`` is always
# a fake here: no test runs the real ``gh`` or touches the network.

H = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)  # the handover in edits tests
HOUR = timedelta(hours=1)


class FakeGh:
    """Stands in for ``gh api <args>``, answering only the calls in ``responses``.

    ``responses`` maps ``tuple(args)`` to the parsed JSON ``gh`` would print. Any other
    call raises. Every call is recorded in ``calls``, so a test can check the sequence
    (an implementation that swallows the error still leaves the bad call on record).
    """

    def __init__(self, responses: dict[tuple[str, ...], object]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str]) -> object:
        key = tuple(args)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"unexpected gh api call: {list(args)!r}")
        # A copy, so an implementation that mutates what it is given cannot alter the fixture.
        return copy.deepcopy(self.responses[key])


def gh_time(ts: datetime) -> str:
    """GitHub's timestamp format: whole seconds, UTC, ``Z`` suffix."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_listed_commit(
    sha: str, *, authored: datetime, committed: datetime, parents: int, message: str
) -> dict:
    """A commit as ``pulls/{n}/commits`` lists it. The listing carries no ``stats``."""
    person = {"name": "Robert Whiffin", "email": "dev@example.com"}
    return {
        "sha": sha,
        "node_id": "C_kwDO" + sha[:12],
        "commit": {
            # The author date is when the change was first written; the committer date
            # moves on every rebase or amend. They differ here on purpose.
            "author": {**person, "date": gh_time(authored)},
            "committer": {**person, "date": gh_time(committed)},
            "message": message,
            "comment_count": 0,
        },
        "author": {"login": "robertwhiffin"},
        "committer": {"login": "robertwhiffin"},
        "parents": [
            {"sha": f"{i + 1:040x}", "url": f"https://api.github.com/commits/{i + 1:040x}"}
            for i in range(parents)
        ],
    }


def gh_commit_detail(listed: dict, *, additions: int, deletions: int, files: list[dict]) -> dict:
    """The same commit as ``commits/{sha}`` returns it, with ``stats`` and ``files``."""
    return {
        **listed,
        "stats": {"total": additions + deletions, "additions": additions, "deletions": deletions},
        "files": files,
    }


def gh_file(name: str, additions: int, deletions: int) -> dict:
    return {
        "filename": name,
        "status": "modified",
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
    }


def assert_utc_aware(ts: datetime) -> None:
    assert isinstance(ts, datetime), ts
    assert ts.tzinfo is not None, f"{ts!r} is naive"
    assert ts.utcoffset() == timedelta(0), ts


def commit(sha: str, when: datetime, lines: int, *, parents: int = 1, message: str | None = None):
    return bm.Commit(
        sha=sha,
        committed_at=when,
        parents=parents,
        lines=lines,
        message=f"fix: {sha}" if message is None else message,
    )


def pr_with(*commits, created_at: datetime = H - 3 * HOUR):
    return bm.PullRequest(
        number=412,
        created_at=created_at,
        merged_at=H + 4 * HOUR,
        body="## Handover\n\nReady for review.",
        commits=tuple(commits),
    )


def brief_commits() -> tuple:
    """The brief's three commits: an hour before the handover (100 lines), exactly at it
    (10), and an hour after it (30). 140 lines in all.

    Listed out of time order on purpose: GitHub lists a PR's commits in graph order, and
    committer dates need not follow it. Edits are picked by time, not by position.
    """
    return (
        commit("after", H + HOUR, 30, message="fix: export keeps slide notes"),
        commit("before", H - HOUR, 100, message="feat: export deck to PPTX"),
        commit("at", H, 10, message="test: cover export of notes"),
    )


def test_fetch_pr_parses_commits_and_lines():
    repo = "robertwhiffin/ai-slide-generator"  # REPO, the default
    work_sha = "3f9c2a1e7b6d5c4f8a0e9d1b2c3a4f5e6d7c8b9a"
    merge_sha = "c0ffee5a1b2c3d4e5f60718293a4b5c6d7e8f901"
    opened = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)
    merged = datetime(2026, 11, 14, 16, 30, 0, tzinfo=timezone.utc)
    work_at = opened - timedelta(hours=1)
    merge_at = opened + timedelta(hours=5)
    work_message = "feat: export deck to PPTX\n\nAdds the export button and its endpoint."
    merge_message = "Merge branch 'main' into feat/export"
    body = "## Handover\n\nAll tasks done; waiting on a browser check."

    work = gh_listed_commit(
        work_sha,
        authored=work_at - timedelta(hours=2),
        committed=work_at,
        parents=1,
        message=work_message,
    )
    merge = gh_listed_commit(
        merge_sha,
        authored=merge_at - timedelta(minutes=10),
        committed=merge_at,
        parents=2,
        message=merge_message,
    )
    pull = {
        "number": 412,
        "title": "feat: export deck to PPTX",
        "state": "closed",
        "draft": False,
        "user": {"login": "robertwhiffin"},
        "created_at": gh_time(opened),
        "updated_at": gh_time(merged),
        "closed_at": gh_time(merged),
        "merged_at": gh_time(merged),
        "body": body,
    }
    pull_call = (f"repos/{repo}/pulls/412",)
    list_call = (f"repos/{repo}/pulls/412/commits?per_page=100", "--paginate", "--slurp")
    gh = FakeGh(
        {
            pull_call: pull,
            # --slurp wraps the pages in one outer list: here, one commit per page.
            list_call: [[work], [merge]],
            (f"repos/{repo}/commits/{work_sha}",): gh_commit_detail(
                work,
                additions=100,
                deletions=20,
                files=[gh_file("src/export.py", 90, 15), gh_file("tests/test_export.py", 10, 5)],
            ),
            # A merge of main touches many files and GitHub truncates ``files``, so only
            # ``stats.total`` holds the whole commit.
            (f"repos/{repo}/commits/{merge_sha}",): gh_commit_detail(
                merge,
                additions=2000,
                deletions=300,
                files=[gh_file("src/other.py", 40, 2)],
            ),
        }
    )

    pr = bm.fetch_pr(412, gh=gh)

    assert gh.calls[:2] == [pull_call, list_call]
    # Then one detail call per commit, for its ``stats.total``, and nothing else.
    assert sorted(gh.calls[2:]) == [
        (f"repos/{repo}/commits/{work_sha}",),
        (f"repos/{repo}/commits/{merge_sha}",),
    ]
    assert_utc_aware(pr.created_at)
    assert_utc_aware(pr.merged_at)
    for c in pr.commits:
        assert_utc_aware(c.committed_at)
    assert pr == bm.PullRequest(
        number=412,
        created_at=opened,
        merged_at=merged,
        body=body,
        commits=(
            bm.Commit(
                sha=work_sha, committed_at=work_at, parents=1, lines=120, message=work_message
            ),
            bm.Commit(
                sha=merge_sha, committed_at=merge_at, parents=2, lines=2300, message=merge_message
            ),
        ),
    )

    # A PR in another repo that was closed without merging: the repo argument is used, and
    # merged_at stays None even though closed_at is set.
    small_sha = "0badc0de" * 5
    small = gh_listed_commit(
        small_sha, authored=opened, committed=opened, parents=1, message="fix: typo"
    )
    gh = FakeGh(
        {
            ("repos/octo/widgets/pulls/7",): {
                **pull,
                "number": 7,
                "state": "closed",
                "closed_at": gh_time(merged),
                "merged_at": None,
            },
            ("repos/octo/widgets/pulls/7/commits?per_page=100", "--paginate", "--slurp"): [[small]],
            (f"repos/octo/widgets/commits/{small_sha}",): gh_commit_detail(
                small, additions=3, deletions=1, files=[gh_file("README.md", 3, 1)]
            ),
        }
    )

    unmerged = bm.fetch_pr(7, repo="octo/widgets", gh=gh)

    assert len(gh.calls) == 3
    assert unmerged == bm.PullRequest(
        number=7,
        created_at=opened,
        merged_at=None,
        body=body,
        commits=(
            bm.Commit(sha=small_sha, committed_at=opened, parents=1, lines=4, message="fix: typo"),
        ),
    )


def test_edits_after_counts_only_commits_after_handover():
    pr = pr_with(*brief_commits())

    # Only the commit an hour after the handover is an edit; the one exactly at it is not.
    assert bm.edits_after(pr, H) == bm.Edits(
        commits=1, lines=30, share=pytest.approx(30 / 140), parked_commits=0, parked_lines=0
    )
    # The same PR from other handovers: the share's denominator is always the whole PR.
    assert bm.edits_after(pr, H - 2 * HOUR) == bm.Edits(
        commits=3, lines=140, share=pytest.approx(1.0), parked_commits=0, parked_lines=0
    )
    assert bm.edits_after(pr, H + 2 * HOUR) == bm.Edits(
        commits=0, lines=0, share=0.0, parked_commits=0, parked_lines=0
    )


def test_merge_commits_are_not_edits():
    unchanged = bm.Edits(
        commits=1, lines=30, share=pytest.approx(30 / 140), parked_commits=0, parked_lines=0
    )
    # Merging main into the branch after the handover brings in 500 lines of other work.
    merge_after = commit(
        "merge-main", H + 2 * HOUR, 500, parents=2, message="Merge branch 'main' into feat/export"
    )
    assert bm.edits_after(pr_with(*brief_commits(), merge_after), H) == unchanged

    # A merge before the handover is not the PR's own lines either: it stays out of the
    # denominator.
    merge_before = commit(
        "merge-main-early",
        H - HOUR / 2,
        800,
        parents=2,
        message="Merge remote-tracking branch 'origin/main' into feat/export",
    )
    assert bm.edits_after(pr_with(*brief_commits(), merge_before, merge_after), H) == unchanged


def test_parked_task_trailer_is_reported_separately():
    parked = commit("parked", H + HOUR, 40, message="fix: finish export\n\nParked-task: 3")

    # The parked commit is kept out of the misses, but its lines are still the PR's lines.
    assert bm.edits_after(pr_with(*brief_commits(), parked), H) == bm.Edits(
        commits=1, lines=30, share=pytest.approx(30 / 180), parked_commits=1, parked_lines=40
    )

    # A trailer before the handover counts in neither bucket. A subject that only mentions
    # the trailer mid-line is not a trailer, so that commit is an ordinary miss.
    early_parked = commit(
        "early-parked", H - 2 * HOUR, 25, message="feat: start export\n\nParked-task: 3"
    )
    mention = commit("mention", H + 2 * HOUR, 5, message="docs: explain the Parked-task: trailer")
    assert bm.edits_after(pr_with(*brief_commits(), parked, early_parked, mention), H) == bm.Edits(
        commits=2, lines=35, share=pytest.approx(35 / 210), parked_commits=1, parked_lines=40
    )


def test_share_is_zero_for_empty_pr():
    nothing = bm.Edits(commits=0, lines=0, share=0.0, parked_commits=0, parked_lines=0)

    assert bm.edits_after(pr_with(), H) == nothing
    # Only a merge commit: the PR has no lines of its own.
    only_merge = commit(
        "merge-main", H + HOUR, 500, parents=2, message="Merge branch 'main' into feat/export"
    )
    assert bm.edits_after(pr_with(only_merge), H) == nothing
    # An empty commit pushed after the handover to re-run CI is an edit of zero lines, and
    # there are still no lines to take a share of.
    empty = commit("rerun-ci", H + HOUR, 0, message="chore: re-run CI")
    assert bm.edits_after(pr_with(empty), H) == bm.Edits(
        commits=1, lines=0, share=0.0, parked_commits=0, parked_lines=0
    )


def test_baseline_handover_is_later_of_pr_open_and_final_review(tmp_path):
    opened = at(3600)
    pr = pr_with(created_at=opened)

    def handover(session_id: str, spans: list[tuple[str, datetime, datetime]]) -> datetime:
        """Write a session whose subagents have these (description, start, end) spans,
        load it, and return its baseline handover for ``pr``."""
        write_session(
            tmp_path,
            session_id,
            [user(at(0), "Execute the plan."), assistant(at(1), f"{session_id}-main", OPUS)],
            {
                f"{session_id}-{i}": (
                    description,
                    [
                        user(start, f"You are the {description}."),
                        assistant(end, f"{session_id}-{i}", OPUS),
                    ],
                )
                for i, (description, start, end) in enumerate(spans)
            },
        )
        return bm.baseline_handover(pr, load_sessions(tmp_path, [session_id]))

    # The final review returns after the PR opened, so its fixes fall before the handover.
    # Fixing red CI afterwards is not part of the final review and does not move it.
    late = handover(
        "LATE",
        [("Final branch review", at(4000), at(9000)), ("Fix red CI", at(9100), at(12000))],
    )
    assert late == at(9000)
    assert_utc_aware(late)

    # The PR opened after the final review returned.
    assert (
        handover(
            "EARLY",
            [("Final branch review", at(1000), at(2000)), ("Fix red CI", at(4000), at(5000))],
        )
        == opened
    )

    # No final review at all: the PR's open time, even though other agents ran later.
    assert handover("NO-FINAL", [("Task 1 supervisor", at(100), at(9000))]) == opened


# ---------------------------------------------------------------------------
# Task 3: build records in the PR body, the report, and the CLI
# ---------------------------------------------------------------------------
#
# Interface under test (Task 3 of the plan):
#
#     BLOCK_START = "<!-- build-metrics"
#     BLOCK_END = "-->"
#     BuildRecord(pr, mode, plan, sessions, first_task_at, handover_at, final_review_at,
#                 cost_usd)                          # frozen; sessions is a tuple of ids
#     render_block(rec) -> str      # BLOCK_START, \n, one-line JSON, \n, BLOCK_END
#     parse_block(body) -> BuildRecord | None
#     build_record(*, pr, mode, plan, sessions, projects_dir, handover_at, first_task=None)
#     report_rows(records, prs) -> list[dict]
#     render_report(rows) -> str
#     main(argv) -> int             # record | baseline | report
#
# As in Task 2, the names are reached through ``bm``, so while they are missing only these
# tests fail. ``record`` reads transcripts and nothing else: the CLI tests point HOME at an
# empty dir, put a fake ``gh`` that fails first on PATH, and make ``bm.gh_json`` and
# ``bm.fetch_pr`` raise. Every attempt is recorded, so a swallowed error still shows.

PLAN = "docs/superpowers/plans/x.md"
MODES = ("chained", "single-session")
RECORD_FIELDS = {
    "pr",
    "mode",
    "plan",
    "sessions",
    "first_task_at",
    "handover_at",
    "final_review_at",
    "cost_usd",
}
TIME_FIELDS = ("first_task_at", "handover_at", "final_review_at")
REPORT_COLUMNS = [
    "PR",
    "mode",
    "time to handover (h)",
    "cost to handover ($)",
    "edits after: commits",
    "lines",
    "share",
    "parked commits",
    "share after final review",
    "merged",
]
ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")
UTC_PLUS_1 = timezone(timedelta(hours=1))


def chained_record():
    """A chained build's record with every field set, holding values a lossy encoding drops."""
    return bm.BuildRecord(
        pr=412,
        mode="chained",
        plan=PLAN,
        sessions=("3b1a43fb-4ff7-4575-8bf1-090b96a5963f", "125625f6-9d1e-4b7a-8c2d-0e5f6a7b8c9d"),
        # Given in a UTC+1 zone; the block writes it as UTC with a Z.
        first_task_at=datetime(2026, 11, 14, 8, 30, 12, 345000, tzinfo=UTC_PLUS_1),
        final_review_at=datetime(2026, 11, 14, 14, 41, 0, 7000, tzinfo=timezone.utc),
        # The default handover is "now", which carries microseconds.
        handover_at=datetime(2026, 11, 14, 15, 2, 9, 123456, tzinfo=timezone.utc),
        cost_usd={"opus": 41.234567, "sonnet": 0.1 + 0.2, "haiku": 0.0123},
    )


def baseline_record():
    """A baseline build's record: one session, and no final review found."""
    return bm.BuildRecord(
        pr=359,
        mode="single-session",
        plan="(baseline)",
        sessions=("dfd8af7c-1a2b-4c3d-8e9f-0a1b2c3d4e5f",),
        first_task_at=datetime(2026, 11, 2, 10, 4, 51, 250000, tzinfo=timezone.utc),
        handover_at=datetime(2026, 11, 2, 18, 0, 0, tzinfo=timezone.utc),
        final_review_at=None,
        cost_usd={"opus": 48.5},
    )


def write_chained_build(root: Path, *, supervisor: tuple[str, int] = (SONNET, 1_000_000)) -> None:
    """A chained build of PLAN over two sessions, plus a build of another plan alongside it.

    B1 (primary checkout) names the plan in its prompt, spends 1M opus output at at(10),
    runs a pre-pass, then dispatches "Task 1 supervisor" at at(100). That supervisor makes
    one call, ``supervisor`` = (model, output tokens), at at(500).

    A2 (the worktree; it sorts first) resumes from the ledger and names the plan only in a
    subagent brief. Its Task 2 supervisor spends 1M opus output at at(1100). The final
    agent's "Final branch review" ends at at(1500), the final agent itself at at(1990), and
    1M opus output is spent at at(2100), after a handover at at(2000).

    C3 builds plans/y.md: its first task is at at(50), and it spends 1M opus at at(700).
    """
    model, output = supervisor
    write_session(
        root,
        "B1",
        [
            user(at(0), f"Execute {PLAN} in chained mode."),
            assistant(at(10), "b1-before", OPUS, output=1_000_000),  # before the first task
            assistant(at(20), "b1-prepass", OPUS, dispatch="Pre-pass"),
            assistant(at(100), "b1-task1", OPUS, dispatch="Task 1 supervisor"),
        ],
        {
            "pre": (
                "Pre-pass",
                [user(at(21), "You are the pre-pass."), assistant(at(80), "pre-1", OPUS)],
            ),
            "t1": (
                "Task 1 supervisor",
                [
                    user(at(101), "You are the Task 1 supervisor."),
                    assistant(at(500), "t1-1", model, output=output),
                    tool_result(at(600)),
                ],
            ),
        },
    )
    write_session(
        root,
        "A2",
        [
            user(at(1000), "Resume the chain from the ledger."),
            assistant(at(1050), "a2-task2", OPUS, dispatch="Task 2 supervisor"),
            assistant(at(1200), "a2-final", OPUS, dispatch="Final agent"),
            assistant(at(2100), "a2-after", OPUS, output=1_000_000),  # after the handover
        ],
        {
            "t2": (
                "Task 2 supervisor",
                [
                    user(at(1051), f"Supervise Task 2 of {PLAN}."),
                    assistant(at(1100), "t2-1", OPUS, output=1_000_000),  # in the window
                    tool_result(at(1190)),
                ],
            ),
            "fa": (
                "Final agent",
                [
                    user(at(1201), "You are the final agent."),
                    assistant(at(1210), "fa-1", OPUS, dispatch="Final branch review"),
                    tool_result(at(1990), "PR marked ready for review."),
                ],
            ),
            "fbr": (
                "Final branch review",
                [user(at(1211), "Review the whole branch."), assistant(at(1500), "fbr-1", OPUS)],
                {"parentAgentId": "fa", "spawnDepth": 2},
            ),
        },
        project=WORKTREE,
    )
    write_session(
        root,
        "C3",
        [
            user(at(0), "Execute docs/superpowers/plans/y.md in chained mode."),
            assistant(at(50), "c3-task1", OPUS, dispatch="Task 1 supervisor"),
            assistant(at(700), "c3-spend", OPUS, output=1_000_000),
        ],
    )


class NoGh:
    """Guards a CLI run that must not reach GitHub or read the real ``~/.claude``.

    HOME points at an empty dir, and a fake ``gh`` that logs its arguments and exits 1 is
    first on PATH; a child process inherits both. ``bm.gh_json`` and ``bm.fetch_pr`` record
    the call and raise. ``calls()`` lists every attempt made through any of these.
    """

    def __init__(self, tmp_path: Path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        self.log = tmp_path / "gh-calls.log"
        fake_gh = bin_dir / "gh"
        fake_gh.write_text(f'#!/bin/sh\necho "gh $*" >> "{self.log}"\nexit 1\n')
        fake_gh.chmod(0o755)
        self.attempts: list[str] = []

        def refuse(*args, **kwargs):
            self.attempts.append(f"in-process: {args!r}")
            raise AssertionError("record must not call gh")

        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.setattr(bm, "gh_json", refuse)
        monkeypatch.setattr(bm, "fetch_pr", refuse)

    def calls(self) -> list[str]:
        logged = self.log.read_text().splitlines() if self.log.exists() else []
        return [*self.attempts, *logged]


def run_module(args: list[str]) -> subprocess.CompletedProcess:
    """``python -m scripts.build_metrics <args>``, as the final agent runs it.

    Run from the dir holding the ``scripts`` package the tests imported, with this
    process's environment (so a ``NoGh`` guard applies to it too).
    """
    return subprocess.run(
        [sys.executable, "-m", "scripts.build_metrics", *args],
        cwd=Path(bm.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )


def table_cells(text: str) -> list[list[str]]:
    """The stripped cells of each Markdown table line in ``text``, outer pipes dropped."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        rows.append([cell.strip() for cell in line.split("|")])
    return rows


def number(cell: str) -> float | None:
    """A rendered number (``4``, ``4.0``, ``$30.00``, ``0.10``, ``10%``) as a float, with a
    percentage as a fraction. None for anything else: a blank, ``-``, ``—``, ``n/a``."""
    match = re.fullmatch(r"\$?(-?\d+(?:\.\d+)?)\s*(%?)", cell.strip())
    if not match:
        return None
    value = float(match.group(1))
    return value / 100 if match.group(2) else value


def report_row(
    pr, mode, time_h, cost_total, commits, lines, share, parked, after_review, merged=True
) -> dict:
    return {
        "pr": pr,
        "mode": mode,
        "time_h": time_h,
        "cost_total": cost_total,
        "commits": commits,
        "lines": lines,
        "share": share,
        "parked_commits": parked,
        "share_after_final_review": after_review,
        "merged": merged,
    }


def test_block_round_trips():
    for rec in (chained_record(), baseline_record()):
        block = bm.render_block(rec)

        parsed = bm.parse_block(block)

        # Every field survives: aware datetimes (one given in UTC+1, one with microseconds),
        # final_review_at=None, the sessions tuple, and costs to the last bit.
        assert parsed == rec
        assert isinstance(parsed.sessions, tuple)
        for name in TIME_FIELDS:
            if getattr(rec, name) is not None:
                assert_utc_aware(getattr(parsed, name))

        # The block: the start marker, one line of JSON, the end marker.
        lines = block.split("\n")
        assert len(lines) == 3, block
        assert lines[0] == "<!-- build-metrics"
        assert lines[2] == "-->"
        data = json.loads(lines[1])
        assert data["version"] == 1
        assert set(data) == RECORD_FIELDS | {"version"}
        assert list(data) == sorted(data)  # sort_keys, at every level
        assert list(data["cost_usd"]) == sorted(data["cost_usd"])
        assert data["pr"] == rec.pr
        assert data["mode"] == rec.mode
        assert data["plan"] == rec.plan
        assert data["sessions"] == list(rec.sessions)
        assert data["cost_usd"] == rec.cost_usd
        for name in TIME_FIELDS:
            value = getattr(rec, name)
            if value is None:
                assert data[name] is None
            else:
                assert ISO_Z.fullmatch(data[name]), data[name]
                assert datetime.fromisoformat(data[name].replace("Z", "+00:00")) == value

    assert bm.BLOCK_START == "<!-- build-metrics"
    assert bm.BLOCK_END == "-->"
    with pytest.raises(dataclasses.FrozenInstanceError):
        chained_record().pr = 413


def test_parse_block_absent_or_malformed_returns_none():
    absent = [
        "",
        "## Handover\n\nAll seven tasks done. Waiting on a browser check.",
        # A PR template's HTML comment is a comment, but not a build-metrics block.
        "<!-- Describe the change and how you tested it. -->\n## Summary\n\nAdds the export.",
    ]
    malformed = [
        "<!-- build-metrics\n{not json}\n-->",
        # Cut short, say by a hand edit of the body.
        '<!-- build-metrics\n{"version": 1, "pr": 412, "mode": "chained"\n-->',
        # JSON, but not a record.
        '<!-- build-metrics\n[412, "chained"]\n-->',
        '<!-- build-metrics\n{"version": 1, "pr": 412}\n-->',
    ]

    for body in absent:
        assert bm.parse_block(body) is None, body
    for block in malformed:
        assert bm.parse_block(block) is None, block
        assert bm.parse_block(f"## Handover\n\nReady.\n\n{block}\n\nRulings: none.\n") is None


def test_block_survives_surrounding_body():
    rec = chained_record()
    # HTML comments before and after the block: its end is the first "-->" after its start.
    body = (
        "<!-- Describe the change and how you tested it. -->\n"
        "## Handover\n\n"
        f"Built in chained mode from `{PLAN}`. All 7 tasks done; CI is green.\n\n"
        "### Rulings\n\n- Task 3: kept the plan's report columns.\n\n"
        f"{bm.render_block(rec)}\n\n"
        "### Waits on you\n\n- [ ] Browser check of the export button\n- [ ] Merge\n\n"
        "Finish a parked task with a `Parked-task: <n>` commit trailer.\n"
        "<!-- Reviewers: tick the boxes above. -->\n"
    )

    assert bm.parse_block(body) == rec
    # GitHub returns a body edited in its web UI (a box ticked, say) with CRLF line endings.
    assert bm.parse_block(body.replace("\n", "\r\n")) == rec


def test_build_record_windows_cost_from_first_task_to_handover(tmp_path):
    # Opus only: 1M output before the first "Task 1 supervisor" dispatch (B1, at(10)), 1M
    # between it and the handover (A2's Task 2 supervisor, at(1100)), and 1M after the
    # handover (A2, at(2100)). C3, another build in the same dirs, is not one of the sessions.
    write_chained_build(tmp_path, supervisor=(OPUS, 0))
    handover = at(2000)

    rec = bm.build_record(
        pr=7,
        mode="chained",
        plan=PLAN,
        sessions=["A2", "B1"],
        projects_dir=tmp_path,
        handover_at=handover,
    )

    assert rec.cost_usd == {"opus": pytest.approx(20.0)}
    assert rec == bm.BuildRecord(
        pr=7,
        mode="chained",
        plan=PLAN,
        sessions=("A2", "B1"),
        first_task_at=at(100),
        handover_at=handover,
        final_review_at=at(1500),  # final_review_end(): "Final branch review", not "Final agent"
        cost_usd={"opus": pytest.approx(20.0)},
    )

    # first_task overrides the dispatch found in the transcripts, and the window opens there.
    assert bm.build_record(
        pr=359,
        mode="single-session",
        plan="(baseline)",
        sessions=["A2", "B1"],
        projects_dir=tmp_path,
        handover_at=handover,
        first_task=at(5),
    ) == bm.BuildRecord(
        pr=359,
        mode="single-session",
        plan="(baseline)",
        sessions=("A2", "B1"),
        first_task_at=at(5),
        handover_at=handover,
        final_review_at=at(1500),
        cost_usd={"opus": pytest.approx(40.0)},
    )


def test_report_rows_compute_time_cost_and_edits():
    # The brief's record: a 5 h window, $10 + $2.50, and PR 412's three commits (140 lines,
    # one 30-line commit after the handover).
    brief = bm.BuildRecord(
        pr=412,
        mode="single-session",
        plan="(baseline)",
        sessions=("S",),
        first_task_at=H - 5 * HOUR,
        handover_at=H,
        final_review_at=None,
        cost_usd={"opus": 10.0, "sonnet": 2.5},
    )
    # An earlier chained build whose parked task was finished after its handover.
    h2 = H - 24 * HOUR
    earlier = bm.BuildRecord(
        pr=413,
        mode="chained",
        plan=PLAN,
        sessions=("T",),
        first_task_at=h2 - 1.5 * HOUR,
        handover_at=h2,
        final_review_at=None,
        cost_usd={"opus": 7.0},
    )
    pr413 = bm.PullRequest(
        number=413,
        created_at=h2 - HOUR,
        merged_at=h2 + 3 * HOUR,
        body="",
        commits=(
            commit("work", h2 - 2 * HOUR, 60),
            commit("miss", h2 + HOUR, 15),
            commit("parked", h2 + 2 * HOUR, 25, message="feat: finish import\n\nParked-task: 2"),
        ),
    )

    rows = bm.report_rows([brief, earlier], {412: pr_with(*brief_commits()), 413: pr413})

    # One row per record, each with its own PR's edits, sorted by handover.
    assert rows == [
        {
            "pr": 413,
            "mode": "chained",
            "time_h": pytest.approx(1.5),
            "cost_total": pytest.approx(7.0),
            "commits": 1,
            "lines": 15,
            "share": pytest.approx(15 / 100),
            "parked_commits": 1,
            "share_after_final_review": None,
            "merged": True,
        },
        {
            "pr": 412,
            "mode": "single-session",
            "time_h": pytest.approx(5.0),
            "cost_total": pytest.approx(12.5),
            "commits": 1,
            "lines": 30,
            "share": pytest.approx(30 / 140),
            "parked_commits": 0,
            "share_after_final_review": None,
            "merged": True,
        },
    ]


def test_report_rows_include_share_after_final_review():
    # 140 lines: 90 before the final review returned (h - 1h), a 20-line review fix between
    # it and the handover (h), and a 30-line miss after the handover.
    commits = (
        commit("work", H - 3 * HOUR, 90),
        commit("review-fix", H - HOUR / 2, 20, message="fix: final review findings"),
        commit("miss", H + HOUR, 30),
    )

    def build(pr_number: int, mode: str, final_review_at: datetime | None):
        record = bm.BuildRecord(
            pr=pr_number,
            mode=mode,
            plan=PLAN if mode == "chained" else "(baseline)",
            sessions=(f"s{pr_number}",),
            first_task_at=H - 6 * HOUR,
            handover_at=H,
            final_review_at=final_review_at,
            cost_usd={"opus": 30.0},
        )
        pull = bm.PullRequest(
            number=pr_number,
            created_at=H - 4 * HOUR,
            merged_at=H + 5 * HOUR,
            body="",
            commits=commits,
        )
        return record, pull

    chained = build(501, "chained", H - HOUR)
    # A baseline's final review is known too, but its handover already comes after it.
    baseline = build(502, "single-session", H - HOUR)
    no_review = build(503, "chained", None)
    builds = [chained, baseline, no_review]

    rows = bm.report_rows([r for r, _ in builds], {p.number: p for _, p in builds})

    by_pr = {row["pr"]: row for row in rows}
    assert len(rows) == 3 and set(by_pr) == {501, 502, 503}
    assert by_pr[501]["share_after_final_review"] == pytest.approx(50 / 140)
    # The edits after the handover are the same for all three.
    for row in rows:
        assert (row["commits"], row["lines"], row["share"]) == (1, 30, pytest.approx(30 / 140))
    assert by_pr[502]["share_after_final_review"] is None
    assert by_pr[503]["share_after_final_review"] is None


def test_render_report_has_median_row_per_mode():
    # Each chained column's median comes from a different row, and no mean equals a median.
    chained = [
        report_row(401, "chained", 2.0, 30.0, 5, 60, 0.10, 0, 0.40),
        report_row(402, "chained", 9.0, 10.0, 2, 0, 0.30, 1, 0.05),
        report_row(403, "chained", 4.0, 80.0, 0, 20, 0.0, 0, 0.15, merged=False),
    ]
    single = [
        report_row(359, "single-session", 8.0, 48.0, 0, 0, 0.0, 0, None),
        report_row(351, "single-session", 3.5, 126.0, 3, 90, 0.12, 0, None),
        report_row(354, "single-session", 28.0, 24.0, 9, 400, 0.26, 0, None),
    ]
    # In handover order the modes interleave; a median over all six rows differs per column.
    rows = [single[0], chained[0], single[1], chained[1], single[2], chained[2]]
    medians = {  # time_h, cost_total, commits, share, share after final review
        "chained": (4.0, 30.0, 2, 0.10, 0.15),
        "single-session": (8.0, 48.0, 3, 0.12, None),
    }

    table = table_cells(bm.render_report(rows))

    assert table[0] == REPORT_COLUMNS
    assert len(table[1]) == len(REPORT_COLUMNS)
    assert all(re.fullmatch(r":?-+:?", cell) for cell in table[1]), table[1]
    body = table[2:]
    assert all(len(cells) == len(REPORT_COLUMNS) for cells in body), body
    assert len(body) == len(rows) + 2, body

    # One line per row, in the order given.
    for cells, row in zip(body[: len(rows)], rows):
        assert int(re.search(r"\d+", cells[0]).group()) == row["pr"], cells
        assert cells[1] == row["mode"], cells
        assert number(cells[2]) == pytest.approx(row["time_h"], abs=0.051), cells
        assert number(cells[3]) == pytest.approx(row["cost_total"], abs=0.006), cells
        assert number(cells[4]) == row["commits"], cells
        assert number(cells[5]) == row["lines"], cells
        assert number(cells[6]) == pytest.approx(row["share"], abs=0.0051), cells
        assert number(cells[7]) == row["parked_commits"], cells
        if row["share_after_final_review"] is None:
            assert number(cells[8]) is None, cells
        else:
            assert number(cells[8]) == pytest.approx(row["share_after_final_review"], abs=0.0051)
        assert cells[9] == ("yes" if row["merged"] else "no"), cells

    # Then one median row per mode, each over that mode's rows only.
    by_mode = {}
    for cells in body[len(rows) :]:
        labels = [mode for mode in MODES if f"median ({mode})" in " | ".join(cells)]
        assert len(labels) == 1, cells
        by_mode[labels[0]] = cells
    assert set(by_mode) == set(MODES)
    for mode, (time_h, cost, commits, share, after_review) in medians.items():
        cells = by_mode[mode]
        assert number(cells[2]) == pytest.approx(time_h, abs=0.051), cells
        assert number(cells[3]) == pytest.approx(cost, abs=0.006), cells
        assert number(cells[4]) == pytest.approx(commits), cells
        assert number(cells[6]) == pytest.approx(share, abs=0.0051), cells
        if after_review is None:
            assert number(cells[8]) is None, cells
        else:
            assert number(cells[8]) == pytest.approx(after_review, abs=0.0051), cells

    # Only the modes present get a median row.
    only_chained = bm.render_report(chained)
    assert only_chained.count("median (chained)") == 1
    assert "median (single-session)" not in only_chained


def test_cli_record_prints_block(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    write_chained_build(projects)
    guard = NoGh(tmp_path, monkeypatch)
    handover = "2026-11-17T09:33:20Z"  # at(2000)
    argv = ["record", "--pr", "7", "--plan", PLAN, "--handover", handover]
    argv += ["--projects-dir", str(projects)]
    # Sessions found by the plan path (A2 names it only in a subagent brief; C3 is another
    # plan's build), mode chained by default, the window from B1's first task to the
    # handover: 1M opus output in A2's Task 2 supervisor and 1M sonnet output in B1's.
    expected = bm.BuildRecord(
        pr=7,
        mode="chained",
        plan=PLAN,
        sessions=("A2", "B1"),
        first_task_at=at(100),
        handover_at=at(2000),
        final_review_at=at(1500),
        cost_usd={"opus": pytest.approx(20.0), "sonnet": pytest.approx(10.0)},
    )

    assert bm.main(argv) == 0
    out = capsys.readouterr().out

    assert bm.parse_block(out).pr == 7
    assert bm.parse_block(out) == expected
    # stdout is the block and nothing else: the final agent pastes it into the PR body.
    assert out.strip() == bm.render_block(bm.parse_block(out))

    # --session names the sessions instead: B1 alone has the first task but no final review.
    assert bm.main([*argv, "--session", "B1"]) == 0
    only_b1 = bm.parse_block(capsys.readouterr().out)
    assert only_b1.sessions == ("B1",)
    assert (only_b1.first_task_at, only_b1.handover_at) == (at(100), at(2000))
    assert only_b1.final_review_at is None
    assert {k: v for k, v in only_b1.cost_usd.items() if v} == {"sonnet": pytest.approx(10.0)}

    # Without --handover, the handover is now, in UTC.
    before = datetime.now(timezone.utc)
    assert bm.main(["record", "--pr", "7", "--plan", PLAN, "--projects-dir", str(projects)]) == 0
    after = datetime.now(timezone.utc)
    now_rec = bm.parse_block(capsys.readouterr().out)
    assert_utc_aware(now_rec.handover_at)
    assert before - timedelta(seconds=1) <= now_rec.handover_at <= after + timedelta(seconds=1)

    # The same as the final agent runs it: `python -m scripts.build_metrics record ...`.
    child = run_module(argv)
    assert child.returncode == 0, child.stderr
    assert bm.parse_block(child.stdout) == expected

    assert guard.calls() == []


def test_cli_record_exits_2_without_sessions(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    projects.mkdir()
    guard = NoGh(tmp_path, monkeypatch)
    argv = ["record", "--pr", "7", "--plan", PLAN, "--handover", "2026-11-17T09:33:20Z"]
    argv += ["--projects-dir", str(projects)]

    def assert_exits_2() -> None:
        assert bm.main(argv) == 2
        out, err = capsys.readouterr()
        assert err.strip(), "the reason goes to stderr"
        assert "build-metrics" not in out
        child = run_module(argv)
        assert child.returncode == 2, (child.stdout, child.stderr)
        assert child.stderr.strip()
        assert "build-metrics" not in child.stdout

    # An empty projects dir.
    assert_exits_2()

    # Only another plan's build: no session names this plan.
    write_session(
        projects,
        "C3",
        [
            user(at(0), "Execute docs/superpowers/plans/y.md in chained mode."),
            assistant(at(50), "c3-task1", OPUS, dispatch="Task 1 supervisor"),
        ],
    )
    assert_exits_2()

    # A session names the plan but stopped in the pre-pass: no first task, so no record.
    write_session(
        projects,
        "P",
        [
            user(at(0), f"Execute {PLAN} in chained mode."),
            assistant(at(20), "p-prepass", OPUS, dispatch="Pre-pass"),
        ],
        {
            "pre": (
                "Pre-pass",
                [user(at(21), "You are the pre-pass."), assistant(at(80), "p1", OPUS)],
            )
        },
    )
    assert_exits_2()

    assert guard.calls() == []


# ---------------------------------------------------------------------------
# Final-review fixes: `record` keys on the ledger, and the final review is clipped
# ---------------------------------------------------------------------------
#
#     Dispatch(ts, description, prompt="")   # prompt: the Agent call's input.prompt
#     build_record(..., find=None)           # chained: the clock starts at the earliest
#                                            # "Task <n> supervisor" whose prompt has `find`
#     record --find STRING (default: the --plan value) --first-task ISO
#
# A chained build's top-level fills the ledger's absolute path into every stage brief, so
# the ledger path names this build's stage dispatches and nothing else.

LEDGER = "/Users/dev/tellr-loop/x/LEDGER.md"


def dispatch_block(description: str, prompt: str) -> dict:
    """An Agent tool_use with this prompt (``agent_block`` writes a stock one)."""
    return {
        "type": "tool_use",
        "id": "toolu_" + re.sub(r"\W", "_", description)[:40],
        "name": "Agent",
        "input": {"description": description, "prompt": prompt, "subagent_type": "general-purpose"},
    }


def stage_brief(stage: str, *, ledger: str = LEDGER, plan: str = PLAN) -> str:
    """The head of a filled stage brief, as the top-level sends it."""
    return f"You are the `{stage}` of a chained build.\n\n- Plan: `{plan}`\n- Ledger: `{ledger}`"


def nonzero(costs: dict[str, float]) -> dict[str, float]:
    return {family: cost for family, cost in costs.items() if cost}


def test_cli_record_costs_only_the_chains_sessions(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    guard = NoGh(tmp_path, monkeypatch)
    # The build. Its Task 1 supervisor spends 1M sonnet output at at(500).
    write_session(
        projects,
        "build",
        [
            user(at(0), f"Execute {PLAN} in chained mode."),
            assistant(
                at(100),
                "b-1",
                OPUS,
                blocks=(dispatch_block("Task 1 supervisor", stage_brief("Task 1 supervisor")),),
            ),
        ],
        {
            "t1": (
                "Task 1 supervisor",
                [
                    user(at(101), stage_brief("Task 1 supervisor")),
                    assistant(at(500), "t1-1", SONNET, output=1_000_000),
                    tool_result(at(600)),
                ],
            )
        },
    )
    # The top-level died while the final agent waited on CI, and a fresh session resumed the
    # build. It dispatched only the final agent, whose brief does not know the plan path.
    # The final agent spends 1M opus output at at(1300); its review ends at at(1500).
    resume_brief = stage_brief("Final agent", plan="(ledger header)")
    write_session(
        projects,
        "resume",
        [
            user(at(1000), f"Continue the build in {LEDGER}."),
            assistant(at(1200), "r-1", OPUS, blocks=(dispatch_block("Final agent", resume_brief),)),
        ],
        {
            "fa": (
                "Final agent",
                [
                    user(at(1201), resume_brief),
                    assistant(
                        at(1300), "fa-1", OPUS, output=1_000_000, dispatch="Final branch review"
                    ),
                    tool_result(at(1990), "PR marked ready for review."),
                ],
            ),
            "fbr": (
                "Final branch review",
                [user(at(1301), "Review the whole branch."), assistant(at(1500), "fbr-1", OPUS)],
                {"parentAgentId": "fa", "spawnDepth": 2},
            ),
        },
        project=WORKTREE,
    )
    # The user talking the plan over while it builds. It names the plan, but neither names
    # the ledger nor dispatches a stage. 1M opus output at at(300).
    write_session(
        projects,
        "chat",
        [
            user(at(200), f"While that builds: is Task 3 of {PLAN} still right?"),
            assistant(at(300), "c-1", OPUS, output=1_000_000, dispatch="Explore Task 3 code"),
        ],
    )
    # A smoke run of the same plan, with a ledger of its own: a supervisor whose brief names
    # this plan but not this ledger. 1M haiku output at at(400).
    smoke_brief = stage_brief("Task 1 supervisor", ledger="/Users/dev/tellr-loop/smoke/LEDGER.md")
    write_session(
        projects,
        "smoke",
        [
            user(at(0), f"Smoke-run {PLAN}."),
            assistant(
                at(400),
                "s-1",
                HAIKU,
                output=1_000_000,
                blocks=(dispatch_block("Task 1 supervisor", smoke_brief),),
            ),
        ],
    )
    argv = ["record", "--pr", "7", "--plan", PLAN, "--handover", iso(at(2000))]
    argv += ["--projects-dir", str(projects)]

    # --find the ledger: the build and its resume, and nothing else.
    assert bm.main([*argv, "--find", LEDGER]) == 0
    out, err = capsys.readouterr()
    rec = bm.parse_block(out)
    assert rec.sessions == ("build", "resume")
    assert rec.plan == PLAN  # --plan is still what the record names
    assert (rec.first_task_at, rec.final_review_at) == (at(100), at(1500))
    assert nonzero(rec.cost_usd) == {"sonnet": pytest.approx(10.0), "opus": pytest.approx(20.0)}
    assert "build-metrics: sessions: build, resume" in err.splitlines()

    # Without --find the plan path finds them. The chat names the plan too, but dispatched
    # no stage, so it is still left out; the smoke run's supervisor is a stage, so it counts.
    assert bm.main(argv) == 0
    out, err = capsys.readouterr()
    rec = bm.parse_block(out)
    assert rec.sessions == ("build", "smoke")
    assert nonzero(rec.cost_usd) == {"sonnet": pytest.approx(10.0), "haiku": pytest.approx(0.5)}
    assert "build-metrics: sessions: build, smoke" in err.splitlines()

    # The stage filter is for chained builds only.
    assert bm.main([*argv, "--mode", "single-session"]) == 0
    out, err = capsys.readouterr()
    assert bm.parse_block(out).sessions == ("build", "chat", "smoke")
    assert "build-metrics: sessions: build, chat, smoke" in err.splitlines()

    assert guard.calls() == []


def test_chained_clock_starts_at_this_builds_first_supervisor(tmp_path, capsys):
    # One session that ran other work before this build: a reviewer of an earlier build
    # (its description names a task, and its prompt even names this ledger), and another
    # build's chain. Neither starts this build's clock.
    other_ledger = "/Users/dev/tellr-loop/other/LEDGER.md"
    write_session(
        tmp_path,
        "S",
        [
            user(at(0), "Review the last build, then run the next one."),
            assistant(
                at(10),
                "m-review",
                OPUS,
                blocks=(
                    dispatch_block(
                        "Review Task 8 supervisor's commits", f"Check them against {LEDGER}."
                    ),
                ),
            ),
            assistant(
                at(20),
                "m-other",
                OPUS,
                blocks=(
                    dispatch_block(
                        "Task 1 supervisor", stage_brief("Task 1 supervisor", ledger=other_ledger)
                    ),
                ),
            ),
            assistant(at(50), "m-between", OPUS, output=1_000_000),  # before this build's clock
            assistant(
                at(100),
                "m-task1",
                OPUS,
                blocks=(dispatch_block("Task 1 supervisor", stage_brief("Task 1 supervisor")),),
            ),
            assistant(at(500), "m-spend", SONNET, output=1_000_000),
        ],
    )

    def record(mode: str, find: str) -> bm.BuildRecord:
        return bm.build_record(
            pr=7,
            mode=mode,
            plan=PLAN,
            find=find,
            sessions=["S"],
            projects_dir=tmp_path,
            handover_at=at(2000),
        )

    # The Agent call's prompt is kept on its dispatch; a positional Dispatch still builds.
    t = load_sessions(tmp_path, ["S"])
    assert {d.prompt for d in t.dispatches if d.ts == at(100)} == {stage_brief("Task 1 supervisor")}
    assert Dispatch(at(5), "Pre-pass").prompt == ""

    rec = record("chained", LEDGER)
    err = capsys.readouterr().err
    assert rec.first_task_at == at(100)
    assert nonzero(rec.cost_usd) == {"sonnet": pytest.approx(10.0)}  # m-between is outside
    # The matched dispatch and its time go to stderr, for the final agent's ledger entry.
    assert "Task 1 supervisor" in err and "2026-11-17T09:01:40" in err

    # No supervisor's prompt names the string: fall back to the first task dispatch, and say
    # so on stderr.
    missing = "/Users/dev/tellr-loop/never/LEDGER.md"
    rec = record("chained", missing)
    err = capsys.readouterr().err
    assert rec.first_task_at == at(10)
    assert missing in err
    assert "Review Task 8 supervisor's commits" in err and "2026-11-17T09:00:10" in err

    # A single-session build keeps the first task dispatch.
    assert record("single-session", LEDGER).first_task_at == at(10)


def test_cli_record_first_task_overrides(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    write_chained_build(projects)
    guard = NoGh(tmp_path, monkeypatch)
    argv = ["record", "--pr", "7", "--plan", PLAN, "--handover", "2026-11-17T09:33:20Z"]
    argv += ["--projects-dir", str(projects)]

    # The window opens at the override, so B1's 1M opus output at at(10) is in it.
    assert bm.main([*argv, "--first-task", "2026-11-17T09:00:05Z"]) == 0
    rec = bm.parse_block(capsys.readouterr().out)
    assert rec.first_task_at == at(5)
    assert nonzero(rec.cost_usd) == {"opus": pytest.approx(40.0), "sonnet": pytest.approx(10.0)}

    with pytest.raises(SystemExit) as refused:
        bm.main([*argv, "--first-task", "yesterday morning"])
    assert refused.value.code == 2

    assert guard.calls() == []


def test_build_record_clips_final_review_to_handover(tmp_path):
    write_chained_build(tmp_path)

    # The final review's last span ends at at(1500), after a handover given at at(1200).
    rec = bm.build_record(
        pr=7,
        mode="chained",
        plan=PLAN,
        sessions=["A2", "B1"],
        projects_dir=tmp_path,
        handover_at=at(1200),
    )

    assert rec.final_review_at == at(1200)
    assert rec.handover_at == at(1200)


def test_report_marks_unmerged_prs():
    # Two builds with the same edits after handover; only one PR is merged. The open PR's
    # edits can still grow, and the report says so.
    def build(number: int, merged_at: datetime | None):
        record = bm.BuildRecord(
            pr=number,
            mode="chained",
            plan=PLAN,
            sessions=(f"s{number}",),
            first_task_at=H - 2 * HOUR,
            handover_at=H,
            final_review_at=None,
            cost_usd={"opus": 9.0},
        )
        pull = bm.PullRequest(
            number=number,
            created_at=H - HOUR,
            merged_at=merged_at,
            body="",
            commits=brief_commits(),
        )
        return record, pull

    merged, still_open = build(601, H + 4 * HOUR), build(602, None)

    rows = bm.report_rows([merged[0], still_open[0]], {601: merged[1], 602: still_open[1]})

    assert {row["pr"]: row["merged"] for row in rows} == {601: True, 602: False}
    table = table_cells(bm.render_report(rows))
    assert table[0][-1] == "merged"
    by_pr = {cells[0]: cells for cells in table[2:] if cells[0].startswith("#")}
    assert by_pr["#601"][-1] == "yes"
    assert by_pr["#602"][-1] == "no"
    # The other columns keep their places.
    assert table[0][:-1] == REPORT_COLUMNS[:-1]
    assert number(by_pr["#602"][6]) == pytest.approx(30 / 140, abs=0.0051)
