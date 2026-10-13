# #271 predecessor heads — recorded at Task 0 phase B (2026-09-27)

- **Local root:** `feat/langgraph-core` = `12a521dc771f7e004375d9607390e09f59973f1c` (Merge #270).
- **This branch:** `plan/lakebase-contract-acceptance-271`, HEAD `9a63ab1b74e2559e38c2aecc0bb6a21416f5b4e3` at probe time, rebased onto `12a521dc7`.
- **INTEGRATION_BASE** = `12a521dc7` (file `INTEGRATION_BASE`, written at Phase B start; not rewritten here). **TASK1_BASE** (file) = `0500629354d5…`, the pre-rebase Phase A base; it is immutable history and is NOT an ancestor of the rebased HEAD (expected: the rebase rewrote the Phase A commits). `a08389ec3` (Phase A code base) IS an ancestor of `INTEGRATION_BASE`.
- Source: `git log --merges --first-parent feat/langgraph-core`; parents from `git rev-parse <merge>^1 <merge>^2`; branch tips from `git branch -v --no-abbrev`; worktree HEADs from `git -C .worktrees/issue-26N-plan rev-parse HEAD`.

| Ticket | Merge commit on `feat/langgraph-core` | `^1` / `^2` | Reviewed head (= `^2`) | Last code commit in the reviewed range | Evidence it is the reviewed head | Ancestor of HEAD | Ancestor of INTEGRATION_BASE |
|---|---|---|---|---|---|---|---|
| #264 | `c040dbde0` Merge #264: safe output-schema overlays | `d72ad974d` / `e3aa3650c` | `e3aa3650c` | — | merged before #271 planning; recorded by #265–#267 ledgers | yes | yes |
| #266 | `e91fcd856` Merge #266: exact model endpoint discovery and validation | `50c8cbf35` / `3189ad5ad` | `3189ad5ad` | — | as above | yes | yes |
| #267 | `a08389ec3` Merge #267: run versioned Agent Test Cases against a draft | `e91fcd856` / `adbc6fef7` | `adbc6fef7` | — | Phase A code base of this plan | yes | yes |
| xdist fix | `82309f48d` Merge: stable parametrised test ids so xdist can collect | `a08389ec3` / `ab2f1e749` | `ab2f1e749` (`fix/stable-test-ids` tip) | `ab2f1e749` | branch tip == `^2`; ruled in the #271 Task 1 record | yes | yes |
| #268 | `16aa02b76` Merge #268: test evidence, verdicts and draft readiness | `82309f48d` / `dd129b832` | `dd129b832` (`feat/test-evidence-readiness-268` tip, "docs: record #268 whole-branch fix wave and controller check") | `2c008c97e` (whole-branch fix N1/m2) | branch tip == `^2` == `git -C .worktrees/issue-268-plan rev-parse HEAD` | yes | yes |
| #269 | `c7ea1d943` Merge #269: Graph Release publication | `16aa02b76` / `126ea2bb6` | `126ea2bb6` (`plan/publish-release-269` tip, "docs: record #269 merge gate") | `8666939de` (whole-branch fix m1/m2) | branch tip == `^2` == worktree HEAD; #270's `predecessor-heads.md` records the same | yes | yes |
| #270 | `12a521dc7` Merge #270: Graph Release history and rollback | `c7ea1d943` / `7b5bcc1df` | `7b5bcc1df` (`plan/release-history-rollback-270` tip, "docs: record #270 whole-branch fix wave and merge gate") | `8fd1e046c` (whole-branch fix, Task 8 N2) | branch tip == `^2` == worktree HEAD | yes | yes |

Ancestry: `git merge-base --is-ancestor <h> HEAD` and `… 12a521dc7` printed yes for every commit above (`7b5bcc1df 126ea2bb6 dd129b832 ab2f1e749 adbc6fef7 3189ad5ad e3aa3650c 12a521dc7 c7ea1d943 16aa02b76 82309f48d a08389ec3 e91fcd856 c040dbde0`).

## INTEGRATION_BASE..HEAD at probe time

`git log --oneline 12a521dc7..HEAD` = 13 commits. Non-docs files per commit (`git diff-tree --name-only -r`, excluding `docs/` and `.superpowers/`):

| Commit | Kind | Code files |
|---|---|---|
| `f8cb8dd86` plan; `372878aaf` OQ rulings; `677e4573e` corrections | docs | none |
| `92c1fa49a` Task 1 (rebased) | test | `tests/conftest.py`, `tests/unit/test_unit_suite_database_isolation.py`, `tests/unit/test_style_exclusivity_chokepoint.py`, `tests/unit/test_style_exclusivity_persistence_boundary.py` |
| `adc42fdba`, `c130ccaab`, `7bbab3065` | docs | none |
| `761e76703` Task 5 (rebased) | build | `packages/databricks-tellr-app/pyproject.toml`, `pyproject.toml`, `requirements.txt`, `tests/unit/test_app_wheel_dependencies.py` |
| `f41f6d86d`, `a88c3215a` | docs | none |
| `119e673ce` Task 5 fix round (rebased) | build | the same four files |
| `383fcd70b`, `9a63ab1b7` | docs | none |

- `git diff --stat 12a521dc7 HEAD -- src tests frontend packages .github scripts pyproject.toml requirements.txt` = 8 files, +272/−31. `git diff --stat 119e673ce HEAD -- <same>` is empty, and `git diff --stat 12a521dc7 HEAD -- src frontend .github scripts` is empty. So code-wise the range is exactly the three rebased Phase A code commits.
- Rebase fidelity: `git patch-id --stable` over each commit's non-docs diff is identical pre/post rebase: `d92eae76d`=`92c1fa49a` (`6a8ea108b88b`), `3767ef831`=`761e76703` (`4543f6ce8e07`), `52972f731`=`119e673ce` (`e99687a1fa2b`).

## Pre-merge gate (Task 14 Step 7) must re-run

For every row: `git merge-base --is-ancestor <reviewed head> HEAD` and `… feat/langgraph-core`; `git rev-parse <branch>` still equals the reviewed head; `git rev-parse feat/langgraph-core` still `12a521dc7` (any advance must be rebased onto, with corrections and baselines refreshed).
