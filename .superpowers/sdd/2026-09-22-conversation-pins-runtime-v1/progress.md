# SDD ledger — plan: docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md

Execution head before Task 1: `2033f041dd50621f930b1e94ca48558102f3a167`.
Final predecessor authority: `29e03411487476383b34101b7b34513dbb917f26`.
Corrections: `.superpowers/sdd/2026-09-22-conversation-pins-runtime-v1/PLAN-CORRECTIONS.md`.

Environment baseline:
- `/Users/robert.whiffin/.pyenv/shims/python`, Python 3.11.0; `.venv` absent.
- Shared site-packages only; no install or environment creation.
- `frontend/node_modules` is an ignored symlink to the verified #260 dependency tree.

Cause baseline at `2033f041d`:
- Backend exact focused command covering migration/startup/runtime/graph/CI seams: 444 passed, 0 failed, 0 skipped. Warning causes only: existing Pydantic deprecations, `langchain-community` sunset, and PySpark `distutils` version deprecations.
- Frontend unit: 9 files / 90 tests passed. TypeScript typecheck passed. Warning causes only: stale `baseline-browser-mapping` and Browserslist data.
- PostgreSQL-specific new #261 files do not exist yet; each task must execute its real-PostgreSQL tests with zero skips before completion.

Plan-vs-code task self-consistency scan:

| Task | Declared production/test outputs versus current consumers | Finding / ruling |
| --- | --- | --- |
| 1 | Adds nullable pin, migration/backfill/startup, and central engine predicate; current marker lives in `chat_service.py` and startup order is `init_db` then Graph bootstrap then legacy backfills. | Clean after plan explicitly owns `chat_service.py`; preserve behavior while delegating the predicate. |
| 2 | Produces active-release lock and pin loader consumed by creation and graph entry. | Files block omitted `src/services/conversation_pins.py`. Ruling: correction 1 adds it; do not place persistence logic in API modules. |
| 3 | Produces exact-ID complete-release loader from the persisted seven-role aggregate. | Clean; typed `DefinitionContent` and current hash validator are the only content authority. |
| 4 | Replaces runtime construction/signature, adds typed identity sink and test-only compatibility path, and migrates all direct callers. | Clean after four review rounds; provider conversion must occur inside the callback before either sink observes it. |
| 5 | Loads the pin at graph entry, overwrites hostile initial state, propagates through both `Send` payloads/retries/re-review, and migrates shared fakes. | Clean; current `graph_turn_env` invokes the compiled graph directly, so its state seed is mandatory rather than optional fixture setup. |
| 6 | Makes persisted failures escape later-node recovery and emits one safe graph-stream event. | Clean with correction 3 for failures that have no release identity. |
| 7 | Adds safe create/get/list version projection with one active query and joined pins. | Clean; public fields remain the only projection and list must avoid N+1. |
| 8 | Makes browser root creation pre-message graph-capable, persists version state, adds badge/start-latest, and owns Playwright enrollment. | Clean; `api.createSession`, `SessionContext`, and `AppLayout` are all explicitly owned. |
| 9 | Runs real PostgreSQL/compiled-graph acceptance with a global typed output deque and enrolls four PG files in CI. | Clean after review corrections; the fake selects only by explicit role/global segment, never absent payload session IDs. |

Plan-vs-code shared-file/interface scan:

