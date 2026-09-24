# Task 3R independent review

Reviewer: independent; did not write this code. Every claim below was re-run, not relayed.

Worktree: `.worktrees/issue-262-plan`, branch `plan/conversation-collaboration-262`.
HEAD verified `a7fc0ae2c47d8d09107358efcbb772ff8370f8c2`, tree clean at start and at end.
Range reviewed: `cf9fa4c393efa16baf0213018c524bc747127797..a7fc0ae2c47d8d09107358efcbb772ff8370f8c2`
(`73bf7cdf4`, `0b5545a0c`, `4abd82dd1`, `a7fc0ae2c`).

Environment: `/Users/robert.whiffin/.pyenv/shims/python` (3.11.0, databricks-sdk 0.112.0,
SQLAlchemy 2.0.36). `PYTHONPATH` set to the worktree plus its `packages/databricks-tellr`;
`databricks_tellr` and `src` both resolved inside this worktree. No `pip install`, no `uv`,
no `.venv`, no `npm`, no Playwright, no commits, no subagents.

---

## Verdicts

**Spec compliance: COMPLIANT.** All four C-11 causes are addressed, each in the form the
correction demands. R1 is a production fix, not fixture debt. R3 and R4 are genuine
coverage-gap repairs, not silenced `AttributeError`s.

**Task quality: APPROVED.** Critical 0, Important 0, Minor 5. No assertion anywhere in the
diff was weakened or removed.

---

## C-11 cause-by-cause

### R1 — server-side `collaboration_identity` — ADDRESSED as a production fix

`src/database/models/session.py:31-64` declares a `FunctionElement` subclass with a default
`@compiles` rendering `gen_random_uuid()` and a `sqlite` rendering
`lower(hex(randomblob(16)))`, attached as `server_default` on both columns
(`:147` `UserSession`, `:315` `SessionSlideDeck`). `src/core/database.py:731-741` adds an
idempotent `CREATE TRIGGER IF NOT EXISTS ... AFTER INSERT ... WHEN NEW.collaboration_identity
IS NULL` for the legacy SQLite ALTER path, which cannot carry an expression default.

Each item the brief asked me to confirm, verified directly:

- **SQLite rendering matches `Uuid(as_uuid=True)`'s storage form.** Probed empirically: a
  typed ORM insert stores `'745c93da65d04ed497ae07b8c5218d92'` (`typeof` = text, length 32);
  `lower(hex(randomblob(16)))` yields the same 32-char lowercase-hex shape; a value written
  by the raw expression reads back through the typed column as a `UUID`. Identical form.
- **Evaluated per row.** Proved by sabotage A below (a constant renderer makes the
  distinctness assertion go RED).
- **`nullable=False` still holds.** `UserSession.__table__.c.collaboration_identity.nullable`
  and `SessionSlideDeck`'s both report `False` at runtime; the compiled DDL ends `NOT NULL`
  on both dialects.
- **PostgreSQL `SET DEFAULT` / `SET NOT NULL` intact.** `src/core/database.py` still runs
  `UPDATE ... gen_random_uuid() WHERE ... IS NULL` (:746), `ALTER COLUMN ... SET DEFAULT
  gen_random_uuid()` (:753) and `ALTER COLUMN ... SET NOT NULL` (:759). The diff inserts only
  the SQLite trigger block; the `else:` branch is byte-unchanged.
- **Immutability guard still fires for both models.** Ran a live probe: mutating
  `collaboration_identity` on a persisted `UserSession` and on a persisted `SessionSlideDeck`
  both raise `ValueError: collaboration identity is immutable`. The decorators at
  `session.py:505-509` are untouched.

Compiled DDL, observed:

```
POSTGRES: collaboration_identity UUID DEFAULT gen_random_uuid() NOT NULL,
SQLITE:   collaboration_identity CHAR(32) DEFAULT (lower(hex(randomblob(16)))) NOT NULL,
```

