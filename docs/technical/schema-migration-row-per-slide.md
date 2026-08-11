# Row-per-Slide Schema Migration Runbook

**Version:** PR1 of the agentification rebuild (feat/langgraph-core → feat/pr1-row-per-slide)
**Target release:** v0.4.1+
**Data at risk:** all existing customer decks (production Lakebase)

---

## Overview

This runbook covers the migration of slide decks from a monolithic `deck_json` TEXT
blob into a normalised `session_slides` table (one row per slide). The migration is
designed to be safe to deploy against live production data: a dual-write/dual-read
layer means an older build can still read `deck_json` and simply ignores the new rows.

The backfill is a **separate manual step** from the code deploy. Do not skip it — all
pre-PR1 decks have no rows and will continue reading from the blob until the backfill
runs. Cutover (dropping the legacy columns) is a further separate, operator-gated step
after a 1–2 week verification window.

---

## Pre-flight checklist

Before starting:

- [ ] **Snapshot / backup.** Take a snapshot of the production Lakebase instance (or
  the branch you are migrating) before deploying. The backfill is idempotent and safe
  to abort, but a snapshot is the only safe rollback past day 0.
- [ ] **Verify on a dev fork first.** The PostgreSQL migration path has only been
  exercised on SQLite (no local Postgres was available during development). The SQL
  itself is standard `ALTER TABLE ... ADD COLUMN TEXT NULL` and the inspector guard is
  dialect-agnostic, but **you must confirm the migration applies cleanly on a Lakebase
  dev fork before running it against production.** See the pre-production verification
  step below.
- [ ] **Confirm the correct branch.** The running app must be on the PR1 release. Check
  with `GET /api/version` — the reported version should be 0.4.1 or greater.
- [ ] **Python environment.** Run the backfill script from a machine that has the PR1
  codebase installed and can reach the production database (`DATABASE_URL` set, or
  `PGHOST`/`PGUSER` in environment, or a `.env` file in the repo root).

---

## Timeline

| Phase | Day | What happens |
|-------|-----|--------------|
| Deploy code | 0 | `init_db()` adds new schema; app starts dual-writing rows |
| Backfill | 0 | Script migrates existing decks that have no rows yet |
| Verification window | 0–14 | Monitor exports, restore, and slide operations |
| Cutover | 14+ | Operator drops `deck_json` / `verification_map`; removes dual-write code |

---

## Phase 1 — Deploy code (app restart handles schema)

Merge PR1 and deploy as normal. No manual schema command is needed.

**How the schema migration runs.** There is no Alembic in this repo. Schema changes
are applied automatically during FastAPI startup. The sequence in `src/api/main.py`
(the `lifespan` context manager) is:

1. If running in Lakebase environment, generate the initial OAuth token.
2. Call `init_db()` from `src/core/database.py`.
   - `Base.metadata.create_all(bind=engine)` — creates the `session_slides` table if
     it does not already exist (safe for existing installs; `create_all` is a no-op
     for tables that already exist).
   - `_run_migrations(engine, schema)` — calls `_migrate_row_per_slide_schema`, which
     adds the following new columns to already-existing tables via idempotent
     `ALTER TABLE ... ADD COLUMN TEXT NULL` statements (guarded by a column-existence
     check):
     - `session_slide_decks.deck_spec_json` — future architect spec snapshot
     - `session_slide_decks.css` — extracted stylesheet (needed by row read path)
     - `session_slide_decks.external_scripts_json` — CDN scripts list (needed by row read path)
     - `session_slide_decks.head_meta_json` — `<head>` metas (needed by row read path)
     - `slide_deck_versions.deck_spec_json` — spec snapshot at save-point time
   - `init_db()` is idempotent: re-running it (or restarting the app) is safe.

This happens **before** any request is served, so by the time the app is healthy the
new columns exist and `save_slide_deck` will begin writing both representations in
the same transaction.

**Confirming the migration ran.** Connect to the database and run:

