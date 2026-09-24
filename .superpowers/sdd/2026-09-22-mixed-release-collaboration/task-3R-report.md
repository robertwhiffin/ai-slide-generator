# Task 3R report — repair the four C-11 regressions

Status: **DONE_WITH_CONCERNS** (one substantive finding that narrows C-11's R1 claim; see
"Finding that changes a ledger claim". No gate failed, no invariant weakened.)

Base: `cf9fa4c393efa16baf0213018c524bc747127797` (verified before starting).
HEAD: `a7fc0ae2c47d8d09107358efcbb772ff8370f8c2` on `plan/conversation-collaboration-262`.
Both `795262c16` and `cf9fa4c39` are ancestors of HEAD. Worktree clean.

## Commits

| SHA | Cause | Subject |
| --- | --- | --- |
| `73bf7cdf4` | R1 | `fix: generate collaboration identities server-side (#262)` |
| `0b5545a0c` | R2 | `test: seed the active release for marker-carrying duplicates (#262)` |
| `4abd82dd1` | R3 | `test: exercise the threaded mutation context on both workers (#262)` |
| `a7fc0ae2c` | R4 | `test: prove the restore event's actor derivation (#262)` |

R1 is the only production change. R2–R4 are test/double changes, as their causes require.

## Import provenance (proved once, used for every command below)

```
cd /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-262-plan
export PYTHONPATH=/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-262-plan:/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-262-plan/packages/databricks-tellr
/Users/robert.whiffin/.pyenv/shims/python -c "..."
```

```
python: 3.11.0
executable: /Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python
databricks_tellr: /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-262-plan/packages/databricks-tellr/databricks_tellr/__init__.py
src: /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-262-plan/src/__init__.py
databricks-sdk: 0.112.0
```

Both `databricks_tellr` and `src` resolve inside this worktree, not the foreign clone the
ledger warns about. No `pip install`, no `uv`, no `.venv`, no `npm`, no Playwright.

## Baseline reproduced before any change

```
$ python -m pytest <the seven affected files> -p no:randomly -q
15 failed, 76 passed, 5 warnings in 4.41s
```

The 15 FAILED node IDs matched the brief's enumeration exactly, name for name.

---

## R1 — `NOT NULL constraint failed: user_sessions.collaboration_identity` (7 tests)

### RED first, for the production defect

Two new tests in `tests/unit/test_database_migrations.py`, written before touching any
fixture or model:

```
$ python -m pytest tests/unit/test_database_migrations.py -k collaboration_identity -q --tb=line
.../sqlalchemy/engine/default.py:941: sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: user_sessions.collaboration_identity
tests/unit/test_database_migrations.py:476: AssertionError: a post-migration raw insert into user_sessions got no identity: ['6e2db94ff8ac73b8bfa99a7962b8d946', 'facc5010e6fb6c1117a1ff8affccf8b8', 'c414d29fad004888881cd397dcbab8ac', None]
FAILED tests/unit/test_database_migrations.py::test_collaboration_identity_is_server_generated_on_a_fresh_schema
FAILED tests/unit/test_database_migrations.py::test_collaboration_identity_backfill_and_default_on_the_legacy_alter_path
2 failed, 6 deselected
```

Two distinct real reasons: the fresh `create_all` schema rejects the insert outright, and the
legacy ALTER path accepts it but stores NULL. Note the backfill half of the second test passed
from the start — the migration's existing `UPDATE ... WHERE collaboration_identity IS NULL` was
already correct and per-row distinct; I verified `randomblob`/`gen_random_uuid` are evaluated
per row rather than once per statement.

### The fix

`src/database/models/session.py` — the column now declares a dialect-dispatched
`server_default` via a `FunctionElement` with `@compiles` overloads, kept alongside the
existing `default=uuid.uuid4` (an ORM insert still gets its UUID without a RETURNING
round-trip):

