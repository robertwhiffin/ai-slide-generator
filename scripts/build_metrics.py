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

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    # The Agent call's input.prompt. Left out of equality and repr: a dispatch is its time
    # and description (as the dedupe key in load_sessions has it), and a brief is long.
    prompt: str = field(default="", compare=False, repr=False)


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
# Chained builds, matched against the whole description: the dispatch that starts the clock,
# and the dispatches that make a session part of the chain.
SUPERVISOR_RE = re.compile(r"Task \d+ supervisor")
CHAIN_STAGE_RE = re.compile(r"Task \d+ supervisor|Final agent")


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
                            inp = inp if isinstance(inp, dict) else {}
                            desc = str(inp.get("description", ""))
                            if (ts, desc) not in seen_dispatch:
                                seen_dispatch.add((ts, desc))
                                prompt = str(inp.get("prompt", ""))
                                dispatches.append(Dispatch(ts=ts, description=desc, prompt=prompt))
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


def first_supervisor_at(t: Transcript, find: str) -> Dispatch | None:
    """The earliest ``Task <n> supervisor`` dispatch whose prompt contains ``find``.

    Every stage brief carries the ledger's path, so with ``find`` the ledger this skips a
    reviewer that merely names a task and another build's chain in the same session.
    """
    matches = [
        d for d in t.dispatches if SUPERVISOR_RE.fullmatch(d.description) and find in d.prompt
    ]
    return min(matches, key=lambda d: d.ts) if matches else None


def chain_sessions(projects_dir: Path, session_ids: Iterable[str]) -> list[str]:
    """The sessions that dispatched a chain stage: a task supervisor or the final agent.

    The final agent counts too: a build resumed while its final agent ran dispatches only
    that agent, and that resumed session is the one the final agent records from.
    """
    kept = []
    for session_id in session_ids:
        dispatches = load_sessions(projects_dir, [session_id]).dispatches
        if any(CHAIN_STAGE_RE.fullmatch(d.description) for d in dispatches):
            kept.append(session_id)
    return kept


def final_review_end(t: Transcript) -> datetime | None:
    ends = [s.end for s in t.spans if FINAL_RE.search(s.description)]
    return max(ends) if ends else None


REPO = "robertwhiffin/ai-slide-generator"
PARKED_RE = re.compile(r"^Parked-task:\s*\S+", re.M)
GhJson = Callable[[list[str]], Any]  # runs `gh api <args>`, returns parsed JSON


@dataclass(frozen=True)
class Commit:
    sha: str
    committed_at: datetime
    parents: int
    lines: int  # additions + deletions (API stats.total)
    message: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    created_at: datetime
    merged_at: datetime | None
    body: str
    commits: tuple[Commit, ...]


@dataclass(frozen=True)
class Edits:
    commits: int
    lines: int
    share: float  # lines / all non-merge lines in the PR; 0.0 when the PR has none
    parked_commits: int
    parked_lines: int


def gh_json(args: list[str]) -> Any:
    result = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def fetch_pr(number: int, *, repo: str = REPO, gh: GhJson = gh_json) -> PullRequest:
    pull = gh([f"repos/{repo}/pulls/{number}"])
    pages = gh([f"repos/{repo}/pulls/{number}/commits?per_page=100", "--paginate", "--slurp"])
    listed = [item for page in pages for item in page]
    commits = []
    for item in listed:
        sha = item["sha"]
        detail = gh([f"repos/{repo}/commits/{sha}"])
        commits.append(
            Commit(
                sha=sha,
                committed_at=_parse_ts(item["commit"]["committer"]["date"]),
                parents=len(item.get("parents", [])),
                lines=int(detail.get("stats", {}).get("total", 0)),
                message=item["commit"].get("message", ""),
            )
        )
    return PullRequest(
        number=number,
        created_at=_parse_ts(pull["created_at"]),
        merged_at=_parse_ts(pull.get("merged_at")),
        body=pull.get("body") or "",
        commits=tuple(commits),
    )


def baseline_handover(pr: PullRequest, t: Transcript) -> datetime:
    """The later of the PR opening and the end of the final review."""
    end = final_review_end(t)
    return pr.created_at if end is None else max(pr.created_at, end)


