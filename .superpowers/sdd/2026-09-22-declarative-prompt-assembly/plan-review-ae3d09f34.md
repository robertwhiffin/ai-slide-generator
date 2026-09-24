# Plan review: declarative protected prompt assembly (#265)

**Reviewed commit:** `ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Verdict:** **CHANGES_REQUIRED**

**Findings:** 2 critical, 6 important, 1 minor

## Findings

### Critical 1 — The generic validator order is incompatible with the reviewed #266 stale-save contract

The plan makes one immutable tuple of content validators and requires **every** supplied validator to run before stale comparison (lines 126, 136, 439, and 461). The reviewed #266 plan at `c26389743` requires the opposite for its remote endpoint validator: stale saves return the coherent 409 without calling the validator (its lines 172–174, 187, and 191). This is not a harmless downstream choice. #265 owns the shared extension seam that #266 must consume, while line 24 also says #265 must not reserve a later feature's behavior.

As written, either #266 violates its no-remote-call-on-stale requirement, or it must replace/bypass the seam #265 introduces. Define validator phases or equivalent semantics now: deterministic local candidate validators such as assembly validation may run before stale precedence, while remote/expensive validators run only after stale comparison. Specify ordering, aggregation, and no-write behavior for each phase, and add sentinel tests proving both paths without naming #266 in production code.

### Critical 2 — The terminal binding is incorrectly included in the textual model prompt

Lines 107–110 define `prompt` as the join of every `ResolvedPromptStage.rendered_text`; line 124 includes terminal binding in that list; and the required hostile-payload test at lines 313–326 asserts the same join. That sends a textual `langchain.with_structured_output` marker to the model. The binding design says this is “a terminal structured-output binding stage after prompt assembly” (§9.1, line 407), and the current #261 adapter performs the real binding with `model.with_structured_output(schema)` before invocation. The plan itself also says only the adapter calls `with_structured_output` (line 22).

Keep the terminal stage in protected display/provenance and in the protected digest, but make it non-prompt metadata (for example, `contributes_to_prompt=False`). Define `prompt` as the join of prompt-contributing stages only, then test that the terminal stage is last in execution/provenance while its label/literal is absent from the textual prompt and the adapter applies the binding exactly once.

### Important 1 — The protected-assembly upgrade has no implementable 409 wire type

The stable method returns `DraftSaveConflict[None]` (lines 129–133), but the current #263 API schema at `1d706e21b` requires `DraftSaveConflictResponse.client_candidate: EditableModelDraftRequest` and the route always constructs that request. #265 says only that upgrade staleness is “#263's 409” and never defines the JSON or TypeScript parser/reducer behavior. The reviewed #264 plan at `7e9ef7553` explicitly resolves the same problem with `client_candidate: null` and a client parser for the null upgrade candidate (lines 91–99).

Define the exact #265 upgrade response as the existing stale family with `client_candidate: null` (or define another fully specified compatible type), update the backend union/schema and frontend parser, and require route/parser/reducer tests for an exact-seven coherent snapshot and null candidate.

### Important 2 — Task 0's executable predecessor assertions name superseded reviewed heads

Task 0 still asserts #261 `9e9be573e…` and #263 `49989d4a…` (lines 160 and 181–182). The current reviewed local heads are #261 `785d9aaca35a3a9103cd4283afdc6bda3b679882` and #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7`. The prose says to replace stale checkpoints, but the committed commands are the execution contract and do not prove those final reviewed heads.

Update the commands and ownership prose to the current full SHAs. Also record the present external gate accurately: local `feat/langgraph-core` is `76a88f238e84f17cc60eba8a62e00dc80fc26115`; it contains current #263 but neither the current nor stale #261 checkpoint. Task 0 must therefore stop until a reviewed **local** integration commit contains final #261 and #263. That current integration absence is an execution blocker, not itself a #265 design defect.

### Important 3 — The final regression matrix omits #261's current PostgreSQL typed-failure/no-fallback suite

