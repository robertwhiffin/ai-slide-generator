# Task 3 review — `AgentRuntime.run_candidate` and the deterministic fake adapter (#267)

Reviewer: independent task reviewer. Range `dec69b365..84da2c71d` (impl `fac5571f8`). Temp worktree `rev-267-3` at `84da2c71d`, pytest run from inside it (`src` import confirmed to resolve to `rev-267-3/src/services/agent_runtime.py`). `test ! -e .venv` held before and after. No installs, no commits, dev DB untouched.

## Spec Compliance: ❌ (two controller rulings not yet implemented; everything else ✅)

| Clause | Verdict | Evidence |
|---|---|---|
| C12 checks in order: role → content role → hash; `ValueError("candidate_hash does not match candidate_content")` | ✅ | `agent_runtime.py:722-730`; tests `:981`, `:997`, `:1008` |
| C12/C31 delegate to `_run_resolved`, never `run`/loader/binding helper/`saved_model_configuration`/`_write_locked_content` | ✅ | AST test `test_run_candidate_delegates_to_run_resolved_and_never_to_run` |
| `run`, `AgentRuntime.__init__`, `get_agent_runtime`, `saved_model_configuration`, `_supplied_output_keys` unchanged | ✅ | My AST dump comparison base vs HEAD: all identical. `bind_structured_output_model` identical except its docstring. `DatabricksModelAdapter.invoke` differs only by forwarding `transport_options=self._transport_options` (None in production, so `**(None or {})` is the base kwargs) |
| Exactly one `with_structured_output(` in `src` | ✅ | `grep -rn` finds only `agent_runtime.py:436` |
| #266 probe classification and bounds untouched | ✅ | `model_endpoint_probe.py` absent from diff; `test_model_endpoint_probe.py` and `test_probe_failure_contract_client_join.py` green |
| Graph nodes untouched | ✅ | `src/services/graph` absent from diff; `test_graph_nodes.py` (incl. `TestNoRolesModelPromptCarriesSessionIdentifiers`) green |
| C13 v2 overlay candidate runs now; v1 overlay guard kept → `assembly_error` | ✅ | tests `:1082`, `:1097` |
| C15/C34 private keyword-only `_raw_output_observer`, called immediately before `validate_output`; `run` passes none | ✅ | `:868-875`; but see I-3 (the `run` side is only pinned at `run`'s call site) |
| C16/C33 status taxonomy; `error_detail` code/class only | ✅ with ⚠️ | `_classify_candidate_failure` `:620-637`; ⚠️ see I-4, M-2, M-3 |
| C16 "logged with its traceback" for `unexpected_error` | ❌ superseded | Controller ruling: class name only. `exc_info=error` at `:761` still present (I-2) |
| C26 fake in `tests/fixtures/`, `FAKE_OUTPUTS` single table, modes incl. pause | ✅ | `tests/fixtures/deterministic_model_adapter.py`; both suites import it |
| C27 sentinels `-1` in `agent_runtime.py`, not `persisted_graph_release.py`; `run(-1)` still raises `GraphReleaseNotFoundError` | ✅ | `:574-576`; `test_persisted_graph_release.py::test_the_candidate_sentinel_release_id_never_resolves_through_run` |
| C27 identity `(-1,-1,key,-1,hash,"","")` reaches the **production logging** sink | ❌ | Controller ruling R1 REJECTED; `get_agent_test_runtime` still wires `LoggingAgentInvocationIdentitySink` (`:933`) and tests pin it (I-1) |
| C33 `transport_options` kw-only, default None; `get_agent_test_runtime` 120 s / 0 retries, `lru_cache`d | ✅ | `:447-455`, `:910-935`; kwargs tests `:1428`, `:1438`, `:1467` |
| C33 call-site guards for `run_candidate` / `get_agent_test_runtime`; C31 workbench forbids binding names | ✅ with ⚠️ | `:1359-1402`; ⚠️ M-4 |
| R2 session ids refused, not stripped | ✅ | `:731-734`; my sabotage S1/S2 both RED |

## Strengths
- The production path is genuinely untouched: `run`/`get_agent_runtime` are AST-identical, and the adapter's `None` default is byte-equivalent kwargs, pinned by the unedited `:645-677` test plus the new "still hands no transport options" test.
- Caller-contract violations raise before any sink or adapter touch, with `adapter.calls == [] and sink.calls == []` asserted on every refusal test.
- The prompt-parity test is honest: it runs real `run` (via a static loader) against real `run_candidate` with separate fake adapters and compares prompt bytes, configuration, JSON schema and diagnostics across 7 roles × design-system × v1/v2 assembly. Both sides share `_run_resolved` — by design (C12) — so the test is not vacuous for what it is meant to catch: any transformation `run_candidate` applies to payload or context. My context-flip mutation turned 28/28 RED; the implementer's payload mutation also RED 28.
- `OutputParserException` import is lazy and guarded; `langchain_core` is installed and the class subclasses `ValueError`, so ordering after the `PersistedConfigurationUnavailableError` check is safe.
- The fake adapter returns the *composed* schema instance on success, so it cannot let an unvalidated object slip through; `invalid_optional_field` deliberately bypasses the bound schema so only `validate_output` can reject it.
- The implementer's 23-row mutation table is thorough and every row is anchored and restored.

## Issues

### Critical
None.

### Important

**I-1 — Candidate runs still log fabricated `-1` identities to the production sink (ruling R1 not implemented).**
- `src/services/agent_runtime.py:933` (`get_agent_test_runtime` wires `LoggingAgentInvocationIdentitySink`); `_run_resolved` `:878` always calls `self._identity_sink.invoke`; pinned by `tests/unit/test_agent_runtime.py:1455` and `tests/unit/test_persisted_agent_runtime.py:1928`, `:1973`, which assert the `persisted_agent_invocation` record *is* emitted with sentinels.
- Why: the controller ruled that fabricated release/revision ids must not enter the production invocation log (standing rule; #266's probe logs nothing to it). Anything aggregating `persisted_agent_invocation` by release gets a `-1` bucket.
- Fix (preferred, structural): give `_run_resolved` a second private keyword-only override, e.g. `_identity_sink: AgentInvocationIdentitySink | None = None`, and have `run_candidate` always pass a non-recording pass-through sink (`callback()` only — not `RecordingAgentInvocationIdentitySink`, which on the `lru_cache`d test runtime would grow without bound). `run` keeps passing nothing; `test_production_run_passes_no_raw_output_observer` (`keywords == []`) already pins that. Then `run_candidate` emits its own single record, e.g. `logger.info("agent_candidate_run", extra={"agent_key", "status", "error_code", "error_class"})` where `error_code` is the code part of `error_detail` (no exception text). Alternative (weaker): leave `_run_resolved` alone and build `get_agent_test_runtime` with a pass-through sink; this leaves `run_candidate` on a production runtime still logging sentinels, guarded only by the call-site test.
- Tests to change/add: replace the two persisted-runtime sentinel-record tests with "a candidate run on a `LoggingAgentInvocationIdentitySink` runtime emits zero `persisted_agent_invocation` records and exactly one candidate record with the exact field set"; change `:1455`; keep the sentinel identity only where it is still observable (`PinnedInvocationEndpointError.graph_release_id == -1`, already tested at `:1191`). C27's recording-sink identity assertion is superseded by the ruling. Sabotage: route `run_candidate` back through `self._identity_sink` → RED on the zero-record test.

**I-2 — `unexpected_error` is logged with its traceback.**
- `src/services/agent_runtime.py:757-762` (`exc_info=error`).
- Why: provider exception text can echo prompt or model content; the user's decision is that no model prose reaches the application log. `error_detail` is clean, but the log is not.
- Fix: drop `exc_info`; log class name only (fold into I-1's single candidate record). Add a caplog test: `_Boom` raising `RuntimeError("provider text https://secret-host/token=abc")`, capture at DEBUG on the root logger, assert `"secret-host"` appears in no record's `getMessage()`, `exc_text`, `exc_info`, or `vars(record)`. Sabotage: restore `exc_info=error` → RED.

**I-3 — No test pins that production `run` logs no raw output; the new observer seam can leak model output for every production call with the suite green.**
- `src/services/agent_runtime.py:873-874`; the only guard is `tests/unit/test_agent_runtime.py:1324`, which checks `run`'s call site, not `_run_resolved`'s default.
- Evidence: my mutation R1 (in `_run_resolved`, replace the `None` guard with `(_raw_output_observer or (lambda raw: logger.info("raw_output %s", dict(raw))))(supplied)`) survived 724/724 across seven files including `test_graph_nodes.py` and `test_persisted_agent_runtime.py`. An execution-proof variant (default raises) went 104 RED, so the line runs on every `run`. Existing log tests filter on `record.msg == EXPECTED_LOG_MESSAGE`, so an extra record is invisible to them.
- Fix: add a test that drives `run` (and, after I-1, `run_candidate`) through a `LoggingAgentInvocationIdentitySink` runtime with the fake adapter, returning output containing a unique sentinel string (e.g. `message="never-log-this-output"`), captures at DEBUG on the root logger, and asserts (a) every record from `src.services.agent_runtime` / the sink logger is the one permitted message and (b) the sentinel appears in no rendered record. Sabotage: my R1 mutation → RED.

**I-4 — Outcome classification is not pinned against text-based matching.**
- `src/services/agent_runtime.py:635`; tests `:1171` (`provider_parse_error`), `:1205`, `:1225`.
- Evidence: my mutation R2 (replace `_is_provider_parse_error(error)` with `any(w in str(error).lower() for w in ("pars", "validation error"))`) survived 724/724. The test inputs happen to carry those words (`"unparseable provider text"`, pydantic's "validation error for _ParseProbe"), and the `RuntimeError` text contains neither.
- Why: classification by exception text would let provider prose steer stored evidence status, and is exactly what "code/class only" forbids.
- Fix: add two cases: `OutputParserException("x")` (bland text) → `incomplete`; `RuntimeError("could not parse output: 1 validation error")` → `model_error`, `unexpected_error:RuntimeError`. Sabotage: R2 → RED.

### Minor

**M-1 — `CandidateRunOutcome.error` carries the raw exception (and `result.diagnostics.definition_version == -1`).** `agent_runtime.py:597-602`. Neither is persisted or rendered in Task 3, but Task 4/5 must persist only `error_detail`, never `str(outcome.error)`/`repr`, and must take revision identity from the transaction-1 snapshot (C27), never from `diagnostics.definition_version`. Carry into Task 4's brief; a Task 4 test should assert no `-1` reaches an evidence row or a response body.

**M-2 — A pydantic `ValidationError` from the binding step (not the model call) is classified `incomplete`.** `agent_runtime.py:624-627` claims a bare `ValidationError` "can only have come from the provider call", but `ChatDatabricks(**kwargs)` is a pydantic model constructed inside `bind_structured_output_model`, before any request. Saved configurations are prevalidated and transport options are constants, so this is unlikely; either correct the docstring or distinguish binding-time errors (e.g. the adapter wraps binding separately). Evidence would read `incomplete` with no raw output for a run that never reached the model.

**M-3 — `NotImplementedError` is mapped to `structured_output_unsupported` regardless of origin.** `agent_runtime.py:633`. C33 scopes that row to the binding step; a `NotImplementedError` from `structured_model.invoke`, or from the assembler (the pre-invocation `try` at `:786-838` does not convert it), would be reported as an endpoint capability problem. Low likelihood; document or narrow.

**M-4 — The two call-site guards are subset checks with no aim check.** `tests/unit/test_agent_runtime.py:1336-1371`. `_modules_referencing(...) <= {...}` passes if the walker finds no files; liveness is only implied by the sibling `test_no_module_binds_...` asserting a non-empty binding map. Add `assert "src/services/agent_runtime.py" in {p.relative_to(root).as_posix() for p in files}` and a positive control (`_modules_referencing("get_agent_runtime")` must contain `src/services/graph/nodes.py`, which imports it at `:63`). They are also name-based (`getattr(rt, "run_candidate")` bypasses) — acceptable, note only.

**M-5 — Parity test uses a session-less production context.** `tests/unit/test_agent_runtime.py:1043-1080`. Production `run` calls carry session ids; parity against `AgentAssemblyContext(dsa, "root", "actor")` on the `run` side would directly show the assembler ignores them (the refusal makes the candidate side session-less by construction). Cheap strengthening; also consider adding the `v2_schema` overlay axis.

## Sabotage evidence

All from inside `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-267-3` (detached `84da2c71d`), command:
`PYTHONPATH=$T:$T/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/rev-267-3.sqlite /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rf <scope>`.
Narrow scope = `tests/unit/test_agent_runtime.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_persisted_graph_release.py` (GREEN baseline 236 passed). Wide scope = narrow + `test_graph_nodes.py test_model_endpoint_probe.py test_agent_definition_workbench_routes.py test_probe_failure_contract_client_join.py` (GREEN baseline 724 passed). Each mutation applied by a script asserting the anchor occurs exactly once; restore = `git checkout 84da2c71d -- src/services/agent_runtime.py`, then marker count 0 and `git diff --quiet` clean.

| # | Mutation (file `src/services/agent_runtime.py`) | Anchor | Marker `grep -c` | Scope | Result | Failing tests | Restore |
|---|---|---|---|---|---|---|---|
| S1 (assigned) | accept session ids: `if False and (root_session_id or actor_session_id):` | 1 | `REV267_3_S1` = 1 | narrow | **RED 2/236** | `test_run_candidate_refuses_a_session_identity[context0]`, `[context1]` | 0, clean |
| S2 (assigned) | strip silently: replace the `raise` with `assembly_context = AgentAssemblyContext(assembly_context.design_system_active)` | 1 | `REV267_3_S2` = 1 | narrow | **RED 2/236** | same two | 0, clean |
| R3 (own) | pass a different assembly context: `AgentAssemblyContext(not assembly_context.design_system_active)` into `_run_resolved` | 1 | `REV267_3_R3` = 1 | narrow | **RED 28/236** | `test_candidate_prompt_schema_and_configuration_equal_the_production_path[*]` ×28 (all 7 roles × 2 × 2) | 0, clean |
| R1 (own) | observer fires for `run` in production: default observer logs `raw_output %s` | 1 | `REV267_3_R1` = 1 | narrow + wide | **SURVIVED** 236/236, 724/724 | none → I-3 | 0, clean |
| R1X (execution proof) | same default, but raising | 1 | `REV267_3_R1X` = 1 | runtime suites | 104 failed / 108 passed (line executes on `run`) | many | 0, clean |
| R2 (own) | classify a raw exception by its text (`"pars"`, `"validation error"`) | 1 | `REV267_3_R2` = 1 | narrow + wide | **SURVIVED** 236/236, 724/724 | none → I-4 | 0, clean |

After all restores: `git status --short` clean in `rev-267-3`; wide scope 724 passed.

Full unit suite at `84da2c71d` (from inside `rev-267-3`, `DATABASE_URL=sqlite:////tmp/rev-267-3-full.sqlite`): 6 failed, 6376 passed, 110 skipped, 136 warnings (386 s). The 6 failures are exactly the baseline nodes: `test_deploy_autoscaling.py` ×2, `test_style_exclusivity_chokepoint.py` ×3, `test_style_exclusivity_persistence_boundary.py` ×1. This matches the implementer's figures, and there is no new failure cause.

## Task quality: Needs fixes

Required before approval: I-1 (ruling R1), I-2 (no traceback), I-3 and I-4 (tests that kill my surviving mutations R1 and R2, each sabotage-verified). Minor items may be carried into Task 4's brief (M-1 must be).
