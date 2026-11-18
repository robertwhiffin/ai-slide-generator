# Chained Plan Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, with the `executing-plans-tellr` skill. Steps use checkbox (`- [ ]`) syntax for tracking.

Execution: single-session

(This plan builds the chained mode, so it runs the current way.)

**Goal:** Add a `chained` execution mode (the new default) to the `executing-plans-tellr` skill, keep today's practice as `single-session`, and add a script that measures time, cost and edits after handover for every build against a committed baseline.

**Architecture:** The skill gains a mode switch and a new §10 describing the chain: a thin top-level session dispatches a pre-pass agent, one Opus supervisor per task, and a final agent that ends at a ready-for-review PR. All state lives in the ledger. Dispatch briefs are template files next to `SKILL.md`. `scripts/build_metrics.py` parses Claude Code transcripts and GitHub PR data. It stores each chained build's record as a hidden block in the PR body (durable on GitHub), keeps the baseline in `docs/agents/build-metrics-baseline.json`, and prints a comparison table.

**Tech Stack:** Python 3 standard library (`json`, `dataclasses`, `datetime`, `re`, `subprocess`, `argparse`, `pathlib`), pytest, `gh` CLI, Markdown.

**Spec:** `docs/superpowers/specs/2026-11-13-chained-plan-execution-design.md`

## Global Constraints

- Python env: per-worktree uv venv (`uv sync --extra dev` in the worktree root); run everything with `uv run`; never `pip install`.
- `scripts/build_metrics.py` uses the standard library only. No dependency changes.
- Unit tests never read `~/.claude`, never call `gh`, never touch the network. The transcript root and the `gh` runner are parameters.
- Prices, $ per million tokens (list prices, relative only), input / output / cache read / cache write: opus 4.00 / 20.00 / 0.20 / 8.00; sonnet 2.00 / 10.00 / 0.10 / 4.00; haiku 0.10 / 0.50 / 0.01 / 0.20. Any other model costs 0 and is not reported.
- GitHub: repo `robertwhiffin/ai-slide-generator`, personal account `robertwhiffin`, never the EMU account.
- No thresholds and no automatic revert anywhere. The user decides by hand. (Spec: "When to revert".)
- `SKILL.md` §1–§9 body text stays word for word. Only additions, plus the frontmatter `description`.
- Plan header syntax: a line `Execution: chained` or `Execution: single-session`. A missing line means the skill's default.
- Default-mode line in `SKILL.md`, exactly: `**Default mode: chained.**`
- Agent `description` for chained stages, exactly: `Pre-pass`, `Task <n> supervisor`, `Final agent`. The final agent's §7 review dispatch is `Final branch review`. The metrics script keys on `Task <n>` and on `final` (but not `Final agent`).
- Revert tag: `executing-plans-tellr/single-session-v1` on the merge-base with `origin/main`. It must not start with `v`, because `.github/workflows/publish.yml` publishes to PyPI on `v*` tags.
- Chained builds end at the handover: the PR is marked ready for review, or, for a build with parked tasks, the final agent finishes with the PR still a draft. No devloop deploy inside the chain.

## Review Focus

1. **A tag starting with `v` publishes to PyPI.** Expect the revert tag to be pushed safely. Task 7 Step 1 checks the name before tagging.
2. **Model ids arrive prefixed (`system.ai.claude-opus-5-5`), as `<synthetic>`, or non-Claude (`system.ai.gpt-6-1-sol`).** Expect them to be classified by family, and unknown ones to cost nothing. Task 1 `test_model_ids_are_classified_by_family`.
3. **One API response spans several transcript lines with the same message id.** Expect it to be counted once. Task 1 `test_split_message_counted_once`.
4. **Merging `main` into the branch after handover.** Expect it not to count as a miss. Task 2 `test_merge_commits_are_not_edits`.
5. **The top-level session dies mid-chain.** Expect a fresh session to resume from the last `NEXT:` line alone. Task 6 runs it.

## File map

