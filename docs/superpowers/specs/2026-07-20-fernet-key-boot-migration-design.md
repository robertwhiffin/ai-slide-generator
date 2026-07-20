# Design: Fernet key migration + scrub at app boot (SDR-4437 CRITICAL-3 follow-up)

> Supersedes the handoff `docs/superpowers/specs/2026-07-17-fernet-key-migration-handoff.md`.
> Fixes the silent data-loss bug where any upgrade NOT run through `deploy_local
> update` boots the new keyless code, finds `encryption_keys` empty, ignores the
> env-var key still in app.yaml, and generates a fresh key — orphaning every
> existing encrypted Google credential/token.

## Problem

SDR-4437 CRITICAL-3 moved the Google-OAuth Fernet master key out of `app.yaml`
(`GOOGLE_OAUTH_ENCRYPTION_KEY` env var) into the `encryption_keys` Lakebase
table. The relocation was implemented **only in the deploy tool**
(`_migrate_encryption_key_to_lakebase`), and the boot-time key resolver
(`src/core/encryption.py`) was given **deliberately no env-var fallback**.

Consequence: any upgrade that does not go through the deploy tool's relocation —
most importantly the **Databricks Apps UI "Deploy" button**, which reuses the
existing (still-key-bearing) app.yaml — boots the new code against an empty
`encryption_keys` table, ignores the env-var key, and generates a fresh key.
All existing ciphertext becomes undecryptable, and the app self-deletes the
"stale" rows on read. Silent, permanent data loss.

The root cause is that the migration lived in the deploy tool instead of being
self-contained in the artifact. The three real upgrade paths diverge in whether
the env var is present at first boot:

| Path | app.yaml at first boot | Env var present? |
|------|------------------------|------------------|
| UI "Deploy" button | old app.yaml reused | **yes** |
| `tellr.update()` (`_update_databricks`) | regenerated from keyless template | no (unless carried forward) |
| `deploy_local update` (`update_local`) | regenerated from keyless template | no (unless carried forward) |

## Goal

One migration mechanism, self-contained in the artifact, behaving **identically
in dev and prod**. Correctness (no data loss) must never depend on which tool
performed the upgrade. The plaintext key must be removed from app.yaml at rest
(SDR hard requirement), but that removal must never be able to cause data loss.

**Requirement framing (an honest tension to name up front):** the two goals above
can conflict. The scrub (Unit 2) is best-effort and never blocks boot, so if the
app SP lacks write ACL on its own source folder, boot-scrub cannot land. In that
case the hard requirement is met only by a **tool-driven deploy** (`tellr.update`
/ `deploy_local`) writing the keyless template — which becomes the *guaranteed*
mechanism, not merely a backstop. Concretely: an install upgraded **only** via
the UI Deploy button whose SP lacks source-folder write ACL will retain the
plaintext key in app.yaml indefinitely (surfaced only by a boot log line) until a
tool-driven deploy runs. The write-ACL probe (Unit 2) determines which regime we
are in; the plan must decide whether a tool-driven deploy is therefore mandatory
for SDR sign-off, or whether best-effort boot-scrub is accepted with the log as
the escape hatch. We do NOT block boot to force the requirement — data
availability outranks at-rest hygiene at boot time.

## Design decisions (settled with the user)

1. **The key MUST be scrubbed from app.yaml at rest** (SDR hard requirement),
   with a safeguard: never scrub before the table is confirmed to hold the
   matching, valid key.
2. **Scrub happens at boot (self-scrub)**, decoupled from correctness — it is
   strictly best-effort and never blocks boot or gates the data-loss fix.
