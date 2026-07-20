"""Fernet symmetric encryption for sensitive data (OAuth credentials, tokens).

Uses AES-128-CBC with HMAC-SHA256 authentication via the ``cryptography``
library. The master key lives in the ``encryption_keys`` table of the
application database (SDR-4437 CRITICAL-3): dynamic, persistent across
restarts/restores, unique per deployment, zero operator setup.

Resolution is SELECT-first, then race-safe INSERT-if-absent:

1. ``SELECT key_value FROM encryption_keys WHERE id = 1`` — read-first is
   load-bearing: on upgraded installs the table is created by the *deployer*
   role and the app SP holds an explicit SELECT, INSERT grant; reading first
   means INSERT privilege is never exercised when the row already exists.
2. If absent, seed from a legacy ``.encryption_key`` file in the project root
   (local dev — keeps pre-existing dev ciphertext decryptable), else generate
   a fresh key.
3. ``INSERT ... ON CONFLICT (id) DO NOTHING`` + read-back, so concurrent
   workers/replicas converge on one key.

The seed order on an empty table is env var → legacy key file → fresh generate
(see ``_seed_value``). The ``GOOGLE_OAUTH_ENCRYPTION_KEY`` env-var read is the
one-time legacy→table migration (SDR-4437 CRITICAL-3 follow-up): it reverses
PR-3's original "no env-var fallback" decision, which caused silent data loss on
any upgrade that did not go through the deploy tool. Because resolution is
SELECT-first, the env var is consulted only on the cutover boot; every later
boot reads the row. ``_scrub_app_yaml_key`` then removes the now-redundant
plaintext key from the workspace app.yaml (best-effort).
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

import yaml
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

logger = logging.getLogger(__name__)

_KEY_FILE = Path(__file__).resolve().parents[2] / ".encryption_key"

# NOTE: these statements are deliberately schema-UNQUALIFIED, unlike the
# _qual()-qualified raw SQL in database.py::_run_migrations. This module must
# also run against SQLite (unit tests — no schemas) and schema-less local
# Postgres. On Lakebase the bare name resolves to
# <LAKEBASE_SCHEMA>.encryption_keys ONLY because _get_database_url appends
# options=-csearch_path%3D<schema> to the URL (database.py:239,259) and the
# do_connect listener injects just the password, preserving those options.
# If that search_path mechanism ever changes, these statements would silently
# target public.encryption_keys — keep this coupling in mind.
_SELECT_KEY = text("SELECT key_value FROM encryption_keys WHERE id = 1")
_INSERT_KEY = text(
    "INSERT INTO encryption_keys (id, key_value, created_at) "
    "VALUES (1, :key_value, CURRENT_TIMESTAMP) "
    "ON CONFLICT (id) DO NOTHING"
)


def _validated(key: bytes) -> bytes:
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "encryption_keys row id=1 is not a valid Fernet key — refusing to "
            "start with a corrupt master key. Restore the correct key value "
            "before restarting."
        ) from exc
    return key


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


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    """Return the Fernet master key from the encryption_keys table (id=1)."""
    from src.core.database import get_db_session

    # 1. Read-first (see module docstring for why this order matters).
    with get_db_session() as session:
        row = session.execute(_SELECT_KEY).first()
    if row and row[0]:
        return _validated(row[0].encode())

    # 2 + 3. Seed if absent — race-safe across workers/replicas.
    seed = _seed_value()
    with get_db_session() as session:
        session.execute(_INSERT_KEY, {"key_value": seed.decode()})
    with get_db_session() as session:
        row = session.execute(_SELECT_KEY).first()
    if not row or not row[0]:
        raise RuntimeError(
            "Failed to seed encryption_keys: no key row after insert. "
            "Check the app's SELECT, INSERT grants on the data schema."
        )
    return _validated(row[0].encode())


def ensure_encryption_key() -> None:
    """Pre-fork boot hook: load/seed the key before uvicorn workers fork.

    Called from the deployed app's init_database step so all workers find
    the row already present (the lazy path in get_encryption_key covers
    local dev and replicas regardless).
    """
    get_encryption_key()


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


def encrypt_data(plaintext: str) -> str:
    """Encrypt *plaintext* and return a base64-encoded ciphertext string."""
    f = Fernet(get_encryption_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_data(ciphertext: str) -> str:
    """Decrypt a base64-encoded *ciphertext* string and return the plaintext.

    Raises:
        cryptography.fernet.InvalidToken: If the key does not match or data is corrupt.
    """
    f = Fernet(get_encryption_key())
    return f.decrypt(ciphertext.encode()).decode()