- Create `scripts/build_metrics.py`: transcripts, cost, GitHub, edits, records, CLI.
- Create `tests/unit/test_build_metrics.py`.
- Create `docs/agents/build-metrics-baseline.json` (generated in Task 4).
- Modify `scripts/README.md`: a `build_metrics.py` section.
- Modify `.claude/skills/executing-plans-tellr/SKILL.md`: mode switch and §10.
- Create `.claude/skills/executing-plans-tellr/pre-pass-brief.md`, `task-supervisor-brief.md`, `final-agent-brief.md`.
- Modify `CLAUDE.md`: the `Execution:` line and the resume phrase.

**Order:** 1 → 2 → 3 → 4, then 5 → 6 → 7. Task 5 only names the Task 3 CLI commands. Everything runs sequentially in one worktree.

---

### Task 1: Transcripts and cost

`Models: test=opus impl=sonnet`

**Files:**
- Create: `scripts/build_metrics.py`
- Test: `tests/unit/test_build_metrics.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ApiCall:
    ts: datetime          # timezone-aware UTC
    family: str           # "opus" | "sonnet" | "haiku"
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
    dispatches: tuple[Dispatch, ...]   # Agent tool_use blocks in main AND subagent transcripts
    spans: tuple[AgentSpan, ...]       # one per subagent transcript

PRICES: dict[str, tuple[float, float, float, float]]   # family -> (input, output, cache_read, cache_write) $/M
TASK_RE = re.compile(r"\btask\s*\d+|^T\d+\b", re.I)
FINAL_RE = re.compile(r"\bfinal\b(?! agent)|whole[- ]branch", re.I)

def model_family(model_id: str) -> str | None
def load_sessions(projects_dir: Path, session_ids: Sequence[str]) -> Transcript
def find_sessions(projects_dir: Path, needle: str) -> list[str]          # sorted session ids
def cost_usd(calls: Iterable[ApiCall], start: datetime, end: datetime) -> dict[str, float]
def first_task_at(t: Transcript) -> Dispatch | None                       # earliest dispatch matching TASK_RE
def final_review_end(t: Transcript) -> datetime | None                    # latest span.end whose description matches FINAL_RE
```

**Transcript layout** (the test helper writes exactly this):
- Main transcript: `<projects_dir>/<any project dir>/<session_id>.jsonl`. Subagents at any depth: `<projects_dir>/<same dir>/<session_id>/subagents/agent-<id>.jsonl`, with a sibling `agent-<id>.meta.json` holding `"description"` (nested ones also hold `"parentAgentId"`).
- An assistant line: `{"type": "assistant", "timestamp": "<ISO-8601 Z>", "message": {"id": "...", "model": "...", "usage": {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}, "content": [...]}}`. The same `message.id` repeats on several lines with identical usage; count it once per transcript.
- A dispatch is a content block `{"type": "tool_use", "name": "Agent", "input": {"description": "..."}}`.
- A subagent's span runs from its first to its last line `timestamp`. Its description comes from its meta file.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_build_metrics.py`, with a helper `write_session(root, session_id, main_lines, subagents: dict[str, tuple[str, list[dict]]])` and a line builder `assistant(ts, msg_id, model, *, input=0, output=0, cache_read=0, cache_write=0, dispatch=None)`:
  - `test_split_message_counted_once`: two lines, same id, opus, `output=1000` → `cost_usd(...) == {"opus": pytest.approx(0.02)}`.
  - `test_model_ids_are_classified_by_family`: `model_family("system.ai.claude-opus-5-5") == "opus"`, `("claude-sonnet-5-5") == "sonnet"`, `("claude-haiku-5-5") == "haiku"`, `("<synthetic>") is None`, `("system.ai.gpt-6-1-sol") is None`. A session with one gpt call and one haiku call → `cost_usd` keys are exactly `{"haiku"}`.
  - `test_cost_prices_every_token_kind`: one opus call with 1,000,000 of each token kind → `pytest.approx(32.2)`. One sonnet call → `pytest.approx(16.1)`.
  - `test_cost_window_is_inclusive`: calls at `start - 1s`, `start`, `end`, `end + 1s`, each opus `output=1_000_000` → `pytest.approx(40.0)`.
  - `test_subagents_at_any_depth_are_loaded`: one main call plus two subagent files (one meta with `parentAgentId`) → `len(t.calls) == 3` and `len(t.spans) == 2`.
  - `test_find_sessions_matches_needle_in_main_or_subagent`: A has `docs/superpowers/plans/x.md` in a main line, B only in a subagent line, C nowhere → `["A", "B"]`.
  - `test_first_task_at_ignores_prepass_and_exploration`: dispatches `"Explore tests dir"` (t0), `"Pre-pass"` (t1), `"Task 1 supervisor"` (t2), `"Task 2 supervisor"` (t3) → returns the t2 dispatch. A transcript whose only dispatch is `"T9 docs writer"` → that one.
  - `test_final_review_end_is_last_matching_span_end`: spans `"Final branch review"` (end t5), `"Review Task 2"` (end t6), `"Final review re-run"` (end t7), `"Final agent"` (end t8) → t7. `"Final agent"` alone → `None`. No spans → `None`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: FAIL (`ModuleNotFoundError: scripts.build_metrics`).

