# Plan rereview: declarative protected prompt assembly (#265)

**Reviewed commit:** `9f67addeb648f518c599697d9c9d79f3f500d7f1`

**Reviewed plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

**Binding spec:**
`docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md`

**Prior independent review:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-rereview-f99a1e7.md`

**Correction mapping inspected but independently re-probed:**
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-correction-report-6.md`

**Verdict:** **APPROVED**

**Findings:** 0 critical, 0 important, 0 minor

## Findings

None.

## Prior-blocker verification

| Prior blocker | Result | Independent evidence |
|---|---|---|
| Critical: a persisted edited v1 prompt could not reach the exact transition source | Resolved | The plan adds one fail-closed, read-only, lock-aware server operation at lines 252–293 and assigns source bytes solely to `PromptAssembler.legacy_v1_prompt_source`. It requires the affected role, exact current v1 identity/rules pair, an actually edited stored prompt, and exact published/base revision/hash/full-source equality before returning bytes. Stale wins first; all three current-only 422 cases and success are total no-write. Client requirements at lines 1043–1057 and 1087–1109 quarantine the distinct edited saved/local forms before installing only the returned exact source into local v1 state. The administrator must then explicitly Save v1 and explicitly Upgrade; source recovery neither strips nor writes nor retries. Task 4's fresh-session PostgreSQL sequence and Task 6's browser sequence both start from a persisted one-code-point edit and prove `422 -> exact-source recovery -> v1 Save -> Upgrade -> authored-only v2`, retained edited bytes, and no automatic transition. |
| Important: singular recovery state could not retain local and pre-existing alternatives | Resolved | Global constraint 24 and Task 5 lines 1065–1135 replace `recoveryForm` with ordered entry-owned `retainedForms`. Each stable ID owns a complete sanitized form, exact displaced prompt as manual-only bytes, and source/reason metadata. Reload appends rather than overwrites; restore addresses one ID and re-sanitizes against the current saved version; candidate construction reads only sanitized local state. The required reducer/hook/component/browser matrix gives local and pre-existing alternatives distinct endpoint/temperature/max-token/top-p sentinels, restores every ID, and covers Data Analyst and Build Reviewer as selected and affected-unselected entries in coherent exact-seven responses. Immediate PUT checks after Keep, Reload, and every restore prove manual-only v1 bytes cannot become v2 candidates. |
| Important: final gate enrolled but did not execute #261's runtime/caller/compiled-graph matrix | Resolved | Task 0 lines 413–490 requires the final reviewed #261 head and its concrete commands to be copied into overriding `PLAN-CORRECTIONS.md`, reconciled against the reviewed tree, and executed as the cause baseline. Task 6 lines 1304–1333 contains the currently observed full minimum and makes the imported final matrix authoritative if it expands or renames suites. It separately executes all four #261 PostgreSQL modules with zero skips, the persisted loader/runtime and identity/failure suites, builder/router/node/state compiled-graph suites, deck/graph turn integrations, full frontend units/typecheck, conversation-version Playwright, the CI guards, and #260's graph-configuration constraints PostgreSQL suite. The final-review handoff repeats those exact evidence requirements at lines 1383–1390. |

## Earlier-finding verification