```
user_sessions       sqlite      -> collaboration_identity CHAR(32) DEFAULT (lower(hex(randomblob(16)))) NOT NULL
user_sessions       postgresql  -> collaboration_identity UUID DEFAULT gen_random_uuid() NOT NULL
session_slide_decks sqlite      -> collaboration_identity CHAR(32) DEFAULT (lower(hex(randomblob(16)))) NOT NULL
session_slide_decks postgresql  -> collaboration_identity UUID DEFAULT gen_random_uuid() NOT NULL
```

SQLAlchemy's SQLite DDL compiler supplies the parentheses SQLite requires for an expression
default, so the compiler function does not add them.

`src/core/database.py` — `_migrate_shared_deck_mutation_schema`'s SQLite branch gains an
idempotent `CREATE TRIGGER IF NOT EXISTS ... AFTER INSERT ... WHEN NEW.collaboration_identity
IS NULL`. This is necessary because SQLite rejects a non-constant default in `ALTER TABLE ADD
COLUMN` ("Cannot add a column with non-constant default") and has no `ALTER COLUMN SET
DEFAULT`; I probed both. Without it a legacy SQLite table would let a raw insert store NULL,
after which every mutation on that row fails in `shared_deck_attribution` with
`"collaboration identities must exist before mutation evidence"`.

**Migration placement.** No ordering decision was needed and none was guessed. I modified the
existing `_migrate_shared_deck_mutation_schema` in place; its registry position (immediately
after `_migrate_conversation_pin_schema`, before
`_install_graph_configuration_mutation_guards` and `_reassign_new_objects_to_shared_owner`) is
unchanged, and the documented reasons for that position still hold — the new trigger is a
SQLite object created before the owner-reassignment pass, like its siblings.

`nullable=False` is retained on both models, and `_reject_collaboration_identity_change` is
untouched (`tests/unit/test_shared_deck_attribution.py::test_collaboration_identities_are_immutable_through_the_orm`
passes).

### GREEN

```
$ python -m pytest tests/unit/test_database_migrations.py -q
9 passed

$ python -m pytest tests/unit/test_deck_permissions_migration.py tests/unit/test_deck_workspace_sharing_migration.py \
    tests/unit/test_drop_config_prompt_columns.py tests/unit/test_spec_dirty_marker.py -q
38 passed
```

### Sabotage verification

| Sabotage | Result |
| --- | --- |
| A — `server_default` removed from both columns | RED: `NOT NULL constraint failed: user_sessions.collaboration_identity` |
| B2 — the SQLite legacy trigger creation excised | RED: `a post-migration raw insert into user_sessions got no identity: [..., None]` |
| M2 — `server_default` removed, column-definition guard | RED: `user_sessions.collaboration_identity has no server-side default; every non-ORM insert omitting it would violate NOT NULL` |
| N — column default **and** the PG migration's `SET DEFAULT` removed | RED on PostgreSQL: `(psycopg2.errors.NotNullViolation) null value in column "collaboration_identity" of relation "user_sessions" violates not-null constraint` |

An earlier attempt at B (renaming the trigger) did **not** go red — renaming a trigger does
not disable it. I recorded that as an ineffective sabotage and replaced it with B2, which
removes the creation outright.

---

## Finding that changes a ledger claim (the reason for DONE_WITH_CONCERNS)

Sabotage M (removing only the model `server_default`) left the **PostgreSQL** suite green:

```
--- SABOTAGE M: server_default removed, PostgreSQL ---
3 passed
```

Cause: on non-SQLite dialects `_migrate_shared_deck_mutation_schema` already ran
`ALTER TABLE ... ALTER COLUMN collaboration_identity SET DEFAULT gen_random_uuid()`
unconditionally, and `_run_migrations` runs at startup after `create_all`. So on PostgreSQL a
startup-migrated deployment already had a working server-side default.

**C-11's R1 wording — "Any non-ORM insert path ... fails in production exactly as these tests
do" — is therefore too strong for PostgreSQL.** The observed 7 failures were SQLite-only in
their manifestation. I am reporting this rather than restating the ledger's claim.

The defect is still real and still worth the production change, in a narrower form:

