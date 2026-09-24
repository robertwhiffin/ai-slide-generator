# Plan rereview: declarative protected prompt assembly (#265)

**Reviewed commit:** `6945b1c4714ed5c24e717cf171e44718f248f101`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Binding spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`

**Prior full review:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-a932d5dc9.md`

**Author mapping inspected but independently re-probed:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-correction-report-4.md`

**Verdict:** **CHANGES_REQUIRED**

**Findings:** 1 critical, 2 important, 1 minor

## Findings

### Critical 1 — Cross-version conflict and recovery paths can make the v1 composite savable as a v2 prompt

The new dirty-before-start and in-flight quarantine closes the direct successful-upgrade
case, but it does not cover the existing #263 conflict and recovery paths that Task 5
explicitly preserves (plan lines 949–976 and 1037–1043).

At reviewed #263 `1d706e21b...`, `saveConflicted` replaces `entry.saved` with the server
definition but always retains the selected role's old local form
(`draftEditorState.ts:308–323`). `keepLocal` then clears only the conflict
(`:355–357`). `reloadServer` copies the complete old local form into `recoveryForm`, and
`restoreRecovery` later restores that complete form into candidate-producing local state
(`:345–366`). These are deliberately lossless for same-format saves, but they are unsafe
across the protected-assembly transition.

For Data Analyst or Build Reviewer, a second administrator can move the authoritative row
from v1 to v2 while this client still holds the v1 composite. An ordinary stale PUT receives
the current exact-seven v2 snapshot. Under the required reducer behavior, the selected entry
then has a v2 `saved` definition and the old v1 composite in `local`; **Keep local** makes that
combination directly savable. **Reload server** followed by the existing **Restore retained
values** can do the same. A v1 `recoveryForm` created by any earlier conflict can also survive
a later successful upgrade and be restored afterward. Candidate construction then takes the
legacy composite from `local` and v2 rules from the v2 entry. The backend identity/rules
invariant correctly sees a v2/v2 pair and cannot detect that protected v1 notice/criteria
bytes have re-entered authored `prompt_text`; the next assembly duplicates them.

The plan's tests cover dirty-before-start, edit-during-flight, successful replacement, and
generic 409 recovery, but never a 409 or retained recovery whose authoritative definition
crosses v1→v2. The final handoff similarly omits that matrix.

Make every reducer path version-transition-aware. Whenever an affected role's authoritative
definition changes from v1 to v2, preserve the old prompt byte-for-byte only in
`legacyPromptRecoveries`, install the server-authored v2 prompt in candidate-producing local
state, and preserve only safe non-prompt local fields. `keepLocal`, `reloadServer`, and
`restoreRecovery` must never restore a v1 composite over a v2 saved definition. Add reducer,
hook, component, and Playwright cases for both affected roles covering ordinary-save and
upgrade conflicts, clean and dirty local prompts, both conflict actions, a pre-existing v1
`recoveryForm`, and an immediate subsequent PUT that cannot contain composite/recovery text.

### Important 1 — `already_current` before stale makes a concurrent upgrade unrecoverable

The plan requires `upgrade_definition_to_v2` to validate the locked source and emit
`already_current` before stale comparison (lines 201–203, 242, 289–319, 779–788). That order
works only when the caller already holds the v2 definition. It fails in the ordinary
concurrent case:

1. client A and client B both hold v1 at lock 0;
2. A upgrades successfully to v2 at lock 1;
3. B submits Upgrade with expected lock 0;
4. B locks the current v2 row, and the transition method returns `422 already_current`
   before the lock mismatch can produce `409`.

The 422 envelope carries no coherent server snapshot, so B remains on its stale v1
authoritative/local form. Task 5's `already_current` assertion instead assumes the client
already has an authoritative v2 definition (lines 931–935), and the PostgreSQL race covers
only a v1 same-content winner, not an upgrade winner (lines 809–818). Repeating Upgrade can
repeat the same 422; the required no-reload/no-retry client behavior supplies no reconciliation
path.

The transition method should remain the sole owner of `already_current`, but server-derived
transition checks should run only after the locked snapshot is proved current for this
request. This preserves ordinary request-local validation-before-stale while respecting the
plan's own local-before-stale/remote-after-stale split. Add a real two-session upgrade/upgrade
race: the first writer creates v2, the stale waiter returns coherent `409` with the exact v2
snapshot and no write, and only a current request can return `already_current`. Carry that
case through route, reducer, component, and browser tests together with Critical 1.

### Important 2 — The historical v1 rules-format declaration cannot become digest-covered without changing v1 identity

Task 2 says the bundle's declared rules format is digest-covered protected metadata
(lines 541–547), while global constraints forbid changing the historical v1 identity/digest
or generated definitions (line 18). The reviewed #261 v1 digest material in
`agent_runtime.py:_protected_prompt_material` covers criteria, deck brief, environment text,
payload serialization, terminal binding, and the notice; it does **not** include an assembly
rules format declaration. The corrected plan itself later says specifically that the **v2**
digest includes the declared rules format (lines 618–623).

Therefore an implementation cannot make the new v1 declaration digest-covered and retain
`e4ff3d...` at the same time. Recomputing or relabelling the v1 digest would violate the
historical-release contract. State the realizable contract explicitly: the exact historical
v1 identity is immutably associated with format 1 by the retained registry and regression
tests, while the newly minted v2 digest covers its format-2 declaration. The functional
hybrid rejection in both directions remains required. Do not instruct an implementer to
regenerate or reinterpret the v1 digest.

### Minor 1 — The final local matrix omits the existing #261 CI-enrollment guard

The final matrix runs the #261 PostgreSQL runtime-failure module directly, but not
`tests/unit/test_ci_collects_integration_tests.py` (plan lines 1084–1105). Reviewed #261 adds
a dedicated assertion that this file remains named in the `integration-graph` workflow.
Because #265 begins by creating a local integration commit from independently developed
#261/#263 lines and will not receive remote CI, include that unit guard in Task 0 and the final
matrix. This is a small matrix omission, not a production-design defect.

## Prior-finding verification

| Prior finding | Result | Independent evidence |
|---|---|---|
| Prior C1: ordinary save could form a v1-identity/v2-rules hybrid | Core backend correction is sound; final approval still blocked by Critical 1 | Lines 191–215 bind exact identities to rule formats and restrict transition to the upgrade. Tasks 2–4 cover both hybrid directions at assembler/runtime/facade/route boundaries, invalid-plus-stale precedence, typed runtime failure, and no-write. The remaining bypass carries composite prompt bytes across a valid v2/v2 pair rather than violating the pair itself. |
| Prior C2: dirty or in-flight legacy prompt could be carried through successful upgrade | Direct success case resolved; conflict/recovery variants remain open | Lines 949–969 block dirty start, quarantine queued prompt edits, preserve bytes manually, and install the server-authored target on success. Lines 971–976 retain #263's format-agnostic conflict/recovery behavior, producing Critical 1. |
| Prior I1: `AssemblyRules` union left known consumers broken | Resolved | At current #261 source, the executable class-style consumer remains `agent_runtime.py:673` and the invalid `isinstance` target remains `test_persisted_graph_release.py:138`; Task 1 updates both in the union-producing commit, runs both suites, and Task 3/final matrices retain the persisted-release suite. Other current uses are annotations or v1 response/client shapes that later tasks intentionally evolve before v2 draft persistence. |
| Prior I2: impossible PostgreSQL save/upgrade race | Resolved | Lines 809–818 now use the realizable v1 same-content winner at lock 0→1, waiting stale upgrade, then fresh 1→2 upgrade, with distinct PIDs, observed waiting, preservation, coherent snapshot, and no-write assertions. |
| Prior I3: `already_current` lacked one owner/exact contract | Ownership and literals resolved; stale ordering remains open | The transition method is the sole owner and the exact field/code/message is carried through backend/client tests. Important 1 identifies the concurrent-state ordering gap. |

## Verified positives

- `PromptAssembler.validate` is now the sole candidate-semantic walker. Pydantic v2 models
  deliberately preserve shape-valid semantic errors, the draft adapter copies issues without
  policy, and exact per-block/phase ordering is specified and tested.
- Both identity/rules hybrid directions are rejected before block walking, hash/write, model,
  and identity sink. Unknown identities remain a distinct typed failure. Runtime conversion
  preserves #261's pre-model/pre-sink behavior and provider conversion remains inside the
  sink callback.
- The successful Data Analyst/Build Reviewer transition is exact and loss-aware: literal
  generated-v1 source tuples, one-code-point rejection, authored-only targets, no substring
  heuristic, no published-v1 mutation, and exact once-only protected rendering.
- The corrected `AssemblyRules` task no longer knowingly leaves an `Annotated` union consumer
  broken between commits. The persisted-release test is present in Tasks 1 and 3 and the final
  matrix.
- #263 remains the one mapper/hash/audit/lock writer. Local validators precede stale, generic
  post-stale validators run only for a current lock, and every reached rejection is specified
  as a total no-write.
- The v1 same-content PostgreSQL race is realizable under #263's parent/selected-row locking
  and checks state identities rather than counts.
- Client request ownership remains in `useDraftEditor.ts`; reducer state/operation ownership
  remains in `draftEditorState.ts`; `DefinitionEditor.tsx` owns tabs/conflict/recovery UI; no
  second controller, store, request counter, pending gate, or writer is introduced.
- Dependency ordering is consistent with the current #264 and #266 plans: shared integration
  is locally gated as reviewed #260 + final reviewed #261 + reviewed #263 → #265 → #264 →
  #266, with collision-free Task 1 exceptions for later slices and execution-time ancestry
  re-probes.

## Read-only state and evidence probes

- The review worktree began clean and exactly at
  `6945b1c4714ed5c24e717cf171e44718f248f101`.
- Local `feat/langgraph-core` remains
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`. It contains reviewed #260
  `29e034114...` and #263 `1d706e21b...`, but not reviewed/current #261 work or research
  `447791d7a...`; the plan correctly blocks execution on this base.
