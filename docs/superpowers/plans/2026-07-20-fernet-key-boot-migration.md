# Fernet Key Boot Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Fernet master-key migration self-contained in the app artifact so every upgrade path (UI Deploy button, `tellr.update()`, `deploy_local`) migrates the legacy `GOOGLE_OAUTH_ENCRYPTION_KEY` into the `encryption_keys` table at boot instead of only in the deploy tool — eliminating the silent data-loss bug where a non-deploy-tool upgrade generates a fresh key and orphans existing ciphertext.

**Architecture:** Three units. (1) Boot-time seed: `_seed_value()` reads the env var first, so the SELECT-first resolver seeds the table from it on the one-time cutover boot. (2) Boot-time self-scrub: a new best-effort `_scrub_app_yaml_key()` removes the plaintext key from the workspace app.yaml after confirming the table holds the matching valid key, never blocking boot. (3) Deploy-tool carry-forward: `tellr.update()` and `deploy_local update` stop doing deploy-time DDL relocation and instead re-emit the existing key into the regenerated app.yaml so boot can migrate it; the fork/branching precondition that guards against forking an unmigrated source is KEPT.

**Tech Stack:** Python 3.11 (Databricks Apps runtime), SQLAlchemy (SQLite in tests, Lakebase Postgres in prod), `cryptography.fernet`, `databricks-sdk` (`WorkspaceClient`), `string.Template` for app.yaml generation, PyYAML, pytest.

## Global Constraints

- **Target runtime is Python 3.11** — no `os.unshare`, no 3.12-only APIs; `datetime.utcnow` is avoided (the model supplies `CURRENT_TIMESTAMP` in SQL).
- **`encryption.py` SQL statements stay schema-UNQUALIFIED** — the module runs against SQLite (tests) and Lakebase (where `search_path` resolves the bare name). Do NOT add schema qualification to statements in `src/core/encryption.py`.
- **The scrub must NEVER raise out of the boot hook** — it is best-effort; a scrub failure can never abort boot or gate the data-loss fix. It lives in its own `try/except` call site in `run.py`, outside the `ensure_encryption_key()` block that does `raise SystemExit(1)`.
- **The scrub must NEVER remove the last copy of the key** — it re-reads and validates the table key, and only removes the app.yaml entry when it exactly matches that validated key.
- **`_read_existing_encryption_key` stays strict** — it raises `DeploymentError` on an unreadable app.yaml (never returns None on error), because a silent skip would orphan ciphertext.
- **The legacy-key fork precondition in `_check_branching_preconditions` is KEPT** — carry-forward does not run on the branching/fork path; the precondition is the only guard against forking an unmigrated source.
- **Model contract for `encryption_keys`:** columns are exactly `{id: INTEGER PK non-autoincrement, key_value: TEXT NOT NULL, created_at: TIMESTAMP NOT NULL}`. Every insert path supplies `CURRENT_TIMESTAMP` explicitly.
- **Commit after every task.** Branch off `main` (see Task 0). Do NOT push.
- Env var name is exactly `GOOGLE_OAUTH_ENCRYPTION_KEY`. Runtime app-name env var is exactly `DATABRICKS_APP_NAME`.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/core/encryption.py` | Boot key resolver + new self-scrub | Modify `_seed_value()`; add `_scrub_app_yaml_key()`; rewrite module docstring |
| `packages/databricks-tellr-app/databricks_tellr_app/run.py` | Boot hook | Add a separate scrub call after the `ensure_encryption_key()` block |
| `packages/databricks-tellr/databricks_tellr/deploy.py` | Deploy tool | Add `encryption_key` param to `_write_app_yaml`; convert `_update_databricks` to carry-forward; delete `_migrate_encryption_key_to_lakebase` |
| `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template` | Generated app.yaml | Add `$ENCRYPTION_KEY_BLOCK` placeholder |
| `scripts/deploy_local.py` | Local deploy tool | Convert `update_local` to carry-forward; remove dead imports; KEEP fork precondition |
| `tests/unit/test_encryption.py` | Unit tests | Add env-seed + scrub tests |
| `tests/unit/test_deploy_encryption_key_migration.py` | Unit tests | Repurpose from DDL-relocation to carry-forward |
| `tests/unit/test_deploy_local_preflight.py` | Unit tests | Unchanged assertions (precondition kept) — verify still green |
| `.claude/skills/deploy-tellr-dev/`, `docs/technical/dev-deploy.md` | Docs | Document boot-migration + carry-forward |

---

## Task 0: Branch setup

**Files:** none (git only)

- [ ] **Step 1: Create the working branch off main**

The spec scopes this as new work separate from the review-clean PR-4 branch. Verify the current branch, then branch off `main`.

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git status --short && git branch --show-current
```
Expected: shows the current branch (likely `security/sdr4437-pr4-oauth-errors`). The plan/spec docs under `docs/superpowers/` are untracked or committed there.

- [ ] **Step 2: Branch off main**

Run:
```bash
git fetch origin
git checkout -b security/fernet-key-boot-migration origin/main
```
Expected: new branch created from `origin/main`.

- [ ] **Step 3: Bring the spec + plan onto the branch**

