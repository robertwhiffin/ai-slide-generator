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

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
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