- Local `feat/conversation-pins-runtime-261` is at
  `0b1b375016f70ff499175d7435b40ac4ac285548`, whose Task 7 fix has a clean scoped rereview,
  but its ledger shows Task 8 in progress and Task 9 still pending. It is therefore not a
  final #261 authority. Its dirty worktree contains unrelated in-progress Task 8 frontend and
  workflow changes; no file was modified or test run there. Source paths used for this review
  were confirmed unchanged from the named commit.
- The #261 Task 7 commits after `785d9aaca...` do not touch runtime, manifest, persisted loader,
  or persisted-release tests. Independent searches at `0b1b375...` confirmed the union
  consumers and exact four-argument runtime, persisted loader, identity sink, provider
  conversion, and pre-sink validation seams cited above.
- Read-only execution with `/Users/robert.whiffin/.pyenv/shims/python` confirmed generated v1
  Data Analyst prompt length 1578/SHA-256 `d824f882...`, Build Reviewer length 1908/SHA-256
  `22d7dfa4...`, exact prompt equality, definition version 2, protected identity
  `(1, e4ff3d...)`, and typed rules equal to
  `AssemblyRules.model_validate(assembly_rules_for(agent_key))`. The raw helper returns a dict,
  so the prior report's unqualified direct equality wording was not relied on.
- Reviewed #263 source confirms `_write_locked_content` is the sole writer and confirms the
  exact selected-entry conflict/keep/reload/restore behavior cited in Critical 1.
- GitHub issues #261, #263, #264, #265, and #266 are all still open. #265 remains explicitly
  blocked by #263. Local #264 has only its permitted collision-free early implementation above
  its plan line and does not contain #263/#265; its own gate blocks shared-file work. The #266
  plan requires reviewed local #265 and #264 ancestry before shared-file work.
- No implementation suite was run because this is a pinned plan-only review. No plan,
  production code, tests, dependencies, remote refs, issue, PR, integration branch, or push was
  changed.

## Verdict

**CHANGES_REQUIRED.** The corrected backend pairing, issue ownership, union migration, and
realizable v1-save/upgrade race are substantially stronger. Approval is blocked because a
remote v1→v2 transition can still strand or reintroduce legacy composite prompt bytes through
the retained conflict/recovery state machine. The transition/stale order and historical-v1
digest wording must also be made realizable, and the new cross-version cases must be added to
the final test/review matrices.
