# Task 7 report: release identity through the shipped graph-mode seam, across three releases (AC8, AC4, AC5)

**Status:** DONE_WITH_CONCERNS. The test is test-only and GREEN, and `src/` is unchanged. **One real production defect was found** during the S17 mutation work. It is reported below and not fixed.

## Commits
TASK_BASE is `693df109e`. HEAD moved to `eb3daa898` during the task: that is the controller's Task 6 review docs commit.

1. `b03f76eb5` `test: prove pinned release identity through graph state, fan-out and traces across three releases (#271)`. It touches:
   - `tests/integration/test_graph_lifecycle_runtime_postgres.py` (new);
   - `.github/workflows/test.yml` (enrolled in `integration-graph` after `test_graph_lifecycle_acceptance_postgres.py`);
   - `tests/unit/test_ci_collects_integration_tests.py` (new pin `test_graph_lifecycle_runtime_is_collected_by_integration_graph`).
2. `fb5d40caa` `test: label bundle-stage turn failures S17 and fail a turn on any error event (#271 Task 7)`. It touches the new file only.
3. This report, force-added. The mutation runner is copied to `reports/t271-7-run_mut.py` for the reviewer.

## What the file does
- Both tests run `lifecycle_journey.run_to("S16")`, with the tripwire still armed. They then drive one first graph turn per conversation through `ChatService.send_message_streaming(session_id, "USE AGENT MODE build a deck", engine_mode="graph")`:
  - `old-root` on v1 (id 1);
  - `new-root` on v2 (id 3), which is non-active;
  - `post-rollback-root` on v3 (id 4), which restores v1.
- **Seam.** This is `graph_chat_env`'s recipe adapted to the journey's PostgreSQL factory:
  - `get_graph` is set to a compiled graph over `SqlAlchemyCheckpointSaver(factory)`;
  - `builder.get_session_local` and the `nodes`, `slide_repository` and `deck_level_writer` `get_db_session` accessors point at the factory;
  - settings, the naming model, `get_user_client` and `ChatDatabricks` are stubbed;
  - `_build_agent_for_session` is booby-trapped;
  - `SessionManager` and `src.core.database.get_db_session` are already bound by the journey.
- **Runtime.** The runtime is production's `AgentRuntime(PersistedGraphReleaseLoader(factory), adapter, LoggingAgentInvocationIdentitySink(logging.getLogger("src.services.agent_runtime")))`, patched in at `src.services.graph.nodes.get_agent_runtime`. The sink's records are captured with `caplog`.
- **Model boundary (C8).** The adapter is `_ToolFreeOrderedAdapter`:
  - It uses the ordered A1 deque (the `_first_turn_outputs()` roles) and checks the role and the bound schema's class.
  - It delegates to a **real `DatabricksModelAdapter`**. That adapter's `model_factory` returns a `ChatModel` double:
    - `with_structured_output(schema)` answers `schema.model_validate(output)`, and adds `diagnostic_notes` when the bound composed schema offers it;
    - `bind_tools(...)`, with any list including `[]`, records the call and raises;
    - any other attribute read also records and raises.
  - So AC5 is asserted on **every** model call of every turn (30 calls), not on one turn per role. This is a superset of C8.2.
