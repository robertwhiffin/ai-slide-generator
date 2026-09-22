# Issue #261 plan repair report — second correction

**Plan:** docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md

**Authorities re-probed:** GitHub #258, #261, #262; the 2026-09-21 design; #260 worktree preflight; final #260 merge 29e034114; current branch code; .superpowers/issue-261-plan-review.md; and .superpowers/issue-261-plan-rereview.md.

## Rulings

1. #261 owns only explicit POST /api/sessions creation. Browser new-root creation is that explicit path and sends graphCapable true before its first message; chat auto-create, contributors, duplicates, and mixed-release collaboration remain #262.
2. The API default is false for non-browser callers. A browser root is capability-pinned, not a claim that its first monolith turn used the graph; the UI label is Pinned Graph Version.
3. The active-release lock has exactly two READ COMMITTED scans. A publication-first wait that makes R1 ineligible triggers the second fresh scan and pins R2. Creation-first locks/pins R1 and makes publication wait.
4. Production MLflow tracing is forbidden by merged PRD authority. The plan uses a structured non-retaining application-log identity sink with an allowlist of identity/outcome fields and no customer content or trace table.
5. Dangling-release end-to-end PostgreSQL setup is removed: RESTRICT plus immutable release guards make it invalid. Direct loader proves absent ID; shipped graph seam proves null pin.

## Review findings corrected

| Review finding | Plan correction |
|---|---|
| #262 scope collision | Global boundary and Task 2 exclude chat route/auto-create and assert that boundary. |
| Unproduced pin loader | Task 2 produces implementation-level loader code and Task 5 consumes it. |
| Unmigrated callers/fixtures | Task 4/5 inventory includes all named runtime adapters, direct callers, rereview tests, and graph_turn_env. |
| PostgreSQL files omitted from CI | Task 9 owns all four integration files in integration-graph and CI collection guard. |
| Zero mappings read as absent | Task 3 requires release-anchored outer join and zero-mapping RED/sabotage. |
| Later node failures swallowed | Task 6 defines one typed failure family and re-raises it from every broad recovery block. |
| Missing constructors/acceptance program | Tasks 3/4 declare loader/runtime/trace interfaces and Task 9 defines the ordered deterministic role-output program. |
| Misleading eager pin | Explicit default-false intent and cost-if-wrong ruling. |
| Endpoint identity omitted | Task 4 introduces endpoint error/trace proof. |
| Collision table incomplete | The final table orders nodes, rereview tests, chat service, workflow, and graph harness edits. |

## Second-pass corrections

| Re-review finding | Plan correction |
|---|---|
| Ordinary browser graph root was unpinned | Task 8 owns API camel/snake serialization, browser true intent before first message, SessionContext version state/reset/restore, and normal New Session graph-first-message E2E. |
| Publication-first lock failed | Task 2 gives two-scan READ COMMITTED code and forced R1-to-R2/R1-first ordering assertions. |
| Runtime callers and fixture omitted | Tasks 4/5 list every rereviewed compatibility suite and make graph_turn_env seed graph_release_id in direct graph state. |
| MLflow conflicts with final merge | MLflow removed; logging identity sink has explicit content-retention/security contract and production construction. |
| Assembly/schema vague | Task 3 uses DefinitionContent/AssemblyRules; Task 4 defines exact V1 evaluator and all-role/context parity. |
| Typed failures incomplete | Task 4 conversion table plus Task 6 exact safe stream event make later node re-raise effective. |
| Acceptance state machine incomplete | Task 9 supplies A/B, two turns, every retry/rebuild tail, typed outputs, real Send wrapper, and ordered identity assertions. |
| uv violated pyenv rule | Every backend command uses python -m pytest; pre/post checks require shared Python 3.11 and absent .venv. |
| chat_service collision wrong | Task 1 owns selector delegation and Task 6 owns stream contract; collision table is ordered. |

## Plan-quality verification

- Read all required skills: writing-plans, codebase-design, executing-plans-tellr.
- Ran placeholder/signature/scope/CI keyword scans against the repaired plan; removed all ellipsis/TODO-style placeholders.
- Re-ran no-MLflow, no-uv, browser-intent, compatibility-caller, state-seed, and CI-enrollment searches after the second correction.
- Ran git diff --check successfully.
- No production code or tests were run or changed; this is planning-only work.
