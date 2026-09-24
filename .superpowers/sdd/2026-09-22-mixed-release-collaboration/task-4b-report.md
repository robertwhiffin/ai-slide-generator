# Task 4 slice 4B — runtime root/actor trace

**Status: DONE_WITH_CONCERNS.** Every mandated behaviour is implemented and guarded by a
mutation-verified test. The concerns are scope/boundary facts a reviewer must rule on, not
known defects: slice 4B cannot be delivered without editing two files C-9's file list omits
(`graph/nodes.py`, `graph/routers.py`), and bullet 2's "only the re-review identity test goes
RED" is measurably unachievable as literally worded under this design — the re-fan expression
carries two clauses, so any sabotage of it REDs both. Details in §8.

## 1. Execution identity

- Worktree: `.worktrees/issue-262-plan`, branch `plan/conversation-collaboration-262`.
- Base HEAD verified by the triple check before any edit: `git rev-parse HEAD` =
  `f5ec0bfd56a0dbf96f20878b273039be7300cf96`; `git status --porcelain`, `git diff HEAD` and
  `git diff --cached` all empty. The brief's first value (`60a73be5d`) was superseded as the
  brief itself said; the live value matched the corrected `f5ec0bfd5`.
- Import provenance, proved once from the worktree root with
  `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr`:
  `python 3.11.0`, `databricks-sdk 0.112.0`, `sys.prefix=/Users/robert.whiffin/.pyenv/versions/3.11.0`
  (no `.venv`), `databricks_tellr` →
  `.worktrees/issue-262-plan/packages/databricks-tellr/databricks_tellr/__init__.py`,
  `src.services.agent_runtime` and `src.services.graph.nodes` → this worktree.
  No `pip install`, no `uv`, no `.venv`, no frontend command was run.

## 2. How root/actor were threaded WITHOUT changing `run`'s arity

`AgentRuntime.run(self, agent_key, graph_release_id, payload, assembly_context)` is untouched.
The trace rides the **fourth argument**:

```
invoke_graph  ── resolves the owner ONCE ──►  state["root_session_id"], state["actor_session_id"]
                                                  │
        ┌─────────────────────────────────────────┴───────────────────────────────┐
        │ state nodes (architect, data_analyst, fixer, fix_reviewer, deck_reviewer)│
        │ Send payloads: build_branch_payload  →  builder  →  record  →  re-fan    │
        │ rereview_committed_slides: two explicit parameters, like its release     │
        └─────────────────────────────────────────┬───────────────────────────────┘
                                                  ▼
                       nodes._assembly_context(design_system_active, root, actor)
                                                  ▼
                       AgentAssemblyContext(design_system_active, root, actor)   ← 4th arg
                                                  ▼
                       AgentRuntime._run_resolved  →  AgentInvocationIdentity(..., root, actor)
                                                  ▼
                       identity sink (logs / accumulates; persists nothing)
```

Design decisions, with the reason each was forced:

1. **`AgentAssemblyContext` gained two fields with `""` defaults**, not required fields.
   ~60 call sites outside slice 4B's file list construct it as `AgentAssemblyContext(False)`
   (`test_prompt_assembler.py`, `test_persisted_agent_runtime.py`, `test_agent_runtime.py`,
   `tests/agentic/gates.py`, four integration modules). Required fields would break every one.
   Same reasoning for `AgentInvocationIdentity`, which five constructions in
   `test_persisted_agent_runtime.py` build positionally with exactly five arguments.
2. **Because the defaults exist, the no-blank-trace guarantee is structural.** All ten
   production call sites route through one private helper `nodes._assembly_context`, and
   `TestNoCallSiteMayTraceBlank` asserts on the AST that (a) there are exactly ten
   `get_agent_runtime().run(...)` calls, (b) every fourth argument is an `_assembly_context(...)`
   call with exactly three positional arguments and no keywords, (c) each site's 2nd/3rd
   argument textually references `root_session_id` / `actor_session_id`, and (d)
   `AgentAssemblyContext` is constructed in exactly **one** place in the module. M18 proves the
   guard bites: converting one site back to an inline `AgentAssemblyContext(...)` REDs (a) and (d)
   while #265's arity guard stays green — i.e. #265's guard is structurally blind to this
   regression, which is why the new one exists.