- **Seeding.** Before each turn, `builder.invoke_graph` is wrapped (it is lazily imported by `_send_message_streaming_graph`) to seed a **different** release: `old-root`←3, `new-root`←4, `post-rollback-root`←1. The test asserts that the seed reached the graph input exactly (`{"architect_message", "graph_release_id": seed}`).
- **`Send` recording.** `routers.Send` is recorded, as in the pin acceptance file (`:426-432`).
- **Bounded waits.** Each turn is consumed on a context-copied thread with `join(120 s)` and an assertion that the thread is no longer alive. There is no other wait.
- **S13 `[#261]`**, test `test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces`. For each turn:
  - There is no ERROR event, and the last event is COMPLETE.
  - **State:** the final checkpoint's `graph_release_id` equals the pin, not the seed.
  - **Fan-out:** `Send` targets are exactly `{builder, build_reviewer}`, each payload list is `[pin]`, and the adapter roles equal `A1_ROLES`.
  - **Resolution:** the records' `(agent_key, graph_release_id, graph_version, revision_id, content_hash)` equal, exactly and in A1 order, `(role, pin, version, *_release_mapping(factory, pin)[role])`. For v3, the revision ids equal v1's and `graph_version == 3`. It also asserts `mappings[v3] == mappings[v1]`, and that v2 differs from v1 in exactly `{architect, builder, fixer}`.
  - **Log contract:**
    - the extras (`vars(record)` minus `STANDARD_LOG_RECORD_ATTRS`) are exactly the 8-field literal success set;
    - `outcome` is `success` and `error_class` is None;
    - `type(additional_field_names) is list`, equal to `["diagnostic_notes"]` for the v2 builder only and `[]` otherwise;
    - `rendered_record` contains none of the 14 prose strings (the fake outputs' free-text leaves plus the diagnostic note) and none of the 7 session ids.
  - **No identifiers to the model:** no prompt contains any of the 7 session ids, `ADMIN`, `OWNER`, `CONTRIBUTOR`, the checkpoint's `turn_id`, or any of the six key names.
  - **No tools:** `tool_bindings == []`; the double's method calls are exactly `with_structured_output` × 30; the bound schemas and the prompts reached the double 1:1 with the runtime's calls; the deque is empty.
  - **No fabricated ids:** the ids across all 30 records are exactly `{1, 3, 4}`, and the (id, version) pairs are exactly `{(1,1), (3,2), (4,3)}`. `tripwire.reads == []`.
- **S17 `[#265]`**, test `test_every_readable_release_executes_with_its_own_bundles_after_it_stops_being_active`. Its turns are driven under the S17 label, so a turn that cannot execute a historical bundle is blamed on S17.
  - The release rows are `[(1,1,F),(3,2,F),(4,3,T)]`.
  - For every one of the 10 `agent_definition_revision` rows, per C32:
    - `PromptAssembler().resolve_bundle(content.protected_assembly)` returns the exact (version, digest);
    - `AgentSchemaRegistry().identity_for(role, v) == SchemaContractIdentity(role, v, persisted digest)`;
    - `compose(role, identity, overlay)` succeeds.
  - v2's architect revision is (protected 2, schema 1) with the literal `ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST`. v2's builder revision is (protected 1, schema 2) with the literal `BUILDER_SCHEMA_CONTRACT_V2_DIGEST`. Every v3 revision is (1, 1).
  - The `new-root` builder bound the composed schema twice, both times with `diagnostic_notes` in `model_fields`, and every `new-root` architect prompt contains `CUSTOM_BLOCK_TEXT`.
  - The `post-rollback-root` and `old-root` builders bound schemas without `diagnostic_notes`, and their architect prompts do not contain the custom block.
- **Turn driver for Task 8:** `open_turn_driver(journey, monkeypatch, caplog)` returns a `GraphTurnDriver`. Its `.drive(session_id, seed_release_id=...)` returns a `TurnRecord` with these fields: `events`, `calls`, `records`, `sends`, `initial`, `checkpoint`, `pin`, `seeded_release_id`. Also exported: `_run_pinned_turns(..., driving=Stage)`.

## Gates
Env: `PYTHONPATH=tree:tree/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t271-7.sqlite`, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`. One file per invocation, with `-rs -m "not live"`. There were zero skips in every run.

| Gate | Result |
|---|---|
| `test_graph_lifecycle_runtime_postgres.py` (new) | 2 passed (≈7 s) |
| `test_graph_lifecycle_acceptance_postgres.py` (Task 6) | 1 passed |
| `test_conversation_pin_acceptance_postgres.py` (unchanged) | 1 passed |
| `test_persisted_graph_runtime_failures_postgres.py` (unchanged) | 7 passed |
| `test_graph_mode_turn.py` | 39 passed |
| `tests/unit/test_ci_collects_integration_tests.py` | 24 passed |
| `tests/unit/test_graph_lifecycle_stage_attribution.py` | 17 passed (Task 6's fix round is in progress in this tree) |
| Full unit (`-n 4`, `DATABASE_URL` unset as in Task 6; UTC 18:38:14 to 18:41:21, far from midnight) | 2 failed / 7222 passed / 110 skipped. The 2 failures are exactly the `test_deploy_autoscaling` pair (the baseline cause). |
| ruff check (both touched `.py` files), ruff format (new file) | clean |

- `.venv` is absent.
- `ai_slide_generator` was never touched.
- `tellr_int_*`: 6 databases before and 5 after. The missing one, `232440eafb834805`, was not mine: it was dropped by its owner (a concurrent agent). None of my runs leaked a database, and I dropped nothing.

## Mutation table
- All mutations ran in my own worktree, `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-7-mut`, detached at `fb5d40caa`. It has since been removed. The shared worktree's `src/` was never touched.
- Each mutation asserted that its anchor occurred exactly once and carried a `T271M*` marker. After each run the file was restored with `git checkout fb5d40caa -- <file>`, and `git diff --quiet fb5d40caa -- <file>` was asserted.
- GREEN in the mutation tree before starting: 2 passed.

| # | Seam mutated | Result (first label) |
|---|---|---|
| M1 | **Plan REVIEWER sabotage**: drop `"graph_version"` from `_LOGGED_IDENTITY_FIELDS` | RED 1/2: `[#261] S13 … AttributeError: 'LogRecord' object has no attribute 'graph_version'` |
| M2 | **C8 reviewer sabotage**: `bind_structured_output_model` calls `model.bind_tools([])` | RED 2/2: `[#261] S13 … _ToolBindingAttempted: graph runtime bound tools: []` and `[#265] S17 … _ToolBindingAttempted` |
| M3 | `invoke_graph` lets a seeded `graph_release_id` win over the pin (`builder.py` `state.update`) | RED 2/2, with `GraphRecursionError` (10007 steps, about 48 s, inside the 120 s bound) |
| M4 | `build_reviewer` re-fan takes `record.get("graph_release_id")` instead of `state[...]` (`routers.py`) | **GREEN, and expected.** On an honest turn the record already carries the pin, so this re-declaration only matters for a hostile record. That case is owned by `test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record`. Replaced by M4b. |
| M4b | `build_branch_payload` sends `graph_release_id: 1` | RED 2/2: `[#261] S13 … AssertionError: new-root (pin id 3, v2)` / `assert [1] == [3]` (the fan-out assertion) |
| M5 | Success record adds an `actor` extra (the actor session id) | RED 1/2: `[#261] S13 … ('old-root (pin id 1, v1)', ['actor', …])` (the allow-list) |
| M6 | `additional_field_names` carries values, not names | RED 1/2: `[#261] S13 … ('new-root (pin id 3, v2)', 'builder', ["{'diagnostic_notes': ('Lifecycle diagnostic prose…',)}"])` |
| M7 | Architect payload gains `"conversation_ref": session_id` | RED 1/2: `[#261] S13 … ('old-root (pin id 1, v1)', 'architect', ['old-root'])` |
| M8 | Loader sets `graph_version=release.id` (id ≠ version) | RED 1/2: `[#261] S13 … AssertionError: new-root (pin id 3, v2)` (the identities) |
| M9 | Drop v2 from `_default_bundles()` | RED 2/2, but upstream at `[#265] S05 assembly` (the admin upgrade 422s). Replaced by M9b for S17. |
| M9b | The published `AgentRuntime.run` drops every protected-v2 bundle from its instance `_bundles` (C32: per instance) | RED 2/2: `[#261] S13 …` and `[#265] S17 historical bundles … TypeError: super(type, obj)…` (see the **Defect**) |
| M10 | The builder's v2 schema bundle has no optional fields | RED 2/2, upstream at `[#264] S04 overlay` (422). Replaced by M10b. |
| M10b | The published path binds `composed.canonical_model`, not the composed schema | RED 2/2: `[#261] S13 … ('new-root (pin id 3, v2)', 'builder', [])` and `[#265] S17 … assert False` (the `diagnostic_notes` check) |
| M11 | Architect payload gains `"initiated_by"` | RED 1/2: `[#261] S13 … ['lifecycle-owner@example.com', 'initiated_by']` |
| CI | Remove the workflow line | RED 2/24 (the new pin plus `test_every_integration_file_is_collected_or_excluded_with_reason`) |

**Not run:** the plan's CONTROLLER sabotage (`builder.py:345` set to the active release id; predicted `[#261] S13` on old-root). It is the controller's, and M3, M4b and M8 are different anchors.

## Defect found (production; not fixed; routed to the controller for C22 triage)
**A persisted-runtime failure raised inside a compiled-graph node reaches the chat seam as `TypeError`, not as the typed error. So the safe `pinned_graph_configuration_unavailable` event is never emitted for it.**

- **Cause.**
  - `PersistedConfigurationUnavailableError` and `PinnedInvocationEndpointError` are `@dataclass(frozen=True, slots=True)` subclasses of `RuntimeError` (`src/services/persisted_graph_release.py:39-68`).
  - When such an exception propagates through any `@contextlib.contextmanager`, `_GeneratorContextManager.__exit__` takes its `except RuntimeError` branch and executes `exc.__traceback__ = traceback`.
  - The frozen/slots dataclass `__setattr__` then raises `TypeError: super(type, obj): obj must be an instance or subtype of type`.
  - LangGraph runs every node inside `set_config_context(...)`, a context manager (`langgraph/_internal/_runnable.py:683`). So every such error raised by a node (for example `nodes.py:1484`, the architect's `get_agent_runtime().run`) becomes a `TypeError`.
- **Minimal repro** (Python 3.11.0, no database):

  ```python
  import contextlib
  from src.services.persisted_graph_release import PersistedConfigurationUnavailableError
  @contextlib.contextmanager
  def cm(): yield
  with cm(): raise PersistedConfigurationUnavailableError(code="protected_bundle_unavailable")
  # -> TypeError: super(type, obj): obj must be an instance or subtype of type
  ```

  - `PinnedInvocationEndpointError` behaves the same way.
  - `GraphReleaseNotFoundError`, which is a plain class, does not.
- **Through the shipped seam** (M9b): `_send_message_streaming_graph.run_graph`'s `except (PersistedRuntimeError, …)` at `chat_service.py:1914` misses. The generic `except Exception` at `:1952` emits `ERROR` with `error="super(type, obj): …"` and logs `Graph turn failed` with `exc_info`. Then `:2030` re-raises the `TypeError`.
- **Consequences:**
  - the safe envelope and its identity-safe log are lost for bundle-unavailable, invalid-definition, lakebase-unavailable and removed-endpoint failures mid-turn;
  - the public error text leaks an internal message;
  - any caller matching `PersistedRuntimeError`, such as the sweeper and job queue, sees `TypeError`.
- **Why it is green today.** `test_persisted_graph_runtime_failures_postgres.py` (`_safe_event_from_graph_seam`, `:246-258`) replaces `invoke_graph` with a function that raises directly. `test_graph_mode_turn.py`'s envelope tests only raise pin errors from `invoke_graph` before any node runs. No test raises one of these errors from inside a compiled-graph node.
- **Suggested owner:** #261 (explicit pinned failures) or #260 (the error types), via Task 8's C24/C47 scope, which already edits this envelope.
- **Suggested fix:** it is not mine to apply. Options:
  - drop `frozen`/`slots` on the two exception dataclasses;
  - or define a `__setattr__` that permits the dunder attributes `__traceback__`, `__cause__`, `__context__` and `__suppress_context__`.
- **A regression test Task 8 could add:** my M9b recipe, dropping the v2 protected bundle from the turn runtime's `_prompt_assembler._bundles` and driving `new-root`, then asserting the safe event and `PersistedConfigurationUnavailableError` from `send_message_streaming`.

## Deviations
1. **C8 superset.** The real `DatabricksModelAdapter` with the raising `ChatModel` double drives **all** turns and roles (30 calls), not "one turn per role" with `DeterministicFakeModelAdapter` elsewhere. That keeps determinism, because the ordered deque still supplies the outputs, and strengthens AC5.
2. **The stage helper.** `journey.in_stage(stage)` has not landed (the Task 6 fix round is in progress). The file routes its stage bodies through `_in_stage(journey, stage)`, which today returns Task 6's `stage(current)`. The switch is the one-line body change `return journey.in_stage(current)`. No Task 7 body calls `journey.call`, so nothing touches `journey._current`.
3. **S17 re-drives the turns.** Each test runs the journey and the three turns itself (≈3.5 s each), rather than sharing state across tests. The S17 test labels its turns S17.
4. **"Prose" is defined.** A prose string is a string leaf with whitespace, markup or `://`. Role vocabulary such as `build`, `clean` and `surfaced` is excluded; `build` is a substring of the allow-listed `agent_key` `builder`. 14 strings are checked.
5. **Imports.** `A1_ROLES`, `_first_turn_outputs` and `_release_mapping` come from the pin acceptance file, by name. Nothing comes from the workbench file.
6. **Ordering (C46).** The progress ruling is 6 → 7 → 8, so Task 8's GREEN step must re-run this file after it edits `chat_service.py`.

## Concerns
- **The defect above.** It needs C22 triage before routing. It also means C24/C47's "safe event" work in Task 8 will not be observable for node-raised errors until it is fixed.
- **Session-count assertions.** The turns add chat messages and deck rows to `old-root`, `new-root` and `post-rollback-root`. They run after S12b and S16 have asserted, and no journey stage runs after them, because S18 is not run in this file. So Task 6's exact counts are undisturbed.
- **M3's runtime.** M3 (seed wins) produced a 10007-step graph recursion lasting about 48 s. That is a failure mode, not a hang, and it stays inside the 120 s bound. A future seam change that recurses could still approach the bound.