1. The ORM metadata did not declare the default, so the schema `create_all` produces is wrong
   on **every** dialect and was being repaired afterwards by a startup migration. Any path
   that builds the schema from metadata without `_run_migrations` — which several suites and
   this repo's own `tests/unit/conftest.py` do — gets a `NOT NULL` column with no default.
2. On SQLite it fails outright, which is how it surfaced.
3. Depending on a repair migration to fix a column `create_all` just created is a brittle
   ordering coupling; the column is now the single source of truth for both dialects.

To pin the invariant where the PostgreSQL mask cannot reach it, I added
`test_collaboration_identity_column_declares_a_server_default_per_dialect` — a
dialect-independent assertion on the column definition and its compiled DDL. Sabotage M2 above
shows it fires. Sabotage N shows the PostgreSQL insert test has teeth once the mask is also
removed.

I did **not** remove the migration's `SET DEFAULT`: it is correct, idempotent, and is what
repairs already-deployed databases.

---

## R2 — `ActiveGraphReleaseUnavailableError: no active Graph Release` (4 tests)

RED, all four for the real reason:

```
src/services/conversation_pins.py:74: ActiveGraphReleaseUnavailableError: no active Graph Release   (x4)
4 failed, 1 passed
```

Repair in `tests/unit/test_engine_mode_selection.py`: a helper publishes a superseded release
(`effective_to` set) **and** the active one (`effective_to IS NULL`), and pins the **source**
session to the **superseded** one. Pinning the source to the older release is what makes the
repair provable rather than merely passing: the copy must carry the release locked at its own
creation, so copying the source pin or selecting none is observable.

```
$ python -m pytest tests/unit/test_engine_mode_selection.py -q
33 passed
```

Each of the four still proves what it was written for (mode stickiness, marker-row-only copy,
contributor resolution, marker timestamp ordering). Added, not substituted: the graph-mode and
contributor cases assert the copy's pin is the active release and the source's is still the
superseded one; the monolith case (already passing) now also proves an available active
release does **not** pin a non-graph copy.

Nothing was relaxed: `lock_active_graph_release` and `_require_active_graph_release` are
untouched, duplication still infers nothing and still never copies the source pin.

| Sabotage | Result |
| --- | --- |
| C — `graph_release_id = deck_owner.graph_release_id` (copy source pin) | RED: `assert 501 == 502` in both pin-asserting tests |
| D — no pin selected for a marker-carrying copy | RED: `assert None == 502` in both |

Honest limit: this fixture cannot distinguish "lock the active row" from "infer the latest
version", because under SCD2 the active release always carries the highest `version_number`.
The lock's own semantics remain owned by `tests/unit/test_remaining_creation_locks.py`, which
is in gate 4 and passes.

---

## R3 — `'FakeDeckStore' object has no attribute 'deck_mutation_context'` (3 tests)

Treated as the coverage gap it is. `FakeDeckStore` now reproduces `SessionManager`'s contract:

- `deck_mutation_context(session_id, *, operation, object_type, object_id=None)` with the real
  signature; it snapshots the session's persisted pin into a real frozen
  `DeckMutationContext(..., suppress_nested_events=True)` and raises `SessionNotFoundError`
  for an unknown session.
- `save_slide_deck` accepts `mutation` and applies the checks `record_shared_deck_mutation`
  applies before it will write evidence — legal operation/object pair (using the production
  `_OPERATION_OBJECT_TYPES` mapping), actor equals the session being written, and the actor
  carries that session's persisted pin. A context the real recorder would reject is rejected
  here.

All three coherence tests now assert the context that reached each write — including on the
deliberately stale worker, where recovering from staleness must not lose or rebuild the
context — while still proving the staleness property each was written for. The observed traces:

```
delete only               -> [('delete_slide', 'deck', 77)]
delete then reorder on B  -> [('delete_slide', 'deck', 77), ('reorder_slides', 'deck', 77)]
delete then update on B   -> [('delete_slide', 'deck', 77), ('update_slide', 'deck', 77)]
```

