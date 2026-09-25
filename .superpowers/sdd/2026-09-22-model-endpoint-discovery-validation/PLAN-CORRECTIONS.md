# PLAN-CORRECTIONS — exact model endpoint discovery and validation (#266)

Plan: `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`

## Execution phase

This file currently authorizes only Task 1. Tasks 2–6 remain gated by the plan's
mandatory reviewed local integration of #260, #261, #263, #265, and #264. Before
Task 2, append the required integrated-code correction pass to this file; do not
replace the evidence below.

## Recorded bases

- `TASK1_BASE=0cfc80472d74c83d37b1281c9faad872cdb033bc`
- `PLAN_HISTORY_BASE=a94c907d2db75e53743289651443fe9583bfa8f7`
- Final `IMPLEMENTATION_BASE` is intentionally absent until the Task-2 local
  integration gate.

Reviewed #260 `29e03411487476383b34101b7b34513dbb917f26` is an ancestor of
`TASK1_BASE`. The observed #261 candidate `876f2a91f1df4b4b03276a7258934a53954eb637`,
#263 final head `1d706e21b92aad68314da2e79bb4d1d5626663b7`, #264 Task-1 head
`ac69f62b6792d812f99eef53f725085bc90c61a6`, #265 plan head
`3a3583c3061456d9292c43f9a1b45dffffca52be`, and research head
`447791d7af34aafc18612cecead6a90805b367ec` are not ancestors of `TASK1_BASE`.
The pre-integration range contains no merge commit.

## ALLOWED_PREINTEGRATION_266_HISTORY

Exact ordered `git log --reverse --format='%H %s' "$PLAN_HISTORY_BASE".."$TASK1_BASE"`:

```text
ef726d7e5fbdbd7288ea13bf702ed26ae50bb61c docs: revalidate model endpoint discovery (#266)
2c618a8c7237d974f0622747d2da4469437121ab docs: plan exact model endpoint discovery (#266)
c26389743f17f225c3d92dfb579f0c19ae4fd6f5 docs: remove circular model discovery dependency
9929fd4d9754c9bbfc2f16e3ad794f29002ca838 docs: review model endpoint discovery plan
85bcc1672866ace09ba21958d46850b607790be9 docs: correct model endpoint discovery plan (#266)
6622ea02312b283aff4d8e1b02824a159aa6e1b6 docs: rereview model endpoint discovery plan
86b292f7dec433551e4b863373cab0992705a2fa docs: correct model endpoint review base
750c03af1617c9a7e0b106300674cdac091beecd docs: rereview corrected model endpoint plan
26ab712f14e3daf9deacdc9aea683b9c9bca9f5a docs: make model discovery replay auditable
b853eef3c15b0bca0e3ab9f5706e21bde67b1b24 docs: rereview model discovery replay ledger
500ae52eab2cf38dc0a6a3ad4e513671218b5880 docs: ledger model discovery task reviews
0cfc80472d74c83d37b1281c9faad872cdb033bc docs: approve model discovery task ledger
```

Every entry is reviewed #266 research, planning, correction, review, or re-review
history. There is no predecessor-ticket implementation commit in this interval.

## Environment and external-contract re-probe

- Worktree branch: `plan/model-discovery-266`; clean at Task-0 start.
- `.venv`: absent before and after every Task-0 command.
- Interpreter: `/Users/robert.whiffin/.pyenv/shims/python`, Python 3.11.0.
- Installed `databricks-sdk`: 0.112.0.
- `ServingEndpointsAPI.list`: `(self) -> Iterator[ServingEndpoint]`.
- `ServingEndpointsAPI.get`: `(self, name: str) -> ServingEndpointDetailed`.
- `ServedEntityOutput` constructor includes `foundation_model`.
- `EndpointStateReady`: `NOT_READY`, `READY`.
- `EndpointStateConfigUpdate`: `IN_PROGRESS`, `NOT_UPDATING`,
  `UPDATE_CANCELED`, `UPDATE_FAILED`.
- `PermissionDenied`, `ResourceDoesNotExist`, and `DatabricksError` exist at the
  installed SDK exception boundary required by Task 1.
- `src/services/model_endpoint_catalog.py` and
  `tests/unit/test_model_endpoint_catalog.py` are both absent.

## Current code/test seams

- `src/services/agent_runtime.py` owns injected `model_factory` and
  `client_factory`; production constructs `ChatDatabricks` with the exact stored
  endpoint and calls `with_structured_output(schema)`.
- `tests/unit/test_agent_runtime.py` already has a deterministic recording model
  and client factory for that seam.
- `src/api/routes/tools.py` lists generic endpoints using top-level `task` and
  converts exceptions to an empty list. It is evidence of the forbidden prior
  pattern and is not a reusable #266 boundary.
- The CI collection guard is `tests/unit/test_ci_collects_integration_tests.py`.

## Cause baseline

