"""Measure the time and cost of an agent build from Claude Code transcripts.

A build window runs from the first task dispatch to the end of the final review. Within it
this module totals token usage per model family and prices it at list prices. The figures
are list prices, relative only: use them to compare builds, not to reconcile a bill.

Transcripts live under ``<projects_dir>/<project dir>/``. A session's main transcript is
``<session_id>.jsonl``; its subagents are ``<session_id>/subagents/agent-<id>.jsonl`` with a
sibling ``agent-<id>.meta.json`` holding the description. A session that enters a worktree
has files in more than one project dir, so every project dir is searched.

Standard library only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ApiCall:
    ts: datetime
    family: str
    input: int
    output: int
    cache_read: int
    cache_write: int


@dataclass(frozen=True)
class Dispatch:
    ts: datetime
    description: str


@dataclass(frozen=True)
class AgentSpan:
    description: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Transcript:
    session_ids: tuple[str, ...]
    calls: tuple[ApiCall, ...]
    dispatches: tuple[Dispatch, ...]
    spans: tuple[AgentSpan, ...]


# family -> (input, output, cache_read, cache_write), list prices in $ per million tokens
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus": (4.00, 20.00, 0.20, 8.00),
    "sonnet": (2.00, 10.00, 0.10, 4.00),
    "haiku": (0.10, 0.50, 0.01, 0.20),
}

TASK_RE = re.compile(r"\btask\s*\d+|^T\d+\b", re.I)
FINAL_RE = re.compile(r"\bfinal\b(?! agent)|whole[- ]branch", re.I)


def model_family(model_id: str) -> str | None:
    lowered = (model_id or "").lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in lowered:
            return family
    return None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _read_lines(path: Path) -> Iterator[dict]:
    """Yield parsed JSON objects, skipping lines that fail to parse."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in text.splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def _session_files(projects_dir: Path, session_id: str) -> tuple[list[Path], list[Path]]:
    """(main transcripts, subagent transcripts) for a session, across every project dir."""
    mains = sorted(projects_dir.glob(f"*/{session_id}.jsonl"))
    subs = sorted(projects_dir.glob(f"*/{session_id}/subagents/**/agent-*.jsonl"))
    return mains, subs


def _tokens(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def load_sessions(projects_dir: Path, session_ids: Sequence[str]) -> Transcript:
    projects_dir = Path(projects_dir)
    calls: list[ApiCall] = []
    dispatches: list[Dispatch] = []
    spans: list[AgentSpan] = []
    seen_ids: set[str] = set()
    seen_dispatch: set[tuple[datetime, str]] = set()

    for session_id in session_ids:
        mains, subs = _session_files(projects_dir, session_id)
        for path in [*mains, *subs]:
            is_sub = path in subs
            first_ts: datetime | None = None
            last_ts: datetime | None = None
            for line in _read_lines(path):
                ts = _parse_ts(line.get("timestamp"))
                if ts is not None:
                    first_ts = first_ts or ts
                    last_ts = ts if last_ts is None or ts > last_ts else last_ts
                if line.get("type") != "assistant" or ts is None:
                    continue
                message = line.get("message")
                if not isinstance(message, dict):
                    continue
                # Dispatches come from every line: one API response is split over several
                # lines with one content block each, so the tool_use may be on a repeat line.
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") == "Agent"
                        ):
                            inp = block.get("input")
                            desc = str(inp.get("description", "")) if isinstance(inp, dict) else ""
                            if (ts, desc) not in seen_dispatch:
                                seen_dispatch.add((ts, desc))
                                dispatches.append(Dispatch(ts=ts, description=desc))
                usage = message.get("usage")
                family = model_family(str(message.get("model", "")))
                if not isinstance(usage, dict) or family is None:
                    continue
                # Usage is repeated on every line of a split response: count it once. A
                # message id names one API response, so dedupe across every loaded file and
                # session (a stale or copied transcript must not double-count).
                msg_id = message.get("id")
                if isinstance(msg_id, str) and msg_id:
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                calls.append(
                    ApiCall(
                        ts=ts,
                        family=family,
                        input=_tokens(usage, "input_tokens"),
                        output=_tokens(usage, "output_tokens"),
                        cache_read=_tokens(usage, "cache_read_input_tokens"),
                        cache_write=_tokens(usage, "cache_creation_input_tokens"),
                    )
                )
            if is_sub and first_ts is not None and last_ts is not None:
                description = ""
                meta = path.with_name(path.name[: -len(".jsonl")] + ".meta.json")
                try:
                    loaded = json.loads(meta.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        description = str(loaded.get("description", ""))
                except (OSError, ValueError):
                    pass
                spans.append(AgentSpan(description=description, start=first_ts, end=last_ts))

    return Transcript(
        session_ids=tuple(session_ids),
        calls=tuple(calls),
        dispatches=tuple(dispatches),
        spans=tuple(spans),
    )


def _contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def find_sessions(projects_dir: Path, needle: str) -> list[str]:
    """Sorted ids of sessions whose main or subagent transcripts contain ``needle``."""
    projects_dir = Path(projects_dir)
    found: set[str] = set()
    for path in projects_dir.glob("*/*.jsonl"):
        if path.stem not in found and _contains(path, needle):
            found.add(path.stem)
    for path in projects_dir.glob("*/*/subagents/**/agent-*.jsonl"):
        session_id = path.relative_to(projects_dir).parts[1]
        if session_id not in found and _contains(path, needle):
            found.add(session_id)
    return sorted(found)


def cost_usd(calls: Iterable[ApiCall], start: datetime, end: datetime) -> dict[str, float]:
    """List-price cost per family for calls with start <= ts <= end."""
    totals: dict[str, float] = {}
    for call in calls:
        prices = PRICES.get(call.family)
        if prices is None or not (start <= call.ts <= end):
            continue
        p_in, p_out, p_read, p_write = prices
        cost = (
            call.input * p_in
            + call.output * p_out
            + call.cache_read * p_read
            + call.cache_write * p_write
        ) / 1_000_000
        totals[call.family] = totals.get(call.family, 0.0) + cost
    return totals


def first_task_at(t: Transcript) -> Dispatch | None:
    matches = [d for d in t.dispatches if TASK_RE.search(d.description)]
    return min(matches, key=lambda d: d.ts) if matches else None


def final_review_end(t: Transcript) -> datetime | None:
    ends = [s.end for s in t.spans if FINAL_RE.search(s.description)]
    return max(ends) if ends else None