The R1 commit `73bf7cdf4` is the only commit in the range touching `src/`; `0b5545a0c`,
`4abd82dd1` and `a7fc0ae2c` are test-only. I confirmed this per commit.

### R2 — active Graph Release seeded for marker-carrying duplicates — ADDRESSED

`tests/unit/test_engine_mode_selection.py:76-152` publishes a superseded release (501,
`effective_to` set) and an active one (502, `effective_to IS NULL`), and pins the **source**
session to the superseded one. That is the right shape: a copy-the-source-pin regression
returns 501 instead of 502 and is observable.

Production side confirmed untouched and still C-2-conformant: `duplicate_session` queries the
source's earliest user marker, computes `carried_marker`, and only then calls
`lock_active_graph_release(db).release_id` — before constructing `new_session`. The source pin
is never read into the copy. `lock_active_graph_release` and `_require_active_graph_release`
are not in the diff.

All four original assertions are intact; the pin assertions are additions. The monolith case
additionally proves that an available active release does *not* pin a non-graph copy.

### R3 — `FakeDeckStore.deck_mutation_context` — ADDRESSED as a coverage gap

This was the finding I was asked to scrutinise hardest. It holds up.

The double at `tests/unit/test_multiworker_cache_coherence.py:75-100` reproduces the real
`SessionManager.deck_mutation_context` (`session_manager.py:3414-3431`) faithfully: same
keyword-only signature, snapshots the session's persisted pin into a real frozen
`DeckMutationContext(..., suppress_nested_events=True)`, raises `SessionNotFoundError` for an
unknown session. It is the production dataclass, not a stub.

`_accept_mutation` (`:102-127`) applies the same three checks the real
`record_shared_deck_mutation` (`src/services/shared_deck_attribution.py:75-83`) applies before
it will write evidence — legal operation/object pair against the production
`_OPERATION_OBJECT_TYPES` mapping, actor equals the session being written, and actor pin equals
that session's persisted pin.

**The three tests genuinely traverse the threaded path.** They drive the real
`ChatService.delete_slide`, `ChatService.reorder_slides` and `ChatService.update_slide` with
only `get_session_manager` patched to the double. Those are three of the five real
`deck_mutation_context` call sites in `chat_service.py` (:3433 reorder, :3538 update, :3626
duplicate, :3749 insert, :4066 delete); `duplicate_slide` and `insert_slide` are the
integration matrix's per C-8. `seed_db` deliberately passes no `mutation`, so
`mutation_trace()` counts only real ChatService writes — an exact-equality trace assertion,
so an extra or missing write is caught too.

**Each still proves its original property.** Diff is purely additive: the staleness
assertions (`len(deck_b.slides) == len(db)`, `len(saved["slides"]) == 5`, `deleted_html not in
saved_htmls`) are unchanged, and the trace assertions sit after them. The stale-worker cases
are the valuable ones: recovering from staleness must not lose or rebuild the context, and the
pin assertion is what makes a rebuild observable.

Anti-drift guard present (`:391-441`): a signature-conformance test binds ten real
`SessionManager` collaborator signatures against the double's. The controller already proved
it goes RED on a real keyword-only parameter addition; I did not repeat that.

### R4 — `MockSessionForVersions.session_id` — ADDRESSED as a coverage gap

`tests/unit/test_save_points.py:37-69` separates `id` (row PK), `session_id` (business key /
actor) and `graph_release_id` (pin). All 11 construction sites renamed `session_id=1` →
`row_id=1`, so the int PK is no longer spelled like the business key.

`test_restore_valid_scenarios` now proves the derivation: exactly one recorder call,
`restore_version`/`deck`/`object_id is None`, actor session id and release taken from the
requesting session, the deck already carrying the restored snapshot at call time, at least one
flush done, and the transaction still open — measured as `__enter__` minus `__exit__` counts,
which is the correct measurement given `require_editing_lock` opens and closes its own session
first. The production code matches (`session_manager.py` `db.flush()` then
`record_shared_deck_mutation(...)` inside the same `get_db_session` block).

