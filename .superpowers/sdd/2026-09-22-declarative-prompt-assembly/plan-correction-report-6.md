# Plan correction report 6: declarative protected prompt assembly (#265)

**Corrected from:** `e218594113218b5321f724bc797ffff8254470ab`

**Binding inputs:**

- `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`
- `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`
- `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-f99a1e7.md`

This is a plan-only correction. No production code, tests, dependencies, remote refs, issue,
PR, push, or integration branch was changed.

## Finding-to-amendment map

### C1 — persisted edited v1 had no operation that could restore the exact transition source

The plan now defines one narrow server-backed recovery operation:
`POST /api/admin/agent-definitions/draft/{agent_key}/legacy-prompt-source`, with strict
`{"lock_version": n}` and authorization-before-body parsing. It reuses #263's aggregate lock,
compares stale first, and returns the existing null-candidate exact-seven `409` on mismatch.
For a current request it fails closed unless all of these are true:

- the role is Data Analyst or Build Reviewer;
- the draft has the exact v1 identity/rules pair and its prompt differs from the retained
  source; and
- the published/base revision, hash, and full source tuple exactly match the assembler-owned
  retained literal transition record.

Success returns only the exact server-supplied v1 prompt, source revision/hash, and current
draft metadata. It performs no map/hash/flush/audit/lock increment, published mutation, Save,
or Upgrade. The plan assigns the literal to `PromptAssembler`, locking/preconditions to the
facade, and HTTP/auth/strict serialization to the route. It adds exact
`legacy_prompt_source_unsupported`, `legacy_prompt_source_not_required`, and
`legacy_prompt_source_unavailable` 422 contracts and total-no-write tests.

The client action **Restore published Graph Version 1 prompt** quarantines both edited saved
and local alternatives before installing only the returned source in local v1 state. The
administrator must then explicitly perform ordinary v1 Save and Upgrade, followed by manual
reapplication. Task 4 covers facade, route, and real-PostgreSQL behavior; Task 5 covers parser,
reducer, hook, and component ownership; Task 6 drives the full persisted one-code-point edit
→ Upgrade 422 → source recovery → v1 Save → Upgrade → authored-only v2 sequence for
both affected roles. Substring stripping, automatic Save/Upgrade, a client-supplied source,
and a second writer remain forbidden.

### I1 — singular recovery state could not retain both safe alternatives losslessly

The plan removes the singular `recoveryForm` design and does not add the prompt-only
`legacyPromptRecoveries` list. Each definition entry instead owns ordered `retainedForms`.
Every retained entry has:

- deterministic stable ID `retained:<agent_key>:<ordinal>` from an entry-owned monotonic
  counter;
- a full form with prompt/rules sanitized against the current authoritative version;
- the exact displaced prompt as copyable manual-only bytes; and
- source/reason metadata.

Reload appends the current local alternative rather than overwriting existing entries.
Restore addresses one ID and re-sanitizes it against the current saved version. Candidate
construction reads only local sanitized state, never a retained entry or manual-only bytes.
On v1→v2 adoption, every retained form gets authoritative v2 prompt/rules while its distinct
endpoint, temperature, max-token, and top-p tuple survives.

Reducer, hook, component, and Playwright matrices now give current-local and pre-existing
alternatives distinct safe-field sentinels, restore every ID after Keep/Reload, and cover Data
Analyst and Build Reviewer as both selected and affected-unselected entries in exact-seven
responses. Every branch ends with an immediate PUT proving no manual-only v1 prompt became a
v2 candidate.

### I2 — final gate enrolled #261 tests without executing its final acceptance matrix

Task 0 now requires the final reviewed #261 head and concrete final command matrix to be
copied into `PLAN-CORRECTIONS.md`, reconciled against the reviewed tree, and executed as the
cause baseline. Task 6 executes that resolved matrix in addition to #265's focused suites.
The observed minimum now includes:

- separate zero-skip PostgreSQL commands for conversation-pin migration, creation,
  persisted-runtime failures, and full acceptance;
- `test_graph_builder.py`, `test_graph_routers.py`, `test_graph_nodes.py`,
  `test_graph_state.py`, `test_deck_level_spec_change.py`, `test_graph_mode_turn.py`,
  `test_deck_spec_change_turn.py`, `test_sweeper_describe_only.py`, and the remaining #261
  loader/runtime/caller and CI guards;
- #260's `test_graph_configuration_constraints_postgres.py`;
- full frontend units/typecheck; and
- `conversation-graph-version.spec.ts` when present in the final reviewed #261 matrix.

The four #261 PostgreSQL files are deliberately separate commands so each records an
independent zero-skip result. The CI-enrollment guard remains, but is no longer treated as a
substitute for running the guarded tests.

## Re-probed local evidence

- The correction worktree started clean at
  `e218594113218b5321f724bc797ffff8254470ab`, which contains the round-6 rereview.
- Local `feat/langgraph-core` remains
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`; it still lacks a final reviewed #261 head, so
  Task 0 remains blocked on a reviewed local integration base.
- The rereview observed committed #261 `a98fdc313b90f07639e32081f6c5c979225f89e6`
  with Tasks 1–8 reviewed and dirty Task 9 work. During this correction that worktree had
  advanced cleanly to `4b88a73c5485440cc587fb9e6829ff03b0a1548c`, with Task 9 commits above
  `a98fdc313`; neither observation replaces final review authority.
- The committed #261 plan's Task 9 concrete gate supplied the observed command/file minimum
  imported into Tasks 0 and 6. Execution must still re-resolve the final reviewed successor.
- Reviewed #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7` remains the frontend and locked-writer
  ownership baseline that the plan extends.

No implementation suite was run because this deliverable changes only the plan and this
correction report. No `uv`, `pip`, install command, or `.venv` operation was used.
