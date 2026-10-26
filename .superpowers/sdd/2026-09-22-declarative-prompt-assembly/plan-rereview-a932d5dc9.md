# Plan rereview: declarative protected prompt assembly (#265)

**Reviewed commit:** `a932d5dc93cc0f49e1862498cce1379265aece02`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Binding spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`

**Prior reviews:**

- `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-review-ae3d09f34.md`
- `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-8f6365e36.md`

**Verdict:** **CHANGES_REQUIRED**

**Findings:** 2 critical, 3 important

## Findings

### Critical 1 — An ordinary save can submit v2 rules against the retained v1 identity and bypass the protected upgrade

The corrected explicit upgrade is exact, but the ordinary-save contract still admits a
hybrid that avoids it. Task 4 makes `candidate.assembly_rules` optional and accepts an exact
v2 rules record whenever it is supplied, then rehydrates it onto server-owned fields (plan
lines 756–764). A normal save retains the stored protected identity, so a Graph Version 1
draft can become `(v1 protected_assembly, v2 assembly_rules)` without calling
`upgrade_definition_to_v2`. Pydantic intentionally permits every shape-valid v2 rule set
(lines 20 and 434–440), and neither the semantic table (lines 275–289) nor the Task 4 test
list (lines 679–721) defines or tests a rules-version/bundle-identity pairing invariant.
“Normal saves keep strict protected identity comparison” does not close this: the request
does not carry an identity to compare, and immutability merely retains v1.

For Data Analyst and Build Reviewer this can evade the exact source-tuple transition and
leave the legacy composite notice/criteria in editable `prompt_text` while selecting v2
rules. Depending on an implementer's unstated dispatch choice, the hybrid may persist or may
fail through an incidental protected-plan error; neither result satisfies the plan's claimed
single, stable semantic authority. The reverse corrupted-persistence hybrid—v2 identity with
v1 rules—is also unspecified.

Add an explicit `PromptAssembler.validate` invariant and stable ordered issue row tying rule
format to protected bundle identity. Add facade/route tests that submit v2 rules to a v1
draft, including invalid-plus-stale, and prove exact `422`, no post-stale call, and total
no-write. Add runtime tests for both hybrid directions before model/sink. Only the
server-owned upgrade may create the v2 identity/rules pair.

### Critical 2 — Preserving prompt edits across a successful upgrade reintroduces the legacy composite into v2

Task 5 keeps prompt editing enabled while an upgrade is in flight (lines 840–849) and requires
upgrade success to preserve prompt/model edits made while pending (lines 851–856). For either
affected role, the local form is still the v1 composite when the request starts. A user can
start from a pristine stored definition, click Upgrade, edit the local composite before the
response, and receive a valid server-owned authored-only v2 definition. The reducer then
preserves the locally edited **composite** over that v2 definition. The next ordinary v2 save
stores the legacy notice/criteria as authored text and the assembler adds the protected v2
stage again.

The server cannot repair this after upgrade without the substring guessing the plan correctly
forbids, and the existing edited-legacy rejection does not help because the edit was never
part of the locked v1 row examined by the upgrade. The same problem exists when the local
prompt was already dirty before the POST. The browser requirements test persisted edited-v1
rejection and pristine success separately (line 940), but never this interleaving.

Require the affected v1 prompt form to equal the authoritative saved prompt before Upgrade,
and prevent it from becoming a savable composite while that upgrade is pending—for example,
disable prompt editing for that role during the request while leaving safe fields editable,
or quarantine a late edit in recovery/manual-resolution state rather than carrying it into
the v2 form. Add hook/reducer/component/browser tests for dirty-before-start and edit-during-
flight, preserving every authored byte for manual reapplication while proving no composite
can subsequently be sent as a v2 authored prompt.

### Important 1 — The `AssemblyRules` union migration leaves a known #261 loader test stale and outside every gate

Task 1 replaces the concrete `AssemblyRules` Pydantic class with an `Annotated` type alias,
but changes only the manifest and its focused test (lines 395–450). At reviewed #261
`785d9aaca...`, `src/services/agent_runtime.py:673` calls
`AssemblyRules.model_validate(...)`, and `tests/unit/test_persisted_graph_release.py:138`
does `isinstance(definition.content.assembly_rules, AssemblyRules)`. The current moving #261
line at `0b1b37501...` still has both consumers. An `Annotated` union has no
`model_validate`, and it is not a valid `isinstance` target.

Task 3 eventually removes the runtime call, but it does not list or run
`tests/unit/test_persisted_graph_release.py` (lines 608–645). The final matrix also omits that
file while claiming persisted-loader coverage (lines 950–970). Thus Tasks 1–2 knowingly leave
the production runtime broken, and the final branch can retain a failing canonical loader
suite. That suite also owns exact-release/no-active-fallback and malformed persisted assembly
coverage.

Update the known consumers in the union-producing task or provide a temporary typed adapter
that keeps every task commit green. Update the loader test to assert `AssemblyRulesV1` (and
the intended v2 typed value), add the file to the appropriate task scope, and run it in Task 3
and the final matrix.

### Important 2 — The required PostgreSQL save/upgrade race has impossible starting state and outcome

Task 4 requires the first session to hold the #263 locks for “a valid v2 save”, win at lock 1,
then requires a concurrent upgrade to wait and return stale `409`, followed by a fresh upgrade
at lock 1 (lines 723–732). These facts cannot coexist:

- From bootstrap lock 0, a normal save must not create v2 because protected identity is
  immutable and the explicit upgrade is the sole transition.
- If the first writer is the protected upgrade and creates v2 at lock 1, the waiting second
  upgrade rehydrates current v2 and must return `422 already_current` before stale comparison,
  not `409`.
- If the draft was v2 before the race, lock 0/bootstrap and a later fresh upgrade are false.

Use a normal **v1 same-content or model-only** winning save that preserves the exact prompt
transition tuple. It can advance lock 0→1 while the upgrade waits; the loser can then validly
return stale `409`, and a fresh upgrade can advance 1→2. State those inputs explicitly and
assert the winner did not alter prompt/rules/identity, in addition to PIDs, observed waiting,
the coherent seven-role snapshot, and loser no-write.

### Important 3 — `already_current` has no single owner or exact issue contract

The plan says `PromptAssembler.validate` is the sole semantic issue producer and
`upgrade_definition_to_v2` owns only the one manual-resolution transition issue (lines
123–131). It later requires an existing v2 definition to return `422 already_current`
(line 225), but the exhaustive semantic table contains no field or message for that condition
(lines 275–289). Task 4 repeats only the code literal (lines 704–715).

If the facade detects current v2, it becomes a second transition authority. If the assembler
upgrade detects it, the “only one transition issue” statement is false. Either way, route,
client, and browser tests have no binding exact envelope. Make the upgrade method the sole
transition-state authority, define the exact `field`/`code`/`message` and ordering for
`already_current`, and carry that row through facade, route, TypeScript parser, and UI tests.

## Prior-finding verification

| Prior finding | Result | Evidence in the amended plan / current code |
|---|---|---|
| Rereview C1: loss-aware Data Analyst/Build Reviewer transition | Core explicit transition resolved; end-to-end still blocked by Critical 1–2 above | Lines 155–199 define literal digest-covered source tuples and authored-only targets. Lines 524–543 guard them against the generated v1 definitions. Lines 691–729 require fresh-session and PostgreSQL exactly-once/no-write proof. Read-only probes confirmed both generated prompts, definition version `2`, v1 identity, and typed v1 rules exactly match the declared sources. |
| Rereview I1: Pydantic preempts assembler semantics | Resolved | Lines 20 and 434–440 restrict v2 Pydantic models to wire shape. Lines 123–131 assign semantic issues to one walker, and lines 681–687 require the exact five-error stale route/facade path through Pydantic into that walker. |
| Original C1: local versus post-stale validator timing | Resolved | Lines 203–215 and 744–754 define immutable ordered phases, local-before-stale precedence, post-stale current-only execution, aggregation order, and no-write behavior. |
| Original C2: terminal binding entered prompt text | Resolved | Lines 133–141 make terminal provenance final and non-contributing. Tasks 2–3 require safe-text absence and exactly one adapter binding. |
| Original I1: nullable upgrade conflict | Resolved | Lines 217–235 define `DraftSaveConflict[None]`, exact `client_candidate:null`, operation-aware parsing, and one coherent exact-seven snapshot. |
| Original I2: stale predecessor assertions | Resolved | Task 0 names reviewed #260/#261/#263 evidence, rejects research `447791d7a`, requires execution-time re-resolution, and blocks the currently insufficient local integration base. |
| Original I3: missing #261 PostgreSQL typed-failure/no-fallback suite | Resolved | Task 0 and Task 6 invoke `tests/integration/test_persisted_graph_runtime_failures_postgres.py` separately and require zero skips and cause comparison. |
| Original I4: incomplete/bracketed validation contract | Dotted parser/semantic ordering resolved; upgrade completeness still blocked by Important 3 | Lines 238–289 use dotted paths and separate parser from assembler ownership. The five-error tuple is exact. `already_current` remains outside the table. |
| Original I5: unavailable-bundle discriminator | Resolved | `ProtectedAssemblyBundleUnavailable` is a stable subtype, and Tasks 2–3 require subtype-first conversion for fake version/digest without message parsing. |
| Original I6: persisted v2 runtime breadth | Resolved | Lines 620–624 require all seven roles, relevant design-system/deck-brief contexts, exact persisted identities, prompt/provenance, adapter call, binding, and sink behavior. |
| Original M1: stale remote integration report | Resolved | Both correction reports now require local-only integration and prohibit naming or using `origin/integration/261-263`. |

## Verified positives

- The generated v1 source records are now concrete rather than heuristic. Read-only execution
  showed Data Analyst generated `prompt_text == INSTRUCTIONS`, length 1578, SHA-256
  `d824f8826d11c9682d4a60357e30bc412f9206612cc6668703dc3c331e767fb7`; Build Reviewer
  generated `prompt_text == INSTRUCTIONS`, SHA-256
  `22d7dfa4c8b1d425bc2f95a6beb1699f10d20aef4941a21f3b0a80d446fe33fc`. Both have
  `definition_version == 2`, protected version `1`, digest
  `e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852`, and typed rules
  equal to `assembly_rules_for(agent_key)`.
- The Build Reviewer target preserves its non-criteria authored material and names the one
  justified deterministic reference rewrite. The plan forbids runtime/manifest substring
  stripping and tests the target against the checked-in generated source.
- Historical generated v1 JSON, published revisions, hashes, identities, and releases remain
  immutable. The upgrade writes only the selected draft through #263's common mapper/hash/
  audit/lock helper and explicitly proves published-v1 equality after reload.
- The five-error semantic route is ordered and falsifiable: blank, invalid role anchor,
  invalid anchor condition, duplicate UUID, and backwards anchor order; it precedes stale,
  calls no post-stale validator, and proves total no-write.
- V2 payload serialization is single-owner and canonical; hostile provenance uses owned stage
  IDs; terminal binding is absent from safe textual prompts and applied once by the adapter.
- #261's four-argument call, exact persisted release selection, pre-sink configuration
  failures, callback-contained provider conversion, identity sink, and no-fallback PostgreSQL
  coverage are preserved in the plan.
- #263 remains the sole locked writer and frontend state/request-ID/pending-operation owner.
  Auth-before-body, nullable upgrade conflicts, exact-seven recovery, same-content audit/lock,
  reached-phase ordering, and PostgreSQL zero-skip requirements are explicit.
- The local sequencing is consistent across the current #264 and #266 plans: reviewed #265,
  then #264, then #266, after final reviewed #260/#261/#263, with an execution-time predecessor
  and final-merge ancestry gate.

## Read-only state and evidence probes

- Before this artifact was written, the review worktree was clean on
  `plan/prompt-assembly-265` at exact
  `a932d5dc93cc0f49e1862498cce1379265aece02`; `git diff --check` was clean.
- Local `feat/langgraph-core` remained
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`. Ancestry probes returned true for reviewed
  #260 `29e034114...` and #263 `1d706e21b...`, false for reviewed #261 `785d9aaca...`, and
  false for research `447791d7a...`. The plan correctly blocks this base.
