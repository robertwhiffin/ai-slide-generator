# Plan rereview: declarative protected prompt assembly (#265)

**Reviewed commit:** `8f6365e36f393ed3e4edbaded48fe8b50c20afb3`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Binding spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`

**Prior review:** `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-review-ae3d09f34.md`

**Verdict:** **CHANGES_REQUIRED**

**Findings:** 1 critical, 1 important

## Findings

### Critical 1 — The upgrade preserves the two legacy composite prompts, so v2 does not actually separate or protect their embedded stages

The binding spec says protection first requires separating the current Data Analyst security text and generated Build Reviewer criteria from authored prompt text (spec lines 397–418). The amended plan correctly creates authored-only constants and code-owned v2 notice/criteria stages (plan lines 126–132 and 425–427), but its only persisted v1→v2 operation explicitly changes **only** `assembly_rules` and protected identity while keeping `prompt_text` byte-identical (lines 156 and 532).

That is incompatible with the current persisted v1 content:

- At reviewed local #263/root `76a88f238e84f17cc60eba8a62e00dc80fc26115`, `src/core/skills/data_analyst.py:14-37` defines `INSTRUCTIONS` as `UNTRUSTED_DATA_NOTICE + "\n\n" + authored text`. The generated v1 manifest stores that composite string in `prompt_text`.
- At the same commit, `src/core/skills/build_reviewer.py:13-46` generates the entire prompt—including the live `CRITERIA` block—and assigns it to `INSTRUCTIONS`; the generated v1 manifest stores that composite string in `prompt_text`.
- V2 assembly then appends a new role-specific protected notice for every role and a generated protected criteria stage for Build Reviewer (plan line 132).

Consequences after the planned upgrade:

1. Data Analyst retains the old security notice inside the editable authored field and receives the new protected notice later, so protected security content remains user-editable and is duplicated.
2. Build Reviewer retains the generated criteria inside the editable authored field and receives another generated protected criteria stage, so criteria are duplicated and one copy remains editable.
3. The Task 4 assertion that `prompt_text` remains identical actively locks in this defect, while Task 2/3 synthetic-v2 tests can pass by constructing authored-only fixtures and never exercising the upgraded persisted content.

The plan must define an exact, loss-aware server-side upgrade for these two roles. It needs to say how a pristine legacy composite prompt becomes the authored-only v2 prompt and what happens when an admin edited that legacy composite before upgrade (for example, a stable rejection/manual-resolution path rather than silently dropping or reclassifying text). Add an execution test that starts with the real generated v1 definition for each affected role, runs the one locked upgrade, reloads the stored `DefinitionContent`, assembles it, and proves the protected notice/criteria occur exactly once and are absent from the editable authored prompt. Historical published v1 rows and their bytes/identities must remain unchanged.

### Important 1 — Task 1 rejects semantic v2 rules before the Task 4 local validator that is supposed to own their exact ordered errors

The plan assigns duplicate IDs, blank text, illegal role/anchor conditions, and non-monotonic anchors to assembler-owned semantic validation with exact dotted `DraftValidationIssue` values (lines 169–217). It also says #265 registers `PromptAssembler.validate(definition=content)` in the local-candidate phase over a complete rehydrated `DefinitionContent`, after #263 command/round-trip/immutable checks (lines 134–146 and 550–552).

Task 1, however, requires `DefinitionContent.validate_role_assembly` itself to reject duplicate IDs, blank text, illegal role/condition combinations, and canonical-order failures (lines 320–344). Current #263 code rehydrates/round-trips with `DefinitionContent.model_validate(...)` before its write (`76a88f238e84f17cc60eba8a62e00dc80fc26115:src/services/graph_configuration_draft.py:142-151` and `181-199`). Therefore an invalid request cannot become the complete validated `DefinitionContent` passed to `PromptAssembler.validate`: Pydantic fails first. The writer either returns the current generic `content/invalid_content` error, invents a second Pydantic-error translation path, or bypasses the required round-trip. Each choice contradicts the stated ownership, exact issue tuple, or validation order.

Choose one executable ownership model. The simplest is to keep `DefinitionContent`/`AssemblyRulesV2` strict about wire shape and discriminators but move candidate semantic rules (duplicate/blank/role-condition/order) exclusively into the assembler validator, which runs before stale comparison and before persistence; runtime assembly still rejects semantically invalid persisted content before model invocation. Alternatively define a separate candidate-validation value and a shared issue-producing function, then spell out exactly when it runs and how it becomes a validated `DefinitionContent`. Whichever design is chosen, add one multi-error route/facade test that proves the complete dotted tuple reaches the local phase in block/table order, precedes stale comparison, invokes no post-stale validator, and performs no write.

## Prior finding verification

| Prior finding | Result | Evidence in amended plan / current state |
|---|---|---|
| C1 validator timing | Resolved | Two immutable phases are explicit at lines 134–146 and 526–552. Local validators precede stale comparison; post-stale validators run only for a current snapshot. Current reviewed #266 plan `c26389743`/head `9929fd4d9` still requires its remote endpoint validation after stale comparison, so the seam now supports it. |
| C2 terminal binding in prompt text | Resolved | Lines 110–118 make the terminal stage final provenance with `contributes_to_prompt=False`; prompt joins contributing stages only. Task 2 adds safe-payload absence and hostile provenance tests, and Task 3 retains exactly one adapter binding. |
| I1 nullable upgrade conflict | Resolved | Lines 148–166 define `DraftSaveConflict[None]`, exact `client_candidate:null`, coherent exact-seven snapshot, operation-aware client parsing, and the shared reducer path. |
| I2 stale predecessor assertions | Resolved | Task 0 names reviewed #261 `785d9aaca35a3a9103cd4283afdc6bda3b679882`, #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7`, and requires execution-time replacement from final review evidence. Read-only ancestry re-probe confirms local root `76a88f238e84f17cc60eba8a62e00dc80fc26115` contains #260/#263 but not that #261 head, so the gate correctly remains closed. |
| I3 missing #261 PostgreSQL suite | Resolved | Task 0 and Task 6 run `tests/integration/test_persisted_graph_runtime_failures_postgres.py` separately with the explicit URL and zero skips; final review requires the named result. The file exists on the active #261 line. |
| I4 incomplete/bracketed validation contract | Partly resolved, with new ownership contradiction above | Lines 169–217 use dotted indices, separate parser and semantic tables, define every prior missing field/code/message, and state combined ordering. The remaining defect is not missing literals; it is that Task 1 prevents the semantic phase from receiving those candidates. |
| I5 unavailable-bundle discriminator | Resolved | Lines 90–94 define stable subtype `ProtectedAssemblyBundleUnavailable`; Tasks 2–3 require subtype-first conversion, fake version/digest coverage, zero model calls, and pre-sink failure without message parsing. |
| I6 all-seven persisted-v2 runtime breadth | Resolved | Task 3 lines 469–484 parameterize all seven roles, relevant design-system states, Build Reviewer truthy/falsy deck briefs, exact release/revision/hash/protected identities, prompt/provenance, adapter/binding, and sink behavior. |
| M1 stale remote workflow report | Resolved | `.superpowers/issue-265-plan-fix-report.md` now describes only reviewed local integration and explicitly forbids `origin/integration/261-263`. |

