"""Fernet symmetric encryption for sensitive data (OAuth credentials, tokens).

Uses AES-128-CBC with HMAC-SHA256 authentication via the ``cryptography``
library. The master key comes from one of two places, selected at boot:

1. **Secret-backed (opt-in).** When the deploy tool has attached a Databricks
   Apps secret resource, the platform injects ``TELLR_ENCRYPTION_KEY`` into the
   environment and that value is the key. This path never touches the database.
   See docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md.
2. **Lakebase-backed (default, unchanged).** The key lives in the
   ``encryption_keys`` table of the application database (SDR-4437 CRITICAL-3):
   dynamic, persistent across restarts/restores, unique per deployment, zero
   operator setup.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

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

    Priority (SELECT-first in _from_lakebase means this runs only when
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


_SECRET_ENV_VAR = "TELLR_ENCRYPTION_KEY"


def key_source() -> str:
    """Report where the master key comes from, without reading the key itself.

    Consumed by /api/health so the deploy tool can confirm a relocated app is
    actually reading the secret before it deletes the Lakebase row.
    """
    return "secret" if os.getenv(_SECRET_ENV_VAR, "").strip() else "lakebase"


def _from_secret() -> bytes:
    """Return the Fernet key injected by the Apps secret resource.

    Deliberately touches no database: a secret-mode app's encryption_keys table
    is empty by construction, and writing to it would defeat the whole point.
    """
    raw = os.getenv(_SECRET_ENV_VAR, "").strip()
    try:
        Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"{_SECRET_ENV_VAR} is not a valid Fernet key — refusing to start. "
            f"Check the value stored in the secret backing the "
            f"{_SECRET_ENV_VAR} app resource."
        ) from exc
    logger.info("Encryption key loaded from the %s secret resource", _SECRET_ENV_VAR)
    return raw.encode()


def _from_lakebase() -> bytes:
    """Return the Fernet master key from the encryption_keys table (id=1)."""
    from src.core.database import get_db_session

    # 1. Read-first: check for an existing row before seeding so concurrent
    #    workers never mint two different keys (INSERT … ON CONFLICT DO NOTHING
    #    is still safe against the race, but this avoids the seed call entirely).
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


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    """Return the Fernet master key, from the secret resource or Lakebase."""
    if os.getenv(_SECRET_ENV_VAR, "").strip():
        return _from_secret()
    return _from_lakebase()


def ensure_encryption_key() -> None:
    """Pre-fork boot hook: load/seed the key before uvicorn workers fork.

    Called from the deployed app's init_database step so all workers find
    the row already present (the lazy path in get_encryption_key covers
    local dev and replicas regardless).
    """
    get_encryption_key()


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