- [ ] **Step 3: Implement the Task 1 interfaces in `scripts/build_metrics.py`**

Parse transcripts with `json.loads` per line and skip lines that fail to parse. `model_family` classifies by substring `opus` / `sonnet` / `haiku`. `cost_usd` drops families not in `PRICES`. Module docstring: what the script measures, plus "list prices, relative only".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/build_metrics.py tests/unit/test_build_metrics.py
git commit -m "feat(build-metrics): transcript parsing and list-price cost"
```

---

### Task 2: GitHub data, handover and edits

`Models: test=opus impl=sonnet`

**Files:**
- Modify: `scripts/build_metrics.py`
- Test: `tests/unit/test_build_metrics.py`

**Interfaces:**
- Consumes: `Transcript`, `final_review_end` (Task 1).
- Produces:

```python
REPO = "robertwhiffin/ai-slide-generator"
PARKED_RE = re.compile(r"^Parked-task:\s*\S+", re.M)
GhJson = Callable[[list[str]], Any]     # runs `gh api <args>`, returns parsed JSON

@dataclass(frozen=True)
class Commit:
    sha: str
    committed_at: datetime
    parents: int
    lines: int          # additions + deletions (API stats.total)
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
    share: float          # lines / all non-merge lines in the PR; 0.0 when the PR has none
    parked_commits: int
    parked_lines: int

