# Issue #265 plan correction report

**Plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`
**Review addressed:** `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-review.md`

## Resolved findings

| Finding | Correction |
|---|---|
| C1 remote integration base and impossible `HEAD` equality | Task 0 now records one concrete reviewed commit from local `feat/langgraph-core`, proves reviewed #260/#261/#263 ancestry, excludes research commit `447791d7af34aafc18612cecead6a90805b367ec`, rebases locally, and checks the recorded base is an ancestor of `HEAD`. No remote integration ref, fetch, push, or PR is permitted. Final local order is #265, #264, #266 after #260+#261+#263. |
| C2 raw assembler failure escaped #261 | Raw `PromptAssemblyRejected` is limited to assembler tests. Runtime tests and implementation preserve `invalid_persisted_definition`, `protected_bundle_unavailable`, pre-sink validation, provider conversion inside the callback, zero model calls, and sink observations. |
| C3 hostile delimiter test was not falsifiable | `AssembledPrompt` now exposes code-owned stage provenance. Tests locate notice/open/payload/close/terminal by unique `stage_id`, assert exact stage reconstruction and payload-stage uniqueness, and prove the closing-after-terminal sabotage fails even when attacker text contains both delimiters and stage names. |
| I1 fictional #263 frontend owners | The plan records the reviewed #263 reality: `AgentDefinitionWorkbench.tsx` owns tabs/read-only rendering, `draftEditorState.ts` owns aggregate pending/recovery state, and `agentDefinitions.ts` owns transport/parsing. Task 5 modifies those files, explicitly adds missing orchestration to the existing component, adds `draftEditorState.test.ts`, and does not claim nonexistent inherited editor/hook modules. |
| I2 incomplete corrections pre-pass/baselines | Task 0 requires the complete SDD per-task and pairwise file/interface table, exact caller/constructor inventory, authoritative overrides/rulings, exact pyenv path, and cause-based failure/skip baselines. The corrections file goes to every implementer and reviewer. Cause sets are re-derived after manifest/runtime/schema changes. |
| I3 Task 1 could not turn GREEN | Task 1 now owns only manifest grammar/hash/order tests and never imports the assembler. `test_prompt_assembler.py` is created in Task 2. |
| I4 no canonical flat-block ordering | Anchor ranks are explicit and non-decreasing; sibling order is preserved and significant; cross-anchor input is rejected, never regrouped. Manifest, assembler, writer/422, client parser/state, component, and browser tests cover it. |
| I5 unstable errors and missing auth-first tests | The plan defines authoritative field/code/message rows and deterministic ordering across local validation and ordered validators. It adds exact domain/envelope assertions, invalid-plus-stale `422`, valid-stale seven-role `409`, no-write checks, and non-admin malformed/extra-body authorization-first tests. |
| I6 protected content not displayed/non-editability indirect | Admin responses now carry server-derived exact `display_text` for protected literal stages and a canonical serializer description, excluded from every request DTO. UI tests render role/context stages and directly assert absence of text, delete, reorder, condition, and anchor controls. V1 custom editing remains unavailable until successful server-owned upgrade. |
| I7 final matrix too narrow | The final matrix now includes #261 persisted runtime/loader, agent-resolution prompt, graph-node/caller/failure tests, content mapping/bootstrap tests, and full #263 backend/PostgreSQL/frontend coverage. Results are compared by causes, not counts. |
| M1 role-specific notice ambiguous | V2 now specifies an exact role-keyed notice template rendered with each code-owned role display name. All seven values and display names are digest material and tested; historical v1 bytes remain unchanged. |

## Additional execution safeguards added

- `executing-plans-tellr` plus `superpowers:subagent-driven-development` are mandatory.
- Every task uses an exact `TASK_BASE..TASK_HEAD` review package.
- Controller and reviewer run distinct, named sabotage targets, verify marker placement, restore, and capture RED/GREEN evidence.
- The final whole-branch package is exactly `IMPLEMENTATION_BASE..HEAD` and requires a writer comparison, rollback/no-write ruling, and integration verdict.
- No `uv`, `pip`, install, virtual environment, push, or PR operation is allowed.

## Residual execution concern

The current local `feat/langgraph-core` head visible during this correction is
`774703e4487877bf65e0eeff173892d3e00ceac5`, which does not yet contain the reviewed #261
and #263 heads. This is intentionally a hard Task 0 gate: implementation cannot start until
those reviewed heads are integrated into, and reviewed as, one newer concrete local
`feat/langgraph-core` commit.