The spec (`docs/superpowers/specs/2026-07-20-fernet-key-boot-migration-design.md`) and this plan were committed on the previous branch. Cherry-pick or copy them so they travel with the work:
```bash
git checkout security/sdr4437-pr4-oauth-errors -- docs/superpowers/specs/2026-07-20-fernet-key-boot-migration-design.md docs/superpowers/plans/2026-07-20-fernet-key-boot-migration.md
git add docs/superpowers/specs/2026-07-20-fernet-key-boot-migration-design.md docs/superpowers/plans/2026-07-20-fernet-key-boot-migration.md
git commit -m "docs: carry fernet-key-boot-migration spec + plan onto feature branch"
```
Expected: both docs present on `security/fernet-key-boot-migration`.

> Note: if `main` already contains these docs (merged), skip Step 3.

---

## Task 1: Boot-time env-var seed (the correctness fix)

**Files:**
- Modify: `src/core/encryption.py` (`_seed_value`, lines 66-74; module docstring, lines 1-24)
- Test: `tests/unit/test_encryption.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_seed_value()` now returns the `GOOGLE_OAUTH_ENCRYPTION_KEY` env value (as `bytes`) when set and the table is empty; unchanged return type (`bytes`). `get_encryption_key()` behaviour is unchanged except for this new highest-priority seed source.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_encryption.py` (the `db` fixture already patches the session factory and `_KEY_FILE`; env is controlled via `monkeypatch`):

```python
def test_env_var_seeds_empty_table(db, monkeypatch):
    """SDR-4437: the one-time legacy→table migration. An empty table plus a
    GOOGLE_OAUTH_ENCRYPTION_KEY env var seeds the table from that env value."""
    engine, _ = db
    legacy = Fernet.generate_key().decode()
    monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", legacy)
    assert get_encryption_key() == legacy.encode()
    assert _stored_key(engine) == legacy


def test_env_var_takes_priority_over_key_file(db, tmp_path, monkeypatch):
    """When both are present on an empty table, the env var (migration source)
    wins over the legacy key file."""
    engine, _ = db
    env_key = Fernet.generate_key().decode()
    file_key = Fernet.generate_key().decode()
    (tmp_path / ".encryption_key").write_text(file_key)
    monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", env_key)
    assert get_encryption_key() == env_key.encode()
    assert _stored_key(engine) == env_key


def test_existing_row_ignores_env_var(db, monkeypatch):
    """One-time cutover: once the row exists, the env var is never consulted."""
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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_encryption.py::test_env_var_seeds_empty_table tests/unit/test_encryption.py::test_env_var_takes_priority_over_key_file -v`
Expected: FAIL — `test_env_var_seeds_empty_table` and `_takes_priority` fail because `_seed_value()` currently ignores the env var (it generates a fresh key or reads the file). (`test_existing_row_ignores_env_var` will already PASS because SELECT-first never calls `_seed_value` — that's fine; it locks in the invariant.)

- [ ] **Step 3: Modify `_seed_value()` to read the env var first**

In `src/core/encryption.py`, replace the current `_seed_value` (lines 66-74):

```python
def _seed_value() -> bytes:
    """Pick the value to seed an empty encryption_keys table with."""
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        if key:
            logger.info("Seeding encryption_keys from legacy key file %s", _KEY_FILE)
            return key.encode()
    logger.info("Generating new Fernet master key (fresh install)")
    return Fernet.generate_key()