- The #261 branch moved during this rereview from observed `6d8fa37fb...` to
  `0b1b375016f70ff499175d7435b40ac4ac285548`; reviewed `785d9aaca...` is an ancestor, but
  the moving head was not treated as final review authority. This reinforces Task 0's
  execution-time review-evidence gate.
- The reviewed #263 source at `1d706e21b...` confirms `_write_locked_content` is the one
  mapper/hash/flush/audit/lock path; router admin/principal dependencies precede raw-body
  parsing; `useDraftEditor.ts` owns the two request refs; `draftEditorState.ts` owns the one
  pending gate and seven-role conflict merge; `DefinitionEditor.tsx` owns the four tabs and
  explicit save.
- The reviewed/current #261 source confirms the exact four-argument runtime, persisted loader,
  provider conversion inside the identity-sink callback, and the stale `AssemblyRules`
  consumers cited in Important 1.
- No implementation tests were run because this was a pinned plan-only review. No plan,
  production, test, dependency, remote ref, issue, PR, push, merge, or published artifact was
  mutated.

## Verdict

**CHANGES_REQUIRED.** The corrected explicit server transition and the unified semantic
walker are substantially stronger, but ordinary-save version pairing and the frontend
in-flight edit path can still bypass the protected transition. The three important gaps also
leave a canonical #261 loader regression ungated, require an impossible concurrency outcome,
and leave `already_current` without one exact authority.
