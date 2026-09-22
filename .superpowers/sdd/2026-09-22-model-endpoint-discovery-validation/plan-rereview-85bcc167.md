# Plan rereview — exact model endpoint discovery and validation (#266)

**Reviewed commit:** `85bcc1672866ace09ba21958d46850b607790be9`
**Plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Verdict:** **CHANGES_REQUIRED**

Finding count: **0 Critical, 1 Important, 0 Minor.**

## Finding

### Important 1 — `IMPLEMENTATION_BASE` is captured before the required rebase, so the final whole-branch review can include predecessor work

**Plan:** [lines 51, 65–69, 495–497](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:51)

Task 0 records the current `IMPLEMENTATION_BASE` before Task 1.  Task 1 is expressly
allowed to run on the reviewed #260 base, while the gate before Task 2 then rebases its
commit onto a later local integration containing #260, #261, #263, #265, and #264.  The
gate records that later commit as `INTEGRATION_BASE`, but never replaces the earlier
`IMPLEMENTATION_BASE`.  The final review nevertheless uses
`IMPLEMENTATION_BASE..HEAD`.

In the normal permitted history, the Task-0 base is an ancestor of the later integration
base.  The final range therefore includes predecessor #261/#263/#265/#264 changes in
addition to #266, defeating the exact-base whole-branch review and making a clean
merge verdict ambiguous.  This is currently material: local `feat/langgraph-core` is
still #263-only, while the final reviewed heads must advance and be merged locally at
the Task-2 gate.

Use distinct names for the two purposes.  Preserve Task 0's pre-integration checkpoint
as (for example) `TASK1_BASE`; after the required local integration is proven and the
Task-1 commit is rebased, write the final `IMPLEMENTATION_BASE` to the exact
`INTEGRATION_BASE` SHA.  Before final review, prove both that it is an ancestor of
`HEAD` and that `IMPLEMENTATION_BASE..HEAD` contains only the rebased Task 1 plus
Tasks 2–6 paths/commits—not predecessor integration changes.  Attach that proof to the
final review package.

## Prior finding verification

The four findings in `plan-review-c26389743.md` are addressed:

1. A non-mutating Task 0 now precedes Task 1, records the absolute pyenv interpreter,
   SDK/fake/CI inventory, and cause-based baseline, and attaches its corrections ledger
   to the Task 1 briefs ([plan:15, 29–61](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:15)).
2. Endpoint validation is now explicitly phased: pure URL/name policy before stale
   comparison, then remote `get(name)`/state validation only for a current locked
   request; the tests require invalid-plus-stale `422` with zero SDK calls and
   valid-plus-stale `409` with zero remote calls ([plan:22, 106–115, 206–232](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:22)).
3. Backend commands use the absolute shared pyenv path, and the final verification
   lists the seven required PostgreSQL modules separately with explicit URL and
   individual zero-skip evidence ([plan:18, 443–493](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:18)).
4. Component and Playwright flows now cover a manually entered non-URL name absent
   from discovery, typed server failure, retained form, explicit correction/retry, and
   the closed five-leaf #263 PUT shape ([plan:301–336, 420–441](docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:301)).

## Independently verified positives

- The installed SDK is `0.112.0`; `ServingEndpointsAPI.list()` is argument-free,
  `get(name)` is present, and `ServedEntityOutput` exposes `foundation_model`.  The
  plan's Serving Endpoints boundary, local search, exact parent-name persistence, and
  non-empty-failure behavior match the first-party research.  It does not assume a
  dedicated `system.ai` API, `task` heuristic, alias guarantee, OpenAPI capability
  oracle, or `query(response_format=...)` contract.
- The current runtime constructs `ChatDatabricks` from the exact configuration and
  runtime workspace client, then calls `with_structured_output(schema)` before invoke.
  Task 5 requires the saved-candidate probe to share that extracted binding seam with
  deterministic fakes; the request admits only `lock_version`, copies its server-side
  identity before network work, and writes no draft/audit/test/approval/chat/deck state.
- #263 remains the sole draft writer and save route.  The plan consumes #265's now
  explicit local-candidate/post-stale validator phases and preserves the one mapper,
  hash, flush, audit, lock, request-ID/reducer, and coherent seven-role conflict
  contracts.
- The plan preserves exact endpoint names, rejects arbitrary URL-shaped input locally,
  avoids aliases and seed auto-advance, keeps errors sanitized, and never accepts an
  endpoint/host/token/prompt/schema/payload override for the probe.
- Current heads are deliberately moving: #261 is now `04526b306`, #264 is
  `77223ae71`, and #265's corrected plan is approved at `3a3583c30`; none should be
  hard-coded as Task-2 authority.  The plan correctly requires re-resolving reviewed
  heads and proving their local ancestry.  #267 remains downstream of a reviewed local
  #266 merge, so no circular implementation dependency remains.

No implementation, PR, push, merge, dependency installation, or environment creation
was performed.  Correct the review-base handoff, then rereview before execution.