Command:

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_ci_collects_integration_tests.py
```

Result: 22 passed, zero failed, zero skipped. Warning causes:

1. Pydantic class-based `Config` deprecation in `src/api/schemas/requests.py`.
2. Pydantic class-based `Config` deprecation in `src/api/schemas/responses.py`.
3. Established `langchain-community` sunset warning from `chat_service.py`.
4. Pydantic class-based `Config` deprecation in Unity Catalog's toolkit.
5. Pydantic v1 `@validator` deprecation in Databricks AI Bridge.

Any new failure, skip, or warning cause in Task 1 is a regression even if the
counts happen to match.

## Task 1 consistency table

| Plan claim | Live-code observation | Correction / ruling |
| --- | --- | --- |
| Create only catalog module and focused unit test before integration | Both paths are absent; no predecessor owns them | No correction. Task 1 may proceed in this worktree. |
| Discover with one argument-free list call and `foundation_model` | Installed SDK and constructor match | No correction. Never use generic `task`, `served_models`, OpenAPI, or query. |
| Validate exact custom name with `get(name)` | Installed SDK exposes exact-name get and named state enums | No correction. Preserve input bytes; no trim or alias rewrite. |
| Map named SDK exception categories | Required installed exception classes exist | No correction. Do not infer provider HTTP codes or catch into empty success. |
| Deterministic fake belongs with the port | No existing #266 fake or catalog module exists | No correction. Fake must require no SDK mock and expose exact call evidence. |
| RED is missing-module collection failure | Test module is absent | No correction. Capture RED before production creation. |

## Binding overrides and rulings

No Task 1 plan text requires correction against the live code or installed SDK.

- Ruling: execute Task 1 only on the current pre-integration branch; do not bring
  #261/#263/#264/#265 code into this range. The plan expressly isolates these two
  new files. Cost if wrong: Task 1 would need replay/re-review before Task 2, but
  no shared predecessor file is exposed now.
- Ruling: treat `routes/tools.py` only as negative evidence. Cost if wrong:
  reusing it would silently misclassify endpoints and erase observable failures.
- Ruling: reserve exact-detail-name equality for the independent reviewer sabotage;
  the controller sabotage remains the top-level `task` heuristic required by the
  plan. Cost if wrong: duplicated sabotage would leave alias handling unfalsified.

## Required Task 1 handoff

Every Task 1 implementer and reviewer must read this file first. The Task 1 package
base is the full `TASK1_BASE` above, never `HEAD~1`. After Task 1 and all fix/report/
review/re-review commits close, append the exact reviewer-approved
`ALLOWED_TASK1_266_HISTORY` before the Task-2 replay gate.

## Post-Task-1 pre-rebase history audit (approved)

- `PRE_REBASE_266_HEAD=ce10838ac9951fb3728029cb42db56dbd0cb8efc`
- `git rev-parse HEAD` equals `PRE_REBASE_266_HEAD`.

### ALLOWED_TASK1_266_HISTORY

Exact ordered `git log --reverse --format='%H %s' "$TASK1_BASE".."$PRE_REBASE_266_HEAD"`:

```text
3b6542cacee893a4a8e6409e6aff0a3b65aa3926 feat: add exact model endpoint catalog (#266)
e464ab1a4800005227de928cb590174981541cd9 docs: record model endpoint catalog task 1 report
ce10838ac9951fb3728029cb42db56dbd0cb8efc docs: approve model endpoint catalog task 1
```

One-for-one classification:

| Commit | Classification | Verified file scope |
| --- | --- | --- |
| `3b6542cacee893a4a8e6409e6aff0a3b65aa3926` | implementation | Adds only `src/services/model_endpoint_catalog.py` and `tests/unit/test_model_endpoint_catalog.py`. |
| `e464ab1a4800005227de928cb590174981541cd9` | report | Adds only Task-1 report and controller-sabotage evidence under this plan's ignored SDD workspace. |
| `ce10838ac9951fb3728029cb42db56dbd0cb8efc` | review | Adds only `progress.md` and the Task-1 review under this plan's ignored SDD workspace. |

Exact equality checks:

- Raw `TASK1_BASE..PRE_REBASE_266_HEAD` history equals the `ALLOWED_TASK1_266_HISTORY` ledger above, exactly and in order.
- Raw `PLAN_HISTORY_BASE..PRE_REBASE_266_HEAD` history equals exactly, in order, frozen `ALLOWED_PREINTEGRATION_266_HISTORY` followed by `ALLOWED_TASK1_266_HISTORY` (15 commits total: 12 pre-integration plus 3 Task-1).
- The Task-1 parent chain is linear: `TASK1_BASE -> 3b6542c -> e464ab1 -> ce10838a`.

Source safety checks:

- `git rev-list --merges "$PLAN_HISTORY_BASE".."$PRE_REBASE_266_HEAD"` is empty.
- Reviewed #261 `876f2a91f1df4b4b03276a7258934a53954eb637`, #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7`, #264 `ac69f62b6792d812f99eef53f725085bc90c61a6`, and #265 `3a3583c3061456d9292c43f9a1b45dffffca52be` are each not ancestors of `PRE_REBASE_266_HEAD`.
- Neither the Task-1 ledger nor complete source ledger contains a #261/#263/#264/#265 predecessor entry.

Approval: history is clean and approved for the mandated complete-source replay. This approves only the pre-rebase source ledger; the required local integration, rebase, range-diff, and integrated-code corrections gate remain outstanding.

---

# Task 0 phase B — integrated-code re-probe (2026-09-25)

This addendum extends, and does not replace, the Task 0 phase A record above. It
**overrides the plan** wherever the two disagree. Every Task 2–6 implementer and
reviewer brief must attach it and acknowledge every numbered correction below.
Verdicts: CONFIRMED (the plan is right against live code), CORRECTED (the plan's
claim is wrong and the correction binds), NEW DEFECT (a hazard the plan does not
name). Line numbers are at `TASK1_REBASED_HEAD` unless stated.

## Correction 1 — CONFIRMED: replay, range proof and final bases

- `PRE_REBASE_266_HEAD=ce10838ac9951fb3728029cb42db56dbd0cb8efc`, tagged `backup/266-pre-rebase-ce10838ac` (a tag, not a branch).
- `INTEGRATION_BASE=c040dbde087e1c9ff4bc07656b74b3d09aa06300` (`feat/langgraph-core`, "Merge #264: safe output-schema overlays"). It is not `447791d7a`.
- Command: `git rebase --onto c040dbde0 a94c907d2db75e53743289651443fe9583bfa8f7 plan/model-discovery-266`. All 15 commits applied with no conflicts.
- `TASK1_REBASED_HEAD=c5de240440b161bf31adbd205924f210ee5818d7`.
- `git merge-base --is-ancestor c040dbde0 HEAD` returned 0. `git rev-list --left-right --count c040dbde0...HEAD` returned `0 15`, so the branch is 0 behind and 15 ahead. `git rev-list --merges c040dbde0..HEAD` is empty.
- `git range-diff a94c907d2..ce10838ac c040dbde0..HEAD` shows **15 of 15 commits as `=`**, with **zero `!`**, zero added and zero dropped:
  `ef726d7e5=44b632ed3`, `2c618a8c7=649e3865d`, `c26389743=a56251554`, `9929fd4d9=6a12ba52f`,
  `85bcc1672=9a5dc6423`, `6622ea023=69317336e`, `86b292f7d=d703b0e1e`, `750c03af1=8b2599ceb`,
  `26ab712f1=aa3ed85b9`, `b853eef3c=7c7aa6b48`, `500ae52ea=41d4fd7f8`, `0cfc80472=26a0948cc`,
  `3b6542cac=8eac1da6e` (Task 1 implementation), `e464ab1a4=1cd4a30eb` (report), `ce10838ac=c5de24044` (review).
- `git diff --name-only c040dbde0 HEAD` equals `git diff --name-only a94c907d2 ce10838ac` as a set. `comm -23` and `comm -13` are both empty, and a `LC_ALL=C` re-sort re-confirmed it. Each set has the same 17 paths. For each of the 17 paths the blob at `ce10838ac` is byte-identical to the blob at `HEAD`, and both new source files are absent at `c040dbde0`.
- Merged predecessor heads (the second parent of each local merge commit), each an ancestor of `INTEGRATION_BASE`:
  #260 `29e03411487476383b34101b7b34513dbb917f26` (merge `774703e44`) ·
  #261 `e9ab7f937dea063e155f9df8e24ac52fdaa6b754` (merge `795262c16`; the phase-A observed candidate `876f2a91f` is also an ancestor) ·
  #263 `1d706e21b92aad68314da2e79bb4d1d5626663b7` (merge `76a88f238`) ·
  #265 `7eaf58f01f24523957f9c93df5f74401f47120f1` (merge `3ed8f9b6a`) ·
  #264 `e3aa3650c3cd8501158e7750944494657d9bee50` (merge `c040dbde0`).
  **CORRECTED:** phase A recorded #265 "plan head" `3a3583c30` and #264 "Task-1 head" `ac69f62b6` as heads. Neither is an ancestor, because both branches were rebased before they merged. The merged heads above supersede them.
- **`IMPLEMENTATION_BASE=c040dbde087e1c9ff4bc07656b74b3d09aa06300`**, which is an ancestor of `HEAD`. It is reserved for the final whole-branch range only. Every Task 2–6 package records its own `TASK_BASE`/`TASK_HEAD`. `TASK1_BASE` (`0cfc80472`) stays valid only for the closed Task 1 package.
- Task 1's work survives the replay. `tests/unit/test_model_endpoint_catalog.py` gives 19 passed (identical to Task 1's review). Together with `test_agent_runtime.py` and `test_ci_collects_integration_tests.py` the result is 64 passed, 0 failed, 0 skipped. Ruff is clean on both Task 1 files.

## Correction 2 — CONFIRMED: environment, provenance and the SDK contract at 0.112.0

