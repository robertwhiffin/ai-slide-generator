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
2. If absent, seed from the ``GOOGLE_OAUTH_ENCRYPTION_KEY`` env var (the
   UI-button upgrade net — see below), else a legacy ``.encryption_key`` file
   in the project root (local dev — keeps pre-existing dev ciphertext
   decryptable), else generate a fresh key. See ``_seed_value``.
3. ``INSERT ... ON CONFLICT (id) DO NOTHING`` + read-back, so concurrent
   workers/replicas converge on one key.

The supported upgrade path is ``tellr.update`` / ``deploy_local``, which — run
as the deploying human — reads the legacy ``GOOGLE_OAUTH_ENCRYPTION_KEY`` from
the existing app.yaml, seeds it into this table, and writes a keyless app.yaml
(SDR-4437 remediation, PR-3). As a safety net for a stray Databricks Apps UI
"Deploy" button upgrade — which bypasses the tool and reuses the old,
still-key-bearing app.yaml — ``_seed_value`` reads that same
``GOOGLE_OAUTH_ENCRYPTION_KEY`` env var (Apps injects every app.yaml ``env:``
entry into the process environment) so the booting app re-seeds the table from
the injected key instead of fresh-generating one and orphaning existing
ciphertext. Because resolution is SELECT-first, the env var is consulted only
while the table is empty; after any successful migration the stored row wins.
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
