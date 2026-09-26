# #267 Task 2 — independent task review

Reviewed range: TASK_BASE `9c75074b2`..`1c9936818` (HEAD `78badbcd1` adds a docs-only commit). Temporary worktree: `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-267-2`, now removed. I read the brief, Corrections 9, 22, 23, 36 and 38, the progress rulings (P2, P3, P5, and Task 2's concerns 1, 2 and 4), the report, and #269's Correction 1, Correction 2, Correction 20 and plan lines 206–212 and 725.

## Spec Compliance: ✅ (with ⚠️)

**✅ Met:**
- **C9, the refusal:** both refusals fire before any row changes: `deactivate_test_case` of the last required case, and `update_test_case(is_required=False)` on it. The supersede case is also covered.
- **C9, the envelope:** the body is `invalid_test_case` with ordered `DraftFieldErrorResponse` items.
- **C9, the lock:** L2 is `SELECT … WHERE agent_key=:k ORDER BY id FOR UPDATE`, with no `is_active` filter (`agent_test_workbench.py:144-156`). The writer takes no L0 lock and makes no remote call.
- **C22, supersede:** the old row is retired and `version + 1` is inserted in one `session.begin()` (`:422-468`). A rename returns `name_immutable`. A unique-constraint loss returns 409 `stale_test_case`.
- **C22, validation:** there is no sentinel. The payload must be a JSON object of at most 64 KiB, serialized compactly with `allow_nan=False`. `assembly_context` must be exactly `{design_system_active: bool}` in both the DTO and the service. `name` is trimmed, non-blank and at most 200 characters.
- **C23/C36:** the four routes are on the one existing router, at `routes/agent_definitions.py:882-989`. There is no second router, and `main.py` is untouched. POST and PUT parse the body only after `require_admin` and `require_draft_write_principal`. The writer runs off the loop on all four routes, and a loop-observer test is parametrized over all four (`test_agent_definition_workbench_routes.py:5172-5212`).
- **Scope:** `git diff --stat` touches exactly the six planned files plus the report. Bootstrap, seed, hashing and existing routes are unchanged.

**⚠️ Not yet met:**
- The controller's no-op ruling for Task 2's concern 1 is not implemented. See I1.
- C22 requires the supersede to be "in one transaction", and nothing enforces that. See I2.

## Strengths
- **Lock placement.** The lock-then-re-read placement is correct. The only pre-lock read is the `agent_key` column (`:505-507`), so the identity map cannot serve a stale entity, and `populate_existing` is set on both the lock and the re-read.
- **Retirement order.** The supersede retires the old row before it inserts the successor, so #269's L2 `FOR SHARE` on an active required row also blocks re-versioning, not only deactivation. This is stronger than #269 C20 assumed.
- **Issue ordering.** `TestCaseRejected` sorts issues by one tuple, `_FIELD_ORDER`. So the ordering holds wherever issues are appended.
- **Duplicate names.** The duplicate-name path moved onto the unique constraint (`805c250f9`). That is the right fix for a pre-check the mutation sweep showed was redundant.
- **Test quality.** The two-session PostgreSQL test pauses on the real UPDATE and observes a real `pg_locks` waiter, so it proves serialization and not just the outcome.
- **Controller sabotage reproduced.** The report's mutation table is internally consistent, and it matches my two runs: the baseline GREEN counts were 325 unit and 20 PostgreSQL.

## Lock order and deadlock ruling (named risk)
- **No deadlock path exists**, for four reasons:
  - The case writer acquires only L2 row locks, in ascending `id`, on one role. It never waits on L0 or L3 while holding L2.
  - `agent_test_case` has no foreign keys, and `agent_test_run.test_case_id` is a plain integer. So neither the successor INSERT nor a Task 4 run INSERT takes an implicit `KEY SHARE`.
  - #269's gate takes release and draft L0, then `FOR SHARE` on the active required case rows of the changed roles, also in ascending `id` (plan `:725`). Two lockers that both acquire in ascending `id` (the gate over a subset of rows, the writer over a superset) cannot cycle. PostgreSQL applies LockRows above the Sort, so rows are locked in `ORDER BY` order.
  - Bootstrap, both today and after #269 C2 (advisory lock, then L0 `FOR SHARE`), reads cases without a lock, so it never waits on L2.
- **Benign interaction (for #269 Task 4):** if a supersede of a role's only required case commits while the gate waits on that row, PostgreSQL's EvalPlanQual recheck drops the retired row. The successor's INSERT is not in the gate's snapshot. The gate then reports a spurious `no_required_case`, which is an over-refusal that a retry fixes. It is not an under-refusal.
- **AC1 bootstrap invariant:** it is preserved for the atomic path as built. It is not proven for a split supersede (see I2).

## Issues

### Critical
None.

### Important

**I1 — an identical update still supersedes, so an unchanged save orphans approvals**
- **Where:** `src/services/agent_test_workbench.py:436-468`.
- **What:** the controller's ruling for Task 2's concern 1 says an update whose content equals the current version must be a no-op: 200, the current snapshot, no new version and no retire. The code always retires the old row and inserts `version + 1`.
- **Why:** approvals (#268, and #269's gate on `(test_case_id, test_case_version)`) are recorded against the current id. An identical resubmit from the UI would silently invalidate them.
- **Fix.** I agree with the ruling. Implement it like this:
  - Put the no-op check **inside** the lock, after the `name` validation and after the `not old.is_active → TestCaseStale` check. An identical PUT to a superseded id must stay 409.
  - Return `TestCaseVersion.from_row(old)` without touching `updated_by` or `updated_at`.
  - **Do not compare with Python `==` on dicts.** In Python, `{"a": 1} == {"a": True} == {"a": 1.0}`. I re-probed this and it returns `True True`. A change from `1` to `true` would therefore be dropped as a no-op.
  - Compare canonical serializations instead: `json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` for `synthetic_payload` and for `assembly_context`, plus `is_required is old.is_required`. Sorting the keys also absorbs JSONB's key reordering.
- **Tests:**
  - an identical PUT returns 200 with the same `id` and `version`, the exact row tuples are unchanged, and the row count is unchanged;
  - `1` → `true` and `1` → `1.0` in the payload each **do** create `version + 1`;
  - an identical PUT on a superseded id is 409;
  - an identical PUT that echoes the name is still a no-op.
- **Sabotage for the fix round:** replace the canonical comparison with `==`. Predicted RED: the `1` → `true` test.

**I2 — C22's "one transaction" supersede is unpinned: splitting it into two commits leaves every test GREEN**
- **Where:** `src/services/agent_test_workbench.py:448-468`. The tests are in `tests/unit/test_agent_test_workbench.py` and `tests/integration/test_agent_definition_workbench_postgres.py`.
- **What:** I tried two split-commit mutations (evidence below). Both left 325/325 unit and 20/20 PostgreSQL tests GREEN:
  - insert and commit the successor, then retire the old row in a second transaction;
  - retire and commit the old row, then insert in a second transaction.
- **Why:**
  - Insert-first exposes two active versions of one lineage to readers between the commits. #269's gate and #268's readiness would both count them, which is exactly the harm C22 names.
  - Retire-first exposes zero active versions. If the insert then fails for any reason other than a version collision, the retirement stays committed. If that case was the role's only required case, the next boot exits (C9's cost). So this regression breaks the AC1 invariant, and nothing catches it.
  - The comment at `:451-452` states the invariant, but no test holds it.
- **Fix:** add these tests:
  - **Unit, atomicity:** count `after_commit` events on the session during one `update_test_case`, and assert exactly 1.
  - **Unit, failure injection:** make the successor INSERT raise a non-collision error, for example with a `before_cursor_execute` listener that raises `OperationalError` on `INSERT INTO agent_test_case`. Then assert the old row's exact tuple is unchanged and still active, the row count is unchanged, and bootstrap still returns OK.
  - **PostgreSQL, optional:** pause the writer after the successor INSERT, before it commits. From a second session, assert the lineage has exactly one active row, the old one.

**I3 — the two-session PostgreSQL test cannot detect the last-required guard counting only `is_active`**
- **Where:**
  - the test: `tests/integration/test_agent_definition_workbench_postgres.py:1948-2060`;
  - the predicate: `src/services/agent_test_workbench.py:182-183`.
- **What:** the controller assigned this mutation: make `_active_required_count` count `row.is_active` only. It went RED on exactly one unit test and left the two-session PostgreSQL test GREEN (20/20). The PostgreSQL setup gives architect only two cases, and both are required, so "active" and "active and required" are the same count there. A second weakness: only one unit test catches the mutation (`test_optional_and_inactive_rows_do_not_count_as_required_coverage`). No route test and no update-path test catches it, because the update-path refusal tests have no active optional row.
- **Why:** the controller required both RED. The concurrency proof of the AC1 guard should not depend on the role having no optional cases, because real roles will have them.
- **Fix:**
  - In the two-session test's setup, add one **active optional** architect case. Under the mutation, both retirements then see a count of 3 or 2 and both commit, so bootstrap raises and the test goes RED. The correct code is unchanged.
  - Add an update-path unit case: with an active optional case present, `is_required=False` on the only required case is still 422.

### Minor

**m1 — wrong path and query types get FastAPI's default 422 envelope**
- **Where:** `routes/agent_definitions.py:887-889`, `:932`, `:972`.
- **What:** a non-integer `{test_case_id}`, or a value like `include_inactive=maybe`, gets FastAPI's default `{"detail": [...]}` 422, not `invalid_test_case`.
- **Assessment:** authorization still runs first, because `require_admin` is a router dependency. This is consistent with the rest of the router, which uses no custom path or query rendering.
- **Ruling:** acceptable. Record it in the Task 6 client contract so the client does not strict-parse these as `invalid_test_case`.

**m2 — PUT with an invalid body on an unknown id returns 404, not 422**
- **Where:** `agent_test_workbench.py:416-423`.
- **What:** content issues are computed first but raised only after `_lock_role_of`, so a missing id wins.
- **Ruling:** acceptable, and arguably correct. Add a one-line pin, or state it in the docstring, so the order is deliberate.

**m3 — nothing pins the `updated_at` refresh on the retired row**
- **Where:** `agent_test_workbench.py:450`.
- **What:** `old.updated_at = func.now()`. On PostgreSQL this is the transaction start time, so it equals the successor's `created_at`. That is fine, but it is not pinned beyond "changed".
- **Ruling:** no action required.

**m4 — the 404 uses the plain `{"detail": "Test case not found"}` body**
- **Where:** `routes/agent_definitions.py:843`.
- **Ruling:** acceptable (the report's concern 3). Record it for the Task 6 parser.

## Sabotage evidence

Environment for every row:
- Temporary worktree `rev-267-2` at `1c9936818`.
- `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/rev-267-2.sqlite /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly`.
- PostgreSQL runs add `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, with one file per invocation and zero skips.
- `test ! -e .venv` held before and after.

The scopes are:
- **Unit:** `tests/unit/test_agent_test_workbench.py tests/unit/test_agent_definition_workbench_routes.py`.
- **PostgreSQL:** `tests/integration/test_agent_definition_workbench_postgres.py`.

The pre-sabotage baseline was GREEN: 325 unit passed, and 20 PostgreSQL passed with 0 skips.

| ID | Mutation | Anchor | Marker `grep -c` | Unit | PostgreSQL | Restore | GREEN after |
|---|---|---|---|---|---|---|---|
| REV267_2_ACTIVE_ONLY (controller-assigned) | `_active_required_count`: `if row.is_active and row.is_required` → `if row.is_active` (the refusal predicate; the lock is untouched) | 1 | 1 | **RED 1 failed / 324 passed:** `test_agent_test_workbench.py::test_optional_and_inactive_rows_do_not_count_as_required_coverage` | **GREEN 20 passed.** Not caught; the two-session test does not go RED (I3). | `git checkout 1c9936818 -- src/services/agent_test_workbench.py`; `git diff --exit-code` clean | service file 53 passed |
| REV267_2_SPLIT_SUPERSEDE (own) | Insert and commit the successor in the first `session.begin()`, then retire the old row in a second `session.begin()`, so two versions are briefly active | 1 (script-asserted `count(old) == 1`) | 1 | **GREEN 325 passed.** Not caught. | **GREEN 20 passed.** Not caught. | same; clean | — |
| REV267_2_RETIRE_COMMITS_FIRST (own, the variant) | Retire and commit the old row in the first transaction, then insert the successor in a second one | 1 (script-asserted) | 1 | **GREEN 325 passed.** Not caught. | **GREEN 20 passed.** Not caught. | same; clean; `git status --porcelain` empty; no `REV267_2` marker left | 325 unit, 20 PostgreSQL |

After the last restore, the unit scope passed 325 and the PostgreSQL file passed 20. The worktree was removed (`git worktree remove`, then `prune`), and `git worktree list` shows no `rev-267-2`. The controller's spent target, the unknown-agent-key guard, was not repeated.

## Task quality: Needs fixes

The fix round must address I1, I2 and I3. None is Critical: the code as built is atomic and correct. I2 and I3 are test gaps on the two invariants that protect boot, and I1 is the controller's outstanding ruling.
