# #270 predecessor heads — recorded at Task 0 phase B (2026-09-27)

- **Local root:** `feat/langgraph-core` = `c7ea1d9434f5083c474c4ca73c39cb593384588c` (Merge #269).
- **This branch:** `plan/release-history-rollback-270`, HEAD `7465854f4` at probe time, rebased onto `c7ea1d943`.
- **INTEGRATION_BASE** = `c7ea1d943` (file `INTEGRATION_BASE`, written once). **TASK1_BASE** = `dbbea85e1` (file `TASK1_BASE`, Phase A, unchanged). The two files are distinct, as plan line 17 requires.
- Source of the merge list: `git log --merges --oneline -4 feat/langgraph-core`; parents from `git rev-parse <merge>^1 <merge>^2`.

| Ticket | Merge commit on `feat/langgraph-core` | Parents (`^1` / `^2`) | Reviewed branch head (= `^2`) | Evidence it is the reviewed head | Ancestor of HEAD | Ancestor of `feat/langgraph-core` |
|---|---|---|---|---|---|---|
| #268 | `16aa02b76` Merge #268: test evidence, verdicts and draft readiness | `82309f48d` / `dd129b832` | `dd129b832` (`feat/test-evidence-readiness-268` tip, "docs: record #268 whole-branch fix wave and controller check") | branch tip == merge `^2` (`git branch -v`); #269's `predecessor-heads.md` records the same head | yes | yes |
| #269 | `c7ea1d943` Merge #269: Graph Release publication | `16aa02b76` / `126ea2bb6` | `126ea2bb6` (`plan/publish-release-269` tip, "docs: record #269 merge gate"); last code commit `8666939de` (whole-branch fix) | branch tip == merge `^2`; `git -C .worktrees/issue-269-plan rev-parse HEAD` = `126ea2bb6`; `git diff --stat 8666939de 126ea2bb6 -- src tests frontend packages .github` is empty (only `29c4ad0c6`, `126ea2bb6`, both docs); #269 `progress.md` ends "Whole-branch: complete — MERGE" | yes | yes |

Ancestry commands (all printed "yes"): `git merge-base --is-ancestor <h> HEAD` and `... feat/langgraph-core` for `16aa02b76`, `dd129b832`, `c7ea1d943`, `126ea2bb6`, `8666939de`.

## INTEGRATION_BASE..HEAD at probe time

`git log --oneline c7ea1d943..HEAD` = 8 commits:

| Commit | Kind | Files |
|---|---|---|
| `144deba26` docs: plan graph release history and rollback | docs | plan, `progress.md` |
| `2d31172fe` docs: rule on #270's planning open questions | docs | `progress.md` |
| `c073f6990` docs: record #270 plan corrections from plan review 1 | docs | `PLAN-CORRECTIONS.md`, `progress.md` |
| `29df4c318` feat: immutable graph release history read model (#270) | **Task 1 (rebased)** | `src/services/graph_release_history.py`, `tests/unit/test_graph_release_history.py`, `tests/integration/test_graph_release_history_postgres.py`, `tests/unit/test_ci_collects_integration_tests.py`, `.github/workflows/test.yml` |
| `7610fe177`, `7efbee74f`, `c3e1dbc8e`, `7465854f4` | docs | ledger, `task-1-report.md`, `INTEGRATION_BASE` |

- `git diff --stat c7ea1d943 29df4c318 -- src tests frontend packages .github` = `git diff --stat c7ea1d943 HEAD -- …` = 5 files, +1094 (identical), and `git diff --stat 29df4c318 HEAD -- src tests frontend packages .github` is empty. So code-wise `INTEGRATION_BASE..HEAD` is exactly the rebased Task 1.
- `git range-diff d0e4d693a~1..d0e4d693a 29df4c318~1..29df4c318` differs only in the context lines of the two append-only conflicts (`test.yml` integration-graph list, `test_ci_collects_integration_tests.py`); `git diff d0e4d693a 29df4c318 -- src/services/graph_release_history.py tests/unit/test_graph_release_history.py tests/integration/test_graph_release_history_postgres.py` is empty.

## Pre-merge gate (Task 10) must re-run

For each row: `git merge-base --is-ancestor <reviewed head> HEAD` and `… feat/langgraph-core`, and `git rev-parse <branch>` still equal to the reviewed head. `git rev-parse feat/langgraph-core` must still be `c7ea1d943` (or any advance must be rebased onto, with corrections and baselines refreshed).
