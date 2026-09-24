# Plan correction report 5: declarative protected prompt assembly (#265)

**Corrected from:** `eff0d4b8647acd8be34b58bfd6667ac4051f1254`

**Binding inputs:**

- `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`
- `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`
- `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-6945b1c.md`

This is a plan-only correction. No production code, tests, dependencies, remote refs, issue,
PR, push, or integration branch was changed.

## Finding-to-amendment map

### C1 — cross-version conflict/recovery could make a legacy composite savable as v2

The plan now applies one version-aware reducer invariant whenever an affected role's
authoritative definition crosses v1→v2, regardless of whether that happens through Upgrade
200, ordinary Save 409, or Upgrade 409, and independently for every affected selected or
unselected entry in an exact-seven snapshot:

- every displaced prompt from `local` or a pre-existing `recoveryForm` is copied
  byte-for-byte only into the entry-owned append-only `legacyPromptRecoveries` list;
- candidate-producing local and retained forms receive the server-authored v2 prompt and v2
  rules, while safe non-prompt local/recovery fields remain lossless;
- `saveConflicted`, Keep local, Reload server, Restore retained values, and upgrade success
  all reapply the invariant against the current saved version; and
- candidate construction reads only sanitized local state and never a recovery entry.

Task 5 now requires reducer, hook, and integrated component matrices for Data Analyst and
Build Reviewer, ordinary-save and upgrade conflicts, clean and dirty prompt state, both
conflict actions, a pre-existing v1 recovery form, safe non-prompt preservation, and an
immediate PUT proving that neither a composite nor any recovery text is candidate-producing.
Task 6 repeats the full matrix in Playwright. The final reviewer must report the same matrix.

This directly covers the reviewed #263 behavior: `saveConflicted` adopts server `saved` while
retaining selected local state, Keep local clears only the conflict, and Reload server /
Restore retained values store and restore complete forms. Those same-format semantics remain
lossless; only an affected v1→v2 boundary quarantines prompt/rules while preserving safe
fields.

### I1 — stale concurrent upgrade was masked by `already_current`

The upgrade transaction now compares `expected_lock_version` with the selected locked
aggregate before invoking `PromptAssembler.upgrade_definition_to_v2`. Therefore:

- a stale upgrade always returns the coherent exact-seven `409` with
  `client_candidate:null`, even if the locked row is already v2 or contains edited legacy
  prompt text;
- only a current request invokes the transition method and can receive its exact
  `already_current` or manual-resolution issue; and
- the transition method remains the sole issue owner. The facade never derives version,
  digest, rules, or prompt state.

Task 4 adds current/stale facade and route cases plus a real PostgreSQL upgrade/upgrade race:
the winner alone creates v2, the observed stale waiter returns the coherent v2 `409` with no
write or transition call, and a fresh current request alone returns `422 already_current`.
Tasks 5–6 carry the stale-v2 conflict through reducer, component, and browser reconciliation.

### I2 — historical v1 rules-format association was not digest-covered

The global and bundle contracts now distinguish the two realizable guarantees:

- the retained registry and regression tests immutably associate the historical v1 identity
  with format 1, but that declaration is not retroactively digest-covered; and
- the newly minted v2 digest covers its format-2 declaration.

Task 2 still requires hybrid rejection in both directions and valid-pair tests, while
explicitly forbidding recomputation, reinterpretation, or mutation of the frozen v1 digest.
Only the v2 digest material includes the declared format.

### M1 — #261 CI-enrollment guard was absent from local matrices

Task 0 now runs `tests/unit/test_ci_collects_integration_tests.py` as an explicit baseline
guard. Task 6 includes it in the final unit matrix, and the final reviewer must record its
workflow-enrollment result together with the zero-skip PostgreSQL runtime-failure result.

## Re-probed local evidence

- The correction worktree started clean at
  `eff0d4b8647acd8be34b58bfd6667ac4051f1254`, which contains the completed round-5 review.
- Local `feat/langgraph-core` remains
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`; it contains reviewed #260 and #263 but not
  reviewed #261, so Task 0 remains blocked on a final reviewed local integration base.
- Local `feat/conversation-pins-runtime-261` remains observed at
  `0b1b375016f70ff499175d7435b40ac4ac285548`, with Task 8 in progress and Task 9 pending;
  it remains observation rather than final authority.
- Reviewed #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7` confirms the exact conflict seams addressed
  above: `saveConflicted` adopts server saved state but retains selected local form,
  `keepLocal` clears only conflict, and reload/restore retains and restores complete forms.
- #264 and #266 retain the required local integration order #265 → #264 → #266.

No implementation suite was run because this deliverable changes only the plan and its
correction report. No `uv`, `pip`, install command, or `.venv` was used.