```sql
-- All five new columns must be present; query returns 5 rows if migration is complete.
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'app_data'   -- replace with your LAKEBASE_SCHEMA value
  AND ((table_name = 'session_slide_decks'
        AND column_name IN ('deck_spec_json', 'css', 'external_scripts_json',
                            'head_meta_json'))
    OR (table_name = 'slide_deck_versions'
        AND column_name = 'deck_spec_json'))
ORDER BY table_name, column_name;
```

Expected: 5 rows. If fewer, the migration did not complete — check app startup logs
for errors from `_migrate_row_per_slide_schema`.

Also confirm `session_slides` exists:

```sql
SELECT COUNT(*) FROM session_slides;  -- should return 0 pre-backfill
```

**Pre-production verification step.** Before migrating production, deploy PR1 to a
dev fork and confirm the above queries return the expected results. On a Lakebase dev
fork, `init_db()` runs on first startup; check the app logs for lines containing
`Migration: adding ... column to session_slide_decks` or
`Migration: row-per-slide schema migration complete`. If the app boots and the column
check returns 5 rows, the Postgres path is working for your Lakebase version.

---

## Phase 2 — Dry-run backfill

From the repo root with the production database reachable:

```bash
python -m scripts.backfill_session_slides
```

No `--yes` flag means dry-run — **no data is modified.** The script prints a summary
line per session and a totals line at the end. Review the output:

```
Backfilling N session(s) [dry-run]
  session pk=123: 5 inserted, 0 skipped, 2 verification migrated, css_backfilled=1, ext_backfilled=1, head_meta_backfilled=1, orphans_pruned=0
  session pk=124: 12 inserted, 0 skipped, 0 verification migrated, css_backfilled=1, ext_backfilled=1, head_meta_backfilled=1, orphans_pruned=0
  ...
Summary: 1024 slides inserted, 0 skipped, 87 verification records migrated, 0 orphans pruned.

Dry-run complete. Re-run with --yes to apply.
```

What each counter means:

| Counter | Meaning |
|---------|---------|
| `slides_inserted` | Rows that would be (or were) added to `session_slides` |
| `slides_skipped` | Positions that already have a row (idempotency guard) |
| `verification_migrated` | Slides whose verification verdict was migrated from the blob |
| `css_backfilled` | 1 if `deck.css` was NULL and would be set from `deck_json` |
| `ext_backfilled` | 1 if `deck.external_scripts_json` was NULL and would be set |
| `head_meta_backfilled` | 1 if `deck.head_meta_json` was NULL and would be set from `deck_json` |
| `orphans_pruned` | Rows at `position >= slide_count` that would be deleted |

**Why orphan pruning matters.** The row read path returns ALL rows in position order.
A phantom row at position N would make the deck appear to have N+1 slides — the export
grows, and (in PR3) the all-committed predicate waits forever on a position no builder
will fill.

To backfill a single session (useful for testing):

```bash
# --session-id takes the STRING business key (from the URL, e.g. /session/abc123def456)
python -m scripts.backfill_session_slides --session-id <string-key>
```

The script resolves the string key to the integer PK via `UserSession.session_id`.
If the key is not found it exits with code 1 and prints to stderr.

---

## Phase 3 — Apply backfill

```bash
python -m scripts.backfill_session_slides --yes
```

**Exit codes:**

- `0` — all sessions backfilled successfully (including the case of zero sessions).
- `1` — one or more sessions failed. Successful sessions were already committed;
  failed sessions are listed in the stderr output with their integer PKs.

**Always check the exit code.** A non-zero exit means partial completion and requires
investigation. Successful commits are not rolled back; re-running with `--yes` is safe
(already-backfilled positions are skipped via the idempotency guard).

**Idempotency.** A row at `(session_id, position)` is skipped if it already exists.
The script can be re-run safely at any time. A partial run (killed mid-flight or
exited non-zero) will resume cleanly — each session's transaction is committed
independently; failed sessions are rolled back without affecting others.

