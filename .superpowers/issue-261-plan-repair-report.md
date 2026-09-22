# Issue #261 plan repair report

**Plan:** docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md

**Authorities re-probed:** GitHub #258, #261, #262; the 2026-09-21 design; #260 worktree preflight; current branch code; and .superpowers/issue-261-plan-review.md.

## Rulings

1. #261 owns only explicit POST /api/sessions creation. Chat auto-create, contributors, duplicate sessions, and mixed-release collaboration remain #262.
2. graph_capable is an explicit, default-false root intent. This avoids assigning graph provenance to a plain monolith root. If product authority later defines all roots as capable, the contained change is request/default/UI parity, rather than corrective migration of wrongly pinned sessions.
3. Dangling-release end-to-end PostgreSQL setup is removed: RESTRICT plus immutable release guards make it invalid. Direct loader proves absent ID; shipped graph seam proves null pin.

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

## Plan-quality verification

- Read all required skills: writing-plans, codebase-design, executing-plans-tellr.
- Ran placeholder/signature/scope/CI keyword scans against the repaired plan; removed all ellipsis/TODO-style placeholders.
- Ran git diff --check successfully.
- No production code or tests were run or changed; this is planning-only work.
