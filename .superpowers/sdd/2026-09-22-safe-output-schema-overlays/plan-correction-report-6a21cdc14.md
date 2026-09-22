# Plan correction report — review `6a21cdc14`

## Outcome

Corrected `docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md` without changing implementation code or narrowing issue #264. The execution workspace is now consistently `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/`.

## Re-probed evidence

- Binding design: `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`, especially §§7–8, 11, 14–18.
- GitHub #258 and #264 were re-read on 2026-09-22.
- Reviewed #260 local merge observed at `774703e4487877bf65e0eeff173892d3e00ceac5`, containing reviewed head `29e03411487476383b34101b7b34513dbb917f26`.
- The supplied final #263 interface checkpoint was inspected at `771910ca1045d165a54e794f48fd4f0c206e4fa7`: `invalid_draft`; error items `{field, code, message}`; request content under `candidate`; and exact-seven `stale_draft` server snapshots. During correction its branch advanced to `1d706e21b92aad68314da2e79bb4d1d5626663b7`; that delta changes only `frontend/tests/e2e/agent-definition-workbench.spec.ts`, not the inspected interfaces.
- Corrected #265 plan was inspected at `ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`; it preserves `candidate.*`, `invalid_draft`, one aggregate writer/controller, and local order #265 → #264 → #266.
- #261 moved during this correction. It was first observed at `439971b3448fd6d0d64a9993305da47193754a56`, then advanced to `785d9aaca35a3a9103cd4283afdc6bda3b679882`. The latter retains the identity-sink callback boundary in `agent_runtime_identity.py` and runtime callback-before-success order. The plan treats both SHAs as observations and requires a fresh final-head probe.

## Finding resolution

| Review finding | Exact correction |
|---|---|
| Critical C1 — incompatible save/error wire contract | Replaced every planned `invalid_definition`/`path`/unprefixed overlay location with landed `invalid_draft`, `{field, code, message}`, and `candidate.schema_overlay...`. Made deterministic error ordering authoritative. Defined ordinary and schema-upgrade 422 bodies and the upgrade 409 contract, including `client_candidate: null`, one coherent locked snapshot, and exactly the seven role keys. Added direct backend/client coverage for those literals. |
| Important I1 — corrections pre-pass occurred after Task 1 | Added Task 0 before all dispatch. It creates and attaches the correctly named `PLAN-CORRECTIONS.md`, inventories every task and shared producer/consumer pair, and records cause-based #260 baselines before Task 1. It refreshes and expands the same file against the concrete #260+#261+#263+#265 local integration commit before Task 2. Task 1 remains new-file-only and collision-free. |
| Important I2 — diagnostics-only scope and unsafe trace ordering | Extended the existing #261 recording/logging sink contract instead of deferring traces. Adapter invocation, provider conversion, raw-key checks, composed validation, canonical projection, and `additional_fields` freezing must finish inside the callback before success. Both sinks now require success/error coverage and exact distinct `{}`, null, and empty-list trace values; invalid canonical/optional output must be observed as error. Exact-ID resolution and no fallback remain mandatory. |
| Important I3 — wrong interpreter/browser roots | Every backend pytest command uses `/Users/robert.whiffin/.pyenv/shims/python`; backend gates include `test ! -e .venv`. Playwright runs only from `frontend` with the checked-in config, Chromium project, and one worker. The plan forbids installs, `uv`, `pip`, and root-level `npx`. |
| Minor M1 — unreachable optional-catalog ruling | Removed the untracked ruling citation. The seven exact `diagnostic_notes` descriptions/examples and its type/cardinality/absence semantics are embedded as the authoritative decision. |
| Review prompt/path mismatch | All future ledger, corrections, report, brief, and review-package paths use `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/`; the obsolete workspace name is explicitly forbidden. |

## Preserved execution guarantees

- Local integration order remains #265 → #264 → #266, with no remote integration dependency.
- Review packages use exact recorded task bases and the whole-branch integration base, never `HEAD~1`.
- Controller and reviewer sabotage distinct executed seams with marker, RED, restore, and GREEN evidence.
- PostgreSQL tests require real execution with zero skips and identity/state assertions.
- The final review uses the most-capable reviewer and requires writer, sink-outcome, no-write/rollback, and merge verdicts.

## Residual concerns

- No concrete #260+#261+#263+#265 local integration commit exists yet in the observed repository state; Task 0 correctly blocks Task 2 until one reviewed local commit exists and all predecessor ancestry is proved.
- #261 and #263 moved during review. Their final reviewed heads and any new caller/failure/browser files must be captured in `PLAN-CORRECTIONS.md` immediately before Task 2.
- #265 is currently a corrected plan rather than landed integrated code. Task 0 must reconcile its eventual schema/route/client owners with the explicitly defined schema-upgrade `client_candidate: null` contract before shared edits; changing that contract requires a recorded spec ruling, not an ad hoc compatibility layer.

This was a documentation-only correction. No implementation tests, dependency commands, PR, push, or merge were run.

## Round 2 resolution — review `20b019b07`

Re-corrected the plan after re-reading the full review and re-probing local refs on 2026-09-22. Current local observations remain `feat/langgraph-core` at `774703e4487877bf65e0eeff173892d3e00ceac5`, `feat/conversation-pins-runtime-261` at `785d9aaca35a3a9103cd4283afdc6bda3b679882`, `feat/shared-graph-draft-editor-263` at `1d706e21b92aad68314da2e79bb4d1d5626663b7`, and corrected #265 plan at `ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`. The plan records these only as observations; execution still re-resolves final reviewed heads.

| Review finding | Round 2 correction |
|---|---|
| Important I1 — ambiguous post-rebase base | Replaced the overloaded old base artifact with immutable `TASK1_BASE` and `INTEGRATION_BASE`, plus `predecessor-heads.md`. `TASK1_BASE` is now only Task 1 starting evidence. `INTEGRATION_BASE..HEAD` is the required final review/package range, and Task 0/Task 7 must prove that range contains exactly rebased Task 1 plus Tasks 2-6, with no integrated predecessor commits packaged as #264 work. |
| Important I2 — incomplete/current verification matrix | Added current #261 `tests/integration/test_persisted_graph_runtime_failures_postgres.py` to Task 3 and Task 7 with `TELLR_TEST_POSTGRES_URL` and zero-skip requirements. Expanded Task 7 to exact backend unit paths covering #260/#261/#263/#265/#264, exact named PostgreSQL invocations for #260 bootstrap/constraints, #261 persisted-runtime failures, #263/#265 workbench, and #264 overlay tests, plus exact frontend unit/typecheck/ESLint/Playwright commands. Task 0 may reconcile renamed files but may not drop the current #261 PostgreSQL failure coverage. |
| Important I3 — missing final-head/pre-merge gate | Added a final pre-local-merge gate that re-resolves final reviewed #261/#263/#265 heads and current local root, proves those heads and recorded `INTEGRATION_BASE` are ancestors of both local root and #264 `HEAD`, recomputes the reviewed `INTEGRATION_BASE..HEAD` diff, refuses merge if reconciliation changes that reviewed #264 diff, and requires integration/rebase plus refreshed corrections, baselines, affected task review, and final review if any predecessor advanced. |

Preserved constraints: local-only order #265 -> #264 -> #266; Task 0/Task 1 isolation; exact package ranges; no remote refs/fetch/PR/push/merge; absolute shared pyenv pytest; no installs, `uv`, `pip`, or `.venv`.