**CSS and external_scripts lift.** The backfill also sets `deck.css` and
`deck.external_scripts_json` from `deck_json` for any deck where those columns are
still NULL. This is critical: the row read path reads `css` and `external_scripts_json`
from the dedicated columns, not from `deck_json`. A missed lift causes every slide
export to lose its stylesheet and Chart.js CDN silently on first read after backfill.

**Verification record migration.** Verdicts stored in the blob `verification_map`
before the backfill are migrated onto the corresponding `session_slides.verification_record`
fields (keyed by content hash). Verdicts recorded after the backfill (on row-backed
sessions) already live on the rows.

---

## Phase 4 — Verify exports and operations

After the backfill:

1. **Export a sample of decks.** Pick 3–5 real sessions covering different styles and
   slide counts. Export each to PPTX and to Google Slides. Confirm slide count, content,
   CSS, and embedded scripts match what was shown in the UI before the migration.

2. **Test restore.** On a test session, create a save point, make an edit, then
   restore. The restored deck should show the pre-edit content. `restore_version` now
   re-materialises rows, prunes phantom rows, restores `css`/`external_scripts_json`/
   `scripts_content`, copies `deck_spec_json` back, and merges (never overwrites)
   verification verdicts — confirm all of these are preserved.

3. **Sanity SQL.** Confirm all decks that have a blob also have rows (post-backfill,
   all should):

   ```sql
   -- Decks with deck_json but no session_slides rows (should be 0 post-backfill)
   SELECT ssd.session_id, ssd.slide_count
   FROM session_slide_decks ssd
   WHERE ssd.deck_json IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM session_slides ss WHERE ss.session_id = ssd.session_id
     )
   ORDER BY ssd.session_id;
   ```

   ```sql
   -- Row count vs slide_count per session (should match; orphan_count should be 0)
   SELECT ssd.session_id,
          ssd.slide_count,
          COUNT(ss.position) AS row_count,
          SUM(CASE WHEN ss.position >= ssd.slide_count THEN 1 ELSE 0 END) AS orphan_count
   FROM session_slide_decks ssd
   LEFT JOIN session_slides ss ON ss.session_id = ssd.session_id
   GROUP BY ssd.session_id, ssd.slide_count
   HAVING COUNT(ss.position) <> ssd.slide_count OR
          SUM(CASE WHEN ss.position >= ssd.slide_count THEN 1 ELSE 0 END) > 0
   ORDER BY ssd.session_id;
   ```

   An empty result set means all decks have exactly `slide_count` rows and no orphans.

4. **Monitor application logs** for the 1–2 weeks following migration. Look for
   `UndefinedColumn`, `json.JSONDecodeError`, or errors from `get_slide_deck` /
   `get_verification_map`. There is no built-in alerting; check logs manually or set up
   a log filter for `ERROR` lines from `session_manager`.

---

## Phase 5 — Cutover (day 14+, operator-gated)

This step is **deferred and manual**. Do not run it until:

- No sessions remain with blob-only state (Phase 4 SQL returns empty).
- No regressions observed in exports, restore, or slide operations.
- A production snapshot has been taken immediately before this step.

**Step 1: Drop legacy columns.**

```sql
ALTER TABLE session_slide_decks DROP COLUMN deck_json;
ALTER TABLE session_slide_decks DROP COLUMN verification_map;
```

**Step 2: Remove dual-write fallback code.** After confirming the above DDL has run
on production, the fallback branches in `session_manager.py` (`save_slide_deck`,
`get_slide_deck`, `get_verification_map`, `write_slide_verification`) can be deleted
and a new app version deployed. This is a code change with its own PR — do not merge
it before the DDL has run.

---

## Rollback

### Pre-cutover (mostly safe — read the limits)

Before the legacy columns are dropped, rolling back is a redeploy:

1. Redeploy the previous (pre-PR1) build.
2. The older build reads `deck_json` and ignores `session_slides` rows entirely.