| Tasks | Producer → consumer / shared seam | Finding / required order |
| --- | --- | --- |
| 1 → 2 | `conversation_pins.py`: schema/backfill foundations → active lock/pin loader | Sequential; Task 2 ownership corrected explicitly. |
| 1 → 6 | `chat_service.py`: shared engine predicate → safe pinned-runtime stream failure | Sequential; preserve monolith selection and generic errors outside the typed pinned family. |
| 2 → 7 | `conversation_pins.py`, `session_manager.py`, `routes/sessions.py`: pin creation → response projection | Sequential; reuse `PinnedRelease`, no duplicate active-release query path. |
| 2 → 8 | `CreateSessionRequest.graph_capable` → frontend camel/snake client and browser caller | Backend wire contract must land before UI use. |
| 2 → 9 | active-release lock/session creation → forced publication/session acceptance | Task 9 consumes Task 2 behavior unchanged. |
| 3 → 4 | `PersistedGraphReleaseLoader`/`ResolvedDefinition` → `AgentRuntime` | Sequential exact-ID handoff; no active/latest fallback. |
| 4 → 5 | four-argument runtime + compatibility adapter → every node/fake/direct caller | Sequential signature cutover; Task 5 must rerun all Task 4 caller suites. |
| 4 → 6 | `PersistedRuntimeError` family/provider conversion → selective node rethrow and safe stream | Sequential; ordinary output-validation failures remain recoverable. |
| 4 → 9 | recording identity sink/runtime → end-to-end identity assertions | Task 9 consumes the same production callback semantics with deterministic fakes. |
| 5 → 6 | `nodes.py` propagation/retry/re-review → typed failure escape | Sequential edits to the same recovery blocks. |
| 5 → 9 | graph state/router sends and `test_graph_mode_turn.py` → acceptance capture | Task 9 extends, never replaces, the shipped graph path. |
| 6 → 9 | persisted-failure integration seam → final PostgreSQL matrix/CI enrollment | Task 9 owns final workflow list after Task 6 creates the file. |
| 7 → 8 | safe Graph Version response fields → frontend session state/badge | Wire fields must be stable before UI integration. |
| 7 → 9 | pinned/active projection → V1-old versus V2-active assertions | Task 9 validates exact identities, not counts. |
| 8 → 9 | `.github/workflows/test.yml`: Playwright entry → four backend PG entries | Sequential same-file ownership; Task 9 preserves Task 8 entry. |

Pre-pass rulings:
- Ruling: apply the four `PLAN-CORRECTIONS.md` overrides — they reconcile one omitted shared file, the isolated frontend environment, unavailable pin identity during logging, and review range ownership. Cost if wrong is recorded in the corrections file.
- No other task contradiction, undefined consumer, impossible sabotage, or review-rubric conflict remains after the five independent plan-review rounds.