3. **No ciphertext-aware empty-table guard.** The legacy-install state
   (ciphertext under the env key + an empty `encryption_keys` table) *is* a
   real ciphertext-with-empty-table state — but it is fully **handled** by
   env-var seeding (Unit 1), not something we need a guard for. Beyond that
   migration, ciphertext is only ever written by `encrypt_data()`, which calls
   `get_encryption_key()`, which seeds the table first — so a *new* orphaning
   ciphertext-with-empty-table state cannot arise through normal operation. Given
   both the legacy case (handled) and the steady state (can't occur), a runtime
   guard is YAGNI. Boot-seed is the simple SELECT-first → env → key-file → fresh
   ladder.
4. **The deploy tools carry the existing key forward** into the regenerated
   app.yaml (instead of doing a deploy-time DDL relocation). Boot then seeds the
   table and scrubs. This makes boot the single migrator on every path.

## Architecture

Three units, one responsibility each:

### Unit 1 — Boot-time seed (the correctness fix)

`src/core/encryption.py`. `get_encryption_key()` already does **SELECT-first,
then seed-if-absent**. The only change is what `_seed_value()` reads. Re-add the
env-var read as the *migration* source, ahead of the existing key-file/fresh
ladder:

```
_seed_value():   # only reached on an empty table (SELECT-first miss)
  1. GOOGLE_OAUTH_ENCRYPTION_KEY env var, if set   ← NEW (legacy → table migration)
  2. legacy .encryption_key file (local dev)        ← unchanged
  3. Fernet.generate_key() (fresh install)          ← unchanged
```

Because the resolver is SELECT-first, this is a **one-time cutover**: the first
boot of the migrated code seeds the table from whatever env var is present;
every boot thereafter reads the row and never consults the env var again. This
reverses PR-3's documented "no env-var fallback" decision — an intentional
reversal; the module docstring (encryption.py:20-23) is rewritten to describe
the migration + scrub semantics.

**Item 2 ("create the table if absent") is already handled** and needs no new
migration entry. Boot order today is:

```
run.py::init_database()
  └─ src/core/database.py::init_db()
       ├─ Base.metadata.create_all()   # creates encryption_keys (registered model)
       └─ _run_migrations()            # ALTERs existing tables only
  └─ (default content seeding)
  └─ src/core/encryption.py::ensure_encryption_key()   # SELECT-first → _seed_value()
```

`_run_migrations()` only alters existing tables, so table *creation* is covered
by `create_all()`. The "run migrations" hook the handoff refers to is this
existing `ensure_encryption_key()` step — enhanced, not newly added.

This single change fixes the data-loss bug on all three upgrade paths (given
Unit 3 supplies the env var on the tool paths).

### Unit 2 — Boot-time self-scrub (the SDR hygiene guarantee)

`src/core/encryption.py::_scrub_app_yaml_key()` (new). **Best-effort; never
raises; never blocks boot.**

**Call site (load-bearing):** invoke it as its **own** step in
`run.py::init_database()`, immediately after the existing `ensure_encryption_key()`
block — NOT folded inside `ensure_encryption_key()`. That existing block is
wrapped in a `try/except` that does `raise SystemExit(1)` (run.py:68-75); if the
scrub lived inside it, a scrub bug that leaked an exception would abort boot,
directly violating "never blocks boot." Give the scrub its own call wrapped in
its own broad `try/except` that only logs — so a scrub failure can never reach
the SystemExit path and can never gate the data-loss fix.

```
_scrub_app_yaml_key():
  0. Guard: return unless DATABRICKS_APP_NAME is set (no-op on local/SQLite/tests).
  1. SELECT the key from the table and validate it as a real Fernet key.
     Missing/invalid → DO NOT scrub, log error, return.
     (Never remove the last copy unless the table copy is proven good.)
  2. ws = get_system_client(); path = ws.apps.get(DATABRICKS_APP_NAME).default_source_code_path
  3. download {path}/app.yaml → parse. No GOOGLE_OAUTH_ENCRYPTION_KEY entry → return (idempotent).
  4. entry value == validated table key → drop the entry, re-serialise, upload (overwrite), log "scrubbed".
     entry value != table key → DO NOT scrub, log loud warning (divergent key — human must inspect).
  5. try/except around the whole body: any failure (no write ACL, download/parse/upload error)
     → log clearly, return. Boot continues.
```

Two safety properties:

- **Ordering prevents data loss.** Step 1 validates the table key before
  app.yaml is touched; step 4 removes the env entry only when it *matches* that
  validated key. The scrub can therefore only ever remove a redundant copy. On
  any anomaly the plaintext key stays as a SELECT-first-ignored backup.
- **No live-process impact.** The rewritten app.yaml takes effect only on the
  next deploy; the table is already the runtime source of truth. The scrub only
  changes what is at rest in the workspace file.

**Empirical unknown (probe during implementation):** whether the app SP holds
write ACL on its own `default_source_code_path` (often owned by the deploying
human). If not, step 4's upload fails → caught → logged → boot proceeds, and the
plaintext key persists until a tool-driven deploy overwrites it with the keyless
template (Unit 3 is the backstop). Correctness holds either way.

### Unit 3 — Deploy-tool carry-forward (item 1)

`packages/databricks-tellr/databricks_tellr/deploy.py::_update_databricks` and
`scripts/deploy_local.py::update_local`. Replace the deploy-time DDL relocation
with **carry-forward** so boot is the single migrator.

```
OLD (remove): read legacy key → open Lakebase conn → _migrate_encryption_key_to_lakebase(DDL+GRANT+INSERT)
NEW (keep):   read legacy key → pass it into _write_app_yaml so the regenerated
              app.yaml re-includes GOOGLE_OAUTH_ENCRYPTION_KEY iff a legacy key
              was present. Boot seeds the table from it, then scrubs on first boot.
```

- `_write_app_yaml` gains an optional `encryption_key` param. When set, it emits
  the `GOOGLE_OAUTH_ENCRYPTION_KEY` env entry; when `None` (already-migrated and
  fresh installs), app.yaml stays keyless exactly as today. **Templating note:**
  `_write_app_yaml` renders via `string.Template(...).substitute(...)`
  (`deploy.py:1401`) and `app.yaml.template` currently has *no* key placeholder
  at all. `string.Template` supports no conditionals and raises `KeyError` on any
  unmatched `$` placeholder, so "emit the entry only when a key is present" needs
  a concrete mechanism — e.g. a full-block placeholder (`$ENCRYPTION_KEY_BLOCK`)
  substituted with either the complete `- name:/value:` entry or the empty string
  (taking care not to emit malformed YAML) — not a placeholder that is merely
  "absent when no key."
- **`update_local` branching-path guard:** `legacy_key` is assigned only inside
  the non-branching `else:` block (`deploy_local.py:700`), but the shared
  `_write_app_yaml` call (`deploy_local.py:768`) runs on both the branching and
  non-branching paths. Initialise the carry-forward value to `None` before the
  branching `if/else` (the fork path never reads a source key), or the branching
  path will `NameError` when the key is wired into that shared call.
- **Delete** `_migrate_encryption_key_to_lakebase` and its deploy-time Lakebase
  connection for key purposes. This also removes the ownership-gated DDL/GRANT
  against Lakebase that was itself a source of fork-permission pain. **Also
  remove its top-level import at `scripts/deploy_local.py:40`** (inside the
  `from databricks_tellr.deploy import (...)` block) — otherwise every
  `deploy_local` invocation (create / update / delete) fails at import with
  `ImportError`, not just the update path. The `_get_lakebase_connection` import
  (`deploy_local.py:37`) also becomes dead once the update-path relocation block
  is removed (its only remaining use is the migration at line 706); drop it too
  for cleanliness.
- **Keep** `_read_existing_encryption_key` (strict reader — still needed to
  detect and carry the legacy key; raising on an unreadable app.yaml stays, so a
  transient read failure can't silently skip the migration).
- **Everything else in the deploy tools stays** (handoff correction): Lakebase
  branching, schema setup, SP role grants, breaking-migration checks. Only the
  key mechanism moves to boot.
- **`create` / `_create_databricks` needs no change** — already writes keyless
  and boots to generate a fresh key for a genuinely new install.
- **KEEP the legacy-key fork precondition** in
  `deploy_local.py::_check_branching_preconditions` (the `if legacy_key:`
  rejection at lines 289-297). This is a correction to an earlier draft that
  proposed deleting it: carry-forward does **not** run on the branching/fork
  path. Tracing `update_local`, the key logic lives only in the non-branching
  `else:` block (deploy_local.py:694-716); the branching path (631-693) never
  reads or carries a key — the fork inherits the key via copy-on-write of the
  `encryption_keys` table and its app.yaml is generated keyless. So if a fork is
  created while its source env is still **unmigrated** (env key in app.yaml,
  empty table), the fork's COW table is empty AND its app.yaml carries no env var
  → boot's `_seed_value()` finds nothing → `Fernet.generate_key()` → the
  COW-inherited ciphertext is orphaned and self-deleted. That is the exact
  CRITICAL-3 bug on the exact path the handoff documented as broken. The
  precondition is the only guard against forking an unmigrated source, and boot
  does **not** replace it on this path. Operational consequence (acceptable): a
  source env must be migrated once (via UI button / `tellr.update` /
  `deploy_local` carry-forward, all of which run boot-seed) before it can be
  forked — after which forks inherit the key by COW and boot is SELECT-first.
  Do NOT resurrect the reverted "downgrade preflight to warn" hack.
- **`_read_existing_encryption_key` stays load-bearing in the preflight for a
  second reason:** lines 281-287 wrap it in a `try/except` that doubles as the
  "source env not deployed / unreachable" probe (re-raised as "not deployed"),
  which `test_deploy_local_preflight.py::test_preflight_fails_when_source_not_deployed`
  depends on. Both the read and the `if legacy_key:` rejection stay.

## Data flow (all paths converge on boot)

```
Legacy install (env key in app.yaml, encrypted rows under that key)
        │
        ├─ UI "Deploy" button ─────────► old app.yaml reused (env var present) ─┐
        ├─ tellr.update() ─────────────► carry-forward writes env var into new app.yaml ─┤
        └─ deploy_local update ────────► carry-forward writes env var into new app.yaml ─┤
                                                                                          ▼
                                          Boot: init_db (create_all + migrations)
                                                ensure_encryption_key():
                                                  SELECT id=1 → empty
                                                  _seed_value() → env var → INSERT
                                                  (old ciphertext now decryptable) ✓
                                                _scrub_app_yaml_key():
                                                  validate table key → matches env → scrub app.yaml
                                                  (or log + keep if SP lacks write ACL)
                                                                                          ▼
                                          Every later boot / redeploy on ANY path:
                                                SELECT id=1 → row present → use it (env ignored)
                                                scrub → no entry → no-op (idempotent) ✓
```

Once an install has migrated once (table holds the key), all three paths are
already safe by SELECT-first; the env var matters only for the single legacy
cutover boot.

**The devloop/branching fork path is deliberately absent from the diagram above**
because it does NOT carry the key forward. A fork inherits the key by
copy-on-write of the `encryption_keys` table, which is only populated once the
source env has itself been migrated. The `_check_branching_preconditions`
legacy-key check (retained — see Unit 3) enforces that ordering: it refuses to
fork a source whose app.yaml still carries an unmigrated key. So the fork path is
safe not because carry-forward reaches it, but because it can only run against an
already-migrated source whose table row the fork inherits.

## Testing

**Unit** (extend existing files):

- `test_encryption.py` — seed order: (a) env present → table seeded from env;
  (b) no env, key file present → from file; (c) neither → fresh generated;
  (d) SELECT-first: existing row wins, env var ignored even when set (one-time
  cutover + idempotency).
- `test_encryption.py` — `_scrub_app_yaml_key` (mock `WorkspaceClient`): no-op
  when `DATABRICKS_APP_NAME` unset; no-op when table key invalid/missing (safety
  gate); removes entry only on value-match; **leaves entry on mismatch**;
  swallows download/upload failure and returns without raising (boot continues).
- `test_deploy_encryption_key_migration.py` — repurpose from "DDL relocation" to
  "carry-forward": `_write_app_yaml(encryption_key=...)` emits the env entry;
  `encryption_key=None` stays keyless; `_update_databricks`/`update_local` pass
  the read legacy key through to `_write_app_yaml` and **no longer** open a
  Lakebase connection for key migration.
- `test_deploy_local_preflight.py` — the legacy-key fork precondition is **kept**
  (see Unit 3), so its assertions stay. Keep
  `test_preflight_fails_when_source_not_deployed` (relies on the retained
  `_read_existing_encryption_key` deployment probe) and the "source still carries
  a legacy key → reject the fork" assertion.

**Live verification** (hard-won lesson: CLI ≠ deployed OBO/SP behavior — only a
deployed app proves runtime paths). On disposable devloop instance(s) carrying
**real legacy ciphertext**:

1. Stand up a legacy-style install (env key in app.yaml + a real encrypted
   Google token row).
2. **UI-button upgrade** to the new build → assert: table seeded from env, old
   token still decrypts, app.yaml scrubbed (or a loud log if the SP lacks write
   ACL — **this is the write-ACL probe**).
3. **`tellr.update()` / `deploy_local` upgrade** on a second instance → same
   assertions (proves carry-forward).
4. Idempotency: second boot/redeploy is a no-op (SELECT-first; nothing to scrub).

## Docs

- Rewrite `encryption.py` module docstring (lines 20-23): the "deliberately NO
  env-var fallback" paragraph becomes the migration + scrub semantics.
- Update `.claude/skills/deploy-tellr-dev/` and `docs/technical/dev-deploy.md`
  (handoff item 3): the key lives in the table, boot migrates + scrubs, and dev
  tools carry the key forward exactly like prod — so the dev/prod divergence
  that let CRITICAL-3 pass in dev but lose data in prod cannot recur.
- This spec supersedes the handoff doc.

## Rollout / PR scoping

New work, separate from the review-clean, already-pushed PR-4
(`security/sdr4437-pr4-oauth-errors`). Recommend its **own branch/PR off `main`**
so it does not destabilise merge-ready PR-4. Confirm branch state at plan time
(the tree may have moved).

## Out of scope / explicitly rejected

- Ciphertext-aware empty-table hard-fail (YAGNI — see decision 3).
- Keeping the env var permanently as a backup (violates the SDR hard
  requirement — decision 1).
- Keeping deploy-time relocation as belt-and-suspenders (keeps the
  not-self-contained problem and two divergent mechanisms — decision 4).
- Weakening `_check_branching_preconditions` to a warning (the reverted hack).
  Note: the legacy-key fork precondition itself is **kept**, not deleted — see
  Unit 3. Boot carry-forward does not run on the fork path, so that precondition
  remains the only guard against forking an unmigrated source.
- Adding source-key carry-forward into the branching/fork path (the fork inherits
  the key by copy-on-write of the `encryption_keys` table; requiring the source
  to be migrated-once before it can be forked is the accepted operational
  constraint instead).
