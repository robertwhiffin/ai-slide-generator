# Plan correction report 4: declarative protected prompt assembly (#265)

**Corrected from:** `9eabfddb24838a7ef3f3b2e7e4b39e5ef586a92f`

**Binding inputs:**

- `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`
- `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`
- `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-a932d5dc9.md`

This is a plan-only correction. No production code, tests, dependencies, remote refs, issue,
PR, or integration branch was changed.

## Finding-to-amendment map

### C1 — ordinary save could form a v1-identity/v2-rules hybrid

Amended the stable interface and issue contract at plan lines 123–132, 190–215, and 281–322:

- every protected bundle declares one digest-covered `assembly_rules_format_version`;
- `PromptAssembler.validate` resolves the exact identity first and is the sole authority that
  binds v1 identity to v1 rules and v2 identity to v2 rules;
- either resolved hybrid returns the single stable issue
  `candidate.assembly_rules.format_version / assembly_bundle_mismatch / Assembly rules
  format must match the protected assembly bundle.` before all block/protected-plan checks;
- an unknown identity remains the typed unavailable-bundle result; and
- only `upgrade_definition_to_v2` may transition stored v1 content to the v2 pair. Ordinary
  saves can edit v2 rules only after the stored identity already is v2.

Added exact verification requirements:

- Task 2 assembler tests cover both hybrid directions and valid pairs (lines 541–548).
- Task 3 persists both hybrid directions through #261's exact release loader and requires
  `invalid_persisted_definition` before model/sink (lines 682–686).
- Task 4 facade and route tests cover v1 identity plus submitted v2 rules, the reverse
  corrupted-persistence fixture, invalid-plus-stale precedence, exact ordered `422`, no
  post-stale calls, and fresh-session total no-write (lines 754–764).
- The final reviewer must produce the assembler/facade/route/runtime hybrid matrix (lines
  1137–1141).

### C2 — dirty or in-flight legacy prompt could be carried into a savable v2 form

Replaced the unsafe “preserve prompt edits while upgrade is pending” rule with one explicit
lossless quarantine protocol in Task 5 (lines 936–990 and 1015–1042):

- Data Analyst and Build Reviewer v1 upgrades require local prompt bytes to equal the saved
  authoritative bytes before any request ID/ref or POST is created.
- Dirty-before-start text remains in the form and is appended byte-for-byte, including
  Unicode and whitespace, to `legacyPromptRecoveries` in the existing reducer state.
- **Preserve and restore saved prompt** is an explicit local-only action; recovery bytes are
  copyable/manual-only and are never read by candidate construction or automatically
  stripped/reapplied.
- During an affected Upgrade, the prompt control is disabled while safe fields remain
  editable. The reducer quarantines any queued/programmatic prompt event and leaves the
  savable prompt at the authoritative v1 value.
- Success installs the server-authored v2 target in both authoritative and local prompt
  state. It never merges the v1 composite back into v2.

Task 5 now requires hook, reducer, and integrated component tests for dirty-before-start,
byte preservation, explicit restore, edit-during-flight quarantine, safe-field preservation,
success, and an immediate PUT that cannot contain recovery/composite text (lines 965–990).
Task 6 repeats the complete interleaving in Playwright for both affected roles (line 1073).

### I1 — `Annotated` union left known #261 consumers broken and ungated

Task 1 now changes all known consumers in the same commit (lines 419–487):

- `src/services/agent_runtime.py` replaces `AssemblyRules.model_validate(...)` with the
  module-owned `TypeAdapter(AssemblyRules).validate_python(...)` compatibility-loader seam.
- `tests/unit/test_persisted_graph_release.py` replaces the invalid union `isinstance` target
  with concrete `AssemblyRulesV1`/`AssemblyRulesV2` assertions and retains exact-release,
  no-active-fallback, and malformed persisted-assembly coverage.
- Task 1 runs the manifest, runtime, and persisted-release suites together.

The persisted-release suite is also in Task 3's file scope/command (lines 666–707), the final
matrix (line 1086), and the final review evidence list (line 1145). No task intentionally
leaves the production consumer broken between Task 1 and Task 3.

### I2 — PostgreSQL race required an impossible state

Task 4 now fixes one realizable interleaving (lines 809–819):

1. bootstrap is pristine v1 at lock 0;
2. an ordinary v1 same-content save, with rules omitted, holds the lock and wins 0→1;
3. the waiting upgrade used expected lock 0 and returns stale `409` after the winner commits;
4. a fresh upgrade at expected lock 1 alone creates v2 and advances 1→2.

The test must assert distinct PIDs and an observed waiter, and it must prove the winner
preserved exact prompt bytes, v1 rules, protected identity, hash, transition tuple, and
published revision. It also asserts the exact-seven stale snapshot, loser no-write, and the
fresh upgrade's authored-only prompt/rules/identity.

### I3 — `already_current` lacked one owner and exact contract

The plan now makes `upgrade_definition_to_v2` the sole transition-state authority (lines
123–126, 200–215, and 241). It first runs the common semantic validator. For a semantically
valid current v2 pair it emits exactly:

- field: `protected_assembly.version`
- code: `already_current`
- message: `Protected assembly is already current.`

The exact row and ordering are in the exhaustive issue table at line 310. It is singular,
occurs before candidate construction/stale/post-stale work, and cannot mask malformed current
v2 content. Task 2 tests method ownership and ordering (lines 591–594); Task 4 spies on the
method and verifies facade/route structural copying, exact envelope, and no-write (lines
782–788); Task 5 verifies parser/reducer/component behavior (lines 930–934); and Task 6
verifies the Assembly-linked, zero-retry browser result (line 1073).

## Re-probed local evidence

- Worktree started clean on `plan/prompt-assembly-265` at
  `9eabfddb24838a7ef3f3b2e7e4b39e5ef586a92f`.
- Local `feat/langgraph-core` is still
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`; Task 0 remains blocked because it does not
  contain reviewed #261 `785d9aaca35a3a9103cd4283afdc6bda3b679882`.
- Local `feat/conversation-pins-runtime-261` is now observed at
  `0b1b375016f70ff499175d7435b40ac4ac285548`. Both that head and reviewed
  `785d9aaca...` still contain `AssemblyRules.model_validate` in
  `src/services/agent_runtime.py:673` and `isinstance(..., AssemblyRules)` in
  `tests/unit/test_persisted_graph_release.py:138`. The moving head is observation only, not
  review authority.
- Reviewed #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7` still has
  `_write_locked_content` as the mapper/hash/audit/lock writer,
  `useDraftEditor.ts` as owner of `nextRequestIdRef` and `inFlightRequestIdRef`, and
  `draftEditorState.ts` as owner of `pendingSave` and conflict merge. The correction extends
  those owners and adds no second writer, request counter, pending gate, store, or controller.
- Task 0's exact local-only ancestry commands, research-commit rejection, pyenv-only rule,
  no-install rule, and before-Task-1/before-shared-file re-probes are unchanged.

No test suite was run: the deliverable is a plan and correction report, and the only runtime
claims above were checked read-only against local Git objects.