def gh_json(args: list[str]) -> Any       # subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
def fetch_pr(number: int, *, repo: str = REPO, gh: GhJson = gh_json) -> PullRequest
def baseline_handover(pr: PullRequest, t: Transcript) -> datetime   # max(pr.created_at, final_review_end(t)), or created_at if none
def edits_after(pr: PullRequest, handover: datetime) -> Edits
```

`fetch_pr` calls, in order: `[f"repos/{repo}/pulls/{n}"]`, then `[f"repos/{repo}/pulls/{n}/commits?per_page=100", "--paginate", "--slurp"]` (a list of pages; flatten it), then `[f"repos/{repo}/commits/{sha}"]` for each commit (`stats.total`). Use `commit.committer.date` and `len(parents)`.

`edits_after` rules: only non-merge commits (`parents == 1`) count, and only those strictly after `handover`. A commit whose message matches `PARKED_RE` goes in the parked bucket instead of the miss bucket. The `share` denominator is every non-merge commit in the PR.

- [ ] **Step 1: Write the failing tests** (a fake `gh` built from a dict `{tuple(args): json}`):
  - `test_fetch_pr_parses_commits_and_lines`: a PR with one normal commit (`stats.total` 120) and one merge commit (2 parents) → two `Commit`s with `lines` 120 and the merge's total, `parents` 1 and 2, `created_at` timezone-aware.
  - `test_edits_after_counts_only_commits_after_handover`: commits at `h - 1h` (100 lines), exactly `h` (10), `h + 1h` (30) → `Edits(commits=1, lines=30, share=pytest.approx(30 / 140), parked_commits=0, parked_lines=0)`.
  - `test_merge_commits_are_not_edits`: add a merge commit at `h + 2h` with 500 lines → counts and share unchanged from the previous case.
  - `test_parked_task_trailer_is_reported_separately`: a commit at `h + 1h`, message `"fix: finish export\n\nParked-task: 3"`, 40 lines → `parked_commits == 1`, `parked_lines == 40`, and it is not in `commits`.
  - `test_share_is_zero_for_empty_pr`: no commits → `share == 0.0`.
  - `test_baseline_handover_is_later_of_pr_open_and_final_review`: final review ends after `created_at` → that end; ends before → `created_at`; no final span → `created_at`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: the 6 new tests FAIL (`ImportError` / `AttributeError`); Task 1's 8 pass.

- [ ] **Step 3: Implement the Task 2 interfaces in `scripts/build_metrics.py`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/build_metrics.py tests/unit/test_build_metrics.py
git commit -m "feat(build-metrics): PR commits, handover and edits after it"
```

---

### Task 3: Records, report and CLI

`Models: test=opus impl=sonnet`

**Files:**
- Modify: `scripts/build_metrics.py`, `scripts/README.md`
- Test: `tests/unit/test_build_metrics.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces:

```python
BLOCK_START = "<!-- build-metrics"
BLOCK_END = "-->"

@dataclass(frozen=True)
class BuildRecord:
    pr: int
    mode: str                 # "chained" | "single-session"
    plan: str                 # plan path, or "(baseline)"
    sessions: tuple[str, ...]
    first_task_at: datetime
    handover_at: datetime
    final_review_at: datetime | None   # final_review_end() at record time
    cost_usd: dict[str, float]

def render_block(rec: BuildRecord) -> str    # BLOCK_START, newline, one-line JSON (sort_keys, "version": 1, ISO-8601 Z times), newline, BLOCK_END
def parse_block(body: str) -> BuildRecord | None
def build_record(*, pr: int, mode: str, plan: str, sessions: Sequence[str], projects_dir: Path,
                 handover_at: datetime, first_task: datetime | None = None) -> BuildRecord
