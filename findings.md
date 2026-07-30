# Round 7 findings

Branch `ty/authz-optionc-e2e`, worktree off tip `aaca44c`. One commit per item.

Environment note: a real **PostgreSQL 14.22 (Homebrew)** was reachable on
`127.0.0.1:5432`, so Item 1's mandatory live-Postgres matrix was actually run. No
Docker in this environment; none was needed.

---

## Item 1 — migration was non-idempotent and could hard-fail startup (CRITICAL)

**Status: FIXED.** Commit: see `git log` for `fix(database): stop the brand-text
column migrations from fighting each other`.

### RED first, on real PostgreSQL

New spec: `tests/unit/test_brand_text_migration_postgres.py` (5 tests).
Before the fix, 4 of 5 failed. Verbatim failures:

```
E  AssertionError: after migration run 1 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_fresh_database_stays_text_across_repeated_migration_runs

E  AssertionError: after migration run 2 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_legacy_narrow_database_converges_to_text_and_stays[legacy-50-100]

E  AssertionError: after migration run 2 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_legacy_narrow_database_converges_to_text_and_stays[legacy-255-255]
```

This reproduces codex's oscillation exactly: a **fresh `create_all` database was
NARROWED** on run 1, and the legacy databases **flipped back to 255** on run 2.

The killer case failed with the production boot failure, traced to the exact line:

```
src/core/database.py:537: in _run_migrations
    _migrate_widen_token_name(conn, inspector, schema, _qual, is_sqlite)
src/core/database.py:707: in _migrate_widen_token_name
E  [SQL: ALTER TABLE "design_system_token" ALTER COLUMN name TYPE VARCHAR(255)]
E  psycopg2.errors.StringDataRightTruncation: value too long for type character varying(255)
```

The whole migration runs inside a single `engine.begin()` transaction, so this
escaping error aborts every migration after it — a boot failure on a database
holding legitimate long brand tokens.

### Fix (structural)

(a) `_migrate_widen_token_name` / `_migrate_widen_token_group` are **retired to
no-ops**. Their target (`VARCHAR(255)`) is strictly narrower than the `TEXT` the
superseding migration produces, so there is no state from which they are an
improvement — a widener whose target is now `Text` must never fire. They are kept
as documented no-ops (not deleted) so the history stays discoverable in code and
in log archaeology; their call sites are replaced by a comment explaining why.

(b) `_migrate_uncap_brand_text_columns` now reflects with a **fresh inspector per
column** instead of the shared one threaded through `_run_migrations`. The shared
inspector caches reflection, which is why the uncap step used to *skip* the two
columns the widener had just narrowed. Deciding on a live read makes it converge
to `TEXT` from any starting state (varchar(50)/(100)/(255)/text) and be a true
fixpoint.

(c) The per-column `SAVEPOINT` is already inside a `try/except` that logs and
continues, so one problem column cannot abort the run. This is now **asserted**
rather than assumed.

### GREEN + non-tautology proof

All 5 pass on live Postgres. The containment test is proven non-vacuous: with the
`try/except` temporarily removed, it fails (`NotSupportedError`), while the other
four still pass — so it is specifically the containment it measures.

### CI gating

The module is marked `pytest.mark.postgres` (marker registered in
`pyproject.toml`) and **skips itself at module level** when no PostgreSQL answers:

```
$ TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:59999/nope pytest ...
1 skipped in 0.05s
```

So CI without Postgres is unaffected. Point `TELLR_TEST_POSTGRES_URL` at a
throwaway server to run it. Each test creates and drops its own uniquely-named
database; verified 0 leftover `tellr_migr_%` databases after a full run.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2466 passed, 11 skipped | 2471 passed, 11 skipped | +5 (the new spec), 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

No test disappeared. The two pre-existing SQLite widener specs
(`tests/unit/test_design_system_import.py::test_widen_helper_is_a_noop_on_sqlite`
and `::test_widen_group_helper_is_a_noop_on_sqlite`) still pass — they assert the
no-op-on-SQLite contract, which retirement preserves and strengthens (now a no-op
on every dialect).