The new `session_slides` table and the new columns on `session_slide_decks` /
`slide_deck_versions` are inert — they cause no harm and can be left in place.

**What the guarantee actually is.** It is *not* "no data is lost". It is
narrower, and worth stating precisely:

> **Slide content, CSS and external scripts survive a rollback, because
> `save_slide_deck` and `restore_version` both keep `deck_json` current on every
> write. Verification verdicts earned after PR1 deploys do NOT survive.**

Verified by probe against this build, path by path:

| Write path | keeps `deck_json` current? |
|---|---|
| `save_slide_deck` (dual-write, INSERT and UPDATE) | YES |
| `restore_version` | YES |
| `write_slide_verification` (row branch) | **NO** — writes only the row |
| `SlideWriter.write_slide` / `commit_placeholder` | **NO** — writes only rows |

So there are two real limits:

1. **Post-deploy verification verdicts are lost on rollback.** Once a deck has
   `session_slides` rows, `write_slide_verification` writes the verdict to the
   row's `verification_record` and never touches `verification_map`
   (`save_verification` was deleted in PR1). An older build reads the blob, so
   those slides come back showing as unverified. Recoverable by re-verifying,
   but it *is* data loss — plan for it rather than being surprised. (Verdicts on
   decks that have no rows yet still go to the blob, and those do survive.)

2. **`SlideWriter` breaks the guarantee outright, and PR3 is when that starts to
   matter.** `write_slide` updates the row and leaves `deck_json` showing the
   *old* HTML — confirmed by probe: after a `write_slide` at position 0 the row
   read `<p>AGENT</p>` while `deck_json` still read `<p>A</p>`. `SlideWriter` has
   **no production callers in PR1**, so this is latent today. State the rule
   explicitly:

   > The rollback guarantee for slide *content* holds only while `SlideWriter`
   > has no production callers. The moment PR3's graph starts writing slides
   > through it, a rollback silently reverts every agent-authored slide.

   Before PR3 ships, either give `SlideWriter` a `deck_json` write-through or
   accept that rollback is snapshot-only from that point on.

### Exposure: decks edited between deploy and backfill

Deploy and backfill are not atomic, and there is a window between them. If a user
edits a deck in that window, the dual-write creates `session_slides` rows for it
with `verification_record = NULL`; the read path then prefers rows, so any
verdicts that deck had already earned in `verification_map` become unreachable.
`get_verification_map` returns `{}` for it, and the next save point snapshots an
empty map.

The backfill **cannot repair this**: its idempotency guard skips any position
that already has a row (`slides_skipped`), so it will not fill in the missing
verdicts.

This is accepted deliberately — there is no verdict-repair process and none is
wanted. The window is minutes, and it costs the affected user a re-verify, not
any slide content. **Mitigation: run Phase 3 promptly after Phase 1.** The longer
the gap, the more decks can fall into it.

### Post-cutover (destructive)

After `deck_json` and `verification_map` are dropped, rollback requires restoring from
the pre-cutover snapshot. There is no code-only path back.

---

## Troubleshooting

### Symptom: `psycopg2.errors.UndefinedColumn: column session_slide_decks.deck_spec_json does not exist`

**Meaning:** The ORM knows about the new column but the database does not. This means
code from PR1 is running but `init_db()` / `_migrate_row_per_slide_schema` did not
execute (or failed silently) during startup.

**Fix:**
1. Check app startup logs for errors in `_migrate_row_per_slide_schema`.
2. If `init_db()` was skipped (e.g. `PYTEST_CURRENT_TEST` was set in the production
   environment, which suppresses the call), ensure that env var is not set in production.