`test_restore_event_failure_aborts_the_restore` is new and proves the failure escapes from
inside the block (`__exit__` receives `RuntimeError`) and that the post-commit `discard_marker`
never runs. Original assertions unchanged.

### Mechanical check: no weakened assertions

I extracted every removed line in the range. The complete set of non-additive test edits is:
one import line, `acquire_session_lock`'s signature widened to accept the real
`timeout_seconds`, the `MockSessionForVersions` docstring/`__init__`, eleven `session_id=1` →
`row_id=1` renames, and one `with patch(...)` line widened into a two-patch `with`. **Zero
assertions were removed or weakened anywhere in the diff.**

---

## Blast radius — what breaks that this diff does not touch

Nothing. Checked, and the answer is net-positive rather than neutral:

- **No raw-SQL writers of either table in production code.** Zero
  `INSERT INTO user_sessions` / `INSERT INTO session_slide_decks` statements anywhere in
  `src/`, `packages/` or `scripts/`; no `bulk_save_objects`/`bulk_insert_mappings` against
  them; and **no explicit `collaboration_identity=` assignment anywhere in `src/` or
  `tests/`**. So the only paths the column default changes are metadata-built schemas — which
  is exactly what the controller's C-11 R1 amendment says, and I independently reach the same
  conclusion.
- **The one production metadata-only path is `src/core/lakebase.py:339`**
  (`initialize_lakebase_tables`, `Base.metadata.create_all` with no `_run_migrations`). Before
  this fix it would have created a defaultless `NOT NULL` column on PostgreSQL. It has **zero
  callers** repo-wide, so the exposure is latent, not live — but the fix is the right one and
  this is the concrete path that justifies it.
- **`tests/unit/conftest.py:124-125` and `tests/integration/conftest.py:102-103` do run
  `_run_migrations`**, so the new SQLite trigger is now installed in essentially every SQLite
  fixture in the suite. It fires only when the inserted identity is NULL, so ORM inserts are
  unaffected; the unchanged full-suite residual confirms this empirically.
- **No trigger interaction.** The new trigger is the only SQLite trigger the codebase creates
  — every other `CREATE TRIGGER` in `database.py` (:841, :928, :1050, :1062, :2230) sits behind
  an `if is_sqlite: return`. The PostgreSQL immutability trigger is a `BEFORE UPDATE` on a
  dialect where the inline column default means no post-insert `UPDATE` ever happens.
- **No test asserts the DDL or trigger set of these tables** other than the new tests, so
  nothing was silently masked.

---

## Findings

No Critical. No Important.

**Minor 1 — SQLite identities are not RFC-4122 UUIDs.**
`src/database/models/session.py:62`. `lower(hex(randomblob(16)))` produces 128 uniformly
random bits with no version or variant nibbles, so `Uuid(as_uuid=True)` reads them back as
UUIDs of arbitrary version (I observed `version=2`), whereas PostgreSQL's `gen_random_uuid()`
yields a proper v4. Two dialects now generate structurally different values from the same
declared type. Pre-existing in kind — the base commit's backfill already used `randomblob` —
and nothing in the codebase reads `.version` or `.variant`, so it is harmless today. Worth a
comment rather than a change.

**Minor 2 — legacy SQLite catalog nullability diverges from the model.**
`src/core/database.py:705-710`. The ALTER path adds `VARCHAR(32) NULL` and the SQLite branch
never reaches `SET NOT NULL`, so a legacy SQLite catalog reports the column nullable while the
model declares `nullable=False`. The trigger closes the behavioural gap. Independently
confirmed. Already disclosed by the author (concern 2) and accepted by the controller as a
deferred item; I agree with that disposition — closing it needs a table rebuild for a dev-only
backend.