def edits_after(pr: PullRequest, handover: datetime) -> Edits:
    own = [c for c in pr.commits if c.parents == 1]
    total = sum(c.lines for c in own)
    after = [c for c in own if c.committed_at > handover]
    parked = [c for c in after if PARKED_RE.search(c.message)]
    misses = [c for c in after if not PARKED_RE.search(c.message)]
    lines = sum(c.lines for c in misses)
    return Edits(
        commits=len(misses),
        lines=lines,
        share=lines / total if total else 0.0,
        parked_commits=len(parked),
        parked_lines=sum(c.lines for c in parked),
    )


# ---------------------------------------------------------------------------
# Build records (kept in the PR body), the report, and the CLI
# ---------------------------------------------------------------------------

BLOCK_START = "<!-- build-metrics"
BLOCK_END = "-->"
RECORD_VERSION = 1
DEFAULT_BASELINE = Path(__file__).resolve().parents[1] / "docs/agents/build-metrics-baseline.json"


@dataclass(frozen=True)
class BuildRecord:
    pr: int
    mode: str  # "chained" | "single-session"
    plan: str  # plan path, or "(baseline)"
    sessions: tuple[str, ...]
    first_task_at: datetime
    handover_at: datetime
    final_review_at: datetime | None  # final_review_end() at record time
    cost_usd: dict[str, float]


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def record_to_dict(rec: BuildRecord) -> dict:
    return {
        "version": RECORD_VERSION,
        "pr": rec.pr,
        "mode": rec.mode,
        "plan": rec.plan,
        "sessions": list(rec.sessions),
        "first_task_at": _iso(rec.first_task_at),
        "handover_at": _iso(rec.handover_at),
        "final_review_at": _iso(rec.final_review_at),
        "cost_usd": dict(rec.cost_usd),
    }


def record_from_dict(data: object) -> BuildRecord | None:
    """A record from its JSON form, or None if it is not a well-formed record."""
    if not isinstance(data, dict) or data.get("version") != RECORD_VERSION:
        return None
    try:
        pr, mode, plan = data["pr"], data["mode"], data["plan"]
        sessions, costs = data["sessions"], data["cost_usd"]
        first, handover = _parse_ts(data["first_task_at"]), _parse_ts(data["handover_at"])
        raw_review = data["final_review_at"]
        review = _parse_ts(raw_review)
    except KeyError:
        return None
    if not (isinstance(pr, int) and isinstance(mode, str) and isinstance(plan, str)):
        return None
    if not (isinstance(sessions, list) and all(isinstance(x, str) for x in sessions)):
        return None
    if not (isinstance(costs, dict) and all(isinstance(v, (int, float)) for v in costs.values())):
        return None
    if first is None or handover is None or (raw_review is not None and review is None):
        return None
    return BuildRecord(
        pr=pr,
        mode=mode,
        plan=plan,
        sessions=tuple(sessions),
        first_task_at=first,
        handover_at=handover,
        final_review_at=review,
        cost_usd={str(k): float(v) for k, v in costs.items()},
    )


def render_block(rec: BuildRecord) -> str:
    return f"{BLOCK_START}\n{json.dumps(record_to_dict(rec), sort_keys=True)}\n{BLOCK_END}"


def parse_block(body: str) -> BuildRecord | None:
    """The first well-formed build-metrics block in a PR body, else None."""
    pos = 0
    while True:
        start = body.find(BLOCK_START, pos)
        if start < 0:
            return None
        begin = start + len(BLOCK_START)
        end = body.find(BLOCK_END, begin)
        if end < 0:
            return None
        try:
            rec = record_from_dict(json.loads(body[begin:end]))
        except ValueError:
            rec = None
        if rec is not None:
            return rec
        pos = begin


