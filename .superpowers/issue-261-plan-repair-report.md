# Issue #261 plan repair report — third correction

**Plan:** docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md

**Authorities re-probed:** GitHub #258, #261, #262; the 2026-09-21 design; #260 worktree preflight; final #260 merge 29e034114; current branch code; .superpowers/issue-261-plan-review.md; and .superpowers/issue-261-plan-rereview.md.

## Rulings

1. #261 owns only explicit POST /api/sessions creation. Browser new-root creation is that explicit path and sends graphCapable true before its first message; chat auto-create, contributors, duplicates, and mixed-release collaboration remain #262.
2. The API default is false for non-browser callers. A browser root is capability-pinned, not a claim that its first monolith turn used the graph; the UI label is Pinned Graph Version.
3. The active-release lock has exactly two READ COMMITTED scans. A publication-first wait that makes R1 ineligible triggers the second fresh scan and pins R2. Creation-first locks/pins R1 and makes publication wait.
4. Production MLflow tracing is forbidden by merged PRD authority. The plan uses a structured non-retaining application-log identity sink with an allowlist of identity/outcome fields and no customer content or trace table.
5. Dangling-release end-to-end PostgreSQL setup is removed: RESTRICT plus immutable release guards make it invalid. Direct loader proves absent ID; shipped graph seam proves null pin.

## Review findings corrected

| Review finding | Plan correction |
|---|---|
| #262 scope collision | Global boundary and Task 2 exclude chat route/auto-create and assert that boundary. |
| Unproduced pin loader | Task 2 produces implementation-level loader code and Task 5 consumes it. |
| Unmigrated callers/fixtures | Task 4/5 inventory includes all named runtime adapters, direct callers, rereview tests, and graph_turn_env. |
| PostgreSQL files omitted from CI | Task 9 owns all four integration files in integration-graph and CI collection guard. |
| Zero mappings read as absent | Task 3 requires release-anchored outer join and zero-mapping RED/sabotage. |
| Later node failures swallowed | Task 6 defines one typed failure family and re-raises it from every broad recovery block. |
| Missing constructors/acceptance program | Tasks 3/4 declare loader/runtime/trace interfaces and Task 9 defines the ordered deterministic role-output program. |
| Misleading eager pin | Explicit default-false intent and cost-if-wrong ruling. |
| Endpoint identity omitted | Task 4 introduces endpoint error/trace proof. |
| Collision table incomplete | The final table orders nodes, rereview tests, chat service, workflow, and graph harness edits. |

## Second-pass corrections

| Re-review finding | Plan correction |
|---|---|
| Ordinary browser graph root was unpinned | Task 8 owns API camel/snake serialization, browser true intent before first message, SessionContext version state/reset/restore, and normal New Session graph-first-message E2E. |
| Publication-first lock failed | Task 2 gives two-scan READ COMMITTED code and forced R1-to-R2/R1-first ordering assertions. |
| Runtime callers and fixture omitted | Tasks 4/5 list every rereviewed compatibility suite and make graph_turn_env seed graph_release_id in direct graph state. |
| MLflow conflicts with final merge | MLflow removed; logging identity sink has explicit content-retention/security contract and production construction. |
| Assembly/schema vague | Task 3 uses DefinitionContent/AssemblyRules; Task 4 defines exact V1 evaluator and all-role/context parity. |
| Typed failures incomplete | Task 4 conversion table plus Task 6 exact safe stream event make later node re-raise effective. |
| Acceptance state machine incomplete | Task 9 supplies A/B, two turns, every retry/rebuild tail, typed outputs, real Send wrapper, and ordered identity assertions. |
| uv violated pyenv rule | Every backend command uses python -m pytest; pre/post checks require shared Python 3.11 and absent .venv. |
| chat_service collision wrong | Task 1 owns selector delegation and Task 6 owns stream contract; collision table is ordered. |

## Plan-quality verification

- Read all required skills: writing-plans, codebase-design, executing-plans-tellr.
- Ran placeholder/signature/scope/CI keyword scans against the repaired plan; removed all ellipsis/TODO-style placeholders.
- Re-ran no-MLflow, no-uv, browser-intent, compatibility-caller, state-seed, and CI-enrollment searches after the second correction.
- Ran git diff --check successfully.
- No production code or tests were run or changed; this is planning-only work.

## Third-pass correction for `.superpowers/issue-261-plan-rereview-2.md`

**Code seams re-probed:** `validate_definition_hash` wraps malformed semantic
content and altered hashes in `GraphConfigurationIntegrityError`; the current
model adapter owns provider construction, `with_structured_output`, and
invocation in one call; `DataRequest.metric` is required; an architect edit
requires `target_positions`; and the Build Reviewer, Fixer, Fix Reviewer, and
serial re-review payloads have no `session_id`. The existing graph-thread
fallback stringifies exceptions as `error=str(e)`.

| Residual finding | Third-pass correction |
|---|---|
| Pin loading is outside the persisted error family | Task 6 explicitly catches `ConversationPinMissingError` and `ConversationSessionNotFoundError` at the graph/chat boundary, sends the same safe persisted-configuration event, and proves neither reaches generic stringification. |
| Invalid or altered persisted content escapes typed recovery | Task 3 catches the actual `GraphConfigurationIntegrityError` wrapper and converts it to `PersistedConfigurationUnavailableError(code="invalid_persisted_definition")`; Task 6 proves both malformed typed content and altered hashes through Builder and Deck Reviewer recovery. |
| Payloads cannot key an A/1-A/2-B/1 adapter by session | Task 4 adds an explicit `agent_key` adapter argument (the two reviewer roles share a schema), and Task 9 uses it with a global ordered deque, serial segment boundaries, runtime-sink identity, and Send-pin assertions. |
| Acceptance fixture constructors are invalid/incomplete | Task 9 now uses `DataRequest(metric="revenue")`, a `changed_spec` copied with audience `Changed audience`, and a valid edit output with `deck_spec=changed_spec` and `target_positions=[0]`, followed by the exact five-call rereview/rebuild tail. |
| Endpoint availability and output validity have no seam | Task 4 names provider phases and provider exception classes that become `ModelProviderUnavailableError`; the identity-sink callback turns only that wrapper into `PinnedInvocationEndpointError`, while Pydantic/parser validation and unknown exceptions stay ordinary node-recoverable failures. |
| Compatibility cannot manufacture persisted identity | Task 4 defines the test-only `CompatibilityResolvedDefinitionLoader`: synthetic graph/release ID 1, code-owned definition version as revision ID, and `definition_content_hash(content)`. It rejects other releases; cached production construction is cleared and proven not to use it. |

The prior second-pass report is retained above as historical context; this section
supersedes its former claims about typed failures, acceptance selection, endpoint
classification, and compatibility construction. No implementation or tests were
run for this planning-only third correction.
