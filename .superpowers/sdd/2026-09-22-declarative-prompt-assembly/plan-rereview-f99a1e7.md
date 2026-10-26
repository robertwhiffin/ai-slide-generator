# Plan rereview: declarative protected prompt assembly (#265)

**Reviewed commit:** `f99a1e7e4dab43af512899f0f7056ca4244084dd`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Binding spec:**
`docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`

**Prior independent review:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-6945b1c.md`

**Correction mapping inspected but independently re-probed:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-correction-report-5.md`

**Verdict:** **CHANGES_REQUIRED**

**Findings:** 1 critical, 2 important

## Findings

### Critical 1 — The persisted-edited-v1 manual-resolution path has no operation that can restore the exact transition source

The backend transition is correctly loss-aware: an affected v1 draft whose persisted
`prompt_text` differs by one code point from the retained generated source returns
`legacy_prompt_manual_resolution_required` and writes nothing (plan lines 204–223 and
799–807). The client contract then says the administrator must restore the exact Graph
Version 1 prompt, Save, Upgrade, and manually reapply the retained edit (lines 955–964).
However, the only concrete restore operation added by the plan is **Preserve and restore
saved prompt** (lines 984–993). That copies `entry.saved.prompt_text` back into `local`.

Those are different values in precisely the case that reaches this error. If an admin has
already made an ordinary v1 prompt save, `entry.saved.prompt_text` is the edited composite,
not the immutable generated/published v1 source required by
`LegacyV1PromptTransition.source_composite_prompt`. The 422 path creates no recovery form,
does no server-authored reset, and deliberately performs no client rewrite. Restoring the
saved prompt and retrying therefore submits the same edited persisted value and returns the
same 422 forever.

Reviewed #263 confirms that the editor state stores only the current `saved`/`local` forms
and an optional conflict recovery form; `DefinitionEditor` does receive the published node,
but its Prompt tab exposes only `entry.local`. The corrected plan does not define a control
that copies the immutable published v1 prompt, a server-owned reset operation, or any other
way to obtain the exact transition source. Its claimed “Restore, Save, Upgrade, then
reapply” workflow is consequently not implementable from the specified UI.

Define one exact recovery operation and source of truth. A narrow option is a clearly named
**Restore published Graph Version 1 prompt** action that is available only when the affected
saved definition still has the exact v1 identity/rules and the published/base definition is
the retained transition source. It must first quarantine the edited saved/local bytes, then
place the exact server-supplied published composite into candidate-producing local state for
an explicit ordinary v1 Save; only after that succeeds may Upgrade run. If those preconditions
are not true, fail closed rather than guessing. Add reducer, hook, component, route-backed
workflow, and Playwright coverage starting from an already-persisted one-code-point edit and
proving 422 → exact-source restore → v1 Save → v2 Upgrade → authored-only prompt, with no
automatic stripping and no loss of the edited bytes.

### Important 1 — One singular `recoveryForm` cannot preserve both safe snapshots required by the new cross-version Reload matrix

The correction requires a pre-existing v1 recovery form and the current local form to retain
all safe non-prompt fields losslessly when an authoritative response crosses v1→v2 (global
constraint line 24; Task 5 lines 1006–1027 and 1099–1110). It also requires **Reload server**
followed by **Restore retained values** for that same state.

At reviewed #263, each entry has exactly one `recoveryForm`. `reloadServer` overwrites that
slot with the current local form before replacing local with server values. The corrected plan
keeps that singular form and adds only `legacyPromptRecoveries`, explicitly a list of prompt
strings. Consider a realizable entry with three distinct safe-field tuples:

1. authoritative server v2 values;
2. current dirty local v1 values; and
3. a pre-existing v1 `recoveryForm` from an earlier conflict.

The v1→v2 adoption can sanitize the prompts and temporarily retain tuples 2 and 3 in local
and `recoveryForm`. But **Reload server** must move tuple 2 out of local while tuple 3 already
occupies the only recovery slot. Overwriting the slot loses tuple 3; retaining the slot loses
tuple 2. The prompt-only list cannot store either safe-field tuple. Thus the plan's required
lossless behavior is impossible whenever the local and pre-existing recovery model values
differ—the exact case a sentinel test should exercise.

Specify a representation capable of retaining both alternatives (for example, ordered full
safe-field recovery entries whose prompt/rules are always sanitized against the current
authoritative version), or explicitly define and justify a loss policy instead of claiming
losslessness. Tests must give local and pre-existing recovery forms distinct endpoint,
temperature, token, and top-p sentinels and cover Keep local plus Reload → each retained-form
restore for Data Analyst and Build Reviewer. Apply the same exact-seven reducer check to an
affected unselected role; the current browser wording only explicitly crosses the selected
definition.

