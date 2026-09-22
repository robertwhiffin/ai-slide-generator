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
- Review packages use exact recorded task bases and the whole-branch implementation base, never `HEAD~1`.
- Controller and reviewer sabotage distinct executed seams with marker, RED, restore, and GREEN evidence.
- PostgreSQL tests require real execution with zero skips and identity/state assertions.
- The final review uses the most-capable reviewer and requires writer, sink-outcome, no-write/rollback, and merge verdicts.

## Residual concerns

- No concrete #260+#261+#263+#265 local integration commit exists yet in the observed repository state; Task 0 correctly blocks Task 2 until one reviewed local commit exists and all predecessor ancestry is proved.
- #261 and #263 moved during review. Their final reviewed heads and any new caller/failure/browser files must be captured in `PLAN-CORRECTIONS.md` immediately before Task 2.
- #265 is currently a corrected plan rather than landed integrated code. Task 0 must reconcile its eventual schema/route/client owners with the explicitly defined schema-upgrade `client_candidate: null` contract before shared edits; changing that contract requires a recorded spec ruling, not an ad hoc compatibility layer.

This was a documentation-only correction. No implementation tests, dependency commands, PR, push, or merge were run.