- Exact identity/rules pairing remains one assembler-owned gate. A resolved v1/v2 hybrid emits only `assembly_bundle_mismatch`; an unresolved identity retains the typed unavailable failure. Historical v1's format-1 association is registry/test-frozen without being falsely described as digest-covered, while v2's format declaration is digest-covered.
- Upgrade stale ordering is coherent. The facade compares the locked aggregate version before invoking the transition authority. Only `upgrade_definition_to_v2` owns `already_current` and manual-resolution issues; stale upgrade and stale source recovery return the exact-seven null-candidate 409 and never run current-state transition checks.
- Both PostgreSQL race constructions match #263's locking and same-content semantics: a v1 same-content save advances only lock/audit before the stale waiter and fresh upgrade, and a separate upgrade/upgrade race yields one v2 writer, one coherent stale loser, then current-only `already_current`.
- Runtime integration preserves #261's four-argument release-pinned interface, exact-release loader, pre-sink validation, provider conversion inside the identity-sink callback, and Builder/Fixer retry pins. Bundle-unavailable and invalid-persisted-definition paths occur before model and sink.
- The discriminated `AssemblyRules` union migration covers the two special consumers observed in the current #261 tree: the compatibility loader's class-style parse and the concrete-type assertion in `test_persisted_graph_release.py`; `DefinitionContent.validate_role_assembly` is changed in the producing manifest task.
- #263 remains the sole mapper/hash/audit/lock writer and the sole frontend request/reducer ownership chain. The plan extends its ordered validator phases, aggregate pending gate, request IDs/ref, exact-seven conflict snapshot, and mounted editor ownership rather than adding parallel state or writers.
- Prompt quarantine covers dirty-before-start, queued edits during Upgrade, source recovery, success, ordinary-save 409, upgrade 409, Keep, Reload, and restore-by-ID. Affected prompt controls are state-guarded during Upgrade while safe-field edits remain lossless.
- The browser and final-review matrices cover both affected roles, selected/unselected exact-seven adoption, all source-recovery envelopes, immediate candidate safety, protected-row non-editability, exact request bodies, stale/current races, rollback/no-write, and writer-by-writer review.

## Read-only state and evidence probes

- The plan worktree began clean and exactly at `9f67addeb648f518c599697d9c9d79f3f500d7f1`.
- Local `feat/langgraph-core` is still `76a88f238e84f17cc60eba8a62e00dc80fc26115`. Reviewed #260 `29e034114...` and #263 `1d706e21b...` are ancestors; reviewed #261 `785d9aaca...`, the current #261 branch head `5bbdca80e...`, and research `447791d7a...` are not. The plan therefore correctly blocks shared implementation on the present local base.
- The current #261 branch is not final review authority. Its head `5bbdca80ecd37c0990fbd450721bcc3e533d0db7` records Task 9 as `Needs fixes` because exact turn identity was synthesized rather than observed, and its worktree has a dirty acceptance-test correction. Task 0 correctly requires a clean final-reviewed successor and imports that successor's concrete matrix rather than trusting the moving branch.
- The current #261 Task 9 concrete gate independently matches Task 6's observed minimum: four PostgreSQL modules; database/startup/conversation-pin, persisted-release/runtime, manifest/bootstrap, builder/router/node/state, deck-spec and graph-turn suites; CI/E2E guards; full frontend units/typecheck; and conversation-version Playwright. Every named file currently exists. #260's `test_graph_configuration_constraints_postgres.py` also exists and is explicitly added by #265.
- Reviewed #263 source confirms the one locked writer, parent-before-selected locking, same-content lock/audit increment, coherent exact-seven snapshots, one `pendingSave` gate, one request counter/ref pair, and the singular recovery representation that this plan replaces.
- An absolute-pyenv, bytecode-disabled probe reconfirmed the frozen v1 transition facts: Data Analyst length/SHA-256 `1578`/`d824f8826d11c9682d4a60357e30bc412f9206612cc6668703dc3c331e767fb`; Build Reviewer `1908`/`22d7dfa4c8b1d425bc2f95a6beb1699f10d20aef4941a21f3b0a80d446fe33fc`; exact generated-manifest prompt equality; definition version `2`; protected identity `(1, e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852)`; and typed v1 rules equality for both roles.
- Current #264 and #266 plans still require local shared-file order `#265 -> #264 -> #266`; neither supplies authority to overtake this plan's prerequisite gate.
- GitHub issues #258, #263, and #265 remain open; #265 still explicitly declares #263 as its blocker. No implementation suite was run for this plan-only review.

## Verdict

**APPROVED.** The corrected plan now gives persisted edited v1 content a realizable, fail-closed exact-source recovery workflow; preserves arbitrarily many distinct safe-field alternatives without making legacy prompt bytes candidates; and makes the final reviewed #261 execution matrix plus #260 constraints mandatory at both preflight and completion. The present repository is not yet eligible to execute the plan because #261 still lacks a clean final-reviewed successor, and Task 0 correctly treats that as a hard gate rather than an implementation-time assumption.