def build_record(
    *,
    pr: int,
    mode: str,
    plan: str,
    sessions: Sequence[str],
    projects_dir: Path,
    handover_at: datetime,
    first_task: datetime | None = None,
    find: str | None = None,
) -> BuildRecord:
    """Cost is windowed from the first task to the handover. Raises ValueError if no first
    task is given and none is found in the transcripts.

    Without ``first_task``, a chained build's clock starts at the earliest
    ``Task <n> supervisor`` dispatch whose prompt contains ``find`` (default: ``plan``), and
    falls back to the first task dispatch when there is none. The dispatch chosen, and any
    fall-back, are printed on stderr.
    """
    t = load_sessions(projects_dir, sessions)
    if first_task is None:
        found = None
        if mode == "chained":
            needle = find or plan
            found = first_supervisor_at(t, needle)
            if found is None:
                print(
                    f"build-metrics: no 'Task <n> supervisor' dispatch has {needle} in its "
                    "prompt; falling back to the first task dispatch",
                    file=sys.stderr,
                )
        if found is None:
            found = first_task_at(t)
        if found is None:
            raise ValueError("no task dispatch found in the sessions")
        print(
            f"build-metrics: first task {found.description!r} at {_iso(found.ts)}",
            file=sys.stderr,
        )
        first_task = found.ts
    review = final_review_end(t)
    if review is not None and review > handover_at:
        review = handover_at  # a review that ends after the handover is cut off at it
    return BuildRecord(
        pr=pr,
        mode=mode,
        plan=plan,
        sessions=tuple(sessions),
        first_task_at=first_task,
        handover_at=handover_at,
        final_review_at=review,
        cost_usd=cost_usd(t.calls, first_task, handover_at),
    )


def report_rows(records: Sequence[BuildRecord], prs: Mapping[int, PullRequest]) -> list[dict]:
    rows = []
    for rec in sorted(records, key=lambda r: r.handover_at):
        pull = prs[rec.pr]
        edits = edits_after(pull, rec.handover_at)
        after_review = None
        if rec.mode == "chained" and rec.final_review_at is not None:
            after_review = edits_after(pull, rec.final_review_at).share
        rows.append(
            {
                "pr": rec.pr,
                "mode": rec.mode,
                "time_h": (rec.handover_at - rec.first_task_at).total_seconds() / 3600,
                "cost_total": sum(rec.cost_usd.values()),
                "commits": edits.commits,
                "lines": edits.lines,
                "share": edits.share,
                "parked_commits": edits.parked_commits,
                "share_after_final_review": after_review,
                # An open PR's edits after handover are still growing.
                "merged": pull.merged_at is not None,
            }
        )
    return rows