- The interpreter is `/Users/robert.whiffin/.pyenv/shims/python`, which resolves to `/Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python`, Python 3.11.0. `.venv` was absent before and after every gate.
- With `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr`, provenance resolves inside this worktree for `src/__init__.py`, `packages/databricks-tellr/databricks_tellr/__init__.py` and `src/services/model_endpoint_catalog.py`.
- **Installed `databricks-sdk` is exactly `0.112.0`** (`importlib.metadata.version`). This is a live re-probe, not an assumption:
  - `ServingEndpointsAPI.list(self) -> Iterator[ServingEndpoint]` takes no arguments. Its source is one `GET /api/2.0/serving-endpoints` and returns `[]` when `endpoints` is absent.
  - `ServingEndpointsAPI.get(self, name: str) -> ServingEndpointDetailed`. Its source is `GET f"/api/2.0/serving-endpoints/{name}"`, with the name **interpolated unescaped** (see correction 4).
  - `get_open_api(self, name: str) -> GetOpenApiResponse` is present. `query(...)` has **no** `response_format` parameter.
  - `ServedEntityOutput.foundation_model: Optional[FoundationModel]`. `FoundationModel` has exactly `description, display_name, docs, name`.
  - `ServingEndpoint` has `config, name, state, task, …`. `EndpointCoreConfigSummary` has exactly `served_entities, served_models`. `EndpointState` has exactly `config_update, ready`.
  - `EndpointStateReady` is `NOT_READY, READY`. `EndpointStateConfigUpdate` is `IN_PROGRESS, NOT_UPDATING, UPDATE_CANCELED, UPDATE_FAILED`.
  - `PermissionDenied`, `ResourceDoesNotExist` (a subclass of `NotFound`), `DatabricksError`, `NotFound` and `Unauthenticated` exist. `PermissionDenied` is a `DatabricksError`.
  - `WorkspaceClient` has **no** `system_ai` or foundation-model attribute. The only name containing "system" is `system_schemas`.
- The plan's "SDK/transport failure → unavailable" row is **not** satisfied by the landed Task 1 code. See correction 3.

## Correction 3 — NEW DEFECT (blocking for Task 2's brief): SDK transport exhaustion is not a `DatabricksError`

`src/services/model_endpoint_catalog.py` maps only `PermissionDenied`, `ResourceDoesNotExist` and
`DatabricksError`: `list_system_models` at `:83-97` and `validate_custom_endpoint_remote` at `:133-152`.
In SDK 0.112.0, `databricks.sdk.retries.retried` retries `requests.ConnectionError`/`Timeout` until
`retry_timeout_seconds`, then raises builtin **`TimeoutError(...) from last_err`**. When
`max_attempts` is exceeded it raises builtin `RuntimeError`. Measured on the real `_BaseClient` with
`requests.Session.request` forced to raise `ConnectionError` and `retry_timeout_seconds=2`, the
result was `builtins.TimeoutError`, `isinstance(e, DatabricksError) is False`, `__cause__` was
`ConnectionError`, after 3.6 s. This used no network and no remote. So a transport outage escapes
both catalog methods as a raw exception. The route then answers 500 instead of `503 catalog_unavailable`,
and the save answers 500 instead of `422 endpoint_unavailable`. The plan's table requires both
"SDK/transport failure" rows.
**Ruling:** Task 2 fixes this in `model_endpoint_catalog.py` for **both** methods before it
consumes the catalog. It maps `TimeoutError`, `RuntimeError` raised by the SDK retry wrapper,
`requests.exceptions.RequestException` and `OSError` to the existing unavailable codes and never
reads the exception text. It adds one RED→GREEN test per method that raises builtin `TimeoutError`
from the fake SDK. This adds `src/services/model_endpoint_catalog.py` and
`tests/unit/test_model_endpoint_catalog.py` to Task 2's file set. Task 1 stays closed; this is a
separately ledgered Task 2 commit. Cost if wrong: every outage-time save and discovery surfaces as
an opaque 500, which the plan forbids and which a unit fake that only raises `DatabricksError` can never catch.

## Correction 4 — NEW DEFECT (blocking for Task 2's brief): endpoint names are interpolated into the request path

The SDK builds `f"/api/2.0/serving-endpoints/{name}"` without escaping. I measured the prepared
requests URL through `_BaseClient` with a stubbed session, with no network:
`'../../2.0/secrets/scopes/list'` becomes `https://h/api/2.0/secrets/scopes/list`, so dot-segments
are normalised into a **different workspace API**. `'x?y=1#frag'` keeps a query and a fragment, and
`'a%2Fb'` keeps its percent-escape. The space-containing name that Task 1 must preserve encodes
safely as `%20`. The plan's local policy (`:66`, `_URL_PREFIX`) rejects only scheme/`//` prefixes.
So an admin-entered name can make the **service-principal** client issue a GET against an arbitrary
workspace path. The response is only compared by `name`, so nothing is echoed, but the request is
made. The same saved name reaches `ChatDatabricks(endpoint=...)` at runtime and in Task 5's probe.
**Ruling (the controller may override the code choice):** extend `validate_endpoint_name_policy`
so it also rejects any name containing `/`, `\`, `?`, `#` or `%`, or an ASCII control character,
or equal to `.` or `..`. Report this under the **existing** `endpoint_url_not_allowed` code and
message, so the closed `EndpointValidationCode` literal and the table stay unchanged. Spaces and all
other characters stay accepted verbatim. Add the same guard defensively at the top of
`validate_custom_endpoint_remote` so that the remote method refuses before any `get`. Task 5's
probe re-runs the policy on the **saved** name before it invokes anything, because rows saved
before #266 never passed it. Park the pre-existing runtime exposure for legacy rows for the
whole-branch/security review; it is out of #266's write path. Cost if wrong: a path-traversal
primitive under the app identity ships behind an "exact name" feature. Cost of the ruling if it is
itself wrong: a real endpoint name containing one of these characters becomes unsaveable, and no
evidence of such a name exists.

## Correction 5 — CONFIRMED and SHARPENED: the one locked writer and its four entry points

The owner is `src/services/graph_configuration_draft.py`, class `_GraphConfigurationDraft` `:242`.
The one mapper/hash/flush/audit/lock write is `_write_locked_content` `:755` (`@staticmethod`).
The only `lock_version += 1` is at `:774`, and it returns `changed=new_hash != old_hash`, so
same-content saves still advance the lock and audit. That is landed behaviour, not Task 2 work.
The four entry points each open `with session.begin():` and `_read_workbench_for_draft_write` (FOR UPDATE):