3. **The IDs never reach a model.** `PromptAssembler` reads only `design_system_active` off the
   context, so the context is a pure trace channel. The narrow reviewer/fixer payloads were left
   narrow (M20 guards that). The builder's `Send` payload does carry them, because that payload
   *is* the builder's model payload — it already carried `session_id`, `turn_id` and
   `initiated_by` (a principal), so the disclosure class is unchanged, not widened.
4. **Reads are tolerant, writes are authoritative.** `_assembly_context`, `build_branch_payload`
   and the re-fan use `.get(...) or ""`; `invoke_graph` writes both keys on every invocation,
   *after* `dict(initial)`, so a caller-seeded root/actor is overwritten. Tolerance is deliberate:
   the trace is evidence *about* a mutation, never a precondition for one, and a strict read
   inside `build_reviewer_node` would land in an exception handler that **placeholds the user's
   slide**. It also keeps every out-of-boundary payload-constructing test green.
5. **The owner is resolved by one query, one hop.** New `builder.load_collaboration_root`
   (injectable as `root_loader`, mirroring `pin_loader`) selects
   `root.session_id` joined on `coalesce(requested.parent_session_id, requested.id)` — the same
   single-hop shape C-16 ruled correct — and raises `ConversationSessionNotFoundError` for an
   unknown conversation. A root session resolves to itself.
6. **C-3 ordering preserved and asserted.** `pin_loader` is still the first statement in
   `invoke_graph`; the owner is resolved after it. A null-pinned legacy root therefore raises
   `ConversationPinMissingError` before any node, any writer and before the owner lookup —
   no content write, no mutation event, claim released, marker still queued.
7. **IDs never select the release; the actor's state pin does.** `pin_loader` is called with the
   actor's `session_id`, and the release the runtime resolves is `run`'s second argument.
   Guarded twice (M3 at the runtime, M7b at `invoke_graph`).

## 3. #265's AST guard

`tests/unit/test_graph_nodes.py::TestAgentRuntimeSeam::test_every_production_runtime_call_passes_all_four_pinned_arguments`
is **green and unmodified**: still `len(calls) == 10`, still
`len(call.args) == 4 and call.keywords == []`. I did not edit it, and both insertions the rebase
merged into that file survive — #265's AST check and #262's `DeckMutationContext` /
`MutationActor` imports (the latter still used by three `TestFixerNode`/`TestFixReviewerNode`
boundary tests). Sabotage-verified as live, not vacuous: M19 adds a fifth argument to one
production `run(...)` call and that test REDs (along with 22 others).

## 4. Cause baseline — causes, not counts

Full `tests/unit`, same command and environment throughout.

| | failed | passed | skipped |
|---|---|---|---|
| base `f5ec0bfd5` (measured before any edit) | 6 | 5325→**5609** | 110 |
| after slice 4B | 6 | **5637** | 110 |

The pre-rebase residual in the brief was 6/5325/110; #265's and 4A's integration lifted the
passed count to 5609 and added **no new failure cause**. The six failures are the same six
before and after, with identical causes:

- `test_deploy_autoscaling.py` ×2 — unrelated assertions
  (`Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`,
  `- autoscaling / + provisioned`).
- `test_style_exclusivity_chokepoint.py` ×3 — diverged double:
  `AttributeError: '_FakeSession' object has no attribute 'execute'` at `conversation_pins.py:79`.
- `test_style_exclusivity_persistence_boundary.py` ×1 — fixture class:
  `ConversationGraphReleaseIntegrityError: no active Graph Release`, the raise at
  `conversation_pins.py:83`.

C-10's `test_deck_permission_routes.py::test_create_session_no_profile_params` is **no longer
failing** — slice 4A repaired that fixture as C-10 assigned. Nothing outside the documented set
fails. Net +28 passed = the 28 tests this slice adds.

**Graph integration suites** (`test_architect_reply_is_persisted`, `test_graph_mode_turn`,
`test_graph_orchestration`, `test_sweeper_describe_only`, `test_shared_deck_mutation_attribution`,
`test_conversation_pin_acceptance_postgres`, `test_persisted_graph_runtime_failures_postgres`):
**2 failed / 151 passed**. Both failures were then **reproduced on the pristine base** by
restoring all seven files with `git show HEAD:<path>` and re-running — they are inherited, not
mine, and both are Task-3-era fixture drift of C-11's class:

