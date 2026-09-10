# Handoff: Fernet encryption-key migration is broken (SDR-4437 CRITICAL-3)

> Purpose: seed a FRESH brainstorming/design session. The root cause is settled;
> this doc is the starting point so the new agent skips the discovery detours.

## The root problem (settled)

CRITICAL-3 moved the Google-OAuth Fernet master key **out of `app.yaml`
(`GOOGLE_OAUTH_ENCRYPTION_KEY` env var) and into the `encryption_keys` table**.
The relocation runs **only in the deploy tool** (`scripts/deploy_local.py` →
`update_local` non-branching path → `_migrate_encryption_key_to_lakebase`,
around line 700-716). The app's boot-time key resolver
(`src/core/encryption.py::get_encryption_key` / `_seed_value`) has
**deliberately NO env-var fallback** (see the module docstring, lines 20-23).

**Consequence (the bug):** any upgrade that is NOT run through
`deploy_local update` — e.g. bumping the version pin in the Databricks Apps UI,
or any other redeploy — boots the new code, finds `encryption_keys` empty,
ignores the env-var key still sitting in app.yaml, and **generates a fresh
key**. Every existing encrypted credential/token (Google) becomes
undecryptable, and the app self-deletes the "stale" rows on read
(`admin.py::get_google_credentials_status` ~line 147;
`google_slides_auth.py` ~line 138). Silent data loss.

The migration being coupled to the deploy tool means the upgrade is not
self-contained in the artifact. It should be.

## Evidence (proven this session)

- Manually upgraded live app `db-tellr-170726` from `0.3.12` → `0.3.13.dev16`
  via the UI (app.yaml still had `GOOGLE_OAUTH_ENCRYPTION_KEY`). Boot log showed
  "Ensuring encryption key... Encryption key ready" — but the table had no
  relocated row, so the new code did not use the app.yaml key. Uploaded
  credential did not survive.
- `deploy_local` devloop (fork) path can't test upgrades at all: it re-forks
  prod every deploy and (post-CRITICAL-3) boots keyless → fresh key → purges
  inherited ciphertext. Confirmed via a fork deploy earlier.
- v0.3.12 template HAD the key in app.yaml (2 refs); current template is keyless
  (0 refs) — confirms the env→table move.

## What the user wants (three work items)

1. **Strip `deploy_local` of the key migration only.** IMPORTANT correction
   from the user: deploy_local SHOULD keep doing Lakebase branching, schema
   setup, and SP role grants — those are infra provisioning the app SP can't do.
   ONLY the encryption-key migration (`_migrate_encryption_key_to_lakebase`
   call in `update_local`, ~line 700-716) moves out.
2. **Introduce a boot-time migration path.** The app already runs
   `init_database()` at boot (`packages/databricks-tellr-app/databricks_tellr_app/run.py`),
   which already calls `ensure_encryption_key()`. There is an existing
   migrations mechanism — user said "we already have a run migrations command
   somewhere" (look at `src/core/database.py` `_run_migrations` / `init_db`, and
   the app.yaml `command:` block that calls
   `databricks_tellr_app.run.init_database`). The key-relocation belongs here.
3. **Update the deploy skill** so this can't recur:
   `.claude/skills/deploy-tellr-dev/` (and `docs/technical/dev-deploy.md`).

## The open design question (unanswered — decide in the new session)

How should boot seed `encryption_keys` when the table is empty? Options
discussed (this REVERSES PR-3's "no env-var fallback / YAGNI" decision, so it's
a real design call, ideally with the original CRITICAL-3 rationale in view):

- **A. env-var → table, SELECT-first:** row exists → use it; empty + env set →
  seed from env (the migration); empty + no env → generate fresh (new install).
- **B. same, but hard-fail in production** when table empty AND no env var
  (don't silently fresh-generate and orphan prod ciphertext; fresh-generate only
  in dev/test).
- **C. keep the env var permanently** (don't use a table) — undoes CRITICAL-3's
  design; probably not what's wanted, listed for completeness.

Leaning B for prod-safety, but confirm against the CRITICAL-3 rationale
(pip-distributed, no secret scope, zero operator setup — see
`memory/sdr_4437_remediation.md`).

## Key files

- `src/core/encryption.py` — boot key resolver (`get_encryption_key`,
  `_seed_value`, `ensure_encryption_key`); the "no env fallback" docstring.
- `packages/databricks-tellr-app/databricks_tellr_app/run.py` —
  `init_database()` boot hook (already calls `ensure_encryption_key`).
- `scripts/deploy_local.py` — `update_local` (~700), `create_local`,
  `_check_branching_preconditions` (~260, the over-broad fork preflight),
  `_migrate_encryption_key_to_lakebase` import.
- `packages/databricks-tellr/databricks_tellr/deploy.py` —
  `_migrate_encryption_key_to_lakebase` (the relocate-not-rotate logic to move),
  `_read_existing_encryption_key`, `app.yaml.template` (now keyless).
- `src/core/database.py` — `init_db` / `_run_migrations` (existing migration
  mechanism to fold the key-migration into).
- Tests: `tests/unit/test_deploy_encryption_key_migration.py`,
  `test_deploy_local_preflight.py`, `test_encryption.py`.

## State of the tree RIGHT NOW (important)

- Branch `security/sdr4437-pr4-oauth-errors` @ `21b67b9` (PR-4, pushed, review-
  clean). A workaround commit that downgraded the fork preflight to warn was
  made then **reverted** — do NOT resurrect it; the real fix is boot-time
  migration, not weakening the preflight.
- Live test app `db-tellr-170726` is on `0.3.13.dev16` with an orphaned
  credential (fresh key). Disposable.
- The 5 SDR-4437 PRs (#223/224/226/227/228) are already MERGED to main. PR-4
  (#4, HIGH-7/MEDIUM-2/MEDIUM-3) is the open branch; this key-migration fix is a
  NEW, SEPARATE piece of work — decide whether it rides on PR-4 or its own PR.
- `0.3.13.dev16` published to real PyPI (built from `21b67b9`).

## Suggested first move for the new session

Run `superpowers:brainstorming` fresh with THIS doc as the only context. Decide
the open question (A/B/C), confirm scope (item 1 = key-migration only), then
design boot-time migration + deploy_local strip + skill update, and hand to
`superpowers:writing-plans`.