## Verified positives

- The plan now preserves #261's exact four-argument production call and explicit `graph_release_id`, the persisted loader, pre-sink configuration failures, identity-sink callback ordering, and provider conversion inside that callback. Builder/Fixer retry IDs and no-fallback behavior have focused unit and real-PostgreSQL gates.
- V1 replay is treated as historical behavior: generated v1 data is not regenerated, v1 rules still compare to `assembly_rules_for(agent_key)`, and Task 2/3 require byte- and identity-exact persisted execution across all seven roles.
- The v2 payload boundary is materially strong: only `PromptAssembler` owns the exact canonical serializer, hostile strings are verified by owned stage identity rather than substring position, and terminal binding remains digest/display provenance without entering model text.
- #263 remains the sole locked writer/mapper/hash/audit path and the sole route/frontend state machine. Same-content saves, invalid-plus-stale precedence, coherent exact-seven conflicts, `client_candidate:null` upgrade conflicts, auth-before-body behavior, and no-write paths all have explicit tests.
- Parser and semantic tables now use exhaustive dotted paths and stable field/code/message literals; issue order is not sorted or regrouped.
- PostgreSQL coverage is separately named and requires zero skips for persisted-runtime failures, workbench writer races, and bootstrap. Cause sets—not counts—are the regression baseline.
- Local integration order is unambiguous: reviewed #265, then #264, then #266, only after final reviewed #260/#261/#263. No remote integration branch, push, PR, package install, migration, or DDL is authorized.

## Read-only state and evidence probes

- The review worktree was clean on `plan/prompt-assembly-265` at exact `8f6365e36f393ed3e4edbaded48fe8b50c20afb3` before this artifact was written.
- Local `feat/langgraph-core` remained `76a88f238e84f17cc60eba8a62e00dc80fc26115`; ancestry probes returned true for reviewed #260/#263 and false for reviewed #261 and research head `447791d7af34aafc18612cecead6a90805b367ec`.
- The #261 worktree was initially observed at the supplied `77e42b3c170373407afddc1c98d982af5c3806fa`, then advanced concurrently during review through Task 7 commits to `6d8fa37fbb63c2eff2716707a15f9d2c6677e032`. Its ledger showed Task 6 approved and Task 7 still in its implementation/fix flow; none of those moving heads was treated as final authority. This validates, rather than weakens, Task 0's execution-time final-review gate.
- Read-only GitHub probes on 2026-09-22 confirmed issues #261, #263, and #265 remain open; #265's acceptance criteria still require protected notices/criteria, protected anchors, exact role-wide payload boundaries, historical bundle identities, and adversarial all-role coverage.
- No implementation tests were run because this was a plan-only review at a pinned clean commit. No production/test/plan file, dependency, remote ref, PR, or issue was mutated.

## Verdict

**CHANGES_REQUIRED.** The prior nine findings are materially addressed, but implementation must not begin until the v1-composite→v2 authored-prompt transition and the semantic-validation ownership/order contradiction are corrected in the plan and covered by falsifiable tests.