1. `test_graph_orchestration.py::test_a_position_left_uncommitted_by_a_completed_batch_is_placeheld_by_the_stall_path`
   — `TypeError: only_the_foreman_may_placehold() got an unexpected keyword argument 'mutation'`;
   the test's double predates the `mutation` kwarg, the placeholder never lands, and the turn
   runs to `GraphRecursionError`.
2. `test_persisted_graph_runtime_failures_postgres.py::test_persisted_corruption_escapes_later_node_recovery[deck_reviewer-deck_reviewer-_wrong_hash_revision]`
   — `ValueError: mutation actor pin does not match its persisted pin`, which surfaces an extra
   `info` chat message the assertion does not expect.

Restoration was done from `cp` backups (`/tmp/4b_backup`), never `git checkout <commit> -- paths`;
drift was enumerated from `git diff --name-only HEAD` and every file verified byte-identical to
its backup afterwards, with `git diff --cached` empty.

PostgreSQL: fixtures made their own throwaway databases; `ai_slide_generator` was not migrated,
altered or dropped, and no database I did not create was dropped.

## 5. Clause-to-mutation table

Harness: `/tmp/4b_mutate.py`, results `/tmp/4b_mutation_results.json`, log
`/tmp/4b_mutation_log.txt`. Per **C-27** it asserts the anchor count before patching and refuses
to patch on any count but the expected one (`ANCHOR COUNT n, expected m — REFUSED`). Every
mutation restores all seven files from `cp` backups afterwards. Each run executes
`test_graph_nodes.py test_graph_routers.py test_graph_builder.py` (233 tests), so the table
records not only *that* a clause REDs but *what else* does — the discrimination evidence.

**Anchor counts: 27 of 27 as expected (26 × 1, M17 × 2). Zero mis-aimed anchors. Blanks: zero.**