REPORT_HEADER = [
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


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _median(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def _count(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render_report(rows: list[dict]) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines = [line(REPORT_HEADER), line(["---"] * len(REPORT_HEADER))]
    for r in rows:
        lines.append(
            line(
                [
                    f"#{r['pr']}",
                    r["mode"],
                    f"{r['time_h']:.1f}",
                    f"{r['cost_total']:.2f}",
                    str(r["commits"]),
                    str(r["lines"]),
                    _pct(r["share"]),
                    str(r["parked_commits"]),
                    _pct(r["share_after_final_review"]),
                    "yes" if r["merged"] else "no",
                ]
            )
        )
    for mode in dict.fromkeys(r["mode"] for r in rows):
        group = [r for r in rows if r["mode"] == mode]
        lines.append(
            line(
                [
                    f"median ({mode})",
                    "",
                    f"{_median(r['time_h'] for r in group):.1f}",
                    f"{_median(r['cost_total'] for r in group):.2f}",
                    _count(_median(r["commits"] for r in group)),
                    _count(_median(r["lines"] for r in group)),
                    _pct(_median(r["share"] for r in group)),
                    _count(_median(r["parked_commits"] for r in group)),
                    _pct(_median(r["share_after_final_review"] for r in group)),
                    "",
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _projects_dir(arg: str | None) -> Path:
    return Path(os.path.expanduser(arg or "~/.claude/projects"))


def _cmd_record(args: argparse.Namespace) -> int:
    projects_dir = _projects_dir(args.projects_dir)
    needle = args.find or args.plan
    sessions = list(args.session)
    if not sessions:
        sessions = find_sessions(projects_dir, needle)
        if args.mode == "chained":
            # Other sessions name the plan too: a chat about it, another build of it.
            sessions = chain_sessions(projects_dir, sessions)
    if not sessions:
        stage = " and dispatched a chain stage" if args.mode == "chained" else ""
        print(
            f"build-metrics: no session names {needle}{stage} under {projects_dir}",
            file=sys.stderr,
        )
        return 2
    print(f"build-metrics: sessions: {', '.join(sessions)}", file=sys.stderr)
    if args.first_task is not None:
        print(f"build-metrics: first task {_iso(args.first_task)} (--first-task)", file=sys.stderr)
    try:
        rec = build_record(
            pr=args.pr,
            mode=args.mode,
            plan=args.plan,
            sessions=sessions,
            projects_dir=projects_dir,
            handover_at=args.handover or datetime.now(timezone.utc),
            first_task=args.first_task,
            find=needle,
        )
    except ValueError as exc:
        print(f"build-metrics: {exc}", file=sys.stderr)
        return 2
    print(render_block(rec))
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    projects_dir = _projects_dir(args.projects_dir)
    entries = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = []
    for entry in entries:
        session = entry["session"]
        t = load_sessions(projects_dir, [session])
        raw_override = entry.get("first_task_at")
        override = _parse_ts(raw_override)
        if raw_override is not None and override is None:
            # An override exists because the found dispatch is wrong: never fall back to it.
            print(
                f"build-metrics: PR {entry['pr']}: first_task_at {raw_override!r} is not ISO-8601",
                file=sys.stderr,
            )
            return 2
        matched = first_task_at(t)
        first = override or (matched.ts if matched else None)
        if first is None:
            print(f"build-metrics: PR {entry['pr']}: no task dispatch in {session}", file=sys.stderr)
            return 2
        pull = fetch_pr(entry["pr"])
        handover = baseline_handover(pull, t)
        rec = build_record(
            pr=entry["pr"],
            mode="single-session",
            plan="(baseline)",
            sessions=[session],
            projects_dir=projects_dir,
            handover_at=handover,
            first_task=first,
        )
        records.append(rec)
        what = "(first_task_at override)" if override or matched is None else repr(matched.description)
        print(
            f"PR {rec.pr}: first dispatch {what}; first task {_iso(first)}; "
            f"handover {_iso(handover)}; ${sum(rec.cost_usd.values()):.2f}"
        )
    records.sort(key=lambda r: r.pr)
    Path(args.out).write_text(
        json.dumps([record_to_dict(r) for r in records], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline) if args.baseline else DEFAULT_BASELINE
    records: dict[int, BuildRecord] = {}
    if baseline_path.exists():
        for item in json.loads(baseline_path.read_text(encoding="utf-8")):
            rec = record_from_dict(item)
            if rec is not None:
                records[rec.pr] = rec
    elif args.baseline:
        print(f"build-metrics: no baseline file at {baseline_path}", file=sys.stderr)
        return 2
    pages = gh_json([f"repos/{REPO}/pulls?state=all&per_page=100", "--paginate", "--slurp"])
    pulls = sorted((p for page in pages for p in page), key=lambda p: p["number"], reverse=True)
    for pull in pulls[: args.limit]:
        rec = parse_block(pull.get("body") or "")
        if rec is not None:
            records[rec.pr] = rec
    prs = {n: fetch_pr(n) for n in records}
    print(render_report(report_rows(list(records.values()), prs)), end="")
    return 0


def _iso_arg(value: str) -> datetime:
    ts = _parse_ts(value)
    if ts is None:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 time: {value!r}")
    return ts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_metrics", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="print the build-metrics block for a PR body")
    rec.add_argument("--pr", type=int, required=True)
    rec.add_argument("--plan", required=True)
    rec.add_argument(
        "--find",
        help="string that names the build's sessions and supervisors (default: --plan); "
        "a chained build passes its ledger's absolute path",
    )
    rec.add_argument("--mode", default="chained", choices=["chained", "single-session"])
    rec.add_argument("--session", action="append", default=[])
    rec.add_argument("--handover", type=_iso_arg)
    rec.add_argument("--first-task", type=_iso_arg, help="start the clock here (ISO-8601)")
    rec.add_argument("--projects-dir")
    rec.set_defaults(func=_cmd_record)

    base = sub.add_parser("baseline", help="build the single-session baseline file")
    base.add_argument("--input", required=True)
    base.add_argument("--out", required=True)
    base.add_argument("--projects-dir")
    base.set_defaults(func=_cmd_baseline)

    rep = sub.add_parser("report", help="print the report table")
    rep.add_argument("--baseline")
    rep.add_argument("--limit", type=int, default=200)
    rep.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        # Name the call that failed: report and baseline make one per PR and commit.
        detail = (exc.stderr or "").strip() or f"exit {exc.returncode}"
        print(f"build-metrics: {' '.join(map(str, exc.cmd))} failed: {detail}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