3. Re-run the migration manually — connect to the database and run:
   ```sql
   ALTER TABLE session_slide_decks ADD COLUMN IF NOT EXISTS deck_spec_json TEXT NULL;
   ALTER TABLE session_slide_decks ADD COLUMN IF NOT EXISTS css TEXT NULL;
   ALTER TABLE session_slide_decks ADD COLUMN IF NOT EXISTS external_scripts_json TEXT NULL;
   ALTER TABLE slide_deck_versions ADD COLUMN IF NOT EXISTS deck_spec_json TEXT NULL;
   ```
   (`IF NOT EXISTS` is PostgreSQL 9.6+ syntax; safe to re-run.)
4. Create the `session_slides` table if it is also missing:
   ```sql
   -- Only needed if the table was never created; app startup creates it via create_all
   -- Check first: SELECT to_regclass('app_data.session_slides');
   ```
   If the table is absent, the safest fix is to restart the app so `create_all` runs
   against the correct schema.

This is also the exact error you will see in `tests/integration/test_savepoint_e2e.py`
when those tests are run against a local Postgres whose schema predates the migration.
The fix there is to run `init_db()` once against that database.

### Symptom: Backfill exits with code 1; some sessions in the stderr list

The backfill committed all other sessions before rolling back the failed one. Re-run
with `--yes` after investigating the error:

```bash
python -m scripts.backfill_session_slides --yes --session-id <string-key-of-failed-session>
```

If the session key is unknown, cross-reference the integer PK from the stderr list
against `user_sessions.id`.

### Symptom: Exports look correct but missing CSS / Chart.js after backfill

The `css_backfilled` and `ext_backfilled` counters were both 0 for the affected
sessions — meaning those columns were already non-NULL but may have been set to empty
string. Check directly:

```sql
SELECT session_id, LENGTH(css), LENGTH(external_scripts_json)
FROM session_slide_decks
WHERE session_id = <pk>;
```

If `css` is `''` (empty string, not NULL) the backfill guard (`deck.css IS None`)
skipped it. In this case, inspect the `deck_json` blob to recover the original value
and set it manually:

```sql
UPDATE session_slide_decks
SET css = <value_from_deck_json>
WHERE session_id = <pk>;
```

### Symptom: `session_slides` row count does not match `slide_count` post-backfill

Re-run the backfill for the affected session:

```bash
python -m scripts.backfill_session_slides --session-id <string-key>   # dry-run first
python -m scripts.backfill_session_slides --session-id <string-key> --yes
```

The idempotency guard skips positions that already have rows and prunes orphans, so
re-running is safe.

### Symptom: App seems to be reading stale slide content after restore

`restore_version` re-materialises rows in the same transaction. If the deck had rows
before the restore and the restored deck is shorter, orphan pruning should have removed
the extra rows. Verify with:

```sql
SELECT position FROM session_slides
WHERE session_id = <pk>
ORDER BY position;
```

If positions beyond the restored slide count remain, the restore transaction may have
been rolled back while the `deck_json` write committed (inconsistent state). In this
case, re-run the backfill for the session to re-align rows to the current `deck_json`.

---

## Schema reference

### New table: `session_slides`

Created by `Base.metadata.create_all()` from the `SessionSlide` ORM model
(`src/database/models/session.py`). Composite primary key `(session_id, position)`.

| Column | Type | Notes |
|--------|------|-------|
| `session_id` | INTEGER FK | References `user_sessions.id` (CASCADE DELETE) |
| `position` | INTEGER | 0-based slide index (primary key, part 2) |
| `id` | VARCHAR(64) | Globally unique UUID (not the PK) |
| `html` | TEXT | Body HTML for this slide |
| `slide_id` | VARCHAR(255) | Original slide UUID from `deck_json` |
| `scripts` | TEXT | Per-slide JS (Chart.js initialisation etc.) |
| `created_by` | VARCHAR(255) | Nullable |
| `created_at` | DATETIME | Nullable |
| `modified_by` | VARCHAR(255) | Nullable |
| `modified_at` | DATETIME | Nullable |
| `verification_record` | TEXT | JSON `{content_hash: verdict}`, merged not overwritten |
| `deck_spec_slide` | TEXT | Reserved for PR3 (architect agent spec fragment) |

