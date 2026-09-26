# Response to plan review `plan-review-c26389743.md`

**Reviewed plan base:** `9929fd4d9754c9bbfc2f16e3ad794f29002ca838`
**Outcome:** all four Important findings addressed in the amended Issue #266 plan.

## Important 1 — preflight before Task 1

Added mandatory non-implementation Task 0 before Task 1. It fails on `.venv`, records `/Users/robert.whiffin/.pyenv/shims/python`, re-probes installed SDK signatures and the `foundation_model` field, inventories Task 1's current owners/fakes/tests/CI seam, runs and records a cause-based Task 1 baseline, and creates the exact overriding `PLAN-CORRECTIONS.md` attached to Task 1 briefs. The after-Task-1/before-Task-2 gate remains and now extends the same ledger with a stricter integrated re-probe.

## Important 2 — validation ordering around stale comparison

Split validation into pure `validate_endpoint_name_policy` and remote-only `validate_custom_endpoint_remote`. The one #263 save pipeline now runs deterministic local endpoint-name policy before stale comparison, returns a coherent stale result before remote I/O, and performs exact-name/readiness/update-state SDK validation only for a current locked snapshot. Required unit and PostgreSQL evidence now includes:

- invalid URL plus stale lock → ordered one-item `422`, no write, zero SDK/remote calls;
- locally valid endpoint plus stale lock → coherent seven-role `409`, no write, zero remote calls; and
- the existing two-PID/observed-waiter stale-loser concurrency proof with no loser remote call.

## Important 3 — interpreter and PostgreSQL matrix

Replaced every backend command with `/Users/robert.whiffin/.pyenv/shims/python`. PostgreSQL commands use an explicit `TELLR_TEST_POSTGRES_URL` and run separately for bootstrap, constraints, persisted runtime failures, conversation pin migration, conversation pin creation, workbench validation/concurrency, and schema overlay. Each result must be recorded separately with zero skips; unavailable PostgreSQL, a missing concrete module, or a server-unavailable skip fails the gate. The corrections ledger may add final/renamed predecessor modules but cannot remove or combine the mandatory set.

## Important 4 — manual custom endpoint UI/browser acceptance

Added component and Playwright success plus typed server-failure/correction/retry flows for a manually entered non-URL endpoint absent from discovery. They assert #263's request shape (`lock_version` plus exactly five editable candidate leaves), exact-name retention, absence of discovery metadata/URL/host/token/provider fields, sanitized typed field errors, preservation of the complete unsaved form, and successful explicit retry. The local URL case remains a separate zero-PUT proof.

## Preserved verified architecture

The amended plan retains the server-owned probe request containing only `lock_version`, no endpoint or arbitrary payload override, no probe writes, shared runtime/probe structured-output binding, exact endpoint identity without aliases or auto-advance, #263's one writer/route, local #265→#264→#266 integration, deterministic fakes, and first-party evidence; #267 remains downstream.