def report_rows(records: Sequence[BuildRecord], prs: Mapping[int, PullRequest]) -> list[dict]
def render_report(rows: list[dict]) -> str
def main(argv: list[str] | None = None) -> int
```

`report_rows` returns one dict per record with keys `pr, mode, time_h, cost_total, commits, lines, share, parked_commits, share_after_final_review`, sorted by `handover_at`. `cost_total` is the sum of `cost_usd`. `share_after_final_review` is `edits_after(pr, final_review_at).share` for chained records with a `final_review_at`, else `None`. `render_report` prints a Markdown table with the columns `PR | mode | time to handover (h) | cost to handover ($) | edits after: commits | lines | share | parked commits | share after final review`, then one `median (<mode>)` row per mode present. No thresholds.

CLI (`uv run python -m scripts.build_metrics <command>`). `--projects-dir` defaults to `~/.claude/projects`.
- `record --pr N --plan PATH [--mode chained] [--session ID ...] [--handover ISO] [--projects-dir DIR]`: sessions default to `find_sessions(projects_dir, plan)`; handover defaults to now (UTC). Prints `render_block(...)` to stdout. Exit 2 with a message on stderr if no session is found or `first_task_at` is `None`.
- `baseline --input JSON --out PATH [--projects-dir DIR]`: the input is a list of `{"pr": int, "session": str, "first_task_at"?: ISO}`. For each entry: load the session, find the first task (or use the override), `fetch_pr`, `baseline_handover`, cost in the window, mode `single-session`, plan `"(baseline)"`. Writes a JSON list sorted by `pr`. Prints one line per build: PR, matched first-dispatch description, first task, handover, total $.
- `report [--baseline PATH] [--limit N]`: records = the baseline file (default `docs/agents/build-metrics-baseline.json`) plus `parse_block` of every PR body from `gh api repos/{REPO}/pulls?state=all&per_page=100 --paginate --slurp` (newest `--limit`, default 200). Calls `fetch_pr` for each record and prints `render_report`.

- [ ] **Step 1: Write the failing tests**
  - `test_block_round_trips`: `parse_block(render_block(rec)) == rec`.
  - `test_parse_block_absent_or_malformed_returns_none`: a body without the block → `None`; a block with invalid JSON → `None`.
  - `test_block_survives_surrounding_body`: handover prose before and after the block → parses.
  - `test_build_record_windows_cost_from_first_task_to_handover`: opus calls before the first `Task 1 supervisor` dispatch, between it and handover, and after handover (each `output=1_000_000`) → `cost_usd == {"opus": pytest.approx(20.0)}`.
  - `test_report_rows_compute_time_cost_and_edits`: a record with a 5 h window and `{"opus": 10.0, "sonnet": 2.5}`, plus a PR with one 30-line commit after handover of 140 lines total → row `time_h == pytest.approx(5.0)`, `cost_total == pytest.approx(12.5)`, `commits == 1`, `share == pytest.approx(30 / 140)`.
  - `test_report_rows_include_share_after_final_review`: a chained record with `final_review_at = handover - 1h`, plus a 20-line commit between the two and a 30-line commit after handover (140 total) → `share_after_final_review == pytest.approx(50 / 140)`. A `single-session` record → `None`.
  - `test_render_report_has_median_row_per_mode`: rows of both modes → output contains `median (chained)` and `median (single-session)`.
  - `test_cli_record_prints_block`: `main(["record", "--pr", "7", "--plan", "docs/superpowers/plans/x.md", "--handover", "<ISO>", "--projects-dir", str(tmp)])` returns 0, and `parse_block(capsys stdout).pr == 7`.
  - `test_cli_record_exits_2_without_sessions`: an empty projects dir → returns 2.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: the 9 new tests FAIL; 14 pass.

- [ ] **Step 3: Implement the Task 3 interfaces, and add a `build_metrics.py` section to `scripts/README.md`** (what it measures, the three commands, "list prices, relative only", "the user reads the report and decides; no thresholds").

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: PASS (23 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/build_metrics.py scripts/README.md tests/unit/test_build_metrics.py
git commit -m "feat(build-metrics): PR-body records, baseline and report commands"
```

---

### Task 4: Baseline

`Models: test=n/a impl=opus (controller)`

**Files:**
- Create: `docs/agents/build-metrics-baseline.json`

**Interfaces:**
- Consumes: the `baseline` and `report` commands (Task 3).

- [ ] **Step 1: Write the input** to `~/tellr-loop/chained-plan-execution/baseline-input.json`:

| pr | session |
|---|---|
| 359 | `dfd8af7c-6886-4b96-b4f0-37416a87dfe3` |
| 385 | `742d711f-3942-455e-8991-313f731c4609` |
| 384 | `bc92b130-7822-48a0-891e-1f234186f197` |
| 360 | `816dc5cb-afcc-4331-9dfc-bdd544ee3b7d` |
| 354 | `ebd20c8f-55a5-4a7e-af25-33e29f98c436` |
| 356 | `bea865f1-408c-431d-abf2-2178a1c0e9f1` |
| 347 | `dafb74a1-38ea-4e1c-96e1-5a3b19312ed0` |
| 351 | `125625f6-cd95-43d5-b8b4-a8964179e636` |

- [ ] **Step 2: Generate the baseline**

Run: `uv run python -m scripts.build_metrics baseline --input ~/tellr-loop/chained-plan-execution/baseline-input.json --out docs/agents/build-metrics-baseline.json`
Expected: 8 lines printed, the file written.