```

with:

```python
def _seed_value() -> bytes:
    """Pick the value to seed an empty encryption_keys table with.

    Priority (SELECT-first in get_encryption_key means this runs only when the
    table is empty):
    1. GOOGLE_OAUTH_ENCRYPTION_KEY env var — the one-time legacy→table
       migration (SDR-4437 CRITICAL-3 follow-up). Present on the cutover boot
       via the reused app.yaml (UI Deploy) or carry-forward (deploy tools).
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

Add `import os` to the imports at the top of the file if not already present (currently the file imports `logging`, `functools.lru_cache`, `pathlib.Path` — `os` is NOT yet imported, so add it).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_encryption.py -v`
Expected: PASS — all new tests plus the existing suite (fresh-install, existing-row-wins, key-file-seed, concurrent-seed, roundtrip, corrupt-key) stay green.

- [ ] **Step 5: Rewrite the module docstring**

In `src/core/encryption.py`, replace the "There is deliberately NO env-var fallback…" paragraph (lines 20-23) with:

```
The seed order on an empty table is env var → legacy key file → fresh generate
(see ``_seed_value``). The ``GOOGLE_OAUTH_ENCRYPTION_KEY`` env-var read is the
one-time legacy→table migration (SDR-4437 CRITICAL-3 follow-up): it reverses
PR-3's original "no env-var fallback" decision, which caused silent data loss on
any upgrade that did not go through the deploy tool. Because resolution is
SELECT-first, the env var is consulted only on the cutover boot; every later
boot reads the row. ``_scrub_app_yaml_key`` then removes the now-redundant
plaintext key from the workspace app.yaml (best-effort).
```

- [ ] **Step 6: Commit**

```bash
git add src/core/encryption.py tests/unit/test_encryption.py
git commit -m "fix(encryption): seed encryption_keys from env var (boot-time key migration)

Re-adds the GOOGLE_OAUTH_ENCRYPTION_KEY read to _seed_value as the highest-
priority seed source. Because get_encryption_key is SELECT-first, this is a
one-time cutover that fixes the CRITICAL-3 data-loss bug on every upgrade path.

Co-authored-by: Isaac"
```

---

## Task 2: Boot-time self-scrub function

**Files:**
- Modify: `src/core/encryption.py` (add `_scrub_app_yaml_key()`)
- Test: `tests/unit/test_encryption.py`

**Interfaces:**
- Consumes: `get_encryption_key()` (to obtain/validate the table key), `os.getenv("DATABRICKS_APP_NAME")`, `src.core.databricks_client.get_system_client()` → `WorkspaceClient`.
- Produces: `_scrub_app_yaml_key() -> None`. Best-effort; never raises. Removes the `GOOGLE_OAUTH_ENCRYPTION_KEY` env entry from `{default_source_code_path}/app.yaml` only when its value equals the validated table key.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_encryption.py`:

```python
import yaml
from unittest.mock import MagicMock


def _app_yaml_bytes(with_key: str | None) -> bytes:
    env = [{"name": "ENVIRONMENT", "value": "production"}]
    if with_key is not None:
        env.append({"name": "GOOGLE_OAUTH_ENCRYPTION_KEY", "value": with_key})
    return yaml.safe_dump({"name": "tellr", "env": env}).encode()


def _mock_ws_with_app_yaml(content_bytes: bytes, source_path="/Workspace/x"):
    ws = MagicMock()
    ws.apps.get.return_value = MagicMock(default_source_code_path=source_path)
    resp = MagicMock()
    resp.read.return_value = content_bytes
    ws.workspace.download.return_value = resp
    return ws


def test_scrub_noop_when_app_name_unset(db, monkeypatch):
    """Local/SQLite/tests have no DATABRICKS_APP_NAME → scrub is a no-op."""
    from src.core.encryption import _scrub_app_yaml_key
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    called = []
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client",
        lambda *a, **k: called.append(1),
    )
    _scrub_app_yaml_key()
    assert called == []  # never even built a client


def test_scrub_removes_entry_on_value_match(db, monkeypatch):
    from src.core.encryption import _scrub_app_yaml_key
    # Seed the table so get_encryption_key returns a known key.
    key = get_encryption_key().decode()
    monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")
    ws = _mock_ws_with_app_yaml(_app_yaml_bytes(with_key=key))
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client", lambda *a, **k: ws
    )
    _scrub_app_yaml_key()
    # uploaded content must no longer contain the key entry
    uploaded = ws.workspace.upload.call_args
    assert uploaded is not None
    body = uploaded.args[1] if len(uploaded.args) > 1 else uploaded.kwargs["content"]
    text_body = body.decode() if isinstance(body, bytes) else (
        body.read().decode() if hasattr(body, "read") else str(body)
    )
    assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in text_body


def test_scrub_leaves_entry_on_value_mismatch(db, monkeypatch):
    """A divergent key must NOT be removed — it might be the only copy of a
    different key. Log and leave it."""
    from src.core.encryption import _scrub_app_yaml_key
    get_encryption_key()  # seed table
    monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")
    ws = _mock_ws_with_app_yaml(_app_yaml_bytes(with_key="a-different-key"))
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client", lambda *a, **k: ws
    )
    _scrub_app_yaml_key()
    ws.workspace.upload.assert_not_called()


def test_scrub_noop_when_no_key_entry(db, monkeypatch):
    """Already-scrubbed app.yaml → nothing to do, no upload (idempotent)."""
    from src.core.encryption import _scrub_app_yaml_key
    get_encryption_key()
    monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")
    ws = _mock_ws_with_app_yaml(_app_yaml_bytes(with_key=None))
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client", lambda *a, **k: ws
    )
    _scrub_app_yaml_key()
    ws.workspace.upload.assert_not_called()


def test_scrub_swallows_download_failure(db, monkeypatch):
    """Any failure (no ACL, download error) is caught — scrub never raises."""
    from src.core.encryption import _scrub_app_yaml_key
    get_encryption_key()
    monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")
    ws = MagicMock()
    ws.apps.get.return_value = MagicMock(default_source_code_path="/Workspace/x")
    ws.workspace.download.side_effect = OSError("no read ACL")
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client", lambda *a, **k: ws
    )
    _scrub_app_yaml_key()  # must NOT raise
    ws.workspace.upload.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_encryption.py -k scrub -v`
Expected: FAIL — `ImportError: cannot import name '_scrub_app_yaml_key'`.

- [ ] **Step 3: Implement `_scrub_app_yaml_key()`**

Add to `src/core/encryption.py` (after `ensure_encryption_key`). Note `import os` and `import yaml` at the top (add `import yaml` — the module does not import it yet):

```python
def _scrub_app_yaml_key() -> None:
    """Best-effort: remove the now-redundant plaintext GOOGLE_OAUTH_ENCRYPTION_KEY
    from the deployed workspace app.yaml (SDR-4437 CRITICAL-3 hygiene).

    NEVER raises and NEVER blocks boot. Only removes the entry when its value
    matches the validated table key, so it can only ever delete a redundant
    copy. No-op outside a Databricks Apps runtime. The rewritten app.yaml takes
    effect on the NEXT deploy; the table is already the runtime source of truth.
    """
    app_name = os.getenv("DATABRICKS_APP_NAME")
    if not app_name:
        return  # local/SQLite/tests — nothing to scrub

    try:
        # 1. Re-read + validate the table key (never remove the last valid copy).
        table_key = get_encryption_key()  # bytes; raises if corrupt
        Fernet(table_key)  # explicit validation guard
        table_key_str = table_key.decode()

        # 2. Locate our own source folder.
        from src.core.databricks_client import get_system_client

        ws = get_system_client()
        source_path = ws.apps.get(name=app_name).default_source_code_path
        if not source_path:
            logger.warning("Scrub: app has no default_source_code_path; skipping")
            return

        # 3. Download + parse the deployed app.yaml.
        resp = ws.workspace.download(f"{source_path}/app.yaml")
        raw = resp.read() if hasattr(resp, "read") else resp
        content = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        parsed = yaml.safe_load(content) or {}
        env_list = parsed.get("env", [])

        entry = next(
            (e for e in env_list if e.get("name") == "GOOGLE_OAUTH_ENCRYPTION_KEY"),
            None,
        )
        if entry is None:
            return  # already scrubbed / never had it — idempotent

        # 4. Only remove on exact value match with the validated table key.
        if entry.get("value") != table_key_str:
            logger.warning(
                "Scrub: app.yaml GOOGLE_OAUTH_ENCRYPTION_KEY differs from the "
                "table key — leaving it in place for manual inspection."
            )
            return

        parsed["env"] = [
            e for e in env_list if e.get("name") != "GOOGLE_OAUTH_ENCRYPTION_KEY"
        ]
        new_content = yaml.safe_dump(parsed, sort_keys=False)
        from databricks.sdk.service.workspace import ImportFormat

        ws.workspace.upload(
            f"{source_path}/app.yaml",
            new_content.encode("utf-8"),
            format=ImportFormat.AUTO,
            overwrite=True,
        )
        logger.info("Scrub: removed plaintext encryption key from deployed app.yaml")
    except Exception as exc:  # never propagate — best-effort by contract
        logger.warning("Scrub: could not remove key from app.yaml (%s)", exc)
```

> NOTE on the test's upload-body assertion: the implementation passes the content as a positional `bytes` arg. The test reads `uploaded.args[1]`. Keep them consistent — content is arg index 1 (path is arg 0).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_encryption.py -k scrub -v`
Expected: PASS — all five scrub tests green.

- [ ] **Step 5: Run the full encryption suite**

Run: `pytest tests/unit/test_encryption.py -v`
Expected: PASS — Task 1 + Task 2 tests + pre-existing tests all green.

- [ ] **Step 6: Commit**

```bash
git add src/core/encryption.py tests/unit/test_encryption.py
git commit -m "feat(encryption): best-effort boot-time app.yaml key scrub

Adds _scrub_app_yaml_key: removes the redundant plaintext key from the deployed
app.yaml only after validating the table holds the matching key. Never raises,
never blocks boot, no-op outside a Databricks Apps runtime.

Co-authored-by: Isaac"
```

---

## Task 3: Wire the scrub into the boot hook

**Files:**
- Modify: `packages/databricks-tellr-app/databricks_tellr_app/run.py` (`init_database`, after lines 65-75)
- Test: `tests/unit/test_encryption.py`

**Interfaces:**
- Consumes: `src.core.encryption._scrub_app_yaml_key` (from Task 2).
- Produces: `init_database()` calls the scrub in its own `try/except` after the `ensure_encryption_key()` block; a scrub exception is logged and swallowed (does NOT `SystemExit`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_encryption.py` (reuses the `_load_run_module` helper already in that file):

```python
def test_init_database_invokes_scrub_after_key_hook(monkeypatch):
    """run.py::init_database calls _scrub_app_yaml_key after ensure_encryption_key."""
    run = _load_run_module()
    order = []
    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: None,
    )
    monkeypatch.setattr(
        "src.core.encryption.ensure_encryption_key", lambda: order.append("ensure")
    )
    monkeypatch.setattr(
        "src.core.encryption._scrub_app_yaml_key", lambda: order.append("scrub")
    )
    run.init_database()
    assert order == ["ensure", "scrub"]


def test_init_database_survives_scrub_failure(monkeypatch):
    """A scrub failure must NOT abort boot (it is best-effort)."""
    run = _load_run_module()
    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: None,
    )
    monkeypatch.setattr("src.core.encryption.ensure_encryption_key", lambda: None)

    def _boom():
        raise RuntimeError("scrub blew up")

    monkeypatch.setattr("src.core.encryption._scrub_app_yaml_key", _boom)
    # Must return normally — NO SystemExit.
    run.init_database()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_encryption.py -k "scrub_after or survives_scrub" -v`
Expected: FAIL — `init_database` does not call `_scrub_app_yaml_key` yet.

- [ ] **Step 3: Add the scrub call site in `run.py`**

In `packages/databricks-tellr-app/databricks_tellr_app/run.py`, after the existing encryption-key block (the `try/except` ending at line 75 that logs "Encryption key ready"), add a SEPARATE block:

```python
    # Best-effort: remove the now-redundant plaintext key from the deployed
    # app.yaml (SDR-4437 CRITICAL-3 hygiene). Deliberately a SEPARATE block with
    # its own swallow-all except — a scrub failure must never abort boot, so it
    # must not share the ensure_encryption_key block above (which SystemExits).
    logger.info("Scrubbing legacy key from app.yaml (best-effort)...")
    try:
        from src.core.encryption import _scrub_app_yaml_key
        _scrub_app_yaml_key()
    except Exception as e:  # noqa: BLE001 — best-effort, never blocks boot
        logger.warning(f"app.yaml key scrub skipped: {e}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_encryption.py -k "scrub_after or survives_scrub" -v`
Expected: PASS — ordering test and survive-failure test both green.

- [ ] **Step 5: Run the run.py-related suite**

Run: `pytest tests/unit/test_encryption.py -k "init_database" -v`
Expected: PASS — the two pre-existing `init_database` tests plus the two new ones.

- [ ] **Step 6: Commit**

```bash
git add packages/databricks-tellr-app/databricks_tellr_app/run.py tests/unit/test_encryption.py
git commit -m "feat(run): call best-effort app.yaml key scrub at boot

Separate try/except after ensure_encryption_key so a scrub failure logs and is
swallowed rather than reaching the SystemExit(1) path.

Co-authored-by: Isaac"
```

---

## Task 4: Add `$ENCRYPTION_KEY_BLOCK` to the app.yaml template + `_write_app_yaml`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` (`_write_app_yaml`, lines 1363-1418)
- Test: `tests/unit/test_deploy_encryption_key_migration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_write_app_yaml(..., encryption_key: str | None = None)`. When `encryption_key` is a non-empty string, the generated app.yaml contains a `GOOGLE_OAUTH_ENCRYPTION_KEY` env entry with that value; when `None`/empty, the app.yaml is keyless (exactly as today).

- [ ] **Step 1: Write the failing test**

Add a new test class to `tests/unit/test_deploy_encryption_key_migration.py`:

```python
class TestWriteAppYamlKeyBlock:
    def _read_yaml(self, staging):
        import yaml
        return yaml.safe_load((staging / "app.yaml").read_text())

    def test_keyless_when_no_key(self, tmp_path):
        from databricks_tellr.deploy import _write_app_yaml
        _write_app_yaml(
            tmp_path, "lb", SCHEMA,
            lakebase_result={"type": "provisioned"},
        )
        parsed = self._read_yaml(tmp_path)
        names = [e["name"] for e in parsed["env"]]
        assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in names

    def test_emits_entry_when_key_present(self, tmp_path):
        from databricks_tellr.deploy import _write_app_yaml
        _write_app_yaml(
            tmp_path, "lb", SCHEMA,
            lakebase_result={"type": "provisioned"},
            encryption_key=KEY,
        )
        parsed = self._read_yaml(tmp_path)
        entry = next(
            e for e in parsed["env"] if e["name"] == "GOOGLE_OAUTH_ENCRYPTION_KEY"
        )
        assert entry["value"] == KEY
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_deploy_encryption_key_migration.py::TestWriteAppYamlKeyBlock -v`
Expected: FAIL — `_write_app_yaml` has no `encryption_key` param (`TypeError: unexpected keyword argument`), and the template has no key block.

- [ ] **Step 3: Add the placeholder to the template**

In `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`, add `$ENCRYPTION_KEY_BLOCK` as the LAST line of the `env:` section (after the `HUASHU_PIPELINE_ENABLED` block, lines 68-69). Place it at column 0 so the substituted block controls its own indentation:

```yaml
  - name: HUASHU_PIPELINE_ENABLED
    value: "1"
$ENCRYPTION_KEY_BLOCK
```

> `string.Template` requires EVERY `$name` to be supplied to `.substitute()` or it raises `KeyError`. Task adds the key to the substitute call in Step 4, so the template stays renderable.

- [ ] **Step 4: Add the `encryption_key` param and block rendering to `_write_app_yaml`**

In `packages/databricks-tellr/databricks_tellr/deploy.py`, change the signature (line 1363-1370) to add the param:

```python
def _write_app_yaml(
    staging_dir: Path,
    lakebase_name: str,
    schema_name: str,
    seed_databricks_defaults: bool = False,
    lakebase_result: dict[str, Any] | None = None,
    mlflow_tracing: dict[str, str] | None = None,
    encryption_key: str | None = None,
) -> None:
```

Update the docstring's first paragraph (lines 1373-1374) to:

```
    The Fernet encryption key is written ONLY when ``encryption_key`` is
    provided (the one-time legacy→table carry-forward). Boot seeds the
    encryption_keys table from it and then scrubs it from app.yaml. When
    ``encryption_key`` is None the app.yaml is keyless (steady state).
```

Immediately before the `content = Template(...).substitute(...)` call (line 1401), build the block:

```python
    if encryption_key:
        key_block = (
            "  - name: GOOGLE_OAUTH_ENCRYPTION_KEY\n"
            f'    value: "{encryption_key}"'
        )
    else:
        key_block = ""
```

Add `ENCRYPTION_KEY_BLOCK=key_block,` to the `.substitute(...)` keyword arguments (alongside the existing `LAKEBASE_INSTANCE=...` etc.).

> The block uses two-space indentation to match the other `- name:` entries under `env:`. When empty, the `$ENCRYPTION_KEY_BLOCK` line becomes a blank line, which is valid YAML.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_deploy_encryption_key_migration.py::TestWriteAppYamlKeyBlock -v`
Expected: PASS — keyless and key-present cases both correct.

- [ ] **Step 6: Verify the existing keyless-template test still passes**

There is an existing test asserting the template/app.yaml is keyless (from PR-3, e.g. `test_write_app_yaml_is_keyless`). Run the full deploy test module:

Run: `pytest tests/unit/test_deploy_encryption_key_migration.py -v`
Expected: the `TestWriteAppYamlKeyBlock` tests PASS; note any failures in the `TestUpdateDatabricksWiring` / `TestMigrateEncryptionKey` classes — those are rewritten in Task 5, so failures there are expected and handled next.

- [ ] **Step 7: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_encryption_key_migration.py
git commit -m "feat(deploy): _write_app_yaml can carry the encryption key forward

Adds a \$ENCRYPTION_KEY_BLOCK placeholder + optional encryption_key param so the
regenerated app.yaml re-emits GOOGLE_OAUTH_ENCRYPTION_KEY when a legacy key is
carried forward; keyless otherwise.

Co-authored-by: Isaac"
```

---

## Task 5: Convert `_update_databricks` to carry-forward + delete the DDL relocation

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` (`_update_databricks` key block lines 548-568; delete `_migrate_encryption_key_to_lakebase` lines 791-847)
- Test: `tests/unit/test_deploy_encryption_key_migration.py`

**Interfaces:**
- Consumes: `_write_app_yaml(..., encryption_key=...)` (Task 4), `_read_existing_encryption_key` (kept).
- Produces: `_update_databricks` reads any legacy key and passes it to `_write_app_yaml`; it no longer opens a Lakebase connection for key migration and no longer calls `_migrate_encryption_key_to_lakebase` (which is deleted).

- [ ] **Step 1: Rewrite the wiring tests**

Replace the `TestMigrateEncryptionKey` class AND the `TestUpdateDatabricksWiring` class in `tests/unit/test_deploy_encryption_key_migration.py` with carry-forward tests. Keep the `TestReadExistingEncryptionKeyStrict` class unchanged (the strict reader stays). Keep the top-of-file constants (`KEY`, `OTHER_KEY`, `CLIENT_ID`, `SCHEMA`). Update the import block (lines 9-13) to drop the deleted symbol:

```python
from databricks_tellr.deploy import (
    DeploymentError,
    _read_existing_encryption_key,
)
```

Replace both classes with:

```python
class TestUpdateDatabricksCarryForward:
    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=KEY)
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_legacy_key_is_carried_into_app_yaml(
        self, mock_upload, mock_yaml, mock_reqs, mock_read,
        mock_check, mock_lakebase, mock_ws_factory,
    ):
        from databricks_tellr.deploy import _update_databricks

        ws = MagicMock()
        mock_ws_factory.return_value = ws
        mock_lakebase.return_value = {"type": "provisioned", "name": "lb"}
        ws.apps.get.return_value = MagicMock(url="https://app")

        _update_databricks(
            app_name="app", app_file_workspace_path="/Workspace/x",
            lakebase_name="lb", schema_name=SCHEMA,
        )
        # key is carried forward into the regenerated app.yaml
        assert mock_yaml.call_args.kwargs.get("encryption_key") == KEY

    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=None)
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_no_legacy_key_writes_keyless(
        self, mock_upload, mock_yaml, mock_reqs, mock_read,
        mock_check, mock_lakebase, mock_ws_factory,
    ):
        from databricks_tellr.deploy import _update_databricks

        ws = MagicMock()
        mock_ws_factory.return_value = ws
        mock_lakebase.return_value = {"type": "provisioned", "name": "lb"}
        ws.apps.get.return_value = MagicMock(url="https://app")

        _update_databricks(
            app_name="app", app_file_workspace_path="/Workspace/x",
            lakebase_name="lb", schema_name=SCHEMA,
        )
        # keyless: encryption_key is None (or absent)
        assert not mock_yaml.call_args.kwargs.get("encryption_key")

    def test_migrate_function_is_removed(self):
        """The deploy-time DDL relocation is gone; boot owns migration now."""
        import databricks_tellr.deploy as d
        assert not hasattr(d, "_migrate_encryption_key_to_lakebase")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_deploy_encryption_key_migration.py::TestUpdateDatabricksCarryForward -v`
Expected: FAIL — `_update_databricks` still runs DDL relocation and does not pass `encryption_key` to `_write_app_yaml`; `_migrate_encryption_key_to_lakebase` still exists.

- [ ] **Step 3: Rewrite the `_update_databricks` key block**

In `packages/databricks-tellr/databricks_tellr/deploy.py`, the current block (lines 527-529 read the key; lines 548-568 relocate it via DDL). Replace the DDL-relocation block (the whole `if encryption_key:` block at lines 552-568, starting `if encryption_key:` and ending at `print("   Key relocated ...`)` with NOTHING — remove it — and change the `_write_app_yaml` call (lines 573-580) to pass the key:

The read at lines 527-529 stays:
```python
    # Preserve the existing key so boot can migrate it (carry-forward).
    if not encryption_key:
        encryption_key = _read_existing_encryption_key(ws, app_file_workspace_path)
```

Delete lines 548-568 (the `# CRITICAL-3 migration:` comment through `print("   Key relocated ...")`).

Change the `_write_app_yaml` call to add `encryption_key=encryption_key`:
```python
            _write_app_yaml(
                staging,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                lakebase_result=lakebase_result,
                mlflow_tracing=mlflow_subs,
                encryption_key=encryption_key,
            )
```

- [ ] **Step 4: Delete `_migrate_encryption_key_to_lakebase`**

Delete the entire function `_migrate_encryption_key_to_lakebase` (lines 791-847, from `def _migrate_encryption_key_to_lakebase(` through the closing `)` of the GRANT block). Leave `_read_existing_encryption_key` (lines 757-788) in place.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_deploy_encryption_key_migration.py -v`
Expected: PASS — `TestUpdateDatabricksCarryForward` (3 tests), `TestReadExistingEncryptionKeyStrict` (3 tests), `TestWriteAppYamlKeyBlock` (2 tests) all green.

- [ ] **Step 6: Update the DDL-validation test docstring**

`tests/unit/test_ddl_identifier_validation.py` line 55 (docstring prose only, not an import) lists `_migrate_encryption_key_to_lakebase` as a validated site. Remove it from that docstring list so the doc stays accurate:

Change lines 54-55 from:
```
    Validated sites (all call validate_schema_name before interpolating):
    _migrate_encryption_key_to_lakebase, _setup_database_schema, _reset_schema,
```
to:
```
    Validated sites (all call validate_schema_name before interpolating):
    _setup_database_schema, _reset_schema,
```

Run: `pytest tests/unit/test_ddl_identifier_validation.py -v`
Expected: PASS — unchanged (the function was never imported there).

- [ ] **Step 7: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_encryption_key_migration.py tests/unit/test_ddl_identifier_validation.py
git commit -m "refactor(deploy): carry key forward in _update_databricks, delete DDL relocation

tellr.update() now re-emits the legacy key into the regenerated app.yaml (boot
migrates it) instead of doing a deploy-time DDL relocation into Lakebase.
Deletes _migrate_encryption_key_to_lakebase.

Co-authored-by: Isaac"
```

---

## Task 6: Convert `deploy_local.update_local` to carry-forward + clean imports

**Files:**
- Modify: `scripts/deploy_local.py` (imports lines 33-49; `update_local` non-branching block lines 700-716; `_write_app_yaml` call lines 768-775)
- Test: `tests/unit/test_deploy_local_preflight.py` (verify unchanged assertions still pass)

**Interfaces:**
- Consumes: `_write_app_yaml(..., encryption_key=...)` (Task 4), `_read_existing_encryption_key` (kept).
- Produces: `update_local` carries any legacy key forward into the regenerated app.yaml; no Lakebase connection for key migration; the fork precondition (`_check_branching_preconditions`) is UNCHANGED.

- [ ] **Step 1: Initialise the carry-forward variable before the branching split**

In `scripts/deploy_local.py::update_local`, `legacy_key` is currently assigned only inside the non-branching `else:` (line 700). The shared `_write_app_yaml` call (line 768) runs on BOTH paths, so wire a value that is `None` on the fork path. Immediately before the `if branch_from_env:` split (before line 631), add:

```python
        # Carry-forward of the legacy encryption key into the regenerated
        # app.yaml (boot migrates it). Only the non-branching path reads a
        # source key; the fork path inherits the key via the COW table, so it
        # stays None here.
        carry_forward_key: str | None = None
```

- [ ] **Step 2: Rewrite the non-branching relocation block**

Replace the non-branching `else:` relocation block (lines 700-716, from `legacy_key = _read_existing_encryption_key(ws, workspace_path)` through `print("   Key relocated")`) with:

```python
            legacy_key = _read_existing_encryption_key(ws, workspace_path)
            if legacy_key:
                # CRITICAL-3: carry the key forward into the regenerated
                # app.yaml; boot seeds the table from it and scrubs. No more
                # deploy-time DDL relocation.
                carry_forward_key = legacy_key
                print("   Carrying existing encryption key forward into app.yaml")
```

- [ ] **Step 3: Pass the key into the shared `_write_app_yaml` call**

Change the `_write_app_yaml` call (lines 768-775) to add `encryption_key=carry_forward_key`:

```python
            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                lakebase_result=lakebase_result,
                mlflow_tracing=mlflow_subs,
                encryption_key=carry_forward_key,
            )
```

- [ ] **Step 4: Remove now-dead imports**

In the `from databricks_tellr.deploy import (...)` block (lines 33-49), remove two names that are no longer used:
- `_migrate_encryption_key_to_lakebase` (line 40) — function deleted in Task 5.
- `_get_lakebase_connection` (line 37) — its only use was the deleted relocation block (line 706); lines 548/687 are comments, not calls.

> Keep `_read_existing_encryption_key` (line 44) — used by both the retained fork precondition (line 282) and the carry-forward read (line 700).

Verify no other live use of `_get_lakebase_connection` remains:
```bash
grep -n "_get_lakebase_connection(" scripts/deploy_local.py
```
Expected: NO matches (only the comment mentions at 548/687, which don't have the trailing `(`). If a real call appears, keep the import and note it.

- [ ] **Step 5: Verify the module imports cleanly**

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -c "import sys; sys.path.insert(0, 'packages/databricks-tellr'); import scripts.deploy_local"
```
Expected: no `ImportError`, no `NameError`. (If `scripts` is not a package, run `python scripts/deploy_local.py --help` instead and expect the argparse help, not an import error.)

- [ ] **Step 6: Run the preflight tests (must stay green — precondition kept)**

Run: `pytest tests/unit/test_deploy_local_preflight.py -v`
Expected: PASS — all 8 tests, unchanged. The legacy-key rejection (`test_preflight_fails_when_source_still_has_legacy_key`) and the not-deployed probe (`test_preflight_fails_when_source_not_deployed`) both still pass because `_check_branching_preconditions` is untouched.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_local.py
git commit -m "refactor(deploy_local): carry key forward in update_local, drop dead imports

update_local carries the legacy key into the regenerated app.yaml (boot
migrates) instead of DDL relocation. Removes the _migrate_encryption_key_to_lakebase
and _get_lakebase_connection imports (now unused). Fork precondition kept.

Co-authored-by: Isaac"
```

---

## Task 7: Full unit-suite convergence check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend unit suite**

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
pytest tests/unit -q
```
Expected: PASS except the KNOWN pre-existing baseline failures documented in project memory (cairo/SVG-render, mlflow-tracing, autoscaling-mock). Confirm ZERO net-new failures attributable to this change. If any failure references `encryption`, `_write_app_yaml`, `_migrate_encryption_key_to_lakebase`, `deploy_local`, or `run.py`, fix it before proceeding.

- [ ] **Step 2: Grep for any lingering references to the deleted function**

Run:
```bash
grep -rn "_migrate_encryption_key_to_lakebase" --include="*.py" . | grep -v build/ | grep -v worktrees/
```
Expected: NO matches outside comments/docstrings. If a live import/call remains, remove it.

- [ ] **Step 3: Commit any convergence fixes**

```bash
git add -A
git commit -m "test: converge unit suite for fernet key boot migration

Co-authored-by: Isaac"
```
(Skip if Step 1 was clean and nothing changed.)

---

## Task 8: Documentation

**Files:**
- Modify: `docs/technical/dev-deploy.md`
- Modify: `.claude/skills/deploy-tellr-dev/SKILL.md` (or the skill's main doc file — check the directory)

**Interfaces:** none.

- [ ] **Step 1: Inspect the deploy-tellr-dev skill file**

Run:
```bash
ls -la .claude/skills/deploy-tellr-dev/
```
Identify the main doc (likely `SKILL.md`).

- [ ] **Step 2: Add a "Fernet key handling" note to `docs/technical/dev-deploy.md`**

Add a section stating:
- The Fernet master key lives in the `encryption_keys` Lakebase table, not app.yaml.
- On upgrade, boot seeds the table from `GOOGLE_OAUTH_ENCRYPTION_KEY` if the table is empty (one-time cutover), then best-effort scrubs the key from app.yaml.
- Deploy tools (`tellr.update`, `deploy_local update`) carry any existing key forward into the regenerated app.yaml so boot can migrate it — they no longer relocate it via DDL.
- The devloop/fork path relies on COW inheritance of the table and requires the source env to be migrated once first (enforced by the fork preflight).
- **Rule reinforced:** because boot owns migration identically on every path, code that works under `deploy_local` also works under a UI-button upgrade — there is no dev/prod divergence in key handling.

- [ ] **Step 3: Update the deploy-tellr-dev skill doc**

Add the same key-handling summary (2-3 sentences) so a future dev-loop deploy does not reintroduce a deploy-only migration.

- [ ] **Step 4: Commit**

```bash
git add docs/technical/dev-deploy.md .claude/skills/deploy-tellr-dev/
git commit -m "docs(deploy): document boot-time key migration + carry-forward

Co-authored-by: Isaac"
```

---

## Task 9: Live verification (deployed instance — run from the MAIN session)

> **Operational, not unit-testable.** Per project memory: CLI/local tests do NOT prove deployed OBO/SP behavior — only a deployed app does. Live deploys run from the MAIN session (coordinator-relayed deploys are classifier-blocked). Requires publishing a dev build (`publish-dev.yml` → `.devN`) and `deploy_local`.

- [ ] **Step 1: Publish a dev build**

Run: `gh workflow run publish-dev.yml` and note the published `.devN` version.

- [ ] **Step 2: Stand up a legacy-style instance**

Deploy a `0.3.12`-era build (env key in app.yaml) on a disposable devloop instance, log in as a real user, connect a Google credential so a real `token_encrypted` row is written under the legacy key.

- [ ] **Step 3: UI-button upgrade → verify**

Upgrade the instance to the new `.devN` via the Databricks Apps UI Deploy button (reuses the old app.yaml). Then verify:
- Boot log shows "Seeding encryption_keys from GOOGLE_OAUTH_ENCRYPTION_KEY (migration)".
- The stored Google token still decrypts (open the app, confirm the credential is present/usable).
- The `encryption_keys` table has the row equal to the legacy key.
- app.yaml is scrubbed (`GOOGLE_OAUTH_ENCRYPTION_KEY` gone) OR a "Scrub: could not remove key" warning is logged — **record which** (this is the write-ACL probe: it tells us whether boot-scrub lands in prod or whether the deploy tool's keyless template is the effective scrubber).

- [ ] **Step 4: Deploy-tool upgrade → verify carry-forward**

On a SECOND legacy-style instance, upgrade via `./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>`. Verify the same three assertions (table seeded, token decrypts, scrub or logged warning) — this proves carry-forward re-emits the key into the regenerated app.yaml.

- [ ] **Step 5: Idempotency**

Redeploy/restart the upgraded instance. Verify boot uses the table row (SELECT-first; no "Seeding … from GOOGLE_OAUTH…" log the second time) and the scrub is a no-op (no key entry to remove).

- [ ] **Step 6: Record the write-ACL outcome in the spec**

Update the spec's Unit 2 "Empirical unknown" and Goal "Requirement framing" with the observed write-ACL result and whether a tool-driven deploy is therefore required for SDR sign-off.

- [ ] **Step 7: Tear down**

```bash
./scripts/deploy_local.sh delete --env devloop --instance <name>
```

---

## Task 10: PR

- [ ] **Step 1: Review the branch diff**

Run: `git log --oneline origin/main..HEAD` and `git diff origin/main --stat`
Expected: the Task 1-8 commits (+ Task 9's spec update).

- [ ] **Step 2: Consider Isaac Review before opening the PR**

Tip: these changes haven't been reviewed with Isaac Review yet — you can run /review (Databricks' recommended code-review pipeline) before or after pushing.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin security/fernet-key-boot-migration
```
Open a PR against `main` describing: the data-loss bug, the three-unit fix, the KEPT fork precondition (and why), and the Task 9 live-verification results (esp. the write-ACL outcome).