Task 1: dispatched (base `2033f041dd50621f930b1e94ca48558102f3a167`; implementer `/root/issue_261_task1`; brief `task-1-brief.md`; report `task-1-report.md`).
Task 1: implementer DONE at `22f176453f1cfcb4e9272250422683f4aceaf08f`; PostgreSQL 1, focused 23, regression 444, and engine-mode 33 all passed with unchanged warning causes.
Task 1: controller sabotage independently changed the executed first-message rank predicate from `1` to `2` (`SABOTAGE_CONTROLLER_SECOND_MESSAGE`); the PostgreSQL identity-map test failed, restoration removed the marker, and the same test passed (1 passed). This target is distinct from the implementer targets (null guard, root-owner coalesce, FK delete action).
Task 1: review dispatched with package `review-2033f041d..22f176453.diff`; reviewer `/root/issue_261_task1_review`.
Task 1: review failed — Spec ❌ / Task quality Not approved. Important: `tests/integration/test_conversation_pin_migration_postgres.py` is not enrolled in `.github/workflows/test.yml` `integration-graph`, contrary to the plan-wide CI requirement. Reviewer independently disabled migration invocation: RED because `graph_release_id` was absent; exact restoration: GREEN (1 passed).
Task 1: fix round 1/5 dispatched to original implementer; covering files are `.github/workflows/test.yml`, `tests/integration/test_conversation_pin_migration_postgres.py`, and CI collection guards.
Task 1: fix round 1/5 (1 addressed, 0 open — enrolled the PostgreSQL migration/backfill test in `integration-graph` with a job-specific collection guard; commit `f7a619f98a77b3bbce2d4b34da0f564b0b7d6324`).
Task 1: complete (commits `2033f04..f7a619f`, review clean).
Task 2: dispatched (base `f7a619f98a77b3bbce2d4b34da0f564b0b7d6324`; implementer `/root/issue_261_task2`; brief `task-2-brief.md`; report `task-2-report.md`).
Task 2: implementer DONE at `fd7cccfb38ed0ee42c04dbcfa2f534345a7bb1f1`; unit 12, forced real-PostgreSQL concurrency 2, CI guards 5, and Task 1 regressions 23 passed with zero PostgreSQL skips and unchanged warning causes.
Task 2: controller sabotage independently dropped the locked release ID from new `UserSession` construction (`SABOTAGE_CONTROLLER_DROP_EXPLICIT_PIN`); exact graph-capable-root pin test failed on `None != 41`, restoration removed marker, same test passed.
Task 2: review dispatched with package `review-f7a619f98..fd7cccfb3.diff`; reviewer `/root/issue_261_task2_review`.
Task 2: review failed — Spec ❌ / Task quality Not approved. Important: tests cover the request-model default and direct manager false behavior, but route coverage is true-only; omitted and explicit-false `POST /api/sessions` are not proven unpinned. Reviewer sabotaged route forwarding: RED (1 failed); exact restoration: GREEN (1 passed), marker absent.
Task 2: fix round 1/5 dispatched to original implementer; covering file is `tests/unit/test_conversation_pin_creation.py` and the actual explicit sessions route.
Task 2: fix round 1/5 (1 addressed, 0 open — added real HTTP/FastAPI parsing plus real persistence coverage for omitted and explicit-false requests; commit `000ad593778c51581dc1c4437eeb7519dbf6e1bd`).
Task 2: complete (commits `f7a619f..000ad59`, review clean).
Task 3: dispatched (base `000ad593778c51581dc1c4437eeb7519dbf6e1bd`; implementer `/root/issue_261_task3`; brief `task-3-brief.md`; report `task-3-report.md`).
Task 3: implementer DONE at `1f07630caee7c24081344ac2525325861e046c05`; 17 task tests, 55 focused regressions, and 444 broad regressions passed with unchanged warning causes.
Task 3: controller sabotage independently replaced exact-ID resolution with the active-release predicate (`SABOTAGE_CONTROLLER_ACTIVE_FALLBACK`); persisted V1/V2 ID test resolved V1 as V2 and failed, restoration removed marker and passed.
Task 3: review dispatched with package `review-000ad5937..1f07630ca.diff`; reviewer `/root/issue_261_task3_review`.
Task 3: reviewer disabled the executed direct validation-error conversion; the focused conversion test failed with raw `ValueError`, restoration removed marker and passed.
Task 3: complete (commits `000ad59..1f07630`, review clean; Spec ✅; Task quality Approved; no findings).
Task 4: dispatched (base `1f07630caee7c24081344ac2525325861e046c05`; implementer `/root/issue_261_task4`; brief `task-4-brief.md`; report `task-4-report.md`).
Task 4: implementer DONE at `7295c81f84528cfb168ea2d4940e5991dc093448`; persisted suite 36, focused compatibility/parity 169, live gate 1 environmental skip, Ruff and diff check clean with unchanged warning causes.
Task 4: controller sabotage independently replaced the resolved role passed to the model adapter with `builder` (`TASK4_CONTROLLER_ROLE_SABOTAGE`); the exact persisted-runtime identity/role test failed on `builder != architect`, restoration removed the marker and the same test passed.
Task 4: review dispatched with package `review-1f07630ca..7295c81f8.diff`; reviewer `/root/issue_261_task4_review`.
Task 4: review failed — Spec ❌ / Task quality Not approved. Important: non-SQLAlchemy session-factory construction/context-entry failures escaped instead of mapping to `lakebase_unavailable`; the required `agent_runtime_identity.py` module was absent; exact loader/endpoint/contract/no-fallback assertions were incomplete. Reviewer independently replaced the production logging sink with the recording sink: exact construction node RED, restoration GREEN, marker absent.
Task 4: fix round 1/5 dispatched to original implementer; covering files are `src/services/agent_runtime.py`, `src/services/persisted_graph_release.py`, new `src/services/agent_runtime_identity.py`, and persisted/runtime unit tests.
Task 4: fix round 1/5 implementation at `9e9be573e` — moved identity seam to its required module, mapped factory/open failures narrowly, added exact persisted identity/config/contract/one-endpoint/no-fallback assertions; focused 188 passed, Ruff/diff clean.
Task 4: fix round 1/5 (3 addressed, 0 open; commits `7295c81..9e9be573`).
Task 4: complete (commits `1f07630..9e9be573`, review clean after fix round 1; Spec ✅; Task quality Approved; no findings).
Task 5: implementer DONE at `439971b34`; 524 passed with one expected live-model spend-opt-in skip, Ruff and diff checks clean, and warning/skip causes unchanged.
Task 5: controller sabotage independently changed only the Architect runtime call from the authoritative state pin to `state["graph_release_id"] + 1000` (`TASK5_CONTROLLER_ARCHITECT_PIN_SABOTAGE`); the exact runtime seam test failed on `1001 != 1`, restoration removed the marker, and the same test passed. This differs from the implementer's entry/fan-out/retry/re-review/fixture targets and leaves the state-schema target to the reviewer.
Task 5: reviewer independently removed the `GraphState.graph_release_id` single-writer declaration; the annotation test failed because the key was missing, exact restoration removed the marker, and the same test passed. Spec ✅; Task quality Approved; no findings.
Task 5: complete (commits `9e9be57..439971b`, review clean).
Task 6: implementer DONE at `785d9aaca`; focused 193 and real-PostgreSQL 7 passed with zero skips, task-owned Ruff/format/diff checks clean, and legacy warning/Ruff cause sets unchanged.
Task 6: controller sabotage independently replaced exact release-ID selection with the active-release predicate (`TASK6_CONTROLLER_ACTIVE_FALLBACK_SABOTAGE`); the nonexistent/incomplete exact-loader PostgreSQL cases both failed because the active V2 was returned instead of either requested failure, exact restoration removed the marker, and the same cases passed (2 passed, 0 skipped). This differs from the implementer's public-envelope target and leaves one later-node re-raise bypass to the reviewer.
Task 6: review failed — Spec ❌ / Task quality Needs fixes. Important: after the private safe event, the typed exception is re-raised and both SSE and polling stringify it into a second/unsafe public error; outer route/job-worker handlers also duplicate-log the exception message and traceback after the identity-safe log. Reviewer Deck Reviewer re-raise bypass: RED 1 failed/0 skipped; restoration GREEN 1 passed/0 skipped.
Task 6: minor (deferred): focused Task 6/reviewer test output retains established third-party deprecation warning causes.
Task 6: Ruling: permit the smallest Task 6 edits to `src/api/routes/chat.py` and `src/api/services/job_queue.py` required to make typed pinned-configuration failure terminal and transport-safe. The issue/spec's exact public envelope and no-leak/no-trace requirements override the plan's general #262 file-ownership boundary; chat creation, auto-create, contributor/duplicate, and mixed-release behavior remain forbidden. Cost if wrong: #262 may need a small conflict resolution in these transport handlers, but leaving exact release IDs publicly/logically exposed is a security/correctness defect.
Task 6: fix round 1/5 dispatched to original implementer; covering seams are public SSE, async job/poll, and their outer logging handlers plus the existing private persisted-failure suite.
Task 6: fix round 1/5 implementation at `77e42b3c1` — made the typed pinned failure terminal across SSE and async worker/poll, added exact public transport/no-duplicate-log coverage; focused public 2, PostgreSQL 7/0 skipped, graph/runtime/transport 223, and job-queue 8 passed.
Task 6: observation (deferred to final review): the fix-round sabotage exposed a pre-existing generic job-worker error branch that can pop `jobs[request_id]` before wrapper handling; the typed pinned-failure path no longer enters it and this fix did not broaden generic error semantics.
Task 6: fix round 1/5 (2 addressed, 0 open — made typed pinned failures terminal and safe across SSE and async worker/poll transport, with no outer identity/trace re-log; commit `77e42b3c1`).
Task 6: complete (commits `439971b..77e42b3`, review clean after fix round 1; Spec ✅; Task quality Approved; no findings).
Task 7: dispatched (base `77e42b3c170373407afddc1c98d982af5c3806fa`; implementer `/root/issue_261_task7`; brief `task-7-brief.md`; report `task-7-report.md`).
Task 7: implementer DONE_WITH_CONCERNS at `b988ff7db9acf2136d9c30d2b452925480798b33` (implementation `677fade7f`); focused projection/routes 88 passed, 2 established route skips; broader creation regression had 5 failures with one cause: Task 2 fixtures create no active release or return a nonexistent mocked pin.
Task 7: Ruling: permit the smallest fixture-only update to `tests/unit/test_conversation_pin_creation.py` so all pre-existing creation regressions seed a real active release and any mocked pin refers to a real row. Task 7 makes missing active/dangling pinned releases explicit integrity errors, so retaining impossible fixtures would accept a known red regression. Production behavior and Task 2 creation semantics must not change. Cost if wrong: a fixture could conceal an unintended dependency on active release state, so the task reviewer must inspect and sabotage query shape independently.
Task 7: concern resolved at `6d8fa37fbb63c2eff2716707a15f9d2c6677e032`; creation unit 14 passed and combined projection/creation/routes 102 passed with 2 established MLflow skips and unchanged warning causes.
Task 7: controller sabotage replaced the batch projection with an executed per-session helper loop (`TASK7_CONTROLLER_N_PLUS_ONE_SABOTAGE`); the exact query-shape test failed on 4 Graph Release queries instead of 2, restoration removed the marker and the same test passed. Evidence: `task-7-controller-sabotage.md`.
Task 7: review failed — Spec ✅ / Task quality Needs fixes. Important: direct regression coverage is missing for non-integer single pins, dangling batch-join referents, and requested sessions omitted from the batch projection. Production behavior is approved; correction is test-only. Reviewer independently inverted the batch missing-session guard: RED 1 failed, restoration GREEN 1 passed, marker absent.
Task 7: fix round 1/5 dispatched to original implementer; covering file is `tests/unit/test_conversation_graph_version_responses.py`, with no production change permitted.
Task 7: fix round 1/5 (1 addressed, 0 open — added direct coverage for non-integer single pins, dangling batch referents, and omitted batch rows; commit `0b1b37501`).
Task 7: complete (commits `77e42b3..0b1b375`, review clean after fix round 1; Spec ✅; Task quality Approved; no findings).
Task 8: dispatched (base `0b1b375016f70ff499175d7435b40ac4ac285548`; implementer `/root/issue_261_task8`; brief `task-8-brief.md`; report `task-8-report.md`).
Task 8: implementer DONE at `87dc8fd7d` (implementation `2544ab35c`); Vitest 95/95, typecheck clean, focused Chromium 4/4, E2E matrix guard 4/4; no concerns.
Task 8: controller sabotage independently bypassed the null-version status branch (`TASK8_CONTROLLER_NULL_STATUS_SABOTAGE`); the exact null-state test failed 1/5 because the UI invented the ordinary version rendering, restoration removed the marker and the same focused suite passed 5/5. Evidence: `task-8-controller-sabotage.md`.
Task 8: reviewer independently inserted an executed old-A PATCH before switching to B; the focused Start-latest Playwright case failed on `Received: ["PATCH"]`, exact restoration removed the marker and passed 1/1. Spec ✅; Task quality Approved; no Critical/Important findings.
Task 8: minor (deferred): direct API coverage asserts explicit `graphCapable:true` but not the otherwise-correct default/explicit-false serialization branch; final whole-branch review must triage it.
Task 8: complete (commits `0b1b375..60d64cc`, review clean with 1 deferred minor).
Task 9: implementation started from exact base `a98fdc313b90f07639e32081f6c5c979225f89e6`; no pre-existing worktree changes and `.venv` absent.
Task 9: TDD RED — the new job-specific acceptance enrollment guard failed because `tests/integration/test_conversation_pin_acceptance_postgres.py` was absent from `integration-graph`; GREEN after adding the deterministic PostgreSQL acceptance and workflow entry.
Task 9: implemented one global 25-entry typed adapter deque with exact A/1 (10), A/2 (5), B/1 (10) segmentation; real PostgreSQL migration/models/bootstrap, session creation, persisted loader/runtime, compiled graph/checkpointer, recording identity sink, and deep-copied real Send payloads. Every segment asserts exact graph version, release, revision, hash, role order, Builder/Build Reviewer pins, and no Foreman identity.
Task 9: falsification — V2 hash corruption RED on persisted hash validation; active-ID fallback RED on A graph version 2 versus 1; C-reuses-A pin RED on C version 1 versus latest 2. Reviewer re-fan's first sabotage missed because the builder record retained the pin; strengthened executed-payload deletion RED on Build Reviewer KeyError/6-versus-10 identity segment. Every marker was restored and the acceptance returned GREEN after each.
Task 9: Ruling: the brief's `cd frontend && npm test -- --run` is stale because current `npm test` invokes Playwright and rejects Vitest's `--run`. Run the repository's actual `npm run test:unit` (`vitest run`) as the exact unit-suite equivalent, while recording the literal command's CLI failure. Cost if wrong: a future package-script rename could make the equivalence stale, so the final review must check `frontend/package.json` rather than trusting the command name.
Task 9: concrete gates — PostgreSQL 11 passed / 0 skipped; focused backend 525 passed / 0 skipped; frontend unit 10 files / 95 tests; TypeScript clean; focused Chromium 4 passed outside the macOS browser sandbox after the sandbox-only Mach-port denial; CI/E2E guards 11 passed. Warning cause sets only established Pydantic, langchain-community, Unity Catalog/Databricks bridge, PySpark distutils, baseline-browser-mapping, and Browserslist deprecations/staleness.
Task 9: implementer DONE at `a4c65e427` (implementation `71901d2ba`); implementation self-review clean, task report `task-9-report.md`, no concerns.
Task 9: controller sabotage independently forced the executed single-session old-version projection false (`TASK9_CONTROLLER_OLD_PROJECTION_SABOTAGE`); the real PostgreSQL acceptance failed on A `(1, 2, False)` versus `(1, 2, True)`, exact restoration removed the marker and passed 1/1 with the same established warning causes. Evidence: `task-9-controller-sabotage.md`.
Task 9: review failed — Spec ❌ / Task quality Needs fixes. Important: the exact turn identity was synthesized because both expected and actual tuples copied the segment's declared session/turn; changing A/2 from turn 2 to 999 stayed green. The remaining PostgreSQL state machine, identity, Send-pin, persistence, and CI requirements were approved.
Task 9: fix round 1/5 implemented an observed checkpoint envelope in the acceptance test only. It scans the real saver history oldest-first, derives the per-session ordinal from distinct persisted opaque turn IDs, matches the graph result exactly once, and confirms the observed turn is the session's latest checkpoint; caller declarations now occur only on the expected side.
Task 9: fix-round falsification independently changed declared A/2 turn 2 to 999 under `TASK9_TURN_BLIND_SPOT_REPRO`; real PostgreSQL RED compared observed turn 2 with expected 999. Exact restoration removed the marker and returned GREEN (1 passed / 0 skipped). Fresh gates: PostgreSQL matrix 11 passed / 0 skipped; focused backend 525 passed / 0 skipped; acceptance restoration 1 passed / 0 skipped; Ruff check/format and `git diff --check` clean. Cause sets remain established LangChain, Pydantic, Unity Catalog/Databricks bridge, PySpark, and route-model deprecations only.