- [ ] **Step 3: Check every matched first dispatch is a build task.** It should not be an investigation or planning agent. Where it isn't, add a `first_task_at` override taken from the transcript, re-run, and note the override in the ledger.

- [ ] **Step 4: Sanity-check against the spec**

Run: `uv run python -m scripts.build_metrics report`
Expected: 8 `single-session` rows and a `median (single-session)` row. Build cost should land near the spec's ~$50 median. Edits after handover should be at or below the spec's first-pass table, because the handover is later than the final-review dispatch. Explain in the ledger any PR that differs from the spec table by more than 5 points of share. Paste the table into the ledger.

- [ ] **Step 5: Commit**

```bash
git add docs/agents/build-metrics-baseline.json
git commit -m "docs(agents): build-metrics baseline from eight single-session builds"
```

---

### Task 5: The skill: mode switch, §10, briefs, CLAUDE.md

`Models: test=n/a (Task 6 runs it) impl=opus`

**Files:**
- Modify: `.claude/skills/executing-plans-tellr/SKILL.md`, `CLAUDE.md`
- Create: `.claude/skills/executing-plans-tellr/pre-pass-brief.md`, `task-supervisor-brief.md`, `final-agent-brief.md`

**Interfaces:**
- Consumes: the CLI commands `record` and `report` (Task 3), by name.
- Produces, for Task 6 and every future chained build:
  - The verdict format, exactly:
    ```
    VERDICT stage=<pre-pass|task-<n>|final> status=<done|parked|failed> next=<task-<n>|final|done>
    commits: <first-sha>..<last-sha> | none
    summary: <one line>
    rulings: <one line, or "none">
    ```
  - The ledger's state line: each stage's entry ends with `NEXT: <task-<n>|final|done>`. The last `NEXT:` line in the ledger is the chain's state.
  - Brief placeholders: `{{SKILL_DIR}}`, `{{PLAN}}`, `{{CORRECTIONS}}`, `{{LEDGER}}`, `{{WORKTREE}}`, `{{BRANCH}}`, `{{TASK}}`, `{{PUBLISH}}` (`yes` | `no`; `no` = smoke run: the final agent does §7 and its fixes, writes the handover to the ledger, and does not push or open a PR).

The implementer writes the prose. These are the decisions it must carry (from the spec):

- [ ] **Step 1: `SKILL.md`, a new section "Choosing the mode", directly after the intro:**
  - The line `**Default mode: chained.**`.
  - Plans may override it with `Execution: chained` or `Execution: single-session`; a missing line means the default.
  - `single-session` is §1–§9 as written, with one coordinating session.
  - `chained` is §10. §1–§9 still apply inside its stages: the "controller" in §1–§9 is the task supervisor or the final agent.
  - Reverting: per plan, edit its `Execution:` line. Globally, flip the default line. Fully, `git show executing-plans-tellr/single-session-v1:.claude/skills/executing-plans-tellr/SKILL.md`.
  - Measuring: `uv run python -m scripts.build_metrics report`. The user reads it and decides. No thresholds.