Task 6 claims the matrix includes #261 graph-node/caller/failure suites (lines 623–627), but the commands at lines 611–619 never run `tests/integration/test_persisted_graph_runtime_failures_postgres.py`. That file exists at the current reviewed #261 head and exercises pinned persisted-runtime failure and no-fallback behavior that was added after the stale Task 0 checkpoint.

Add an explicit PostgreSQL invocation for this file, require zero skips, and include its named failure/skip causes in preflight and final comparisons. The whole-branch review handoff should require its result alongside the #261 unit suites.

### Important 4 — The promised authoritative validation contract is internally incomplete and uses the wrong field syntax

The table at lines 143–151 uses bracket paths such as `candidate.assembly_rules.custom_blocks[{i}].block_id`. The current #263 request parser constructs dotted Pydantic paths (`candidate.assembly_rules.custom_blocks.0.block_id`), and reviewed downstream #264 also standardizes dotted index paths. In addition, Task 4 calls the table “authoritative” while requiring exact envelopes for fake digest, invalid protected placement, missing/duplicate singleton, payload block, terminal mismatch, unknown kind/condition, and extras (line 439); most of those rows have no stable field/code/message in the table.

Choose one exact dotted-path convention for parser and semantic errors, and complete the table for every exact-envelope condition Task 4 names. Separate parser-owned Pydantic errors from assembler-owned semantic errors and state their deterministic combined order.

### Important 5 — Unavailable bundle identity cannot be mapped separately with the specified exception surface

The only stable assembler exception is `PromptAssemblyRejected` (lines 90–91). Task 2 says an unknown/fake protected bundle is a raw assembly rejection (lines 329–340), while Task 3 requires runtime to catch unavailable bundle identity “separately” and map it to `protected_bundle_unavailable`, with other persisted assembly failures mapped to `invalid_persisted_definition` (lines 384 and 395). No exception subtype, discriminator, or exact issue code makes that split reliable.

Define a stable unavailable-bundle exception/subclass or an exact machine-readable issue discriminator, and test fake version, fake digest, malformed persisted rules, zero-model invocation, and pre-sink observation separately. Do not route on message text.

### Important 6 — V2 runtime integration is not explicitly proved for all seven roles

Task 2 parameterizes raw assembler coverage across all seven roles (lines 308–326), and Task 3 explicitly covers persisted **v1** prompts across seven roles. Its v2 runtime requirement only says “Build v2 definitions” and assert hostile boundary/diagnostic equality (line 384), without requiring all seven roles and relevant contexts through the persisted production runtime. Raw assembler coverage cannot detect role-specific mapping, persisted-loader, sink, or adapter integration mistakes.

Parameterize the Task 3 v2 persisted-runtime test over all seven `GRAPH_V1_AGENT_KEYS` (and the relevant design-system/deck-brief contexts), asserting exact resolved identity, assembled prompt/provenance, adapter call, and sink behavior for each role.

### Minor 1 — The tracked correction report contradicts the corrected local-only workflow

`.superpowers/issue-265-plan-fix-report.md` line 23 still says Task 0 fetches and rebases onto `origin/integration/261-263`. The plan now explicitly forbids fetching or naming that branch (lines 15, 37, and 666–669). Update or remove the stale sentence so the handoff does not direct an executor to violate the plan.

## Evidence and positive assessment

- The corrected local integration order (#265 → #264 → #266), cause-based baselines, Task 0 correction ledger, serialized shared-file ownership, and controller/reviewer sabotage protocol are materially stronger than the earlier plan.
- The plan now preserves #261's exact four-argument runtime, persisted-release resolution, sink observation order, provider-error conversion, and v1 historical compatibility.
- Current #263 frontend owners, auth-before-body parsing, single locked writer, exact-seven conflict recovery, protected UI non-editability, and same-content lock/audit behavior are identified correctly.
- Hostile delimiter testing uses stage provenance rather than attacker-controlled substring positions, and the anchor rank/order contract is now explicit.

No implementation should start from the currently observed local base. After the nine plan corrections above, Task 0 must still re-probe the then-current local branches and stop unless final reviewed #260, #261, and #263 are all ancestors of one reviewed local `feat/langgraph-core` commit.