| Entry point | Line | Measured phase order |
| --- | ---: | --- |
| `save_editable_model_draft` | 270 | command checks `:276-284` → lock → rebuild + `DefinitionContent.model_validate` → **local tuple `:315`** → **stale `:316`** → **post-stale tuple `:323`** → write |
| `save_draft_content` | 331 | `_validate_common` → strict type → lock → round-trip → `_immutable_content_issues` `:366` → **local `:373`** → **stale `:374`** → **post-stale `:381`** → write |
| `upgrade_draft_protected_assembly` | 389 | lock → **stale `:404` first** → assembler upgrade → local `:419` → post-stale `:420` → write |
| `upgrade_draft_schema_contract` (#264, the fourth) | 428 | lock → **local on current `:460`** → stale `:461` → `already_current` → upgrade → local on target `:473` → post-stale `:474` → write |

`save_draft_content` has **no production caller** (repo grep over `src/`). The PUT route calls only `save_editable_model_draft` (`routes/agent_definitions.py:428`).

## Correction 6 — CORRECTED (binding placement ruling): where #266's two phases register

The plan names `RemoteEndpointDraftValidator(Protocol).validate(content) -> None` and says to register it "in #263's pipeline". The landed pipeline has:
- `DraftCandidateValidator = Callable[[DefinitionContent], tuple[DraftValidationIssue, ...]]` (`:136`). Its validators **return** issues and never raise.
- `local_candidate_validators` (`:250-253`, `(_assembly_candidate_validator, _schema_overlay_candidate_validator)`), which runs **before** stale in every save.
- `post_stale_validators` (`:256`, `()`), which runs only for a current candidate.
- These are **class attributes shared by all four entry points**. A validator added to either tuple also runs on both upgrades.
- #264's landed guard `tests/unit/test_graph_configuration_draft.py:2107` `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only` asserts the **exact** tuples (`local == (assembly, overlay)`, `post_stale == ()`).

As #264's correction 16 showed, the tuple a validator joins decides the wire status. If it joins the **local** tuple, invalid-plus-stale returns an ordered **422**. If it joins the **post-stale** tuple, the stale check short-circuits it, so a stale request returns **409** with the validator never called.

Class-wide registration is wrong for #266 for two measured reasons:
1. Both upgrades would run endpoint checks, and the remote check would make network calls. An upgrade on a draft whose saved endpoint has since become not-ready would 422 on `candidate.model.endpoint_name`.
2. That 422 would be **invisible**. `rejectOperation` (`frontend/.../draftEditorState.ts:656-676`) maps inline field errors only when `operation === 'save'` (`:672`). `nonInlineIssues` (`:637`) drops every inline-owned field, including `candidate.model.endpoint_name` (`INLINE_FIELD_OWNERS` `:222-228`). So an upgrade rejection naming the endpoint shows nothing at all.

**Ruling:**
- **Local phase:** add one private `_endpoint_name_policy_validator` (a `DraftCandidateValidator` adapter over `validate_endpoint_name_policy` that translates `EndpointValidationFailure` into `DraftValidationIssue("candidate.model.endpoint_name", code, message)`). Run it **only in the two save entry points**, inside the same aggregate: `self._run_candidate_validators(self.local_candidate_validators + (_endpoint_name_policy_validator,), content)` at `:315` and `:373`. Its issue therefore follows the assembly and overlay issues in the one ordered 422.
- **Remote phase:** keep the plan's `RemoteEndpointDraftValidator` Protocol (`validate(content) -> None`, raising `EndpointValidationFailure`). Adapt it through one private adapter and run it **only in the two save entry points**, after `self.post_stale_validators` and immediately before `_write_locked_content`, exactly once.
- **Leave both class tuples unchanged.** The #264 guard `:2107` then stays GREEN unmodified. Task 2 adds a sibling guard that pins the save-only composition, so moving the policy into the class tuple, or the remote call above the stale return, REDs.

Cost if wrong: either upgrades acquire network I/O and an invisible failure mode, or the stale-ordering contract inverts. The plan's two ordering cases (URL plus stale gives 422 with zero remote calls; valid plus stale gives the seven-role 409 with zero remote calls) are unchanged by this ruling.

## Correction 7 — NEW DEFECT + RULING: composition and injection (measured 134-test radius)

Routes construct `GraphConfiguration()` with **no arguments** at five sites (`routes/agent_definitions.py:370, :428, :472, :512, :552`), and no facade class defines `__init__`.

**Measured radius.** I temporarily registered a post-stale validator that always returned `endpoint_unavailable` (marker `PHASEB_RADIUS_PROBE`). It REDs **134 tests**: `test_graph_configuration_draft.py` 76 of 121, `test_agent_definition_workbench_routes.py` 37 of 164, `test_agent_definition_workbench_postgres.py` 12 of 15 and `test_agent_schema_overlay_postgres.py` 9 of 10. After a byte-exact restore (md5 `77cd8c49308252c21f146e95d58fd949` before and after, marker absent, `git status` clean), `test_graph_configuration_draft.py` is back to 121 passed. So a production-default remote validator that runs in tests is not viable without rewriting 134 tests.

**Ruling:**
- `GraphConfiguration(*, remote_endpoint_validator: RemoteEndpointDraftValidator | None = None)`. `None` means the remote phase is skipped. This is documented as trusted/test composition only.
- `graph_configuration.py` exports one production factory that lazily builds `DatabricksModelEndpointCatalog(get_system_client())` behind the Protocol.
- **Task 3** wires it. The PUT route obtains the validator through a FastAPI dependency (which resolves after the router's `require_admin`) and passes it to `GraphConfiguration(...)` for `save_editable_model_draft` only. `_app_for` (`tests/unit/test_agent_definition_workbench_routes.py:136`) installs a default accepting fake override, so the existing 164 stay green.
- Task 3 must add a route test, with sabotage, proving that the production dependency supplies a non-`None` validator. The sabotage is to pass `None`; the test must RED.
- Between Task 2 and Task 3 the production PUT does not yet validate remotely. That intermediate state is acceptable because nothing merges before the whole-branch review.

Cost if wrong: a fail-open default that a forgotten wire silently disables. The Task 3 wiring test is the guard against exactly that.

## Correction 8 — NEW DEFECT (non-blocking; parked for the user and the whole-branch review): remote I/O under the exclusive draft lock

The plan mandates remote `get` after the locked snapshot is current, which is inside the save's `with session.begin():`. At that point FOR UPDATE is held on `GraphRelease`/`GraphDraft` and on the selected row (`graph_configuration_workbench.py:188-208, :363-375`). `get_system_client` builds a default `WorkspaceClient` (`src/core/databricks_client.py:194`). The SDK default `retry_timeout_seconds` is **300** (`_base_client.py:79`). So during a transport outage one save can hold the draft lock for up to about 5 minutes, and every other save, upgrade and `read_workbench` (FOR SHARE) queues behind it.

**Ruling:** Task 2 implements the plan's order as written. Its PostgreSQL test already proves a blocking validator with a lock waiter. Record a bounded-client option (a dedicated catalog client with a short `retry_timeout_seconds`) as a **user decision**; Tasks 2–6 must not invent credential handling. Cost if wrong: an outage-time lock convoy, with no data corruption.

## Correction 9 — CONFIRMED: the admin authorisation dependency, routes and schemas

- Router: `routes/agent_definitions.py:51-55`, `prefix="/api/admin/agent-definitions"`, `dependencies=[Depends(require_admin)]`. `require_admin` is in `src/api/routes/_authz.py:326` and bypasses outside production. Tests force production through `_force_admin` (`test_agent_definition_workbench_routes.py:153-157`).
- `require_draft_write_principal` (`:58`). The PUT (`:380-453`) takes `request: Request` plus the principal dependency and parses `await request.json()` **inside** the handler, so authorisation precedes body parsing by mechanism. The POST siblings share `_parse_lock_request` (`:269`), which uses the strict `DraftLockRequest` (`schemas:391`, `{"lock_version": int>=0}`, `extra="forbid"`, `strict=True`). Task 5's probe route must reuse `_parse_lock_request`, and its body is exactly that DTO.
- One response-helper set: `_draft_validation_response` `:140`, `_rejection_response` `:228` (copies domain issues verbatim), `_conflict_response` `:242`, `_malformed_json_response` `:353`. The seven-role 409 comes from `_conflict_response(outcome, client_candidate=None)`, and Task 5 reuses that exact call.
- Schemas: `_DefinitionContentResponse` (`schemas:180`) now carries read-only, server-derived `selectable_optional_fields` (`:197`) and `canonical_fields` (`:204`), both computed from `SCHEMA_CONTRACT_BUNDLES` and never accepted. `EditableModelDraftRequest` (`:372`) is `prompt_text`, `model`, optional `assembly_rules` and optional `schema_overlay`. `EditableModelDraftModelRequest` (`:332`) holds the four model leaves; `endpoint_name` has a blank validator only (`:338`). `DraftValidationErrorResponse.code: Literal["invalid_draft"]` (`:410`) and `DraftSaveConflictResponse.code: Literal["stale_draft"]` (`:426`).
- **Ruling:** the Task 3 and Task 5 DTOs are new sibling classes with `extra="forbid"`. They must not subclass or extend `_DefinitionContentResponse`, `EditableModelDraftRequest` or `DraftLockRequest`, and must not add a field to any of them.
- The new GET sits beside `@router.get("/workbench")` (`:365`). There is no path collision, because `/draft/{agent_key}` has no GET.

## Correction 10 — CORRECTED: "only five editable leaves" holds only for a v1-assembly candidate with no overlay edits

The integrated serializer `validateDraftForm` (`draftEditorState.ts:533-575`) always emits `prompt_text` plus the four `model` leaves. It **adds `assembly_rules`** whenever the local form holds v2 rules, and **adds `schema_overlay`** whenever overlay edits exist (`:566-575`, "keeps the five-field body"). The packaged seed has all seven roles at assembly `format_version` 1 and schema contract 1, with endpoint `databricks-claude-opus-4-6` (live probe of `load_graph_v1_manifest()`), so the five-leaf body is exact for the seed.

**Ruling:** Task 4 and Task 6 assert the five-leaf body **only** on a seed/v1 role with no overlay edits. The discovery, manual-entry and correction flows must use such a role. Any v2 or overlay-edited case asserts the exact integrated serializer output instead, which adds only the key that serializer owns. Neither task may widen or narrow the serializer. Cost if wrong: a correct v2 body fails a five-leaf assertion, or a test is weakened to pass.

## Correction 11 — CONFIRMED: `AgentRuntime.run`, the loader, and the endpoint binding Task 5 probes

- `AgentRuntime.run(self, agent_key, graph_release_id, payload, assembly_context) -> AgentInvocationResult` (`agent_runtime.py:551`) is **four positional arguments**. That arity is pinned across ten call sites by `tests/unit/test_graph_nodes.py:222`. `__init__` (`:518`) is keyword-only: `persisted_release_loader`, `model_adapter`, `identity_sink`. Production is `get_agent_runtime()` (`:688`, `lru_cache`), built from `PersistedGraphReleaseLoader` + `DatabricksModelAdapter()` + `LoggingAgentInvocationIdentitySink`.
- `PersistedGraphReleaseLoader.resolve(graph_release_id, agent_key)` (`persisted_graph_release.py:98`) resolves **published releases, not the draft**. So the probe cannot go through `run`. It must read the draft candidate from the workbench (correction 13) and call the shared binding helper directly.
- The binding is `_run_resolved` (`:570`): `AgentModelConfiguration(endpoint_name=content.model.endpoint_name, …)` (`:629-634`), then `self._model_adapter.invoke(...)` inside the identity-sink callback (`:650-664`). `DatabricksModelAdapter.invoke` (`:414-461`) builds `self._model_factory(endpoint=configuration.endpoint_name, temperature, max_tokens, top_p, workspace_client=self._client_factory())` (`:445-451`) and calls `model.with_structured_output(schema)` (`:452`) and `.invoke(prompt)`. Its defaults are `ChatDatabricks(**kwargs)` (`:403-406`) and `get_system_client()` (`:409-412`); the latter is the runtime identity.
- **Two constraints the plan does not name:**
  1. `invoke` collapses the whole provider tuple, **including `PermissionDenied`**, into `ModelProviderUnavailableError` (`:429-461`). A probe that reused `invoke` could never return `403 endpoint_probe_forbidden`. The extracted helper must therefore sit **below** that catch and return the bound structured model. `invoke` keeps its catch exactly, and the probe classifies separately. `NotImplementedError` is not in the tuple today.
  2. `test_agent_runtime.py:435` (`runtime_source.count("with_structured_output(") == 1`) and the AST guard `:523-548` (`structured_bindings(agent_runtime) == 1`, `nodes == 0`, `prompt_assembler == 0`) pin **exactly one** binding call, in `agent_runtime.py`. The helper therefore lives in `agent_runtime.py`, and `model_endpoint_probe.py` imports it and never calls `with_structured_output(` itself. Those guards do not scan `model_endpoint_probe.py`, so the plan's reviewer sabotage `TASK5_REVIEWER_STRUCTURED_BINDING_SABOTAGE` needs a **new** probe-side test that asserts the helper identity. The existing guard cannot catch that sabotage.

## Correction 12 — CORRECTED: the probe binds the saved model configuration, not the endpoint alone

The plan's `StructuredOutputProbeAdapter.probe(endpoint_name: str)` would invoke with sampling values that differ from the saved candidate's, which is not the runtime seam.

**Ruling:** it becomes `probe(configuration: AgentModelConfiguration) -> None`. The configuration is built from the copied saved candidate exactly as `_run_resolved` does (`:629-634`). The reported identity stays `endpoint_name`, `candidate_hash`, `lock_version`. No request field may supply any part of it. Cost if wrong: a probe that succeeds while the saved `max_tokens` would fail structured output at runtime.

## Correction 13 — NEW DEFECT: the probe's read can hold a share lock across the remote call

`read_workbench` (`graph_configuration_workbench.py:179-186`) takes `FOR SHARE` on the parents (`:200-208`) inside the **caller's** implicit transaction. The GET route holds it for the request lifetime (`routes:365-377`). If Task 5's service reads this way and then invokes the model, every concurrent save's FOR UPDATE blocks for the whole probe. That directly contradicts the plan's "do not hold a database lock during the remote invocation".

**Ruling:**
- The probe reads and copies its snapshot inside `with session.begin():` and exits it (releasing the locks) **before** any policy re-check or network work.
- It computes the 409 with the existing `_draft_aggregate_snapshot` (`graph_configuration_draft.py:737`), reached through `GraphConfiguration`, and never a copy of it.
- Task 5 **adds a PostgreSQL proof** to `tests/integration/test_agent_definition_workbench_postgres.py`: while a blocking fake probe is in flight, a concurrent save commits, and the probe still reports its copied pre-save identity. This adds that file, and `tests/unit/test_ci_collects_integration_tests.py` only if needed, to Task 5.

Cost if wrong: a slow endpoint stalls every draft writer, and unit SQLite cannot show it.

## Correction 14 — CORRECTED: `tests/unit/test_graph_configuration_workbench.py` does not exist

It is absent at `HEAD`, absent at `c040dbde0`, and has never existed in any ref (`git log --all` over the path is empty). Workbench reads are tested in `test_graph_configuration_draft.py`, `test_agent_definition_workbench_routes.py` and the PostgreSQL suite. The plan says "Modify" (Task 5) and lists it in Task 5's RED command and Task 6's matrix. A missing path makes pytest error, not skip.

**Ruling:** Task 5 **creates** it and puts the probe-snapshot facade tests there. The matrix keeps it, and Task 6 must see it present. If Task 5's read method lives in `graph_configuration_draft.py`, which is the natural home because `DraftSaveConflict` and `_draft_aggregate_snapshot` live there, that file joins Task 5's set. `tests/unit/test_model_endpoint_probe.py` is also absent, as expected, and Task 5 creates it.

## Correction 15 — CONFIRMED: one reducer, one request counter, one gate; and who may join it

These are the only instances:
- reducer `draftEditorReducer` at `draftEditorState.ts:827`, wired by the one `useReducer` at `useDraftEditor.ts:31`
- request counter `nextRequestIdRef = useRef(1)` at `:32`, allocated at `:50, :103, :146, :189`
- in-flight ref `:33`
- gate `operationBlocked()` at `:40` (`inFlightRequestIdRef.current !== null || state.pendingSave !== null`)
- `DraftOperationKind = 'save' | 'upgrade' | 'sourceRecovery' | 'schemaUpgrade'` at `:138`, with the one `pendingSave` slot at `:155`
- the render-side gate `AgentDefinitionWorkbench.tsx:97-100` (`operationsDisabled = pending !== null`)

**Ruling:**
- Task 6's Probe joins this gate as `operation: 'probe'`, uses `nextRequestIdRef`, and adds no second reducer, ref or gate. A probe success must not change the lock, the saved entry, or any form value.
- Task 4's catalog refresh is a **read**, not a draft operation, and **must not** enter `pendingSave`. It must not block Save, and Save must not block its recovery. It may keep one private freshness token (for example `catalogRequestTokenRef`) whose only job is to drop out-of-order GET responses. That token is not a second operation controller, and reviewers must not flag it as one.

Cost if wrong: either a catalog load disables Save, or a probe races Save under a second counter.

## Correction 16 — CORRECTED: catalog state must be owned once per workbench, not per role editor

`AgentDefinitionWorkbench.tsx:94-136` renders **one `DefinitionEditor` per model role at the same time**, hiding the non-selected ones (`:107`). Each editor has its own `activeTab` state (`DefinitionEditor.tsx:138`). "Fetch on first Model-tab opening" inside `DefinitionEditor` would therefore fetch up to seven times per identity-scoped catalog.

**Ruling:**
- The catalog state machine (`idle | loading | ready | empty | error`, last good list, freshness token) is owned **once** by `AgentDefinitionWorkbench` (or a hook it calls) and passed to the selected role's Model panel.
- The first Model-tab opening of **any** role triggers one GET, and only an explicit **Refresh models** triggers another.
- Search text may stay per role.
- `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx` joins Task 4's file set.

Cost if wrong: repeated sensitive calls, plus a GET count that breaks the landed one-read assertions (correction 17).

## Correction 17 — NEW DEFECT (pre-brief for Tasks 4 and 6): the landed test harnesses route by method, not by URL

- **Vitest harnesses.** `AgentDefinitionWorkbench.test.tsx` answers **every GET with the workbench body** (`:181-183`, `:831`, `:1652`, `:1729`) and `mockFetchResponse` (`:90-97`) answers every URL alike. Any catalog GET would receive a workbench object, fail the strict parser, and render an error. Several assertions count every GET: `:806`, `:1091`, `:1408`, `:1657` (`toHaveBeenCalledTimes(1)`) and `:1691`. The Model tab is opened 11 times. Exact-name locators for the endpoint control (`{ name: 'Endpoint' }`) appear 5 times (`:204, :321, :465, :697, :747`).
- **Playwright.** The spec routes only `**/api/admin/agent-definitions/workbench` (`:32`, `:64`), `draft/*` (`:33`, `:90`) and the three `draft/*/…` POSTs (`:468-470`). There is **no catch-all**, so an unmocked catalog GET reaches the dev proxy and fails. The Model tab is opened 19 times, and `{ name: 'Endpoint' }` appears 19 times. Playwright matches that substring case-insensitively, so it could multi-match new "endpoint" labels under strict mode.

**Ruling:**
- Task 4 routes every harness **by URL**, with a default accepting catalog response.
- It narrows the GET-count assertions to the workbench URL **without weakening them**, and adds a separate catalog-count assertion.
- It updates each `Endpoint` locator to the new accessible name "Custom endpoint name" in the same commit. The grep count for the old exact name must reach 0, with no assertion deleted.
- The e2e spec gets one shared default catalog route next to the workbench route.
- Task 6 routes the probe POST by URL. The current non-GET branches parse every POST as a PUT (`:183-186`).

Cost if wrong: dozens of unrelated REDs misread as #266 defects, or a harness that silently answers the wrong endpoint.

## Correction 18 — CONFIRMED: the endpoint 422 binding and the unsaved-form retention are already landed

- `INLINE_FIELD_OWNERS['candidate.model.endpoint_name'] = 'endpoint_name'` (`draftEditorState.ts:224`).
- `rejectOperation` for `save` sets `fieldErrors` from the response (`:672`) and leaves `local` untouched.
- `FieldError` renders `role="alert"` (`DefinitionEditor.tsx:88`), and the endpoint input's `aria-describedby` points at it (`:367`).
- The Task 1 table messages contain no endpoint text.

So Task 4's "bind the typed server issue to the custom field without clearing" is consumption, not new work.

**Ruling:** Task 4's only new local check is the URL/path policy (correction 4), added in `validateDraftForm` (`:533`) so a rejected value produces `saveInvalid` with **zero PUT**. It must mirror the server's policy exactly. A join test against the server's policy is recommended. `issueTab`'s `'assembly'` fallback (`DefinitionEditor.tsx:43-51`) never sees the endpoint, because inline-owned issues are filtered out (`:637`).

## Correction 19 — CONFIRMED: text-read joins and the strict-JSON fixture blocks

Files read **as text** by Python tests:
- `test_prompt_assembler.py` (`_read_client` `:959`, root `:921`) reads `frontend/tests/fixtures/mocks.ts` (`:922`), `frontend/src/api/agentDefinitions.ts` (`:923`, `CUSTOM_ANCHORS`/vocabularies `:1181, :1245`), `AssemblyEditor.tsx` (`:924-932`), `draftEditorState.ts` (`:1300-1308`, `LEGACY_COMPOSITE_ROLES`), `frontend/tests/e2e/agent-definition-workbench.spec.ts` (`:1310`, `const AFFECTED_ROLES`), `tests/integration/test_agent_definition_workbench_postgres.py` (`:1313`, `AFFECTED_ROLES = (`), `src/services/prompt_assembler.py` (`:1379`) and **`src/services/graph_configuration_draft.py` (`:1387`, `_LEGACY_SOURCE_ROLES` then `= (`)**.
- `test_agent_definition_workbench_routes.py:3275-3291` `_client_json_fixture` parses `export const NAME:` … `= {` … `\n};` in `mocks.ts` **as strict JSON**. The blocks are `CANONICAL_FIELD_DESCRIPTORS` (`mocks.ts:951`) and `DIAGNOSTIC_NOTES_DESCRIPTORS` (`:932`).
- `_client_rejection` (`test_prompt_assembler.py:1013`) reads `MANUAL_RESOLUTION_REJECTION` (`mocks.ts:1466`), `ALREADY_CURRENT_REJECTION` (`:1479`) and `SCHEMA_ALREADY_CURRENT_REJECTION` (`:1001`). The PostgreSQL suite's `_client_rejection_triple` (`:1129`) reads the first two. Both slice from `source.index("export const NAME")` to the first `\n}`/`\n};`.

**Rulings (Tasks 2, 4, 6):**
- In `graph_configuration_draft.py`, do not introduce a name containing `_LEGACY_SOURCE_ROLES` above `:138` and do not reflow that tuple. All #266 additions go below it.
- In `mocks.ts`, keep those two blocks strict JSON: no comments, no trailing commas, no single quotes.
- Add no constant whose name has one of the five joined names as a prefix above that name. For example, `ALREADY_CURRENT_REJECTION_…` above `:1479` would be matched first.
- New catalog and probe fixtures go at the end of the file.
- Do not reorder `CUSTOM_ANCHORS` in `agentDefinitions.ts`.
- `src/` is also AST- and regex-scanned by `test_agent_schema_registry.py:1314` (only one `class SchemaContractIdentity`), `:1441` (importers of `agent_schema_registry` private names) and `test_app_wheel_dependencies.py:122`. New modules may import only packages already declared in `packages/databricks-tellr-app/pyproject.toml`. `databricks-sdk` and `databricks-langchain` already are.

## Correction 20 — CONFIRMED: CI collection and PostgreSQL enrolment

- `tests/integration/test_agent_definition_workbench_postgres.py` has `pytestmark = pytest.mark.postgres` (`:70`) and is already named in the `integration-graph` run block (`.github/workflows/test.yml:463`). The guard's completeness assertion (`test_ci_collects_integration_tests.py:156-163`) is therefore satisfied. Task 2 needs **no** guard or workflow edit, and Task 5 needs none for the same file.
- All eight PostgreSQL modules in correction 22's matrix carry `pytestmark = pytest.mark.postgres`.
- As in #264's correction 23, `test_conversation_pin_acceptance_postgres.py` is CI-enrolled (guard `:239`) and is **added** to the final matrix. `test_claim_exclusivity_postgres.py` and the other non-slice PostgreSQL modules stay out of this ticket's matrix.

## Correction 21 — Scans

### Per-task internal consistency (Tasks 2–6), against integrated code

| Task | Declared files vs what its own interface and tests need | Verdict / required change |
| --- | --- | --- |
| 2 | The plan's list (`graph_configuration_draft.py`, `graph_configuration.py`, draft unit tests, PG workbench suite) lacks the catalog fix. Its RED `-k endpoint` names no existing test (expected). | CORRECTED: add `model_endpoint_catalog.py` and its test (c3, c4). Save-only phase composition (c6). Constructor injection, no route change (c7). The CI guard needs no edit (c20). |
| 3 | Schema, route and route-test files match. The route needs the injected validator wiring as well as the new GET. | CORRECTED scope: Task 3 also owns the PUT's production validator dependency and the `_app_for` default override (c7). Build the DTOs as new siblings (c9). |
| 4 | The four files lack the workbench owner of the catalog state. Five-leaf assertions are valid only for v1 roles. | CORRECTED: add `AgentDefinitionWorkbench.tsx` (c16). Harness routing by URL and the locator migration (c17). Five-leaf scope (c10). Only the local URL/path check is new (c18). |
| 5 | The listed `test_graph_configuration_workbench.py` does not exist. There is no PG proof for "no lock during invocation". The helper's location is forced. | CORRECTED: create the test file (c14). Add a PG proof to the workbench suite (c13). Put the helper in `agent_runtime.py`, below `invoke`'s catch (c11). `probe(configuration)` (c12). Re-run the policy on the saved name (c4). |
| 6 | Owners exist as listed (`draftEditorState.test.ts` and the e2e spec are present). The matrix names one absent file. | CONFIRMED with Probe as `'probe'` in the one gate (c15). The matrix gains the pin-acceptance suite (c20), and `test_graph_configuration_workbench.py` must exist by then (c14). |

### Pairwise producer/consumer and shared files

| Pair | Producer → consumer | Shared files | Order / ruling |
| --- | --- | --- | --- |
| 1→2 | Policy, remote validator and typed failures → save pipeline | `model_endpoint_catalog.py` (Task 2 fixes c3/c4) | Sequential. Task 2's first commit is the catalog fix. |
| 1→3 | `list_system_models`, `ModelEndpointCatalogFailure`, the fake → GET route | `model_endpoint_catalog.py` (read-only for Task 3) | Sequential after 2, because Task 2's c3 fix is what makes 503 reachable. |
| 2→3 | Constructor injection plus production factory → PUT wiring | `graph_configuration.py` (Task 2), `routes/agent_definitions.py` (Task 3) | Sequential. Task 3 must not re-implement validation. |
| 2→5 | The same facade and `_draft_aggregate_snapshot` → probe read and 409 | `graph_configuration_draft.py`, `graph_configuration.py`, PG workbench suite | Sequential. Never parallel. |
| 3→4 | Exact GET envelope → strict client parser | `agentDefinitions.ts` (Task 4) | Sequential. The backend contract comes first. |
| 3→5 | Route module, schemas, route tests | `routes/agent_definitions.py`, `schemas/agent_definitions.py`, `test_agent_definition_workbench_routes.py` | Sequential. Same three files. |
| 4→6 | Catalog client, catalog state and harness routing → Probe client, state and UI | `agentDefinitions.ts`, `DefinitionEditor.tsx`, `AgentDefinitionWorkbench.tsx`, `AgentDefinitionWorkbench.test.tsx`, `mocks.ts`, e2e spec | Sequential. The same six frontend files. |
| 5→6 | Probe route contract → client parser, `'probe'` gate, UI | `agentDefinitions.ts`, `useDraftEditor.ts`, `draftEditorState.ts`(+test) | Sequential. |
| 2↔4, 2↔6, 3↔6, 4↔5 | None beyond the transitive chain | None directly | No direct shared file, but still serialized by the chain above. |

### Files #266 shares with what #264 just integrated (`git diff --name-only d72ad974d c040dbde0`, 35 paths, intersected with #266's planned or corrected sets under `LC_ALL=C`)

| Shared file | #264 change that matters to #266 |
| --- | --- |
| `src/services/graph_configuration_draft.py` | The fourth entry point `upgrade_draft_schema_contract` (`:428`), the overlay validator in the local tuple (`:250-253`) and the exact-tuple guard (c5, c6). |
| `tests/unit/test_graph_configuration_draft.py` | The guard `:2107` pins both tuples. The save-only ruling keeps it unmodified (c6). |
| `src/api/routes/agent_definitions.py` | The `schema-contract-upgrade` route (`:496-533`) and the overlay `ValidationError` prefix catch in the PUT (`:411-418`), which Task 3 must not reorder. |
| `src/api/schemas/agent_definitions.py` | `selectable_optional_fields` / `canonical_fields` and `EditableSchemaOverlayRequest` (c9). |
| `tests/unit/test_agent_definition_workbench_routes.py` | Strict-JSON fixture joins `:3275-3320` (c19) and overlay invalid-plus-stale 422 `:2865` (a local-phase precedent). |
| `src/services/agent_runtime.py` / `tests/unit/test_agent_runtime.py` | The schema-registry composition in `_run_resolved`, the `ValidatedAgentOutput` callback and the one-binding guard (c11). |
| `frontend/src/api/agentDefinitions.ts` | `upgradeDraftSchemaContract`, the `postDraftOperation` union `'protected-assembly-upgrade' \| 'schema-contract-upgrade' \| 'legacy-prompt-source'` (`:756-760`, which Task 6 extends or bypasses) and overlay types. |
| `draftEditorState.ts` / `draftEditorState.test.ts` / `useDraftEditor.ts` | `'schemaUpgrade'` operation kind and overlay form state (c15). |
| `DefinitionEditor.tsx` / `AgentDefinitionWorkbench.tsx` / `AgentDefinitionWorkbench.test.tsx` | The fourth tab "Output Schema" (`DefinitionEditor.tsx:23-31`), which gives four tabs: Prompt, Model, Output Schema, Assembly. Also the `issueTab` routing (`:43-51`) and the harness GET routing (c17). |
| `frontend/tests/fixtures/mocks.ts` / e2e spec | The strict-JSON blocks and `SCHEMA_ALREADY_CURRENT_REJECTION` (c19), plus 13 new schema e2e tests. |
| `tests/unit/test_ci_collects_integration_tests.py` / `.github/workflows/test.yml` | The overlay PG suite enrolled (`:332`, `test.yml:464`). Nothing is owed by #266 (c20). |

## Correction 22 — Cause baselines at `TASK1_REBASED_HEAD` (causes, not counts)

- **Full unit suite** (`tests/unit -q -p no:randomly -rf`), run twice with the same result: **6 failed, 5900 passed, 110 skipped, 136 warnings**. The six failures are **exactly the controller's integration-head set**, confirmed by traceback:
  1. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available`: `:124 assert 'provisioned' == 'autoscaling'`.
  2. `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails`: `:152 Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
  3–5. `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint` ×3: `AttributeError: '_FakeSession' object has no attribute 'execute'` at `src/services/conversation_pins.py:79`.
  6. `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError: no active Graph Release` at `conversation_pins.py:83`.
  Failures 3–6 share one chokepoint, `_require_active_graph_release` (`:79`/`:83`). There are **zero failures outside the set**, and none of the six is in #266's matrix.
- **Skip causes (110)** from `-rs`: 105 huashu PPTX tests needing node, `services/pptx-emit-huashu/node_modules` and Chrome; 1 RLIMIT_AS not enforced on macOS; 3 documented graph-path RC3/RC6/RC14 non-applicability skips; 1 missing `opentelemetry.exporter` import. **No skip is in #266's matrix.**
- **#266 focused unit matrix** (Task 6 list, excluding the two absent files): `test_model_endpoint_catalog` 19 · `test_graph_configuration_draft` 121 · `test_agent_definition_workbench_routes` 164 · `test_agent_runtime` 31 · `test_persisted_agent_runtime` 108 · `test_prompt_assembler` 79 · `test_agent_schema_registry` 84 · `test_ci_collects_integration_tests` 14. That is **620 passed, 0 failed, 0 skipped**. Absent: `test_model_endpoint_probe.py` (Task 5 creates it) and `test_graph_configuration_workbench.py` (c14).
- **PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`), one invocation per file, **zero skips in every file**: `test_graph_configuration_bootstrap_postgres` 2 · `test_graph_configuration_constraints_postgres` 7 · `test_persisted_graph_runtime_failures_postgres` 7 · `test_conversation_pin_migration_postgres` 1 · `test_conversation_pin_creation_postgres` 2 · `test_agent_definition_workbench_postgres` 15 · `test_agent_schema_overlay_postgres` 10 · `test_conversation_pin_acceptance_postgres` 1 (added per c20). That is **45 passed, 0 failed, 0 skipped**. The dev database `ai_slide_generator` was not touched, and the fixtures own throwaway databases.
- **Warning cause set.** The focused and PostgreSQL runs show five locations: `src/api/schemas/requests.py:53` and `src/api/schemas/responses.py:45` (Pydantic class-based config), `src/api/services/chat_service.py:19` (`langchain-community` sunset), `unitycatalog/ai/langchain/toolkit.py:29` and `databricks_ai_bridge/vector_search_retriever_tool.py:107`. These are identical to phase A's five causes. The full suite's 136 warnings are the broader set #264 recorded; compare by location.
- **Frontend.** `lsof -i :3000` was empty before and after, and no vite/playwright process was left. Commands used only the symlinked `node_modules`, with no install:
  - `npm run test:unit`: **14 files, 333 passed, 0 skipped**, including the four workbench files.
  - `npm run typecheck` (`tsc -b`): exit 0.
  - `npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts`: exit 0 with no findings.
  - `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1`: **60 passed, 0 skipped** (1.1 min).
  - `git status --porcelain` was empty afterwards.
- Any new failure, skip or warning **location** in Tasks 2–6 is a regression even if the counts match. After the Task 2 injection and the Task 5 runtime extraction, re-derive the causes.

## Correction 23 — Rulings summary and task pre-briefs

**Task 2 must be dispatched against these known defects:**
- The catalog fix (c3): builtin `TimeoutError`/`RuntimeError`/transport errors become unavailable, for list **and** get.
- The path-metacharacter policy (c4).
- The save-only local and remote composition that leaves the class tuples and the `:2107` guard untouched (c6).
- Constructor injection with a `None` default and a production factory in `graph_configuration.py`, with no route edit (c7).
- The upgrade entry points must not gain endpoint checks (c6).
- The `_LEGACY_SOURCE_ROLES` text-read hazard (c19).
- The lock-hold decision is parked (c8).
- The plan's two ordering unit cases, the PG stale-loser proof and the sabotage targets stand unchanged. `TASK2_VALIDATOR_BYPASS_SABOTAGE` must hit the save-only remote call, and `TASK2_REVIEWER_STALE_REMOTE_SABOTAGE` moves it above the stale return.

**Task 3:**
- The GET beside `/workbench`, with the catalog obtained through a dependency after `require_admin` and mapped only from `ModelEndpointCatalogFailure` (503 depends on c3).
- The PUT production validator dependency, plus the wiring test and its sabotage, plus the `_app_for` default fake (c7).
- New sibling DTOs (c9).
- Keep the overlay prefix catch position (`:411-418`).

**Task 4:**
- Hoist the catalog state to `AgentDefinitionWorkbench.tsx` (c16).
- The catalog read keeps out of `pendingSave` (c15).
- Harness routing by URL, GET-count narrowing and migration of the 5+19 `Endpoint` locators (c17).
- Five-leaf assertions only on v1 or no-overlay roles (c10).
- The local URL/path check in `validateDraftForm`, mirroring c4 (c18).
- `mocks.ts` strict-JSON and prefix rules (c19).
- Any non-200 other than a valid 403 or 503 becomes an error-with-retry state, never empty.

**Task 5:**
- The helper goes in `agent_runtime.py` below `invoke`'s catch, with one `with_structured_output(` repo-wide in `agent_runtime.py` (c11).
- `probe(configuration)` (c12).
- Read, copy and release inside `with session.begin():`, plus a new PG proof (c13).
- Create `test_graph_configuration_workbench.py` (c14).
- Re-run the policy on the saved name (c4).
- Reuse `_parse_lock_request`, `DraftLockRequest` and `_conflict_response(..., client_candidate=None)` (c9).
- `run`'s arity is untouched (c11).

**Task 6:**
- Probe is `'probe'` in the one gate and `nextRequestIdRef` (c15).
- Route the probe POST by URL (c17).
- The matrix includes the pin-acceptance suite (c20) and requires both new unit files present (c14).
- The final range starts at `IMPLEMENTATION_BASE=c040dbde0` (c1).

**Rulings on plan-versus-code conflicts, with the cost if wrong:**
- c3: outage-time 500s.
- c4: a path-traversal primitive under the service principal, or, if the ruling is wrong, an unsaveable exotic name.
- c6: upgrades acquire invisible endpoint failures, or the stale order inverts.
- c7: a forgotten wire silently fails open; the Task 3 wiring test guards it.
- c8: an outage lock convoy; this is parked for the user.
- c10: correct v2 bodies fail, or tests are weakened.
- c12: a probe that does not match the runtime configuration.
- c13: probes stall every writer.
- c14: the matrix errors on a missing file.
- c15 and c16: gate coupling, or seven catalog GETs.
- c17: dozens of misattributed REDs.
