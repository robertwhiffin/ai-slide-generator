# Issue #265 plan correction report

**Plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`
**Review addressed:** `.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-review-ae3d09f34.md`

## Resolution map

| Finding | Correction |
|---|---|
| C1 validator timing | The writer seam now has two immutable ordered phases. Deterministic/local candidate validators run before stale comparison; remote/expensive validators run only for a current candidate. #265 registers only its local assembler validator. Ordering, aggregation, phase short-circuiting, stale no-call, no-write behavior, and generic sentinel tests are explicit without naming downstream policy in production. |
| C2 terminal binding in prompt text | `ResolvedPromptStage` now carries `contributes_to_prompt`. Terminal binding remains final protected provenance/display/digest metadata with `False`; textual prompt joins only contributing stages. A safe-payload test proves the binding literal is absent from prompt text, hostile tests use provenance, and runtime tests prove the adapter calls `with_structured_output` exactly once. |
| I1 upgrade 409 wire type | Upgrade conflicts retain the existing `stale_draft` family with `client_candidate:null` and one coherent exact-seven snapshot. The backend union/schema/route and operation-aware TypeScript parser/reducer/component/browser coverage distinguish null upgrade candidates from non-null ordinary-save candidates. |
| I2 predecessor assertions | Task 0 now names reviewed #261 `785d9aaca35a3a9103cd4283afdc6bda3b679882` and final #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7`, while requiring execution-time final review evidence. It records active #261 `77e42b3c170373407afddc1c98d982af5c3806fa` as unreviewed observation only. Observed local integration `76a88f238e84f17cc60eba8a62e00dc80fc26115` contains #263 but not reviewed #261 and therefore fails the gate. |
| I3 PostgreSQL regression omission | Task 0 baseline and Task 6 final matrix now run `tests/integration/test_persisted_graph_runtime_failures_postgres.py` in its own URL-prefixed command with zero skips. Cause/skip comparison and final whole-branch handoff require its named result. |
| I4 validation contract | Parser-owned and assembler-owned tables are separate and complete. Paths use dotted indices. The tables define exact field/code/message mappings for malformed JSON, strict types, extras, unsupported/unknown literals, duplicate/blank/anchor semantics, fake version/digest, protected placement, singleton, payload, and terminal failures. Deterministic combined phase ordering is explicit. |
| I5 unavailable bundle surface | `ProtectedAssemblyBundleUnavailable` is a stable subtype caught before `PromptAssemblyRejected`; no caller parses messages. Fake version/digest map to `protected_bundle_unavailable`; malformed persisted rules/plan shape map to `invalid_persisted_definition`; both remain zero-model and pre-sink. |
| I6 persisted v2 runtime breadth | Task 3 parameterizes all seven `GRAPH_V1_AGENT_KEYS`, relevant design-system states, and Build Reviewer truthy/falsy deck-brief contexts through persisted runtime. It asserts release/revision/content/protected identities, exact prompt/provenance, one adapter call/binding, and sink behavior. |
| M1 stale remote workflow report | `.superpowers/issue-265-plan-fix-report.md` now describes only reviewed local integration and removes the obsolete fetch/rebase instruction for `origin/integration/261-263`. |

## Preserved constraints

- Local shared order remains reviewed #265 → #264 → #266 after final reviewed #260+#261+#263.
- #261 four-argument runtime, exact persisted release selection, pre-sink failures, identity sink, provider conversion, and no fallback remain protected.
- #263 remains the single locked writer and the frontend retains one aggregate state/request-ID/pending-operation machine.
- V1 bytes/identities, server-owned protected display, auth-before-body parsing, explicit saves, ordered `invalid_draft` issues, exact-seven recovery, and sabotage evidence remain required.
- No implementation, install, remote integration, push, or PR action was performed during this correction.

## Residual execution gate

No #265 implementation may start from observed local integration
`76a88f238e84f17cc60eba8a62e00dc80fc26115`; it lacks reviewed #261. Task 0 must resolve the
then-final reviewed #261 head (not assume observed active head `77e42b3c...`), create or select
one reviewed local integration commit containing final #260/#261/#263, and rerun ancestry,
ownership, and cause-based baselines before Task 1.