### New columns on `session_slide_decks`

Added by `_migrate_row_per_slide_schema` via `ALTER TABLE`:

| Column | Notes |
|--------|-------|
| `deck_spec_json` | Future architect spec snapshot (nullable, reserved for PR3) |
| `css` | Extracted stylesheet; populated by dual-write and backfill |
| `external_scripts_json` | JSON array of CDN URLs; populated by dual-write and backfill |
| `head_meta_json` | JSON object of `<head>` metas (charset, viewport, …); populated by dual-write, restore and backfill. Falls back to the `head_meta` inside `deck_json` when NULL, so pre-existing decks keep their viewport on the first row-path read |

### New column on `slide_deck_versions`

| Column | Notes |
|--------|-------|
| `deck_spec_json` | Spec snapshot at save-point time; copied back by `restore_version` |

### Legacy columns (present during dual-write period, dropped at cutover)

| Table | Column | Notes |
|-------|--------|-------|
| `session_slide_decks` | `deck_json` | Full slide deck as JSON blob |
| `session_slide_decks` | `verification_map` | Flat `{content_hash: verdict}` blob |

---

## Dual-write / dual-read semantics (reference)

Understanding these makes the rollback story clear.

**`save_slide_deck`** writes BOTH `deck_json` and `session_slides` rows (plus
`css`/`external_scripts_json`/`head_meta_json`) in the same transaction. Both
representations are in sync for slide *content* after PR1 deploys — but see the
Rollback section for the two paths (`write_slide_verification`'s row branch and
`SlideWriter`) that write rows only.

**`get_slide_deck`** prefers rows: if ANY `session_slides` rows exist for the deck,
it reconstructs the deck dict from rows + deck-level columns and ignores `deck_json`.
If no rows exist (legacy session, not yet backfilled), it falls back to `deck_json`
exactly as before. Both branches emit the same key set, including `head_meta` and
per-slide `index`, so a deck's shape does not depend on which path served it. This
is why rolling back to a pre-PR1 build restores the right slides before cutover:
the old build reads only `deck_json`, which `save_slide_deck` kept current.

**Row writes go through one helper.** `_upsert_slide_row` in `session_manager.py`
is the single writer of a `session_slides` row, used by the dual-write,
`restore_version`, the backfill and `SlideWriter`. On UPDATE it rewrites the full
identity field set (`slide_id`, `created_by`, `created_at`), because reorder,
insert and delete move slides *between* positions — a row must describe the slide
currently at that position, not the one that used to be there. Verification
records are re-attributed to the slide they belong to (by `slide_id`, then content
hash, then unclaimed position) so a verdict follows its slide across a reorder
instead of being inherited by the new occupant.

**`get_verification_map`** aggregates `verification_record` from all rows if any rows
exist; falls back to the `verification_map` blob for row-less sessions.

**`write_slide_verification`** writes to `session_slides.verification_record` (merge
semantics, not overwrite) for row-backed sessions; falls back to the blob for row-less
sessions. The old `save_verification` blob writer was deleted — verdicts now live
exclusively on rows once the dual-write has run. Merge semantics mean that if a slide's
HTML is edited (new hash) and then reverted (original hash), the verdict for the
original hash is still in the row.

---

## Open questions

1. **PostgreSQL ADD COLUMN on large tables.** `ALTER TABLE ... ADD COLUMN TEXT NULL`
   on PostgreSQL ≥ 11 is a metadata-only operation (no table rewrite) for nullable
   columns with no default, so it is safe on large tables without locking. Confirm this
   is true for the Lakebase PostgreSQL version in your production environment before
   running against a table with millions of rows.

2. **`test_savepoint_e2e.py` in CI.** This test file is referenced in the integration
   test suite and reaches a live Postgres if one is reachable. Whether the CI
   environment provides a migrated Postgres is not confirmed. If it does not, the tests
   may fail with `UndefinedColumn` until the migration runs in that environment too.