**Minor 3 — the trigger populates after the row lands, so SQLite `INSERT ... RETURNING
collaboration_identity` would return NULL on a legacy-shaped table.**
`src/core/database.py:731-741`. Latent only: there is no such writer in production code (see
blast radius), and the new tests read with a separate `SELECT`. Flagging because it is the one
behavioural difference between the trigger and a true column default.

**Minor 4 — the context-contract test pins semantics to hardcoded values, not to the real
manager.** `tests/unit/test_multiworker_cache_coherence.py:405-441`. The signature guard
catches parameter drift; the contract test asserts `suppress_nested_events is True` and the
pin snapshot against literals rather than against
`SessionManager.deck_mutation_context`'s actual output. If the real manager stopped setting
`suppress_nested_events=True`, the double would drift undetected. Narrow residual gap in an
otherwise well-built anti-drift guard.

**Minor 5 — the restore test cannot distinguish the session row's `session_id` from the
`session_id` argument.** `tests/unit/test_save_points.py:41` and `:622-623`.
`RESTORE_SESSION_ID` equals the value passed to `restore_version`, so an implementation that
used the parameter instead of `session.session_id` would still pass. The pin half (`4242`) is
unambiguously derived from the row, which is the substantive half of C-4, and the two are
equivalent in production because `_get_session_or_raise` looks the row up by that exact id —
so this is a completeness note, not a defect.

---

## Sabotage results

Both targets distinct from the implementer's twelve and the controller's drift sabotage.

### Sabotage A — SQLite `@compiles` renderer returns a CONSTANT instead of a per-row expression

`src/database/models/session.py:61-63`, `_render_collaboration_identity_default_sqlite` changed
to return `"'0123456789abcdef0123456789abcdef'"` (a 32-char hex constant, so the failure cannot
come from a length or parse artefact).

Marker confirmed on the executed path before believing the RED — the emitted DDL carries the
constant, and the trigger and the PostgreSQL rendering are untouched, so this sabotage isolates
the column-default mechanism only:

```
POSTGRES column DDL: ['collaboration_identity UUID DEFAULT gen_random_uuid() NOT NULL,']
SQLITE column DDL: ["collaboration_identity CHAR(32) DEFAULT ('0123456789abcdef0123456789abcdef') NOT NULL,"]
INSTALLED TRIGGERS:
  trg_user_sessions_collaboration_identity_default: ... SET collaboration_identity = lower(hex(randomblob(16))) WHERE rowid = NEW.rowid; END
```

RED:

```
$ python -m pytest tests/unit/test_database_migrations.py -p no:randomly -q -rs
......FF.                                                                [100%]
___ test_collaboration_identity_column_declares_a_server_default_per_dialect ___
E           AssertionError: assert 'collaboration_identity CHAR(32) DEFAULT (lower(hex(randomblob(16)))) NOT NULL' in '\nCREATE TABLE user_sessions (...'
tests/unit/test_database_migrations.py:389: AssertionError
______ test_collaboration_identity_is_server_generated_on_a_fresh_schema _______
>           assert len(set(identities)) == len(identities), (
E           AssertionError: user_sessions.collaboration_identity is not distinct per row: ['0123456789abcdef0123456789abcdef', '0123456789abcdef0123456789abcdef']
E           assert 1 == 2
E            +  where 1 = len({'0123456789abcdef0123456789abcdef'})
E            +    where {'0123456789abcdef0123456789abcdef'} = set(['0123456789abcdef0123456789abcdef', '0123456789abcdef0123456789abcdef'])
E            +  and   2 = len(['0123456789abcdef0123456789abcdef', '0123456789abcdef0123456789abcdef'])
tests/unit/test_database_migrations.py:421: AssertionError
2 failed, 7 passed, 5 warnings in 0.41s
```

The distinctness guarantee is genuinely tested — the assertion fires with its own named
message, and the column-definition guard fires independently.

Restored (`git checkout src/database/models/session.py`), tree exactly clean at
`a7fc0ae2c47d8d09107358efcbb772ff8370f8c2`, GREEN:

```
$ git status --porcelain      (no output)
$ python -m pytest tests/unit/test_database_migrations.py -p no:randomly -q
9 passed, 5 warnings in 0.28s
```

### Sabotage B — break the `AFTER INSERT` trigger's BODY (not its name)

`src/core/database.py:738`, the trigger body's generator changed from
`SET collaboration_identity = lower(hex(randomblob(16)))` to
`SET collaboration_identity = NULL`. The `WHEN` clause already requires NULL, so the trigger
becomes a no-op while remaining a valid, installed trigger.

Marker confirmed on the executed path first — module parses, the installed trigger SQL carries
the broken body, a raw post-migration insert is observably identity-less, and the `create_all`
column default is untouched (so this isolates the trigger mechanism only):

```
$ python -c "import ast; ast.parse(open('src/core/database.py').read()); print('PARSES OK')"
PARSES OK
SQLITE column DDL: ['collaboration_identity CHAR(32) DEFAULT (lower(hex(randomblob(16)))) NOT NULL,']
INSTALLED TRIGGERS:
  trg_user_sessions_collaboration_identity_default: CREATE TRIGGER trg_user_sessions_collaboration_identity_default AFTER INSERT ON "user_sessions" WHEN NEW.collaboration_identity IS NULL BEGIN UPDATE "user_sessions" SET collaboration_identity = NULL WHERE rowid = NEW.rowid; END
  trg_session_slide_decks_collaboration_identity_default: ... SET collaboration_identity = NULL WHERE rowid = NEW.rowid; END
identities after raw insert: [(1, '1a0f8dd206ee679a6eb02b00652e957e'), (2, None)]
```

(Row 1 keeps its identity from the migration's one-shot `UPDATE ... WHERE IS NULL` backfill;
row 2, the post-migration raw insert, is `None`. The two mechanisms are correctly independent.)

RED:

```
$ python -m pytest tests/unit/test_database_migrations.py -p no:randomly -q -rs
........F                                                                [100%]
__ test_collaboration_identity_backfill_and_default_on_the_legacy_alter_path ___
>           assert all(value for value in identities), (
E           AssertionError: a post-migration raw insert into user_sessions got no identity: ['417f576cc90f4a52656e8f2a594b5e09', '8dc176203ca4d221e05a89150d835c82', 'ac3a825327619ad911daa6d86cf99ca8', None]
E           assert False
tests/unit/test_database_migrations.py:517: AssertionError
1 failed, 8 passed, 5 warnings in 0.40s
```

The trigger is verified, not merely present.

Restored (`git checkout src/core/database.py`), tree exactly clean at
`a7fc0ae2c47d8d09107358efcbb772ff8370f8c2`, GREEN:

```
$ git status --porcelain      (no output)
$ python -m pytest tests/unit/test_database_migrations.py -p no:randomly -q
9 passed, 5 warnings in 0.40s
```

Neither sabotage was ineffective; neither needed discarding.

---

## Independent residual-failure set

Measured by me, not relayed:

```
$ python -m pytest tests/unit -p no:randomly -q
FAILED tests/unit/test_deck_permission_routes.py::TestCreateSessionNoProfile::test_create_session_no_profile_params
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_stores_a_single_authority_config_unchanged
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_accepts_no_agent_config
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
7 failed, 5236 passed, 110 skipped, 135 warnings in 311.21s (0:05:11)
```

**Exactly seven failures, node for node the brief's acceptable set** — `test_deck_permission_routes`
x1 (C-10), `test_deploy_autoscaling` x2, `test_style_exclusivity_chokepoint` x3,
`test_style_exclusivity_persistence_boundary` x1. None is in a file this diff touches. My set
agrees with the controller's independent measurement and with the author's report, including
the pass/skip counts.

Other gates, all re-run by me:

| Gate | Command result |
| --- | --- |
| Seven affected files | `94 passed, 5 warnings in 5.14s` — zero failures, zero skips (`-rs` reported none) |
| Migrations + startup (`test_database_migrations`, `test_startup_migrations`, `test_backfill_startup_autorun`, `test_migration`) | `23 passed` |
| C-6 / Task 3 must-not-regress (`test_session_duplicate`, `test_shared_deck_attribution`, `test_graph_nodes`, `test_remaining_creation_locks`, `test_session_cleanup`) | `162 passed` |
| PostgreSQL (`test_shared_deck_mutation_migration_postgres`, `test_shared_deck_mutation_attribution`) | `63 passed`, zero skips |
| `git diff --check` | clean |
| Ruff delta on the seven changed files | **zero** — 45 findings before, 45 after, identical rule-code distribution per file (measured by piping each file's base content through `ruff check --stdin-filename`, so per-file-ignores and project config apply) |

Idempotence: `test_collaboration_identity_backfill_and_default_on_the_legacy_alter_path` runs
the migration twice and asserts the second pass rewrites no existing identity and raises
nothing; it passes. I also confirmed the trigger uses `IF NOT EXISTS` and the backfill is
`WHERE collaboration_identity IS NULL`, so both are re-run safe.

---

## Cannot verify from diff

1. **The real-transaction restore rollback.** The unit test proves ordering and the escape
   path with MagicMock; the live matrix (content + rows + deletions + event rolling back
   together) lives in
   `tests/integration/test_shared_deck_mutation_attribution.py::test_restore_records_contributor_r2_event_inside_restore_transaction`
   and `::test_restore_event_failure_rolls_back_content_deletions_and_event`. I confirmed both
   exist and that the suite passes (63 passed), but sabotaging them was outside my assigned
   targets, so I am not independently attesting their teeth. C-8 assigns that ownership, and
   the Task 3 review already exercised it.
2. **`gen_random_uuid()` availability on the deployment target.** `create_all` now emits
   `DEFAULT gen_random_uuid()` at CREATE TABLE time, which needs the function to exist then
   (built in from PostgreSQL 13). Verified against the local test PostgreSQL via the
   integration suite; cannot verify the Databricks Lakebase target from here. Low risk — the
   pre-existing migration already depended on the same function.
3. **Ruff absolute count.** The author reports 47/47; I measure 45/45 on the same seven files.
   The substantive claim (zero new findings) is independently confirmed; I cannot reconcile the
   absolute count without the author's exact invocation.
4. **The shared dev PostgreSQL database.** I did not connect to or modify
   `ai_slide_generator`. I did confirm the *mechanism* behind the author's concern 3
   statically: `restore_version`'s post-commit `discard_marker(session_id)` uses
   `spec_sync`'s own unpatched `get_db_session`, so it reaches the configured engine from a
   unit test, and it swallows the resulting error. I also confirmed that call predates this
   branch — it is present in `restore_version` at the integration head `795262c16` as well as
   at base `cf9fa4c39` — so it is inherited, not caused here. Because the missing column
   fails the ORM `SELECT`, no write reaches that database.

---

## Summary

The task does what C-11 asked, in the form C-11 asked for. R1 is a real production fix whose
two mechanisms (per-dialect column default, legacy-path trigger) I sabotaged independently and
found both genuinely tested. R3 and R4 are real coverage-gap repairs: the doubles now carry the
production contracts, the tests drive real production writers through the threaded path, and
nothing was weakened to make them pass. The author's own narrowing of C-11's R1 claim is
correct and is the kind of finding a reviewer wants volunteered rather than buried — my
independent blast-radius sweep reaches the same conclusion and adds the one concrete
metadata-only production path (`lakebase.py:339`, currently callerless) that justifies the fix.
The five Minors are all narrow; none blocks.

Worktree left exactly as found: clean tree at `a7fc0ae2c47d8d09107358efcbb772ff8370f8c2`,
no commits, no pushes.