### Important 2 — The final gate runs the CI enrollment guard but omits the final #261 runtime/caller acceptance matrix it guards

Task 0 correctly refuses to start until a final reviewed #261 head is integrated, and Task 6
now runs `tests/unit/test_ci_collects_integration_tests.py`. But the hard-coded final commands
(lines 1183–1204) execute only #261's persisted-runtime-failure PostgreSQL module and a subset
of its unit suites.

The committed #261 plan at current observed head `a98fdc313...` defines its Task 9 final gate
with four PostgreSQL files—migration, creation, persisted failures, and
`test_conversation_pin_acceptance_postgres.py`—plus `test_graph_builder.py`,
`test_graph_routers.py`, `test_graph_state.py`, deck-spec/graph-turn integrations, and related
call-path suites. The acceptance test deliberately drives the real persisted loader/runtime,
compiled graph, all model roles, retry/re-review paths, identity sink, and fan-out pins. Those
are exactly the seams Task 3 changes. The CI guard proves only that the modules are named in a
workflow; it does not execute them.

Make Task 0 import the final reviewed predecessor's concrete regression matrix into
`PLAN-CORRECTIONS.md`, and make Task 6 run that resolved matrix in addition to #265's focused
tests. At minimum retain all four final #261 PostgreSQL modules with separate zero-skip
results and its runtime/caller/compiled-graph unit and integration suites. Also carry the
current #260 graph-configuration constraints PostgreSQL suite forward. The final-review
handoff's generic “exact #261/#263 regression results” is not a substitute for executable
commands.

## Prior-finding verification

| Prior finding | Result | Independent evidence |
|---|---|---|
| Prior C1: cross-version conflict/recovery could make a legacy composite savable | Candidate safety is now specified, but full approval remains blocked by Important 1 | Global constraint 24 and Task 5 centralize v1→v2 adoption across ordinary-save 409, upgrade 409, upgrade 200, Keep local, Reload, Restore, and exact-seven selected/unselected entries. They force authoritative v2 prompt/rules into candidate-producing forms and require immediate-PUT proof. The remaining defect is representational loss of one safe-field alternative, not reintroduction of the prompt into a candidate. |
| Prior I1: `already_current` masked a stale concurrent upgrade | Resolved | The locked facade compares `expected_lock_version` before calling the transition method (lines 204–210, 249, 327–330, 888–895). Current-only transition issues retain one owner. Task 4 defines a real upgrade/upgrade winner, observed waiter, coherent v2 409 loser, and fresh current-only 422. Reviewed #263 locks the singleton draft parent before the selected row, so the race is realizable: the loser may wait on the parent lock and then observes lock 1 and the winner's v2 snapshot. |
| Prior I2: historical v1 rules-format association was falsely digest-covered | Resolved | Lines 18 and 192–202 explicitly state that the retained registry/tests associate v1 with format 1 without reinterpreting its frozen digest; only v2 covers its format-2 declaration. Task 2 tests both hybrid directions and forbids v1 digest recomputation. A source probe confirmed current `_protected_prompt_material()` has no rules-format declaration. |
| Prior M1: final matrix omitted the #261 CI-enrollment guard | The named omission is resolved; the broader predecessor execution matrix is not | Task 0 and Task 6 run `test_ci_collects_integration_tests.py`, and final review requires its result. Important 2 explains why enrollment alone does not execute the final #261 acceptance/caller suites. |
| Earlier C1: ordinary save admitted a v1-identity/v2-rules hybrid | Resolved | Exact identity/rules pairing precedes block walking and hashing. Task 4 covers both hybrid directions at facade/route boundaries, invalid-plus-stale precedence, no post-stale validation, and total no-write; Task 3 carries both through persisted runtime before model/sink. |
| Earlier C2: successful upgrade could retain a dirty/in-flight legacy composite | Resolved for the successful transition | Affected roles must be prompt-clean before start, queued prompt edits are quarantined, prompt editing is state-guarded during the request, and the server-authored v2 prompt replaces local state before the next PUT. The new Critical 1 concerns a persisted edited v1 source rejected before success. |
| Earlier I1: `AssemblyRules` union left known #261 consumers broken | Resolved | Task 1 updates `agent_runtime.py` to use a module-owned `TypeAdapter`, replaces invalid `isinstance(..., AssemblyRules)`, and runs `test_persisted_graph_release.py`; Task 3 and the final matrix retain it. Current #261 still has exactly the two special union consumers named by the plan plus the manifest validator that Task 1 directly rewrites. |
| Earlier I2: save/upgrade PostgreSQL race was impossible | Resolved | The first race now uses a v1 same-content winner that advances 0→1 without changing the transition tuple, followed by a stale waiter and fresh 1→2 upgrade. The second race separately covers two upgrades. Both fit #263's parent/selected locking and same-content write behavior. |
| Earlier I3: `already_current` lacked one owner/exact contract | Resolved | `upgrade_definition_to_v2` alone owns the exact field/code/message. Facade, route, parser, reducer, component, and browser contracts copy/render it without deriving state, and stale requests never invoke that authority. |

