# Handoff: Fernet key — add the boot-seed safety net on top of main's PR-3 migration

> Purpose: seed a FRESH agent/session to do the RIGHT, SMALL version of this work
> on a NEW branch from `main`. The branch `security/fernet-key-boot-migration`
> (and its draft PR #230) is a dead end — delete it (see "Cleanup" below).
> This doc is self-contained; you should not need the old branch's spec/plan.

## TL;DR of the whole saga (so you don't repeat it)

SDR-4437 CRITICAL-3 moved the Google-OAuth Fernet master key out of `app.yaml`
into the `encryption_keys` Lakebase table. **That migration is DONE and correct
on `main` (PR-3, merged as #226).** The deploy tool (`tellr.update()` /
`_update_databricks`, and `deploy_local`) — running as the human, which has the
privilege — reads the key from the existing app.yaml, seeds it into the table,
and writes a keyless app.yaml. Verified working (Lifecycle-A upgrade test passed
in the SDR work).

**The one real gap:** the boot-time key resolver (`src/core/encryption.py::
_seed_value`) does NOT read the `GOOGLE_OAUTH_ENCRYPTION_KEY` env var. So if
someone upgrades an un-migrated app via the **Databricks Apps UI "Deploy"
button** (which bypasses `tellr.update` and reuses the old, still-key-bearing
app.yaml), the new code boots against an empty table, ignores the env-var key
that Apps injected from that app.yaml, and generates a FRESH key → all existing
encrypted Google credentials/tokens are orphaned (and self-deleted on read).
Silent data loss.

**The fix (this handoff's entire scope):** add the env-var read to `_seed_value`
as the highest-priority seed source, so a stray UI-button boot re-seeds the table
from the injected env var instead of fresh-generating. Because
`get_encryption_key()` is already SELECT-first, this is a one-time, harmless net:
after a proper `tellr.update` migration the table already holds the key and the
env var is never consulted again. Plus a docs note + a **major-ish version bump**
signalling "upgrade via `tellr.update`, not the UI button."

## Why the ABANDONED branch was wrong (do NOT resurrect its approach)

`security/fernet-key-boot-migration` tried to make the whole migration
self-contained in the app artifact: boot seeds the table from env, then a
new `_scrub_app_yaml_key()` rewrites the workspace app.yaml at boot to remove
the key, and the deploy tools "carry the key forward" instead of seeding the
table. It got fully implemented and reviewed — then live-testing proved the
core assumption is **architecturally impossible**:

> The running app's **service principal has no access to its own source
> app.yaml** (it lives under the deploying human's `/Workspace/Users/...`
> home). Boot-scrub's very first step — `ws.workspace.download(app.yaml)` —
> fails with "Path (...) doesn't exist" (the workspace API masks
> no-permission as not-found).

Proven on live app `db-tellr-200726`, boot log:
```
INFO  - Encryption key ready
INFO  - Scrubbing legacy key from app.yaml (best-effort)...
WARNING - Scrub: could not remove key from app.yaml
          (Path (/Workspace/Users/robert.whiffin@databricks.com/.apps/prod/tellr-200726/app.yaml) doesn't exist.)
```
Because the deploy tool re-carried the key on every deploy and boot-scrub could
never remove it, the key persisted across 3+ deploys. This is the 3rd/4th time
this wall was hit. **Removing the key from app.yaml is inherently privileged;
only the human-run deploy tool has that privilege — which is exactly what
main's PR-3 already does.** Hence: keep PR-3, add only the boot-seed net.

## The key mechanism question (answered — important, don't get confused)

There are TWO different key reads in TWO different contexts:

1. **`tellr.update()` — runs in the notebook, as the human.** Reads the
   **app.yaml FILE** via `ws.workspace.download(...)`
   (`_read_existing_encryption_key`, deploy.py). It CANNOT and does not read
   process env vars — it reads the file. It then seeds the table directly over
   a Lakebase connection (`_migrate_encryption_key_to_lakebase`). This is on
   `main` and unchanged by this work.
2. **`_seed_value()` — runs at APP BOOT, inside the deployed container.** This
   is the `os.getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")` read we are ADDING.
   Databricks Apps injects every app.yaml `env:` entry into the container's
   process environment, so a key still present in app.yaml's `env:` block IS a
   real OS env var to the booting app. (This is exactly how the pre-PR-3 app
   read the key.)

So the env-var read is the **app-runtime/boot path**, NOT the notebook path.
They never overlap: the notebook reads the file; the app reads its injected
environment. The net (item 2) only fires for the un-migrated UI-button case; a
tool-migrated app has a keyless app.yaml, so no env var, but the table row wins
via SELECT-first.

## Exactly what to change (scope — keep it this small)

Branch off `main` (base was `7ca384c` at time of writing; use current
`origin/main`). Then:

1. **`src/core/encryption.py::_seed_value()`** — add the env-var read as the
   FIRST source in the ladder, ahead of the key-file and generate-fresh
   branches. Add `import os` (the module does not import it on main). Rewrite
   the module docstring's "deliberately NO env-var fallback" paragraph
   (encryption.py lines ~20-23 on main) to explain this is the UI-button-path
   safety net. Because `get_encryption_key()` is already SELECT-first
   (verified on main), no other logic changes — the env var is only read when
   the table is empty.

   Target behaviour of `_seed_value()`:
   ```
   1. GOOGLE_OAUTH_ENCRYPTION_KEY env var, if set   ← NEW (UI-button net)
   2. legacy .encryption_key file (local dev)        ← unchanged
   3. Fernet.generate_key() (fresh install)          ← unchanged
   ```

   EXACT code to write (this was implemented + reviewed clean on the abandoned
   branch; the only edit vs there is the docstring, which drops the now-gone
   "carry-forward" wording). Embedded here so this doc is self-sufficient —
   the abandoned branch is deleted:

   ```python
   def _seed_value() -> bytes:
       """Pick the value to seed an empty encryption_keys table with.

       Priority (SELECT-first in get_encryption_key means this runs only when
       the table is empty):
       1. GOOGLE_OAUTH_ENCRYPTION_KEY env var — the safety net for a stray
          Databricks Apps UI "Deploy" button upgrade of an un-migrated app
          (SDR-4437 CRITICAL-3 follow-up). The supported upgrade path is
          tellr.update, which seeds the table directly and writes a keyless
          app.yaml; this env read only fires when someone bypasses it via the
          UI button, whose reused app.yaml still carries the key (Apps injects
          every app.yaml env entry into the process environment).
       2. legacy .encryption_key file (local dev — keeps dev ciphertext readable).
       3. a freshly generated key (genuinely new install).
       """
       env_key = os.getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")
       if env_key and env_key.strip():
           logger.info("Seeding encryption_keys from GOOGLE_OAUTH_ENCRYPTION_KEY (migration)")
           return env_key.strip().encode()
       if _KEY_FILE.exists():
           key = _KEY_FILE.read_text().strip()
           if key:
               logger.info("Seeding encryption_keys from legacy key file %s", _KEY_FILE)
               return key.encode()
       logger.info("Generating new Fernet master key (fresh install)")
       return Fernet.generate_key()
   ```

2. **Tests — `tests/unit/test_encryption.py`** (TDD). These three tests +
   the fixture hermeticity line were implemented + reviewed clean on the
   abandoned branch. Embedded verbatim below (self-sufficient — do not try to
   `git show` the deleted branch). They rely on the existing `db` fixture,
   `get_encryption_key`, `_stored_key(engine)` helper, and `text`/`Fernet`
   imports already present in the file on main.

   Add to the `db` fixture body (near the existing `_KEY_FILE` monkeypatch),
   for hermeticity — otherwise fresh-install/key-file/concurrent tests break if
   a dev shell exports the var (a real review finding):
   ```python
       monkeypatch.delenv("GOOGLE_OAUTH_ENCRYPTION_KEY", raising=False)
   ```

   The three env-seed tests:
   ```python
   def test_env_var_seeds_empty_table(db, monkeypatch):
       """SDR-4437: an empty table plus a GOOGLE_OAUTH_ENCRYPTION_KEY env var
       seeds the table from that env value (the UI-button-upgrade net)."""
       engine, _ = db
       legacy = Fernet.generate_key().decode()
       monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", legacy)
       assert get_encryption_key() == legacy.encode()
       assert _stored_key(engine) == legacy

   def test_env_var_takes_priority_over_key_file(db, tmp_path, monkeypatch):
       """When both are present on an empty table, the env var (migration
       source) wins over the legacy key file."""
       engine, _ = db
       env_key = Fernet.generate_key().decode()
       file_key = Fernet.generate_key().decode()
       (tmp_path / ".encryption_key").write_text(file_key)
       monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", env_key)
       assert get_encryption_key() == env_key.encode()
       assert _stored_key(engine) == env_key

   def test_existing_row_ignores_env_var(db, monkeypatch):
       """One-time cutover: once the row exists, the env var is never consulted.
       Passes even pre-change because SELECT-first never calls _seed_value when
       the row exists — that IS the invariant being locked."""
       engine, session = db
       existing = Fernet.generate_key().decode()
       with session() as s:
           s.execute(
               text(
                   "INSERT INTO encryption_keys (id, key_value, created_at) "
                   "VALUES (1, :k, CURRENT_TIMESTAMP)"
               ),
               {"k": existing},
           )
       monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
       assert get_encryption_key() == existing.encode()
   ```

3. **Docs** — `docs/technical/dev-deploy.md` and
   `.claude/skills/deploy-tellr-dev/SKILL.md`: state that (a) the key lives in
   the `encryption_keys` table; (b) `tellr.update` / `deploy_local` do the
   migration (read app.yaml key → seed table → write keyless app.yaml); (c) the
   **supported upgrade path is `tellr.update`, NOT the UI Deploy button**;
   (d) boot-seed-from-env is a safety net for a stray UI-button upgrade, not the
   primary mechanism. Do NOT document a boot-scrub — there is none.

4. **Version bump** — bump both `packages/databricks-tellr/pyproject.toml` and
   `packages/databricks-tellr-app/pyproject.toml` (currently `0.3.12` on both;
   note the published dev builds are at `0.3.13.devN`). Robert wants a
   deliberate bump to signal a breaking upgrade-procedure change ("upgrade via
   tellr.update, not the UI button"). Confirm with Robert whether that's
   `0.4.0` (minor) or `1.0.0` (major) — he said "major version bump", so lean
   `1.0.0` unless he says otherwise. The bump is COMMUNICATION, not enforcement
   (see open question below).

## What NOT to do (explicit scope guards)

- Do NOT touch `_update_databricks` / `deploy_local` migration logic — main's
  PR-3 version is correct and works. No carry-forward, no `$ENCRYPTION_KEY_BLOCK`.
- Do NOT add a boot-time app.yaml scrub — the SP can't write its own source.
- Do NOT delete `_migrate_encryption_key_to_lakebase` — it's the working
  migration on main.
- Do NOT touch the fork/devloop path or `_check_branching_preconditions` — the
  fork inherits the key via copy-on-write of the table, and the preflight
  already refuses to fork an un-migrated source. Out of scope.
- Do NOT add a "ciphertext-aware hard-fail" empty-table guard unless Robert
  asks (see open question) — previously dropped as YAGNI; the net makes it
  unnecessary.

## Open questions for Robert (confirm before/while implementing)

1. **Version number:** `1.0.0` (he said "major") vs `0.4.0`? Confirm.
2. **Enforcement vs communication:** The plan treats the version bump as a
   signal and relies entirely on the boot-seed net for safety (the UI button is
   still clickable — can't be removed). Robert leaned this way. If he instead
   wants a hard gate (boot refuses to fresh-generate when it detects existing
   ciphertext in google_oauth_tokens / google_global_credentials), that's the
   previously-dropped ciphertext-aware guard — reopenable, but argue the net
   makes it unnecessary. Default: net only, no gate.

## Lakebase write permissions for the net's INSERT (verified reasoning — Robert asked)

The net's seed does `INSERT INTO encryption_keys`. Confirm this is safe under
the shared-owner / group-permission model ([[lakebase_shared_owner]]):

- **The net adds NO new write.** The boot-time `INSERT INTO encryption_keys`
  already exists in shipped CRITICAL-3 code (`get_encryption_key` seeds the
  table at boot). The net only changes the seeded *value* (env var vs
  fresh-generate). Proven live: `db-tellr-200726` boot log showed
  "Encryption key ready" = that INSERT already succeeds there.
- **Table setup runs on EVERY boot**, not just `tellr.update`: the app.yaml
  `command:` runs `python -c "...init_database()"` before the server starts, so
  `init_db()` (`create_all` + `_run_migrations`, incl.
  `_reassign_new_objects_to_shared_owner`) ensures `encryption_keys` exists and
  is correctly owned BEFORE the seed INSERT. So even the UI-button path sets up
  the table.
- **Ownership resolves the INSERT on every env:**
  - Shared-owner envs (prod `app_data_prod`, devloop forks): app SP creates the
    table → reassign re-homes it to `tellr_app_owners` → app SP INHERITs → INSERT
    works. This is the SAME inheritance the app uses to write
    `google_global_credentials` / `google_oauth_tokens` / `user_sessions` on
    every request (all owned by `tellr_app_owners` on prod). Robert confirmed a
    manual `google_global_credentials` write succeeded on the test app — same
    schema, same role, same path.
  - Standalone non-shared envs: `tellr_app_owners` absent → reassign no-ops →
    app SP owns the table it created → INSERT works directly.
  - `tellr.update` path (separate): the deploy migration CREATEs the table as
    the human and does an explicit `GRANT SELECT, INSERT ON encryption_keys TO
    <app_sp>` — so the app SP can still INSERT/SELECT even when the human owns it.
- **The ONE thing to confirm live** (don't overclaim it as proven): the
  shared-owner INHERIT path for the `encryption_keys` INSERT specifically has
  only been reasoned from the model + observed for OTHER tables — the live test
  app was standalone, not shared-owner. The post-fix acceptance on a prod-state
  app (below) should confirm the seed INSERT succeeds on a shared-owner env.
  Low risk (identical mechanism to working credential writes), but verify once.

## Verification (same hard-won rule as before)

Unit tests prove the seed logic. But runtime OBO/boot behaviour can ONLY be
proven on a DEPLOYED app (CLI/local tokens diverge from the app's injected
environment). The live test that FOUND this whole bug:
- App `db-tellr-200726` (live, disposable), workspace source
  `/Workspace/Users/robert.whiffin@databricks.com/.apps/prod/tellr-200726`.
- To read its boot log you MUST use an OAuth (U2M) profile, not PAT:
  a profile `tellr-dev-oauth` was created this session
  (`databricks auth login --host https://fevm-db-tellr-dev-workspace.cloud.databricks.com/ --profile tellr-dev-oauth`).
  Then: `databricks apps logs db-tellr-200726 -p tellr-dev-oauth`.
  (`databricks apps logs` refuses PAT auth — "OAuth Token not supported for
  current auth type pat". The `tellr-dev` profile is PAT.)
- Post-fix acceptance: stand up / reuse a legacy-state app (key in app.yaml,
  real Google credential = real ciphertext), upgrade via the UI button, confirm
  boot log shows "Seeding encryption_keys from GOOGLE_OAUTH_ENCRYPTION_KEY" and
  the old credential still decrypts. Then confirm `tellr.update` path also
  migrates + writes keyless app.yaml (main's existing behaviour) and old
  credential still decrypts.
- Publishing dev builds for live test: `gh workflow run publish-dev.yml --ref
  <branch>` (needs the branch pushed; auto-increments next `.devN` to REAL
  PyPI), then `deploy_local ... --from-pypi <version>`. `0.3.13.dev17` was the
  last published (from the abandoned branch — do not reuse for the new work).

## Cleanup (part of the work — do this)

- Close draft PR #230 on `robertwhiffin/ai-slide-generator`
  (`gh pr close 230 --repo robertwhiffin/ai-slide-generator --comment
  "Abandoned — architecturally unworkable (app SP can't write its own source
  app.yaml). Replaced by a small boot-seed net on top of main's PR-3 migration;
  see docs/superpowers/specs/2026-07-20-fernet-key-net-handoff.md."`).
- The branch `security/fernet-key-boot-migration` has ALREADY BEEN DELETED
  (local + remote) by the session that wrote this handoff. Everything reusable
  from it (the `_seed_value` code + the three tests + the fixture hermeticity
  line) is embedded verbatim in items 1-2 above — you need nothing from that
  branch. If for some reason it still exists, delete it:
  `git branch -D security/fernet-key-boot-migration` /
  `git push origin --delete security/fernet-key-boot-migration`.
- The abandoned branch's spec/plan under `docs/superpowers/{specs,plans}/
  2026-07-20-fernet-key-boot-migration*.md` describe the WRONG (carry-forward +
  scrub) design — do not follow them; this handoff supersedes them. Delete or
  leave them, but don't let a future reader mistake them for the plan.
- The SDD ledger + scratch for the abandoned run live under
  `.superpowers/sdd/` (git-ignored) — harmless, ignore.
- Tear down the live test app when done:
  `deploy_local.sh delete --env <...> --instance <...>` (or via the UI), and
  the `tellr-dev-oauth` profile can stay (useful for log reads).

## Key files (on main)

- `src/core/encryption.py` — `_seed_value` (the one change), `get_encryption_key`
  (SELECT-first, unchanged), module docstring (rewrite).
- `packages/databricks-tellr-app/databricks_tellr_app/run.py` —
  `init_database()` boot hook calls `ensure_encryption_key()`. (No scrub call —
  do not add one.)
- `packages/databricks-tellr/databricks_tellr/deploy.py` —
  `_update_databricks` (migration, KEEP), `_read_existing_encryption_key`
  (reads the FILE, KEEP), `_migrate_encryption_key_to_lakebase` (KEEP).
- `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template` —
  keyless on main (KEEP keyless).
- `pyproject.toml` x2 — version bump.
- `tests/unit/test_encryption.py` — add net tests + fixture hermeticity.
- `docs/technical/dev-deploy.md`, `.claude/skills/deploy-tellr-dev/SKILL.md` —
  docs.

## Suggested first moves for the new session

1. Read this doc. Confirm the two open questions with Robert (version number;
   net-only vs hard gate).
2. The reusable code + tests are embedded verbatim in items 1-2 above — nothing
   to recover from git. The abandoned branch and its draft PR #230 are already
   cleaned up. You are ALREADY on a fresh branch off `origin/main`
   (`security/fernet-key-net`) that carries only this handoff doc.
3. Apply the small `_seed_value` change + tests (TDD), docstring rewrite, docs,
   version bump. Full unit suite: expect only the known baseline failures
   (SVG/cairo, mlflow-tracing, autoscaling-mock) — ZERO net-new.
4. Push, publish a dev build, run the live UI-button + tellr.update acceptance
   on a legacy-state app. Open a fresh PR to main. Consider `/review` (Isaac)
   before merge.