- [ ] **Step 2: `SKILL.md`, a new "## 10. Chained execution" after §9.** It covers:
  - **Roles:** top-level (the user's session, any model), `Pre-pass` (Opus), `Task <n> supervisor` (Opus, one per task, sequential), `Final agent` (Opus). Those exact descriptions.
  - **Top-level rules:** after plan approval it dispatches stages in order (background, then waits for the notification; no polling) and reads only verdicts. It fills briefs from the template files. It never runs tests, git or deploys, and never reads diffs, transcripts or the ledger. The one exception is resuming: `grep '^NEXT:' <ledger> | tail -1`.
  - **Resume:** "continue the build in `<ledger>`" → read the last `NEXT:` line and dispatch that stage. A stage whose previous attempt died gets a fresh agent of the same stage, which first does §5 salvage.
  - **Ledger:** `~/tellr-loop/<build>/LEDGER.md`, created by the pre-pass. Each stage appends an entry with stage, tiers used, verdicts, rework (stops, fix rounds, rewrites), rulings, parked items with reason, commit range, and start/end UTC. The entry ends with its `NEXT:` line.
  - **Pre-pass:** §2, plus checks for `Execution:` and `Models:` (an untagged task → `status=failed`, listing the tasks). It writes a `Depends on:` line per task into `PLAN-CORRECTIONS.md`, taken from the plan's order/parallelism section, so supervisors never infer dependencies.
  - **Task supervisor:** runs §9's pipeline with §1 sabotage (its own targets; the reviewer gets different ones), §3 and §4. It commits, makes and records rulings, and returns the verdict.
  - **Parking:** a supervisor that cannot proceed parks its task with the reason. It sets `next` to the next task whose `Depends on:` contains no parked task, and records the skipped dependents as parked in its entry.
  - **Final agent:** §7 (dispatched with description `Final branch review`) plus fixes. Then it pushes as `robertwhiffin` (checks `gh auth status`), runs `gh pr create --draft`, waits on `gh pr checks --watch`, and fixes red CI in the chain. Once green it runs `uv run python -m scripts.build_metrics record --pr <n> --plan <plan>` and puts the block into the PR body. The body also carries the handover: rulings, parked items, the `Parked-task: <n>` commit trailer to use when finishing one, and what waits on the user (browser check, devloop deploy, merge). Then `gh pr ready <n>`, unless anything is parked, in which case the PR stays a draft. It writes `NEXT: done`. No devloop deploy.
  - Cross-references from §1–§9 go in §10, not into §1–§9 themselves.

- [ ] **Step 3: The three brief templates.** Each one states its stage, what to read (the `SKILL.md` sections, `{{PLAN}}`, `{{CORRECTIONS}}`, `{{LEDGER}}`), what to write (a ledger entry ending in `NEXT:`), and the literal verdict format. `task-supervisor-brief.md` carries `{{TASK}}`. `final-agent-brief.md` carries `{{PUBLISH}}` and `{{BRANCH}}`.

- [ ] **Step 4: Update the frontmatter `description`** to mention chained (default) and single-session modes, and the trigger "continue the build in".

- [ ] **Step 5: `CLAUDE.md`.** In "Executing an implementation plan", add: plans carry `Execution: chained | single-session` (a missing line means the skill default); "continue the build in `<ledger>`" resumes a chained build; the report command.

- [ ] **Step 6: Verify §1–§9 are untouched**

Run: `git diff origin/main -- .claude/skills/executing-plans-tellr/SKILL.md | grep '^-[^-]'`
Expected: only the old frontmatter `description` line.

Run: `grep -c '^\*\*Default mode: chained\.\*\*$' .claude/skills/executing-plans-tellr/SKILL.md`
Expected: `1`.

Run: `grep -l 'VERDICT stage=' .claude/skills/executing-plans-tellr/*-brief.md | wc -l`
Expected: `3`.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/executing-plans-tellr/ CLAUDE.md
git commit -m "feat(skill): chained execution mode for executing-plans-tellr"
```

---

### Task 6: Smoke run of the chain, including a resume

`Models: test=n/a impl=opus (controller)`

**Files:**
- Throwaway only: `/tmp/chain-smoke/` (toy repo) and `~/tellr-loop/chain-smoke/LEDGER.md`. Fixes to Task 5's files are committed in this worktree.

- [ ] **Step 1: Build the toy repo.** `git init /tmp/chain-smoke`, with `toy/__init__.py`, an empty `toy/calc.py` and an initial commit. Tests run with `<worktree>/.venv/bin/python -m pytest -q`. Write `/tmp/chain-smoke/PLAN.md` with `Execution: chained` and four tasks, each `Models: test=sonnet impl=haiku`:
  - Task 1 `add(a: int, b: int) -> int`.
  - Task 2 `mul(a: int, b: int) -> int`, `Depends on: Task 1`. The task says to read `/tmp/chain-smoke/SPEC-T2.txt` for the rounding rule. That file does not exist, so the supervisor must park.
  - Task 3 `square(x: int) -> int` via `mul`, `Depends on: Task 2` (expected parked by dependency).
  - Task 4 `neg(x: int) -> int`, independent.

- [ ] **Step 2: First half.** Dispatch agent `Smoke top-level A` (Opus). Its brief: you are the top-level session of a chained build; read `{{SKILL_DIR}}/SKILL.md` "Choosing the mode" and §10; plan `/tmp/chain-smoke/PLAN.md`; ledger `~/tellr-loop/chain-smoke/LEDGER.md`; `PUBLISH=no`. Stop after the `Task 1 supervisor` verdict, as if your session died, and report the verdicts you received.

- [ ] **Step 3: Second half.** Dispatch agent `Smoke top-level B` (Opus) with only: the skill pointer, `PUBLISH=no`, and "continue the build in `~/tellr-loop/chain-smoke/LEDGER.md`".

- [ ] **Step 4: Check, and paste the evidence into the build ledger:**
  - a. The ledger has entries for the pre-pass and tasks 1–4 (task 2 parked, its reason naming `SPEC-T2.txt`; task 3 parked by dependency; task 4 done) and the final stage. Every entry has the minimum fields. The last line is `NEXT: done`.
  - b. `/tmp/chain-smoke` has commits for tasks 1 and 4 only, and its tests pass.
  - c. B's first tool call was the `grep '^NEXT:'`.
  - d. A's and B's tool calls are only `Agent`, `Read` of `SKILL.md` or the brief templates, and B's one `grep`. Check by listing the `tool_use` names and inputs in their transcripts: `<controller session>/subagents/agent-<id>.jsonl`, found by the `Smoke top-level` description in the `.meta.json` files.
  - e. The top-level stayed small: the last API call of A and of B had less than 80k tokens of context.
  - f. Supervisors dispatched their own agents. Their transcripts are in the controller session's `subagents/` directory with `parentAgentId` set.
  - g. Every verdict matches the exact format.
  - h. Record the smoke run's cost (`cost_usd` over the run's window) in the ledger.

- [ ] **Step 5: On any failed check,** fix the wording in Task 5's files, commit `fix(skill): <what>`, and re-run the failing half from a fresh toy repo and ledger. Repeat until a–g pass.

---

### Task 7: Revert tag, final review and PR

`Models: test=n/a impl=opus (controller)`

- [ ] **Step 1: Tag the pre-change commit**

```bash
tag=executing-plans-tellr/single-session-v1
case "$tag" in v*) echo "tag would publish to PyPI"; exit 1;; esac
git tag -a "$tag" "$(git merge-base HEAD origin/main)" -m "executing-plans-tellr before chained mode"
git show "$tag:.claude/skills/executing-plans-tellr/SKILL.md" | grep -c 'Default mode'
```

Expected: the last command prints `0`.

- [ ] **Step 2: Whole-branch review (§7)** on Opus, given the ledger's parked/deferred list. Ask for a check of every spec section against the code and the skill text, and a merge/no-merge verdict. Apply the fixes.

- [ ] **Step 3: Tests**

Run: `uv run pytest tests/unit/test_build_metrics.py -q`
Expected: PASS (23 tests).

- [ ] **Step 4: Push and open the PR** as `robertwhiffin` (`gh auth status` shows it active; `gh auth switch -u robertwhiffin` if not):

```bash
git push -u origin feat/chained-plan-execution
git push origin executing-plans-tellr/single-session-v1
gh pr create --title "Chained plan execution for executing-plans-tellr, with build metrics" --body-file <body>
```

The body summarises the spec, the baseline table (Task 4), the smoke-run evidence (Task 6), and how to revert. It ends with `This pull request and its description were written by Isaac.`

- [ ] **Step 5: Wait for CI**

Run: `gh pr checks --watch`
Expected: all checks pass. Fix any that fail.