Anti-drift guard (the brief's explicit reviewer concern):
`test_fake_deck_store_accepts_every_call_the_real_store_accepts` binds each real
`SessionManager` collaborator signature against the double's, so a future threaded argument
cannot be silently missed. It also closed a pre-existing divergence
(`acquire_session_lock`'s `timeout_seconds`). A second test pins the returned object to the
real frozen dataclass, the unknown-session raise, and the illegal-pair refusal.

```
$ python -m pytest tests/unit/test_multiworker_cache_coherence.py -q
6 passed
```

| Sabotage | Result |
| --- | --- |
| E — `delete_slide` stops threading its context (`mutation=None`) | RED x3: `assert [] == [('delete_slide', 'deck', 77)]` etc. |
| G — the double loses `deck_mutation_context` (the original drift) | RED x4: the original `AttributeError` at `chat_service.py:4066` **and** the drift guard's named message |
| H — a writer rebuilds the context and loses the pin | RED x3: `mutation actor must carry the session's persisted pin: None != 77` |
| I — the double stops snapshotting the pin (drifts to a stub) | RED x4, including the contract test |

Sabotage F (dropping the pin in the *real* `SessionManager.deck_mutation_context`) correctly
did **not** go red: `get_session_manager` is patched to the double, so this suite never calls
that code. I record it as a mis-aimed sabotage, replaced by H and I, which target the seam this
suite actually owns.

---

## R4 — `'MockSessionForVersions' object has no attribute 'session_id'` (1 test)

`MockSessionForVersions` conflated the two identity fields a real `UserSession` keeps separate
and omitted the pin entirely. It now carries `id` (row PK), `session_id` (the business key
attribution names as the actor) and `graph_release_id`. All 11 construction sites were updated
(`session_id=1` → `row_id=1`) so the int PK is no longer spelled like the business key.

Adding the attribute alone is demonstrably insufficient — it only moves the failure into the
recorder's identity checks, which I observed:

```
src/services/shared_deck_attribution.py:83: AttributeError: 'MockSlideDeckRecord' object has no attribute 'id'
```

So `test_restore_valid_scenarios` now proves the derivation itself: exactly one recorder call,
`restore_version`/`deck`/`object_id is None`, the actor's session id and release taken from the
requesting session (`RESTORE_SESSION_ID`, `4242`), the deck already carrying the restored
snapshot at call time, at least one flush already done, and the restore transaction still open
(measured as `__enter__` minus `__exit__` counts, because `require_editing_lock` opens and
closes its own session first — comparing against `__exit__.called` alone is wrong here and I
corrected that).

A new test, `test_restore_event_failure_aborts_the_restore`, proves an evidence failure escapes
`restore_version` from inside the `get_db_session` block (so the context manager rolls back:
`__exit__` receives `RuntimeError`) and the post-commit `discard_marker` never runs.

Scope note: the live-transaction rollback matrix stays where C-8 put it —
`tests/integration/test_shared_deck_mutation_attribution.py::test_restore_records_contributor_r2_event_inside_restore_transaction`
and `::test_restore_event_failure_rolls_back_content_deletions_and_event`, both passing. This
unit test is MagicMock-driven by construction; rewriting it onto a live engine would change
what it was written to prove, and would duplicate the integration owner.

```
$ python -m pytest tests/unit/test_save_points.py -q
17 passed
```

| Sabotage | Result |
| --- | --- |
| J — restore stops appending its event | RED x2 (both restore tests) |
| K — the restore event loses the session's persisted pin | RED: `assert None == 4242` |
| L — evidence appended before the content rewrite | RED: `assert 0 >= 1` (flush ordering) |

---

## Gates

### Gate 1 — the seven affected files

```
$ python -m pytest tests/unit/test_deck_permissions_migration.py tests/unit/test_deck_workspace_sharing_migration.py \
    tests/unit/test_drop_config_prompt_columns.py tests/unit/test_spec_dirty_marker.py \
    tests/unit/test_engine_mode_selection.py tests/unit/test_multiworker_cache_coherence.py \
    tests/unit/test_save_points.py -p no:randomly -q -rs
94 passed, 5 warnings in 4.28s
```

Zero failures, **zero skips** (`-rs` reported none; the PostgreSQL-gated nodes in
`test_spec_dirty_marker.py` ran). 94 = the 91 these files carry plus 3 new tests (2 in
`test_multiworker_cache_coherence.py`, 1 in `test_save_points.py`).

### Gate 2 — full `tests/unit`, reported as named causes

```
$ python -m pytest tests/unit -p no:randomly -q
FAILED tests/unit/test_deck_permission_routes.py::TestCreateSessionNoProfile::test_create_session_no_profile_params
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_stores_a_single_authority_config_unchanged
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_accepts_no_agent_config
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
7 failed, 5236 passed, 110 skipped, 135 warnings in 300.29s (0:05:00)
```

**This is exactly the brief's acceptable residual set, node for node.** Causes:

1. `test_deck_permission_routes.py` x1 — `ConversationGraphReleaseIntegrityError: no active
   Graph Release` at `conversation_pins.py:83`. Correction C-10, slice 4A's, file untouched.
2. `test_deploy_autoscaling.py` x2 — `assert 'provisioned' == 'autoscaling'` and
   `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
   Lakebase deploy selection; unrelated to #262.
3. `test_style_exclusivity_chokepoint.py` x3 — `'_FakeSession' object has no attribute
   'execute'` at `conversation_pins.py:79`. Same cause class as C-6/C-10: a fixture double
   predating #261's projection.
4. `test_style_exclusivity_persistence_boundary.py` x1 — `no active Graph Release` at
   `conversation_pins.py:83`. Same class.

Count check against the measured baselines: integration head 14 failed / 5176 passed / 110
skipped; this branch before Task 3R 22 failed / 5215 passed / 110 skipped; now 7 failed /
5236 passed / 110 skipped. 22 − 15 = 7. Skips unchanged at 110. None of the seven residual
failures is in a file this task touched.

### Gate 3 — migrations, including idempotence across two runs

```
$ python -m pytest tests/unit/test_database_migrations.py tests/unit/test_startup_migrations.py \
    tests/unit/test_backfill_startup_autorun.py tests/unit/test_migration.py -p no:randomly -q -rs
23 passed, 10 warnings in 1.36s
```

Explicit two-run idempotence proof on one SQLite database, with raw inserts between the runs:

```
RUN 1
  after run 1 + 2 raw inserts: (['3efeb58e9e752cd859394e73a8f83a88', '29a4984b6010cea193ccf083c9525d68'], ['7bf30fdbffc72d52ab7947deb4db2f01', '18fae76e689d0a19bcc833a49f75ff1f'])
RUN 2 (idempotence)
  after run 2: (['3efeb58e9e752cd859394e73a8f83a88', '29a4984b6010cea193ccf083c9525d68'], ['7bf30fdbffc72d52ab7947deb4db2f01', '18fae76e689d0a19bcc833a49f75ff1f'])
  after run 2 + 1 raw insert: (['3efeb58e9e752cd859394e73a8f83a88', '29a4984b6010cea193ccf083c9525d68', 'd7316fedbdc63f8e2e8231645d1c4549'], ['7bf30fdbffc72d52ab7947deb4db2f01', '18fae76e689d0a19bcc833a49f75ff1f', '5492a7917e72791de15e5fed9219a929'])
  user_sessions: nullable=False default=lower(hex(randomblob(16)))
  session_slide_decks: nullable=False default=lower(hex(randomblob(16)))
GATE 3b PASS: idempotent across two runs, NOT NULL preserved, server default present
```

Run 2 rewrote no existing identity, raised nothing, and every identity is non-null and
distinct. The two in-suite tests assert the same for the legacy ALTER path.

PostgreSQL (each test builds and drops its own throwaway database via the `postgres_engine`
fixture; no database I did not create was dropped):

```
$ python -m pytest tests/integration/test_shared_deck_mutation_migration_postgres.py \
    tests/integration/test_shared_deck_mutation_attribution.py -p no:randomly -q -rs
63 passed, 5 warnings in 19.12s
```

### Gate 4 — C-6 and Task 3 must-not-regress suites

```
$ python -m pytest tests/unit/test_session_duplicate.py tests/unit/test_shared_deck_attribution.py \
    tests/unit/test_graph_nodes.py tests/unit/test_remaining_creation_locks.py \
    tests/unit/test_session_cleanup.py -p no:randomly -q -rs
162 passed, 125 warnings in 3.39s
```

### Gate 5 — whitespace and lint

```
$ git diff --check
(clean)
```

Ruff: these files carry 47 pre-existing findings at the base commit (unsorted imports, >100-col
lines, whitespace-only blank lines, unused imports — the repo does not gate on Ruff in CI). I
measured the baseline by stashing my changes, so the meaningful claim is the delta:

```
=== ruff delta introduced by Task 3R (expect: none) ===
NO NEW RUFF FINDINGS
=== counts ===
/tmp/3r_ruff_before.txt:47
/tmp/3r_ruff_after.txt:47
```

My first pass did introduce two findings (`N801` on the lowercase `FunctionElement` subclass,
and an `I001` on an in-function import block); both are fixed. The `N801` carries a targeted
`# noqa` with its reason — a `FunctionElement` subclass names the SQL function it renders, so
CapWords would misname it, which is SQLAlchemy's own convention.

## Scope discipline

Touched: `src/database/models/session.py`, `src/core/database.py`,
`tests/unit/test_database_migrations.py`, `tests/unit/test_engine_mode_selection.py`,
`tests/unit/test_multiworker_cache_coherence.py`, `tests/unit/test_save_points.py`,
`tests/integration/test_shared_deck_mutation_migration_postgres.py`.

Not touched, as required: `src/services/agent_runtime.py`,
`src/services/agent_runtime_identity.py`, `src/services/graph/builder.py`,
`src/services/graph/state.py`, `tests/unit/test_deck_permission_routes.py`. No
`src/services/collaboration_history.py` created. No Task 4/5/6 work. No push, no PR, no merge,
no deploy, no subagents dispatched.

All production edits made during sabotage were restored and verified with
`git diff --stat` before proceeding; the four commits contain only intended changes.

## Concerns for the reviewer

1. **The C-11 R1 claim needs narrowing** (detail above). The defect was real but SQLite-only in
   manifestation, because the PostgreSQL migration's unconditional `SET DEFAULT` already masked
   the fresh-install case. The ledger's "fails in production exactly as these tests do" should
   be corrected. A suggested reviewer sabotage: remove only the model `server_default` and
   confirm the *unit* column guard and SQLite tests fire while PostgreSQL stays green — that
   reproduces my finding directly.
2. **SQLite legacy upgrade keeps a nullable column.** `ALTER TABLE ADD COLUMN` cannot carry the
   expression default, and the pre-existing migration also does not `SET NOT NULL` on SQLite
   (a long-standing pattern in this file). The new trigger closes the *behavioural* gap — a
   raw insert now receives an identity — but a legacy SQLite table's column remains nullable in
   the catalog, diverging from the model's `nullable=False`. Closing that needs a table
   rebuild, which I judged disproportionate for a dev-only backend and outside this repair's
   scope. Flagging rather than silently accepting.
3. **Pre-existing: `tests/unit/test_save_points.py` reaches the real dev PostgreSQL.**
   `restore_version`'s post-commit `discard_marker` runs unpatched in
   `test_restore_valid_scenarios` and logs
   `spec_sync.discard_marker failed ... column user_sessions.collaboration_identity does not exist`
   against the shared `ai_slide_generator` dev database. `discard_marker` swallows it, so the
   test passes. This is inherited (the test reached the same code on the integration head) and
   I did not migrate that shared database — but it means the dev PostgreSQL database is behind
   this branch's schema, which someone will want to run `_run_migrations` against before
   manual testing.
4. **R2's fixture cannot distinguish "lock active" from "infer latest"** under SCD2, as noted.
   The lock semantics stay owned by `test_remaining_creation_locks.py`.
5. Two of my sabotage attempts were ineffective and are reported as such (renaming a trigger;
   sabotaging code the suite does not call). Both were replaced with effective ones. I mention
   it because an ineffective sabotage that is not noticed is how a test's teeth get
   overestimated.