## Verified positives

- The backend request/reducer ownership remains coherent: #263's facade is the only
  mapper/hash/audit/lock writer; `PromptAssembler.validate` is the single candidate-semantic
  walker; local validators precede stale only for editable Save candidates; post-stale
  validators are current-only; upgrade compares stale before server-derived transition state.
- Every reached rejection is specified as a no-write path, including invalid-plus-stale
  hybrids, manual resolution, current `already_current`, and stale upgrades. Runtime rejects
  unavailable/hybrid/invalid persisted definitions before model and before the identity sink;
  provider conversion remains inside the sink callback.
- The historical v1 constants and generated definitions remain frozen. A fresh absolute-pyenv
  probe confirmed Data Analyst length/SHA-256 `1578`/`d824f882...`, Build Reviewer
  `1908`/`22d7dfa4...`, exact manifest prompt equality, definition version `2`, protected
  identity `(1, e4ff3d...)`, and typed equality between the stored rules and the
  `AssemblyRules.model_validate(...)` result for `assembly_rules_for(agent_key)`.
- V2's digest covers its declared format, seven role-specific notices, anchors/order,
  serializer, stage/provenance metadata, terminal non-contribution, and both literal
  transition records. Hostile-payload tests use owned stage IDs rather than attacker-controlled
  substring positions.
- The final implementation order is consistent across the current #264 and #266 plans:
  reviewed #260 + final reviewed #261 + reviewed #263, then #265 → #264 → #266. Both downstream
  plans gate shared-file work on the reviewed local predecessor chain.

## Read-only state and evidence probes

- The review worktree began clean and exactly at
  `f99a1e7e4dab43af512899f0f7056ca4244084dd`.
- Local `feat/langgraph-core` remains
  `76a88f238e84f17cc60eba8a62e00dc80fc26115`. Ancestry probes were true for reviewed #260
  `29e034114...` and #263 `1d706e21b...`, false for reviewed #261 `785d9aaca...`, current
  observed #261 `a98fdc313...`, and research `447791d7a...`. The plan therefore correctly
  blocks execution on the present local root.
- The #261 branch has advanced since correction report 5's observation: its committed head is
  now `a98fdc313...`, with Tasks 1–8 reviewed, while its worktree contains dirty Task 9
  acceptance/CI work. Reviewed `785d9aaca...` is its ancestor, but neither the moving head nor
  dirty Task 9 state was treated as final authority. Its committed plan supplies the concrete
  final-matrix evidence used in Important 2.
- Reviewed #263 source independently confirms the singular `recoveryForm`, exact-seven 409
  merge, selected local retention, Keep-local clear-only behavior, Reload overwrite, Restore
  copy-back, one hook request/ref owner, and one locked backend writer cited above.
- GitHub issues #261, #263, #264, #265, and #266 are all still open. #265 remains explicitly
  blocked by #263. The current #264 and #266 plans preserve #265 → #264 → #266 shared-file
  order and execution-time ancestry re-probes.
- No implementation suite was run because this is a pinned plan-only review. Read-only probes
  used the absolute shared pyenv interpreter; no `uv`, `pip`, install, or `.venv` operation was
  used. No plan, production code, tests, dependency, remote ref, issue, PR, push, or integration
  branch was changed.

## Verdict

**CHANGES_REQUIRED.** The prior backend pairing, stale ordering, historical digest, union,
race, and direct cross-version prompt-safety findings are materially corrected. Approval is
still blocked because a persisted edited legacy prompt cannot reach the exact-source state the
backend requires, the singular recovery model cannot satisfy the promised lossless safe-field
matrix, and the final gate does not execute the final #261 runtime/caller acceptance matrix.
