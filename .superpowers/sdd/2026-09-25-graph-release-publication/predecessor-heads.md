# #269 predecessor heads — recorded at Task 0 (2026-09-26)

- **Local root:** `feat/langgraph-core` = `16aa02b76bbec9a22d16e9cc606b09d62c8b450c` (Merge #268).
- **This branch:** `plan/publish-release-269`, HEAD `cd63aa09b00f2fe1e1e5ba8def75c65ec7d84ab3`, rebased onto `16aa02b76`.
  `git log 16aa02b76..HEAD` = 9 commits, all plan/ledger docs; `git diff --stat 16aa02b76 HEAD -- src tests frontend packages .github` is empty.
- **TASK1_BASE = INTEGRATION_BASE = `cd63aa09b`.** The plan (line 16) wants two distinct immutable bases because it assumed Phase A (Tasks 1–3) would be built before #266/#267/#268 integrated. All four predecessors merged first, so no Tasks 1–3 exist to rebase: the integration base *is* the Task 1 base. Both files are written once, read-only (`chmod a-w`). Consequence for Task 9: `INTEGRATION_BASE..HEAD` is exactly Tasks 1–8 (no rebased Phase A to prove), and Task 0 Step 4's "rebase Tasks 1–3 above it" is vacuous.

Source of the merge list: `git log --merges --oneline feat/langgraph-core | head`.

| Ticket | Merge commit on `feat/langgraph-core` | Merge parents (`^1` / `^2`) | Reviewed branch head (= `^2`) | Evidence it is the reviewed head | Ancestor of HEAD `cd63aa09b` | Ancestor of `feat/langgraph-core` |
|---|---|---|---|---|---|---|
| #264 | `c040dbde0` Merge #264: safe output-schema overlays | `d72ad974d` / `e3aa3650c` | `e3aa3650c` (`feat/schema-overlay-264` tip) | branch tip == merge `^2` | yes (`git merge-base --is-ancestor`) | yes |
| #266 | `e91fcd856` Merge #266: exact model endpoint discovery and validation | `50c8cbf35` / `3189ad5ad` | `3189ad5ad` (`plan/model-discovery-266` tip, "docs: record #266 whole-branch fix wave and re-review") | branch tip == merge `^2`; tip commit records the whole-branch re-review | yes | yes |
| #267 | `a08389ec3` Merge #267: run versioned Agent Test Cases against a draft | `e91fcd856` / `adbc6fef7` | `adbc6fef7` (`feat/agent-test-case-runs-267` tip, "docs: record #267 whole-branch fix wave and re-review") | branch tip == merge `^2` | yes | yes |
| #268 | `16aa02b76` Merge #268: test evidence, verdicts and draft readiness | `82309f48d` / `dd129b832` | `dd129b832` (`feat/test-evidence-readiness-268` tip) | branch tip == merge `^2`; #268 `progress.md` ends "Whole-branch: complete — MERGE"; last code commit `2c008c97e` (fix wave, controller-checked); `git diff --stat 2c008c97e dd129b832 -- src tests frontend` empty | yes | yes |

Other ancestors noted (not predecessors, recorded so Task 9's pre-merge gate can re-resolve them): `3ed8f9b6a` Merge #265 (ancestor: yes), `6cbab388a` builder payload/unknown-role fixes, `50c8cbf35` session identifiers out of model payload, `82309f48d` stable parametrised test ids (all ancestors: yes).

Pre-merge gate (Task 9) must re-run: for each row, `git merge-base --is-ancestor <reviewed head> HEAD` and `… feat/langgraph-core`, and `git rev-parse <branch>` still equal to the reviewed head above; any advance means rebase + refreshed corrections/baselines.
