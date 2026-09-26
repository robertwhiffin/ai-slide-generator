# SDD ledger — plan: docs/superpowers/plans/2026-09-26-lakebase-contract-and-epic-acceptance.md

This plan was drafted on 2026-09-26 by a planning agent on `plan/lakebase-contract-acceptance-271`, at base `a08389ec3` (Merge #267). It has Tasks 0–14.

- **Not yet plan-reviewed.** It is executable beyond Phase A (Task 0 phase A, Tasks 1 and 5) only after reviewed #268, #269 and #270 are merged locally and Task 0 phase B has run.
- **Phase A** is Task 0 phase A plus Tasks 1 and 5. These touch no file that #268, #269 or #270 own.
- **Phase B** is Tasks 2–4 and 6–14.
- **AC10 ordering:** Task 12 (the deletion) refuses to start until the Tasks 6–11 suites are green at its base SHA.

## Probes recorded while planning (read-only)

- **P1.** A typecheck of `frontend/tests/**` with a throwaway tsconfig (in `/tmp/probe271-ts`, using the main worktree's node_modules through a symlink) gives 12 errors:
  - 9 × TS2307 on `'/src/…'` browser imports;
  - 2 × TS2339 on `ImportMeta.env`;
  - 1 × TS2740 at `findings-drawer.spec.ts:87`.
- **P2.** Six unit failures at `a08389ec3`:
  - The deploy_autoscaling ×2 also fail on `main` `f6b1506c5`, so they are not caused by the epic.
  - The style_exclusivity ×4 pass on `main`, so they are caused by the epic: `create_session` requires an active Graph Release.

## Rulings made in the plan (for plan review)

- **In scope:**
  - the `frontend/tests` typecheck (Task 4);
  - log needles matching `pathname` (Task 2);
  - the dev-DB default in conftest (Task 1);
  - the style_exclusivity ×4 (Task 1);
  - declaring `openai` (Task 5).
- **Out of scope** (for the user to file as GitHub issues):
  - deploy_autoscaling ×2, which fails on `main`;
  - #266 m7, `tools/model_endpoint_tool.py:75`, which is the legacy tool path.
- **Conditional release gate:** #266 m9, pay-per-token `config_update` (Task 13). It needs the user's authorisation to read the dev workspace.

## Open questions

Q1–Q4 are listed at the end of the plan.

## Controller rulings — 2026-09-26
Controller check of the planner's "file changed on disk before commit" note: working tree clean; committed plan is 1005 lines and is the file on disk; no other agent works in this worktree. Nothing to reconcile.
Ruling: OQ1 — the conftest REFUSES to run a unit suite whose `DATABASE_URL` names `ai_slide_generator` (fail fast), and defaults to a throwaway SQLite URL when unset. Cost if wrong: a developer who deliberately points unit tests at the dev DB must override explicitly.
Ruling: OQ2 — deleting the now-unread authored prompt text in `src/core/skills` is OUT of #271's scope (a follow-up); protected constants stay. Cost if wrong: dead text remains for a while.
Ruling: OQ3 — a documented developer command to re-record the Playwright contract is acceptable (no new make target). Cost if wrong: none.
Ruling: OQ4 — the local merge of #271 may proceed with #266 m9 unverified; the epic is NOT reported shippable until the user authorises and the dev-workspace check passes. Surfaced to the user. Cost if wrong: none locally.
Ruling: the planner's follow-up split is accepted — style-exclusivity ×4 in scope (Task 1); deploy-autoscaling ×2 out (pre-epic, needs an issue); #266 m7 out (needs an issue); `openai` declared (Task 5); typecheck gap and log needles in scope.
Next: independent plan review before execution. Phase A (Tasks 0-A, 1, 5) is runnable at `a08389ec3`.

## Plan review 1 — 2026-09-26

**Verdict:** APPROVE WITH CORRECTIONS. **Counts:** 2 Critical, 9 Important, 12 Minor. Total: 23 corrections.

**Corrections file:** `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/PLAN-CORRECTIONS.md`

**Correction numbers:**
- C1 (Correction 1): Tasks 10/11 replay design
- C2 (Correction 2): Task 6 S12 contributor/duplicate prerequisites
- I1 (Correction 3): Task 4 tsconfig verbatimModuleSyntax and tsc invocation
- I2 (Correction 4): Task 1 xdist worker isolation
- I3 (Correction 5): Task 5 openai specifier and requirements.txt
- I4 (Correction 6): AC1 tripwire (_SKILLS) and guard 2/4 widening
- I5 (Correction 7): **REAL PRODUCTION DEFECT** — `resolve_engine_mode_or` fallback at `chat.py:490-491` and `:697-698` silently routes a pinned graph conversation to the legacy monolith on any DB error; violates spec §15; must be fixed in #271
- I6 (Correction 8): Task 7 AC5 no-tools uses recording DatabricksModelAdapter
- I7 (Correction 9): Task 11 mixed-release warning requires real deck mutations in Task 6
- I8 (Correction 10): Task 3 reviewer sabotage changes one byte, not swaps the role
- I9 (Correction 11): Playwright port-3000 lane; node_modules symlink; tsc --noEmit
- M1 (Correction 12): Task 2 regex widened to `vars\(record`
- M2 (Correction 13): Task 12 Step 2 RED count is guards 1–4, not 1 and 4
- M3 (Correction 14): R7 extended; RecordingAgentInvocationIdentitySink kept as re-export
- M4 (Correction 15): Three stale citations corrected
- M5 (Correction 16): Sweep helper extracted to shared fixture; missing Files block entry
- M6 (Correction 17): Style-fixture assertions confirmed by value, not text
- M7 (Correction 18): Task 8 names existing cases; three setup details for new cases
- M8 (Correction 19): S15 evidence asserted `== []`
- M9 (Correction 20): OQ2 follow-up must keep two skills imports
- M10 (Correction 21): model_validate_json for strict models in Task 10 join
- M11 (Correction 22): Controller triage before routing any failure to predecessor
- M12 (Correction 23): Scoped re-review of Task 0-B corrections before Task 2 dispatches

**Blocking Phase A (before Task 1):**
- Correction 4 (I2): xdist worker isolation

**Blocking Phase A (before Task 5):**
- Correction 5 (I3): openai no-cap specifier

**Blocking Phase A (worktree setup):**
- Correction 11 (I9): frontend/node_modules symlink

**Blocking Phase B (before Task 2):**
- Correction 23 (M12): scoped re-review after Task 0-B

**Blocking Phase B (before Task 3):**
- Correction 10 (I8): reviewer sabotage one-byte change

**Blocking Phase B (before Task 4):**
- Correction 3 (I1): drop verbatimModuleSyntax; re-measure; tsc --noEmit

**Blocking Phase B (before Task 6):**
- Correction 1 (C1): replay design
- Correction 2 (C2): S12 prerequisites
- Correction 6 (I4): tripwire _SKILLS and guard 2/4

**Blocking Phase B (before Task 7):**
- Correction 8 (I6): DatabricksModelAdapter for AC5
- Correction 9 (I7): deck mutations and collab-history exchange

**Blocking Phase B (before Task 8):**
- Correction 7 (I5): production fallback fix (chat.py)

**Blocking Phase B (before Task 10):**
- Correction 11 (I9): lsof gate; tsc --noEmit

**Blocking Phase B (before Task 12):**
- Correction 6 (I4): (also) Task 12 sabotage re-aimed

**I5 noted as real production defect:** `resolve_engine_mode_or` at `src/api/routes/chat.py:490-491` and `:697-698` silently falls through to the legacy monolith on any DB error when the session has a pinned graph release. Found at plan review. Added to the removal inventory and to Task 8 scope in PLAN-CORRECTIONS.md.
