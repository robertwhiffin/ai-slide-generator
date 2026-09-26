# Plan review — exact model endpoint discovery and validation (#266)

**Reviewed commit:** `c26389743f17f225c3d92dfb579f0c19ae4fd6f5`
**Plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Verdict:** **CHANGES_REQUIRED**

## Findings

### Important 1 — Task 1 is permitted before the mandatory Task 0/preflight and baseline

**Plan:** [lines 15, 27, 29–35](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:15)

The plan explicitly permits Task 1 before integration and requires the SDD workspace,
`PLAN-CORRECTIONS.md`, task/pairwise consistency table, and cause-based baseline only
before Task 2.  That contradicts the binding execution protocol inherited from the
reviewed #265 plan, which runs Task 0 and the corrections/baseline pre-pass before
*any* implementation task.  It also means Task 1's new SDK boundary and focused test
can land without the stated current-SDK, fake, CI, Python-environment, or test-cause
inventory.

Add a non-mutating Task 0 before Task 1.  It must fail on `.venv`, record the absolute
pyenv interpreter, inventory Task 1's SDK/fake/test seam, capture the Task 1 baseline
causes, and create/attach the overriding corrections file.  Keep a second, stricter
local-integration re-probe before Task 2; it should extend the original pre-pass rather
than be the first one.

### Important 2 — The endpoint validator is not phased to preserve #265's local-before-stale / remote-after-stale contract

**Plan:** [lines 72–89, 172–174, 185–191](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:72)

`validate_custom_endpoint()` owns both local URL rejection and the remote `get(name)`
operation, but Task 2 returns a stale conflict before invoking that one validator.  A
stale request carrying `https://...` consequently returns `409`, although URL policy is
local validation; moving the validator ahead of stale would instead perform a remote
SDK call for every stale request.  The reviewed #265 seam requires deterministic local
validators before stale comparison, and remote/expensive validation only after a valid
current lock has been established.

Specify two phases and their exact error ordering: a local endpoint-name phase (at least
the URL-shaped rejection) runs with the other local validation before stale comparison;
the remote exact-name/state phase runs only after a valid current locked snapshot.
Require tests for invalid-plus-stale URL => ordered no-write `422` and zero SDK calls,
and valid-but-stale => coherent seven-role `409` and zero remote calls.  The latter
should retain the existing stale-loser concurrency proof.

### Important 3 — The final PostgreSQL/interpreter matrix is neither exact nor executable under the mandated environment

**Plan:** [lines 18, 178–183, 398–421](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:18)

All backend examples invoke bare `python`, despite the global constraint naming the
absolute shared pyenv executable.  More seriously, the final matrix combines two
PostgreSQL modules without the explicit `TELLR_TEST_POSTGRES_URL` and omits the known
current predecessor modules: `test_graph_configuration_bootstrap_postgres.py`,
`test_graph_configuration_constraints_postgres.py`,
`test_persisted_graph_runtime_failures_postgres.py`,
`test_conversation_pin_migration_postgres.py`, and
`test_conversation_pin_creation_postgres.py`.  The approved #264 plan requires each
such module as a separate explicit-URL, zero-skip command; its current #261 head is
`77e42b3c1`, whose Task 6 re-review is approved and whose persisted-runtime failure
module is a load-bearing no-fallback regression suite.  Deferring exact filenames to a
future corrections file does not supply the required execution matrix.

Replace every backend command with `/Users/robert.whiffin/.pyenv/shims/python -m pytest`.
List each required PostgreSQL module in its own command with the explicit URL and a
separately recorded zero-skip result.  The Task 0 re-probe may add renamed/final files,
but must not remove this concrete predecessor set or accept an unavailable-server skip.

### Important 4 — The UI/browser acceptance lacks a manual non-URL validation flow

**Plan:** [lines 254–258, 375–379](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:254)

The frontend tests cover selected discovered names, local URL rejection, and discovery
errors, but never manually enter a non-URL endpoint name and prove the save/validation
round trip.  Consequently they do not demonstrate the issue's custom-endpoint
acceptance: a manually entered exact name is sent only as the existing five editable
values, successful validation preserves it verbatim, and an unknown/forbidden/not-ready
server `invalid_draft` response is visible without leaking endpoint contents.  Backend
route tests alone cannot prove that the advanced field is wired to the shared editor
state and the single save pipeline.

Add component and Playwright cases for a manually entered valid exact name and for at
least one server validation failure.  Assert the PUT has only the five editable fields,
uses no discovery metadata/URL/host/token, retains the typed field error and unsaved
form on failure, and permits explicit correction/retry.  Retain the existing URL case's
zero-PUT assertion.

## Verified constraints and current state

- The #266-owned probe removes the former circular dependency: its strict request is
  only `lock_version`; it loads the saved candidate server-side, accepts no endpoint or
  arbitrary payload override, writes no draft/test/approval state, and explicitly keeps
  #267 downstream ([plan:104–118, 320–348, 425, 434](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:104)).
- The catalog boundary, exact parent-name persistence, no alias advance, local search,
  empty-versus-failure behavior, and no `routes/tools.py` heuristic agree with the
  first-party research evidence and issue #266.  `foundation_model` classification,
  `list()`/`get(name)`, model-serving scope, additional inference scope, and the lack
  of a universal provider-error mapping are all documented in the research note.
- Task 5 correctly targets the current runtime seam: at local `feat/langgraph-core`,
  `DatabricksModelAdapter.invoke` constructs `ChatDatabricks` with the endpoint and
  runtime workspace client, then calls `with_structured_output(schema)` before invoke.
  The plan requires the probe to share that extracted binding seam rather than infer a
  negative result from OpenAPI or SDK `query()`.
- #261 current head is `77e42b3c170373407afddc1c98d982af5c3806fa`; its Task 6
  scoped re-review is approved, but it is not yet an ancestor of local
  `feat/langgraph-core` (`76a88f238e84f17cc60eba8a62e00dc80fc26115`).  The plan's
  local integration gate must continue to block Task 2 until all final reviewed
  predecessor heads are locally integrated and re-probed.
- #264's approved plan is `8c72a5a91`; #265 remains the active shared-seam plan at
  `9c411beaf`.  #266 correctly places shared-file work after local #265 then #264,
  leaves #263 as the sole writer/route, and requires a final local-only merge before
  #267 begins.
- No arbitrary URL, endpoint override, or endpoint-content leak was found in the
  specified request contracts.  The requested adapter and UI fakes are deterministic,
  and the plan preserves the seeded exact endpoint rather than auto-advancing it.

## Required correction outcome

After the four corrections above, re-review the amended plan before implementation.
No production implementation, PR, push, or merge was performed for this review.