| # | Mandated clause | Test claiming it | Mutation | Measured |
|---|---|---|---|---|
| M1 | The runtime identity carries a **non-nullable** root/actor (C-3: no nullable runtime identity) | `TestTheTraceChannel::test_the_identity_carries_a_non_nullable_root_and_actor` | `str = ""` → `str \| None = None` on both fields | **RED** ×1 (exactly that test) |
| M2 | The runtime copies the context IDs onto the identity | `test_the_runtime_copies_the_context_ids_onto_the_identity` + every chain test | delete the two `root_session_id=/actor_session_id=` lines in `_run_resolved` | **RED** ×12 |
| M3 | **IDs never select the release** (runtime resolution) | `test_the_ids_never_select_the_release` | resolve with `int(assembly_context.root_session_id or graph_release_id)` | **RED** ×15 |
| M4 | The IDs never reach the model | `test_the_ids_never_reach_the_model` | inject `actor_session_id` into the payload handed to `PromptAssembler.assemble` | **RED** ×2 |
| M5 | `GraphState` declares both keys (undeclared keys are dropped silently) | `TestGraphStateDeclaresTheTrace::test_root_and_actor_are_declared_single_writer_keys` | delete both declarations | **RED** ×2 (also the pre-existing `test_no_node_or_router_reads_a_key_graphstate_does_not_declare` — correct) |
| M6 | `invoke_graph` **overwrites** a caller-seeded root/actor | `test_the_owner_is_resolved_once_and_hostile_ids_are_overwritten` | `state.get("root_session_id") or root_session_id` (hostile value wins) | **RED** ×1 |
| M7a | **C-3**: the pin is loaded *before* the owner is resolved, so a null-pinned legacy root runs no node and no writer | `test_a_null_pinned_legacy_root_runs_no_node_and_resolves_no_owner` | swap the two loader lines | **RED** ×1 |
| M7b | The release is the **actor's** pin, never the root's | `test_the_release_is_the_actors_pin_and_the_root_never_selects_it` | swap, then `pin_loader(..., root_session_id)` | **RED** ×3 (both C-3 tests + the pre-existing `TestInvokeGraphConfig::test_loads_the_persisted_pin_and_overwrites_hostile_initial_state`) |
| M8 | `build_branch_payload` **declares** root/actor for the fanned branch | `test_the_fanned_branch_payload_declares_the_root_and_the_actor` | delete both payload keys | **RED** ×2 |
| M9a | **Bullet 2 sabotage** as literally worded: root/actor/**release** removed from the reviewer's `dict(record)` re-fan | `test_the_refanned_build_review_records_root_actor_and_the_actors_release` | strip all three keys from the `Send` payload | **RED** ×9 — the re-review identity test, the hostile-record test, the end-to-end walk, and **6 pre-existing** tests that need `payload["graph_release_id"]` |
| M9b | The re-fan **re-declares** provenance from state rather than trusting the record | `test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record` | delete the three re-declaration lines | **RED** ×2 (that test + the pre-existing `TestBuildReviewerRefan::test_one_send_per_unreviewed_position_with_the_builder_s_own_record`) |
| M9c | Same clause, narrowed to root/actor | as M9b | delete only the root/actor re-declaration lines | **RED** ×1 (exactly the hostile-record test; the identity test stays green because `dict(record)` still carries correct values — see §8) |
| M9d | *(mis-aimed, reported per C-27)* | — | filter root/actor out of the `**dict(record)` spread only | **REDs nothing** — the explicit re-declaration two lines below restores them. Anchor count was correct (1); the *semantics* were wrong. Re-aimed as M9e. |
| M9e | **Bullet 2 sabotage, re-aimed**: the reviewer *receives* no root/actor, release intact | `test_the_refanned_build_review_records_root_actor_and_the_actors_release` | filter from the spread **and** delete the re-declarations | **RED** ×3 — the re-review identity test, the hostile-record test, the end-to-end walk. **Zero pre-existing tests; zero other node's identity test.** |
| M10 | The builder's **unsafe-output retry** carries the same identity | `test_the_builder_and_its_unsafe_output_retry_record_one_identity` | blank the retry site's context (`_assembly_context(dsa, "", "")`) | **RED** ×3 (incl. the AST guard) |
| M11 | The fixer's **retry** carries the same identity | `test_the_fixer_and_its_unsafe_output_retry_record_one_identity` | blank the fixer retry site | **RED** ×2 |
| M12 | The **fix reviewer's** record carries root/actor/release | `test_the_fix_reviewer_records_root_actor_and_the_actors_release` | blank that site | **RED** ×3 |
| M13 | The **deck reviewer** carries root/actor/release | `test_the_deck_reviewer_records_root_actor_and_the_actors_release` | blank that site | **RED** ×3 |
| M14 | The **architect** carries root/actor/release | `test_the_architect_records_root_actor_and_the_actors_release` | blank that site | **RED** ×4 |
| M15 | **`rereview_committed_slides`** traces the root/actor it is given | `test_the_committed_slide_rereview_records_root_actor_and_the_release` | blank its context | **RED** ×4 |
| M16 | The architect **hands** the re-review pass state's root/actor | `test_the_architect_hands_the_re_review_pass_its_root_and_actor` | pass `"", ""` at the call site | **RED** ×1 — *this clause was a blank on the first pass; see §6* |
| M17 | The downstream **mutation event's** actor is the actor session (AC4: trace and evidence agree) | `test_the_persisted_mutation_event_agrees_with_the_runtime_trace` | `_deck_mutation_context(payload["root_session_id"], ...)` (2 anchors, both patched) | **RED** ×4 |
| M18 | **Guard check**: a call site that builds its context inline is caught | `TestNoCallSiteMayTraceBlank` (a) and (d) | one `_assembly_context(...)` → inline `AgentAssemblyContext(...)` | **RED** ×2; #265's arity guard stays **green** |
| M19 | **Guard check (#265, inherited)**: `run(...)` arity still pinned at four/zero | `test_every_production_runtime_call_passes_all_four_pinned_arguments` | add a fifth positional argument to one `run(...)` | **RED** ×23 — the inherited guard is live, not vacuous |
| M20 | A **narrow** reviewer payload never carries a session ID | `test_no_narrow_payload_prompt_carries_a_session_id` | add root/actor to `review_payload` | **RED** ×1 |
| M21 | The default loader follows the **one hop** to the owner | `test_the_default_loader_resolves_a_contributor_to_its_owner` | `coalesce(parent, id)` → `requested.id` | **RED** ×1 |
| M22 | The default loader **refuses** an unknown conversation | `test_the_default_loader_refuses_an_unknown_conversation` | `raise` → `return session_id` | **RED** ×1 |

Plus the whole-turn assertion (`test_the_whole_turn_records_one_immutable_root_actor_and_release`)
which walks every handoff bullet 1 names in one contributor turn — architect → `build_branch_payload`
→ builder (unsafe output + retry) → re-fan `dict(record)` → build_reviewer (objective finding)
→ fixer → fix_reviewer → deck_reviewer → `rereview_committed_slides` — and REDs under 9 of the 27
mutations.

**Blank count: 0.** No clause in bullets 1, 2 or the bullet-7 runtime-identity half is recorded
as guarded by a mutation that REDs nothing.

## 6. The blank I hit, and the re-aim (C-27)

**M16 REDed nothing on the first pass.** Its anchor count was 1 and its aim was right; the
*coverage* was missing. `test_the_whole_turn...` calls `rereview_committed_slides` directly with
explicit arguments, so nothing exercised `architect_node`'s own deck-level branch — the only
place that can supply the pass with state's root/actor. Following the brief's instruction to
suspect my own aim first, I added
`test_the_architect_hands_the_re_review_pass_its_root_and_actor`, which persists an old spec via
`write_deck_level_columns`, seeds a committed row, and returns a retargeted spec so
`classify_spec_change` → `deck_level` drives the pass from inside the node. M16 then REDs exactly
that test.

**M9d also REDed nothing, and that one is more interesting**: its anchor count was correct, so
C-27's assertion could not catch it. The patch filtered root/actor out of the `**dict(record)`
spread while the explicit re-declaration two lines below silently restored them. Recorded as
evidence that an anchor-count assertion is necessary but **not sufficient**: a mutation must also
be confirmed to change behaviour, or "REDs nothing" gets misread as a coverage gap. Re-aimed as
M9e, which removes both sources.

## 7. Files changed

| File | Change |
|---|---|
| `src/services/agent_runtime_identity.py` | `AgentInvocationIdentity` gains `root_session_id`, `actor_session_id` (`str`, defaulted) |
| `src/services/agent_runtime.py` | `AgentAssemblyContext` gains the same two; `_run_resolved` maps context → identity |
| `src/services/graph/state.py` | `GraphState` declares both keys, single-writer, no reducer, not turn-scoped |
| `src/services/graph/builder.py` | new `load_collaboration_root`; `root_loader` parameter; both keys written after `dict(initial)`; pin-before-owner ordering documented |
| `src/services/graph/nodes.py` | new `_assembly_context` (sole constructor); all 10 call sites; `build_branch_payload` declares both; `rereview_committed_slides` gains the two parameters and the architect passes them |
| `src/services/graph/routers.py` | the build-reviewer re-fan re-declares release/root/actor from state |
| `tests/unit/test_graph_nodes.py` | +28 tests in 5 classes; `_branch_payload` carries both keys |

Not touched: `src/services/collaboration_history.py` and everything else slice 4A owns;
`frontend/src/api/agentDefinitions.ts` (`CUSTOM_ANCHORS` order untouched); `tests/unit/conftest_graph.py`;
`tests/unit/test_graph_routers.py`; `tests/unit/test_graph_builder.py`;
`tests/unit/test_graph_state.py`; `test_persisted_agent_runtime.py`; `test_prompt_assembler.py`.

## 8. Concerns for the reviewer

1. **C-9's file list for slice 4B is incomplete, and I exceeded it by two files.** Bullets 1 and
   2 name `foreman_router`'s `Send`, `build_branch_payload`, the builder's retry payload, the
   build-reviewer `dict(record)` re-fan, the fixer retry, the fix-reviewer record and
   `rereview_committed_slides`. Six of those seven live in `src/services/graph/nodes.py` and the
   re-fan lives in `src/services/graph/routers.py` — **neither file appears in C-9's "Modify"
   list for either slice**, and neither appears in the plan's Task 4 Files block. There is no way
   to satisfy bullets 1–2 without them. Both are disjoint from 4A's ownership and from #265's
   diff, so the edit collides with nothing; the boundary text is what needs a correction. Same
   class of omission as C-18.
2. **All slice-4B tests went into `tests/unit/test_graph_nodes.py`, including `invoke_graph` and
   router tests**, because it is the only test file C-9 grants 4B. `TestInvokeGraphResolvesTheTrace`
   would more naturally live in `test_graph_builder.py` and the two re-fan tests in
   `test_graph_routers.py`. I kept the boundary and flagged the placement rather than editing
   files I was not given.
3. **Bullet 2's "only the re-review identity test must go RED" is not literally achievable here,
   and the measurement says why.** Two clauses share the one re-fan expression: the reviewer must
   *receive* provenance, and the re-fan must *re-declare* it from state instead of trusting a
   record that round-trips the checkpointer. Any sabotage of that expression REDs both tests
   (M9e: 3 REDs, all three re-fan/trace tests, zero pre-existing). The literal wording (M9a) is
   worse, not better: stripping the release too REDs six pre-existing tests. What bullet 2 is
   really protecting — that the sabotage does not RED the builder, fixer, fix-reviewer,
   deck-reviewer, architect or `rereview` identity tests — **holds exactly** under M9a, M9c and M9e.
   If the intent was that the re-fan be the *sole* source of the reviewer's provenance, that
   requires `build_branch_payload` **not** to declare it, which bullet 2 also mandates; the two
   requirements cannot both be literally satisfied.
4. **The two new dataclass fields are defaulted, not required.** That is forced by ~60
   out-of-boundary construction sites (§2.1) and it means a *future* call site could trace blank.
   The mitigation is the AST guard, sabotage-verified by M18. A reviewer who wants required
   fields should expect a ~10-file test-only diff across #265's and the agentic suites.
5. **`LoggingAgentInvocationIdentitySink` logs `**identity.__dict__`**, so both session IDs now
   appear in the `persisted_agent_invocation` log line. That follows from the plan putting them
   on `AgentInvocationIdentity` and from "extend the identity sink only"; the sink still persists
   nothing and no row the history API reads changed. Flagged because it is a disclosure surface
   decision, not an accident.
6. **`test_graph_builder.py`'s `fake_graph` fixture cannot model a second query.** Its
   `_PinnedSession.scalar()` answers every statement with a pin row, so under that stub
   `state["root_session_id"]` receives that row object rather than a session-ID string. No
   assertion there reads it and all 15 of its `invoke_graph` tests stay green, but the fixture is
   now lying to a reader. Repairing it belongs to whoever owns that file; my own tests inject a
   real `root_loader` or exercise the default loader against the real SQLite database
   (M21/M22 guard the query itself).
7. **Two inherited integration failures** (§4) are Task-3-era fixture drift, reproduced on the
   pristine base. They are unowned by any open slice and should be recorded as C-11-class causes.
8. **Not done, and out of scope by C-9**: no MLflow or Lakebase trace was added (bullet 2 says
   identity sink only), and no PostgreSQL integration test for the runtime trace was added —
   bullet 1's target is the identity sink plus the downstream event, both of which are asserted
   against a real database in `test_the_persisted_mutation_event_agrees_with_the_runtime_trace`.

## 9. Test summary

- `tests/unit`: **6 failed / 5637 passed / 110 skipped** — the same six inherited causes as the
  base, byte-for-byte the documented set.
- Slice-4B tests: **28 passed** (`TestTheTraceChannel` 5, `TestGraphStateDeclaresTheTrace` 1,
  `TestInvokeGraphResolvesTheTrace` 5, `TestRuntimeRootActorTrace` 14, `TestNoCallSiteMayTraceBlank` 3).
- Graph/runtime focus (`test_graph_nodes`, `test_graph_routers`, `test_graph_builder`,
  `test_graph_state`, `test_agent_runtime`, `test_persisted_agent_runtime`,
  `test_deck_level_spec_change`, `test_prompt_assembler`): **506 passed, 0 failed**.
- Graph integration: **151 passed / 2 failed**, both inherited and reproduced at base.
- Mutations: **27 run, 27 anchor counts as expected, 26 RED, 1 mis-aim re-aimed, 0 blanks.**
